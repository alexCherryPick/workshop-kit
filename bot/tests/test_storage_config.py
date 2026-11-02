# -*- coding: utf-8 -*-
"""Оракул конфига хранилища вложений в комплекте (D20 T3): шаблон .workshop/storage.yaml, install.py storage-init /
storage-status / check-secrets, сохранение конфига при обновлении комплекта.

Что доказывается (бриф T3 §0): на этом входе конфиг заказчика устанавливается, проверяется и переживает обновление
комплекта без потерь — (а) факты и отказы с причиной, (б) key_prefix создаётся ровно один раз, (в) канарейка
идемпотентна, исходы — исходы адаптера, (г) значения ключей нигде, кроме окружения, (д) обновление сохраняет конфиг
побайтово, (е) без хранилища комплект работает.

ОРАКУЛ ОТДЕЛЬНО ОТ ПИСАТЕЛЯ: установщик гоняется ПРОЦЕССОМ; конфиг, реестр, шаблон и норму оракул разбирает PyYAML
(писатель — yamlmini); «неизменен» и «только дописано» — сравнение БАЙТ файла (sha256, difflib по строкам-байтам без
strip/splitlines-текста); префикс — регулярное выражение над байтами; хранилище — фейк T2 (fake_s3: своя SigV4, без
импорта attach). Секреты — положительный контракт на ЗАКРЫТОМ множестве синтетических значений (SYNTH): ни одно не
встречается ни в одном выводе, ни в файле конфига, ни в истории git."""
import difflib
import hashlib
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import yaml

_TESTS = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.dirname(_TESTS)
_ROOT = os.path.dirname(_BOT)
_KIT = os.path.join(_BOT, "kit")
sys.path.insert(0, _TESTS)
sys.path.insert(0, _BOT)
import fake_s3  # noqa: E402
import attach.core as attach  # noqa: E402  (только для сверки «реестры из источника» и маршрута без хранилища)

PY = sys.executable
INSTALL = os.path.join(_KIT, "install.py")
TEMPLATE = os.path.join(_KIT, "templates", "storage.yaml")
STEPS = os.path.join(_KIT, "install-steps.yaml")
NORM_PATH = os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml")
CONFIG_REL = ".workshop/storage.yaml"


def pyyaml(path_or_bytes):
    if isinstance(path_or_bytes, bytes):
        return yaml.safe_load(path_or_bytes.decode("utf-8"))
    with open(path_or_bytes, "rb") as f:
        return yaml.safe_load(f.read().decode("utf-8"))


NORM = pyyaml(NORM_PATH)
REG = pyyaml(STEPS)
S3_SECRETS = [s for s in REG["secrets"] if "storage_credential" in s]
S3_NAMES = {s["storage_credential"]: s["name"] for s in S3_SECRETS}          # из реестра — единственный адрес имён
OTHER_SECRETS = [s["name"] for s in REG["secrets"] if s.get("required")]

# Закрытое множество синтетических значений (положительный контракт секретов). Префиксы, созданные установщиком
# в прогонах, дописываются в CREATED_PREFIXES и проверяются тем же контрактом.
AKID = "AKIDSYNTH0T3Q7W3E9R1"
SECRET = "synthSECRET-t3+Zq8Lm3Np5Rv7Tx9Bc1Df4Gh6Jk/unique"
OTHER_VALUE = "synth-other-ci-secret-t3-value"
SYNTH = (AKID, SECRET, OTHER_VALUE)
CREATED_PREFIXES = []
OUTPUTS = []                       # (test id, вывод) всех прогонов модуля — для сквозной проверки контракта
WRITER_PERMS = {"HEAD", "GET", "PUT"}    # права ключа писателя PadelApp: put/get/head, без list и delete
PREFIX_RE = re.compile(rb'\n {2,}key_prefix: "([0-9a-f]{32}/)"\n')
PROVIDERS = fake_s3.PROVIDERS


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def base_env(storage_secrets=True, others=True, partial=False):
    # PYTHONPATH прогона (selfcheck_t1 ставит bot/ монорепо) не наследуется: установщик у заказчика его не имеет, а
    # с ним копия комплекта без пакета attach видела бы адаптер монорепо (ложный зелёный/красный порядка до T4)
    env = {k: v for k, v in os.environ.items() if not k.startswith("WORKSHOP_") and k != "PYTHONPATH"}
    if others:
        for n in OTHER_SECRETS:
            env[n] = OTHER_VALUE
    if storage_secrets:
        env[S3_NAMES["access_key_id"]] = AKID
        if not partial:
            env[S3_NAMES["secret_access_key"]] = SECRET
    return env


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)


