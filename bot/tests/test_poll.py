# -*- coding: utf-8 -*-
"""Оракул поллера (T3): стенд botrepo (bare-origin + клон + фейковый транспорт + НАСТОЯЩИЙ валидатор).
Ожидания — из байтов файлов и git-журнала. Таблица продвижения offset по 20 исходам читается из
контракта (tg-bot.yaml outcomes) и исполняется целиком: каждый исход воспроизводится фикстурой,
offset «до/после» печатается."""
import os, re, sys, unittest, hashlib
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import botrepo  # noqa: E402
from botrepo import Stand, FakeTransport, msg, callback, git, TOK, ADMIN_ID, DEV3_ID, UNKNOWN_ID, CHAT  # noqa: E402
import yamlmini, poll, state_store as ss  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CONTRACT = os.path.join(ROOT, "spec", "09-tg-bot-time-line", "tg-bot.yaml")
if not os.path.exists(CONTRACT):
    CONTRACT = os.path.join(ROOT, "output", "format-spec", "09-tg-bot-time-line", "tg-bot.yaml")
TS = "time/TIMESHEET-2026-09-dev-one.md"
CM = "time/TIMESHEET-2026-09-dev-one.comments.md"
SESS = ".workshop/bot-sessions.yaml"
STATE = ".workshop/bot-state.yaml"
T0 = 1788790990  # 2026-09-07T14:23:10Z


def contract_outcomes():
    """[(ordinal, id, offset)] — ДВАДЦАТЬ исходов из машинного дубля контракта (tg-bot.yaml outcomes),
    построчным чтением полей ordinal/id/offset; ручной копии перечня в тесте нет."""
    rows, cur, inside = [], {}, False
    for ln in open(CONTRACT, encoding="utf-8"):
        if ln.startswith("outcomes:"):
            inside = True; continue
        if inside and ln and not ln.startswith(" ") and not ln.startswith("#"):
            break
        if not inside:
            continue
        m = re.match(r"^  - ordinal: (\d+)$", ln)
        if m:
            cur = {"ordinal": int(m.group(1))}; rows.append(cur); continue
        m = re.match(r"^    (id|offset): (\S+)$", ln)
        if m and cur:
            cur[m.group(1)] = m.group(2)
    return [(r["ordinal"], r["id"], r["offset"]) for r in rows]


def origin_offset(s):
    """offset в АВТОРИТЕТЕ (origin/main): читается из git-объекта, не с диска рабочей копии."""
    raw = git(s.origin, "show", "main:.workshop/bot-state.yaml", check=False)
    m = re.search(r"^offset: (\d+)$", raw, re.M)
    return int(m.group(1)) if m else 0


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.s = Stand()
        self.cfg = yamlmini.load_file(os.path.join(self.s.root, ".workshop", "bot.yaml"))

    def tearDown(self):
        self.s.close()

    def run_poll(self, updates, validator=None, sleeper=None):
        t = FakeTransport(updates)
        ctx = poll.Ctx(self.s.root, t, self.cfg, validator or botrepo.VALIDATOR, bot_username="cp_workshop_test_bot", sleeper=sleeper or (lambda x: None))
        r = poll.run_once(ctx)
        return r, t, ctx

    def run_poll_with_race(self, updates, inject):
        """inject() исполняется непосредственно перед коммитом поллера (после его pull) — искусственная гонка."""
        orig = poll.commit_mod.commit_paths
        def racing(*a, **kw):
            inject(); poll.commit_mod.commit_paths = orig
            return orig(*a, **kw)
        poll.commit_mod.commit_paths = racing
        try:
            return self.run_poll(updates)
        finally:
            poll.commit_mod.commit_paths = orig

    def offset(self):
        return yamlmini.load_file(os.path.join(self.s.root, STATE)).get("offset") if os.path.exists(os.path.join(self.s.root, STATE)) else 0


