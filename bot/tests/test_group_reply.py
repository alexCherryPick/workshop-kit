# -*- coding: utf-8 -*-
"""А6 (ЭРРАТА D10 «А»; контракт §1В(а), §1 №исход-4, №исход-9): в группе privacy-mode доставляет боту только команды
и ОТВЕТЫ (reply) на его сообщения — ответ боту адресован: неразобранный ответ получает переспрос (исход 4), а не
тишину исхода 9. Матрица ПАКЕТОМ на стенде T3 (поллер целиком): группа × {ответ боту разобранный, ответ боту
неразобранный, ответ боту-исправление, ответ человеку (разобранный/нет), ответ чужому боту, корень топика, `@бот` без
ответа, реплика без `/`, команда, команда с ошибкой} + личка + незнакомый отправитель. Ожидания — из контракта, тексты
и токены — из реестров построчным чтением (литералов команд нет)."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import botrepo  # noqa: E402
from botrepo import Stand, FakeTransport, msg, TOK, UNKNOWN_ID, CHAT  # noqa: E402
import yamlmini, poll  # noqa: E402

BOT_ID = 999000001
BOT_NAME = "cp_workshop_test_bot"
ME = {"id": BOT_ID, "is_bot": True, "first_name": "B", "username": BOT_NAME}
HUMAN = {"id": 100000003, "is_bot": False, "first_name": "H"}
OTHER_BOT = {"id": BOT_ID + 7, "is_bot": True, "first_name": "O", "username": "otherbot"}
MACHINE_NAME = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
REPLY_MAX = 160                                  # контракт §1 №исход-4 (бюджет v8)


def first_correction_example():
    path = os.path.join(botrepo.BOT, "kit", "duration-forms.yaml")
    lines = open(path, encoding="utf-8").read().split("\n")
    i = lines.index("correction_examples:")
    return re.match(r'^  - "(.*)"$', lines[i + 1]).group(1)


def dated_track_example():
    cur = None
    for ln in open(os.path.join(botrepo.BOT, "kit", "commands.yaml"), encoding="utf-8"):
        m = re.match(r"^  - id: (\S+)", ln)
        if m:
            cur = m.group(1)
        m = re.match(r'^    example_dated: "(.*)"$', ln)
        if m and TOK.get(cur) == TOK["track"]:
            return m.group(1)
    raise AssertionError("в реестре нет примера track с датой")


def reply_to(u, frm, extra=None):
    rt = {"message_id": 1, "date": u["message"]["date"] - 60, "chat": dict(u["message"]["chat"]), "text": "x", "from": frm}
    rt.update(extra or {})
    u["message"]["reply_to_message"] = rt
    return u


class GroupReplyMatrix(unittest.TestCase):
    def setUp(self):
        self.s = Stand()
        self.cfg = yamlmini.load_file(os.path.join(self.s.root, ".workshop", "bot.yaml"))

    def tearDown(self):
        self.s.close()

    def run_one(self, u, cfg=None, bot_id=BOT_ID):
        t = FakeTransport([u])
        ctx = poll.Ctx(self.s.root, t, cfg or self.cfg, botrepo.VALIDATOR, bot_username=BOT_NAME, bot_id=bot_id, sleeper=lambda x: None)
        r = poll.run_once(ctx)
        return r["outcomes"][-1][1], [x[1] for x in t.sent], ctx

    def short_ok(self, text):
        return (len(text.splitlines()) == 1 and len(text) <= REPLY_MAX and TOK["help"] in text
                and not MACHINE_NAME.search(text))

    def test_a6_matrix_batch(self):
        T = 1788790990
        corr = first_correction_example()
        g = dict(chat_type="supergroup", chat_id=CHAT)
        cases = [
            # (клетка, update, ожидаемый исход, ответ: None — ответа нет, "short" — одна строка переспроса, "any" — есть)
            ("группа · ответ боту · разобран", reply_to(msg("2ч созвон по ответу", date=T + 1, **g), ME), "recorded", "any"),
            ("группа · ответ боту · не разобран", reply_to(msg("просто текст", date=T + 2, **g), ME), "reask_unparsed", "short"),
            ("группа · ответ боту · исправление", reply_to(msg(corr, date=T + 3, **g), ME), "reask_correction", "short"),
            ("группа · ответ человеку · не разобран", reply_to(msg("просто текст", date=T + 4, **g), HUMAN), "non_input", None),
            ("группа · ответ человеку · разобран", reply_to(msg("45м ревью по ответу", date=T + 5, **g), HUMAN), "recorded", "any"),
            ("группа · ответ чужому боту · не разобран", reply_to(msg("просто текст", date=T + 6, **g), OTHER_BOT), "non_input", None),
            # L-01: чужой бот, чей id оканчивается нашим (2999000001 против 999000001), — не «свой»: тишина исхода 9
            ("группа · ответ боту с id-суффиксом своего · не разобран", reply_to(msg("просто текст", date=T + 14, **g), dict(OTHER_BOT, id=int("2" + str(BOT_ID)))), "non_input", None),
            ("группа · корень топика (бот) · не разобран", reply_to(msg("просто текст", date=T + 7, **g), ME, {"forum_topic_created": {"name": "t"}}), "non_input", None),
            ("группа · @бот без ответа · не разобран", msg("@%s просто текст" % BOT_NAME, date=T + 8, **g), "reask_unparsed", "short"),
            ("группа · реплика без / · не разобрана", msg("просто текст", date=T + 9, **g), "non_input", None),
            ("группа · команда", msg(TOK["last"], date=T + 10, **g), "last_list_given", "any"),
            ("группа · команда с ошибкой", msg(TOK["last"] + " 0", date=T + 11, **g), "reask_unparsed", "short"),
            ("личка · не разобрано", msg("просто текст", date=T + 12, chat_type="private", chat_id=botrepo.ADMIN_ID), "reask_unparsed", "short"),
        ]
        rows = []
        for name, u, want, reply in cases:
            got, sent, _ = self.run_one(u)
            ok = got == want and ((reply is None and not sent) or (reply == "any" and len(sent) == 1)
                                  or (reply == "short" and len(sent) == 1 and self.short_ok(sent[0])))
            rows.append("  %s  %-46s → %-18s %s" % ("PASS" if ok else "FAIL", name, got, repr(sent[0][:90]) if sent else "(ответа нет)"))
        # имя бота известно, id нет (ответ getMe без id) — ответ боту распознаётся по имени среди ботов
        got, sent, _ = self.run_one(reply_to(msg("просто текст", date=T + 13, **g), ME), bot_id=None)
        ok = got == "reask_unparsed" and len(sent) == 1 and self.short_ok(sent[0])
        rows.append("  %s  %-46s → %-18s %s" % ("PASS" if ok else "FAIL", "группа · ответ боту (id неизвестен, имя) · не разобран", got, repr(sent[0][:90]) if sent else "(ответа нет)"))
        sys.stderr.write("\n[А6 матрица поллера] %d:\n%s\n" % (len(rows), "\n".join(rows)))
        self.assertFalse([r for r in rows if r.startswith("  FAIL")], "\n".join(rows))

    def test_unknown_sender_reply_to_bot_is_addressed(self):
        """Исход 7 (self_registration: off): ответ боту незнакомца — адресован (ответ «тебя нет в карте людей»);
        неадресованная реплика незнакомца в группе — отклонена молча (прежняя клетка)."""
        cfg = dict(self.cfg); cfg["self_registration"] = "off"
        got, sent, _ = self.run_one(reply_to(msg("2ч работа", from_id=UNKNOWN_ID, date=1788791100), ME), cfg=cfg)
        self.assertEqual((got, len(sent)), ("rejected_unknown_sender", 1))
        got, sent, _ = self.run_one(msg("2ч работа", from_id=UNKNOWN_ID, date=1788791200), cfg=cfg)
        self.assertEqual((got, len(sent)), ("rejected_unknown_sender", 0))

    def test_claim_snapshot_track_dotted_date_in_private(self):
        """Снимок заявки В2 сквозь поллер: `<track> 20.09 1.5 часа тест` → переспрос человеческой фразой с примером
        записи за прошлый день; машинного имени причины в ответе нет, в трассе — есть."""
        got, sent, ctx = self.run_one(msg(TOK["track"] + " 20.09 1.5 часа тест", date=1788791300, chat_type="private", chat_id=botrepo.ADMIN_ID))
        self.assertEqual((got, len(sent)), ("reask_unparsed", 1))
        self.assertTrue(self.short_ok(sent[0]), sent[0])
        self.assertIn(dated_track_example(), sent[0])
        notes = [o["note"] for o in ctx.trace.ops if o["op"] == "reask_reason"]
        self.assertEqual(len(notes), 1)
        self.assertTrue(MACHINE_NAME.fullmatch(notes[0]), notes)
        self.assertNotIn(notes[0], sent[0])


if __name__ == "__main__":
    unittest.main()
