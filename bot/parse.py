# -*- coding: utf-8 -*-
"""parse — разбор update по ЗАКРЫТОМУ реестру команд `kit/commands.yaml`. Владелец — T2 (план §0А, §1);
T8 — реестр форм длительности `kit/duration-forms.yaml`, маркеры исправления, грамматика отзыва.

Реестр команд читается на КАЖДОМ прогоне (Parser(registry_path)); списка команд, их токенов и синопсисов
в коде НЕТ — позиции берутся из реестра по полю `token`, хвост — по `tail_rule`, зависимость от
момента — по `time_bearing`. Нормализация — по таблице `normalization` реестра: суффикс `@бот` у
командного токена снимается, регистр токена не учитывается, заголовок — первая строка до LF,
хвост — байты после первого LF (after_first_line) либо после токена (after_token). К байтам хвоста
ничего не применяется (§7: тело коммента — полные байты).

Реестр форм длительности (T8, REQ-094): единицы (с падежами, ru/en), образ числа (десятичные часы),
форма ЧЧ:ММ, разделитель составной длительности и ПОЗИЦИИ читаются из `kit/duration-forms.yaml`;
списка форм в коде нет. Приоритет позиций: ведущая найдена → конец строки не сканируется; конечная —
только при отсутствии ведущей; середина не сканируется; две несоседние длительности без ведущей —
`duration_ambiguous`. Маркеры исправления (исход 6, И5) — оттуда же: `kind: 'correction'`.

Выход — dict:
  kind: 'input' | 'non_input' | 'unparsed' | 'correction'
  position: id позиции реестра (для input), reason (для unparsed/correction)
  time: None | {'kind': 'duration', 'seconds': int} | {'kind': 'interval', 'from': (h, m), 'to': (h, m)}
  date: 'YYYY-MM-DD' | None   — явная дата (умолчание «сегодня» применяет session.py по timezone человека)
  n: int | None; title: str; tail: bytes; text: bytes (полные байты текста сообщения)
  identity: 'tg:<chat>:<message_id>'; message_date, from_id, chat_id, chat_type, update_id, message_id
  is_callback: bool; confirmed: bool (обёрнуто префиксом подтверждения)
Чистый модуль: ни сети, ни git; файлы реестров читаются через yamlmini.
"""

import datetime
import decimal
import os
import re
import unicodedata as _ud
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yamlmini  # noqa: E402

__all__ = ["Parser", "INTERVAL_FORMS", "FORMS_PATH"]

_HERE = os.path.dirname(os.path.abspath(__file__))
FORMS_PATH = os.path.join(_HERE, "kit", "duration-forms.yaml")

_HHMM = r"([01]?\d|2[0-4]):([0-5]\d)"
INTERVAL_FORMS = ("ЧЧ:ММ-ЧЧ:ММ", "с ЧЧ:ММ до ЧЧ:ММ")
_RE_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s+|$)")
_RE_INTERVAL_DASH = re.compile(r"^%s\s*[-–—]\s*%s(?:\s+|$)" % (_HHMM, _HHMM))
_RE_INTERVAL_WORDS = re.compile(r"^с\s+%s\s+до\s+%s(?:\s+|$)" % (_HHMM, _HHMM), re.IGNORECASE)
_RE_INT = re.compile(r"^\d{1,4}$")
_RE_INT_CAND = re.compile(r"^[+-]?\d{1,9}$")
_NOT_LETTER = r"(?![^\W\d_])"   # после единицы — не буква («1мес» ≠ «1м» + «ес»)
_N_PREFIX = re.compile(r"^(?:№|#|[Nn](?:o\.|[ºo°])?)", re.UNICODE)


