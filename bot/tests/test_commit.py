# -*- coding: utf-8 -*-
"""Оракул git-слоя (T3): Р1, писатель двух файлов (ленивое создание, append-only, дозавершение LF,
тождество), коммит/пуш с ретраями, трасса. git-факты — командами git; ожидания байтов — regex/cmp."""
import os, re, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import commit as cm  # noqa: E402

ENV = b"---\nid: 019550fa-1ea0-773c-b820-1e2b73ab4901\ntype: TIMESHEET\nline_form: daily_time_v1\ntitle: t\nperson: dev-one\nperiod_start: 2026-09-01\nperiod_end: 2026-09-30\ntimezone: UTC\ncreated: 2026-09-01\nauthor: workshop_bot\nversion: 1\n---\n"
L1 = b"2026-09-05 1.00  first <!--t:aaaaaaaa-->\n"
L2 = b"2026-09-06 2.00  second <!--t:bbbbbbbb-->\n"
L3 = b"2026-09-07 0.50  third <!--t:cccccccc-->\n"


def git(root, *a, env=None):
    r = subprocess.run(["git", "-C", root] + list(a), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


class P1Tests(unittest.TestCase):
    def test_matrix(self):
        base = ENV + L1
        self.assertEqual(cm.p1_predicate(base, base + L2, base + L3), (True, None))                 # обе дописали
        self.assertEqual(cm.p1_predicate(base, base, base + L3), (True, None))                      # одна сторона нетронута
        self.assertFalse(cm.p1_predicate(None, base + L2, base + L3)[0])                            # (а) add/add
        self.assertFalse(cm.p1_predicate(base, base.replace(b"version: 1", b"version: 2") + L2, base + L3)[0])   # (б) конверт ours
        self.assertFalse(cm.p1_predicate(base, base + L2, base.replace(b"title: t", b"title: u") + L3)[0])       # (б) конверт theirs
        self.assertFalse(cm.p1_predicate(base, ENV + L2, base + L3)[0])                             # (в/г) строка базы удалена
        self.assertFalse(cm.p1_predicate(base, ENV + L1.replace(b"1.00", b"1.50") + L2, base + L3)[0])  # (г) строка базы изменена
        self.assertFalse(cm.p1_predicate(b"no envelope\n" + L1, b"no envelope\n" + L1 + L2, b"no envelope\n" + L1)[0])


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.trace = cm.Trace()
        self.mint = lambda: "019550fa-1ea0-773c-b820-1e2b73ab4901"

    def tearDown(self):
        shutil.rmtree(self.t)

    def raw(self, rel):
        with open(os.path.join(self.t, rel), "rb") as fh:
            return fh.read()

    def spec(self, date, seconds, title, k=0, identity="tg:100000001:4001", mdate=1788790990, tail="хвост".encode("utf-8")):
        line = {"date": date, "seconds": seconds, "interval": None, "title": title, "k": k, "identity": identity, "message_date": mdate}
        com = [{"identity": identity, "message_date": mdate, "body": ("%s\n" % title).encode("utf-8") + tail, "k": k}] if tail else []
        return [line], com

    def write(self, lines, coms):
        return cm.write_line_and_comments(self.t, lines, coms, "dev-one", "Europe/Belgrade", "workshop_bot", None, self.trace, self.mint)

    def test_lazy_creation_header_append_only_and_identity(self):
        lines, coms = self.spec("2026-09-07", 3600, "первая")
        written, lw, blocks = self.write(lines, coms)
        ts = "time/TIMESHEET-2026-09-dev-one.md"; cmf = "time/TIMESHEET-2026-09-dev-one.comments.md"
        self.assertEqual(sorted(written), sorted([ts, cmf]))
        body = self.raw(ts)
        self.assertTrue(body.startswith(b"---\nid: 019550fa-1ea0-773c-b820-1e2b73ab4901\n"))       # конверт с минтованным id
        self.assertEqual(body.count(b"\n---\n"), 1)
        self.assertRegex(body.split(b"\n---\n")[1], rb"^2026-09-07 1\.00  \xd0\xbf\xd0\xb5\xd1\x80\xd0\xb2\xd0\xb0\xd1\x8f <!--t:[0-9a-f]{8}-->\n$")
        cb = self.raw(cmf)
        first = cb.split(b"\n", 1)[0]
        self.assertEqual(first, b"<!-- comments-of: 019550fa-1ea0-773c-b820-1e2b73ab4901 -->")      # заголовок = id контейнера
        self.assertEqual(cb.count(b"about:t:"), 1)
        # второй коммент — только append: заголовок побайтово тот же, число заголовков одно
        lines2, coms2 = self.spec("2026-09-08", 1800, "вторая", identity="tg:100000001:4002", mdate=1788877390)
        self.write(lines2, coms2)
        cb2 = self.raw(cmf)
        self.assertTrue(cb2.startswith(cb))                                                            # append-only
        self.assertEqual(cb2.split(b"\n", 1)[0], first); self.assertEqual(cb2.count(b"comments-of:"), 1)
        self.assertEqual(cb2.count(b"about:t:"), 2)
        # идемпотентность: тот же update повторно → строка тождественна (пропуск), блок уже есть → cmp-равно
        before = (self.raw(ts), cb2)
        written3, lw3, blocks3 = self.write(lines, coms)
        self.assertEqual((written3, lw3, blocks3), ([], [], []))
        self.assertEqual((self.raw(ts), self.raw(cmf)), before)
        self.assertIn("identical", [o["op"] for o in self.trace.ops])

    def test_trailing_lf_is_completed_before_append(self):
        lines, coms = self.spec("2026-09-07", 3600, "первая")
        self.write(lines, coms)
        cmf = os.path.join(self.t, "time/TIMESHEET-2026-09-dev-one.comments.md")
        ts = os.path.join(self.t, "time/TIMESHEET-2026-09-dev-one.md")
        for p in (cmf, ts):                                   # искусственно обрезанный финальный \n
            with open(p, "rb") as fh:
                b = fh.read()
            with open(p, "wb") as fh:
                fh.write(b.rstrip(b"\n"))
        lines2, coms2 = self.spec("2026-09-08", 1800, "вторая", identity="tg:100000001:4002", mdate=1788877390)
        self.write(lines2, coms2)
        with open(cmf, "rb") as fh:
            cb = fh.read()
        heads = [l for l in cb.split(b"\n") if l.startswith(b"### ")]
        self.assertEqual(len(heads), 2)                       # заголовок нового коммента — в начале СВОЕЙ строки, склейки нет
        with open(ts, "rb") as fh:
            tb = fh.read()
        self.assertEqual(len([l for l in tb.split(b"\n") if l.startswith(b"2026-09-")]), 2)

    def test_no_tail_no_comment_file(self):
        lines, coms = self.spec("2026-09-07", 3600, "без хвоста", tail=b"")
        written, lw, blocks = self.write(lines, coms)
        self.assertEqual(written, ["time/TIMESHEET-2026-09-dev-one.md"]); self.assertEqual(blocks, [])


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.origin = os.path.join(self.tmp, "o.git"); self.root = os.path.join(self.tmp, "w")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.root], check=True, stderr=subprocess.DEVNULL)
        git(self.root, "checkout", "-q", "-b", "main")
        self.trace = cm.Trace()
        with open(os.path.join(self.root, "a.txt"), "wb") as fh:
            fh.write(b"a\n")
        cm.commit_paths(self.root, ["a.txt"], "seed", "workshop_bot", "workshop_bot@bot.invalid", self.trace)
        git(self.root, "push", "-q", "-u", "origin", "main")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_commit_paths_author_and_empty_index(self):
        self.assertIsNone(cm.commit_paths(self.root, ["a.txt"], "nothing", "workshop_bot", "x@bot.invalid", self.trace))
        with open(os.path.join(self.root, "a.txt"), "ab") as fh:
            fh.write(b"b\n")
        sha = cm.commit_paths(self.root, ["a.txt"], "msg", "workshop_bot", "workshop_bot@bot.invalid", self.trace)
        self.assertRegex(sha, r"^[0-9a-f]{40}$")
        self.assertEqual(git(self.root, "log", "-1", "--format=%an <%ae>")[1].strip(), "workshop_bot <workshop_bot@bot.invalid>")

    def test_push_retry_exhausted_prints_attempts_and_backoff(self):
        hook = os.path.join(self.origin, "hooks", "pre-receive")
        with open(hook, "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        with open(os.path.join(self.root, "a.txt"), "ab") as fh:
            fh.write(b"c\n")
        cm.commit_paths(self.root, ["a.txt"], "m", "b", "b@x", self.trace)
        waits = []; calls = []
        v = cm.push_with_retry(self.root, self.trace, 4, [1, 2, 3], lambda: (calls.append(1), "retry")[1], sleeper=waits.append)
        self.assertEqual(v, ("exhausted", 4, 6)); self.assertEqual(waits, [1, 2, 3]); self.assertEqual(len(calls), 3)
        self.assertEqual(len([o for o in self.trace.ops if o["op"] == "push"]), 4)
        v2 = cm.push_with_retry(self.root, self.trace, 3, 5, lambda: "conflict_state_file", sleeper=waits.append)
        self.assertEqual(v2, ("refused", 1, "conflict_state_file"))
        self.assertNotIn(b"+refs/", open(os.path.join(os.path.dirname(__file__), "..", "commit.py"), "rb").read())

    def test_reconcile_p1_gate_refuses_before_merge(self):
        # табель в базе; фронт правит конверт и пушит; локально — дописанная строка; reconcile обязан отказать ДО merge
        ts = os.path.join(self.root, "time", "TIMESHEET-2026-09-dev-one.md"); os.makedirs(os.path.dirname(ts))
        with open(ts, "wb") as fh:
            fh.write(ENV + L1)
        with open(os.path.join(self.root, ".gitattributes"), "wb") as fh:
            fh.write(b"time/*.md merge=union\n")
        cm.commit_paths(self.root, ["time", ".gitattributes"], "base", "b", "b@x", self.trace); git(self.root, "push", "-q", "origin", "HEAD")
        other = os.path.join(self.tmp, "other"); subprocess.run(["git", "clone", "-q", self.origin, other], check=True, stderr=subprocess.DEVNULL)
        op = os.path.join(other, "time", "TIMESHEET-2026-09-dev-one.md")
        with open(op, "wb") as fh:
            fh.write(ENV.replace(b"version: 1", b"version: 2") + L1 + L3)
        git(other, "-c", "user.name=f", "-c", "user.email=f@x", "commit", "-qam", "front"); git(other, "push", "-q", "origin", "HEAD:main")
        with open(ts, "ab") as fh:
            fh.write(L2)
        cm.commit_paths(self.root, ["time"], "bot", "b", "b@x", self.trace)
        head = git(self.root, "rev-parse", "HEAD")[1].strip()
        v = cm.reconcile(self.root, self.trace)
        self.assertTrue(v.startswith("p1_unmet:time/TIMESHEET-2026-09-dev-one.md:"), v)
        self.assertEqual(git(self.root, "rev-parse", "HEAD")[1].strip(), head)                       # слияния не было
        self.assertEqual(git(self.root, "status", "--porcelain")[1], "")
        # обратный контроль: законное дописывание обеими сторонами — union, clean
        git(other, "reset", "-q", "--hard", "HEAD~1")
        with open(op, "ab") as fh:
            fh.write(L3)
        git(other, "-c", "user.name=f", "-c", "user.email=f@x", "commit", "-qam", "front2"); git(other, "push", "-q", "-f", "origin", "HEAD:main")  # -f только в ОРАКУЛЕ, чтобы переписать чужую фикстуру
        self.assertEqual(cm.reconcile(self.root, self.trace), "clean")
        with open(ts, "rb") as fh:
            b = fh.read()
        self.assertTrue(b.endswith(L2 + L3) or b.endswith(L3 + L2))
        self.assertIsNotNone(self.trace.between("fetch", "merge"))


if __name__ == "__main__":
    unittest.main()
