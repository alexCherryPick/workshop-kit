# -*- coding: utf-8 -*-
"""Оракул интерфейсов адаптера вложений (D20 T4): CLI (--json по схеме вывода, коды выхода), API бота (attach.botapi),
контракт фронтов (attach.contract, cli-output.schema.json), статус (attach.repo), раскладка пакета в комплект заказчика,
привязка S3-секретов в обёртках и демоне, сетевой профиль (harness/net_profile_scan.py).

Что доказывается (бриф T4 §0): потребители получают адаптер через стабильный, машинно-читаемый и версионированный
интерфейс; комплект несёт его целиком и работает с хранилищем заказчика, не нарушая сетевой профиль бота.

ОРАКУЛ ОТДЕЛЬНО ОТ ПИСАТЕЛЯ:
  * JSON вывода разбирается СВОИМ парсером (mini_json — не модуль json писателя) и проверяется СВОИМ мини-валидатором
    JSON Schema по файлу схемы; перечни схемы сверяются с нормой, прочитанной PyYAML (писатель — сгенерированный
    attach.norm);
  * указатели и состояния корпуса считаются независимым разбором (по строкам байт), не attach.pointer;
  * хранилище — фейк T2 (fake_s3: своя SigV4, без импорта attach); CLI и установщик гоняются ПРОЦЕССОМ;
  * секреты — положительный контракт на закрытом синтетическом множестве SYNTH по всем выводам модуля.
Единицы: прогон CLI — процесс (rc, stdout, stderr); результат API — элемент Saved.results; файл корпуса — путь от корня."""
import ast
import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

_TESTS = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.dirname(_TESTS)
_ROOT = os.path.dirname(_BOT)
_KIT = os.path.join(_BOT, "kit")
sys.path.insert(0, _TESTS)
sys.path.insert(0, _BOT)
import fake_s3  # noqa: E402
import attach.core as C  # noqa: E402  (подготовка входа — писателем; суд — независимо)
import attach.botapi as B  # noqa: E402
import attach.repo as R  # noqa: E402

PY = sys.executable
NORM_PATH = os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml")
SCHEMA_FILE = os.path.join(_BOT, "attach", "cli-output.schema.json")
STEPS = os.path.join(_KIT, "install-steps.yaml")


def pyyaml(path):
    with open(path, "rb") as f:
        return yaml.safe_load(f.read().decode("utf-8"))


NORM = pyyaml(NORM_PATH)
REG = pyyaml(STEPS)
S3_NAMES = {s["storage_credential"]: s["name"] for s in REG["secrets"] if "storage_credential" in s}
READ_OUT = [o["outcome"] for o in NORM["adapter_outcomes"]["read"]]
WRITE_OUT = [o["outcome"] for o in NORM["adapter_outcomes"]["write"]]
STATES = [s["state"] for s in NORM["states"]["list"]]
POINTER_STATES = [s["state"] for s in NORM["states"]["list"] if s["carrier"] == "pointer"]
REASONS = sorted(set(r for s in NORM["states"]["list"] for r in s.get("reasons", [])))
MARKS = {r["reason"]: r["user_mark"] for r in NORM["unsaved"]["reasons"]}
MAGIC = NORM["pointer"]["magic_prefix"].encode("ascii")
LFS = NORM["lfs"]["signature_prefix"].encode("ascii")
FATAL = "adapter-fault"

# Синтетика — закрытое множество положительного контракта секретов.
AKID = "AKIDSYNTH0T4M2N8B4V6"
SECRET = "synthSECRET-t4+Hk2Jm4Lp6Nr8Qt0Sv2Uw4/unique"
WAKID = "AKIDHUMANWD0T4X1Y3Z5"
WSECRET = "synthHUMAN-t4+Aa1Bb2Cc3Dd4Ee5Ff6Gg7/unique"
PREFIX = "synthPREFIX-t4-7c1e9a3f5b2d40861a3c5e7f9b1d3e5a/"
OTHER_VALUE = "synth-other-ci-secret-t4-value"
SYNTH = (AKID, SECRET, WAKID, WSECRET, PREFIX, OTHER_VALUE)
HUMAN = {"access_key_id": "WORKSHOP_HUMAN_WITHDRAW_KEY_ID", "secret_access_key": "WORKSHOP_HUMAN_WITHDRAW_SECRET"}
OUTPUTS = []        # (тест, текст) всех выводов модуля — сквозной контракт секретов (ZZSecrets)
CANARY = "workshop-canary"
CANARY_BODY = b"workshop-storage-canary 1\n"
THR = 1000
RID = "0199a8c0-1a00-7a00-8a00-000000000a01"
RID2 = "0199a8c0-1a00-7a00-8a00-000000000a02"
SRC = "https://t.me/c/1000000001/%d"
PROVIDERS = fake_s3.PROVIDERS
PERMS = {AKID: {"HEAD", "GET", "PUT"}, WAKID: {"DELETE"}}


