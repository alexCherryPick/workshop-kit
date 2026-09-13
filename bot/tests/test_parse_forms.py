# -*- coding: utf-8 -*-
"""Оракул реестра форм длительности (T8, REQ-094). Ожидания — ТОЛЬКО пары «пример → expected_seconds /
expected_title» реестра (golden) и собственный пересчёт на Decimal; regex реестра оракул не читает
(правило сходимости §2: общего хелпера с писателем нет). Матрица мутаций — пакетом."""
import decimal
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import parse  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "..", "kit", "commands.yaml")
FORMS = os.path.join(HERE, "..", "kit", "duration-forms.yaml")


def upd(text, chat_type="private"):
    return {"update_id": 1, "message": {"message_id": 1, "date": 1789188000, "chat": {"id": 5, "type": chat_type},
                                        "from": {"id": 5, "first_name": "A"}, "text": text}}


_DQ = r'"((?:[^"\\]|\\.)*)"'
_SQ = r"'((?:[^']|'')*)'"


def scalar(rest):
    """Своё чтение YAML-скаляра (раунд 4, W5): двойные кавычки с экранированием, одинарные с удвоением, затем
    необязательный комментарий; иное — явный отказ (не пропуск)."""
    m = re.match(r"^\s*(?:%s|%s)\s*(?:#.*)?$" % (_DQ, _SQ), rest)
    if not m:
        raise AssertionError("оракул: неподдерживаемый скаляр реестра: %r" % rest)
    if m.group(1) is not None:
        return _unescape_dq(m.group(1))
    return m.group(2).replace("''", "'")


def _unescape_dq(body):
    r"""Строгий автомат escape двойных кавычек YAML (раунд 5, W3): явный репертуар — \\ \" \/ \n \t \r \0 \xXX \uXXXX
    \UXXXXXXXX; всё прочее — отказ, не «как есть»."""
    out, i = [], 0
    simple = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "t": "\t", "r": "\r", "0": "\0", " ": " "}
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c); i += 1; continue
        i += 1
        if i >= len(body):
            raise AssertionError("оракул: оборванный escape")
        e = body[i]
        if e in simple:
            out.append(simple[e]); i += 1; continue
        width = {"x": 2, "u": 4, "U": 8}.get(e)
        if width is None or not re.match(r"^[0-9A-Fa-f]{%d}$" % width, body[i + 1:i + 1 + width]):
            raise AssertionError("оракул: неподдерживаемый escape \\%s" % e)
        out.append(chr(int(body[i + 1:i + 1 + width], 16))); i += 1 + width
    return "".join(out)


def golden():
    """Построчное чтение реестра: только id/example/expected_seconds/expected_title/negative/correction — без YAML-хелпера писателя."""
    forms, neg, corr, corr_neg = [], [], [], []
    items = {"forms": 0, "neg": 0, "corr": 0, "corr_neg": 0}
    cur, section = None, None
    for ln in open(FORMS, encoding="utf-8"):
        s = ln.rstrip("\n")
        if s.startswith("forms:"):
            section = "forms"; continue
        if s.startswith("negative:"):
            section = "neg"; continue
        if s.startswith("correction_examples:"):
            section = "corr"; continue
        if s.startswith("correction_negative_examples:"):
            section = "corr_neg"; continue
        if s and not s.startswith(" ") and not s.startswith("#"):
            section = None
        if section and s.startswith("  - "):
            items[section] += 1          # число элементов списка — независимо от вида скаляра
        if section == "forms":
            m = re.match(r"^  - id: (\S+)$", s)
            if m:
                cur = {"id": m.group(1)}; forms.append(cur); continue
            m = re.match(r"^    example:(.*)$", s)
            if m and cur:
                cur["example"] = scalar(m.group(1))
            m = re.match(r"^    expected_seconds: (\d+)$", s)
            if m and cur:
                cur["seconds"] = int(m.group(1))
            m = re.match(r"^    expected_title:(.*)$", s)
            if m and cur:
                cur["title"] = scalar(m.group(1))
        elif section == "neg":
            m = re.match(r"^  - example:(.*)$", s)
            if m:
                cur = {"example": scalar(m.group(1))}; neg.append(cur); continue
            m = re.match(r"^    reason: (\S+)$", s)
            if m and cur:
                cur["reason"] = m.group(1)
        elif section == "corr":
            m = re.match(r"^  -(.*)$", s)
            if m:
                corr.append(scalar(m.group(1)))
        elif section == "corr_neg":
            m = re.match(r"^  -(.*)$", s)
            if m:
                corr_neg.append(scalar(m.group(1)))
    # полнота чтения (раунд 3 R4, раунд 4 W5): прочитано ровно столько записей, сколько элементов списка в файле
    assert len(forms) == items["forms"], "оракул потерял формы"
    assert len(neg) == items["neg"] and all("reason" in n for n in neg), "оракул потерял негативы"
    assert len(corr) == items["corr"], "оракул потерял примеры исправления"
    assert len(corr_neg) == items["corr_neg"], "оракул потерял негативы исправления"
    assert all("example" in f and "seconds" in f and "title" in f for f in forms), "форма без полей"
    return forms, neg, corr, corr_neg