def new_repo():
    r = tempfile.mkdtemp(prefix="d20-t3-repo-")
    git(r, "init", "-q")
    git(r, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-q", "--allow-empty", "-m", "base")
    return r


def uncommented_template(endpoint, bucket, extra=(), region="us-east-1"):
    """Заказчик по шагу storage_binding: раскомментировать блок шаблона и вписать эндпоинт, регион, бакет. Блок —
    строки шаблона, начиная с `# storage:`; значения примера заменяются. Шаблон в остальном — байты как есть."""
    raw = read_bytes(TEMPLATE)
    lines = raw.split(b"\n")
    i = lines.index(b"# storage:")
    out = lines[:i] + [b"storage:"]
    for l in lines[i + 1:]:
        if l.startswith(b"#   "):
            k = l[4:].split(b":")[0]
            v = {b"endpoint": endpoint.encode(), b"bucket": bucket.encode(), b"region": region.encode()}.get(k)
            out.append(b"  " + (k + b": " + v if v is not None else l[4:]))
        else:
            out.append(l)
    body = b"\n".join(out)
    if not body.endswith(b"\n"):
        body += b"\n"
    return body + b"".join(b"  " + e.encode() + b"\n" for e in extra)


class Run(object):
    def __init__(self, tc, repo, kit=_KIT):
        self.tc, self.repo, self.kit = tc, repo, kit

    def __call__(self, cmd, env=None, extra=(), post=()):
        argv = [PY, os.path.join(self.kit, "install.py"), "--kit", self.kit, "--repo", self.repo] + list(extra) + [cmd] + list(post)
        p = subprocess.run(argv, env=env if env is not None else base_env(), capture_output=True, text=True, timeout=120)
        out = p.stdout + p.stderr
        OUTPUTS.append((self.tc.id(), cmd, out))
        return p.returncode, out


def config_path(repo):
    return os.path.join(repo, ".workshop", "storage.yaml")


def put_config(repo, data):
    os.makedirs(os.path.join(repo, ".workshop"), exist_ok=True)
    with open(config_path(repo), "wb") as f:
        f.write(data)


def make_fake(provider, **kw):
    return fake_s3.FakeS3(keys={AKID: SECRET}, perms={AKID: set(WRITER_PERMS)}, provider=provider, **kw)


def customer_config(fk, extra=("allow_insecure_http: true", "timeout_s: 2")):
    """Фейк — http на loopback: allow_insecure_http — факт T2 только для локального фейка."""
    return uncommented_template(fk.endpoint, fk.state.bucket, extra=extra)


def only_insertions(old, new):
    """Оракул «прежние байты не тронуты»: по строкам-байтам (разрез по LF, без strip) — только операции insert."""
    a, b = old.split(b"\n"), new.split(b"\n")
    ops = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
    inserted = [l for tag, _i1, _i2, j1, j2 in ops if tag == "insert" for l in b[j1:j2]]
    return all(tag in ("equal", "insert") for tag, *_ in ops), inserted


def per_provider(cls):
    """Классы с фейком гоняются во всех режимах провайдера T2 (aws-no-list, aws-list, yandex)."""
    for prov in PROVIDERS:
        name = "%s_%s" % (cls.__name__, prov.replace("-", "_"))
        globals()[name] = type(name, (cls,), {"PROVIDER": prov, "__module__": cls.__module__})
    return None


class Base(unittest.TestCase):
    PROVIDER = "yandex"

    def setUp(self):
        self.repo = new_repo()
        self.run_ = Run(self, self.repo)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def fake(self, **kw):
        return make_fake(self.PROVIDER, **kw)

    def prefix_of(self, raw=None):
        raw = read_bytes(config_path(self.repo)) if raw is None else raw
        m = PREFIX_RE.findall(raw)
        self.assertEqual(len(m), 1, "ровно одна строка key_prefix")
        p = m[0].decode("ascii")
        CREATED_PREFIXES.append(p)
        self.assertEqual(pyyaml(raw)["storage"]["key_prefix"], p)        # независимый разбор согласен с байтами
        return p


# ============================================================================ реестры из источника (пре-флайт §2)
class RegistriesFromSource(unittest.TestCase):
    def test_template_facts_match_norm_and_adapter(self):
        """Шаблон ↔ норма (storage_binding.config_facts) ↔ адаптер (attach._SCHEMA): ни одного факта вне схемы,
        активных фактов в шаблоне нет (хранилище не настроено), блок примера + дописываемое установщиком
        покрывает факты нормы, кроме порога (у него умолчание нормы)."""
        self.assertIsNone(pyyaml(TEMPLATE), "в шаблоне нет ни одного активного факта")
        norm_facts = [f["fact"] for f in NORM["storage_binding"]["config_facts"]]
        self.assertEqual(set(norm_facts), set(attach.N.CONFIG_FACTS))
        self.assertTrue(set(norm_facts) <= set(attach._SCHEMA))
        example = pyyaml(uncommented_template("https://storage.example.invalid", "b"))
        flat = set("storage." + k for k in example["storage"]) | set(k for k in example if k != "storage")
        self.assertTrue(flat <= set(attach._SCHEMA), flat - set(attach._SCHEMA))
        installer_adds = {"storage.credentials", "storage.key_prefix", "storage.canary_key"}
        self.assertTrue(installer_adds <= set(attach._SCHEMA))
        self.assertEqual(set(norm_facts) - flat - installer_adds, {"git_threshold_bytes"})
        # пример шаблона с дописанным установщиком принимается адаптером
        m = dict(example)
        m["storage"] = dict(example["storage"], credentials=dict(S3_NAMES), key_prefix="0" * 32 + "/",
                            canary_key="workshop-canary")
        self.assertIsNotNone(attach.load_config(m).binding)

    def test_registry_storage_secrets_and_step(self):
        self.assertEqual(set(S3_NAMES), set(attach._CRED_KEYS))
        self.assertEqual(len(S3_SECRETS), len(attach._CRED_KEYS))
        for s in S3_SECRETS:
            self.assertTrue(attach._ENV_NAME_RE.fullmatch(s["name"]))
            self.assertFalse(s["required"])
            self.assertEqual(s["required_when"], "storage_configured")
        step = [s for s in REG["steps"] if s["id"] == "storage_binding"]
        self.assertEqual(len(step), 1)
        self.assertEqual(set(step[0]["required_secrets"]), set(S3_NAMES.values()))
        wv = REG["when_values"]
        self.assertEqual(wv[step[0]["when"]]["secrets_required_when"], "storage_configured")
        self.assertTrue(all(s["when"] in wv for s in REG["steps"]))
        for word in ("приватный", "без версионирования", "без list и без delete"):
            self.assertIn(word, step[0]["guide"].replace("\n", " ").replace("ПРИВАТНЫЙ", "приватный"))

    def test_build_help_reads_registry_and_prints_n(self):
        p = subprocess.run([PY, os.path.join(_KIT, "build_help.py"), "count-steps"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        n = int(p.stdout.strip())
        self.assertEqual(n, len(REG["steps"]))
        p = subprocess.run([PY, os.path.join(_KIT, "build_help.py"), "steps-block"], capture_output=True, text=True)
        for name in S3_NAMES.values():
            self.assertIn("`%s`" % name, p.stdout)
        self.assertIn(REG["when_values"]["storage_optional"]["label"], p.stdout)
        self.assertIn(REG["when_values"]["groups_only"]["label"], p.stdout)
        # значение when вне when_values — отказ генератора, не молчаливая метка
        tmp = tempfile.mkdtemp()
        try:
            bad = os.path.join(tmp, "steps.yaml")
            with open(bad, "wb") as f:
                f.write(read_bytes(STEPS) + b"  - id: zz\n    title: z\n    when: zz_unknown\n    guide: z\n    verified_by: z\n")
            p = subprocess.run([PY, os.path.join(_KIT, "build_help.py"), "steps-block", "--steps", bad],
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("zz_unknown", p.stdout + p.stderr)
        finally:
            shutil.rmtree(tmp)

    def test_manifest_role_config_and_in_sync(self):
        p = subprocess.run([PY, os.path.join(_KIT, "build_manifest.py")], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        doc = yaml.safe_load(p.stdout)
        e = [x for x in doc["entries"] if x["src"] == "bot/kit/templates/storage.yaml"]
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["dst"], e[0]["role"]), (CONFIG_REL, "config"))
        self.assertEqual(e[0]["sha256"], sha(read_bytes(TEMPLATE)))
        self.assertEqual(p.stdout.encode("utf-8"), read_bytes(os.path.join(_KIT, "manifest.yaml")),
                         "манифест в дереве == генерация")

    def test_host_hard_limit_from_norm(self):
        note = NORM["soft_limit"]["host_hard_limit_note"]
        self.assertIn("100 МиБ", note)
        src = read_bytes(INSTALL).decode("utf-8")
        self.assertIn("GIT_HOST_FILE_LIMIT = 100 * 1024 * 1024", src)


# ============================================================================ (е) без хранилища
class WithoutStorage(Base):
    def test_no_file_status_and_init_rc0_no_network(self):
        for cmd in ("storage-status", "storage-init"):
            rc, out = self.run_(cmd, env=base_env(storage_secrets=False))
            self.assertEqual(rc, 0, out)
            self.assertIn("хранилище не настроено — вложения выше порога: unsaved no-storage", out)
        self.assertFalse(os.path.exists(config_path(self.repo)))

    def test_template_as_laid_is_not_configured_and_untouched(self):
        put_config(self.repo, read_bytes(TEMPLATE))
        for cmd in ("storage-status", "storage-init", "storage-init"):
            rc, out = self.run_(cmd, env=base_env(storage_secrets=False))
            self.assertEqual(rc, 0, out)
            self.assertIn("хранилище не настроено", out)
            self.assertEqual(read_bytes(config_path(self.repo)), read_bytes(TEMPLATE))

    def test_routing_without_storage_follows_norm(self):
        cfg = attach.load_config(pyyaml(read_bytes(TEMPLATE)) or {})
        self.assertIsNone(cfg.binding)
        thr = cfg.git_threshold_bytes
        self.assertEqual(thr, NORM["soft_limit"]["bytes"])
        r = attach.route(thr + 1, cfg)
        self.assertEqual((r.target, r.reason), ("unsaved", "no-storage"))
        self.assertEqual(attach.route(thr, cfg).target, "git")

    def test_check_secrets_does_not_require_s3_when_not_configured(self):
        for content in (None, read_bytes(TEMPLATE), b"storage:\n  endpoint: https://h.example.invalid\n"):
            if content is not None:
                put_config(self.repo, content)
            rc, out = self.run_("check-secrets", env=base_env(storage_secrets=False))
            self.assertEqual(rc, 0, out)
            self.assertIn("не требуется", out)
            for n in S3_NAMES.values():
                self.assertIn("secret %s: absent" % n, out)

    def test_threshold_above_host_limit_warns(self):
        put_config(self.repo, b"git_threshold_bytes: 104857601\n")
        rc, out = self.run_("storage-status")
        self.assertEqual(rc, 0, out)
        self.assertIn("выше жёсткого предела", out)
        put_config(self.repo, b"git_threshold_bytes: 104857600\n")
        rc, out = self.run_("storage-status")
        self.assertNotIn("выше жёсткого предела", out)


# ============================================================================ (а) файл конфига: матрица неверных
class ConfigFileMatrix(Base):
    CASES = {
        "yaml-broken": b'storage:\n  endpoint: https://h.example.invalid\n  key_prefix: "line-content-not-printed-q7\n',
        # класс «сообщение разбора отражает строку» (мутация m10): у yamlmini такие сообщения есть — строка в них
        # не должна дойти до вывода установщика
        "yaml-broken-reflecting-line": b"storage:\n  endpoint x-line-content-not-printed-q7\n",
        "yaml-broken-reflecting-colon": b"storage:\n  bucket: a: line-content-not-printed-q7\n",
        "yaml-broken-secret":b'storage:\n  endpoint: https://h.example.invalid\n  key_prefix: "' + SECRET.encode() + b'\n',
        "extra-key": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  colour: blue\n",
        "extra-top-key": b"schema_version: 1\n",
        "wrong-type-bucket": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: 5\n",
        "wrong-type-threshold": b"git_threshold_bytes: big\n",
        "float-timeout-is-string": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  timeout_s: 2.5\n",
        "storage-not-mapping": b"storage: [a, b]\n",
        "top-not-mapping": b"- a\n- b\n",
        "prefix-broken": b'storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  key_prefix: "a\\u0001b"\n',
        "prefix-wrong-type": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  key_prefix: 7\n",
        "prefix-null": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  key_prefix:\n",
        "canary-null": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  canary_key: ~\n",
        "partial-no-bucket": b"storage:\n  endpoint: https://h.example.invalid\n",
        "partial-no-endpoint": b"storage:\n  bucket: b\n",
        "endpoint-http-remote": b"storage:\n  endpoint: http://h.example.invalid\n  bucket: b\n",
        "creds-bad-names": b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n  credentials:\n    access_key_id: lower\n    secret_access_key: X\n",
        "not-utf8": b"storage:\n  bucket: \xff\xfe\n",
        "flow-storage": b"storage: {}\n",
        "cr": b"storage:\r\n  bucket: b\r\n",
    }

    def test_every_invalid_file_is_named_refusal_no_write_no_network(self):
        with self.fake() as fk:
            for name, data in sorted(self.CASES.items()):
                data = data.replace(b"https://h.example.invalid", fk.endpoint.encode()) if b"http://h." not in data else data
                put_config(self.repo, data)
                for cmd in ("storage-init", "storage-status"):
                    n0 = len(fk.state.log)
                    rc, out = self.run_(cmd)
                    with self.subTest(case=name, cmd=cmd):
                        if name == "flow-storage":     # storage: {} — блок без фактов: привязка неполна
                            self.assertEqual(rc, 2, out)
                            self.assertIn("привязка неполна", out)
                        else:
                            self.assertEqual(rc, 2, out)
                            self.assertTrue(out.startswith("FAIL %s:" % cmd) or "\nFAIL %s:" % cmd in out, out)
                        self.assertEqual(read_bytes(config_path(self.repo)), data, "файл не тронут")
                        self.assertEqual(len(fk.state.log), n0, "ни одного запроса к хранилищу")
                        self.assertNotIn(SECRET, out)
                        self.assertNotIn("line-content-not-printed", out)
                        self.assertNotIn("TOOL_FAILURE", out)

    def test_named_causes(self):
        expect = {"extra-key": "факты вне нормы", "wrong-type-bucket": "storage.bucket", "prefix-broken": "storage.key_prefix",
                  "prefix-null": "null", "partial-no-bucket": "нет storage.bucket", "yaml-broken": "строка 3",
                  "not-utf8": "не UTF-8", "float-timeout-is-string": "storage.timeout_s"}
        for name, needle in expect.items():
            put_config(self.repo, self.CASES[name])
            rc, out = self.run_("storage-init")
            with self.subTest(case=name):
                self.assertEqual(rc, 2, out)
                self.assertIn(needle, out)

    def test_not_regular_file_refused(self):
        os.makedirs(config_path(self.repo))
        rc, out = self.run_("storage-init")
        self.assertEqual(rc, 2, out)
        self.assertIn("не обычный файл", out)
        os.rmdir(config_path(self.repo))
        other = os.path.join(self.repo, "elsewhere.yaml")
        with open(other, "wb") as f:
            f.write(b"storage:\n  bucket: b\n")
        os.symlink(other, config_path(self.repo))
        for cmd in ("storage-init", "storage-status", "check-secrets"):
            rc, out = self.run_(cmd)
            self.assertEqual(rc, 2, out)
            self.assertIn("симлинк", out)
        self.assertEqual(read_bytes(other), b"storage:\n  bucket: b\n")

    def test_check_secrets_refuses_invalid_config(self):
        put_config(self.repo, self.CASES["extra-key"])
        rc, out = self.run_("check-secrets")
        self.assertEqual(rc, 2, out)
        self.assertIn("факты вне нормы", out)

    def test_tool_failure_is_separate_outcome(self):
        """Собственная ошибка установщика — rc 10, отличный от «не настроено» (0) и «отказ» (2); текст исключения
        не печатается. Вызывается подменой адаптера в копии комплекта (attach.core.load_config бросает KeyError с
        синтетическим секретом в тексте)."""
        tmp = tempfile.mkdtemp()
        try:
            bot = os.path.join(tmp, "bot")
            shutil.copytree(_KIT, os.path.join(bot, "kit"), ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(os.path.join(_BOT, "attach"), os.path.join(bot, "attach"), ignore=shutil.ignore_patterns("__pycache__"))
            for m in ("yamlmini.py", "identity.py", "comment.py"):
                shutil.copy(os.path.join(_BOT, m), bot)
            core = os.path.join(bot, "attach", "core.py")
            src = read_bytes(core).decode("utf-8")
            src = src.replace("def ensure_canary(config, env=None):\n",
                              "def ensure_canary(config, env=None):\n    raise KeyError(%r)\n" % SECRET, 1)
            with open(core, "wb") as f:
                f.write(src.encode("utf-8"))
            with self.fake() as fk:
                put_config(self.repo, customer_config(fk))
                rc, out = Run(self, self.repo, kit=os.path.join(bot, "kit"))("storage-init")
            self.assertEqual(rc, 10, out)
            self.assertIn("TOOL_FAILURE", out)
            self.assertNotIn(SECRET, out)
        finally:
            shutil.rmtree(tmp)


# ============================================================================ (б)(в) с хранилищем, три режима
@per_provider
class InitMatrix(Base):
    def test_fresh_init_writes_once_creates_canary_probe_ok(self):
        with self.fake() as fk:
            old = customer_config(fk)
            put_config(self.repo, old)
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 0, out)
            new = read_bytes(config_path(self.repo))
            ok, inserted = only_insertions(old, new)
            self.assertTrue(ok, "прежние байты конфига тронуты")
            prefix = self.prefix_of(new)
            self.assertEqual(len(prefix), 33)                       # 32 hex = 128 бит + «/»
            doc = pyyaml(new)
            st = doc["storage"]
            self.assertEqual(st["credentials"], S3_NAMES)          # имена — из реестра
            self.assertEqual(set(inserted) - {b""}, {l for l in inserted if l.strip()} )
            # вставка — ровно credentials (3 строки), key_prefix, canary_key и строка-комментарий
            self.assertEqual(len([l for l in inserted if not l.lstrip().startswith(b"#")]), 5)
            self.assertEqual(len(inserted), 6)
            self.assertIn("canary: uploaded", out)
            self.assertIn("storage_probe_outcome: ok", out)
            canary = prefix + st["canary_key"]
            self.assertIn(canary, fk.state.objects)                 # канарейка — ПОД префиксом
            self.assertEqual(fk.state.objects[canary], attach.CANARY_BODY)
            self.assertTrue(set(fk.methods()) <= WRITER_PERMS, fk.methods())
            self.assertTrue(all(e["akid"] == AKID for e in fk.state.log))
            self.assertNotIn(prefix, out)

    def test_repeat_init_and_status_change_nothing(self):
        with self.fake() as fk:
            put_config(self.repo, customer_config(fk))
            self.assertEqual(self.run_("storage-init")[0], 0)
            snap = read_bytes(config_path(self.repo))
            prefix = self.prefix_of(snap)
            for i in range(3):
                n_mut = len(fk.mutations())
                rc, out = self.run_("storage-init")
                self.assertEqual(rc, 0, out)
                self.assertIn("canary: already-present", out)
                self.assertIn("файл не тронут", out)
                self.assertEqual(len(fk.mutations()), n_mut, "повтор без PUT")
                rc, out = self.run_("storage-status")
                self.assertEqual(rc, 0, out)
                self.assertIn("storage_probe_outcome: ok (canary-valid)", out)
                self.assertEqual(read_bytes(config_path(self.repo)), snap)
            self.assertEqual(self.prefix_of(), prefix)

    def test_canary_absent_then_recreated_without_touching_config(self):
        with self.fake() as fk:
            put_config(self.repo, customer_config(fk))
            self.assertEqual(self.run_("storage-init")[0], 0)
            snap = read_bytes(config_path(self.repo))
            fk.state.objects.clear()
            rc, out = self.run_("storage-status")
            self.assertEqual(rc, 2, out)
            self.assertIn("storage_probe_outcome: storage-denied (canary-", out)   # missing (404) или denied (403 без list)
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 0, out)
            self.assertIn("canary: uploaded", out)
            self.assertEqual(read_bytes(config_path(self.repo)), snap)

    def test_foreign_bytes_under_canary_are_replaced(self):
        with self.fake() as fk:
            put_config(self.repo, customer_config(fk))
            self.assertEqual(self.run_("storage-init")[0], 0)
            prefix = self.prefix_of()
            key = prefix + "workshop-canary"
            fk.state.objects[key] = b"x" * len(attach.CANARY_BODY)
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 0, out)
            self.assertIn("canary: uploaded", out)
            self.assertEqual(fk.state.objects[key], attach.CANARY_BODY)

    def test_canary_unavailable_modes(self):
        cases = (("err5xx", "storage-unavailable"), ("deny", "storage-denied"), ("put_truncate", "storage-unavailable"))
        for mode, outcome in cases:
            with self.fake() as fk:
                put_config(self.repo, customer_config(fk))
                fk.state.mode.add(mode)
                rc, out = self.run_("storage-init")
                with self.subTest(mode=mode):
                    self.assertEqual(rc, 2, out)
                    self.assertIn("canary: %s" % outcome, out)
                    self.assertIn("канарейка не создана: %s" % outcome, out)
                    self.prefix_of()                               # конфиг дописан ДО сети — префикс есть
                    rc2, out2 = self.run_("storage-status")
                    # проба судит КЛЮЧ (2xx GET канарейки), не байты: обрезанная хранилищем канарейка читается — ok;
                    # недоступность и отказ — не ok
                    self.assertEqual(rc2, 0 if mode == "put_truncate" else 2, out2)
                    fk.state.mode.discard(mode)
                    rc3, out3 = self.run_("storage-init")
                    self.assertEqual(rc3, 0, out3)
                    rc4, out4 = self.run_("storage-status")
                    self.assertEqual(rc4, 0, out4)
            os.remove(config_path(self.repo))

    def test_no_such_bucket(self):
        with self.fake() as fk:
            put_config(self.repo, customer_config(fk).replace(fk.state.bucket.encode(), b"absent-bucket"))
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 2, out)
            self.assertIn("storage-unavailable", out)

    def test_secrets_present_absent_partial(self):
        with self.fake() as fk:
            put_config(self.repo, customer_config(fk))
            for label, env in (("absent", base_env(storage_secrets=False)), ("partial", base_env(partial=True))):
                rc, out = self.run_("storage-init", env=env)
                with self.subTest(secrets=label):
                    self.assertEqual(rc, 2, out)
                    self.assertIn("credentials-absent", out)
                    self.assertIn("значений ключа писателя нет в окружении", out)
                    self.assertEqual(fk.mutations(), [], "без ключа — ни одного PUT")
                    rc, out = self.run_("check-secrets", env=env)
                    self.assertEqual(rc, 2, out)
                    self.assertIn("storage: настроено", out)
                    self.assertIn(S3_NAMES["secret_access_key"], out.split("FAIL", 1)[1])
            snap = read_bytes(config_path(self.repo))
            prefix = self.prefix_of(snap)                          # создан первым прогоном, дальше не менялся
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 0, out)
            self.assertEqual(read_bytes(config_path(self.repo)), snap)
            self.assertEqual(self.prefix_of(), prefix)
            rc, out = self.run_("check-secrets")
            self.assertEqual(rc, 0, out)
            for n in S3_NAMES.values():
                self.assertIn("step storage_binding: %s present" % n, out)

    def test_legal_key_permutations_pass(self):
        """Обратный контроль: законная перестановка ключей YAML (порядок фактов в блоке и блоков в файле) — проходит."""
        with self.fake() as fk:
            facts = ["endpoint: %s" % fk.endpoint, "bucket: %s" % fk.state.bucket, "allow_insecure_http: true",
                     "timeout_s: 2"]
            perms = list(itertools.permutations(facts))
            for i, order in enumerate(perms):
                for top_first in (True, False):
                    block = b"storage:\n" + b"".join(b"  " + f.encode() + b"\n" for f in order)
                    top = b"git_threshold_bytes: 1000\n"
                    data = top + block if top_first else block + top
                    put_config(self.repo, data)
                    rc, out = self.run_("storage-init")
                    with self.subTest(order=i, top_first=top_first):
                        self.assertEqual(rc, 0, out)
                        new = read_bytes(config_path(self.repo))
                        self.assertTrue(only_insertions(data, new)[0])
                        self.prefix_of(new)
                        self.assertEqual(pyyaml(new)["git_threshold_bytes"], 1000)
            self.assertEqual(len(set(CREATED_PREFIXES[-len(perms) * 2:])), len(perms) * 2, "каждый префикс — свой")

    def test_explicit_empty_prefix_is_customer_value_kept(self):
        """key_prefix: "" — присутствующее значение нормы (выбор заказчика): не перегенерируется, громкое предупреждение;
        физический ключ канарейки — без префикса."""
        with self.fake() as fk:
            data = customer_config(fk, extra=("allow_insecure_http: true", 'key_prefix: ""'))
            put_config(self.repo, data)
            for _ in range(2):
                rc, out = self.run_("storage-init")
                self.assertEqual(rc, 0, out)
                self.assertIn("! key_prefix пуст", out)
            new = read_bytes(config_path(self.repo))
            self.assertTrue(only_insertions(data, new)[0])
            self.assertEqual(pyyaml(new)["storage"]["key_prefix"], "")
            self.assertEqual(len(re.findall(rb"\n *key_prefix:", new)), 1)
            self.assertIn("workshop-canary", fk.state.objects)

    def test_status_requires_installer_facts(self):
        """Привязка с credentials, но без key_prefix / canary_key — status отказывает с причиной «запустите storage-init»,
        файл не трогает, в хранилище не ходит."""
        with self.fake() as fk:
            data = customer_config(fk, extra=("allow_insecure_http: true", "credentials:",
                                              "  access_key_id: %s" % S3_NAMES["access_key_id"],
                                              "  secret_access_key: %s" % S3_NAMES["secret_access_key"]))
            put_config(self.repo, data)
            rc, out = self.run_("storage-status")
            self.assertEqual(rc, 2, out)
            self.assertIn("storage.key_prefix, storage.canary_key", out)
            self.assertIn("запустите storage-init", out)
            self.assertEqual(read_bytes(config_path(self.repo)), data)
            self.assertEqual(fk.state.log, [])
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 0, out)
            new = read_bytes(config_path(self.repo))
            self.assertTrue(only_insertions(data, new)[0])
            self.prefix_of(new)
            self.assertNotIn("credentials (имена из реестра", out)    # заданные заказчиком credentials не дописываются

    def test_customer_credentials_kept(self):
        """credentials, заданные заказчиком (имена с суффиксом _DEV для тестового бакета) — не трогаются; check-secrets
        требует ИМЕНА КОНФИГА и называет их вне реестра."""
        with self.fake() as fk:
            names = {k: v + "_DEV" for k, v in S3_NAMES.items()}
            data = customer_config(fk, extra=("allow_insecure_http: true", "credentials:",
                                              "  secret_access_key: %s" % names["secret_access_key"],
                                              "  access_key_id: %s" % names["access_key_id"]))
            put_config(self.repo, data)
            env = base_env(storage_secrets=False)
            env[names["access_key_id"]], env[names["secret_access_key"]] = AKID, SECRET
            rc, out = self.run_("storage-init", env=env)
            self.assertEqual(rc, 0, out)
            new = read_bytes(config_path(self.repo))
            self.assertEqual(pyyaml(new)["storage"]["credentials"], names)
            self.assertTrue(only_insertions(data, new)[0])
            rc, out = self.run_("check-secrets", env=env)
            self.assertEqual(rc, 2, out)                      # CI привязывает имена реестра — их нет
            self.assertIn("вне реестра", out)


