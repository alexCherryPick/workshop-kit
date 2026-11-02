# -*- coding: utf-8 -*-
"""Оракул реестров адаптера вложений (D20 T2): attach/norm.py == генерация из attachments.yaml.

Независимость: норма читается здесь PyYAML (НЕ yamlmini, которым пользуется генератор), sha256 —
hashlib над байтами файла. Тест роняет прогон, если (1) норма сменилась без перегенерации,
(2) файл правили руками, (3) константа расходится с узлом нормы, (4) ключи кода (предикаты маршрута,
шаги чтения, правила переходов) расходятся с реестрами — проверено мутацией реестра при импорте."""
import hashlib
import importlib
import os
import subprocess
import sys
import unittest

import yaml

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_BOT)
sys.path.insert(0, _BOT)
import attach.norm as N  # noqa: E402

_CODE_MODULES = ("attach", "attach.core", "attach.pointer")
NORM = os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml")


def _norm():
    with open(NORM, "rb") as f:
        raw = f.read()
    return raw, yaml.safe_load(raw.decode("utf-8"))


class Pin(unittest.TestCase):
    def test_source_sha256_pinned(self):
        raw, _ = _norm()
        self.assertEqual(N.SOURCE_SHA256, hashlib.sha256(raw).hexdigest(),
                         "attachments.yaml сменился: перегенерируй bot/attach/norm.py (bot/kit/gen_attach_norm.py)")

    def test_generated_file_equals_regeneration(self):
        r = subprocess.run([sys.executable, os.path.join(_BOT, "kit", "gen_attach_norm.py"), "--check"],
                           cwd=_ROOT, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Semantic(unittest.TestCase):
    """Каждая константа — против узла нормы, прочитанного независимым парсером."""

    @classmethod
    def setUpClass(cls):
        cls.n = _norm()[1]

    def test_pointer(self):
        p = self.n["pointer"]
        self.assertEqual(N.POINTER_MAGIC_PREFIX, p["magic_prefix"])
        self.assertEqual(N.POINTER_MAGIC_LINE, p["magic_line"])
        self.assertEqual(N.POINTER_FIRST_LINE_PATTERN, p["first_line_pattern"])   # поправка d20/norm-amend
        self.assertEqual(N.POINTER_VERSION_PATTERN, p["version_pattern"])
        self.assertEqual(list(N.POINTER_KNOWN_VERSIONS), [str(v) for v in p["known_versions"]])
        self.assertEqual(N.POINTER_MAX_BYTES, p["max_bytes"])
        self.assertEqual(list(N.POINTER_FIELD_ORDER), p["field_order"])
        self.assertEqual(dict(N.POINTER_FIELD_PATTERNS), {f["name"]: f["pattern"] for f in p["fields"]})
        self.assertEqual(dict(N.POINTER_FIELD_MAX_LEN), {f["name"]: f["max_len"] for f in p["fields"] if "max_len" in f})
        self.assertEqual({s: dict(r) for s, r in N.POINTER_PRESENCE}, p["presence"])

    def test_states_transitions_reasons(self):
        st = self.n["states"]
        self.assertEqual([(s, c, list(r)) for s, c, r in N.STATES],
                         [(x["state"], x["carrier"], x.get("reasons", [])) for x in st["list"]])
        self.assertEqual(list(N.TRANSITIONS), [(t["from"], t["to"]) for t in st["transitions"]])
        self.assertEqual(list(N.TERMINAL_STATES), st["terminal"])
        self.assertEqual(dict(N.UNSAVED_REASONS), {r["reason"]: r["user_mark"] for r in self.n["unsaved"]["reasons"]})

    def test_outcomes_and_order(self):
        ao = self.n["adapter_outcomes"]
        self.assertEqual(list(N.READ_OUTCOMES), [o["outcome"] for o in ao["read"]])
        self.assertEqual(list(N.WRITE_OUTCOMES), [o["outcome"] for o in ao["write"]])
        self.assertEqual(" -> ".join(N.READ_ORDER), ao["read_order"])
        self.assertIs(N.VERIFICATION_REQUIRES_LOCAL_HASH, ao["verification_requires_local_hash"])

    def test_routing_threshold_binding(self):
        self.assertEqual([(s, w, o, r) for s, w, o, r in N.ROUTING_STEPS],
                         [(x["step"], x["when"], x["outcome"], x.get("reason")) for x in self.n["routing"]["steps"]])
        self.assertEqual(N.GIT_THRESHOLD_DEFAULT, self.n["soft_limit"]["bytes"])
        self.assertEqual(N.GIT_THRESHOLD_DEFAULT, 8000000)   # §6.2: слово alex — число в главе
        self.assertEqual(N.THRESHOLD_COMPARISON, self.n["soft_limit"]["comparison"])
        self.assertEqual(list(N.CONFIG_FACTS), [f["fact"] for f in self.n["storage_binding"]["config_facts"]])

    def test_t4_contract_registries(self):
        """D20 T4: смысл исходов, факты статуса, формы ссылок, экранирование подписи, глоб — против PyYAML-разбора."""
        ao = self.n["adapter_outcomes"]
        self.assertEqual(list(N.READ_OUTCOME_MEANINGS), [(o["outcome"], o["meaning"]) for o in ao["read"]])
        self.assertEqual(list(N.WRITE_OUTCOME_MEANINGS), [(o["outcome"], o["meaning"]) for o in ao["write"]])
        self.assertEqual(list(N.STATUS_FACTS), self.n["storage_binding"]["status_facts"])
        self.assertEqual(list(N.LINK_FORMS), [(f["form"], f["syntax"], f["base"]) for f in self.n["link_forms"]["forms"]])
        self.assertEqual(list(N.CAPTION_ESCAPE_CHARS), self.n["filename"]["original_name"]["escaping_required_chars"])
        self.assertEqual(N.GLOB_ALL_ATTACHMENTS, self.n["layout"]["glob_all_attachment_bytes"])

    def test_layout_filename_key_lfs(self):
        self.assertEqual(N.PATH_PATTERN, self.n["layout"]["path_pattern"])
        self.assertEqual(N.FILENAME_PATTERN, self.n["filename"]["pattern"])
        c = self.n["filename"]["components"]
        self.assertEqual((N.SLUG_PATTERN, N.SLUG_MAX_LEN, N.EXT_PATTERN),
                         (c["slug"]["pattern"], c["slug"]["max_len"], c["ext"]["pattern"]))
        self.assertEqual(N.OBJECT_KEY_DERIVATION, self.n["object_key"]["derivation"])
        self.assertEqual(N.LFS_SIGNATURE_PREFIX, self.n["lfs"]["signature_prefix"])


class ProseAgainstIndependentParse(unittest.TestCase):
    """Проза, которую код исполняет, сверена с независимым разбором нормы (PyYAML): текст правил переходов и
    дайджесты, против которых написан код (attach.pointer.IMPLEMENTED_PROSE)."""

    def test_transition_rules_and_pins(self):
        n = _norm()[1]
        st = n["states"]
        self.assertEqual(list(N.TRANSITION_RULES), [(x["from"], x["to"], x["rule"]) for x in st["transitions"]])
        d = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]  # noqa: E731
        indep = {("transition", x["from"], x["to"]): d(x["rule"]) for x in st["transitions"]}
        indep[("pointer", "presence_extra")] = d(n["pointer"]["presence_extra"])
        indep[("pointer", "encoding")] = d(n["pointer"]["encoding"])
        indep[("states", "write_failure")] = d(st["write_failure"])
        indep[("states", "pending_requires_durable_queue")] = d(st["pending_requires_durable_queue"])
        pointer = importlib.import_module("attach.pointer")
        self.assertEqual(indep, pointer.IMPLEMENTED_PROSE)


