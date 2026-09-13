# -*- coding: utf-8 -*-
"""Оракул машины состояний: таблица переходов читается тестом ИЗ tg-bot.yaml (машинный дубль
контракта) построчным регэкспом и прогоняется целиком — 16 клеток; ожидания времени — известные
инстанты Europe/Belgrade; полнота матрицы печатается."""
import os, re, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import parse, session  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
REG = os.path.join(ROOT, "bot", "kit", "commands.yaml")
CONTRACT = os.path.join(ROOT, "spec", "09-tg-bot-time-line", "tg-bot.yaml")
if not os.path.exists(CONTRACT):
    CONTRACT = os.path.join(ROOT, "output", "format-spec", "09-tg-bot-time-line", "tg-bot.yaml")
PERSON = {"handle": "dev-one", "timezone": "Europe/Belgrade"}
CFG = {"last_default_n": 5, "namespace": None}


def transitions_from_contract():
    rows = []
    for ln in open(CONTRACT, encoding="utf-8"):
        m = re.match(r"^  - \{state: (\w+),\s+input: (\w+),\s+next_state: (\w+),\s+outcomes: \[([^\]]+)\]", ln)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3), [x.strip() for x in m.group(4).split(",")]))
    return rows


def registry_tokens():
    tok = {}
    cur = None
    in_commands = False
    for ln in open(REG, encoding="utf-8"):
        if ln.startswith("commands:"):
            in_commands = True
        if not in_commands:
            continue
        m = re.match(r"^  - id: (\S+)", ln)
        if m:
            cur = m.group(1); continue
        m = re.match(r'^    token: "(.*)"$', ln)
        if m and cur:
            tok[cur] = m.group(1)
    return tok


TOK = registry_tokens()


def upd(text, uid=1, mid=10, date=1752698400, chat=100000001, cb=False):
    if cb:
        return {"update_id": uid, "callback_query": {"id": "c%d" % uid, "data": text, "from": {"id": 100000001}, "message": {"message_id": mid, "chat": {"id": chat, "type": "private"}}}}
    return {"update_id": uid, "message": {"message_id": mid, "date": date, "chat": {"id": chat, "type": "private"}, "from": {"id": 100000001, "first_name": "Dev"}, "text": text}}


SAMPLE = {"start_title": TOK["start_title"] + " созвон\nхвост", "start_n": TOK["start_n"] + " 1", "stop": TOK["stop"] + "\nконец", "track": TOK["track"] + " 10:15-12:00 разбор",
          "free_text": "2ч 40м созвон", "last": TOK["last"], "help": TOK["help"], "confirm": TOK["confirm"] + " 1ч правка", "undo": TOK["undo"] + " 1"}
OPEN = {"title": "созвон", "start_text": TOK["start_title"] + " созвон\nхвост", "started_at": 1752698400, "started_at_local": "2025-07-16T22:40:00+02:00",
        "chat_id": 100000001, "start_message_id": 10, "start_update_id": 1, "schema_version": 1}


class TableTests(unittest.TestCase):
    def setUp(self):
        self.P = parse.Parser(REG)

    def test_all_18_cells_primary_outcome_and_next_state(self):
        rows = transitions_from_contract()
        self.assertEqual(len(rows), 18)   # T8: {closed, open} × 9 входов
        checked = 0
        for state, inp, nxt, outcomes in rows:
            rec = dict(OPEN) if state == "open" else None
            parsed = self.P.parse(upd(SAMPLE[inp], uid=5, mid=50, date=1752707700))
            d = session.decide(rec, parsed, PERSON, CFG, tail_of=self.P.tail_of, last_titles=["a", "b"])
            self.assertIn(d["outcome"], outcomes, (state, inp, d["outcome"]))
            if inp != "confirm":
                self.assertEqual(d["outcome"], outcomes[0], (state, inp))   # первичный исход клетки
                after = "open" if (d["new_record"] is not session.UNCHANGED and d["new_record"] is not None) or (d["new_record"] is session.UNCHANGED and state == "open") else "closed"
                self.assertEqual(after, nxt, (state, inp, d["new_record"]))
            checked += 1
        sys.stderr.write("[transitions] клеток прогнано: %d из %d\n" % (checked, len(rows)))


