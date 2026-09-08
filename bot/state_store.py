# -*- coding: utf-8 -*-
"""state_store — единственный писатель ДВУХ файлов состояния комплекта (владелец — T3; контракт §1Б, §3):
  .workshop/bot-sessions.yaml — учёт «открыт/закрыт» (ключ — handle; запись существует ⟺ учёт открыт);
  .workshop/bot-state.yaml   — состояние прогона: подтверждённый offset (единственный авторитет),
                               отклонения неизвестных (self_registration off), самозаписи, отклонения-секреты.
Оба МУТИРУЮТСЯ НА МЕСТЕ, оба ВНЕ union; запись ДЕТЕРМИНИРОВАННА (yamlmini.dumps, стабильный порядок
ключей, LF, один финальный LF): прогон без новых обновлений оставляет git status пустым.
Оба помечены `-merge`: двусторонняя чужая правка — конфликт, громкий отказ (poll.py, исход 10).
Одностороннюю (только в origin) git сливает тривиально — её ловит poll.py сравнением файлов со
снимком чтения: ПЕРЕЧИТАТЬ (read_*), слить дельту telemetry батча, ПЕРЕСЧИТАТЬ решение; слепой повтор
ранее вычисленной мутации запрещён. mutate-функции принимают документ значением и возвращают новый.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yamlmini  # noqa: E402

SESSIONS_PATH = ".workshop/bot-sessions.yaml"
STATE_PATH = ".workshop/bot-state.yaml"
SESSIONS_SCHEMA = 1
STATE_SCHEMA = 1
LIST_CAP = 200  # ограничение списков отклонений/самозаписей — последние 200 (контракт §3)

__all__ = ["SESSIONS_PATH", "STATE_PATH", "read_sessions", "write_sessions", "read_state", "write_state",
           "empty_sessions", "empty_state", "open_session", "close_session", "record_rejection",
           "record_self_registration", "record_secret_rejection", "set_offset", "StateError"]


class StateError(Exception):
    """Файл состояния не читается / не по схеме — сбой инструмента (исход 13), не «пусто»."""


def _text_at_ref(root, ref, rel):
    """Байты файла в git-ref (например origin/main) — None, если файла там нет. Рабочая копия не участвует."""
    import subprocess
    r = subprocess.run(["git", "-C", root, "show", "%s:%s" % (ref, rel)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout.decode("utf-8") if r.returncode == 0 else None


def _read(root, rel, factory, schema_key, schema, schema_optional=False, ref=None):
    """ref=None — рабочая копия; ref='origin/<branch>' — АВТОРИТЕТ (сторож T5 читает только так)."""
    if ref is not None:
        text = _text_at_ref(root, ref, rel)
        if text is None:
            return factory()
        try:
            doc = yamlmini.loads(text)
        except yamlmini.YamlError as e:
            raise StateError("%s@%s не читается: %s" % (rel, ref, e))
    else:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            return factory()
        try:
            doc = yamlmini.load_file(path)
        except (yamlmini.YamlError, OSError) as e:
            raise StateError("%s не читается: %s" % (rel, e))
    if not isinstance(doc, dict):
        raise StateError("%s: корень обязан быть отображением" % rel)
    if schema_key not in doc and schema_optional:
        doc = dict(doc); doc[schema_key] = schema   # шаблон комплекта (sessions: {}) — схема по умолчанию
    if doc.get(schema_key) != schema:
        raise StateError("%s: schema_version %r, ожидается %r — миграция объявляется явно" % (rel, doc.get(schema_key), schema))
    return doc


def _write(root, rel, doc):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = yamlmini.dumps(doc, sort_keys=True).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return data


# ------------------------------------------------------------------ sessions
def empty_sessions():
    return {"schema_version": SESSIONS_SCHEMA, "sessions": {}}


def read_sessions_at(root, ref):
    """Файл состояния учёта В АВТОРИТЕТЕ (git-ref), не в рабочей копии."""
    doc = _read(root, SESSIONS_PATH, empty_sessions, "schema_version", SESSIONS_SCHEMA, schema_optional=True, ref=ref)
    if not isinstance(doc.get("sessions"), dict):
        raise StateError("%s@%s: sessions обязан быть отображением" % (SESSIONS_PATH, ref))
    return doc


def read_state_at(root, ref):
    """Файл состояния прогона В АВТОРИТЕТЕ (git-ref): offset для замера сторожа берётся ТОЛЬКО отсюда."""
    doc = _read(root, STATE_PATH, empty_state, "schema_version", STATE_SCHEMA, ref=ref)
    if not isinstance(doc.get("offset"), int) or isinstance(doc.get("offset"), bool):
        raise StateError("%s@%s: offset обязан быть целым" % (STATE_PATH, ref))
    for k in ("unknown_rejections", "self_registrations", "secret_rejections"):
        if not isinstance(doc.get(k), list):
            raise StateError("%s@%s: %s обязан быть списком" % (STATE_PATH, ref, k))
    return doc


def read_sessions(root):
    # шаблон T1 (`sessions: {}`) верхнего schema_version не несёт — версия схемы лежит В ЗАПИСИ (контракт §3);
    # файловый ключ добавляется первым же прогоном и далее обязателен.
    doc = _read(root, SESSIONS_PATH, empty_sessions, "schema_version", SESSIONS_SCHEMA, schema_optional=True)
    if not isinstance(doc.get("sessions"), dict):
        raise StateError("%s: sessions обязан быть отображением" % SESSIONS_PATH)
    return doc


def write_sessions(root, doc):
    return _write(root, SESSIONS_PATH, doc)


def open_session(doc, handle, record):
    new = {"schema_version": doc["schema_version"], "sessions": dict(doc["sessions"])}
    new["sessions"][handle] = dict(record)
    return new


def close_session(doc, handle):
    new = {"schema_version": doc["schema_version"], "sessions": dict(doc["sessions"])}
    new["sessions"].pop(handle, None)
    return new


# ------------------------------------------------------------------ poll state
def empty_state():
    return {"schema_version": STATE_SCHEMA, "offset": 0, "unknown_rejections": [], "self_registrations": [], "secret_rejections": []}


def read_state(root):
    doc = _read(root, STATE_PATH, empty_state, "schema_version", STATE_SCHEMA)
    if not isinstance(doc.get("offset"), int) or isinstance(doc.get("offset"), bool):
        raise StateError("%s: offset обязан быть целым" % STATE_PATH)
    for k in ("unknown_rejections", "self_registrations", "secret_rejections"):
        if not isinstance(doc.get(k), list):
            raise StateError("%s: %s обязан быть списком" % (STATE_PATH, k))
    return doc


def authority_offset(root, ref="origin/main"):
    """offset АВТОРИТЕТА — из блоба файла состояния на удалённой ветке (после fetch): локальная копия в
    незапушенном коммите подтверждением не является (контракт §1Б(е)). Нет блоба (первый прогон) → None."""
    import subprocess
    r = subprocess.run(["git", "-C", root, "show", "%s:%s" % (ref, STATE_PATH)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        return None
    try:
        doc = yamlmini.loads(r.stdout.decode("utf-8"))
    except (yamlmini.YamlError, UnicodeDecodeError) as e:
        raise StateError("%s@%s не читается: %s" % (STATE_PATH, ref, e))
    off = doc.get("offset") if isinstance(doc, dict) else None
    if not isinstance(off, int) or isinstance(off, bool):
        raise StateError("%s@%s: offset обязан быть целым" % (STATE_PATH, ref))
    return off


def write_state(root, doc):
    return _write(root, STATE_PATH, doc)


def _copy(doc):
    return {k: (list(v) if isinstance(v, list) else v) for k, v in doc.items()}


def set_offset(doc, offset):
    new = _copy(doc)
    new["offset"] = int(offset)
    return new


def _append_capped(doc, key, entry):
    new = _copy(doc)
    new[key] = (new[key] + [dict(entry)])[-LIST_CAP:]
    return new


def record_rejection(doc, telegram_id, at):
    return _append_capped(doc, "unknown_rejections", {"at": int(at), "telegram_id": int(telegram_id)})


def record_self_registration(doc, handle, at):
    return _append_capped(doc, "self_registrations", {"at": int(at), "handle": handle})


def record_secret_rejection(doc, rejection):
    return _append_capped(doc, "secret_rejections", rejection)
