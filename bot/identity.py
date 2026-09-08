# -*- coding: utf-8 -*-
"""identity — разрешение отправителя по карте людей: from.id → человек (контракт §4, П-8; REQ-065/090).
Владелец — T4. Чистый модуль: карта подаётся значением (читает её вызывающий через yamlmini на
каждом прогоне — кэша и констант нет); запись pending-записи и счётчиков — T3 (тем же коммитом).

Атрибуция — СТРОГО по `from.id` отправителя: сигнатура resolve() не принимает chat.id вовсе, поэтому
подмена чата маршрут изменить не может по построению (личный чат и группа — одинаково).

resolve(people, from_id, from_name, settings) → dict:
  kind: 'known'        — запись найдена (active или pending): person = запись;
        'pending_new'  — незнакомый при self_registration on: person = НОВАЯ запись pending
                         (handle tg-<id>, name из мессенджера, timezone = default_timezone), new_entry = она же;
        'rejected'     — незнакомый при self_registration off: исход 7 контракта, rejection = {telegram_id}.
Грамматики (контракт §4): handle человека ^[a-z0-9]+(-[a-z0-9]+)*$ (имя файла), handle бота — author конверта.
"""

import re

PERSON_HANDLE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
AUTHOR_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}$")
PENDING_PREFIX = "tg-"

__all__ = ["resolve", "find_by_telegram_id", "pending_handle", "bot_author_present", "people_list", "append_entry", "validate_people_doc"]

STATUSES = ("active", "pending")


def _zone_ok(tz):
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(tz)
        return True
    except Exception:  # noqa: BLE001 — любая причина = зона не разрешена
        return False


def validate_people_doc(doc, bot_handle=None, require_admin=False):
    """ЕДИНСТВЕННАЯ проверка формы карты людей (install.py check-people зовёт её же; поллер — на каждом
    прогоне через people_list). Ошибка формы — ValueError = собственная ошибка инструмента (исход 13),
    а не «незнакомый отправитель». Возвращает (число записей, число админов с telegram_id)."""
    people = doc.get("people") if isinstance(doc, dict) else None
    if not isinstance(people, list) or not people:
        raise ValueError("карта людей: нет списка people")
    handles, aliases = set(), set()
    seen = {"telegram_id": {}, "forge_login": {}}
    bot_seen, admins = False, 0
    for p in people:
        if not isinstance(p, dict):
            raise ValueError("карта людей: запись не отображение")
        h = p.get("handle")
        if not h or not isinstance(h, str):
            raise ValueError("карта людей: запись без handle")
        for f in ("name", "timezone"):
            if not p.get(f) or not isinstance(p.get(f), str):
                raise ValueError("карта людей: у %s нет обязательного поля %s" % (h, f))
        if h in handles:
            raise ValueError("карта людей: дубль handle %s" % h)
        handles.add(h)
        if p.get("kind") == "bot":
            if not AUTHOR_HANDLE_RE.match(h):
                raise ValueError("карта людей: handle бота %s не по грамматике author" % h)
        elif not PERSON_HANDLE_RE.match(h):
            raise ValueError("карта людей: handle %s не по грамматике person имени файла" % h)
        if p.get("status") not in STATUSES:
            raise ValueError("карта людей: у %s status не active|pending" % h)
        if not _zone_ok(p["timezone"]):
            raise ValueError("карта людей: у %s timezone %r не IANA-зона" % (h, p["timezone"]))
        for field, table in seen.items():
            if field in p and p[field] is not None:
                v = p[field]
                if field == "telegram_id" and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
                    raise ValueError("карта людей: у %s telegram_id %r не положительное целое" % (h, v))
                if field == "forge_login" and (not isinstance(v, str) or not v):
                    raise ValueError("карта людей: у %s forge_login пуст" % h)
                if v in table:
                    raise ValueError("карта людей: %s %r у двух записей (%s и %s) — атрибуция неоднозначна" % (field, v, table[v], h))
                table[v] = h
        if p.get("role") == "admin" and isinstance(p.get("telegram_id"), int) and not isinstance(p.get("telegram_id"), bool):
            admins += 1
        al = p.get("aliases")
        if al is not None and not isinstance(al, list):
            raise ValueError("карта людей: у %s aliases не список" % h)
        for a in al or []:
            if not isinstance(a, str) or a in aliases:
                raise ValueError("карта людей: alias %r не уникален или не строка" % (a,))
            aliases.add(a)
        if h == bot_handle:
            bot_seen = True
    if aliases & handles:
        raise ValueError("карта людей: alias совпадает с handle: %s" % sorted(aliases & handles))
    if bot_handle is not None and not bot_seen:
        raise ValueError("карта людей: handle бота %r отсутствует — конверты бота получили бы W-AUTHOR-UNKNOWN" % bot_handle)
    if require_admin and admins == 0:
        raise ValueError("карта людей: нет ни одной записи role: admin с telegram_id — сторожу некому писать (watchdog.alarm_to: admins)")
    return len(people), admins