# Unicode Default_Ignorable_Code_Point (DerivedCoreProperties): невидимые символы, которые рендер обязан игнорировать —
# форматирующие (Cf), селекторы вариантов (Mn), CGJ (Mn), хангыль-филлеры (Lo), теги; класс «невидимый символ», а не
# категория Cf (раунд 9 T8, Fable-2 W1)
_DEFAULT_IGNORABLE = ((0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
                      (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
                      (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))


def _ignorable(ch):
    """Ровно класс Default_Ignorable_Code_Point (раунд 10 B W3): видимые Cf вне класса — арабские знаки чисел и т.п. — не снимаются."""
    o = ord(ch)
    return any(a <= o <= b for a, b in _DEFAULT_IGNORABLE)


def _lexemes(s):
    """Лексемы аргумента для грамматики: [(сырой_токен, токен_без_невидимых)] по любому Unicode-пробелу; токен, состоящий
    из одних невидимых символов, лексемой НЕ является (раунд 10 B W1: «через <U+200B> 2ч», «<команда отзыва> <U+200B> 3»
    — фантомная пустая лексема сдвигала грамматику). Сырой токен нужен для дословных остатков (причина отзыва)."""
    out = []
    for tok in re.split(r"\s+", s.strip()):
        if not tok:
            continue
        bare = _strip_cf(tok)
        if bare:
            out.append((tok, bare))
    return out


def _strip_cf(s):
    """Невидимые символы (Default_Ignorable_Code_Point: пробел нулевой ширины, мягкий перенос, соединители, селекторы
    вариантов, CGJ, хангыль-филлеры, метка порядка байтов, направляющие, теги) не участвуют в СРАВНЕНИИ лексем грамматики —
    предлога перед конечной длительностью и номера отзыва (раунд 8 Fable W3, раунд 9 Fable W1/W2: снимать их со всей
    строки нельзя — ломаются байтовые контракты хвоста/подтверждения и дословность заголовка); заголовок, причина,
    хвост и тело хранятся дословно."""
    return "".join(ch for ch in s if not _ignorable(ch))


def _number_like(tok):
    """Классификация лексемы аргумента отзыва по Unicode-категориям (раунды 3–5): → (похожа_на_номер, core|None).
    ДЕКОРАЦИИ — композиционная грамматика: обёртки (любые скобки/кавычки Ps/Pe/Pi/Pf, «"», «'») и префиксы номера
    («№», «#», «Nº», «N°», «No», «No.», «N») снимаются В ЛЮБОМ ПОРЯДКЕ, ЛЮБОМ ЧИСЛЕ и сочетании до неподвижной точки
    («#(2-й)», «№（２й）», «N(2)», «##(2-й)», «NNo.(2-й)» [раунд 5 B1]) — снятие префикса не требует, чтобы сразу за ним
    стоял числовой символ. ЧИСЛОПОДОБНОСТЬ — символ с Unicode-числовым значением (Nd/Nl/No: «½», «③», «³»,
    полноширинные и арабо-индийские цифры). Похожа ⟺ в остатке есть числоподобный символ (или остаток начинается со
    знака «+»/«-») И (остаток начинается с числоподобного/знака, ЛИБО снят хоть один префикс, ЛИБО в остатке нет
    букв). Остаток без единого числоподобного символа («nota», «v», «№» без номера) — причина, не номер. core —
    цифры Nd после снятия хвостовой пунктуации и суффикса «-й»/«й»/«го»/«я»; иначе (½, ③, ³, «3x») — None → переспрос."""
    def is_num(ch):
        return _ud.numeric(ch, None) is not None
    def is_letter(ch):
        return _ud.category(ch).startswith("L")
    def is_wrap(ch):
        return _ud.category(ch) in ("Ps", "Pe", "Pi", "Pf") or ch in "\"'"
    bare, had_prefix = _strip_cf(tok), False
    while True:
        prev = bare
        while bare and is_wrap(bare[0]):
            bare = bare[1:]
        while bare and is_wrap(bare[-1]):
            bare = bare[:-1]
        pm = _N_PREFIX.match(bare)
        if pm and pm.end() < len(bare):
            bare = bare[pm.end():]; had_prefix = True
        if bare == prev:
            break
    if not bare or not (any(is_num(c) for c in bare) or bare[0] in "+-"):
        return False, None
    looks = is_num(bare[0]) or bare[0] in "+-" or had_prefix or not any(is_letter(c) for c in bare)
    if not looks:
        return False, None
    core = bare
    while core and (_ud.category(core[-1]).startswith("P") or core[-1].isspace()):
        core = core[:-1]
    core = re.sub(r"-?(й|го|я)$", "", core)
    while core and (_ud.category(core[-1]).startswith("P") or core[-1].isspace()):
        core = core[:-1]
    if core and all(_ud.category(c) == "Nd" for c in core):
        return True, core
    return True, None


class DurationForms(object):
    """Регэкспы длительности, СОБРАННЫЕ из реестра форм на каждом прогоне (единицы, число, ЧЧ:ММ,
    порядок сцепки, разделитель, позиции, исключённые предлоги, маркеры). Списка форм здесь нет — только
    сборка из полей реестра."""

    def __init__(self, forms_path=None):
        self.doc = yamlmini.load_file(forms_path or FORMS_PATH)
        if self.doc.get("registry") != "duration_forms":
            raise ValueError("не реестр форм длительности: %s" % (forms_path or FORMS_PATH))
        num = self.doc["number_pattern"]
        sep = self.doc["compound_separator"]
        self.unit_seconds = {}
        alt_by_unit = {}
        for name, u in self.doc["units"].items():
            toks = sorted((str(t) for t in u["tokens"]), key=len, reverse=True)
            for t in toks:
                self.unit_seconds[t.lower()] = (name, int(u["seconds"]))
            alt_by_unit[name] = "(?:%s)" % "|".join(re.escape(t) for t in toks)
        order = list(self.doc.get("compound_order") or list(self.doc["units"].keys()))
        # сцепка ТОЛЬКО в объявленном порядке единиц, каждая ≤ 1 раза (раунд 1, №11): часы[ минуты] | минуты
        parts = []
        for i, name in enumerate(order):
            piece = r"(?:%s)\s*%s\.?%s" % (num, alt_by_unit[name], _NOT_LETTER)
            tail = "".join(r"(?:%s(?:%s)\s*%s\.?%s)?" % (sep, num, alt_by_unit[n2], _NOT_LETTER) for n2 in order[i + 1:])
            parts.append(piece + tail)
        seq = "(?:%s)" % "|".join(parts)
        unit_any = "(?:%s)" % "|".join(alt_by_unit.values())
        self.re_one = re.compile(r"(%s)\s*(%s)\.?%s" % (num, unit_any, _NOT_LETTER), re.IGNORECASE)
        hhmm = self.doc["hhmm_pattern"]
        hh_pos = list(self.doc.get("hhmm_positions") or ["leading"])
        lead_alt = "(?P<seq>%s)" % seq
        if "leading" in hh_pos:
            lead_alt = "(?P<hhmm>%s)|" % hhmm + lead_alt
        self.re_leading = re.compile(r"^(?:%s)(?=\s|$)" % lead_alt, re.IGNORECASE)
        trail_alt = "(?P<seq>%s)" % seq
        if "trailing" in hh_pos:
            trail_alt = "(?P<hhmm>%s)|" % hhmm + trail_alt
        self.re_trailing = re.compile(r"(?:^|\s)(?:%s)\s*$" % trail_alt, re.IGNORECASE)
        # «где угодно» — для поиска ВТОРОЙ длительности перед конечной; ЧЧ:ММ входит сюда только если реестр
        # разрешает его вне ведущей позиции (раунд 2, W6: «созвон в 15:00 1ч» — время суток, не длительность)
        any_alt = seq if set(hh_pos) <= {"leading"} else "%s|%s" % (hhmm, seq)
        self.re_anywhere = re.compile(r"(?<![^\W_])(?:%s)(?![^\W_])" % any_alt, re.IGNORECASE)   # границы широкие (раунд 4, W3)
        # «серии» длительностей для СЧЁТА и проверки неоднозначности — границы ШИРОКИЕ: не буква/цифра с обеих сторон
        # (раунд 4, W3: «15:00 созвон (1ч)» — единица в скобках тоже длительность для неоднозначности); для ПРИНЯТИЯ
        # формы (re_leading/re_trailing) границы узкие — пробел/край строки (гл. 01 §1)
        self.re_runs = re.compile(r"(?<![^\W_])(?:%s)(?![^\W_])" % seq, re.IGNORECASE)
        self.re_hhmm = re.compile(r"^(\d{1,3}):([0-5]\d)$")
        self.positions = list(self.doc.get("positions") or ["leading"])
        self.excluded_before = set(str(t).lower() for t in (self.doc.get("trailing_excluded_preceding_tokens") or []))
        # операнд сравнения количеств {Q} (раунд 4, W2): число [единица], после которого НЕ буква — «3D», «v2», «2D» операндами
        # не являются; подставляется в регэкспы структурных маркеров реестра
        # границы операнда (раунд 5, W2): число — целая лексема: перед ним не цифра/буква/разделитель дроби, после —
        # не буква, не цифра и не продолжение дроби («20D», «2.0D» — обозначения, не количества; отката внутри числа нет)
        q = r"(?<![^\W_]|[.,])(?:%s)(?:\s*%s\.?)?(?![^\W_]|[.,]\d)" % (num, unit_any)
        self.correction = [re.compile(p.replace("{Q}", q), re.IGNORECASE) for p in (self.doc.get("correction_markers") or [])]
        self.correction_weak = [re.compile(p, re.IGNORECASE) for p in (self.doc.get("correction_markers_weak") or [])]
        preps = [str(t) for t in (self.doc.get("correction_target_prepositions") or [])]
        self.re_target_prep = re.compile(r"(?:^|\s)(?:%s)\s+(?:%s)" % ("|".join(re.escape(t) for t in preps), seq), re.IGNORECASE) if preps else None

    def seconds_of(self, span):
        """Секунды из текста длительности (ЧЧ:ММ или сцепка единиц); None — десятичные минуты."""
        m = self.re_hhmm.match(span)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60
        total = decimal.Decimal(0)
        seen = False
        for mm in self.re_one.finditer(span):
            num, unit = mm.group(1), mm.group(2)
            name, secs = self.unit_seconds[unit.lower()]
            n = decimal.Decimal(num.replace(",", "."))
            if name != "hours" and n != n.to_integral_value():
                return None
            total += n * secs
            seen = True
        if not seen:
            return None
        return int(total.to_integral_value(rounding=decimal.ROUND_HALF_UP))

    def find(self, s):
        """(seconds|None, title, reason|None) по приоритету позиций: ведущая → конечная; середина не
        сканируется; две несоседние длительности без ведущей — duration_ambiguous; конечная после
        предлога/маркера момента (реестр) — не длительность."""
        if "leading" in self.positions:
            m = self.re_leading.match(s)
            if m:
                secs = self.seconds_of(m.group(0))
                rest = s[m.end():]
                # ещё одна длительность ВПЛОТНУЮ к ведущей (повтор единицы, слом порядка) — неоднозначность,
                # а не заголовок «2ч созвон» (гл. 01 §1: «повтор единицы → duration_ambiguous»)
                if secs is None or self.re_one.match(rest.lstrip(" ,")):
                    return None, s, "duration_ambiguous"
                # ведущая ЧЧ:ММ и единичная длительность дальше в строке («15:00 созвон 1ч») — ЧЧ:ММ здесь скорее
                # время суток: неоднозначность, а не 15 часов в табель (раунд 3)
                if m.groupdict().get("hhmm") and self.re_runs.search(rest):
                    return None, s, "duration_ambiguous"
                return secs, rest, None
        if "trailing" in self.positions:
            m = self.re_trailing.search(s)
            if m:
                head = s[:m.start()]
                # предшествующий токен — по тем же границам, что и длительность: любой Unicode-пробел (\s), не только
                # U+0020 (раунд 7, B1: NBSP/TAB перед предлогом обходили запрет «через 2ч»)
                lx = _lexemes(head)
                prev = lx[-1][1].lower() if lx else ""   # последняя НЕПУСТАЯ лексема (фантомные — не лексемы, раунд 10 B W1)
                if prev in self.excluded_before:
                    return None, s, "free_text_without_time"
                if self.re_anywhere.search(head):
                    return None, s, "duration_ambiguous"
                secs = self.seconds_of(m.group(0).strip())
                if secs is None:
                    return None, s, "duration_ambiguous"
                return secs, head, None
        return None, s, "free_text_without_time"

    def is_correction(self, first_line):
        """Форма исправления (раунд 1 №1, раунд 2 W1): нет ведущей длительности ∧ ≥1 длительность ∧
        (структурный маркер сравнения ∨ (слабый маркер ∧ (длительностей ≥ 2 ∨ длительность после предлога цели)))."""
        if self.re_leading.match(first_line.lstrip(" \t")):
            return False
        if not self.re_one.search(first_line):
            return False
        if any(rx.search(first_line) for rx in self.correction):
            return True
        if not any(rx.search(first_line) for rx in self.correction_weak):
            return False
        if len(self.re_runs.findall(first_line)) >= 2:
            return True
        return bool(self.re_target_prep and self.re_target_prep.search(first_line))


class Parser(object):
    def __init__(self, registry_path, bot_username=None, forms_path=None):
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
        self.forms = DurationForms(forms_path)

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
            base = dict(base, addressed=True)
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
        lx = _lexemes(argstr)
        visible = lx[0][1] if len(lx) == 1 else argstr.strip()   # видимая форма единственной лексемы (раунд 10 B W4)
        numeric = _RE_INT_CAND.match(visible) is not None
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
            lx = _lexemes(s)
            n_tok = lx[0][1] if len(lx) == 1 else s.strip()   # одна лексема — её видимая форма (раунд 10 B W4)
            if not _RE_INT.match(n_tok) or int(n_tok) < 1:
                return self._unparsed(base, "n_not_positive_integer")
            out["n"] = int(n_tok)
            return out
        if kind == "free-text":
            m = _RE_DATE.match(s)
            if m:
                out["date"] = self._calendar_date(m.group(1))
                if out["date"] is None:
                    return self._unparsed(base, "date_not_calendar")
                s = s[m.end():]
            t, s2 = self._parse_interval(s)
            if t is None:
                # И5 (раунд 1, №1): форма исправления = маркер + длительность в строке + НЕТ ведущей длительности;
                # проверяется ДО конечной позиции («не 3.25, а 1.25 часа» — не запись 1.25 ч) и ПОСЛЕ ведущей
                # («1ч исправление багов» — запись, чем бы заголовок ни был)
                if self.forms.is_correction(s):
                    return self._correction(base, "correction_like")
                secs, s2, reason = self.forms.find(s.rstrip(" \t"))
                if secs is None:
                    return self._unparsed(base, reason)
                t = {"kind": "duration", "seconds": secs}
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
            lx = _lexemes(s)
            if lx or s.strip():
                n_tok = lx[0][1] if len(lx) == 1 else s.strip()
                if not _RE_INT.match(n_tok) or int(n_tok) < 1:
                    return self._unparsed(base, "n_not_positive_integer")
                out["n"] = int(n_tok)
            return out
        if kind == "undo":
            # [N] [причина]: N — номер заголовка из последнего списка; без N — последняя своя строка;
            # причина — остаток первой строки (в тело коммента идут ПОЛНЫЕ байты сообщения, §1Г(а))
            lx = _lexemes(s)
            head = lx[0][0] if lx else ""
            rest = s.strip()[s.strip().index(head) + len(head):] if head else s.strip()   # остаток — сырые байты после лексемы
            looks_like_n, core = _number_like(head)
            if looks_like_n:
                # лексема, ПОХОЖАЯ на номер, обязана разобраться как N либо дать переспрос — провал в «без N» запрещён
                # (раунд 1 №3, раунд 2 W5, раунд 3 B1/W3): классификация по Unicode-категориям (см. _number_like)
                if core is None or not _RE_INT.match(core) or int(core) < 1:
                    return self._unparsed(base, "n_not_positive_integer")
                out["n"] = int(core)
                out["title"] = rest.strip(" \t")
            else:
                out["title"] = s.strip(" \t")
            return out
        if kind in ("stop", "help"):
            return out
        if kind == "start-title":
            if not s.strip() or not _lexemes(s):   # заголовок без единой видимой лексемы — пуст (раунд 10 B)
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

    @staticmethod
    def _unparsed(base, reason):
        out = dict(base)
        out.update({"kind": "unparsed", "reason": reason})
        return out

    @staticmethod
    def _correction(base, reason):
        out = dict(base)
        out.update({"kind": "correction", "reason": reason})
        return out
