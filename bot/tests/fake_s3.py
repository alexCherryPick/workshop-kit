# -*- coding: utf-8 -*-
"""fake_s3 — локальный фейк S3-совместимого хранилища для тестов адаптера вложений (D20 T2).

ОРАКУЛ ОТДЕЛЬНО ОТ ПИСАТЕЛЯ: ни одного импорта из пакета attach (core / s3 / pointer / norm). Подпись SigV4
проверяется СВОЕЙ реализацией (verify_sigv4) — из СЫРОГО пути запроса и полученных заголовков; сама
проверка сверена с известным ответом из документации AWS (test_attach.FakeOracleKAT). Тело PUT
хешируется здесь и сравнивается с x-amz-content-sha256 (подписанный payload); UNSIGNED-PAYLOAD —
отказ.

Поведение провайдера (state.provider) — на отсутствующий объект при HEAD/GET:
    aws-no-list   — 403 AccessDenied (у ключа нет s3:ListBucket; документировано AWS HeadObject);
    aws-list      — 404 для валидного ключа, 403 для невалидного;
    yandex        — 404 NoSuchKey при ЛЮБОМ ключе, даже невалидном; существующий объект с невалидным ключом — 403
                    (замер ops-padelapp 2026-10-09, IAM-токены).
Режимы (state.mode — множество флагов; state.delay_s — задержка ответа):
    deny          — любой запрос: 403 AccessDenied (ключ отвергнут)
    err5xx        — 503 SlowDown
    delay         — ответ после time.sleep(delay_s) (таймаут или медленный ответ — по соотношению с клиентом)
    put_abort     — PUT: прочитать половину тела и оборвать соединение без ответа
    put_truncate  — PUT: ответить 200, но сохранить обрезанное тело (порча хранилища)
    get_corrupt   — GET: отдать иные байты той же длины
    get_short     — GET: объявить Content-Length объекта, отдать половину и закрыть
    deny_delete   — DELETE: 403
Неверная подпись или неизвестный ключ — 403 SignatureDoesNotMatch / InvalidAccessKeyId.
"""
import hashlib
import hmac
import http.server
import socket
import threading
import time
import urllib.parse


