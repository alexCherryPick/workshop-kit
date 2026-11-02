# -*- coding: utf-8 -*-
"""Оракул поллера (T3): стенд botrepo (bare-origin + клон + фейковый транспорт + НАСТОЯЩИЙ валидатор).
Ожидания — из байтов файлов и git-журнала. Таблица продвижения offset по 23 исходам (T8) читается из
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
    """[(ordinal, id, offset)] — исходы (24: 23 после T8 + session_cancelled) из машинного дубля контракта (tg-bot.yaml outcomes),
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

    def test_last_without_n_lists_all_unique_and_track_n_records(self):
        """REQ-106 / REQ-105: без N — все уникальные заголовки (шаблон комплекта: last_default_n 0); запись по номеру тем же списком."""
        self.assertEqual(int(self.cfg.get("last_default_n", 0)), 0)
        self.run_poll([msg("1ч t%d" % i) for i in range(7)] + [msg("1ч t3")])                    # t3 повторяется — уникальных 7
        r, t, _ = self.run_poll([msg(TOK["last"])])
        self.assertEqual(r["outcomes"][0][1], "last_list_given")
        body = t.sent[-1][1]
        self.assertEqual(len([ln for ln in body.splitlines() if ln[:1].isdigit()]), 7)
        self.assertTrue(body.splitlines()[1].endswith("t3"), body)                                  # новейший первым
        r, t, _ = self.run_poll([msg(TOK["last"] + " 2")])
        self.assertEqual(len([ln for ln in t.sent[-1][1].splitlines() if ln[:1].isdigit()]), 2)
        r, t, _ = self.run_poll([msg(TOK["track"] + " 10:00-11:00 2")])                            # №2 списка = t6
        self.assertEqual(r["outcomes"][0][1], "recorded")
        self.assertIn("«t6»", t.sent[-1][1])
        self.assertIn("t6", open(os.path.join(self.s.root, TS), encoding="utf-8").read().splitlines()[-1])

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


