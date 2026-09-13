# -*- coding: utf-8 -*-
"""Оракул сборки строки и Н1: ожидания — из буквы D04 (кейсы 00:33:18→0.56, 00:00:54→0.02),
перебор всех длительностей 1 с..24 ч против ЭТАЛОНА на Decimal ROUND_HALF_UP (не плавающей и не
функций писателя); маршрут — по грамматике имени файла; разрез — по известным инстантам."""
import decimal, os, re, subprocess, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import line  # noqa: E402

BIN = os.environ.get("BIN", os.path.expanduser("~/repos/workshop/validator/target/release/workshop-validator"))
LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) ((?:0|[1-9][0-9]{0,2})\.[0-9]{2})(?: (\S+Z/\S+Z))?  (.*) <!--t:[0-9a-f]{8}-->$")


def ref_hours(s):
    d = (decimal.Decimal(s) / decimal.Decimal(3600)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)
    return "%s" % d


class N1Tests(unittest.TestCase):
    def test_letter_cases(self):
        self.assertEqual(line.n1_hours(1998), "0.56")   # 00:33:18 — кейс REQ-048
        self.assertEqual(line.n1_hours(54), "0.02")     # анти-тест плавающей: двоичная даёт 0.01
        self.assertEqual(line.n1_hours(17), "0.00")     # край: продюсер переспрашивает (валидатор HOURS_RANGE)
        self.assertEqual(line.n1_hours(18), "0.01")
        self.assertEqual(line.n1_hours(24 * 3600), "24.00")

    def test_full_sweep_against_decimal_and_count_float_divergence(self):
        diverge = 0
        for s in range(1, 24 * 3600 + 1):
            got = line.n1_hours(s)
            self.assertEqual(got, ref_hours(s), s)
            if ("%.2f" % (s / 3600.0)) != got:
                diverge += 1
        sys.stderr.write("[N1 sweep] 1..86400: расхождений с наивным round(): %d\n" % diverge)
        self.assertGreater(diverge, 0)


class LineTests(unittest.TestCase):
    def test_build_line_shape(self):
        ln = line.build_line("2026-09-07", 9600, "созвон  по релизу", "deadbeef", (1757239200, 1757248800))
        m = LINE_RE.match(ln)
        self.assertIsNotNone(m, ln)
        self.assertEqual(m.group(2), "2.67")
        self.assertEqual(m.group(3), "2025-09-07T10:00:00Z/2025-09-07T12:40:00Z")
        self.assertEqual(m.group(4), "созвон  по релизу")   # внутри заголовка пробелы дословно
        ln2 = line.build_line("2026-09-07", 3600, "", "deadbeef")
        self.assertEqual(ln2, "2026-09-07 1.00  <!--t:deadbeef-->")
        ln3 = line.build_line("2026-09-07", 3600, "  с ведущими  ", "deadbeef")
        self.assertTrue(ln3.startswith("2026-09-07 1.00  с ведущими <!--t:"))

    def test_route_and_envelope(self):
        self.assertEqual(line.route("2026-09-07", "dev-one"), "time/TIMESHEET-2026-09-dev-one.md")
        self.assertEqual(line.route("2026-02-01", "p07", "padel"), "time/padel-TIMESHEET-2026-02-p07.md")
        with self.assertRaises(ValueError):
            line.route("2026-09-07", "Dev_One")
        env = line.envelope("019550fa-1ea0-773c-b820-1e2b73ab4901", "dev-one", "2028-02-10", "Europe/Belgrade", "workshop_bot", "2028-02-10")
        self.assertIn("period_start: 2028-02-01\nperiod_end: 2028-02-29\n", env)   # високосный февраль
        for key in ("id:", "type: TIMESHEET", "line_form: daily_time_v1", "title:", "person: dev-one", "timezone: Europe/Belgrade", "created: 2028-02-10", "author: workshop_bot", "version: 1"):
            self.assertIn(key, env)
        self.assertTrue(env.startswith("---\n") and env.endswith("---\n"))

    def test_midnight_split_belgrade_and_negative_control(self):
        segs = line.split_at_local_midnight(1752698400, 1752707700, "Europe/Belgrade")  # 22:40→01:15 местных 16/17.07.2025
        self.assertEqual(segs, [(1752698400, 1752703200, 0), (1752703200, 1752707700, 1)])
        self.assertEqual(line.local_date(1752698400, "Europe/Belgrade"), "2025-07-16")
        self.assertEqual(line.local_date(1752703200, "Europe/Belgrade"), "2025-07-17")
        self.assertEqual(line.split_at_local_midnight(1752698400, 1752707700, "America/Los_Angeles"), [(1752698400, 1752707700, 0)])  # та же сессия — одна строка
        with self.assertRaises(ValueError):
            line.split_at_local_midnight(5, 5, "UTC")

    def test_dst_spring_hours_are_elapsed_time(self):
        # 2025-03-30 00:30Z→02:15Z Europe/Belgrade: по стенным часам 2:45, прожито 1:45 (D04 гл.03 §3.3)
        self.assertEqual(line.n1_hours(1743295500 - 1743289200), "1.75")
        self.assertEqual(line.split_at_local_midnight(1743289200, 1743295500, "Europe/Belgrade"), [(1743289200, 1743295500, 0)])

    @unittest.skipUnless(os.path.exists(BIN), "нет бинаря валидатора")
    def test_validator_rc_mapping(self):
        rc, rep = line.check_line_rc(BIN, "2026-09-07 1.50  зонд <!--t:0badf00d-->", "time/TIMESHEET-2026-09-dev1.md")
        self.assertEqual(rc, 0); self.assertIn("precondition", rep.lower() + rep)
        self.assertEqual(line.rc_to_outcome(rc, rep)[0], "recorded")
        rc, rep = line.check_line_rc(BIN, "2026-09-07 0.00  ноль <!--t:0badf00d-->", "time/TIMESHEET-2026-09-dev1.md")
        self.assertEqual(rc, 2); self.assertEqual(line.rc_to_outcome(rc, rep), ("reask_invalid", "HOURS_RANGE"))
        rc, rep = line.check_line_rc(BIN, "2026-09-07 0:33  x", "time/TIMESHEET-2026-09-dev1.md")
        self.assertEqual(line.rc_to_outcome(rc, rep), ("reask_invalid", "MALFORMED_RECORD"))
        rc, rep = line.check_line_rc("/nonexistent/validator", "2026-09-07 1.00  x", "time/x.md")
        self.assertEqual(rc, 127); self.assertEqual(line.rc_to_outcome(rc, rep)[0], "tool_failure")
        self.assertEqual(line.rc_to_outcome(10, "")[0], "tool_failure")
        self.assertEqual(line.rc_to_outcome(3, "")[0], "run_refused")



    def test_first_rule_prefers_form_address_over_code_inside_it(self):
        """Раунд 1, №8: «§04.3.4 №ERROR-4» → человеку уходит адрес формы, не слово ERROR."""
        self.assertEqual(line._first_rule("ERROR: §04.3.4 №ERROR-4 — дубль id коммента"), "§04.3.4 №ERROR-4")
        self.assertEqual(line._first_rule("ERROR: HOURS_RANGE hours 0.00"), "HOURS_RANGE")
        self.assertEqual(line._first_rule("WARNING: W-ID-VERSION container id"), "W-ID-VERSION")
        self.assertEqual(line.rc_to_outcome(2, "precondition ok\nERROR: §04.3.4 №ERROR-4 x"), ("reask_invalid", "§04.3.4 №ERROR-4"))

if __name__ == "__main__":
    unittest.main()
