# -*- coding: utf-8 -*-
"""Оракул адаптера вложений (D20 T2) — функциональная корректность, property-тесты, пре-флайт §2.

Независимость оракула от писателя:
  * ожидаемые исходы примеров нормы (spec/03-spec-type-schemas/examples/attachments/) — таблица ниже,
    выписанная из прозы примеров («E-ATT-PTR-FORM на 0.3.0» → pointer-invalid и т. п.), а не из адаптера;
  * подпись SigV4 проверяет фейк своей реализацией (fake_s3.verify_sigv4), сверенной с известным ответом AWS;
  * хеши, размеры, обязательность полей — hashlib и PyYAML-разбор нормы здесь, не attach.pointer;
  * «побайтово» — сравнение bytes, без strip/splitlines/текстовых режимов.
Покрытие исходов нормы: каждый assert исхода метится (kind, outcome, test id); при ATTACH_COVERAGE_OUT
метки пишутся JSON'ом — таблицу «исход → тесты» печатает bot/tests/attach_coverage.py из attachments.yaml.
"""
import contextlib
import hashlib
import io
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import unittest

import yaml

_TESTS = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.dirname(_TESTS)
_ROOT = os.path.dirname(_BOT)
sys.path.insert(0, _BOT)
sys.path.insert(0, _TESTS)
import attach.core as attach  # noqa: E402
import attach.pointer as P  # noqa: E402
import attach.s3 as attach_s3  # noqa: E402
import fake_s3  # noqa: E402

EX = os.path.join(_ROOT, "spec", "03-spec-type-schemas", "examples", "attachments")
NORM_PATH = os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml")
with open(NORM_PATH, "rb") as _f:
    NORM = yaml.safe_load(_f.read().decode("utf-8"))

# Синтетические ключи — закрытое множество для положительного контракта секретов.
AKID = "AKIDSYNTH0T2Q7W3E9R1"
SECRET = "synthSECRET-t2+Zq8Lm3Np5Rv7Tx9Bc1Df4Gh6Jk/unique"
WAKID = "AKIDWITHDRAW0T2K4L8M"
WSECRET = "synthWITHDRAW-t2+Yp2Wo4Qi6Uy8Tr0Ee5Sa/unique"
PREFIX = "synthPREFIX-3f9a1c7e5b2d4086a1c3e5f7b9d1e3a5/"   # key_prefix — секрет конфига (alex 2026-10-09)
SYNTH = (AKID, SECRET, WAKID, WSECRET, PREFIX)
ENV = {"WORKSHOP_S3_ACCESS_KEY_ID_DEV": AKID, "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV": SECRET,
       "WORKSHOP_S3_WITHDRAW_ACCESS_KEY_ID_DEV": WAKID, "WORKSHOP_S3_WITHDRAW_SECRET_ACCESS_KEY_DEV": WSECRET}
WCREDS = {"access_key_id": "WORKSHOP_S3_WITHDRAW_ACCESS_KEY_ID_DEV",
          "secret_access_key": "WORKSHOP_S3_WITHDRAW_SECRET_ACCESS_KEY_DEV"}
PERMS = {AKID: {"HEAD", "GET", "PUT"}, WAKID: {"DELETE"}}   # права ключа писателя PadelApp: put/get/head
RID = "0199a8c0-1a00-7a00-8a00-000000000900"
SRC = "https://t.me/c/1000000001/900"
THR = 1000

COVER = []


def tearDownModule():
    out = os.environ.get("ATTACH_COVERAGE_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(COVER, f)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def uid(n):
    return "0199a8c0-2b00-7b00-9b00-%012d" % n


CANARY = "workshop/canary"
PROVIDERS = fake_s3.PROVIDERS


def make_fake(provider, canary=True, prefix=""):
    fk = fake_s3.FakeS3(keys={AKID: SECRET, WAKID: WSECRET}, perms=PERMS, provider=provider)
    if canary:
        fk.state.objects[prefix + CANARY] = b"canary"   # объект-канарейка создаёт установщик (T3)
    return fk


def objs(fk):
    """Объекты бакета без канарейки."""
    return {k: v for k, v in fk.state.objects.items() if not k.endswith(CANARY)}


def cfg(fk=None, threshold=THR, **extra):
    m = {"git_threshold_bytes": threshold}
    if fk is not None:
        m["storage"] = {"endpoint": fk.endpoint, "bucket": fk.state.bucket, "region": "us-east-1", "key_prefix": "",
                        "credentials": {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                                        "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"},
                        "allow_insecure_http": True, "timeout_s": 2, "canary_key": CANARY,
                        "list_permission": fk.state.provider == "aws-list"}
        m["storage"].update(extra)
        m["storage"] = {k: v for k, v in m["storage"].items() if v is not None}
    return attach.load_config(m)


def per_provider(cls):
    """Класс тестов с фейком гоняется во ВСЕХ режимах провайдера (aws-no-list, aws-list, yandex):
    создаются подклассы <Имя>_<режим>, исходное имя не регистрируется как набор тестов."""
    for prov in PROVIDERS:
        name = "%s_%s" % (cls.__name__, prov.replace("-", "_"))
        globals()[name] = type(name, (cls,), {"PROVIDER": prov, "__module__": cls.__module__})
    return None


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def pointer_fields(b):
    """НЕЗАВИСИМЫЙ разбор указателя оракулом (не attach.pointer): строки по LF, поле — до первого пробела."""
    assert b.endswith(b"\n")
    lines = b[:-1].split(b"\n")
    out = {"_magic": lines[0].decode("ascii"), "state": lines[1].decode("ascii")[len("state "):]}
    for ln in lines[2:]:
        k, _, v = ln.decode("ascii").partition(" ")
        out[k] = v
    return out


class Base(unittest.TestCase):
    PROVIDER = "yandex"

    def fake(self, canary=True, prefix=""):
        return make_fake(self.PROVIDER, canary=canary, prefix=prefix)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="d20-t2-")
        self.rd = os.path.join(self.tmp, "tickets")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seen(self, kind, got, want):
        self.assertEqual(got, want)
        assert want in (NORM_READ if kind == "read" else NORM_WRITE), (kind, want)
        COVER.append([kind, want, self.id()])

    def write(self, data, c, n=1, **kw):
        kw.setdefault("source", SRC)
        return attach.write_attachment(self.rd, RID, data, ext="mp4", config=c, uuid=uid(n), slug="clip", env=ENV, **kw)


NORM_READ = [o["outcome"] for o in NORM["adapter_outcomes"]["read"]]
NORM_WRITE = [o["outcome"] for o in NORM["adapter_outcomes"]["write"]]

# ---------------------------------------------------------------------------------------------- примеры нормы
# (каталог примера) -> [(суффикс имени файла, вид, состояние, reason)] — по прозе примеров нормы
EXPECT_POS = {
    "01-git-bytes": [("crash-screen.png", "bytes", "git", None)],
    "02-stored": [("screen-recording.mp4", "pointer", "stored", None)],
    "03-pending": [("field-video.mp4", "pointer", "pending", None)],
    "04-unsaved-no-storage": [("match-replay.mp4", "pointer", "unsaved", "no-storage")],
    "05-unsaved-source-refused": [("long-clip.mov", "pointer", "unsaved", "source-refused")],
    "06-withdrawn": [("config-dump.txt", "pointer", "withdrawn", "secret")],
    "07-comment-above-threshold": [("timeout-repro.mp4", "pointer", "stored", None)],
    "08-container": [("call-recording.m4a", "pointer", "stored", None)],
    "09-external": [("requester-screen.png", "bytes", "git", None)],
    "10-same-bytes-two-records": [("710-shared-clip.mp4", "pointer", "stored", None),
                                  ("711-shared-clip.mp4", "pointer", "stored", None)],
    "11-album-same-bytes": [("712-photo.png", "bytes", "git", None), ("713-photo.png", "bytes", "git", None)],
    "12-unsaved-front-receipt": [("site-walkthrough.mp4", "pointer", "unsaved", "no-storage")],
}
EXPECT_NEG = {   # исход чтения адаптера по прозе примера (E-ATT-PTR-FORM → pointer-invalid и т. д.)
    "n1-pointer-key-mismatch": "pointer-invalid",
    "n2-pointer-version-unknown": "pointer-version-unknown",
    "n3-lfs-pointer": "lfs-unsupported",
    "n4-pointer-presence": "pointer-invalid",
    "n5-pointer-bad-size": "pointer-invalid",
    "n6-pointer-bad-media": "pointer-invalid",
    "n7-pointer-extra-field": "pointer-invalid",
    "n8-pointer-bad-source": "pointer-invalid",
    "n9-pointer-truncated": "pointer-invalid",
    "n10-pointer-first-line-trailing-space": "pointer-invalid",      # поправка d20/norm-amend: first_line_pattern
    "n11-pointer-first-line-nondigit-version": "pointer-invalid",
}


def example_files(d):
    out = []
    for root, _dirs, files in os.walk(os.path.join(EX, d)):
        if os.path.basename(os.path.dirname(root)) == "attachments":
            out.extend(os.path.join(root, f) for f in files)
    return sorted(out)


class NormExamples(Base):
    def test_example_set_is_closed(self):
        self.assertEqual(sorted(os.listdir(EX)), sorted(list(EXPECT_POS) + list(EXPECT_NEG)))

    def test_positive_examples_parse_to_their_state(self):
        for d, exp in EXPECT_POS.items():
            files = example_files(d)
            self.assertEqual(len(files), len(exp), d)
            for (suffix, kind, state, reason), f in zip(exp, files):
                self.assertTrue(f.endswith(suffix), (d, f))
                c = P.classify(read_bytes(f))
                self.assertEqual((c.kind, P.state_of(c), c.fields.get("reason")), (kind, state, reason), d)

    def test_positive_pointer_examples_rerender_byte_equal(self):
        """Писатель детерминирован и канонически равен нормативным примерам: render(разбор) == файл."""
        n = 0
        for d in EXPECT_POS:
            for f in example_files(d):
                b = read_bytes(f)
                c = P.classify(b)
                if c.kind == "pointer":
                    self.assertEqual(P.render(c.state, c.fields), b, f)
                    n += 1
        self.assertEqual(n, 10)

    def test_negative_examples_read_outcomes(self):
        for d, want in EXPECT_NEG.items():
            (f,) = example_files(d)
            r = attach.read_attachment(f, attach.load_config({}), env={})
            self.seen("read", r.outcome, want)
            self.assertIsNone(r.data)

    def test_positive_examples_read_without_storage(self):
        c = attach.load_config({})
        for d, exp in EXPECT_POS.items():
            for (suffix, kind, state, reason), f in zip(exp, example_files(d)):
                r = attach.read_attachment(f, c, env={})
                if kind == "bytes":
                    self.seen("read", r.outcome, "in-git")
                    self.assertEqual(r.data, read_bytes(f))
                elif state in ("stored", "pending"):
                    self.seen("read", r.outcome, "storage-not-configured")
                    self.assertIsNone(r.data)
                elif state == "unsaved":
                    self.seen("read", r.outcome, "not-stored")
                    self.assertEqual((r.reason, r.source), (reason, pointer_fields(read_bytes(f))["source"]))
                else:
                    self.seen("read", r.outcome, "withdrawn")
                    self.assertEqual(r.reason, reason)


# ---------------------------------------------------------------------------------------------- грамматика указателя
def _stored_ptr(data=b"x" * 10, source=None):
    s = sha(data)
    b = ("workshop-attachment-pointer 1\nstate stored\nkey sha256/%s\nsha256 %s\nsize %d\nmedia-type video/mp4\n"
         % (s, s, len(data)))
    if source:
        b += "source %s\n" % source
    return b.encode("ascii")


class PointerGrammar(Base):
    """Пакет мутаций байтовых ограничений §9.3 (полную матрицу строит T5)."""

    def test_byte_mutations_batch(self):
        good = _stored_ptr(source=SRC)
        self.assertEqual(P.classify(good).kind, "pointer")
        s = sha(b"x" * 10)
        muts = {
            "cr": good.replace(b"\n", b"\r\n", 1),
            "tab": good.replace(b"size 10", b"size\t10"),
            "empty-line": good.replace(b"\nsize", b"\n\nsize"),
            "trailing-space": good.replace(b"size 10\n", b"size 10 \n"),
            "no-final-lf": good[:-1],
            "two-final-lf": good + b"\n",
            "upper-hex": good.replace(s.encode(), s.upper().encode(), 1),
            "dup-field": good.replace(b"size 10\n", b"size 10\nsize 10\n"),
            "order": good.replace(b"size 10\nmedia-type video/mp4\n", b"media-type video/mp4\nsize 10\n"),
            "unknown-field": good.replace(b"size 10\n", b"size 10\nnote x\n"),
            "state-unknown": good.replace(b"state stored", b"state lost"),
            "double-space": good.replace(b"size 10", b"size  10"),
            "non-ascii": good.replace(b"video/mp4", b"video/m\xd0\xb04"),
            "over-1024": good + b"x" * 1024 + b"\n",
            "magic-line-extra": good.replace(b"pointer 1\n", b"pointer 1 \n", 1),
            "source-port": good.replace(SRC.encode(), b"https://t.me:443/c/1"),
            "source-userinfo": good.replace(SRC.encode(), b"https://u@t.me/c/1"),
            "source-fragment": good.replace(SRC.encode(), SRC.encode() + b"#x"),
            "source-http": good.replace(SRC.encode(), b"http://t.me/c/1"),
            "source-long": good.replace(SRC.encode(), b"https://t.me/" + b"a" * 600),
            "media-upper": good.replace(b"video/mp4", b"Video/mp4"),
            "size-leading-zero": good.replace(b"size 10", b"size 010"),
            "size-17-digits": good.replace(b"size 10", b"size 12345678901234567"),
            "reason-in-stored": good.replace(b"media-type video/mp4\n", b"media-type video/mp4\nreason secret\n"),
        }
        for name, b in muts.items():
            c = P.classify(b)
            self.assertIn(c.kind, ("pointer-invalid",), name)
        # первая строка нечитаема (нет LF в пределах 1025 байт) — pointer-invalid; иная версия — unknown
        self.assertEqual(P.classify(b"workshop-attachment-pointer " + b"1" * 2000).kind, "pointer-invalid")
        self.assertEqual(P.classify(b"workshop-attachment-pointer 2\nanything at all\x00").kind, "pointer-version-unknown")
        self.assertEqual(P.classify(b"workshop-attachment-pointer 1").kind, "pointer-invalid")
        self.assertEqual(P.classify(b"workshop-attachment-pointer\n").kind, "bytes")   # сигнатура — с пробелом
        self.assertEqual(P.classify(b"").kind, "bytes")
        # BOM перед сигнатурой — не указатель (детекция: байты НАЧИНАЮТСЯ сигнатурой) → байты, in-git
        self.assertEqual(P.classify(b"\xef\xbb\xbf" + good).kind, "bytes")

    def test_first_line_form_batch(self):
        """Поправка d20/norm-amend: первая строка не проходит pointer.first_line_pattern → pointer-invalid (в т. ч.
        «v2», «01»); pointer-version-unknown — только при верной форме и версии не из known_versions."""
        pre = b"workshop-attachment-pointer "
        invalid = [b"", b" ", b"1 ", b" 1", b"v2", b"01", b"00", b"0", b"1.0", b"2a", b"\xd9\xa1", b"1\t", b"+1", b"-1"]
        for v in invalid:
            self.assertEqual(P.classify(pre + v + b"\nstate stored\n").kind, "pointer-invalid", v)
        for v in (b"2", b"10", b"999999"):
            c = P.classify(pre + v + b"\nanything\n")
            self.assertEqual((c.kind, c.version), ("pointer-version-unknown", v.decode()), v)
        self.assertEqual(P.classify(_stored_ptr()).kind, "pointer")

    def test_size_bound_1024(self):
        """Наибольший законный указатель (все поля stored на максимуме грамматик) укладывается в 1024 байта;
        файл с сигнатурой длиннее 1024 байт — pointer-invalid."""
        s = "f" * 64
        mt = "a" * 127 + "/" + "b" * 127
        src = "https://t.me/" + "c" * (512 - len("https://t.me/"))
        b = ("workshop-attachment-pointer 1\nstate stored\nkey sha256/%s\nsha256 %s\nsize 9999999999999999\n"
             "media-type %s\nsource %s\n" % (s, s, mt, src)).encode("ascii")
        self.assertLessEqual(len(b), 1024)
        self.assertEqual(P.classify(b).kind, "pointer")
        self.assertEqual(P.classify(b.replace(b"source https", b"source  https")).kind, "pointer-invalid")
        over = b + b"x" * (1025 - len(b))
        self.assertEqual(len(over), 1025)
        self.assertEqual(P.classify(over).kind, "pointer-invalid")

    def test_presence_table_from_norm_batch(self):
        """Обязательность — из PyYAML-разбора нормы: каждое R снятое и каждое X добавленное — invalid."""
        s = sha(b"q")
        full = {"key": "sha256/" + s, "sha256": s, "size": "1", "media-type": "image/png", "source": SRC}
        reasons = {st["state"]: st.get("reasons", []) for st in NORM["states"]["list"]}
        order = NORM["pointer"]["field_order"]
        for state, row in NORM["pointer"]["presence"].items():
            base = {k: v for k, v in full.items() if row[k] in ("R", "O")}
            if row["reason"] == "R":
                base["reason"] = reasons[state][0]
            base = {k: base[k] for k in order if k in base}
            if state == "unsaved":
                base.pop("key", None)

            def enc(fields):
                b = "workshop-attachment-pointer 1\nstate %s\n" % state
                for k in order:
                    if k in fields:
                        b += "%s %s\n" % (k, fields[k])
                return b.encode("ascii")
            self.assertEqual(P.classify(enc(base)).kind, "pointer", state)
            for k in order:
                if row[k] == "R":
                    m = dict(base)
                    m.pop(k)
                    self.assertEqual(P.classify(enc(m)).kind, "pointer-invalid", (state, "drop", k))
                if row[k] == "X":
                    m = dict(base)
                    m[k] = full.get(k, reasons["withdrawn"][0] if k == "reason" else "x")
                    if k == "reason":
                        m[k] = (reasons[state] or ["secret"])[0]
                    self.assertEqual(P.classify(enc(m)).kind, "pointer-invalid", (state, "add", k))
        # presence_extra: unsaved с sha256 без size
        b = ("workshop-attachment-pointer 1\nstate unsaved\nsha256 %s\nreason no-storage\nsource %s\n" % (s, SRC)).encode()
        self.assertEqual(P.classify(b).kind, "pointer-invalid")
        # reason чужого состояния
        b = ("workshop-attachment-pointer 1\nstate unsaved\nreason secret\nsource %s\n" % SRC).encode()
        self.assertEqual(P.classify(b).kind, "pointer-invalid")
        b = b"workshop-attachment-pointer 1\nstate withdrawn\nreason upload-failed\n"
        self.assertEqual(P.classify(b).kind, "pointer-invalid")

    def test_render_rejects_out_of_norm(self):
        with self.assertRaises(ValueError):
            P.render("stored", {"key": "sha256/" + "0" * 64, "sha256": "1" * 64, "size": "1", "media-type": "a/b"})
        with self.assertRaises(ValueError):
            P.render("git", {})
        with self.assertRaises(ValueError):
            P.render("withdrawn", {"reason": "secret", "note": "x"})


