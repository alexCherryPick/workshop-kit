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
        big_body = b"".join(b"2026-11-%02d 1.00  x <!--t:c%07x-->\n" % (1 + i % 28, i) for i in range(400))   # большое тело
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
            fh.write(crlf_env + b"2026-11-01 1.00  x <!--t:c0000001-->\r\n")                            # МАЛОЕ тело: блочное чтение прочло бы его целиком
        counts = {}
        real_open = builtins.open
        import io
        class CountingRaw(io.RawIOBase):
            """Считает байты, ВЫБРАННЫЕ из файла (readinto сырого файла) — не возвращённые вызывающему: буферизованное
            чтение выбирает блок 8192 и прочло бы чужое тело (clean-room codex по REQ-108 v10 «ни байта тела»)."""
            def __init__(self, raw, key): super().__init__(); self.raw, self.key = raw, key
            def readinto(self, b):
                n = self.raw.readinto(b); counts[self.key] = counts.get(self.key, 0) + (n or 0); return n
            def readable(self): return True
            def seekable(self): return False
            def close(self):
                self.raw.close(); super().close()
        def counting_open(path, mode="r", buffering=-1, *a, **kw):
            if "b" in mode and "r" in mode and str(path).startswith(self.root):
                raw = CountingRaw(io.FileIO(path, "r"), os.path.abspath(str(path)))
                return raw if buffering == 0 else io.BufferedReader(raw)
            return real_open(path, mode, buffering, *a, **kw)
        builtins.open = counting_open
        try:
            rows = aggregation.summarize(self.root, self.people, "dev1")
        finally:
            builtins.open = real_open
        self.assertTrue(rows)
        self.assertEqual(counts[os.path.abspath(c_path)], env_end)                                    # чужой контейнер — ровно конверт, ни байта тела
        self.assertEqual(counts[os.path.abspath(c2_path)], len(crlf_env))                             # CRLF/BOM-конверт — ровно конверт
        self.assertEqual(counts[os.path.abspath(s_path)], len(first))                                 # чужой спутник — первая строка
        own = os.path.join(self.root, next(rel for rel, o in self.owner.items() if o == "dev1"))
        with open(own, "rb") as fh:
            own_data = fh.read()
        own_env = own_data.find(b"\n---\n", 4) + 5
        self.assertEqual(counts[os.path.abspath(own)], own_env + len(own_data))                       # своё — конверт (обнаружение) + целиком

    def test_head_boundary_equals_full_read_boundary(self):
        # T3-fix раунд 3 (astra, BLOCKER): смешанные LF/CRLF и `---` второй строкой — построчная голова кончалась раньше,
        # чем envelope_fields видит терминатор; личная сводка теряла собственную запись. Инвариант: для любого входа
        # envelope_fields(голова) == envelope_fields(весь файл) и суммы личного режима == командного для этого человека.
        cases = {
            "mixed_crlf": b"---\nperson: dev1\n---\r\n---\n2026-11-01 1.00  work <!--t:a0a0a0a1-->\n",
            "empty_then_keys": b"---\n---\nperson: dev1\n---\n2026-11-01 1.00  work <!--t:a0a0a0a2-->\n",
            "crlf_all": b"\xef\xbb\xbf---\r\nperson: dev1\r\n---\r\n2026-11-01 1.00  work <!--t:a0a0a0a3-->\r\n",
            "no_terminator": b"---\nperson: dev1\n2026-11-01 1.00  work <!--t:a0a0a0a4-->\n",
            "terminator_no_lf": b"---\nperson: dev1\n---",
            "dashes_in_value": b"---\ntitle: a\n---\nperson: dev1\n---\n2026-11-01 1.00  work <!--t:a0a0a0a5-->\n",
            "no_envelope": b"2026-11-01 1.00  work <!--t:a0a0a0a6-->\n",
            "three_bytes": b"---",
            "empty": b"",
        }
        for name, raw in cases.items():
            p = os.path.join(self.root, "time", "TIMESHEET-2026-11-%s.md" % name)
            with open(p, "wb") as fh:
                fh.write(raw)
            self.assertEqual(aggregation.envelope_fields(aggregation._read_head(p)), aggregation.envelope_fields(raw), name)
        team = [r for r in aggregation.summarize(self.root, self.people) if r[0] == "dev1"]
        mine = aggregation.summarize(self.root, self.people, "dev1")
        self.assertEqual(mine, team)
        self.assertEqual(dict(((m, c) for _p, m, c in mine)).get("2026-11"), 300)   # mixed_crlf, empty_then_keys, crlf_all; dashes_in_value — person за первым терминатором, пропуск

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


