# -*- coding: utf-8 -*-
"""parse — разбор update по ЗАКРЫТОМУ реестру команд `kit/commands.yaml`. Владелец — T2 (план §0А, §1).

Реестр читается на КАЖДОМ прогоне (Parser(registry_path)); списка команд, их токенов и синопсисов в
коде НЕТ — позиции берутся из реестра по полю `token`, хвост — по `tail_rule`, зависимость от
момента — по `time_bearing`. Нормализация — по таблице `normalization` реестра: суффикс `@бот` у
командного токена снимается, регистр токена не учитывается, заголовок — первая строка до LF,
хвост — байты после первого LF (after_first_line) либо после токена (after_token). К байтам хвоста
ничего не применяется (§7: тело коммента — полные байты).

Выход — dict:
  kind: 'input' | 'non_input' | 'unparsed'
  position: id позиции реестра (для input), reason (для unparsed)
  time: None | {'kind': 'duration', 'seconds': int} | {'kind': 'interval', 'from': (h, m), 'to': (h, m)}
  date: 'YYYY-MM-DD' | None   — явная дата (умолчание «сегодня» применяет session.py по timezone человека)
  n: int | None; title: str; tail: bytes; text: bytes (полные байты текста сообщения)
  identity: 'tg:<chat>:<message_id>'; message_date, from_id, chat_id, chat_type, update_id, message_id
  is_callback: bool; confirmed: bool (обёрнуто префиксом подтверждения)
Чистый модуль: ни сети, ни git; файл реестра читается через yamlmini.
"""

import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yamlmini  # noqa: E402

__all__ = ["Parser", "DURATION_FORMS", "INTERVAL_FORMS"]

_HHMM = r"([01]?\d|2[0-4]):([0-5]\d)"
DURATION_FORMS = ("ЧЧ:ММ", "Nч Mм", "Nh Mm", "Nч", "Mм")
INTERVAL_FORMS = ("ЧЧ:ММ-ЧЧ:ММ", "с ЧЧ:ММ до ЧЧ:ММ")
_RE_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s+|$)")
_RE_INTERVAL_DASH = re.compile(r"^%s\s*[-–—]\s*%s(?:\s+|$)" % (_HHMM, _HHMM))
_RE_INTERVAL_WORDS = re.compile(r"^с\s+%s\s+до\s+%s(?:\s+|$)" % (_HHMM, _HHMM), re.IGNORECASE)
_RE_HHMM = re.compile(r"^(\d{1,3}):([0-5]\d)(?:\s+|$)")
_RE_UNITS = re.compile(r"^(?:(\d{1,3})\s*(?:ч|h)\.?)?\s*(?:(\d{1,3})\s*(?:м|мин|m|min)\.?)?(?:\s+|$)", re.IGNORECASE)
_RE_INT = re.compile(r"^\d{1,4}$")
_RE_INT_CAND = re.compile(r"^[+-]?\d{1,9}$")


