# -*- coding: utf-8 -*-
"""Оракул инструкции хранилища вложений для заказчика (D20 T6): bot/kit/docs/storage-setup.ru.md.

Что проверяется: (1) блоки generated:* == перегенерация build_help из реестра (имён секретов руками нет); (2) имена
секретов, факты конфига, исходы пробы и сбои проверки, пометки «не сохранено», причины изъятия и порог по умолчанию в
прозе совпадают с источниками (реестр шагов и норма — PyYAML, адаптер); (3) инструкция разложена в комплект так же, как
инструкция пользователя, и шаг реестра на неё ссылается; (4) справка CLI write называет path и staged.
Оракул: PyYAML (писатель — yamlmini), сравнение байт, CLI — процессом."""
import os
import re
import subprocess
import sys
import unittest

import yaml

_TESTS = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.dirname(_TESTS)
_ROOT = os.path.dirname(_BOT)
_KIT = os.path.join(_BOT, "kit")
sys.path.insert(0, _BOT)
import attach.core as C  # noqa: E402  (схема фактов адаптера — источник имён фактов)

PY = sys.executable
DOC = os.path.join(_KIT, "docs", "storage-setup.ru.md")
DOC_DST = ".workshop/bot/kit/docs/storage-setup.ru.md"


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def pyyaml(p):
    return yaml.safe_load(read_bytes(p).decode("utf-8"))


REG = pyyaml(os.path.join(_KIT, "install-steps.yaml"))
NORM = pyyaml(os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml"))
TEXT = read_bytes(DOC).decode("utf-8")


def block(name):
    m = re.search(r"<!-- generated:%s:start -->\n(.*?)<!-- generated:%s:end -->" % (name, name), TEXT, re.S)
    assert m, name
    return m.group(1)


class GeneratedFromRegistry(unittest.TestCase):
    def test_doc_equals_regeneration(self):
        r = subprocess.run([PY, os.path.join(_KIT, "build_help.py"), "render-storage", "--guide", DOC], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, read_bytes(DOC), "инструкция == build_help render-storage")

    def test_secret_names_from_registry(self):
        s3 = [s for s in REG["secrets"] if s.get("storage_credential")]
        self.assertEqual(re.findall(r"^- `([A-Z0-9_]+)`", block("storage-secrets"), re.M), [s["name"] for s in s3])
        creds = yaml.safe_load(block("storage-credentials").split("```yaml\n")[1].split("```")[0])
        self.assertEqual(creds["credentials"], {s["storage_credential"]: s["name"] for s in s3})
        self.assertEqual(set(creds["credentials"]), set(C._CRED_KEYS))
        # вне генерируемых блоков имена секретов реестра руками не переписаны
        outside = re.sub(r"<!-- generated:([a-z-]+):start -->.*?<!-- generated:\1:end -->", "", TEXT, flags=re.S)
        for s in REG["secrets"]:
            self.assertNotIn(s["name"], outside)


class ProseMatchesSources(unittest.TestCase):
    def test_config_example_facts_known_to_adapter(self):
        ex = [b for b in re.findall(r"```yaml\n(.*?)```", TEXT, re.S) if b.startswith("storage:")]
        self.assertEqual(len(ex), 1)
        doc = yaml.safe_load(ex[0])
        facts = set("storage." + k for k in doc["storage"])
        self.assertTrue(facts <= set(C._SCHEMA), facts - set(C._SCHEMA))
        for fact in ("git_threshold_bytes", "addressing", "timeout_s", "deadline_s", "list_permission", "key_prefix",
                     "canary_key"):
            self.assertIn("`%s`" % fact if fact != "list_permission" else "`list_permission: true`", TEXT)
            self.assertTrue(fact in C._SCHEMA or "storage." + fact in C._SCHEMA, fact)

    def test_outcomes_and_marks(self):
        probe = re.findall(r"^\| `([a-z-]+)` \|", TEXT.split("Исход пробы")[1].split("Сбои проверки")[0], re.M)
        reads = [o["outcome"] for o in NORM["adapter_outcomes"]["read"]]
        self.assertEqual(probe, ["ok", "storage-denied", "storage-unavailable"])
        self.assertTrue(set(probe) - {"ok"} <= set(reads))
        fails = re.findall(r"^- `([a-z-]+)` —", TEXT.split("Сбои проверки")[1].split("## Эксплуатация")[0], re.M)
        self.assertEqual(fails, ["object-missing", "size-mismatch", "sha-mismatch"])
        self.assertTrue(set(fails) <= set(reads))
        for r in NORM["unsaved"]["reasons"]:
            self.assertIn("«%s»" % r["user_mark"], TEXT)
        for reason in [s for s in NORM["states"]["list"] if s["state"] == "withdrawn"][0]["reasons"]:
            self.assertIn("`%s`" % reason, TEXT)
        n = NORM["soft_limit"]["bytes"]
        self.assertIn("{:,}".format(n).replace(",", " "), TEXT)

    def test_no_secret_like_values(self):
        self.assertNotRegex(TEXT, r"AKIA[0-9A-Z]{12,}|YCAJ[0-9A-Za-z_-]{10,}|YCM[0-9A-Za-z_-]{20,}")
        self.assertNotRegex(TEXT, r"key_prefix: \"[0-9a-f]{32}/\"")


class LaidAndLinked(unittest.TestCase):
    def test_laid_like_user_guide_and_linked_from_step(self):
        man = pyyaml(os.path.join(_KIT, "manifest.yaml"))
        e = {x["dst"]: x for x in man["entries"]}
        guide = e[".workshop/bot/kit/docs/bot-user-guide.ru.md"]
        doc = e[DOC_DST]
        self.assertEqual((doc["src"], doc["role"], doc["mode"]),
                         ("bot/kit/docs/storage-setup.ru.md", guide["role"], guide["mode"]))
        step = [s for s in REG["steps"] if s["id"] == "storage_binding"][0]
        self.assertIn(DOC_DST, step["guide"].replace("\n      ", " ").replace("\n", " "))

    def test_cli_write_help_names_path_and_staged(self):
        r = subprocess.run([PY, "-m", "bot.attach", "write", "--help"], cwd=_ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        h = " ".join(r.stdout.split())
        self.assertIn("path — путь вложения ОТНОСИТЕЛЬНО КАТАЛОГА ЗАПИСИ", h)
        self.assertIn("staged — пути файловой системы", h)


if __name__ == "__main__":
    unittest.main()