# ---------------------------------------------------------------------------------------------- маршрут
@per_provider
class Routing(Base):
    def test_threshold_boundaries_property(self):
        with self.fake() as fk:
            for t in (0, 1, THR, 8000000):
                for c, beyond in ((cfg(None, t), ("unsaved", "no-storage", 4)), (cfg(fk, t), ("storage", None, 4))):
                    for size in (t - 1, t, t + 1):
                        if size < 0:
                            continue
                        r = attach.route(size, c, data_prefix=b"\x00", env=ENV)
                        want = ("git", None, 3) if size <= t else beyond
                        self.assertEqual((r.target, r.reason, r.step), want, (t, size))

    def test_default_threshold_is_norm(self):
        c = attach.load_config({})
        self.assertEqual(c.git_threshold_bytes, NORM["soft_limit"]["bytes"])
        self.assertEqual(attach.route(8000000, c).target, "git")
        self.assertEqual(attach.route(8000001, c).target, "unsaved")

    def test_step1_not_obtained_wins(self):
        with self.fake() as fk:
            for c in (cfg(None), cfg(fk)):
                for size in (None, 0, 5, 10 ** 9):
                    r = attach.route(size, c, obtained=False, env=ENV)
                    self.assertEqual((r.target, r.reason, r.step), ("unsaved", "source-refused", 1))

    def test_step2_pointer_lookalike_bytes_never_git(self):
        data = b"workshop-attachment-pointer 1\nstate stored\n"
        r = attach.route(len(data), cfg(None), data_prefix=data)
        self.assertEqual((r.target, r.reason, r.step), ("unsaved", "no-storage", 2))
        w = self.write(data, cfg(None))
        self.assertEqual(w.state, "unsaved")
        self.assertEqual(pointer_fields(read_bytes(w.staged[0]))["sha256"], sha(data))

    def test_lfs_lookalike_bytes_not_committed_as_bytes(self):
        data = b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n"
        w = self.write(data, cfg(None))
        self.assertEqual((w.state, w.reason, w.route.step), ("unsaved", "no-storage", 2))

    def test_lfs_bytes_below_threshold_routed_by_step2(self):
        """Поправка d20/norm-amend: шаг 2 — magic_prefix ИЛИ lfs.signature_prefix; LFS-байты ниже порога — в
        хранилище (или unsaved no-storage), не в git. Срез префикса — по длиннейшей сигнатуре (42 > 28)."""
        lfs = NORM["lfs"]["signature_prefix"].encode("ascii")
        self.assertGreater(len(lfs), len(NORM["pointer"]["magic_prefix"]))
        for tail in (b"", b"\noid sha256:00\nsize 1\n"):
            data = lfs + tail
            self.assertLess(len(data), THR)
            r = attach.route(len(data), cfg(None), data_prefix=data)
            self.assertEqual((r.target, r.reason, r.step), ("unsaved", "no-storage", 2))
        with self.fake() as fk:
            data = lfs + b"\noid sha256:11\nsize 2\n"
            r = attach.route(len(data), cfg(fk), data_prefix=data, env=ENV)
            self.assertEqual((r.target, r.step), ("storage", 2))
            w = self.write(data, cfg(fk), n=3)
            self.seen("write", w.outcome, "uploaded")
            self.assertEqual(w.state, "stored")
            self.assertEqual(fk.state.objects["sha256/" + sha(data)], data)
            self.seen("read", attach.read_attachment(w.staged[0], cfg(fk), env=ENV).outcome, "ok")
        near = lfs[:-1] + b"2"                                   # не сигнатура — обычный маршрут
        self.assertEqual(attach.route(len(near), cfg(None), data_prefix=near).target, "git")

    def test_credentials_absent_is_not_configured(self):
        with self.fake() as fk:
            r = attach.route(THR + 1, cfg(fk), env={})
            self.assertEqual((r.target, r.reason), ("unsaved", "no-storage"))


# ---------------------------------------------------------------------------------------------- запись
@per_provider
class WriteMatrix(Base):
    def _check_stored(self, w, data, source=SRC):
        b = read_bytes(w.staged[0])
        f = pointer_fields(b)
        self.assertEqual((f["_magic"], f["state"]), ("workshop-attachment-pointer 1", "stored"))
        self.assertEqual((f["key"], f["sha256"], f["size"]), ("sha256/" + sha(data), sha(data), str(len(data))))
        self.assertEqual(f.get("source"), source)
        self.assertEqual(w.path, "attachments/%s/%s-clip.mp4" % (RID, uid(1)))
        self.assertEqual(w.staged, [os.path.join(self.rd, *w.path.split("/"))])

    def test_git_route_writes_exact_bytes(self):
        data = os.urandom(THR)
        w = self.write(data, cfg(None))
        self.assertEqual((w.state, w.outcome), ("git", None))
        self.assertEqual(read_bytes(w.staged[0]), data)

    def test_uploaded(self):
        with self.fake() as fk:
            data = os.urandom(THR + 1)
            w = self.write(data, cfg(fk))
            self.seen("write", w.outcome, "uploaded")
            self._check_stored(w, data)
            self.assertEqual(fk.state.objects["sha256/" + sha(data)], data)
            self.assertEqual(fk.methods(), ["HEAD", "PUT", "GET"])

    def test_already_present(self):
        with self.fake() as fk:
            data = os.urandom(THR + 7)
            fk.state.objects["sha256/" + sha(data)] = data
            w = self.write(data, cfg(fk))
            self.seen("write", w.outcome, "already-present")
            self._check_stored(w, data)
            self.assertNotIn("PUT", fk.methods())

    def test_repaired_same_size_and_other_size(self):
        for foreign in (lambda d: bytes(b ^ 1 for b in d), lambda d: d[:-1]):
            with self.fake() as fk:
                data = os.urandom(THR + 3)
                fk.state.objects["sha256/" + sha(data)] = foreign(data)
                w = self.write(data, cfg(fk))
                self.seen("write", w.outcome, "repaired")
                self.assertEqual(fk.state.objects["sha256/" + sha(data)], data)
                self._check_stored(w, data)
            shutil.rmtree(self.rd)

    def _failure(self, mode, want, setup=None, durable=False):
        with self.fake() as fk:
            fk.state.mode.update(mode)
            if setup:
                setup(fk)
            data = os.urandom(THR + 11)
            w = self.write(data, cfg(fk, timeout_s=0.5), durable_queue=durable)
            self.seen("write", w.outcome, want)
            f = pointer_fields(read_bytes(w.staged[0]))
            if durable:
                self.assertEqual((w.state, f["state"], f["key"], f["source"]), ("pending", "pending", "sha256/" + sha(data), SRC))
            else:
                self.assertEqual((w.state, f["state"], f["reason"], f["sha256"], f["size"], f["source"]),
                                 ("unsaved", "unsaved", "upload-failed", sha(data), str(len(data)), SRC))
                self.assertEqual(w.user_mark, dict((r["reason"], r["user_mark"]) for r in NORM["unsaved"]["reasons"])["upload-failed"])
            return fk

    def test_denied_and_unavailable_batch(self):
        def slow(fk):
            fk.state.delay_s = 1.5
        for durable in (False, True):
            self._failure({"deny"}, "storage-denied", durable=durable)
            shutil.rmtree(self.rd, ignore_errors=True)
            self._failure({"err5xx"}, "storage-unavailable", durable=durable)
            shutil.rmtree(self.rd, ignore_errors=True)
            self._failure({"delay"}, "storage-unavailable", setup=slow, durable=durable)
            shutil.rmtree(self.rd, ignore_errors=True)
            fk = self._failure({"put_abort"}, "storage-unavailable", durable=durable)
            self.assertEqual(objs(fk), {})          # обрыв посреди PUT — объекта нет
            shutil.rmtree(self.rd, ignore_errors=True)
            self._failure({"put_truncate"}, "storage-unavailable", durable=durable)   # проверка после PUT
            shutil.rmtree(self.rd, ignore_errors=True)

    def test_wrong_secret_is_denied(self):
        with self.fake() as fk:
            env = dict(ENV, WORKSHOP_S3_SECRET_ACCESS_KEY_DEV="synthWRONG-secret-value-0000")
            w = attach.write_attachment(self.rd, RID, os.urandom(THR + 1), ext="bin", config=cfg(fk), uuid=uid(1),
                                        source=SRC, env=env)
            self.seen("write", w.outcome, "storage-denied")
            self.assertEqual(fk.state.log[0]["why"], "signature")

    def test_unreachable_endpoint_is_unavailable(self):
        with self.fake() as fk:
            c = cfg(fk)
        # сервер погашен — соединение отвергнуто
        w = self.write(os.urandom(THR + 1), c)
        self.seen("write", w.outcome, "storage-unavailable")

    def test_source_refused(self):
        w = self.write(None, cfg(None), declared_size=83886080, media_type="video/quicktime")
        self.assertEqual((w.state, w.reason, w.outcome), ("unsaved", "source-refused", None))
        f = pointer_fields(read_bytes(w.staged[0]))
        self.assertEqual((f["size"], f["media-type"], f["source"]), ("83886080", "video/quicktime", SRC))
        self.assertNotIn("sha256", f)

    def test_no_storage_records_sha_and_size(self):
        data = os.urandom(THR + 5)
        w = self.write(data, cfg(None))
        f = pointer_fields(read_bytes(w.staged[0]))
        self.assertEqual((w.state, f["reason"], f["sha256"], f["size"]), ("unsaved", "no-storage", sha(data), str(len(data))))

    def test_defer_upload_pending_without_network(self):
        with self.fake() as fk:
            w = self.write(os.urandom(THR + 1), cfg(fk), durable_queue=True, defer_upload=True)
            self.assertEqual((w.state, fk.state.log), ("pending", []))
        with self.assertRaises(attach.AttachInputError):
            self.write(os.urandom(THR + 1), cfg(None), defer_upload=True)

    def test_source_required_off_git_route(self):
        with self.assertRaises(attach.AttachInputError):
            attach.write_attachment(self.rd, RID, os.urandom(THR + 1), ext="mp4", config=cfg(None), uuid=uid(1))
        self.assertFalse(os.path.exists(self.rd))
        w = attach.write_attachment(self.rd, RID, b"small", ext="txt", config=cfg(None), uuid=uid(1))
        self.assertEqual(w.state, "git")

    def test_input_grammar_refused_before_side_effects(self):
        bad = [dict(ext="MP4"), dict(ext="mp4", slug="Clip"), dict(ext="mp4", slug="a" * 41),
               dict(ext="mp4", uuid="0199A8C0-2B00-7B00-9B00-000000000001"), dict(ext="mp4", source="http://x/y")]
        for kw in bad:
            kw.setdefault("uuid", uid(1))
            with self.assertRaises(attach.AttachInputError, msg=kw):
                attach.write_attachment(self.rd, RID, b"x", config=cfg(None), **kw)
        with self.assertRaises(attach.AttachInputError):
            attach.write_attachment(self.rd, RID.upper(), b"x", ext="mp4", config=cfg(None), uuid=uid(1))
        self.assertFalse(os.path.exists(self.rd))

    def test_minted_uuid_is_v7_and_name_grammar(self):
        w = attach.write_attachment(self.rd, RID, b"x", ext="png", config=cfg(None))
        import re
        self.assertRegex(w.path, r"\Aattachments/%s/[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.png\Z" % RID)
        self.assertIsNotNone(re.fullmatch(NORM["filename"]["pattern"], w.path.split("/")[-1]))

    def test_write_never_lists_or_deletes(self):
        with self.fake() as fk:
            for i, mode in enumerate(({"x"}, {"deny"}, {"err5xx"})):
                fk.state.mode = set(mode)
                self.write(os.urandom(THR + 1 + i), cfg(fk), n=10 + i)
            self.assertTrue(set(fk.methods()) <= {"HEAD", "GET", "PUT"})
            self.assertTrue(all("?" not in (e["key"] or "") for e in fk.state.log))


# ---------------------------------------------------------------------------------------------- чтение
@per_provider
class ReadMatrix(Base):
    def _stored(self, fk, data, durable=False, defer=False, n=1):
        w = self.write(data, cfg(fk), n=n, durable_queue=durable, defer_upload=defer)
        return w.staged[0]

    def test_ok_stored_and_pending(self):
        with self.fake() as fk:
            data = os.urandom(THR + 13)
            p = self._stored(fk, data)
            r = attach.read_attachment(p, cfg(fk), env=ENV)
            self.seen("read", r.outcome, "ok")
            self.assertEqual(r.data, data)
            p2 = os.path.join(self.tmp, "b", "attachments", RID, uid(2) + ".mp4")
            os.makedirs(os.path.dirname(p2))
            with open(p2, "wb") as f:
                f.write(P.render("pending", {"key": "sha256/" + sha(data), "sha256": sha(data), "size": str(len(data)),
                                             "media-type": "video/mp4", "source": SRC}))
            r = attach.read_attachment(p2, cfg(fk), env=ENV)
            self.seen("read", r.outcome, "ok")
            self.assertEqual(r.data, data)
            v = attach.verify(p2, cfg(fk), env=ENV)
            self.seen("read", v.outcome, "ok")
            self.assertIsNone(v.data)

    def test_pending_upload_and_object_missing(self):
        with self.fake() as fk:
            data = os.urandom(THR + 2)
            p = self._stored(fk, data, durable=True, defer=True)
            p2 = self._stored(fk, os.urandom(THR + 3), n=2)
            for k in list(objs(fk)):
                del fk.state.objects[k]
            for path, absent in ((p, "pending-upload"), (p2, "object-missing")):
                r = attach.read_attachment(path, cfg(fk), env=ENV)
                if self.PROVIDER == "aws-no-list":
                    self.seen("read", r.outcome, "storage-denied")
                    self.assertEqual(r.detail, "ambiguous-403-no-list")
                else:
                    self.seen("read", r.outcome, absent)

    def test_size_and_sha_mismatch_never_return_bytes(self):
        with self.fake() as fk:
            data = os.urandom(THR + 4)
            p = self._stored(fk, data)
            k = "sha256/" + sha(data)
            for foreign, want in ((data + b"!", "size-mismatch"), (data[:-1], "size-mismatch"),
                                  (bytes(b ^ 0xFF for b in data), "sha-mismatch")):
                fk.state.objects[k] = foreign
                for fn in (attach.read_attachment, attach.verify):
                    r = fn(p, cfg(fk), env=ENV)
                    self.seen("read", r.outcome, want)
                    self.assertIsNone(r.data)
            fk.state.objects[k] = data
            fk.state.mode.add("get_corrupt")
            r = attach.read_attachment(p, cfg(fk), env=ENV)
            self.seen("read", r.outcome, "sha-mismatch")
            self.assertIsNone(r.data)

    def test_storage_failures_on_read(self):
        with self.fake() as fk:
            data = os.urandom(THR + 6)
            p = self._stored(fk, data)
            fk.state.mode = {"deny"}
            self.seen("read", attach.read_attachment(p, cfg(fk), env=ENV).outcome, "storage-denied")
            fk.state.mode = {"err5xx"}
            self.seen("read", attach.read_attachment(p, cfg(fk), env=ENV).outcome, "storage-unavailable")
            fk.state.mode = {"get_short"}
            r = attach.read_attachment(p, cfg(fk), env=ENV)
            self.seen("read", r.outcome, "storage-unavailable")
            self.assertIsNone(r.data)
            fk.state.mode = {"delay"}
            fk.state.delay_s = 1.2
            self.seen("read", attach.read_attachment(p, cfg(fk, timeout_s=0.4), env=ENV).outcome, "storage-unavailable")
            fk.state.delay_s = 0.2      # медленный ответ в пределах таймаута — успех
            r = attach.read_attachment(p, cfg(fk, timeout_s=2), env=ENV)
            self.seen("read", r.outcome, "ok")
            self.assertEqual(r.data, data)
            fk.state.mode = set()
            env = dict(ENV, WORKSHOP_S3_SECRET_ACCESS_KEY_DEV="synthWRONG-secret-value-0000")
            self.seen("read", attach.read_attachment(p, cfg(fk), env=env).outcome, "storage-denied")
            self.seen("read", attach.read_attachment(p, cfg(None), env=ENV).outcome, "storage-not-configured")
            self.seen("read", attach.read_attachment(p, cfg(fk), env={}).outcome, "storage-not-configured")

    def test_read_order_state_before_binding(self):
        """unsaved/withdrawn судятся состоянием до привязки: сеть не трогается."""
        with self.fake() as fk:
            w = self.write(os.urandom(THR + 1), cfg(None))
            r = attach.read_attachment(w.staged[0], cfg(fk), env=ENV)
            self.seen("read", r.outcome, "not-stored")
            self.assertEqual((r.reason, r.source), ("no-storage", SRC))
            self.assertEqual(fk.state.log, [])

    def test_in_git_and_lfs_and_invalid_do_not_touch_network(self):
        with self.fake() as fk:
            w = self.write(b"tiny", cfg(fk))
            r = attach.read_attachment(w.staged[0], cfg(fk), env=ENV)
            self.seen("read", r.outcome, "in-git")
            self.assertEqual(r.data, b"tiny")
            self.assertEqual([e["method"] for e in fk.state.log], [])


