"""yamlmini — строгий загрузчик и детерминированный дампер ПОДМНОЖЕСТВА YAML на stdlib.

Зачем: stdlib YAML не читает, а все реестры комплекта и workflow-обёртки — YAML. Стоковые
загрузчики молча берут последний из дублирующихся ключей (ядро 04.10, прогон C) — здесь дубль
ключа есть ошибка. Владелец — T1 (D09). Python 3.9, без зависимостей.

Подмножество (всё остальное — YamlError, а не «как получится»):
  * блочные мэппинги и последовательности по отступу (пробелы; табуляция в отступе — ошибка);
  * скаляры в одну строку: plain, 'одинарные', "двойные" (escape: обратная косая, кавычка,
    n, t, r, u+4 hex, U+8 hex);
  * блочные скаляры `|`, `|-`, `>`, `>-`;
  * flow-последовательность в одну строку `[a, "b", 'c']` из скаляров; пустые `[]` и `{}`;
  * типизация plain-скаляра: null/~/пусто → None; true/false → bool; целые → int; ОСТАЛЬНОЕ —
    str (в том числе `on`, `off`, `yes`, `no`, дроби: они остаются строками намеренно);
  * комментарии `#` (в начале строки или после пробела вне кавычек).
Запрещено (ошибка): якоря `&`, алиасы `*`, теги `!`, директивы `%`, второй документ, `\r`,
BOM, дубли ключей, flow-мэппинги кроме `{}`, многострочные plain-скаляры.

Дамп: детерминированный — порядок ключей = порядок вставки (или sort_keys=True), LF, ровно один
финальный `\n`; строка дампится plain, только если загрузчик прочитает её обратно той же строкой,
иначе — в двойных кавычках; многострочные строки без хвостовых пробелов — блоком `|`.
"""
import re

__all__ = ["YamlError", "load", "loads", "dumps", "load_file", "dump_file"]


class YamlError(ValueError):
    pass


_KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.\-/]*|\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*')\s*:(?:\s+(.*))?$")
_INT_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")
_PLAIN_SAFE_RE = re.compile(r"^[A-Za-z0-9_./Ѐ-ӿ][A-Za-z0-9_.\-/:@+,()=Ѐ-ӿ«»— ]*$")
_BOOL = {"true": True, "false": False}
_NULLS = {"", "~", "null"}


# ------------------------------------------------------------------ разбор строк
def _strip_comment(line):
    """Снимает комментарий вне кавычек. Возвращает строку без комментария (без rstrip хвоста)."""
    quote = None
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if quote is None:
            if c in ("'", '"'):
                quote = c
            elif c == "#" and (i == 0 or line[i - 1] in (" ", "\t")):
                return line[:i].rstrip(" ")
        else:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = None
        i += 1
    return line


def _prepare(text):
    if "\r" in text:
        raise YamlError("CR в тексте: допускается только LF")
    if text.startswith("﻿"):
        raise YamlError("BOM в начале файла запрещён")
    raw = text.split("\n")
    out = []  # (lineno, indent, content, raw_line)
    for idx, r in enumerate(raw):
        lineno = idx + 1
        if r.strip() == "---":
            if any(o[2] for o in out):
                raise YamlError("строка %d: второй документ (---) запрещён" % lineno)
            continue
        if r.strip() == "...":
            raise YamlError("строка %d: маркер конца документа запрещён" % lineno)
        if r.startswith("%"):
            raise YamlError("строка %d: директива %% запрещена" % lineno)
        stripped_comment = _strip_comment(r)
        if stripped_comment.strip() == "":
            out.append((lineno, None, "", r))
            continue
        indent = len(r) - len(r.lstrip(" "))
        if r[indent:indent + 1] == "\t":
            raise YamlError("строка %d: табуляция в отступе запрещена" % lineno)
        out.append((lineno, indent, stripped_comment[indent:].rstrip(" "), r))
    return out


