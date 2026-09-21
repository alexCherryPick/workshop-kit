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


class LaunchFormTests(unittest.TestCase):
    """D15 T4 (REQ-100, контракт §4.10): форма запуска launch: ci|daemon — раскладка, реестр управляемых обёрток
    в kit-version.yaml, удаления в плане/диффе/dry-run/коммите, check-people без манифеста, отказы на противоречии.
    Ожидания — из файлов репозитория и git (ls-files, show, status), не из функций install.py."""
    WF = (".github/workflows/workshop-bot-poller.yml", ".github/workflows/workshop-bot-heartbeat.yml")
    BOOT = ".github/workflows/workshop-bot-bootstrap.yml"

    def setUp(self):
        self.k = _Kit()
        # обёртки с заполненными пинами (как в релизном коммите канала выдачи) → роль workflow ставится
        for name in ("poller.yml", "heartbeat.yml"):
            w = os.path.join(self.k.kit, "workflows", name)
            with open(w, encoding="utf-8") as fh:
                t = fh.read()
            with open(w, "w", encoding="utf-8") as fh:
                fh.write(t.replace("PIN-ACTION-CHECKOUT-SHA", "a" * 40).replace("PIN-KIT-COMMIT-SHA", "b" * 40))
        self.entries = self.k.entries + [("bot/kit/workflows/poller.yml", self.WF[0], "workflow"),
                                         ("bot/kit/workflows/heartbeat.yml", self.WF[1], "workflow")]
        self.k.write_manifest(entries=self.entries)
        self.repo = tempfile.mkdtemp(prefix="repo-")
        git(self.repo, "init", "-q")
        place_people_map(self.repo)
        os.makedirs(os.path.join(self.repo, ".github", "workflows"))
        shutil.copy(os.path.join(_KIT, "workflows", "bootstrap.yml"), os.path.join(self.repo, self.BOOT))
        shutil.copy(os.path.join(_KIT, "templates", "bot.yaml"), os.path.join(self.repo, ".workshop", "bot.yaml"))
        self._commit_all("base")

    def tearDown(self):
        self.k.cleanup()
        shutil.rmtree(self.repo, ignore_errors=True)

    def _commit_all(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-qm", msg)

    def _set_launch(self, value):
        p = os.path.join(self.repo, ".workshop", "bot.yaml")
        with open(p, encoding="utf-8") as fh:
            lines = [l for l in fh.read().split("\n") if not l.startswith("launch:")]
        if value is not None:
            lines.insert(0, "launch: %s" % value)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    def _kv(self):
        with open(os.path.join(self.repo, ".workshop", "kit-version.yaml"), encoding="utf-8") as fh:
            return fh.read()

    def _exists(self, rel):
        return os.path.exists(os.path.join(self.repo, rel))

    def _tracked(self, rel):
        return git(self.repo, "ls-files", "--error-unmatch", "--", rel).returncode == 0

    def test_template_declares_ci_and_layout_registers_destinations(self):
        with open(os.path.join(_KIT, "templates", "bot.yaml"), encoding="utf-8") as fh:
            self.assertIn("\nlaunch: ci\n", fh.read())
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("форма запуска: ci", out)
        for w in self.WF:
            self.assertTrue(self._exists(w), w)
        kv = self._kv()
        self.assertIn("launch: ci\n", kv)
        self.assertIn("workflow_destinations:\n  - %s\n  - %s\n" % tuple(sorted(self.WF)), kv)
        for key in ("kit_version: 9.9.9", "kit_schema_version: 1", "manifest_schema_version: 1"):
            self.assertIn(key, kv)
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)
        self.assertIn("форма запуска: ci (раскладка: ci)", out)

    def test_absent_field_is_ci_layout_with_soft_note(self):
        self._set_launch(None)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("launch в .workshop/bot.yaml не задан", out)
        self.assertTrue(all(self._exists(w) for w in self.WF))
        self.assertIn("launch: ci\n", self._kv())
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)                       # мягкая ветвь, не отказ
        self.assertIn("не задан", out)

    def test_invalid_value_refused_before_any_write(self):
        self._set_launch("cron")
        before = set(os.listdir(os.path.join(self.repo, ".github", "workflows")))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("launch = 'cron'", out)
        self.assertEqual(set(os.listdir(os.path.join(self.repo, ".github", "workflows"))), before)
        self.assertFalse(self._exists(".workshop/kit-version.yaml"))
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout.strip(), "M .workshop/bot.yaml")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2, out)

    def test_daemon_first_install_creates_no_workflows_keeps_bootstrap(self):
        self._set_launch("daemon")
        self._commit_all("daemon")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("форма запуска: daemon", out)
        self.assertFalse(any(self._exists(w) for w in self.WF))
        self.assertTrue(self._exists(self.BOOT))
        kv = self._kv()
        self.assertIn("launch: daemon\n", kv)
        for w in self.WF:
            self.assertIn("  - %s\n" % w, kv)               # реестр знает назначения и без файлов
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)
        self.assertIn("лежит 0", out)

    def test_ci_to_daemon_removes_managed_in_plan_diff_dryrun_and_commit(self):
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        self.assertTrue(all(self._tracked(w) for w in self.WF))
        # чужой workflow заказчика и посторонний staged-файл — не трогаются и не захватываются
        foreign = os.path.join(self.repo, ".github", "workflows", "deploy.yml")
        with open(foreign, "w", encoding="utf-8") as fh:
            fh.write("name: deploy\non: push\njobs: {}\n")
        self._commit_all("foreign workflow")
        self._set_launch("daemon")
        self._commit_all("switch")                          # строка launch: daemon закоммичена ДО bootstrap (порядок T7)
        with open(os.path.join(self.repo, "notes2.txt"), "w", encoding="utf-8") as fh:
            fh.write("staged by customer 2\n")
        git(self.repo, "add", "--", "notes2.txt")
        # dry-run: удаления в плане, ничего не записано
        rc, out = self.k.install(self.repo, "layout", "--dry-run")
        self.assertEqual(rc, 0, out)
        for w in self.WF:
            self.assertIn("- %s (workflow: удаляется" % w, out)
            self.assertIn("--- a/%s" % w, out)               # дифф удаления
            self.assertTrue(self._exists(w), w)
        self.assertIn("remove=2", out)
        self.assertNotIn("launch: daemon", self._kv())
        # реальная раскладка
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertFalse(any(self._exists(w) for w in self.WF))
        self.assertTrue(self._exists(self.BOOT))
        self.assertTrue(self._exists(".github/workflows/deploy.yml"))
        self.assertIn("launch: daemon\n", self._kv())
        for w in self.WF:
            self.assertIn("  - %s\n" % w, self._kv())         # путь не забыт после удаления
        # коммит: tracked-удаления точными путями; посторонний staged-файл остаётся в индексе, не в коммите
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        self.assertIn("удаления в коммите", out)
        shown = git(self.repo, "show", "--name-status", "--format=", "HEAD").stdout
        for w in self.WF:
            self.assertIn("D\t%s" % w, shown)
        self.assertIn("M\t.workshop/kit-version.yaml", shown)
        self.assertNotIn("notes2.txt", shown)
        self.assertNotIn("deploy.yml", shown)
        self.assertFalse(any(self._tracked(w) for w in self.WF))
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout.strip(), "A  notes2.txt")
        # второй layout — без изменений; check-people при daemon — ok, обёртки не вернулись
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("без изменений", out)
        self.assertFalse(any(self._exists(w) for w in self.WF))
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)

    def test_daemon_with_present_wrapper_is_rc2_and_layout_clears_it(self):
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        self._set_launch("daemon")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2, out)
        self.assertIn("два читателя курсора", out)
        self.assertIn(self.WF[0], out)
        self.assertIn("форма запуска изменена", out)
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)
        # обёртка появилась снова руками (старый bootstrap) — реестр её помнит → снова rc=2
        with open(os.path.join(self.repo, self.WF[1]), "w", encoding="utf-8") as fh:
            fh.write("name: stale\n")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 2, out)
        self.assertIn(self.WF[1], out)

    def test_daemon_to_ci_lays_workflows_again(self):
        self._set_launch("daemon")
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        self._set_launch("ci")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("последняя раскладка: daemon", out)
        self.assertTrue(all(self._exists(w) for w in self.WF))
        self.assertIn("launch: ci\n", self._kv())

    def test_check_people_from_installed_checkout_without_manifest(self):
        # у заказчика check-people зовётся из .workshop/bot/kit (демон) — манифеста там нет: источник — kit-version.yaml
        self._set_launch("daemon")
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        kit_copy = tempfile.mkdtemp(prefix="installed-kit-")
        try:
            shutil.copytree(self.k.kit, os.path.join(kit_copy, "kit"), ignore=shutil.ignore_patterns("manifest.yaml", "__pycache__"))
            for f in ("yamlmini.py", "identity.py", "tg.py"):
                shutil.copy(os.path.join(_BOT, f), kit_copy)
            self.assertFalse(os.path.exists(os.path.join(kit_copy, "kit", "manifest.yaml")))
            inst = os.path.join(kit_copy, "kit", "install.py")
            rc, out = run([inst, "--kit", os.path.join(kit_copy, "kit"), "--repo", self.repo, "check-people"])
            self.assertEqual(rc, 0, out)
            self.assertIn("лежит 0", out)
            with open(os.path.join(self.repo, self.WF[0]), "w", encoding="utf-8") as fh:
                fh.write("name: stale\n")
            rc, out = run([inst, "--kit", os.path.join(kit_copy, "kit"), "--repo", self.repo, "check-people"])
            self.assertEqual(rc, 2, out)
            self.assertIn(self.WF[0], out)
        finally:
            shutil.rmtree(kit_copy, ignore_errors=True)

    def test_old_kit_version_without_fields_is_soft_note_and_next_layout_fills(self):
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        with open(os.path.join(self.repo, ".workshop", "kit-version.yaml"), "w", encoding="utf-8") as fh:
            fh.write("kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\n")   # установка до D15
        self._set_launch("daemon")
        rc, out = self.k.install(self.repo, "check-people")
        self.assertEqual(rc, 0, out)                       # метаданных нет — заметка, не строгий отказ и не ручной список
        self.assertIn("метаданные формы запуска/обёрток отсутствуют", out)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("workflow_destinations:", self._kv())
        self.assertFalse(any(self._exists(w) for w in self.WF))

    def test_corrupt_metadata_and_unsafe_destination_refused(self):
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        base = "kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nmanual_destinations: []\n"
        cases = {
            base + "launch: cron\nworkflow_destinations: []\n": "launch = 'cron' повреждён",
            base + "launch: daemon\nworkflow_destinations: nope\n": "не список путей",
            base + "launch: daemon\nworkflow_destinations:\n  - ../../etc/cron.d/x\n": "небезопасный путь",
            base + "launch: daemon\nworkflow_destinations:\n  - .git/hooks/post-checkout\n": "небезопасный путь",
            base + "launch: daemon\nworkflow_destinations:\n  - a.yml\n  - a.yml\n": "повторы",
            base + "launch: daemon\nworkflow_destinations:\n  - %s\n" % self.BOOT: "ручной файл",
            # T4 раунд 2: частичный/повреждённый набор новых полей — отказ, не пустой список и не мягкая ветвь
            "kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: daemon\nworkflow_destinations: []\n": "неполны",
            "kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nmanual_destinations: broken\n": "неполны",
            base + "launch: daemon\nworkflow_destinations:\n  - a.yml\n  - A.yml\n": "повторы",
            base + "launch: daemon\nworkflow_destinations:\n  - .GitHub/workflows/workshop-bot-bootstrap.yml\n": "ручной файл",
            base + "launch: daemon\nworkflow_destinations:\n  - .Git/probe\n": "небезопасный путь",
            base + "launch: daemon\nworkflow_destinations:\n  - .github/workflows/%s.yml\n" % ("x" * 256): "небезопасный путь",
            base + "launch: daemon\nworkflow_destinations:\n  - .github\n": "каталог",
        }
        for text, needle in cases.items():
            with open(kv, "w", encoding="utf-8") as fh:
                fh.write(text)
            for cmd in ("layout", "check-people"):
                rc, out = self.k.install(self.repo, cmd)
                self.assertEqual(rc, 2, (cmd, text, out))
                self.assertIn(needle, out, (cmd, text))
            self.assertTrue(self._exists(self.BOOT))
            self.assertTrue(all(self._exists(w) for w in self.WF))   # отказ до мутаций: ничего не удалено

    def test_path_aliases_globs_and_git_are_refused_before_any_deletion(self):
        # T4 раунд 1 (astra, BLOCKER ×3): эквивалентное написание пути (`./`), `.git/` через `./`, глоб `*` как pathspec —
        # каноническая форма обязательна; отказ ДО удаления, bootstrap и содержимое .git целы
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        self._set_launch("daemon")
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        base = "kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nmanual_destinations: []\n"
        probe = os.path.join(self.repo, ".git", "probe"); open(probe, "w").write("x")
        for dest in ("./" + self.BOOT, "./.git/probe", ".github/workflows/*.yml", ".github//workflows/a.yml", ".github/workflows/a.yml/",
                     "sub/.git/hooks/x", ".github/workflows/:(top)a.yml", ".github/workflows/a?.yml", ".github/workflows/a[1].yml"):
            with open(kv, "w", encoding="utf-8") as fh:
                fh.write(base + "workflow_destinations:\n  - \"%s\"\n" % dest)
            for cmd in ("layout", "check-people", "commit"):
                rc, out = self.k.install(self.repo, cmd)
                self.assertEqual(rc, 2, (dest, cmd, out)); self.assertIn("небезопасный путь", out, (dest, cmd))
            self.assertTrue(self._exists(self.BOOT), dest); self.assertTrue(os.path.exists(probe), dest)
            self.assertTrue(all(self._exists(w) for w in self.WF), dest)

    def test_manual_protection_without_manifest_and_manifest_duplicates(self):
        # T4 раунд 1 (astra, MAJOR ×2): manual_destinations в kit-version защищают bootstrap и без манифеста; повтор
        # назначения в манифесте — отказ, не set()
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        self.assertIn("manual_destinations:\n  - %s\n" % self.BOOT, self._kv())
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        with open(kv, "w", encoding="utf-8") as fh:
            fh.write("kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nworkflow_destinations:\n  - %s\nmanual_destinations:\n  - %s\n" % (self.BOOT, self.BOOT))
        kit_copy = tempfile.mkdtemp(prefix="installed-kit-")
        try:
            shutil.copytree(self.k.kit, os.path.join(kit_copy, "kit"), ignore=shutil.ignore_patterns("manifest.yaml", "__pycache__"))
            for f in ("yamlmini.py", "identity.py", "tg.py"):
                shutil.copy(os.path.join(_BOT, f), kit_copy)
            rc, out = run([os.path.join(kit_copy, "kit", "install.py"), "--kit", os.path.join(kit_copy, "kit"), "--repo", self.repo, "check-people"])
            self.assertEqual(rc, 2, out); self.assertIn("ручной файл", out)
        finally:
            shutil.rmtree(kit_copy, ignore_errors=True)
        self.k.write_manifest(entries=self.entries + [self.entries[-1]])   # повтор назначения
        for cmd in ("layout", "commit"):
            rc, out = self.k.install(self.repo, cmd)
            self.assertEqual(rc, 2, (cmd, out)); self.assertIn("повторяется", out)

    def test_physical_aliases_and_directory_in_registry(self):
        # T4 раунд 2 (astra, BLOCKER ×3): NFD-написание и регистр — один файл на macOS (samefile) → отказ до удаления;
        # каталог в реестре — отказ (git add -- <каталог> захватил бы чужие файлы)
        import unicodedata
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        os.makedirs(os.path.join(self.repo, "customer")); open(os.path.join(self.repo, "customer", "foreign.txt"), "w").write("x")
        self._commit_all("customer dir")
        open(os.path.join(self.repo, "customer", "foreign.txt"), "w").write("changed"); git(self.repo, "add", "--", "customer/foreign.txt")
        self._set_launch("daemon")
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        base = "kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nmanual_destinations:\n  - %s\n" % self.BOOT
        nfd_boot = unicodedata.normalize("NFD", ".github/workflows/workshop-bot-bootstrap.yml")   # ASCII — NFD == NFC; пробуем не-ASCII компоненту
        for dest, needle in ((".GITHUB/workflows/workshop-bot-bootstrap.yml", "ручной файл"), ("customer", "каталог"),
                             (unicodedata.normalize("NFD", "докс/й.yml"), None)):
            with open(kv, "w", encoding="utf-8") as fh:
                fh.write(base + "workflow_destinations:\n  - \"%s\"\n" % dest)
            for cmd in ("layout", "commit"):
                rc, out = self.k.install(self.repo, cmd)
                if needle:
                    self.assertEqual(rc, 2, (dest, cmd, out)); self.assertIn(needle, out, (dest, cmd))
            self.assertTrue(self._exists(self.BOOT), dest)
        shown = git(self.repo, "log", "--name-status", "--format=", "-1").stdout
        self.assertNotIn("customer/foreign.txt", shown)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout.strip().split("\n")[0], "M  customer/foreign.txt")

    def test_index_only_directory_and_absolute_path_length(self):
        # T4 раунд 3 (astra): каталог, удалённый из дерева, но живой в индексе git, — отказ (git add -- dir захватил бы
        # удаления потомков); длина — по лимитам ФС для АБСОЛЮТНОГО пути, отказ до удаления обёрток
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        os.makedirs(os.path.join(self.repo, "customer")); open(os.path.join(self.repo, "customer", "foreign.txt"), "w").write("x")
        self._commit_all("customer dir")
        shutil.rmtree(os.path.join(self.repo, "customer"))                 # удалён из дерева, в индексе жив
        self._set_launch("daemon")
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        base = "kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nmanual_destinations:\n  - %s\n" % self.BOOT
        with open(kv, "w", encoding="utf-8") as fh:
            fh.write(base + "workflow_destinations:\n  - customer\n")
        for cmd in ("layout", "check-people", "commit"):
            rc, out = self.k.install(self.repo, cmd)
            self.assertEqual(rc, 2, (cmd, out)); self.assertIn("каталог", out, cmd)
        self.assertNotIn("D\tcustomer/foreign.txt", git(self.repo, "log", "--name-status", "--format=", "-1").stdout)
        self.assertTrue(all(self._exists(w) for w in self.WF))
        # абсолютный путь ≥ PC_PATH_MAX — отказ до мутаций (обёртки на месте)
        long_rel = ".github/workflows/" + "/".join(["d" * 200] * 6) + "/x.yml"   # относительная длина > 1024 → лимит ФС
        with open(kv, "w", encoding="utf-8") as fh:
            fh.write(base + "workflow_destinations:\n  - %s\n" % long_rel)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out); self.assertIn("небезопасный путь", out)
        self.assertTrue(all(self._exists(w) for w in self.WF))

    def test_file_hiding_index_directory_and_empty_path_set(self):
        # T4 раунд 4 (astra, BLOCKER ×2): файл на диске с именем каталога индекса — индекс сверяется всегда; пустой набор
        # путей — выход до git-операций (иначе git commit без pathspec берёт чужой индекс)
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        os.makedirs(os.path.join(self.repo, "customer")); open(os.path.join(self.repo, "customer", "foreign.txt"), "w").write("x")
        self._commit_all("customer dir")
        shutil.rmtree(os.path.join(self.repo, "customer")); open(os.path.join(self.repo, "customer"), "w").write("file now")
        self._set_launch("daemon")
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        with open(kv, "w", encoding="utf-8") as fh:
            fh.write("kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nmanual_destinations:\n  - %s\nworkflow_destinations:\n  - customer\n" % self.BOOT)
        head = git(self.repo, "rev-parse", "HEAD").stdout
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 2, out); self.assertIn("каталог в индексе", out)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout, head)                  # коммита установки нет
        # пустой набор: манифест без записей комплекта на диске/в индексе, чужой staged-файл — коммита нет
        k2 = _Kit(); r2 = tempfile.mkdtemp(prefix="repo-")
        try:
            git(r2, "init", "-q"); place_people_map(r2)
            open(os.path.join(r2, "foreign.txt"), "w").write("staged"); git(r2, "add", "--", "foreign.txt")
            k2.write_manifest(entries=[("bot/kit/templates/people.yaml", ".workshop/people.yaml", "manual")])
            rc, out = k2.install(r2, "commit")
            self.assertEqual(rc, 0, out); self.assertIn("изменений нет", out)
            self.assertNotEqual(git(r2, "rev-parse", "--verify", "-q", "HEAD").returncode, 0)   # коммита не появилось
            self.assertIn("A  foreign.txt", git(r2, "status", "--porcelain").stdout)          # чужой staged-файл остался в индексе
        finally:
            k2.cleanup(); shutil.rmtree(r2, ignore_errors=True)

    def test_layout_refuses_index_directories_before_any_deletion(self):
        # T4 раунд 5 (astra, BLOCKER): layout проверяет индекс для ВСЕХ назначений (реестр и манифест), в т. ч. каталог индекса,
        # скрытый файлом на диске, и новое назначение манифеста поверх каталога индекса — отказ до удалений
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        os.makedirs(os.path.join(self.repo, "hidden")); open(os.path.join(self.repo, "hidden", "child.txt"), "w").write("x")
        os.makedirs(os.path.join(self.repo, ".github", "workflows", "newwf.yml")); open(os.path.join(self.repo, ".github", "workflows", "newwf.yml", "c.txt"), "w").write("y")
        self._commit_all("index dirs")
        shutil.rmtree(os.path.join(self.repo, "hidden")); open(os.path.join(self.repo, "hidden"), "w").write("file now")
        shutil.rmtree(os.path.join(self.repo, ".github", "workflows", "newwf.yml"))
        self._set_launch("daemon")
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        with open(kv, "w", encoding="utf-8") as fh:
            fh.write("kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nmanual_destinations:\n  - %s\nworkflow_destinations:\n  - hidden\n" % self.BOOT)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out); self.assertIn("каталог в индексе", out)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "hidden"))); self.assertTrue(all(self._exists(w) for w in self.WF))
        # новое назначение манифеста поверх каталога индекса
        with open(kv, "w", encoding="utf-8") as fh:
            fh.write("kit_version: 9.9.9\nkit_schema_version: 1\nmanifest_schema_version: 1\nlaunch: ci\nmanual_destinations:\n  - %s\nworkflow_destinations: []\n" % self.BOOT)
        self.k.write_manifest(entries=self.entries + [("bot/kit/workflows/poller.yml", ".github/workflows/newwf.yml", "workflow")])
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out); self.assertIn("каталог в индексе", out)
        self.assertTrue(all(self._exists(w) for w in self.WF))

    def test_version_file_parent_file_and_mode_checked_before_mutations(self):
        # T4 раунд 6 (astra): kit-version.yaml — каталог только в индексе; родитель нового назначения — регулярный файл;
        # невалидный mode манифеста — всё отказ ДО удаления обёрток
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        self._set_launch("daemon"); self._commit_all("daemon")
        kv = os.path.join(self.repo, ".workshop", "kit-version.yaml")
        os.remove(kv); os.makedirs(kv); open(os.path.join(kv, "child"), "w").write("x"); self._commit_all("kv dir")
        shutil.rmtree(kv)                                                        # каталог только в индексе
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out); self.assertIn("каталог в индексе", out); self.assertTrue(all(self._exists(w) for w in self.WF))
        git(self.repo, "rm", "-rq", "--cached", ".workshop/kit-version.yaml"); self._commit_all("kv removed")
        rc, out = self.k.install(self.repo, "layout"); self.assertEqual(rc, 0, out)   # снова законно → раскладка (удаления при daemon)
        rc, out = self.k.install(self.repo, "commit"); self.assertEqual(rc, 0, out)
        self._set_launch("ci"); self._commit_all("ci")
        # родитель нового назначения — регулярный файл
        open(os.path.join(self.repo, "blocked"), "w").write("file")
        self.k.write_manifest(entries=self.entries + [("bot/tg.py", "blocked/inner.py", "code")])
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out); self.assertIn("не каталог", out)
        # невалидный mode
        self.k.write_manifest(entries=self.entries)
        with open(self.k.manifest, encoding="utf-8") as fh:
            t = fh.read()
        with open(self.k.manifest, "w", encoding="utf-8") as fh:
            fh.write(t.replace('mode: "0644"', 'mode: "invalid"', 1))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out); self.assertIn("восьмеричных", out)

    def test_registry_step_launch_form_when_always(self):
        with open(os.path.join(_KIT, "install-steps.yaml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("  - id: launch_form\n", text)
        block = text.split("  - id: launch_form\n", 1)[1].split("  - id: ", 1)[0]
        self.assertIn("when: always", block)
        self.assertNotIn("when: daemon", text)             # нового значения when не вводится (build_help.py вне владения D15)


class CronPeriodTests(unittest.TestCase):
    """Раунд 3 W7: период сторожа сверяется с cron обёртки — источником расписания, не копией."""
    def test_cron_forms(self):
        sys.path.insert(0, _KIT); import install   # noqa: E402
        KIT = _KIT
        self.assertEqual(install.cron_period_minutes('on:\n  schedule:\n    - cron: "17 */2 * * *"\n'), 120)
        self.assertEqual(install.cron_period_minutes('    - cron: "*/15 * * * *"\n'), 15)
        self.assertIsNone(install.cron_period_minutes('    - cron: "0 9 * * 1-5"\n'))   # не сверяемо → установщик ОТКАЗЫВАЕТ при наличии обёртки (W6 р.4)
        for cal in ('"17 */2 * * 1"', '"17 */2 1 * *"', '"*/5 * * * 1-5"', '"*/5 * 3 * *"'):   # r5 W3: календарные ограничения — период не постоянен
            self.assertIsNone(install.cron_period_minutes("    - cron: %s\n" % cal), cal)
        for bad in ('"99 */2 * * *"', '"*/61 * * * *"', '"17 */25 * * *"', '"*/0 * * * *"', '"17 */0 * * *"', '"*/٥ * * * *"', '"1７ */2 * * *"'):   # r6 W2: диапазоны и ASCII
            self.assertIsNone(install.cron_period_minutes("    - cron: %s\n" % bad), bad)
        self.assertEqual(install.cron_period_minutes('    - cron: "59 */23 * * *"\n'), 1380)
        self.assertIsNone(install.cron_period_minutes("no schedule"))
        self.assertEqual(install.cron_period_minutes(open(os.path.join(KIT, "workflows", "heartbeat.yml"), encoding="utf-8").read()), 120)


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
