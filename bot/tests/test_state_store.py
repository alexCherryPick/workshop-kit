# -*- coding: utf-8 -*-
"""Оракул файлов состояния (T3): ожидания — из байтов на диске (cmp/regex), без импорта yamlmini для
ожиданий; форма файла состояния прогона — из tg-bot.yaml poll_state_file (построчный регэксп)."""
import os, re, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import state_store as ss  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CONTRACT = os.path.join(ROOT, "spec", "09-tg-bot-time-line", "tg-bot.yaml")
if not os.path.exists(CONTRACT):
    CONTRACT = os.path.join(ROOT, "output", "format-spec", "09-tg-bot-time-line", "tg-bot.yaml")
TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "kit", "templates", "bot-sessions.yaml")


def contract_state_fields():
    out, inside = [], False
    for ln in open(CONTRACT, encoding="utf-8"):
        if ln.startswith("poll_state_file:"):
            inside = True; continue
        if inside and ln and not ln.startswith(" "):
            break
        m = re.match(r"^    - \{name: (\w+),", ln)
        if inside and m:
            out.append(m.group(1))
    return out


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.t, ".workshop"))

    def tearDown(self):
        shutil.rmtree(self.t)

    def raw(self, rel):
        with open(os.path.join(self.t, rel), "rb") as fh:
            return fh.read()

    def test_state_fields_match_contract_and_bytes_are_deterministic(self):
        st = ss.empty_state()
        self.assertEqual(sorted(st), sorted(contract_state_fields()))
        ss.write_state(self.t, st); a = self.raw(ss.STATE_PATH)
        ss.write_state(self.t, dict(reversed(list(st.items())))); b = self.raw(ss.STATE_PATH)
        self.assertEqual(a, b)                                   # порядок ключей входа не влияет на байты
        self.assertTrue(a.endswith(b"\n") and not a.endswith(b"\n\n"))
        keys = [l.split(b":")[0] for l in a.split(b"\n") if l and not l.startswith(b" ")]
        self.assertEqual(keys, sorted(keys))                     # стабильный (отсортированный) порядок ключей
        self.assertEqual(ss.read_state(self.t), st)

    def test_template_without_top_schema_is_accepted_and_written_with_schema(self):
        shutil.copy(TEMPLATE, os.path.join(self.t, ss.SESSIONS_PATH))
        doc = ss.read_sessions(self.t)
        self.assertEqual((doc["schema_version"], doc["sessions"]), (ss.SESSIONS_SCHEMA, {}))
        ss.write_sessions(self.t, doc)
        self.assertIn(b"schema_version: 1", self.raw(ss.SESSIONS_PATH))

    def test_missing_files_are_empty_and_bad_files_are_tool_errors(self):
        self.assertEqual(ss.read_state(self.t)["offset"], 0)
        self.assertEqual(ss.read_sessions(self.t)["sessions"], {})
        for rel, body in ((ss.STATE_PATH, b"- just a list\n"), (ss.STATE_PATH, b"schema_version: 2\noffset: 0\n"),
                          (ss.STATE_PATH, b"schema_version: 1\noffset: '5'\nunknown_rejections: []\nself_registrations: []\nsecret_rejections: []\n"),
                          (ss.SESSIONS_PATH, b"sessions: []\n"), (ss.SESSIONS_PATH, b"schema_version: 1\nsessions: {}\nsessions: {}\n")):
            with open(os.path.join(self.t, rel), "wb") as fh:
                fh.write(body)
            with self.assertRaises(ss.StateError, msg=body):
                (ss.read_state if rel == ss.STATE_PATH else ss.read_sessions)(self.t)

    def test_pure_mutations_and_list_cap(self):
        st = ss.empty_state()
        st2 = ss.set_offset(st, 5)
        self.assertEqual((st["offset"], st2["offset"]), (0, 5))
        for i in range(ss.LIST_CAP + 50):
            st2 = ss.record_rejection(st2, 100000009, 1000 + i)
        self.assertEqual(len(st2["unknown_rejections"]), ss.LIST_CAP)
        self.assertEqual(st2["unknown_rejections"][-1]["at"], 1000 + ss.LIST_CAP + 49)   # хранятся ПОСЛЕДНИЕ
        self.assertEqual(st["unknown_rejections"], [])
        d = ss.empty_sessions()
        rec = {"title": "x", "started_at": 1, "schema_version": 1}
        d2 = ss.open_session(d, "dev-one", rec)
        self.assertEqual((d["sessions"], list(d2["sessions"])), ({}, ["dev-one"]))
        d3 = ss.close_session(d2, "dev-one")
        self.assertEqual((list(d2["sessions"]), d3["sessions"]), (["dev-one"], {}))
        ss.write_sessions(self.t, d2); a = self.raw(ss.SESSIONS_PATH)
        ss.write_sessions(self.t, ss.open_session(ss.empty_sessions(), "dev-one", dict(rec))); b = self.raw(ss.SESSIONS_PATH)
        self.assertEqual(a, b)                                   # одна и та же мутация — cmp-равные байты


if __name__ == "__main__":
    unittest.main()
