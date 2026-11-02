"""Оракул install.py layout для слоя инструкций ИИ-агента (D10 T3): роль managed (профили .workshop-ai/*, standing
AGENTS.md = CLAUDE.md), retire по «путь + ожидаемый SHA», supersedes, именованный конфликт, страж незаполненного
плейсхолдера, роль lines (.gitignore). Установщик — ПРОЦЕСС на mktemp-репо; манифест пишется РУКАМИ (текст + hashlib),
не через yamlmini/build_manifest — оракул не делит с писателем encoder (как test_install.py)."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KIT = os.path.join(_BOT, "kit")
PY = sys.executable


def _quiet_git_env():
    """Автообслуживание git в одноразовых репо теста выключено (через окружение — дочерние git установщика наследуют):
    фоновый `git maintenance` держал maintenance.lock и гонял shutil.rmtree (FileNotFoundError; адверсарий B, m2)."""
    n = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
    for k, v in (("maintenance.auto", "false"), ("gc.auto", "0")):
        os.environ["GIT_CONFIG_KEY_%d" % n] = k
        os.environ["GIT_CONFIG_VALUE_%d" % n] = v
        n += 1
    os.environ["GIT_CONFIG_COUNT"] = str(n)


_quiet_git_env()
OLD_AGENTS = b"# old standing written by hand\n"
OLD_HOURS_V0 = b"# hours v0\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)


class _AiKit(object):
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="aikit-")
        bot = os.path.join(self.root, "bot")
        shutil.copytree(_KIT, os.path.join(bot, "kit"), ignore=shutil.ignore_patterns("__pycache__", "manifest.yaml"))
        for m in ("yamlmini.py", "identity.py", "tg.py"):
            shutil.copy(os.path.join(_BOT, m), bot)
        self.kit = os.path.join(bot, "kit")
        self.manifest = os.path.join(self.root, "manifest.yaml")
        self.files = {}
        self.put("profiles/out/.workshop-ai/workshop-hours.md", b"# Workshop - hours\n\nnorm\n")
        self.put("profiles/out/.workshop-ai/workshop-full.md", b"# Workshop - full\n\nnorm\n")
        self.put("profiles/out/AGENTS.md", b"# Agent\n\n1. read the profile\n")
        self.put("profiles/out/CLAUDE.md", b"# Agent\n\n1. read the profile\n")
        self.entries = [
            ("bot/kit/templates/gitattributes", ".gitattributes", "policy"),
            ("bot/kit/templates/gitignore", ".gitignore", "lines"),
            ("profiles/out/.workshop-ai/workshop-hours.md", ".workshop-ai/workshop-hours.md", "managed"),
            ("profiles/out/.workshop-ai/workshop-full.md", ".workshop-ai/workshop-full.md", "managed"),
            ("profiles/out/AGENTS.md", "AGENTS.md", "managed"),
            ("profiles/out/CLAUDE.md", "CLAUDE.md", "managed"),
        ]
        self.retire = [(".workshop/ai/workshop-hours-v0.md", sha(OLD_HOURS_V0))]
        self.supersedes = [("AGENTS.md", sha(OLD_AGENTS)), ("CLAUDE.md", sha(OLD_AGENTS))]
        self.binding = None          # D10 T24: (path, sha256) привязки customer_layer или сырой текст секции
        self.write_manifest()

    def put(self, rel, data):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)

    def src_sha(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), "rb") as fh:
            return sha(fh.read())

    def write_manifest(self, version="9.9.9"):
        lines = ["schema_version: 1", "kit_version: %s" % version, "kit_schema_version: 1", "workflows_dir: .github/workflows"]
        if isinstance(self.binding, tuple):
            lines += ["customer_layer:", "  path: %s" % self.binding[0], "  sha256: %s" % self.binding[1]]
        elif isinstance(self.binding, str):
            lines += self.binding.split("\n")
        lines.append("entries:")
        for src, dst, role in self.entries:
            lines += ["  - src: %s" % src, "    dst: %s" % dst, "    role: %s" % role, "    sha256: %s" % self.src_sha(src), '    mode: "0644"']
        if self.retire:
            lines.append("retire:")
            for p, s in self.retire:
                lines += ["  - path: %s" % p, "    sha256: %s" % s]
        if self.supersedes:
            lines.append("supersedes:")
            for p, s in self.supersedes:
                lines += ["  - path: %s" % p, "    sha256: %s" % s]
        with open(self.manifest, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def install(self, repo, *extra):
        p = subprocess.run([PY, os.path.join(self.kit, "install.py"), "--kit", self.kit, "--repo", repo, "--manifest", self.manifest] + list(extra),
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


class AiLayoutTests(unittest.TestCase):
    def setUp(self):
        self.k = _AiKit()
        self.repo = tempfile.mkdtemp(prefix="airepo-")
        git(self.repo, "init", "-q")
        with open(os.path.join(self.repo, "README.md"), "wb") as fh:
            fh.write(b"customer\n")
        self.commit("base")

    def tearDown(self):
        shutil.rmtree(self.k.root, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)

    def commit(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@invalid", "commit", "-qm", msg)

    def read(self, rel):
        with open(os.path.join(self.repo, *rel.split("/")), "rb") as fh:
            return fh.read()

    def write(self, rel, data):
        p = os.path.join(self.repo, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)

    def tree(self):
        out = {}
        for dp, dns, fns in os.walk(self.repo):
            if ".git" in dp.split(os.sep):
                continue
            for f in fns:
                p = os.path.join(dp, f)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, self.repo)] = fh.read()
        return out

    # ------------------------------------------------------------------------------------------ чистый клон
    def test_clean_clone_idempotent_agents_equals_claude(self):
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read("AGENTS.md"), self.read("CLAUDE.md"))
        for src, dst, role in self.k.entries:
            if role == "managed":
                self.assertEqual(sha(self.read(dst)), self.k.src_sha(src), dst)
        self.assertIn(b".workshop/me.yaml\n", self.read(".gitignore"))
        self.assertEqual(git(self.repo, "check-ignore", "-q", ".workshop/me.yaml").returncode, 0)
        kv = self.read(".workshop/kit-version.yaml").decode("utf-8")
        self.assertIn("managed:\n  - path: .workshop-ai/workshop-full.md", kv)
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("без изменений", out.split("\n")[-2])
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")

    # ------------------------------------------------------------------------------------------ supersedes / конфликт
    def test_supersedes_known_old_standing_is_replaced_with_diff(self):
        self.write("AGENTS.md", OLD_AGENTS)
        self.write("CLAUDE.md", OLD_AGENTS)
        self.commit("hand standing")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("~ AGENTS.md (managed: прежнее содержимое комплекта %s)" % sha(OLD_AGENTS)[:12], out)
        self.assertIn("-# old standing written by hand", out)
        self.assertEqual(self.read("AGENTS.md"), self.read("CLAUDE.md"))

    def test_local_edit_of_managed_is_named_conflict_nothing_written(self):
        self.write("AGENTS.md", b"# customer edited\n")
        self.write("CLAUDE.md", OLD_AGENTS)
        self.commit("edited")
        before = self.tree()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("КОНФЛИКТ AGENTS.md: локальная правка управляемого файла — ожидался sha256 %s, фактический %s; файл не тронут"
                      % (sha(OLD_AGENTS), sha(b"# customer edited\n")), out)
        self.assertNotIn("КОНФЛИКТ CLAUDE.md", out)
        self.assertEqual(self.tree(), before, "при конфликте ничего не записано")

    def test_upgrade_over_own_previous_version_and_conflict_after_edit(self):
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.commit("v1")
        self.k.put("profiles/out/.workshop-ai/workshop-hours.md", b"# Workshop - hours\n\nnorm v2\n")
        self.k.write_manifest("9.9.10")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("~ .workshop-ai/workshop-hours.md (managed: прежнее содержимое комплекта", out)
        self.assertEqual(self.read(".workshop-ai/workshop-hours.md"), b"# Workshop - hours\n\nnorm v2\n")
        self.commit("v2")
        self.write(".workshop-ai/workshop-hours.md", b"# Workshop - hours\n\nnorm v2\nmy note\n")
        self.k.put("profiles/out/.workshop-ai/workshop-hours.md", b"# Workshop - hours\n\nnorm v3\n")
        self.k.write_manifest("9.9.11")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("КОНФЛИКТ .workshop-ai/workshop-hours.md", out)
        self.assertEqual(self.read(".workshop-ai/workshop-hours.md"), b"# Workshop - hours\n\nnorm v2\nmy note\n")

    def test_unknown_existing_managed_without_record_is_conflict(self):
        self.write(".workshop-ai/workshop-full.md", b"customer own file\n")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("КОНФЛИКТ .workshop-ai/workshop-full.md", out)
        self.assertIn("(прежней раскладки комплекта нет)", out)

    # ------------------------------------------------------------------------------------------ retire
    def test_retire_by_sha_with_diff_and_commit_deletion(self):
        self.write(".workshop/ai/workshop-hours-v0.md", OLD_HOURS_V0)
        self.commit("v0")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("- .workshop/ai/workshop-hours-v0.md (retire: sha256 совпал с ожидаемым %s — снимается)" % sha(OLD_HOURS_V0)[:12], out)
        self.assertIn("-# hours v0", out)
        self.assertIn("retire=1", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".workshop/ai/workshop-hours-v0.md")))
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        shown = git(self.repo, "show", "--name-status", "--format=", "HEAD").stdout
        self.assertIn("D\t.workshop/ai/workshop-hours-v0.md", shown)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("retire — файла нет", out)
        self.assertIn("retire=0", out)

    def test_retire_modified_is_conflict_untouched(self):
        self.write(".workshop/ai/workshop-hours-v0.md", OLD_HOURS_V0 + b"customer note\n")
        before = self.tree()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("КОНФЛИКТ .workshop/ai/workshop-hours-v0.md: локальная правка снимаемого файла — ожидался sha256 %s, фактический %s"
                      % (sha(OLD_HOURS_V0), sha(OLD_HOURS_V0 + b"customer note\n")), out)
        self.assertEqual(self.tree(), before)

    def test_all_conflicts_named_at_once_and_dry_run_refuses_too(self):
        self.write(".workshop/ai/workshop-hours-v0.md", b"edited v0\n")
        self.write("AGENTS.md", b"edited\n")
        before = self.tree()
        for extra in (("--dry-run",), ()):
            rc, out = self.k.install(self.repo, "layout", *extra)
            self.assertEqual(rc, 2, out)
            self.assertIn("КОНФЛИКТ AGENTS.md", out)
            self.assertIn("КОНФЛИКТ .workshop/ai/workshop-hours-v0.md", out)
            self.assertIn("конфликтов 2", out)
            self.assertEqual(self.tree(), before)

    def test_retire_of_a_destination_is_manifest_contradiction(self):
        self.k.retire = [("AGENTS.md", sha(b"x"))]
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("retire AGENTS.md совпадает с назначением", out)

    # ------------------------------------------------------------------------------------------ переезд .workshop/ai -> .workshop-ai
    # Матрица мутаций пакетом (правило сходимости §5) для retire прежнего места профилей: законный переезд по записи
    # последней раскладки; по отпечатку манифеста без записи (законная вариация); потеря (файла нет); перестановка
    # (порядок retire и назначений — тот же итог); дубликат (отказ до мутаций); правка заказчика (конфликт, оба
    # ожидаемых отпечатка названы); обратные контроли: чужой файл в старом каталоге и прежнее назначение без retire
    # не снимаются.
    OLD = (".workshop/ai/workshop-hours.md", ".workshop/ai/workshop-full.md")
    NEW = (".workshop-ai/workshop-hours.md", ".workshop-ai/workshop-full.md")
    SRC = ("profiles/out/.workshop-ai/workshop-hours.md", "profiles/out/.workshop-ai/workshop-full.md")

    def old_kit_installed(self):
        """Комплект прежней версии: профили на старом месте; разложен и закоммичен (kit-version.yaml managed помнит SHA)."""
        self.k.entries = [e for e in self.k.entries if e[2] != "managed" or not e[1].startswith(".workshop-ai/")]
        self.k.entries += [(s, o, "managed") for s, o in zip(self.SRC, self.OLD)]
        self.k.retire = []
        self.k.write_manifest("9.9.9")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        kv = self.read(".workshop/kit-version.yaml").decode("utf-8")
        self.assertIn("  - path: .workshop/ai/workshop-hours.md", kv)

    def new_kit(self, retire_sha=None, reverse=False, dup=False, retire_paths=None):
        """Комплект новой версии: профили в .workshop-ai/, retire прежних путей с отпечатком «иного выпуска» (не равным
        разложенному) — снимать файл должна запись последней раскладки."""
        self.k.entries = [e for e in self.k.entries if not e[1].startswith(".workshop/ai/")]
        self.k.entries = [e for e in self.k.entries if e[2] != "managed" or not e[1].startswith(".workshop-ai/")]
        self.k.entries += [(s, n, "managed") for s, n in zip(self.SRC, self.NEW)]
        paths = list(self.OLD if retire_paths is None else retire_paths)
        self.k.retire = [(p, retire_sha or sha(b"another release of " + p.encode())) for p in paths]
        if dup:
            self.k.retire.append(self.k.retire[0])
        if reverse:
            self.k.retire.reverse()
            self.k.entries.reverse()
        self.k.write_manifest("9.9.10")

    def test_relocation_old_profiles_retired_by_laid_record_and_committed(self):
        self.old_kit_installed()
        self.new_kit()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        for o in self.OLD:
            self.assertIn("- %s (retire: sha256 совпал с последней раскладкой комплекта" % o, out)
            self.assertFalse(os.path.exists(os.path.join(self.repo, o)), o)
        for s, n in zip(self.SRC, self.NEW):
            self.assertEqual(sha(self.read(n)), self.k.src_sha(s), n)
        self.assertIn("retire=2", out)
        kv = self.read(".workshop/kit-version.yaml").decode("utf-8")
        self.assertNotIn(".workshop/ai/", kv)
        self.assertIn("  - path: .workshop-ai/workshop-full.md", kv)
        rc, out = self.k.install(self.repo, "commit")
        self.assertEqual(rc, 0, out)
        shown = git(self.repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").stdout
        for o in self.OLD:
            self.assertIn("D\t%s" % o, shown)
        for n in self.NEW:
            self.assertIn("A\t%s" % n, shown)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("retire=0", out)
        self.assertIn("без изменений", out.split("\n")[-2])

    def test_relocation_by_manifest_sha_without_laid_record(self):
        """Законная вариация: файла нет в записи раскладки (положен не комплектом этой установки), байты == отпечатку
        манифеста — снимается по отпечатку манифеста."""
        data = b"# Workshop - hours\n\nreleased bytes\n"
        self.write(self.OLD[0], data)
        self.commit("hand copy")
        self.new_kit(retire_paths=[self.OLD[0]], retire_sha=sha(data))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("- %s (retire: sha256 совпал с ожидаемым %s — снимается)" % (self.OLD[0], sha(data)[:12]), out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, self.OLD[0])))

    def test_relocation_loss_old_files_absent(self):
        """Потеря: прежних файлов нет (сняты руками) — не ошибка; новые кладутся."""
        self.old_kit_installed()
        for o in self.OLD:
            os.remove(os.path.join(self.repo, o))
        self.new_kit()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        for o in self.OLD:
            self.assertIn("  %s: retire — файла нет" % o, out)
        self.assertIn("retire=0", out)
        for n in self.NEW:
            self.assertTrue(os.path.exists(os.path.join(self.repo, n)), n)

    def test_relocation_customer_edit_is_conflict_naming_both_fingerprints(self):
        self.old_kit_installed()
        laid = sha(self.read(self.OLD[0]))
        self.write(self.OLD[0], self.read(self.OLD[0]) + b"my note\n")
        self.new_kit()
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("КОНФЛИКТ %s: локальная правка снимаемого файла — ожидался sha256 %s или %s, фактический %s; файл не тронут"
                      % (self.OLD[0], sha(b"another release of " + self.OLD[0].encode()), laid, sha(self.read(self.OLD[0]))), out)
        self.assertNotIn("КОНФЛИКТ %s" % self.OLD[1], out)
        self.assertEqual(self.full_snap(), before, "при конфликте ничего не записано и не снято")

    def test_relocation_permutation_same_result(self):
        """Перестановка порядка retire и назначений в манифесте — побайтово тот же итог дерева."""
        results = []
        for reverse in (False, True):
            self.fresh_rich()
            self.old_kit_installed()
            self.new_kit(reverse=reverse)
            rc, out = self.k.install(self.repo, "layout")
            self.assertEqual(rc, 0, out)
            results.append(self.full_snap())
        self.assertEqual(results[0], results[1])

    def test_relocation_duplicate_retire_refused_nothing_changed(self):
        self.old_kit_installed()
        self.new_kit(dup=True)
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("цель %s дважды" % self.OLD[0], out)
        self.assertEqual(self.full_snap(), before)

    def test_relocation_reverse_controls_foreign_file_and_unlisted_old_destination_kept(self):
        """Обратный контроль: чужой файл в прежнем каталоге не снимается; прежнее назначение, не названное retire, тоже
        не снимается (снятие только по явному списку, запись раскладки — лишь второй допустимый отпечаток)."""
        self.old_kit_installed()
        self.write(".workshop/ai/my-notes.md", b"customer notes\n")
        self.new_kit(retire_paths=[self.OLD[0]])
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, self.OLD[0])))
        self.assertTrue(os.path.exists(os.path.join(self.repo, self.OLD[1])), "прежнее назначение без retire снято молча")
        self.assertEqual(self.read(".workshop/ai/my-notes.md"), b"customer notes\n")
        self.assertIn("retire=1", out)

    # ------------------------------------------------------------------------------------------ build_manifest: retire
    # Оракул проекции — СВОЙ построчный читатель retire.yaml и манифеста (не yamlmini писателя, правило сходимости §2):
    # ожидание — полные пары (path, sha256) реестра в его порядке и кратности; сверка — побайтово, без префиксов.
    CANON = {"hours": ".workshop-ai/workshop-hours.md", "tickets": ".workshop-ai/workshop-tickets.md",
             "docs": ".workshop-ai/workshop-docs.md", "full": ".workshop-ai/workshop-full.md"}

    @staticmethod
    def read_retire_registry(text, section="retire"):
        """kit/retire.yaml своим читателем: записи секции (retire | supersedes) — словари ключ → строка (кавычки сняты)."""
        out, cur, sec = [], None, None
        for line in text.split("\n"):
            if line and not line.startswith(" ") and not line.startswith("#"):
                sec = line.split(":", 1)[0]
                continue
            if sec != section or not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("  - "):
                cur = {}
                out.append(cur)
                line = "    " + line[4:]
            k, v = line.strip().split(":", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = v[1:-1]
            cur[k] = v
        return out

    @staticmethod
    def read_manifest_section(text, section, fields):
        """Секция верхнего уровня манифеста своим читателем -> список кортежей полей записей в порядке файла."""
        lines = text.split("\n")
        if section + ":" not in lines:
            return []
        out, cur = [], None
        for line in lines[lines.index(section + ":") + 1:]:
            if line and not line.startswith(" "):
                break
            if line.startswith("  - "):
                cur = {}
                out.append(cur)
                line = "    " + line[4:]
            if line.strip():
                k, v = line.strip().split(":", 1)
                cur[k] = v.strip().strip('"')
        return [tuple(r.get(f) for f in fields) for r in out]

    STANDING = ("AGENTS.md", "CLAUDE.md")

    def bm_kit(self, profiles=("hours", "tickets", "docs", "full"), retire_text=None, dests=None, require=True, standing=True,
               layers=()):
        """Комплект для build_manifest: реестр профилей (назначения — dests или канонические), выходы и пиннинг;
        retire.yaml — рабочий или подменённый; layers — записи inputs пиннинга (логическое имя, sha256). -> (rc, stdout, stderr)."""
        dests = dict(self.CANON, **(dests or {}))
        k = tempfile.mkdtemp(prefix="bmkit-", dir=self.k.root)
        os.makedirs(os.path.join(k, "bot"))
        shutil.copytree(_KIT, os.path.join(k, "bot", "kit"), ignore=shutil.ignore_patterns("__pycache__", "manifest.yaml"))
        shutil.copy(os.path.join(_BOT, "yamlmini.py"), os.path.join(k, "bot"))
        reg = ["profiles:"]
        pins = ["schema_version: 1"]
        if layers:
            pins.append("inputs:")
            for lp, ls in layers:
                pins += ['  - path: "%s"' % lp, '    sha256: "%s"' % ls]
        pins.append("outputs:")
        for pid in profiles:
            data = ("# %s\n" % pid).encode()
            p = os.path.join(k, "profiles", "out", *dests[pid].split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(data)
            reg += ["  - id: %s" % pid, '    destination: "%s"' % dests[pid]]
            pins += ['  - path: "profiles/out/%s"' % dests[pid], '    sha256: "%s"' % sha(data)]
        art = ["artifacts: []"]
        if standing:
            art = ["artifacts:", "  - id: standing-customer", '    destination: "%s"' % " ".join(self.STANDING)]
            for d in self.STANDING:
                data = b"# standing\n"
                with open(os.path.join(k, "profiles", "out", d), "wb") as fh:
                    fh.write(data)
                pins += ['  - path: "profiles/out/%s"' % d, '    sha256: "%s"' % sha(data)]
        os.makedirs(os.path.join(k, "profiles"), exist_ok=True)
        with open(os.path.join(k, "profiles", "profiles.yaml"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(reg + art) + "\n")
        with open(os.path.join(k, "profiles", "sources-manifest.yaml"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(pins) + "\n")
        if retire_text is not None:
            with open(os.path.join(k, "bot", "kit", "retire.yaml"), "w", encoding="utf-8") as fh:
                fh.write(retire_text)
        cmd = [PY, os.path.join(k, "bot", "kit", "build_manifest.py"), "--kit", os.path.join(k, "bot", "kit")]
        p = subprocess.run(cmd + (["--require-profiles"] if require else []), capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def registry_text(self):
        with open(os.path.join(_KIT, "retire.yaml"), encoding="utf-8") as fh:
            return fh.read()

    def test_build_manifest_retire_projection_full_pairs_order_and_multiplicity(self):
        """КАЖДАЯ секция манифеста, выводимая из реестров, — полными записями, в порядке и кратности (класс B-M1/B2-M1):
        retire и supersedes ← kit/retire.yaml; entries[role=managed] ← назначения profiles.yaml × пиннинг выходов.
        Потеря, дубликат, перестановка (в т. ч. путей при равных SHA), суффиксная подмена и обнуление ловятся."""
        rc, out, err = self.bm_kit()
        self.assertEqual(rc, 0, out + err)
        for sec, n in (("retire", 7), ("supersedes", 2)):
            reg = self.read_retire_registry(self.registry_text(), sec)
            want = [(r["path"], r["sha256"]) for r in reg]
            self.assertEqual(len(want), n, sec)
            for path, s in want:
                self.assertRegex(s, r"^[0-9a-f]{64}$", path)
            self.assertEqual(self.read_manifest_section(out, sec, ("path", "sha256")), want, sec)
        for f in ("replaced_by", "origin", "reason"):
            self.assertNotIn(f, out)                                 # поля реестра в манифест не идут
        want_m = sorted([("profiles/out/" + d, d, sha(("# %s\n" % pid).encode())) for pid, d in self.CANON.items()]
                        + [("profiles/out/" + d, d, sha(b"# standing\n")) for d in self.STANDING])
        got_m = [(s, d, h) for s, d, r, h in self.read_manifest_section(out, "entries", ("src", "dst", "role", "sha256"))
                 if r == "managed"]
        self.assertEqual(got_m, want_m)
        self.assertEqual([r for s, d, r in self.read_manifest_section(out, "entries", ("src", "dst", "role"))
                          if s.startswith("profiles/")], ["managed"] * len(want_m))

    def test_build_manifest_destinations_read_from_registry_legal_variation(self):
        """Законная вариация назначений всех четырёх профилей: retire проецируется полностью (7), назначения managed —
        ровно значения реестра; ожидание не выводится из id (вторая таблица путей была бы поймана)."""
        moved = {"hours": "agent-profiles/v3-hours.md", "tickets": "agent-profiles/tix.md",
                 "docs": "kb/agent/docs-profile.md", "full": "all-in-one.md"}
        rc, out, err = self.bm_kit(dests=moved)
        self.assertEqual(rc, 0, out + err)
        reg = self.read_retire_registry(self.registry_text())
        self.assertEqual(self.read_manifest_section(out, "retire", ("path", "sha256")), [(r["path"], r["sha256"]) for r in reg])
        managed = sorted(d for d, role in self.read_manifest_section(out, "entries", ("dst", "role")) if role == "managed")
        self.assertEqual(managed, sorted(list(moved.values()) + list(self.STANDING)))
        self.assertNotIn(".workshop-ai/workshop-", out)         # канонические назначения профилей не просочились
        self.assertNotIn("retire ", err)                          # каждая запись retire спроецирована

    def test_build_manifest_retire_unknown_profile_refused(self):
        rc, out, err = self.bm_kit(profiles=("hours",))
        self.assertEqual(rc, 2, out + err)
        self.assertIn("replaced_by_profile full — нет такого профиля в profiles/profiles.yaml", out)

    def test_build_manifest_retire_replacement_exactly_one_field(self):
        base = ("schema_version: 1\nregistry: kit_retire\nretire:\n  - path: .workshop/ai/x.md\n    sha256: %s\n"
                "    origin: customer_live\n" % sha(b"x"))
        for extra, word in (("", "ни одного"),
                            ("    replaced_by_profile: hours\n    replaced_by: .gitattributes\n", "оба")):
            rc, out, err = self.bm_kit(retire_text=base + extra)
            self.assertEqual(rc, 2, out + err)
            self.assertIn("замена задаётся ровно одним из replaced_by_profile / replaced_by (задано: %s)" % word, out)

    def test_build_manifest_retire_origin_closed_set(self):
        """Неизвестное (в т. ч. той же длины) или отсутствующее origin, kit_output без origin_ref, customer_live с
        origin_ref — отказ: запись не выпадает из сверки отпечатков молча. Обратный контроль — рабочий реестр rc 0."""
        reg = self.registry_text()
        cases = [
            (reg.replace("    origin: kit_output\n", "    origin: kit_outpuX\n", 1), "origin 'kit_outpuX' — не из customer_live|kit_output"),
            (reg.replace("    origin: customer_live\n", "", 1), "origin None — не из customer_live|kit_output"),
            (reg.replace('    origin_ref: "4574eb1:profiles/out/.workshop/ai/workshop-hours.md"\n', "", 1),
             "origin kit_output без origin_ref"),
            (reg.replace("    origin: customer_live\n", '    origin: customer_live\n    origin_ref: "x:y"\n', 1),
             "origin customer_live не несёт origin_ref"),
        ]
        old_ref = '    origin_ref: "4574eb1:profiles/out/.workshop/ai/workshop-hours.md"\n'
        for bad_ref in ('"4574eb1"', '":profiles/out/.workshop/ai/workshop-hours.md"', '"4574eb1:"'):   # B2-m2: форма
            cases.append((reg.replace(old_ref, "    origin_ref: %s\n" % bad_ref, 1), "origin kit_output без origin_ref"))
        for text, msg in cases:
            self.assertNotEqual(text, reg)
            rc, out, err = self.bm_kit(retire_text=text)
            self.assertEqual(rc, 2, out + err)
            self.assertIn(msg, out)
        rc, out, err = self.bm_kit(retire_text=reg)
        self.assertEqual(rc, 0, out + err)

    def test_build_manifest_retire_path_replacement_and_duplicate(self):
        """Законная вариация: замена — назначение не-профиля (путь) — проецируется; дубликат пути в реестре — отказ."""
        one = "  - path: .workshop/ai/x.md\n    sha256: %s\n    replaced_by: .gitattributes\n    origin: customer_live\n" % sha(b"x")
        head = "schema_version: 1\nregistry: kit_retire\nretire:\n"
        rc, out, err = self.bm_kit(retire_text=head + one)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.read_manifest_section(out, "retire", ("path", "sha256")), [(".workshop/ai/x.md", sha(b"x"))])
        rc, out, err = self.bm_kit(retire_text=head + one + one)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("retire .workshop/ai/x.md дважды в kit/retire.yaml", out)

    def test_build_manifest_without_profile_registry_notes_not_refuses(self):
        """Без выходов генератора (и реестра профилей) retire с заменой-профилем не проецируется — примечание, не отказ."""
        k = tempfile.mkdtemp(prefix="bmkit-", dir=self.k.root)
        os.makedirs(os.path.join(k, "bot"))
        shutil.copytree(_KIT, os.path.join(k, "bot", "kit"), ignore=shutil.ignore_patterns("__pycache__", "manifest.yaml"))
        shutil.copy(os.path.join(_BOT, "yamlmini.py"), os.path.join(k, "bot"))
        p = subprocess.run([PY, os.path.join(k, "bot", "kit", "build_manifest.py"), "--kit", os.path.join(k, "bot", "kit")],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("retire:", p.stdout)

    # ------------------------------------------------------------------------------------------ слой заказчика (D10 T24)
    LAYER = b'schema_version: 1\nrepo: "example-org/example-tracker"\nforge: "ExampleForge"\n'
    LAYER_DST = ".workshop-ai/customer-layer.yaml"

    def assert_nothing_written(self, out):
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".workshop")), out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "AGENTS.md")), out)

    def test_layer_binding_equal_layer_installs_and_layer_untouched(self):
        self.k.binding = (self.LAYER_DST, sha(self.LAYER))
        self.k.write_manifest()
        self.write(self.LAYER_DST, self.LAYER)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("слой заказчика %s совпадает с привязкой манифеста (sha256 %s)" % (self.LAYER_DST, sha(self.LAYER)), out)
        self.assertEqual(self.read(self.LAYER_DST), self.LAYER)
        self.assertEqual(sha(self.read("AGENTS.md")), self.k.src_sha("profiles/out/AGENTS.md"))

    def test_layer_binding_missing_layer_named_refusal_nothing_written(self):
        self.k.binding = (self.LAYER_DST, sha(self.LAYER))
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("нет слоя заказчика %s: инструкции агента в комплекте собраны под слой sha256 %s" % (self.LAYER_DST, sha(self.LAYER)), out)
        self.assertNotIn("Traceback", out)
        self.assert_nothing_written(out)

    def test_layer_binding_mutation_pack_refused_and_reverse_control(self):
        """Пакет мутаций байт слоя клона (§5): потеря строки, дубликат строки, перестановка строк, суффиксная подмена,
        обнуление, подмена значения той же длины, лишний финальный LF — именованный отказ rc 2, ничего не записано.
        Обратный контроль: те же байты, записанные заново (иной mtime, иной inode), — rc 0."""
        lines = self.LAYER.split(b"\n")
        muts = {
            "потеря": b"\n".join(lines[:1] + lines[2:]),
            "дубликат": b"\n".join(lines[:2] + lines[1:]),
            "перестановка": b"\n".join([lines[0], lines[2], lines[1]] + lines[3:]),
            "суффикс": self.LAYER + b"# x\n",
            "обнуление": b"",
            "та же длина": self.LAYER.replace(b"example-tracker", b"example-trackeR"),
            "лишний LF": self.LAYER + b"\n",
        }
        self.k.binding = (self.LAYER_DST, sha(self.LAYER))
        self.k.write_manifest()
        for name, data in muts.items():
            self.assertNotEqual(data, self.LAYER, name)
            self.write(self.LAYER_DST, data)
            rc, out = self.k.install(self.repo, "layout")
            self.assertEqual(rc, 2, "%s: %s" % (name, out))
            self.assertIn("слой заказчика %s (sha256 %s) не тот, под который собраны инструкции агента комплекта (sha256 %s)"
                          % (self.LAYER_DST, sha(data), sha(self.LAYER)), out)
            self.assert_nothing_written(out)
        os.remove(os.path.join(self.repo, *self.LAYER_DST.split("/")))
        self.write(self.LAYER_DST, bytes(self.LAYER))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)

    def test_layer_binding_not_regular_file_and_symlink_refused(self):
        self.k.binding = (self.LAYER_DST, sha(self.LAYER))
        self.k.write_manifest()
        os.makedirs(os.path.join(self.repo, *self.LAYER_DST.split("/")))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("слой заказчика %s — не обычный файл" % self.LAYER_DST, out)
        os.rmdir(os.path.join(self.repo, *self.LAYER_DST.split("/")))
        outside = os.path.join(self.k.root, "layer-outside.yaml")
        with open(outside, "wb") as fh:
            fh.write(self.LAYER)
        os.symlink(outside, os.path.join(self.repo, *self.LAYER_DST.split("/")))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("симлинк на пути", out)
        self.assert_nothing_written(out)

    def test_layer_binding_malformed_is_manifest_refusal(self):
        good = sha(self.LAYER)
        for text in ("customer_layer:\n  path: %s\n  sha256: %s" % (self.LAYER_DST, good[:-1]),          # 63 hex
                     "customer_layer:\n  path: %s\n  sha256: %sa" % (self.LAYER_DST, good),             # суффикс
                     "customer_layer:\n  sha256: %s" % good,                                            # потеря поля
                     "customer_layer:\n  path: %s\n  sha256: %s\n  extra: x" % (self.LAYER_DST, good),  # лишнее поле
                     "customer_layer: %s" % self.LAYER_DST):                                              # не запись
            self.k.binding = text
            self.k.write_manifest()
            self.write(self.LAYER_DST, self.LAYER)
            rc, out = self.k.install(self.repo, "layout")
            self.assertEqual(rc, 2, "%s: %s" % (text, out))
            self.assertIn("манифест: customer_layer не запись {path, sha256 (64 hex)}", out)
            self.assert_nothing_written(out)

    def test_layer_binding_without_managed_entries_is_not_checked(self):
        self.k.entries = [e for e in self.k.entries if e[2] != "managed"]
        self.k.retire, self.k.supersedes = [], []
        self.k.binding = (self.LAYER_DST, sha(self.LAYER))
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("слой заказчика", out)

    def test_build_manifest_layer_binding_projection(self):
        """Привязка customer_layer ← запись слоя во inputs пиннинга: путь — дом слоя у заказчика, sha — пиннинга; оба
        логическое имя слоя — образец (при любом источнике байт); дубль записи слоя — отказ; прежнее имя слоя в комплекте
        (пиннинг до T24), нет слоя во inputs или нет записей managed — привязки нет. Образец кладётся ролью code в
        .workshop-ai/, шаблон standing — нет."""
        h = sha(b"layer")
        rc, out, err = self.bm_kit(layers=[("bot/kit/ai/customer-layer.example.yaml", h), ("spec/x.md", sha(b"x"))])
        self.assertEqual(rc, 0, out + err)
        head = out.split("entries:")[0]
        self.assertIn("customer_layer:\n  path: .workshop-ai/customer-layer.yaml\n  sha256: %s\n" % h, head)
        rc, out, err = self.bm_kit(layers=[("bot/kit/ai/customer-layer.example.yaml", h),
                                           ("bot/kit/ai/customer-layer.example.yaml", sha(b"other"))])
        self.assertEqual(rc, 2, out + err)
        self.assertIn("манифест пиннинга профилей называет слой заказчика дважды", out)
        for layers in ([("bot/kit/ai/customer-layer.yaml", h)], [("spec/x.md", h)], [("bot/kit/ai/customer-layer.example.yamlx", h)]):
            rc, out, err = self.bm_kit(layers=layers)
            self.assertEqual(rc, 0, out + err)
            self.assertNotIn("customer_layer", out)
        rc, out, err = self.bm_kit(profiles=(), standing=False, layers=[("bot/kit/ai/customer-layer.example.yaml", h)])
        self.assertNotIn("customer_layer", out)
        rows = self.read_manifest_section(self.bm_kit()[1], "entries", ("src", "dst", "role"))
        self.assertIn(("bot/kit/ai/customer-layer.example.yaml", ".workshop-ai/customer-layer.example.yaml", "code"), rows)
        self.assertEqual([r for r in rows if r[0].startswith("bot/kit/ai/")],
                         [("bot/kit/ai/customer-layer.example.yaml", ".workshop-ai/customer-layer.example.yaml", "code")])

    def test_install_steps_declares_customer_layer_step(self):
        """Шаг «положить слой заказчика» объявлен в реестре ручных шагов (N честно +1): when always, путь слоя в шаге ==
        дому слоя у build_manifest (CUSTOMER_LAYER_DST — единственный адрес), образец назван. Свой читатель (PyYAML/regex)."""
        import re
        import yaml
        steps = yaml.safe_load(open(os.path.join(_KIT, "install-steps.yaml"), encoding="utf-8"))["steps"]
        ids = [st["id"] for st in steps]
        self.assertIn("customer_layer", ids)
        st = steps[ids.index("customer_layer")]
        self.assertEqual(st["when"], "always")
        dst = re.search(r'^CUSTOMER_LAYER_DST = "([^"]+)"', open(os.path.join(_KIT, "build_manifest.py"), encoding="utf-8").read(), re.M).group(1)
        self.assertIn(dst, st["title"] + st["guide"])
        self.assertIn("customer-layer.example.yaml", st["guide"])
        self.assertLess(ids.index("customer_layer"), ids.index("copy_bootstrap_workflow"))   # до первого bootstrap

    # ------------------------------------------------------------------------------------------ сироты временных файлов (B m3)
    CRASH = """import os, sys
