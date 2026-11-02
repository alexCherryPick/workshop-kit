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

    def test_registry_positions_unique_and_parser_reads_all(self):
        # D15: число позиций — свойство реестра (было «ровно 9» — ручной счётчик); инварианты: непуст, id уникальны,
        # парсер знает ровно множество реестра
        ids = [r["id"] for r in self.rows]
        self.assertTrue(ids); self.assertEqual(len(ids), len(set(ids)))
        ids = set(ids)
        self.assertEqual(set(self.P.by_id), ids)
        for r in self.rows:
            self.assertEqual(self.P.by_id[r["id"]]["tail_rule"], r["tail_rule"])

    def test_every_position_reachable(self):
        samples = {"start_title": TOK["start_title"] + " созвон", "start_n": TOK["start_n"] + " 2", "stop": TOK["stop"], "track": TOK["track"] + " 10:15-12:00 разбор",
                   "free_text": "2ч 40м созвон", "last": TOK["last"], "help": TOK["help"], "confirm": TOK["confirm"] + " 1ч правка",
                   "undo": TOK["undo"] + " 1", "summary": TOK["summary"] + " team 2"}
        self.assertEqual(set(samples), {r["id"] for r in self.rows})   # каждая позиция реестра достижима образцом
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
        for bad in ("просто текст", TOK["track"] + " разбор без интервала", TOK["track"] + " 25:00-26:00 x", TOK["start_n"] + " 0", TOK["start_n"] + " -1", TOK["last"] + " много", "/nope", TOK["confirm"]):
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


    def test_stop_optional_clock_time_and_tail(self):
        """REQ-104: первая лексема аргумента закрытия в форме ЧЧ:ММ — время конца; хвост начинается ПОСЛЕ неё."""
        st = self.P.by_id["stop"]["token"]
        r = self.P.parse(upd(st)); self.assertEqual((r["kind"], r.get("stop_time"), r["tail"]), ("input", None, b""))
        r = self.P.parse(upd(st + " 18:30")); self.assertEqual((r["kind"], r["stop_time"], r["tail"]), ("input", (18, 30), b""))
        r = self.P.parse(upd(st + " 18:30 конец дня\nи ниже")); self.assertEqual((r["stop_time"], r["tail"]), ((18, 30), "конец дня\nи ниже".encode("utf-8")))
        r = self.P.parse(upd(st + " 18:30\nниже")); self.assertEqual((r["stop_time"], r["tail"]), ((18, 30), "ниже".encode("utf-8")))
        r = self.P.parse(upd(st + " 24:00")); self.assertEqual(r["stop_time"], (24, 0))
        r = self.P.parse(upd(st + " 24:30")); self.assertEqual((r["kind"], r["reason"]), ("unparsed", "stop_time_not_clock"))
        for bad in ("25:00", "18:75", "18:3", "18:30:00", "18.30", "7:5", "18:30-19:00", "1.5", "15.09.2026", "12345:30", "000018:30"):   # начинается как время, но не время — переспрос, не хвост (без предела длины)
            r = self.P.parse(upd(st + " " + bad + " хвост")); self.assertEqual((r["kind"], r.get("reason")), ("unparsed", "stop_time_not_clock"), bad)
        for wrapped in ("18:30,", "18:30;", "(18:30)", "«18:30»", "18:30!", "18:30.", "18:30–"):    # обёртки и хвостовая пунктуация (и тире) — снимаются, время читается
            r = self.P.parse(upd(st + " " + wrapped + " устал")); self.assertEqual((r["kind"], r.get("stop_time"), r["tail"]), ("input", (18, 30), "устал".encode("utf-8")), wrapped)
        for tail in ("3 звонка", "25", "v2", "2026-09-15", "1830", "500 слов", "2025 план"):       # не начинается как время — хвост как прежде
            r = self.P.parse(upd(st + " " + tail)); self.assertEqual((r["kind"], r.get("stop_time")), ("input", None), tail)
        r = self.P.parse(upd(st + " конец")); self.assertEqual((r["kind"], r.get("stop_time"), r["tail"]), ("input", None, "конец".encode("utf-8")))   # не время — хвост как прежде
        r = self.P.parse(upd(st + " 9:05")); self.assertEqual(r["stop_time"], (9, 5))
        r = self.P.parse(upd(st + " \u200b18:30")); self.assertEqual(r["stop_time"], (18, 30))          # невидимые символы — не лексема

    def test_track_n_instead_of_title(self):
        """REQ-105: единственная лексема после интервала, похожая на номер, — номер из списка последних."""
        tr = self.P.by_id["track"]["token"]
        r = self.P.parse(upd(tr + " 10:00-12:00 2")); self.assertEqual((r["kind"], r["n"], r["title"]), ("input", 2, ""))
        r = self.P.parse(upd(tr + " 2026-09-15 10:00-12:00 №3")); self.assertEqual((r["n"], r["date"]), (3, "2026-09-15"))
        r = self.P.parse(upd(tr + " 10:00-12:00 2 созвона")); self.assertEqual((r["n"], r["title"]), (None, "2 созвона"))   # две лексемы — заголовок
        r = self.P.parse(upd(tr + " 10:00-12:00 0")); self.assertEqual((r["kind"], r["reason"]), ("unparsed", "n_not_positive_integer"))
        r = self.P.parse(upd(tr + " 10:00-12:00 ревью")); self.assertEqual((r["n"], r["title"]), (None, "ревью"))

    def test_phantom_lexeme_in_start_n_and_last(self):
        """Раунд 10 B, W1/W4: лексема из одних невидимых символов — не лексема; видимая форма N у повтора и списка."""
        st, la = self.P.by_id["start_n"]["token"], self.P.by_id["last"]["token"]
        for arg, want in (("\u200b2", 2), (" \u200b 2", 2), ("2\u200b", 2), ("\ufeff5", 5)):
            r = self.P.parse(upd(st + " " + arg)); self.assertEqual((r["kind"], r.get("n")), ("input", want), repr(arg))
            r = self.P.parse(upd(la + " " + arg)); self.assertEqual((r["kind"], r.get("n")), ("input", want), repr(arg))
        r = self.P.parse(upd(st + " \u200b")); self.assertEqual((r["kind"], r["position"]), ("input", "help"))   # пустой заголовок = кнопка Start → справка

    def test_bare_start_is_help_not_reask(self):
        """alex 2026-09-19: голый токен открытия (кнопка Start мессенджера) — справка, не «не понял»."""
        st = self.P.by_id["start_title"]["token"]
        for text in (st, st + " ", st + "\n", "@cp_workshop_test_bot " + st):
            r = self.P.parse(upd(text)); self.assertEqual((r["kind"], r["position"]), ("input", "help"), repr(text))
        r = self.P.parse(upd(st + " созвон")); self.assertEqual(r["position"], "start_title")   # ни номера, ни видимого заголовка