ORACLE = os.path.join(MONO, "harness", "d15_summary_oracle.py")


def oracle_reply(rows, scope, rng, limit=4096):
    """Ожидаемый ответ §4.4 и части — НЕЗАВИСИМЫЙ оракул отдельным процессом (вход — TSV, собранный здесь, не render_tsv)."""
    import json, subprocess
    data = "".join("%s\t%s\t%d\n" % r for r in rows).encode("utf-8")
    argv = [sys.executable, ORACLE, "--reply", "--tsv", "-", "--scope", scope, "--range", "all" if rng is None else "%s..%s" % rng,
            "--limit", str(limit)]
    p = subprocess.run(argv, input=data, capture_output=True)
    if p.returncode != 0:
        raise AssertionError("оракул rc=%d: %r %r" % (p.returncode, p.stdout[-300:], p.stderr[-300:]))
    return json.loads(p.stdout.decode("utf-8"))


def by_bytes(rows):
    return sorted(rows, key=lambda r: (r[0].encode("utf-8"), r[1]))


def product(rows, scope, rng, requested_all=None):
    return aggregation.render_reply(aggregation.select(rows, rng), scope, rng, rng is None if requested_all is None else requested_all)


class ReplyTests(unittest.TestCase):
    ROWS = [("dev1", "2026-08", 125), ("dev1", "2026-09", 3800), ("dev2", "2026-09", 500)]

    def test_forms(self):
        me = [r for r in self.ROWS if r[0] == "dev1"]
        self.assertEqual(aggregation.render_reply(aggregation.select(me, ("2026-09", "2026-09")), "me", ("2026-09", "2026-09"), False),
                         "мои часы за 2026-09\n2026-09 — 38.00 ч")
        self.assertEqual(aggregation.render_reply(me, "me", None, True), "мои часы за 2026-08…2026-09\n2026-08 — 1.25 ч\n2026-09 — 38.00 ч")
        # амендмент §4.4 (summary-month, 2026-10-03): командный ответ по месяцам + «всего»
        self.assertEqual(aggregation.render_reply(aggregation.select(self.ROWS, ("2026-09", "2026-09")), "team", ("2026-09", "2026-09"), False),
                         "команда за 2026-09 — всего 43.00 ч\ndev1 — 38.00 ч\ndev2 — 5.00 ч")
        self.assertEqual(aggregation.render_reply(self.ROWS, "team", None, True),
                         "команда за 2026-08…2026-09\n\n2026-08 — всего 1.25 ч\ndev1 — 1.25 ч\n\n2026-09 — всего 43.00 ч\ndev1 — 38.00 ч\ndev2 — 5.00 ч")
        self.assertEqual(product(self.ROWS, "team", ("2026-07", "2026-09")),
                         "команда за 2026-07…2026-09\n\n2026-08 — всего 1.25 ч\ndev1 — 1.25 ч\n\n2026-09 — всего 43.00 ч\ndev1 — 38.00 ч\ndev2 — 5.00 ч")
        self.assertEqual(aggregation.render_reply([], "me", ("2026-06", "2026-08"), False), "мои часы за 2026-06…2026-08: записей нет")
        self.assertEqual(aggregation.render_reply([], "team", None, True), "команда за все месяцы: записей нет")
        self.assertEqual(aggregation.render_reply([], "team", ("2026-09", "2026-09"), False), "команда за 2026-09: записей нет")

    def test_no_zero_no_trailing_lf_no_at(self):
        text = aggregation.render_reply(self.ROWS, "team", None, True)
        self.assertNotIn("0.00", text); self.assertFalse(text.endswith("\n")); self.assertNotIn("@", text)
        self.assertNotIn("\n\n\n", text)
        self.assertEqual(aggregation.render_tsv([]), b"")


