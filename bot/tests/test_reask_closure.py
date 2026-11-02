# -*- coding: utf-8 -*-
"""R1-fix (блокер адверсария B-01): замкнутость реестра фраз переспроса обеспечивает ПРОДУКТ — единый валидатор
целой таблицы `build_help.check_reask` на всех путях выдачи справки и в поллере до первого update. Норма — §1А(б):
«отсутствие фразы для причины — отказ прогона справки».

Инвариант (что доказывается): для ЛЮБОГО реестра, чья таблица reask_reasons (+ reask_reason_fallback) расходится с
множеством причин КОДА по исходу, либо несёт фразу/заглушку не той формы (пустая, не строка, неразрешимая подстановка,
не одна строка, управляющий символ, машинное имя, ответ > 160 на фактических значениях подстановок), —
  * каждый CLI-путь справки (help, short, commands-block, reasons, render) даёт rc 3 и ИМЯ нарушения, без трассировки;
  * каждая проекция в процессе (render_help, render_short, render_commands_block, render_guide, reask_phrase,
    reask_table) и Ctx.full_help поднимают/дают отказ — справки нет;
  * поллер (Q-01, решение alex 2026-09-26) НЕ останавливается: приём, запись, коммит, offset — как обычно; алярм с
    именем нарушения один раз за прогон; переспрос — только проверенными фразами / проверенной заглушкой / встроенным
    резервом, с пометкой в трассе;
  * собственная ошибка сборщика причин кода — ReasonScanError, rc 4 (фатально, не пропуск).
Обратный контроль: исходный реестр и его законная перестановка проходят, справка побайтово та же; граница бюджета
160 принимается, 161 — нет.

Единицы: одна мутация — одна копия реестра (или одна правка исходников в памяти); одна причина — пара (исход, имя).
Ожидания каждой мутации — из самой мутации (что сломано, то и должно быть названо), не из валидатора. Реестр для
построения мутаций читается построчно (не yamlmini). Матрица — ПАКЕТОМ (§5 правила сходимости): потеря, лишнее,
суффиксная и равнодлинная подмена имени — по КАЖДОЙ записи; обнуление, пробелы, подстановка, CR/VT, машинное имя,
бюджет 160/161 и длинная подстановка, дубль ключа, исход потерян/лишний, заглушка; порча кода-производителя.
Независимость: внешний оракул полноты (test_reask_reasons.code_reasons, свой AST-сбор) СВЕРЯЕТСЯ с продуктовым
сборщиком — классификации обязаны совпасть на исходном коде и на каждой мутации кода без ошибки сборщика."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.abspath(os.path.join(HERE, ".."))
KIT = os.path.join(BOT, "kit")
REG = os.path.join(KIT, "commands.yaml")
PHRASES = os.path.join(KIT, "reask-phrases.yaml")   # R3-fix: фразы — отдельный реестр комплекта
FORMS = os.path.join(KIT, "duration-forms.yaml")
GUIDE = os.path.join(KIT, "docs", "bot-user-guide.ru.md")
GEN = os.path.join(KIT, "build_help.py")
PY = sys.executable
SPEC_REPLY_MAX = 160            # контракт §1 №исход-4 (бюджет v8) — из спеки, не из кода
sys.path.insert(0, BOT)
sys.path.insert(0, KIT)
sys.path.insert(0, HERE)
import build_help  # noqa: E402 — предмет проверки
import yamlmini  # noqa: E402 — только чтобы подать мутированный реестр продукту
import test_reask_reasons as oracle  # noqa: E402 — независимый внешний оракул полноты (свой AST-сбор)



def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


TEXT = _read(REG)            # реестр команд: токены, примеры, позиция справки
PHR = _read(PHRASES)         # реестр фраз переспроса: предмет мутаций
FORMS_TEXT = _read(FORMS)


# ------------------------------------------------------------------ построчное чтение реестра (для мутаций)
def reason_rows(text):
    """[(номер строки, исход, имя)] внутри узла reask_reasons — построчно."""
    rows, cur, inside = [], None, False
    for i, ln in enumerate(text.split("\n")):
        if ln.startswith("reask_reasons:"):
            inside = True; continue
        if inside and ln and not ln.startswith(" ") and not ln.startswith("#"):
            break
        m = re.match(r"^  ([a-z0-9_]+):\s*$", ln)
        if inside and m:
            cur = m.group(1); continue
        m = re.match(r"^    ([a-z0-9_]+): \".*\"$", ln)
        if inside and m and cur:
            rows.append((i, cur, m.group(1)))
    assert rows, "мутации: узел reask_reasons не прочитан"
    return rows


def help_hint_len(text):
    toks = []
    cur = {}
    for ln in text.split("\n"):
        if re.match(r"^  - id: ", ln):
            cur = {}
        m = re.match(r'^    (token|grammar): "?([^"]*)"?$', ln)
        if m:
            cur[m.group(1)] = m.group(2)
            if cur.get("grammar", "").endswith("#grammar-help") and "token" in cur:
                toks.append(cur["token"])
    assert len(set(toks)) == 1, toks
    return len(toks[0] + " — команды и примеры")     # указатель справки — форма REQ-095 (контракт)


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def set_fallback(raw):
    """Заменить строку заглушки сырым YAML-скаляром raw (без обработки escape-последовательностей заменой re)."""
    lines = PHR.split("\n")
    k = [n for n, ln in enumerate(lines) if ln.startswith("reask_reason_fallback: ")]
    assert len(k) == 1, "мутации: строка заглушки не единственна"
    lines[k[0]] = "reask_reason_fallback: " + raw
    return "\n".join(lines)


def set_line(text, i, new):
    lines = text.split("\n")
    lines[i] = new
    return "\n".join(lines)


def drop_line(text, i):
    lines = text.split("\n")
    return "\n".join(lines[:i] + lines[i + 1:])


def phrase_line(name, value):
    return "    %s: \"%s\"" % (name, value)


def long_form_text():
    """Реестр форм, где значение формы, на которую ссылается фраза реестра команд, длиннее на 150 символов."""
    ids = re.findall(r"\{form:([a-z0-9_]+)\}", PHR)
    assert ids, "мутации: ни одна фраза не ссылается на форму"
    lines = FORMS_TEXT.split("\n")
    k = lines.index("  - id: %s" % ids[0])
    j = next(n for n in range(k + 1, len(lines)) if lines[n].startswith("    example: \""))
    lines[j] = lines[j][:-1] + "ж" * 150 + "\""
    return "\n".join(lines)


def registry_mutations():
    """[(метка, текст реестра команд, текст реестра форм, ожидаемые имена нарушений | None для контроля)]."""
    rows = reason_rows(PHR)
    lines = PHR.split("\n")
    out = []
    for i, o, name in rows:
        value = re.match(r'^    [a-z0-9_]+: "(.*)"$', lines[i]).group(1)
        out.append(("потеря %s.%s" % (o, name), drop_line(PHR, i), FORMS_TEXT, {"reask.reason_lost"}))
        out.append(("суффикс %s.%s_x" % (o, name), set_line(PHR, i, phrase_line(name + "_x", value)), FORMS_TEXT,
                    {"reask.reason_lost", "reask.reason_extra"}))
        same = name[:-1] + ("x" if name[-1] != "x" else "y")
        out.append(("равная длина %s.%s→%s" % (o, name, same), set_line(PHR, i, phrase_line(same, value)), FORMS_TEXT,
                    {"reask.reason_lost", "reask.reason_extra"}))
        out.append(("обнуление %s.%s" % (o, name), set_line(PHR, i, phrase_line(name, "")), FORMS_TEXT, {"reask.phrase_empty"}))
    i0, o0, n0 = rows[0]
    room = SPEC_REPLY_MAX - len(". ") - help_hint_len(TEXT)
    outcomes = sorted(set(o for _, o, _ in rows))
    for o in outcomes:
        first = next(i for i, oo, _ in rows if oo == o)
        out.append(("лишнее имя в %s" % o, "\n".join(lines[:first] + ['    zz_extra: "лишняя фраза"'] + lines[first:]),
                    FORMS_TEXT, {"reask.reason_extra"}))
        block = [k for k, ln in enumerate(lines) if ln == "  %s:" % o]
        assert len(block) == 1, o
        cut = [k for k, oo, _ in rows if oo == o]
        out.append(("исход %s потерян целиком" % o, "\n".join(l for k, l in enumerate(lines) if k not in cut and k != block[0]),
                    FORMS_TEXT, {"reask.outcome_missing", "reask.reason_lost"}))
    out += [
        ("пробелы вместо фразы", set_line(PHR, i0, phrase_line(n0, "   ")), FORMS_TEXT, {"reask.phrase_empty"}),
        ("неизвестный id подстановки", set_line(PHR, i0, phrase_line(n0, "x {form:zz_missing_form}")), FORMS_TEXT, {"reask.placeholder"}),
        ("неизвестный вид подстановки", set_line(PHR, i0, phrase_line(n0, "x {zz:help}")), FORMS_TEXT, {"reask.placeholder"}),
        ("неразобранная скобка", set_line(PHR, i0, phrase_line(n0, "x {token:help")), FORMS_TEXT, {"reask.placeholder"}),
        ("CR во фразе", set_line(PHR, i0, phrase_line(n0, "раз\\rдва")), FORMS_TEXT, {"reask.not_one_line"}),
        ("LF во фразе", set_line(PHR, i0, phrase_line(n0, "раз\\nдва")), FORMS_TEXT, {"reask.not_one_line"}),
        ("TAB во фразе (управляющий)", set_line(PHR, i0, phrase_line(n0, "раз\\tдва")), FORMS_TEXT, {"reask.not_one_line"}),
        ("VT во фразе", set_line(PHR, i0, phrase_line(n0, "раз\\u000bдва")), FORMS_TEXT, {"reask.not_one_line"}),
        ("LS (U+2028) во фразе", set_line(PHR, i0, phrase_line(n0, "раз\\u2028два")), FORMS_TEXT, {"reask.not_one_line"}),
        ("NEL (U+0085) во фразе", set_line(PHR, i0, phrase_line(n0, "раз\\u0085два")), FORMS_TEXT, {"reask.not_one_line"}),
        ("своё машинное имя во фразе", set_line(PHR, i0, phrase_line(n0, "не понял (%s)" % n0)), FORMS_TEXT, {"reask.machine_name"}),
        ("чужое машинное имя во фразе", set_line(PHR, i0, phrase_line(n0, "не понял: %s" % rows[-1][2])), FORMS_TEXT, {"reask.machine_name"}),
        ("постороннее `слово_слово` во фразе (не имя причины)", set_line(PHR, i0, phrase_line(n0, "см. поле example_dated")), FORMS_TEXT, {"reask.machine_name"}),
        ("бюджет: ответ 161", set_line(PHR, i0, phrase_line(n0, "ф" * (room + 1))), FORMS_TEXT, {"reask.budget"}),
        ("бюджет: длинная подстановка (значение формы +150)", PHR, long_form_text(), {"reask.budget"}),
        ("дубль ключа причины", "\n".join(lines[:i0 + 1] + [lines[i0]] + lines[i0 + 1:]), FORMS_TEXT, {"reask.phrases_yaml"}),
        ("исход вне REASK_PHRASE_OUTCOMES", PHR.replace("\nreask_reasons:\n", "\nreask_reasons:\n  reask_zz:\n    x: \"y\"\n", 1), FORMS_TEXT, {"reask.outcome_extra"}),
        ("нет узла reask_reasons", PHR.replace("\nreask_reasons:\n", "\nreask_reasons_off:\n", 1), FORMS_TEXT, {"reask.node_missing", "reask.reason_lost"}),
        ("заглушка — машинное имя", set_fallback('"%s"' % n0), FORMS_TEXT, {"reask.fallback_machine_name"}),
        ("заглушка пуста", set_fallback('""'), FORMS_TEXT, {"reask.fallback_phrase_empty"}),
        ("заглушка — имя исхода", set_fallback('"reask_invalid"'), FORMS_TEXT, {"reask.fallback_machine_name"}),
        ("заглушки нет", re.sub(r'(?m)^reask_reason_fallback: ".*"\n', "", PHR), FORMS_TEXT, {"reask.fallback_phrase_not_string"}),
        ("заглушка в две строки", set_fallback('"раз\\rдва"'), FORMS_TEXT, {"reask.fallback_not_one_line"}),
        ("заглушка с подстановкой вне реестра", set_fallback('"x {token:zz_none}"'), FORMS_TEXT, {"reask.fallback_placeholder"}),
        ("заглушка длиннее бюджета", set_fallback('"%s"' % ("ф" * (room + 1))), FORMS_TEXT, {"reask.fallback_budget"}),
        # обратные контроли: граница бюджета ровно 160; законная перестановка записей и исходов
        ("контроль: ответ ровно 160", set_line(PHR, i0, phrase_line(n0, "ф" * room)), FORMS_TEXT, None),
        ("контроль: перестановка двух записей", "\n".join(lines[:i0] + [lines[i0 + 1], lines[i0]] + lines[i0 + 2:]), FORMS_TEXT, None),
    ]
    return out


def product_names(ptext, ftext, tmp):
    """Имена нарушений продукта (в процессе) — через ВСЕ проекции; каждая обязана отказать одинаково."""
    pp, fp = os.path.join(tmp, "p.yaml"), os.path.join(tmp, "f.yaml")
    write(pp, ptext)
    write(fp, ftext)
    try:
        doc, forms = yamlmini.load_file(REG), build_help.load_forms(fp)
    except yamlmini.YamlError:
        return {"registry.yaml"}, []
    got = []
    calls = [("check_reask", lambda: build_help.check_reask(doc, forms, phrases_path=pp)),
             ("render_help", lambda: build_help.render_help(doc, forms, phrases_path=pp)),
             ("render_short", lambda: build_help.render_short(doc, forms, phrases_path=pp)),
             ("render_commands_block", lambda: build_help.render_commands_block(doc, forms, phrases_path=pp)),
             ("render_guide", lambda: build_help.render_guide(GUIDE, doc, build_help.load_steps(os.path.join(KIT, "install-steps.yaml")), forms, pp)),
             ("reask_table", lambda: build_help.reask_table(doc, forms, phrases_path=pp)),
             ("reask_phrase", lambda: build_help.reask_phrase(doc, forms, "reask_unparsed", "free_text_without_time", phrases_path=pp))]
    for label, fn in calls:
        try:
            fn()
            got.append((label, None))
        except build_help.RegistryViolation as e:
            got.append((label, frozenset(e.names)))
    return got[0][1] or set(), got


class RegistryClosureMatrix(unittest.TestCase):
    """Матрица реестра ПАКЕТОМ: в процессе — каждая мутация × каждая проекция."""

    def test_every_projection_refuses_every_mutation(self):
        tmp = tempfile.mkdtemp(prefix="reask-closure-")
        rows, fails = [], []
        try:
            _, base = product_names(PHR, FORMS_TEXT, tmp)
            self.assertTrue(all(v is None for _, v in base), "исходный реестр отвергнут: %s" % base)
            want_help = build_help.render_help(yamlmini.load_file(REG), build_help.load_forms(FORMS))
            for label, ctext, ftext, want in registry_mutations():
                self.assertNotEqual((ctext, ftext), (PHR, FORMS_TEXT), "мутация не построена: %s" % label)
                names, per = product_names(ctext, ftext, tmp)
                if want is None:
                    ok = all(v is None for _, v in per)
                    if ok and "перестановка" in label:
                        ok = build_help.render_help(yamlmini.load_file(REG), build_help.load_forms(FORMS), os.path.join(tmp, "p.yaml")) == want_help
                else:
                    ok = set(names) == want and all(v == frozenset(want) for _, v in per)
                rows.append("  %s  %-58s → %s" % ("PASS" if ok else "FAIL", label[:58], sorted(names) if names else "принят"))
                if not ok:
                    fails.append((label, want, per))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sys.stderr.write("\n[R1-fix: реестр × проекции] %d:\n%s\n" % (len(rows), "\n".join(rows)))
        self.assertFalse(fails, fails[:3])


class CliRefusal(unittest.TestCase):
    """Все CLI-пути справки на подготовленных экземплярах адверсария B-01 (построены здесь же из исходного реестра):
    rc 3 и имя нарушения в stderr, без трассировки; контроль — исходный реестр rc 0."""
    SUBS = (["help"], ["short"], ["commands-block"], ["reasons"], ["render", "--guide", GUIDE])

    def run_all(self, cp, fp):
        out = []
        for sub in self.SUBS:
            p = subprocess.run([PY, GEN] + sub + ["--phrases", cp, "--forms", fp], capture_output=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            out.append((sub[0], p.returncode, p.stderr.decode("utf-8", "replace"), p.stdout))
        return out

    def test_adversary_instances_refused_on_every_cli_path(self):
        rows = reason_rows(PHR)
        lines = PHR.split("\n")
        i, o, name = next(r for r in rows if r[2] == "free_text_without_time")
        value = re.match(r'^    [a-z0-9_]+: "(.*)"$', lines[i]).group(1)
        cases = [
            ("reason-loss", drop_line(PHR, i), "reask.reason_lost"),
            ("reason-extra", "\n".join(lines[:i + 1] + ['    zz_extra: "лишняя фраза"'] + lines[i + 1:]), "reask.reason_extra"),
            ("reason-suffix", set_line(PHR, i, phrase_line(name + "_x", value)), "reask.reason_lost"),
            ("reason-name-same-length", set_line(PHR, i, phrase_line(name[:-1] + "x", value)), "reask.reason_lost"),
            ("reason-zero", set_line(PHR, i, phrase_line(name, "")), "reask.phrase_empty"),
            ("reason-template", set_line(PHR, i, phrase_line(name, value.replace("{form:decimal_hours_word}", "{form:missing_form}"))), "reask.placeholder"),
            ("reason-fallback-machine", set_fallback('"unknown_command"'), "reask.fallback_machine_name"),
            ("reason-locale-cr", set_line(PHR, i, phrase_line(name, "такой команды у бота нет\\rснова")), "reask.not_one_line"),
        ]
        tmp = tempfile.mkdtemp(prefix="reask-cli-")
        report, bad = [], []
        try:
            fp = os.path.join(tmp, "f.yaml")
            write(fp, FORMS_TEXT)
            base = os.path.join(tmp, "base.yaml")
            write(base, PHR)
            for sub, rc, err, out in self.run_all(base, fp):
                self.assertEqual(rc, 0, "контроль: исходный реестр, %s: %s" % (sub, err))
            for label, ctext, want in cases:
                self.assertNotEqual(ctext, PHR, "мутация не построена: %s" % label)
                cp = os.path.join(tmp, "c.yaml")
                write(cp, ctext)
                res = self.run_all(cp, fp)
                ok = all(rc == build_help.RC_REGISTRY_VIOLATION and "[%s]" % want in err and "Traceback" not in err and not out
                         for _, rc, err, out in res)
                report.append("  %s  %-26s rc=%s" % ("PASS" if ok else "FAIL", label, [r[1] for r in res]))
                if not ok:
                    bad.append((label, [(s, rc, err[-300:]) for s, rc, err, _ in res]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sys.stderr.write("\n[R1-fix: CLI help/short/commands-block/reasons/render] %d:\n%s\n" % (len(report), "\n".join(report)))
        self.assertFalse(bad, bad[:2])


class LegalRefactorPlusLoss(unittest.TestCase):
    """R2 (экземпляр адверсария legal-local-and-lost-phrase): законный рефакторинг возвратов duration_ambiguous через
    локальную переменную + потеря её фразы в реестре → отказ на ВСЕХ 5 CLI (rc 3, reask.reason_lost), а в поллере —
    отказ справки и нарушение с тем же именем (Q-01: приём не останавливается), переспрос этой причины — заглушкой с
    пометкой. Обратные контроли: только рефакторинг — rc 0 на всех 5; скрытый производитель через список — rc 3;
    форма, не разрешённая сборщиком, — rc 4."""
    SUBS = (["help"], ["short"], ["commands-block"], ["reasons"], ["render", "--guide", "bot/kit/docs/bot-user-guide.ru.md"])
    PROBE = r"""
