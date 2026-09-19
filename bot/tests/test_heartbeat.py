# -*- coding: utf-8 -*-
"""Оракул сторожа (T5): стенд botrepo (bare-origin + клон + фейковый транспорт + НАСТОЯЩИЙ валидатор
для записи через поллер). Предмет наблюдения — молчание (возраст необработанного), зависшая сессия,
счётчик отклонений. Ожидания — из байтов файлов и журнала исходящих; пороги — из конфига, не литералы."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import botrepo  # noqa: E402
from botrepo import Stand, FakeTransport, msg, git, TOK, ADMIN_ID, UNKNOWN_ID, CHAT  # noqa: E402
import yamlmini, poll, heartbeat, state_store as ss  # noqa: E402

HOUR = 3600
T0 = 1788790990


class Base(unittest.TestCase):
    def setUp(self):
        self.s = Stand()
        self.cfg = yamlmini.load_file(os.path.join(self.s.root, ".workshop", "bot.yaml"))
        self.wd = self.cfg["watchdog"]

    def tearDown(self):
        self.s.close()

    def poll(self, updates):
        return poll.run_once(poll.Ctx(self.s.root, FakeTransport(updates), self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))

    def beat(self, pending=None, now=None):
        t = FakeTransport(pending or [])
        ctx = heartbeat.Ctx(self.s.root, t, self.cfg, now=now, sleeper=lambda x: None)
        return heartbeat.run_once(ctx), t, ctx

    def alarm_mode(self):
        """Режим уведомления (REQ-089): автоотмена выключена — шаблон комплекта включает её по умолчанию (REQ-103)."""
        self.cfg = dict(self.cfg); wd = dict(self.wd); wd["stale_session_cancel_minutes"] = 0
        self.cfg["watchdog"] = wd; self.wd = wd

    def raw(self, rel):
        with open(os.path.join(self.s.root, rel), "rb") as fh:
            return fh.read()


class SilenceTests(Base):
    def test_silence_alarm_and_offset_untouched(self):
        # необработанное сообщение старше порога → алярм админам; курсор не тронут
        silence_h = self.wd["unprocessed_update_alarm_hours"]
        old = msg("2ч работа", date=T0)                     # это сообщение НЕ обрабатывалось поллером
        state_before = self.raw(ss.STATE_PATH) if os.path.exists(os.path.join(self.s.root, ss.STATE_PATH)) else b""
        now = T0 + (silence_h + 1) * HOUR
        r, t, ctx = self.beat(pending=[old], now=now)
        self.assertIsNotNone(r["silence"])
        self.assertEqual(r["silence"]["age_s"], (silence_h + 1) * HOUR)
        self.assertEqual(r["offset_before"], r["offset_after"])              # замер не подтвердил offset
        self.assertNotIn("write", [o["op"] for o in ctx.trace.ops if o["target"].startswith(".workshop/bot-state")])
        gu = [o for o in ctx.trace.ops if o["op"] == "getUpdates"][0]
        self.assertIn("timeout=0", gu["target"])
        self.assertTrue(all(x[0] in botrepo.git and True or True for x in []))  # noop
        self.assertTrue(all("сторож" in x[1] for x in t.sent))
        state_after = self.raw(ss.STATE_PATH) if os.path.exists(os.path.join(self.s.root, ss.STATE_PATH)) else b""
        self.assertEqual(state_before, state_after)

    def test_exact_boundary_is_silent_strictly_greater(self):
        self.alarm_mode()
        # W-1 (T5 раунд 1): граница age == порог МОЛЧИТ (код `>`, глава «старше порога»); age == порог+1 — алярм
        silence_s = self.wd["unprocessed_update_alarm_hours"] * HOUR
        old = msg("2ч работа", date=T0)
        r_eq, t_eq, _ = self.beat(pending=[old], now=T0 + silence_s)         # ровно порог
        self.assertIsNone(r_eq["silence"]); self.assertEqual(t_eq.sent, [])
        r_gt, t_gt, _ = self.beat(pending=[old], now=T0 + silence_s + 1)     # порог + 1 с
        self.assertIsNotNone(r_gt["silence"]); self.assertTrue(t_gt.sent)
        # то же для зависшей сессии
        self.poll([msg(TOK["start_title"] + " задача", date=T0)])
        stale_s = self.wd["stale_session_alarm_hours"] * HOUR
        r1, t1, _ = self.beat(now=T0 + stale_s); self.assertEqual([x for x in r1["stale"] if x["notified"]], [])
        r2, t2, _ = self.beat(now=T0 + stale_s + 1); self.assertEqual(len([x for x in r2["stale"] if x["notified"]]), 1)

    def test_healthy_poller_no_alarm(self):
        # отрицательный контроль: сообщение записано (не ожидает) → возраст ожидающих нет → молчание
        self.poll([msg("2ч работа", date=T0)])
        now = T0 + (self.wd["unprocessed_update_alarm_hours"] + 5) * HOUR
        r, t, ctx = self.beat(pending=[], now=now)          # поллер всё подтвердил: ожидающих нет
        self.assertIsNone(r["silence"])
        self.assertEqual(t.sent, [])

    def test_ran_but_nothing_to_do_is_silent(self):
        # «поллер бегал, но записывать было нечего» (ожидающих нет) → молчание; отличается от «не бегал»
        now = T0 + 100 * HOUR
        r, t, _ = self.beat(pending=[], now=now)
        self.assertIsNone(r["silence"]); self.assertEqual(t.sent, [])
        # «не бегал»: те же по виду логи, но сообщение ОЖИДАЕТ
        r2, t2, _ = self.beat(pending=[msg("1ч x", date=T0)], now=now)
        self.assertIsNotNone(r2["silence"]); self.assertTrue(t2.sent)


class AuthorityTests(Base):
    """Codex B1 (приёмка): сторож читает авторитет origin — {ahead, behind, fetch failure} × {состояние есть/нет}."""
    def test_ahead_local_offset_is_not_confirmed(self):
        # P7: push запрещён → поллер оставил локальный offset продвинутым; сторож обязан передать в getUpdates offset ORIGIN (0)
        self.s.deny_push(True)
        u = msg("2ч работа", date=T0)
        self.poll([u])
        local = ss.read_state(self.s.root)["offset"]
        self.assertEqual(local, u["update_id"] + 1)
        self.s.deny_push(False)
        r, t, ctx = self.beat(pending=[u], now=T0 + 60)
        self.assertEqual(t.offsets, [0])                                # авторитет, не локальная копия
        self.assertEqual((r["offset_before"], r["offset_after"]), (0, 0))
        self.assertIn("authority", [o["op"] for o in ctx.trace.ops])

    def test_behind_clone_sees_stale_session_from_origin(self):
        self.alarm_mode()
        # P8: второй (устаревший) клон создан до открытия учёта; поллер в основном публикует сессию; сторож в старом клоне обязан её увидеть
        other = self.s.other_clone()
        self.poll([msg(TOK["start_title"] + " долгая задача", date=T0)])
        cfg2 = self.cfg
        t = FakeTransport([]); ctx = heartbeat.Ctx(other, t, cfg2, now=T0 + (self.wd["stale_session_alarm_hours"] + 1) * HOUR, sleeper=lambda x: None)
        r = heartbeat.run_once(ctx)
        self.assertEqual(len([x for x in r["stale"] if x["notified"]]), 1)
        self.assertIn("долгая задача", t.sent[0][1])

    def test_fetch_failure_is_tool_failure_not_silence(self):
        import shutil
        shutil.move(self.s.origin, self.s.origin + ".gone")
        try:
            with self.assertRaises(heartbeat.commit_mod.GitError):
                self.beat(pending=[msg("2ч работа", date=T0)], now=T0 + 100 * HOUR)
        finally:
            shutil.move(self.s.origin + ".gone", self.s.origin)


class StaleSessionTests(Base):
    def setUp(self):
        Base.setUp(self); self.alarm_mode()

    def open_session(self, started):
        u = msg(TOK["start_title"] + " долгая задача", date=started)
        self.poll([u])
        self.assertIn("dev-one", ss.read_sessions(self.s.root)["sessions"])

    def test_stale_notifies_person_names_title_and_does_not_close(self):
        stale_h = self.wd["stale_session_alarm_hours"]
        self.open_session(T0)
        before = self.raw(ss.SESSIONS_PATH)
        now = T0 + (stale_h + 1) * HOUR
        r, t, ctx = self.beat(now=now)
        self.assertEqual(len([x for x in r["stale"] if x["notified"]]), 1)
        self.assertEqual(len(t.sent), 1)
        self.assertEqual(t.sent[0][0], CHAT)                       # в чат ЧЕЛОВЕКА (chat_id записи), не админам
        self.assertIn("долгая задача", t.sent[0][1])
        self.assertIn(TOK["track"], t.sent[0][1])                   # шаблон записи задним числом — в уведомлении (REQ-103)
        self.assertEqual(self.raw(ss.SESSIONS_PATH), before)       # НЕ закрыл и НЕ мутировал (cmp)
        self.assertIn("dev-one", ss.read_sessions(self.s.root)["sessions"])

    def test_fresh_session_no_alarm(self):
        self.open_session(T0)
        now = T0 + (self.wd["stale_session_alarm_hours"] - 1) * HOUR
        r, t, _ = self.beat(now=now)
        self.assertEqual([x for x in r["stale"] if x["notified"]], [])
        self.assertEqual(t.sent, [])

    def test_rare_repeat_three_beats_not_three_notifications(self):
        stale_h = self.wd["stale_session_alarm_hours"]; repeat_h = self.wd["stale_session_repeat_hours"]
        self.open_session(T0)
        sent = 0
        for k in range(3):                                          # три прогона крона подряд, шаг час — в пределах repeat
            now = T0 + (stale_h + 1 + k) * HOUR
            r, t, _ = self.beat(now=now)
            sent += len(t.sent)
        self.assertEqual(sent, 1, "три прогона при одной висящей сессии дали %d уведомлений" % sent)
        # спустя repeat — снова одно
        r, t, _ = self.beat(now=T0 + (stale_h + 1 + repeat_h + 1) * HOUR)
        self.assertEqual(len(t.sent), 1)


class CancelTests(Base):
    """Автоотмена (REQ-103, исход 24): порог в МИНУТАХ из конфига; запись снимается одним коммитом без строк;
    подсказка — в чат человека с готовой строкой записи задним числом (дата и время начала из записи)."""
    def open_session(self, started, title="долгая задача"):
        u = msg(TOK["start_title"] + " " + title, date=started)
        self.poll([u])
        self.assertIn("dev-one", ss.read_sessions(self.s.root)["sessions"])

    def test_cancel_removes_session_commits_and_hints_template(self):
        cm = self.wd["stale_session_cancel_minutes"]; self.assertGreater(cm, 0)
        self.open_session(T0)
        rec = ss.read_sessions(self.s.root)["sessions"]["dev-one"]
        head_before = git(self.s.root, "rev-parse", "HEAD").strip()
        r, t, ctx = self.beat(now=T0 + cm * 60 + 1)
        st = [x for x in r["stale"] if x.get("cancelled")]
        self.assertEqual(len(st), 1)
        self.assertNotIn("dev-one", ss.read_sessions(self.s.root)["sessions"])                    # снята локально
        self.assertNotIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])  # и в авторитете (push)
        self.assertEqual(len(t.sent), 1)
        chat, text = t.sent[0][0], t.sent[0][1]
        self.assertEqual(chat, CHAT)                                                              # в чат человека, не админам
        ops = [o["op"] for o in ctx.trace.ops]
        self.assertLess(ops.index("push"), ops.index("send"), ops)                                # «отменён» — после публикации
        self.assertIn("долгая задача", text); self.assertIn("отменён", text)
        tpl = heartbeat.track_template(rec)
        self.assertIn(tpl, text)
        self.assertTrue(tpl.startswith(TOK["track"] + " " + rec["started_at_local"][:10] + " " + rec["started_at_local"][11:16] + "-"), tpl)
        self.assertTrue(tpl.endswith(" долгая задача"), tpl)
        log = [ln.split(" ", 1) for ln in git(self.s.root, "log", "--format=%H %s", "%s..HEAD" % head_before).splitlines()]
        cancel = [h for h, subj in log if "session_cancelled" in subj and "dev-one" in subj]
        self.assertEqual(len(cancel), 1, log)                                                      # ровно один коммит отмены
        stat = git(self.s.root, "show", "--stat", "--format=", cancel[0])
        self.assertIn(ss.SESSIONS_PATH, stat); self.assertNotIn("time/", stat)                    # ноль дневных строк
        self.assertEqual(git(self.s.root, "rev-parse", "HEAD").strip(), git(self.s.root, "rev-parse", "origin/main").strip())   # всё запушено

    def test_below_cancel_threshold_untouched(self):
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        before = self.raw(ss.SESSIONS_PATH)
        r, t, _ = self.beat(now=T0 + cm * 60)                                                     # ровно порог — не больше
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        self.assertEqual([x[1] for x in t.sent if "отменён," in x[1]], [])                      # уведомление (исход 18) — допустимо, отмены нет
        self.assertTrue(all("будет отменён" in x[1] for x in t.sent), t.sent)                   # и оно предупреждает об отмене
        self.assertEqual(self.raw(ss.SESSIONS_PATH), before)

    def test_behind_clone_postpones_cancel_without_mutation(self):
        cm = self.wd["stale_session_cancel_minutes"]
        other = self.s.other_clone()
        self.open_session(T0)
        t = FakeTransport([]); ctx = heartbeat.Ctx(other, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None)
        r = heartbeat.run_once(ctx)
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        self.assertEqual([x[1] for x in t.sent if "отменён," in x[1]], [])                      # «отменён» не сказано
        self.assertIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])     # авторитет не тронут
        self.assertIn("cancel", [o["op"] for o in ctx.trace.ops])
        self.assertEqual(len([x for x in r["stale"] if x["notified"]]), 1)                         # но предупреждён (исход 18)

    def test_cancel_push_rejected_rolls_back_and_says_nothing(self):
        """B1 адверсария: «отменён» — только после push; отвергнутый push → откат, человеку ничего, админам алярм."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        head = git(self.s.root, "rev-parse", "HEAD").strip()
        self.s.deny_push(True)
        try:
            r, t, ctx = self.beat(now=T0 + cm * 60 + 1)
        finally:
            self.s.deny_push(False)
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        subs = git(self.s.root, "log", "--format=%s", "%s..HEAD" % head).splitlines()
        self.assertEqual([s for s in subs if "session_cancelled" in s], [], subs)                       # коммит отмены откачен
        self.assertIn("dev-one", ss.read_sessions(self.s.root)["sessions"])                           # локально жива
        self.assertIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])          # и в авторитете
        self.assertEqual([x[1] for x in t.sent if x[0] == CHAT and "отменён," in x[1]], [])            # человеку «отменён» не сказано
        self.assertTrue(any(x[0] != CHAT and "не опубликована" in x[1] for x in t.sent), t.sent)      # админам — алярм
        self.assertIn("rollback", [o["op"] for o in ctx.trace.ops])
        git(self.s.root, "push", "-q", "origin", "HEAD")                                               # следующая запись поллера публикует локальный хвост (состояние сторожа)
        r2, t2, _ = self.beat(now=T0 + cm * 60 + 2)                                                    # следующий прогон — отменяет
        self.assertEqual(len([x for x in r2["stale"] if x.get("cancelled")]), 1)
        self.assertNotIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])

    def test_cancel_notice_undelivered_is_owed_and_resent(self):
        """B2 адверсария: отказ доставки после push — не сбой; долг в состоянии сторожа, досылка следующим прогоном."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        t = FakeTransport([]); t.fail_send = True
        ctx = heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None)
        r = heartbeat.run_once(ctx)                                                                     # не TOOL_FAILURE
        self.assertEqual(len([x for x in r["stale"] if x.get("cancelled")]), 1)
        self.assertNotIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])
        hb = heartbeat.read_hb_text(ss._text_at_ref(self.s.root, "origin/main", heartbeat.HEARTBEAT_PATH))
        self.assertEqual([k for k in hb["pending_notices"] if k.startswith("dev-one@")], ["dev-one@%d" % T0])   # долг опубликован; ключ — сессия
        self.assertIn("send_failed", [o["op"] for o in ctx.trace.ops])
        r2, t2, _ = self.beat(now=T0 + cm * 60 + 600)                                                  # следующий прогон досылает
        self.assertEqual(len(t2.sent), 1); self.assertEqual(t2.sent[0][0], CHAT); self.assertIn("отменён", t2.sent[0][1])
        hb = heartbeat.read_hb_text(ss._text_at_ref(self.s.root, "origin/main", heartbeat.HEARTBEAT_PATH))
        self.assertEqual(hb["pending_notices"], {})
        r3, t3, _ = self.beat(now=T0 + cm * 60 + 1200)
        self.assertEqual(t3.sent, [])                                                                  # долг погашен один раз

    def test_pending_notice_not_resent_while_ahead(self):
        """W3 раунда 2: копия впереди origin — долг не досылается (снятие не опубликовалось бы), повторов нет."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        t = FakeTransport([]); t.fail_send = True
        heartbeat.run_once(heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None))
        self.s.deny_push(True)                                                                         # поллер записал, push отвергнут → копия ahead
        try:
            self.poll([msg("2ч работа", date=T0 + cm * 60 + 100)])
            sent = 0
            for k in range(3):
                r, tk, ctx = self.beat(now=T0 + cm * 60 + 200 + k * 60); sent += len(tk.sent)
            self.assertEqual(sent, 0, "долг досылался при копии впереди origin")
            self.assertIn("notice", [o["op"] for o in ctx.trace.ops])
        finally:
            self.s.deny_push(False)
        git(self.s.root, "push", "-q", "origin", "HEAD")
        r, t2, _ = self.beat(now=T0 + cm * 60 + 900)
        self.assertEqual(len(t2.sent), 1)                                                              # опубликуемо — досылка ровно раз
        r, t3, _ = self.beat(now=T0 + cm * 60 + 1000)
        self.assertEqual(t3.sent, [])

    def test_two_cancellations_same_person_keep_both_notices(self):
        """W6 раунда 2: ключ долга — сессия, не человек: вторая отмена до досылки не затирает первую."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0, title="первая")
        t = FakeTransport([]); t.fail_send = True
        heartbeat.run_once(heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None))
        self.open_session(T0 + cm * 60 + 100, title="вторая")
        t = FakeTransport([]); t.fail_send = True
        heartbeat.run_once(heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + 2 * cm * 60 + 200, sleeper=lambda x: None))
        hb = heartbeat.read_hb_text(ss._text_at_ref(self.s.root, "origin/main", heartbeat.HEARTBEAT_PATH))
        self.assertEqual(len(hb["pending_notices"]), 2)
        r, t2, _ = self.beat(now=T0 + 2 * cm * 60 + 300)
        self.assertEqual(sorted("первая" in x[1] or "вторая" in x[1] for x in t2.sent), [True, True])
        self.assertTrue(any("первая" in x[1] for x in t2.sent) and any("вторая" in x[1] for x in t2.sent))

    def test_group_chat_free_form_template_tells_how_to_reach_bot(self):
        """W4 раунда 2: число-подобный заголовок в групповом чате — подсказка, как строке дойти до бота (privacy-mode)."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.poll([msg(TOK["start_title"] + " №7", date=T0)])                                          # CHAT < 0 — группа
        r, t, _ = self.beat(now=T0 + cm * 60 + 1)
        self.assertEqual(len(t.sent), 1)
        self.assertIn("ответом на это сообщение", t.sent[0][1])
        self.assertTrue(t.sent[0][1].splitlines()[-1].endswith(" №7"))

    def test_debt_is_committed_with_cancellation(self):
        """Раунд 3 B1: долг уведомления — в том же коммите, что снятие записи; свежий клон origin видит долг."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        head = git(self.s.root, "rev-parse", "HEAD").strip()
        t = FakeTransport([]); t.fail_send = True
        heartbeat.run_once(heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None))
        log = [ln.split(" ", 1) for ln in git(self.s.root, "log", "--format=%H %s", "%s..HEAD" % head).splitlines()]
        cancel = [h for h, subj in log if "session_cancelled" in subj]
        self.assertEqual(len(cancel), 1)
        stat = git(self.s.root, "show", "--stat", "--format=", cancel[0])
        self.assertIn(ss.SESSIONS_PATH, stat); self.assertIn(heartbeat.HEARTBEAT_PATH, stat)
        hb_at_cancel = heartbeat.read_hb_text(git(self.s.root, "show", "%s:%s" % (cancel[0], heartbeat.HEARTBEAT_PATH)))
        self.assertEqual(list(hb_at_cancel["pending_notices"]), ["dev-one@%d" % T0])
        other = self.s.other_clone()                                                                   # свежий клон: долг есть, доставит
        git(other, "pull", "-q", "--ff-only", "origin", "main")
        t2 = FakeTransport([]); r2 = heartbeat.run_once(heartbeat.Ctx(other, t2, self.cfg, now=T0 + cm * 60 + 900, sleeper=lambda x: None))
        self.assertEqual(len(t2.sent), 1); self.assertIn("отменён", t2.sent[0][1])
        git(self.s.root, "fetch", "-q", "origin")
        hb = heartbeat.read_hb_text(ss._text_at_ref(self.s.root, "origin/main", heartbeat.HEARTBEAT_PATH))
        self.assertEqual(hb["pending_notices"], {})

    def test_foreign_staged_changes_postpone_cancel(self):
        """Раунд 3 B2: чужой индекс/правка tracked-файла (не файла учёта) — транзакция откладывается, курсор не публикуется."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        p = os.path.join(self.s.root, ss.STATE_PATH)
        with open(p, "a", encoding="utf-8") as fh: fh.write("# foreign\n")
        git(self.s.root, "add", "--", ss.STATE_PATH)
        r, t, ctx = self.beat(now=T0 + cm * 60 + 1)
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        self.assertIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])
        self.assertNotIn("foreign", ss._text_at_ref(self.s.root, "origin/main", ss.STATE_PATH) or "")
        git(self.s.root, "reset", "-q", "--", ss.STATE_PATH); git(self.s.root, "checkout", "-q", "--", ss.STATE_PATH)
        r, t, _ = self.beat(now=T0 + cm * 60 + 2)
        self.assertEqual(len([x for x in r["stale"] if x.get("cancelled")]), 1)

    def test_long_title_notice_is_chunked_not_lost(self):
        """Раунд 3 W4: длинный заголовок — уведомление уходит частями, как ответы поллера, а не теряется."""
        import poll as poll_mod
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0, title="ж" * 2100)
        r, t, _ = self.beat(now=T0 + cm * 60 + 1)
        ctx = _
        self.assertEqual(len([x for x in r["stale"] if x.get("cancelled")]), 1)
        r, t, ctx = r, t, _
        parts = [x[1] for x in t.sent]                                                                 # фактически отправленные части
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(all(len(p) <= poll_mod.TG_TEXT_MAX for p in parts), [len(p) for p in parts])
        self.assertEqual("\n".join(parts), ctx.sent[0][1])                                             # инвариант сохранения информации

    def test_rollback_keeps_run_progress_delta_only(self):
        """Раунд 4 W1: откат неудавшейся отмены не стирает прогресс прогона по другим людям (last_stale_alarm) и погашенные долги."""
        cm = self.wd["stale_session_cancel_minutes"]; alarm_h = self.wd["stale_session_alarm_hours"]
        # dev-three — старше порога отмены; dev-one — между порогами (получит исход 18 в том же прогоне)
        self.poll([msg(TOK["start_title"] + " старая", date=T0, from_id=botrepo.DEV3_ID, chat_id=CHAT)])
        self.poll([msg(TOK["start_title"] + " свежая", date=T0 + cm * 60 - alarm_h * 3600 - 1200)])          # возраст = порог уведомления + 20 мин
        self.s.deny_push(True)
        try:
            r, t, ctx = self.beat(now=T0 + cm * 60 + 1)
        finally:
            self.s.deny_push(False)
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        self.assertIn("dev-one", heartbeat.read_hb(self.s.root)["last_stale_alarm"])                  # прогресс прогона по dev-one пережил откат (персист локальный, push отвергнут)
        git(self.s.root, "push", "-q", "origin", "HEAD")
        r2, t2, _ = self.beat(now=T0 + cm * 60 + 700)                                                # 10 мин спустя: повтора исхода 18 dev-one нет
        self.assertEqual([x[1] for x in t2.sent if "свежая" in x[1]], [])

    def test_superseded_by_other_writer_no_false_nothing_recorded(self):
        """Раунд 4 W2: между fetch и push сторожа другой клон закрыл ту же сессию — отмена беспредметна, «ничего не записано» не говорится."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        other = self.s.other_clone(); git(other, "pull", "-q", "--ff-only", "origin", "main")
        t = FakeTransport([])
        ctx = heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None)
        orig = heartbeat.commit_mod.commit_paths
        def race(*a, **kw):
            heartbeat.commit_mod.commit_paths = orig
            po = poll.Ctx(other, FakeTransport([msg(TOK["stop"], date=T0 + cm * 60)]), self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
            ro = poll.run_once(po); assert ro["outcomes"][-1][1] == "session_closed_recorded", ro["outcomes"]
            return orig(*a, **kw)
        heartbeat.commit_mod.commit_paths = race
        try:
            r = heartbeat.run_once(ctx)
        finally:
            heartbeat.commit_mod.commit_paths = orig
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        self.assertEqual([x[1] for x in t.sent if "ничего не записано" in x[1]], [])
        self.assertEqual([x[1] for x in t.sent if "не опубликована" in x[1]], [])                      # не сбой — алярма нет
        self.assertTrue(any(o["op"] == "cancel" and "другим писателем" in (o.get("note") or "") for o in ctx.trace.ops))
        self.assertEqual([x[1] for x in t.sent if "не закрыт" in x[1]], [])                             # r5 W1: исход 18 о закрытой сессии не даётся
        self.assertEqual([x for x in r["stale"] if x["handle"] == "dev-one"], [])
        git(self.s.root, "fetch", "-q", "origin")
        self.assertNotIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])
        self.assertEqual(git(self.s.root, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).strip(), "")

    def test_partial_delivery_resumes_from_undelivered_part(self):
        """Раунд 4 W3: доставлена первая часть, вторая отвергнута — долг помнит прогресс, первая часть не повторяется."""
        import poll as poll_mod
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0, title="ж" * 2100)
        t = FakeTransport([]); t.fail_after_parts = 1
        ctx = heartbeat.Ctx(self.s.root, t, self.cfg, now=T0 + cm * 60 + 1, sleeper=lambda x: None)
        r = heartbeat.run_once(ctx)
        self.assertEqual(len(t.sent), 1)
        git(self.s.root, "fetch", "-q", "origin")
        hb = heartbeat.read_hb_text(ss._text_at_ref(self.s.root, "origin/main", heartbeat.HEARTBEAT_PATH))
        note = list(hb["pending_notices"].values())[0]
        self.assertEqual(note.get("from_part"), 1)
        r2, t2, _ = self.beat(now=T0 + cm * 60 + 900)
        self.assertEqual(len(t2.sent), 1)                                                              # только недоставленная часть
        self.assertNotEqual(t2.sent[0][1], t.sent[0][1])
        git(self.s.root, "fetch", "-q", "origin")
        self.assertEqual(heartbeat.read_hb_text(ss._text_at_ref(self.s.root, "origin/main", heartbeat.HEARTBEAT_PATH))["pending_notices"], {})

    def test_dirty_sessions_file_postpones_cancel(self):
        """W1: грязная рабочая копия файла учёта (поллер умер после записи) не уезжает в коммит отмены."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        p = os.path.join(self.s.root, ss.SESSIONS_PATH)
        with open(p, "ab") as fh: fh.write(b"# dirty\n")
        r, t, ctx = self.beat(now=T0 + cm * 60 + 1)
        self.assertEqual([x for x in r["stale"] if x.get("cancelled")], [])
        self.assertIn("dev-one", ss.read_sessions_at(self.s.root, "origin/main")["sessions"])
        self.assertTrue(any(o["op"] == "cancel" and "dirty=True" in (o.get("note") or "") for o in ctx.trace.ops), ctx.trace.ops)

    def test_two_people_cancelled_in_one_beat_two_commits(self):
        """W2: две зависшие сессии разных людей — обе отменяются в одном прогоне, каждая своим коммитом."""
        cm = self.wd["stale_session_cancel_minutes"]
        self.poll([msg(TOK["start_title"] + " a", date=T0), msg(TOK["start_title"] + " b", date=T0, from_id=botrepo.DEV3_ID, chat_id=CHAT)])
        self.assertEqual(len(ss.read_sessions(self.s.root)["sessions"]), 2)
        head = git(self.s.root, "rev-parse", "HEAD").strip()
        r, t, _ = self.beat(now=T0 + cm * 60 + 1)
        self.assertEqual(len([x for x in r["stale"] if x.get("cancelled")]), 2)
        self.assertEqual(ss.read_sessions_at(self.s.root, "origin/main")["sessions"], {})
        subs = git(self.s.root, "log", "--format=%s", "%s..HEAD" % head).splitlines()
        self.assertEqual(len([s for s in subs if "session_cancelled" in s]), 2)

    def test_template_for_number_like_title_is_free_text_form(self):
        """W5: заголовок-число не проходит round-trip через команду записи (стал бы номером списка) — шаблон формой свободной строки."""
        rec = {"title": "№2", "started_at_local": "2026-09-15T16:28:23+03:00"}
        tpl = heartbeat.track_template(rec)
        self.assertFalse(tpl.startswith(TOK["track"]), tpl)
        self.assertEqual(tpl, "2026-09-15 16:28-ЧЧ:ММ №2")
        self.assertTrue(heartbeat.track_template({"title": "два созвона", "started_at_local": "2026-09-15T16:28:23+03:00"}).startswith(TOK["track"] + " 2026-09-15 16:28-"))

    def test_stop_after_cancel_is_reask_and_track_template_records(self):
        cm = self.wd["stale_session_cancel_minutes"]
        self.open_session(T0)
        r, t, _ = self.beat(now=T0 + cm * 60 + 1)
        tpl = t.sent[0][1].splitlines()[-1]
        rp = self.poll([msg(TOK["stop"], date=T0 + cm * 60 + 100)])
        self.assertEqual(rp["outcomes"][-1][1], "reask_stop_without_open")
        rp = self.poll([msg(tpl.replace("ЧЧ:ММ", "23:59"), date=T0 + cm * 60 + 200)])         # человек подставил конец
        self.assertIn(rp["outcomes"][-1][1], ("recorded", "recorded_with_warning"))
        rp = self.poll([msg(tpl, date=T0 + cm * 60 + 300)])                                       # шаблон без подстановки — не запись
        self.assertEqual(rp["outcomes"][-1][1], "reask_unparsed")


