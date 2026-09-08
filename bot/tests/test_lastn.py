# -*- coding: utf-8 -*-
"""Оракул списка последних: ожидания — по объявленному правилу порядка (дата ↓, обратный порядок в
файле, схлопывание дубликата), фикстуры строятся тестом в mktemp; sha256 трёх прогонов равны."""
import hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lastn  # noqa: E402

ENV = "---\nid: 019550fa-1ea0-773c-b820-1e2b73ab4901\ntype: TIMESHEET\nline_form: daily_time_v1\ntitle: t\nperson: %s\nperiod_start: 2026-09-01\nperiod_end: 2026-09-30\ntimezone: UTC\ncreated: 2026-09-01\nauthor: workshop_bot\nversion: 1\n---\n"


class LastnTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.t, "time"))
        self.w("TIMESHEET-2026-09-dev-one.md", ENV % "dev-one" + "2026-09-05 1.00  первое <!--t:aaaaaaaa-->\n2026-09-06 2.00 2026-09-06T08:00:00Z/2026-09-06T10:00:00Z  второе <!--t:bbbbbbbb-->\n2026-09-06 1.00  третье <!--t:cccccccc-->\n  продолжение третьего\n\n2026-09-06 0.50  второе <!--t:dddddddd-->\n2026-09-06 0.25\n")
        self.w("TIMESHEET-2026-08-dev-one.md", ENV % "dev-one" + "2026-08-30 1.00  августовское\n")
        self.w("TIMESHEET-2026-09-dev-two.md", ENV % "dev-two" + "2026-09-07 1.00  чужое <!--t:eeeeeeee-->\n")
        self.w("padel-TIMESHEET-2026-09-dev-one.md", ENV % "dev-one" + "2026-09-07 1.00  из namespace\n")

    def tearDown(self):
        shutil.rmtree(self.t)

    def w(self, name, text):
        open(os.path.join(self.t, "time", name), "w", encoding="utf-8").write(text)

    def test_order_dedupe_and_own_only(self):
        got = lastn.titles(self.t, "dev-one", 10)
        self.assertEqual(got, ["второе", "третье", "первое", "августовское"])   # 06.09: обратный порядок в файле; дубль «второе» схлопнут; пустой не показан
        self.assertNotIn("чужое", got); self.assertNotIn("из namespace", got)
        self.assertEqual(lastn.titles(self.t, "dev-one", 2), ["второе", "третье"])
        self.assertEqual(lastn.titles(self.t, "dev-one", 10, namespace="padel"), ["из namespace"])
        self.assertEqual([os.path.basename(p) for p in lastn.own_containers(self.t, "dev-one")], ["TIMESHEET-2026-08-dev-one.md", "TIMESHEET-2026-09-dev-one.md"])

    def test_titles_verbatim_nbsp_and_trailing_bytes(self):
        # раунд 1, находка 3: свободный текст дословно (ядро 03.2.1) — NBSP и хвостовые байты не снимаются
        self.w("TIMESHEET-2026-07-dev-three.md", ENV % "dev-three" + "2026-07-01 1.00  Задача <!--t:aaaaaaa1-->\n2026-07-02 1.00  Задача\u00a0 <!--t:aaaaaaa2-->\n2026-07-03 1.00  без якоря  \n")
        got = lastn.titles(self.t, "dev-three", 3)
        self.assertEqual(got, ["без якоря  ", "Задача\u00a0", "Задача"])

    def test_three_runs_identical_sha(self):
        shas = {hashlib.sha256(json.dumps(lastn.titles(self.t, "dev-one", 10), ensure_ascii=False).encode()).hexdigest() for _ in range(3)}
        self.assertEqual(len(shas), 1)

    def test_no_time_dir(self):
        self.assertEqual(lastn.titles(tempfile.mkdtemp(), "dev-one", 5), [])


class Round2Tests(unittest.TestCase):
    def test_single_space_separator_is_still_a_record(self):
        # Н-5: один пробел перед свободным текстом — неканон (SEPARATOR_NONCANONICAL), но ЗАПИСЬ (ядро 03.2.3)
        t = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(t, "time"))
            with open(os.path.join(t, "time", "TIMESHEET-2026-09-dev-one.md"), "w", encoding="utf-8") as fh:
                fh.write(ENV % "dev-one" + "2026-09-07 1.00 одним пробелом\n2026-09-06 1.00  двумя\n2026-09-05 2.00 2026-09-05T08:00:00Z/2026-09-05T10:00:00Z с интервалом одним\n")
            self.assertEqual(lastn.titles(t, "dev-one", 5), ["одним пробелом", "двумя", "с интервалом одним"])
        finally:
            shutil.rmtree(t)


if __name__ == "__main__":
    unittest.main()