class _Parser(object):
    def __init__(self, lines):
        self.lines = lines
        self.i = 0

    # --- служебное
    def _skip_blank(self):
        while self.i < len(self.lines) and self.lines[self.i][1] is None:
            self.i += 1

    def _cur(self):
        self._skip_blank()
        if self.i >= len(self.lines):
            return None
        return self.lines[self.i]

    # --- узлы
    def parse_document(self):
        cur = self._cur()
        if cur is None:
            return None
        value = self.parse_node(cur[1])
        cur = self._cur()
        if cur is not None:
            raise YamlError("строка %d: неразобранный хвост документа: %r" % (cur[0], cur[2]))
        return value

    def parse_node(self, indent):
        cur = self._cur()
        if cur is None:
            return None
        lineno, ind, content, _ = cur
        if ind != indent:
            raise YamlError("строка %d: неожиданный отступ %d (ожидался %d)" % (lineno, ind, indent))
        if content == "-" or content.startswith("- "):
            return self.parse_sequence(indent)
        if _KEY_RE.match(content):
            return self.parse_mapping(indent)
        raise YamlError("строка %d: не мэппинг и не последовательность: %r" % (lineno, content))

    def parse_mapping(self, indent):
        result = {}
        while True:
            cur = self._cur()
            if cur is None or cur[1] < indent:
                return result
            lineno, ind, content, _ = cur
            if ind > indent:
                raise YamlError("строка %d: лишний отступ %d внутри мэппинга с отступом %d" % (lineno, ind, indent))
            m = _KEY_RE.match(content)
            if not m:
                if content == "-" or content.startswith("- "):
                    return result
                raise YamlError("строка %d: ожидался ключ, получено %r" % (lineno, content))
            key = self._key(m.group(1), lineno)
            if key in result:
                raise YamlError("строка %d: дублирующийся ключ %r" % (lineno, key))
            rest = m.group(2)
            self.i += 1
            if rest is None or rest == "":
                result[key] = self._nested_value(indent, lineno)
            elif rest[0] in ("|", ">"):
                result[key] = self._block_scalar(rest, indent, lineno)
            else:
                result[key] = self._inline_scalar(rest, lineno)

    def parse_sequence(self, indent):
        result = []
        while True:
            cur = self._cur()
            if cur is None or cur[1] < indent:
                return result
            lineno, ind, content, _ = cur
            if ind > indent:
                raise YamlError("строка %d: лишний отступ внутри последовательности" % lineno)
            if not (content == "-" or content.startswith("- ")):
                return result
            rest = content[2:] if content.startswith("- ") else ""
            rest = rest.lstrip(" ")
            if rest == "":
                self.i += 1
                result.append(self._nested_value(indent, lineno))
            elif rest[0] in ("|", ">"):
                self.i += 1
                result.append(self._block_scalar(rest, indent, lineno))
            elif _KEY_RE.match(rest) or rest == "-" or rest.startswith("- "):
                # элемент — мэппинг/последовательность, начинающаяся на той же строке:
                # виртуально сдвигаем содержимое на отступ элемента
                sub_indent = indent + (len(content) - len(rest))
                self.lines[self.i] = (lineno, sub_indent, rest, cur[3])
                result.append(self.parse_node(sub_indent))
            else:
                self.i += 1
                result.append(self._inline_scalar(rest, lineno))

    def _nested_value(self, indent, lineno):
        cur = self._cur()
        if cur is None:
            return None
        n_lineno, n_ind, n_content, _ = cur
        if n_ind > indent:
            return self.parse_node(n_ind)
        if n_ind == indent and (n_content == "-" or n_content.startswith("- ")):
            return self.parse_sequence(indent)
        return None

    def _block_scalar(self, header, indent, lineno):
        style = header[0]
        chomp = "clip"
        tail = header[1:]
        if tail == "-":
            chomp = "strip"
        elif tail == "+":
            chomp = "keep"
        elif tail != "":
            raise YamlError("строка %d: неподдерживаемый заголовок блочного скаляра %r" % (lineno, header))
        body = []
        block_indent = None
        while self.i < len(self.lines):
            l_no, l_ind, l_content, l_raw = self.lines[self.i]
            if l_raw.strip() == "":
                body.append("")
                self.i += 1
                continue
            raw_indent = len(l_raw) - len(l_raw.lstrip(" "))
            if raw_indent <= indent:
                break
            if block_indent is None:
                block_indent = raw_indent
            if raw_indent < block_indent:
                raise YamlError("строка %d: отступ блочного скаляра меньше первого" % l_no)
            body.append(l_raw[block_indent:])
            self.i += 1
        while body and body[-1] == "":
            trailing = body.pop()
            if chomp == "keep":
                body.append(trailing)
                break
        if style == ">":
            text = _fold(body)
        else:
            text = "\n".join(body)
        if chomp == "strip":
            return text
        if chomp == "keep":
            return text + "\n"
        return text + "\n" if body else ""

    def _key(self, token, lineno):
        if token.startswith('"') or token.startswith("'"):
            return self._inline_scalar(token, lineno)
        return token

    def _inline_scalar(self, text, lineno):
        text = text.strip(" ")
        if text == "":
            return None
        c = text[0]
        if c == '"':
            return _parse_double(text, lineno)
        if c == "'":
            return _parse_single(text, lineno)
        if c in ("[", "{"):
            value, pos = _flow_parse(text, 0, lineno)
            if text[pos:].strip(" ") != "":
                raise YamlError("строка %d: хвост после flow-узла: %r" % (lineno, text[pos:]))
            return value
        if c in ("&", "*", "!", "%", "@", "`"):
            raise YamlError("строка %d: запрещённый префикс скаляра %r (якорь/алиас/тег)" % (lineno, c))
        if ": " in text or text.endswith(":"):
            raise YamlError("строка %d: двоеточие с пробелом внутри plain-скаляра: %r" % (lineno, text))
        return _plain(text)

