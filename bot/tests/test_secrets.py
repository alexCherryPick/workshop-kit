# -*- coding: utf-8 -*-
"""Оракул сканера и хука: паттерны читаются тестом ИЗ реестра построчным регэкспом (не через
secrets.load_patterns для ожиданий); образцы секретов — синтетические; хук гоняется в ЭФЕМЕРНОМ КЛОНЕ."""
import hashlib, os, re, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import secrets as secrets_mod, yamlmini  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REG = os.path.join(ROOT, "bot", "kit", "secret-patterns.yaml")
SAMPLES = {  # синтетические образцы по форме, значения выдуманы
    "messenger_bot_token": b"123456789:AAbbCCddEEffGGhhIIjjKKllMMnnOOppQQr",
    "forge_personal_token": b"ghp_" + b"a" * 36,
    "forge_fine_grained_token": b"github_pat_" + b"B" * 60,
    "aws_access_key_id": b"AKIA" + b"C" * 16,
    "private_key_block": b"-----BEGIN RSA PRIVATE KEY-----",
    "slack_token": b"xoxb-" + b"d1" * 8,
    "jwt": b"eyJ" + b"a" * 12 + b"." + b"b" * 12 + b"." + b"c" * 12,
    "generic_api_key_assignment": b"api_key = " + b"Z" * 20,
}


def registry_names():
    return re.findall(r"^  - name: (\S+)", open(REG, encoding="utf-8").read(), re.M)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.reg = secrets_mod.load_patterns(yamlmini.load_file(REG))

    def test_every_registry_pattern_has_a_positive_sample_and_is_named_not_valued(self):
        names = registry_names()
        self.assertEqual(sorted(names), sorted(SAMPLES))
        for name, sample in SAMPLES.items():
            found = secrets_mod.scan(self.reg, b"2h work " + sample + b" tail")
            self.assertIn(name, [f["name"] for f in found], name)
            for f in found:
                self.assertEqual(sorted(f), ["describe", "name"])
                self.assertNotIn(sample.decode("ascii", "ignore")[:10], f["describe"] + f["name"])

    def test_false_positive_shape(self):
        for benign in ("2ч 40м созвон 123456789012345678".encode(), "1:20 ревью PR-1234567".encode(), b"token: short", b"AKIAshort"):
            self.assertEqual(secrets_mod.scan(self.reg, benign), [], benign)

    def test_registry_is_read_not_hardcoded(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "p.yaml")
            text = open(REG, encoding="utf-8").read().replace("name: aws_access_key_id", "name: cloud_key_renamed")
            open(p, "w", encoding="utf-8").write(text)
            reg2 = secrets_mod.load_patterns(yamlmini.load_file(p))
            self.assertIn("cloud_key_renamed", [f["name"] for f in secrets_mod.scan(reg2, SAMPLES["aws_access_key_id"])])
            src = open(os.path.join(ROOT, "bot", "secrets.py"), encoding="utf-8").read()
            self.assertNotIn("AKIA", src); self.assertNotIn("ghp_", src)
        finally:
            shutil.rmtree(tmp)
        with self.assertRaises(ValueError):
            secrets_mod.load_patterns({"registry": "secret_patterns", "patterns": [], "never_report": []})

    def test_confirmation_only_after_prior_rejection(self):
        text = b"1h key " + SAMPLES["forge_personal_token"]
        rej = [secrets_mod.rejection_record(text, 100000001, 1757239200)]
        self.assertEqual(sorted(rej[0]), ["at", "telegram_id", "text_sha256"])
        self.assertEqual(rej[0]["text_sha256"], hashlib.sha256(text).hexdigest())
        self.assertTrue(secrets_mod.confirmation_allowed(rej, text, 100000001))
        self.assertFalse(secrets_mod.confirmation_allowed(rej, text, 100000002))      # чужое подтверждение
        self.assertFalse(secrets_mod.confirmation_allowed(rej, text + b"x", 100000001))  # иной текст
        self.assertFalse(secrets_mod.confirmation_allowed([], text, 100000001))       # без находки обхода нет


