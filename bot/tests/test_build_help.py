"""Оракул build_help.py. Реестр читается НЕЗАВИСИМЫМ читателем (регэксп по сырому тексту), а не
yamlmini, — оракул не делит с генератором parser. Проверяются: полнота проекции (каждая позиция
реестра — в справке, в краткой справке и в блоке инструкции), детерминизм (два прогона побайтово
равны), чувствительность (добавленная позиция меняет ОБА выхода), маркеры инструкции, N."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KIT = os.path.join(_BOT, "kit")
GEN = os.path.join(_KIT, "build_help.py")
COMMANDS = os.path.join(_KIT, "commands.yaml")
STEPS = os.path.join(_KIT, "install-steps.yaml")
GUIDE = os.path.join(_KIT, "docs", "bot-user-guide.ru.md")
PY = sys.executable


def run(*argv):
    p = subprocess.run([PY, GEN] + list(argv), capture_output=True)
    return p.returncode, p.stdout.decode("utf-8")


def registry_names(path):
    """Независимый читатель: имена позиций из сырого текста (строки `    name: "..."` внутри commands:)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("\ncommands:\n", 1)[1]
    return re.findall(r'^    name: "(.*)"$', body, re.M)


def registry_ids(path):
    """Независимый читатель: id позиций из сырого текста (строки `  - id: ` внутри commands:)."""
    with open(path, encoding="utf-8") as fh:
        body = fh.read().split("\ncommands:\n", 1)[1]
    return re.findall(r"^  - id: (\S+)$", body, re.M)


def registry_tokens(path):
    with open(path, encoding="utf-8") as fh:
        body = fh.read().split("\ncommands:\n", 1)[1]
    return sorted({t for t in re.findall(r'^    token: "(.*)"$', body, re.M) if t})


def help_page_raw_text(text):
    return text.split("\nhelp_page:\n", 1)[1].split("\ncommands:\n", 1)[0]


def help_page_raw(path):
    """Сырой текст макета справки (между `help_page:` и `commands:`) — для проверки литералов команд."""
    with open(path, encoding="utf-8") as fh:
        return help_page_raw_text(fh.read())



def token_by_id(path):
    """Независимый читатель: id позиции → токен (литералов команд в тесте нет)."""
    with open(path, encoding="utf-8") as fh:
        body = fh.read().split("\ncommands:\n", 1)[1]
    out, cur = {}, None
    for ln in body.split("\n"):
        m = re.match(r"^  - id: (\S+)$", ln)
        if m:
            cur = m.group(1); continue
        m = re.match(r'^    token: "(.*)"$', ln)
        if m and cur:
            out[cur] = m.group(1)
    return out


_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        sys.path.insert(0, _BOT)
        import parse  # noqa: E402 — оракул сообщений: настоящий разбор, как у бота
        _PARSER = parse.Parser(COMMANDS, bot_username="cp_workshop_test_bot")
    return _PARSER


def page_items(raw):
    """Независимый читатель макета: элементы `  - ключ: …` с полями `    ключ: …` в ЛЮБОМ порядке; значения в двойных,
    одинарных кавычках или без них (R2-02, R2-03 — без молчаливых пропусков)."""
    items, cur = [], None
    for ln in raw.split("\n"):
        m = re.match(r"^  - (\w+): ?(.*)$", ln)
        if m:
            cur = {m.group(1): _scalar(m.group(2))}; items.append(cur); continue
        m = re.match(r"^    (\w+): ?(.*)$", ln)
        if m and cur is not None:
            cur[m.group(1)] = _scalar(m.group(2)); continue
        if ln.strip() and not ln.lstrip().startswith("#"):
            raise AssertionError("макет: строка вне формы элемента: %r" % ln)
    return items


_DQ_SIMPLE = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
              "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"}
_DQ_HEX = {"x": 2, "u": 4, "U": 8}