class TestTransportDebounce(Base):
    """D19 M5, ЦЕЛЕВАЯ ФОРМА (DECISION 2026-10-17, слово alex 2026-10-18 «ок»): транзиентный сбой транспорта Telegram
    алармит, только когда удачного цикла нет 600 с; затем не чаще 600 с после ДОСТАВЛЕННОГО алярма; верхней границы
    давности last_seen нет. Иные сбои, отсутствие/порча отметки, сбой решения, отметку не обновить — алярм сразу.
    Оракул — литералы политики из DECISION (600/600, 429, 5xx), чисел модуля тест не читает; отметка читается json напрямую.
    Стенды по процессу на цикл и матрица таймаутов — harness/m5_transport_alarm.py."""
    NOW = 1790000000
    A, R = 600, 600                         # DECISION: первое окно и окно повтора — литералы, не из модуля

    def _main(self, exc=None, now=None, send_fails=False):
        import io, contextlib
        sent = []
        class T(object):
            def __init__(self, *a, **kw): pass
            def call(self, method, params): return {"username": "x"}
            def send_message(self, chat_id, text, **kw):
                if send_fails:
                    raise poll.tg.TransportError("sendMessage: api error 502: Bad Gateway", error_code=502, kind="api")
                sent.append((chat_id, text)); return {}
        def ok(ctx): return {"processed": 0, "outcomes": [], "held": None}
        def boom(ctx, _e=exc): raise _e
        saved = (poll.tg.Transport, poll.run_once, poll._now, os.getcwd())
        poll.tg.Transport, poll.run_once = T, (boom if exc is not None else ok)
        poll._now = lambda: (self.NOW if now is None else now)
        out = io.StringIO()
        try:
            os.chdir(self.s.root)
            with contextlib.redirect_stdout(out):
                rc = poll.main()
        finally:
            poll.tg.Transport, poll.run_once, poll._now = saved[:3]
            os.chdir(saved[3])
        return rc, sent, out.getvalue()

    def _path(self):
        return os.path.join(self.s.root, ".workshop-bin", "poller-transport.json")

    def _mark(self):
        import json
        p = self._path()
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def _mark_bytes(self):
        with open(self._path(), "rb") as fh:
            return fh.read()

    def _set_mark(self, raw):
        p = self._path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))

    def _net(self, code=None, kind="network"):
        return poll.tg.TransportError("getUpdates: network error: [Errno 104] Connection reset by peer", method="getUpdates",
                                      error_code=code, kind=kind)

    def _alarm_times(self, times):
        """Отказ транспорта в каждый момент из times; → моменты, в которые алярм ДОСТАВЛЕН (rc 10 всякий раз)."""
        got = []
        for t in times:
            rc, sent, out = self._main(self._net(), now=self.NOW + t)
            self.assertEqual(rc, 10, (t, out))
            if sent:
                self.assertEqual(len(sent), 1, (t, sent))
                got.append(t)
        return got

    def _double_mark_failure_success(self, t):
        """Удачный цикл в момент t при .workshop-bin 0555: rc 0, запись И удаление отметки отказали (байты те же)."""
        before = self._mark_bytes()
        d = os.path.dirname(self._path())
        os.chmod(d, 0o555)
        try:
            rc, sent, out = self._main(now=self.NOW + t)
            self.assertEqual(rc, 0, out)
            self.assertIn("transport-mark: не записана", out)
            self.assertEqual(self._mark_bytes(), before, "отметку удалось изменить — предусловие сценария не выполнено")
        finally:
            os.chmod(d, 0o755)                                          # права вернулись ДО следующего отказа

    def test_success_writes_mark_self_ignored_tree_clean(self):
        rc, sent, out = self._main()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self._mark(), {"last_ok": self.NOW, "alarmed_at": None, "last_seen": self.NOW})
        with open(os.path.join(self.s.root, ".workshop-bin", ".gitignore"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "*\n")
        st = git(self.s.root, "status", "--porcelain", "--ignored=no")
        self.assertNotIn(".workshop-bin", st)

    def test_policy_constants_are_ten_minutes_both(self):
        self.assertEqual((poll.TRANSPORT_ALARM_AFTER_S, poll.TRANSPORT_REALARM_EVERY_S), (600, 600))   # DECISION: 600/600

    def test_threshold_boundary_and_realarm(self):
        A, R, STEP = self.A, self.R, 60                                 # шаг — пауза демона после сбоя
        self._main()                                                    # last_ok = NOW
        def chain(t0, t1):
            for t in range(t0, t1, STEP):
                rc, sent, out = self._main(self._net(), now=self.NOW + t)
                self.assertEqual((rc, sent), (10, []), (t, out))
        chain(STEP, A)                                                  # 60…540 — тишина
        rc, sent, out = self._main(self._net(), now=self.NOW + A - 1)   # 599 — тишина
        self.assertEqual(sent, [], out)
        self.assertIn("алярм отложен", out)
        rc, sent, out = self._main(self._net(), now=self.NOW + A)       # 600 — алярм с длительностью
        self.assertTrue(len(sent) == 1 and "сбой поллера (TransportError)" in sent[0][1] and "удачного цикла нет 10 мин" in sent[0][1], sent)
        self.assertEqual(self._mark(), {"last_ok": self.NOW, "alarmed_at": self.NOW + A, "last_seen": self.NOW + A})
        rc, sent, out = self._main(self._net(), now=self.NOW + A)       # дубль события в тот же момент — тишина
        self.assertEqual(sent, [], out)
        chain(A + STEP, A + R)                                          # окно повтора 660…1140 — тишина
        rc, sent, out = self._main(self._net(), now=self.NOW + A + R - 1)   # 1199 — тишина
        self.assertEqual(sent, [], out)
        self.assertIn("повтор не чаще", out)
        rc, sent, out = self._main(self._net(), now=self.NOW + A + R)   # 1200 — повтор
        self.assertEqual(len(sent), 1, ("повторный алярм через 600 с не ушёл", out))
        self.assertEqual(self._mark()["alarmed_at"], self.NOW + A + R)
        rc, sent, out = self._main(self._net(), now=self.NOW + A + 2 * R - 1)   # 1799 — тишина
        self.assertEqual(sent, [], out)
        rc, sent, out = self._main(self._net(), now=self.NOW + A + 2 * R)       # 1800 — снова повтор
        self.assertEqual(len(sent), 1, out)
        rc, sent, out = self._main(now=self.NOW + 1805)                 # восстановление сбрасывает отметку алярма
        self.assertEqual(self._mark(), {"last_ok": self.NOW + 1805, "alarmed_at": None, "last_seen": self.NOW + 1805})
        rc, sent, out = self._main(self._net(), now=self.NOW + 1810)
        self.assertEqual(sent, [])

    def test_no_upper_bound_on_last_seen_gap(self):
        """Codex R3-02: разрыв циклов больше 300 с (длинный http_timeout + backoff 60 + пауза 2) подавление НЕ выключает —
        решают только 600 с от успеха и 600 с от доставленного алярма."""
        t0 = 0
        for gap, alarm in ((301, False), (332, False), (392, False), (599, False), (600, True), (900, True)):
            t0 += 5000
            self._main(now=self.NOW + t0)
            rc, sent, out = self._main(self._net(), now=self.NOW + t0 + gap)
            self.assertEqual(bool(sent), alarm, (gap, out))
        t0 += 5000                                                      # серия с шагом 392 (300/330): 332, 724, 1116, 1508
        self._main(now=self.NOW + t0)
        got = [t - t0 for t in self._alarm_times([t0 + 332, t0 + 724, t0 + 1116, t0 + 1508])]
        self.assertEqual(got, [724, 1508])

    def test_r2_01_double_mark_failure_then_new_outage(self):
        """Codex R2-01 в целевой форме: успех T, доставленный алярм T+600, удачный цикл T+700 без записи И удаления отметки,
        права вернулись; отказ T+1400 — АЛЯРМ (старое окно повтора истекло: 800 ≥ 600); T+4199 — алярм; T+4200 — тишина."""
        self._main()
        self.assertEqual(self._alarm_times([600]), [600])
        self._double_mark_failure_success(700)
        self.assertEqual(self._alarm_times([1400, 4199, 4200]), [1400, 4199])

    def test_r3_01_double_mark_failure_silence_bounded(self):
        """Codex R3-01 в целевой форме: успех T, алярм T+600, успех T+662 без записи и удаления, права вернулись до отказа;
        отказы T+664+62k (до T+4198) и T+4200. Новая авария алармит в T+1222 (≤ 662 + 600 + 62), а не через 58 мин 56 с;
        далее повтор через ≥ 600 с."""
        self._main()
        self.assertEqual(self._alarm_times([600]), [600])
        self._double_mark_failure_success(662)
        got = self._alarm_times([664 + 62 * k for k in range(58)] + [4200])
        self.assertEqual(got, [1222, 1842, 2462, 3082, 3702])
        self.assertLessEqual(got[0], 662 + 600 + 62)

    def test_transient_classes_vs_immediate(self):
        self._main()
        near = self.NOW + 30
        for code, kind in [(None, "network"), (429, "api"), (429, "http")] + [(c, k) for c in (500, 502, 503, 599) for k in ("api", "http")]:
            rc, sent, out = self._main(self._net(code, kind), now=near)
            self.assertEqual(sent, [], ("транзиентный алармит сразу", code, kind))
        immediate = [self._net(c, k) for c in range(400, 500) if c != 429 for k in ("api", "http")]
        immediate += [self._net(None, "protocol"), self._net(None, None), self._net(None, "api"), self._net(True, "api"),
                      self._net(600, "api"), self._net(399, "http")]
        immediate += [OSError("io"), ValueError("people form"), poll.ss.StateError("state"), poll.commit_mod.GitError("fetch", "d"), RuntimeError("x")]
        for exc in immediate:
            rc, sent, out = self._main(exc, now=near)
            self.assertEqual(rc, 10)
            self.assertTrue(sent and "сбой поллера" in sent[0][1], ("нетранзиентный не алармит сразу", exc, out))

    def test_missing_corrupt_or_future_mark_alarms_conservatively(self):
        """Порча отметки — алярм. Фикстуры — ПОЛНЫЕ отметки (с last_seen), порчено ровно одно поле, поэтому проверка доходит
        до условия; валидный контроль тех же моментов (и с переставленными ключами) — тишина."""
        rc, sent, out = self._main(self._net())                        # отметки нет (CI-форма, свежий клон)
        self.assertTrue(sent, out)
        ok, N = self.NOW - 30, self.NOW
        def full(last_ok="%d" % ok, alarmed_at="null", last_seen="%d" % ok):
            return '{"last_ok": %s, "alarmed_at": %s, "last_seen": %s}' % (last_ok, alarmed_at, last_seen)
        for raw in (full(), '{ "last_seen" : %d , "alarmed_at":null,"last_ok":%d }' % (ok, ok),
                    full(alarmed_at="%d" % ok), full(alarmed_at="%d" % N, last_seen="%d" % N)):
            self._set_mark(raw)
            rc, sent, out = self._main(self._net(), now=N)
            self.assertEqual((rc, sent), (10, []), ("валидная отметка не подавила — контроль фикстур", raw, out))
        corrupt = ["", "{", "[]", "null", '"str"', "1", "[" * 200000 + "]" * 200000, b"\xff\xfe{}",
                   '{"alarmed_at": null, "last_seen": %d}' % ok,                         # нет last_ok
                   '{"last_ok": %d, "alarmed_at": null}' % ok]                           # нет last_seen (старая форма)
        for v in ('"x"', "true", "-1e309", "1e309", "NaN", "Infinity", "9" * 400, "0", "-5", "100000000000"):
            corrupt.append(full(last_ok=v))
        corrupt.append(full(last_ok="%d" % (N + 100), last_seen="%d" % (N + 100)))         # отметка из будущего
        for v in ('"x"', "true", "NaN", "%d" % (ok - 30), "%d" % (N + 100), "100000000000"):
            corrupt.append(full(last_seen=v))                                             # порча, < last_ok, из будущего
        for v in ('"bad"', "true", "NaN", "%d" % (N + 50), "%d" % (ok - 60), "100000000000"):
            corrupt.append(full(alarmed_at=v))                                            # порча, будущее, раньше last_ok
        for raw in corrupt:
            self._set_mark(raw)
            rc, sent, out = self._main(self._net(), now=N)
            self.assertEqual(rc, 10, raw[:80])
            self.assertTrue(sent, ("порча отметки подавила алярм", raw[:80], out))

    def test_mark_write_failure_does_not_break_poller(self):
        os.makedirs(self._path())                                       # путь отметки занят каталогом
        rc, sent, out = self._main()
        self.assertEqual(rc, 0, out)
        self.assertIn("transport-mark: не записана", out)
        rc, sent, out = self._main(self._net())
        self.assertTrue(sent, out)                                      # отметки нет → консервативно алармим

    def test_write_fails_remove_succeeds_resets_suppression(self):
        """Удачный цикл: запись отметки отказала (tmp занят каталогом), удаление удалось — старое окно повтора не живёт."""
        self._main()
        self.assertEqual(self._alarm_times([600]), [600])
        tmp = self._path() + ".tmp"
        os.makedirs(tmp)
        rc, sent, out = self._main(now=self.NOW + 700)
        self.assertEqual(rc, 0, out)
        self.assertIn("transport-mark: не записана", out)
        self.assertFalse(os.path.exists(self._path()), "старая отметка не удалена")
        os.rmdir(tmp)
        self.assertEqual(self._alarm_times([710]), [710])

    def test_unwritable_mark_never_suppresses(self):
        """Отметку не обновить (каталог 0500) — подавлению не доверяем: алярм сразу и при свежем успехе."""
        self._main()
        d = os.path.dirname(self._path())
        os.chmod(d, 0o500)
        try:
            rc, sent, out = self._main(self._net(), now=self.NOW + 30)
            self.assertTrue(sent, out)
            self.assertIn("transport-mark: не записана", out)
        finally:
            os.chmod(d, 0o755)

    def test_unwritable_mark_after_recovery_does_not_keep_suppression(self):
        self._main()
        self._set_mark('{"last_ok": %d, "alarmed_at": %d, "last_seen": %d}' % (self.NOW, self.NOW + 600, self.NOW + 600))
        d = os.path.dirname(self._path())
        os.chmod(d, 0o500)                                              # ни записать, ни удалить
        try:
            rc, sent, out = self._main(now=self.NOW + 700)               # восстановление — отметку не обновить
            self.assertEqual(rc, 0, out)
            self.assertIn("transport-mark: не записана", out)
            rc, sent, out = self._main(self._net(), now=self.NOW + 1400)
            self.assertTrue(sent, ("старое подавление пережило восстановление", out))
        finally:
            os.chmod(d, 0o755)

    def test_undelivered_alarm_does_not_start_realarm_window(self):
        self._main()                                                    # last_ok = NOW
        rc, sent, out = self._main(self._net(), now=self.NOW + 600, send_fails=True)
        self.assertEqual(sent, [])
        self.assertEqual(self._mark()["alarmed_at"], None, "недоставленный алярм открыл окно тишины")
        rc, sent, out = self._main(self._net(), now=self.NOW + 662)     # отправка снова доступна
        self.assertTrue(sent, out)
        self.assertEqual(self._mark()["alarmed_at"], self.NOW + 662)

    def test_decision_failure_alarms(self):
        """Сбой решения или учёта отметки (инъекция не-OSError в чтение и в запись отметки) — алярм уходит, rc прежний
        (10 у отказа, 0 у успеха), поллер не падает: все точки входа M5 в main() — решение, учёт алярма, учёт успеха."""
        def broken(*a, **kw): raise RuntimeError("инъекция")
        for name in ("_read_mark", "_write_mark"):
            self._main()
            orig = getattr(poll, name)
            setattr(poll, name, broken)
            try:
                rc, sent, out = self._main(self._net(), now=self.NOW + 30)
                self.assertEqual(rc, 10, (name, out))
                self.assertEqual(len(sent), 1, (name, out))
                self.assertIn("transport: сбой решения (RuntimeError)", out)
                self.assertIn("transport-mark: сбой учёта (RuntimeError)", out)
                rc, sent, out = self._main(now=self.NOW + 40)
                self.assertEqual(rc, 0, (name, out))
                self.assertIn("processed=0", out)
            finally:
                setattr(poll, name, orig)

    def test_scale_day_long_outage(self):
        """Масштаб: сутки аварии с шагом 62 с (сброс + backoff 60 + пауза 2). Идеал: первый алярм на первом отказе ≥ 600 с,
        далее — на первом ≥ 600 с после доставленного: шаг 62 → каждые 10 отказов (620 с)."""
        self._main()
        times = list(range(62, 86400 + 1, 62))
        expect, last = [], None
        for t in times:                                                 # идеал на истинной истории, независимо от модуля
            if t >= 600 and (last is None or t - last >= 600):
                expect.append(t); last = t
        self.assertEqual(self._alarm_times(times), expect)
        self.assertEqual(len(expect), 139)

    def test_real_transport_keeps_http_status_and_kind(self):
        """Настоящий default_opener + Transport.call: HTTP 401/403/404 без JSON-тела — не транзиентны; 502/503 HTML/пусто —
        транзиентны; обрыв/таймаут — kind network; не-JSON при 2xx — protocol."""
        import io, urllib.error, socket
        tg = poll.tg
        orig = tg.urllib.request.urlopen
        def http(code, body):
            def f(req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(body))
            return f
        def unreadable(code):
            class FP(io.BytesIO):
                def read(self, *a): raise OSError("gone")
            def f(req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, FP())
            return f
        class R(object):
            def __init__(self, b): self.b = b
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self.b
        cases = [(http(401, b""), False, 401, "http"), (http(403, b"<html>forbidden</html>"), False, 403, "http"),
                 (http(404, b"<html>nf</html>"), False, 404, "http"),
                 (unreadable(401), False, 401, "http"), (unreadable(502), True, 502, "http"),
                 (http(502, b"<html>bad gateway</html>"), True, 502, "http"), (http(503, b""), True, 503, "http"),
                 (http(401, b'{"ok": false, "error_code": 401, "description": "Unauthorized"}'), False, 401, "api"),
                 (http(400, b'{"ok": false, "error_code": 400, "description": "Bad Request"}'), False, 400, "api"),
                 (http(429, b'{"ok": false, "error_code": 429, "description": "Too Many Requests"}'), True, 429, "api"),
                 (http(500, b'{"ok": false, "error_code": 500, "description": "Internal"}'), True, 500, "api"),
                 (lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError(ConnectionResetError(104, "reset"))), True, None, "network"),
                 (lambda req, timeout=None: (_ for _ in ()).throw(socket.timeout("timed out")), True, None, "network"),
                 (lambda req, timeout=None: (_ for _ in ()).throw(ConnectionResetError(104, "reset")), True, None, "network"),
                 (lambda req, timeout=None: R(b"<html>ok?</html>"), False, None, "protocol"),
                 (lambda req, timeout=None: R(b'{"result": 1}'), False, None, "protocol")]
        try:
            for opener, transient, code, kind in cases:
                tg.urllib.request.urlopen = opener
                with self.assertRaises(tg.TransportError) as cm:
                    tg.Transport("123:abc", 5).call("getUpdates", {})
                e = cm.exception
                self.assertEqual((e.error_code, e.kind), (code, kind), str(e))
                self.assertEqual(poll._is_transient_transport(e), transient, str(e))
                self.assertNotIn("123:abc", str(e))
        finally:
            tg.urllib.request.urlopen = orig


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
        F["reask_correction"] = lambda: self.run_poll([msg("не 3.25, а 1.25 часа", chat_type="private")])   # T8: маркер исправления реестра форм → исход 6, записи нет
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
        F["summary_given"] = lambda: self.run_poll([msg(TOK["summary"] + " team")])   # D15: чистое чтение, advance
        # T8: отзыв своей строки / возврат по номеру / нечего отзывать
        F["retracted"] = lambda: self.run_poll([msg("2ч работа", date=T0), msg(TOK["undo"] + " по ошибке", date=T0 + 60)])
        F["unretracted"] = lambda: self.run_poll([msg("2ч работа", date=T0), msg(TOK["undo"], date=T0 + 60), msg(TOK["last"], date=T0 + 120), msg(TOK["undo"] + " 1 вернуть", date=T0 + 180)])
        F["reask_undo_not_found"] = lambda: self.run_poll([msg(TOK["undo"])])
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
        self.assertTrue(rows); self.assertEqual(len({r[1] for r in rows}), len(rows))   # D15: число — из реестра, без дублей id
        table = ["  offset-table (исход: offset до → после; advances по контракту)"]
        seen = set()
        for oid, name, adv in rows:
            if name in ("session_stale", "session_cancelled"):
                table.append("  %2d %-26s неприменимо (порождается сторожем T5, к offset отношения не имеет)" % (oid, name)); seen.add(name); continue
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
        self.assertEqual(seen, {r[1] for r in rows})   # D15: множество исполненных исходов == реестр, не мощность
        out = os.environ.get("D09_OFFSET_TABLE")   # selfcheck_t3.sh печатает таблицу из этого файла; поток unittest не засоряется
        if out:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\n".join(table) + "\n")



    def test_reask_long_variable_part_keeps_help_pointer(self):
        """Раунд 1, №2/№9: длинный заголовок в переспросе обрезается, указатель на справку остаётся целиком."""
        long_title = "очень длинный заголовок " * 12
        r, t, _ = self.run_poll([msg(TOK["start_title"] + " " + long_title.strip(), date=T0), msg(TOK["start_title"] + " y", date=T0 + 60)])
        self.assertEqual(r["outcomes"][-1][1], "reask_start_already_open")
        reply = t.sent[-1][1]
        self.assertLessEqual(len(reply), poll.SHORT_REPLY_MAX)
        self.assertEqual(len(reply.split("\n")), 1)
        self.assertIn("…", reply)
        self.assertTrue(reply.endswith(poll.build_help.help_token(_.commands_doc) + " — команды и примеры"), reply)


    def test_reask_long_variable_parts_keep_every_fixed_fragment(self):
        """Раунд 2, W2: фиксированные части ПОСЛЕ переменной (время начала, подсказка закрытия, «поправь и пришли снова»)
        уцелевают при переменной части 0/100/300 символов — все шесть reask_* (у 4 и 23 с ЭРРАТЫ D10 «А» переменной части нет)."""
        ctx = poll.Ctx(self.s.root, FakeTransport([]), self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
        help_tail = poll.build_help.help_token(ctx.commands_doc) + " — команды и примеры"
        for n in (0, 100, 300):
            var = "з" * n
            cases = {
                "reask_invalid": (poll.reply_text(ctx, "reask_invalid", None, {}, {"rule": var}), ["не записал: валидатор отверг строку — правило ", ". Поправь и пришли снова."]),
                "reask_correction": (poll.reply_text(ctx, "reask_correction", None, {}), ["часы на месте бот не правит", "поправить — в приложении. Не записано."]),
                "reask_start_already_open": (poll.reply_text(ctx, "reask_start_already_open", {"reply": {"title": var, "started_at_local": "2026-09-07T16:00:00+02:00"}}, {}), ["учёт уже открыт: «", "» с 2026-09-07T16:00:00+02:00. Закрыть — ", TOK["stop"] + "."]),
                "reask_stop_without_open": (poll.reply_text(ctx, "reask_stop_without_open", None, {}), ["открытого учёта нет."]),
            }
            for oc, (reply, fixed) in cases.items():
                self.assertLessEqual(len(reply), poll.SHORT_REPLY_MAX, (oc, n, reply))
                self.assertEqual(len(reply.split("\n")), 1, (oc, n))
                self.assertTrue(reply.endswith(help_tail), (oc, n, reply))
                for frag in fixed:
                    self.assertIn(frag, reply, (oc, n, frag, reply))
                if n >= 300 and oc not in ("reask_correction", "reask_stop_without_open"):
                    self.assertIn("…", reply, (oc, n))      # обрезана переменная часть, и только она
            # ЭРРАТА D10 «А»: у исходов 4 и 23 причины в ответе НЕТ вовсе (человеческая фраза реестра; причина вне
            # реестра — фраза-заглушка): ни байта переменной части, одна строка, указатель справки цел, обрезать нечего
            for oc in ("reask_unparsed", "reask_undo_not_found"):
                reply = poll.reply_text(ctx, oc, {"reply": {"reason": var}}, {})
                self.assertLessEqual(len(reply), poll.SHORT_REPLY_MAX, (oc, n, reply))
                self.assertEqual(len(reply.split("\n")), 1, (oc, n))
                self.assertTrue(reply.endswith(help_tail), (oc, n, reply))
                self.assertNotIn("…", reply, (oc, n))
                if n:
                    self.assertNotIn("зз", reply, (oc, n, reply))

    def test_main_turns_any_exception_into_tool_failure_with_alarm(self):
        """Раунд 2 W3 / раунд 3 W1+R3: ЛЮБОЕ исключение поллера (все прежние «тихие» классы включительно) → TOOL_FAILURE
        rc=10 + алярм по карте, прочитанной до прогона; без bot.yaml — TOOL_FAILURE, не трейсбек."""
        import io, contextlib, shutil, tempfile
        sent = []
        class T(object):
            def __init__(self, *a, **kw): pass
            def call(self, method, params): return {"username": "x"}
            def send_message(self, chat_id, text, **kw): sent.append((chat_id, text)); return {}
        orig_tr, orig_run, orig_cwd = poll.tg.Transport, poll.run_once, os.getcwd()
        excs = [RecursionError("deep"), poll.ss.StateError("state"), poll.commit_mod.GitError("fetch", "detail"), OSError("io"), ValueError("people form"), RuntimeError("x")]
        stage = {"getme": None}
        class T2(T):
            def call(self, method, params):
                if stage["getme"] is not None: raise stage["getme"]
                return {"username": "x"}
        try:
            poll.tg.Transport = T2
            # матрица (раунд 4, W1): стадия {прогон, getMe} × 6 классов исключений → rc=10, TOOL_FAILURE, алярм
            for where in ("run", "getme"):
                for exc in excs:
                    del sent[:]; stage["getme"] = exc if where == "getme" else None
                    def boom(ctx, _e=exc): raise _e
                    poll.run_once = boom
                    out = io.StringIO()
                    os.chdir(self.s.root)
                    with contextlib.redirect_stdout(out):
                        rc = poll.main()
                    self.assertEqual(rc, 10, (where, type(exc).__name__))
                    self.assertIn("TOOL_FAILURE %s" % type(exc).__name__, out.getvalue())
                    self.assertTrue(sent and "сбой поллера" in sent[0][1], (where, type(exc).__name__, sent, out.getvalue()))
            stage["getme"] = None
            # порченая секция watchdog (строка/список/число/bool) — аварийный контур замкнут: rc=10, алярм admins (раунд 5, W1)
            cfg_path = os.path.join(self.s.root, ".workshop", "bot.yaml"); keep_cfg = open(cfg_path, "rb").read()
            try:
                for bad in ("watchdog: строка\n", "watchdog: [1, 2]\n", "watchdog: 7\n", "watchdog: true\n"):
                    body = re.sub(r"(?ms)^watchdog:\n(?:[ \t]+.*\n)*", "", keep_cfg.decode("utf-8"))
                    with open(cfg_path, "wb") as fh:
                        fh.write((body.rstrip("\n") + "\n" + bad).encode("utf-8"))
                    del sent[:]
                    def boom2(ctx): raise OSError("probe")
                    poll.run_once = boom2
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        rc = poll.main()
                    self.assertEqual(rc, 10, bad); self.assertIn("TOOL_FAILURE OSError", out.getvalue())
                    self.assertTrue(sent and "сбой поллера" in sent[0][1], (bad, sent, out.getvalue()))
            finally:
                with open(cfg_path, "wb") as fh:
                    fh.write(keep_cfg)
            # порча карты людей ДО прогона: адресатов по карте нет, но rc=10 и TOOL_FAILURE есть, трейсбека нет
            del sent[:]
            people_path = os.path.join(self.s.root, ".workshop", "people.yaml"); keep = open(people_path, "rb").read()
            with open(people_path, "wb") as fh:
                fh.write(b"people: [\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = poll.main()
            with open(people_path, "wb") as fh:
                fh.write(keep)
            self.assertEqual(rc, 10); self.assertIn("TOOL_FAILURE", out.getvalue())
            # без bot.yaml — TOOL_FAILURE rc=10, не исключение интерпретатора
            empty = tempfile.mkdtemp()
            try:
                os.chdir(empty); out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = poll.main()
                self.assertEqual(rc, 10); self.assertIn("TOOL_FAILURE", out.getvalue())
            finally:
                os.chdir(orig_cwd); shutil.rmtree(empty, ignore_errors=True)
        finally:
            poll.tg.Transport, poll.run_once = orig_tr, orig_run
            os.chdir(orig_cwd)

    def test_short_template_contract(self):
        """Раунд 3, R2: фиксированные части никогда не режутся — шаблон длиннее лимита отвергается явно; нулевой
        бюджет опускает переменную без «…»; несколько переменных делят бюджет."""
        with self.assertRaises(ValueError):
            poll._short(["A" * 150, ("v" * 300, True), "FIXED_END"], "/tail")
        r = poll._short(["A" * 150, ("v" * 300, True), "END"], "/tail")   # 150+3+6 = 159 ≤ 160: бюджет переменной 1 → «…»
        self.assertEqual(r, "A" * 150 + "…END /tail")
        r = poll._short(["A" * 151, ("v" * 300, True), "END"], "/tail")   # бюджет 0 → переменная опущена без «…»
        self.assertEqual(r, "A" * 151 + "END /tail")
        r = poll._short(["a ", ("x" * 200, True), " b ", ("y" * 200, True), " c"], "/t")
        self.assertLessEqual(len(r), poll.SHORT_REPLY_MAX); self.assertTrue(r.startswith("a ") and " b " in r and r.endswith(" c /t"))
        self.assertEqual(r.count("…"), 2)


    def test_reask_is_one_line_for_any_unicode_line_break(self):
        """Раунд 7, W1: CR, CRLF, VT, FF, NEL, LS, PS в переменной части → один пробел; ответ — одна строка по splitlines()."""
        ctx = poll.Ctx(self.s.root, FakeTransport([]), self.cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
        for br in ("\n", "\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\n\n\r"):   # раунд 8: весь репертуар splitlines()
            for n in (1, 30):
                var = ("unknown_command:/unknown" + br + "next") * n
                for oc, dec, extra in (("reask_unparsed", {"reply": {"reason": var}}, None), ("reask_invalid", None, {"rule": var}),
                                       ("reask_start_already_open", {"reply": {"title": var, "started_at_local": "2026-09-07T16:00:00+02:00"}}, None),
                                       ("reask_undo_not_found", {"reply": {"reason": var}}, None)):
                    reply = poll.reply_text(ctx, oc, dec, {}, extra)
                    self.assertEqual(len(reply.splitlines()), 1, (oc, repr(br), n, reply))
                    self.assertLessEqual(len(reply), poll.SHORT_REPLY_MAX)
                    self.assertTrue(reply.endswith(" — команды и примеры"), reply)


    def test_callback_gate_precedes_every_dispatch(self):
        """Раунд 7 Fable, B1: нажатие кнопки по КАЖДОЙ позиции реестра — либо исполняется (callback_allowed ∧ не
        time_bearing), либо reask_unparsed с причиной; никогда TOOL_FAILURE/исключение; offset продвигается."""
        self.run_poll([msg("2ч созвон", date=T0)])
        for pos in self.cfg_registry_positions():
            token = pos["token"] or ""
            data = {"start_title": token + " x", "start_n": token + " 1", "undo": token + " 1", "track": token + " 10:00-11:00 x",
                    "free_text": "1ч x", "summary": token + " all"}.get(pos["id"], token or "просто текст")   # синтаксически верный аргумент: судится гейт кнопки, не разбор
            r, t, ctx = self.run_poll([callback(data)])
            oc = r["outcomes"][-1][1]
            self.assertNotIn(oc, ("tool_failure",), (pos["id"], oc))
            if pos["time_bearing"]:
                self.assertEqual(oc, "reask_unparsed", pos["id"]); self.assertEqual(botrepo.traced_reason(ctx), "callback_time_bearing"); self.assertNotIn("callback_time_bearing", t.sent[-1][1])
            elif not pos["callback_allowed"]:
                self.assertEqual(oc, "reask_unparsed", pos["id"]); self.assertEqual(botrepo.traced_reason(ctx), "callback_not_allowed"); self.assertNotIn("callback_not_allowed", t.sent[-1][1])
            else:
                self.assertNotEqual(oc, "reask_unparsed", (pos["id"], oc, t.sent[-1][1] if t.sent else None))
            self.assertEqual(self.offset(), r["outcomes"][-1][0] + 1)

    def cfg_registry_positions(self):
        return [p for p in poll.yamlmini.load_file(os.path.join(os.path.dirname(__file__), "..", "kit", "commands.yaml"))["commands"] if p["id"] != "confirm"]

    def test_undelivered_reply_and_long_list_do_not_stall_poller(self):
        """Раунд 7 Fable, B2: (а) список из многих заголовков — частями ≤ 4096, N ограничен last_max_n; (б) отказ
        доставки ответа (403 «бот заблокирован») — исход стоит, offset продвигается, поллер не падает."""
        for k in range(120):
            self.run_poll([msg("1ч заголовок номер %d %s" % (k, "x" * 60), date=T0 + k * 100)])
        r, t, ctx = self.run_poll([msg(TOK["last"] + " 9999", date=T0 + 100000)])
        self.assertEqual(r["outcomes"][-1][1], "last_list_given")
        self.assertTrue(all(len(x[1]) <= poll.TG_TEXT_MAX for x in t.sent), [len(x[1]) for x in t.sent])
        listed = sum(1 for x in t.sent for ln in x[1].split("\n") if re.match(r"\s*\d+[.)]", ln))
        self.assertLessEqual(listed, int(self.cfg.get("last_max_n", 50)))
        for k, exc in enumerate((poll.tg.TransportError("sendMessage: Forbidden: bot was blocked by the user", "sendMessage", "blocked", 403),
                                 poll.tg.TransportError("sendMessage: ConnectionResetError: reset", "sendMessage"))):   # раунд 10 A (m06): и без error_code
            class Blocked(FakeTransport):
                def send_message(self, chat_id, text, **kw):
                    raise exc
            t = Blocked([msg("1ч после блокировки %d" % k, date=T0 + 200000 + k * 100)])
            ctx = poll.Ctx(self.s.root, t, self.cfg, botrepo.VALIDATOR, bot_username="cp_workshop_test_bot", sleeper=lambda x: None)
            r = poll.run_once(ctx)
            self.assertEqual(r["outcomes"][-1][1], "recorded", r["outcomes"])
            self.assertEqual(self.offset(), r["outcomes"][-1][0] + 1)
            self.assertTrue(any("send_failed" in ln for ln in ctx.trace.lines()))


    def test_leading_invisible_chars_keep_byte_contracts(self):
        """Раунд 9 Fable, W1: невидимые символы (BOM/LRM/ZWSP) в начале сообщения не создают фантомного хвоста/коммента и
        не ломают подтверждение: байты хвоста/тела считаются от исходной строки."""
        cm = os.path.join(self.s.root, "time", "TIMESHEET-2026-09-dev-one.comments.md")
        def blocks():
            return open(cm, "rb").read().count(b"<!--c:") if os.path.exists(cm) else 0
        # контроль: тот же цикл без невидимых символов — число комментов после него есть эталон класса
        self.run_poll([msg(TOK["start_title"] + " созвон", date=T0 - 20000, chat_type="private"), msg(TOK["stop"], date=T0 - 16400, chat_type="private")])
        per_cycle = blocks()
        self.run_poll([msg(TOK["undo"], date=T0 - 16000, chat_type="private")])
        for inv in ("\ufeff", "\u200e", "\u200b"):
            before = blocks()
            r, t, ctx = self.run_poll([msg(inv + TOK["start_title"] + " созвон", date=T0, chat_type="private"), msg(inv + TOK["stop"], date=T0 + 3600, chat_type="private")])
            ocs = [x[1] for x in r["outcomes"]]
            self.assertIn(ocs[-1], ("session_closed_recorded", "reask_unparsed"), (repr(inv), ocs, t.sent[-1][1] if t.sent else None))
            if ocs[-1] == "session_closed_recorded":
                self.assertEqual(blocks() - before, per_cycle, (repr(inv), "число комментов ≠ эталону цикла: фантомный коммент из хвоста"))   # раунд 10 B: класс, не пример
            self.run_poll([msg(TOK["stop"], date=T0 + 7000, chat_type="private"), msg(TOK["undo"], date=T0 + 7200, chat_type="private")])

    def test_start_n_beyond_shown_list_is_reask(self):
        """Раунд 9 Fable (мутант m05): повтор по N больше предела показа — переспрос, не повтор невидимой строки."""
        cap = int(self.cfg.get("last_max_n", 50))
        for k in range(cap + 2):
            self.run_poll([msg("1ч строка %d" % k, date=T0 + k * 100)])
        self.run_poll([msg(TOK["last"] + " 9999", date=T0 + 100000)])
        r, t, _ = self.run_poll([msg(TOK["start_n"] + " %d" % (cap + 1), date=T0 + 100010)])
        self.assertEqual(r["outcomes"][-1][1], "reask_unparsed", r["outcomes"])


    def test_state_is_reread_after_fast_forward(self):
        """Раунд 10 A (m03): после fast-forward до origin файлы состояния перечитываются — чужой push, открывший учёт
        dev-one, виден следующему же батчу (иначе закрытие отвечало бы «открытого учёта нет»)."""
        other = self.s.other_clone()
        doc = poll.ss.read_sessions(other)
        doc = poll.ss.open_session(doc, "dev-one", {"title": "чужое открытие", "start_text": "чужое открытие", "started_at": T0 - 3600,
                                                    "started_at_local": "2026-09-07T15:23:10+02:00", "chat_id": CHAT, "start_update_id": 7,
                                                    "start_message_id": 7, "schema_version": 1})
        poll.ss.write_sessions(other, doc)
        git(other, "commit", "-qam", "foreign open for dev-one"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, ctx = self.run_poll([msg(TOK["stop"], date=T0)])
        self.assertEqual(r["outcomes"][-1][1], "session_closed_recorded", (r["outcomes"], t.sent[-1][1] if t.sent else None))


    def test_topic_replies_stay_in_thread_and_pending_name_carries_tag(self):
        """Пост-D09 (форум-группа PadelApp): ответы на команду и на кнопку уходят в топик сообщения (message_thread_id),
        обычный чат — без топика; самозапись несёт имя и @тег из мессенджера."""
        def topic(u, tid=77):
            m = u["message"]; m["is_topic_message"] = True; m["message_thread_id"] = tid; return u
        r, t, ctx = self.run_poll([topic(msg("1ч в топике", date=T0))])
        self.assertEqual(r["outcomes"][-1][1], "recorded"); self.assertEqual(t.threads[-1], 77)
        r, t, ctx = self.run_poll([msg("1ч без топика", date=T0 + 100)])
        self.assertEqual(t.threads[-1], None)
        r, t, ctx = self.run_poll([topic(msg(TOK["last"], date=T0 + 200), 78)])
        self.assertEqual(t.threads[-1], 78)
        cb = callback(TOK["help"]); cb["callback_query"]["message"]["is_topic_message"] = True; cb["callback_query"]["message"]["message_thread_id"] = 79
        r, t, ctx = self.run_poll([cb])
        self.assertEqual(r["outcomes"][-1][1], "help_given"); self.assertEqual(t.threads[-1], 79)
        u = msg("1ч новичок", from_id=UNKNOWN_ID, date=T0 + 300); u["message"]["from"]["username"] = "new_dev"; u["message"]["from"]["first_name"] = "Нови"
        r, t, ctx = self.run_poll([u])
        self.assertEqual(r["outcomes"][-1][1], "recorded")
        people = open(os.path.join(self.s.root, ".workshop", "people.yaml"), encoding="utf-8").read()
        self.assertIn("Нови @new_dev", people)

if __name__ == "__main__":
    unittest.main()
