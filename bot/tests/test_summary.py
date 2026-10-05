# -*- coding: utf-8 -*-
"""Оракул команды сводки (D15 T3): позиция summary `[team] [N|all]` на стенде поллера (botrepo: origin + клон + фейковый
транспорт + настоящий валидатор). Ожидания — из байтов файлов и отправленных частей, не из функций aggregation.
Покрытие: оба состояния учёта; личный/группа/топик; незнакомый при on/off; alias; смена месяца/года; задержка
обработки; кнопка; подтверждение; ошибка чтения (IO → tool_failure, hold, алярм); неизменность первички."""
import hashlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BOT); sys.path.insert(0, os.path.join(BOT, "kit")); sys.path.insert(0, HERE)
import botrepo  # noqa: E402
from botrepo import Stand, FakeTransport, msg, callback, git, TOK, ADMIN_ID, DEV3_ID, UNKNOWN_ID, CHAT  # noqa: E402
import poll, yamlmini  # noqa: E402

SUM = TOK["summary"]
T0 = 1789639200          # 2026-09-20T10:00:00Z (dev-one: Europe/Belgrade)


def sha_tree(root):
    out = {}
    for rel in ("time", ".workshop/people.yaml", ".workshop/bot-sessions.yaml"):
        p = os.path.join(root, rel)
        if os.path.isdir(p):
            for dp, dn, fn in os.walk(p):
                for f in sorted(fn):
                    q = os.path.join(dp, f); out[os.path.relpath(q, root)] = hashlib.sha256(open(q, "rb").read()).hexdigest()
        elif os.path.exists(p):
            out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.s = Stand()
        self.cfg = yamlmini.load_file(os.path.join(self.s.root, ".workshop", "bot.yaml"))

    def tearDown(self):
        self.s.close()

    def run_poll(self, updates, validator=None):
        t = FakeTransport(updates)
        ctx = poll.Ctx(self.s.root, t, self.cfg, validator or botrepo.VALIDATOR, bot_username="cp_workshop_test_bot", sleeper=lambda x: None)
        return poll.run_once(ctx), t, ctx

    def seed(self):
        """Записи через сам бот: dev-one — 2ч за 2026-09-20 и 1ч за 2026-08-15 (задним числом); dev-three — 3ч за 2026-09-19."""
        r, t, _ = self.run_poll([msg("2ч работа", date=T0), msg(TOK["track"] + " 2026-08-15 10:00-11:00 август", date=T0 + 60),
                                 msg("3ч чужая", from_id=DEV3_ID, date=T0 - 86400)])
        self.assertEqual([o[1] for o in r["outcomes"]], ["recorded", "recorded", "recorded"])
        return sha_tree(self.s.root)

    def last_text(self, t):
        return t.sent[-1][1]

    # --- уровни и периоды
    def test_me_current_month_and_previous_and_all(self):
        before = self.seed()
        r, t, _ = self.run_poll([msg(SUM, date=T0 + 120)])
        self.assertEqual(r["outcomes"][-1][1], "summary_given")
        self.assertEqual(self.last_text(t), "мои часы за 2026-09\n2026-09 — 2.00 ч")
        r, t, _ = self.run_poll([msg(SUM + " 1", date=T0 + 180)])
        self.assertEqual(self.last_text(t), "мои часы за 2026-08\n2026-08 — 1.00 ч")
        r, t, _ = self.run_poll([msg(SUM + " 3", date=T0 + 240)])
        self.assertEqual(self.last_text(t), "мои часы за 2026-06…2026-08\n2026-08 — 1.00 ч")   # пустые месяцы не печатаются
        r, t, _ = self.run_poll([msg(SUM + " all", date=T0 + 300)])
        self.assertEqual(self.last_text(t), "мои часы за 2026-08…2026-09\n2026-08 — 1.00 ч\n2026-09 — 2.00 ч")
        self.assertEqual(sha_tree(self.s.root), before)      # первичка, карта и учёт не тронуты
        self.assertEqual(git(self.s.root, "status", "--porcelain"), "")

    def test_team_forms(self):
        # амендмент §4.4 (summary-month, 2026-10-03): группировка по месяцу + «всего»; один месяц — итог в первой строке
        self.seed()
        cases = [(" team", ("2026-09", "2026-09"), "команда за 2026-09 — всего 5.00 ч\ndev-one — 2.00 ч\ndev-three — 3.00 ч"),
                 (" team 1", ("2026-08", "2026-08"), "команда за 2026-08 — всего 1.00 ч\ndev-one — 1.00 ч"),
                 (" team 3", ("2026-06", "2026-08"), "команда за 2026-06…2026-08\n\n2026-08 — всего 1.00 ч\ndev-one — 1.00 ч"),
                 (" team all", None, "команда за 2026-08…2026-09\n\n2026-08 — всего 1.00 ч\ndev-one — 1.00 ч\n\n"
                                     "2026-09 — всего 5.00 ч\ndev-one — 2.00 ч\ndev-three — 3.00 ч")]
        for k, (arg, rng, want) in enumerate(cases):
            r, t, _ = self.run_poll([msg(SUM + arg, date=T0 + 120 + 60 * k)])
            self.assertEqual(r["outcomes"][-1][1], "summary_given")
            self.assertEqual(self.last_text(t), want, arg)
            self.assertEqual([x[1] for x in t.sent][-1:], oracle_reply(self.s.root, "team", rng)["parts"], arg)   # оракул — из байтов файлов
            self.assertNotIn("@", want)

    def test_empty_forms_name_range_without_zero(self):
        r, t, _ = self.run_poll([msg(SUM, date=T0)])
        self.assertEqual(self.last_text(t), "мои часы за 2026-09: записей нет")
        r, t, _ = self.run_poll([msg(SUM + " team all", date=T0 + 60)])
        self.assertEqual(self.last_text(t), "команда за все месяцы: записей нет")
        self.assertNotIn("0.00", self.last_text(t))
        self.assertEqual(r["outcomes"][-1][1], "summary_given")

    def test_now_is_message_date_in_sender_zone_and_delay_does_not_matter(self):
        self.seed()
        jan = 1798848000   # 2027-01-01T20:00:00Z → «предыдущий месяц» = 2026-12, без записей; текущий = 2027-01
        r, t, _ = self.run_poll([msg(SUM + " 4", date=jan)])
        self.assertEqual(self.last_text(t), "мои часы за 2026-09…2026-12\n2026-09 — 2.00 ч")
        # тот же update, обработанный «позже», даёт тот же диапазон (время обработки в ответе не участвует)
        r2, t2, _ = self.run_poll([msg(SUM + " 4", date=jan, update_id=900555555)])
        self.assertEqual(self.last_text(t2), self.last_text(t))

    def test_retracted_line_is_excluded_like_pay(self):
        self.seed()
        r, t, _ = self.run_poll([msg(TOK["undo"] + " ошибся", date=T0 + 600)])     # отзыв последней строки dev-one (2ч, 2026-09-20)
        self.assertEqual(r["outcomes"][-1][1], "retracted")
        r, t, _ = self.run_poll([msg(SUM, date=T0 + 700)])
        self.assertEqual(self.last_text(t), "мои часы за 2026-09: записей нет")

    # --- гейты и контекст
    def test_open_session_does_not_change_and_is_not_touched(self):
        self.run_poll([msg(TOK["start_title"] + " ремонт", date=T0)])
        before = open(os.path.join(self.s.root, ".workshop", "bot-sessions.yaml"), "rb").read()
        r, t, _ = self.run_poll([msg(SUM, date=T0 + 60)])
        self.assertEqual(r["outcomes"][-1][1], "summary_given")
        self.assertEqual(open(os.path.join(self.s.root, ".workshop", "bot-sessions.yaml"), "rb").read(), before)

    def test_group_topic_and_private(self):
        self.seed()
        u = msg(SUM, date=T0 + 60); u["message"]["is_topic_message"] = True; u["message"]["message_thread_id"] = 77
        r, t, _ = self.run_poll([u, msg(SUM, date=T0 + 120, chat_type="private", chat_id=ADMIN_ID)])
        self.assertEqual([o[1] for o in r["outcomes"]], ["summary_given", "summary_given"])
        self.assertEqual(t.threads, [77, None])
        self.assertEqual([c for c, _t, _m in t.sent], [CHAT, ADMIN_ID])

    def test_unknown_sender_on_and_off(self):
        r, t, _ = self.run_poll([msg(SUM, from_id=UNKNOWN_ID, date=T0)])          # self_registration: on → временный handle, карта НЕ пишется
        self.assertEqual(r["outcomes"][-1][1], "summary_given")
        self.assertEqual(self.last_text(t), "мои часы за 2026-09: записей нет")
        self.assertNotIn("tg-%d" % UNKNOWN_ID, self.s.read(".workshop/people.yaml").decode("utf-8"))
        s2 = Stand(self_registration="off")
        try:
            cfg = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
            t2 = FakeTransport([msg(SUM, from_id=UNKNOWN_ID, date=T0, chat_type="private", chat_id=UNKNOWN_ID)])
            r2 = poll.run_once(poll.Ctx(s2.root, t2, cfg, botrepo.VALIDATOR, bot_username="cp_workshop_test_bot", sleeper=lambda x: None))
            self.assertEqual(r2["outcomes"][-1][1], "rejected_unknown_sender")
        finally:
            s2.close()

    def test_callback_and_confirm_are_rejected_without_reading(self):
        self.seed()
        r, t, _ = self.run_poll([callback(SUM)])
        self.assertEqual(r["outcomes"][-1][1], "reask_unparsed"); self.assertIn("callback_not_allowed", self.last_text(t))
        r, t, _ = self.run_poll([msg(TOK["confirm"] + " " + SUM + " team", date=T0)])
        self.assertEqual(r["outcomes"][-1][1], "reask_unparsed"); self.assertIn("confirm_not_allowed", self.last_text(t))
        self.assertEqual(self.offset(), r["outcomes"][-1][0] + 1)

    def test_bad_arguments_reasons(self):
        # закрытый перечень причин сводки (контракт §4.1): 0 / дробь / знак / Unicode-цифра — summary_bad_argument, не причина позиции last
        cases = {SUM + " 0": "summary_bad_argument", SUM + " 1.5": "summary_bad_argument", SUM + " -1": "summary_bad_argument",
                 SUM + " \u0663": "summary_bad_argument", SUM + " ALL": "summary_bad_argument", SUM + " Team": "summary_bad_argument",
                 SUM + " team all 1": "summary_extra_arguments", SUM + " всё": "summary_bad_argument", SUM + " all team": "summary_extra_arguments",
                 SUM + " team x": "summary_bad_argument", SUM + " team\nвторая строка": "summary_multiline", SUM + " 1 2": "summary_extra_arguments"}
        for text, reason in cases.items():
            r, t, _ = self.run_poll([msg(text, date=T0)])
            self.assertEqual(r["outcomes"][-1][1], "reask_unparsed", text)
            self.assertIn(reason, self.last_text(t), text)
            self.assertLessEqual(len(self.last_text(t)), poll.SHORT_REPLY_MAX)

    def write_people_and_sheets(self, handles, months, cents_of):
        """Мигрированные табели: файлы пишутся напрямую (не через бота); handles — синтетические, cents_of(i, m) → сотые."""
        people = self.s.read(".workshop/people.yaml").decode("utf-8")
        extra = "".join("  - handle: %s\n    name: \"%s\"\n    timezone: UTC\n    status: active\n    aliases: []\n" % (h, h) for h in handles)
        people = people.replace("  - handle: workshop_bot", extra + "  - handle: workshop_bot", 1)
        with open(os.path.join(self.s.root, ".workshop", "people.yaml"), "w", encoding="utf-8") as fh:
            fh.write(people)
        os.makedirs(os.path.join(self.s.root, "time"), exist_ok=True)
        for i, h in enumerate(handles):
            for m in months:
                ym = "2026-%02d" % m
                c = cents_of(i, m)
                body = ("---\nid: 0199a%03x-%04x-7000-8000-000000000000\ntype: TIMESHEET\nline_form: daily_time_v1\ntitle: t\nperson: %s\n"
                        "period_start: %s-01\nperiod_end: %s-28\ntimezone: UTC\ncreated: %s-01\nauthor: workshop_bot\nversion: 1\n---\n"
                        "%s-10 %d.%02d  работа <!--t:%04x%04x-->\n" % (i, m, h, ym, ym, ym, ym, c // 100, c % 100, i, m))
                with open(os.path.join(self.s.root, "time", "TIMESHEET-%s-%s.md" % (ym, h)), "w", encoding="utf-8") as fh:
                    fh.write(body)
        git(self.s.root, "add", "-A"); git(self.s.root, "commit", "-q", "-m", "migrated"); git(self.s.root, "push", "-q", "origin", "main")

    def check_parts(self, parts, rng):
        """Отправленные части == части независимого оракула (из байтов файлов); непустые строки — ровно логический ответ."""
        want = oracle_reply(self.s.root, "team", rng)
        self.assertEqual(parts, want["parts"])
        self.assertTrue(all(0 < len(p) <= poll.TG_TEXT_MAX and not p.startswith("\n") and not p.endswith("\n") for p in parts))
        self.assertEqual([x for x in "\n".join(parts).split("\n") if x], [x for x in want["text"].split("\n") if x])
        return want["text"]

    def test_long_team_reply_is_chunked_without_loss(self):
        # 25 людей × 12 месяцев (> 4096 символов): блоки месяцев целые (каждый помещается), ни одна строка не теряется
        self.write_people_and_sheets(["p%02d" % i for i in range(25)], range(1, 13), lambda i, m: 125)
        r, t, _ = self.run_poll([msg(SUM + " team all", date=T0)])
        self.assertEqual(r["outcomes"][-1][1], "summary_given")
        parts = [x[1] for x in t.sent]
        self.assertGreater(len(parts), 1)
        text = self.check_parts(parts, None)
        self.assertEqual(parts[0].split("\n")[0], "команда за 2026-01…2026-12")
        blocks = text.split("\n\n")[1:]
        self.assertEqual(len(blocks), 12)
        for b in blocks:                                                 # блок месяца целиком в одной части
            self.assertEqual(sum(1 for p in parts if b in p), 1)
            self.assertEqual(b.split("\n")[0], "%s — всего 31.25 ч" % b[:7])

    def test_scale_128_people_12_months_oversize_block_splits_between_people(self):
        # 128 людей × 12 месяцев, длинные синтетические handle: блок месяца > 4096 — разрыв только между строками людей,
        # «всего» — первая строка блока; суммы с переносом через 100 сотых
        handles = ["subcontractor-%03d-workshop" % i for i in range(128)]
        self.write_people_and_sheets(handles, range(1, 13), lambda i, m: 1 + (i * 37 + m * 11) % 1000)
        r, t, _ = self.run_poll([msg(SUM + " team all", date=T0)])
        self.assertEqual(r["outcomes"][-1][1], "summary_given")
        parts = [x[1] for x in t.sent]
        text = self.check_parts(parts, None)
        blocks = text.split("\n\n")[1:]
        self.assertEqual(len(blocks), 12)
        self.assertTrue(all(len(b) > poll.TG_TEXT_MAX for b in blocks))
        totals = [p for p in parts if " — всего " in p.split("\n")[0]]
        self.assertEqual(len(totals), 12)                                 # каждый блок начинает часть строкой «всего»
        for p in parts[1:]:
            first = p.split("\n")[0]
            self.assertTrue(" — всего " in first or first.startswith("subcontractor-"), first)
        for b in blocks:                                                  # итог месяца = точная сумма сотых людей
            lines = b.split("\n")
            cents = [int(l.rsplit(" ", 2)[1].replace(".", "")) for l in lines[1:]]
            self.assertEqual(len(cents), 128)
            self.assertEqual(lines[0], "%s — всего %d.%02d ч" % (b[:7], sum(cents) // 100, sum(cents) % 100))

    def test_walk_error_is_tool_failure_not_partial_sum(self):
        # T3 раунд 1 (astra, BLOCKER): ошибка обхода подкаталога time/ (os.walk глотал её без onerror) — tool_failure,
        # hold, алярм, частичная сводка НЕ отправлена, offset origin не подтверждён
        self.seed()
        import aggregation as agg
        orig = os.scandir
        def broken(path=".", *a, **k):
            if str(path).endswith(os.path.join("time")) or str(path).endswith("/time"):
                raise PermissionError(13, "adversary denied")
            return orig(path, *a, **k)
        os.scandir = broken
        try:
            r, t, _ = self.run_poll([msg(SUM + " team", date=T0 + 60)])
        finally:
            os.scandir = orig
        self.assertEqual(r["outcomes"][-1][1], "tool_failure")
        self.assertIsNotNone(r["held"])
        self.assertFalse(any("команда за" in x[1] for x in t.sent))          # частичной сводки нет
        self.assertTrue(any("сбой чтения сводки" in x[1] for x in t.sent))
        self.assertLess(botrepo_origin_offset(self.s), r["outcomes"][-1][0] + 1)

    def test_period_out_of_range_is_reask_outcome(self):
        # T3 раунд 1 (astra, MINOR): календарь за пределами представимого — исход reask_unparsed с причиной, не summary_given
        early = -46000000000                                                  # ~ год 512
        r, t, _ = self.run_poll([msg(SUM + " 9999", date=early)])
        self.assertEqual(r["outcomes"][-1][1], "reask_unparsed")
        self.assertIn("summary_period_out_of_range", self.last_text(t))
        self.assertEqual(self.offset(), r["outcomes"][-1][0] + 1)             # переспрос — advance

    def test_io_error_is_tool_failure_hold_and_alarm(self):
        self.seed()
        # IO-сбой инжектируется в читатель файлов (chmod бесполезен: поллер начинает прогон с `git checkout -- .`,
        # который восстанавливает режим файла) — класс «собственная ошибка инструмента»
        import aggregation as agg
        orig = agg._read
        def broken(path):
            if path.endswith("TIMESHEET-2026-09-dev-one.md"):
                raise OSError(5, "Input/output error (стенд)")
            return orig(path)
        agg._read = broken
        try:
            r, t, _ = self.run_poll([msg(SUM, date=T0 + 60)])
        finally:
            agg._read = orig
        self.assertEqual(r["outcomes"][-1][1], "tool_failure")
        self.assertIsNotNone(r["held"])
        self.assertTrue(any("сбой чтения сводки" in x[1] for x in t.sent))
        self.assertLess(botrepo_origin_offset(self.s), r["outcomes"][-1][0] + 1)   # авторитет не подтвердил удержанный update

    def offset(self):
        raw = self.s.read(".workshop/bot-state.yaml").decode("utf-8")
        m = re.search(r"^offset: (\d+)$", raw, re.M)
        return int(m.group(1)) if m else 0


ORACLE = os.path.join(os.path.dirname(BOT), "harness", "d15_summary_oracle.py")


def oracle_reply(root, scope, rng, limit=None, person=None):
    """Ожидаемый ответ §4.4 и части — независимый оракул T2 отдельным процессом по байтам файлов checkout'а."""
    import json, subprocess
    argv = [sys.executable, ORACLE, "--reply", "--repo", root, "--scope", scope, "--range", "all" if rng is None else "%s..%s" % rng,
            "--limit", str(limit or poll.TG_TEXT_MAX)] + (["--person", person] if person else [])
    p = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise AssertionError("оракул rc=%d: %r %r" % (p.returncode, p.stdout[-300:], p.stderr[-300:]))
    return json.loads(p.stdout.decode("utf-8"))


def botrepo_origin_offset(s):
    raw = git(s.origin, "show", "main:.workshop/bot-state.yaml", check=False)
    m = re.search(r"^offset: (\d+)$", raw, re.M)
    return int(m.group(1)) if m else 0


if __name__ == "__main__":
    unittest.main()
