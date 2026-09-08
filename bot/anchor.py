# -*- coding: utf-8 -*-
"""anchor — якорь дневной строки из идентичности сообщения. Владелец — T2 (контракт §1Г(г), §12).

Правило (tg-bot.yaml comment.identity.anchor_rule): первые 8 hex sha256(
    "workshop-d09-anchor-v1" NUL identity NUL k NUL step ),
где identity = "tg:<chat.id>:<message_id>" сообщения, ПОРОЖДАЮЩЕГО строку (для таймера — закрытие),
k — номер строки (0; 1 — вторая строка полуночной сессии), step — шаг соли при столкновении якоря
в целевом файле с ИНЫМ содержимым (0 по умолчанию). Тот же вход → тот же якорь (правило Т,
D04 §3.4); столкновение — переминт детерминированно шагом соли.

Чистая функция: ни сети, ни git, ни файловой системы. python3 ≥ 3.9, stdlib.
"""

import hashlib
import re

ANCHOR_DOMAIN = "workshop-d09-anchor-v1"
ANCHOR_TOKEN_RE = re.compile(r"<!--t:([0-9a-f]{8})-->")
IDENTITY_RE = re.compile(r"^tg:-?[0-9]+:[0-9]+$")

__all__ = ["ANCHOR_DOMAIN", "identity", "derive", "anchor_token", "existing_anchors", "remint"]


def identity(chat_id, message_id):
    """Идентичность сообщения — байты ASCII 'tg:<chat.id>:<message_id>'."""
    ident = "tg:%d:%d" % (int(chat_id), int(message_id))
    if not IDENTITY_RE.match(ident):
        raise ValueError("identity не по форме: %r" % ident)
    return ident


def derive(ident, k=0, step=0):
    """8 hex якоря. k — номер строки (сегмент полуночного разреза), step — шаг соли."""
    if not IDENTITY_RE.match(ident):
        raise ValueError("identity не по форме: %r" % ident)
    if k < 0 or step < 0:
        raise ValueError("k и step неотрицательны")
    material = b"\x00".join([ANCHOR_DOMAIN.encode("ascii"), ident.encode("ascii"),
                             str(int(k)).encode("ascii"), str(int(step)).encode("ascii")])
    return hashlib.sha256(material).hexdigest()[:8]


def anchor_token(anchor8):
    return "<!--t:%s-->" % anchor8


def existing_anchors(body_bytes):
    """Множество {якорь: строка} из тела контейнера (байты) — для правила Т и столкновений."""
    out = {}
    for raw in body_bytes.split(b"\n"):
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        m = ANCHOR_TOKEN_RE.search(line)
        if m:
            out[m.group(1)] = line
    return out


def remint(ident, k, existing, candidate_line_without_anchor, max_steps=64):
    """Вернуть (якорь, step, identical): identical=True — в файле уже есть ПОБАЙТОВО та же строка
    (тождество, писать не надо, исход identical_repeat); иначе первый step, чей якорь не занят
    ИНЫМ содержимым. `existing` — {якорь: строка_в_файле}.
    ДОГОВОР О КАНДИДАТЕ: candidate_line_without_anchor = line.build_line(..., "00000000") без
    последних len(" <!--t:00000000-->") байт — то есть при ПУСТОМ заголовке кандидат оканчивается
    одним пробелом ("<дата> <часы> "), и full = кандидат + " " + токен побайтово равен build_line."""
    for step in range(max_steps):
        a = derive(ident, k, step)
        full = candidate_line_without_anchor + " " + anchor_token(a) if candidate_line_without_anchor else anchor_token(a)
        if a not in existing:
            return a, step, False
        if existing[a] == full:
            return a, step, True
    raise RuntimeError("не удалось выбрать якорь за %d шагов соли" % max_steps)
