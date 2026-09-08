# -*- coding: utf-8 -*-
"""secrets — рубеж производителя: скан текста сообщения по реестру паттернов ДО записи (ядро 05.3.2
п. 4; контракт §1 исход 8; REQ-019). Владелец — T4. Реестр `kit/secret-patterns.yaml` читается на
каждом прогоне (load_patterns); констант-паттернов в коде нет; T4 реестр не правит.

Контракт отчёта о находке — из реестра (`report_fields`, `never_report`): наружу уходят ТОЛЬКО имя
паттерна и его описание; совпавшее значение и текст сообщения не печатаются никуда.
Подтверждение (П-2, префикс подтверждения из реестра): обход скана допустим ТОЛЬКО для текста, который бот ранее ОТКЛОНИЛ
как секрет — сверка по sha256 текста и telegram_id отправителя (память отклонений — файл состояния
прогона, пишет T3); префикс без предшествующей находки скан не обходит.
"""

import hashlib
import re

__all__ = ["load_patterns", "scan", "text_digest", "confirmation_allowed", "rejection_record"]


def load_patterns(doc):
    if not isinstance(doc, dict) or doc.get("registry") != "secret_patterns":
        raise ValueError("не реестр паттернов секретов")
    compiled = []
    for p in doc["patterns"]:
        compiled.append({"name": p["name"], "describe": p.get("describe", ""), "confidence": p.get("confidence", "high"),
                         "re": re.compile(p["pattern"].encode("utf-8"))})
    report_fields = tuple(doc.get("report_fields") or ["name", "describe"])
    never = set(doc.get("never_report") or [])
    if "matched_value" not in never or "message_text" not in never:
        raise ValueError("реестр обязан объявлять never_report: matched_value и message_text")
    return {"patterns": compiled, "report_fields": report_fields}


def scan(registry, text_bytes):
    """Список находок [{name, describe}] — без значений. Порядок — порядок реестра; один паттерн — одна находка."""
    if not isinstance(text_bytes, (bytes, bytearray)):
        raise TypeError("скан работает с байтами")
    out = []
    for p in registry["patterns"]:
        if p["re"].search(bytes(text_bytes)):
            out.append({k: p[k] for k in registry["report_fields"] if k in p})
    return out


def text_digest(text_bytes):
    return hashlib.sha256(bytes(text_bytes)).hexdigest()


def rejection_record(text_bytes, from_id, at):
    """Запись об отклонении для файла состояния прогона (T3): без текста и без значения."""
    return {"at": int(at), "telegram_id": int(from_id), "text_sha256": text_digest(text_bytes)}


def confirmation_allowed(rejections, inner_text_bytes, from_id):
    """True, если ЭТОТ отправитель ранее получил отклонение ровно за ЭТИ байты."""
    d = text_digest(inner_text_bytes)
    return any(r.get("telegram_id") == int(from_id) and r.get("text_sha256") == d for r in (rejections or []))