class RejectionReportTests(Base):
    def test_counter_named_when_over_threshold(self):
        # off: незнакомый отклоняется и считается
        self.cfg = dict(self.cfg); self.cfg["self_registration"] = "off"
        self.poll([msg("1ч x", from_id=UNKNOWN_ID, chat_type="private"), msg("2ч y", from_id=100000199, chat_type="private")])
        st = ss.read_state(self.s.root)
        self.assertEqual(len(st["unknown_rejections"]), 2)
        r, t, ctx = self.beat(now=T0 + HOUR)
        self.assertIsNotNone(r["rejection"])
        self.assertEqual((r["rejection"]["count"], r["rejection"]["senders"]), (2, 2))
        self.assertTrue(any("2" in x[1] for x in t.sent))
        # второй прогон без новых отклонений — молчание (watermark сдвинут)
        r2, t2, _ = self.beat(now=T0 + 2 * HOUR)
        self.assertIsNone(r2["rejection"])

    def test_zero_counter_no_report(self):
        r, t, _ = self.beat(now=T0 + HOUR)
        self.assertIsNone(r["rejection"])
        self.assertEqual([x for x in t.sent if "отклонено" in x[1]], [])


class DeliveryMatchTests(Base):
    def test_t3_alarm_and_heartbeat_share_addressee(self):
        # T5 ВЕРИФИЦИРУЕТ доставку исходов T3 (10/11), не реализует отправку: адресат поллера == адресат сторожа
        import identity as identity_mod
        people = identity_mod.people_list(yamlmini.load_file(os.path.join(self.s.root, ".workshop", "people.yaml")))
        hb_addr = set(identity_mod.alarm_targets(people, self.wd["alarm_to"]))
        # исход 11 (исчерпание ретраев) поллера — алярм; собираем его адресатов из журнала исходящих
        self.s.deny_push(True)
        r, t, ctx = None, None, None
        pt = FakeTransport([msg("2ч работа", date=T0)])
        pctx = poll.Ctx(self.s.root, pt, self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
        poll.run_once(pctx)
        poller_alarm_to = {chat for chat, text, _ in pt.sent if "сторож" in text}
        self.assertEqual(poller_alarm_to, hb_addr)                 # СОВПАДЕНИЕ адресата (сверка по конфигу)
        self.assertTrue(poller_alarm_to)

    def test_no_vendor_host_second_addressee(self):
        # адресат берётся из того же конфига, что и поллер; вендорских хостов ноль, второго адресата нет
        import re
        for mod in ("heartbeat.py", "poll.py"):
            src = open(os.path.join(os.path.dirname(__file__), "..", mod), encoding="utf-8").read()
            hosts = re.findall(r"https?://[a-z0-9.\-]+", src)
            self.assertEqual([h for h in hosts if "bot.invalid" not in h], [], "%s: вендорский хост %s" % (mod, hosts))


class ThresholdTests(Base):
    def test_thresholds_from_config_not_literals(self):
        # пороги читаются из конфига: изменение конфига меняет поведение без правки кода
        self.cfg = dict(self.cfg)
        wd = dict(self.wd); wd["stale_session_alarm_hours"] = 100; wd["stale_session_cancel_minutes"] = 0; self.cfg["watchdog"] = wd
        u = msg(TOK["start_title"] + " x", date=T0); self.poll([u])
        r, t, _ = self.beat(now=T0 + 50 * HOUR)                    # 50 ч < 100 ч порога → молчание
        self.assertEqual([x for x in r["stale"] if x["notified"]], [])
        # жёстких чисел-часов в коде сторожа нет
        src = open(os.path.join(os.path.dirname(__file__), "..", "heartbeat.py"), encoding="utf-8").read()
        import re
        # разрешены дефолты .get(...,N) и множитель 3600; запрещены прочие «часовые» литералы политики
        body = src.split('"""', 2)[-1]
        bad = re.findall(r"(?<![.\w])(?:12|20|24)(?![\w0-9])", body)
        self.assertEqual(bad, [], "числа-политики в коде сторожа: %s" % bad)


if __name__ == "__main__":
    unittest.main()