def people_list(doc):
    """Список записей карты — ТОЛЬКО после строгой проверки формы (мягкого чтения нет: тип-дрейф поля
    карты не превращает известного человека в незнакомого)."""
    validate_people_doc(doc)
    return doc["people"]


def _taken_names(people):
    out = set()
    for p in people:
        out.add(p.get("handle"))
        out.update(p.get("aliases") or [])
    return out


def find_by_telegram_id(people, from_id):
    """Ровно одна запись с этим telegram_id (bool не считается целым); дубль — ошибка карты."""
    if isinstance(from_id, bool) or not isinstance(from_id, int):
        raise ValueError("from.id обязан быть целым")
    hits = [p for p in people if isinstance(p, dict) and p.get("telegram_id") == from_id and not isinstance(p.get("telegram_id"), bool)]
    if len(hits) > 1:
        raise ValueError("карта людей: telegram_id %d у нескольких записей — атрибуция неоднозначна" % from_id)
    return hits[0] if hits else None


def pending_handle(from_id):
    h = "%s%d" % (PENDING_PREFIX, int(from_id))
    if not PERSON_HANDLE_RE.match(h):
        raise ValueError("временный handle не по грамматике: %r" % h)
    return h


def resolve(people, from_id, from_name, settings):
    p = find_by_telegram_id(people, from_id)
    if p is not None:
        if not PERSON_HANDLE_RE.match(str(p.get("handle"))):
            raise ValueError("карта людей: handle %r не по грамматике person имени файла" % p.get("handle"))
        return {"kind": "known", "person": p, "new_entry": None, "rejection": None}
    mode = str(settings.get("self_registration", "on")).lower()
    if mode == "on":
        if pending_handle(from_id) in _taken_names(people):
            raise ValueError("карта людей: временный handle %s уже занят handle/alias другой записи без telegram_id — сверка карты нужна руками" % pending_handle(from_id))
        entry = {"handle": pending_handle(from_id), "name": (from_name or pending_handle(from_id)),
                 "timezone": settings.get("default_timezone", "UTC"), "telegram_id": int(from_id),
                 "status": "pending", "aliases": []}
        return {"kind": "pending_new", "person": entry, "new_entry": entry, "rejection": None}
    if mode == "off":
        return {"kind": "rejected", "person": None, "new_entry": None, "rejection": {"telegram_id": int(from_id)}}
    raise ValueError("self_registration обязан быть on|off, получено %r" % settings.get("self_registration"))


def append_entry(doc, entry):
    """Новая карта с дописанной записью (чистая функция; байты пишет T3 через yamlmini.dumps)."""
    people = people_list(doc)
    if find_by_telegram_id(people, entry["telegram_id"]) is not None:
        return doc  # уже есть — второй записи нет
    if entry["handle"] in _taken_names(people):
        raise ValueError("карта людей: handle %s уже занят handle/alias другой записи — дописывание дало бы карту, которую check-people отвергнет" % entry["handle"])
    new = dict(doc)
    new["people"] = list(people) + [dict(entry)]
    return new


def alarm_targets(people, alarm_to):
    """Адресаты сторожа/алярма (bot.yaml watchdog.alarm_to): целое — chat_id как есть; `admins` — id мессенджера
    всех записей role: admin. Карту читает ТОЛЬКО этот модуль (T1 §17: второго реестра людей нет)."""
    if isinstance(alarm_to, int) and not isinstance(alarm_to, bool):
        return [alarm_to]
    return [p["telegram_id"] for p in people if p.get("role") == "admin" and isinstance(p.get("telegram_id"), int) and not isinstance(p.get("telegram_id"), bool)]


def bot_author_present(people, bot_handle):
    """handle бота — в карте (иначе W-AUTHOR-UNKNOWN); грамматика author конверта."""
    if not AUTHOR_HANDLE_RE.match(str(bot_handle)):
        return False
    return any(isinstance(p, dict) and p.get("handle") == bot_handle for p in people)