import json, sys
sys.path[:0] = ["bot", "bot/kit"]
import poll, build_help
ctx = poll.Ctx(".", None, {}, "/unused")
v = ctx.reask_violation
out = poll.reply_text(ctx, "reask_unparsed", {"reply": {"reason": "duration_ambiguous"}}, {})
print(json.dumps({"violation": v.names if v else None, "help_refused": ctx.full_help() == poll.HELP_REFUSED_TEXT,
                  "reply": out, "trace": [o["note"] for o in ctx.trace.ops if o["op"] == "reask_reason"]}, ensure_ascii=False))
"""

    def tree(self, tmp, parse_fn=None, registry=PHR):
        dst = os.path.join(tmp, "bot")
        shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        write(os.path.join(dst, "kit", "reask-phrases.yaml"), registry)
        if parse_fn:
            p = os.path.join(dst, "parse.py")
            src = _read(p)
            out = parse_fn(src)
            self.assertNotEqual(out, src, "мутация кода не построена")
            write(p, out)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        cli = [subprocess.run([PY, "bot/kit/build_help.py"] + sub, cwd=tmp, capture_output=True, env=env) for sub in self.SUBS]
        return cli, subprocess.run([PY, "-c", self.PROBE], cwd=tmp, capture_output=True, env=env)

    def test_refactor_plus_loss_refused_everywhere(self):
        amb = 'return None, s, "duration_ambiguous"'
        local = lambda src: re.sub(r"(?m)^([ \t]*)" + re.escape(amb) + "$", lambda m: m.group(1) + 'zz_r = (None, s, "duration_ambiguous")\n' + m.group(1) + "return zz_r", src)
        hidden = lambda src: src.replace('        if "leading" in self.positions:\n', '        if s == "zz-list":\n            return [None, s, "zz_list_reason"]\n        if "leading" in self.positions:\n', 1)
        bad_form = lambda src: src.replace('        if "leading" in self.positions:\n', '        if s == "zz":\n            return None\n        if "leading" in self.positions:\n', 1)
        i = next(k for k, _, n in reason_rows(PHR) if n == "duration_ambiguous")
        cases = [("рефакторинг + потеря фразы", local, drop_line(PHR, i), 3, "reask.reason_lost"),
                 ("контроль: только рефакторинг", local, PHR, 0, None),
                 ("скрытый производитель списком", hidden, PHR, 3, "reask.reason_lost"),
                 ("форма вне сборщика: return None", bad_form, PHR, 4, "reask.scan_error")]
        rows = []
        for label, fn, reg, want_rc, want in cases:
            tmp = tempfile.mkdtemp(prefix="reask-r2-")
            try:
                cli, probe = self.tree(tmp, fn, reg)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            rcs = [p.returncode for p in cli]
            errs = [p.stderr.decode("utf-8", "replace") for p in cli]
            ok = rcs == [want_rc] * 5 and all("Traceback" not in e for e in errs) and \
                (want is None or all("[%s]" % want in e and not p.stdout for e, p in zip(errs, cli)))
            self.assertEqual(probe.returncode, 0, (label, probe.stderr.decode("utf-8", "replace")[-500:]))
            import json
            rt = json.loads(probe.stdout.decode("utf-8"))
            if want is None:
                ok = ok and rt["violation"] is None and not rt["help_refused"]
            else:
                ok = ok and want in rt["violation"] and rt["help_refused"]
            if label.startswith("рефакторинг"):
                ok = ok and "duration_ambiguous" not in rt["reply"] and rt["trace"] and "заглушка" in rt["trace"][-1]
            rows.append("  %s  %-34s CLI rc=%s runtime=%s" % ("PASS" if ok else "FAIL", label, rcs, rt["violation"]))
            self.assertTrue(ok, (label, rcs, errs[0][-400:], rt))
        sys.stderr.write("\n[R2-fix: рефакторинг + потеря × CLI ×5 + поллер] %d:\n%s\n" % (len(rows), "\n".join(rows)))


def dated_free_text():
    """Пример формы «дата + длительность» (expected_date) — построчно из реестра форм."""
    cur = None
    for ln in FORMS_TEXT.split("\n"):
        m = re.match(r'^    example: "(.*)"$', ln)
        if m:
            cur = m.group(1)
        if re.match(r'^    expected_date: "\d{4}-\d{2}-\d{2}"$', ln) and cur:
            return cur
    raise AssertionError("в реестре форм нет формы с датой")


def dated_track():
    m = re.search(r'(?m)^    example_dated: "(.*)"$', TEXT)
    assert m, "в реестре команд нет example_dated"
    return m.group(1)


class StandDeadline(BaseException):
    """Прерывание зависшего стенда. BaseException — чтобы его не поглотили продуктовые `except Exception` (контур
    main, последний рубеж degraded_reask): зависание обязано стать FAIL/ERROR теста, а не «успешной» деградацией."""


class PollerIsolation(unittest.TestCase):
    """Q-01 (решение alex 2026-09-26): приём часов ИЗОЛИРОВАН от реестра фраз. Порченый реестр × {свободный текст с
    датой, команда интервала с датой, отзыв} → записи сделаны, коммит есть, offset сдвинут, push прошёл, main() rc 0; алярм ровно
    один за прогон и с именем нарушения; команда справки — отказ справки; неразобранное — проверенная фраза, если она цела, иначе
    проверенная заглушка, при порченой заглушке — встроенный резерв; исходный реестр — прежнее поведение, алярмов нет."""
    T = 1789812000

    def run_main(self, phrases_text, commands_text=None):
        """phrases_text: str/bytes — байты реестра фраз; None — файла нет; "<dir>" — на его месте каталог.
        commands_text — подмена реестра команд (грамматика; порча — не предмет Q-01)."""
        sys.path.insert(0, HERE)
        import botrepo, poll, contextlib, io  # noqa: E402
        stand = botrepo.Stand()
        tmp = tempfile.mkdtemp(prefix="reask-q01-")
        here, transport = poll._HERE, poll.tg.Transport
        try:
            shutil.copytree(BOT, os.path.join(tmp, "bot"), ignore=shutil.ignore_patterns("tests", "__pycache__"))
            pp = os.path.join(tmp, "bot", "kit", "reask-phrases.yaml")
            cleanup = None
            if callable(phrases_text):
                cleanup = phrases_text(pp, tmp)          # особый источник (FIFO, устройство, ссылка) — R4-fix
            elif phrases_text is None:
                os.remove(pp)
            elif phrases_text == "<dir>":
                os.remove(pp); os.mkdir(pp)
            elif isinstance(phrases_text, bytes):
                with open(pp, "wb") as fh:
                    fh.write(phrases_text)
            else:
                write(pp, phrases_text)
            if commands_text is not None:
                write(os.path.join(tmp, "bot", "kit", "commands.yaml"), commands_text)
            tok = botrepo.TOK
            P = dict(chat_type="private", chat_id=botrepo.ADMIN_ID)
            ups = [botrepo.msg(dated_free_text(), date=self.T, **P),
                   botrepo.msg(dated_track(), date=self.T + 1, **P),
                   botrepo.msg(tok["undo"], date=self.T + 2, **P),
                   botrepo.msg(tok["help"], date=self.T + 3, **P),
                   botrepo.msg("просто текст без часов", date=self.T + 4, **P),
                   botrepo.msg(tok["last"] + " 0", date=self.T + 5, **P)]
            tr = botrepo.FakeTransport(ups)
            before = int(stand.commits())
            poll._HERE = os.path.join(tmp, "bot")
            poll.tg.Transport = lambda *a, **k: tr
            old, cap = os.getcwd(), io.StringIO()
            os.chdir(stand.root)
            import signal  # noqa: E402

            def _hung(*a):
                raise StandDeadline("поллер ждёт ввода-вывода дольше 60 с — приём заблокирован")
            prev = signal.signal(signal.SIGALRM, _hung)
            signal.setitimer(signal.ITIMER_REAL, 60, 5)      # повтор каждые 5 с: повторное ожидание тоже прерывается
            try:
                with contextlib.redirect_stdout(cap):
                    rc = poll.main()
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, prev)
                os.chdir(old)
                if cleanup:
                    cleanup()
            sp = os.path.join(stand.root, ".workshop", "bot-state.yaml")
            state = yamlmini.load_file(sp) if os.path.exists(sp) else {"offset": 0}   # фатальный прогон состояния не пишет
            time_text = "".join(_read(os.path.join(stand.root, "time", f)) for f in sorted(os.listdir(os.path.join(stand.root, "time")))) \
                if os.path.isdir(os.path.join(stand.root, "time")) else ""
            return {"rc": rc, "stdout": cap.getvalue(), "sent": [t for _, t, _ in tr.sent], "calls": tr.calls,
                    "commits": int(stand.commits()) - before, "offset": state["offset"], "last": ups[-1]["update_id"],
                    "pushed": stand.origin_head() == stand.head(), "time": time_text}
        finally:
            poll._HERE, poll.tg.Transport = here, transport
            stand.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def check_intake(self, r, label):
        self.assertEqual(r["rc"], 0, (label, r["stdout"][-600:]))
        self.assertIn("getUpdates", r["calls"], label)
        self.assertEqual(r["offset"], r["last"] + 1, label)
        self.assertTrue(r["pushed"], label)
        self.assertGreaterEqual(r["commits"], 3, label)                   # две записи + отзыв (+ состояние)
        for want in ("recorded", "retracted", "help_given", "reask_unparsed"):
            self.assertIn(want, r["stdout"], (label, want))
        title = dated_track().split(" ", 3)[3]
        self.assertIn(title, r["time"], label)

    def test_damaged_registry_does_not_stop_intake(self):
        rows = reason_rows(PHR)
        lines = PHR.split("\n")
        i = next(k for k, _, n in rows if n == "free_text_without_time")
        loss = drop_line(PHR, i)
        cases = [
            ("потеря фразы свободного текста", loss, "reask.reason_lost", False),
            ("потеря фразы + порченая заглушка", "\n".join(l if not l.startswith("reask_reason_fallback: ") else
                                                           'reask_reason_fallback: "x {token:zz_none}"' for l in loss.split("\n")),
             "reask.fallback_placeholder", True),
        ]
        fallback = re.search(r'(?m)^reask_reason_fallback: "(.*)"$', PHR).group(1)
        n0 = re.search(r'(?m)^    n_not_positive_integer: "(.*)"$', PHR).group(1)
        for label, text, name, builtin in cases:
            r = self.run_main(text)
            self.check_intake(r, label)
            alarms = [t for t in r["sent"] if t.startswith("⚠ сторож бота:")]
            self.assertEqual(len(alarms), 1, (label, alarms))
            self.assertIn(name, alarms[0], label)
            self.assertIn("справка отказывает", alarms[0], label)
            import poll  # noqa: E402
            self.assertIn(poll.HELP_REFUSED_TEXT, r["sent"], label)
            self.assertIn("help_refused", r["stdout"], label)
            reserve = build_help.SAFE_REASK_FALLBACK if builtin else fallback
            self.assertTrue(any(t.startswith(reserve + ".") and len(t) <= SPEC_REPLY_MAX for t in r["sent"]), (label, r["sent"]))
            self.assertTrue(any(t.startswith(n0.split("{")[0]) for t in r["sent"]), "цела — фраза реестра: %s" % label)
            self.assertIn("заглушка", r["stdout"], label)
            if builtin:
                self.assertIn("встроенный резерв", r["stdout"], label)

    def test_intact_registry_unchanged_behaviour(self):
        r = self.run_main(PHR)
        self.check_intake(r, "исходный реестр")
        self.assertFalse([t for t in r["sent"] if t.startswith("⚠ сторож бота:")], "алярм без нарушения")
        import poll  # noqa: E402
        self.assertNotIn(poll.HELP_REFUSED_TEXT, r["sent"])
        # [Перенос D19 M2 на kernel-v2, 2026-10-13: справка — по макету help_page; признак выданной справки — её текст
        # целиком (render_help), а не строка «позиций в реестре» прежнего перечня.]
        want_help = build_help.render_help(yamlmini.load_file(REG), build_help.load_forms(FORMS), strict=True)   # strict: эталон — макет, не фолбэк
        self.assertIn(build_help.help_token(yamlmini.load_file(REG)), want_help)
        self.assertIn(want_help, r["sent"])
        self.assertNotIn("reask_registry", r["stdout"])

    def test_builtin_reserve_passes_the_same_form_check(self):
        doc, forms = yamlmini.load_file(REG), build_help.load_forms(FORMS)
        phrase, bad = build_help._phrase_violations(doc, forms, "SAFE", build_help.SAFE_REASK_FALLBACK,
                                                    build_help.help_hint(doc), set(REASK_NAMES()))
        self.assertEqual(bad, [])
        self.assertEqual(phrase, build_help.SAFE_REASK_FALLBACK)


class PhrasesSyntaxIsolation(unittest.TestCase):
    """R3-fix, Q-01-01 (блокер адверсария R3): СИНТАКСИЧЕСКАЯ порча реестра фраз (дубль ключа, неизвестный escape,
    незакрытая кавычка, отступ/табуляция, не UTF-8, файла нет/каталог, пустой/без registry) — не останавливает приём:
    фразы — отдельный файл kit/reask-phrases.yaml со своей загрузкой, реестр команд и парсер его байтов не видят.
    Каждая порча: записи/отзыв сделаны, коммиты, offset, push, rc 0, алярм ровно один с именем нарушения, справка
    отказана, неразобранное — проверенная фраза недоступна → встроенный резерв. Минимум два экземпляра на измерение;
    четыре экземпляра адверсария R3 (дубль free_text_without_time и track_without_interval, «bad \q», незакрытая
    кавычка у заглушки) — среди них. Обратный контроль: порча ГРАММАТИКИ (позиции команд) по-прежнему фатальна."""

    T = PollerIsolation.T
    run_main = PollerIsolation.run_main          # тот же стенд, без повторного прогона тестов PollerIsolation
    check_intake = PollerIsolation.check_intake

    def cases(self):
        L = PHR.split("\n")
        idx = lambda key: next(k for k, l in enumerate(L) if l.startswith("    %s:" % key) or l.startswith("%s:" % key))
        dup = lambda key: "\n".join(L[:idx(key) + 1] + [L[idx(key)]] + L[idx(key) + 1:])
        setl = lambda key, new: "\n".join(L[:idx(key)] + [new] + L[idx(key) + 1:])
        fb = lambda raw: setl("reask_reason_fallback", "reask_reason_fallback: " + raw)
        ph = lambda key, raw: setl(key, "    %s: %s" % (key, raw))
        Y, M, E, R = "reask.phrases_yaml", "reask.phrases_missing", "reask.phrases_empty", "reask.phrases_registry"
        return [
            ("дубль ключа: free_text_without_time (R3)", dup("free_text_without_time"), Y),
            ("дубль ключа: track_without_interval (R3)", dup("track_without_interval"), Y),
            ("дубль ключа: заглушка", dup("reask_reason_fallback"), Y),
            ("escape: «bad \\q» у заглушки (R3)", fb('"bad \\q"'), Y),
            ("escape: \\x во фразе", ph("no_line", '"нечего \\x41 отзывать"'), Y),
            ("escape: неполный \\u во фразе", ph("title_empty", '"нужен \\u12 заголовок"'), Y),
            ("кавычка: незакрытая у заглушки (R3)", fb('"unclosed'), Y),
            ("кавычка: незакрытая у фразы", ph("unknown_command", '"такой команды у бота нет'), Y),
            ("отступ: табуляция перед фразой", setl("not_utf8", "\t" + L[idx("not_utf8")].lstrip()), Y),
            ("отступ: три пробела перед фразой", setl("title_empty", "   " + L[idx("title_empty")].lstrip()), Y),
            ("кодировка: байты не UTF-8", PHR.encode("utf-8") + b"\xff\xfe\n", Y),
            ("файла нет", None, M),
            ("на месте файла каталог", "<dir>", "reask.phrases_not_regular"),
            ("файл пуст (0 байт)", "", E),
            ("файл из пробелов и переводов строк", "  \n\n \n", E),
            ("только комментарий, без registry", "# фразы\n", R),
        ]

    def test_syntax_damage_does_not_stop_intake(self):
        import poll  # noqa: E402
        rows, bad = [], []
        for label, text, name in self.cases():
            self.assertNotEqual(text, PHR, "мутация не построена: %s" % label)
            r = self.run_main(text)
            try:
                self.check_intake(r, label)
                alarms = [t for t in r["sent"] if t.startswith("⚠ сторож бота:")]
                self.assertEqual(len(alarms), 1, (label, alarms))
                self.assertIn(name, alarms[0], label)
                self.assertIn(poll.HELP_REFUSED_TEXT, r["sent"], label)
                self.assertTrue(any(t.startswith(build_help.SAFE_REASK_FALLBACK + ".") for t in r["sent"]), label)
                self.assertIn("встроенный резерв", r["stdout"], label)
                self.assertNotIn("TOOL_FAILURE", r["stdout"], label)
                ok = True
            except AssertionError as e:
                ok = False
                bad.append((label, str(e)[:300]))
            rows.append("  %s  %-44s → rc=%s коммитов=%s offset=%s алярм=%s" % (
                "PASS" if ok else "FAIL", label, r["rc"], r["commits"], r["offset"] - r["last"], name))
        sys.stderr.write("\n[R3-fix: синтаксис реестра фраз × приём] %d:\n%s\n" % (len(rows), "\n".join(rows)))
        self.assertFalse(bad, bad)

    def test_grammar_damage_is_still_fatal(self):
        """Не предмет Q-01: порча реестра КОМАНД (позиции, грамматика) — фатальна, как была: rc 10, getUpdates не зовётся."""
        broken = [("дубль id позиции", TEXT.replace("\ncommands:\n", "\ncommands:\n  - id: zz\n  - id: zz\n", 1)),
                  ("незакрытая кавычка в позиции", re.sub(r'(?m)^(    example: )"(.*)"$', lambda m: m.group(1) + '"' + m.group(2), TEXT, count=1))]
        for label, text in broken:
            self.assertNotEqual(text, TEXT, label)
            r = self.run_main(PHR, commands_text=text)
            self.assertEqual(r["rc"], 10, (label, r["stdout"][-300:]))
            self.assertNotIn("getUpdates", r["calls"], label)
            self.assertIn("TOOL_FAILURE", r["stdout"], label)


class PhrasesIoBoundary(unittest.TestCase):
    """R4-fix, B-R4-01: загрузка фраз НЕ ЖДЁТ ввода-вывода. Источник, на котором обычные open/read блокируются (FIFO без
    писателя — ожидание в open; FIFO с открытым писателем без данных — ожидание в read), и источник без конца
    (символьное устройство), в т.ч. как ЦЕЛЬ символьной ссылки, отвергаются по fstat открытого дескриптора без
    единого read: приём, запись, коммит, push, offset — обычные, алярм reask.phrases_not_regular ровно один, справка
    отказана. Обычный файл больше предела — reask.phrases_too_large. Обратные контроли: обычный файл, относительная и
    абсолютная ссылка на обычный файл — прежнее поведение, без алярма. Стенд прерывает зависание через 60 с — это
    FAIL теста, а не rc продукта."""
    T = PollerIsolation.T
    run_main = PollerIsolation.run_main
    check_intake = PollerIsolation.check_intake

    @staticmethod
    def fifo_link(writer):
        def setup(pp, tmp):
            fifo = os.path.join(tmp, "synthetic-pipe")
            os.mkfifo(fifo)
            os.remove(pp)
            os.symlink(fifo, pp)
            fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK) if writer else None   # писатель есть, данных и EOF нет
            return (lambda: os.close(fd)) if fd is not None else None
        return setup

    @staticmethod
    def fifo_in_place(pp, tmp):
        os.remove(pp)
        os.mkfifo(pp)

    @staticmethod
    def dev_zero_link(pp, tmp):
        os.remove(pp)
        os.symlink("/dev/zero", pp)

    @staticmethod
    def too_large(pp, tmp):
        pad = "# " + "ж" * 60 + "\n"
        with open(pp, "w", encoding="utf-8") as fh:
            fh.write(PHR + pad * (build_help.PHRASES_MAX_BYTES // len(pad.encode("utf-8")) + 10))

    @staticmethod
    def link_to_regular(relative):
        def setup(pp, tmp):
            real = os.path.join(tmp, "phrases-real.yaml")
            write(real, PHR)
            os.remove(pp)
            os.symlink(os.path.relpath(real, os.path.dirname(pp)) if relative else real, pp)
        return setup

    def test_blocking_sources_do_not_stop_intake(self):
        import poll  # noqa: E402
        NR = "reask.phrases_not_regular"
        cases = [("ссылка → FIFO без писателя (ожидание в open, R4)", self.fifo_link(False), NR),
                 ("ссылка → FIFO с писателем без данных (ожидание в read, R4)", self.fifo_link(True), NR),
                 ("FIFO на месте файла", self.fifo_in_place, NR),
                 ("ссылка → /dev/zero (чтение без конца)", self.dev_zero_link, NR),
                 ("обычный файл больше предела", self.too_large, "reask.phrases_too_large")]
        rows = []
        for label, setup, name in cases:
            r = self.run_main(setup)
            self.check_intake(r, label)
            alarms = [t for t in r["sent"] if t.startswith("⚠ сторож бота:")]
            self.assertEqual(len(alarms), 1, (label, alarms))
            self.assertIn(name, alarms[0], label)
            self.assertIn(poll.HELP_REFUSED_TEXT, r["sent"], label)
            self.assertLess(r["calls"].index("getMe") if "getMe" in r["calls"] else -1, r["calls"].index("getUpdates"), label)
            rows.append("  PASS  %-58s → rc=%s offset=+1 алярм=%s" % (label, r["rc"], name))
        sys.stderr.write("\n[R4-fix: источник реестра фраз × приём] %d:\n%s\n" % (len(rows), "\n".join(rows)))

    def test_links_to_regular_file_behave_as_before(self):
        import poll  # noqa: E402
        for label, setup in (("относительная ссылка на обычный файл", self.link_to_regular(True)),
                             ("абсолютная ссылка на обычный файл", self.link_to_regular(False))):
            r = self.run_main(setup)
            self.check_intake(r, label)
            self.assertFalse([t for t in r["sent"] if t.startswith("⚠ сторож бота:")], label)
            self.assertNotIn(poll.HELP_REFUSED_TEXT, r["sent"], label)
            self.assertIn(build_help.render_help(yamlmini.load_file(REG), build_help.load_forms(FORMS), strict=True), r["sent"], label)   # D19 M2: справка по макету (strict — эталон не фолбэк)

    def test_loader_returns_at_once_on_blocking_sources(self):
        """Прямо на загрузчике: FIFO без писателя и с писателем, /dev/zero, каталог — нарушение сразу, без чтения."""
        import signal, time  # noqa: E401,E402
        tmp = tempfile.mkdtemp(prefix="reask-io-")
        self.addCleanup(shutil.rmtree, tmp, True)
        fifo = os.path.join(tmp, "p")
        os.mkfifo(fifo)
        link = os.path.join(tmp, "l")
        os.symlink(fifo, link)
        zero = os.path.join(tmp, "z")
        os.symlink("/dev/zero", zero)
        def _hung(*a):
            raise StandDeadline("загрузчик ждёт ввода-вывода")
        prev = signal.signal(signal.SIGALRM, _hung)
        signal.setitimer(signal.ITIMER_REAL, 10, 2)
        try:
            for path in (fifo, link, zero, tmp):
                t = time.monotonic()
                doc, bad = build_help.load_phrases(path)
                self.assertEqual((doc, [b[0] for b in bad]), ({}, ["reask.phrases_not_regular"]), path)
                self.assertLess(time.monotonic() - t, 1.0, path)
            fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            try:
                self.assertEqual([b[0] for b in build_help.load_phrases(link)[1]], ["reask.phrases_not_regular"])
            finally:
                os.close(fd)
            self.assertEqual(build_help.load_phrases(PHRASES)[1], [])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, prev)


class PhrasesSizeBound(unittest.TestCase):
    """R4-fix: предел реестра фраз держится ДВАЖДЫ — по заявленному размеру (без единого read) и по фактически
    прочитанным байтам (файл растёт между fstat и read). Каждая граница проверяется отдельно."""

    def big(self):
        tmp = tempfile.mkdtemp(prefix="reask-size-")
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "p.yaml")
        with open(p, "wb") as fh:
            fh.write(PHR.encode("utf-8") + b"#" * (build_help.PHRASES_MAX_BYTES + 1))
        return p

    def test_declared_size_refused_without_reading(self):
        p, reads = self.big(), []
        real = os.read

        def counting(fd, n):
            reads.append(n)
            return real(fd, n)
        build_help.os.read = counting
        try:
            doc, bad = build_help.load_phrases(p)
        finally:
            build_help.os.read = real
        self.assertEqual([b[0] for b in bad], ["reask.phrases_too_large"])
        self.assertEqual(reads, [], "больше предела по fstat — ни одного read")

    def test_actual_bytes_bounded_when_file_grows(self):
        p = self.big()
        real = os.fstat

        class Small(object):
            def __init__(self, st):
                self.st_mode, self.st_size = st.st_mode, 10      # «в момент fstat файл был маленьким»
        build_help.os.fstat = lambda fd: Small(real(fd))
        try:
            doc, bad = build_help.load_phrases(p)
        finally:
            build_help.os.fstat = real
        self.assertEqual([b[0] for b in bad], ["reask.phrases_too_large"])

    def test_limit_boundary(self):
        tmp = tempfile.mkdtemp(prefix="reask-size-")
        self.addCleanup(shutil.rmtree, tmp, True)
        base = PHR.encode("utf-8")
        for extra, want in ((build_help.PHRASES_MAX_BYTES - len(base), []), (build_help.PHRASES_MAX_BYTES - len(base) + 1, ["reask.phrases_too_large"])):
            p = os.path.join(tmp, "p%d.yaml" % extra)
            with open(p, "wb") as fh:
                fh.write(base + b"#" * extra)
            self.assertEqual(os.path.getsize(p) - build_help.PHRASES_MAX_BYTES, 0 if not want else 1)
            self.assertEqual([b[0] for b in build_help.load_phrases(p)[1]], want, extra)


class RuntimeReasonAlarm(unittest.TestCase):
    """R3-fix, страховка рантайма: причина от разбора/отзыва, которой нет в ПРОВЕРЕННОЙ таблице фраз, — заглушка
    человеку, пометка в трассе И алярм администратору с именем причины, один раз за прогон на причину. Если отсутствие
    фразы уже названо алярмом реестра этого прогона (нарушение по этой причине или по всей таблице) — второго нет;
    нарушение по ДРУГОЙ причине алярм по этой не гасит."""

    def ctx(self):
        sys.path.insert(0, HERE)
        import botrepo, poll  # noqa: E402
        self.stand = botrepo.Stand()
        self.addCleanup(self.stand.close)
        cfg = yamlmini.load_file(os.path.join(self.stand.root, ".workshop", "bot.yaml"))
        tr = botrepo.FakeTransport([])
        return poll, poll.Ctx(self.stand.root, tr, cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None), tr

    def alarms(self, tr):
        return [t for _, t, _ in tr.sent if t.startswith("⚠ сторож бота:")]

    def test_unknown_reason_alarms_once_per_reason(self):
        poll, ctx, tr = self.ctx()
        fb = re.search(r'(?m)^reask_reason_fallback: "(.*)"$', PHR).group(1)
        for reason in ("zz_unmapped_one", "zz_unmapped_one", "zz_unmapped_one:хвост", "zz_unmapped_two", "free_text_without_time"):
            text = poll.reply_text(ctx, "reask_unparsed", {"reply": {"reason": reason}}, {})
            if reason.startswith("zz_"):
                self.assertTrue(text.startswith(fb + "."), text)
                self.assertNotIn("zz_", text)
        al = self.alarms(tr)
        self.assertEqual(len(al), 2, al)
        self.assertIn("zz_unmapped_one", al[0]); self.assertIn("zz_unmapped_two", al[1])
        self.assertNotIn("хвост", "".join(al))                     # хвост причины — текст человека, в алярм не идёт
        poll.reply_text(ctx, "reask_undo_not_found", {"reply": {"reason": "zz_unmapped_one"}}, {})
        self.assertEqual(len(self.alarms(tr)), 3, "другой исход — другой ключ алярма")

    def test_outcome_level_violation_explains_only_its_outcome(self):
        """R4-fix, M-R4-01: нарушение ИСХОДА гасит алярмы только причин этого исхода. Два реальных реестра адверсария:
        таблица reask_undo_not_found удалена; она же заменена []. Неизвестные причины разбора — алярм каждой; причина
        отзыва — нет (объяснена нарушением исхода). Обратный контроль: нарушение таблицы reask_unparsed — наоборот."""
        poll, ctx, tr = self.ctx()
        doc, forms = yamlmini.load_file(REG), build_help.load_forms(FORMS)
        L = PHR.split("\n")
        k = L.index("  reask_undo_not_found:")
        end = next(i for i in range(k + 1, len(L)) if not L[i].startswith("    "))
        u = L.index("  reask_unparsed:")
        uend = next(i for i in range(u + 1, len(L)) if not L[i].startswith("    "))
        regs = [("таблица отзыва удалена", "\n".join(L[:k] + L[end:]), "reask_undo_not_found"),
                ("таблица отзыва — []", "\n".join(L[:k] + ["  reask_undo_not_found: []"] + L[end:]), "reask_undo_not_found"),
                ("таблица разбора — [] (обратный контроль)", "\n".join(L[:u] + ["  reask_unparsed: []"] + L[uend:]), "reask_unparsed")]
        tmp = tempfile.mkdtemp(prefix="reask-m4-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for label, text, broken in regs:
            pp = os.path.join(tmp, "p.yaml")
            write(pp, text)
            _, v = build_help.degraded_reask(doc, forms, phrases_path=pp)
            self.assertIsNotNone(v, label)
            self.assertTrue(any(n in ("reask.outcome_missing", "reask.table_not_mapping") for n in v.names), (label, v.names))
            ctx.reask_violation, ctx.alarmed_keys = v, set()
            before = len(self.alarms(tr))
            other = "reask_unparsed" if broken == "reask_undo_not_found" else "reask_undo_not_found"
            for outcome, reason in ((other, "zz_alpha"), (other, "zz_beta"), (broken, "zz_gamma")):
                poll.reply_text(ctx, outcome, {"reply": {"reason": reason}}, {})
            got = self.alarms(tr)[before:]
            self.assertEqual(len(got), 2, (label, got))
            self.assertIn("zz_alpha", got[0]); self.assertIn("zz_beta", got[1])
            self.assertNotIn("zz_gamma", "".join(got), label)

    def test_registry_alarm_explains_only_its_own_reasons(self):
        poll, ctx, tr = self.ctx()
        ctx.reask_violation = build_help.RegistryViolation([("reask.reason_lost", "reask_reasons.reask_unparsed.zz_named", "x")])
        poll.reply_text(ctx, "reask_unparsed", {"reply": {"reason": "zz_named"}}, {})
        self.assertEqual(self.alarms(tr), [], "причина уже названа нарушением реестра")
        poll.reply_text(ctx, "reask_unparsed", {"reply": {"reason": "zz_other"}}, {})
        self.assertEqual(len(self.alarms(tr)), 1)
        self.assertIn("zz_other", self.alarms(tr)[0])
        ctx.reask_violation = build_help.RegistryViolation([("reask.phrases_yaml", "p", "x")])
        poll.reply_text(ctx, "reask_unparsed", {"reply": {"reason": "zz_third"}}, {})
        self.assertEqual(len(self.alarms(tr)), 1, "файл фраз не читается — алярм реестра покрывает всё")

    def test_alarm_failure_does_not_break_reply(self):
        poll, ctx, tr = self.ctx()
        ctx.transport = None                                       # отправка алярма падает — ответ человеку всё равно есть
        text = poll.reply_text(ctx, "reask_unparsed", {"reply": {"reason": "zz_unmapped"}}, {})
        self.assertTrue(text)
        self.assertTrue([o for o in ctx.trace.ops if o["op"] == "alarm_failed"])


def REASK_NAMES():
    return [n for _, _, n in reason_rows(PHR)]


class CodeSideClosure(unittest.TestCase):
    """Множество причин — из КОДА: правка производителя без правки реестра — отказ; неразрешимый источник, пересылка
    без охраны, ответ-фраза без причины, неоднозначный сток, неразбираемый модуль — ошибка сборщика (rc 4).
    Сверка с независимым оракулом: на исходном коде и на мутациях без ошибки сборщика классификации совпадают."""

    def setUp(self):
        self.src = build_help.bot_sources()
        self.doc = yamlmini.load_file(REG)
        self.forms = build_help.load_forms(FORMS)

    def patch(self, mod, old, new, count=1):
        s = self.src[mod].decode("utf-8")
        self.assertEqual(s.count(old), count, "якорь мутации %s: %r (ожидалось %d)" % (mod, old, count))
        out = dict(self.src)
        out[mod] = s.replace(old, new).encode("utf-8")
        return out

    def product(self, src):
        try:
            build_help.check_reask(self.doc, self.forms, sources=src)
            return set(), None
        except build_help.ReasonScanError as e:
            return set(e.names), "scan"
        except build_help.RegistryViolation as e:
            return set(e.names), "registry"

    def oracle_view(self, src):
        return {o: set(v) for o, v in oracle.code_reasons({k: v.decode("utf-8") for k, v in src.items()}).items()}

    def product_view(self, src):
        return {o: set(v) for o, v in build_help.code_reasons(src).items()}

    def test_product_scan_equals_independent_oracle(self):
        self.assertEqual(self.product_view(self.src), self.oracle_view(self.src))
        self.assertEqual(self.product(self.src), (set(), None))

    def test_code_mutation_matrix_batch(self):
        L, E, S = {"reask.reason_lost"}, {"reask.reason_extra"}, {"reask.scan_error"}
        s = self.src["parse.py"].decode("utf-8")
        a, b = "secs, s2, reason = self.forms.find(", "return self._unparsed(base, reason)"
        self.assertEqual((s.count(a), s.count(b)), (1, 1), "якорь контроля переименования")
        renamed = dict(self.src, **{"parse.py": s.replace(a, a.replace("reason", "why")).replace(b, b.replace("reason", "why")).encode("utf-8")})
        cases = [
            ("разбор: новая причина вместо единственной", self.patch("parse.py", '_unparsed(base, "not_utf8")', '_unparsed(base, "zz_new_reason")'), L | E, "registry"),
            ("разбор: динамическое имя «имя:%s»", self.patch("parse.py", '"unknown_command:%s" % cmd', '"zz_dyn:%s" % cmd'), L | E, "registry"),
            ("разбор: через распаковку find()", self.patch("parse.py", 'return None, s, "free_text_without_time"\n', 'return None, s, "zz_find_reason"\n', count=2), L | E, "registry"),
            ("машина состояний: новый переспрос", self.patch("session.py", '_reask("reask_unparsed", "last_list_unavailable", n=parsed["n"])', '_reask("reask_unparsed", "zz_sess", n=parsed["n"])', count=2), L | E, "registry"),
            ("поллер: литерал ответа", self.patch("poll.py", '{"reply": {"reason": "confirm_not_allowed"}}', '{"reply": {"reason": "zz_poll"}}'), L | E, "registry"),
            ("агрегация: str(e) ← raise ValueError", self.patch("aggregation.py", 'raise ValueError("summary_period_out_of_range")', 'raise ValueError("zz_period")'), L | E, "registry"),
            ("отзыв: новый отказ выбора цели", self.patch("undo.py", 'return "reask", "n_out_of_range"', 'return "reask", "zz_undo"'), L | E, "registry"),
            ("отзыв: причина-фраза теряет производителя", self.patch("poll.py", '{"reply": {"reason": "target_changed"}}', '{"reply": {"reason": "no_line"}}'), E, "registry"),
            ("ошибка сборщика: неразрешимый источник", self.patch("poll.py", '{"reply": {"reason": "confirm_not_allowed"}}', '{"reply": {"reason": uid}}'), S, "scan"),
            ("ошибка сборщика: пересылка без охраны вида", self.patch("poll.py", 'if parsed["kind"] == "unparsed":\n', 'if parsed.get("addressed") or True:\n'), S, "scan"),
            ("ошибка сборщика: ответ-фраза без причины", self.patch("poll.py", '{"reply": {"reason": "confirm_not_allowed"}}', '{"reply": {}}'), S, "scan"),
            ("ошибка сборщика: динамическая причина без имени", self.patch("parse.py", '"unknown_command:%s" % cmd', '"%s" % cmd'), S, "scan"),
            ("ошибка сборщика: raise с нелитеральной причиной", self.patch("aggregation.py", 'raise ValueError("summary_bad_argument")', 'raise ValueError("bad %s" % n)'), S, "scan"),
            ("ошибка сборщика: неоднозначный сток", dict(self.src, **{"zz_dup.py": b"def _unparsed(a, b):\n    return a\n"}), S, "scan"),
            ("ошибка сборщика: модуль не разобран", dict(self.src, **{"zz_broken.py": b"def (:\n"}), S, "scan"),
            ("ошибка сборщика: исход-фраза в вызове без причины", self.patch("poll.py", '{"reply": {"reason": "target_changed"}}', '{"note": "target_changed"}'), S, "scan"),
            # обратные контроли: переименование локальной переменной причины (присваивание и сток); порядок модулей
            ("контроль: переименование переменной причины", renamed, set(), None),
            ("контроль: обратный порядок модулей", dict(reversed(list(self.src.items()))), set(), None),
        ]
        rows, bad = [], []
        for label, src, want, kind in cases:
            got, gk = self.product(src)
            ok = got == want and gk == kind
            if ok and kind != "scan":        # сверка с независимым оракулом там, где сборщик не отказал
                try:
                    ok = self.product_view(src) == self.oracle_view(src)
                except oracle.OracleError:
                    ok = False
            rows.append("  %s  %-50s → %s %s" % ("PASS" if ok else "FAIL", label, gk or "принят", sorted(got)))
            if not ok:
                bad.append((label, want, kind, got, gk))
        sys.stderr.write("\n[R1-fix: код × сборщик] %d:\n%s\n" % (len(rows), "\n".join(rows)))
        self.assertFalse(bad, bad)

    # ------------------------------------------------------------------ R2: формы возврата источника распаковки
    FIND_NEEDLE = '        if "leading" in self.positions:\n'       # начало тела DurationForms.find после разбора строки
    AMBIG = 'return None, s, "duration_ambiguous"'

    def insert_find(self, code):
        return self.patch("parse.py", self.FIND_NEEDLE, code + self.FIND_NEEDLE)

    def each_ambig(self, fn):
        """Каждый возврат duration_ambiguous заменить fn(отступ) — законный рефакторинг, построчно с отступом."""
        s = self.src["parse.py"].decode("utf-8")
        n = s.count(self.AMBIG)
        self.assertGreaterEqual(n, 2, "якорь duration_ambiguous")
        out = re.sub(r"(?m)^([ \t]*)" + re.escape(self.AMBIG) + "$", lambda m: fn(m.group(1)), s)
        self.assertNotEqual(out, s)
        return dict(self.src, **{"parse.py": out.encode("utf-8")})

    def test_r2_return_forms_matrix_batch(self):
        """Инвариант R2: КАЖДЫЙ return источника распаковки либо разрешён и учтён (с охраной), либо ошибка сборщика
        rc 4; скрытый производитель в любой поддержанной форме — новая причина (rc 3, фразы нет); законный рефакторинг
        существующих возвратов — то же множество и принятие. Ожидаемое множество — исходное ± то, что внесла мутация
        (не из сборщика и не из оракула)."""
        L, E, S = {"reask.reason_lost"}, {"reask.reason_extra"}, {"reask.scan_error"}
        U, N = "reask_unparsed", "reask_undo_not_found"
        base = self.product_view(self.src)
        ind = "            "
        undo_old = 'return "reask", "n_out_of_range"'
        cases = [
            # скрытые производители (новая причина без фразы) — отказ rc 3 «потеряна»
            ("скрытый: return [список]", self.insert_find('        if s == "zz-list":\n%sreturn [None, s, "zz_list_reason"]\n' % ind), L, "registry", {(U, "zz_list_reason")}, set()),
            ("скрытый: через локальную переменную-кортеж", self.insert_find('        if s == "zz-local":\n%szz_r = (None, s, "zz_local_reason")\n%sreturn zz_r\n' % (ind, ind)), L, "registry", {(U, "zz_local_reason")}, set()),
            ("скрытый: локальная переменная-список", self.insert_find('        if s == "zz-local":\n%szz_r = [None, s, "zz_llist_reason"]\n%sreturn zz_r\n' % (ind, ind)), L, "registry", {(U, "zz_llist_reason")}, set()),
            ("скрытый: условное выражение (обе ветви)", self.insert_find('        if s.startswith("zz"):\n%sreturn (None, s, "zz_if_a") if s == "zz" else (None, s, "zz_if_b")\n' % ind), L, "registry", {(U, "zz_if_a"), (U, "zz_if_b")}, set()),
            ("скрытый: локальная, переприсвоенная дважды", self.insert_find('        if s == "zz-two":\n%szz_r = (None, s, "zz_first")\n%szz_r = (None, s, "zz_second")\n%sreturn zz_r\n' % (ind, ind, ind)), L, "registry", {(U, "zz_first"), (U, "zz_second")}, set()),
            ("скрытый в отзыве: через локальную", self.patch("undo.py", undo_old, 'zz_r = ("reask", "zz_undo_local")\n        return zz_r'), L | E, "registry", {(N, "zz_undo_local")}, {(N, "n_out_of_range")}),
            # законные рефакторинги существующих возвратов — принятие, множество то же
            ("законно: возвраты duration_ambiguous списком", self.each_ambig(lambda i: i + 'return [None, s, "duration_ambiguous"]'), set(), None, set(), set()),
            ("законно: через локальную переменную-кортеж", self.each_ambig(lambda i: i + 'zz_r = (None, s, "duration_ambiguous")\n' + i + "return zz_r"), set(), None, set(), set()),
            ("законно: через локальную переменную-список", self.each_ambig(lambda i: i + 'zz_r = [None, s, "duration_ambiguous"]\n' + i + "return zz_r"), set(), None, set(), set()),
            ("законно: цепочка локальных имён", self.each_ambig(lambda i: i + 'zz_a = (None, s, "duration_ambiguous")\n' + i + "zz_b = zz_a\n" + i + "return zz_b"), set(), None, set(), set()),
            ("законно: отзыв через локальную", self.patch("undo.py", undo_old, 'zz_r = ("reask", "n_out_of_range")\n        return zz_r'), set(), None, set(), set()),
            ("законно: отзыв списком", self.patch("undo.py", undo_old, 'return ["reask", "n_out_of_range"]'), set(), None, set(), set()),
            ("законно: условное с существующими именами", self.each_ambig(lambda i: i + 'return (None, s, "duration_ambiguous") if s else (None, s, "free_text_without_time")'), set(), None, set(), set()),
            # формы, которые сборщик не разрешает, — ошибка rc 4, а не пропуск
            ("rc 4: return None в источнике", self.insert_find('        if s == "zz":\n%sreturn None\n' % ind), S, "scan", None, None),
            ("rc 4: return без значения", self.insert_find('        if s == "zz":\n%sreturn\n' % ind), S, "scan", None, None),
            ("rc 4: кортеж другой длины", self.insert_find('        if s == "zz":\n%sreturn None, s\n' % ind), S, "scan", None, None),
            ("rc 4: кортеж со звёздочкой", self.insert_find('        if s == "zz":\n%sreturn (None, *[s, "zz_star"])\n' % ind), S, "scan", None, None),
            ("rc 4: возврат вызова вне кода бота", self.insert_find('        if s == "zz":\n%sreturn tuple([None, s, "zz_tuple"])\n' % ind), S, "scan", None, None),
            ("rc 4: возврат по индексу", self.insert_find('        if s == "zz":\n%sreturn [(None, s, "zz_idx")][0]\n' % ind), S, "scan", None, None),
            ("rc 4: локальная связана циклом", self.insert_find('        if s == "zz":\n%sfor zz_r in [(None, s, "zz_for")]:\n%s    pass\n%sreturn zz_r\n' % (ind, ind, ind)), S, "scan", None, None),
            ("rc 4: локальная связана with-as", self.insert_find('        if s == "zz":\n%szz_r = (None, s, "zz_w")\n%swith open(s) as zz_r:\n%s    pass\n%sreturn zz_r\n' % (ind, ind, ind, ind)), S, "scan", None, None),
            ("rc 4: локальная через :=", self.insert_find('        if (zz_r := (None, s, "zz_walrus")) and s == "zz":\n%sreturn zz_r\n' % ind), S, "scan", None, None),
            ("rc 4: причина записана по ключу [\"reason\"]", self.patch("parse.py", '        out.update({"kind": "unparsed", "reason": reason})\n',
                                                                       '        out.update({"kind": "unparsed", "reason": reason})\n        out["reason"] = reason\n'), S, "scan", None, None),
            ("rc 4: raise переменной в замыкании try", self.patch("aggregation.py", 'raise ValueError("summary_bad_argument")',
                                                                  'zz_err = ValueError("summary_bad_argument")\n        raise zz_err'), S, "scan", None, None),
            ("rc 4: источник — генератор", self.insert_find('        if s == "zz":\n%syield None\n' % ind), S, "scan", None, None),
        ]
        rows, bad = [], []
        for label, src, want, kind, add, drop in cases:
            got, gk = self.product(src)
            ok = got == want and gk == kind
            if ok and add is not None:
                exp = {o: set(v) for o, v in base.items()}
                for o, n in add:
                    exp[o].add(n)
                for o, n in drop:
                    exp[o].discard(n)
                ok = self.product_view(src) == exp
            rows.append("  %s  %-48s → %s %s" % ("PASS" if ok else "FAIL", label, gk or "принят", sorted(got)))
            if not ok:
                bad.append((label, want, kind, got, gk))
        sys.stderr.write("\n[R2-fix: формы возврата × сборщик] %d:\n%s\n" % (len(rows), "\n".join(rows)))
        self.assertFalse(bad, bad)

    def test_scan_error_is_distinct_fatal_cli_outcome(self):
        """rc 4 ≠ rc 3: собственная ошибка сборщика не смешивается с нарушением реестра."""
        self.assertNotEqual(build_help.RC_SCAN_ERROR, build_help.RC_REGISTRY_VIOLATION)
        self.assertTrue(issubclass(build_help.ReasonScanError, build_help.RegistryViolation))
        self.assertEqual(build_help.ReasonScanError([("reask.scan_error", "x", "y")]).rc, build_help.RC_SCAN_ERROR)


if __name__ == "__main__":
    unittest.main()
