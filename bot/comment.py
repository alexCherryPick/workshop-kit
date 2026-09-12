# -*- coding: utf-8 -*-
"""comment — сборка бот-коммента: заголовочная строка + тело (полные байты) + детерминированный id.
Владелец — T2 (контракт §1Г, §0Д плана). Чистая функция: ни сети, ни git, ни файловой системы;
запись файла-спутника — T3 (commit.py).

Форма (ядро 04.3.1): `### <ISO-8601Z> · <автор> <!--c:<id> about:t:<якорь>-->` + тело + LF.
Разделитель — MIDDLE DOT U+00B7 в одиночных пробелах. Автор — handle ЧЕЛОВЕКА (04.3.2).
Id — UUIDv7 (tg-bot.yaml comment.identity.comment_id_rule):
    h = sha256("workshop-d09-comment-v1" NUL identity NUL k)
    48 бит времени = message.date·1000 сообщения-носителя; версия 7; 12 бит из h; вариант 10; 62 бита из h.
Домен соли отличен от домена якоря; повтор того же сообщения → побайтово тот же блок (union
дедуплицирует его в один экземпляр, ядро 04.7.3).
Тело — ПОЛНЫЕ байты текста сообщения-носителя: без .strip(), splitlines() и текстовых пайплайнов.
«Коммента нет» — отдельный выход (None), не пустое тело: пустой коммент писать запрещено (04.3.4).
"""

import datetime
import hashlib
import re
import uuid

COMMENT_DOMAIN = "workshop-d09-comment-v1"
MIDDLE_DOT = "·"
AUTHOR_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HEADER_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) · ([A-Za-z0-9._-]{1,64}) <!--c:([0-9a-f-]{36}) about:t:([0-9a-f]{8})-->$")

__all__ = ["COMMENT_DOMAIN", "comment_id", "timestamp_z", "header_line", "build", "comments_of_header"]


def uuid7_random(now_ms=None, entropy=None):
    """СЛУЧАЙНЫЙ UUIDv7 той же раскладкой бит, что и comment_id: 48 бит времени (unix-мс), версия 7,
    вариант 10, остальное — случайно. Нужен минту id контейнера при ленивом создании (id контейнера
    НЕ детерминирован — пересоздание незапушенного файла даёт новый id, глава §4), но форма обязана
    быть v7: иначе валидатор помечает собственную запись бота W-ID-VERSION (живой прогон 2026-09-12)."""
    import os as _os
    import time as _time
    ts_ms = int(_time.time() * 1000) if now_ms is None else int(now_ms)
    if ts_ms < 0 or ts_ms >= (1 << 48):
        raise ValueError("время вне диапазона UUIDv7")
    e = _os.urandom(10) if entropy is None else bytes(entropy)
    rand_a = int.from_bytes(e[0:2], "big") & ((1 << 12) - 1)
    rand_b = int.from_bytes(e[2:10], "big") & ((1 << 62) - 1)
    return str(uuid.UUID(int=(ts_ms << 80) | (7 << 76) | (rand_a << 64) | (2 << 62) | rand_b))


def comment_id(ident, message_date, k=0):
    """UUIDv7 детерминированно из идентичности сообщения-носителя и k."""
    if not re.match(r"^tg:-?[0-9]+:[0-9]+$", ident):
        raise ValueError("identity не по форме: %r" % ident)
    h = hashlib.sha256(b"\x00".join([COMMENT_DOMAIN.encode("ascii"), ident.encode("ascii"), str(int(k)).encode("ascii")])).digest()
    ts_ms = int(message_date) * 1000
    if ts_ms < 0 or ts_ms >= (1 << 48):
        raise ValueError("message.date вне диапазона UUIDv7")
    rand_a = int.from_bytes(h[0:2], "big") & 0x0FFF
    rand_b = int.from_bytes(h[2:10], "big") & ((1 << 62) - 1)
    value = (ts_ms << 80) | (7 << 76) | (rand_a << 64) | (2 << 62) | rand_b
    return str(uuid.UUID(int=value))


def timestamp_z(message_date):
    """Форма 02.2.1: YYYY-MM-DDThh:mm:ssZ из целых секунд эпохи."""
    return datetime.datetime.fromtimestamp(int(message_date), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def header_line(message_date, author_handle, cid, anchor8):
    if not AUTHOR_TOKEN_RE.match(author_handle):
        raise ValueError("автор не по грамматике 04.3.1: %r" % author_handle)
    return "### %s %s %s <!--c:%s about:t:%s-->" % (timestamp_z(message_date), MIDDLE_DOT, author_handle, cid, anchor8)


def build(ident, message_date, body_bytes, author_handle, anchor8, k=0):
    """Вернуть (id, заголовочная строка, блок-байты) либо None, если тела нет (коммента нет).
    Блок = заголовок + LF + тело + LF (ровно один финальный LF; если тело уже кончается LF —
    второй не добавляется, но тело не режется)."""
    if body_bytes is None or len(body_bytes) == 0:
        return None
    if not isinstance(body_bytes, (bytes, bytearray)):
        raise TypeError("тело коммента — байты, не строка")
    cid = comment_id(ident, message_date, k)
    head = header_line(message_date, author_handle, cid, anchor8)
    block = head.encode("utf-8") + b"\n" + bytes(body_bytes)
    if not block.endswith(b"\n"):
        block += b"\n"
    return cid, head, block


def comments_of_header(container_id):
    """Первая строка файла-спутника — детерминированная и неизменяемая (ядро 04.2.1)."""
    return "<!-- comments-of: %s -->" % container_id
