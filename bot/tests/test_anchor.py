# -*- coding: utf-8 -*-
"""Оракул якоря: ожидания пересчитаны hashlib'ом ПРЯМО В ТЕСТЕ по формуле контракта §1Г(г)
(домен, NUL-разделители), не импортом функций писателя для вычисления ожиданий."""
import hashlib, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import anchor  # noqa: E402


def ref(identity, k, step):
    return hashlib.sha256(b"\x00".join([b"workshop-d09-anchor-v1", identity.encode(), str(k).encode(), str(step).encode()])).hexdigest()[:8]


class AnchorTests(unittest.TestCase):
    def test_formula_and_determinism(self):
        i = anchor.identity(100000001, 4123)
        self.assertEqual(i, "tg:100000001:4123")
        self.assertEqual(anchor.derive(i), ref(i, 0, 0))
        self.assertEqual(anchor.derive(i, 1), ref(i, 1, 0))
        self.assertEqual(anchor.derive(i, 0, 3), ref(i, 0, 3))
        self.assertEqual(anchor.derive(i), anchor.derive(i))          # тот же вход → тот же якорь
        self.assertNotEqual(anchor.derive(i), anchor.derive("tg:100000001:41230"))  # суффиксная подмена
        self.assertNotEqual(anchor.derive(i, 0), anchor.derive(i, 1))

    def test_negative_chat_id_and_bad_identity(self):
        self.assertEqual(anchor.identity(-1001234, 7), "tg:-1001234:7")
        with self.assertRaises(ValueError):
            anchor.derive("chat:1:2")

    def test_remint_identical_and_collision(self):
        i = "tg:1:2"
        a0 = ref(i, 0, 0)
        line0 = "2026-09-07 1.00  x"
        existing = {a0: line0 + " <!--t:%s-->" % a0}
        self.assertEqual(anchor.remint(i, 0, existing, line0), (a0, 0, True))   # тождество
        existing = {a0: "2026-09-07 2.00  другое <!--t:%s-->" % a0}
        a, step, ident = anchor.remint(i, 0, existing, line0)
        self.assertEqual((a, step, ident), (ref(i, 0, 1), 1, False))           # переминт шагом соли
        self.assertEqual(anchor.remint(i, 0, existing, line0), (a, step, ident))  # повтор даёт тот же переминт

    def test_existing_anchors_from_body(self):
        body = "2026-09-07 1.00  a <!--t:0a1b2c3d-->\n  продолжение\n2026-09-08 2.00  b <!--t:1b2c3d4e-->\n".encode()
        ex = anchor.existing_anchors(body)
        self.assertEqual(sorted(ex), ["0a1b2c3d", "1b2c3d4e"])


class Round2Tests(unittest.TestCase):
    def test_empty_title_candidate_contract(self):
        # Н-6: договор о кандидате — «строка без якоря» = build_line без последних len(" <!--t:00000000-->") байт;
        # при пустом заголовке кандидат оканчивается ОДНИМ пробелом, и тождество распознаётся
        import line as line_mod
        ident = "tg:1:2"
        a = anchor.derive(ident, 0, 0)
        full = line_mod.build_line("2026-09-07", 3600, "", a)
        cand = line_mod.build_line("2026-09-07", 3600, "", "00000000")[: -len(" <!--t:00000000-->")]
        self.assertTrue(cand.endswith(" "))
        self.assertEqual(anchor.remint(ident, 0, {a: full}, cand), (a, 0, True))
        # обратный контроль: иная строка под тем же якорем — переминт
        self.assertEqual(anchor.remint(ident, 0, {a: full + "x"}, cand)[2], False)


if __name__ == "__main__":
    unittest.main()