def registry_examples():
    """[(id, поле, пример)] — поля example / example_dated позиций реестра построчно (ЭРРАТА D10 «А», Б2) и префикс
    подтверждения; литералов примеров в тесте нет."""
    out, cur, inside, confirm = [], None, False, None
    for ln in open(REG, encoding="utf-8"):
        m = re.match(r'^confirm_prefix: "(.*)"$', ln)
        if m:
            confirm = m.group(1)
        if ln.startswith("commands:"):
            inside = True
        if not inside:
            continue
        m = re.match(r"^  - id: (\S+)", ln)
        if m:
            cur = m.group(1); continue
        m = re.match(r'^    (example|example_dated): "(.*)"$', ln)
        if m and cur:
            out.append((cur, m.group(1), m.group(2)))
    return out, confirm


class RegistryExampleTests(unittest.TestCase):
    """Б2: КАЖДЫЙ пример позиции реестра разбирается в СВОЮ позицию (пример подтверждения — обёрткой своей позиции);
    пример с явной датой — ровно в эту дату. Иначе справка учит вводу, которого бот не примет."""

    def test_every_registry_example_parses_into_its_position(self):
        P = parse.Parser(REG, bot_username="cp_workshop_test_bot")
        rows, confirm = registry_examples()
        self.assertTrue(any(f == "example_dated" for _, f, _ in rows), "в реестре нет ни одного примера задним числом")
        seen = set()
        for pid, field, ex in rows:
            r = P.parse(upd(ex))
            got = r.get("wrapped_by") if TOK.get(pid) == confirm else r.get("position")
            self.assertEqual((r["kind"], got), ("input", pid), "%s.%s %r → %s" % (pid, field, ex, r.get("reason")))
            dm = re.search(r"(?:^|\s)(\d{4}-\d{2}-\d{2})(?:\s|$)", ex)
            self.assertEqual(r.get("date"), dm.group(1) if dm else None, "%s.%s: дата примера" % (pid, field))
            if field == "example_dated":
                self.assertIsNotNone(dm, "%s.example_dated без явной даты" % pid)
            seen.add(pid)
        self.assertEqual(seen, set(r["id"] for r in registry_rows()), "у позиции нет примера")