class HookTests(unittest.TestCase):
    def _repo(self):
        origin = tempfile.mkdtemp(); work = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
        subprocess.run(["git", "clone", "-q", origin, work], check=True, stderr=subprocess.DEVNULL)
        env = {"GIT_AUTHOR_NAME": "d", "GIT_AUTHOR_EMAIL": "d@x", "GIT_COMMITTER_NAME": "d", "GIT_COMMITTER_EMAIL": "d@x"}
        os.makedirs(os.path.join(work, ".workshop", "bot", "kit"))
        os.makedirs(os.path.join(work, ".workshop", "hooks"))
        for f in ("yamlmini.py", "secrets.py"):
            shutil.copy(os.path.join(ROOT, "bot", f), os.path.join(work, ".workshop", "bot", f))
        shutil.copy(REG, os.path.join(work, ".workshop", "bot", "kit", "secret-patterns.yaml"))
        shutil.copy(os.path.join(ROOT, "bot", "kit", "hooks", "pre-commit"), os.path.join(work, ".workshop", "hooks", "pre-commit"))
        os.chmod(os.path.join(work, ".workshop", "hooks", "pre-commit"), 0o755)
        subprocess.run(["git", "add", "-A"], cwd=work, check=True)
        subprocess.run(["git", "commit", "-qm", "kit"], cwd=work, check=True, env=dict(os.environ, **env))
        subprocess.run(["git", "push", "-q", "origin", "HEAD"], cwd=work, check=True)
        return origin, env

    def test_hook_fires_only_in_clone_with_hooksPath(self):
        origin, env = self._repo()
        for with_hooks in (True, False):
            clone = tempfile.mkdtemp()   # эфемерный клон «как CI»: хуки не клонируются
            subprocess.run(["git", "clone", "-q", origin, clone], check=True, stderr=subprocess.DEVNULL)
            if with_hooks:
                subprocess.run(["git", "config", "core.hooksPath", ".workshop/hooks"], cwd=clone, check=True)
            open(os.path.join(clone, "note.md"), "wb").write(b"see " + SAMPLES["forge_personal_token"] + b"\n")
            subprocess.run(["git", "add", "note.md"], cwd=clone, check=True)
            r = subprocess.run(["git", "commit", "-qm", "leak"], cwd=clone, env=dict(os.environ, **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            n = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=clone, stdout=subprocess.PIPE).stdout.decode().strip()
            if with_hooks:
                self.assertNotEqual(r.returncode, 0); self.assertEqual(n, "1")
                self.assertIn("forge_personal_token", r.stderr.decode()); self.assertNotIn("ghp_aaaa", r.stderr.decode())
                r1 = subprocess.run(["git", "commit", "-qm", "legacy"], cwd=clone, env=dict(os.environ, WORKSHOP_SECRET_CONFIRMED="1", **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(r1.returncode, 0)   # «1» обходом не является: подтверждение привязано к именам находок (W-6)
                r3 = subprocess.run(["git", "commit", "-qm", "other"], cwd=clone, env=dict(os.environ, WORKSHOP_SECRET_CONFIRMED="slack_token", **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(r3.returncode, 0)   # чужое имя не открывает эту находку
                r2 = subprocess.run(["git", "commit", "-qm", "confirmed"], cwd=clone, env=dict(os.environ, WORKSHOP_SECRET_CONFIRMED="forge_personal_token", **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(r2.returncode, 0, r2.stderr)
            else:
                self.assertEqual(r.returncode, 0); self.assertEqual(n, "2")   # без hooksPath рубежа нет — шаг обязателен
            shutil.rmtree(clone)


    # --- регрессии раунда 1 (B-1 а/б, W-3): переименование, строка `++…`, комплект отсутствует
    def _commit(self, clone, env, msg="c", extra_env=None):
        e = dict(os.environ, **env); e.update(extra_env or {})
        r = subprocess.run(["git", "commit", "-qm", msg], cwd=clone, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        n = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=clone, stdout=subprocess.PIPE).stdout.decode().strip()
        return r.returncode, int(n), r.stderr.decode("utf-8", "replace")

    def test_hook_scans_renamed_files_and_plusplus_lines(self):
        origin, env = self._repo()
        clone = tempfile.mkdtemp()
        subprocess.run(["git", "clone", "-q", origin, clone], check=True, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "core.hooksPath", ".workshop/hooks"], cwd=clone, check=True)
        with open(os.path.join(clone, "big.md"), "wb") as fh:
            fh.write(b"\n".join(b"line %d" % i for i in range(200)) + b"\n")
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
        rc, n, _ = self._commit(clone, env, "base"); self.assertEqual((rc, n), (0, 2))
        # (а) переименование + токен: статус R — строка обязана попасть в скан
        subprocess.run(["git", "mv", "big.md", "moved.md"], cwd=clone, check=True)
        with open(os.path.join(clone, "moved.md"), "ab") as fh:
            fh.write(b"see " + SAMPLES["forge_personal_token"] + b"\n")
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
        rc, n, err = self._commit(clone, env, "rename")
        self.assertEqual((rc, n), (1, 2), err); self.assertIn("forge_personal_token", err); self.assertNotIn(b"ghp_aaaa", err.encode())
        subprocess.run(["git", "reset", "-q", "--hard"], cwd=clone, check=True)
        # (б) строка содержимого, начинающаяся с `++` — не заголовок диффа
        with open(os.path.join(clone, "big.md"), "ab") as fh:
            fh.write(b"++" + SAMPLES["forge_personal_token"] + b"\n")
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
        rc, n, err = self._commit(clone, env, "plusplus")
        self.assertEqual((rc, n), (1, 2), err)
        # обратный контроль: строка `++` без секрета проходит
        subprocess.run(["git", "reset", "-q", "--hard"], cwd=clone, check=True)
        with open(os.path.join(clone, "big.md"), "ab") as fh:
            fh.write(b"++ plain\n")
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
        rc, n, err = self._commit(clone, env, "ctrl"); self.assertEqual((rc, n), (0, 3), err)
        shutil.rmtree(clone)

    def test_hook_fails_closed_without_kit(self):
        origin, env = self._repo()
        clone = tempfile.mkdtemp()
        subprocess.run(["git", "clone", "-q", origin, clone], check=True, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "core.hooksPath", ".workshop/hooks"], cwd=clone, check=True)
        subprocess.run(["git", "rm", "-rq", ".workshop/bot"], cwd=clone, check=True)   # hooksPath есть, комплекта нет
        with open(os.path.join(clone, "note.md"), "wb") as fh:
            fh.write(b"plain\n")
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
        rc, n, err = self._commit(clone, env, "nokit")
        self.assertEqual((rc, n), (1, 1), err); self.assertIn("hooksPath", err)
        shutil.rmtree(clone)


if __name__ == "__main__":
    unittest.main()