class FormsGoldenTests(unittest.TestCase):
    def setUp(self):
        self.P = parse.Parser(REG)
        self.forms, self.neg, self.corr, self.corr_neg = golden()

    def test_registry_is_read_not_copied(self):
        self.assertGreaterEqual(len(self.forms), 18)
        src = open(os.path.join(HERE, "..", "parse.py"), encoding="utf-8").read()
        for forbidden in ("DURATION_FORMS", "_RE_UNITS", "_RE_HHMM", "(?:ч|h)", "мин|m|min"):
            self.assertNotIn(forbidden, src, "литерал форм в коде парсера: %s" % forbidden)

    def test_every_form_example_matches_golden(self):
        rows = []
        for f in self.forms:
            r = self.P.parse(upd(f["example"]))
            got = (r.get("kind"), (r.get("time") or {}).get("seconds"), r.get("title"))
            rows.append("  %-28s %-38r → %s" % (f["id"], f["example"], got))
            self.assertEqual(got, ("input", f["seconds"], f["title"]), f["id"])
        sys.stderr.write("\n[forms golden] %d форм:\n%s\n" % (len(rows), "\n".join(rows)))

    def test_negative_corpus_reasons(self):
        for n in self.neg:
            r = self.P.parse(upd(n["example"]))
            self.assertEqual((r["kind"], r.get("reason")), ("unparsed", n["reason"]), n["example"])

    def test_correction_markers_produce_outcome6_and_negatives_record(self):
        for c in self.corr:
            self.assertEqual(self.P.parse(upd(c))["kind"], "correction", c)
        for c in self.corr_neg:
            self.assertEqual(self.P.parse(upd(c))["kind"], "input", c)

    def units_from_registry(self):
        units, cur = {}, None
        in_units = False
        for ln in open(FORMS, encoding="utf-8"):
            s = ln.rstrip("\n")
            if s.startswith("units:"):
                in_units = True; continue
            if in_units and s and not s.startswith(" "):
                break
            if not in_units:
                continue
            m = re.match(r"^  (\w+):$", s)
            if m:
                cur = {"name": m.group(1)}; continue
            m = re.match(r"^    seconds: (\d+)$", s)
            if m and cur:
                cur["seconds"] = int(m.group(1))
            m = re.match(r"^    tokens: \[(.*)\]$", s)
            if m and cur:
                for t in m.group(1).split(","):
                    units[t.strip().lower()] = cur["seconds"]
        self.assertGreaterEqual(len(units), 10)
        return units

    def test_independent_decimal_recount(self):
        """Собственный пересчёт секунд из примера словарём единиц ОРАКУЛА (не реестром писателя)."""
        units = self.units_from_registry()   # раунд 1: словарь единиц оракула читается из реестра своим построчным читателем, не копируется
        rx = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-zа-я]+)\.?", re.IGNORECASE)
        for f in self.forms:
            ex = f["example"]
            if ":" in ex.split()[0]:      # ЧЧ:ММ — только ведущая позиция (hhmm_positions)
                hh, mm = re.match(r"(\d+):(\d\d)", ex.split()[0]).groups(); want = int(hh) * 3600 + int(mm) * 60
            else:
                want = decimal.Decimal(0)
                head = ex.split(" ")
                tokens = [t for t in rx.finditer(ex) if t.group(2).lower() in units]
                # правило позиций оракула (своё, без исключений по id): есть ведущая сцепка — считается только она
                # (максимальная серия единиц от начала строки); иначе — серия в конце строки
                lead = re.match(r"^(?:\s*\d+(?:[.,]\d+)?\s*[a-zа-я]+\.?,?)+", ex, re.IGNORECASE)
                if lead and rx.match(ex.strip()):
                    tokens = [t for t in tokens if t.end() <= lead.end()]
                else:
                    tail = re.search(r"(?:\s*\d+(?:[.,]\d+)?\s*[a-zа-я]+\.?,?)+\s*$", ex, re.IGNORECASE)
                    tokens = [t for t in tokens if tail and t.start() >= tail.start()]
                for t in tokens:
                    want += decimal.Decimal(t.group(1).replace(",", ".")) * units[t.group(2).lower()]
                want = int(want)
            self.assertEqual(want, f["seconds"], "golden реестра расходится с независимым пересчётом: %s" % f["id"])

    def test_mutation_matrix_batch(self):
        P = self.P
        cases = [
            ("единица без числа", "ч проба", "unparsed", "free_text_without_time"),
            ("число без единицы", "1 проба", "unparsed", "free_text_without_time"),
            ("две несоседние", "созвон 30м с юристами 1ч", "unparsed", "duration_ambiguous"),
            ("повтор единицы", "1ч 2ч созвон", "unparsed", "duration_ambiguous"),
            ("десятичные минуты", "1.5м созвон", "unparsed", "duration_ambiguous"),
            ("единица на конце при ведущей", "1ч пробежка 400м", "input", 3600),
            ("буквы сразу после единицы", "1мес проба", "unparsed", "free_text_without_time"),
            ("составная соседняя", "1 час 15 минут созвон", "input", 4500),
            ("запятая-десятичная", "0,5ч созвон", "input", 1800),
            ("конечная с датой", "2026-09-01 проба 1ч", "input", 3600),
            ("маркер исправления", "вместо 2ч — 1ч", "correction", "correction_like"),
            ("25 часов — не грамматика, а HOURS_RANGE валидатора", "25ч созвон", "input", 90000),
        ]
        rows = []
        for name, text, kind, detail in cases:
            r = P.parse(upd(text))
            got = (r["kind"], r.get("reason") if r["kind"] != "input" else (r.get("time") or {}).get("seconds"))
            rows.append("  %-4s %-45s %r → %s" % ("PASS" if got == (kind, detail) else "FAIL", name, text, got))
            self.assertEqual(got, (kind, detail), name)
        sys.stderr.write("\n[forms mutations] %d:\n%s\n" % (len(rows), "\n".join(rows)))

    def test_oracle_reader_is_metamorphic_to_yaml_formatting(self):
        """Раунд 4, W5: комментарий с кавычками и одинарные кавычки не меняют прочитанное; неподдерживаемый скаляр — отказ."""
        self.assertEqual(scalar(' "1:20 созвон" # "note"'), "1:20 созвон")
        self.assertEqual(scalar(" 'not 3h but 1h'"), "not 3h but 1h")
        self.assertEqual(scalar(" 'it''s'  # x"), "it's")
        self.assertEqual(scalar(' "a \\"q\\" b"'), 'a "q" b')
        self.assertEqual(scalar(' "\\u0031:20 созвон"'), "1:20 созвон")
        self.assertEqual(scalar(' "\\U00000031:20 \\x41"'), "1:20 A")
        with self.assertRaises(AssertionError):
            scalar(" bare text")
        with self.assertRaises(AssertionError):
            scalar(' "\\q"')

    def test_preposition_guard_uses_unicode_whitespace(self):
        """Раунд 7, B1: разделитель перед предлогом — любой Unicode-пробел, запрет конечной длительности не обходится."""
        preps = ["в", "через", "около", "for", "in", "until", "Через", "ОКОЛО", "Until", "ABOUT"]   # регистр предлога (раунд 8, оракул)
        seps = [" ", "\t", "\u00a0", "\u2009", "\u202f"]
        durs = ["2ч", "30 min", "1 час"]
        for p in preps:
            for sep in seps:
                for d in durs:
                    r = self.P.parse(upd("созвон%s%s %s" % (sep, p, d)))
                    self.assertEqual((r["kind"], r.get("reason")), ("unparsed", "free_text_without_time"), repr((p, sep, d)))
        r = self.P.parse(upd("созвон\u00a0с юристами 1ч"))
        self.assertEqual((r["kind"], r["time"]["seconds"]), ("input", 3600))
        # раунд 8 (Fable W3): невидимые форматирующие символы (Cf) перед/внутри предлога не создают «другого слова»
        for inv in ("\u200b", "\u00ad", "\u200d", "\u200c", "\u2060", "\ufeff", "\u202a", "\ufe0f", "\u034f", "\u115f", "\u3164", "\U000e0001", "\u061c"):   # + Default_Ignorable вне Cf (раунд 9)
            for text in ("созвон чер%sез 2ч" % inv, "созвон %sчерез 2ч" % inv, "созвон через%s 2ч" % inv, "созвон через %s 2ч" % inv, "созвон через %s%s 2ч" % (inv, inv)):   # фантомная лексема из одних невидимых — не лексема (раунд 10 B W1)
                r = self.P.parse(upd(text))
                self.assertEqual((r["kind"], r.get("reason")), ("unparsed", "free_text_without_time"), repr(text))
        r = self.P.parse(upd("1ч со\u00adзвон"))
        self.assertEqual((r["kind"], r["title"]), ("input", "со\u00adзвон"))   # заголовок дословно (раунд 9, W2)
        r = self.P.parse(upd("1ч ٠٫٥ разбор"))   # видимый Cf вне Default_Ignorable (арабский знак) — не снимается
        self.assertEqual(r["title"], "٠٫٥ разбор")
        r = self.P.parse(upd("1ч 👩‍💻 разбор"))
        self.assertEqual((r["kind"], r["title"]), ("input", "👩‍💻 разбор"))     # ZWJ-эмодзи в заголовке цел

    def test_legal_reordering_is_not_equal_but_both_parse(self):
        a = self.P.parse(upd("проба 1ч")); b = self.P.parse(upd("1ч проба"))
        self.assertEqual((a["time"], a["title"]), (b["time"], b["title"]))


if __name__ == "__main__":
    unittest.main()