class ReplyToBotTests(unittest.TestCase):
    """А6: ответ (reply) на сообщение САМОГО бота — адресован (как обращение `@бот`); ответ человеку, чужому боту,
    корневому служебному сообщению топика — нет. Матрица пакетом: {id известен, только имя, ничего} × автор ответа."""
    BOT_ID = 999000001

    def upd_reply(self, text, rt_from, extra=None):
        u = upd(text, chat=-1001, ctype="supergroup")
        rt = {"message_id": 5, "date": 1, "chat": {"id": -1001, "type": "supergroup"}, "text": "x"}
        if rt_from is not None:
            rt["from"] = rt_from
        rt.update(extra or {})
        u["message"]["reply_to_message"] = rt
        return u

    def test_reply_to_bot_matrix(self):
        me = {"id": self.BOT_ID, "is_bot": True, "first_name": "B", "username": "cp_workshop_test_bot"}
        other_bot = {"id": self.BOT_ID + 1, "is_bot": True, "first_name": "O", "username": "otherbot"}
        human = {"id": 100000003, "is_bot": False, "first_name": "H", "username": "cp_workshop_test_bot"}
        spoof = {"id": self.BOT_ID + 2, "is_bot": True, "first_name": "S", "username": "cp_workshop_test_bot"}
        by_id = parse.Parser(REG, bot_username="cp_workshop_test_bot", bot_id=self.BOT_ID)
        by_name = parse.Parser(REG, bot_username="cp_workshop_test_bot")
        blind = parse.Parser(REG)
        cases = [
            ("id: ответ боту, текст не разобран", by_id, self.upd_reply("просто текст", me), ("unparsed", True, True)),
            ("id: ответ боту, свободная строка", by_id, self.upd_reply("2ч созвон", me), ("input", True, True)),
            ("id: ответ боту, команда", by_id, self.upd_reply(TOK["last"], me), ("input", True, True)),
            ("id: ответ боту с тем же именем, но другим id", by_id, self.upd_reply("просто текст", spoof), ("unparsed", False, False)),
            ("id: ответ чужому боту", by_id, self.upd_reply("просто текст", other_bot), ("unparsed", False, False)),
            ("id: ответ человеку", by_id, self.upd_reply("просто текст", human), ("unparsed", False, False)),
            ("id: корень топика форум-группы от бота", by_id, self.upd_reply("просто текст", me, {"forum_topic_created": {"name": "t"}}), ("unparsed", False, False)),
            ("id: ответ без автора", by_id, self.upd_reply("просто текст", None), ("unparsed", False, False)),
            ("id: без ответа", by_id, upd("просто текст", chat=-1001, ctype="supergroup"), ("unparsed", False, False)),
            ("id: bool вместо id", parse.Parser(REG, bot_id=True), self.upd_reply("просто текст", dict(me, id=True)), ("unparsed", False, False)),
            # L-01 (адверсарий R1): идентичность — ТОЧНОЕ равенство целых; свой id не суффикс, не префикс, не подстрока,
            # не строка и не модуль чужого (чужой бот с чужим именем, чтобы клетку не закрыл запасной путь по имени)
            ("id: чужой id с нашим суффиксом (2999000001)", by_id, self.upd_reply("просто текст", dict(other_bot, id=int("2" + str(self.BOT_ID)))), ("unparsed", False, False)),
            ("id: чужой id с нашим префиксом (9990000017)", by_id, self.upd_reply("просто текст", dict(other_bot, id=int(str(self.BOT_ID) + "7"))), ("unparsed", False, False)),
            ("id: чужой id — наш без последней цифры", by_id, self.upd_reply("просто текст", dict(other_bot, id=int(str(self.BOT_ID)[:-1]))), ("unparsed", False, False)),
            ("id: наш id строкой", by_id, self.upd_reply("просто текст", dict(other_bot, id=str(self.BOT_ID))), ("unparsed", False, False)),
            ("id: наш id со знаком минус", by_id, self.upd_reply("просто текст", dict(other_bot, id=-self.BOT_ID)), ("unparsed", False, False)),
            ("id: наш id дробным числом", by_id, self.upd_reply("просто текст", dict(other_bot, id=float(self.BOT_ID))), ("unparsed", False, False)),
            ("имя: ответ боту", by_name, self.upd_reply("просто текст", me), ("unparsed", True, True)),
            ("имя: регистр имени", by_name, self.upd_reply("просто текст", dict(me, username="CP_Workshop_Test_Bot")), ("unparsed", True, True)),
            ("имя: человек с тем же именем", by_name, self.upd_reply("просто текст", human), ("unparsed", False, False)),
            ("имя: чужой бот", by_name, self.upd_reply("просто текст", other_bot), ("unparsed", False, False)),
            ("ничего не известно: ответ боту", blind, self.upd_reply("просто текст", me), ("unparsed", False, False)),
            ("обращение @бот без ответа (прежняя клетка)", by_id, upd("@cp_workshop_test_bot просто текст", chat=-1001, ctype="supergroup"), ("unparsed", True, False)),
        ]
        rows = []
        for name, P, u, want in cases:
            r = P.parse(u)
            got = (r["kind"], bool(r.get("addressed")), bool(r.get("reply_to_bot")))
            rows.append("  %s  %-45s → %s" % ("PASS" if got == want else "FAIL", name, got))
            self.assertEqual(got, want, name)
        sys.stderr.write("\n[А6 разбор] %d:\n%s\n" % (len(rows), "\n".join(rows)))


if __name__ == "__main__":
    unittest.main()
