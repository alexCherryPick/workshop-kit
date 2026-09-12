"""Оракул install.py / build_manifest.py / people_handles.py / wrapper_predicate.py.
Установщик гоняется как ПРОЦЕСС на mktemp-репо; манифест для теста пишется РУКАМИ (текст +
hashlib), а не через yamlmini/build_manifest — оракул не делит с писателем encoder. Карта людей —
РУЧНОЙ шаг заказчика (роль manual): тесты кладут её сами, как заказчик, копией шаблона."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_BOT)
_KIT = os.path.join(_BOT, "kit")
PY = sys.executable


def run(argv, cwd=None, env=None):
    p = subprocess.run([PY] + argv, cwd=cwd, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)


def place_people_map(repo):
    """Ручной шаг people_map реестра: заказчик копирует шаблон и правит; здесь — копия шаблона."""
    os.makedirs(os.path.join(repo, ".workshop"), exist_ok=True)
    shutil.copy(os.path.join(_KIT, "templates", "people.yaml"), os.path.join(repo, ".workshop", "people.yaml"))


class _Kit(object):
    """Минимальный комплект во временном каталоге: bot/kit/{install.py, yamlmini, шаблоны}, манифест руками."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="kit-")
        bot = os.path.join(self.root, "bot")
        shutil.copytree(_KIT, os.path.join(bot, "kit"), ignore=shutil.ignore_patterns("__pycache__", "manifest.yaml"))
        shutil.copy(os.path.join(_BOT, "yamlmini.py"), bot)
        shutil.copy(os.path.join(_BOT, "identity.py"), bot)   # check-people делегирует проверку формы карты identity.validate_people_doc
        shutil.copy(os.path.join(_BOT, "tg.py"), bot)
        self.kit = os.path.join(bot, "kit")
        self.manifest = os.path.join(self.root, "manifest.yaml")
        self.entries = [
            ("bot/tg.py", ".workshop/bot/tg.py", "code"),
            ("bot/kit/templates/gitattributes", ".gitattributes", "policy"),
            ("bot/kit/templates/people.yaml", ".workshop/people.yaml", "manual"),
            ("bot/kit/templates/bot.yaml", ".workshop/bot.yaml", "config"),
            ("bot/kit/templates/bot-sessions.yaml", ".workshop/bot-sessions.yaml", "state"),
            ("bot/kit/workflows/bootstrap.yml", ".github/workflows/workshop-bot-bootstrap.yml", "manual"),
        ]
        self.write_manifest()

    def write_manifest(self, kit_schema_version=1, entries=None):
        lines = ["schema_version: 1", "kit_version: 9.9.9", "kit_schema_version: %d" % kit_schema_version,
                 "workflows_dir: .github/workflows", "entries:"]
        for src, dst, role in (entries if entries is not None else self.entries):
            lines += ["  - src: %s" % src, "    dst: %s" % dst, "    role: %s" % role,
                      "    sha256: %s" % sha(os.path.join(self.root, src)), "    mode: \"0644\""]
        with open(self.manifest, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def install(self, repo, *extra):
        return run([os.path.join(self.kit, "install.py"), "--kit", self.kit, "--repo", repo, "--manifest", self.manifest] + list(extra))

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.k = _Kit()
        self.repo = tempfile.mkdtemp(prefix="repo-")
        git(self.repo, "init", "-q")
        os.makedirs(os.path.join(self.repo, "time"))
        with open(os.path.join(self.repo, "time", "TIMESHEET-2026-09-dev-one.md"), "wb") as fh:
            fh.write(b"---\ncustomer data\n---\n")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-qm", "base")

    def tearDown(self):
        self.k.cleanup()
        shutil.rmtree(self.repo, ignore_errors=True)

    def _tree_mentions(self, needle):
        for root, _dirs, files in os.walk(self.repo):
            if ".git" in root.split(os.sep):
                continue
            for f in files:
                with open(os.path.join(root, f), "rb") as fh:
                    if needle in fh.read():
                        return os.path.relpath(os.path.join(root, f), self.repo)
        return None

    def test_first_install_then_diff_only(self):
        before = sha(os.path.join(self.repo, "time", "TIMESHEET-2026-09-dev-one.md"))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        for _, dst, role in self.k.entries:
            if role != "manual":
                self.assertTrue(os.path.exists(os.path.join(self.repo, dst)), dst)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".github", "workflows", "workshop-bot-bootstrap.yml")))
        # карта людей — ручной шаг: установщик её НЕ создаёт, синтетические люди в репо не попадают
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".workshop", "people.yaml")))
        self.assertIn(".workshop/people.yaml: ручной файл, ОТСУТСТВУЕТ", out)
        self.assertIsNone(self._tree_mentions(b"dev-one"))
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        # второй прогон — дифф пуст, дерево чистое
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("без изменений", out)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        self.assertEqual(sha(os.path.join(self.repo, "time", "TIMESHEET-2026-09-dev-one.md")), before)

    def test_update_overwrites_code_but_keeps_customer_files(self):
        place_people_map(self.repo)  # ручной шаг заказчика — до установки
        self.k.install(self.repo, "layout")
        # заказчик правит карту людей; комплект обновляет tg.py
        people = os.path.join(self.repo, ".workshop", "people.yaml")
        with open(people, "a", encoding="utf-8") as fh:
            fh.write("  - handle: dev-four\n    name: \"Четвёртый\"\n    timezone: UTC\n    status: active\n")
        people_sha = sha(people)
        with open(os.path.join(self.k.root, "bot", "tg.py"), "a", encoding="utf-8") as fh:
            fh.write("\n# обновление комплекта\n")
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("~ .workshop/bot/tg.py", out)
        self.assertIn("+# обновление комплекта", out)
        self.assertIn(".workshop/people.yaml: ручной файл присутствует, комплект его не трогает (не равен шаблону комплекта)", out)
        self.assertIn("= .workshop/bot.yaml (config: файл заказчика, не трогается)", out)
        self.assertEqual(sha(people), people_sha)
        with open(os.path.join(self.repo, ".workshop", "bot", "tg.py"), encoding="utf-8") as fh:
            self.assertIn("обновление комплекта", fh.read())

    def test_kit_integrity_mismatch_refused(self):
        with open(os.path.join(self.k.root, "bot", "tg.py"), "a", encoding="utf-8") as fh:
            fh.write("# tampered\n")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2)
        self.assertIn("не совпадает с манифестом", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".workshop")))

    def test_schema_migration_declared_not_automatic(self):
        self.k.install(self.repo, "layout")
        self.k.write_manifest(kit_schema_version=2)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2)
        self.assertIn("несовместимая схема", out)

    def test_missing_manifest_is_refusal(self):
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "--repo", self.repo, "layout"])
        self.assertEqual(rc, 2)
        self.assertIn("манифест комплекта отсутствует", out)

    def test_unsafe_manifest_destination_refused(self):
        # класс: `..`, абсолютный, .git/, симлинк на пути — каждый отказ ДО записи чего-либо
        os.symlink(tempfile.gettempdir(), os.path.join(self.repo, "escape"))
        for dst in ("../outside.py", "/tmp/outside.py", ".git/hooks/pre-commit", "escape/inside.py", "a//b.py"):
            self.k.write_manifest(entries=[("bot/tg.py", dst, "code")])
            rc, out = self.k.install(self.repo, "layout")
            self.assertEqual(rc, 2, dst + ": " + out)
            self.assertIn("небезопасный путь назначения", out)
            self.assertFalse(os.path.exists(os.path.join(self.repo, ".workshop", "kit-version.yaml")), dst)

    def test_layout_refuses_workflow_with_unfilled_pin(self):
        # живой прогон 2026-09-12: обёртка комплекта с PIN-… ставилась молча и падала в CI
        # «unable to resolve action» — установка обязана отказать с названной причиной
        repo = tempfile.mkdtemp(prefix="repo-")
        run(["git", "init", "-q", repo])
        entries = self.k.entries + [("bot/kit/workflows/poller.yml", ".github/workflows/workshop-bot-poller.yml", "workflow")]
        self.k.write_manifest(entries=entries)
        rc, out = self.k.install(repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("НЕЗАПОЛНЕННЫЕ пины", out)
        self.assertIn("PIN-ACTION-CHECKOUT-SHA", out)
        # пины заполнены (как в релизном коммите канала выдачи) → раскладка проходит
        w = os.path.join(self.k.kit, "workflows", "poller.yml")
        with open(w, encoding="utf-8") as fh:
            t = fh.read()
        with open(w, "w", encoding="utf-8") as fh:
            fh.write(t.replace("PIN-ACTION-CHECKOUT-SHA", "a" * 40))
        self.k.write_manifest(entries=entries)
        rc, out = self.k.install(repo, "layout")
        self.assertEqual(rc, 0, out)
        shutil.rmtree(repo, ignore_errors=True)

    def test_check_people_after_layout(self):
        place_people_map(self.repo)
        self.k.install(self.repo, "layout")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)
        self.assertIn("workshop_bot присутствует", out)
        self.assertIn("админов с telegram_id: 1", out)
        p = os.path.join(self.repo, ".workshop", "people.yaml")
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        # без handle бота — отказ с названной причиной
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text.replace("handle: workshop_bot", "handle: other_bot"))
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2)
        self.assertIn("handle бота", out)
        # без единого admin с telegram_id — отказ с названной причиной (сторожу некому писать)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text.replace("    role: admin\n", ""))
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2)
        self.assertIn("role: admin", out)
        # без карты вовсе — отказ с названной причиной, называющей ручной шаг
        os.remove(p)
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2)
        self.assertIn("карты людей нет", out)
        self.assertIn("people_map", out)

    def test_check_people_rejects_bad_timezone_and_dup(self):
        place_people_map(self.repo)
        self.k.install(self.repo, "layout")
        p = os.path.join(self.repo, ".workshop", "people.yaml")
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("  - handle: dev-five\n    name: x\n    timezone: Mars/Olympus\n    status: active\n")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2)
        self.assertIn("не IANA-зона", out)
        # два человека с одним telegram_id → отказ (атрибуция неоднозначна); то же для forge_login
        for field, value in (("telegram_id", "100000001"), ("forge_login", "example-two")):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text + "  - handle: dev-six\n    name: x\n    timezone: UTC\n    %s: %s\n    status: active\n" % (field, value))
            rc, out = self.k.install(self.repo, "check-people")
            self.assertEqual(rc, 2, out)
            self.assertIn("%s %s" % (field, repr(int(value)) if value.isdigit() else repr(value)), out)
            self.assertIn("атрибуция неоднозначна", out)

    def test_check_secrets_env(self):
        env = dict(os.environ)
        for k in ("WORKSHOP_TG_BOT_TOKEN", "WORKSHOP_FORGE_TOKEN", "WORKSHOP_DEPLOY_KEY"):
            env.pop(k, None)
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-secrets"], env=env)
        self.assertEqual(rc, 2)
        self.assertIn("WORKSHOP_TG_BOT_TOKEN", out)
        self.assertNotIn("secret-value", out)
        # положительный контроль deploy-key: токен отсутствует, альтернатива есть — ok и по реестру, и по шагу
        env["WORKSHOP_TG_BOT_TOKEN"] = "secret-value-1"
        env["WORKSHOP_DEPLOY_KEY"] = "secret-value-2"
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-secrets"], env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("alternative WORKSHOP_DEPLOY_KEY present", out)
        self.assertIn("step forge_credential_secret: WORKSHOP_FORGE_TOKEN alternative WORKSHOP_DEPLOY_KEY present", out)
        self.assertIn("step bot_token_secret: WORKSHOP_TG_BOT_TOKEN present", out)
        self.assertNotIn("secret-value", out)
        # шаг, требующий имя вне реестра секретов, — отказ (второй копии имён нет)
        steps = os.path.join(self.k.kit, "install-steps.yaml")
        with open(steps, "a", encoding="utf-8") as fh:
            fh.write("  - id: zz_probe\n    title: проба\n    when: always\n    guide: проба\n    required_secrets: [WORKSHOP_UNKNOWN]\n    verified_by: проба\n")
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-secrets"], env=env)
        self.assertEqual(rc, 2)
        self.assertIn("WORKSHOP_UNKNOWN", out)


