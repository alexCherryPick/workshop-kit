"""Оракул install.py types-plan (D10 T24, REQ-085): план конфига типов ТОЛЬКО для типов заказчика, стандартной поставки нет.
Установщик — ПРОЦЕСС на mktemp-репо; оракул не импортирует install.py/yamlmini: деревья — PyYAML, байты — своей нарезкой по
LF; набор форм ядра — у валидатора (WORKSHOP_VALIDATOR, 0.3.0). Каждый прогон проверяет, что конфиг НЕ записан (план —
только печать), а применённый `git apply` план даёт ожидаемое дерево и сохраняет прочие строки побайтово и по порядку."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(_BOT, "kit", "install.py")
PY = sys.executable
VALIDATOR = os.environ.get("WORKSHOP_VALIDATOR", "")

HEAD = ("spec: cherrypick-workshop-format\nconfig_kind: repo_types\nconfig_version: 3\nextends_schema_version: 2\n")
RUNBOOK = "  - name: RUNBOOK\n    record_class: document\n    definition: \"регламент\"\n    fields: []\n"
PLAYBOOK = "  - name: PLAYBOOK\n    record_class: document\n    definition: \"сценарий\"\n    fields: []\n"
TASK_SHADOW = "  - name: TASK\n    record_class: ticket\n    definition: \"работа\"\n    fields: []\n"
REQUEST_SHADOW = "  - name: REQUEST\n    record_class: ticket\n    definition: \"обращение\"\n    fields: []\n"
KERNEL_TIGHT = ("kernel:\n  tightenings:\n    - type: DOC\n      field: status\n      op: require_field\n"
                "      from: {required: false}\n      to: {required: true}\n      diagnostics: {}\n"
                "      rationale: \"статус обязателен\"\n")
INCOMPLETE = "  - name: RUNBOOK\n    record_class: document\n"          # без definition и fields — E-CFG-TYPE-NAME-FORM
NOLF = "добавьте перевод строки в конец файла и повторите"     # отказ R7O-02 (а)


@unittest.skipUnless(VALIDATOR and os.path.isfile(VALIDATOR), "нужен WORKSHOP_VALIDATOR (0.3.0)")
class TypesPlanTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="types-plan-")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        os.makedirs(os.path.join(self.repo, ".workshop"))

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def cfg_path(self):
        return os.path.join(self.repo, ".workshop", "types.yaml")

    def put(self, rel, text):
        p = os.path.join(self.repo, rel)
        with open(p, "wb") as fh:
            fh.write(text.encode("utf-8"))
        return p

    def plan(self, *extra):
        before = open(self.cfg_path(), "rb").read() if os.path.exists(self.cfg_path()) else None
        p = subprocess.run([PY, INSTALL, "--repo", self.repo, "types-plan", "--validator", VALIDATOR] + list(extra),
                           capture_output=True, text=True)
        after = open(self.cfg_path(), "rb").read() if os.path.exists(self.cfg_path()) else None
        self.assertEqual(before, after, "types-plan записал конфиг — план обязан быть только печатью")
        return p.returncode, p.stdout + p.stderr

    def apply(self, out):
        diff = out[out.index("--- a/.workshop/types.yaml"):out.rindex("types-plan: план выше")]
        p = self.put("plan.diff", diff)
        r = subprocess.run(["git", "-C", self.repo, "apply", p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return open(self.cfg_path(), "rb").read().decode("utf-8")

    def check_config(self):
        r = subprocess.run([VALIDATOR, "check-config", "--config", self.cfg_path()], capture_output=True, text=True)
        return r.returncode, r.stdout

    def assert_subsequence(self, old_lines, new_lines, dropped):
        """Инвариант сохранения: каждая строка старого конфига, кроме снятых и config_version, есть в новом — в том же
        порядке и с той же кратностью (побайтово)."""
        keep = [l for k, l in enumerate(old_lines) if k not in dropped and not l.startswith("config_version:")]
        it = iter([l for l in new_lines if not l.startswith("config_version:")])
        for l in keep:
            for m in it:
                if m == l:
                    break
            else:
                self.fail("строка старого конфига потеряна или переставлена: %r" % l)

    # -------------------------------------------------------------------------------- нет конфига
    def test_no_config_no_standard_supply(self):
        rc, out = self.plan()
        self.assertEqual(rc, 0, out)
        self.assertIn("стандартной поставки типов нет (REQ-085)", out)
        self.assertFalse(os.path.exists(self.cfg_path()))

    def test_no_config_with_from_is_named_refusal(self):
        src = self.put("in.yaml", "types:\n" + PLAYBOOK)
        rc, out = self.plan("--from", src)
        self.assertEqual(rc, 2, out)
        self.assertIn("стандартной поставки типов нет (REQ-085)", out)
        self.assertNotIn("Traceback", out)

    # -------------------------------------------------------------------------------- затенение формы ядра (§15.1)
    def test_shadowed_kernel_declaration_removed_rest_conserved(self):
        text = HEAD + "types:\n" + TASK_SHADOW + RUNBOOK
        self.put(".workshop/types.yaml", text)
        rc, out = self.plan()
        self.assertEqual(rc, 0, out)
        self.assertIn("снять: TASK", out)
        new = self.apply(out)
        tree = yaml.safe_load(new)
        self.assertEqual([t["name"] for t in tree["types"]], ["RUNBOOK"])
        self.assertEqual(tree["config_version"], 4)
        old_lines = text.split("\n")
        a = old_lines.index("  - name: TASK")
        self.assert_subsequence(old_lines, new.split("\n"), set(range(a, a + 4)))
        rc, rep = self.check_config()
        self.assertEqual(rc, 0, rep)
        self.assertNotIn("W-CFG-KERNEL-SHADOW", rep)

    def test_two_shadows_any_order_both_removed(self):
        for body in (TASK_SHADOW + RUNBOOK + REQUEST_SHADOW, REQUEST_SHADOW + TASK_SHADOW + RUNBOOK):
            self.put(".workshop/types.yaml", HEAD + "types:\n" + body)
            rc, out = self.plan()
            self.assertEqual(rc, 0, out)
            new = self.apply(out)
            self.assertEqual([t["name"] for t in yaml.safe_load(new)["types"]], ["RUNBOOK"])
            subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    def test_clean_config_without_from_no_change(self):
        self.put(".workshop/types.yaml", HEAD + "types:\n" + RUNBOOK)
        rc, out = self.plan()
        self.assertEqual(rc, 0, out)
        self.assertIn("без изменений", out)
        self.assertNotIn("--- a/", out)

    # -------------------------------------------------------------------------------- типы заказчика из файла
    def test_from_adds_customer_type_tail_conserved(self):
        text = HEAD + "types:\n" + RUNBOOK + "\n# хвост заказчика\nother_key: 1\n"
        self.put(".workshop/types.yaml", text)
        src = self.put("in.yaml", "types:\n" + PLAYBOOK)
        rc, out = self.plan("--from", src)
        self.assertEqual(rc, 0, out)
        new = self.apply(out)
        tree = yaml.safe_load(new)
        self.assertEqual([t["name"] for t in tree["types"]], ["RUNBOOK", "PLAYBOOK"])
        self.assertEqual(tree["other_key"], 1)
        self.assert_subsequence(text.split("\n"), new.split("\n"), set())
        self.assertIn(PLAYBOOK, new)          # элемент входа — побайтово
        rc, rep = self.check_config()
        self.assertIn("-- errors: 0,", rep)   # other_key — неизвестный ключ конфига: предупреждение, не ошибка (rc 1)
        self.assertLessEqual(rc, 1, rep)

    def test_from_into_empty_flow_list(self):
        self.put(".workshop/types.yaml", HEAD + "types: []\n")
        src = self.put("in.yaml", "types:\n" + PLAYBOOK)
        rc, out = self.plan("--from", src)
        self.assertEqual(rc, 0, out)
        new = self.apply(out)
        self.assertEqual([t["name"] for t in yaml.safe_load(new)["types"]], ["PLAYBOOK"])

    def test_from_without_types_key_appends_block(self):
        self.put(".workshop/types.yaml", HEAD)
        src = self.put("in.yaml", "types:\n" + PLAYBOOK)
        rc, out = self.plan("--from", src)
        self.assertEqual(rc, 0, out)
        new = self.apply(out)
        self.assertEqual([t["name"] for t in yaml.safe_load(new)["types"]], ["PLAYBOOK"])
        self.assertEqual(self.check_config()[0], 0)

    def test_from_already_present_identical_any_order(self):
        self.put(".workshop/types.yaml", HEAD + "types:\n" + RUNBOOK + PLAYBOOK)
        src = self.put("in.yaml", "types:\n" + PLAYBOOK + RUNBOOK)     # законная перестановка во входе
        rc, out = self.plan("--from", src)
        self.assertEqual(rc, 0, out)
        self.assertIn("уже есть: RUNBOOK", out)
        self.assertIn("уже есть: PLAYBOOK", out)
        self.assertIn("без изменений", out)

    def test_mutation_pack_on_input(self):
        """Пакет мутаций входа §5: подмена значения той же длины и суффикс — конфликт; дубль — отказ; форма ядра —
        отказ; потеря name — форма не поддержана; обнуление входа — отказ."""
        self.put(".workshop/types.yaml", HEAD + "types:\n" + RUNBOOK)
        cases = [
            ("подмена той же длины", "types:\n" + RUNBOOK.replace("регламент", "регламенТ"), "КОНФЛИКТ: тип RUNBOOK"),
            ("суффикс", "types:\n" + RUNBOOK.replace("fields: []", "fields: []\n    pad_width: 3"), "КОНФЛИКТ: тип RUNBOOK"),
            ("дубль", "types:\n" + PLAYBOOK + PLAYBOOK, "тип PLAYBOOK дважды"),
            ("форма ядра во входе", "types:\n" + REQUEST_SHADOW, "формы ядра REQUEST"),
            ("элемент без name", "types:\n  - record_class: document\n    name: X\n", "без первого ключа name"),
            ("обнуление", "", "во входе нет объявлений types"),
            ("flow-список", "types: [{name: X}]\n", "форма не поддержана"),
        ]
        for name, text, needle in cases:
            src = self.put("in.yaml", text)
            rc, out = self.plan("--from", src)
            self.assertEqual(rc, 2, "%s: %s" % (name, out))
            self.assertIn(needle, out, name)
            self.assertNotIn("Traceback", out, name)

    # -------------------------------------------------------------------------------- R1F-01: результат — валидный конфиг
    def _plan_valid(self, text, *extra):
        """План строится (rc 0), применяется `git apply`, результат проходит check-config без ошибок и без затенения."""
        self.put(".workshop/types.yaml", text)
        rc, out = self.plan(*extra)
        self.assertEqual(rc, 0, out)
        new = self.apply(out)
        crc, rep = self.check_config()
        self.assertIn("-- errors: 0,", rep, new)
        self.assertNotIn("W-CFG-KERNEL-SHADOW", rep)
        self.assertEqual(crc, 0, rep)
        return new, out

    def test_r1f01_dimensions_removal_result_valid(self):
        """Измерения входа снятия: последнее по порядку; единственное; рядом с типом заказчика; рядом с ужесточениями
        ядра (блок kernel до и после types); пустой файл после снятия (только шапка)."""
        cases = [
            ("последнее по порядку", HEAD + "types:\n" + RUNBOOK + TASK_SHADOW, ["RUNBOOK"]),
            ("рядом с типом заказчика", HEAD + "types:\n" + RUNBOOK + TASK_SHADOW + PLAYBOOK, ["RUNBOOK", "PLAYBOOK"]),
            ("единственное, types в середине", HEAD + "types:\n" + TASK_SHADOW + KERNEL_TIGHT, None),
            ("все затеняющие", HEAD + "types:\n" + TASK_SHADOW + REQUEST_SHADOW + "label_pad: []\n", None),
            ("рядом с ужесточениями", HEAD + KERNEL_TIGHT + "types:\n" + TASK_SHADOW + RUNBOOK, ["RUNBOOK"]),
            ("единственное после ужесточений", HEAD + KERNEL_TIGHT + "types:\n" + TASK_SHADOW, None),
            ("пустой файл после снятия", HEAD + "types:\n" + TASK_SHADOW, None),
            ("пустой файл, комментарий в блоке", HEAD + "types:\n  # объявления заказчика\n" + TASK_SHADOW, None),
        ]
        for name, text, names in cases:
            with self.subTest(name):
                new, _out = self._plan_valid(text)
                tree = yaml.safe_load(new)
                if names is None:
                    self.assertNotIn("types", tree, "%s: ключ types без элементов обязан уйти целиком" % name)
                else:
                    self.assertEqual([t["name"] for t in tree["types"]], names, name)
                self.assertEqual(tree["config_version"], 4, name)
                if "kernel" in text:
                    self.assertEqual(tree["kernel"], yaml.safe_load(KERNEL_TIGHT)["kernel"], name)
                if name.startswith("пустой файл"):
                    self.assertEqual(new, HEAD.replace("config_version: 3", "config_version: 4"), name)
                subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    def test_r1f01_incomplete_from_declaration_refused(self):
        """Неполное объявление во входе (без definition/fields): результат не прошёл бы check-config — отказ rc 2 с
        названными кодами валидатора, диффа нет."""
        for base in (HEAD + "types:\n" + RUNBOOK, HEAD, HEAD + "types: []\n"):
            with self.subTest(base=base[-20:]):
                self.put(".workshop/types.yaml", base)
                src = self.put("in.yaml", "types:\n" + INCOMPLETE.replace("RUNBOOK", "PLAYBOOK"))
                rc, out = self.plan("--from", src)
                self.assertEqual(rc, 2, out)
                self.assertIn("E-CFG-TYPE-NAME-FORM", out)
                self.assertIn("не проходит check-config", out)
                self.assertNotIn("--- a/", out)
                self.assertNotIn("Traceback", out)

    def test_r1f01_invalid_config_before_plan_refused(self):
        self.put(".workshop/types.yaml", HEAD + "types:\n" + TASK_SHADOW + INCOMPLETE)
        rc, out = self.plan()
        self.assertEqual(rc, 2, out)
        self.assertIn("уже до плана не проходит check-config", out)
        self.assertNotIn("--- a/", out)

    def _mutant(self, old, new):
        d = tempfile.mkdtemp(prefix="types-plan-mut-")
        self.addCleanup(shutil.rmtree, d, True)
        src = open(INSTALL, encoding="utf-8").read()
        self.assertEqual(src.count(old), 1, "якорь мутанта не найден: %r" % old)
        os.makedirs(os.path.join(d, "kit"))
        mp = os.path.join(d, "kit", "install.py")
        with open(mp, "w", encoding="utf-8") as fh:
            fh.write(src.replace(old, new))
        return mp

    def _run(self, install, *extra):
        env = dict(os.environ, PYTHONPATH=_BOT)
        p = subprocess.run([PY, install, "--repo", self.repo, "types-plan", "--validator", VALIDATOR] + list(extra),
                           capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr

    def test_r1f01_mutants_killed(self):
        """Мутанты самопроверки: (1) самопроверка без check-config — неполный вход даёт план (rc 0) с невалидным
        результатом, тест отказа его ловит; (2) ключ types не убирается — check-config результата отказывает (rc 2),
        тест измерения «единственное» его ловит. Обратный контроль: исходный инструмент на тех же входах — как в тестах."""
        no_check = self._mutant("    _selfcheck_plan(validator, raw, plan, new_text)\n", "")
        keep_key = self._mutant("        drop.update(range(i_types, block_end))\n", "        pass\n")
        self.put(".workshop/types.yaml", HEAD + "types:\n" + RUNBOOK)
        src = self.put("in.yaml", "types:\n" + INCOMPLETE.replace("RUNBOOK", "PLAYBOOK"))
        rc, out = self._run(no_check, "--from", src)
        self.assertEqual(rc, 0, "мутант без check-config не дал плана — тест отказа его не различает: " + out)
        self.apply(out)
        self.assertEqual(self.check_config()[0], 2, "результат мутанта валиден — мутант не опасен")
        subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)
        self.assertEqual(self._run(INSTALL, "--from", src)[0], 2)
        self.put(".workshop/types.yaml", HEAD + "types:\n" + TASK_SHADOW)
        rc, out = self._run(keep_key)
        self.assertEqual(rc, 2, "мутант «ключ остаётся» не пойман самопроверкой: " + out)
        self.assertIn("E-CFG-KEY-FORM", out)
        self.assertEqual(self._run(INSTALL)[0], 0)
        # (3) оба сразу — латка «сверка имён» без check-config и без снятия ключа: план выдан, результат невалиден
        src_text = open(no_check, encoding="utf-8").read().replace(
            "        drop.update(range(i_types, block_end))\n", "        pass\n")
        with open(no_check, "w", encoding="utf-8") as fh:
            fh.write(src_text)
        rc, out = self._run(no_check)
        self.assertEqual(rc, 0, out)
        self.apply(out)
        self.assertEqual(self.check_config()[0], 2, "двойной мутант дал валидный конфиг — измерение «единственное» слепо")

    # -------------------------------------------------------------------------------- R2C-01: проверяется НАПЕЧАТАННЫЙ план
    def put_bytes(self, rel, data):
        p = os.path.join(self.repo, rel)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def apply_independent(self, out):
        """Свой оракул: печатаемый diff -> `git apply --check` и `git apply` на ИСХОДНЫХ байтах, затем check-config."""
        diff = out[out.index("--- a/.workshop/types.yaml"):out.rindex("types-plan: план выше")]
        p = self.put_bytes("plan.diff", diff.encode("utf-8"))
        for extra in (["--check"], []):
            r = subprocess.run(["git", "-C", self.repo, "apply"] + extra + [p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "печатаемый план не применяется: %s" % r.stderr)
        new = open(self.cfg_path(), "rb").read()
        crc, rep = self.check_config()
        self.assertIn("-- errors: 0,", rep)
        self.assertNotIn("W-CFG-KERNEL-SHADOW", rep)
        return new

    def test_r2c01_byte_dimensions_plan_applies(self):
        """Измерения байтов входа (файлы с финальным LF; без него — именованный отказ, test_r7o02_no_final_lf_*):
        хвостовые пробелы; последняя строка — комментарий; снятие последним и рядом с типом; добавление. Каждый
        напечатанный план применяется к исходным байтам, результат валиден, прочие байты сохранены."""
        H = HEAD.encode("utf-8")
        cases = [
            ("снятие последним", H + b"types:\n" + TASK_SHADOW.encode("utf-8"), (), ["TASK"]),
            ("снятие рядом с типом", H + b"types:\n" + (RUNBOOK + TASK_SHADOW).encode("utf-8"), (), ["TASK"]),
            ("добавление", H + b"types:\n" + RUNBOOK.encode("utf-8"), ("--from",), []),
            ("хвостовые пробелы", (HEAD.replace("config_version: 3", "config_version: 3   ") + "types:   \n"
                                   + TASK_SHADOW.replace("ticket", "ticket  ") + RUNBOOK).encode("utf-8"), (), ["TASK"]),
            ("последняя строка — комментарий", H + b"types:\n" + TASK_SHADOW.encode("utf-8") + b"# conec\n", (), ["TASK"]),
            ("добавление после комментария", H + b"types:\n" + RUNBOOK.encode("utf-8") + b"# conec\n", ("--from",), []),
        ]
        for name, data, extra, removed in cases:
            with self.subTest(name):
                self.put_bytes(".workshop/types.yaml", data)
                args = []
                if extra:
                    args = ["--from", self.put("in.yaml", "types:\n" + PLAYBOOK)]
                rc, out = self.plan(*args)
                self.assertEqual(rc, 0, out)
                new = self.apply_independent(out)
                tree = yaml.safe_load(new.decode("utf-8"))
                names = [t["name"] for t in (tree.get("types") or [])]
                for r in removed:
                    self.assertNotIn(r, names, name)
                if extra:
                    self.assertIn("PLAYBOOK", names, name)
                kept = [l for l in data.split(b"\n") if l and not l.startswith(b"config_version:")
                        and not any(l.startswith(x) for x in (b"  - name: TASK", b"    record_class: ticket", b"    definition: \"\xd1\x80\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xb0\"", b"    fields: []"))]
                for l in kept:
                    if l.startswith(b"types:") and not names:
                        continue
                    self.assertIn(l, new, "%s: строка исходника потеряна: %r" % (name, l))
                subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    def test_r2c01_refused_forms(self):
        for name, data, needle in (("CRLF", (HEAD + "types:\n" + TASK_SHADOW).replace("\n", "\r\n").encode("utf-8"), "CR в файле"),
                                   ("BOM", b"\xef\xbb\xbf" + (HEAD + "types:\n" + TASK_SHADOW).encode("utf-8"), "BOM"),
                                   ("пустой файл", b"", "уже до плана не проходит check-config")):
            with self.subTest(name):
                self.put_bytes(".workshop/types.yaml", data)
                rc, out = self.plan()
                self.assertEqual(rc, 2, out)
                self.assertIn(needle, out)
                self.assertNotIn("--- a/", out)
                self.assertNotIn("Traceback", out)

    def test_r2c01_mutants_killed(self):
        """Печать плана расходится с байтами (разрез строк не только по LF — класс R4O-04; вход с U+2028 в комментарии
        снимаемого): (1) вместе с «самопроверка без apply» — план выдан (rc 0) и НЕ применяется (независимый git apply
        отвергает) — тест его убивает; (2) только порча печати — самопроверка с apply ловит: план не выдан, rc 10.
        Прежний мутант «печать без маркера No newline» после R7O-02 эквивалентен: вход без финального LF до печати
        плана не доходит (именованный отказ), и маркер не бывает нужен."""
        src = open(INSTALL, encoding="utf-8").read()
        nomark = [('    out = re.split(r"(?<=\\n)", text)\n    return out[:-1] if out and out[-1] == "" else out\n',
                   '    return text.splitlines(True)\n')]
        noapply = [('        for extra in (["--check"], []):\n', '        for extra in ():\n'),
                   ('        got = _read(path)\n', '        got = new_text.encode("utf-8")\n        open(path, "wb").write(got)\n')]
        for old, _n in nomark + noapply:
            self.assertEqual(src.count(old), 1, "якорь мутанта: %r" % old)
        data = (HEAD + "types:\n" + RUNBOOK + "  # до\u2028после\n" + TASK_SHADOW).encode("utf-8")
        both = self._mutant(nomark[0][0], nomark[0][1])
        t = open(both, encoding="utf-8").read()
        for old, new in noapply:
            t = t.replace(old, new)
        open(both, "w", encoding="utf-8").write(t)
        self.put_bytes(".workshop/types.yaml", data)
        rc, out = self._run(both)
        self.assertEqual(rc, 0, out)
        diff = out[out.index("--- a/.workshop/types.yaml"):out.rindex("types-plan: план выше")]
        p = self.put_bytes("plan.diff", diff.encode("utf-8"))
        r = subprocess.run(["git", "-C", self.repo, "apply", "--check", p], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0, "мутант «без apply» выдал применимый план — измерение слепо")
        only = self._mutant(nomark[0][0], nomark[0][1])
        rc, out = self._run(only)
        self.assertEqual(rc, 10, out)
        self.assertIn("не применяется", out)
        self.assertNotIn("--- a/", out)
        rc, out = self._run(INSTALL)
        self.assertEqual(rc, 0, out)

    # -------------------------------------------------------------------------------- R4O-04: разделители кроме LF
    def test_r4o04_unicode_separators_plan_applies_or_named_refusal(self):
        """U+2028, U+2029, U+0085, VT, FF — не перевод строки для разметки, git apply и источника. Места: комментарий вне
        блока; комментарий в снимаемом блоке; кавычки definition типа заказчика. Исход — применимый план (свой git apply
        + check-config) или именованный отказ rc 2; НИКОГДА rc 10 и трассбек."""
        seps = {"U+2028": " ", "U+2029": " ", "U+0085": "\u0085", "VT": "\x0b", "FF": "\x0c"}
        places = {
            "комментарий вне блока": lambda c: HEAD + "# до" + c + "после\n" + "types:\n" + TASK_SHADOW + RUNBOOK,
            "комментарий в снимаемом блоке": lambda c: HEAD + "types:\n" + TASK_SHADOW + "    # x" + c + "y\n" + RUNBOOK,
            "definition типа заказчика": lambda c: HEAD + "types:\n" + TASK_SHADOW + RUNBOOK.replace("регламент", "регла" + c + "мент"),
        }
        applied = 0
        for sn, c in seps.items():
            for pn, mk in places.items():
                with self.subTest(sep=sn, place=pn):
                    data = mk(c).encode("utf-8")
                    self.put_bytes(".workshop/types.yaml", data)
                    rc, out = self.plan()
                    self.assertNotIn("Traceback", out)
                    self.assertIn(rc, (0, 2), out)
                    if rc == 0:
                        new = self.apply_independent(out)
                        self.assertNotIn(b"name: TASK", new)
                        if pn != "комментарий в снимаемом блоке":
                            self.assertIn(c.encode("utf-8"), new, "символ %s потерян" % sn)
                        applied += 1
                    subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)
        self.assertGreaterEqual(applied, 9, "U+2028/U+2029/U+0085 — законные символы YAML: план обязан применяться")

    # -------------------------------------------------------------------------------- R4O-06: комментарий над следующим
    def test_r4o06_comment_above_next_declaration_stays(self):
        """Решение окна: комментарий непосредственно над следующим объявлением типа заказчика относится к нему и
        остаётся; граница снятия — последняя строка ядрового элемента. Варианты: с отступом, с колонки 0, после пустой
        строки, два подряд."""
        for name, note in (("с отступом", "  # регламент заказчика\n"), ("с колонки 0", "# регламент заказчика\n"),
                           ("после пустой строки", "\n  # регламент заказчика\n"),
                           ("два подряд", "  # регламент заказчика\n  # второй\n")):
            with self.subTest(name):
                self.put(".workshop/types.yaml", HEAD + "types:\n" + TASK_SHADOW + note + RUNBOOK)
                rc, out = self.plan()
                self.assertEqual(rc, 0, out)
                new = self.apply_independent(out).decode("utf-8")
                self.assertIn(note.lstrip("\n") + RUNBOOK, new, "комментарий над следующим объявлением снят")
                self.assertNotIn("name: TASK", new)
                subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)
        # обратный контроль: комментарий ВНУТРИ ядрового элемента уходит вместе с ним
        self.put(".workshop/types.yaml", HEAD + "types:\n" + TASK_SHADOW.replace("    fields: []", "    # внутри\n    fields: []") + RUNBOOK)
        rc, out = self.plan()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("# внутри", self.apply_independent(out).decode("utf-8"))

    # -------------------------------------------------------------------------------- R5C-03: границы — по YAML; значение
    GUIDE = ("  - name: GUIDE\n    record_class: document\n    fields: []\n    definition: |\n"
             "      First line of definition\n      # This is definition data, not a YAML comment")

    def _types_by_name(self, raw):
        tree = yaml.safe_load(raw) or {}
        return dict((t["name"], t) for t in (tree.get("types") or []))

    def test_r5c03_block_scalar_hash_line_is_data(self):
        """Строка блочного скаляра, начинающаяся с `#`, — данные: добавленное объявление (последнее во входе) и
        оставленное объявление заказчика (последнее в конфиге, затем добавление) сохраняют ЗНАЧЕНИЕ — сверка разбором
        PyYAML со входом без каких-либо поправок, не только применимость и валидность."""
        cases = [
            ("добавление: скаляр с # последним во входе",
             HEAD + "types:\n" + TASK_SHADOW + "  # регламент заказчика\n" + RUNBOOK, "types:\n" + self.GUIDE + "\n"),
            ("оставленный заказчика со скаляром # последним, затем добавление",
             HEAD + "types:\n" + TASK_SHADOW + self.GUIDE + "\n", "types:\n" + PLAYBOOK),
        ]
        for name, cfg, inc in cases:
            with self.subTest(name):
                self.put(".workshop/types.yaml", cfg)
                src = self.put("in.yaml", inc)
                rc, out = self.plan("--from", src)
                self.assertEqual(rc, 0, out)
                new = self.apply_independent(out)
                got = self._types_by_name(new.decode("utf-8"))
                want = dict(self._types_by_name(cfg))
                want.pop("TASK", None)
                want.update(self._types_by_name(inc))
                self.assertEqual(got, want, "%s: значения объявлений не сохранены" % name)
                if "регламент" in cfg:
                    self.assertIn("  # регламент заказчика\n  - name: RUNBOOK", new.decode("utf-8"))
                subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    # -------------------------------------------------------------------------------- R5F-02: комментарий над снимаемым
    def test_r5f02_comment_above_removed_goes_with_it(self):
        """Единое правило принадлежности: непрерывные комментарии прямо над `- name:` — этого элемента. Над снимаемым
        ядровым — уходят с ним: позиция {первый, средний, последний} × вид {с отступом, с колонки 0, после пустой строки};
        над оставленным — остаются (обратный контроль)."""
        notes = {"с отступом": "  # затенение ядра — снять\n", "с колонки 0": "# затенение ядра — снять\n",
                 "после пустой строки": "\n  # затенение ядра — снять\n"}
        for pos in ("первый", "средний", "последний"):
            for vn, note in notes.items():
                with self.subTest(pos=pos, note=vn):
                    if pos == "первый":
                        body = note + TASK_SHADOW + "  # регламент заказчика\n" + RUNBOOK
                    elif pos == "средний":
                        body = RUNBOOK + note + TASK_SHADOW + "  # регламент заказчика\n" + PLAYBOOK
                    else:
                        body = "  # регламент заказчика\n" + RUNBOOK + note + TASK_SHADOW
                    self.put(".workshop/types.yaml", HEAD + "types:\n" + body)
                    rc, out = self.plan()
                    self.assertEqual(rc, 0, out)
                    new = self.apply_independent(out).decode("utf-8")
                    self.assertNotIn("затенение ядра", new, "комментарий над снятым ядровым остался сиротой")
                    self.assertIn("  # регламент заказчика\n", new, "комментарий над оставленным снят")
                    self.assertNotIn("name: TASK", new)
                    subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    # -------------------------------------------------------------------------------- R6O-03: инвариант байт без парсера
    def test_r6o03_block_scalar_last_kept_before_removed_keeps_lf(self):
        """Матрица: блочный скаляр `|` / `|-` / `>` у сохраняемого типа заказчика, стоящего последним перед снимаемым
        ядровым (последним в файле) × файл без финального LF / с LF. Без LF — именованный отказ (R7O-02 (а)), плана нет;
        с LF — значение сохраняемого (PyYAML) == значению во входе БЕЗ поправок, байты объявления == отрезку входа."""
        for ind in ("|", "|-", ">"):
            for lf in (False, True):
                with self.subTest(indicator=ind, final_lf=lf):
                    court = ("  - name: COURT\n    record_class: document\n    fields: []\n    definition: %s\n"
                             "      строка один\n      #2 тоже данные\n" % ind)
                    cfg = HEAD + "types:\n" + court + TASK_SHADOW
                    if not lf:
                        cfg = cfg.rstrip("\n")
                    self.put(".workshop/types.yaml", cfg)
                    rc, out = self.plan()
                    if not lf:
                        self.assert_named_refusal(rc, out, NOLF)
                        continue
                    self.assertEqual(rc, 0, out)
                    new = self.apply_independent(out)
                    self.assertEqual(self._types_by_name(new.decode("utf-8"))["COURT"], self._types_by_name(cfg)["COURT"],
                                     "значение сохраняемого блочного скаляра изменилось")
                    self.assertIn(court.encode("utf-8"), new, "байты сохраняемого объявления изменились")
                    subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    def test_r6c03_source_dimension_added_declaration(self):
        """Измерение «источник объявления»: вход (сохраняемое) / --from (добавляемое) × финальный LF есть / нет ×
        `|` / `|-` / `>`. Без LF у затронутого файла — именованный отказ (R7O-02 (а), решение окна: значение не меняется
        НИКОГДА, нормализации LF нет); с LF — значение (PyYAML) == значению во входе без поправок."""
        for ind in ("|", "|-", ">"):
            decl = ("  - name: GUIDE\n    record_class: document\n    fields: []\n    definition: %s\n"
                    "      строка один\n      #2 тоже данные" % ind)
            for source in ("вход", "--from"):
                for lf in (False, True):
                    with self.subTest(indicator=ind, source=source, final_lf=lf):
                        d = decl + ("\n" if lf else "")
                        if source == "вход":
                            cfg, inc = HEAD + "types:\n" + TASK_SHADOW + d, None     # сохраняемое — последним
                        else:
                            cfg, inc = HEAD + "types:\n" + RUNBOOK, "types:\n" + d   # конфиг с LF; LF входа — измерение
                        self.put(".workshop/types.yaml", cfg)
                        args = ["--from", self.put("in.yaml", inc)] if inc else []
                        rc, out = self.plan(*args)
                        if not lf:
                            self.assert_named_refusal(rc, out, NOLF)
                            self.assertIn("in.yaml" if inc else ".workshop/types.yaml", out, "отказ не назвал файл")
                            continue
                        self.assertEqual(rc, 0, out)
                        new = self.apply_independent(out)
                        origin = inc if inc else cfg
                        self.assertEqual(self._types_by_name(new.decode("utf-8"))["GUIDE"], self._types_by_name(origin)["GUIDE"],
                                         "значение объявления изменилось")
                        self.assertIn(d.encode("utf-8"), new, "байты объявления изменились")
                        subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    # -------------------------------------------------------------------------------- R7O-02: значение не меняется никогда
    def assert_named_refusal(self, rc, out, needle):
        self.assertEqual(rc, 2, out)
        self.assertIn(needle, out)
        self.assertNotIn("--- a/", out, "при отказе план напечатан")
        self.assertNotIn("Traceback", out)

    def test_r7o02_no_final_lf_named_refusal(self):
        """(а) Затронутый файл не кончается LF -> отказ rc 2 без плана, сообщение говорит, что сделать. Измерения: снятие
        (последним / рядом с типом / последняя строка — комментарий), добавление (конфиг без LF / вход --from без LF).
        Обратный контроль домена: конфиг без LF, но правки нет — не отказ («без изменений»); --from без LF, но ничего из
        него не добавляется (всё уже есть) — не отказ, в том числе когда конфиг правится снятием."""
        H = HEAD
        cases = [
            ("снятие последним", H + "types:\n" + TASK_SHADOW.rstrip("\n"), None, ".workshop/types.yaml"),
            ("снятие рядом с типом", H + "types:\n" + (RUNBOOK + TASK_SHADOW).rstrip("\n"), None, ".workshop/types.yaml"),
            ("последняя строка — комментарий", H + "types:\n" + TASK_SHADOW + "# conec", None, ".workshop/types.yaml"),
            ("добавление, конфиг без LF", H + "types:\n" + RUNBOOK.rstrip("\n"), "types:\n" + PLAYBOOK, ".workshop/types.yaml"),
            ("добавление, вход без LF", H + "types:\n" + RUNBOOK, "types:\n" + PLAYBOOK.rstrip("\n"), "in.yaml"),
        ]
        for name, cfg, inc, where in cases:
            with self.subTest(name):
                self.put(".workshop/types.yaml", cfg)
                args = ["--from", self.put("in.yaml", inc)] if inc else []
                rc, out = self.plan(*args)
                self.assert_named_refusal(rc, out, NOLF)
                self.assertIn(where, out)
        self.put(".workshop/types.yaml", H + "types:\n" + RUNBOOK.rstrip("\n"))
        rc, out = self.plan()
        self.assertEqual(rc, 0, out)
        self.assertIn("без изменений", out)
        rc, out = self.plan("--from", self.put("in.yaml", "types:\n" + RUNBOOK.rstrip("\n")))
        self.assertEqual(rc, 0, out)
        self.assertIn("уже есть: RUNBOOK", out)
        # --from без LF, из него ничего не добавляется, а конфиг (с LF) правится снятием — --from не затронут, план есть
        self.put(".workshop/types.yaml", H + "types:\n" + TASK_SHADOW + RUNBOOK)
        rc, out = self.plan("--from", self.put("in.yaml", "types:\n" + RUNBOOK.rstrip("\n")))
        self.assertEqual(rc, 0, out)
        self.assertIn("уже есть: RUNBOOK", out)
        self.assertNotIn("name: TASK", self.apply_independent(out).decode("utf-8"))

    @staticmethod
    def _decl(name, cls, definition):
        return "  - name: %s\n    record_class: %s\n    fields: []\n    definition: %s\n" % (name, cls, definition)

    @staticmethod
    def _scalar(ch):
        """Значение блочного скаляра с `#`-строками; у keep (`+`) — с хвостовой пустой строкой, входящей в значение."""
        return ch + "\n      Строка значения.\n      # не комментарий\n      #хвост" + ("\n" if ch.endswith("+") else "")

    def _value_matrix(self):
        """Матрица R7 Opus (tp7: три источника × `|`,`|-`,`>`,`|+`,`>-` × LF / без = 30) + свои строки: chomping `>+`;
        источник B' (B с конфигом С финальным LF — иначе B отказывает на конфиге и --from не проверяется); D — keep у
        сохраняемого в середине перед снимаемым, за которым ещё тип; F — keep не последним ключом элемента (граница правки его не касается); G — keep у
        сохраняемого далеко от правки. -> [(имя, конфиг, вход --from | None, keep на границе?, все файлы с LF?)]."""
        D, sc, out = self._decl, self._scalar, []
        for ch in ("|", "|-", ">", "|+", ">-", ">+"):
            keep = ch.endswith("+")
            for lf in (False, True):
                cut = (lambda t: t) if lf else (lambda t: t.rstrip("\n"))
                tag = "%s %s" % (ch, "LF" if lf else "noLF")
                a = HEAD + "types:\n  # COURT — наш\n" + D("COURT", "ticket", sc(ch)) + "  # TASK — снять\n" + D("TASK", "ticket", '"работа"')
                frm = "types:\n  # PLAY — сценарий\n" + D("PLAY", "document", sc(ch))
                base = HEAD + "types:\n" + D("RUNBOOK", "document", '"регламент"') + "  # DOC — снять\n" + D("DOC", "document", '"док"')
                c = HEAD + "types:\n  # TASK — снять\n" + D("TASK", "ticket", '"работа"') + D("COURT", "ticket", sc(ch))
                out.append(("A " + tag, cut(a), None, keep, lf))
                out.append(("B " + tag, base.rstrip("\n"), cut(frm), keep, False))
                out.append(("B' " + tag, base, cut(frm), keep, lf))
                out.append(("C " + tag, cut(c), cut(frm), keep, lf))
                d = HEAD + "types:\n" + D("COURT", "ticket", sc(ch)) + D("TASK", "ticket", '"работа"') + RUNBOOK
                out.append(("D " + tag, cut(d), None, keep, lf))
                f = (HEAD + "types:\n  - name: COURT\n    record_class: ticket\n    definition: " + sc(ch)
                     + "\n    fields: []\n" + TASK_SHADOW)
                out.append(("F " + tag, cut(f), None, False, lf))
                g = HEAD + "types:\n" + D("COURT", "ticket", sc(ch)) + "\n" + RUNBOOK + TASK_SHADOW
                out.append(("G " + tag, cut(g), None, False, lf))
        return out

    def test_r7o02_value_matrix_zero_corruption(self):
        """Инвариант (решение окна, R7O-02): types-plan НИКОГДА не меняет значение сохраняемого или добавляемого
        объявления. Исход каждого входа — либо именованный отказ rc 2 без плана ((а) нет LF, (б) keep на границе правки),
        либо план, который независимый `git apply` применяет к исходным байтам, check-config чист, и ЗНАЧЕНИЯ (PyYAML) всех
        сохраняемых и добавленных объявлений == значениям во входе БЕЗ поправок, порядок типов и ключи вне types те же.
        Обратный контроль домена отказов: все файлы с LF и keep не на границе — обязан быть план (rc 0)."""
        corrupt, refused, planned = [], 0, 0
        for name, cfg, inc, keep_edge, all_lf in self._value_matrix():
            with self.subTest(name):
                self.put(".workshop/types.yaml", cfg)
                args = ["--from", self.put("in.yaml", inc)] if inc is not None else []
                rc, out = self.plan(*args)
                self.assertNotIn("Traceback", out)
                if rc == 2:
                    refused += 1
                    self.assertNotIn("--- a/", out, "при отказе план напечатан")
                    self.assertTrue(NOLF in out or "chomping keep" in out, "отказ без имени: %s" % out)
                    if NOLF not in out:
                        self.assertRegex(out, r"(\.workshop/types\.yaml|in\.yaml):[0-9]+: блочный скаляр", "отказ (б) не назвал место")
                    self.assertFalse(all_lf and not keep_edge, "%s: отказ вне домена (а)/(б): %s" % (name, out))
                    continue
                self.assertEqual(rc, 0, out)
                planned += 1
                new = self.apply_independent(out).decode("utf-8")
                old_t, new_t = yaml.safe_load(cfg) or {}, yaml.safe_load(new) or {}
                inc_t = (yaml.safe_load(inc) or {}) if inc is not None else {}
                kern = {"TASK", "DOC"}
                want = [t for t in (old_t.get("types") or []) if t["name"] not in kern]
                have = set(t["name"] for t in want)
                want += [t for t in (inc_t.get("types") or []) if t["name"] not in have]
                if new_t.get("types") != (want or None) or \
                        dict((k, v) for k, v in new_t.items() if k not in ("types", "config_version")) != \
                        dict((k, v) for k, v in old_t.items() if k not in ("types", "config_version")):
                    corrupt.append(name)
                subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)
        self.assertEqual(corrupt, [], "значения изменены при rc 0: %s" % corrupt)
        self.assertGreaterEqual(planned, 20, "домен плана выродился")
        self.assertGreaterEqual(refused, 20, "домен отказов выродился")

    # -------------------------------------------------------------------------------- R8O-02: комментарий глубже ключей
    NOTE4 = "    # заметка заказчика\n"

    def test_r8o02_deep_comment_after_last_key_all_variants(self):
        """T24 R8O-02 (D10 T26): комментарий с отступом ≥ 4 (глубже колонки дефиса, на уровне ключей элемента) после
        последнего ключа объявления — часть ЭТОГО объявления, как комментарий между ключами. Все 8 вариантов R8-opus §S2
        (c1–c8): план выдан (rc 0, не TOOL_FAILURE), применяется `git apply` к исходным байтам, check-config чист; значения
        (PyYAML) оставленных == входу, добавленных == --from, снятого нет, config_version +1; комментарий — с тем
        объявлением, глубже которого стоит (оставленное — остаётся байт в байт, снятое — уходит вместе с ним)."""
        N4, N6 = self.NOTE4, "      # заметка заказчика\n"
        RB_MID = RUNBOOK.replace("    fields: []\n", N4 + "    fields: []\n")
        cases = [
            # (вариант, конфиг, --from | None, ожидаемо снятые, фрагмент, обязанный остаться | None, фрагмента нет | None)
            ("c1 отступ 4 после сохраняемого, следующий снимается", "types:\n" + RUNBOOK + N4 + TASK_SHADOW, None,
             {"TASK"}, RUNBOOK + N4, None),
            ("c2 то же, за ним сохраняемый, снимаемый последним", "types:\n" + RUNBOOK + N4 + PLAYBOOK + TASK_SHADOW, None,
             {"TASK"}, RUNBOOK + N4 + PLAYBOOK, None),
            ("c3 отступ 4 после снимаемого, за ним сохраняемый", "types:\n" + TASK_SHADOW + N4 + RUNBOOK, None,
             {"TASK"}, RUNBOOK, N4),
            ("c4 отступ 6", "types:\n" + RUNBOOK + N6 + TASK_SHADOW, None, {"TASK"}, RUNBOOK + N6, None),
            ("c5 отступ 4 между ключами элемента", "types:\n" + RB_MID + TASK_SHADOW, None, {"TASK"}, RB_MID, None),
            ("c6 после сохраняемого последнего, --from добавляет", "types:\n" + TASK_SHADOW + RUNBOOK + N4,
             "types:\n" + PLAYBOOK, {"TASK"}, RUNBOOK + N4 + PLAYBOOK, None),
            ("c7 ничего не снимается, --from добавляет", "types:\n" + RUNBOOK + N4, "types:\n" + PLAYBOOK, set(),
             RUNBOOK + N4 + PLAYBOOK, None),
            ("c8 в --from после добавляемого", "types:\n" + RUNBOOK, "types:\n" + PLAYBOOK + N4, set(),
             RUNBOOK + PLAYBOOK + N4, None),
        ]
        for name, body, inc, gone, kept_frag, absent in cases:
            with self.subTest(name):
                cfg = HEAD + body
                self.put(".workshop/types.yaml", cfg)
                extra = ("--from", self.put("in.yaml", inc)) if inc is not None else ()
                rc, out = self.plan(*extra)
                self.assertEqual(rc, 0, "%s: %s" % (name, out))
                self.assertNotIn("Traceback", out)
                new = self.apply_independent(out).decode("utf-8")
                want = self._types_by_name(cfg)
                for g in gone:
                    want.pop(g)
                if inc is not None:
                    want.update(self._types_by_name(inc))
                self.assertEqual(self._types_by_name(new), want, "%s: значения объявлений не сохранены" % name)
                self.assertEqual(yaml.safe_load(new)["config_version"], yaml.safe_load(cfg)["config_version"] + 1)
                self.assertIn(kept_frag, new, "%s: байты оставленного/добавленного объявления с комментарием изменились" % name)
                if absent is not None:
                    self.assertNotIn(absent, new, "%s: комментарий снятого объявления остался сиротой" % name)
                subprocess.run(["git", "-C", self.repo, "checkout", "--", "."], capture_output=True)

    def test_missing_validator_named_refusal(self):
        self.put(".workshop/types.yaml", HEAD + "types:\n" + RUNBOOK)
        p = subprocess.run([PY, INSTALL, "--repo", self.repo, "types-plan"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("нет бинаря валидатора", p.stdout)

    def test_unsupported_config_forms_refused(self):
        for text, needle in ((HEAD + "types: [{name: RUNBOOK}]\n", "не блочный список"),
                             (HEAD + "types:\n  - record_class: document\n    name: RUNBOOK\n", "без первого ключа name"),
                             (HEAD.replace("\n", "\r\n") + "types: []\r\n", "CR в файле"),
                             # список без отступа — законный YAML, но разметка по строкам его не видит: сверка со строгим
                             # чтением обязана отказать, а не построить план по пустой разметке
                             (HEAD + "types:\n- name: RUNBOOK\n  record_class: document\n  definition: \"р\"\n  fields: []\n",
                              "не совпала со строгим чтением")):
            self.put(".workshop/types.yaml", text)
            rc, out = self.plan()
            self.assertEqual(rc, 2, out)
            self.assertIn(needle, out)


if __name__ == "__main__":
    unittest.main()
