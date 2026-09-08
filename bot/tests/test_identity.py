# -*- coding: utf-8 -*-
"""Оракул атрибуции: карта читается тестом построчным регэкспом из шаблона (не yamlmini/identity для
ожиданий); PII — положительный контракт на закрытом синтетическом множестве."""
import os, re, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import identity  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "kit", "templates", "people.yaml")
SYNTHETIC_IDS = {100000001, 100000002, 100000003, 100000004, 100000005, 100000009}
SYNTHETIC_HANDLES = {"dev-one", "dev-two", "dev-three", "dev0", "dev1", "dev2", "dev3", "dev4", "dev5", "p07", "workshop_bot", "tg-100000009", "tg-100000003"}
# ПОЛОЖИТЕЛЬНЫЙ контракт на ИМЕНА: закрытое множество строк фикстур (охота за именами открыта по построению — правило §2)
SYNTHETIC_NAMES = {"Пример Один (только мессенджер; админ — адресат сторожа)", "Пример Два (только форжа)",
                   "Пример Три (мессенджер и форжа)", "Бот учёта времени (author конверта контейнеров, которые создаёт бот)",
                   "Новый Человек", "Кто угодно", "x", "Имя"}


def template_people():
    rows, cur = [], None
    for ln in open(TEMPLATE, encoding="utf-8"):
        m = re.match(r"^  - handle: (\S+)", ln)
        if m:
            cur = {"handle": m.group(1)}; rows.append(cur); continue
        m = re.match(r"^    (telegram_id|timezone|status|role|name|kind|forge_login): (.*)$", ln)
        if m and cur is not None:
            v = m.group(2).strip().strip('"')
            cur[m.group(1)] = int(v) if m.group(1) == "telegram_id" else v
            continue
        m = re.match(r"^    aliases: \[(.*)\]$", ln)
        if m and cur is not None:
            cur["aliases"] = [a.strip() for a in m.group(1).split(",") if a.strip()]
    for r in rows:
        r.setdefault("aliases", [])
    return rows