class KitRefTests(unittest.TestCase):
    def setUp(self):
        self.k = _Kit()
        self.checkout = tempfile.mkdtemp(prefix="kitco-")
        git(self.checkout, "init", "-q")
        with open(os.path.join(self.checkout, "x"), "w") as fh:
            fh.write("x\n")
        git(self.checkout, "add", "-A")
        git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-qm", "kit")
        self.head = git(self.checkout, "rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.k.cleanup()
        shutil.rmtree(self.checkout, ignore_errors=True)

    def _release(self, ref, repository="alexCherryPick/workshop-kit"):
        p = os.path.join(self.k.root, "rel.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("schema_version: 1\nkit:\n  repository: %s\n  ref: %s\n  channel: public\npinned_version: \"1\"\nreleases: []\n" % (repository, ref))
        return p

    def _run(self, ref, **kw):
        return run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-kit-ref",
                    "--release", self._release(ref, **kw), "--kit-checkout", self.checkout])

    def test_matching_pin_passes(self):
        rc, out = self._run(self.head)
        self.assertEqual(rc, 0, out)
        self.assertIn("check-kit-ref: ok", out)
        self.assertIn(self.head, out)

    def test_divergent_pin_refused(self):
        rc, out = self._run("f" * 40)
        self.assertEqual(rc, 2)
        self.assertIn("пин комплекта расходится", out)
        self.assertIn(self.head, out)

    def test_placeholder_and_zero_pin_refused(self):
        rc, out = self._run("PIN-KIT-COMMIT-SHA")
        self.assertEqual(rc, 2)
        self.assertIn("пин комплекта не заполнен", out)
        rc, out = self._run("0" * 40)
        self.assertEqual(rc, 2)
        self.assertIn("нулевой SHA", out)

    def test_release_layer_commit_over_pinned_code_commit(self):
        # релизный слой (находка живого прогона): R над K меняет ТОЛЬКО пины → ok; любой иной файл → отказ
        K = self.head
        os.makedirs(os.path.join(self.checkout, "bot", "kit", "workflows"))
        for rel in ("bot/kit/validator-release.yaml", "bot/kit/workflows/bootstrap.yml", "bot/kit/manifest.yaml"):
            with open(os.path.join(self.checkout, rel), "w") as fh:
                fh.write("pins\n")
        git(self.checkout, "add", "-A"); git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-qm", "release layer")
        rc, out = self._run(K)
        self.assertEqual(rc, 0, out); self.assertIn("релизный слой", out); self.assertIn(K, out)
        with open(os.path.join(self.checkout, "bot", "poll.py"), "w") as fh:
            fh.write("code\n")
        git(self.checkout, "add", "-A"); git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-q", "--amend", "-m", "release layer + code")
        rc, out = self._run(K)
        self.assertEqual(rc, 2); self.assertIn("меняет не только пины", out); self.assertIn("bot/poll.py", out)
        # два коммита над K — не слой
        git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-q", "--allow-empty", "-m", "another")
        rc, out = self._run(K)
        self.assertEqual(rc, 2); self.assertIn("расходится", out)

    def test_release_layer_needs_depth_two_shallow_clone_named(self):
        # живой прогон 2026-09-08: мелкий клон (depth 1) у релизного коммита R не имеет родителя — отказ обязан НАЗВАТЬ причину
        K = self.head
        os.makedirs(os.path.join(self.checkout, "bot", "kit"))
        with open(os.path.join(self.checkout, "bot", "kit", "validator-release.yaml"), "w") as fh:
            fh.write("pins\n")
        git(self.checkout, "add", "-A"); git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-qm", "release layer")
        R = git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        shallow = tempfile.mkdtemp(prefix="shallow-")
        import subprocess as _sp
        self.assertEqual(_sp.run(["git", "clone", "-q", "--depth", "1", "file://" + self.checkout, shallow], stdin=_sp.DEVNULL, stdout=_sp.PIPE, stderr=_sp.PIPE).returncode, 0)
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-kit-ref", "--release", self._release(K), "--kit-checkout", shallow])
        self.assertEqual(rc, 2); self.assertIn("МЕЛКИЙ клон", out); self.assertIn("fetch-depth: 2", out)
        deep = tempfile.mkdtemp(prefix="deep-")
        self.assertEqual(_sp.run(["git", "clone", "-q", "--depth", "2", "file://" + self.checkout, deep], stdin=_sp.DEVNULL, stdout=_sp.PIPE, stderr=_sp.PIPE).returncode, 0)
        git(deep, "remote", "set-url", "origin", "git@example.invalid:alexCherryPick/workshop-kit.git")   # как у checkout'а из канала
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-kit-ref", "--release", self._release(K), "--kit-checkout", deep])
        self.assertEqual(rc, 0, out); self.assertIn("релизный слой", out)
        shutil.rmtree(shallow, ignore_errors=True); shutil.rmtree(deep, ignore_errors=True)

    def test_shipped_release_manifest_pin_refuses_foreign_checkout(self):
        # до релиза пин — плейсхолдер («не заполнен»); после релиза — полный SHA, чужой checkout «расходится»; пропуска нет
        import re as _re
        with open(os.path.join(self.k.kit, "validator-release.yaml"), encoding="utf-8") as fh:
            ref = _re.search(r"^  ref: (\S+)$", fh.read(), _re.M).group(1)
        rc, out = run([os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "check-kit-ref", "--kit-checkout", self.checkout])
        self.assertEqual(rc, 2)
        self.assertIn("расходится" if _re.match(r"^[0-9a-f]{40}$", ref) else "пин комплекта не заполнен", out)

    def test_repository_mismatch_refused(self):
        git(self.checkout, "remote", "add", "origin", "https://example.invalid/other-org/other.git")
        rc, out = self._run(self.head)
        self.assertEqual(rc, 2)
        self.assertIn("не совпадает с kit.repository", out)
        git(self.checkout, "remote", "set-url", "origin", "git@example.invalid:alexCherryPick/workshop-kit.git")
        rc, out = self._run(self.head)
        self.assertEqual(rc, 0, out)