def _skip_ws(text, pos):
    while pos < len(text) and text[pos] == " ":
        pos += 1
    return pos


def _flow_quoted(text, pos, lineno):
    q = text[pos]
    i = pos + 1
    while i < len(text):
        ch = text[i]
        if q == '"' and ch == "\\":
            i += 2
            continue
        if ch == q:
            if q == "'" and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            token = text[pos:i + 1]
            return (_parse_double(token, lineno) if q == '"' else _parse_single(token, lineno)), i + 1
        i += 1
    raise YamlError("строка %d: незакрытая кавычка во flow-узле" % lineno)


def _flow_plain(text, pos, lineno, terminators):
    i = pos
    while i < len(text) and text[i] not in terminators:
        if text[i] == ":" and (i + 1 == len(text) or text[i + 1] == " "):
            break
        i += 1
    token = text[pos:i].strip(" ")
    if token == "":
        raise YamlError("строка %d: пустой скаляр во flow-узле" % lineno)
    if token[0] in ("&", "*", "!", "%", "@", "`"):
        raise YamlError("строка %d: запрещённый префикс скаляра %r (якорь/алиас/тег)" % (lineno, token[0]))
    return _plain(token), i


def _flow_parse(text, pos, lineno):
    """Разбор одного flow-узла (последовательность/мэппинг/скаляр) с позиции pos; возвращает (значение, позиция)."""
    pos = _skip_ws(text, pos)
    if pos >= len(text):
        raise YamlError("строка %d: обрыв flow-узла" % lineno)
    ch = text[pos]
    if ch == "[":
        out = []
        pos = _skip_ws(text, pos + 1)
        if pos < len(text) and text[pos] == "]":
            return out, pos + 1
        while True:
            value, pos = _flow_parse(text, pos, lineno)
            out.append(value)
            pos = _skip_ws(text, pos)
            if pos >= len(text):
                raise YamlError("строка %d: незакрытая flow-последовательность" % lineno)
            if text[pos] == ",":
                pos = _skip_ws(text, pos + 1)
                if pos < len(text) and text[pos] == "]":
                    return out, pos + 1
                continue
            if text[pos] == "]":
                return out, pos + 1
            raise YamlError("строка %d: ожидалась , или ] во flow-последовательности" % lineno)
    if ch == "{":
        out = {}
        pos = _skip_ws(text, pos + 1)
        if pos < len(text) and text[pos] == "}":
            return out, pos + 1
        while True:
            if text[pos] in ("'", '"'):
                key, pos = _flow_quoted(text, pos, lineno)
            else:
                key, pos = _flow_plain(text, pos, lineno, ",}]")
                key = str(key) if key is not None else ""
            pos = _skip_ws(text, pos)
            if pos >= len(text) or text[pos] != ":":
                raise YamlError("строка %d: во flow-мэппинге ожидалось ':' после ключа %r" % (lineno, key))
            pos += 1
            if pos < len(text) and text[pos] not in (" ", ",", "}"):
                raise YamlError("строка %d: после ':' во flow-мэппинге нужен пробел" % lineno)
            if key in out:
                raise YamlError("строка %d: дублирующийся ключ %r во flow-мэппинге" % (lineno, key))
            pos = _skip_ws(text, pos)
            if pos < len(text) and text[pos] in (",", "}"):
                out[key] = None
            else:
                out[key], pos = _flow_parse(text, pos, lineno)
            pos = _skip_ws(text, pos)
            if pos >= len(text):
                raise YamlError("строка %d: незакрытый flow-мэппинг" % lineno)
            if text[pos] == ",":
                pos = _skip_ws(text, pos + 1)
                if pos < len(text) and text[pos] == "}":
                    return out, pos + 1
                continue
            if text[pos] == "}":
                return out, pos + 1
            raise YamlError("строка %d: ожидалась , или } во flow-мэппинге" % lineno)
    if ch in ("'", '"'):
        return _flow_quoted(text, pos, lineno)
    return _flow_plain(text, pos, lineno, ",]}")


