# -*- coding: utf-8 -*-
"""Оракул читателя сумм (D15 T3): паритет с golden T2 (expected — ДАННЫЕ, не код оракула), арифметика по D04
(А1–А8, правило Д), периоды по зоне отправителя, форма ответа §4.4. Ожидания считаются из байтов файлов и
пиннованного expected.tsv; функции aggregation вызываются как испытуемые, не как источник ожиданий."""
import base64
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.abspath(os.path.join(HERE, ".."))
MONO = os.path.abspath(os.path.join(BOT, ".."))
sys.path.insert(0, BOT); sys.path.insert(0, os.path.join(BOT, "kit"))
import aggregation, yamlmini, identity  # noqa: E402

FIX = os.path.join(MONO, "harness", "fixtures", "d15")


def materialize_golden(root):
    """Golden-корпус T2 — данные (json), не код оракула: файлы выписываются побайтово."""
    with open(os.path.join(FIX, "summary-corpus.json"), "rb") as fh:
        corpus = json.loads(fh.read().decode("utf-8"))
    for e in corpus["files"]:
        p = os.path.join(root, e["path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(base64.b64decode(e["base64"]) if "base64" in e else e["text"].encode("utf-8"))
    os.makedirs(os.path.join(root, ".workshop"), exist_ok=True)
    with open(os.path.join(root, ".workshop", "people.yaml"), "wb") as fh:
        fh.write(corpus["people"].encode("utf-8"))


class GoldenParityTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="d15-agg-")
        materialize_golden(self.root)
        self.people = identity.people_list(yamlmini.load_file(os.path.join(self.root, ".workshop", "people.yaml")))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_tsv_equals_pinned_expected_bytes(self):
        got = aggregation.render_tsv(aggregation.summarize(self.root, self.people))
        with open(os.path.join(FIX, "summary-expected.tsv"), "rb") as fh:
            exp = fh.read()
        self.assertEqual(got, exp)
        self.assertTrue(exp.endswith(b"\n") and b"\r" not in exp and not exp.startswith(b"\xef\xbb\xbf"))

    def test_level_filters_and_alias(self):
        rows = aggregation.summarize(self.root, self.people, "dev1")
        self.assertEqual([r[0] for r in rows], ["dev1"] * len(rows))
        self.assertIn(("dev1", "2026-09", 3800), rows)          # 300 сотых из файла под alias tg-100 вошли
        self.assertEqual(aggregation.summarize(self.root, self.people, "tg-100"), [])   # alias — не канонический ключ

    def test_no_zero_rows_and_month_of_line_date(self):
        rows = aggregation.summarize(self.root, self.people)
        self.assertTrue(all(c > 0 for _p, _m, c in rows))
        self.assertNotIn(("dev2", "2026-07"), [(p, m) for p, m, _c in rows])   # полностью отозванный месяц
        self.assertIn(("dev1", "2026-09", 3800), rows)                          # 12.00 из АВГУСТОВСКОГО файла — в сентябрь

    def test_person_from_envelope_not_filename(self):
        # тот же файл, конверт person=dev2, имя файла — dev1: считается за dev2
        src = os.path.join(self.root, "time", "TIMESHEET-2026-10-dev1.md")
        data = open(src, "rb").read().replace(b"person: dev1", b"person: dev2")
        with open(src, "wb") as fh:
            fh.write(data)
        rows = dict(((p, m), c) for p, m, c in aggregation.summarize(self.root, self.people))
        self.assertEqual(rows.get(("dev2", "2026-10")), 2500 + 150)   # + собственные 150 dev2 за октябрь (golden, контейнер с BOM)
        self.assertNotIn(("dev1", "2026-10"), rows)

    def test_content_never_raises_but_io_does(self):
        bad = os.path.join(self.root, "time", "TIMESHEET-2026-11-dev1.md")
        with open(bad, "wb") as fh:
            fh.write(b"---\nperson: dev1\n---\n\xff\xfe garbage\n2026-11-01 1.00 ok <!--t:aaaabbbb-->\n2026-11-02 x\n")
        rows = dict(((p, m), c) for p, m, c in aggregation.summarize(self.root, self.people))
        self.assertEqual(rows.get(("dev1", "2026-11")), 100)
        os.chmod(bad, 0)
        try:
            with self.assertRaises(OSError):
                aggregation.summarize(self.root, self.people)
        finally:
            os.chmod(bad, 0o644)

    def test_two_passes_and_reversed_walk_are_identical(self):
        # T3 раунд 1 (astra, MINOR): сравнение продукта с самим собой слепо — ожидание берётся из ПИННОВАННОГО expected,
        # а обход действительно переставляется (обратный порядок контейнеров и спутников)
        with open(os.path.join(FIX, "summary-expected.tsv"), "rb") as fh:
            exp = fh.read()
        a = aggregation.render_tsv(aggregation.summarize(self.root, self.people))
        orig = aggregation._containers
        aggregation._containers = lambda root: tuple(list(reversed(x)) for x in orig(root))
        try:
            b = aggregation.render_tsv(aggregation.summarize(self.root, self.people))
        finally:
            aggregation._containers = orig
        self.assertEqual(a, exp); self.assertEqual(b, exp)

    def test_walk_error_is_io_failure_not_partial_sum(self):
        # T3 раунд 1 (astra, BLOCKER): недоступный подкаталог time/ — IO-сбой наружу (tool_failure), не частичная сумма
        sub = os.path.join(self.root, "time", "sub")
        os.makedirs(sub)
        shutil.copy(os.path.join(self.root, "time", "TIMESHEET-2026-10-dev1.md"), os.path.join(sub, "TIMESHEET-2026-10-dev1.md"))
        os.chmod(sub, 0)
        try:
            with self.assertRaises(OSError):
                aggregation.summarize(self.root, self.people)
        finally:
            os.chmod(sub, 0o755)

    def test_duplicate_envelope_key_with_any_value_is_unfit(self):
        # T3 раунд 1 (astra, BLOCKER): повтор ключа считается по КЛЮЧУ — пустое значение или значение с пробелом тоже дубль
        env = b"---\nid: 0199a000-0000-7000-8000-000000000099\nperson: dev1\n%s\n---\n2026-11-01 1.00  x <!--t:a1a1a1a1-->\n"
        for dup in (b"person: ", b"person: dev two", b"person:", b"id: ", b"id: 0199a000-0000-7000-8000-000000000099"):
            self.assertIsNone(aggregation.envelope_fields(env % dup), dup)
        self.assertEqual(aggregation.envelope_fields(env % b"title: x")["person"], "dev1")

    def test_content_defects_are_traced_as_warnings(self):
        # T3 раунд 1 (astra, MAJOR): порченый UTF-8 в строке-записи, некалендарная дата, строка `### ` не по грамматике —
        # WARNING в трассу (запись читается по А8)
        p = os.path.join(self.root, "time", "TIMESHEET-2026-11-dev1.md")
        with open(p, "wb") as fh:
            fh.write(b"---\nid: 0199a000-0000-7000-8000-000000000077\nperson: dev1\n---\n2026-11-01 1.00  \xff\xfe <!--t:a1a1a1a1-->\n2026-13-99 2.00  x <!--t:a1a1a1a2-->\n")
        with open(p[:-3] + ".comments.md", "wb") as fh:
            fh.write("<!-- comments-of: 0199a000-0000-7000-8000-000000000077 -->\n\n### мусор без времени <!--c:x-->\nтело\n".encode("utf-8"))
        notes = []
        rows = dict(((pp, m), c) for pp, m, c in aggregation.summarize(self.root, self.people, trace=lambda k, rel, n: notes.append(n.split(":")[0])))
        self.assertEqual(rows.get(("dev1", "2026-11")), 100); self.assertEqual(rows.get(("dev1", "2026-13")), 200)
        for code in ("FILE_UTF8", "DATE_INVALID", "HEADER_MALFORMED"):
            self.assertIn(code, notes)

    def test_every_pinned_mutation_matches_its_expected_rows(self):
        # регрессия класса «границы логической записи / K7» (раунд 2) и всей матрицы T2: каждая мутация корпуса
        # материализуется ОРАКУЛОМ как отдельным процессом (данные), продукт обязан дать ровно expected_rows мутации
        import subprocess
        with open(os.path.join(FIX, "summary-mutations.json"), "rb") as fh:
            muts = json.loads(fh.read().decode("utf-8"))["mutations"]
        self.assertTrue(muts)
        oracle = os.path.join(MONO, "harness", "d15_summary_oracle.py")
        for m in muts:
            root = tempfile.mkdtemp(prefix="d15-mut-")
            try:
                r = subprocess.run([sys.executable, oracle, "--materialize", root, "--mutate", m["id"]],
                                   stdin=subprocess.DEVNULL, capture_output=True)
                self.assertEqual(r.returncode, 0, (m["id"], r.stdout))
                people = identity.people_list(yamlmini.load_file(os.path.join(root, ".workshop", "people.yaml")))
                got = aggregation.render_tsv(aggregation.summarize(root, people))
                want = "".join("%s\t%s\t%d\n" % (p, mo, int(c)) for p, mo, c in m["expected_rows"]).encode("utf-8")
                self.assertEqual(got, want, m["id"])
                # личные уровни (T3-fix, охват чтения): для каждого человека — ровно его строки пиннованного expected
                for who in sorted(set(p for p, _mo, _c in m["expected_rows"]) | set(str(pp["handle"]) for pp in people)):
                    got_p = aggregation.render_tsv(aggregation.summarize(root, people, who))
                    want_p = "".join("%s\t%s\t%d\n" % (p, mo, int(c)) for p, mo, c in m["expected_rows"] if p == who).encode("utf-8")
                    self.assertEqual(got_p, want_p, (m["id"], who))
            finally:
                shutil.rmtree(root, ignore_errors=True)

    def test_logical_record_boundaries_and_k7(self):
        # ядро 03.2.3–03.2.5: сирота, продолжение без отступа (near-miss), пустая строка внутри записи, Unicode-дата;
        # правило Т при байт-идентичных первых строках — победитель по K7 (продолжение), WARNING в трассу
        body = ("# сирота\n"
                "2026-12-01 2.00  x <!--t:e7e7e7e1-->\nzzz без отступа\n"
                "2026-12-01 2.00  x <!--t:e7e7e7e1-->\n с отступом\n"
                "2026-12-03 0.25  y <!--t:e7e7e7e3-->\n\n 2026-12-03 8.00  не запись\n"
                "2026-12-04 0.50  z <!--t:e7e7e7e4-->\n2026-12-04 7.5  near-miss\n"
                "٢٠٢٦-١٢-٠٥ 6.00  Unicode\n").encode("utf-8")
        notes = []
        recs = aggregation._records(body, lambda k, rel, n: notes.append((k, n)), "x")
        self.assertEqual([(d, c, a) for d, c, a, _k in recs],
                         [("2026-12-01", 200, "e7e7e7e1"), ("2026-12-01", 200, "e7e7e7e1"), ("2026-12-03", 25, "e7e7e7e3"), ("2026-12-04", 50, "e7e7e7e4")])
        self.assertEqual(recs[0][3], b"2026-12-01 2.00  x <!--t:e7e7e7e1-->\nzzz \xd0\xb1\xd0\xb5\xd0\xb7 \xd0\xbe\xd1\x82\xd1\x81\xd1\x82\xd1\x83\xd0\xbf\xd0\xb0")
        self.assertEqual(recs[2][3].split(b"\n")[1:2], [b""])                      # пустая строка — в K7 записи
        self.assertTrue(recs[3][3].endswith("Unicode".encode("utf-8")))          # Unicode-дата — продолжение записи z
        self.assertEqual([n for k, n in notes if n.startswith("ORPHAN")], ["ORPHAN_CONTINUATION: продолжение до первой записи"])
        self.assertEqual(sum(1 for k, n in notes if n.startswith("NEAR_MISS")), 1)
        winners = aggregation._rule_t(recs, lambda k, rel, n: notes.append((k, n)), "x")
        k7 = [r[3] for r in winners if r[2] == "e7e7e7e1"]
        self.assertEqual(k7, [b"2026-12-01 2.00  x <!--t:e7e7e7e1-->\n \xd1\x81 \xd0\xbe\xd1\x82\xd1\x81\xd1\x82\xd1\x83\xd0\xbf\xd0\xbe\xd0\xbc"])
        self.assertEqual(sum(1 for k, n in notes if "e7e7e7e1" in n), 1)
        # побайтовый дубль якоря — не расхождение, WARNING нет
        notes2 = []
        dup = aggregation._records(b"2026-12-01 2.00  x <!--t:e7e7e7e1-->\n2026-12-01 2.00  x <!--t:e7e7e7e1-->\n", lambda *a: None, "x")
        aggregation._rule_t(dup, lambda k, rel, n: notes2.append(n), "x")
        self.assertEqual(notes2, [])


class PersonalScopeTests(unittest.TestCase):
    """REQ-108 v10 / решение alex 1(б) 2026-09-21: личные уровни читают тела и спутники ТОЛЬКО собственных контейнеров;
    конверты всех контейнеров и первая строка всех спутников — обнаружение (принадлежность по конверту, не по имени).
    Ожидания — из байтов golden (person конверта), продукт вызывается как испытуемый."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="d15-scope-")
        materialize_golden(self.root)
        self.people = identity.people_list(yamlmini.load_file(os.path.join(self.root, ".workshop", "people.yaml")))
        # владелец каждого контейнера — по конверту (канон handle+aliases считается из карты, не из имени файла)
        canon = {}
        for pp in self.people:
            canon[pp["handle"]] = pp["handle"]
            for a in pp.get("aliases") or []:
                canon[str(a)] = pp["handle"]
        self.owner = {}
        tdir = os.path.join(self.root, "time")
        for dp, _dn, fn in os.walk(tdir):
            for f in fn:
                if f.endswith(".md") and not f.endswith(".comments.md"):
                    path = os.path.join(dp, f)
                    with open(path, "rb") as fh:
                        head = fh.read()
                    m = [l for l in head.split(b"\n") if l.startswith(b"person:")]
                    if m:
                        person = m[0].split(b":", 1)[1].split(b" #")[0].strip().strip(b'"').strip(b"'").decode("utf-8")   # формы скаляра 01 §2.5
                        self.owner[os.path.relpath(path, self.root)] = canon.get(person, person)
        self.assertGreaterEqual(len(set(self.owner.values())), 3)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _parsed(self, only_person):
        seen = []
        orig = aggregation._records
        aggregation._records = lambda body, trace, rel: (seen.append(rel), orig(body, trace, rel))[1]
        try:
            rows = aggregation.summarize(self.root, self.people, only_person)
        finally:
            aggregation._records = orig
        return rows, set(seen)

    def test_personal_mode_parses_only_own_bodies_team_parses_all(self):
        with open(os.path.join(FIX, "summary-expected.tsv"), "rb") as fh:
            exp = fh.read().decode("utf-8").splitlines()
        for who in sorted(set(self.owner.values())):
            rows, parsed = self._parsed(who)
            own = set(rel for rel, o in self.owner.items() if o == who)
            self.assertEqual(parsed, own, who)                                  # ни одного чужого тела
            want = [tuple(l.split("\t")) for l in exp if l.split("\t")[0] == who]
            self.assertEqual([(p, m, str(c)) for p, m, c in rows], want, who)  # суммы — пиннованный expected
        _rows, parsed = self._parsed(None)
        self.assertEqual(parsed, set(self.owner))                               # уровень 3 — все контейнеры

    def test_personal_mode_does_not_read_foreign_bodies(self):
        # тело чужого контейнера недоступно (инжекция в читатель тела) — «мои часы» считаются; команда — IO-сбой
        foreign = next(rel for rel, o in self.owner.items() if o != "dev1")
        orig = aggregation._read
        def broken(path):
            if os.path.relpath(path, self.root) == foreign:
                raise OSError(5, "Input/output error (стенд)")
            return orig(path)
        aggregation._read = broken
        try:
            rows = aggregation.summarize(self.root, self.people, "dev1")
            with self.assertRaises(OSError):
                aggregation.summarize(self.root, self.people)
        finally:
            aggregation._read = orig
        self.assertEqual(rows, aggregation.summarize(self.root, self.people, "dev1"))
        self.assertTrue(rows)

    def test_foreign_envelope_unreadable_is_io_failure(self):
        # конверт чужого контейнера прочитать нельзя ⇒ владелец неизвестен ⇒ собственный IO-сбой (§4.3), не частичная сумма
        foreign = os.path.join(self.root, next(rel for rel, o in self.owner.items() if o != "dev1"))
        os.chmod(foreign, 0)
        try:
            with self.assertRaises(OSError):
                aggregation.summarize(self.root, self.people, "dev1")
        finally:
            os.chmod(foreign, 0o644)

    def test_foreign_defects_are_not_traced_in_personal_mode(self):
        # дефекты чужого тела/спутника (FILE_UTF8, DATE_INVALID, HEADER_MALFORMED) — WARNING только в командном режиме
        p = os.path.join(self.root, "time", "TIMESHEET-2026-11-dev2.md")
        with open(p, "wb") as fh:
            fh.write(b"---\nid: 0199a000-0000-7000-8000-000000000088\nperson: dev2\n---\n2026-11-01 1.00  \xff\xfe <!--t:b1b1b1b1-->\n2026-13-99 2.00  x <!--t:b1b1b1b2-->\n")
        with open(p[:-3] + ".comments.md", "wb") as fh:
            fh.write("<!-- comments-of: 0199a000-0000-7000-8000-000000000088 -->\n\n### мусор без времени <!--c:x-->\nтело\n".encode("utf-8"))
        codes = ("FILE_UTF8", "DATE_INVALID", "HEADER_MALFORMED")
        mine = []
        aggregation.summarize(self.root, self.people, "dev1", trace=lambda k, rel, n: mine.append(n.split(":")[0]))
        self.assertFalse(set(codes) & set(mine), mine)
        team = []
        rows = dict(((pp, m), c) for pp, m, c in aggregation.summarize(self.root, self.people, trace=lambda k, rel, n: team.append(n.split(":")[0])))
        for code in codes:
            self.assertIn(code, team)
        self.assertEqual(rows.get(("dev2", "2026-11")), 100)
        theirs = []
        rows2 = dict(((pp, m), c) for pp, m, c in aggregation.summarize(self.root, self.people, "dev2", trace=lambda k, rel, n: theirs.append(n.split(":")[0])))
        for code in codes:
            self.assertIn(code, theirs)                                        # собственные дефекты видны владельцу
        self.assertEqual(rows2.get(("dev2", "2026-11")), 100)

    def test_foreign_files_bytes_read_are_bounded(self):
        # T3-fix раунд 1 (astra, MAJOR): байты, прочитанные из ЧУЖИХ файлов, — измеряются обёрткой над open:
        # чужой контейнер — не дальше конверта + один блок; чужой спутник — ровно первая строка; своих — целиком.
        # Ловит подмену _read_head → _read и _read_first_line → _read.
        import builtins
        foreign_c = next(rel for rel, o in self.owner.items() if o != "dev1")
        c_path = os.path.join(self.root, foreign_c)
        with open(c_path, "rb") as fh:
            head = fh.read()
        env_end = head.find(b"\n---\n", 4) + 5
        big_body = b"".join(b"2026-11-%02d 1.00  x <!--t:c%07x-->\n" % (1 + i % 28, i) for i in range(400))   # > 4096 байт тела
        with open(c_path, "wb") as fh:
            fh.write(head[:env_end] + big_body)
        s_path = c_path[:-3] + ".comments.md"
        first = b"<!-- comments-of: " + head[head.find(b"id: ") + 4:].split(b"\n", 1)[0].strip() + b" -->\n"
        with open(s_path, "wb") as fh:
            fh.write(first + b"\n" + b"### 2026-11-01T10:00:00+00:00 <!--c:aaaaaaaa-->\n" + b"x" * 20000 + b"\n")
        # второй чужой контейнер — CRLF-конверт + BOM (класс форм 01 §1.2/§2.5): предел тот же
        foreign2 = next(rel for rel, o in self.owner.items() if o != "dev1" and rel != foreign_c)
        c2_path = os.path.join(self.root, foreign2)
        with open(c2_path, "rb") as fh:
            head2 = fh.read()
        env2 = head2[:head2.find(b"\n---\n", 4) + 5]
        crlf_env = b"\xef\xbb\xbf" + env2.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        with open(c2_path, "wb") as fh:
            fh.write(crlf_env + big_body.replace(b"\n", b"\r\n"))
        counts = {}
        real_open = builtins.open
        class Counting:
            def __init__(self, fh, key): self.fh, self.key = fh, key
            def read(self, n=-1):
                d = self.fh.read(n); counts[self.key] = counts.get(self.key, 0) + len(d); return d
            def readline(self, n=-1):
                d = self.fh.readline(n); counts[self.key] = counts.get(self.key, 0) + len(d); return d
            def __enter__(self): return self
            def __exit__(self, *a): return self.fh.__exit__(*a)
            def __getattr__(self, k): return getattr(self.fh, k)
        def counting_open(path, mode="r", *a, **kw):
            fh = real_open(path, mode, *a, **kw)
            return Counting(fh, os.path.abspath(str(path))) if "b" in mode and str(path).startswith(self.root) else fh
        builtins.open = counting_open
        try:
            rows = aggregation.summarize(self.root, self.people, "dev1")
        finally:
            builtins.open = real_open
        self.assertTrue(rows)
        BLOCK = 4096                                                                                  # буква амендмента §3: «один блок 4096 байт» — не константа продукта
        self.assertLessEqual(counts[os.path.abspath(c_path)], env_end + BLOCK)                        # чужое тело не читалось
        self.assertLessEqual(counts[os.path.abspath(c2_path)], len(crlf_env) + BLOCK)                 # CRLF/BOM-конверт — тот же предел
        self.assertEqual(counts[os.path.abspath(s_path)], len(first))                                 # чужой спутник — первая строка
        own = next(rel for rel, o in self.owner.items() if o == "dev1")
        self.assertEqual(counts[os.path.abspath(os.path.join(self.root, own))] % os.path.getsize(os.path.join(self.root, own)), 0)  # своё — целиком (голова + остаток)
        self.assertGreaterEqual(counts[os.path.abspath(os.path.join(self.root, own))], os.path.getsize(os.path.join(self.root, own)))

    def test_personal_rows_equal_oracle_person_mode(self):
        import subprocess
        oracle = os.path.join(MONO, "harness", "d15_summary_oracle.py")
        for who in sorted(set(self.owner.values())):
            r = subprocess.run([sys.executable, oracle, "--emit", "--repo", self.root, "--person", who],
                               stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(r.returncode, 0, (who, r.stderr))
            self.assertEqual(aggregation.render_tsv(aggregation.summarize(self.root, self.people, who)), r.stdout, who)


class ReusedReadersTests(unittest.TestCase):
    """Регрессии класса «переиспользуемые читатели» (адверсарий T2 раунд 2): кольцо отзывов нечётной длины, CRLF-спутник,
    Unicode-цифры в токене времени заголовка — читатель undo/comment, которым сводка обязана пользоваться (контракт §3)."""
    def _hdr(self, ts, cid, link, target):
        return "### %s · dev1 <!--c:%s %s%s-->\nтело\n\n" % (ts, cid, link, target)

    def test_retraction_cycles_of_any_length_are_inactive(self):
        import undo
        C = lambda n: "0199c000-0000-7000-8000-%012d" % n   # noqa: E731
        for n in (2, 3, 4, 5):
            # кольцо: C1 retracts C2, C2 retracts C3, …, Cn retracts C1; каждый ещё отзывает строку-якорь
            text = "<!-- comments-of: x -->\n\n"
            for i in range(1, n + 1):
                text += self._hdr("2026-09-0%dT10:00:00Z" % i, C(i), "retracts:", C(i % n + 1))
                text += self._hdr("2026-09-0%dT11:00:00Z" % i, C(100 + i), "retracts:t:", "aaaa%04d" % i)
            hdrs = undo.parse_sibling(text.encode("utf-8"))
            self.assertEqual([undo.comment_active(C(i), hdrs) for i in range(1, n + 1)], [False] * n, n)
            self.assertTrue(all(undo.comment_active(C(100 + i), hdrs) for i in range(1, n + 1)))   # вне кольца — действуют
        # кольцо с внешним действующим отзывом одного участника: наименьшая неподвижная точка решает соседа
        text = "<!-- comments-of: x -->\n\n" + self._hdr("2026-09-01T10:00:00Z", C(1), "retracts:", C(2)) + \
            self._hdr("2026-09-02T10:00:00Z", C(2), "retracts:", C(1)) + self._hdr("2026-09-03T10:00:00Z", C(3), "retracts:", C(1))
        hdrs = undo.parse_sibling(text.encode("utf-8"))
        self.assertEqual([undo.comment_active(C(i), hdrs) for i in (1, 2, 3)], [False, True, True])

    def test_crlf_sibling_and_unicode_digit_timestamp(self):
        import undo
        lf = ("<!-- comments-of: x -->\n\n" + self._hdr("2026-09-06T10:00:00Z", "0199c000-0000-7000-8000-000000000001", "retracts:t:", "bbbb0004")).encode("utf-8")
        self.assertEqual(len(undo.parse_sibling(lf)), 1)
        self.assertEqual(len(undo.parse_sibling(lf.replace(b"\n", b"\r\n"))), 1)          # CRLF — тот же заголовок
        uni = ("<!-- comments-of: x -->\n\n" + self._hdr("\u0662\u0660\u0662\u0666-09-06T10:00:00Z", "0199c000-0000-7000-8000-000000000001", "retracts:t:", "bbbb0004")).encode("utf-8")
        self.assertEqual(undo.parse_sibling(uni), [])                                          # Unicode-цифры — не заголовок


class PeriodTests(unittest.TestCase):
    T = 1789639200   # 2026-09-20T10:00:00Z

    def test_current_and_previous_full_months(self):
        self.assertEqual(aggregation.period_months(self.T, "Europe/Belgrade", "current"), ("2026-09", "2026-09"))
        self.assertEqual(aggregation.period_months(self.T, "Europe/Belgrade", 1), ("2026-08", "2026-08"))
        self.assertEqual(aggregation.period_months(self.T, "Europe/Belgrade", 3), ("2026-06", "2026-08"))
        self.assertIsNone(aggregation.period_months(self.T, "Europe/Belgrade", "all"))

    def test_year_boundary_and_sender_zone(self):
        jan = 1798848000   # 2027-01-01T20:00:00Z
        self.assertEqual(aggregation.period_months(jan, "Europe/Belgrade", 1), ("2026-12", "2026-12"))
        self.assertEqual(aggregation.period_months(jan, "Europe/Belgrade", 13), ("2025-12", "2026-12"))
        edge = 1767227400  # 2026-01-01T00:30:00Z: в Калькутте уже январь, в Лос-Анджелесе ещё декабрь
        self.assertEqual(aggregation.period_months(edge, "Asia/Kolkata", "current"), ("2026-01", "2026-01"))
        self.assertEqual(aggregation.period_months(edge, "America/Los_Angeles", "current"), ("2025-12", "2025-12"))

    def test_delay_of_processing_does_not_change_period(self):
        # период — от message.date, не от момента обработки: ожидание — литерал из даты сообщения (не продукт с продуктом;
        # T3 раунд 1, astra MINOR), «сейчас» процесса подменяется и на результат не влияет
        import datetime as _dt
        class _Frozen(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2031, 6, 15, 12, 0, tzinfo=tz)
        real = _dt.datetime
        _dt.datetime = _Frozen
        try:
            self.assertEqual(aggregation.period_months(self.T, "UTC", 2), ("2026-07", "2026-08"))
            self.assertEqual(aggregation.period_months(self.T + 5 * 86400, "UTC", 2), ("2026-07", "2026-08"))
        finally:
            _dt.datetime = real

    def test_bad_n(self):
        with self.assertRaises(ValueError):
            aggregation.period_months(self.T, "UTC", 0)


class ReplyTests(unittest.TestCase):
    ROWS = [("dev1", "2026-08", 125), ("dev1", "2026-09", 3800), ("dev2", "2026-09", 500)]

    def test_forms(self):
        me = [r for r in self.ROWS if r[0] == "dev1"]
        self.assertEqual(aggregation.render_reply(aggregation.select(me, ("2026-09", "2026-09")), "me", ("2026-09", "2026-09"), False),
                         "мои часы за 2026-09\n2026-09 — 38.00 ч")
        self.assertEqual(aggregation.render_reply(me, "me", None, True), "мои часы за 2026-08…2026-09\n2026-08 — 1.25 ч\n2026-09 — 38.00 ч")
        self.assertEqual(aggregation.render_reply(aggregation.select(self.ROWS, ("2026-09", "2026-09")), "team", ("2026-09", "2026-09"), False),
                         "команда за 2026-09\ndev1\n2026-09 — 38.00 ч\ndev2\n2026-09 — 5.00 ч")
        self.assertEqual(aggregation.render_reply([], "me", ("2026-06", "2026-08"), False), "мои часы за 2026-06…2026-08: записей нет")
        self.assertEqual(aggregation.render_reply([], "team", None, True), "команда за все месяцы: записей нет")

    def test_no_zero_no_trailing_lf_no_at(self):
        text = aggregation.render_reply(self.ROWS, "team", None, True)
        self.assertNotIn("0.00", text); self.assertFalse(text.endswith("\n")); self.assertNotIn("@", text)
        self.assertEqual(aggregation.render_tsv([]), b"")


if __name__ == "__main__":
    unittest.main()