class ValidatorVerifyTests(unittest.TestCase):
    def setUp(self):
        self.k = _Kit()
        self.tmp = tempfile.mkdtemp(prefix="val-")
        self.binary = os.path.join(self.tmp, "fake-validator")
        with open(self.binary, "wb") as fh:
            fh.write(b"#!/bin/sh\necho fake\n" + os.urandom(64))
        self.good = sha(self.binary)

    def tearDown(self):
        self.k.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _release(self, digest, source="path: fake-validator"):
        p = os.path.join(self.tmp, "validator-release.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("schema_version: 1\npinned_version: \"1.0\"\nreleases:\n  - version: \"1.0\"\n    artifacts:\n"
                     "      - target: t1\n        %s\n        sha256: \"%s\"\n        purpose: p\n" % (source, digest))
        return p

    def test_match_passes_and_installs(self):
        dest = os.path.join(self.tmp, "out-bin")
        rc, out = self.k.install(self.tmp, "validator", "--release", self._release(self.good), "--target", "t1", "--dest", dest)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.access(dest, os.X_OK))
        self.assertIn("sha256 совпал", out)

    def test_default_dest_is_self_ignored_dir_in_repo(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        rc, out = self.k.install(repo, "validator", "--release", self._release(self.good), "--target", "t1")
        self.assertEqual(rc, 0, out)
        dest = os.path.join(repo, ".workshop-bin", "workshop-validator")
        self.assertTrue(os.access(dest, os.X_OK))
        with open(os.path.join(repo, ".workshop-bin", ".gitignore"), "rb") as fh:
            self.assertEqual(fh.read(), b"*\n")
        self.assertEqual(git(repo, "status", "--porcelain").stdout, "")
        self.assertIn(".workshop-bin/workshop-validator", out)

    def test_one_byte_flip_fails_loudly(self):
        with open(self.binary, "r+b") as fh:
            fh.seek(10)
            b = fh.read(1)
            fh.seek(10)
            fh.write(bytes([b[0] ^ 1]))
        dest = os.path.join(self.tmp, "out-bin")
        rc, out = self.k.install(self.tmp, "validator", "--release", self._release(self.good), "--target", "t1", "--dest", dest)
        self.assertEqual(rc, 2)
        self.assertIn("НЕ СОВПАЛ", out)
        self.assertIn(self.good, out)
        self.assertFalse(os.path.exists(dest))

    def test_placeholder_digest_fails_not_passes(self):
        rc, out = self.k.install(self.tmp, "validator", "--release", self._release("PLACEHOLDER-FILLED-BY-FIRST-RELEASE"), "--target", "t1")
        self.assertEqual(rc, 2)
        self.assertIn("не является дайджестом", out)

    def test_zero_digest_refused_explicitly(self):
        rc, out = self.k.install(self.tmp, "validator", "--release", self._release("0" * 64), "--target", "t1")
        self.assertEqual(rc, 2)
        self.assertIn("нулевой дайджест", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".workshop-bin")))

    def test_non_https_url_refused_before_download(self):
        rel = self._release(self.good, source="url: \"http://example.invalid/workshop-validator\"")
        rc, out = self.k.install(self.tmp, "validator", "--release", rel, "--target", "t1")
        self.assertEqual(rc, 2)
        self.assertIn("не https", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".workshop-bin")))

    def test_shipped_release_manifest_refuses_foreign_binary(self):
        # до релиза — плейсхолдер sha256 («не является дайджестом»); после — несовпадение с чужим бинарём («НЕ СОВПАЛ»)
        rc, out = self.k.install(self.tmp, "validator", "--path", self.binary)
        self.assertEqual(rc, 2)
        self.assertTrue("не является дайджестом" in out or "НЕ СОВПАЛ" in out, out)