sys.argv = sys.argv[:1] + sys.argv[2:]
sys.path.insert(0, os.path.dirname(sys.argv[1]))
import importlib.util
spec = importlib.util.spec_from_file_location("install", sys.argv[1]); inst = importlib.util.module_from_spec(spec); spec.loader.exec_module(inst)
real = os.replace
def replace(a, b):
    real(a, b)
    os._exit(86)                     # смерть процесса сразу после первой замены: журнал отката в памяти потерян
os.replace = replace
sys.exit(inst.main(sys.argv[2:]))
"""

    def orphans(self):
        return sorted(os.path.relpath(os.path.join(dp, f), self.repo) for dp, dns, fns in os.walk(self.repo)
                      if ".git" not in dp.split(os.sep) for f in fns if f.startswith(".workshop-kit-tmp-"))

    def test_crash_after_first_replace_retry_leaves_no_temp_files(self):
        drv = os.path.join(self.k.root, "crash.py")
        with open(drv, "w", encoding="utf-8") as fh:
            fh.write(self.CRASH)
        p = subprocess.run([PY, drv, "x", os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "--repo", self.repo,
                            "--manifest", self.k.manifest, "layout"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 86, p.stdout + p.stderr)
        left = self.orphans()
        self.assertTrue(left, "сценарий не оставил сирот — проверка беспредметна")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        for o in left:
            self.assertIn("- %s (временный файл прерванной раскладки комплекта — снимается)" % o.replace(os.sep, "/"), out)
        self.assertIn("tmp=%d" % len(left), out)
        self.assertEqual(self.orphans(), [])
        for src, dst, role in self.k.entries:
            if role == "managed":
                self.assertEqual(sha(self.read(dst)), self.k.src_sha(src), dst)
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("tmp=", out)
        self.assertIn("без изменений", out.split("\n")[-2])

    def test_orphan_cleanup_exact_name_regular_file_target_dirs_only(self):
        """Снимаются только файлы точной формы имени, обычные, в каталогах целей; dry-run только называет.
        Обратный контроль: похожие имена, ссылка с точным именем и сирота вне каталогов целей не трогаются."""
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        exact = [".workshop-ai/.workshop-kit-tmp-123-1", ".workshop/.workshop-kit-tmp-99-7", ".workshop-kit-tmp-5-12",
                 ".workshop/ai/.workshop-kit-tmp-4242-1"]        # .workshop/ai/ — каталог ТОЛЬКО retire (B2-m1)
        self.write(".workshop/ai/customer-notes.md", b"customer\n")
        keep = [".workshop-ai/.workshop-kit-tmp-notes", ".workshop-ai/.workshop-kit-tmp-1-2.bak", ".workshop-ai/x.workshop-kit-tmp-1-2",
                "other/.workshop-kit-tmp-5-5"]
        for rel in exact + keep:
            self.write(rel, b"tmp\n")
        os.symlink(os.path.join(self.repo, "README.md"), os.path.join(self.repo, ".workshop-ai", ".workshop-kit-tmp-7-7"))
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("tmp=4", out)
        self.assertEqual(self.full_snap(), before, "dry-run изменил дерево")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertIn("tmp=4", out)
        self.assertEqual(self.read(".workshop/ai/customer-notes.md"), b"customer\n")
        for rel in exact:
            self.assertFalse(os.path.lexists(os.path.join(self.repo, rel)), rel)
        for rel in keep:
            self.assertEqual(self.read(rel), b"tmp\n", rel)
        self.assertTrue(os.path.islink(os.path.join(self.repo, ".workshop-ai", ".workshop-kit-tmp-7-7")))

    # ------------------------------------------------------------------------------------------ плейсхолдер
    def test_unfilled_placeholder_refused_before_mutations(self):
        self.k.put("profiles/out/AGENTS.md", b"# Agent in {{customer: repo}}\n")
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("незаполненный плейсхолдер {{customer: repo}} в AGENTS.md", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".workshop")))

    def test_github_expression_is_not_a_placeholder(self):
        self.k.put("profiles/out/AGENTS.md", b"# Agent\n\nsecret: ${{ secrets.X }}\n")
        self.k.put("profiles/out/CLAUDE.md", b"# Agent\n\nsecret: ${{ secrets.X }}\n")
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)

    # ------------------------------------------------------------------------------------------ .gitignore
    def test_gitignore_line_appended_customer_lines_kept(self):
        self.write(".gitignore", b"node_modules/\n*.log")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(".gitignore"), b"node_modules/\n*.log\n.workshop/me.yaml\n")
        self.assertIn("~ .gitignore (lines: дописано строк 1", out)
        rc, out = self.k.install(self.repo, "layout")
        self.assertIn(".gitignore: обязательные строки на месте", out)

    def test_gitignore_already_has_line(self):
        self.write(".gitignore", b"# personal file of the agent\n.workshop/me.yaml\n")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(".gitignore"), b"# personal file of the agent\n.workshop/me.yaml\n")

    # ------------------------------------------------------------------------------------------ метаданные
    def test_corrupted_managed_record_refused(self):
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        kv = self.read(".workshop/kit-version.yaml").decode("utf-8")
        self.write(".workshop/kit-version.yaml", kv.replace("managed:\n", "managed: broken\nx_managed:\n").encode("utf-8"))
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("managed не список записей", out)

    # ------------------------------------------------------------------------------------------ R1: B7 транзакция
    def full_snap(self):
        """Снимок дерева: для каждого пути (кроме .git) — вид, байты, mode; каталоги тоже (создание/удаление каталога — изменение)."""
        out = {}
        for dp, dns, fns in os.walk(self.repo):
            dns[:] = [d for d in dns if d != ".git"]
            for d in dns:
                out[os.path.relpath(os.path.join(dp, d), self.repo)] = ("dir", os.stat(os.path.join(dp, d)).st_mode & 0o7777)
            for f in fns:
                q = os.path.join(dp, f)
                with open(q, "rb") as fh:
                    out[os.path.relpath(q, self.repo)] = ("file", fh.read(), os.stat(q).st_mode & 0o7777)
        return out

    def rich_repo(self):
        """Исходное состояние, в котором layout делает ВСЕ виды мутаций: создание каталогов и файлов, замену (supersedes),
        дописывание (.gitignore, mode 0600), удаление (retire)."""
        self.write("AGENTS.md", OLD_AGENTS)
        self.write("CLAUDE.md", OLD_AGENTS)
        self.write(".gitignore", b"node_modules/\n")
        os.chmod(os.path.join(self.repo, ".gitignore"), 0o600)
        self.write(".workshop/ai/workshop-hours-v0.md", OLD_HOURS_V0)
        self.commit("rich")

    INJECT = """import os, sys