class CodeKeysFollowRegistry(unittest.TestCase):
    """Мутация реестра → импорт кода падает NormDrift (ключи кода не рукописная копия, а сверяются)."""

    def _reimport_with(self, attr, value):
        orig = getattr(N, attr)
        setattr(N, attr, value)
        try:
            for m in _CODE_MODULES:
                sys.modules.pop(m, None)
            with self.assertRaises(Exception) as cm:
                importlib.import_module("attach.core")
            return cm.exception
        finally:
            setattr(N, attr, orig)
            for m in _CODE_MODULES:
                sys.modules.pop(m, None)
            importlib.import_module("attach.core")

    def test_transition_added(self):
        e = self._reimport_with("TRANSITIONS", tuple(N.TRANSITIONS) + (("stored", "unsaved"),))
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_transition_removed(self):
        e = self._reimport_with("TRANSITIONS", tuple(N.TRANSITIONS)[1:])
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_routing_when_changed(self):
        steps = list(N.ROUTING_STEPS)
        steps[2] = (3, "size < threshold", "git", None)
        e = self._reimport_with("ROUTING_STEPS", tuple(steps))
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_comparison_changed(self):
        e = self._reimport_with("THRESHOLD_COMPARISON", "greater_or_equal")
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_presence_state_dropped(self):
        e = self._reimport_with("POINTER_PRESENCE", tuple(N.POINTER_PRESENCE)[:-1])
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_transition_rule_meaning_changed(self):
        """Бэклог R1 п.7: смена СМЫСЛА rule перехода (текст), а не только SOURCE_SHA256, роняет импорт."""
        rules = list(N.TRANSITION_RULES)
        f, t, r = rules[0]
        rules[0] = (f, t, r + " и ещё условие")
        e = self._reimport_with("TRANSITION_RULES", tuple(rules))
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_presence_extra_meaning_changed(self):
        e = self._reimport_with("POINTER_PRESENCE_EXTRA", N.POINTER_PRESENCE_EXTRA + " и media-type")
        self.assertEqual(type(e).__name__, "NormDrift")

    def test_read_order_permuted_is_fault_at_read(self):
        attach = importlib.import_module("attach.core")
        orig = N.READ_ORDER
        N.READ_ORDER = tuple(reversed(orig))
        try:
            with self.assertRaises(attach.AdapterFault):
                attach.read_attachment(os.path.join(_ROOT, "spec", "03-spec-type-schemas", "examples", "attachments",
                                                    "01-git-bytes", "tickets", "issue", "2026-10", "2026-10-0",
                                                    "attachments", "0199a8c0-1a00-7a00-8a00-000000000701",
                                                    "0199a8c0-2b00-7b00-9b00-000000000701-crash-screen.png"),
                                       attach.load_config({}))
        finally:
            N.READ_ORDER = orig


if __name__ == "__main__":
    unittest.main()