def _fold(lines):
    out = []
    para = []
    for l in lines:
        if l == "":
            if para:
                out.append(" ".join(para))
                para = []
            out.append("")
        else:
            para.append(l)
    if para:
        out.append(" ".join(para))
    # схлопываем: абзацы разделены одним "\n"
    text = ""
    for idx, seg in enumerate(out):
        if seg == "":
            text += "\n"
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += seg
    return text


def _plain(text):
    if text in _NULLS:
        return None
    if text in _BOOL:
        return _BOOL[text]
    if _INT_RE.match(text):
        return int(text)
    return text


_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0"}


def _parse_double(text, lineno):
    if len(text) < 2 or not text.endswith('"'):
        raise YamlError("строка %d: незакрытая двойная кавычка" % lineno)
    body = text[1:-1]
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            i += 1
            if i >= len(body):
                raise YamlError("строка %d: оборванный escape" % lineno)
            e = body[i]
            if e == "u":
                hexs = body[i + 1:i + 5]
                if len(hexs) != 4 or not re.match(r"^[0-9a-fA-F]{4}$", hexs):
                    raise YamlError("строка %d: плохой \\u escape" % lineno)
                out.append(chr(int(hexs, 16)))
                i += 4
            elif e == "U":
                hexs = body[i + 1:i + 9]
                if len(hexs) != 8 or not re.match(r"^[0-9a-fA-F]{8}$", hexs):
                    raise YamlError("строка %d: плохой \\U escape" % lineno)
                out.append(chr(int(hexs, 16)))
                i += 8
            elif e in _ESC:
                out.append(_ESC[e])
            else:
                raise YamlError("строка %d: неизвестный escape \\%s" % (lineno, e))
        elif ch == '"':
            raise YamlError("строка %d: неэкранированная кавычка внутри строки" % lineno)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _parse_single(text, lineno):
    if len(text) < 2 or not text.endswith("'"):
        raise YamlError("строка %d: незакрытая одинарная кавычка" % lineno)
    body = text[1:-1]
    if re.search(r"(?<!')'(?!')", body):
        raise YamlError("строка %d: одиночная кавычка внутри одинарной строки" % lineno)
    return body.replace("''", "'")