op, nth, log = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.argv = sys.argv[:1] + sys.argv[4:]
sys.path.insert(0, os.path.dirname(sys.argv[1]))
import importlib.util
spec = importlib.util.spec_from_file_location("install", sys.argv[1]); inst = importlib.util.module_from_spec(spec); spec.loader.exec_module(inst)
state = {"active": False, "n": 0}
orig_run = inst._LayoutTxn.run
def run(self, *a, **k):
    state["active"] = True
    try:
        return orig_run(self, *a, **k)
    finally:
        state["active"] = False
inst._LayoutTxn.run = run
real = getattr(os, op)
def wrapped(*a, **k):
    if state["active"]:
        state["n"] += 1
        if state["n"] == nth:
            raise OSError(28, "инъекция теста: %s #%d" % (op, nth))
    return real(*a, **k)
setattr(os, op, wrapped)
try:
    rc = inst.main(sys.argv[2:])
finally:
    open(log, "w").write(str(state["n"]))
sys.exit(rc)
"""

    def injected(self, op, nth):
        drv = os.path.join(self.k.root, "inject.py")
        with open(drv, "w", encoding="utf-8") as fh:
            fh.write(self.INJECT)
        log = os.path.join(self.k.root, "calls.txt")
        p = subprocess.run([PY, drv, op, str(nth), log, os.path.join(self.k.kit, "install.py"), "--kit", self.k.kit, "--repo", self.repo,
                            "--manifest", self.k.manifest, "layout"], capture_output=True, text=True)
        with open(log) as fh:
            return p.returncode, p.stdout + p.stderr, int(fh.read())

    def fresh_rich(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        self.repo = tempfile.mkdtemp(prefix="airepo-")      # новый каталог: остаток прежнего не мешает
        git(self.repo, "init", "-q")
        self.write("README.md", b"customer\n")
        self.commit("base")
        self.rich_repo()

    def test_b7_fault_matrix_rolls_back_every_position(self):
        """Инвариант B7: отказ ЛЮБОЙ операции мутации (подготовка — mkdir/создание/запись/chmod временного файла; фиксация —
        удаление, замена) в начале, середине и конце — rc 10, дерево (байты, mode, наличие файлов и каталогов) равно исходному."""
        self.k.entries.append(("bot/tg.py", ".workshop/bot/tg.py", "code"))      # новый каталог — есть и mkdir
        self.k.write_manifest()
        counts = {}
        for op in ("mkdir", "open", "write", "chmod", "remove", "replace"):
            self.fresh_rich()
            rc, out, n = self.injected(op, 0)                 # счётный прогон: число вызовов операции в транзакции
            self.assertEqual(rc, 0, out)
            counts[op] = n
        cases = []
        for op, n in counts.items():
            self.assertGreater(n, 0, "операция %s в транзакции не вызывалась — матрица неполна" % op)
            for nth in sorted(set([1, (n + 1) // 2, n])):
                self.fresh_rich()
                start = self.full_snap()
                rc, out, _ = self.injected(op, nth)
                self.assertEqual(rc, 10, "%s #%d/%d: %s" % (op, nth, n, out))
                self.assertIn("инъекция теста: %s #%d" % (op, nth), out)
                self.assertIn("откат: дерево заказчика возвращено", out)
                self.assertEqual(self.full_snap(), start, "%s #%d/%d: дерево после отказа ≠ исходному" % (op, nth, n))
                cases.append("%s#%d/%d" % (op, nth, n))
        print("\n  B7 матрица: %d случаев: %s" % (len(cases), " ".join(cases)))
        self.assertGreaterEqual(len(cases), 12)

    # ------------------------------------------------------------------------------------------ R1: B8 единый план
    def test_b8_retire_duplicate_path_refused_nothing_removed(self):
        self.write(".workshop/ai/workshop-hours-v0.md", OLD_HOURS_V0)
        self.k.retire = [(".workshop/ai/workshop-hours-v0.md", sha(OLD_HOURS_V0))] * 2
        self.k.write_manifest()
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("цель .workshop/ai/workshop-hours-v0.md дважды", out)
        self.assertEqual(self.full_snap(), before)

    def test_b8_retire_of_service_record_refused(self):
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.k.retire = [(".workshop/kit-version.yaml", sha(self.read(".workshop/kit-version.yaml")))]
        self.k.write_manifest()
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn(".workshop/kit-version.yaml дважды (служебная запись и retire)", out)
        self.assertEqual(self.full_snap(), before)

    def test_b8_retire_of_manual_file_refused(self):
        self.k.entries.append(("bot/kit/templates/people.yaml", ".workshop/people.yaml", "manual"))
        self.k.retire = [(".workshop/people.yaml", sha(b"x"))]
        self.k.write_manifest()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn(".workshop/people.yaml", out)

    def test_b8_physical_alias_between_targets_refused(self):
        self.write("AGENTS.md", OLD_AGENTS)
        os.link(os.path.join(self.repo, "AGENTS.md"), os.path.join(self.repo, "CLAUDE.md"))
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn("AGENTS.md и CLAUDE.md — один физический файл", out)
        self.assertEqual(self.full_snap(), before)

    # ------------------------------------------------------------------------------------------ R1: B9 hard link наружу
    @staticmethod
    def dir_bytes(d):
        out = {}
        for f in os.listdir(d):
            with open(os.path.join(d, f), "rb") as fh:
                out[f] = fh.read()
        return out

    def test_b9_hardlink_neighbor_outside_root_unchanged(self):
        outside = tempfile.mkdtemp(prefix="outside-")
        try:
            for rel, data in ((".gitignore", b"node_modules/\n"), ("AGENTS.md", OLD_AGENTS), ("CLAUDE.md", OLD_AGENTS),
                              (".workshop/ai/workshop-hours-v0.md", OLD_HOURS_V0)):
                self.write(rel, data)
                os.link(os.path.join(self.repo, rel), os.path.join(outside, rel.replace("/", "_")))
            snap = self.dir_bytes(outside)
            rc, out = self.k.install(self.repo, "layout")
            self.assertEqual(rc, 0, out)
            self.assertEqual(self.dir_bytes(outside), snap,
                             "соседний файл вне корня изменён через hard link")
            self.assertEqual(os.stat(os.path.join(self.repo, "AGENTS.md")).st_nlink, 1)
            self.assertIn(b".workshop/me.yaml", self.read(".gitignore"))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # ------------------------------------------------------------------------------------------ R1: B10 итог check-ignore, M1
    def ignored(self):
        return git(self.repo, "check-ignore", "-q", ".workshop/me.yaml").returncode == 0

    def test_b10_negation_after_line_managed_line_appended_after(self):
        for neg in (b"!.workshop/me.yaml\n", b"!*.yaml\n"):
            self.write(".gitignore", b".workshop/me.yaml\n" + neg)
            self.assertFalse(self.ignored())
            rc, out = self.k.install(self.repo, "layout")
            self.assertEqual(rc, 0, out)
            self.assertEqual(self.read(".gitignore"), b".workshop/me.yaml\n" + neg + b".workshop/me.yaml\n")
            self.assertTrue(self.ignored(), "после раскладки .workshop/me.yaml не игнорируется")
            rc, out = self.k.install(self.repo, "layout")
            self.assertIn("обязательные строки на месте и действуют", out)

    def test_b10_nested_negation_refused_and_rolled_back(self):
        self.write(".workshop/.gitignore", b"!me.yaml\n")
        before = self.full_snap()
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 2, out)
        self.assertIn(".workshop/me.yaml НЕ игнорируется (git check-ignore)", out)
        self.assertIn("откат: дерево заказчика возвращено", out)
        self.assertEqual(self.full_snap(), before)

    def test_m1_crlf_line_counts_as_present(self):
        self.write(".gitignore", b"a\r\n.workshop/me.yaml\r\n")
        rc, out = self.k.install(self.repo, "layout")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(".gitignore"), b"a\r\n.workshop/me.yaml\r\n")
        self.assertTrue(self.ignored())


if __name__ == "__main__":
    unittest.main()
