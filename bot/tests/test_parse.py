# -*- coding: utf-8 -*-
"""Оракул парсера: реестр читается тестом НЕЗАВИСИМО построчным регэкспом (не yamlmini и не
Parser) — так проверяется, что парсер не держит копии; ожидания по формам ввода — из буквы
реестра (normalization, tail_rule)."""
import os, re, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import parse  # noqa: E402

REG = os.path.join(os.path.dirname(__file__), "..", "kit", "commands.yaml")


def registry_rows():
    rows = []
    cur = None
    in_commands = False
    for ln in open(REG, encoding="utf-8"):
        if ln.startswith("commands:"):
            in_commands = True
        if not in_commands:
            continue
        m = re.match(r"^  - id: (\S+)", ln)
        if m:
            cur = {"id": m.group(1)}; rows.append(cur); continue
        if cur is not None:
            m = re.match(r"^    (token|tail_rule|time_bearing|callback_allowed): (.*)$", ln)
            if m:
                cur[m.group(1)] = m.group(2).strip().strip('"')
    return rows


TOK = {r["id"]: r.get("token", "") for r in registry_rows()}   # токены — ИЗ реестра, литералов команд в тесте нет


def upd(text, uid=1, mid=10, chat=100000001, frm=100000001, ctype="private", date=1788790990):
    return {"update_id": uid, "message": {"message_id": mid, "date": date, "chat": {"id": chat, "type": ctype}, "from": {"id": frm, "first_name": "Dev"}, "text": text}}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.P = parse.Parser(REG, bot_username="cp_workshop_test_bot")
        self.rows = registry_rows()

    def test_registry_has_nine_positions_and_parser_reads_it(self):
        self.assertEqual(len(self.rows), 9)   # T8: +undo
        ids = {r["id"] for r in self.rows}
        self.assertEqual(set(self.P.by_id), ids)
        for r in self.rows:
            self.assertEqual(self.P.by_id[r["id"]]["tail_rule"], r["tail_rule"])

    def test_every_position_reachable(self):
        samples = {"start_title": TOK["start_title"] + " созвон", "start_n": TOK["start_n"] + " 2", "stop": TOK["stop"], "track": TOK["track"] + " 10:15-12:00 разбор",
                   "free_text": "2ч 40м созвон", "last": TOK["last"], "help": TOK["help"], "confirm": TOK["confirm"] + " 1ч правка"}
        for pid, text in samples.items():
            r = self.P.parse(upd(text))
            self.assertEqual(r["kind"], "input", text)
            self.assertEqual(r["position"], "free_text" if pid == "confirm" else pid, text)
            self.assertEqual(r["confirmed"], pid == "confirm")

    def test_normalization_table(self):
        st = TOK["start_title"]
        for text in (st.upper() + " созвон", st + "@cp_workshop_test_bot созвон", st.capitalize() + "@CP_WORKSHOP_TEST_BOT   созвон", "@cp_workshop_test_bot " + st + " созвон"):
            r = self.P.parse(upd(text))
            self.assertEqual((r["kind"], r["position"], r["title"]), ("input", "start_title", "созвон"), text)
        r = self.P.parse(upd(st + "  два  пробела  внутри "))
        self.assertEqual(r["title"], "два  пробела  внутри")   # внутри заголовка байты дословно, края снимаются

    def test_tail_rules_are_bytes_verbatim(self):
        text = TOK["start_title"] + " заголовок\nвторая строка\r\n\n🚀 конец"
        r = self.P.parse(upd(text))
        self.assertEqual(r["tail"], "вторая строка\r\n\n🚀 конец".encode("utf-8"))
        self.assertEqual(r["text"], text.encode("utf-8"))
        r = self.P.parse(upd(TOK["stop"] + "  хвост после токена\nи строка"))
        self.assertEqual(r["tail"], "хвост после токена\nи строка".encode("utf-8"))
        r = self.P.parse(upd(TOK["stop"]))
        self.assertEqual(r["tail"], b"")
        r = self.P.parse(upd(TOK["last"] + "\nчто-то"))
        self.assertEqual(r["tail"], b"")   # tail_rule: none
        r = self.P.parse(upd(TOK["confirm"] + " 1ч правка\nхвост"))
        self.assertEqual((r["position"], r["tail"]), ("free_text", "хвост".encode("utf-8")))  # as_wrapped

    def test_time_forms_closed_list(self):
        cases = {"2ч 40м x": 9600, "2h40m x": 9600, "1:20 x": 4800, "45м x": 2700, "3ч x": 10800, "0:33 x": 1980, "2 ч 40 мин x": 9600}
        for text, secs in cases.items():
            r = self.P.parse(upd(text))
            self.assertEqual((r["kind"], r["time"]["kind"], r["time"]["seconds"]), ("input", "duration", secs), text)
        r = self.P.parse(upd("с 10:15 до 12:00 разбор"))
        self.assertEqual(r["time"], {"kind": "interval", "from": (10, 15), "to": (12, 0)})
        r = self.P.parse(upd("2026-09-05 10:15-12:00 разбор"))
        self.assertEqual((r["date"], r["title"]), ("2026-09-05", "разбор"))
        for bad in ("просто текст", TOK["track"] + " разбор без интервала", TOK["track"] + " 25:00-26:00 x", TOK["start_title"], TOK["start_n"] + " 0", TOK["start_n"] + " -1", TOK["last"] + " много", "/nope", TOK["confirm"]):
            r = self.P.parse(upd(bad))
            self.assertEqual(r["kind"], "unparsed", bad)

    def test_non_inputs_and_callbacks(self):
        self.assertEqual(self.P.parse({"update_id": 1, "channel_post": {"text": "x"}})["kind"], "non_input")
        self.assertEqual(self.P.parse({"update_id": 1, "edited_message": {"text": "x"}})["kind"], "non_input")
        self.assertEqual(self.P.parse({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 1, "type": "private"}, "from": {"id": 1}, "sticker": {}}})["kind"], "non_input")
        self.assertEqual(self.P.parse(upd(TOK["start_title"] + " x", ctype="channel"))["kind"], "non_input")
        cq = {"update_id": 6, "callback_query": {"id": "77", "data": TOK["start_n"] + " 2", "from": {"id": 100000001}, "message": {"message_id": 9, "date": 1, "chat": {"id": 100000001, "type": "private"}}}}
        r = self.P.parse(cq)
        self.assertEqual((r["kind"], r["position"], r["is_callback"], r["message_date"]), ("input", "start_n", True, None))
        self.assertTrue(r["time_bearing"] and not r["callback_allowed"])

    def test_group_attribution_fields(self):
        r = self.P.parse(upd(TOK["start_title"] + "@cp_workshop_test_bot x", chat=-1001, frm=100000003, ctype="supergroup"))
        self.assertEqual((r["chat_id"], r["from_id"], r["chat_type"], r["identity"]), (-1001, 100000003, "supergroup", "tg:-1001:10"))

    def test_registry_mutation_changes_parse_without_code_change(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "commands.yaml")
            shutil.copy(REG, p)
            text = open(p, encoding="utf-8").read().replace('token: "%s"' % TOK["stop"], 'token: "/finish"')
            open(p, "w", encoding="utf-8").write(text)
            P2 = parse.Parser(p)
            self.assertEqual(P2.parse(upd("/finish"))["position"], "stop")
            self.assertEqual(P2.parse(upd(TOK["stop"]))["kind"], "unparsed")
        finally:
            shutil.rmtree(tmp)

    def test_new_position_with_existing_grammar_needs_no_code_change(self):
        # раунд 1, находка 4: диспетчеризация — по ссылке grammar реестра, не по id
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "commands.yaml")
            text = open(REG, encoding="utf-8").read()
            text += ('  - id: assistance\n    name: "/assist"\n    token: "/assist"\n    synopsis: ""\n    grammar: "01-message-to-line.md#grammar-help"\n'
                     '    example: "/assist"\n    time_bearing: false\n    callback_allowed: true\n    tail_rule: none\n    outcomes: [help_given]\n    help_text: x\n    guide_text: x\n')
            open(p, "w", encoding="utf-8").write(text)
            r = parse.Parser(p).parse(upd("/assist"))
            self.assertEqual((r["kind"], r["position"]), ("input", "assistance"))
        finally:
            shutil.rmtree(tmp)
        # раунд 1, находка 5: N в last — положительное целое
        self.assertEqual(self.P.parse(upd(TOK["last"] + " 0"))["kind"], "unparsed")

    def test_no_command_literals_in_parser_code(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "parse.py"), encoding="utf-8").read()
        for tok in set(t for t in TOK.values() if t):
            self.assertNotIn('"%s"' % tok, src); self.assertNotIn("'%s'" % tok, src)