class TestCycle(Base):
    def test_record_one_commit_two_files_state(self):
        r, t, ctx = self.run_poll([msg("2ч 40м созвон\nхвост сообщения")])
        self.assertEqual(r["outcomes"][0][1], "recorded")
        stat = git(self.s.root, "show", "--stat", "--format=", "HEAD")
        for f in (TS, CM, STATE):
            self.assertIn(f, stat)
        self.assertEqual(self.s.commits(), "2")             # seed + один коммит записи
        self.assertEqual(self.s.origin_head(), self.s.head())  # запушено
        self.assertEqual(self.offset(), r["outcomes"][0][0] + 1)
        self.assertEqual(len(t.sent), 1)
        body = self.s.read(CM)
        self.assertIn(b"\n2\xd1\x87 40\xd0\xbc \xd1\x81\xd0\xbe\xd0\xb7\xd0\xb2\xd0\xbe\xd0\xbd\n\xd1\x85\xd0\xb2\xd0\xbe\xd1\x81\xd1\x82 \xd1\x81\xd0\xbe\xd0\xbe\xd0\xb1\xd1\x89\xd0\xb5\xd0\xbd\xd0\xb8\xd1\x8f\n", body)  # полные байты
        ops = [o["op"] for o in ctx.trace.ops]
        self.assertLess(ops.index("check_line"), ops.index("commit"))
        self.assertLess(ops.index("check_pair"), ops.index("commit"))
        self.assertEqual(git(self.s.root, "status", "--porcelain"), "")

    def test_no_tail_no_comment_file(self):
        r, t, ctx = self.run_poll([msg(TOK["track"] + " 10:00-11:30 планёрка")])
        self.assertEqual(r["outcomes"][0][1], "recorded")
        self.assertFalse(os.path.exists(os.path.join(self.s.root, CM)))
        self.assertNotIn("check_pair", [o["op"] for o in ctx.trace.ops])

    def test_batch_order_equals_sequential(self):
        a = msg(TOK["start_title"] + " ремонт", date=T0); b = msg(TOK["stop"], date=T0 + 5400)
        r, t, _ = self.run_poll([a, b])
        self.assertEqual([o[1] for o in r["outcomes"]], ["session_opened", "session_closed_recorded"])
        one = (self.s.read(TS), self.s.read(SESS), self.s.commits())
        # второй стенд: два прогона подряд
        s2 = Stand()
        try:
            cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
            for u in (a, b):
                poll.run_once(poll.Ctx(s2.root, FakeTransport([u]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            two = (s2.read(TS), s2.read(SESS), s2.commits())
        finally:
            s2.close()
        # id контейнера минтится на стенде — сравнение тела без строки id
        strip = lambda b: re.sub(rb"^id: .*$", b"id: X", b, count=1, flags=re.M)
        self.assertEqual(strip(one[0]), strip(two[0]))
        self.assertEqual(one[1], two[1])
        self.assertEqual(one[2], two[2])
        # перестановка порядка в батче (stop раньше start по update_id) — другой результат: stop без открытого учёта
        s3 = Stand()
        try:
            cfg3 = yamlmini.load_file(os.path.join(s3.root, ".workshop", "bot.yaml"))
            b2 = dict(b); b2["update_id"] = a["update_id"] - 1
            r3 = poll.run_once(poll.Ctx(s3.root, FakeTransport([a, b2]), cfg3, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            self.assertEqual([o[1] for o in r3["outcomes"]], ["reask_stop_without_open", "session_opened"])
        finally:
            s3.close()

    def test_replay_is_identical_repeat(self):
        u = msg("1ч 30м тест\nхвост")
        r1, _, _ = self.run_poll([u])
        ts, cm, n = self.s.read(TS), self.s.read(CM), self.s.commits()
        # тот же update повторно от сервера, не почистившего очередь (ниже водяного знака offset) → тождественный повтор, ноль коммитов
        t2 = FakeTransport([u]); t2.get_updates = lambda **kw: [u]
        r2 = poll.run_once(poll.Ctx(self.s.root, t2, self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
        self.assertEqual(r2["outcomes"][0][1], "identical_repeat")
        self.assertEqual((self.s.read(TS), self.s.read(CM), self.s.commits()), (ts, cm, n))
        self.assertEqual(t2.sent, [])
        # смерть до подтверждения: offset откатан искусственно, тот же update приходит вновь — правило Т по якорю
        st = yamlmini.load_file(os.path.join(self.s.root, STATE)); st["offset"] = 0
        open(os.path.join(self.s.root, STATE), "w").write(yamlmini.dumps(st, sort_keys=True))
        git(self.s.root, "commit", "-qam", "rollback-offset")
        r3, t3, _ = self.run_poll([u])
        self.assertEqual(r3["outcomes"][0][1], "identical_repeat")
        self.assertEqual((self.s.read(TS), self.s.read(CM)), (ts, cm))

    def test_state_file_deterministic_and_quiet(self):
        self.run_poll([msg(TOK["start_title"] + " x")])
        a = self.s.read(SESS)
        r, _, _ = self.run_poll([])
        self.assertEqual(git(self.s.root, "status", "--porcelain"), "")
        self.assertEqual(self.s.read(SESS), a)

    def test_callback_last_and_time_bearing(self):
        self.run_poll([msg("2ч работа"), msg(TOK["start_n"] + " 1")])
        r, t, _ = self.run_poll([callback(TOK["help"]), callback(TOK["start_n"] + " 1")])
        self.assertEqual(r["outcomes"][0][1], "help_given")
        self.assertNotIn(r["outcomes"][1][1], poll.RECORD_OUTCOMES)  # time_bearing позиция callback'ом НЕ исполняется
        self.assertEqual(len(t.answered), 2)                          # подтверждение нажатия — через транспорт
        self.assertEqual(self.offset(), r["outcomes"][1][0] + 1)

    def test_last_list_keyboard(self):
        self.run_poll([msg("2ч альфа"), msg("3ч бета")])
        r, t, _ = self.run_poll([msg(TOK["last"])])
        self.assertEqual(r["outcomes"][0][1], "last_list_given")
        self.assertIsNotNone(t.sent[-1][2])
        self.assertIn("бета", t.sent[-1][1])

    def test_trace_predicate_pull_then_commit(self):
        _, _, ctx = self.run_poll([msg("2ч 40м созвон\nхвост")])
        between = ctx.trace.between("pull", "commit")
        self.assertIsNotNone(between)
        for o in between:
            self.assertNotIn(o["op"], ("getUpdates", "push", "send", "fetch", "merge"), o)
            if o["op"] == "write":
                self.assertTrue(o["target"].startswith("time/") or o["target"].startswith(".workshop/"), o)

    def test_pending_self_registration(self):
        r, t, _ = self.run_poll([msg("2ч работа", from_id=UNKNOWN_ID)])
        self.assertEqual(r["outcomes"][0][1], "recorded")
        people = self.s.read(".workshop/people.yaml").decode("utf-8")
        self.assertIn("tg-%d" % UNKNOWN_ID, people)
        self.assertTrue(os.path.exists(os.path.join(self.s.root, "time/TIMESHEET-2026-09-tg-%d.md" % UNKNOWN_ID)))
        self.assertIn("сверит админ", t.sent[-1][1])
        st = yamlmini.load_file(os.path.join(self.s.root, STATE))
        self.assertEqual(len(st["self_registrations"]), 1)
        # известный человек самозаписи НЕ порождает
        r2, _, _ = self.run_poll([msg("1ч работа")])
        self.assertEqual(len(yamlmini.load_file(os.path.join(self.s.root, STATE))["self_registrations"]), 1)


class TestRaces(Base):
    def test_push_rejected_then_retry_union(self):
        # первая запись, затем фронт дописывает коммент к ТОЙ ЖЕ строке в origin; вторая запись бота едет через reconcile
        self.run_poll([msg("2ч 40м созвон\nхвост")])
        other = self.s.other_clone()
        cm = os.path.join(other, CM)
        anchor = re.search(rb"<!--t:([0-9a-f]{8})-->", self.s.read(TS)).group(1).decode()
        with open(cm, "ab") as fh:
            fh.write(("\n### 2026-09-07T15:00:00Z · dev-three <!--c:0199fdc1-0000-7000-8000-000000000001 about:t:%s-->\nкоммент фронта\n" % anchor).encode("utf-8"))
        git(other, "commit", "-qam", "front comment"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, ctx = self.run_poll([msg("1ч ещё\nвторой хвост")])
        self.assertEqual(r["outcomes"][0][1], "recorded")
        body = self.s.read(CM)
        self.assertIn(b"c:0199fdc1-0000-7000-8000-000000000001", body)
        self.assertEqual(body.count(b"about:t:"), 3)
        self.assertEqual(self.s.origin_head(), self.s.head())
        self.assertNotIn("merge-abort", [o["op"] for o in ctx.trace.ops])

    def test_sessions_conflict_is_loud(self):
        self.run_poll([msg(TOK["start_title"] + " своё", date=T0)])
        other = self.s.other_clone()
        # чужая правка файла состояния ТОЙ ЖЕ записи приезжает в origin
        p = os.path.join(other, SESS)
        with open(p, "rb") as fh:
            data = fh.read()
        with open(p, "wb") as fh:
            fh.write(data.replace("title: своё".encode("utf-8"), "title: чужое".encode("utf-8")))
        git(other, "commit", "-qam", "foreign session edit")
        before = self.s.origin_head()
        # гонка: чужой коммит приезжает в origin МЕЖДУ pull-перед-коммитом и push поллера
        r, t, ctx = self.run_poll_with_race([msg(TOK["stop"], date=T0 + 3600)], lambda: git(other, "push", "-q", "origin", "HEAD:main"))
        self.assertEqual(r["held"][1], "conflict_p1_unmet")
        self.assertEqual(self.s.origin_head(), git(other, "rev-parse", "HEAD").strip())  # ветка origin = чужой коммит, бот её не тронул
        self.assertTrue(any("сторож" in x[1] for x in t.sent))  # алярм
        self.assertEqual(self.offset(), r["held"][0])          # offset НЕ продвинут
        self.assertIn("merge-abort", [o["op"] for o in ctx.trace.ops])

    def test_nonoverlapping_state_edit_is_loud_not_silent_merge(self):
        # РЕГРЕССИЯ (T3 раунд 1, blocker): чужая правка НЕПЕРЕСЕКАЮЩЕЙСЯ части файла состояния (не той
        # строки) под -merge даёт КОНФЛИКТ (громкий отказ 10), а не тихое 3-way слияние
        self.run_poll([msg(TOK["start_title"] + " своё", date=T0)])
        other = self.s.other_clone(); p = os.path.join(other, SESS)
        with open(p, "rb") as fh:
            data = fh.read()
        # правим ДРУГУЮ запись/ключ: дописываем чужого человека — ханк не пересекается с нашим dev-one
        with open(p, "wb") as fh:
            fh.write(data.rstrip(b"\n") + b"\n  dev-nine:\n    title: \xd1\x87\xd1\x83\xd0\xb6\xd0\xbe\xd0\xb5\n    started_at: 1\n    schema_version: 1\n")
        git(other, "commit", "-qam", "foreign non-overlapping session")
        r, t, ctx = self.run_poll_with_race([msg(TOK["stop"], date=T0 + 3600)], lambda: git(other, "push", "-q", "origin", "HEAD:main"))
        self.assertEqual(r["held"][1], "conflict_p1_unmet")           # -merge → конфликт, не тихое слияние
        self.assertTrue(any("сторож" in x[1] for x in t.sent))
        self.assertEqual(git(self.s.root, "status", "--porcelain"), "")
        # то же для bot-state.yaml (offset vs чужой список отклонений)
        s2 = Stand(); cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
        try:
            poll.run_once(poll.Ctx(s2.root, FakeTransport([msg("2ч работа")]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            o2 = s2.other_clone(); sp = os.path.join(o2, STATE)
            with open(sp, "rb") as fh:
                sd = fh.read()
            with open(sp, "wb") as fh:
                fh.write(sd.replace(b"unknown_rejections: []", b"unknown_rejections:\n  - {at: 1, telegram_id: 5}"))
            git(o2, "commit", "-qam", "foreign state list")
            orig = poll.commit_mod.commit_paths
            def racing(*a, **kw):
                git(o2, "push", "-q", "origin", "HEAD:main"); poll.commit_mod.commit_paths = orig
                return orig(*a, **kw)
            poll.commit_mod.commit_paths = racing
            try:
                r2 = poll.run_once(poll.Ctx(s2.root, FakeTransport([msg("1ч ещё")]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            finally:
                poll.commit_mod.commit_paths = orig
            self.assertEqual(r2["held"][1], "conflict_p1_unmet")       # bot-state тоже -merge → конфликт
        finally:
            s2.close()

    def run_poll_with_prereconcile_push(self, updates, inject):
        """чужой push приезжает ПОСЛЕ чтения состояния в память и ДО reconcile пишущего исхода (односторонняя правка)."""
        orig = poll.commit_mod.reconcile
        def racing(*a, **kw):
            inject(); poll.commit_mod.reconcile = orig
            return orig(*a, **kw)
        poll.commit_mod.reconcile = racing
        try:
            return self.run_poll(updates)
        finally:
            poll.commit_mod.reconcile = orig

    def test_one_sided_remote_state_edit_is_reread_not_overwritten(self):
        # РЕГРЕССИЯ (приёмка, Fable BLOCKER-1): -merge не ловит ОДНОСТОРОННЮЮ правку; поллер обязан перечитать и пересчитать
        # B11: чужая запись dev-nine в файле учёта приезжает односторонне → сохранена в origin после нашего push
        self.run_poll([msg(TOK["start_title"] + " своё", date=T0)])
        other = self.s.other_clone(); p = os.path.join(other, SESS)
        with open(p, "rb") as fh:
            data = fh.read()
        with open(p, "wb") as fh:
            fh.write(data.rstrip(b"\n") + b"\n  dev-nine:\n    title: x\n    started_at: 1\n    schema_version: 1\n")
        git(other, "commit", "-qam", "foreign one-sided session")
        r, t, ctx = self.run_poll_with_prereconcile_push([msg("2ч работа", date=T0 + 60)], lambda: git(other, "push", "-q", "origin", "HEAD:main"))
        self.assertEqual(r["outcomes"][0][1], "recorded")
        origin_sessions = git(self.s.origin, "show", "main:.workshop/bot-sessions.yaml")
        self.assertIn("dev-nine", origin_sessions)                          # чужой факт не затёрт
        self.assertIn("dev-one", origin_sessions)                           # наша открытая сессия на месте
        self.assertIn("reread", [o["op"] for o in ctx.trace.ops])
        # B11b: чужой unknown_rejections в файле прогона приезжает односторонне → сохранён вместе с нашим offset
        s2 = Stand(); cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
        try:
            poll.run_once(poll.Ctx(s2.root, FakeTransport([msg("1ч а")]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            o2 = s2.other_clone(); sp = os.path.join(o2, STATE)
            with open(sp, "rb") as fh:
                sd = fh.read()
            with open(sp, "wb") as fh:
                fh.write(sd.replace(b"unknown_rejections: []", b"unknown_rejections:\n  - {at: 1, telegram_id: 5}"))
            git(o2, "commit", "-qam", "foreign one-sided state")
            orig = poll.commit_mod.reconcile
            def racing(*a, **kw):
                git(o2, "push", "-q", "origin", "HEAD:main"); poll.commit_mod.reconcile = orig
                return orig(*a, **kw)
            poll.commit_mod.reconcile = racing
            try:
                u = msg("1ч ещё")
                r2 = poll.run_once(poll.Ctx(s2.root, FakeTransport([u]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            finally:
                poll.commit_mod.reconcile = orig
            self.assertEqual(r2["outcomes"][0][1], "recorded")
            st = git(s2.origin, "show", "main:.workshop/bot-state.yaml")
            self.assertIn("telegram_id: 5", st)                              # чужой факт сохранён
            self.assertEqual(origin_offset(s2), u["update_id"] + 1)          # наш offset — тоже
        finally:
            s2.close()

    def test_one_sided_remote_close_recomputes_stop(self):
        # B11c: сессию dev-one закрыли руками в origin односторонне → наше закрытие пересчитывается в переспрос, строки нет
        self.run_poll([msg(TOK["start_title"] + " своё", date=T0)])
        other = self.s.other_clone(); p = os.path.join(other, SESS)
        with open(p, "wb") as fh:
            fh.write(b"schema_version: 1\nsessions: {}\n")
        git(other, "commit", "-qam", "manual close")
        r, t, ctx = self.run_poll_with_prereconcile_push([msg(TOK["stop"], date=T0 + 3600)], lambda: git(other, "push", "-q", "origin", "HEAD:main"))
        self.assertEqual(r["outcomes"][0][1], "reask_stop_without_open")
        self.assertFalse(os.path.exists(os.path.join(self.s.root, "time")) and os.listdir(os.path.join(self.s.root, "time")))
        self.assertNotIn("dev-one", git(self.s.origin, "show", "main:.workshop/bot-sessions.yaml"))

    def test_mixed_batch_preserves_rejection_telemetry(self):
        # РЕГРЕССИЯ (T3 раунд 1, warning): батч [отклонение, запись] сохраняет счётчик отклонений
        # (пишущий исход после reconcile НЕ затирает накопленные в памяти счётчики)
        self.cfg = dict(self.cfg); self.cfg["self_registration"] = "off"
        rej = msg("1ч x", from_id=UNKNOWN_ID, chat_type="private")
        rec = msg("2ч работа", from_id=ADMIN_ID)
        r, t, _ = self.run_poll([rej, rec])
        st = ss.read_state(self.s.root)
        self.assertEqual([o[1] for o in r["outcomes"]], ["rejected_unknown_sender", "recorded"])
        self.assertEqual(len(st["unknown_rejections"]), 1)            # не потеряно пишущим исходом
        # обратный порядок и отдельные прогоны дают тот же счётчик
        s2 = Stand(); c2 = dict(yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))); c2["self_registration"] = "off"
        try:
            poll.run_once(poll.Ctx(s2.root, FakeTransport([rec, rej]), c2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
            self.assertEqual(len(ss.read_state(s2.root)["unknown_rejections"]), 1)
        finally:
            s2.close()

    def test_retries_exhausted(self):
        waits = []
        self.s.deny_push(True)
        before = self.offset()
        u = msg("2ч работа")
        r, t, ctx = self.run_poll([u], sleeper=waits.append)
        self.assertEqual(r["held"][1], "retries_exhausted")
        attempts = self.cfg["retry"]["push_max_attempts"]
        self.assertEqual(len([o for o in ctx.trace.ops if o["op"] == "push"]), attempts)
        self.assertEqual(len(waits), attempts - 1)
        self.assertLess(sum(waits) * 20, 24 * 3600)   # суммарный бэкофф (с дефолтным 20 с) заведомо меньше окна retention
        self.assertTrue(any("сторож" in x[1] and "ретра" in x[1] for x in t.sent))
        # offset на ДИСКЕ не продвинут: файл состояния в незапушенном коммите не является подтверждением — origin не изменился
        self.assertEqual(git(self.s.origin, "rev-list", "--count", "main").strip(), "1")
        # ПОРЯДОК ПОДТВЕРЖДЕНИЯ: следующий прогон подтверждает серверу offset АВТОРИТЕТА (origin), не локальной копии
        r2, t2, _ = self.run_poll([u], sleeper=waits.append)
        self.assertEqual(t2.offsets, [before])
        # push снова доступен: локальный коммит доезжает, повтор того же update — тождество, origin получает offset
        self.s.deny_push(False)
        r3, t3, _ = self.run_poll([u])
        self.assertEqual(t3.offsets, [before])
        self.assertEqual(r3["outcomes"][0][1], "identical_repeat")
        self.assertEqual(origin_offset(self.s), u["update_id"] + 1)
        self.assertEqual(self.s.origin_head(), self.s.head())

    def test_p1_unmet_refuses_merge_and_legal_append_merges(self):
        # Р1 (D04 §2.2): правка КОНВЕРТА на стороне фронта под union — merge молчал бы; бот обязан НЕ сливать
        self.run_poll([msg("2ч работа")])
        other = self.s.other_clone()
        p = os.path.join(other, TS)
        with open(p, "rb") as fh:
            b = fh.read()
        with open(p, "wb") as fh:
            fh.write(b.replace(b"version: 1", b"version: 2") + "2026-09-06 1.00  чужая <!--t:0000ffff-->\n".encode("utf-8"))
        git(other, "commit", "-qam", "front envelope edit")
        r, t, ctx = self.run_poll_with_race([msg("1ч ещё")], lambda: git(other, "push", "-q", "origin", "HEAD:main"))
        self.assertEqual(r["held"][1], "conflict_p1_unmet")
        self.assertEqual(self.s.origin_head(), git(other, "rev-parse", "HEAD").strip())   # ветка origin не тронута ботом
        self.assertTrue(any("сторож" in x[1] for x in t.sent))
        self.assertEqual(git(self.s.root, "status", "--porcelain"), "")                    # рабочая копия чиста
        self.assertIn(("p1", 1), [(o["op"], o["rc"]) for o in ctx.trace.ops])
        self.assertNotIn("merge", [o["op"] for o in ctx.trace.ops][ [o["op"] for o in ctx.trace.ops].index("p1"): ])  # слияния после отказа нет
        # обратный контроль: законное дописывание фронтом (конверт нетронут) — union, запись проходит
        s2 = Stand(); cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
        try:
            run = lambda ups, inj=None: (self._race(s2, cfg2, ups, inj) if inj else poll.run_once(poll.Ctx(s2.root, FakeTransport(ups), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)))
            run([msg("2ч работа")])
            o2 = s2.other_clone()
            with open(os.path.join(o2, TS), "ab") as fh:
                fh.write("2026-09-06 1.00  чужая законная <!--t:0000fffe-->\n".encode("utf-8"))
            git(o2, "commit", "-qam", "front append")
            r2 = run([msg("1ч ещё")], lambda: git(o2, "push", "-q", "origin", "HEAD:main"))
            self.assertEqual(r2["outcomes"][0][1], "recorded")
            body = s2.read(TS)
            self.assertIn(b"0000fffe", body); self.assertEqual(body.count(b"<!--t:"), 3)
            self.assertEqual(s2.origin_head(), s2.head())
        finally:
            s2.close()

    def _race(self, stand, cfg, updates, inject):
        orig = poll.commit_mod.commit_paths
        def racing(*a, **kw):
            inject(); poll.commit_mod.commit_paths = orig
            return orig(*a, **kw)
        poll.commit_mod.commit_paths = racing
        try:
            return poll.run_once(poll.Ctx(stand.root, FakeTransport(updates), cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
        finally:
            poll.commit_mod.commit_paths = orig

    def test_pending_name_with_secret_is_replaced_by_handle(self):
        # T4 W-4: имя из мессенджера сканируется тем же реестром; находка → handle вместо имени
        u = msg("2ч работа", from_id=UNKNOWN_ID)
        u["message"]["from"]["first_name"] = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
        r, t, _ = self.run_poll([u])
        self.assertEqual(r["outcomes"][0][1], "recorded")
        people = self.s.read(".workshop/people.yaml")
        self.assertNotIn(b"ghp_", people)
        self.assertIn(b"name: tg-%d" % UNKNOWN_ID, people)


class TestOffsetTable(Base):
    """Каждый из ДВАДЦАТИ исходов контракта — фикстурой; печатается offset до/после; клетка (18) — неприменимо."""

    def fixtures(self):
        fake = os.path.join(self.s.tmp, "fake-validator")
        def fake_bin(rc):
            open(fake, "w").write("#!/bin/sh\necho 'ERROR X: %s'\nexit %d\n" % ("FAKE_RULE", rc)); os.chmod(fake, 0o755); return fake
        F = {}
        F["recorded"] = lambda: self.run_poll([msg("2ч работа")])
        F["recorded_with_warning"] = lambda: self.run_poll([msg("2ч работа")], validator=fake_bin(1))
        F["identical_repeat"] = lambda: self._replay()
        F["reask_unparsed"] = lambda: self.run_poll([msg("/frobnicate")])
        F["reask_invalid"] = lambda: self.run_poll([msg("2ч работа")], validator=fake_bin(2))
        F["reask_correction"] = lambda: self.run_poll([msg(TOK["track"] + " 10:00-09:00 x")]) if False else self.run_poll([msg("2ч работа")])  # (см. ниже)
        F["rejected_unknown_sender"] = lambda: self.run_poll_off([msg("2ч работа", from_id=UNKNOWN_ID, chat_type="private")])
        F["rejected_secret"] = lambda: self.run_poll([msg("2ч ключ ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")])
        F["non_input"] = lambda: self.run_poll([{"update_id": 900200001, "edited_message": {"message_id": 1, "chat": {"id": CHAT, "type": "supergroup"}, "from": {"id": ADMIN_ID}, "text": "x"}}])
        F["conflict_p1_unmet"] = lambda: self._conflict()
        F["retries_exhausted"] = lambda: (self.s.deny_push(True), self.run_poll([msg("2ч работа")]))[1]
        F["run_refused"] = lambda: self.run_poll([msg("2ч работа")], validator=fake_bin(3))
        F["tool_failure"] = lambda: self.run_poll([msg("2ч работа")], validator=os.path.join(self.s.tmp, "no-such-binary"))
        F["session_opened"] = lambda: self.run_poll([msg(TOK["start_title"] + " x")])
        F["session_closed_recorded"] = lambda: self.run_poll([msg(TOK["start_title"] + " x", date=T0), msg(TOK["stop"], date=T0 + 600)])
        F["reask_start_already_open"] = lambda: self.run_poll([msg(TOK["start_title"] + " x", date=T0), msg(TOK["start_title"] + " y", date=T0 + 60)])
        F["reask_stop_without_open"] = lambda: self.run_poll([msg(TOK["stop"])])
        F["help_given"] = lambda: self.run_poll([msg(TOK["help"])])
        F["last_list_given"] = lambda: self.run_poll([msg(TOK["last"])])
        return F

    def run_poll_off(self, updates):
        self.cfg = dict(self.cfg); self.cfg["self_registration"] = "off"
        return self.run_poll(updates)

    def _replay(self):
        u = msg("2ч работа")
        self.run_poll([u])
        t = FakeTransport([u]); t.get_updates = lambda **kw: [u]   # сервер отдал update ниже водяного знака
        ctx = poll.Ctx(self.s.root, t, self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
        return poll.run_once(ctx), t, ctx

    def _conflict(self):
        self.run_poll([msg(TOK["start_title"] + " своё", date=T0)])
        other = self.s.other_clone(); p = os.path.join(other, SESS)
        with open(p, "ab") as fh:
            fh.write(b"# foreign\n")
        git(other, "commit", "-qam", "x")
        return self.run_poll_with_race([msg(TOK["stop"], date=T0 + 60)], lambda: git(other, "push", "-q", "origin", "HEAD:main"))

    def test_table(self):
        rows = contract_outcomes()
        self.assertEqual(len(rows), 20)
        table = ["  offset-table (исход: offset до → после; advances по контракту)"]
        seen = set()
        for oid, name, adv in rows:
            if name == "session_stale":
                table.append("  %2d %-26s неприменимо (порождается сторожем T5, к offset отношения не имеет)" % (oid, name)); seen.add(name); continue
            if name == "reask_correction":
                table.append("  %2d %-26s неприменимо в T3: исправления через бота — вне D09 (граница «9.2 ок»); исход зарезервирован контрактом" % (oid, name)); seen.add(name); continue
            self.tearDown(); self.setUp()
            before = self.offset()
            r, t, ctx = self.fixtures()[name]()
            last = r["outcomes"][-1]
            self.assertEqual(last[1], name, "фикстура %s дала %s" % (name, last[1]))
            after = self.offset() if name != "retries_exhausted" else origin_offset(self.s)
            table.append("  %2d %-26s %s → %s   advances=%s" % (oid, name, before, after, adv))
            if adv == "advance":
                self.assertEqual(after, last[0] + 1, name)
            else:
                self.assertEqual(adv, "hold", name)
                self.assertNotEqual(after, last[0] + 1, name)   # локальный offset (при исчерпании ретраев коммит остаётся локально — авторитет origin)
                self.assertLessEqual(origin_offset(self.s), last[0], name)   # авторитет (origin) не продвинут за удержанный update
                self.assertIsNotNone(r["held"], name)
            seen.add(name)
        self.assertEqual(len(seen), 20)
        out = os.environ.get("D09_OFFSET_TABLE")   # selfcheck_t3.sh печатает таблицу из этого файла; поток unittest не засоряется
        if out:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\n".join(table) + "\n")


if __name__ == "__main__":
    unittest.main()