class Parser(object):
    def __init__(self, registry_path, bot_username=None):
        self.registry = yamlmini.load_file(registry_path)
        if self.registry.get("registry") != "commands":
            raise ValueError("не реестр команд: %s" % registry_path)
        self.positions = self.registry["commands"]
        self.confirm_prefix = self.registry["confirm_prefix"]
        self.bot_username = (bot_username or "").lower().lstrip("@")
        self.by_token = {}
        for p in self.positions:
            self.by_token.setdefault(p["token"].lower(), []).append(p)
        self.by_id = {p["id"]: p for p in self.positions}

    # ------------------------------------------------------------------ вход
    def parse(self, update):
        base = self._envelope(update)
        if base["kind"] != "input":
            return base
        return self._parse_text(base, base["text"], confirmed=False)

    def _envelope(self, update):
        if not isinstance(update, dict):
            return {"kind": "non_input", "reason": "not_a_dict"}
        uid = update.get("update_id")
        if "message" in update and isinstance(update["message"], dict):
            m = update["message"]
            if not isinstance(m.get("text"), str):
                return {"kind": "non_input", "reason": "message_without_text", "update_id": uid}
            chat = m.get("chat") or {}
            if chat.get("type") not in ("private", "group", "supergroup"):
                return {"kind": "non_input", "reason": "chat_type_%s" % chat.get("type"), "update_id": uid}
            frm = m.get("from") or {}
            if not isinstance(frm.get("id"), int):
                return {"kind": "non_input", "reason": "no_sender", "update_id": uid}
            return {"kind": "input", "is_callback": False, "update_id": uid, "message_id": m.get("message_id"),
                    "chat_id": chat.get("id"), "chat_type": chat.get("type"), "from_id": frm["id"],
                    "from_name": (frm.get("first_name") or frm.get("username") or ""), "message_date": m.get("date"),
                    "identity": "tg:%d:%d" % (chat.get("id"), m.get("message_id")), "text": m["text"].encode("utf-8")}
        if "callback_query" in update and isinstance(update["callback_query"], dict):
            cq = update["callback_query"]
            msg = cq.get("message") or {}
            chat = msg.get("chat") or {}
            frm = cq.get("from") or {}
            if not isinstance(cq.get("data"), str) or not isinstance(frm.get("id"), int):
                return {"kind": "non_input", "reason": "callback_without_data", "update_id": uid}
            return {"kind": "input", "is_callback": True, "callback_query_id": cq.get("id"), "update_id": uid,
                    "message_id": msg.get("message_id"), "chat_id": chat.get("id"), "chat_type": chat.get("type"),
                    "from_id": frm["id"], "from_name": (frm.get("first_name") or frm.get("username") or ""),
                    "message_date": None,  # у нажатия НЕТ времени нажатия (П-6) — источником времени не является
                    "identity": "tg:%d:%d:cb:%s" % (chat.get("id", 0), msg.get("message_id", 0), cq.get("id")),
                    "text": cq["data"].encode("utf-8")}
        for k in ("edited_message", "channel_post", "edited_channel_post", "my_chat_member", "chat_member"):
            if k in update:
                return {"kind": "non_input", "reason": k, "update_id": uid}
        return {"kind": "non_input", "reason": "unknown_update_shape", "update_id": uid}

    # ------------------------------------------------------------------ текст
    def tail_of(self, text_bytes):
        """Хвост ПРОИЗВОЛЬНОГО текста по tail_rule его позиции (для носителя открытия при закрытии —
        session.py читает правило реестра отсюда, а не копией). Не вход / не разобрано → b""."""
        out = self._parse_text({"kind": "input", "text": bytes(text_bytes)}, bytes(text_bytes), confirmed=False)
        return out.get("tail", b"") if out.get("kind") == "input" else b""

    def _mention(self, name):
        """Обращение `@name`: своё имя → снять; чужой бот → не наш вход; имя бота неизвестно (None) → любое снимается."""
        if not self.bot_username:
            return "strip"
        return "strip" if name.lower() == self.bot_username else "other"

    def _parse_text(self, base, text, confirmed):
        first_nl = text.find(b"\n")
        first_line_b = text if first_nl < 0 else text[:first_nl]
        rest_after_lf = b"" if first_nl < 0 else text[first_nl + 1:]
        try:
            first_line = first_line_b.decode("utf-8")
        except UnicodeDecodeError:
            return self._unparsed(base, "not_utf8")
        if first_line.endswith("\r"):          # CRLF: CR не часть заголовка/аргумента; байты хвоста и тела не трогаются
            first_line = first_line[:-1]
        consumed = len(first_line) - len(first_line.lstrip(" \t"))
        stripped = first_line[consumed:]
        m = re.match(r"^@([A-Za-z0-9_]+)(?:[ \t]+|$)", stripped)
        if m:                                    # обращение к боту в группе (реестр strip_bot_mention)
            if self._mention(m.group(1)) == "other":
                return {"kind": "non_input", "reason": "addressed_to_other_bot", "update_id": base.get("update_id")}
            consumed += m.end()
            stripped = stripped[m.end():]
        token, sep, argstr = stripped.partition(" ")
        consumed += len(token) + len(sep) + (len(argstr) - len(argstr.lstrip(" \t")))
        argstr = argstr.lstrip(" \t")
        cmd = token
        if cmd.startswith("/"):
            ms = re.search(r"@([A-Za-z0-9_]+)$", cmd)
            if ms:
                if self._mention(ms.group(1)) == "other":
                    return {"kind": "non_input", "reason": "addressed_to_other_bot", "update_id": base.get("update_id")}
                cmd = cmd[:ms.start()]
            cmd = cmd.lower()
            positions = self.by_token.get(cmd)
            if not positions:
                return self._unparsed(base, "unknown_command:%s" % cmd)
            # подтверждение: обёрнутый вход разбирается тем же циклом
            if cmd == self.confirm_prefix.lower():
                inner_first = argstr.encode("utf-8")
                inner = inner_first + ((b"\n" + rest_after_lf) if first_nl >= 0 else b"")
                if not inner_first:
                    return self._unparsed(base, "confirm_without_message")
                out = self._parse_text(base, inner, confirmed=True)
                if out["kind"] == "input":
                    out["wrapped_by"] = "confirm"
                    out["confirm_inner_text"] = inner   # байты ОТКЛОНЁННОГО ранее сообщения — для сверки подтверждения (T4)
                return out
            pos = self._choose_slash_position(positions, argstr)
            return self._apply_position(base, pos, argstr, text, len(first_line[:consumed].encode("utf-8")), rest_after_lf, confirmed)
        # свободная строка — позиция с пустым token
        positions = self.by_token.get("")
        if not positions:
            return self._unparsed(base, "no_free_text_position")
        return self._apply_position(base, positions[0], stripped, text, len(first_line[:consumed].encode("utf-8")), rest_after_lf, confirmed)

    @staticmethod
    def grammar_kind(pos):
        """Вид грамматики аргумента — из поля `grammar` реестра (`…#grammar-<kind>`), не из id позиции:
        новая позиция с существующей грамматикой разбирается без правки кода (контракт §1А)."""
        ref = str(pos.get("grammar", ""))
        if "#grammar-" not in ref:
            raise ValueError("позиция %r: поле grammar обязано ссылаться на #grammar-<kind>" % pos.get("id"))
        return ref.split("#grammar-", 1)[1].strip()

    def _choose_slash_position(self, positions, argstr):
        """Один токен может нести несколько позиций (грамматики start-title / start-n): различаются формой аргумента."""
        if len(positions) == 1:
            return positions[0]
        numeric = _RE_INT_CAND.match(argstr.strip()) is not None
        for p in positions:
            if (self.grammar_kind(p) == "start-n") == numeric:
                return p
        return positions[0]

    @staticmethod
    def _calendar_date(s):
        """Явная дата обязана быть календарной (месяц 01–12, день по месяцу и високосности); иначе None."""
        try:
            return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10])).isoformat()
        except ValueError:
            return None

    def _apply_position(self, base, pos, argstr, text, after_token_offset, rest_after_lf, confirmed):
        out = dict(base)
        out.update({"kind": "input", "position": pos["id"], "time_bearing": bool(pos["time_bearing"]),
                    "callback_allowed": bool(pos["callback_allowed"]), "confirmed": confirmed,
                    "time": None, "date": None, "n": None, "title": "", "tail": b""})
        rule = pos["tail_rule"]
        if rule == "after_first_line":
            out["tail"] = rest_after_lf
        elif rule == "after_token":
            # от той же НОРМАЛИЗОВАННОЙ командной строки, что и токен: после снятых пробелов, обращения
            # `@бот` и самого токена (с суффиксом) — байты дальше; CR/LF первой строки хвостом не считаются
            body = text[after_token_offset:]
            if body.startswith(b"\r\n"):
                body = body[2:]
            elif body.startswith(b"\n"):
                body = body[1:]
            out["tail"] = body
        elif rule in ("none", "as_wrapped"):
            out["tail"] = b""
        kind = self.grammar_kind(pos)
        s = argstr
        if kind == "start-n":
            if not _RE_INT.match(s.strip()) or int(s.strip()) < 1:
                return self._unparsed(base, "n_not_positive_integer")
            out["n"] = int(s.strip())
            return out
        if kind == "free-text":
            m = _RE_DATE.match(s)
            if m:
                out["date"] = self._calendar_date(m.group(1))
                if out["date"] is None:
                    return self._unparsed(base, "date_not_calendar")
                s = s[m.end():]
            t, s2 = self._parse_time(s)
            if t is None:
                return self._unparsed(base, "free_text_without_time")
            out["time"] = t
            out["title"] = s2.strip(" \t")
            return out
        if kind == "track":
            m = _RE_DATE.match(s)
            if m:
                out["date"] = self._calendar_date(m.group(1))
                if out["date"] is None:
                    return self._unparsed(base, "date_not_calendar")
                s = s[m.end():]
            t, s2 = self._parse_interval(s)
            if t is None:
                return self._unparsed(base, "track_without_interval")
            out["time"] = t
            out["title"] = s2.strip(" \t")
            return out
        if kind == "last":
            if s.strip():
                if not _RE_INT.match(s.strip()) or int(s.strip()) < 1:
                    return self._unparsed(base, "n_not_positive_integer")
                out["n"] = int(s.strip())
            return out
        if kind in ("stop", "help"):
            return out
        if kind == "start-title":
            if not s.strip():
                return self._unparsed(base, "title_empty")
            out["title"] = s.strip(" \t")
            return out
        raise ValueError("позиция %r: неизвестная грамматика %r (закрытый перечень главы 01)" % (pos.get("id"), kind))

    def _parse_interval(self, s):
        for rx in (_RE_INTERVAL_DASH, _RE_INTERVAL_WORDS):
            m = rx.match(s)
            if m:
                h1, m1, h2, m2 = (int(m.group(i)) for i in range(1, 5))
                if h1 > 24 or h2 > 24 or (h1 == 24 and m1 > 0) or (h2 == 24 and m2 > 0):
                    return None, s
                return {"kind": "interval", "from": (h1, m1), "to": (h2, m2)}, s[m.end():]
        return None, s

    def _parse_time(self, s):
        t, rest = self._parse_interval(s)
        if t is not None:
            return t, rest
        m = _RE_HHMM.match(s)
        if m:
            return {"kind": "duration", "seconds": int(m.group(1)) * 3600 + int(m.group(2)) * 60}, s[m.end():]
        m = _RE_UNITS.match(s)
        if m and (m.group(1) or m.group(2)) and m.end() > 0:
            h = int(m.group(1) or 0)
            mi = int(m.group(2) or 0)
            return {"kind": "duration", "seconds": h * 3600 + mi * 60}, s[m.end():]
        return None, s

    @staticmethod
    def _unparsed(base, reason):
        out = dict(base)
        out.update({"kind": "unparsed", "reason": reason})
        return out