def _h(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def verify_sigv4(method, raw_path, headers, payload_hash, secrets_by_akid, region_expected=None):
    """Сверка подписи. headers — dict имя(нижний регистр) → значение. Возвращает (ok, akid, причина)."""
    auth = headers.get("authorization", "")
    if not auth.startswith("AWS4-HMAC-SHA256 "):
        return False, None, "no-sigv4"
    parts = {}
    for item in auth[len("AWS4-HMAC-SHA256 "):].split(","):
        k, _, v = item.strip().partition("=")
        parts[k] = v
    try:
        cred, signed, sig = parts["Credential"], parts["SignedHeaders"], parts["Signature"]
    except KeyError:
        return False, None, "auth-form"
    akid, date, region, service, term = cred.split("/")
    if akid not in secrets_by_akid:
        return False, akid, "unknown-akid"
    if service != "s3" or term != "aws4_request":
        return False, akid, "scope"
    if region_expected is not None and region != region_expected:
        return False, akid, "region"
    signed_list = signed.split(";")
    for need in ("host", "x-amz-content-sha256", "x-amz-date"):
        if need not in signed_list:
            return False, akid, "unsigned-" + need
    path, _, query = raw_path.partition("?")
    if query:
        return False, akid, "query-unexpected"
    canon_h = "".join("%s:%s\n" % (n, " ".join(headers.get(n, "").split())) for n in signed_list)
    creq = "%s\n%s\n%s\n%s\n%s\n%s" % (method, path, "", canon_h, signed, payload_hash)
    amz_date = headers.get("x-amz-date", "")
    if not amz_date.startswith(date):
        return False, akid, "date"
    sts = "AWS4-HMAC-SHA256\n%s\n%s/%s/%s/%s\n%s" % (amz_date, date, region, service, term,
                                                     hashlib.sha256(creq.encode("utf-8")).hexdigest())
    k = _h(("AWS4" + secrets_by_akid[akid]).encode("utf-8"), date)
    for piece in (region, service, term):
        k = _h(k, piece)
    want = hmac.new(k, sts.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig), akid, "ok" if hmac.compare_digest(want, sig) else "signature"


PROVIDERS = ("aws-no-list", "aws-list", "yandex")


class State(object):
    def __init__(self, bucket, keys, region="us-east-1", perms=None, provider="yandex"):
        if provider not in PROVIDERS:
            raise ValueError("provider: %s" % "|".join(PROVIDERS))
        self.provider = provider
        self.bucket = bucket
        self.keys = dict(keys)            # akid -> secret
        self.perms = dict(perms or {})    # akid -> множество методов (нет записи — все); как права ключа у провайдера
        self.region = region
        self.objects = {}                 # object key (раскодированный) -> bytes
        self.mode = set()
        self.delay_s = 0.0
        self.log = []                     # dict: method, key, akid, why, claimed, body_sha256, signed
        self.deny_keys = set()            # политика на конкретный ключ: 403 AccessDenied (объект может существовать)
        self.hold_next = None             # (entered, release): следующий запрос ждёт release (события, не задержки)
        self.echo = None                  # (code, message): ответ-ошибка 403/503 с этими строками в XML (отражение)
        self.echo_status = 503
        self.lock = threading.Lock()


def _make_handler(state):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _key(self):
            path = self.path.partition("?")[0]
            host = self.headers.get("Host", "")
            hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host
            if hostname.startswith(state.bucket + "."):
                return urllib.parse.unquote(path[1:]), "virtual"
            pre = "/" + state.bucket + "/"
            if path.startswith(pre):
                return urllib.parse.unquote(path[len(pre):]), "path"
            return None, None

        def _send(self, status, body=b"", length=None, extra=None):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body) if length is None else length))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)

        def _err(self, status, code, message=None):
            body = "<Error><Code>%s</Code>%s</Error>" % (code, "" if message is None else "<Message>%s</Message>" % message)
            self._send(status, body.encode("utf-8"))

        def _handle(self):
            with state.lock:
                hold, state.hold_next = state.hold_next, None
            if hold is not None:
                hold[0].set()
                hold[1].wait(60)
            key, _addr = self._key()
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            body = b""
            if self.command == "PUT":
                n = int(self.headers.get("Content-Length", "0"))
                if "put_abort" in state.mode:
                    self.rfile.read(n // 2)
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    with state.lock:
                        state.log.append({"method": self.command, "key": key, "akid": None, "why": "aborted",
                                          "claimed": hdrs.get("x-amz-content-sha256"), "body_sha256": None,
                                          "signed": None})
                    return
                body = self.rfile.read(n)
            if "delay" in state.mode:
                time.sleep(state.delay_s)
            claimed = hdrs.get("x-amz-content-sha256", "")
            ok, akid, why = verify_sigv4(self.command, self.path, hdrs, claimed, state.keys, state.region)
            auth = hdrs.get("authorization", "")
            signed = auth.split("SignedHeaders=")[1].split(",")[0] if "SignedHeaders=" in auth else None
            with state.lock:
                state.log.append({"method": self.command, "key": key, "akid": akid, "why": why, "claimed": claimed,
                                  "body_sha256": hashlib.sha256(body).hexdigest(), "signed": signed})
            # Права ключа: подпись, режим deny (ключ отозван), права метода (у писателя нет LIST/DELETE).
            if not ok:
                deny_code = "InvalidAccessKeyId" if why == "unknown-akid" else "SignatureDoesNotMatch"
            elif "deny" in state.mode or (self.command == "DELETE" and "deny_delete" in state.mode):
                deny_code = "AccessDenied"
            elif akid in state.perms and self.command not in state.perms[akid]:
                deny_code = "AccessDenied"
            else:
                deny_code = None
            with state.lock:
                exists = key is not None and key in state.objects
            missing_read = self.command in ("HEAD", "GET") and key is not None and not exists
            if state.provider == "yandex" and missing_read:
                # замер ops-padelapp 2026-10-09: отсутствующий ключ — 404 NoSuchKey при ЛЮБОМ ключе доступа
                return self._err(404, "NoSuchKey") if self.command == "GET" else self._send(404)
            if state.echo is not None:
                return self._err(state.echo_status, state.echo[0], state.echo[1])
            if deny_code is None and key in state.deny_keys:
                deny_code = "AccessDenied"
            if deny_code is not None:
                return self._err(403, deny_code)
            if state.provider == "aws-no-list" and missing_read:
                # AWS HeadObject/GetObject: без s3:ListBucket отсутствующий объект — 403 AccessDenied
                return self._err(403, "AccessDenied")
            if "err5xx" in state.mode:
                return self._err(503, "SlowDown")
            if key is None:
                return self._err(404, "NoSuchBucket")
            if self.command == "PUT":
                if claimed == "UNSIGNED-PAYLOAD" or claimed != hashlib.sha256(body).hexdigest():
                    return self._err(400, "XAmzContentSHA256Mismatch")
                with state.lock:
                    state.objects[key] = body[: len(body) // 2] if "put_truncate" in state.mode else body
                return self._send(200, extra={"ETag": '"%s"' % hashlib.md5(body).hexdigest()})
            if claimed != hashlib.sha256(b"").hexdigest():
                return self._err(400, "XAmzContentSHA256Mismatch")
            with state.lock:
                obj = state.objects.get(key)
            if self.command == "DELETE":
                with state.lock:
                    state.objects.pop(key, None)
                return self._send(204)
            if obj is None:
                return self._err(404, "NoSuchKey") if self.command == "GET" else self._send(404)
            if self.command == "HEAD":
                return self._send(200, length=len(obj))
            if "get_corrupt" in state.mode:
                obj = bytes(b ^ 0x5A for b in obj)
            if "get_short" in state.mode:
                self.send_response(200)
                self.send_header("Content-Length", str(len(obj)))
                self.end_headers()
                self.wfile.write(obj[: len(obj) // 2])
                self.wfile.flush()
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
            return self._send(200, obj)

        do_GET = do_PUT = do_HEAD = do_DELETE = _handle

    return H


class FakeS3(object):
    def __init__(self, bucket="workshop-test", keys=None, region="us-east-1", perms=None, provider="yandex"):
        self.state = State(bucket, keys or {}, region, perms, provider)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self.state))
        self.server.daemon_threads = True
        self.server.handle_error = lambda request, client_address: None   # обрывы режимов фейка — штатны, без шума
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    @property
    def endpoint(self):
        return "http://127.0.0.1:%d" % self.port

    def methods(self):
        return [e["method"] for e in self.state.log]

    def mutations(self):
        """Изменяющие запросы, дошедшие до хранилища (PUT/DELETE — в т. ч. отвергнутые и оборванные)."""
        return [e for e in self.state.log if e["method"] in ("PUT", "DELETE")]