# ------------------------------------------------------------------ публичный API
def loads(text):
    if not isinstance(text, str):
        raise YamlError("ожидается str (декодируй байты как UTF-8 заранее)")
    lines = _prepare(text)
    return _Parser(lines).parse_document()


load = loads


def load_file(path):
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise YamlError("%s: не UTF-8: %s" % (path, e))
    try:
        return loads(text)
    except YamlError as e:
        raise YamlError("%s: %s" % (path, e))


# ------------------------------------------------------------------ дамп
def _needs_quote(s):
    if s == "":
        return True
    if s in _NULLS or s in _BOOL or _INT_RE.match(s):
        return True
    if s != s.strip(" "):
        return True
    if "\n" in s or "\t" in s:
        return True
    if s[0] in ("-", "?", "[", "]", "{", "}", '"', "'", "|", ">", "&", "*", "!", "%", "@", "`", "#", ","):
        return True
    if ": " in s or s.endswith(":") or " #" in s:
        return True
    return not _PLAIN_SAFE_RE.match(s)


def _quote(s):
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _quote(v) if _needs_quote(v) else v
    raise YamlError("недампируемый тип %s" % type(v).__name__)


def _block_ok(s):
    if "\n" not in s or not s.endswith("\n"):
        return False
    for l in s.split("\n"):
        if l != l.rstrip(" \t") or "\r" in l:
            return False
    return s.count("\n") >= 1 and not s.endswith("\n\n")


def _emit(v, indent, out, sort_keys):
    pad = " " * indent
    if isinstance(v, dict):
        keys = sorted(v.keys()) if sort_keys else list(v.keys())
        for k in keys:
            if not isinstance(k, str):
                raise YamlError("ключ не строка: %r" % (k,))
            ktxt = _quote(k) if _needs_quote(k) or not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/]*$", k) else k
            val = v[k]
            if isinstance(val, dict):
                if not val:
                    out.append("%s%s: {}" % (pad, ktxt))
                else:
                    out.append("%s%s:" % (pad, ktxt))
                    _emit(val, indent + 2, out, sort_keys)
            elif isinstance(val, list):
                if not val:
                    out.append("%s%s: []" % (pad, ktxt))
                else:
                    out.append("%s%s:" % (pad, ktxt))
                    _emit(val, indent + 2, out, sort_keys)
            elif isinstance(val, str) and _block_ok(val):
                out.append("%s%s: |" % (pad, ktxt))
                for l in val[:-1].split("\n"):
                    out.append(("%s  %s" % (pad, l)) if l else "")
            else:
                out.append("%s%s: %s" % (pad, ktxt, _scalar(val)))
    elif isinstance(v, list):
        for item in v:
            if isinstance(item, dict) and item:
                sub = []
                _emit(item, indent + 2, sub, sort_keys)
                first = sub[0]
                out.append("%s- %s" % (pad, first[indent + 2:]))
                out.extend(sub[1:])
            elif isinstance(item, list) and item:
                sub = []
                _emit(item, indent + 2, sub, sort_keys)
                out.append("%s- %s" % (pad, sub[0][indent + 2:]))
                out.extend(sub[1:])
            elif isinstance(item, (dict, list)):
                out.append("%s- %s" % (pad, "{}" if isinstance(item, dict) else "[]"))
            else:
                out.append("%s- %s" % (pad, _scalar(item)))
    else:
        out.append(pad + _scalar(v))


def dumps(obj, sort_keys=False):
    out = []
    _emit(obj, 0, out, sort_keys)
    text = "\n".join(out)
    return text + "\n"


def dump_file(path, obj, sort_keys=False):
    data = dumps(obj, sort_keys=sort_keys).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return data