def _dq_decode(body):
    """Escape-последовательности строки YAML в двойных кавычках — полный набор YAML 1.2 (надмножество того, что читает
    продукт), собственный декодер оракула (B1: закодированный литерал команды не прячется). Неизвестный escape — отказ."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c); i += 1; continue
        if i + 1 >= len(body):
            raise AssertionError("макет: оборванный escape в %r" % body)
        e = body[i + 1]
        if e in _DQ_SIMPLE:
            out.append(_DQ_SIMPLE[e]); i += 2
        elif e in _DQ_HEX:
            n = _DQ_HEX[e]; h = body[i + 2:i + 2 + n]
            if len(h) != n or not re.fullmatch(r"[0-9A-Fa-f]+", h):
                raise AssertionError("макет: плохой \\%s escape в %r" % (e, body))
            out.append(chr(int(h, 16))); i += 2 + n
        else:
            raise AssertionError("макет: неизвестный escape \\%s в %r" % (e, body))
    return "".join(out)


def _scalar(v):
    """Значение поля макета: "двойные" (escape раскрываются), 'одинарные' ('' → '), plain; хвостовой комментарий
    ` # …` вне кавычек снимается. Любая иная форма (текст после закрывающей кавычки, незакрытая кавычка) — отказ
    оракула, а не сырое значение (M4 P2)."""
    v = v.strip()
    if v[:1] in ('"', "'"):
        q, i, buf = v[0], 1, []
        while i < len(v):
            c = v[i]
            if q == '"' and c == "\\":
                buf.append(v[i:i + 2]); i += 2; continue
            if c == q:
                if q == "'" and v[i + 1:i + 2] == "'":
                    buf.append("'"); i += 2; continue
                break
            buf.append(c); i += 1
        else:
            raise AssertionError("макет: незакрытая кавычка: %r" % v)
        rest = v[i + 1:]
        if rest.strip() and not re.match(r"^[ \t]+#", rest):
            raise AssertionError("макет: текст после закрывающей кавычки: %r" % v)
        body = "".join(buf)
        return _dq_decode(body) if q == '"' else body
    m = re.search(r"[ \t]#", v)
    return v[:m.start()].rstrip() if m else v

def page_prose(raw):
    """Все значения text / note / lead макета (любые кавычки) — где литералы команд запрещены."""
    return [it[k] for it in page_items(raw) for k in ("text", "note", "lead") if k in it]


def mismatched_examples(raw):
    """Элементы `ex` макета, у которых нет line или line не разбирается в объявленную позицию (обёртка wrapped_by —
    тоже позиция). Каждый элемент ex проверяется; извлечение не зависит от порядка полей."""
    exs = [it for it in page_items(raw) if "ex" in it]
    assert exs, "в макете нет примеров"
    bad = []
    for it in exs:
        pid, line = it["ex"], it.get("line")
        if not line:
            bad.append((pid, None, "нет line", None)); continue
        r = _parser().parse({"update_id": 1, "message": {"message_id": 1, "date": 1788790990, "chat": {"id": 1, "type": "private"},
                                                         "from": {"id": 1, "first_name": "Dev"}, "text": line}})
        if r.get("kind") != "input" or pid not in (r.get("position"), r.get("wrapped_by")):
            bad.append((pid, line, r.get("position"), r.get("wrapped_by")))
    return bad

def help_positions(text):
    """Каждая строка справки с отступом — сообщение, которое бот принимает: часть до « — » разбирается парсером.
    Возвращает (список (сообщение, разбор), множество представленных позиций, включая обёртку)."""
    rows, seen = [], set()
    for ln in text.split("\n"):
        if not ln.startswith("  "):
            continue
        msg = ln[2:].split(" — ", 1)[0]
        r = _parser().parse({"update_id": 1, "message": {"message_id": 1, "date": 1788790990, "chat": {"id": 1, "type": "private"},
                                                         "from": {"id": 1, "first_name": "Dev"}, "text": msg}})
        rows.append((msg, r))
        if r.get("kind") == "input":
            seen.add(r["position"])
            if r.get("wrapped_by"):
                seen.add(r["wrapped_by"])
    return rows, seen


def steps_count(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("\nsteps:\n", 1)[1]
    return len(re.findall(r"^  - id: ", body, re.M))


class ProjectionTests(unittest.TestCase):
    def test_registry_positions_unique_and_nonempty(self):
        # D15: число позиций — свойство реестра, не константа теста (прежнее «ровно 9» — ручной счётчик);
        # инвариант: имена уникальны, реестр непуст, и render печатает ровно это число
        names = registry_names(COMMANDS)
        self.assertTrue(names)
        self.assertEqual(len(names), len(set(names)))

    def test_help_short_block_cover_every_position(self):
        names = registry_names(COMMANDS)
        for sub in ("short", "commands-block"):
            rc, out = run(sub)
            self.assertEqual(rc, 0, out)
            for n in names:
                self.assertIn(n, out, "%s: нет позиции %r" % (sub, n))
        # [D19 M2, 2026-10-12: справка — по макету help_page; её полнота — HelpPageTests: каждая позиция реестра
        # представлена примером, который принимает парсер (прежнее «имя позиции в справке» — для справки без макета).]
        rc, out = run("help")
        self.assertEqual(rc, 0, out)
        self.assertEqual(help_positions(out)[1], set(registry_ids(COMMANDS)))

    def test_deterministic(self):
        for sub in ("help", "short", "commands-block", "steps-block"):
            self.assertEqual(run(sub), run(sub))

    def test_added_position_changes_both_outputs(self):
        tmp = tempfile.mkdtemp(prefix="bh-")
        try:
            p = os.path.join(tmp, "commands.yaml")
            with open(COMMANDS, encoding="utf-8") as fh:
                text = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text + (
                    "  - id: zz_probe\n    name: \"/zzprobe\"\n    token: \"/zzprobe\"\n    synopsis: \"\"\n"
                    "    grammar: x\n    example: \"/zzprobe\"\n    time_bearing: false\n    callback_allowed: false\n"
                    "    tail_rule: none\n    outcomes: [help_given]\n    help_text: проба\n    guide_text: |\n      проба\n"))
            for sub in ("help", "commands-block"):
                rc, base = run(sub)
                rc2, mut = run(sub, "--commands", p)
                self.assertEqual((rc, rc2), (0, 0))
                self.assertNotEqual(base, mut)
                self.assertIn("/zzprobe", mut)
                self.assertNotIn("/zzprobe", base)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_steps_block_and_count(self):
        n = steps_count(STEPS)
        rc, out = run("count-steps")
        self.assertEqual(out.strip(), str(n))
        rc, block = run("steps-block")
        self.assertIn("N = %d" % n, block)
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", block, re.M)), n)
        tmp = tempfile.mkdtemp(prefix="st-")
        try:
            p = os.path.join(tmp, "steps.yaml")
            with open(STEPS, encoding="utf-8") as fh:
                text = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text + "  - id: zz_probe\n    title: проба\n    when: always\n    guide: проба\n    verified_by: проба\n")
            rc, out2 = run("count-steps", "--steps", p)
            self.assertEqual(out2.strip(), str(n + 1))
            rc, block2 = run("steps-block", "--steps", p)
            self.assertNotEqual(block, block2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_guide_markers_and_render_idempotent(self):
        with open(GUIDE, encoding="utf-8") as fh:
            guide = fh.read()
        for tag in ("commands", "steps", "correction-example"):
            self.assertEqual(guide.count("<!-- generated:%s:start -->" % tag), 1)
            self.assertEqual(guide.count("<!-- generated:%s:end -->" % tag), 1)
        rc, rendered = run("render", "--guide", GUIDE)
        self.assertEqual(rc, 0)
        self.assertEqual(rendered, guide, "инструкция на диске не равна перегенерированной: блоки правлены руками?")
        for n in registry_names(COMMANDS):
            self.assertIn(n, guide)
        # проза вне сгенерированных блоков не называет команд литералами
        prose = re.sub(r"<!-- generated:commands:start -->.*?<!-- generated:commands:end -->", "", guide, flags=re.S)
        prose = re.sub(r"<!-- generated:steps:start -->.*?<!-- generated:steps:end -->", "", prose, flags=re.S)
        # пример исхода 6 в прозе — из реестра (раунд 2, W4): совпадает с correction_examples[0] и парсится как correction
        m = re.search(r"<!-- generated:correction-example:start -->(.*?)<!-- generated:correction-example:end -->", guide, re.S)
        self.assertIsNotNone(m)
        first = re.search(r'^correction_examples:\n  - "(.*)"$', open(os.path.join(os.path.dirname(COMMANDS), "duration-forms.yaml"), encoding="utf-8").read(), re.M).group(1)
        self.assertEqual(m.group(1), "«%s»" % first)
        self.assertNotIn("«", re.sub(r"<!-- generated:correction-example:start -->.*?<!-- generated:correction-example:end -->", "", prose.split("<!-- section: reask -->", 1)[1].split("<!-- section:", 1)[0], flags=re.S).replace("«длительность и\nзаголовок»", ""), "в разделе переспроса — рукописные примеры вне реестра")
        for n in registry_names(COMMANDS):
            tok = n.split(" ")[0]
            if tok.startswith("/") or tok.startswith("!"):
                self.assertNotIn(tok, prose, "литерал команды в прозе инструкции: %s" % tok)


class HelpPageTests(unittest.TestCase):
    """[D19 M2, 2026-10-12, слово alex] Справка по макету help_page: примеры первым экраном, команды — сценариями."""

    def test_every_indented_line_is_accepted_message(self):
        rc, out = run("help")
        self.assertEqual(rc, 0, out)
        rows, _ = help_positions(out)
        self.assertTrue(rows)
        for msg, r in rows:
            self.assertEqual(r.get("kind"), "input", "пример справки бот не примет: %r → %r" % (msg, r.get("reason")))
            m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", msg)
            if m:
                self.assertEqual(r.get("date"), m.group(1), "дата примера не прочитана: %r" % msg)

    def test_every_position_represented_and_tokens_complete(self):
        rc, out = run("help")
        _, seen = help_positions(out)
        self.assertEqual(seen, set(registry_ids(COMMANDS)))
        lexical = set(re.findall(r"(?<![\w@])/[a-z_]+\b", out))
        self.assertEqual(lexical, set(registry_tokens(COMMANDS)))

    def test_each_example_matches_declared_position(self):
        """R1-05: пример `ex: <id>` разбирается именно в позицию id (подтверждение — обёрткой wrapped_by)."""
        bad = mismatched_examples(help_page_raw(COMMANDS))
        self.assertEqual(bad, [])

    def test_runtime_broken_page_falls_back(self):
        """R1-02: испорченный макет в рантайме не роняет ответ — прежний перечень; CLI — отказ."""
        code = ("import sys; sys.path[:0] = [%r, %r]; import build_help as b; d = b.load_commands(sys.argv[1]); "
                "d['help_page'] = [x if x.get('ex') != 'last' else dict(x, ex='nonexistent') for x in d['help_page']] + [42]; "
                "t = b.render_help(d, b.load_forms(sys.argv[2])); print('LEGACY' if t.startswith('Команды бота') else 'PAGE')"
                % (_KIT, _BOT))
        p = subprocess.run([PY, "-c", code, COMMANDS, os.path.join(_KIT, "duration-forms.yaml")], capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(p.stdout.decode().strip(), "LEGACY")

    def test_fits_one_message_and_no_registry_jargon(self):
        rc, out = run("help")
        self.assertLessEqual(len(out), 4096)
        for jargon in ("позиций в реестре", "реестр", "push", "дневн"):
            self.assertNotIn(jargon, out)

    def test_page_text_has_no_command_literals(self):
        prose = "\n".join(page_prose(help_page_raw(COMMANDS)))
        for tok in registry_tokens(COMMANDS):
            self.assertNotIn(tok, prose, "литерал команды в тексте макета (нужна подстановка {token:…}): %s" % tok)

    def test_mutation_batch(self):
        """Матрица мутаций макета пакетом: ошибки макета — отказ генератора; порча примера/потеря позиции — красный
        оракул; законная перестановка — зелёный оракул."""
        with open(COMMANDS, encoding="utf-8") as fh:
            base = fh.read()
        tmp = tempfile.mkdtemp(prefix="hp-")

        def gen(text):
            p = os.path.join(tmp, "commands.yaml")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
            return run("help", "--commands", p)

        def once(old, new):
            self.assertEqual(base.count(old), 1, old)
            return base.replace(old, new)
        try:
            # отказ генератора (rc != 0): неизвестная позиция, неизвестная форма, неизвестная подстановка
            for bad in (once("  - ex: last\n", "  - ex: nonexistent\n"),
                        once("units_short_leading, minutes_short_only", "units_short_leading, no_such_form"),
                        once("из {token:last};", "из {token:nope};")):
                rc, out = gen(bad)
                self.assertNotEqual(rc, 0, "генератор принял испорченный макет")
            # порча примера: бот такое сообщение не примет → оракул красный
            stop = token_by_id(COMMANDS)["stop"]
            rc, out = gen(once('    line: "%s 18:30"' % stop, '    line: "%s 25:99"' % stop))
            self.assertEqual(rc, 0)
            self.assertTrue(any(r.get("kind") != "input" for _, r in help_positions(out)[0]))
            # потеря позиции в макете: справка всё равно полна (позиция — в конце парой name — help_text)
            last = token_by_id(COMMANDS)["last"]
            m = re.search(r'^  - ex: last\n    line: ".*"\n(?:    note: ".*"\n)?', base, re.M)
            self.assertIsNotNone(m)
            dup = m.group(0)
            rc, out = gen(once(dup, ""))
            self.assertEqual(rc, 0)
            self.assertIn('%s [N] — ' % last, out)
            rows, seen = help_positions(out)
            self.assertTrue(all(r.get("kind") == "input" for _, r in rows), "резервный пример позиции бот не примет")
            self.assertIn("last", seen)
            rc, out = gen(once('    lead: "Ещё можно так: "', '    lead: "{token:nonexistent} Ещё можно так: "'))
            self.assertNotEqual(rc, 0, "lead с неизвестной подстановкой принят")
            # дубликат примера: генератор не падает, строка повторена (вид — решение макета)
            rc, out = gen(once(dup, dup + dup))
            self.assertEqual(rc, 0)
            self.assertEqual(out.count("\n  %s — " % last), 2)
            # законная перестановка двух секций: оракул зелёный, вывод другой
            a = '  - text: "Отрезком времени:"\n'
            rc0, out0 = run("help")
            rc, out = gen(once(a, "") .replace('  - text: "Секундомером:"\n', a + '  - text: "Секундомером:"\n', 1))
            self.assertEqual(rc, 0)
            self.assertNotEqual(out, out0)
            self.assertTrue(all(r.get("kind") == "input" for _, r in help_positions(out)[0]))
            # R1-05: перестановка line у двух примеров разных позиций — оракул «пример ↔ позиция» красный
            help_tok = token_by_id(COMMANDS)["help"]
            sw = base.replace('    line: "%s"\n' % last, '    line: "@@L"\n', 1).replace('    line: "%s"\n' % help_tok, '    line: "%s"\n' % last, 1).replace('    line: "@@L"\n', '    line: "%s"\n' % help_tok, 1)
            self.assertNotEqual(sw, base)
            self.assertTrue(mismatched_examples(help_page_raw_text(sw)))
            # R2-02: та же перестановка при другом допустимом порядке полей (note между ex и line) — не пропускается
            ms = re.search(r'^  - ex: start_title\n    line: (".*")\n    note: (".*")\n', base, re.M)
            mn = re.search(r'^  - ex: start_n\n    line: (".*")\n    note: (".*")\n', base, re.M)
            self.assertTrue(ms and mn)
            ro = base.replace(ms.group(0), "  - ex: start_title\n    note: %s\n    line: %s\n" % (ms.group(2), mn.group(1)), 1) \
                     .replace(mn.group(0), "  - ex: start_n\n    note: %s\n    line: %s\n" % (mn.group(2), ms.group(1)), 1)
            rc, out = gen(ro)
            self.assertEqual(rc, 0)
            self.assertEqual(len(mismatched_examples(help_page_raw_text(ro))), 2)
            # R2-03: литерал команды в lead в одинарных кавычках — находится проверкой литералов
            stop_tok = token_by_id(COMMANDS)["stop"]
            lq = once('    lead: "Ещё можно так: "', "    lead: '%s — конец; ещё форма: '" % stop_tok)
            rc, out = gen(lq)
            self.assertEqual(rc, 0)
            self.assertTrue(any(stop_tok in v for v in page_prose(help_page_raw_text(lq))))
            # B1: литерал команды, закодированный escape-последовательностью двойных кавычек, — тоже находится
            enc = "".join("\\u%04x" % ord(ch) if ch == "/" else ch for ch in stop_tok)
            # исход каждой формы закреплён (M4 P3): \\u, \\U, \\/ продукт читает → литерал в ответе и найден оракулом
            # (в том числе с хвостовым комментарием — M4 P2); \\x продукт не читает → отказ генератора
            forms = [(enc, True), (stop_tok.replace("/", "\\U0000002f", 1), True), (stop_tok.replace("/", "\\/", 1), True),
                     (stop_tok.replace("/", "\\x2f", 1), False)]
            for form, readable in forms:
                for tail in ("", " # комментарий"):
                    le = once('    lead: "Ещё можно так: "', '    lead: "%s — конец; ещё форма: "%s' % (form, tail))
                    rc, out = gen(le)
                    if not readable:
                        self.assertNotEqual(rc, 0, form); continue
                    self.assertEqual(rc, 0, form + tail)
                    self.assertIn(stop_tok + " — конец", out, form + tail)
                    self.assertTrue(any(stop_tok in v for v in page_prose(help_page_raw_text(le))), form + tail)
            # text с escape-литералом и комментарием (воспроизведение P2) — тоже находится
            te = base.replace("\nhelp_page:\n", '\nhelp_page:\n  - text: "%s" # audit\n' % enc, 1)
            self.assertTrue(any(stop_tok in v for v in page_prose(help_page_raw_text(te))))
            # неподдержанная форма значения — отказ оракула, а не сырое значение
            with self.assertRaises(AssertionError):
                page_prose('  - text: "незакрытая\n')
            with self.assertRaises(AssertionError):
                page_prose('  - text: "а" лишнее\n')
            # без макета — прежняя справка (обратная совместимость проекции)
            rc, out = gen(base.replace("\nhelp_page:\n", "\nhelp_page_off:\n", 1))
            self.assertEqual(rc, 0)
            self.assertIn("позиций в реестре: %d" % len(registry_ids(COMMANDS)), out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
