# -*- coding: utf-8 -*-
"""attach.s3 — минимальный клиент S3-совместимого хранилища на stdlib: HEAD / GET / PUT / DELETE
с подписью AWS SigV4 и ПОДПИСАННЫМ payload (`x-amz-content-sha256` = sha256 тела).

Владелец — D20 T2. Политики здесь нет: модуль отвечает транспортным классом ответа (Resp.cls), а
перевод в исходы нормы делает attach.core. Классы:
    ok          — 2xx
    not-found   — 404
    denied      — 401/403 и прочие 3xx/4xx, кроме названных ниже (повтор не поможет: ключ, регион, бакет)
    unavailable — 5xx, 408, 429, 400 с кодом XAmzContentSHA256Mismatch / RequestTimeout / IncompleteBody,
                  сеть, TLS, таймаут, обрыв тела, дедлайн (повтор может помочь)
Секреты: значения ключей живут только в объекте Credentials (repr маскирован) и в вычислении подписи;
ни в одно сообщение, исключение или поле Resp они не попадают — Resp.detail проходит через mask().
TLS проверяется всегда (ssl.create_default_context); http:// — только при allow_insecure_http=True и
только на loopback-хост (локальный фейк тестов).
"""
import datetime
import hashlib
import hmac
import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.parse

__all__ = ["Credentials", "Endpoint", "Resp", "S3Client", "EndpointError", "sigv4_headers"]

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
_RETRYABLE_400 = (b"XAmzContentSHA256Mismatch", b"RequestTimeout", b"IncompleteBody")


class EndpointError(ValueError):
    """Эндпоинт или адресация вне контракта (порча конфига)."""


class Credentials(object):
    __slots__ = ("_akid", "_secret")

    def __init__(self, access_key_id, secret_access_key):
        if not access_key_id or not secret_access_key:
            raise ValueError("пустой ключ")
        self._akid = access_key_id
        self._secret = secret_access_key

    def __repr__(self):
        return "Credentials(***)"

    __str__ = __repr__

    def values(self):
        return (self._akid, self._secret)


def mask(text, creds, redact=()):
    """Маскирует значения ключей в произвольной строке (каждый путь ошибки проходит через неё)."""
    if text is None:
        return None
    s = str(text)
    vals = list(creds.values()) if creds is not None else []
    vals += [v for v in redact if v]
    for v in sorted(vals, key=len, reverse=True):   # длинное первым: префикс может содержать короткое значение
        s = s.replace(v, "***")
    return s


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class Endpoint(object):
    """Разобранный эндпоинт + адресация. url — https://<хост>[:<порт>] (без пути, query, учётных данных)."""
    __slots__ = ("scheme", "host", "port", "addressing", "bucket")

    def __init__(self, url, bucket, addressing="path", allow_insecure_http=False):
        if addressing not in ("path", "virtual"):
            raise EndpointError("адресация — path | virtual")
        if not isinstance(url, str) or not isinstance(bucket, str):
            raise EndpointError("эндпоинт и бакет — строки")
        # Любая ошибка разбора (порт, хост, IPv6-скобки) — EndpointError БЕЗ отражения входа: значение
        # эндпоинта может нести что угодно, вплоть до вставленного по ошибке секрета.
        try:
            p = urllib.parse.urlsplit(url)
            host = p.hostname
            port = p.port
            parts = (p.scheme, p.username, p.password, p.query, p.fragment, p.path)
        except Exception:  # noqa: BLE001
            raise EndpointError("эндпоинт не разбирается как URL (схема, хост, порт)") from None
        if any(ord(c) < 0x21 or ord(c) > 0x7E for c in url):
            raise EndpointError("эндпоинт — печатный ASCII без пробелов")
        if p.scheme not in ("https", "http"):
            raise EndpointError("эндпоинт — https-URL")
        if p.scheme == "http" and not allow_insecure_http:
            raise EndpointError("http:// разрешён только явным флагом тестового фейка")
        if p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
            raise EndpointError("эндпоинт без учётных данных, пути, query и фрагмента")
        if not host:
            raise EndpointError("эндпоинт без хоста")
        if p.scheme == "http" and not _is_loopback(host):
            raise EndpointError("http:// — только loopback (локальный фейк)")
        if not bucket or "/" in bucket or any(c.isspace() for c in bucket):
            raise EndpointError("имя бакета вне формы")
        self.scheme = p.scheme
        self.host = host
        self.port = port
        self.addressing = addressing
        self.bucket = bucket

    def host_header(self):
        h = self.host if self.addressing == "path" else self.bucket + "." + self.host
        default = 443 if self.scheme == "https" else 80
        if self.port is not None and self.port != default:
            h = "%s:%d" % (h, self.port)
        return h

    def connect_host(self):
        return self.host if self.addressing == "path" else self.bucket + "." + self.host

    def canonical_uri(self, key):
        enc = "/".join(_uri_encode(seg) for seg in key.split("/"))
        if self.addressing == "path":
            return "/" + _uri_encode(self.bucket) + "/" + enc
        return "/" + enc