# ============================================================================ (д) обновление комплекта
class _KitCopy(object):
    """Копия комплекта с манифестом, написанным РУКАМИ (оракул не делит encoder с build_manifest)."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="d20-t3-kit-")
        bot = os.path.join(self.root, "bot")
        shutil.copytree(_KIT, os.path.join(bot, "kit"), ignore=shutil.ignore_patterns("__pycache__", "manifest.yaml"))
        shutil.copytree(os.path.join(_BOT, "attach"), os.path.join(bot, "attach"), ignore=shutil.ignore_patterns("__pycache__"))
        for m in ("yamlmini.py", "identity.py", "comment.py"):
            shutil.copy(os.path.join(_BOT, m), bot)
        self.kit = os.path.join(bot, "kit")
        self.manifest = os.path.join(self.root, "manifest.yaml")
        self.version = 0
        self.release()

    def template(self):
        return os.path.join(self.kit, "templates", "storage.yaml")

    def release(self, template_suffix=b""):
        """Новая версия комплекта: новая версия шаблона конфига (байты меняются) и манифест."""
        self.version += 1
        if template_suffix:
            with open(self.template(), "ab") as f:
                f.write(template_suffix)
        lines = ["schema_version: 1", "kit_version: 0.%d.0" % self.version, "kit_schema_version: 1",
                 "workflows_dir: .github/workflows", "entries:"]
        for src, dst, role in (("bot/kit/templates/storage.yaml", CONFIG_REL, "config"),
                               ("bot/kit/templates/gitattributes", ".gitattributes", "policy")):
            lines += ["  - src: %s" % src, "    dst: %s" % dst, "    role: %s" % role,
                      "    sha256: %s" % sha(read_bytes(os.path.join(self.root, src))), '    mode: "0644"']
        with open(self.manifest, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class KitUpdate(Base):
    def setUp(self):
        super().setUp()
        self.k = _KitCopy()
        self.krun = Run(self, self.repo, kit=self.k.kit)

    def tearDown(self):
        self.k.cleanup()
        super().tearDown()

    def layout(self):
        rc, out = self.krun("layout", extra=("--manifest", self.k.manifest))
        self.assertEqual(rc, 0, out)
        return out

    def test_first_layout_lays_template_then_keeps(self):
        out = self.layout()
        self.assertIn("+ %s (config)" % CONFIG_REL, out)
        self.assertEqual(read_bytes(config_path(self.repo)), read_bytes(self.k.template()))
        self.k.release(b"# v2 template line\n")
        out = self.layout()
        self.assertIn("= %s (config: файл заказчика, не трогается)" % CONFIG_REL, out)
        self.assertNotEqual(read_bytes(config_path(self.repo)), read_bytes(self.k.template()))

    def _matrix(self, prepare):
        """prepare(fk) -> байты конфига заказчика до обновлений; затем N обновлений комплекта (новая версия шаблона)
        × (layout, storage-init, storage-status): конфиг побайтово равен снимку после первого init (или исходному)."""
        with make_fake(self.PROVIDER) as fk:
            self.layout()
            data = prepare(fk)
            put_config(self.repo, data)
            rc0, out0 = self.krun("storage-init")
            snap = read_bytes(config_path(self.repo))
            for n in range(1, 4):
                self.k.release(("# template v%d\n" % (n + 1)).encode())
                out = self.layout()
                self.assertIn("= %s (config: файл заказчика, не трогается)" % CONFIG_REL, out)
                self.assertEqual(sha(read_bytes(config_path(self.repo))), sha(snap), "обновление %d" % n)
                rc, out = self.krun("storage-init")
                self.assertEqual(rc, rc0, out)
                self.assertEqual(read_bytes(config_path(self.repo)), snap)
            return rc0, out0, data, snap

    def test_update_with_prefix(self):
        rc0, out0, data, snap = self._matrix(lambda fk: customer_config(fk))
        self.assertEqual(rc0, 0, out0)
        self.prefix_of(snap)

    def test_update_prefix_absent_layout_never_generates(self):
        """Префикса нет (заказчик ещё не запускал storage-init): обновление его НЕ создаёт — создаёт только storage-init."""
        with make_fake(self.PROVIDER) as fk:
            self.layout()
            data = customer_config(fk)
            put_config(self.repo, data)
            for n in range(3):
                self.k.release(("# template v%d\n" % (n + 10)).encode())
                self.layout()
                self.assertEqual(read_bytes(config_path(self.repo)), data)
                self.assertEqual(PREFIX_RE.findall(read_bytes(config_path(self.repo))), [])
            rc, out = self.krun("storage-init")
            self.assertEqual(rc, 0, out)
            self.prefix_of()

    def test_update_prefix_broken_kept_and_refused(self):
        def broken(fk):
            return customer_config(fk, extra=("allow_insecure_http: true", 'key_prefix: "x\\u0007y/"'))
        rc0, out0, data, snap = self._matrix(broken)
        self.assertEqual(rc0, 2, out0)
        self.assertIn("storage.key_prefix", out0)
        self.assertEqual(snap, data)

    def test_commit_puts_config_in_git_without_secret_values(self):
        with make_fake(self.PROVIDER) as fk:
            self.layout()
            put_config(self.repo, customer_config(fk))
            rc, out = self.krun("storage-init")
            self.assertEqual(rc, 0, out)
            rc, out = self.krun("commit", extra=("--manifest", self.k.manifest))
            self.assertEqual(rc, 0, out)
            log = subprocess.run(["git", "-C", self.repo, "log", "-p", "--all"], capture_output=True).stdout
            self.assertIn(b"key_prefix", log)
            for v in (AKID, SECRET, OTHER_VALUE):
                self.assertNotIn(v.encode(), log)


@per_provider
class KitUpdate_(KitUpdate):
    pass


del KitUpdate          # исходное имя не гоняется: только подклассы трёх режимов провайдера


# ============================================================================ (б) ровно один раз под конкуренцией
class Concurrency(Base):
    def test_second_init_waits_on_lock_and_keeps_first_prefix(self):
        hook = tempfile.mkdtemp()
        try:
            put_config(self.repo, b"storage:\n  endpoint: https://storage.example.invalid\n  bucket: b\n")
            env1 = base_env(storage_secrets=False)
            env1["WORKSHOP_KIT_TEST_HOOK_DIR"] = hook
            argv = [PY, INSTALL, "--kit", _KIT, "--repo", self.repo, "storage-init"]
            p1 = subprocess.Popen(argv, env=env1, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 30
            while not [f for f in os.listdir(hook) if f.startswith("held-")] and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue([f for f in os.listdir(hook) if f.startswith("held-")], "первый не дошёл до блокировки")
            p2 = subprocess.Popen(argv, env=base_env(storage_secrets=False), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            time.sleep(1.0)
            self.assertIsNone(p2.poll(), "второй storage-init обязан ждать блокировку, а не писать параллельно")
            open(os.path.join(hook, "release"), "wb").close()
            o1 = p1.communicate(timeout=60)[0].decode("utf-8")
            o2 = p2.communicate(timeout=60)[0].decode("utf-8")
            OUTPUTS.extend([(self.id(), "p1", o1), (self.id(), "p2", o2)])
            created = [o for o in (o1, o2) if "key_prefix (создан" in o]
            self.assertEqual(len(created), 1, (o1, o2))
            self.assertIn("уже есть — файл не тронут", o2)
            self.prefix_of()
        finally:
            shutil.rmtree(hook)


# ============================================================================ (г) секреты и маскирование
class SecretsContract(Base):
    def test_secret_value_in_config_refused_without_echo(self):
        with make_fake("yandex") as fk:
            for place in ("comment", "creds-as-name", "region"):
                data = customer_config(fk)
                if place == "comment":
                    data += ("# ключ: %s\n" % SECRET).encode()
                elif place == "creds-as-name":
                    data += ("  credentials:\n    access_key_id: %s\n    secret_access_key: %s\n"
                             % (AKID, S3_NAMES["secret_access_key"])).encode()
                else:
                    data = data.replace(b"  allow_insecure_http: true\n", ("  region: %s\n  allow_insecure_http: true\n" % AKID).encode())
                put_config(self.repo, data)
                for cmd in ("storage-init", "storage-status", "check-secrets"):
                    rc, out = self.run_(cmd)
                    with self.subTest(place=place, cmd=cmd):
                        self.assertEqual(rc, 2, out)
                        self.assertIn("найдено ЗНАЧЕНИЕ секрета", out)
                        self.assertEqual(read_bytes(config_path(self.repo)), data)
                self.assertEqual(fk.state.log, [])

    def test_prefix_never_printed_in_any_path(self):
        with make_fake("aws-no-list") as fk:
            put_config(self.repo, customer_config(fk))
            outs = [self.run_("storage-init")[1]]
            prefix = self.prefix_of()
            for mode in ("deny", "err5xx", "get_corrupt"):
                fk.state.mode = {mode}
                outs += [self.run_("storage-status")[1], self.run_("storage-init")[1]]
            fk.state.mode = set()
            fk.state.echo = ("AccessDenied", prefix + "workshop-canary " + AKID)   # сервер отражает ключ и префикс
            fk.state.echo_status = 403
            outs += [self.run_("storage-status")[1], self.run_("storage-init")[1]]
            for o in outs:
                self.assertNotIn(prefix, o)
                self.assertNotIn(prefix.rstrip("/"), o)
                self.assertNotIn(AKID, o)


class EdgeLocale(Base):
    def test_locales(self):
        with make_fake("yandex") as fk:
            for loc in ("C", "POSIX", "tr_TR.UTF-8", "ar_SA.UTF-8"):
                put_config(self.repo, customer_config(fk))
                env = base_env()
                env["LC_ALL"] = loc
                env["LANG"] = loc
                for cmd, want in (("storage-init", 0), ("storage-status", 0), ("check-secrets", 0)):
                    rc, out = self.run_(cmd, env=env)
                    with self.subTest(loc=loc, cmd=cmd):
                        self.assertEqual(rc, want, out)
                self.prefix_of()
                os.remove(config_path(self.repo))


# ============================================================================ R1 (Fable), F1: префикс и история git
def gitc(repo, *a):
    r = subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@invalid"] + list(a),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def std_block(fk, extra=()):
    facts = ["endpoint: %s" % fk.endpoint, "bucket: %s" % fk.state.bucket, "allow_insecure_http: true", "timeout_s: 2"]
    return b"storage:\n" + b"".join(b"  " + f.encode() + b"\n" for f in list(facts) + list(extra))


class PrefixHistory(Base):
    """Инвариант: key_prefix никогда не создаётся заново, если инструмент может доказать, что он уже был (след в
    истории git любой ветки). Матрица — пакетом: удалён файл (rm; git rm + commit), удалена строка, `""` вместо строки
    (законно), история только в другой ветке, мелкий клон (сказать), не git-репозиторий (генерировать), явный флаг
    процедуры смены хранилища, предупреждение layout."""

    def committed_prefix(self, fk):
        data = std_block(fk)
        put_config(self.repo, data)
        rc, out = self.run_("storage-init")
        self.assertEqual(rc, 0, out)
        old = self.prefix_of()
        gitc(self.repo, "add", "--", CONFIG_REL)
        gitc(self.repo, "commit", "-qm", "storage config")
        sha = gitc(self.repo, "rev-parse", "HEAD").strip()
        return data, old, sha

    def assert_refused(self, fk, sha, old):
        before = read_bytes(config_path(self.repo))
        n0 = len(fk.state.log)
        rc, out = self.run_("storage-init")
        self.assertEqual(rc, 2, out)
        self.assertIn("коммит %s" % sha, out)
        self.assertIn("git show %s:%s" % (sha, CONFIG_REL), out)
        self.assertIn("--new-storage-prefix", out)
        self.assertNotIn(old, out)
        self.assertNotIn(old.rstrip("/"), out)
        self.assertEqual(read_bytes(config_path(self.repo)), before, "файл не тронут")
        self.assertEqual(len(fk.state.log), n0, "в хранилище не ходили")
        return out

    def restore_and_init(self, sha, old):
        r = subprocess.run(["git", "-C", self.repo, "show", "%s:%s" % (sha, CONFIG_REL)], capture_output=True)
        put_config(self.repo, r.stdout)
        rc, out = self.run_("storage-init")
        self.assertEqual(rc, 0, out)
        self.assertIn("уже есть — файл не тронут", out)
        self.assertEqual(self.prefix_of(), old)

    def test_file_removed_rm(self):
        with self.fake() as fk:
            data, old, sha = self.committed_prefix(fk)
            os.remove(config_path(self.repo))
            put_config(self.repo, data)                       # заказчик заново вписал блок без префикса
            self.assert_refused(fk, sha, old)
            self.restore_and_init(sha, old)

    def test_file_removed_git_rm_commit(self):
        with self.fake() as fk:
            data, old, sha = self.committed_prefix(fk)
            gitc(self.repo, "rm", "-q", "--", CONFIG_REL)
            gitc(self.repo, "commit", "-qm", "rm storage config")
            put_config(self.repo, data)
            self.assert_refused(fk, sha, old)                 # SHA — коммит С префиксом, не коммит удаления
            self.restore_and_init(sha, old)

    def test_line_removed_committed_and_not(self):
        with self.fake() as fk:
            _data, old, sha = self.committed_prefix(fk)
            raw = read_bytes(config_path(self.repo))
            no_line = re.sub(rb"\n *key_prefix: [^\n]*", b"", raw)
            put_config(self.repo, no_line)
            self.assert_refused(fk, sha, old)
            gitc(self.repo, "commit", "-qam", "drop prefix line")
            self.assert_refused(fk, sha, old)

    def test_empty_prefix_replacing_line_is_legal(self):
        with self.fake() as fk:
            _data, old, _sha = self.committed_prefix(fk)
            raw = read_bytes(config_path(self.repo))
            put_config(self.repo, re.sub(rb'key_prefix: "[^"]*"', b'key_prefix: ""', raw))
            rc, out = self.run_("storage-init")
            self.assertEqual(rc, 0, out)
            self.assertIn("! key_prefix пуст", out)
            self.assertEqual(pyyaml(read_bytes(config_path(self.repo)))["storage"]["key_prefix"], "")

    def test_history_only_in_other_branch(self):
        with self.fake() as fk:
            base = gitc(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
            gitc(self.repo, "checkout", "-qb", "other")
            data, old, sha = self.committed_prefix(fk)
            gitc(self.repo, "checkout", "-q", base)
            self.assertFalse(os.path.exists(config_path(self.repo)))
            put_config(self.repo, data)
            self.assert_refused(fk, sha, old)

    def test_new_storage_prefix_flag(self):
        with self.fake() as fk:
            data, old, sha = self.committed_prefix(fk)
            os.remove(config_path(self.repo))
            put_config(self.repo, data)
            rc, out = self.run_("storage-init", post=("--new-storage-prefix",))
            self.assertEqual(rc, 0, out)
            self.assertIn("--new-storage-prefix: создаётся НОВЫЙ key_prefix", out)
            self.assertIn(sha[:12], out)
            self.assertIn("прежние вложения остаются под старым префиксом", out)
            new = self.prefix_of()
            self.assertNotEqual(new, old)
            self.assertNotIn(old, out)
            self.assertNotIn(new, out)

    def test_not_a_git_repo_generates(self):
        plain = tempfile.mkdtemp(prefix="d20-t3-plain-")
        try:
            with self.fake() as fk:
                put_config(plain, std_block(fk))
                rc, out = Run(self, plain)("storage-init")
                self.assertEqual(rc, 0, out)
                self.assertIn("не в git-репозитории", out)
                self.assertIn("key_prefix (создан", out)
                self.prefix_of(read_bytes(config_path(plain)))
        finally:
            shutil.rmtree(plain)

    def test_shallow_clone_says_history_incomplete(self):
        with self.fake() as fk:
            data, old, sha = self.committed_prefix(fk)
            raw = read_bytes(config_path(self.repo))
            put_config(self.repo, re.sub(rb"\n *key_prefix: [^\n]*", b"", raw))
            gitc(self.repo, "commit", "-qam", "drop prefix line")
            for i in range(2):
                with open(os.path.join(self.repo, "f%d" % i), "wb") as f:
                    f.write(b"x")
                gitc(self.repo, "add", "-A")
                gitc(self.repo, "commit", "-qm", "c%d" % i)
            # 5 коммитов: base, конфиг с префиксом, удаление строки, c0, c1 — глубина 1 след не видит, глубина 4 видит
            for depth, expect_rc in ((1, 0), (4, 2)):
                clone = tempfile.mkdtemp(prefix="d20-t3-shallow-")
                try:
                    subprocess.run(["git", "clone", "-q", "--depth", str(depth), "file://" + self.repo, clone], check=True)
                    self.assertEqual(git(clone, "rev-parse", "--is-shallow-repository").stdout.strip(), "true")
                    rc, out = Run(self, clone)("storage-init")
                    with self.subTest(depth=depth):
                        self.assertEqual(rc, expect_rc, out)
                        if expect_rc == 0:          # след за границей клона: генерируем, но говорим
                            self.assertIn("клон МЕЛКИЙ", out)
                            self.prefix_of(read_bytes(config_path(clone)))
                        else:                       # след внутри клона: отказ
                            self.assertIn("коммит %s" % sha, out)
                            self.assertNotIn(old, out)
                finally:
                    shutil.rmtree(clone)

    def test_layout_warns_when_config_has_history(self):
        k = _KitCopy()
        try:
            krun = Run(self, self.repo, kit=k.kit)
            rc, out = krun("layout", extra=("--manifest", k.manifest))
            self.assertEqual(rc, 0, out)
            self.assertNotIn("был в истории git", out)        # первая установка — без предупреждения
            with self.fake() as fk:
                _data, old, sha = self.committed_prefix(fk)
            gitc(self.repo, "rm", "-q", "--", CONFIG_REL)
            gitc(self.repo, "commit", "-qm", "rm")
            rc, out = krun("layout", extra=("--manifest", k.manifest))
            self.assertEqual(rc, 0, out)
            self.assertIn("! %s: файл был в истории git (коммит %s)" % (CONFIG_REL, sha[:12]), out)
            self.assertIn("git show %s:%s" % (sha, CONFIG_REL), out)
            self.assertNotIn(old, out)
        finally:
            k.cleanup()


class PrefixHistorySubdir(unittest.TestCase):
    """R2 (F1-R2): --repo — подкаталог git-toplevel (top/proj). Pathspec `log` git разрешает от cwd, `<sha>:<путь>` —
    от toplevel; страж истории обязан видеть след и здесь: удалён файл / удалена строка → отказ с SHA и командой
    восстановления от toplevel; layout предупреждает."""

    def setUp(self):
        self.top = new_repo()
        self.repo = os.path.join(self.top, "proj")
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "README"), "wb") as f:     # проект живёт и после git rm конфига
            f.write(b"proj\n")
        gitc(self.top, "add", "-A")
        gitc(self.top, "commit", "-qm", "proj")
        self.run_ = Run(self, self.repo)

    def tearDown(self):
        shutil.rmtree(self.top, ignore_errors=True)

    def committed(self, fk):
        put_config(self.repo, std_block(fk))
        rc, out = self.run_("storage-init")
        self.assertEqual(rc, 0, out)
        raw = read_bytes(config_path(self.repo))
        old = PREFIX_RE.findall(raw)[0].decode()
        CREATED_PREFIXES.append(old)
        gitc(self.top, "add", "-A")
        gitc(self.top, "commit", "-qm", "cfg")
        return raw, old, gitc(self.top, "rev-parse", "HEAD").strip()

    def refused(self, sha, old):
        rc, out = self.run_("storage-init")
        self.assertEqual(rc, 2, out)
        self.assertIn("коммит %s" % sha, out)
        self.assertIn("git show %s:proj/%s" % (sha, CONFIG_REL), out)
        self.assertNotIn(old, out)
        r = subprocess.run(["git", "-C", self.top, "show", "%s:proj/%s" % (sha, CONFIG_REL)], capture_output=True)
        self.assertEqual(r.returncode, 0)                         # команда восстановления исполнима как напечатана
        self.assertIn(old.encode(), r.stdout)

    def test_file_removed(self):
        with make_fake("yandex") as fk:
            _raw, old, sha = self.committed(fk)
            os.remove(config_path(self.repo))
            put_config(self.repo, std_block(fk))
            self.refused(sha, old)

    def test_line_removed(self):
        with make_fake("yandex") as fk:
            raw, old, sha = self.committed(fk)
            put_config(self.repo, re.sub(rb"\n *key_prefix: [^\n]*", b"", raw))
            self.refused(sha, old)

    def test_layout_warns(self):
        k = _KitCopy()
        try:
            with make_fake("yandex") as fk:
                _raw, old, sha = self.committed(fk)
            gitc(self.top, "rm", "-q", "--", "proj/" + CONFIG_REL)
            gitc(self.top, "commit", "-qm", "rm")
            rc, out = Run(self, self.repo, kit=k.kit)("layout", extra=("--manifest", k.manifest))
            self.assertEqual(rc, 0, out)
            self.assertIn("файл был в истории git (коммит %s)" % sha[:12], out)
            self.assertIn("git show %s:proj/%s" % (sha, CONFIG_REL), out)
            self.assertNotIn(old, out)
        finally:
            k.cleanup()


# ============================================================================ R1 (Fable), F2: порядок — файл до адаптера
class PreT4Order(Base):
    """У заказчика до T4 пакета attach нет: без файла и с шаблоном — rc 0 «не настроено» (адаптер не нужен), с фактами —
    rc 2 «адаптер не найден»; check-secrets с шаблоном — секреты хранилища не требуются."""

    def setUp(self):
        super().setUp()
        self.k = _KitCopy()
        shutil.rmtree(os.path.join(os.path.dirname(self.k.kit), "attach"))
        self.krun = Run(self, self.repo, kit=self.k.kit)

    def tearDown(self):
        self.k.cleanup()
        super().tearDown()

    def test_order(self):
        env = base_env(storage_secrets=False)
        for label, content, want in (("no-file", None, 0), ("template", read_bytes(TEMPLATE), 0),
                                     ("empty-storage", b"storage:\n", 0),
                                     ("facts", b"storage:\n  endpoint: https://h.example.invalid\n  bucket: b\n", 2),
                                     ("threshold-only", b"git_threshold_bytes: big\n", 2)):
            if content is None:
                if os.path.exists(config_path(self.repo)):
                    os.remove(config_path(self.repo))
            else:
                put_config(self.repo, content)
            for cmd in ("storage-status", "storage-init", "check-secrets"):
                rc, out = self.krun(cmd, env=env)
                with self.subTest(case=label, cmd=cmd):
                    self.assertEqual(rc, want, out)
                    self.assertNotIn("Traceback", out)
                    if want == 0 and cmd != "check-secrets":
                        self.assertIn("хранилище не настроено", out)
                    if want == 2:
                        self.assertIn("адаптер вложений", out)
                    if content is not None:
                        self.assertEqual(read_bytes(config_path(self.repo)), content)


# ============================================================================ R1 (Fable): байтовые края как регрессии
@per_provider
class FableR1Bytes(Base):
    def cases(self, fk):
        F = [b"  endpoint: " + fk.endpoint.encode() + b"\n", b"  bucket: " + fk.state.bucket.encode() + b"\n",
             b"  allow_insecure_http: true\n", b"  timeout_s: 2\n"]
        names = (S3_NAMES["access_key_id"].encode(), S3_NAMES["secret_access_key"].encode())
        ok = {
            "no-final-lf": (b"storage:\n" + b"".join(F)).rstrip(b"\n"),
            "hdr-comment": b"storage:   # my storage\n" + b"".join(F),
            "hdr-trailing-space": b"storage: \n" + b"".join(F),
            "comment-lines-between": b"storage:\n# col0 comment\n    # col4 comment\n\n" + b"".join(F),
            "ind4": b"storage:\n" + b"".join(b"  " + l for l in F),
            "ind1": b"storage:\n" + b"".join(l[1:] for l in F),
            "blank-line-after-hdr": b"storage:\n\n" + b"".join(F),
            "top-first": b"git_threshold_bytes: 4096\n# comment\n\nstorage:\n" + b"".join(F) + b"# trailing comment\n",
            "top-last": b"storage:\n" + b"".join(F) + b"\ngit_threshold_bytes: 4096\n",
            "creds-present-4ind": b"storage:\n" + b"".join(F) + b"  credentials:\n      access_key_id: %s\n      secret_access_key: %s\n" % names,
            "prefix-present-canary-absent": b"storage:\n" + b"".join(F) + b'  key_prefix: "' + b"ab" * 16 + b'/"\n',
            "canary-present-prefix-absent": b"storage:\n" + b"".join(F) + b"  canary_key: my-canary\n",
            "two-blank-lines-trailing": b"storage:\n" + b"".join(F) + b"\n\n",
            "comment-with-storage-colon": b"# storage:\n#   bucket: old\nstorage:\n" + b"".join(F),
            "utf8-comment": "storage:\n  # заказчик: комментарий — ёлки\n".encode() + b"".join(F),
        }
        refuse = {
            "crlf": (b"storage:\n" + b"".join(F)).replace(b"\n", b"\r\n"),
            "bom": b"\xef\xbb\xbf" + b"storage:\n" + b"".join(F),
            "tabs": b"storage:\n" + b"".join(b"\t" + l[2:] for l in F),
            "quoted-hdr": b'"storage":\n' + b"".join(F),
            "flow": b"storage: {endpoint: " + fk.endpoint.encode() + b", bucket: " + fk.state.bucket.encode() + b", allow_insecure_http: true}\n",
            "dup-prefix": b"storage:\n" + b"".join(F) + b'  key_prefix: "aa/"\n  key_prefix: "bb/"\n',
        }
        return ok, refuse

    def test_edges_insert_only_and_idempotent(self):
        with self.fake() as fk:
            ok, _r = self.cases(fk)
            for name, data in sorted(ok.items()):
                put_config(self.repo, data)
                rc, out = self.run_("storage-init")
                new = read_bytes(config_path(self.repo))
                with self.subTest(case=name):
                    self.assertEqual(rc, 0, out)
                    self.assertTrue(only_insertions(data, new)[0])
                    st = pyyaml(new)["storage"]
                    self.assertTrue({"credentials", "key_prefix", "canary_key"} <= set(st))
                    self.assertEqual(new[-1:], data[-1:])
                    if name == "prefix-present-canary-absent":
                        self.assertEqual(st["key_prefix"], "ab" * 16 + "/")
                        self.assertEqual(len(re.findall(rb"key_prefix:", new)), 1)
                    if name == "canary-present-prefix-absent":
                        self.assertEqual(st["canary_key"], "my-canary")
                        self.assertTrue(any(k.endswith("my-canary") for k in fk.state.objects))
                    rc2, out2 = self.run_("storage-init")
                    self.assertEqual(rc2, 0, out2)
                    self.assertEqual(read_bytes(config_path(self.repo)), new)
                    if isinstance(st.get("key_prefix"), str) and len(st["key_prefix"]) == 33:
                        CREATED_PREFIXES.append(st["key_prefix"])
                os.remove(config_path(self.repo))

    def test_honest_refusals_without_normalisation(self):
        with self.fake() as fk:
            _ok, refuse = self.cases(fk)
            for name, data in sorted(refuse.items()):
                put_config(self.repo, data)
                n0 = len(fk.state.log)
                rc, out = self.run_("storage-init")
                with self.subTest(case=name):
                    self.assertEqual(rc, 2, out)
                    self.assertEqual(read_bytes(config_path(self.repo)), data)
                    self.assertEqual(len(fk.state.log), n0)
                    self.assertNotIn("Traceback", out)


class ZZSecretsOverAllOutputs(unittest.TestCase):
    """Сквозной положительный контракт — последним классом модуля (порядок unittest — по имени): ни одно значение
    закрытого синтетического множества (ключи, значение прочих секретов CI, КАЖДЫЙ созданный префикс) не встречается
    ни в одном выводе прогонов этого модуля."""

    def test_no_synthetic_value_in_any_output(self):
        if not OUTPUTS or not CREATED_PREFIXES:
            self.skipTest("контракт сквозной: гоняется вместе с модулем целиком")
        vals = list(SYNTH) + sorted(set(CREATED_PREFIXES))
        leaks = [(tid, cmd, v) for tid, cmd, out in OUTPUTS for v in vals if v in out]
        self.assertEqual(leaks, [])


if __name__ == "__main__":
    unittest.main()