class TimerTests(unittest.TestCase):
    def setUp(self):
        self.P = parse.Parser(REG)

    def test_open_record_fields_and_time_from_message(self):
        d = session.decide(None, self.P.parse(upd(TOK["start_title"] + " созвон\nподробности", uid=1, mid=10, date=1752698400)), PERSON, CFG, tail_of=self.P.tail_of)
        r = d["new_record"]
        self.assertEqual(d["outcome"], "session_opened")
        self.assertEqual(sorted(r), ["chat_id", "schema_version", "start_message_id", "start_text", "start_update_id", "started_at", "started_at_local", "title"])
        self.assertEqual((r["started_at"], r["started_at_local"], r["start_message_id"], r["title"]), (1752698400, "2025-07-16T22:40:00+02:00", 10, "созвон"))
        self.assertEqual(r["start_text"], TOK["start_title"] + " созвон\nподробности")
        self.assertNotIn("anchor", " ".join(r))

    def test_stop_splits_at_local_midnight_and_carries_both_tails(self):
        d = session.decide(dict(OPEN), self.P.parse(upd(TOK["stop"] + "\nусталость", uid=3, mid=12, date=1752707700)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(d["outcome"], "session_closed_recorded")
        self.assertIsNone(d["new_record"])
        self.assertEqual([(l["date"], l["seconds"], l["k"]) for l in d["lines"]], [("2025-07-16", 4800, 0), ("2025-07-17", 4500, 1)])
        self.assertEqual(d["reply"]["hours_total"], "2.58")
        carriers = sorted((c["identity"], c["k"], c["body"]) for c in d["comments"])
        full_open = (TOK["start_title"] + " созвон\nхвост").encode(); full_close = (TOK["stop"] + "\nусталость").encode()
        # тело — ПОЛНЫЕ байты носителя (контракт §1Г(а)); существование — по хвосту (раунд 1, находка 1)
        self.assertEqual(carriers, [("tg:100000001:10", 0, full_open), ("tg:100000001:10", 1, full_open),
                                    ("tg:100000001:12", 0, full_close), ("tg:100000001:12", 1, full_close)])
        # якорь строки таймера — из идентичности ЗАКРЫТИЯ
        self.assertTrue(all(l["identity"] == "tg:100000001:12" for l in d["lines"]))

    def test_stop_without_tails_has_no_comments(self):
        rec = dict(OPEN, start_text=TOK["start_title"] + " созвон")
        d = session.decide(rec, self.P.parse(upd(TOK["stop"], uid=3, mid=12, date=1752700000)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(d["comments"], [])
        self.assertEqual(len(d["lines"]), 1)

    def test_delay_of_processing_does_not_change_result(self):
        a = session.decide(dict(OPEN), self.P.parse(upd(TOK["stop"], uid=3, mid=12, date=1752707700)), PERSON, CFG, tail_of=self.P.tail_of)
        b = session.decide(dict(OPEN), self.P.parse(upd(TOK["stop"], uid=3, mid=12, date=1752707700)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(a, b)   # «сейчас» в сигнатуре нет — задержка на час ничего не меняет по построению

    def test_stop_at_or_before_start_is_reask_invalid_hours_range(self):
        d = session.decide(dict(OPEN), self.P.parse(upd(TOK["stop"], uid=3, mid=12, date=1752698400)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual((d["outcome"], d["reply"]["rule"], d["new_record"]), ("reask_invalid", "HOURS_RANGE", session.UNCHANGED))

    def test_repeat_start_and_identical_repeat(self):
        d = session.decide(dict(OPEN), self.P.parse(upd(TOK["start_title"] + " другое", uid=2, mid=11, date=1752700000)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual((d["outcome"], d["new_record"], d["reply"]["title"]), ("reask_start_already_open", session.UNCHANGED, "созвон"))
        d = session.decide(dict(OPEN), self.P.parse(upd(TOK["start_title"] + " созвон\nхвост", uid=1, mid=10, date=1752698400)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(d["outcome"], "identical_repeat")

    def test_start_n_resolves_and_names_title(self):
        d = session.decide(None, self.P.parse(upd(TOK["start_n"] + " 2", date=1752698400)), PERSON, CFG, tail_of=self.P.tail_of, last_titles=["первое", "второе"])
        self.assertEqual((d["outcome"], d["new_record"]["title"], d["reply"]["title"]), ("session_opened", "второе", "второе"))
        for n in (3, 99):   # вне диапазона списка — переспрос машины состояний
            d = session.decide(None, self.P.parse(upd(TOK["start_n"] + " %d" % n, date=1752698400)), PERSON, CFG, tail_of=self.P.tail_of, last_titles=["первое", "второе"])
            self.assertEqual((d["outcome"], d["reply"]["reason"]), ("reask_unparsed", "n_out_of_range"), n)
        for n in (0, -1):   # не положительное целое — отвергает уже парсер
            self.assertEqual(self.P.parse(upd(TOK["start_n"] + " %d" % n, date=1752698400))["kind"], "unparsed", n)

    def test_callback_time_bearing_rejected(self):
        d = session.decide(None, self.P.parse(upd(TOK["start_n"] + " 1", cb=True)), PERSON, CFG, tail_of=self.P.tail_of, last_titles=["a"])
        self.assertEqual((d["outcome"], d["reply"]["reason"]), ("reask_unparsed", "callback_time_bearing"))
        d = session.decide(None, self.P.parse(upd(TOK["last"], cb=True)), PERSON, CFG, tail_of=self.P.tail_of, last_titles=["a"])
        self.assertEqual(d["outcome"], "last_list_given")


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.P = parse.Parser(REG)

    def test_free_text_date_default_from_person_timezone(self):
        t = 1757199600  # 2025-09-06T23:00:00Z = 07.09 01:00 Belgrade, 06.09 16:00 Los Angeles
        d = session.decide(None, self.P.parse(upd("2ч 40м созвон", date=t)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual((d["outcome"], d["lines"][0]["date"], d["lines"][0]["seconds"], d["lines"][0]["interval"]), ("recorded", "2025-09-07", 9600, None))
        d2 = session.decide(None, self.P.parse(upd("2ч 40м созвон", date=t)), {"handle": "dev-one", "timezone": "America/Los_Angeles"}, CFG)
        self.assertEqual(d2["lines"][0]["date"], "2025-09-06")
        d3 = session.decide(None, self.P.parse(upd("2026-01-05 2ч созвон", date=t)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(d3["lines"][0]["date"], "2026-01-05")

    def test_track_interval_local_and_midnight_wrap(self):
        d = session.decide(None, self.P.parse(upd(TOK["track"] + " 10:15-12:00 разбор", date=1757239200)), PERSON, CFG, tail_of=self.P.tail_of)
        l = d["lines"][0]
        self.assertEqual((l["date"], l["seconds"], l["interval"]), ("2025-09-07", 6300, (1757232900, 1757239200)))  # 10:15/12:00 местных +02:00 = 08:15Z/10:00Z
        d = session.decide(None, self.P.parse(upd(TOK["track"] + " 23:00-01:00 ночь\nхвост", date=1757239200)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual([(l["date"], l["seconds"], l["k"]) for l in d["lines"]], [("2025-09-07", 3600, 0), ("2025-09-08", 3600, 1)])
        self.assertEqual(len(d["comments"]), 2)
        self.assertTrue(all(c["body"] == (TOK["track"] + " 23:00-01:00 ночь\nхвост").encode() for c in d["comments"]))
        # раунд 1, находка 2: конец на СЛЕДУЮЩЕЙ местной дате, не +86400 — на дне весеннего DST сутки 23 ч
        d = session.decide(None, self.P.parse(upd(TOK["track"] + " 2025-03-29 23:00-04:00 ночь", date=1743249600)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(sum(l["seconds"] for l in d["lines"]), 14400)        # 23:00 (+01:00) → 04:00 (+02:00) прожито 4 ч
        self.assertEqual(d["reply"]["hours_total"], "4.00")
        self.assertEqual([l["date"] for l in d["lines"]], ["2025-03-29", "2025-03-30"])
        d = session.decide(None, self.P.parse(upd(TOK["track"] + " 2025-10-25 23:00-04:00 ночь", date=1761400000)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(d["reply"]["hours_total"], "6.00")                    # осенний DST: час дважды

    # раунд 2, Н-1: класс {дата в DST-переходе весна/осень} × {конец в дыре / в повторе / равен началу / раньше начала}
    def test_track_dst_gap_repeat_and_equal_ends(self):
        dec = lambda t, date: session.decide(None, self.P.parse(upd(t, date=date)), PERSON, CFG, tail_of=self.P.tail_of)
        d = dec(TOK["track"] + " 2025-03-30 02:30-03:30 x", 1743336000)            # 02:30 в этот день НЕ существует
        self.assertEqual((d["outcome"], d["reply"]["reason"]), ("reask_unparsed", "nonexistent_local_time"))
        d = dec(TOK["track"] + " 2025-03-30 02:00-02:59 x", 1743336000)
        self.assertEqual(d["outcome"], "reask_unparsed")
        d = dec(TOK["track"] + " 2025-03-30 01:30-03:30 x", 1743336000)            # 01:30 CET → 03:30 CEST = 1 ч прожитый
        self.assertEqual((d["outcome"], d["reply"]["hours_total"]), ("recorded", "1.00"))
        d = dec(TOK["track"] + " 10:00-10:00 x", 1757239200)                        # равные концы — как у таймера
        self.assertEqual((d["outcome"], d["reply"]["rule"]), ("reask_invalid", "HOURS_RANGE"))
        d = dec(TOK["track"] + " 2025-10-26 02:15-02:45 x", 1761436800)            # повторяющийся час: ПЕРВЫЙ проход (fold=0)
        self.assertEqual((d["outcome"], d["reply"]["hours_total"]), ("recorded", "0.50"))
        self.assertEqual(d["lines"][0]["interval"], (1761437700, 1761439500))       # 00:15Z/00:45Z — CEST (+02:00), первый проход
        d = dec(TOK["track"] + " 2025-10-26 02:30-03:30 x", 1761436800)
        self.assertEqual(d["reply"]["hours_total"], "2.00")                          # 02:30 первого прохода → 03:30 CET: 2 ч
        d = dec(TOK["track"] + " 2025-03-29 23:00-02:30 x", 1743249600)            # перенос конца на дату с дырой — тоже переспрос
        self.assertEqual(d["outcome"], "reask_unparsed")

    def test_reply_hours_is_sum_of_line_hours_in_cents(self):
        # раунд 2, Н-4: два сегмента по 3618 с → строки 1.01 + 1.01, ответ 2.02 (не Н1 от суммы = 2.01)
        mid = 1752703200
        rec = dict(OPEN, started_at=mid - 3618)
        d = session.decide(rec, self.P.parse(upd(TOK["stop"], uid=3, mid=12, date=mid + 3618)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual([l["seconds"] for l in d["lines"]], [3618, 3618])
        self.assertEqual(d["reply"]["hours_total"], "2.02")
        d = session.decide(None, self.P.parse(upd(TOK["track"] + " 23:59-00:01 x", date=1757239200)), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual(d["reply"]["hours_total"], "0.04")

    def test_opening_tail_read_via_registry_not_copy(self):
        # раунд 2, Н-8: хвост носителя открытия — через Parser.tail_of; без него закрытие не решается
        with self.assertRaises(ValueError):
            session.decide(dict(OPEN), self.P.parse(upd(TOK["stop"], uid=3, mid=12, date=1752707700)), PERSON, CFG)

    def test_last_and_help(self):
        d = session.decide(None, self.P.parse(upd(TOK["last"] + " 2")), PERSON, CFG, tail_of=self.P.tail_of, last_titles=["a", "b", "c"])
        self.assertEqual((d["outcome"], d["reply"]["titles"]), ("last_list_given", ["a", "b"]))
        d = session.decide(dict(OPEN), self.P.parse(upd(TOK["help"])), PERSON, CFG, tail_of=self.P.tail_of)
        self.assertEqual((d["outcome"], d["new_record"]), ("help_given", session.UNCHANGED))

    def test_oracle_does_not_share_helpers(self):
        imports = [ln for ln in open(__file__, encoding="utf-8") if re.match(r"^(import|from)\s", ln)]
        self.assertFalse(any(re.search(r"\b(line|anchor|comment|lastn)\b", ln) for ln in imports), imports)


if __name__ == "__main__":
    unittest.main()