# ---------------------------------------------------------------------------------------------- переходы
def _p(state, **f):
    return P.render(state, {k.replace("_", "-"): v for k, v in f.items()})


@per_provider
class Transitions(Base):
    def test_crafted_table(self):
        d = b"payload-bytes"
        s, k, n = sha(d), "sha256/" + sha(d), str(len(d))
        other = sha(b"other")
        pend = _p("pending", key=k, sha256=s, size=n, media_type="video/mp4", source=SRC)
        stor = _p("stored", key=k, sha256=s, size=n, media_type="video/mp4", source=SRC)
        stor_nosrc = _p("stored", key=k, sha256=s, size=n, media_type="video/mp4")
        stor_mt = _p("stored", key=k, sha256=s, size=n, media_type="image/png", source=SRC)
        stor_other = _p("stored", key="sha256/" + other, sha256=other, size="5", media_type="video/mp4", source=SRC)
        uns_fail = _p("unsaved", sha256=s, size=n, media_type="video/mp4", reason="upload-failed", source=SRC)
        uns_fail_bad = _p("unsaved", sha256=s, size=n, media_type="image/png", reason="upload-failed", source=SRC)
        uns_nost = _p("unsaved", sha256=s, size=n, media_type="video/mp4", reason="no-storage", source=SRC)
        uns_ref = _p("unsaved", size="999", media_type="video/mp4", reason="source-refused", source=SRC)
        uns_ref_nosize = _p("unsaved", reason="source-refused", source=SRC)
        wd_sec = _p("withdrawn", reason="secret")
        wd_era = _p("withdrawn", reason="erasure")
        lfs = b"version https://git-lfs.github.com/spec/v1\n"
        cases = [
            (pend, stor, True), (pend, stor_nosrc, False), (pend, stor_mt, False),
            (pend, uns_fail, True), (pend, uns_fail_bad, False), (pend, uns_nost, False),
            (uns_nost, stor, True), (uns_nost, stor_mt, True), (uns_nost, stor_nosrc, False), (uns_nost, stor_other, False),
            (uns_ref, stor_other, False),            # объявленный size записан — ОБЯЗАН совпасть
            (uns_ref_nosize, stor_other, True),      # нет sha256 и size — сверить нечем (цена названа нормой)
            (uns_nost, d, True), (uns_nost, b"other", False), (uns_ref, b"anything", True),
            (stor, wd_sec, True), (pend, wd_era, True), (uns_nost, wd_sec, True), (d, wd_sec, True),
            (stor, stor_mt, False), (stor, uns_fail, False), (stor, d, False), (stor, pend, False),
            (d, b"other bytes", False), (d, stor, False),
            (wd_sec, wd_era, False), (wd_sec, stor, False), (wd_sec, d, False),
            (lfs, wd_sec, False), (b"workshop-attachment-pointer 2\n", wd_sec, False),
            (stor, stor, True), (d, d, True),
        ]
        for i, (a, b, want) in enumerate(cases):
            self.assertEqual(P.check_transition(a, b)[0], want, (i, P.check_transition(a, b)))

    def test_complete_pending_changes_only_state_line(self):
        with self.fake() as fk:
            data = os.urandom(THR + 21)
            w = self.write_pending(fk, data)
            before = read_bytes(w)
            r = attach.complete_pending(w, data, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "uploaded")
            after = read_bytes(w)
            self.assertEqual(after, before.replace(b"state pending", b"state stored"))
            self.assertEqual(sum(1 for x, y in zip(before.split(b"\n"), after.split(b"\n")) if x != y), 1)
            with self.assertRaises(attach.AttachInputError):    # уже stored — не pending
                attach.complete_pending(w, data, cfg(fk), env=ENV)

    def write_pending(self, fk, data, n=1):
        w = self.write(data, cfg(fk), n=n, durable_queue=True, defer_upload=True)
        return w.staged[0]

    def test_complete_pending_refusals(self):
        with self.fake() as fk:
            data = os.urandom(THR + 22)
            p = self.write_pending(fk, data)
            before = read_bytes(p)
            r = attach.complete_pending(p, data + b"x", cfg(fk), env=ENV)
            self.seen("write", r.outcome, "bytes-mismatch")
            r = attach.complete_pending(p, data, cfg(None), env=ENV)
            self.seen("write", r.outcome, "storage-not-configured")
            r = attach.complete_pending(p, data, cfg(fk), env={})
            self.seen("write", r.outcome, "storage-not-configured")
            fk.state.mode = {"deny"}
            r = attach.complete_pending(p, data, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "storage-denied")
            fk.state.mode = {"err5xx"}
            r = attach.complete_pending(p, data, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "storage-unavailable")
            self.assertEqual(read_bytes(p), before)
            self.assertEqual(objs(fk), {})              # отказы ничего не загрузили
            fk.state.mode = set()
            fk.state.objects["sha256/" + sha(data)] = data
            r = attach.complete_pending(p, data, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "already-present")
            with self.assertRaises(attach.AttachInputError):
                attach.complete_pending(p, data, cfg(fk), env=ENV)

    def test_fail_pending(self):
        with self.fake() as fk:
            data = os.urandom(THR + 23)
            p = self.write_pending(fk, data)
            before = read_bytes(p)
            r = attach.fail_pending(p)
            after = read_bytes(p)
            self.assertEqual((r.state, r.reason), ("unsaved", "upload-failed"))
            self.assertTrue(P.check_transition(before, after)[0])
            fb, fa = pointer_fields(before), pointer_fields(after)
            for k in ("sha256", "size", "media-type", "source"):
                self.assertEqual(fb[k], fa[k])
            self.assertNotIn("key", fa)

    def test_late_save_to_storage_and_git(self):
        with self.fake() as fk:
            data = os.urandom(THR + 30)
            p = self.write(data, cfg(None)).staged[0]          # unsaved no-storage
            r = attach.late_save(p, data[:-1], cfg(fk), env=ENV)
            self.seen("write", r.outcome, "bytes-mismatch")
            r = attach.late_save(p, data, cfg(None), env=ENV)
            self.seen("write", r.outcome, "storage-not-configured")
            before = read_bytes(p)
            r = attach.late_save(p, data, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "uploaded")
            self.assertTrue(P.check_transition(before, read_bytes(p))[0])
            self.assertEqual(pointer_fields(read_bytes(p))["source"], SRC)
            # поднятый порог открывает досохранение в git
            data2 = os.urandom(THR + 40)
            p2 = self.write(data2, cfg(None), n=2).staged[0]
            r = attach.late_save(p2, data2, cfg(None, threshold=THR * 2), env=ENV)
            self.assertEqual(r.state, "git")
            self.assertEqual(read_bytes(p2), data2)

    def test_late_save_source_refused_size_must_match_for_storage(self):
        with self.fake() as fk:
            p = self.write(None, cfg(None), declared_size=THR + 50).staged[0]
            r = attach.late_save(p, os.urandom(THR + 49), cfg(fk), env=ENV)
            self.seen("write", r.outcome, "bytes-mismatch")
            data = os.urandom(THR + 50)
            r = attach.late_save(p, data, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "uploaded")

    def test_withdraw_flows(self):
        with self.fake() as fk:
            data = os.urandom(THR + 60)
            p = self.write(data, cfg(fk)).staged[0]
            k = "sha256/" + sha(data)
            r = attach.withdraw(p, "secret", cfg(None), WCREDS, env=ENV)
            self.seen("write", r.outcome, "storage-not-configured")
            r = attach.withdraw(p, "secret", cfg(fk), WCREDS, env=ENV)
            self.assertEqual((r.state, r.detail), ("withdrawn", "object-deleted"))
            self.assertNotIn(k, fk.state.objects)
            dels = [e for e in fk.state.log if e["method"] == "DELETE"]
            self.assertEqual([e["akid"] for e in dels], [WAKID])     # ключ изъятия, не писателя
            self.assertEqual(read_bytes(p), b"workshop-attachment-pointer 1\nstate withdrawn\nreason secret\n")
            self.assertEqual(attach.withdraw(p, "secret", cfg(fk), WCREDS, env=ENV).detail, "already-withdrawn")
            with self.assertRaises(attach.AttachInputError):
                attach.withdraw(p, "erasure", cfg(fk), WCREDS, env=ENV)
            # ключ писателя DELETE не может (права put/get/head) — подмена привязки отвергается хранилищем
            p2 = self.write(os.urandom(THR + 61), cfg(fk), n=2).staged[0]
            bad = {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV", "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"}
            before = read_bytes(p2)
            r = attach.withdraw(p2, "erasure", cfg(fk), bad, env=ENV)
            self.seen("write", r.outcome, "storage-denied")
            self.assertEqual(read_bytes(p2), before)
            fk.state.mode = {"err5xx"}
            r = attach.withdraw(p2, "erasure", cfg(fk), WCREDS, env=ENV)
            self.seen("write", r.outcome, "storage-unavailable")
            fk.state.mode = set()
            # git → withdrawn и unsaved → withdrawn — без сети
            n0 = len(fk.state.log)
            g = self.write(b"small", cfg(fk), n=3).staged[0]
            self.assertEqual(attach.withdraw(g, "erasure", cfg(fk), WCREDS, env=ENV).state, "withdrawn")
            u = self.write(None, cfg(fk), n=4, declared_size=5).staged[0]
            self.assertEqual(attach.withdraw(u, "erasure", cfg(fk), WCREDS, env=ENV).state, "withdrawn")
            self.assertEqual(len(fk.state.log), n0)
            with self.assertRaises(attach.AttachInputError):
                attach.withdraw(u, "upload-failed", cfg(fk), WCREDS, env=ENV)

    def test_withdraw_pending_with_object_deletes_by_key(self):
        # D20 N2 (attachments.yaml states.transitions pending → withdrawn): «объект по key удалён, если он есть (загрузка могла
        # завершиться до перехода в stored), — так же, как у stored»: указатель pending, объект в хранилище — законный DELETE
        # по key ключом изъятия; без объекта — изъятие тоже законно (DELETE 404 — not-found), указатель — withdrawn
        with self.fake() as fk:
            d = os.urandom(THR + 62)
            k = "sha256/" + sha(d)
            p = place(carrier_path(self.rd, 7), ptr_pending(d))
            fk.state.objects[k] = d                                   # загрузка завершилась, указатель ещё pending
            r = attach.withdraw(p, "secret", cfg(fk), WCREDS, env=ENV)
            self.assertEqual((r.state, r.detail), ("withdrawn", "object-deleted"))
            self.assertNotIn(k, fk.state.objects)
            dels = [e for e in fk.state.log if e["method"] == "DELETE"]
            self.assertEqual([e["akid"] for e in dels], [WAKID])
            self.assertEqual(read_bytes(p), b"workshop-attachment-pointer 1\nstate withdrawn\nreason secret\n")
            d2 = os.urandom(THR + 63)
            p2 = place(carrier_path(self.rd, 8), ptr_pending(d2))      # объекта нет: загрузка не завершилась
            r2 = attach.withdraw(p2, "erasure", cfg(fk), WCREDS, env=ENV)
            self.assertEqual(r2.state, "withdrawn")
            self.assertEqual(read_bytes(p2), b"workshop-attachment-pointer 1\nstate withdrawn\nreason erasure\n")

    def test_adapter_never_writes_illegal_transition(self):
        with self.fake() as fk:
            data = os.urandom(THR + 70)
            p = self.write(data, cfg(fk)).staged[0]
            before = read_bytes(p)
            n0 = len(fk.mutations())
            w = self.write(os.urandom(THR + 70), cfg(fk))           # тот же uuid, иные байты — до сети
            self.seen("write", w.outcome, "bytes-mismatch")
            w = self.write(data, cfg(None))                         # хранилища нет: stored не трогается
            self.assertEqual((w.state, w.outcome, w.detail), ("stored", None, "already-recorded"))
            self.assertEqual(read_bytes(p), before)
            self.assertEqual(len(fk.mutations()), n0)


# ---------------------------------------------------------------------------------------------- идемпотентность
@per_provider
class Idempotency(Base):
    def test_same_bytes_two_records_one_object(self):
        with self.fake() as fk:
            data = os.urandom(THR + 80)
            w1 = attach.write_attachment(self.rd, RID, data, ext="mp4", config=cfg(fk), uuid=uid(1), source=SRC, env=ENV)
            rid2 = "0199a8c0-1a00-7a00-8a00-000000000901"
            w2 = attach.write_attachment(self.rd, rid2, data, ext="mp4", config=cfg(fk), uuid=uid(2), source=SRC, env=ENV)
            self.seen("write", w1.outcome, "uploaded")
            self.seen("write", w2.outcome, "already-present")
            self.assertEqual(pointer_fields(read_bytes(w1.staged[0]))["key"], pointer_fields(read_bytes(w2.staged[0]))["key"])
            self.assertEqual(fk.methods().count("PUT"), 1)

    def test_crash_between_upload_and_pointer_then_retry(self):
        with self.fake() as fk:
            data = os.urandom(THR + 81)

            def boom(outcome):
                raise RuntimeError("crash")
            with self.assertRaises(attach.AdapterFault):
                self.write(data, cfg(fk), _after_upload=boom)
            self.assertEqual([f for _r, _d, fs in os.walk(self.rd) for f in fs], [])   # носителя нет
            w = self.write(data, cfg(fk))                          # повтор — тот же uuid и имя
            self.seen("write", w.outcome, "already-present")
            self.assertEqual(fk.methods().count("PUT"), 1)

    def test_retry_after_upload_failed_same_uuid(self):
        with self.fake() as fk:
            data = os.urandom(THR + 82)
            fk.state.mode = {"err5xx"}
            w = self.write(data, cfg(fk))
            self.assertEqual(w.state, "unsaved")
            before = read_bytes(w.staged[0])
            fk.state.mode = set()
            w2 = self.write(data, cfg(fk))
            self.seen("write", w2.outcome, "uploaded")
            self.assertTrue(P.check_transition(before, read_bytes(w2.staged[0]))[0])

    def test_repeat_identical_is_noop_and_deterministic(self):
        with self.fake() as fk:
            data = os.urandom(THR + 83)
            w1 = self.write(data, cfg(fk))
            b1 = read_bytes(w1.staged[0])
            m1 = os.stat(w1.staged[0]).st_mtime_ns
            w2 = self.write(data, cfg(fk))
            self.assertEqual((read_bytes(w2.staged[0]), os.stat(w2.staged[0]).st_mtime_ns), (b1, m1))
            other = os.path.join(self.tmp, "other")
            w3 = attach.write_attachment(other, RID, data, ext="mp4", config=cfg(fk), uuid=uid(1), slug="clip",
                                         source=SRC, env=ENV)
            self.assertEqual(read_bytes(w3.staged[0]), b1)


# ---------------------------------------------------------------------------------------------- property
@per_provider
class Properties(Base):
    def test_random_bytes_round_trip_and_integrity(self):
        rnd = random.Random(20261009)
        with self.fake() as fk:
            for i in range(40):
                size = rnd.choice([0, 1, THR - 1, THR, THR + 1, rnd.randint(0, 3 * THR)])
                data = bytes(rnd.getrandbits(8) for _ in range(size))
                if i % 7 == 0:
                    data = b"workshop-attachment-pointer " + data
                w = attach.write_attachment(self.rd, RID, data, ext="bin", config=cfg(fk), uuid=uid(100 + i),
                                            source=SRC, env=ENV)
                want_git = len(data) <= THR and not data.startswith(b"workshop-attachment-pointer ")
                self.assertEqual(w.state, "git" if want_git else "stored", (i, len(data)))
                key = "sha256/" + sha(data)
                corrupt = (not want_git) and rnd.random() < 0.5
                if corrupt:
                    obj = bytearray(fk.state.objects[key])
                    if obj and rnd.random() < 0.5:
                        obj[rnd.randrange(len(obj))] ^= 1 << rnd.randrange(8)
                    else:
                        obj += b"\x00"
                    fk.state.objects[key] = bytes(obj)
                r = attach.read_attachment(w.staged[0], cfg(fk), env=ENV)
                if r.outcome in ("ok", "in-git"):
                    self.assertEqual(r.data, data)      # (е): выданные байты — ровно поданные
                    self.assertFalse(corrupt)
                else:
                    self.assertTrue(corrupt)
                    self.assertIn(r.outcome, ("size-mismatch", "sha-mismatch"))
                    self.assertIsNone(r.data)
                if corrupt:
                    fk.state.objects[key] = data

    def test_default_threshold_exact_bytes(self):
        for size, want in ((7999999, "git"), (8000000, "git"), (8000001, "unsaved")):
            data = os.urandom(size)
            w = attach.write_attachment(self.rd, RID, data, ext="bin", config=attach.load_config({}),
                                        uuid=uid(size % 1000), source=SRC)
            self.assertEqual(w.state, want)
            if want == "git":
                self.assertEqual(read_bytes(w.staged[0]), data)


# ---------------------------------------------------------------------------------------------- SigV4 и транспорт
class FakeOracleKAT(unittest.TestCase):
    def test_aws_documented_get_object_example(self):
        """Известный ответ AWS (Signature V4, «Example: GET Object», examplebucket, 20130524) — проверка самого оракула."""
        hdrs = {"host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9",
                "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "x-amz-date": "20130524T000000Z",
                "authorization": "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request,"
                                 "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,"
                                 "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"}
        ok, akid, why = fake_s3.verify_sigv4("GET", "/test.txt", hdrs, hdrs["x-amz-content-sha256"],
                                             {"AKIAIOSFODNN7EXAMPLE": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"})
        self.assertEqual((ok, why), (True, "ok"))
        hdrs["range"] = "bytes=0-8"
        self.assertFalse(fake_s3.verify_sigv4("GET", "/test.txt", hdrs, hdrs["x-amz-content-sha256"],
                                              {"AKIAIOSFODNN7EXAMPLE": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"})[0])


@per_provider
class Transport(Base):
    def test_oracle_shares_no_code_with_writer(self):
        import ast
        with open(os.path.join(_TESTS, "fake_s3.py"), "rb") as f:
            tree = ast.parse(f.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
        self.assertFalse({m for m in mods if m.split(".")[0] in ("attach", "yamlmini", "comment")}, mods)

    def test_put_payload_is_signed(self):
        with self.fake() as fk:
            data = os.urandom(THR + 90)
            self.write(data, cfg(fk))
            puts = [e for e in fk.state.log if e["method"] == "PUT"]
            self.assertEqual(len(puts), 1)
            self.assertEqual(puts[0]["claimed"], sha(data))
            self.assertEqual(puts[0]["body_sha256"], sha(data))
            self.assertIn("x-amz-content-sha256", puts[0]["signed"].split(";"))
            self.assertTrue(all(e["why"] == "ok" for e in fk.state.log))

    def test_tampered_body_is_refused_by_storage(self):
        """Тело, не равное подписанному хешу, хранилище отвергает (400) — адаптер: storage-unavailable."""
        with self.fake() as fk:
            orig = attach_s3.S3Client.put

            def tampering_put(self_, key, body):
                h = attach_s3.sigv4_headers("PUT", self_.endpoint, key, sha(body), self_.creds, self_.region, self_._clock())
                import http.client
                c = http.client.HTTPConnection("127.0.0.1", fk.port, timeout=2)
                h["Content-Length"] = str(len(body))
                c.request("PUT", self_.endpoint.canonical_uri(key), body=body[:-1] + b"Z", headers=h)
                r = c.getresponse()
                head = r.read()
                c.close()
                return attach_s3.Resp(attach_s3._classify_status(r.status, head), status=r.status)
            attach_s3.S3Client.put = tampering_put
            try:
                w = self.write(os.urandom(THR + 91), cfg(fk))
            finally:
                attach_s3.S3Client.put = orig
            self.seen("write", w.outcome, "storage-unavailable")
            self.assertEqual(objs(fk), {})

    def test_virtual_hosted_addressing_and_prefix_encoding(self):
        with self.fake() as fk:
            orig = attach_s3.Endpoint.connect_host
            attach_s3.Endpoint.connect_host = lambda self_: "127.0.0.1"
            try:
                c = cfg(fk, addressing="virtual", key_prefix="team a/v1+", endpoint="http://localhost:%d" % fk.port)
                data = os.urandom(THR + 92)
                w = self.write(data, c)
                self.seen("write", w.outcome, "uploaded")
                self.assertIn("team a/v1+sha256/" + sha(data), fk.state.objects)
                r = attach.read_attachment(w.staged[0], c, env=ENV)
                self.seen("read", r.outcome, "ok")
            finally:
                attach_s3.Endpoint.connect_host = orig
            self.assertTrue(all(e["why"] == "ok" for e in fk.state.log))

    def test_tls_always_http_only_flagged_loopback(self):
        base = {"bucket": "b", "credentials": {"access_key_id": "A", "secret_access_key": "B"}}
        for ep, flag in (("http://127.0.0.1:9", False), ("http://example.org", True), ("ftp://x", True),
                         ("https://u:p@s3.example.org", False), ("https://s3.example.org/path", False),
                         ("https://s3.example.org?x=1", False)):
            with self.assertRaises(attach.ConfigError, msg=ep):
                attach.load_config({"storage": dict(base, endpoint=ep, allow_insecure_http=flag)})
        c = attach.load_config({"storage": dict(base, endpoint="https://127.0.0.1:1")})
        self.assertIsNotNone(c.binding)
        # https на локальный порт без TLS-сервера — сеть/TLS → storage-unavailable, не тихий откат на http
        with self.fake() as fk:
            c = attach.load_config({"git_threshold_bytes": THR, "storage": dict(base, endpoint="https://127.0.0.1:%d" % fk.port,
                                                           credentials={"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                                                                        "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"},
                                                           timeout_s=2)})
            w = self.write(os.urandom(THR + 1), c)
            self.seen("write", w.outcome, "storage-unavailable")


# ---------------------------------------------------------------------------------------------- секреты
@per_provider
class Secrets(Base):
    """Положительный контракт: ни одно значение из ЗАКРЫТОГО множества SYNTH не встречается ни в одном
    выводе — результаты, исключения (str/repr/traceback), логи, stdout/stderr CLI, файлы рабочего дерева."""

    def _scan(self, blobs):
        for b in blobs:
            if isinstance(b, str):
                b = b.encode("utf-8", "surrogateescape")
            for v in SYNTH:
                self.assertNotIn(v.encode("utf-8"), b)

    def test_client_masks_own_secrets_and_prefix(self):
        """Второй рубеж прямо: клиент, построенный адаптером, вырезает свои ключи и префикс из любой строки наружу.
        Мутация «снять маскирование» (redact=() или _mask=identity) роняет этот тест."""
        c = cfg(None)
        with self.fake(prefix=PREFIX) as fk:
            c = cfg(fk, key_prefix=PREFIX)
            cl = attach._client(c.binding, attach._creds(c.binding.cred_names, ENV))
            text = cl._mask("detail %s %s %s end" % (AKID, SECRET, PREFIX))
            for v in (AKID, SECRET, PREFIX):
                self.assertNotIn(v, text)
            self.assertIn("end", text)

    def test_no_secret_anywhere(self):
        blobs = []
        log = io.StringIO()
        h = logging.StreamHandler(log)
        logging.getLogger().addHandler(h)
        logging.getLogger().setLevel(logging.DEBUG)
        try:
            with self.fake(prefix=PREFIX) as fk:
                c = cfg(fk, key_prefix=PREFIX)
                # отсутствующий объект: путь неоднозначного 403 и канарейки — тоже под контрактом
                d0 = os.urandom(THR + 9)
                w0 = attach.write_attachment(os.path.join(self.tmp, "z"), RID, d0, ext="bin", config=c, uuid=uid(888),
                                             source=SRC, env=ENV)
                del fk.state.objects[PREFIX + "sha256/" + sha(d0)]
                for cc in (c, cfg(fk, key_prefix=PREFIX, canary_key=None)):
                    blobs += [repr(attach.read_attachment(w0.staged[0], cc, env=ENV)), repr(attach.probe_storage(cc, env=ENV))]
                for mode in (set(), {"deny"}, {"err5xx"}, {"put_abort"}, {"put_truncate"}, {"get_corrupt"}, {"get_short"}):
                    fk.state.mode = set(mode)
                    for durable in (False, True):
                        try:
                            rd = os.path.join(self.tmp, "m%d%s" % (len(blobs), durable))
                            w = attach.write_attachment(rd, RID, os.urandom(THR + 1), ext="bin", config=c,
                                                        uuid=uid(len(blobs)), source=SRC, durable_queue=durable, env=ENV)
                            blobs += [repr(w), json.dumps(w.as_dict(), ensure_ascii=False)]
                            r = attach.read_attachment(w.staged[0], c, env=ENV)
                            blobs += [repr(r), json.dumps(r.as_dict(), ensure_ascii=False)]
                        except Exception as e:  # noqa: BLE001
                            blobs += [str(e), repr(e), traceback.format_exc()]
                # исключения путей ошибки: порча конфига, вход, сбой адаптера
                for bad in ({"storage": {"endpoint": "http://evil.example", "bucket": "b",
                                         "credentials": {"access_key_id": AKID, "secret_access_key": SECRET}}},
                            {"storage": {"endpoint": fk.endpoint, "bucket": "b",
                                         "credentials": {"access_key_id": "lower" + SECRET, "secret_access_key": "X"}}}):
                    try:
                        attach.load_config(bad)
                    except Exception as e:  # noqa: BLE001
                        blobs += [str(e), repr(e), traceback.format_exc()]
                orig = attach_s3.S3Client._conn

                def explode(self_):
                    raise OSError("boom with %s" % SECRET)
                attach_s3.S3Client._conn = explode
                try:
                    w = attach.write_attachment(os.path.join(self.tmp, "x"), RID, os.urandom(THR + 1), ext="bin",
                                                config=c, uuid=uid(999), source=SRC, env=ENV)
                    blobs += [repr(w)]
                except Exception as e:  # noqa: BLE001
                    blobs += [str(e), repr(e), traceback.format_exc()]
                finally:
                    attach_s3.S3Client._conn = orig
                blobs.append(repr(attach_s3.Credentials(AKID, SECRET)))
                blobs.append(repr(c.binding))
                # CLI
                cfgp = os.path.join(self.tmp, "cfg.json")
                with open(cfgp, "w", encoding="utf-8") as f:
                    json.dump({"git_threshold_bytes": THR, "storage": {
                        "endpoint": fk.endpoint, "bucket": fk.state.bucket, "allow_insecure_http": True,
                        "key_prefix": PREFIX, "canary_key": CANARY,
                        "credentials": {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                                        "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"}}}, f)
                dp = os.path.join(self.tmp, "d.bin")
                with open(dp, "wb") as f:
                    f.write(os.urandom(THR + 1))
                env = dict(os.environ, **ENV)
                for mode in (set(), {"deny"}):
                    fk.state.mode = set(mode)
                    out = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", cfgp, "write", "--record-dir",
                                          os.path.join(self.tmp, "cli"), "--record-id", RID, "--ext", "bin", "--data", dp,
                                          "--source", SRC, "--uuid", uid(500 + len(mode))],
                                         cwd=_ROOT, env=env, capture_output=True)
                    blobs += [out.stdout, out.stderr]
                    self.assertEqual(out.returncode, 0, out.stderr)
                fk.state.mode = set()
                for args in (["read", w0.staged[0]], ["verify", w0.staged[0]], ["probe"]):
                    out = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", cfgp] + args,
                                         cwd=_ROOT, env=env, capture_output=True)
                    blobs += [out.stdout, out.stderr]
                    self.assertEqual(out.returncode, 0, out.stderr)
                try:   # префикс вне формы (управляющий символ) — ConfigError без отражения значения
                    attach.load_config({"storage": {"endpoint": fk.endpoint, "bucket": "b", "key_prefix": PREFIX + "\x00",
                                                    "allow_insecure_http": True,
                                                    "credentials": {"access_key_id": "A", "secret_access_key": "B"}}})
                except Exception as e:  # noqa: BLE001
                    blobs += [str(e), repr(e), "".join(traceback.format_exception(type(e), e, e.__traceback__))]
        finally:
            logging.getLogger().removeHandler(h)
        blobs.append(log.getvalue())
        for root, _d, files in os.walk(self.tmp):
            for fn in files:
                if fn != "cfg.json":
                    blobs.append(read_bytes(os.path.join(root, fn)))
        self.assertGreater(len(blobs), 30)
        self._scan(blobs)


# ---------------------------------------------------------------------------------------------- собственная ошибка
@per_provider
class AdapterFaultOutcome(Base):
    def test_fault_is_separate_from_norm_outcomes(self):
        self.assertNotIn(attach.ADAPTER_FAULT, NORM_READ + NORM_WRITE)
        self.assertTrue(issubclass(attach.ConfigError, attach.AdapterFault))

    def test_unexpected_exception_is_fault(self):
        orig = attach._upload
        attach._upload = lambda *a, **k: 1 / 0
        try:
            with self.fake() as fk:
                with self.assertRaises(attach.AdapterFault) as cm:
                    self.write(os.urandom(THR + 1), cfg(fk))
            self.assertEqual(cm.exception.outcome, "adapter-fault")
        finally:
            attach._upload = orig

    def test_corrupt_config_is_fault(self):
        for bad in ({"git_threshold_bytes": -1}, {"git_threshold_bytes": "8000000"}, {"git_threshold_bytes": True},
                    {"unknown": 1}, {"storage": "x"}, {"storage": {"endpoint": 5}},
                    {"storage": {"key_prefix": "a\x00b"}}, {"storage": {"list_permission": "yes"}},
                    {"storage": {"canary_key": 1}}, {"storage": {"bucket": "a/b", "endpoint": "https://h"}},
                    {"storage": {"endpoint": "https://s3.example.org", "bucket": "b", "credentials": "WORKSHOP"}},
                    {"storage": {"endpoint": "https://s3.example.org", "bucket": "b", "addressing": "dns",
                                 "credentials": {"access_key_id": "A", "secret_access_key": "B"}}},
                    {"storage": {"endpoint": "https://s3.example.org", "bucket": "b", "timeout_s": 0,
                                 "credentials": {"access_key_id": "A", "secret_access_key": "B"}}}, []):
            with self.assertRaises(attach.ConfigError, msg=bad):
                attach.load_config(bad)

    def test_own_output_unparsable_is_fault(self):
        orig = P.render
        P.render = lambda state, fields: b"workshop-attachment-pointer 1\nstate broken\n"
        try:
            with self.assertRaises(attach.AdapterFault):
                self.write(os.urandom(THR + 1), cfg(None))
        finally:
            P.render = orig

    def test_cli_exit_codes(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "wb") as f:
            f.write(b"{not json")
        p = os.path.join(EX, "01-git-bytes")
        f = example_files("01-git-bytes")[0]
        r = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", bad, "read", f], cwd=_ROOT, capture_output=True)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(json.loads(r.stdout)["outcome"], "adapter-fault")
        r = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "read", os.path.join(p, "nope")], cwd=_ROOT, capture_output=True)
        self.assertEqual(r.returncode, 2)


# ---------------------------------------------------------------------------------------------- CLI
@per_provider
class Cli(Base):
    def run_cli(self, *args, env=None):
        r = subprocess.run([sys.executable, "-m", "bot.attach", "--json"] + list(args), cwd=_ROOT, capture_output=True,
                           env=dict(os.environ, **(env or {})))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_cli_round_trip(self):
        f = example_files("n3-lfs-pointer")[0]
        self.assertEqual(self.run_cli("classify", f)["kind"], "lfs")
        # D20 T4: вывод --json несёт конверт схемы вывода (output_schema_version, command, outcome) — поля T2 те же
        self.assertEqual({k: v for k, v in self.run_cli("route", "--size", "8000001").items()
                          if k not in ("output_schema_version", "command", "outcome")},
                         {"target": "unsaved", "reason": "no-storage", "step": 4})
        with self.fake() as fk:
            cfgp = os.path.join(self.tmp, "cfg.json")
            with open(cfgp, "w", encoding="utf-8") as fh:
                json.dump({"git_threshold_bytes": THR, "storage": {
                    "endpoint": fk.endpoint, "bucket": fk.state.bucket, "allow_insecure_http": True,
                    "credentials": {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                                    "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"}}}, fh)
            data = os.urandom(THR + 5)
            dp = os.path.join(self.tmp, "d.bin")
            with open(dp, "wb") as fh:
                fh.write(data)
            w = self.run_cli("--config", cfgp, "write", "--record-dir", self.rd, "--record-id", RID, "--ext", "bin",
                             "--data", dp, "--source", SRC, "--uuid", uid(1), env=ENV)
            self.assertEqual((w["state"], w["outcome"]), ("stored", "uploaded"))
            out = os.path.join(self.tmp, "out.bin")
            r = self.run_cli("--config", cfgp, "read", w["staged"][0], "--out", out, env=ENV)
            self.assertEqual(r["outcome"], "ok")
            self.assertEqual(read_bytes(out), data)



# ============================================================================================== R1 (verify-r1-codex.md)
def carrier_path(rd, n=1):
    return os.path.join(rd, "attachments", RID, uid(n) + "-clip.mp4")


def place(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def ptr_stored(d):
    s = sha(d)
    return P.render("stored", {"key": "sha256/" + s, "sha256": s, "size": str(len(d)), "media-type": "video/mp4",
                               "source": SRC})


def ptr_pending(d):
    s = sha(d)
    return P.render("pending", {"key": "sha256/" + s, "sha256": s, "size": str(len(d)), "media-type": "video/mp4",
                                "source": SRC})


def cfg_json(path, fk, **extra):
    st = {"endpoint": fk.endpoint, "bucket": fk.state.bucket, "allow_insecure_http": True, "timeout_s": 5,
          "canary_key": CANARY, "list_permission": fk.state.provider == "aws-list",
          "credentials": {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                          "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"}}
    st.update(extra)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"git_threshold_bytes": THR, "storage": st}, f, ensure_ascii=False)
    return path


# ---- находка 1 (BLOCKER): 403 без ListBucket. Инвариант: отсутствие объекта и отказ ключа не подменяют друг
# друга; запись после неоднозначного 403 идёт PUT'ом; чтение различает 403 канарейкой. Измерения: режим
# провайдера × (объект есть | нет) × (ключ валиден | подпись неверна | ключ отозван) × канарейка (нет | не в
# бакете | есть) × list_permission × операция (запись | чтение | проба).
@per_provider
class NoListSemantics(Base):
    def test_empty_bucket_write_uploads_without_list(self):
        with self.fake() as fk:
            data = os.urandom(THR + 100)
            w = self.write(data, cfg(fk))
            self.seen("write", w.outcome, "uploaded")
            self.assertEqual(objs(fk), {"sha256/" + sha(data): data})
            self.assertEqual(fk.methods(), ["HEAD", "PUT", "GET"])
            if self.PROVIDER == "aws-no-list":
                self.assertEqual(w.detail, "head-403-ambiguous-put")

    def test_absent_object_read_matrix(self):
        """404 → отсутствие во всех режимах; 403 (aws-no-list) → storage-denied ambiguous-403-no-list; канарейка
        (нет / не в бакете / есть) на классификацию чтения не влияет."""
        with self.fake(canary=False) as fk:
            p_st = self.write(os.urandom(THR + 101), cfg(fk), n=1).staged[0]
            p_pe = self.write(os.urandom(THR + 102), cfg(fk), n=2, durable_queue=True, defer_upload=True).staged[0]
            for k in list(objs(fk)):
                del fk.state.objects[k]
            for canary_cfg, canary_obj in ((None, False), (CANARY, False), (CANARY, True)):
                if canary_obj:
                    fk.state.objects[CANARY] = b"c"
                c = cfg(fk, canary_key=canary_cfg)
                for p, absent in ((p_st, "object-missing"), (p_pe, "pending-upload")):
                    for fn in (attach.read_attachment, attach.verify):
                        n0 = len(fk.state.log)
                        r = fn(p, c, env=ENV)
                        self.assertIsNone(r.data)
                        self.assertEqual([e["method"] for e in fk.state.log[n0:]], ["GET"])   # канарейку не спрашивают
                        if self.PROVIDER == "aws-no-list":
                            self.seen("read", r.outcome, "storage-denied")
                            self.assertEqual(r.detail, "ambiguous-403-no-list")
                        else:
                            self.seen("read", r.outcome, absent)

    def test_invalid_key_matrix(self):
        with self.fake() as fk:
            data = os.urandom(THR + 103)
            p_have = self.write(data, cfg(fk), n=1).staged[0]
            d2 = os.urandom(THR + 104)
            p_none = self.write(d2, cfg(fk), n=2).staged[0]
            del fk.state.objects["sha256/" + sha(d2)]
            bad_env = dict(ENV, WORKSHOP_S3_SECRET_ACCESS_KEY_DEV="synthWRONG-secret-value-0000")
            r = attach.read_attachment(p_have, cfg(fk), env=bad_env)
            self.seen("read", r.outcome, "storage-denied")                    # подпись — отказ однозначный
            r = attach.read_attachment(p_none, cfg(fk), env=bad_env)
            if self.PROVIDER == "yandex":
                self.seen("read", r.outcome, "object-missing")                # замер: 404 при любом ключе
            else:
                self.seen("read", r.outcome, "storage-denied")
            fk.state.mode = {"deny"}                                           # ключ отозван (AccessDenied)
            r = attach.read_attachment(p_have, cfg(fk), env=ENV)
            self.seen("read", r.outcome, "storage-denied")
            r = attach.read_attachment(p_none, cfg(fk), env=ENV)
            self.seen("read", r.outcome, "object-missing" if self.PROVIDER == "yandex" else "storage-denied")
            n0 = len(fk.mutations())
            w = self.write(os.urandom(THR + 105), cfg(fk), n=3)
            self.seen("write", w.outcome, "storage-denied")
            self.assertEqual(objs(fk), {"sha256/" + sha(data): data})
            self.assertLessEqual(len(fk.mutations()) - n0, 1)                # максимум отвергнутый PUT

    def test_list_permission_true_skips_put_after_403(self):
        with self.fake() as fk:
            w = self.write(os.urandom(THR + 106), cfg(fk, list_permission=True))
            if self.PROVIDER == "aws-no-list":                                 # конфиг лжёт про list — громко
                self.seen("write", w.outcome, "storage-denied")
                self.assertEqual(fk.mutations(), [])
            else:
                self.seen("write", w.outcome, "uploaded")

    def test_probe_storage(self):
        with self.fake() as fk:
            self.assertEqual(attach.probe_storage(cfg(fk), env=ENV)["storage_probe_outcome"], "ok")
            self.assertIsNone(attach.probe_storage(cfg(fk, canary_key=None), env=ENV)["storage_probe_outcome"])
            self.assertFalse(attach.probe_storage(cfg(None), env=ENV)["storage_configured"])
            fk.state.mode = {"deny"}
            self.assertEqual(attach.probe_storage(cfg(fk), env=ENV)["storage_probe_outcome"], "storage-denied")
            fk.state.mode = {"err5xx"}
            self.assertEqual(attach.probe_storage(cfg(fk), env=ENV)["storage_probe_outcome"], "storage-unavailable")
            fk.state.mode = set()
            del fk.state.objects[CANARY]
            self.assertEqual(attach.probe_storage(cfg(fk), env=ENV)["storage_probe_outcome"], "storage-denied")

    def test_utf8_key_prefix_end_to_end(self):
        prefix = "команда/v1 +"
        with self.fake(prefix=prefix) as fk:
            c = cfg(fk, key_prefix=prefix)
            data = os.urandom(THR + 107)
            w = self.write(data, c)
            self.seen("write", w.outcome, "uploaded")
            self.assertEqual(fk.state.objects[prefix + "sha256/" + sha(data)], data)
            self.seen("read", attach.read_attachment(w.staged[0], c, env=ENV).outcome, "ok")
            self.assertTrue(all(e["why"] == "ok" for e in fk.state.log))   # подпись сверена оракулом фейка
            del fk.state.objects[prefix + "sha256/" + sha(data)]
            r = attach.read_attachment(w.staged[0], c, env=ENV)
            self.seen("read", r.outcome, "storage-denied" if self.PROVIDER == "aws-no-list" else "object-missing")
            self.assertEqual(attach.probe_storage(c, env=ENV)["storage_probe_outcome"], "ok")   # канарейка под префиксом


# ---- находка 2 (MAJOR): атомарность перехода. Инвариант: переход по пути — перечтение, проверки, сеть, запись —
# сериализован межпроцессно; итог — законная цепочка переходов, изъятый объект не воскресает. Измерения: порядок
# старта (complete первым | withdraw первым) × блокировка (есть | снята — негативный контроль).
@per_provider
class Atomicity(Base):
    """Синхронизация — событиями (бэклог R2): фейк держит первый запрос процесса A (hold_next), пока тест не
    отпустит; процесс B печатает «flock-request» в момент запроса блокировки — тест читает эту строку, а не спит."""
    SCRIPT = ("import os, sys, types\nsys.path.insert(0, %r)\nimport attach.fsio as F\nimport attach.core as c\n"
              "_real = F.fcntl.flock\n"
              "def _flock(fd, op):\n    if op == F.fcntl.LOCK_EX:\n        print('flock-request', flush=True)\n"
              "    return _real(fd, op)\n"
              "if os.environ.get('ATTACH_NOLOCK'):\n"
              "    _flock = lambda fd, op: print('flock-request', flush=True) if op == F.fcntl.LOCK_EX else None\n"
              "F.fcntl = types.SimpleNamespace(flock=_flock, LOCK_EX=F.fcntl.LOCK_EX, LOCK_UN=F.fcntl.LOCK_UN)\n"
              "sys.exit(c.main(['--json'] + sys.argv[1:]))\n") % _BOT

    def _race(self, first, nolock):
        import threading
        with self.fake() as fk:
            data = os.urandom(THR + 300)
            p = self.write(data, cfg(fk), durable_queue=True, defer_upload=True).staged[0]
            dp = place(os.path.join(self.tmp, "q.bin"), data)
            cp = cfg_json(os.path.join(self.tmp, "cfg.json"), fk)
            env = dict(os.environ, **ENV)
            if nolock:
                env["ATTACH_NOLOCK"] = "1"
            cmd = {"complete": [sys.executable, "-c", self.SCRIPT, "--config", cp, "complete-pending", p, "--data", dp],
                   "withdraw": [sys.executable, "-c", self.SCRIPT, "--config", cp, "withdraw", p, "--reason", "secret",
                                "--withdraw-key-id-env", "WORKSHOP_S3_WITHDRAW_ACCESS_KEY_ID_DEV",
                                "--withdraw-secret-env", "WORKSHOP_S3_WITHDRAW_SECRET_ACCESS_KEY_DEV", "--confirm-withdraw"]}
            second = "withdraw" if first == "complete" else "complete"
            entered, release = threading.Event(), threading.Event()
            fk.state.hold_next = (entered, release)
            pa = subprocess.Popen(cmd[first], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pb = None
            try:
                self.assertTrue(entered.wait(30), "A не дошёл до сети")      # A держит блокировку и стоит в сети
                pb = subprocess.Popen(cmd[second], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(pb.stdout.readline().strip(), b"flock-request")  # B запросил блокировку при занятой
                if nolock:
                    ob = pb.communicate(timeout=60)                           # без блокировки B проходит целиком
            finally:
                release.set()
            oa = pa.communicate(timeout=60)
            if not nolock:
                ob = pb.communicate(timeout=60)
            rc = {first: pa.returncode, second: pb.returncode}
            final = read_bytes(p)
            log = [e["method"] for e in fk.state.log if e["method"] in ("PUT", "DELETE")]
            resurrected = "sha256/" + sha(data) in fk.state.objects
            put_after_delete = "DELETE" in log and "PUT" in log[log.index("DELETE"):]
            return rc, final, resurrected, put_after_delete, (oa, ob)

    def test_concurrent_complete_and_withdraw_serialized(self):
        for first in ("complete", "withdraw"):
            rc, final, resurrected, pad, outs = self._race(first, nolock=False)
            self.assertEqual(final, b"workshop-attachment-pointer 1\nstate withdrawn\nreason secret\n", (first, outs))
            self.assertFalse(resurrected, (first, outs))
            self.assertFalse(pad, first)
            self.assertEqual(rc["withdraw"], 0, outs)
            # второй получает либо законный переход (withdraw после stored), либо отказ перехода (complete после withdrawn)
            self.assertEqual(rc["complete"], 0 if first == "complete" else 2, outs)
            shutil.rmtree(self.rd)

    def test_negative_control_without_lock_violates(self):
        """Контроль: без блокировки та же гонка воскрешает изъятый объект — тест различает дефект."""
        rc, final, resurrected, pad, outs = self._race("complete", nolock=True)
        self.assertTrue(resurrected or pad or not final.endswith(b"state withdrawn\nreason secret\n"), outs)

    def test_lock_released_when_holder_killed(self):
        """Регрессия Codex R2 (lock_checks): держатель блокировки убит SIGKILL — ожидающие операции завершаются."""
        child = ("import sys\nsys.path.insert(0, sys.argv[1])\nimport attach.fsio as F\n"
                 "with F.CarrierDir(sys.argv[2], 'attachments', sys.argv[3], lock=True):\n"
                 "    print('held', flush=True)\n    sys.stdin.read()\n")
        with self.fake() as fk:
            d = os.urandom(THR + 301)
            p = self.write(d, cfg(fk), durable_queue=True, defer_upload=True).staged[0]
            cp = cfg_json(os.path.join(self.tmp, "cfg.json"), fk)
            dp = place(os.path.join(self.tmp, "q.bin"), d)
            holder = subprocess.Popen([sys.executable, "-c", child, _BOT, self.rd, RID], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE)
            self.assertEqual(holder.stdout.readline().strip(), b"held")
            w = subprocess.Popen([sys.executable, "-c", self.SCRIPT, "--config", cp, "complete-pending", p, "--data", dp],
                                 env=dict(os.environ, **ENV), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(w.stdout.readline().strip(), b"flock-request")
            self.assertEqual(fk.state.log, [])                     # пока держатель жив — ни одного запроса
            holder.kill()
            holder.communicate()
            out, err = w.communicate(timeout=60)
            self.assertEqual(w.returncode, 0, err)
            self.assertEqual(pointer_fields(read_bytes(p))["state"], "stored")


# ---- находка 3 (MAJOR): единый контроль записи в носитель. Инвариант: ни одна запись не попадает в путь под
# attachments/ мимо суда переходов; назначение и алиасы проверяются до открытия на запись. Измерения: назначение
# (сам носитель | symlink на него | hardlink | каталог-symlink | другой носитель | неверное имя под attachments/ |
# корень attachments/ | обычный новый | обычный существующий) × путь (CLI read --out | библиотека).
@per_provider
class WriteControl(Base):
    def _carriers(self, fk):
        data = os.urandom(THR + 400)
        x = self.write(data, cfg(fk), n=1).staged[0]
        g = self.write(b"git-bytes", cfg(fk), n=2).staged[0]
        return data, x, g

    def _alias_cases(self, x):
        ad = os.path.dirname(x)
        cases = {}
        cases["self"] = x
        link = os.path.join(self.tmp, "link.mp4")
        os.symlink(x, link)
        cases["symlink"] = link
        hl = os.path.join(self.tmp, "hard.mp4")
        os.link(x, hl)
        cases["hardlink"] = hl
        dl = os.path.join(self.tmp, "dlink")
        os.symlink(ad, dl)
        cases["dir-symlink"] = os.path.join(dl, os.path.basename(x))
        cases["other-carrier"] = os.path.join(ad, uid(9) + "-x.mp4")
        cases["reserved-bad-name"] = os.path.join(ad, "junk.bin")
        cases["reserved-root"] = os.path.join(os.path.dirname(ad), "junk.bin")
        return cases

    def test_read_out_alias_matrix_cli(self):
        with self.fake() as fk:
            data, x, g = self._carriers(fk)
            cp = cfg_json(os.path.join(self.tmp, "cfg.json"), fk)
            env = dict(os.environ, **ENV)
            for src in (x, g):
                before = {p: read_bytes(p) for p in (x, g)}
                for name, out in self._alias_cases(src).items():
                    existed = os.path.lexists(out)
                    r = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", cp, "read", src, "--out", out],
                                       cwd=_ROOT, env=env, capture_output=True)
                    self.assertEqual(r.returncode, 2, (name, r.stdout))
                    self.assertEqual({p: read_bytes(p) for p in (x, g)}, before, name)
                    self.assertEqual(os.path.lexists(out), existed, name)
                for name in ("link.mp4", "hard.mp4", "dlink"):
                    os.unlink(os.path.join(self.tmp, name))
                ok_new = os.path.join(self.tmp, "out-new.bin")
                ok_old = place(os.path.join(self.tmp, "out-old.bin"), b"old")
                for out in (ok_new, ok_old):
                    r = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", cp, "read", src, "--out", out],
                                       cwd=_ROOT, env=env, capture_output=True)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertEqual(read_bytes(out), data if src == x else b"git-bytes")
                    os.unlink(out)

    def test_library_save_refuses_same_matrix(self):
        with self.fake() as fk:
            data, x, g = self._carriers(fk)
            before = read_bytes(x)
            for name, out in self._alias_cases(x).items():
                with self.assertRaises(attach.AttachInputError, msg=name):
                    attach.save_bytes_outside_carriers(out, b"evil", source_path=x)
                self.assertEqual(read_bytes(x), before, name)

    def test_carrier_symlinks_refused_everywhere(self):
        with self.fake() as fk:
            outside = place(os.path.join(self.tmp, "outside.bin"), ptr_pending(b"q" * (THR + 1)))
            p = carrier_path(self.rd, 5)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.symlink(outside, p)
            for call in (lambda: attach.complete_pending(p, b"q" * (THR + 1), cfg(fk), env=ENV),
                         lambda: attach.fail_pending(p),
                         lambda: attach.withdraw(p, "secret", cfg(fk), WCREDS, env=ENV),
                         lambda: attach.late_save(p, b"q", cfg(fk), env=ENV),
                         lambda: self.write(b"q" * (THR + 1), cfg(fk), n=5),
                         lambda: attach.read_attachment(p, cfg(fk), env=ENV)):
                with self.assertRaises(attach.AttachInputError):
                    call()
            self.assertEqual(read_bytes(outside), ptr_pending(b"q" * (THR + 1)))
            # каталог attachments/<record-id>/ — symlink наружу
            rd2 = os.path.join(self.tmp, "t2")
            os.makedirs(os.path.join(rd2, "attachments"))
            out_dir = os.path.join(self.tmp, "elsewhere")
            os.makedirs(out_dir)
            os.symlink(out_dir, os.path.join(rd2, "attachments", RID))
            with self.assertRaises(attach.AttachInputError):
                attach.write_attachment(rd2, RID, b"x", ext="png", config=cfg(fk), uuid=uid(6), env=ENV)
            self.assertEqual(os.listdir(out_dir), [])
            self.assertEqual(fk.mutations(), [])

    def test_hardlinked_carrier_other_link_untouched(self):
        with self.fake() as fk:
            d = os.urandom(THR + 401)
            p = self.write(d, cfg(fk), durable_queue=True, defer_upload=True).staged[0]
            alias = os.path.join(self.tmp, "alias.ptr")
            os.link(p, alias)
            before = read_bytes(p)
            r = attach.complete_pending(p, d, cfg(fk), env=ENV)
            self.seen("write", r.outcome, "uploaded")
            self.assertEqual(read_bytes(alias), before)                        # замена записи каталога, не inode
            self.assertEqual(pointer_fields(read_bytes(p))["state"], "stored")


# ---- находка 4 (MAJOR): проверки до сети. Инвариант: существующий носитель, sha256/size и допустимость операции
# судятся ДО любого PUT/DELETE; отказ — ноль изменяющих запросов. Измерения: носитель (git | stored | pending |
# unsaved с sha | unsaved только size | unsaved без size | withdrawn | invalid | lfs) × вход (те же байты | чужие той
# же длины | чужие иной длины | без байт) × провайдер.
@per_provider
class PreNetworkChecks(Base):
    def test_existing_carrier_matrix(self):
        d = os.urandom(THR + 500)
        same_len = bytes(b ^ 0x33 for b in d)
        other_len = d + b"!"
        s = sha(d)
        carriers = {
            "git": d,
            "stored": ptr_stored(d),
            "pending": ptr_pending(d),
            "unsaved-sha": P.render("unsaved", {"sha256": s, "size": str(len(d)), "media-type": "video/mp4",
                                                "reason": "no-storage", "source": SRC}),
            "unsaved-size": P.render("unsaved", {"size": str(len(d)), "reason": "source-refused", "source": SRC}),
            "unsaved-bare": P.render("unsaved", {"reason": "source-refused", "source": SRC}),
            "withdrawn": P.render("withdrawn", {"reason": "secret"}),
            "invalid": b"workshop-attachment-pointer 1\nstate lost\n",
            "lfs": b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n",
        }
        E = attach.AttachInputError
        # (носитель, вход) -> (исход | класс исключения, состояние после, изменяющих запросов)
        expect = {
            ("git", "same"): (None, "git", 0), ("git", "same_len"): ("bytes-mismatch", "git", 0),
            ("git", "other_len"): ("bytes-mismatch", "git", 0), ("git", "none"): (E, "git", 0),
            ("stored", "same"): (None, "stored", 0), ("stored", "same_len"): ("bytes-mismatch", "stored", 0),
            ("stored", "other_len"): ("bytes-mismatch", "stored", 0), ("stored", "none"): (E, "stored", 0),
            ("pending", "same"): ("uploaded", "stored", 1), ("pending", "same_len"): ("bytes-mismatch", "pending", 0),
            ("pending", "other_len"): ("bytes-mismatch", "pending", 0), ("pending", "none"): (E, "pending", 0),
            ("unsaved-sha", "same"): ("uploaded", "stored", 1),
            ("unsaved-sha", "same_len"): ("bytes-mismatch", "unsaved", 0),
            ("unsaved-sha", "other_len"): ("bytes-mismatch", "unsaved", 0), ("unsaved-sha", "none"): (E, "unsaved", 0),
            ("unsaved-size", "same"): ("uploaded", "stored", 1),
            ("unsaved-size", "same_len"): ("uploaded", "stored", 1),       # sha не записан — сверить нечем (цена нормы)
            ("unsaved-size", "other_len"): ("bytes-mismatch", "unsaved", 0), ("unsaved-size", "none"): (E, "unsaved", 0),
            ("unsaved-bare", "same"): ("uploaded", "stored", 1), ("unsaved-bare", "same_len"): ("uploaded", "stored", 1),
            ("unsaved-bare", "other_len"): ("uploaded", "stored", 1), ("unsaved-bare", "none"): (E, "unsaved", 0),
        }
        for k in ("withdrawn", "invalid", "lfs"):
            for i in ("same", "same_len", "other_len", "none"):
                expect[(k, i)] = (E, None, 0)
        inputs = {"same": d, "same_len": same_len, "other_len": other_len, "none": None}
        self.assertEqual(len(expect), len(carriers) * len(inputs))
        with self.fake() as fk:
            for (ck, ik), (want, state_after, nmut) in sorted(expect.items()):
                shutil.rmtree(self.rd, ignore_errors=True)
                for key in list(objs(fk)):
                    del fk.state.objects[key]
                p = place(carrier_path(self.rd, 1), carriers[ck])
                m0 = len(fk.mutations())
                if want is E:
                    with self.assertRaises(E, msg=(ck, ik)):
                        self.write(inputs[ik], cfg(fk))
                else:
                    w = self.write(inputs[ik], cfg(fk))
                    self.assertEqual(w.outcome, want, (ck, ik, w))
                    if want is not None:
                        self.seen("write", w.outcome, want)
                    self.assertEqual(w.staged, [p])
                self.assertEqual(len(fk.mutations()) - m0, nmut, (ck, ik))
                after = P.classify(read_bytes(p))
                if state_after is not None:
                    self.assertEqual(P.state_of(after), state_after, (ck, ik))
                if nmut == 0:
                    self.assertEqual(read_bytes(p), carriers[ck], (ck, ik))
                else:
                    self.assertTrue(P.check_transition(carriers[ck], read_bytes(p))[0], (ck, ik))

    def test_public_ops_refuse_before_network(self):
        with self.fake() as fk:
            d = os.urandom(THR + 501)
            p = place(carrier_path(self.rd, 2), ptr_pending(d))
            m0 = len(fk.mutations())
            self.seen("write", attach.complete_pending(p, d + b"x", cfg(fk), env=ENV).outcome, "bytes-mismatch")
            u = place(carrier_path(self.rd, 3), P.render("unsaved", {"sha256": sha(d), "size": str(len(d)),
                                                                     "reason": "upload-failed", "source": SRC}))
            self.seen("write", attach.late_save(u, d[:-1], cfg(fk), env=ENV).outcome, "bytes-mismatch")
            for bad in (b"workshop-attachment-pointer 1\nstate lost\n", P.render("withdrawn", {"reason": "erasure"})):
                place(p, bad)
                with self.assertRaises(attach.AttachInputError):
                    attach.withdraw(p, "secret", cfg(fk), WCREDS, env=ENV)
                with self.assertRaises(attach.AttachInputError):
                    attach.complete_pending(p, d, cfg(fk), env=ENV)
            self.assertEqual(len(fk.mutations()) - m0, 0)


# ---- находка 5 (MAJOR): конфиг по норме. Инвариант: отсутствие обязательного факта привязки — исход нормы
# «хранилище не настроено» с громкой деталью; присутствующий факт неверного типа — ConfigError. Измерения:
# подмножество отсутствующих {endpoint, bucket, credentials} (7 непустых) × форма отсутствия (ключа нет | "" |
# null) × операция (маршрут | запись | чтение).
class ConfigNorm(Base):
    FULL = {"endpoint": "https://s3.example.org", "bucket": "b",
            "credentials": {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                            "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"}}

    def test_partial_binding_matrix(self):
        import itertools
        req = ("endpoint", "bucket", "credentials")
        stored_example = example_files("02-stored")[0]
        n = 0
        for k in range(1, 4):
            for missing in itertools.combinations(req, k):
                for form in ("drop", "null"):
                    st = dict(self.FULL)
                    for m in missing:
                        if form == "drop":
                            st.pop(m)
                        else:
                            st[m] = None
                    c = attach.load_config({"git_threshold_bytes": THR, "storage": st})
                    self.assertIsNone(c.binding)
                    self.assertEqual(c.binding_missing, tuple("storage." + m for m in req if m in missing))
                    r = attach.route(THR + 1, c, env=ENV)
                    self.assertEqual((r.target, r.reason), ("unsaved", "no-storage"))
                    for m in missing:
                        self.assertIn("storage." + m, r.detail)
                    shutil.rmtree(self.rd, ignore_errors=True)
                    w = self.write(os.urandom(THR + 1), c)
                    self.assertEqual((w.state, w.reason), ("unsaved", "no-storage"))
                    self.assertIn("binding-incomplete", w.detail)
                    rr = attach.read_attachment(stored_example, c, env=ENV)
                    self.seen("read", rr.outcome, "storage-not-configured")
                    self.assertIn("binding-incomplete", rr.detail)
                    n += 1
        self.assertEqual(n, 14)
        c = attach.load_config({"storage": {}})
        self.assertEqual(c.binding_missing, ("storage.endpoint", "storage.bucket", "storage.credentials"))

    def test_present_wrong_type_is_config_error_matrix(self):
        bad = {"endpoint": [1, b"https://x", "ftp://x"], "bucket": [1, "a/b"], "region": [1, "ru central"],
               "key_prefix": [1, "a\x00b", "a\x7fb", "x" * 600], "credentials": ["NAME", {"access_key_id": "a"}],
               "addressing": ["dns", 1], "timeout_s": [0, -1, "5", True], "deadline_s": [0],
               "allow_insecure_http": ["yes"], "list_permission": [1, "true"], "canary_key": [1, "c\x01"]}
        for fact, values in bad.items():
            for v in values:
                st = dict(self.FULL)
                st[fact] = v
                with self.assertRaises(attach.ConfigError, msg=(fact, v)):
                    attach.load_config({"storage": st})
        for prefix in ("команда/", "", "a b/+%/"):
            self.assertEqual(attach.load_config({"storage": dict(self.FULL, key_prefix=prefix)}).binding.key_prefix, prefix)


# ---- пре-флайт §2.3 + секреты: ошибка разбора endpoint. Инвариант: любой разбор endpoint, сорвавшийся на
# порту/схеме/хосте/пути, — ConfigError (rc 3) без отражения входа. Измерения: место вставки значения ×
# путь (библиотека | CLI).
class EndpointNoReflection(Base):
    S = "synthEPSECRET-9x7Qw2Er4Ty6"

    def eps(self):
        s = self.S
        return ["https://s3.example.org:%s" % s, "https://s3.example.org:%s/" % s, "https://[%s" % s,
                "https://%s@s3.example.org" % s, "https://s3.example.org/%s" % s, "https://s3.example.org?%s" % s,
                "https://s3.example.org#%s" % s, "%s://s3.example.org" % s, "https:// %s" % s,
                "https://s3.example.org:99999%s" % s[:0] + "9", "http://%s.example.org" % s, "https://%s" % ("[" + s + "]")]

    def test_library(self):
        for ep in self.eps():
            with self.assertRaises(attach.ConfigError, msg=ep) as cm:
                attach.load_config({"storage": dict(ConfigNorm.FULL, endpoint=ep)})
            e = cm.exception
            text = str(e) + repr(e) + "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.assertNotIn(self.S, text, ep)

    def test_cli_rc3_without_reflection(self):
        f = example_files("01-git-bytes")[0]
        for i, ep in enumerate(self.eps()):
            cp = os.path.join(self.tmp, "c%d.json" % i)
            with open(cp, "w", encoding="utf-8") as fh:
                json.dump({"storage": dict(ConfigNorm.FULL, endpoint=ep)}, fh)
            r = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", cp, "read", f], cwd=_ROOT,
                               capture_output=True)
            self.assertEqual(r.returncode, 3, (ep, r.stdout, r.stderr))
            self.assertEqual(json.loads(r.stdout)["outcome"], "adapter-fault")
            self.assertNotIn(self.S.encode(), r.stdout + r.stderr, ep)



# ============================================================================================== R2 (протокол Codex R2)
import threading  # noqa: E402
import attach.fsio as FS  # noqa: E402

PREFIX_HEX = "93c81fed406b2a7950de41bfec803729"   # законный 128-битный префикс и законный токен XML <Code> (Codex R2)


class _Hook(object):
    """Одноразовый перехват attach.fsio.TEST_HOOK на заданной стадии."""

    def __init__(self, stage, fn):
        self.stage, self.fn, self.fired = stage, fn, False

    def __call__(self, stage, **ctx):
        if stage == self.stage and not self.fired:
            self.fired = True
            self.fn(**ctx)

    def __enter__(self):
        FS.TEST_HOOK = self
        return self

    def __exit__(self, *a):
        FS.TEST_HOOK = None


# ---- класс R2-1: доступность одного объекта никогда не доказывает отсутствие другого. Измерения: провайдер ×
# состояние (stored | pending) × операция (read | verify) × канарейка (доступна | нет) × объект (есть | нет) ×
# list_permission.
@per_provider
class PolicyDeny(Base):
    def test_target_policy_403_is_denied_with_canary_available(self):
        with self.fake() as fk:
            d = os.urandom(THR + 600)
            c = cfg(fk)
            p = self.write(d, c).staged[0]
            key = "sha256/" + sha(d)
            fk.state.deny_keys.add(key)                       # объект ЕСТЬ, политика на конкретный ключ
            self.assertEqual(attach.probe_storage(c, env=ENV)["storage_probe_outcome"], "ok")   # канарейка доступна
            for state, content in (("stored", ptr_stored(d)), ("pending", ptr_pending(d))):
                place(p, content)
                for lp in (False, True):
                    for fn in (attach.read_attachment, attach.verify):
                        r = fn(p, cfg(fk, list_permission=lp), env=ENV)
                        self.seen("read", r.outcome, "storage-denied")
                        self.assertIsNone(r.data)
                        self.assertEqual(r.detail, "http 403 AccessDenied" if lp else "ambiguous-403-no-list")
            # тот же 403 на ОТСУТСТВУЮЩИЙ объект — тоже отказ, а не «отсутствует» (кроме Yandex, где отсутствие — 404)
            del fk.state.objects[key]
            place(p, ptr_stored(d))
            r = attach.read_attachment(p, c, env=ENV)
            self.seen("read", r.outcome, "object-missing" if self.PROVIDER == "yandex" else "storage-denied")

    def test_canary_never_consulted_by_read(self):
        with self.fake() as fk:
            d = os.urandom(THR + 601)
            p = self.write(d, cfg(fk)).staged[0]
            for k in list(objs(fk)):
                del fk.state.objects[k]
            n0 = len(fk.state.log)
            attach.read_attachment(p, cfg(fk), env=ENV)
            attach.verify(p, cfg(fk), env=ENV)
            self.assertTrue(all(not (e["key"] or "").endswith(CANARY) for e in fk.state.log[n0:]))


# ---- класс R2-2: проверенный объект ФС и изменяемый — один и тот же. Измерения: путь записи (новая запись, повтор,
# complete_pending, fail_pending, late_save, withdraw) × подменяемый компонент (конечный файл → symlink;
# <record-id>/ → rename + symlink; attachments/ → rename + symlink; корень записи → rename + symlink) в момент между
# открытием цепочки и записью; вне носителей — save_bytes_outside_carriers × (конечный файл → symlink; каталог
# назначения → rename + symlink на каталог носителя).
class FsToctou(Base):
    OPS = ("fresh", "retry", "complete", "fail", "late", "withdraw")
    SWAPS = ("leaf", "rid-dir", "attachments-dir", "record-dir")

    def _setup(self, fk, op, d):
        c = cfg(fk)
        if op == "fresh":
            return None, (lambda: self.write(d, c, n=7))
        if op in ("retry", "complete", "fail"):
            p = self.write(d, c, n=7, durable_queue=True, defer_upload=True).staged[0]
            call = {"retry": lambda: self.write(d, c, n=7),
                    "complete": lambda: attach.complete_pending(p, d, c, env=ENV),
                    "fail": lambda: attach.fail_pending(p)}[op]
            return p, call
        if op == "late":
            p = self.write(d, cfg(None), n=7).staged[0]
            return p, (lambda: attach.late_save(p, d, c, env=ENV))
        p = self.write(d, c, n=7).staged[0]
        return p, (lambda: attach.withdraw(p, "secret", c, WCREDS, env=ENV))

    def _evil_tree(self, d):
        evil = os.path.join(self.tmp, "evil")
        bait = place(os.path.join(evil, "tickets", "attachments", RID, uid(7) + "-clip.mp4"), ptr_pending(d))
        return evil, bait

    def _snapshot(self, root):
        out = {}
        for r, ds, fs in os.walk(root):
            for f in fs:
                out[os.path.relpath(os.path.join(r, f), root)] = read_bytes(os.path.join(r, f))
        return out

    def _swap(self, swap, evil, bait):
        rd = self.rd
        att = os.path.join(rd, "attachments")
        ridd = os.path.join(att, RID)
        leaf = os.path.join(ridd, uid(7) + "-clip.mp4")
        if swap == "leaf":
            if os.path.lexists(leaf):
                os.rename(leaf, leaf + ".parked")
            os.symlink(bait, leaf)
        elif swap == "rid-dir":
            os.makedirs(ridd, exist_ok=True)
            os.rename(ridd, ridd + "-parked")
            os.symlink(os.path.dirname(bait), ridd)
        elif swap == "attachments-dir":
            os.makedirs(ridd, exist_ok=True)
            os.rename(att, att + "-parked")
            os.symlink(os.path.join(evil, "tickets", "attachments"), att)
        else:
            os.rename(rd, rd + "-parked")
            os.symlink(os.path.join(evil, "tickets"), rd)

    def test_swap_matrix_all_write_paths(self):
        n = 0
        for op in self.OPS:
            for swap in self.SWAPS:
                shutil.rmtree(self.tmp)
                os.makedirs(self.tmp)
                with self.fake() as fk:
                    d = os.urandom(THR + 700)
                    p, call = self._setup(fk, op, d)
                    evil, bait = self._evil_tree(d)
                    before = self._snapshot(evil)
                    m0 = len(fk.mutations())
                    with _Hook("carrier-opened", lambda **k: self._swap(swap, evil, bait)) as h:
                        try:
                            call()
                            err = None
                        except attach.AttachInputError as e:
                            err = e
                    self.assertTrue(h.fired, (op, swap))
                    self.assertEqual(self._snapshot(evil), before, (op, swap))       # подменённая цель не тронута
                    if swap == "leaf":
                        self.assertIsNotNone(err, (op, swap))                         # symlink носителя — отказ
                        self.assertEqual(len(fk.mutations()) - m0, 0, (op, swap))     # и до сети
                    else:
                        # запись ушла в ИСХОДНЫЙ (теперь переименованный) каталог — тот, что был проверен
                        self.assertIsNone(err, (op, swap, err))
                        parked = {"rid-dir": os.path.join(self.rd, "attachments", RID + "-parked"),
                                  "attachments-dir": os.path.join(self.rd, "attachments-parked", RID),
                                  "record-dir": os.path.join(self.rd + "-parked", "attachments", RID)}[swap]
                        got = read_bytes(os.path.join(parked, uid(7) + "-clip.mp4"))
                        self.assertIn(P.classify(got).kind, ("pointer", "bytes"), (op, swap))
                    n += 1
        self.assertEqual(n, len(self.OPS) * len(self.SWAPS))

    def test_static_symlink_components_refused(self):
        """Компонент уже symlink ДО операции (attachments/ или <record-id>/) — отказ на открытии цепочки
        (O_NOFOLLOW), цель symlink не тронута, сети нет. Корень записи — доверенный путь вызывающего (realpath)."""
        for comp in ("attachments-dir", "rid-dir"):
            for op in self.OPS:
                shutil.rmtree(self.tmp)
                os.makedirs(self.tmp)
                with self.fake() as fk:
                    d = os.urandom(THR + 702)
                    p, call = self._setup(fk, op, d)
                    evil, bait = self._evil_tree(d)
                    self._swap(comp, evil, bait)
                    before = self._snapshot(evil)
                    m0 = len(fk.mutations())
                    with self.assertRaises(attach.AttachInputError, msg=(comp, op)):
                        call()
                    self.assertEqual(self._snapshot(evil), before, (comp, op))
                    self.assertEqual(len(fk.mutations()) - m0, 0, (comp, op))
                    for fn in (attach.read_attachment, attach.verify):
                        with self.assertRaises(attach.AttachInputError):
                            fn(os.path.join(self.rd, "attachments", RID, uid(7) + "-clip.mp4"), cfg(fk), env=ENV)

    def test_out_swap_matrix(self):
        """Регрессия Codex R2 out_races: подмена конечного файла и каталога назначения между проверкой и записью."""
        for swap in ("none", "leaf-symlink", "parent-symlink", "parent-rename-real-dir"):
            shutil.rmtree(self.tmp)
            os.makedirs(self.tmp)
            d = os.urandom(THR + 701)
            carrier = place(carrier_path(self.rd, 1), ptr_stored(d))
            old = read_bytes(carrier)
            outdir = os.path.join(self.tmp, "export")
            os.mkdir(outdir)
            out = os.path.join(outdir, os.path.basename(carrier))

            def act(**k):
                if swap == "leaf-symlink":
                    os.symlink(carrier, out)
                elif swap == "parent-symlink":
                    os.rename(outdir, outdir + "-parked")
                    os.symlink(os.path.dirname(carrier), outdir)
                elif swap == "parent-rename-real-dir":
                    os.rename(outdir, outdir + "-parked")
                    os.mkdir(outdir)
            with _Hook("out-dir-opened", act):
                try:
                    attach.save_bytes_outside_carriers(out, b"replacement payload", source_path=carrier)
                    err = None
                except attach.AttachInputError as e:
                    err = e
            self.assertEqual(read_bytes(carrier), old, swap)                         # stored → git не случился
            if swap == "leaf-symlink":
                self.assertIsNotNone(err)
            elif swap in ("parent-symlink", "parent-rename-real-dir"):
                self.assertIsNone(err)
                self.assertEqual(read_bytes(os.path.join(outdir + "-parked", os.path.basename(carrier))),
                                 b"replacement payload")
            else:
                self.assertEqual(read_bytes(out), b"replacement payload")


# ---- класс R2-3: классификация и выдача байт — из одного открытого файла. Измерения: состояние при открытии
# (git-байты) × законный переход по пути между классификацией и дочитыванием (withdraw | замена другим
# содержимым) × read | verify. Синхронизация — событиями.
class ReadSnapshot(Base):
    def _race(self, mutate, keep_fn, n=1):
        raw = os.urandom(5000) + b"tail"          # длиннее max_bytes+1: дочитывание после классификации обязательно
        p = self.write(raw, cfg(None, threshold=10000), n=n).staged[0]
        classified, mutated = threading.Event(), threading.Event()
        res = {}

        def hook(**k):
            classified.set()
            self.assertTrue(mutated.wait(30))

        def reader():
            res["r"] = keep_fn(p, cfg(None), env={})
        with _Hook("read-classified", hook):
            t = threading.Thread(target=reader)
            t.start()
            self.assertTrue(classified.wait(30))
            mutate(p)
            mutated.set()
            t.join(30)
        return raw, p, res["r"]

    def test_read_vs_withdraw(self):
        raw, p, r = self._race(lambda p: attach.withdraw(p, "secret", cfg(None), WCREDS, env={}), attach.read_attachment)
        self.seen("read", r.outcome, "in-git")
        self.assertEqual(r.data, raw)                                  # не указатель withdrawn
        self.assertEqual(P.state_of(P.classify(read_bytes(p))), "withdrawn")

    def test_read_vs_foreign_replace_and_verify(self):
        def replace(p):
            os.rename(p, p + ".old")
            place(p, ptr_stored(b"other"))
        raw, p, r = self._race(replace, attach.read_attachment)
        self.assertEqual((r.outcome, r.data), ("in-git", raw))
        raw, p, r = self._race(lambda p: attach.withdraw(p, "erasure", cfg(None), WCREDS, env={}), attach.verify, n=2)
        self.assertEqual((r.outcome, r.data), ("in-git", None))


# ---- класс R2-4: ни одна строка хранилища не выходит наружу как есть. Измерения: значение (ключ доступа, секрет,
# ключ изъятия, секрет изъятия, префикс; префикс в форме XML-кода) × место отражения (<Code> | <Message>) × статус
# (403 | 503) × поверхность (Resp.code/detail/repr; ReadResult; WriteResult; withdraw; probe; CLI; исключения; логи)
# × слой защиты (оба | только перечень кодов | только маскирование).
@per_provider
class ServerStrings(Base):
    VALUES = SYNTH + (PREFIX_HEX,)

    def _surfaces(self, fk, c, p, d, wc_env, with_withdraw=True):
        out = []
        b = c.binding
        for creds in ((AKID, SECRET), (WAKID, WSECRET)) if with_withdraw else ((AKID, SECRET),):
            cl = attach._client(b, attach_s3.Credentials(*creds))
            for r in (cl.get(b.key_prefix + "sha256/" + sha(d), len(d)), cl.head("x"), cl.put("x", b"b"), cl.delete("x")):
                out += [repr(r), str(r.code), str(r.detail)]
        for fn in (attach.read_attachment, attach.verify):
            r = fn(p, c, env=ENV)
            out += [repr(r), json.dumps(r.as_dict(), ensure_ascii=False)]
        out.append(repr(attach.probe_storage(c, env=ENV)))
        w = attach.write_attachment(os.path.join(self.tmp, "w"), RID, os.urandom(THR + 3), ext="bin", config=c,
                                    uuid=uid(31), source=SRC, env=ENV)
        out.append(repr(w))
        if with_withdraw:
            out.append(repr(attach.withdraw(p, "secret", c, WCREDS, env=ENV)))
        return out

    def _run(self, prefix, where, status, layers=("codes", "mask"), values=None, with_withdraw=True):
        with self.fake(prefix=prefix) as fk:
            c = cfg(fk, key_prefix=prefix)
            d = os.urandom(THR + 800)
            p = self.write(d, c).staged[0]
            orig_code, orig_client = attach_s3.safe_code, attach._client
            if "codes" not in layers:     # слой 1 снят: сырой код сервера
                attach_s3.safe_code = lambda body: (attach_s3._CODE_RE.search(body or b"").group(1).decode("utf-8", "replace")
                                                    if attach_s3._CODE_RE.search(body or b"") else None)
            if "mask" not in layers:      # слой 2 снят: клиент без маскирования

                def nomask(*a, **k):
                    cl = orig_client(*a, **k)
                    cl._mask = lambda text: text
                    return cl
                attach._client = nomask
            blobs = []
            try:
                for v in (values or self.VALUES):
                    fk.state.echo = (v, "ok") if where == "code" else ("AccessDenied", v)
                    fk.state.echo_status = status
                    blobs += self._surfaces(fk, c, p, d, ENV, with_withdraw)
                    place(p, ptr_stored(d))
            finally:
                attach_s3.safe_code, attach._client = orig_code, orig_client
                fk.state.echo = None
            return blobs

    def _leaks(self, blobs, values):
        return sorted({v for v in values for b in blobs if v in b})

    def test_closed_code_list_unit(self):
        self.assertEqual(attach_s3.safe_code(b"<Error><Code>AccessDenied</Code></Error>"), "AccessDenied")
        for raw in (SECRET.encode(), PREFIX_HEX.encode(), b"Access Denied", b"x" * 100, "Ключ".encode()):
            self.assertEqual(attach_s3.safe_code(b"<Code>" + raw + b"</Code>"), attach_s3.UNRECOGNIZED)
        self.assertIsNone(attach_s3.safe_code(b"<Message>" + SECRET.encode() + b"</Message>"))

    def test_both_layers_matrix(self):
        for where in ("code", "message"):
            for status in (403, 503):
                blobs = self._run(PREFIX, where, status) + self._run(PREFIX_HEX, where, status)
                self.assertEqual(self._leaks(blobs, self.VALUES), [], (where, status))

    def test_each_layer_alone_holds(self):
        """Слои проверяются по отдельности: снятие ЛЮБОГО одного не открывает утечку своих значений клиента
        (ключ доступа, секрет, префикс). Это и делает мутацию «снять маскирование» наблюдаемой здесь — вместе
        с прямым тестом маскирования в Secrets."""
        own = (AKID, SECRET, PREFIX_HEX)   # значения, которые клиент писателя знает и обязан маскировать сам
        for layers in (("codes",), ("mask",)):
            blobs = self._run(PREFIX_HEX, "code", 503, layers=layers, values=own, with_withdraw=False)
            self.assertEqual(self._leaks([b for b in blobs], own), [], layers)

    def test_negative_control_both_layers_off_leaks(self):
        blobs = self._run(PREFIX_HEX, "code", 503, layers=(), values=(PREFIX_HEX,), with_withdraw=False)
        self.assertIn(PREFIX_HEX, self._leaks(blobs, (PREFIX_HEX,)))

    def test_cli_surfaces(self):
        with self.fake(prefix=PREFIX_HEX) as fk:
            c = cfg(fk, key_prefix=PREFIX_HEX)
            d = os.urandom(THR + 801)
            p = self.write(d, c).staged[0]
            cp = cfg_json(os.path.join(self.tmp, "cfg.json"), fk, key_prefix=PREFIX_HEX)
            dp = place(os.path.join(self.tmp, "d.bin"), os.urandom(THR + 802))
            env = dict(os.environ, **ENV)
            blobs = []
            for v in self.VALUES:
                for where in ("code", "message"):
                    fk.state.echo = (v, "m") if where == "code" else ("SlowDown", v)
                    for args in (["read", p], ["verify", p], ["probe"],
                                 ["write", "--record-dir", os.path.join(self.tmp, "cw"), "--record-id", RID, "--ext",
                                  "bin", "--data", dp, "--source", SRC, "--uuid", uid(40)]):
                        r = subprocess.run([sys.executable, "-m", "bot.attach", "--json", "--config", cp] + args, cwd=_ROOT,
                                           env=env, capture_output=True)
                        blobs.append((r.stdout + r.stderr).decode("utf-8", "replace"))
            fk.state.echo = None
            self.assertEqual(self._leaks(blobs, self.VALUES), [])


# ---- класс R2-5: тип — до умолчания; отсутствие факта ≠ ложное значение другого типа. Измерения: каждый факт
# схемы × {отсутствует, null, False, 0, "", [], {}, неверный тип}.
class ConfigTypeMatrix(Base):
    PROBES = ("absent", "null", False, 0, "", [], {}, "wrong")
    WRONG = {"git_threshold_bytes": "8000000", "storage.endpoint": 5, "storage.region": 1, "storage.bucket": 1,
             "storage.key_prefix": 1, "storage.credentials": "NAME", "storage.addressing": 1, "storage.timeout_s": "5",
             "storage.deadline_s": "5", "storage.allow_insecure_http": "true", "storage.list_permission": "true",
             "storage.canary_key": 1}
    # что ДОПУСТИМО из проб (остальное — ConfigError); отсутствие/null — умолчание или «не настроено»
    VALID = {"git_threshold_bytes": {0}, "storage.key_prefix": {""},
             "storage.allow_insecure_http": {False}, "storage.list_permission": {False}}
    DEFAULTS = {"git_threshold_bytes": ("thr", 8000000), "storage.region": ("region", "us-east-1"),
                "storage.key_prefix": ("key_prefix", ""), "storage.addressing": ("addressing", "path"),
                "storage.timeout_s": ("timeout_s", 30), "storage.deadline_s": ("deadline_s", 600),
                "storage.allow_insecure_http": ("allow_insecure_http", False),
                "storage.list_permission": ("list_permission", False), "storage.canary_key": ("canary_key", None)}

    def test_matrix(self):
        facts = list(attach._SCHEMA)
        self.assertEqual(set(facts), set(self.WRONG))
        n = 0
        for fact in facts:
            for probe in self.PROBES:
                m = {"storage": dict(ConfigNorm.FULL)}
                if fact == "git_threshold_bytes":
                    tgt, k = m, fact
                else:
                    tgt, k = m["storage"], fact.split(".", 1)[1]
                tgt.pop(k, None)
                if probe == "null":
                    tgt[k] = None
                elif probe == "wrong":
                    tgt[k] = self.WRONG[fact]
                elif probe != "absent":
                    tgt[k] = probe
                n += 1
                if probe in ("absent", "null"):
                    c = attach.load_config(m)
                    if fact in ("storage.endpoint", "storage.bucket", "storage.credentials"):
                        self.assertIsNone(c.binding, fact)
                        self.assertEqual(c.binding_missing, (fact,))
                    else:
                        attr, want = self.DEFAULTS[fact]
                        got = c.git_threshold_bytes if attr == "thr" else getattr(c.binding, attr)
                        self.assertEqual(got, want, (fact, probe))
                    continue
                valid = any(probe == v and type(probe) is type(v) for v in self.VALID.get(fact, ()))
                if valid:
                    c = attach.load_config(m)
                    got = c.git_threshold_bytes if fact == "git_threshold_bytes" else getattr(c.binding, k)
                    self.assertEqual((got, type(got)), (probe, type(probe)), (fact, probe))
                else:
                    with self.assertRaises(attach.ConfigError, msg=(fact, probe)):
                        attach.load_config(m)
        self.assertEqual(n, len(facts) * len(self.PROBES))


# ---- регрессии Codex R2 (adversarial.py) — дословные входы адверсария
class CodexR2Regressions(Base):
    def test_policies(self):
        for provider in PROVIDERS:
            with make_fake(provider) as fk:
                d = b"policy payload" * 100
                c = cfg(fk, list_permission=False)
                p = attach.write_attachment(self.rd, RID, d, ext="mp4", uuid=uid(1), slug="clip", source=SRC, config=c,
                                            env=ENV).staged[0]
                fk.state.deny_keys.add("sha256/" + sha(d))
                for state in ("stored", "pending"):
                    place(p, ptr_stored(d) if state == "stored" else ptr_pending(d))
                    for fn in (attach.read_attachment, attach.verify):
                        self.assertEqual(fn(p, c, env=ENV).outcome, "storage-denied", (provider, state))
            shutil.rmtree(self.rd)

    def test_config_edges(self):
        for v in (False, 0, [], {}, True, 1):
            with self.assertRaises(attach.ConfigError, msg=repr(v)):
                attach.load_config({"storage": dict(ConfigNorm.FULL, key_prefix=v)})
        self.assertEqual(attach.load_config({"storage": ConfigNorm.FULL}).binding.key_prefix, "")   # пустой — значение нормы

    def test_secret_echo_prefix_hex(self):
        with make_fake("yandex", prefix=PREFIX_HEX) as fk:
            d = b"secret echo payload" * 100
            c = cfg(fk, key_prefix=PREFIX_HEX)
            p = attach.write_attachment(self.rd, RID, d, ext="mp4", uuid=uid(1), slug="clip", source=SRC, config=c,
                                        env=ENV).staged[0]
            fk.state.echo = (PREFIX_HEX, None)
            fk.state.echo_status = 503
            client = attach._client(c.binding, attach._creds(c.binding.cred_names, ENV))
            vals = [repr(client.get(PREFIX_HEX + "sha256/" + sha(d), len(d))), repr(c.binding)]
            vals += [repr(attach.read_attachment(p, c, env=ENV)), repr(attach.verify(p, c, env=ENV))]
            vals.append(repr(attach.write_attachment(self.rd, RID, d, ext="mp4", uuid=uid(2), slug="clip", source=SRC,
                                                     config=c, env=ENV)))
            vals.append(repr(attach.withdraw(p, "secret", c, WCREDS, env=ENV)))
            fk.state.echo = None
            self.assertFalse([v for v in vals if PREFIX_HEX in v])

    def test_read_versus_withdraw_between_opens(self):
        raw = b"git bytes before withdrawal"
        p = attach.write_attachment(self.rd, RID, raw, ext="mp4", uuid=uid(1), slug="clip", source=SRC,
                                    config=cfg(None), env=ENV).staged[0]

        def between(**k):
            attach.withdraw(p, "secret", cfg(None), WCREDS, env=ENV)
        with _Hook("read-classified", between):
            r = attach.read_attachment(p, cfg(None))
        self.assertEqual((r.outcome, r.data), ("in-git", raw))



# ============================================================================================== R3 (протокол Fable R3)
# Класс: обходчик attach.fsio обязан разрешать путь носителя так же, как ядро, по трём измерениям — права предков,
# тип файла, форма пути — и при этом держать защиту R2-2 от подмены. Регрессии — порт adversarial-r3.py (S1–S6, S8).
import socket as _socket  # noqa: E402
import stat as _stat  # noqa: E402

CLI_TIMEOUT = 20


def _cli(args, env=None, timeout=CLI_TIMEOUT):
    """CLI в отдельном процессе с таймаутом: зависание — провал теста, а не зависший прогон."""
    try:
        r = subprocess.run([sys.executable, "-m", "bot.attach", "--json"] + args, cwd=_ROOT, capture_output=True,
                           env=dict(os.environ, **(env or ENV)), timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return r


def _ops_cli(cp, p, rd, dp, n):
    """Все операции над путём p через CLI (каждая — свой процесс)."""
    return {
        "read": ["--config", cp, "read", p],
        "verify": ["--config", cp, "verify", p],
        "write-retry": ["--config", cp, "write", "--record-dir", rd, "--record-id", RID, "--uuid", uid(n), "--slug",
                        "clip", "--ext", "mp4", "--data", dp, "--source", SRC],
        "complete-pending": ["--config", cp, "complete-pending", p, "--data", dp],
        "fail-pending": ["--config", cp, "fail-pending", p],
        "late-save": ["--config", cp, "late-save", p, "--data", dp],
        "withdraw": ["--config", cp, "withdraw", p, "--reason", "secret", "--withdraw-key-id-env",
                     "WORKSHOP_S3_WITHDRAW_ACCESS_KEY_ID_DEV", "--withdraw-secret-env",
                     "WORKSHOP_S3_WITHDRAW_SECRET_ACCESS_KEY_DEV", "--confirm-withdraw"],
    }


class R3Ancestors(Base):
    """Измерение 1 — права предков: каталог-предок корня записи с правом только x (0o111). Ядро разрешает такой путь
    (POSIX требует лишь x), адаптер обязан тоже: исходы нормы на всех операциях, без adapter-fault."""

    def setUp(self):
        super().setUp()
        if not FS.TRAVERSE_ONLY:
            self.skipTest("нет O_PATH/O_SEARCH: фолбэк O_RDONLY требует права r у предков (записано в журнале)")
        self.xo = os.path.join(self.tmp, "srv")
        self.rd = os.path.join(self.xo, "repo", "tickets")
        os.makedirs(self.rd)

    def tearDown(self):
        os.chmod(self.xo, 0o755)
        super().tearDown()

    def test_all_operations_norm_outcomes(self):
        with self.fake() as fk:
            c = cfg(fk)
            d = os.urandom(THR + 900)
            os.chmod(self.xo, 0o111)
            g = self.write(b"git bytes" * 10, c, n=1)
            self.assertEqual(g.state, "git")
            s = self.write(d, c, n=2)
            self.seen("write", s.outcome, "uploaded")
            self.assertEqual(self.write(d, c, n=2).detail, "already-recorded")
            self.seen("read", attach.read_attachment(g.staged[0], c, env=ENV).outcome, "in-git")
            self.seen("read", attach.read_attachment(s.staged[0], c, env=ENV).outcome, "ok")
            self.seen("read", attach.verify(s.staged[0], c, env=ENV).outcome, "ok")
            pend = self.write(d + b"p", c, n=3, durable_queue=True, defer_upload=True).staged[0]
            self.seen("write", attach.complete_pending(pend, d + b"p", c, env=ENV).outcome, "uploaded")
            pend2 = self.write(d + b"q", c, n=4, durable_queue=True, defer_upload=True).staged[0]
            self.assertEqual(attach.fail_pending(pend2).state, "unsaved")
            uns = self.write(d + b"u", cfg(None), n=5).staged[0]
            self.seen("write", attach.late_save(uns, d + b"u", c, env=ENV).outcome, "uploaded")
            self.assertEqual(attach.withdraw(s.staged[0], "secret", c, WCREDS, env=ENV).state, "withdrawn")
            out = os.path.join(self.xo, "repo", "out.bin")
            attach.save_bytes_outside_carriers(out, b"x", source_path=g.staged[0])
            self.assertEqual(read_bytes(out), b"x")
            cp = cfg_json(os.path.join(self.tmp, "cfg.json"), fk)
            r = _cli(["--config", cp, "read", g.staged[0], "--out", os.path.join(self.xo, "repo", "out2.bin")])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_swap_protection_holds_under_xonly_ancestor(self):
        """R2-2 держится: подмена <record-id>/ между открытием и записью при x-only предке не перенаправляет запись."""
        with self.fake() as fk:
            c = cfg(fk)
            d = os.urandom(THR + 901)
            p = self.write(d, c, n=7, durable_queue=True, defer_upload=True).staged[0]
            evil = os.path.join(self.tmp, "evil")
            bait = place(os.path.join(evil, uid(7) + "-clip.mp4"), ptr_pending(d))
            ridd = os.path.dirname(p)
            os.chmod(self.xo, 0o111)

            def swap(**k):
                os.rename(ridd, ridd + "-parked")
                os.symlink(evil, ridd)
            with _Hook("carrier-opened", swap):
                r = attach.complete_pending(p, d, c, env=ENV)
            self.seen("write", r.outcome, "uploaded")
            self.assertEqual(read_bytes(bait), ptr_pending(d))
            self.assertEqual(pointer_fields(read_bytes(os.path.join(ridd + "-parked", uid(7) + "-clip.mp4")))["state"],
                             "stored")


class R3FileTypes(Base):
    """Измерение 2 — тип файла на месте носителя: FIFO, сокет, каталог (устройство — если ОС позволяет mknod).
    Все операции → AttachInputError (rc 2) без зависания; проверяется в отдельных процессах с таймаутом."""

    def _make(self, kind, p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if kind == "fifo":
            os.mkfifo(p)
        elif kind == "dir":
            os.mkdir(p)
        elif kind == "socket":
            cwd = os.getcwd()
            os.chdir(os.path.dirname(p))   # длина пути сокета ограничена — bind относительного имени
            try:
                sk = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                sk.bind(os.path.basename(p))
                self.addCleanup(sk.close)
            finally:
                os.chdir(cwd)
        elif kind == "device":
            try:
                os.mknod(p, 0o600 | _stat.S_IFCHR, os.makedev(1, 3))
            except (PermissionError, OSError):
                return False
        return True

    def test_special_file_matrix(self):
        made = []
        with self.fake() as fk:
            cp = cfg_json(os.path.join(self.tmp, "cfg.json"), fk)
            dp = place(os.path.join(self.tmp, "d.bin"), os.urandom(THR + 902))
            for i, kind in enumerate(("fifo", "socket", "dir", "device")):
                rd = os.path.join(self.tmp, "t%d" % i, "tickets")
                p = carrier_path(rd, 11)
                if not self._make(kind, p):
                    continue
                made.append(kind)
                for op, args in _ops_cli(cp, p, rd, dp, 11).items():
                    r = _cli(args)
                    self.assertIsNotNone(r, "ЗАВИСАНИЕ: %s / %s" % (kind, op))
                    self.assertEqual(r.returncode, 2, (kind, op, r.stdout, r.stderr))
                    self.assertEqual(json.loads(r.stdout)["error"], "input", (kind, op))
                self.assertEqual(fk.mutations(), [], kind)
                # назначение read --out — тоже спецфайл
                if kind in ("fifo", "dir"):
                    g = attach.write_attachment(os.path.join(self.tmp, "g%d" % i), RID, b"g", ext="png", config=cfg(None),
                                                uuid=uid(12), env=ENV).staged[0]
                    r = _cli(["--config", cp, "read", g, "--out", p])
                    self.assertIsNotNone(r, "ЗАВИСАНИЕ: out %s" % kind)
                    self.assertEqual(r.returncode, 2, (kind, r.stdout))
        self.assertTrue({"fifo", "socket", "dir"} <= set(made), made)

    def test_library_fifo_no_hang(self):
        p = carrier_path(self.rd, 13)
        self._make("fifo", p)
        res = {}

        def run():
            try:
                attach.read_attachment(p, cfg(None), env={})
            except attach.AttachInputError:
                res["ok"] = True
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive(), "read_attachment висит на FIFO")
        self.assertTrue(res.get("ok"))


class R3PathForm(Base):
    """Измерение 3 — форма пути: «.», «..», пустые компоненты → AttachInputError на всех операциях; «..» после symlink
    не читает ни лексический, ни ядровый файл. Корень записи через symlink (домашний каталог) — законен, разрешается
    ядром один раз; ретаргет symlink между открытием и записью запись не перенаправляет."""

    def test_forbidden_forms_all_ops(self):
        a = os.path.join(self.tmp, "A")
        b = os.path.join(self.tmp, "B")
        os.makedirs(a)
        os.makedirs(b)
        os.symlink(b, os.path.join(a, "link"))
        name = uid(1) + "-clip.mp4"
        dotdot = os.path.join(a, "link", "..", "attachments", RID, name)
        kernel = os.path.realpath(dotdot)
        lexical = os.path.normpath(dotdot)
        place(kernel, b"kernel bytes")
        place(lexical, b"lexical bytes")
        forms = [dotdot,
                 os.path.join(a, ".", "attachments", RID, name),
                 a + os.sep + os.sep + os.path.join("attachments", RID, name),
                 os.path.join(a, "attachments", RID, name) + os.sep,
                 os.path.join(a, "attachments", ".", RID, name),
                 "." + os.sep + os.path.join("attachments", RID, name),
                 os.path.join("..", "attachments", RID, name)]
        c = cfg(None)
        for f in forms:
            for call in (lambda: attach.read_attachment(f, c, env={}), lambda: attach.verify(f, c, env={}),
                         lambda: attach.complete_pending(f, b"x", c, env={}), lambda: attach.fail_pending(f),
                         lambda: attach.late_save(f, b"x", c, env={}),
                         lambda: attach.withdraw(f, "secret", c, WCREDS, env={})):
                with self.assertRaises(attach.AttachInputError, msg=f):
                    call()
        for rd in (os.path.join(a, "link", ".."), os.path.join(a, "."), a + os.sep + os.sep + "x"):
            with self.assertRaises(attach.AttachInputError, msg=rd):
                attach.write_attachment(rd, RID, b"x", ext="mp4", config=c, uuid=uid(2), env={})
        self.assertEqual((read_bytes(kernel), read_bytes(lexical)), (b"kernel bytes", b"lexical bytes"))

    def test_symlink_root_legal_and_retarget_safe(self):
        """Порт S3 Fable: корень записи через symlink — все операции законны; ретаргет symlink — приманка цела."""
        with self.fake() as fk:
            real = os.path.join(self.tmp, "real-home", "repo")
            os.makedirs(real)
            link = os.path.join(self.tmp, "home-link")
            os.symlink(os.path.join(self.tmp, "real-home"), link)
            rd = os.path.join(link, "repo", "tickets")
            c = cfg(fk)
            d = os.urandom(THR + 903)
            w = attach.write_attachment(rd, RID, d, ext="mp4", uuid=uid(1), slug="clip", source=SRC, config=c, env=ENV)
            self.seen("write", w.outcome, "uploaded")
            self.assertTrue(os.path.exists(os.path.join(real, "tickets", "attachments", RID, uid(1) + "-clip.mp4")))
            self.seen("read", attach.read_attachment(w.staged[0], c, env=ENV).outcome, "ok")
            self.assertEqual(attach.withdraw(w.staged[0], "secret", c, WCREDS, env=ENV).state, "withdrawn")
            evil = os.path.join(self.tmp, "evil-home", "repo", "tickets", "attachments", RID)
            os.makedirs(evil)
            bait = place(os.path.join(evil, uid(4) + "-clip.mp4"), ptr_pending(d))

            def retarget(**k):
                os.unlink(link)
                os.symlink(os.path.join(self.tmp, "evil-home"), link)
            with _Hook("carrier-opened", retarget):
                attach.write_attachment(rd, RID, d, ext="mp4", uuid=uid(4), slug="clip", source=SRC, config=c, env=ENV)
            self.assertEqual(read_bytes(bait), ptr_pending(d))
            self.assertTrue(os.path.exists(os.path.join(real, "tickets", "attachments", RID, uid(4) + "-clip.mp4")))


# ---- R3-4 NoSuchBucket: одно условие (бакета нет) — один класс для GET / PUT / DELETE / probe:
# storage-unavailable, деталь no-such-bucket. HEAD без тела неотличим (ограничение — в журнале).
@per_provider
class NoSuchBucket(Base):
    def test_matrix(self):
        with self.fake() as fk:
            good = cfg(fk)
            bad = cfg(fk, bucket="no-such-bucket")
            d = os.urandom(THR + 904)
            p = self.write(d, good, n=1).staged[0]
            for fn in (attach.read_attachment, attach.verify):
                r = fn(p, bad, env=ENV)
                self.seen("read", r.outcome, "storage-unavailable")
                self.assertEqual(r.detail, "no-such-bucket")
            w = self.write(d + b"2", bad, n=2)
            self.seen("write", w.outcome, "storage-unavailable")
            self.assertEqual((w.state, w.detail), ("unsaved", "no-such-bucket"))
            pend = self.write(d + b"3", bad, n=3, durable_queue=True, defer_upload=True).staged[0]
            r = attach.complete_pending(pend, d + b"3", bad, env=ENV)
            self.assertEqual((r.outcome, r.detail), ("storage-unavailable", "no-such-bucket"))
            uns = self.write(d + b"4", cfg(None), n=4).staged[0]
            r = attach.late_save(uns, d + b"4", bad, env=ENV)
            self.assertEqual((r.outcome, r.detail), ("storage-unavailable", "no-such-bucket"))
            before = read_bytes(p)
            r = attach.withdraw(p, "secret", bad, WCREDS, env=ENV)     # DELETE 404 NoSuchBucket — НЕ успех изъятия
            self.assertEqual((r.outcome, r.detail), ("storage-unavailable", "no-such-bucket"))
            self.assertEqual(read_bytes(p), before)
            pr = attach.probe_storage(bad, env=ENV)
            self.assertEqual((pr["storage_probe_outcome"], pr["detail"]), ("storage-unavailable", "no-such-bucket"))
            self.assertIn("sha256/" + sha(d), fk.state.objects)                     # хороший бакет не тронут


class R3Backlog(Base):
    def test_infinite_timeouts_are_config_errors(self):
        for fact in ("timeout_s", "deadline_s"):
            for v in (float("inf"), float("-inf"), float("nan")):
                with self.assertRaises(attach.ConfigError, msg=(fact, v)):
                    attach.load_config({"storage": dict(ConfigNorm.FULL, **{fact: v})})
        cp = os.path.join(self.tmp, "c.json")
        with open(cp, "w", encoding="utf-8") as f:
            f.write('{"storage": {"endpoint": "https://s3.example.org", "bucket": "b", "timeout_s": Infinity, '
                    '"credentials": {"access_key_id": "A", "secret_access_key": "B"}}}')
        r = _cli(["--config", cp, "probe"])
        self.assertEqual(r.returncode, 3, r.stdout)

    def test_tmp_left_by_sigkill_swept_under_lock(self):
        """Порт S8 Fable: SIGKILL между созданием temp и renameat оставляет «.<имя>.tmp-<hex>»; следующая операция
        под блокировкой каталога его подметает. Чужие точечные файлы и носители не трогаются."""
        script = ("import os, sys, signal\nsys.path[:0] = [%r, %r]\nimport test_attach as T\nfrom attach import core as C\n"
                  "os.fsync = lambda fd: os.kill(os.getpid(), signal.SIGKILL)\n"
                  "C.write_attachment(%r, T.RID, b'g'*10, ext='mp4', uuid=T.uid(1), slug='clip', source=T.SRC, "
                  "config=T.cfg(None), env=T.ENV)\n") % (_TESTS, _BOT, self.rd)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=60)
        self.assertEqual(r.returncode, -9)
        d = os.path.join(self.rd, "attachments", RID)
        left = os.listdir(d)
        self.assertEqual(len(left), 1)
        self.assertRegex(left[0], r"\A\.%s-clip\.mp4\.tmp-[0-9a-f]{12}\Z" % uid(1))
        place(os.path.join(d, ".keep"), b"")                      # чужой точечный файл — не трогать
        g = self.write(b"next", cfg(None), n=2)
        self.assertEqual(sorted(os.listdir(d)), sorted([".keep", os.path.basename(g.staged[0])]))
        # повтор убитой записи — с прежним uuid — проходит штатно
        w = attach.write_attachment(self.rd, RID, b"g" * 10, ext="mp4", uuid=uid(1), slug="clip", source=SRC,
                                    config=cfg(None), env=ENV)
        self.assertEqual(read_bytes(w.staged[0]), b"g" * 10)


if __name__ == "__main__":
    unittest.main()