class ReplyMutationMatrixTests(unittest.TestCase):
    """Матрица мутаций ответа пакетом (правило сходимости §5; поручение summary-month п. 4): продукт == независимый
    оракул на законных входах; мутации actual и порча helper продукта обязаны расходиться с оракулом."""
    BASE = by_bytes([("anna", "2026-07", 99), ("bob", "2026-07", 1), ("anna", "2026-08", 1250), ("carl", "2026-08", 333),
                     ("anna", "2026-09", 2608), ("bob", "2026-09", 750), ("carl", "2026-09", 42)])

    def legit_inputs(self):
        big = by_bytes([("p%03d" % i, "2026-%02d" % m, 1 + (i * 37 + m * 11) % 1000) for i in range(128) for m in range(1, 13)])
        return [
            ("три месяца", self.BASE, "team", ("2026-07", "2026-09")),
            ("all", self.BASE, "team", None),
            ("один месяц", self.BASE, "team", ("2026-09", "2026-09")),
            ("диапазон с пустыми месяцами", self.BASE, "team", ("2026-01", "2026-12")),
            ("перенос через 100 сотых", [("a", "2026-09", 99), ("b", "2026-09", 1), ("c", "2026-10", 50), ("d", "2026-10", 50)], "team", None),
            ("перенос, итог 10.00", by_bytes([("p%d" % k, "2026-09", 125) for k in range(8)]), "team", ("2026-09", "2026-09")),
            ("один человек", [("solo", "2026-09", 1)], "team", ("2026-09", "2026-09")),
            ("один человек, all", [("solo", "2026-08", 7), ("solo", "2026-09", 993)], "team", None),
            ("UTF-8 байты handle", by_bytes([("z", "2026-09", 1), ("a-b", "2026-09", 2), ("a", "2026-09", 3), ("a0", "2026-09", 4)]), "team", None),
            ("крупные часы", [("a", "2026-09", 99999), ("b", "2026-09", 1)], "team", None),
            ("128×12", big, "team", None),
            ("личный", [("anna", "2026-07", 99), ("anna", "2026-09", 2608)], "me", None),
            ("пустой диапазон", self.BASE, "team", ("2025-01", "2025-03")),
        ]

    def test_product_equals_independent_oracle_on_legit_inputs(self):
        for name, rows, scope, rng in self.legit_inputs():
            want = oracle_reply(rows, scope, rng)
            self.assertEqual(product(rows, scope, rng), want["text"], name)

    def test_legit_permutation_of_input_rows_is_control(self):
        # законная перестановка: порядок входных строк (не по байтам) не меняет командный ответ — обратный контроль на ложное
        # срабатывание (личный ответ, не менявшийся амендментом, по-прежнему получает строки summarize в порядке TSV)
        import random
        rnd = random.Random(20261003)
        for name, rows, scope, rng in self.legit_inputs():
            if scope != "team":
                continue
            shuffled = list(rows); rnd.shuffle(shuffled)
            self.assertEqual(product(shuffled, scope, rng), oracle_reply(rows, scope, rng)["text"], name)

    def actual_mutants(self, text):
        lines = text.split("\n")
        person_idx = [k for k, l in enumerate(lines) if l and " — всего " not in l and " за " not in l]
        total_idx = [k for k, l in enumerate(lines) if " — всего " in l]
        blocks = text.split("\n\n")
        def bump(line, d):
            num = line.rsplit(" ", 2)[1]
            c = int(num.replace(".", "")) + d
            return line.replace(" " + num + " ", " %d.%02d " % (c // 100, c % 100))
        return {
            "потеря человека": "\n".join(lines[:person_idx[0]] + lines[person_idx[0] + 1:]),
            "сумма месяца +1 сотая": "\n".join(bump(l, 1) if k == total_idx[0] else l for k, l in enumerate(lines)),
            "сумма месяца −1 сотая": "\n".join(bump(l, -1) if k == total_idx[-1] else l for k, l in enumerate(lines)),
            "перестановка месяцев": "\n\n".join([blocks[0], blocks[2], blocks[1]] + blocks[3:]),
            "перестановка людей": "\n".join(lines[:person_idx[0]] + [lines[person_idx[1]], lines[person_idx[0]]] + lines[person_idx[1] + 1:]),
            "дубликат строки": "\n".join(lines + [lines[-1]]),
            "суффиксная подмена handle": text.replace("anna — ", "annaa — ", 1),
            "подмена той же длины": text.replace("26.08", "26.09", 1),
            "обнуление": "",
            "строка месяца у человека (прежняя форма)": text.replace("anna — ", "anna\n2026-07 — ", 1),
            "общий итог поверх месяцев": text + "\n\nвсего 47.83 ч",
            "@ перед handle": text.replace("anna — ", "@anna — ", 1),
            "пустые строки сняты": text.replace("\n\n", "\n"),
            "завершающий LF": text + "\n",
        }

    def test_actual_mutations_are_caught(self):
        want = oracle_reply(self.BASE, "team", ("2026-07", "2026-09"))["text"]
        got = product(self.BASE, "team", ("2026-07", "2026-09"))
        self.assertEqual(got, want)                                                     # контроль
        caught = dict((k, v != want) for k, v in self.actual_mutants(got).items())
        self.assertEqual([k for k, ok in caught.items() if not ok], [], caught)
        self.assertGreaterEqual(len(caught), 14)

    def test_input_mutations_change_expected(self):
        # мутации ИСТОЧНИКА: оракул пересчитывает expected, продукт обязан совпасть с новым (а не со старым)
        rng = ("2026-07", "2026-09")
        base = oracle_reply(self.BASE, "team", rng)["text"]
        variants = {
            "потеря человека": [r for r in self.BASE if not (r[0] == "carl" and r[1] == "2026-08")],
            "сотая у одного": [(p, m, c + 1 if (p, m) == ("bob", "2026-07") else c) for p, m, c in self.BASE],
            "перенос через 100": [(p, m, 100 if (p, m) == ("anna", "2026-07") else c) for p, m, c in self.BASE],
            "сдвиг часов между месяцами": [(p, "2026-08" if (p, m) == ("bob", "2026-07") else m, c) for p, m, c in self.BASE
                                           if (p, m) != ("bob", "2026-08")],
        }
        for name, rows in variants.items():
            rows = by_bytes(rows)
            want = oracle_reply(rows, "team", rng)["text"]
            self.assertNotEqual(want, base, name)
            self.assertEqual(product(rows, "team", rng), want, name)

    def test_helper_corruption_diverges_from_oracle(self):
        rng = ("2026-07", "2026-09")
        want = oracle_reply(self.BASE, "team", rng)["text"]
        orig_hours = aggregation._hours
        mutants = {
            "_hours без ведущего нуля": lambda c: "%d.%d" % (c // 100, c % 100),
            "_hours через float до десятых": lambda c: "%.1f0" % (c / 100.0),
            "_hours усечение сотых": lambda c: "%d.%02d" % (c // 100, (c % 100) // 10 * 10),
        }
        silent = []
        for name, fn in mutants.items():
            aggregation._hours = fn
            try:
                if product(self.BASE, "team", rng) == want:
                    silent.append(name)
            finally:
                aggregation._hours = orig_hours
        self.assertEqual(silent, [])
        self.assertEqual(product(self.BASE, "team", rng), want)

    def test_locale_does_not_change_bytes(self):
        import subprocess
        code = ("import sys, json, locale\nsys.path.insert(0, %r); sys.path.insert(0, %r)\n"
                "try:\n    locale.setlocale(locale.LC_ALL, '')\nexcept locale.Error:\n    pass\n"
                "import aggregation\nrows = %r\n"
                "sys.stdout.buffer.write(aggregation.render_reply(rows, 'team', None, True).encode('utf-8'))\n" % (BOT, os.path.join(BOT, "kit"), self.BASE))
        outs = set()
        for loc in ("C", "en_US.UTF-8", "ru_RU.UTF-8", "tr_TR.UTF-8"):
            p = subprocess.run([sys.executable, "-c", code], capture_output=True, env=dict(os.environ, LC_ALL=loc, LANG=loc))
            self.assertEqual(p.returncode, 0, p.stderr)
            outs.add(p.stdout)
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs.pop().decode("utf-8"), oracle_reply(self.BASE, "team", None)["text"])


class TransportSplitTests(unittest.TestCase):
    """Транспортное разбиение §4.4 (амендмент): части продукта == части независимого оракула; блок месяца не рвётся без
    необходимости; длинный блок — разрыв только между строками людей; ни одно число не теряется и не дублируется."""

    @staticmethod
    def chunks(text, limit):
        import poll
        return poll._chunks(text, limit)

    def battery(self):
        big = by_bytes([("p%03d" % i, "2026-%02d" % m, 1 + (i * 37 + m * 11) % 1000) for i in range(128) for m in range(1, 13)])
        long_h = by_bytes([("subcontractor-%03d-workshop" % i, "2026-%02d" % m, 125 + i) for i in range(128) for m in range(1, 13)])
        small = ReplyMutationMatrixTests.BASE
        return [("128×12", big, None), ("128×12 длинные handle", long_h, None), ("малый", small, None),
                ("один месяц 128", [r for r in long_h if r[1] == "2026-03"], ("2026-03", "2026-03"))]

    def test_parts_equal_oracle_on_limit_battery(self):
        n = 0
        for name, rows, rng in self.battery():
            text = product(rows, "team", rng)
            longest = max(len(l) for l in text.split("\n"))
            for lim in (longest, longest + 1, 64, 100, 257, 1000, 4096):
                if lim < longest:
                    continue
                want = oracle_reply(rows, "team", rng, lim)
                self.assertEqual(want["text"], text, name)
                got = self.chunks(text, lim)
                self.assertEqual(got, want["parts"], (name, lim))
                n += len(got)
                self.assertTrue(all(0 < len(p) <= lim and not p.startswith("\n") and not p.endswith("\n") for p in got), (name, lim))
                self.assertEqual([x for x in "\n".join(got).split("\n") if x], [x for x in text.split("\n") if x], (name, lim))
        self.assertGreater(n, 0)

    def test_month_block_not_split_when_it_fits_and_total_leads(self):
        rows = by_bytes([("p%02d" % i, "2026-%02d" % m, 125) for i in range(25) for m in range(1, 13)])
        text = product(rows, "team", None)
        parts = self.chunks(text, 4096)
        self.assertGreater(len(parts), 1)
        for b in text.split("\n\n")[1:]:
            self.assertEqual(sum(1 for p in parts if b in p), 1)                      # блок целиком в одной части
        for p in parts[1:]:
            self.assertRegex(p.split("\n")[0], r"^2026-[0-9]{2} — всего [0-9]+\.[0-9]{2} ч$")

    def test_oversize_block_breaks_only_between_people(self):
        rows = [("subcontractor-%03d-workshop" % i, "2026-09", 125 + i) for i in range(128)]
        text = product(rows, "team", ("2026-09", "2026-09"))
        self.assertGreater(len(text), 4096)
        parts = self.chunks(text, 4096)
        self.assertEqual(parts[0].split("\n")[0], "команда за 2026-09 — всего %d.%02d ч" % (sum(125 + i for i in range(128)) // 100, sum(125 + i for i in range(128)) % 100))
        for p in parts[1:]:
            self.assertTrue(all(l.startswith("subcontractor-") for l in p.split("\n")), p[:80])

    def test_split_mutations_are_caught(self):
        rows = by_bytes([("subcontractor-%03d-workshop" % i, "2026-%02d" % m, 125 + i) for i in range(128) for m in (1, 2)])
        text = product(rows, "team", None)
        want = oracle_reply(rows, "team", None)["parts"]
        got = self.chunks(text, 4096)
        self.assertEqual(got, want)
        self.assertGreaterEqual(len(got), 3)
        self.assertEqual(got[0], "команда за 2026-01…2026-02")                         # блок 2026-01 длиннее лимита — с новой части
        a, b = got[1], got[2]                                                          # разрез внутри блока 2026-01
        last_line = a.split("\n")[-1]
        rest = got[3:]
        mutants = {
            "дубликат строки на разрезе": [got[0], a, last_line + "\n" + b] + rest,
            "потеря строки на разрезе": [got[0], a.rsplit("\n", 1)[0], b] + rest,
            "строка перенесена через разрез": [got[0], a.rsplit("\n", 1)[0], last_line + "\n" + b] + rest,
            "пустая строка в начале части": [got[0], a, "\n" + b] + rest,
            "части переставлены": [got[0], b, a] + rest,
            "склейка двух частей": [got[0], a + "\n" + b] + rest,
            "заголовок приклеен к блоку": [got[0] + "\n\n" + a, b] + rest,
        }
        self.assertEqual([k for k, v in mutants.items() if v == want], [])

    def test_text_without_blank_lines_splits_as_before(self):
        # обратный контроль: текст без пустых строк (личный ответ, список заголовков) режется прежним правилом строк
        text = "\n".join("строка %04d — 1.25 ч" % k for k in range(400))
        parts = self.chunks(text, 4096)
        self.assertEqual("\n".join(parts), text)
        self.assertTrue(all(len(p) <= 4096 for p in parts))
        self.assertTrue(all(len(parts[k]) + 1 + len(parts[k + 1].split("\n")[0]) > 4096 for k in range(len(parts) - 1)))


if __name__ == "__main__":
    unittest.main()