SETTINGS_ON = {"self_registration": "on", "default_timezone": "Europe/Belgrade"}
SETTINGS_OFF = {"self_registration": "off", "default_timezone": "Europe/Belgrade"}


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.people = template_people()

    def test_known_by_from_id_never_by_chat(self):
        r = identity.resolve(self.people, 100000003, "Кто угодно", SETTINGS_ON)
        self.assertEqual((r["kind"], r["person"]["handle"], r["person"]["timezone"]), ("known", "dev-three", "Asia/Tbilisi"))
        import inspect
        self.assertNotIn("chat", inspect.signature(identity.resolve).parameters)   # структурно: чата в сигнатуре нет

    def test_unknown_on_is_pending_new(self):
        r = identity.resolve(self.people, 100000009, "Новый Человек", SETTINGS_ON)
        self.assertEqual(r["kind"], "pending_new")
        e = r["new_entry"]
        self.assertEqual((e["handle"], e["name"], e["timezone"], e["telegram_id"], e["status"], e["aliases"]),
                         ("tg-100000009", "Новый Человек", "Europe/Belgrade", 100000009, "pending", []))
        doc = {"schema_version": 1, "people": self.people}
        doc2 = identity.append_entry(doc, e)
        self.assertEqual(len(doc2["people"]), len(self.people) + 1)
        doc3 = identity.append_entry(doc2, e)                     # повтор того же id — второй записи нет
        self.assertEqual(len(doc3["people"]), len(doc2["people"]))
        r2 = identity.resolve(doc2["people"], 100000009, "x", SETTINGS_ON)
        self.assertEqual((r2["kind"], r2["person"]["status"]), ("known", "pending"))

    def test_unknown_off_is_rejected_with_counter_record(self):
        r = identity.resolve(self.people, 100000009, "x", SETTINGS_OFF)
        self.assertEqual((r["kind"], r["person"], r["rejection"]), ("rejected", None, {"telegram_id": 100000009}))
        with self.assertRaises(ValueError):
            identity.resolve(self.people, 100000009, "x", {"self_registration": "maybe"})

    def test_duplicate_transport_identity_is_error_not_guess(self):
        dup = self.people + [{"handle": "dev-nine", "telegram_id": 100000003, "timezone": "UTC", "name": "x", "aliases": []}]
        with self.assertRaises(ValueError):
            identity.resolve(dup, 100000003, "x", SETTINGS_ON)
        with self.assertRaises(ValueError):
            identity.resolve(self.people, True, "x", SETTINGS_ON)

    def test_handle_grammars(self):
        bad = [{"handle": "dev_1", "telegram_id": 100000004, "timezone": "UTC", "name": "x", "aliases": []}]
        with self.assertRaises(ValueError):
            identity.resolve(bad, 100000004, "x", SETTINGS_ON)
        self.assertTrue(identity.bot_author_present(self.people, "workshop_bot"))
        self.assertFalse(identity.bot_author_present(self.people, "other_bot"))
        self.assertFalse(identity.bot_author_present(self.people, "Bad Bot"))

    def test_pii_positive_contract(self):
        ids = {p["telegram_id"] for p in self.people if "telegram_id" in p} | {100000009}
        handles = {p["handle"] for p in self.people} | {a for p in self.people for a in p["aliases"]}
        names = {p["name"] for p in self.people}
        self.assertTrue(ids <= SYNTHETIC_IDS, ids - SYNTHETIC_IDS)
        self.assertTrue(handles <= SYNTHETIC_HANDLES, handles - SYNTHETIC_HANDLES)
        self.assertTrue(names <= SYNTHETIC_NAMES, names - SYNTHETIC_NAMES)
        self.assertEqual([p["aliases"] for p in self.people if p["handle"] == "dev-three"], [["tg-100000003"]])  # оракул читает aliases

    # --- регрессии раунда 1 (B-2, W-5): строгая карта, тип-дрейф × {on, off}, коллизия временного handle
    def test_map_type_drift_is_tool_error_not_stranger(self):
        for settings in (SETTINGS_ON, SETTINGS_OFF):
            people = [dict(p) for p in self.people]
            people[0]["telegram_id"] = "100000001"          # строка вместо целого (ручная правка карты)
            with self.assertRaises(ValueError):
                identity.people_list({"schema_version": 1, "people": people})
            with self.assertRaises(ValueError):
                identity.append_entry({"schema_version": 1, "people": people}, {"handle": "tg-100000009", "telegram_id": 100000009})
        bad = [dict(p) for p in self.people]; del bad[0]["timezone"]
        with self.assertRaises(ValueError):
            identity.validate_people_doc({"people": bad})
        bad = [dict(p) for p in self.people]; bad[1]["status"] = "weird"
        with self.assertRaises(ValueError):
            identity.validate_people_doc({"people": bad})
        bad = [dict(p) for p in self.people]; bad[1]["telegram_id"] = 100000001   # дубль у ДРУГОЙ записи
        with self.assertRaises(ValueError):
            identity.validate_people_doc({"people": bad})
        self.assertEqual(identity.validate_people_doc({"people": self.people}, "workshop_bot", require_admin=True)[1], 1)

    def test_pending_handle_collision_is_error(self):
        people = [dict(p) for p in self.people]
        people[2] = dict(people[2]); del people[2]["telegram_id"]     # админ снял telegram_id, alias tg-100000003 остался
        with self.assertRaises(ValueError):
            identity.resolve(people, 100000003, "x", SETTINGS_ON)
        with self.assertRaises(ValueError):
            identity.append_entry({"people": people}, {"handle": "tg-100000003", "name": "x", "timezone": "UTC", "telegram_id": 100000003, "status": "pending", "aliases": []})


if __name__ == "__main__":
    unittest.main()
