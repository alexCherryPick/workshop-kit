"""Оракул yamlmini — ожидаемые значения построены РУКАМИ (литералы), не через дампер/лоадер
(правило CLAUDE.md: оракул не делит с писателем parser/encoder/helper)."""
import os
import sys
import unittest

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BOT)
import yamlmini  # noqa: E402


class LoadTests(unittest.TestCase):
    def test_block_mapping_and_sequence(self):
        text = "a: 1\nb:\n  - x\n  - y\nc:\n  d: true\n  e: null\n"
        self.assertEqual(yamlmini.loads(text), {"a": 1, "b": ["x", "y"], "c": {"d": True, "e": None}})

    def test_sequence_of_mappings_same_line(self):
        text = "steps:\n  - name: a\n    run: b\n  - run: c\n"
        self.assertEqual(yamlmini.loads(text), {"steps": [{"name": "a", "run": "b"}, {"run": "c"}]})

    def test_flow_nodes(self):
        text = "t: {state: closed, outcomes: [a, \"b c\"], n: 2}\nempty: {}\nl: []\n"
        self.assertEqual(yamlmini.loads(text), {"t": {"state": "closed", "outcomes": ["a", "b c"], "n": 2}, "empty": {}, "l": []})

    def test_duplicate_key_is_error(self):
        with self.assertRaises(yamlmini.YamlError):
            yamlmini.loads("a: 1\na: 2\n")
        with self.assertRaises(yamlmini.YamlError):
            yamlmini.loads("m: {a: 1, a: 2}\n")

    def test_forbidden_features(self):
        for bad in ("a: &x 1\n", "a: *x\n", "a: !!str 1\n", "a: 1\n---\nb: 2\n", "\ta: 1\n", "a: 1\r\n"):
            with self.assertRaises(yamlmini.YamlError, msg=bad):
                yamlmini.loads(bad)

    def test_on_off_stay_strings(self):
        self.assertEqual(yamlmini.loads("s: on\nt: off\nu: yes\n"), {"s": "on", "t": "off", "u": "yes"})

    def test_quoted_scalars(self):
        self.assertEqual(yamlmini.loads('a: "x\\ny \\u00b7 z"\nb: \'it\'\'s\'\n'), {"a": "x\ny · z", "b": "it's"})

    def test_block_scalar_literal_and_folded(self):
        text = "a: |\n  one\n  two\n\n  four\nb: >-\n  p q\n  r\n"
        self.assertEqual(yamlmini.loads(text), {"a": "one\ntwo\n\nfour\n", "b": "p q r"})

    def test_comments(self):
        text = "# top\na: 1  # trailing\nb: \"x # not comment\"\n"
        self.assertEqual(yamlmini.loads(text), {"a": 1, "b": "x # not comment"})

    def test_secret_binding_plain(self):
        self.assertEqual(yamlmini.loads("T: ${{ secrets.X }}\n"), {"T": "${{ secrets.X }}"})


class DumpTests(unittest.TestCase):
    def test_dump_shape_and_final_newline(self):
        out = yamlmini.dumps({"a": 1, "b": ["x", {"k": "v", "k2": [1, 2]}], "c": {"d": True, "e": None}, "s": "on"})
        # `on` в этом подмножестве — строка и при чтении, поэтому дампится plain и читается обратно той же строкой
        self.assertEqual(out, 'a: 1\nb:\n  - x\n  - k: v\n    k2:\n      - 1\n      - 2\nc:\n  d: true\n  e: null\ns: on\n')
        self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"))

    def test_dump_multiline_block(self):
        self.assertEqual(yamlmini.dumps({"t": "x\ny\n"}), "t: |\n  x\n  y\n")

    def test_dump_quotes_when_needed(self):
        self.assertEqual(yamlmini.dumps({"a": "1", "b": "", "c": "x: y", "d": "- z"}), 'a: "1"\nb: ""\nc: "x: y"\nd: "- z"\n')

    def test_dump_sort_keys(self):
        self.assertEqual(yamlmini.dumps({"b": 1, "a": 2}, sort_keys=True), "a: 2\nb: 1\n")

    def test_roundtrip_of_arbitrary_text(self):
        # дампер обязан кодировать так, чтобы лоадер вернул те же байты текста (start_text в файле состояния)
        s = "заголовок первой строкой\nхвост \"в кавычках\" \\ и tab\tконец"
        self.assertEqual(yamlmini.loads(yamlmini.dumps({"t": s})), {"t": s})


if __name__ == "__main__":
    unittest.main()