class Round2Tests(unittest.TestCase):
    def setUp(self):
        self.P = parse.Parser(REG, bot_username="cp_workshop_test_bot")

    def test_explicit_date_must_be_calendar(self):
        # Н-2: {месяц 00/13, день 00/30.02/31.04, високосность} × {track, free_text}
        for bad in ("2025-02-30", "2025-13-45", "2025-00-10", "2025-04-31", "2025-01-00", "2023-02-29"):
            for t in (TOK["track"] + " %s 10:00-11:00 x" % bad, "%s 1ч x" % bad):
                r = self.P.parse(upd(t))
                self.assertEqual((r["kind"], r["reason"]), ("unparsed", "date_not_calendar"), t)
        for good in ("2024-02-29", "2025-04-30"):
            self.assertEqual(self.P.parse(upd("%s 1ч x" % good))["date"], good)

    def test_mention_forms_and_after_token_tail(self):
        # Н-3: хвост after_token — от нормализованной командной строки; суффикс — только своего бота
        st = TOK["stop"]
        r = self.P.parse(upd("@cp_workshop_test_bot " + st))
        self.assertEqual((r["position"], r["tail"]), ("stop", b""))
        r = self.P.parse(upd("@cp_workshop_test_bot " + st + "\nхвост"))
        self.assertEqual((r["position"], r["tail"], r["text"]), ("stop", "хвост".encode(), ("@cp_workshop_test_bot " + st + "\nхвост").encode()))
        r = self.P.parse(upd(st + "@cp_workshop_test_bot"))
        self.assertEqual((r["position"], r["tail"]), ("stop", b""))
        r = self.P.parse(upd(st + "@CP_WORKSHOP_TEST_BOT  два пробела"))
        self.assertEqual((r["position"], r["tail"]), ("stop", "два пробела".encode()))
        for other in (st + "@otherbot tail", "@otherbot " + st, TOK["start_title"] + "@otherbot x"):
            r = self.P.parse(upd(other))
            self.assertEqual((r["kind"], r["reason"]), ("non_input", "addressed_to_other_bot"), other)
        # имя бота неизвестно парсеру (None) — любой суффикс снимается (режим тестов; документировано в §0А)
        r = parse.Parser(REG).parse(upd(st + "@anybot x"))
        self.assertEqual((r["position"], r["tail"]), ("stop", b"x"))

    def test_cr_is_not_part_of_title(self):
        # Н-7: CRLF — CR не входит в заголовок/аргумент; тело и хвост — байты как есть
        r = self.P.parse(upd(TOK["start_title"] + " заголовок\r\nхвост"))
        self.assertEqual((r["title"], r["tail"], r["text"][-6:]), ("заголовок", "хвост".encode(), "хвост".encode()[-6:]))
        self.assertIn(b"\r\n", r["text"])
        r = self.P.parse(upd(TOK["stop"] + "\r\nхвост"))
        self.assertEqual((r["position"], r["tail"]), ("stop", "хвост".encode()))
        r = self.P.parse(upd("2ч созвон\r\nтело"))
        self.assertEqual(r["title"], "созвон")



    def test_undo_n_grammar_matrix(self):
        """Раунд 1, №3: N — только положительное целое; опечатки не превращаются в «без номера»."""
        und = self.P.by_id["undo"]["token"]
        def one(text):
            r = self.P.parse(upd(text))
            return (r["kind"], r.get("n"), r.get("title"), r.get("reason"))
        cases = [
            ("3", ("input", 3, "", None)), ("3 лишняя", ("input", 3, "лишняя", None)), ("03", ("input", 3, "", None)),
            ("3-й лишняя", ("input", 3, "лишняя", None)), ("3й", ("input", 3, "", None)), ("№3", ("input", 3, "", None)),
            ("#3 x", ("input", 3, "x", None)), ("3, лишняя", ("input", 3, "лишняя", None)),
            ("", ("input", None, "", None)), ("причина", ("input", None, "причина", None)),
            ("3x", ("unparsed", None, None, "n_not_positive_integer")), ("0", ("unparsed", None, None, "n_not_positive_integer")),
            ("-1", ("unparsed", None, None, "n_not_positive_integer")), ("+2", ("unparsed", None, None, "n_not_positive_integer")),
            ("3.5", ("unparsed", None, None, "n_not_positive_integer")), ("1e3", ("unparsed", None, None, "n_not_positive_integer")),
            # раунд 2, W5: скобки/кавычки вокруг номера — номер; цифры без букв, не разобравшиеся, — переспрос
            ("(3)", ("input", 3, "", None)), ("«3»", ("input", 3, "", None)), ("[3] лишняя", ("input", 3, "лишняя", None)),
            ('"3"', ("input", 3, "", None)), ("3.", ("input", 3, "", None)), ("(3-й)", ("input", 3, "", None)),
            ("2026-09-01", ("unparsed", None, None, "n_not_positive_integer")), ("(x)", ("input", None, "(x)", None)),
            ("v2 лишняя", ("input", None, "v2 лишняя", None)),
            # раунд 3 (B1/W3): Unicode-обёртки и префиксы, числоподобные символы — N либо переспрос, никогда «без N»
            ("（２й） лишняя", ("input", 2, "лишняя", None)), ("“3”", ("input", 3, "", None)), ("«3».", ("input", 3, "", None)),
            ("Nº3", ("input", 3, "", None)), ("N3", ("input", 3, "", None)), ("No.4 x", ("input", 4, "x", None)), ("n°2", ("input", 2, "", None)),
            ("#３", ("input", 3, "", None)), ("٣", ("input", 3, "", None)),
            ("½", ("unparsed", None, None, "n_not_positive_integer")), ("③", ("unparsed", None, None, "n_not_positive_integer")),
            ("³", ("unparsed", None, None, "n_not_positive_integer")), ("Ⅲ", ("unparsed", None, None, "n_not_positive_integer")),
            ("N", ("input", None, "N", None)), ("nota", ("input", None, "nota", None)),
            # раунд 4 (B1): композиция префикс × обёртка × суффикс — снимается до неподвижной точки
            ("#(2-й) лишняя", ("input", 2, "лишняя", None)), ("№（２й） лишняя", ("input", 2, "лишняя", None)), ("N(2)", ("input", 2, "", None)),
            ("(№2)", ("input", 2, "", None)), ("(#3-й)", ("input", 3, "", None)), ("«No.2»", ("input", 2, "", None)),
            ("#(x)", ("input", None, "#(x)", None)), ("№", ("input", None, "№", None)),   # без единого числоподобного символа — причина (раунд 5)
            ("(3x)", ("unparsed", None, None, "n_not_positive_integer")), ("[½]", ("unparsed", None, None, "n_not_positive_integer")),
            # раунд 5 (B1): соседние префиксы в любом числе и порядке
            ("##(2-й) лишняя", ("input", 2, "лишняя", None)), ("№#（２й） лишняя", ("input", 2, "лишняя", None)), ("NNo.(2-й)", ("input", 2, "", None)),
            ("N(№2-й)", ("input", 2, "", None)), ("№№3", ("input", 3, "", None)), ("#N#3", ("input", 3, "", None)),
            ("##(x)", ("input", None, "##(x)", None)), ("NN", ("input", None, "NN", None)), ("№#", ("input", None, "№#", None)),
            ("##(3x)", ("unparsed", None, None, "n_not_positive_integer")),
            ("\u200b3", ("input", 3, "", None)), ("(\u00ad3)", ("input", 3, "", None)), ("3\u200d лишняя", ("input", 3, "лишняя", None)),   # Cf в лексеме N (раунд 9)
            ("\u200b 3", ("input", 3, "", None)), ("\u200b 3 лишняя", ("input", 3, "лишняя", None)), ("\ufeff\u200b 3", ("input", 3, "", None)),   # фантомная лексема (раунд 10)
        ]
        for tail, want in cases:
            text = (und + " " + tail).rstrip()
            self.assertEqual(one(text), want, text)


    def test_phantom_lexeme_in_start_n_and_last(self):
        """Раунд 10 B, W1/W4: лексема из одних невидимых символов — не лексема; видимая форма N у повтора и списка."""
        st, la = self.P.by_id["start_n"]["token"], self.P.by_id["last"]["token"]
        for arg, want in (("\u200b2", 2), (" \u200b 2", 2), ("2\u200b", 2), ("\ufeff5", 5)):
            r = self.P.parse(upd(st + " " + arg)); self.assertEqual((r["kind"], r.get("n")), ("input", want), repr(arg))
            r = self.P.parse(upd(la + " " + arg)); self.assertEqual((r["kind"], r.get("n")), ("input", want), repr(arg))
        r = self.P.parse(upd(st + " \u200b")); self.assertEqual((r["kind"], r.get("reason")), ("unparsed", "title_empty"))   # ни номера, ни видимого заголовка

if __name__ == "__main__":
    unittest.main()