def env_all(storage=True, human=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WORKSHOP_") and k != "PYTHONPATH"}
    for s in REG["secrets"]:
        if s.get("required"):
            env[s["name"]] = OTHER_VALUE      # прочие обязательные секреты CI (токен бота, форжи) — синтетика
    if storage:
        env[S3_NAMES["access_key_id"]] = AKID
        env[S3_NAMES["secret_access_key"]] = SECRET
    if human:
        env[HUMAN["access_key_id"]] = WAKID
        env[HUMAN["secret_access_key"]] = WSECRET
    return env


ENV = env_all()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def uid(n):
    return "0199a8c0-2b00-7b00-9b00-%012d" % n


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def make_fake(provider):
    fk = fake_s3.FakeS3(keys={AKID: SECRET, WAKID: WSECRET}, perms=PERMS, provider=provider)
    fk.state.objects[PREFIX + CANARY] = CANARY_BODY
    return fk


def storage_yaml(fk, threshold=THR, extra=""):
    """Конфиг заказчика (формат T3) байтами — оракул пишет текст сам, без yamlmini."""
    s = "git_threshold_bytes: %d\n" % threshold
    if fk is not None:
        s += ("storage:\n  endpoint: %s\n  bucket: %s\n  region: us-east-1\n  allow_insecure_http: true\n  timeout_s: 2\n"
              "  list_permission: %s\n  credentials:\n    access_key_id: %s\n    secret_access_key: %s\n"
              "  key_prefix: \"%s\"\n  canary_key: %s\n" % (fk.endpoint, fk.state.bucket,
                                                         "true" if fk.state.provider == "aws-list" else "false",
                                                         S3_NAMES["access_key_id"], S3_NAMES["secret_access_key"],
                                                         PREFIX, CANARY))
    return (s + extra).encode("ascii")


def put_storage_yaml(repo, data):
    os.makedirs(os.path.join(repo, ".workshop"), exist_ok=True)
    with open(os.path.join(repo, ".workshop", "storage.yaml"), "wb") as f:
        f.write(data)


def per_provider(cls):
    for prov in PROVIDERS:
        name = "%s_%s" % (cls.__name__, prov.replace("-", "_"))
        globals()[name] = type(name, (cls,), {"PROVIDER": prov, "__module__": cls.__module__})
    return None


# ============================================================================ независимый JSON и мини-валидатор схемы
class JsonError(ValueError):
    pass


def mini_json(text):
    """Свой разбор JSON (RFC 8259): объект, массив, строка (экранирование, \\uXXXX с суррогатами), число, литералы.
    Повтор ключа объекта — ошибка (строже json писателя)."""
    pos = [0]
    n = len(text)

    def ws():
        while pos[0] < n and text[pos[0]] in " \t\r\n":
            pos[0] += 1

    def expect(ch):
        if pos[0] >= n or text[pos[0]] != ch:
            raise JsonError("ожидалось %r в %d" % (ch, pos[0]))
        pos[0] += 1

    def string():
        expect('"')
        out = []
        while True:
            if pos[0] >= n:
                raise JsonError("незакрытая строка")
            c = text[pos[0]]
            pos[0] += 1
            if c == '"':
                return "".join(out)
            if c == "\\":
                e = text[pos[0]]
                pos[0] += 1
                if e in '"\\/':
                    out.append(e)
                elif e in "bfnrt":
                    out.append({"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}[e])
                elif e == "u":
                    cp = int(text[pos[0]:pos[0] + 4], 16)
                    pos[0] += 4
                    if 0xD800 <= cp <= 0xDBFF and text[pos[0]:pos[0] + 2] == "\\u":
                        lo = int(text[pos[0] + 2:pos[0] + 6], 16)
                        pos[0] += 6
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                    out.append(chr(cp))
                else:
                    raise JsonError("экранирование")
            elif ord(c) < 0x20:
                raise JsonError("управляющий символ в строке")
            else:
                out.append(c)

    def number():
        m = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?").match(text, pos[0])
        if not m:
            raise JsonError("число")
        pos[0] = m.end()
        return float(m.group(0)) if (m.group(2) or m.group(3)) else int(m.group(0))

    def value():
        ws()
        if pos[0] >= n:
            raise JsonError("конец")
        c = text[pos[0]]
        if c == "{":
            pos[0] += 1
            obj = {}
            ws()
            if text[pos[0]] == "}":
                pos[0] += 1
                return obj
            while True:
                ws()
                k = string()
                if k in obj:
                    raise JsonError("повтор ключа %r" % k)
                ws()
                expect(":")
                obj[k] = value()
                ws()
                if text[pos[0]] == ",":
                    pos[0] += 1
                    continue
                expect("}")
                return obj
        if c == "[":
            pos[0] += 1
            arr = []
            ws()
            if text[pos[0]] == "]":
                pos[0] += 1
                return arr
            while True:
                arr.append(value())
                ws()
                if text[pos[0]] == ",":
                    pos[0] += 1
                    continue
                expect("]")
                return arr
        if c == '"':
            return string()
        for lit, v in (("true", True), ("false", False), ("null", None)):
            if text.startswith(lit, pos[0]):
                pos[0] += len(lit)
                return v
        return number()

    v = value()
    ws()
    if pos[0] != n:
        raise JsonError("хвост после значения")
    return v


def _same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    return a == b


_KNOWN_KW = {"$ref", "oneOf", "const", "enum", "type", "minimum", "properties", "required", "additionalProperties", "items"}
_IGNORED_KW = {"$id", "$comment", "title", "$defs"}


def validate(inst, schema, root, path="$"):
    """Мини-валидатор подмножества JSON Schema. Неизвестное ключевое слово — ошибка самого валидатора (не пропуск)."""
    errs = []
    for k in schema:
        if k not in _KNOWN_KW and k not in _IGNORED_KW and not k.startswith("x-"):
            raise AssertionError("ключевое слово схемы вне валидатора: %s" % k)
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/$defs/"), ref
        return validate(inst, root["$defs"][ref[len("#/$defs/"):]], root, path)
    if "oneOf" in schema:
        ok = [i for i, s in enumerate(schema["oneOf"]) if not validate(inst, s, root, path)]
        if len(ok) != 1:
            errs.append("%s: oneOf — подходит %d ветвей" % (path, len(ok)))
        return errs
    if "const" in schema and not _same(inst, schema["const"]):
        errs.append("%s: не const %r" % (path, schema["const"]))
    if "enum" in schema and not any(_same(inst, e) for e in schema["enum"]):
        errs.append("%s: %r вне enum" % (path, inst))
    t = schema.get("type")
    if t is not None:
        ok = {"null": inst is None, "boolean": isinstance(inst, bool),
              "integer": isinstance(inst, int) and not isinstance(inst, bool),
              "string": isinstance(inst, str), "array": isinstance(inst, list), "object": isinstance(inst, dict)}[t]
        if not ok:
            return errs + ["%s: не %s" % (path, t)]
    if "minimum" in schema and isinstance(inst, int) and inst < schema["minimum"]:
        errs.append("%s: меньше minimum" % path)
    if isinstance(inst, dict):
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in inst:
                errs.append("%s: нет %s" % (path, r))
        for k, v in inst.items():
            if k in props:
                errs += validate(v, props[k], root, path + "." + k)
            elif schema.get("additionalProperties") is False:
                errs.append("%s: лишнее поле %s" % (path, k))
    if isinstance(inst, list) and "items" in schema:
        for i, v in enumerate(inst):
            errs += validate(v, schema["items"], root, "%s[%d]" % (path, i))
    return errs


SCHEMA = mini_json(read_bytes(SCHEMA_FILE).decode("utf-8"))


def pointer_fields(b):
    """Независимый разбор указателя: строки по LF; поле — до первого пробела."""
    lines = b[:-1].split(b"\n")
    out = {"state": lines[1].decode("ascii")[len("state "):]}
    for ln in lines[2:]:
        k, _, v = ln.decode("ascii").partition(" ")
        out[k] = v
    return out


# ============================================================================ CLI процессом
def cli(args, env=None, cwd=None, json_mode=True, entry=None):
    """CLI отдельным процессом. -> (rc, stdout, stderr, разобранный объект | None)."""
    argv = ([PY, "-m", "bot.attach"] if entry is None else entry) + (["--json"] if json_mode else []) + list(args)
    r = subprocess.run(argv, cwd=cwd or _ROOT, env=env if env is not None else ENV, capture_output=True, timeout=120)
    out, err = r.stdout.decode("utf-8"), r.stderr.decode("utf-8")
    OUTPUTS.append((" ".join(args[:2]), out + err))
    obj = mini_json(out.strip()) if json_mode and out.strip() else None
    return r.returncode, out, err, obj


class Base(unittest.TestCase):
    PROVIDER = "yandex"

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="d20-t4-")
        self.rd = os.path.join(self.repo, "tickets", "issue", "2026-10", "rec")
        os.makedirs(self.rd)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def fake(self):
        return make_fake(self.PROVIDER)

    def cfg(self, fk, threshold=THR):
        put_storage_yaml(self.repo, storage_yaml(fk, threshold))
        return R.load_repo_config(self.repo)

    def assert_schema_valid(self, obj):
        errs = validate(obj, SCHEMA, SCHEMA)
        self.assertEqual(errs, [], obj)


# ============================================================================ (в) контракт из нормы
class ContractFromNorm(unittest.TestCase):
    def test_schema_file_equals_generation(self):
        r = subprocess.run([PY, "-m", "bot.attach", "schema"], cwd=_ROOT, capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, read_bytes(SCHEMA_FILE), "cli-output.schema.json == генерация (python3 -m bot.attach schema)")

    def test_enums_equal_norm_independent_parse(self):
        d = SCHEMA["$defs"]
        self.assertEqual(d["read_outcome"]["enum"], READ_OUT)
        self.assertEqual(d["write_outcome"]["enum"], WRITE_OUT)
        self.assertEqual(d["read_outcome"]["x-meanings"], {o["outcome"]: o["meaning"] for o in NORM["adapter_outcomes"]["read"]})
        self.assertEqual(d["write_outcome"]["x-meanings"], {o["outcome"]: o["meaning"] for o in NORM["adapter_outcomes"]["write"]})
        self.assertEqual(d["state"]["enum"], STATES)
        self.assertEqual(sorted(d["reason"]["enum"]), REASONS)
        self.assertEqual(sorted(d["user_mark"]["enum"]), sorted(MARKS.values()))
        self.assertEqual(sorted(d["route_target"]["enum"]),
                         sorted(set(p for o in NORM["routing"]["outcome_meaning"] for p in o.split("_or_"))))
        self.assertTrue(set(d["probe_outcome"]["enum"]) <= set(READ_OUT) | {"ok"})
        self.assertTrue(set(d["verification_failure"]["enum"]) <= set(READ_OUT))
        self.assertEqual(SCHEMA["x-status-facts"], NORM["storage_binding"]["status_facts"])
        st = d["cmd_status"]["properties"]
        self.assertEqual(sorted(st["pointers_by_state"]["properties"]), sorted(POINTER_STATES))
        self.assertTrue(set(NORM["storage_binding"]["status_facts"]) <= set(st))
        self.assertEqual(SCHEMA["x-norm"]["source_sha256"], hashlib.sha256(read_bytes(NORM_PATH)).hexdigest())

    def test_outcome_field_is_norm_plus_fault_only(self):
        """Поле outcome во всех формах: исходы нормы (read ∪ write), null и собственный adapter-fault — и только они."""
        vals = set()

        def collect(s):
            if "$ref" in s:
                return collect(SCHEMA["$defs"][s["$ref"][len("#/$defs/"):]])
            if "oneOf" in s:
                for x in s["oneOf"]:
                    collect(x)
            for k in ("enum",):
                vals.update(x for x in s.get(k, []))
            if "const" in s:
                vals.add(s["const"])
            if s.get("type") == "null":
                vals.add(None)
        for name, d in SCHEMA["$defs"].items():
            if name.startswith("cmd_"):
                collect(d["properties"]["outcome"])
        self.assertEqual(vals, set(READ_OUT) | set(WRITE_OUT) | {FATAL, None})

    def test_exit_codes_closed(self):
        self.assertEqual([e["rc"] for e in SCHEMA["x-exit-codes"]], [0, 2, 3])
        self.assertEqual(sorted(SCHEMA["x-commands"]), sorted(c for c in SCHEMA["x-commands"]))

    def test_no_hand_copies_in_contract_source(self):
        """Схема переписана руками — запрещено: в attach/contract.py нет строковых литералов, равных исходу, состоянию,
        причине, пометке, цели маршрута или факту статуса нормы."""
        src = read_bytes(os.path.join(_BOT, "attach", "contract.py")).decode("utf-8")
        forbidden = set(READ_OUT) | set(WRITE_OUT) | set(STATES) | set(REASONS) | set(MARKS.values()) | \
            set(NORM["storage_binding"]["status_facts"]) | {"git", "storage", "unsaved"}
        lits = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lits.add(node.value)
        self.assertEqual(lits & forbidden, set())

    def test_cli_subcommands_equal_contract(self):
        import attach.cli as cli_mod
        import argparse
        ap = cli_mod._parser()
        subs = [a for a in ap._actions if isinstance(a, argparse._SubParsersAction)][0]
        self.assertEqual(set(subs.choices), set(SCHEMA["x-commands"]) | {"schema"})

    def test_every_command_has_a_form(self):
        forms = set(n[len("cmd_"):] for n in SCHEMA["$defs"] if n.startswith("cmd_"))
        self.assertTrue(set(SCHEMA["x-commands"].values()) <= forms)
        self.assertEqual(len(SCHEMA["oneOf"]), len(forms))


# ============================================================================ (а) CLI: JSON-схема × все исходы
@per_provider
class CliOutcomeMatrix(Base):
    """Каждый исход нормы (14 чтения + 7 записи) и собственный adapter-fault получены ПРОЦЕССОМ CLI с --json: вывод
    разобран независимым парсером, валиден по схеме, исход — ожидаемый для построенного входа, rc из закрытого перечня."""

    def _write(self, cfg, data, n, rd=None, rid=RID, **kw):
        return C.write_attachment(rd or self.rd, rid, data, ext="bin", config=cfg, uuid=uid(n), source=SRC % n,
                                  env=ENV, **kw)

    def _place(self, n, content):
        p = os.path.join(self.rd, "attachments", RID, uid(n) + ".bin")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(content)
        return p

    def test_all_outcomes(self):
        seen = {}
        with self.fake() as fk:
            cfg = self.cfg(fk)
            rp = ["--repo", self.repo]
            big = lambda k: bytes([k]) * (THR + 1 + k)  # noqa: E731
            p_git = self._write(cfg, b"small", 1).staged[0]
            p_ok = self._write(cfg, big(2), 2).staged[0]
            p_pend = self._write(cfg, big(3), 3, durable_queue=True, defer_upload=True).staged[0]
            p_miss = self._write(cfg, big(4), 4).staged[0]
            del fk.state.objects[PREFIX + "sha256/" + sha(big(4))]
            p_size = self._write(cfg, big(5), 5).staged[0]
            fk.state.objects[PREFIX + "sha256/" + sha(big(5))] = b"x" * 3
            p_sha = self._write(cfg, big(6), 6).staged[0]
            fk.state.objects[PREFIX + "sha256/" + sha(big(6))] = bytes([255]) * len(big(6))
            p_uns = self._write(cfg, None, 7, declared_size=THR * 50).staged[0]
            p_wd = self._write(cfg, b"withdraw me", 8).staged[0]
            C.withdraw(p_wd, "erasure", cfg, HUMAN, env=ENV)
            p_inv = self._place(9, MAGIC + b"1\nstate bogus\n")
            p_ver = self._place(10, MAGIC + b"7\nstate stored\n")
            p_lfs = self._place(11, LFS + b"\noid sha256:" + b"0" * 64 + b"\nsize 5\n")
            # aws-no-list: без ListBucket отсутствующий объект — 403, и адаптер честно отвечает storage-denied (T2 R2-1:
            # 403 на целевом никогда не доказывает отсутствие) — pending-upload / object-missing в этом режиме недостижимы
            absent = (lambda o: "storage-denied") if self.PROVIDER == "aws-no-list" else (lambda o: o)  # noqa: E731
            cases = [("in-git", p_git, rp, None), ("ok", p_ok, rp, None), (absent("pending-upload"), p_pend, rp, None),
                     (absent("object-missing"), p_miss, rp, None), ("size-mismatch", p_size, rp, None),
                     ("sha-mismatch", p_sha, rp, None), ("not-stored", p_uns, rp, None), ("withdrawn", p_wd, rp, None),
                     ("pointer-invalid", p_inv, rp, None), ("pointer-version-unknown", p_ver, rp, None),
                     ("lfs-unsupported", p_lfs, rp, None)]
            empty = os.path.join(self.repo, "empty.json")
            with open(empty, "wb") as f:
                f.write(b"{}")
            cases.append(("storage-not-configured", p_ok, ["--config", empty], None))
            cases.append(("storage-denied", p_ok, rp, "deny"))
            cases.append(("storage-unavailable", p_ok, rp, "err5xx"))
            for want, p, conf, mode in cases:
                fk.state.mode = {mode} if mode else set()
                for cmd in ("read", "verify"):
                    rc, out, err, obj = cli(conf + [cmd, p])
                    with self.subTest(outcome=want, cmd=cmd):
                        self.assertEqual(rc, 0, out + err)
                        self.assert_schema_valid(obj)
                        self.assertEqual((obj["command"], obj["outcome"]), (cmd, want))
                        seen[want] = True
            fk.state.mode = set()
            # исходы записи
            d_up = big(20)
            wargs = lambda n, dp, rid=RID: rp + ["write", "--record-dir", self.rd, "--record-id", rid, "--uuid", uid(n),  # noqa: E731
                                                 "--ext", "bin", "--source", SRC % n, "--data", dp]
            dp = os.path.join(self.repo, "d20.bin")
            with open(dp, "wb") as f:
                f.write(d_up)
            wcases = [("uploaded", wargs(20, dp), None), ("already-present", wargs(21, dp, RID2), None)]
            d_rep = big(22)
            fk.state.objects[PREFIX + "sha256/" + sha(d_rep)] = b"wrong"
            dp2 = os.path.join(self.repo, "d22.bin")
            with open(dp2, "wb") as f:
                f.write(d_rep)
            wcases.append(("repaired", wargs(22, dp2), None))
            dp3 = os.path.join(self.repo, "d23.bin")
            with open(dp3, "wb") as f:
                f.write(big(23))
            wcases.append(("bytes-mismatch", wargs(20, dp3), None))          # повтор uuid 20 чужими байтами
            wcases.append(("storage-denied", wargs(24, dp3), "deny"))
            wcases.append(("storage-unavailable", wargs(25, dp3), "err5xx"))
            for want, args, mode in wcases:
                fk.state.mode = {mode} if mode else set()
                rc, out, err, obj = cli(args)
                with self.subTest(outcome=want, cmd="write"):
                    self.assertEqual(rc, 0, out + err)
                    self.assert_schema_valid(obj)
                    self.assertEqual(obj["outcome"], want)
                    seen["w:" + want] = True
            fk.state.mode = set()
            # storage-not-configured записи: досохранение unsaved выше порога без привязки
            p_ns = C.write_attachment(self.rd, RID, big(26), ext="bin", config=C.load_config({"git_threshold_bytes": THR}),
                                      uuid=uid(26), source=SRC % 26, env=ENV).staged[0]
            dp4 = os.path.join(self.repo, "d26.bin")
            with open(dp4, "wb") as f:
                f.write(big(26))
            thr_only = os.path.join(self.repo, "thr.json")
            with open(thr_only, "wb") as f:
                f.write(b'{"git_threshold_bytes": %d}' % THR)
            rc, out, err, obj = cli(["--config", thr_only, "late-save", p_ns, "--data", dp4])
            self.assertEqual(rc, 0, out + err)
            self.assert_schema_valid(obj)
            self.assertEqual(obj["outcome"], "storage-not-configured")
            seen["w:storage-not-configured"] = True
            # собственная ошибка: конфиг не разбирается — rc 3, outcome adapter-fault
            bad = os.path.join(self.repo, "bad.json")
            with open(bad, "wb") as f:
                f.write(b"{not json")
            rc, out, err, obj = cli(["--config", bad, "read", p_ok])
            self.assertEqual((rc, obj["outcome"]), (3, FATAL))
            self.assert_schema_valid(obj)
            # ошибка входа: rc 2, error input, outcome null; разбор аргументов — тоже rc 2 в форме JSON
            for args in (rp + ["read", os.path.join(self.rd, "nope")], ["read"], ["--bogus", "probe"],
                         ["--repo", self.repo, "--config", empty, "probe"]):
                rc, out, err, obj = cli(args)
                with self.subTest(input=args):
                    self.assertEqual(rc, 2, out + err)
                    self.assert_schema_valid(obj)
                    self.assertEqual((obj["error"], obj["outcome"]), ("input", None))
        unreachable = {"pending-upload", "object-missing"} if self.PROVIDER == "aws-no-list" else set()
        self.assertEqual(set(k for k in seen if not k.startswith("w:")), set(READ_OUT) - unreachable)
        self.assertEqual(set(k[2:] for k in seen if k.startswith("w:")), set(WRITE_OUT))

    def test_other_commands_schema_valid(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            rp = ["--repo", self.repo]
            p = C.write_attachment(self.rd, RID, b"q" * (THR + 7), ext="bin", config=cfg, uuid=uid(1), source=SRC % 1,
                                   env=ENV).staged[0]
            pq = C.write_attachment(self.rd, RID, b"p" * (THR + 9), ext="bin", config=cfg, uuid=uid(2), source=SRC % 2,
                                    durable_queue=True, defer_upload=True, env=ENV).staged[0]
            dq = os.path.join(self.repo, "q.bin")
            with open(dq, "wb") as f:
                f.write(b"p" * (THR + 9))
            for args, cmd in ((rp + ["route", "--size", str(THR + 1)], "route"), (rp + ["probe"], "probe"),
                              (rp + ["status"], "status"), (rp + ["status", "--verify"], "status"),
                              (rp + ["status", "--verify", "--max-pointers", "0"], "status"),
                              (["classify", p], "classify"), (rp + ["key-paths", p], "key-paths"),
                              (rp + ["complete-pending", pq, "--data", dq], "complete-pending")):
                rc, out, err, obj = cli(args)
                with self.subTest(args=args):
                    self.assertEqual(rc, 0, out + err)
                    self.assert_schema_valid(obj)
                    self.assertEqual(obj["command"], cmd)
                    self.assertEqual(obj["output_schema_version"], SCHEMA["x-output-schema-version"])

    def test_human_mode_same_rc_no_json(self):
        with self.fake() as fk:
            self.cfg(fk)
            for args, want_rc in ((["--repo", self.repo, "probe"], 0), (["read", "/nonexistent/x"], 2)):
                rc, out, err, _ = cli(args, json_mode=False)
                self.assertEqual(rc, want_rc)
                self.assertRaises(JsonError, mini_json, out.strip())
                self.assertIn("outcome: ", out)
                self.assertNotIn("Traceback", out + err)


# ============================================================================ (б) API бота
def items_of(datas, base=100, form="markdown_link"):
    return [B.Incoming(d, ext="bin", source=SRC % (base + i), caption="файл [%d] из %d\\" % (i + 1, len(datas)),
                       ident="tg:-1001:%d" % (base + i), message_date=1760000000 + i, form=form,
                       declared_size=(THR * 30 if d is None else None)) for i, d in enumerate(datas)]


def oracle_link(form, path, caption):
    """Строка ссылки — из синтаксиса нормы (PyYAML) и правила экранирования подписи, построена оракулом."""
    syn = [f["syntax"] for f in NORM["link_forms"]["forms"] if f["form"] == form][0]
    esc = "".join("\\" + c if c in NORM["filename"]["original_name"]["escaping_required_chars"] else c for c in caption)
    return syn.replace("<подпись>", esc).replace("attachments/<id>/<имя>", path)


def check_preservation(self, items, saved, record_dir=None, dedupe=True):
    """Инвариант сохранения (оракул): N элементов → N результатов в том же порядке; uuid своего элемента или первого
    экземпляра одинаковых байт; путь — attachments/<rid>/<uuid>.<ext>; ссылка — оракульная строка; staged — пути
    результатов без повторов в порядке элементов; путей = элементов минус повторы байт (при dedupe)."""
    rd = record_dir or self.rd
    self.assertEqual(len(saved.results), len(items))
    first = {}
    for i, (it, r) in enumerate(zip(items, saved.results)):
        self.assertEqual(r.index, i)
        h = None if it.data is None else sha(it.data)
        if dedupe and h is not None and h in first:
            j = first[h]
            self.assertEqual((r.same_as, r.uuid, r.path), (j, items[j].uuid, saved.results[j].path))
        else:
            if h is not None:
                first.setdefault(h, i)
            self.assertIsNone(r.same_as)
            self.assertEqual(r.uuid, it.uuid)
            self.assertEqual(r.path, "attachments/%s/%s.%s" % (RID, it.uuid, it.ext))
        self.assertEqual(r.link, oracle_link(it.form, r.path, it.caption))
    want_staged = []
    for r in saved.results:
        for s in r.staged:
            if s not in want_staged:
                want_staged.append(s)
    self.assertEqual(saved.staged, want_staged)
    for s in saved.staged:
        self.assertTrue(os.path.isfile(s), s)
        self.assertTrue(s.startswith(rd + os.sep))
    self.assertEqual(saved.replies, [r.index for r in saved.results if r.reply is not None])
    for r in saved.results:
        if r.state == "unsaved":
            self.assertEqual(r.reply["user_mark"], MARKS[r.reason])
            self.assertEqual(r.reply["reason"], r.reason)


@per_provider
class BotApiMatrix(Base):
    check_preservation = check_preservation

    def test_album_sizes_0_1_10(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            for n in (0, 1, 10):
                datas = [os.urandom(THR - 1 + (i % 3)) for i in range(12)]
                its = items_of(datas[:n], base=1000 * (n + 1))
                s = B.save(self.rd, RID, its, config=cfg, env=ENV)
                self.check_preservation(its, s)
                states = [r.state for r in s.results]
                self.assertEqual(states, [("git", "git", "stored")[i % 3] for i in range(n)])
                self.assertEqual(len(s.staged), n)
                for r, it in zip(s.results, its):
                    on_disk = read_bytes(os.path.join(self.rd, *r.path.split("/")))
                    if r.state == "git":
                        self.assertEqual(on_disk, it.data)
                    else:
                        f = pointer_fields(on_disk)
                        self.assertEqual((f["state"], f["sha256"], f["size"]), ("stored", sha(it.data), str(len(it.data))))
                        self.assertEqual(fk.state.objects[PREFIX + "sha256/" + sha(it.data)], it.data)

    def test_same_bytes_dedupe_and_not(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            a, b = os.urandom(THR + 50), os.urandom(THR + 60)
            datas = [a, b, a, a, b, os.urandom(10), a, b, a, os.urandom(THR + 70)]
            its = items_of(datas, base=200)
            s = B.save(self.rd, RID, its, config=cfg, env=ENV)
            self.check_preservation(its, s)
            self.assertEqual(len(set(r.path for r in s.results)), 4)          # a, b, мелкий, последний
            self.assertEqual(len(s.staged), 4)
            self.assertEqual(len(set(r.link for r in s.results)), 10)         # подписи разные — 10 ссылок
            objs = [k for k in fk.state.objects if k.startswith(PREFIX + "sha256/")]
            self.assertEqual(len(objs), 3)
            its2 = items_of(datas, base=300)
            s2 = B.save(self.rd, RID, its2, config=cfg, env=ENV, dedupe_same_bytes=False)
            self.check_preservation(its2, s2, dedupe=False)
            self.assertEqual(len(set(r.path for r in s2.results)), 10)        # N путей
            self.assertEqual(len([k for k in fk.state.objects if k.startswith(PREFIX + "sha256/")]), 3)   # объект один
            self.assertEqual([r.write_outcome for r in s2.results if r.state == "stored"], ["already-present"] * 9)

    def test_partly_not_obtained_and_threshold_edges(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            datas = [os.urandom(THR), None, os.urandom(THR + 1), None, b""]
            its = items_of(datas, base=400)
            s = B.save(self.rd, RID, its, config=cfg, env=ENV)
            self.check_preservation(its, s)
            self.assertEqual([(r.state, r.reason) for r in s.results],
                             [("git", None), ("unsaved", "source-refused"), ("stored", None), ("unsaved", "source-refused"),
                              ("git", None)])
            self.assertEqual(s.replies, [1, 3])
            for i in (1, 3):
                f = pointer_fields(read_bytes(os.path.join(self.rd, *s.results[i].path.split("/"))))
                self.assertEqual((f["state"], f["reason"], f["source"], f["size"]), ("unsaved", "source-refused",
                                                                                      SRC % (400 + i), str(THR * 30)))

    def test_storage_absent_unavailable_denied(self):
        data = [os.urandom(THR + 5), os.urandom(5)]
        # нет привязки
        put_storage_yaml(self.repo, storage_yaml(None))
        cfg0 = R.load_repo_config(self.repo)
        its = items_of(data, base=500)
        s = B.save(self.rd, RID, its, config=cfg0, env=ENV)
        self.check_preservation(its, s)
        self.assertEqual([(r.state, r.reason, r.write_outcome) for r in s.results],
                         [("unsaved", "no-storage", None), ("git", None, None)])
        self.assertEqual(s.results[0].reply["user_mark"], MARKS["no-storage"])
        with self.fake() as fk:
            cfg = self.cfg(fk)
            for mode, want in (("err5xx", "storage-unavailable"), ("deny", "storage-denied")):
                fk.state.mode = {mode}
                its = items_of(data, base=600 if mode == "deny" else 700)
                s = B.save(self.rd, RID, its, config=cfg, env=ENV)
                self.check_preservation(its, s)
                self.assertEqual((s.results[0].state, s.results[0].reason, s.results[0].write_outcome),
                                 ("unsaved", "upload-failed", want))
                self.assertEqual(s.results[0].reply["write_outcome"], want)
            fk.state.mode = set()

    def test_retry_after_break_same_uuid(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            datas = [os.urandom(THR + 11), os.urandom(12), None]
            its = items_of(datas, base=800)
            fk.state.mode = {"err5xx"}
            s1 = B.save(self.rd, RID, its, config=cfg, env=ENV)
            self.assertEqual(s1.results[0].state, "unsaved")
            fk.state.mode = set()
            its_again = items_of(datas, base=800)     # обрыв: то же событие пришло снова — те же ident
            self.assertEqual([i.uuid for i in its_again], [i.uuid for i in its])
            n_put = len([e for e in fk.state.log if e["method"] == "PUT"])
            s2 = B.save(self.rd, RID, its_again, config=cfg, env=ENV)
            self.check_preservation(its_again, s2)
            self.assertEqual([r.path for r in s2.results], [r.path for r in s1.results])
            self.assertEqual([r.link for r in s2.results], [r.link for r in s1.results])
            self.assertEqual((s2.results[0].state, s2.results[0].write_outcome), ("stored", "uploaded"))
            self.assertEqual(s2.results[1].detail, "already-recorded")
            self.assertEqual(s2.results[2].detail, "already-recorded")
            s3 = B.save(self.rd, RID, its_again, config=cfg, env=ENV)    # третий раз — всё тождественно, PUT нет
            self.assertEqual([r.detail for r in s3.results], ["already-recorded"] * 3)
            self.assertEqual(len([e for e in fk.state.log if e["method"] == "PUT"]), n_put + 1)
            # обрыв МЕЖДУ загрузкой и записью указателя (объект есть, указателя нет): повтор — already-present, путь тот же
            its4 = items_of([os.urandom(THR + 13)], base=850)
            s4 = B.save(self.rd, RID, its4, config=cfg, env=ENV)
            os.remove(s4.staged[0])
            s5 = B.save(self.rd, RID, items_of([its4[0].data], base=850), config=cfg, env=ENV)
            self.assertEqual((s5.results[0].path, s5.results[0].state, s5.results[0].write_outcome),
                             (s4.results[0].path, "stored", "already-present"))

    def test_queue_pending_then_complete(self):
        qdir = tempfile.mkdtemp(prefix="d20-t4-queue-")
        try:
            q = B.FileQueue(qdir, env={})
            with self.fake() as fk:
                cfg = self.cfg(fk)
                d = os.urandom(THR + 33)
                its = items_of([d, os.urandom(3)], base=900)
                fk.state.mode = {"err5xx"}
                s = B.save(self.rd, RID, its, config=cfg, env=ENV, queue=q)
                self.check_preservation(its, s)
                self.assertEqual((s.results[0].state, s.results[0].reply), ("pending", None))
                self.assertEqual(q.get(sha(d)), d)
                self.assertEqual(s.queue_release, [])
                fk.state.mode = set()
                w = B.complete_from_queue(os.path.join(self.rd, *s.results[0].path.split("/")), q, cfg, env=ENV)
                self.assertEqual((w.state, w.outcome), ("stored", "uploaded"))
                s2 = B.save(self.rd, RID, items_of([os.urandom(THR + 34)], base=950), config=cfg, env=ENV, queue=q)
                self.assertEqual(s2.results[0].state, "stored")
                self.assertEqual(s2.queue_release, [{"sha256": s2.results[0].sha256, "holder": s2.staged[0]}])
        finally:
            shutil.rmtree(qdir, ignore_errors=True)

    def test_comment_attachment_above_threshold(self):
        """Вложение коммента — папка записи (норма owners.comment_attachments); выше порога — указатель; строка ссылки
        та же из файла записи и из файла комментов; текстов API не пишет."""
        with self.fake() as fk:
            cfg = self.cfg(fk)
            comments = os.path.join(self.rd, "ISSUE-1.comments.md")
            with open(comments, "wb") as f:
                f.write(b"<!-- comments-of: %s -->\n" % RID.encode())
            before = read_bytes(comments)
            its = items_of([os.urandom(THR * 3)], base=1100, form="markdown_embed")
            s = B.save(self.rd, RID, its, config=cfg, env=ENV)
            self.check_preservation(its, s)
            self.assertEqual(s.results[0].state, "stored")
            self.assertTrue(s.results[0].link.startswith("!["))
            self.assertEqual(read_bytes(comments), before)
            self.assertEqual(os.path.dirname(os.path.dirname(s.staged[0])), os.path.join(self.rd, "attachments"))


class BotApiProperties(Base):
    def test_random_albums_preservation(self):
        rnd = random.Random(20261012)
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)
            pool = [os.urandom(rnd.choice((1, THR - 1, THR, THR + 1, THR * 2))) for _ in range(5)]
            for trial in range(25):
                n = rnd.randint(0, 9)
                datas = [None if rnd.random() < 0.15 else rnd.choice(pool) for _ in range(n)]
                its = items_of(datas, base=5000 + trial * 20)
                dd = rnd.random() < 0.5
                s = B.save(self.rd, RID, its, config=cfg, env=ENV, dedupe_same_bytes=dd)
                check_preservation(self, its, s, dedupe=dd)

    def test_input_judged_before_any_write(self):
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)
            its = items_of([os.urandom(5), os.urandom(THR + 5)], base=7000)
            its.append(its[0])                                       # тот же uuid дважды
            self.assertRaises(C.AttachInputError, B.save, self.rd, RID, its, config=cfg, env=ENV)
            self.assertFalse(os.path.exists(os.path.join(self.rd, "attachments")))
            self.assertEqual([e for e in fk.state.log if e["method"] == "PUT"], [])
            for bad in (dict(caption=""), dict(caption="a\nb"), dict(source=None), dict(ext="PNG"),
                        dict(form="backtick_mention"), dict(uuid=uid(1), ident="tg:1:1"), dict(declared_size=-1),
                        dict(declared_size=True), dict(media_type="Image/PNG"), dict(source="http://t.me/c/1/1")):
                kw = dict(ext="bin", source=SRC % 1, caption="c", ident="tg:-1:1", message_date=1760000000)
                kw.update(bad)
                if "uuid" in bad:
                    kw["message_date"] = 1760000000
                with self.subTest(bad=bad):
                    self.assertRaises(C.AttachInputError, lambda: B.Incoming(b"x", **kw))

    def test_attachment_uuid_deterministic_v7(self):
        u1 = B.attachment_uuid("tg:-100:5", 1760000000, 0)
        self.assertEqual(u1, B.attachment_uuid("tg:-100:5", 1760000000, 0))
        self.assertNotEqual(u1, B.attachment_uuid("tg:-100:5", 1760000000, 1))
        self.assertNotEqual(u1, B.attachment_uuid("tg:-100:6", 1760000000, 0))
        self.assertTrue(re.fullmatch(NORM["filename"]["pattern"], u1 + ".bin"))
        self.assertEqual(u1[14], "7")
        self.assertEqual(int(u1.replace("-", "")[:12], 16), 1760000000 * 1000)

    def test_item_error_is_its_own_result(self):
        """Ошибка элемента (по пути — withdrawn, терминально) — результат С error и reply у ЭТОГО элемента; прочие сохранены."""
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)
            its = items_of([os.urandom(7), os.urandom(8)], base=7100)
            s = B.save(self.rd, RID, its, config=cfg, env=ENV)
            C.withdraw(s.staged[0], "erasure", cfg, HUMAN, env=ENV)
            s2 = B.save(self.rd, RID, items_of([its[0].data, its[1].data], base=7100), config=cfg, env=ENV)
            self.assertEqual((s2.results[0].error, s2.results[0].reply["error"]), ("input", "input"))
            self.assertEqual(s2.results[1].detail, "already-recorded")
            self.assertEqual(s2.replies, [0])

    def test_queue_refuses_ephemeral_ci_and_git_tree(self):
        self.assertRaises(B.QueueRefused, B.FileQueue, tempfile.mkdtemp(), env={"GITHUB_ACTIONS": "true"})
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.assertRaises(B.QueueRefused, B.FileQueue, os.path.join(self.repo, "q"), env={})
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)

            class Fake(object):
                durable = False
            self.assertRaises(C.AttachInputError, B.save, self.rd, RID, [], config=cfg, queue=Fake())


ENTRY = [PY, os.path.join(_BOT, "attach")]     # каталог пакета как скрипт — та же форма, что у заказчика


class RepoConfigFile(Base):
    """`.workshop/storage.yaml` для CLI и API: нет файла — не настроено; не обычный файл, symlink каталога, не UTF-8, не
    разбирается — собственная ошибка (rc 3) без отражения содержимого."""

    def test_forms(self):
        self.assertIsNone(R.load_repo_config(self.repo).binding)
        marker = "SYNTH-LINE-MARKER-t4"
        for label, data in (("not-utf8", b"\xff\xfe storage:\n"), ("broken", ("storage: [%s\n" % marker).encode()),
                            ("bad-type", b"git_threshold_bytes: big\n")):
            put_storage_yaml(self.repo, data)
            rc, out, err, obj = cli(["--repo", self.repo, "probe"])
            with self.subTest(label=label):
                self.assertEqual((rc, obj["outcome"]), (3, FATAL))
                self.assertNotIn(marker, out + err)
        os.remove(os.path.join(self.repo, ".workshop", "storage.yaml"))
        os.mkdir(os.path.join(self.repo, ".workshop", "storage.yaml"))
        rc, out, err, obj = cli(["--repo", self.repo, "probe"])
        self.assertEqual(rc, 3)
        other = tempfile.mkdtemp(prefix="d20-t4-other-")
        try:
            shutil.rmtree(os.path.join(self.repo, ".workshop"))
            put_storage_yaml(other, storage_yaml(None))
            os.symlink(os.path.join(other, ".workshop"), os.path.join(self.repo, ".workshop"))
            rc, out, err, obj = cli(["--repo", self.repo, "probe"])
            self.assertEqual(rc, 3)
        finally:
            shutil.rmtree(other, ignore_errors=True)


class LeadingDotPaths(Base):
    """Бэклог T2 R4: ядро отвергает компонент «.» (в т. ч. ведущий `./`) — CLI и API бота снимают ведущие `./` сами;
    `..`, `//` и «.» внутри пути по-прежнему судит ядро (отказ)."""

    def test_cli_and_api(self):
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)
            rel_rd = os.path.relpath(self.rd, self.repo)
            dp = os.path.join(self.repo, "d.bin")
            with open(dp, "wb") as f:
                f.write(os.urandom(THR + 2))
            rc, out, err, w = cli(["--repo", ".", "write", "--record-dir", "./" + rel_rd, "--record-id", RID, "--uuid",
                                   uid(1), "--ext", "bin", "--source", SRC % 1, "--data", "./d.bin"], cwd=self.repo,
                                  entry=ENTRY)
            self.assertEqual((rc, w["state"]), (0, "stored"), out + err)
            self.assertFalse(os.path.isabs(w["staged"][0]))            # путь — от cwd, как дан record-dir
            rel_p = "./" + w["staged"][0]
            for cmd in ("read", "verify", "key-paths"):
                rc, out, err, obj = cli(["--repo", "./", cmd, rel_p], cwd=self.repo, entry=ENTRY)
                self.assertEqual(rc, 0, out + err)
            self.assertEqual(obj["paths"], [rel_p[2:]])
            for bad in ("." + os.sep + "." + os.sep + rel_rd + os.sep + "." + os.sep + "x", rel_rd + os.sep + ".." + os.sep + "y"):
                rc, out, err, obj = cli(["--repo", ".", "write", "--record-dir", bad, "--record-id", RID, "--uuid", uid(2),
                                         "--ext", "bin", "--source", SRC % 2, "--data", dp], cwd=self.repo, entry=ENTRY)
                self.assertEqual((rc, obj["error"]), (2, "input"), bad)
            here = os.getcwd()
            os.chdir(self.rd)
            try:
                s = B.save(".", RID, items_of([os.urandom(5)], base=8100), config=cfg, env=ENV)
                s2 = B.save("./", RID, items_of([os.urandom(6)], base=8101), config=cfg, env=ENV)
            finally:
                os.chdir(here)
            self.assertEqual([r.state for r in s.results + s2.results], ["git", "git"])
            self.assertTrue(os.path.isabs(s.staged[0]) and os.path.isfile(s.staged[0]))


class BotApiNoWithdraw(unittest.TestCase):
    """API бота изъятия не открывает (бриф §2): ни имени, ни реэкспорта, ни обращения к withdraw в исходнике."""

    def test_namespace(self):
        self.assertFalse(any("withdraw" in n for n in dir(B)))
        self.assertFalse(any("withdraw" in n for n in B.__all__))

    def test_source_has_no_withdraw_reference(self):
        src = read_bytes(os.path.join(_BOT, "attach", "botapi.py")).decode("utf-8")
        tree = ast.parse(src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.alias):
                names.add(node.name)
                names.add(node.asname or "")
        self.assertFalse([n for n in names if "withdraw" in n], names)

    def test_bot_modules_do_not_call_withdraw(self):
        for f in sorted(os.listdir(_BOT)):
            if f.endswith(".py"):
                src = read_bytes(os.path.join(_BOT, f)).decode("utf-8")
                self.assertNotRegex(src, r"\bwithdraw", f)


# ============================================================================ (е) статус и один key
@per_provider
class StatusAndKey(Base):
    def corpus(self, fk, cfg):
        its = items_of([os.urandom(THR + 1), os.urandom(THR + 2), os.urandom(3), None, os.urandom(THR + 3)], base=1300)
        s = B.save(self.rd, RID, its, config=cfg, env=ENV)
        C.write_attachment(self.rd, RID, os.urandom(THR + 4), ext="bin", config=cfg, uuid=uid(77), source=SRC % 77,
                           durable_queue=True, defer_upload=True, env=ENV)
        C.withdraw(s.staged[2], "erasure", cfg, HUMAN, env=ENV)
        return s

    def independent_count(self):
        """Оракул: обход по своему правилу (attachments/<x>/<файл>, обычные файлы, без .git и вложенных репо)."""
        by, git_b = dict((s, 0) for s in POINTER_STATES), 0
        for root, dirs, files in os.walk(self.repo):
            dirs[:] = [d for d in dirs if d != ".git" and not os.path.exists(os.path.join(root, d, ".git"))]
            if os.path.basename(os.path.dirname(root)) != "attachments":
                continue
            for f in files:
                p = os.path.join(root, f)
                if os.path.islink(p) or re.fullmatch(r"\..+\.tmp-[0-9a-f]{12}", f):   # временный файл адаптера
                    continue
                b = read_bytes(p)
                if b.startswith(MAGIC):
                    st = b.split(b"\n")[1].decode("ascii")[len("state "):]
                    by[st] += 1
                elif not b.startswith(LFS):
                    git_b += 1
        return by, git_b

    def test_counts_and_verify(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            s = self.corpus(fk, cfg)
            # шум: вложенный репозиторий с указателем, symlink в attachments/<rid>/, файл глубже глоба
            nested = os.path.join(self.repo, ".workshop-kit")
            os.makedirs(os.path.join(nested, ".git"))
            os.makedirs(os.path.join(nested, "x", "attachments", RID))
            shutil.copy(s.staged[0], os.path.join(nested, "x", "attachments", RID, uid(1) + ".bin"))
            os.symlink(s.staged[0], os.path.join(self.rd, "attachments", RID, uid(2) + ".bin"))
            with open(os.path.join(self.rd, "attachments", RID, ".%s.bin.tmp-0123456789ab" % uid(4)), "wb") as f:
                f.write(b"half-written temp of an interrupted write")      # имя зарезервировано адаптером
            deep = os.path.join(self.rd, "attachments", RID, "deeper")
            os.makedirs(deep)
            shutil.copy(s.staged[0], os.path.join(deep, uid(3) + ".bin"))
            st = B.status(self.repo, cfg, env=ENV)
            by, git_b = self.independent_count()
            self.assertEqual(st["pointers_by_state"], by)
            self.assertEqual(st["bytes_in_git"], git_b)
            self.assertEqual(st["non_regular"], 1)
            self.assertEqual(st["storage_probe_outcome"], "ok")
            self.assertIsNone(st["last_verification_failures"])
            # сбои проверки: объект пропал, длина иная, байты иные
            p0, p1 = s.results[0], s.results[1]
            del fk.state.objects[PREFIX + "sha256/" + p0.sha256]
            fk.state.objects[PREFIX + "sha256/" + p1.sha256] = b"zz"
            st = B.status(self.repo, cfg, env=ENV, verify=True)
            got = sorted((f["path"].split("/")[-1], f["outcome"]) for f in st["last_verification_failures"])
            want = [(p1.path.split("/")[-1], "size-mismatch")]
            if self.PROVIDER != "aws-no-list":       # без ListBucket отсутствие — storage-denied (не сбой проверки)
                want.append((p0.path.split("/")[-1], "object-missing"))
            self.assertEqual(got, sorted(want))
            self.assertEqual(st["verification"]["checked"], 4)
            self.assertEqual(sum(st["verification"]["outcomes"].values()), 4)
            self.assertEqual(st["verification"]["outcomes"].get("ok"), 1)
            if self.PROVIDER != "aws-no-list":
                self.assertEqual(st["verification"]["outcomes"].get("pending-upload"), 1)
            st = B.status(self.repo, cfg, env=ENV, verify=True, max_pointers=1)
            self.assertEqual((st["verification"]["checked"], st["verification"]["truncated"]), (1, True))
            fk.state.mode = {"err5xx"}
            st = B.status(self.repo, cfg, env=ENV)
            self.assertEqual(st["storage_probe_outcome"], "storage-unavailable")
            fk.state.mode = set()
        st = B.status(self.repo, C.load_config({}), env=ENV)
        self.assertEqual((st["storage_configured"], st["storage_probe_outcome"]), (False, None))

    def test_key_set_one_commit_cli(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            d = os.urandom(THR + 40)
            rd2 = os.path.join(self.repo, "docs", "rec2")
            s1 = B.save(self.rd, RID, items_of([d], base=1400), config=cfg, env=ENV)
            s2 = B.save(rd2, RID2, items_of([d], base=1401), config=cfg, env=ENV)
            s3 = B.save(rd2, RID2, items_of([d], base=1402), config=cfg, env=ENV, dedupe_same_bytes=False)
            put_storage_yaml(self.repo, storage_yaml(None, extra=""))      # временно без привязки — unsaved с тем же sha
            s4 = B.save(rd2, RID2, items_of([d], base=1403), config=R.load_repo_config(self.repo), env=ENV)
            cfg = self.cfg(fk)
            self.assertEqual(s4.results[0].state, "unsaved")
            rp = ["--repo", self.repo]
            rc, out, err, obj = cli(rp + ["key-paths", s1.staged[0]])
            self.assertEqual(rc, 0, out + err)
            want = sorted(os.path.relpath(x, self.repo).replace(os.sep, "/") for x in s1.staged + s2.staged + s3.staged)
            self.assertEqual(obj["paths"], want)
            self.assertEqual(obj["unsaved_same_sha256"], [os.path.relpath(s4.staged[0], self.repo).replace(os.sep, "/")])
            base = rp + ["withdraw-key-set", s1.staged[0], "--reason", "secret"]
            human = ["--withdraw-key-id-env", HUMAN["access_key_id"], "--withdraw-secret-env", HUMAN["secret_access_key"]]
            writer = ["--withdraw-key-id-env", S3_NAMES["access_key_id"], "--withdraw-secret-env", S3_NAMES["secret_access_key"]]
            snap = [read_bytes(os.path.join(self.repo, p)) for p in want]
            for extra, why in ((human, "без --confirm-withdraw"), (writer + ["--confirm-withdraw"], "ключ писателя")):
                rc, out, err, obj = cli(base + extra)
                with self.subTest(why=why):
                    self.assertEqual((rc, obj["error"]), (2, "input"))
                    self.assertEqual([read_bytes(os.path.join(self.repo, p)) for p in want], snap)
                    self.assertEqual([e for e in fk.state.log if e["method"] == "DELETE"], [])
            rc, out, err, obj = cli(base + human + ["--confirm-withdraw"])
            self.assertEqual(rc, 0, out + err)
            self.assert_schema_valid(obj)
            self.assertTrue(obj["complete"])
            self.assertEqual(sorted(os.path.relpath(x, self.repo).replace(os.sep, "/") for x in obj["staged"]), want)
            for p in want:
                f = pointer_fields(read_bytes(os.path.join(self.repo, p)))
                self.assertEqual((f["state"], f["reason"]), ("withdrawn", "secret"))
            self.assertNotIn(PREFIX + "sha256/" + sha(d), fk.state.objects)
            self.assertTrue(all(e["akid"] == WAKID for e in fk.state.log if e["method"] == "DELETE"))
            self.assertTrue(all(it["error"] is None and it["result"]["state"] == "withdrawn" for it in obj["results"]))


# ============================================================================ R1 Fable, F1: набор одного key судится целиком до DELETE
@per_provider
class R1KeySetJudgedBeforeDelete(Base):
    """Инвариант: ни одно необратимое действие (DELETE) не исполняется, пока весь набор не прошёл суд (грамматика пути,
    обычный файл, указатель stored | pending с этим key). Ошибка элемента — его результат (error), complete=false, rc 0."""

    def setup_set(self, fk):
        cfg = self.cfg(fk)
        d = os.urandom(THR + 41)
        s = B.save(self.rd, RID, items_of([d], base=8200), config=cfg, env=ENV)
        rd2 = os.path.join(self.repo, "docs", "r2")
        s2 = B.save(rd2, RID2, items_of([d], base=8201), config=cfg, env=ENV)
        return cfg, d, s.staged[0], s2.staged[0]

    def run_set(self, path):
        human = ["--withdraw-key-id-env", HUMAN["access_key_id"], "--withdraw-secret-env", HUMAN["secret_access_key"]]
        return cli(["--repo", self.repo, "withdraw-key-set", path, "--reason", "secret", "--confirm-withdraw"] + human)

    def assert_untouched(self, fk, d, paths, snap):
        self.assertEqual([e for e in fk.state.log if e["method"] == "DELETE"], [])
        self.assertIn(PREFIX + "sha256/" + sha(d), fk.state.objects)
        self.assertEqual([read_bytes(p) for p in paths], snap)

    def test_stray_name_blocks_whole_set(self):
        """Проба Fable: копия указателя под именем вне грамматики в attachments/<rid>/ — в наборе (по содержимому),
        суд её отвергает, DELETE не исполняется, законные указатели остаются stored при живом объекте."""
        with self.fake() as fk:
            cfg, d, p1, p2 = self.setup_set(fk)
            stray = os.path.join(os.path.dirname(p1), "zz-stray-copy.bin")
            shutil.copy(p1, stray)
            snap = [read_bytes(p) for p in (p1, p2, stray)]
            rc, out, err, obj = self.run_set(p1)
            self.assertEqual(rc, 0, out + err)
            self.assert_schema_valid(obj)
            self.assertFalse(obj["complete"])
            self.assertEqual(obj["staged"], [])
            bad = [it for it in obj["results"] if it["error"] is not None]
            self.assertEqual([it["path"].split("/")[-1] for it in bad], ["zz-stray-copy.bin"])
            self.assertTrue(all(it["result"] is None for it in obj["results"]))
            self.assertEqual(len(obj["results"]), 3)
            self.assert_untouched(fk, d, (p1, p2, stray), snap)

    def test_broken_pointer_naming_key_blocks(self):
        with self.fake() as fk:
            cfg, d, p1, p2 = self.setup_set(fk)
            broken = os.path.join(os.path.dirname(p1), uid(99) + ".bin")
            with open(broken, "wb") as f:
                f.write(read_bytes(p1).replace(b"\nstate stored\n", b"\nstate stored \n"))   # хвостовой пробел
            snap = [read_bytes(p) for p in (p1, p2, broken)]
            rc, out, err, obj = self.run_set(p1)
            self.assertEqual((rc, obj["complete"], obj["staged"]), (0, False, []))
            self.assertEqual([it["path"].split("/")[-1] for it in obj["results"] if it["error"]], [uid(99) + ".bin"])
            self.assert_untouched(fk, d, (p1, p2, broken), snap)

    def test_withdrawn_member_blocks(self):
        """Элемент, ставший withdrawn между сбором и судом (набор передан явно), — отказ элемента, DELETE нет."""
        with self.fake() as fk:
            cfg, d, p1, p2 = self.setup_set(fk)
            g = B.save(self.rd, RID, items_of([os.urandom(9)], base=8202), config=cfg, env=ENV).staged[0]
            C.withdraw(g, "erasure", cfg, HUMAN, env=ENV)
            snap = [read_bytes(p) for p in (p1, p2, g)]
            rels = sorted(os.path.relpath(x, self.repo).replace(os.sep, "/") for x in (p1, p2, g))
            res = R.withdraw_key_set(self.repo, p1, "secret", cfg, HUMAN, env=ENV, _candidates=rels)
            self.assertFalse(res["complete"])
            self.assertEqual([it["path"] for it in res["results"] if it["error"]],
                             [os.path.relpath(g, self.repo).replace(os.sep, "/")])
            self.assert_untouched(fk, d, (p1, p2, g), snap)

    def test_storage_refusal_before_first_delete_changes_nothing(self):
        with self.fake() as fk:
            cfg, d, p1, p2 = self.setup_set(fk)
            snap = [read_bytes(p) for p in (p1, p2)]
            fk.state.mode = {"err5xx"}
            rc, out, err, obj = self.run_set(p1)
            fk.state.mode = set()
            self.assertEqual((rc, obj["complete"], obj["staged"]), (0, False, []))
            self.assertEqual(obj["results"][0]["result"]["outcome"], "storage-unavailable")
            self.assertEqual(obj["results"][1]["detail"], "not-attempted")
            self.assertEqual([read_bytes(p) for p in (p1, p2)], snap)


# ============================================================================ R1 Fable, F2: байты очереди живут, пока их требует pending
@per_provider
class R1QueueHolders(Base):
    """Инвариант: байты в очереди живут, пока на них ссылается хоть один pending корпуса или незавершённый вызов
    (держатели FileQueue); pending без байтов доводится по факту объекта (confirm_pending: GET + sha256 → stored)."""

    def setUp(self):
        super().setUp()
        self.qdir = tempfile.mkdtemp(prefix="d20-t4-q-")
        self.q = B.FileQueue(self.qdir, env={})

    def tearDown(self):
        shutil.rmtree(self.qdir, ignore_errors=True)
        super().tearDown()

    def release_all(self, saved):
        for r in saved.queue_release:
            self.q.release(r["sha256"], r["holder"])

    def test_fable_scenario_and_permutations(self):
        """Вызов 1 [A] под 5xx → pending (держатель 1); вызов 2 [A] (другое сообщение) → stored → release держателя 2 —
        байты A ОСТАЮТСЯ (pending 1 их требует); довод pending 1 из очереди → stored; release держателя 1 → байты сняты.
        Перестановки порядка «release 2 / довод 1 / release 1» — во всех байты не теряются, пока жив pending."""
        orders = (("rel2", "complete1", "rel1"), ("complete1", "rel2", "rel1"), ("complete1", "rel1", "rel2"))
        for n, order in enumerate(orders):
            with self.fake() as fk:
                cfg = self.cfg(fk)
                a = os.urandom(THR + 51 + n)
                fk.state.mode = {"err5xx"}
                s1 = B.save(self.rd, RID, items_of([a], base=8300 + 10 * n), config=cfg, env=ENV, queue=self.q)
                fk.state.mode = set()
                self.assertEqual(s1.results[0].state, "pending")
                s2 = B.save(self.rd, RID, items_of([a], base=8301 + 10 * n), config=cfg, env=ENV, queue=self.q)
                self.assertEqual(s2.results[0].state, "stored")
                p1 = s1.staged[0]
                for k, step in enumerate(order):
                    with self.subTest(order=order, step=step):
                        if step == "rel2":
                            self.release_all(s2)
                            if "complete1" not in order[:k]:      # pending 1 жив — байты обязаны остаться
                                self.assertEqual(self.q.get(sha(a)), a, "pending 1 ещё требует байты")
                        elif step == "complete1":
                            w = B.complete_from_queue(p1, self.q, cfg, env=ENV)
                            self.assertEqual(w.state, "stored")
                        else:
                            self.q.release(sha(a), p1)
                self.assertIsNone(self.q.get(sha(a)), "все держатели сняты — байты удалены")
                self.assertEqual(os.listdir(self.qdir), [])

    def test_pending_without_bytes_confirmed_by_object(self):
        with self.fake() as fk:
            cfg = self.cfg(fk)
            a = os.urandom(THR + 61)
            fk.state.mode = {"err5xx"}
            s1 = B.save(self.rd, RID, items_of([a], base=8400), config=cfg, env=ENV, queue=self.q)
            fk.state.mode = set()
            p1 = s1.staged[0]
            os.remove(os.path.join(self.qdir, sha(a)))                     # байты потеряны (сбой, чужое снятие)
            w = B.complete_from_queue(p1, self.q, cfg, env=ENV)           # объекта нет — pending не меняется
            self.assertEqual((w.state, w.outcome), ("pending", "storage-denied" if self.PROVIDER == "aws-no-list" else None))
            self.assertEqual(pointer_fields(read_bytes(p1))["state"], "pending")
            fk.state.objects[PREFIX + "sha256/" + sha(a)] = b"x" * len(a)  # чужие байты той же длины — не довод
            self.assertEqual(B.complete_from_queue(p1, self.q, cfg, env=ENV).detail, "object-differs")
            fk.state.objects[PREFIX + "sha256/" + sha(a)] = a              # объект загружен другим вызовом
            before = read_bytes(p1)
            w = B.complete_from_queue(p1, self.q, cfg, env=ENV)
            self.assertEqual((w.state, w.outcome), ("stored", "already-present"))
            self.assertEqual(read_bytes(p1), before.replace(b"\nstate pending\n", b"\nstate stored\n", 1))

    def test_unfinished_call_holder_keeps_bytes(self):
        """Держатель, чей файл ещё не записан (незавершённый вызов), байты держит при чужом release."""
        a = os.urandom(THR + 71)
        h1 = os.path.join(self.rd, "attachments", RID, uid(71) + ".bin")
        h2 = os.path.join(self.rd, "attachments", RID, uid(72) + ".bin")
        self.q.put(sha(a), a, h1)
        self.q.put(sha(a), a, h2)
        self.assertFalse(self.q.release(sha(a), h2))
        self.assertEqual(self.q.get(sha(a)), a)
        self.assertEqual(self.q.holders(sha(a)), [h1])
        self.assertRaises(C.AttachInputError, self.q.put, sha(a), a, "relative/path")


class R1StagedAbsolute(Base):
    def test_relative_record_dir_gives_absolute_staged(self):
        here = os.getcwd()
        os.chdir(self.repo)
        try:
            s = B.save(os.path.relpath(self.rd, self.repo), RID, items_of([os.urandom(5), os.urandom(6)], base=8500),
                       config=C.load_config({}), env=ENV)
        finally:
            os.chdir(here)
        self.assertTrue(all(os.path.isabs(x) and os.path.isfile(x) for x in s.staged))
        self.assertTrue(all(os.path.isabs(x) for r in s.results for x in r.staged))


# ============================================================================ (г) комплект: раскладка и работа из РАЗЛОЖЕННОГО
def laid_repo():
    repo = tempfile.mkdtemp(prefix="d20-t4-cust-")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-q", "--allow-empty",
                    "-m", "base"], check=True)
    # D10 T24: слой заказчика живёт в его репозитории; комплект монорепо собран под синтетический образец — его и кладём
    # (манифест, собранный под образец, несёт привязку customer_layer, и layout сверяет её со слоем клона)
    os.makedirs(os.path.join(repo, ".workshop-ai"))
    shutil.copy(os.path.join(_KIT, "ai", "customer-layer.example.yaml"), os.path.join(repo, ".workshop-ai", "customer-layer.yaml"))
    r = subprocess.run([PY, os.path.join(_KIT, "install.py"), "--kit", _KIT, "--repo", repo, "layout",
                        "--allow-unfilled-pins"], env=env_all(), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return repo


@per_provider
class KitFromLaid(unittest.TestCase):
    PROVIDER = "yandex"

    def setUp(self):
        self.repo = laid_repo()
        self.inst = os.path.join(self.repo, ".workshop", "bot", "kit", "install.py")
        self.entry = [PY, os.path.join(self.repo, ".workshop", "bot", "attach")]

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def run_inst(self, cmd, env):
        r = subprocess.run([PY, self.inst, cmd], cwd=self.repo, env=env, capture_output=True, text=True, timeout=120)
        OUTPUTS.append(("laid " + cmd, r.stdout + r.stderr))
        return r.returncode, r.stdout + r.stderr

    def test_package_laid_byte_equal_without_tools(self):
        man = pyyaml(os.path.join(_KIT, "manifest.yaml"))
        dsts = {e["dst"]: e for e in man["entries"]}
        src_py = sorted(f for f in os.listdir(os.path.join(_BOT, "attach")) if f.endswith(".py"))
        for f in src_py:
            d = ".workshop/bot/attach/" + f
            self.assertIn(d, dsts)
            self.assertEqual(dsts[d]["role"], "code")
            self.assertEqual(read_bytes(os.path.join(self.repo, d)), read_bytes(os.path.join(_BOT, "attach", f)))
        laid = sorted(os.listdir(os.path.join(self.repo, ".workshop", "bot", "attach")))
        self.assertEqual([x for x in laid if x != "__pycache__"], src_py)
        self.assertFalse(any("gen_attach_norm" in d for d in dsts))
        self.assertFalse(any(d.endswith(".json") for d in dsts if "/attach/" in d))

    def test_storage_commands_and_cli_from_laid_kit(self):
        with make_fake(self.PROVIDER) as fk:
            base = ("storage:\n  endpoint: %s\n  region: us-east-1\n  bucket: %s\n  allow_insecure_http: true\n"
                    "  timeout_s: 2\n" % (fk.endpoint, fk.state.bucket)).encode("ascii")
            put_storage_yaml(self.repo, base)
            del fk.state.objects[PREFIX + CANARY]
            rc, out = self.run_inst("storage-init", env_all())
            self.assertEqual(rc, 0, out)
            self.assertNotIn("адаптер вложений", out)
            self.assertIn("storage_probe_outcome: ok", out)
            rc, out = self.run_inst("storage-status", env_all())
            self.assertEqual(rc, 0, out)
            rc, out = self.run_inst("check-secrets", env_all(storage=False))
            self.assertEqual(rc, 2, out)
            for n in S3_NAMES.values():
                self.assertIn(n, out)
            rc, out = self.run_inst("check-secrets", env_all())
            self.assertEqual(rc, 0, out)
            # CLI из разложенного комплекта: запись, чтение, статус — без PYTHONPATH, cwd = корень репозитория
            rd = os.path.join(self.repo, "tickets", "r")
            os.makedirs(rd)
            dp = os.path.join(self.repo, "..", os.path.basename(self.repo) + "-data.bin")
            with open(dp, "wb") as f:
                f.write(os.urandom(9_000_000))
            try:
                rc, out, err, w = cli(["write", "--record-dir", rd, "--record-id", RID, "--uuid", uid(1), "--ext", "bin",
                                       "--source", SRC % 1, "--data", dp], env=env_all(), cwd=self.repo, entry=self.entry)
            finally:
                os.remove(dp)
            self.assertEqual(rc, 0, out + err)
            self.assertEqual((w["state"], w["outcome"]), ("stored", "uploaded"))
            for args, cmd in ((["read", w["staged"][0]], "read"), (["status", "--verify"], "status"), (["probe"], "probe")):
                rc, out, err, obj = cli(args, env=env_all(), cwd=self.repo, entry=self.entry)
                with self.subTest(cmd=cmd):
                    self.assertEqual(rc, 0, out + err)
                    self.assertEqual(validate(obj, SCHEMA, SCHEMA), [])
            self.assertEqual(obj["storage_probe_outcome"], "ok")
            rc, out, err, obj = cli(["status"], env=env_all(), cwd=self.repo, entry=self.entry)
            self.assertEqual(obj["pointers_by_state"]["stored"], 1)
            # `python3 -m attach` из .workshop/bot — тот же пакет
            r = subprocess.run([PY, "-m", "attach", "--json", "schema"], cwd=os.path.join(self.repo, ".workshop", "bot"),
                               env=env_all(), capture_output=True)
            self.assertEqual(r.stdout, read_bytes(SCHEMA_FILE))

    def test_laid_cli_does_not_shadow_stdlib(self):
        """Каталог пакета как скрипт: модули пакета не видны верхним уровнем, bot/ — в конце sys.path."""
        probe = ("import runpy, sys\nsys.argv = ['attach', '--json', 'probe']\n"
                 "try:\n    runpy.run_path(%r, run_name='__main__')\nexcept SystemExit:\n    pass\n"
                 "import secrets\nprint('STDLIB-SECRETS' if hasattr(secrets, 'token_hex') else 'SHADOWED')\n"
                 "print('PKG-DIR-IN-PATH' if any(p.rstrip('/').endswith('/attach') for p in sys.path) else 'CLEAN')\n"
                 % os.path.join(self.repo, ".workshop", "bot", "attach"))
        r = subprocess.run([PY, "-c", probe], cwd=self.repo, env=env_all(), capture_output=True, text=True)
        self.assertIn("STDLIB-SECRETS", r.stdout, r.stdout + r.stderr)
        self.assertIn("CLEAN", r.stdout)


class WorkflowSecretsBinding(unittest.TestCase):
    """S3-секреты привязаны по реестру install-steps.yaml: в bootstrap и poller — env-привязки ровно имён реестра,
    в примере окружения демона — строки имён; вторых копий имён (иных, чем реестр) нет."""

    def test_wrappers_bind_registry_names(self):
        names = set(s["name"] for s in REG["secrets"])
        for wf in ("bootstrap.yml", "poller.yml"):
            doc = pyyaml(os.path.join(_KIT, "workflows", wf))
            env = doc["env"]
            with self.subTest(wf=wf):
                self.assertEqual(set(env), names)
                for k, v in env.items():
                    self.assertEqual(v, "${{ secrets.%s }}" % k)
                r = subprocess.run([PY, os.path.join(_KIT, "wrapper_predicate.py"), os.path.join(_KIT, "workflows", wf),
                                    "--contract", os.path.join(_ROOT, "spec", "09-tg-bot-time-line", "tg-bot.yaml"),
                                    "--require-hooks-path"], capture_output=True, text=True)
                self.assertIn("structure: PASS", r.stdout, r.stdout + r.stderr)

    def test_daemon_env_example(self):
        raw = read_bytes(os.path.join(_KIT, "daemon", "env.workshop.example")).decode("utf-8")
        keys = [l.split("=")[0] for l in raw.split("\n") if l and not l.startswith("#")]
        self.assertTrue(set(S3_NAMES.values()) <= set(keys))
        self.assertTrue(set(keys) <= set(s["name"] for s in REG["secrets"]))
        self.assertTrue(all(l.endswith("=") for l in raw.split("\n") if l and not l.startswith("#")), "значений нет")


# ============================================================================ (д) сетевой профиль: независимый сканер
def _scanner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("net_profile_scan", os.path.join(_ROOT, "harness", "net_profile_scan.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class NetworkProfileScan(unittest.TestCase):
    def setUp(self):
        self.m = _scanner()
        self.root = tempfile.mkdtemp(prefix="d20-t4-np-")
        shutil.copytree(_BOT, os.path.join(self.root, "bot"), ignore=shutil.ignore_patterns("__pycache__", "tests"))
        os.makedirs(os.path.join(self.root, "spec", "03-spec-type-schemas"))
        shutil.copy(NORM_PATH, os.path.join(self.root, "spec", "03-spec-type-schemas"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _append(self, rel, text):
        with open(os.path.join(self.root, rel), "a", encoding="utf-8") as f:
            f.write(text)

    def test_clean_tree_passes(self):
        _h, v, unused = self.m.static_scan(self.root)
        self.assertEqual((v, unused), ([], []))
        self.assertEqual(self.m.norm_lfs_signature(self.root), NORM["lfs"]["signature_prefix"])

    def test_storage_host_literals_rejected(self):
        for rel, text in (("bot/attach/s3.py", '\nDEFAULT = "https://storage.yandexcloud.net"\n'),
                          ("bot/attach/core.py", '\nHOST = "s3.amazonaws.com"\n'),
                          ("bot/poll.py", "\n# endpoint: https://abc.r2.cloudflarestorage.com\n"),
                          ("bot/attach/repo.py", '\nX = f"https://{b}.storage.googleapis.com"\n')):
            shutil.copy(os.path.join(_BOT, *rel.split("/")[1:]), os.path.join(self.root, rel))
            self._append(rel, text)
            _h, v, _u = self.m.static_scan(self.root)
            with self.subTest(rel=rel):
                self.assertTrue(v, text)
            shutil.copy(os.path.join(_BOT, *rel.split("/")[1:]), os.path.join(self.root, rel))

    def test_r1_fable_mutations_all_text_files(self):
        """R1: скан по ВСЕМ текстовым файлам комплекта, без учёта регистра, конкатенация, конечная метка вне любого
        перечня (не слово кода) — каждая мутация Fable ловится; копия восстанавливается после каждой."""
        cases = (("bot/kit/templates/storage.yaml", "\n#   endpoint: https://storage.yandexcloud.net\n"),
                 ("bot/kit/templates/storage.yaml", "\n#   endpoint: storage.yandexcloud.net\n"),
                 ("bot/kit/daemon/entrypoint.sh", "\nS3_HOST=s3.amazonaws.com\n"),
                 ("bot/kit/install-steps.yaml", "\n# endpoint: https://hb.vkcs.cloud\n"),
                 ("bot/kit/install-steps.yaml", "\n# пример: objects.provider.museum\n"),
                 ("bot/attach/s3.py", '\nX = "HTTPS://STORAGE.YANDEXCLOUD.NET"\n'),
                 ("bot/attach/s3.py", '\nX = "Storage.YandexCloud.Net"\n'),
                 ("bot/attach/s3.py", '\nX = "storage." + "yandexcloud" + ".net"\n'),
                 ("bot/attach/core.py", '\nX = "https://" + "files" + ".myprovider.online"\n'),
                 ("bot/attach/core.py", '\nX = "s3.provider.kz"\n'),
                 ("bot/poll.py", '\nX = "https://%s.objstore.zz/" % b\n'),
                 ("bot/kit/docs/bot-user-guide.ru.md", "\nХранилище: https://s3.example-storage.app/bucket\n"),
                 ("bot/kit/workflows/poller.yml", "\n# curl https://minio.corp.lan:9000\n"))
        for rel, text in cases:
            src = os.path.join(self.root, rel)
            orig = read_bytes(src)
            self._append(rel, text)
            _h, v, _u = self.m.static_scan(self.root)
            with self.subTest(rel=rel, text=text.strip()):
                self.assertTrue(v, text)
            with open(src, "wb") as f:
                f.write(orig)
        self.assertEqual(self.m.static_scan(self.root)[1], [])      # чистый артефакт — ложных срабатываний нет

    def test_r1_runtime_udp_and_subprocess_rejected(self):
        """Аудит-хук слышит UDP sendto и запуск процесса: мутант адаптера, делающий их в _client, отвергнут."""
        root = tempfile.mkdtemp(prefix="d20-t4-rt-")
        try:
            shutil.copytree(_BOT, os.path.join(root, "bot"), ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(os.path.join(_ROOT, "spec", "03-spec-type-schemas"),
                            os.path.join(root, "spec", "03-spec-type-schemas"))
            core = os.path.join(root, "bot", "attach", "core.py")
            orig = read_bytes(core).decode("utf-8")
            anchor = "def _client(binding, creds):\n"
            for label, inject in (
                    ("udp", "    import socket as _so\n    _so.socket(_so.AF_INET, _so.SOCK_DGRAM).sendto(b'x', ('127.0.0.1', 9))\n"),
                    ("subprocess", "    import subprocess as _sp\n    _sp.run(['true'])\n"),
                    ("os.system", "    import os as _o\n    _o.system('true')\n")):
                with open(core, "wb") as f:
                    f.write(orig.replace(anchor, anchor + inject, 1).encode("utf-8"))
                ok, lines = self.m.runtime(root)
                with self.subTest(mutant=label):
                    self.assertFalse(ok, "\n".join(lines))
            with open(core, "wb") as f:
                f.write(orig.encode("utf-8"))
            ok, lines = self.m.runtime(root)
            self.assertTrue(ok, "\n".join(lines))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_allowlist_is_exact_and_used(self):
        rel = "bot/attach/norm.py"
        self._append(rel, '\nOTHER = "https://git-lfs.github.com/other"\n')
        _h, v, _u = self.m.static_scan(self.root)
        self.assertTrue(v)                       # тот же хост вне литерала аллоулиста — нарушение
        shutil.copy(os.path.join(_BOT, "attach", "norm.py"), os.path.join(self.root, rel))
        allow = (("bot/attach/norm.py", "version https://git-lfs.github.com/spec/v2", "x"),)
        _h, v, unused = self.m.static_scan(self.root, allowlist=allow)
        self.assertTrue(v and unused)            # литерал аллоулиста не совпал — и нарушение, и устаревшая запись

    def test_reserved_names_and_identifiers_are_not_hosts(self):
        self._append("bot/attach/core.py", '\nZ = "https://x.example.invalid"  # self.host api.telegram.org\n')
        _h, v, _u = self.m.static_scan(self.root)
        self.assertEqual(v, [])

    def test_runtime_endpoint_from_config_and_negative_control(self):
        ok, lines = self.m.runtime(_ROOT)
        self.assertTrue(ok, "\n".join(lines))

    def test_judge_rejects_host_not_from_config(self):
        allowed, hosts = {("127.0.0.1", 9000), ("api.telegram.org", 443)}, {"127.0.0.1", "api.telegram.org"}
        self.assertEqual(self.m.judge([("connect", "127.0.0.1", 9000), ("getaddrinfo", "127.0.0.1", 9000)], allowed, hosts), [])
        self.assertTrue(self.m.judge([("connect", "127.0.0.1", 9001)], allowed, hosts))
        self.assertTrue(self.m.judge([("getaddrinfo", "storage.yandexcloud.net", 443)], allowed, hosts))


# ============================================================================ краевая локаль
class EdgeLocale(Base):
    def test_locales(self):
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)
            p = C.write_attachment(self.rd, RID, os.urandom(THR + 3), ext="bin", config=cfg, uuid=uid(1),
                                   source=SRC % 1, env=ENV).staged[0]
            for loc in ("C", "POSIX", "tr_TR.UTF-8", "ar_SA.UTF-8"):
                env = dict(ENV, LC_ALL=loc, LANG=loc)
                env.pop("PYTHONIOENCODING", None)
                for args in (["--repo", self.repo, "read", p], ["--repo", self.repo, "status"], ["read", "/nonexistent/x"]):
                    rc, out, err, obj = cli(args, env=env)
                    with self.subTest(loc=loc, args=args[-1]):
                        self.assertIn(rc, (0, 2))
                        self.assertEqual(validate(obj, SCHEMA, SCHEMA), [])
                        self.assertNotIn("Traceback", err)
                    rc, out, err, _ = cli(args, env=env, json_mode=False)
                    self.assertNotIn("Traceback", err)


# ============================================================================ секреты: положительный контракт
class ZZSecretsOverAllOutputs(Base):
    """Последний класс модуля: ни одно значение SYNTH (ключ писателя, ключ человека, префикс) не встречается ни в одном
    выводе CLI и установщика модуля (OUTPUTS), ни в repr результатов API; плюс отражение сервером (echo)."""

    def test_server_echo_and_api_repr(self):
        with make_fake("yandex") as fk:
            cfg = self.cfg(fk)
            s = B.save(self.rd, RID, items_of([os.urandom(THR + 9)], base=9000), config=cfg, env=ENV)
            fk.state.echo = (PREFIX + AKID, SECRET + WSECRET)
            for st in (403, 503):
                fk.state.echo_status = st
                for args in (["--repo", self.repo, "read", s.staged[0]], ["--repo", self.repo, "status", "--verify"],
                             ["--repo", self.repo, "probe"]):
                    cli(args)
                    cli(args, json_mode=False)
            texts = [repr(s.as_dict()), repr(B.status(self.repo, cfg, env=ENV, verify=True)), repr(cfg.binding)]
            for t in texts:
                for v in SYNTH:
                    self.assertNotIn(v, t)

    def test_zz_all_outputs(self):
        self.assertTrue(len(OUTPUTS) >= 12, len(OUTPUTS))
        for name, text in OUTPUTS:
            for v in SYNTH:
                self.assertNotIn(v, text, name)


if __name__ == "__main__":
    unittest.main()