class ManifestAndExportTests(unittest.TestCase):
    def test_build_manifest_deterministic_and_roles(self):
        rc1, out1 = run([os.path.join(_KIT, "build_manifest.py")])
        rc2, out2 = run([os.path.join(_KIT, "build_manifest.py")])
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual(out1, out2)
        self.assertIn("dst: .gitattributes\n    role: policy", out1)
        self.assertIn("dst: .workshop/people.yaml\n    role: manual", out1)
        self.assertIn("dst: .workshop/bot-sessions.yaml\n    role: state", out1)
        self.assertIn("dst: .github/workflows/workshop-bot-bootstrap.yml\n    role: manual", out1)
        self.assertNotIn("role: data", out1)
        self.assertNotIn("bot/tests/", out1)
        # РАНТАЙМ комплекта у заказчика: install.py и его реестры ставятся (обёртки поллера и сторожа
        # зовут `install.py validator` каждый прогон) — живой прогон 2026-09-12
        self.assertIn("dst: .workshop/bot/kit/install.py\n    role: code", out1)
        self.assertIn("dst: .workshop/bot/kit/install-steps.yaml\n    role: code", out1)
        self.assertIn("dst: .workshop/bot/kit/validator-release.yaml\n    role: code", out1)
        # инструменты СБОРКИ у заказчика не нужны и не ставятся
        self.assertIn("dst: .workshop/bot/kit/build_help.py\n    role: code", out1)   # poll.py импортирует
        for tool in ("build_manifest.py", "wrapper_predicate.py"):
            self.assertNotIn("src: bot/kit/%s" % tool, out1)
        self.assertTrue(out1.endswith("\n") and not out1.endswith("\n\n"))

    def test_people_handles_exports_handles_and_aliases(self):
        rc, out = run([os.path.join(_KIT, "people_handles.py"), os.path.join(_KIT, "templates", "people.yaml")])
        self.assertEqual(rc, 0, out)
        lines = out.strip("\n").split("\n")
        self.assertIn("workshop_bot", lines)
        self.assertIn("tg-100000003", lines)
        self.assertEqual(len(lines), len(set(lines)))
        self.assertTrue(all(" " not in l for l in lines))

    def test_wrapper_predicate_pass_and_mutations(self):
        contract = os.path.join(_ROOT, "spec", "09-tg-bot-time-line", "tg-bot.yaml")
        if not os.path.exists(contract):  # планировочный репо: главы в output/
            contract = os.path.join(_ROOT, "output", "format-spec", "09-tg-bot-time-line", "tg-bot.yaml")
        src = os.path.join(_KIT, "workflows", "bootstrap.yml")
        with open(src, encoding="utf-8") as fh:
            base = fh.read()
        # положительный контроль: обёртка с токеном-с-фолбэком И deploy-key проходит
        self.assertIn("ssh-key: ${{ secrets.WORKSHOP_DEPLOY_KEY }}", base)
        self.assertIn("token: ${{ secrets.WORKSHOP_FORGE_TOKEN || github.token }}", base)
        rc, out = run([os.path.join(_KIT, "wrapper_predicate.py"), src, "--contract", contract, "--require-hooks-path"])
        self.assertIn("structure: PASS", out)
        self.assertIn(rc, (0, 1))
        tmp = tempfile.mkdtemp(prefix="wp-")
        try:
            muts = {
                "if_in_step": base.replace("      - name: check secrets\n", "      - name: check secrets\n        if: always()\n"),
                "policy_literal_in_run": base.replace("install.py layout\n", "install.py layout --retries 20\n"),
                "two_calls_in_run": base.replace("install.py layout\n", "install.py layout && echo done\n"),
                "unknown_top_key": base.replace("permissions:\n", "defaults: {}\npermissions:\n"),
                "uses_not_allowed": base.replace("      - name: check secrets\n        run: python3 .workshop-kit/bot/kit/install.py check-secrets\n",
                                                 "      - name: setup\n        uses: some-org/setup-thing@0123456789012345678901234567890123456789\n"),
                # правка 1 вердикта: токен без фолбэка при пустом секрете валит checkout; deploy-key объявлен, но не подключён
                "checkout_token_no_fallback": base.replace("token: ${{ secrets.WORKSHOP_FORGE_TOKEN || github.token }}", "token: ${{ secrets.WORKSHOP_FORGE_TOKEN }}"),
                "checkout_alternative_not_bound": base.replace("          ssh-key: ${{ secrets.WORKSHOP_DEPLOY_KEY }}\n", ""),
                "checkout_with_key_not_allowed": base.replace("          fetch-depth: 0\n", "          fetch-depth: 0\n          submodules: true\n"),
                "checkout_with_form_invalid": base.replace("ssh-key: ${{ secrets.WORKSHOP_DEPLOY_KEY }}", "ssh-key: literal-not-a-secret"),
            }
            for reason, text in muts.items():
                self.assertNotEqual(text, base, reason)
                p = os.path.join(tmp, reason + ".yml")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(text)
                rc, out = run([os.path.join(_KIT, "wrapper_predicate.py"), p, "--contract", contract, "--require-hooks-path"])
                self.assertEqual(rc, 2, reason + ": " + out)
                self.assertIn("structure: FAIL", out)
                self.assertIn(reason, out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