def _uri_encode(s):
    out = []
    for b in s.encode("utf-8"):
        out.append(chr(b) if b in _UNRESERVED else "%%%02X" % b)
    return "".join(out)


def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4_headers(method, endpoint, key, payload_sha256, creds, region, now):
    """Заголовки запроса с подписью SigV4 (сервис s3, без query). now — datetime UTC."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    host = endpoint.host_header()
    headers = {"host": host, "x-amz-content-sha256": payload_sha256, "x-amz-date": amz_date}
    signed = ";".join(sorted(headers))
    canon_headers = "".join("%s:%s\n" % (k, headers[k].strip()) for k in sorted(headers))
    canonical = "\n".join([method, endpoint.canonical_uri(key), "", canon_headers, signed, payload_sha256])
    scope = "%s/%s/s3/aws4_request" % (date, region)
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    akid, secret = creds.values()
    k = _hmac(("AWS4" + secret).encode("utf-8"), date)
    k = _hmac(k, region)
    k = _hmac(k, "s3")
    k = _hmac(k, "aws4_request")
    sig = hmac.new(k, sts.encode("utf-8"), hashlib.sha256).hexdigest()
    out = {"Host": host, "x-amz-content-sha256": payload_sha256, "x-amz-date": amz_date,
           "Authorization": "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (akid, scope, signed, sig)}
    return out


class Resp(object):
    """code — код ошибки S3 из тела (<Code>…</Code>) у не-2xx ответов с телом; у HEAD тела нет — None."""
    __slots__ = ("cls", "status", "length", "body", "detail", "code")

    def __init__(self, cls, status=None, length=None, body=None, detail=None, code=None):
        self.cls = cls
        self.status = status
        self.length = length
        self.body = body
        self.detail = detail
        self.code = code

    def __repr__(self):
        return "Resp(cls=%r, status=%r, code=%r, length=%r, detail=%r)" % (
            self.cls, self.status, self.code, self.length, self.detail)


_CODE_RE = re.compile(rb"<Code>([^<]{0,128})</Code>")
# ЗАКРЫТЫЙ перечень кодов ошибок S3, которые адаптер выпускает наружу. Строка сервера (<Code>, <Message>,
# заголовки, тело) недоверенна: она может отражать что угодно, включая ключи и префикс запроса. Наружу — только
# литерал из этого перечня (не строка сервера) либо UNRECOGNIZED.
KNOWN_CODES = frozenset((
    "AccessDenied", "AccountProblem", "AllAccessDisabled", "AuthorizationHeaderMalformed", "BadDigest",
    "EntityTooLarge", "ExpiredToken", "IncompleteBody", "InternalError", "InvalidAccessKeyId", "InvalidArgument",
    "InvalidBucketName", "InvalidObjectState", "InvalidRequest", "InvalidSecurity", "InvalidToken",
    "MethodNotAllowed", "MissingContentLength", "NoSuchBucket", "NoSuchKey", "NotImplemented",
    "PermanentRedirect", "PreconditionFailed", "RequestTimeTooSkewed", "RequestTimeout", "ServiceUnavailable",
    "SignatureDoesNotMatch", "SlowDown", "TemporaryRedirect", "TokenRefreshRequired", "XAmzContentSHA256Mismatch",
))
UNRECOGNIZED = "unrecognized"
_CODE_LITERAL = {c.encode("ascii"): c for c in KNOWN_CODES}


def safe_code(body_head):
    """Код ошибки из тела ответа → литерал закрытого перечня | UNRECOGNIZED | None (кода нет).
    Возвращается НАШ литерал, а не байты сервера: длина и алфавит ограничены построением."""
    m = _CODE_RE.search(body_head or b"")
    if not m:
        return None
    return _CODE_LITERAL.get(m.group(1), UNRECOGNIZED)


NO_SUCH_BUCKET = "no-such-bucket"


def _classify_status(status, body_head):
    if 200 <= status < 300:
        return "ok"
    if status == 404 and safe_code(body_head) == "NoSuchBucket":
        # бакета нет — это не «объекта нет»: класс unavailable для всех методов с телом ответа (GET/PUT/DELETE).
        # HEAD тела не несёт и остаётся неотличим (ограничение записано в журнале T2).
        return "unavailable"
    if status == 404:
        return "not-found"
    if status >= 500 or status in (408, 429):
        return "unavailable"
    if status == 400 and body_head and any(c in body_head for c in _RETRYABLE_400):
        return "unavailable"
    return "denied"


class S3Client(object):
    """Один объект — одна привязка (эндпоинт, бакет, регион, ключи). Ключи объектов — полные
    физические ключи (префикс заказчика уже приклеен вызывающим)."""

    def __init__(self, endpoint, region, creds, timeout_s=30.0, deadline_s=600.0, clock=None, ssl_context=None,
                 redact=()):
        self.redact = tuple(redact)   # key_prefix заказчика — секрет конфига (слово alex 2026-10-09)
        self.endpoint = endpoint
        self.region = region
        self.creds = creds
        self.timeout_s = float(timeout_s)
        self.deadline_s = float(deadline_s)
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self._ctx = ssl_context or ssl.create_default_context()

    def _mask(self, text):
        """Второй рубеж (первый — закрытый перечень кодов): ключи и префикс привязки вырезаются из любой строки,
        уходящей наружу из клиента."""
        return mask(text, self.creds, self.redact)

    def _conn(self):
        ep = self.endpoint
        if ep.scheme == "https":
            return http.client.HTTPSConnection(ep.connect_host(), ep.port, timeout=self.timeout_s, context=self._ctx)
        return http.client.HTTPConnection(ep.connect_host(), ep.port, timeout=self.timeout_s)

    def _request(self, method, key, body=None, read_limit=None, expect_len=None, sink=None):
        """Один запрос. read_limit — сколько байт тела максимум читать в память (None — не читать
        тело, кроме ошибочного); sink(chunk) — потоковая выдача тела 2xx вместо памяти.
        expect_len — если Content-Length 2xx не равен ему, тело не читается (Resp.length сообщает)."""
        payload = hashlib.sha256(body).hexdigest() if body is not None else EMPTY_SHA256
        try:
            hdrs = sigv4_headers(method, self.endpoint, key, payload, self.creds, self.region, self._clock())
        except Exception as e:  # noqa: BLE001 — сбой подписи — порча входа, без значений
            raise EndpointError("подпись не построена: %s" % type(e).__name__) from None
        uri = self.endpoint.canonical_uri(key)
        conn = None
        start = time.monotonic()
        try:
            try:
                conn = self._conn()
                if body is not None:
                    hdrs["Content-Length"] = str(len(body))
                conn.request(method, uri, body=body, headers=hdrs)
                r = conn.getresponse()
            except (socket.timeout, TimeoutError):
                return Resp("unavailable", detail="timeout")
            except ssl.SSLError as e:
                return Resp("unavailable", detail=self._mask("tls: %s" % type(e).__name__))
            except (OSError, http.client.HTTPException) as e:
                return Resp("unavailable", detail=self._mask("network: %s" % type(e).__name__))
            status = r.status
            clen = r.getheader("Content-Length")
            length = int(clen) if clen is not None and clen.isdigit() else None
            if not (200 <= status < 300):
                head = b""
                if method not in ("HEAD",):
                    try:
                        head = r.read(4096)
                    except Exception:  # noqa: BLE001 — тело ошибки вторично
                        head = b""
                cls = _classify_status(status, head)
                code = safe_code(head)
                code = None if code is None else self._mask(code)
                if status == 404 and code == "NoSuchBucket":
                    return Resp(cls, status=status, length=length, code=code, detail=NO_SUCH_BUCKET)
                return Resp(cls, status=status, length=length, code=code,
                            detail=self._mask("http %d%s" % (status, (" " + code) if code else "")))
            if method == "HEAD" or (read_limit is None and sink is None):
                return Resp("ok", status=status, length=length)
            if expect_len is not None and length is not None and length != expect_len:
                return Resp("ok", status=status, length=length, body=None, detail="length-differs")
            buf = [] if sink is None else None
            got = 0
            while True:
                if time.monotonic() - start > self.deadline_s:
                    return Resp("unavailable", status=status, detail="deadline")
                try:
                    chunk = r.read(65536)
                except (socket.timeout, TimeoutError):
                    return Resp("unavailable", status=status, detail="timeout")
                except (OSError, http.client.HTTPException) as e:
                    return Resp("unavailable", status=status, detail=self._mask("body: %s" % type(e).__name__))
                if not chunk:
                    break
                got += len(chunk)
                if read_limit is not None and got > read_limit:
                    return Resp("ok", status=status, length=got, body=None, detail="over-limit")
                if sink is None:
                    buf.append(chunk)
                else:
                    sink(chunk)
            if length is not None and got != length:
                return Resp("unavailable", status=status, detail="body-truncated")
            return Resp("ok", status=status, length=got, body=b"".join(buf) if buf is not None else None)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def head(self, key):
        return self._request("HEAD", key)

    def get(self, key, read_limit, expect_len=None, sink=None):
        return self._request("GET", key, read_limit=read_limit, expect_len=expect_len, sink=sink)

    def put(self, key, body):
        if not isinstance(body, (bytes, bytearray)):
            raise TypeError("тело PUT — байты")
        return self._request("PUT", key, body=bytes(body))

    def delete(self, key):
        return self._request("DELETE", key)
