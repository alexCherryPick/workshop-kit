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
        wd = dict(self.wd); wd["stale_session_alarm_hours"] = 100; self.cfg["watchdog"] = wd
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
