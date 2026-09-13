# -*- coding: utf-8 -*-
"""Оракул отзыва (T8, REQ-093) — стенд botrepo (bare-origin + клон + фейковый транспорт + НАСТОЯЩИЙ
валидатор). Ожидания — из БАЙТОВ файлов и git-журнала: свой разбор строк и заголовков комментов, своя
чётность цепочек отзывов, свои суммы; функции undo.py оракул не импортирует. Матрица G14 — пакетом."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import botrepo  # noqa: E402
from botrepo import Stand, FakeTransport, msg, git, TOK, ADMIN_ID, DEV3_ID  # noqa: E402
import yamlmini, poll  # noqa: E402

TS = "time/TIMESHEET-2026-09-dev-one.md"
CM = "time/TIMESHEET-2026-09-dev-one.comments.md"
T0 = 1788790990  # 2026-09-07T14:23:10Z
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) +(\d+\.\d{2})(?: +\S+/\S+)?  (.*?) ?<!--t:([0-9a-f]{8})-->$")
HDR = re.compile(r"^### (\S+) · (\S+) <!--c:([0-9a-f-]{36}) (retracts:t:|retracts:|about:t:)(\S+)-->$")   # свой regex; токен времени — любой (доли секунд валидны)


class Oracle(object):
    """Свой разбор контейнера и спутника; действие коммента и строки — «нет/есть хотя бы один действующий отзыв» (своя реализация)."""
    def __init__(self, root):
        self.root = root

    def lines(self, rel=TS):
        p = os.path.join(self.root, rel)
        if not os.path.exists(p):
            return []
        body = open(p, "rb").read().decode("utf-8").split("\n---\n", 1)[1]
        out = []
        for ln in body.split("\n"):
            m = LINE.match(ln)
            if m:
                out.append({"date": m.group(1), "hours": m.group(2), "title": m.group(3), "anchor": m.group(4)})
        return out

    def blocks(self, rel=CM):
        p = os.path.join(self.root, rel)
        if not os.path.exists(p):
            return []
        raw = open(p, "rb").read()
        heads = []
        cur = None
        for lb in raw.split(b"\n")[2:]:      # после заголовка спутника и пустой строки
            try:
                s = lb.decode("utf-8")
            except UnicodeDecodeError:
                s = None
            m = HDR.match(s) if s is not None else None
            if m:
                cur = {"ts": m.group(1), "author": m.group(2), "cid": m.group(3), "link": m.group(4), "target": m.group(5), "body": []}
                heads.append(cur)
            elif cur is not None:
                cur["body"].append(lb)
        for h in heads:
            b = b"\n".join(h["body"])
            h["body"] = b[:-1] if b.endswith(b"\n") else b
        return heads

    def active(self, cid, heads, seen=()):
        """Идемпотентность по цели и для комментов (раунд 1, №6): коммент действует ⟺ нет ни одного действующего retracts:<cid>."""
        if cid in seen:
            return False
        return not any(h["link"] == "retracts:" and h["target"] == cid and self.active(h["cid"], heads, seen + (cid,)) for h in heads)

    def retracted(self, anchor, heads):
        """Идемпотентность по цели: хотя бы один ДЕЙСТВУЮЩИЙ отзыв → отозвана (D04 гл. 05 §4.3)."""
        return sum(1 for h in heads if h["link"] == "retracts:t:" and h["target"] == anchor and self.active(h["cid"], heads)) >= 1

    def hours_in_account(self):
        heads = self.blocks()
        cents = 0
        for l in self.lines():
            if not self.retracted(l["anchor"], heads):
                cents += int(l["hours"].replace(".", ""))
        return cents


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.s = Stand()
        self.cfg = yamlmini.load_file(os.path.join(self.s.root, ".workshop", "bot.yaml"))
        self.o = Oracle(self.s.root)

    def tearDown(self):
        self.s.close()

    def run_poll(self, updates, validator=None, transport=None):
        t = transport or FakeTransport(updates)
        ctx = poll.Ctx(self.s.root, t, self.cfg, validator or botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
        return poll.run_once(ctx), t, ctx

    def commits(self):
        return git(self.s.root, "log", "--format=%s", "origin/main").strip().split("\n")

    def test_matrix_g14_batch(self):
        s, o = self.s, self.o
        rows = []
        def m(name, cond, detail=""):
            rows.append("  %-4s %-52s %s" % ("PASS" if cond else "FAIL", name, detail)); self.assertTrue(cond, name + " " + detail)
        # запись двух строк
        self.run_poll([msg("2ч созвон", date=T0), msg("1ч ревью", date=T0 + 10)])
        before = self.commits(); self.assertEqual(o.hours_in_account(), 300)
        container_before = s.read(TS)
        # 1. своя последняя (без N) → отозвана, ОДИН коммит, контейнер побайтово не изменился, тело = байты сообщения
        u = msg(TOK["undo"] + " по ошибке\nвторая строка причины", date=T0 + 20)
        r, t, _ = self.run_poll([u])
        after = self.commits()
        m("1 своя последняя → retracted", r["outcomes"][-1][1] == "retracted", str(r["outcomes"]))
        m("1a один коммит на сообщение", len(after) == len(before) + 1, "%d → %d" % (len(before), len(after)))
        m("1b контейнер побайтово не изменился", s.read(TS) == container_before)
        b = o.blocks()
        m("1c тело коммента cmp-равно байтам сообщения", b[-1]["body"] == u["message"]["text"].encode("utf-8"), repr(b[-1]["body"][:40]))
        m("1d автор — handle человека, связка retracts:t: на якорь строки «ревью»", b[-1]["author"] == "dev-one" and b[-1]["link"] == "retracts:t:" and b[-1]["target"] == [l for l in o.lines() if l["title"] == "ревью"][0]["anchor"])
        m("1e сумма оракула исключает отозванную", o.hours_in_account() == 200, str(o.hours_in_account()))
        m("1f ответ называет строку", "«ревью»" in t.sent[-1][1] and "отозвано" in t.sent[-1][1], t.sent[-1][1][:60])
        # 2. повтор ТОГО ЖЕ update после push → identical (правило Т по id коммента), второго блока нет
        t2 = FakeTransport([u]); t2.get_updates = lambda **kw: [u]
        r, _, _ = self.run_poll([u], transport=t2)
        m("2 повтор update после push → identical_repeat, блок один", r["outcomes"][-1][1] == "identical_repeat" and len(o.blocks()) == 1, str(r["outcomes"]))
        # 3. по N: возврат по номеру отозванной, затем повторный отзыв; чётность цепочки
        self.run_poll([msg(TOK["last"], date=T0 + 30)])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 1 вернуть", date=T0 + 40)])
        m("3 по N отозванная → unretracted (retracts:<c-id>)", r["outcomes"][-1][1] == "unretracted" and o.blocks()[-1]["link"] == "retracts:" and o.blocks()[-1]["target"] == b[-1]["cid"], str(r["outcomes"]))
        m("3a сумма вернулась", o.hours_in_account() == 300, str(o.hours_in_account()))
        r, _, _ = self.run_poll([msg(TOK["undo"] + " 1 снова", date=T0 + 50)])
        m("3b возврат возвращённой → снова retracted", r["outcomes"][-1][1] == "retracted" and o.hours_in_account() == 200)
        # 4. голый команды отзыва не переключает: отзывает СЛЕДУЮЩУЮ неотозванную, затем — нечего
        r, _, _ = self.run_poll([msg(TOK["undo"], date=T0 + 60)])
        m("4 без N → следующая неотозванная («созвон»)", r["outcomes"][-1][1] == "retracted" and o.hours_in_account() == 0)
        r, t, _ = self.run_poll([msg(TOK["undo"], date=T0 + 70)])
        m("4a без N при всём отозванном → reask no_line", r["outcomes"][-1][1] == "reask_undo_not_found" and "no_line" in t.sent[-1][1] and len(t.sent[-1][1].split("\n")) == 1)
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 9", date=T0 + 80)])
        m("4b N вне списка → n_out_of_range", r["outcomes"][-1][1] == "reask_undo_not_found" and "n_out_of_range" in t.sent[-1][1])
        # 5. чужая строка недосягаема: dev-three отзывает — у него нет строк
        r, t, _ = self.run_poll([msg(TOK["undo"], from_id=DEV3_ID, date=T0 + 90)])
        m("5 чужая строка → у другого человека no_line, файлы dev-one не тронуты", r["outcomes"][-1][1] == "reask_undo_not_found" and s.read(TS) == container_before)
        # 6. два независимых отзыва одной цели (второй канал) → возврат ОБОИХ одним коммитом
        heads = o.blocks(); target_anchor = [l for l in o.lines() if l["title"] == "созвон"][0]["anchor"]
        other = s.other_clone()
        foreign = ("### 2026-09-07T15:00:00Z · dev-one <!--c:01a07c50-0000-7000-8000-000000000001 retracts:t:%s-->\nвторой канал\n" % target_anchor).encode()
        with open(os.path.join(other, CM), "ab") as fh:
            fh.write(foreign)
        git(other, "commit", "-qam", "foreign retraction"); git(other, "push", "-q", "origin", "HEAD:main")
        self.run_poll([msg(TOK["last"], date=T0 + 100)])
        n_before = len(self.commits()); rets_before = len([h for h in o.blocks() if h["link"] == "retracts:"])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 2 вернуть созвон", date=T0 + 110)])
        heads = o.blocks(); rets_to = [h for h in heads if h["link"] == "retracts:"]
        m("6 два действующих отзыва (второй канал) → возврат ОБОИХ одним коммитом", r["outcomes"][-1][1] == "unretracted" and len(self.commits()) == n_before + 1 and not o.retracted(target_anchor, heads) and len(rets_to) == rets_before + 2, "%s блоков retracts: +%d" % (str(r["outcomes"]), len(rets_to) - rets_before))
        # 7. строка без якоря — не цель и не перескакивается
        with open(os.path.join(s.root, TS), "ab") as fh:
            fh.write("2026-09-08 0.50  рукописная без якоря\n".encode("utf-8"))
        git(s.root, "commit", "-qam", "hand"); git(s.root, "push", "-q", "origin", "main")
        r, t, _ = self.run_poll([msg(TOK["undo"], date=T0 + 120)])
        m("7 хвост без якоря → target_unanchored, ничего не отозвано", r["outcomes"][-1][1] == "reask_undo_not_found" and "target_unanchored" in t.sent[-1][1])
        sys.stderr.write("\n[G14 matrix] %d:\n%s\n" % (len(rows), "\n".join(rows)))

    def run_poll_with_prereconcile_push(self, updates, inject):
        """чужой push приезжает после выбора цели и ДО reconcile отзыва (гонка раунда 1, №4)."""
        orig = poll.commit_mod.reconcile
        def racing(*a, **kw):
            inject(); poll.commit_mod.reconcile = orig
            return orig(*a, **kw)
        poll.commit_mod.reconcile = racing
        try:
            return self.run_poll(updates)
        finally:
            poll.commit_mod.reconcile = orig

    def _append_foreign(self, clone, block, rel=CM):
        git(clone, "pull", "-q", "--ff-only", "origin", "main")   # второй писатель всегда пишет поверх актуального origin
        p = os.path.join(clone, rel)
        if not os.path.exists(p):
            cid = re.search(r"^id: (\S+)", open(os.path.join(clone, TS), "rb").read().decode("utf-8"), re.M).group(1)
            with open(p, "wb") as fh:
                fh.write(("<!-- comments-of: %s -->\n\n" % cid).encode())
        with open(p, "ab") as fh:
            fh.write(block)
        git(clone, "add", rel)

    def _foreign_block(self, link, target, k, body="второй канал"):
        return ("### 2026-09-07T15:00:0%dZ · dev-one <!--c:01a07c50-0000-7000-8000-00000000000%d %s%s-->\n%s\n" % (k, k, link, target, body)).encode()

    def test_target_changed_in_reconcile_is_reask_not_toggle(self):
        """Раунд 1, №4 (P13): чужой отзыв той же строки приезжает между выбором цели и reconcile → исход 23
        target_changed, блока нет; повтор команды после — уже возврат по актуальному состоянию."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        anchor = o.lines()[0]["anchor"]
        other = s.other_clone()
        def inject():
            self._append_foreign(other, self._foreign_block("retracts:t:", anchor, 1))
            git(other, "commit", "-qm", "foreign retraction"); git(other, "push", "-q", "origin", "HEAD:main")
        n = len(self.commits())
        r, t, _ = self.run_poll_with_prereconcile_push([msg(TOK["undo"], date=T0 + 20)], inject)
        self.assertEqual(r["outcomes"][-1][1], "reask_undo_not_found", r["outcomes"])
        self.assertIn("target_changed", t.sent[-1][1])
        self.assertEqual(len(self.commits()), n + 2)      # чужой коммит + коммит offset; спутник ботом не коммитился:
        self.assertEqual(git(s.root, "log", "--format=%s", "-1", "origin/main", "--", CM).strip(), "foreign retraction")
        self.assertEqual(len([h for h in o.blocks() if h["author"] == "dev-one" and h["link"] == "retracts:t:"]), 1)
        self.assertTrue(o.retracted(anchor, o.blocks()))
        # по актуальному списку: строка отозвана чужим каналом → отзыва без N нет (no_line), с N — возврат
        r, t, _ = self.run_poll([msg(TOK["undo"], date=T0 + 30)])
        self.assertEqual(r["outcomes"][-1][1], "reask_undo_not_found"); self.assertIn("no_line", t.sent[-1][1])
        self.run_poll([msg(TOK["last"], date=T0 + 40)])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 1", date=T0 + 50)])
        self.assertEqual(r["outcomes"][-1][1], "unretracted")
        self.assertFalse(o.retracted(anchor, o.blocks()))

    def test_two_returns_from_two_channels_are_one_return(self):
        """Раунд 1, №6 (P3): два независимых возврата одного отзыва (retracts:<c> дважды из двух каналов) =
        возврат, не повторный отзыв; следующий отзыв той строки — НОВЫЙ retracts:t:. Одновременный возврат
        (чужой приезжает в reconcile нашего) — target_changed, а не два блока."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0), msg(TOK["undo"], date=T0 + 10)])
        anchor = o.lines()[0]["anchor"]
        ret_cid = [h for h in o.blocks() if h["link"] == "retracts:t:"][0]["cid"]
        other = s.other_clone()
        # (а) одновременный возврат: наш отзыв по N вычислил «отозвана → возврат», чужой возврат приехал в reconcile
        self.run_poll([msg(TOK["last"], date=T0 + 15)])
        def inject():
            self._append_foreign(other, self._foreign_block("retracts:", ret_cid, 2, "возврат из фронта"))
            git(other, "commit", "-qm", "foreign return"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, _ = self.run_poll_with_prereconcile_push([msg(TOK["undo"] + " 1", date=T0 + 20)], inject)
        self.assertEqual(r["outcomes"][-1][1], "reask_undo_not_found"); self.assertIn("target_changed", t.sent[-1][1])
        heads = o.blocks()
        self.assertEqual(len([h for h in heads if h["link"] == "retracts:" and h["target"] == ret_cid]), 1)
        self.assertFalse(o.retracted(anchor, heads)); self.assertEqual(o.hours_in_account(), 200)
        # (б) второй возврат того же отзыва из ещё одного канала — идемпотентен: строка остаётся возвращённой
        self._append_foreign(other, self._foreign_block("retracts:", ret_cid, 3, "возврат из приложения"))
        git(other, "commit", "-qm", "foreign return 2"); git(other, "push", "-q", "origin", "HEAD:main")
        self.run_poll([msg(TOK["last"], date=T0 + 25)])
        heads = o.blocks()
        self.assertEqual(len([h for h in heads if h["link"] == "retracts:" and h["target"] == ret_cid]), 2)
        self.assertFalse(o.retracted(anchor, heads), "два возврата одного отзыва снова «отозвали» строку")
        # (в) отзыв заново по N: НОВЫЙ retracts:t:, не «отзыв возврата»
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 1", date=T0 + 30)])
        self.assertEqual(r["outcomes"][-1][1], "retracted", r["outcomes"])
        heads = o.blocks()
        self.assertEqual(len([h for h in heads if h["link"] == "retracts:t:" and h["target"] == anchor]), 2)
        self.assertTrue(o.retracted(anchor, heads)); self.assertEqual(o.hours_in_account(), 0)

    def test_deep_retraction_chain_and_ring_do_not_crash_poller(self):
        """Раунд 2, W3: цепочка «отзыв отзыва» глубиной 5000 законна для валидатора — список последних и возврат
        отвечают, поллер не падает; кольцо 5000 для ядра незаконно (№ERROR-5) — список отвечает, отзыв даёт
        reask_invalid с адресом формы; оракул считает действие своей рекурсией с поднятым лимитом."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0), msg(TOK["undo"], date=T0 + 10)])
        anchor = o.lines()[0]["anchor"]
        ret_cid = [h for h in o.blocks() if h["link"] == "retracts:t:"][0]["cid"]
        other = s.other_clone()
        N = 5000
        def cid(k): return "01a07c50-0000-7000-8000-%012x" % k
        chain = b"".join(("### 2026-09-07T15:00:00Z · dev-one <!--c:%s retracts:%s-->\nx\n" % (cid(k), ret_cid if k == 1 else cid(k - 1))).encode() for k in range(1, N + 1))
        ring = b"".join(("### 2026-09-07T15:00:00Z · dev-one <!--c:%s retracts:%s-->\nx\n" % (cid(100000 + k), cid(100000 + (k % N) + 1))).encode() for k in range(1, N + 1))
        self._append_foreign(other, chain)
        git(other, "commit", "-qm", "deep chain"); git(other, "push", "-q", "origin", "HEAD:main")
        import time
        t0 = time.time()
        r, t, _ = self.run_poll([msg(TOK["last"], date=T0 + 20)])
        self.assertEqual(r["outcomes"][-1][1], "last_list_given", r["outcomes"])
        self.assertLess(time.time() - t0, 30)
        # цепочка чётной длины над отзывом: 5000 звеньев → отзыв ret_cid ДЕЙСТВУЕТ (звено 5000 действует, 4999 нет, … 1 нет)
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 4 * N))
        heads = o.blocks()
        self.assertTrue(o.retracted(anchor, heads))
        self.assertIn("отозвано", t.sent[-1][1])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 1", date=T0 + 30)])
        self.assertEqual(r["outcomes"][-1][1], "unretracted", r["outcomes"])
        self.assertFalse(o.retracted(anchor, o.blocks()))
        # кольцо: для ядра это НЕЗАКОННЫЙ спутник (§04.3.4 №ERROR-5) — список не падает, отзыв даёт reask_invalid
        # с АДРЕСОМ формы (раунд 1 №8), коммита нет
        self._append_foreign(other, ring)
        git(other, "commit", "-qm", "ring"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, _ = self.run_poll([msg(TOK["last"], date=T0 + 40)])
        self.assertEqual(r["outcomes"][-1][1], "last_list_given", r["outcomes"])
        r, t, _ = self.run_poll([msg(TOK["undo"], date=T0 + 50)])
        self.assertEqual(r["outcomes"][-1][1], "reask_invalid", r["outcomes"])
        self.assertIn("№ERROR-5", t.sent[-1][1]); self.assertNotIn("правило ERROR ", t.sent[-1][1])
        self.assertEqual(git(s.root, "log", "--format=%s", "-1", "origin/main", "--", CM).strip(), "ring")

    def test_permutation_of_sibling_blocks_in_reconcile_is_not_target_change(self):
        """Раунд 5, W4: законная перестановка блоков спутника чужим писателем в reconcile состояние цели не меняет
        (множество действующих отзывов то же) — возврат исполняется; порядок блоков не семантичен."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        anchor = o.lines()[0]["anchor"]
        other = s.other_clone()
        self._append_foreign(other, self._foreign_block("retracts:t:", anchor, 1, "канал A") + self._foreign_block("retracts:t:", anchor, 2, "канал B"))
        git(other, "commit", "-qm", "two foreign retractions"); git(other, "push", "-q", "origin", "HEAD:main")
        self.run_poll([msg(TOK["last"], date=T0 + 10)])
        def inject():
            git(other, "pull", "-q", "--ff-only", "origin", "main")
            p = os.path.join(other, CM); raw = open(p, "rb").read()
            a = self._foreign_block("retracts:t:", anchor, 1, "канал A"); b = self._foreign_block("retracts:t:", anchor, 2, "канал B")
            assert a + b in raw
            with open(p, "wb") as fh:
                fh.write(raw.replace(a + b, b + a))
            git(other, "add", CM); git(other, "commit", "-qm", "permute blocks"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, _ = self.run_poll_with_prereconcile_push([msg(TOK["undo"] + " 1", date=T0 + 20)], inject)
        self.assertEqual(r["outcomes"][-1][1], "unretracted", (r["outcomes"], t.sent[-1][1] if t.sent else None))
        heads = o.blocks()
        self.assertFalse(o.retracted(anchor, heads)); self.assertEqual(len([h for h in heads if h["link"] == "retracts:"]), 2)

    def test_second_foreign_retraction_in_reconcile_is_target_change(self):
        """Раунд 7 Fable (мутант M10): цель отозвана одним чужим отзывом; в reconcile приезжает ВТОРОЙ — множество
        действующих отзывов изменилось → target_changed, блока возврата нет (иначе возврат снял бы только первый)."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        anchor = o.lines()[0]["anchor"]
        other = s.other_clone()
        self._append_foreign(other, self._foreign_block("retracts:t:", anchor, 1, "канал A"))
        git(other, "commit", "-qm", "foreign A"); git(other, "push", "-q", "origin", "HEAD:main")
        self.run_poll([msg(TOK["last"], date=T0 + 10)])
        def inject():
            self._append_foreign(other, self._foreign_block("retracts:t:", anchor, 2, "канал B"))
            git(other, "commit", "-qm", "foreign B"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, _ = self.run_poll_with_prereconcile_push([msg(TOK["undo"] + " 1", date=T0 + 20)], inject)
        self.assertEqual(r["outcomes"][-1][1], "reask_undo_not_found", r["outcomes"]); self.assertIn("target_changed", t.sent[-1][1])
        heads = o.blocks()
        self.assertEqual(len([h for h in heads if h["link"] == "retracts:"]), 0); self.assertTrue(o.retracted(anchor, heads))
        # та же МОЩНОСТЬ, другой состав (раунд 8, мутант len-вместо-set): отзыв A возвращён чужим каналом, добавлен отзыв C
        self.run_poll([msg(TOK["last"], date=T0 + 30)])
        a_cid = [h for h in o.blocks() if h["link"] == "retracts:t:" and h["body"] == "канал A".encode("utf-8")][0]["cid"]
        def inject2():
            self._append_foreign(other, self._foreign_block("retracts:", a_cid, 3, "возврат A") + self._foreign_block("retracts:t:", anchor, 4, "канал C"))
            git(other, "commit", "-qm", "swap A for C"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, _ = self.run_poll_with_prereconcile_push([msg(TOK["undo"] + " 1", date=T0 + 40)], inject2)
        self.assertEqual(r["outcomes"][-1][1], "reask_undo_not_found", r["outcomes"]); self.assertIn("target_changed", t.sent[-1][1])

    def test_n_beyond_shown_list_is_out_of_range(self):
        """Раунд 8 Fable, W1: N больше предела показа (last_max_n) — n_out_of_range, а не отзыв невидимой строки."""
        s, o = self.s, self.o
        cap = int(self.cfg.get("last_max_n", 50))
        for k in range(cap + 3):
            self.run_poll([msg("1ч строка %d" % k, date=T0 + k * 100)])
        self.run_poll([msg(TOK["last"] + " 9999", date=T0 + 100000)])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " %d" % (cap + 1), date=T0 + 100010)])
        self.assertEqual(r["outcomes"][-1][1], "reask_undo_not_found", r["outcomes"]); self.assertIn("n_out_of_range", t.sent[-1][1])
        self.assertEqual(o.hours_in_account(), (cap + 3) * 100)
        r, t, _ = self.run_poll([msg(TOK["undo"] + " %d" % cap, date=T0 + 100020)])
        self.assertEqual(r["outcomes"][-1][1], "retracted", r["outcomes"])

    def test_foreign_retraction_with_fractional_seconds_is_seen(self):
        """Раунд 9 Fable-2, B1: чужой отзыв с долями секунд в токене времени (ядро 02.2.1 — валидный вход, валидатор
        принимает) виден боту: список помечает строку отозванной, отзыв по N — возврат, а не второй отзыв."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        anchor = o.lines()[0]["anchor"]
        other = s.other_clone()
        block = ("### 2026-09-07T15:00:00.123456789012Z · dev-one <!--c:01a07c50-0000-7000-8000-0000000000f1 retracts:t:%s-->\nдоли секунд\n" % anchor).encode()   # 12 цифр: ядро/валидатор — \d+ (раунд 10 B W2)
        self._append_foreign(other, block)
        git(other, "commit", "-qm", "foreign fractional"); git(other, "push", "-q", "origin", "HEAD:main")
        r, t, _ = self.run_poll([msg(TOK["last"], date=T0 + 10)])
        self.assertIn("отозвано", t.sent[-1][1])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " 1", date=T0 + 20)])
        self.assertEqual(r["outcomes"][-1][1], "unretracted", r["outcomes"])
        heads = [h for h in o.blocks() if h["link"] == "retracts:"]
        self.assertEqual(len(heads), 1); self.assertEqual(heads[0]["target"], "01a07c50-0000-7000-8000-0000000000f1")

    def test_target_in_other_container_gets_block_in_its_sibling(self):
        """Раунд 1 (P6): цель по N — строка в ДРУГОМ контейнере (другой месяц) → блок в спутнике того контейнера."""
        s, o = self.s, self.o
        TS8 = "time/TIMESHEET-2026-08-dev-one.md"; CM8 = "time/TIMESHEET-2026-08-dev-one.comments.md"
        head = s.read(TS).decode("utf-8") if os.path.exists(os.path.join(s.root, TS)) else None
        self.run_poll([msg("2ч созвон", date=T0)])
        sept = s.read(TS).decode("utf-8")
        front = sept.split("\n---\n", 1)[0].replace("2026-09", "2026-08").replace("id: ", "id: 0", 1)[:0]
        # контейнер августа — из контейнера сентября со сменой месяца и id (валидатор требует уникальный UUIDv7)
        aug = sept.split("\n---\n", 1)[0]
        aug = re.sub(r"^id: (\S+)$", lambda m: "id: " + m.group(1)[:-4] + "0a08", aug, flags=re.M).replace("2026-09", "2026-08")
        aug += "\n---\n2026-08-20 1.00  август <!--t:0a0a0a0a-->\n"
        with open(os.path.join(s.root, TS8), "wb") as fh:
            fh.write(aug.encode("utf-8"))
        git(s.root, "add", TS8); git(s.root, "commit", "-qm", "august"); git(s.root, "push", "-q", "origin", "main")
        r, t, _ = self.run_poll([msg(TOK["last"], date=T0 + 10)])
        self.assertIn("август", t.sent[-1][1])
        titles = [ln for ln in t.sent[-1][1].split("\n") if "август" in ln]
        n = int(re.match(r"\s*(\d+)", titles[0]).group(1))
        r, t, _ = self.run_poll([msg(TOK["undo"] + " %d лишняя" % n, date=T0 + 20)])
        self.assertEqual(r["outcomes"][-1][1], "retracted", r["outcomes"])
        self.assertTrue(os.path.exists(os.path.join(s.root, CM8)))
        self.assertTrue(o.retracted("0a0a0a0a", o.blocks(CM8)))
        self.assertFalse(any(h["target"] == "0a0a0a0a" for h in o.blocks(CM)))
        self.assertEqual(s.read(TS8).decode("utf-8"), aug)

    def test_repeat_before_push_is_identical_not_return(self):
        """Ревью #2: после retries_exhausted локальный коммит с отзывом живёт; тот же update приходит снова —
        правило Т ДО выбора цели → identical, а не «цель уже отозвана → возврат»."""
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        s.deny_push(True)
        u = msg(TOK["undo"], date=T0 + 20)
        r, _, _ = self.run_poll([u])
        self.assertEqual(r["outcomes"][-1][1], "retries_exhausted")
        s.deny_push(False)
        r, _, _ = self.run_poll([u])          # update ниже НЕ водяного знака origin → приходит снова
        kinds = [x[1] for x in r["outcomes"]]
        self.assertIn("identical_repeat", kinds, kinds)
        self.assertEqual(len([h for h in o.blocks() if h["link"] == "retracts:t:"]), 1)
        self.assertEqual(o.hours_in_account(), 0)

    def test_midnight_pair_two_commands(self):
        s, o = self.s, self.o
        # сессия через местную полночь Belgrade: 23:30 → 00:30 (2026-09-07 21:30Z … 22:30Z)
        self.run_poll([msg(TOK["start_title"] + " ночная", date=1788816600), msg(TOK["stop"], date=1788820200)])
        self.assertEqual(len(o.lines()), 2)
        r, t, _ = self.run_poll([msg(TOK["undo"], date=1788820300)])
        self.assertEqual(r["outcomes"][-1][1], "retracted")
        heads = o.blocks()
        self.assertEqual(sum(1 for l in o.lines() if o.retracted(l["anchor"], heads)), 1, "одна команда — одна строка")
        self.assertIn("2026-09-08", t.sent[-1][1])
        self.run_poll([msg(TOK["undo"], date=1788820400)])
        heads = o.blocks()
        self.assertEqual(sum(1 for l in o.lines() if o.retracted(l["anchor"], heads)), 2)

    def test_secret_in_reason_is_scanned_and_confirm_passes(self):
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        r, t, _ = self.run_poll([msg(TOK["undo"] + " ключ ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd", date=T0 + 20)])
        self.assertEqual(r["outcomes"][-1][1], "rejected_secret")
        self.assertEqual(len(o.blocks()), 0)
        r, t, _ = self.run_poll([msg(TOK["confirm"] + " " + TOK["undo"] + " ключ ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd", date=T0 + 30)])
        self.assertEqual(r["outcomes"][-1][1], "retracted")

    def test_corrupted_sibling_check_pair_refuses_commit(self):
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0)])
        # спутник с дублем c:<id> ломает check-pair (rc=2) → reask_invalid, коммита нет
        hdr = "<!-- comments-of: %s -->\n\n" % re.search(r"^id: (\S+)", s.read(TS).decode(), re.M).group(1)
        dup = "### 2026-09-07T15:00:00Z · dev-one <!--c:01a07c50-0000-7000-8000-000000000002 about:t:%s-->\nx\n" % o.lines()[0]["anchor"]
        with open(os.path.join(s.root, CM), "wb") as fh:
            fh.write((hdr + dup + dup).encode())
        git(s.root, "add", CM); git(s.root, "commit", "-qm", "corrupt"); git(s.root, "push", "-q", "origin", "main")
        n = len(self.commits())
        r, t, _ = self.run_poll([msg(TOK["undo"], date=T0 + 20)])
        self.assertEqual(r["outcomes"][-1][1], "reask_invalid")
        cm_commits = git(s.root, "log", "--format=%s", "origin/main", "--", CM).strip().split("\n")
        self.assertEqual(cm_commits[0], "corrupt")        # спутник не коммитился (раунд 1: тавтология оракула заменена)
        self.assertEqual(len(self.commits()), n + 1)      # ровно коммит offset (переспрос продвигает offset)
        self.assertNotIn("retracts:t:", s.read(CM).decode())

    def test_last_marks_retracted_and_short_replies(self):
        s, o = self.s, self.o
        self.run_poll([msg("2ч созвон", date=T0), msg(TOK["undo"], date=T0 + 10)])
        r, t, _ = self.run_poll([msg(TOK["last"], date=T0 + 20)])
        self.assertIn("отозвано", t.sent[-1][1])
        for text in ("просто текст", TOK["stop"]):
            r, t, _ = self.run_poll([msg(text, chat_type="private", date=T0 + 30)])
            reply = t.sent[-1][1]
            self.assertEqual(len(reply.split("\n")), 1, reply)
            self.assertLessEqual(len(reply), poll.SHORT_REPLY_MAX)
            self.assertIn(TOK["help"], reply)
            self.assertNotIn(TOK["track"], reply)   # перечня команд нет


if __name__ == "__main__":
    unittest.main()
