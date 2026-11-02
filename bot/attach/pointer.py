# -*- coding: utf-8 -*-
"""attach.pointer — разбор и запись указателя вложения (норма 04 §9.3) и суд переходов (§9.6).

Владелец — D20 T2. Чистые функции над БАЙТАМИ: ни сети, ни файловой системы, ни текстовых режимов.
Реестры (сигнатура, версии, порядок и грамматики полей, обязательность, состояния, причины, переходы,
производная ключа, сигнатура LFS) — только из `attach.norm` (генерируется из attachments.yaml).
Проза нормы, которой нет в реестрах (байтовые ограничения, условия строк переходов), исполняется
здесь по ключам реестров; ключи кода сверяются с реестрами при импорте (расхождение — NormDrift).

Классы содержимого файла по пути вложения (`classify`):
    bytes            — байты вложения (не указатель этой главы и не LFS) → исход чтения in-git
    lfs              — указатель Git LFS → lfs-unsupported
    pointer          — указатель версии 1, грамматика выполнена
    pointer-invalid  — сигнатура есть, первая строка нечитаема ЛИБО версия 1 и грамматика не выполнена
    pointer-version-unknown — сигнатура есть, версия не из known_versions
Порядок суда — §9.3 «Порядок суда»: (1) первая строка в пределах max_bytes+1 байт; (2) версия;
(3) байтовые ограничения и грамматика версии 1 — один вердикт на файл.
"""
import hashlib
import re

from . import norm as N

__all__ = ["NormDrift", "Classified", "classify", "render", "derive_key", "check_transition",
           "POINTER_STATES", "STATE_REASONS", "FIELD_ORDER"]


class NormDrift(RuntimeError):
    """Код и сгенерированные реестры разошлись — собственная ошибка адаптера (фатально)."""


MAGIC_PREFIX = N.POINTER_MAGIC_PREFIX.encode("ascii")
MAGIC_LINE = N.POINTER_MAGIC_LINE.encode("ascii")
LFS_PREFIX = N.LFS_SIGNATURE_PREFIX.encode("ascii")
MAX_BYTES = N.POINTER_MAX_BYTES
_FIRST_LINE_RE = re.compile(N.POINTER_FIRST_LINE_PATTERN)
_VERSION_RE = re.compile(N.POINTER_VERSION_PATTERN)
if (_FIRST_LINE_RE.fullmatch(N.POINTER_MAGIC_LINE) is None
        or _FIRST_LINE_RE.fullmatch(N.POINTER_MAGIC_PREFIX + "7") is None):
    raise NormDrift("magic_line / magic_prefix вне first_line_pattern")
FIELD_ORDER = tuple(N.POINTER_FIELD_ORDER)
_FIELD_RE = {name: re.compile(pat) for name, pat in N.POINTER_FIELD_PATTERNS}
_FIELD_MAX = dict(N.POINTER_FIELD_MAX_LEN)
PRESENCE = {st: dict(row) for st, row in N.POINTER_PRESENCE}
POINTER_STATES = tuple(s for s, carrier, _r in N.STATES if carrier == "pointer")
BYTES_STATES = tuple(s for s, carrier, _r in N.STATES if carrier == "bytes")
STATE_REASONS = {s: tuple(r) for s, _c, r in N.STATES}

# производная ключа: "sha256/<sha256>" → префикс + значение поля sha256
_DERIV_TOKEN = "<sha256>"
if not N.OBJECT_KEY_DERIVATION.endswith(_DERIV_TOKEN) or N.OBJECT_KEY_DERIVATION.count("<") != 1:
    raise NormDrift("object_key.derivation вне ожидаемой формы: %r" % N.OBJECT_KEY_DERIVATION)
KEY_PREFIX = N.OBJECT_KEY_DERIVATION[: -len(_DERIV_TOKEN)]

if set(PRESENCE) != set(POINTER_STATES):
    raise NormDrift("pointer.presence и states.list (carrier pointer) разошлись")
if set(_FIELD_RE) != set(FIELD_ORDER):
    raise NormDrift("pointer.fields и pointer.field_order разошлись")
if len(BYTES_STATES) != 1:
    raise NormDrift("ожидалось ровно одно состояние с носителем bytes")
GIT_STATE = BYTES_STATES[0]


def derive_key(sha256_hex):
    return KEY_PREFIX + sha256_hex


def _full(name, value):
    """Поле целиком под грамматикой (fullmatch: `$` Python иначе пропускает финальный LF)."""
    if _FIELD_RE[name].fullmatch(value) is None:
        return False
    mx = _FIELD_MAX.get(name)
    return mx is None or len(value) <= mx


class Classified(object):
    """Результат разбора. kind — см. модульную справку; state и fields — только у kind == 'pointer'
    (fields — dict имя → значение str; порядок — FIELD_ORDER); у 'bytes' state == GIT_STATE.
    defect — короткое имя нарушения (для диагностики; не исход нормы)."""
    __slots__ = ("kind", "state", "fields", "version", "defect")

    def __init__(self, kind, state=None, fields=None, version=None, defect=None):
        self.kind = kind
        self.state = state
        self.fields = fields or {}
        self.version = version
        self.defect = defect

    def __repr__(self):
        return "Classified(kind=%r, state=%r, fields=%r, version=%r, defect=%r)" % (
            self.kind, self.state, self.fields, self.version, self.defect)


def _invalid(defect, version=None):
    return Classified("pointer-invalid", version=version, defect=defect)


def _printable(b):
    return all(0x20 <= c <= 0x7E for c in b)


def classify(data):
    """Байты файла по пути вложения → Classified. data — bytes (полное содержимое файла; для решения
    «указатель или нет» достаточно первых max_bytes+1 байт, но байтовые ограничения требуют всего)."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("classify принимает только байты")
    data = bytes(data)
    if not data.startswith(MAGIC_PREFIX):
        if data.startswith(LFS_PREFIX):
            return Classified("lfs")
        return Classified("bytes", state=GIT_STATE)
    # (1) первая строка в пределах max_bytes + 1 байт
    head = data[: MAX_BYTES + 1]
    lf = head.find(b"\n")
    if lf < 0:
        return _invalid("first-line-unreadable")
    first = head[:lf]
    if not _printable(first):
        return _invalid("first-line-not-ascii")
    # первая строка — по pointer.first_line_pattern нормы (поправка d20/norm-amend): хвостовой пробел, пустая
    # версия, два пробела, нецифры, ведущий ноль → pointer-invalid; version-unknown — только при верной форме
    if _FIRST_LINE_RE.fullmatch(first.decode("ascii")) is None:
        return _invalid("first-line-form")
    version_s = first[len(MAGIC_PREFIX):].decode("ascii")
    if _VERSION_RE.fullmatch(version_s) is None:
        raise NormDrift("first_line_pattern и version_pattern нормы разошлись")
    # (2) версия
    if version_s not in N.POINTER_KNOWN_VERSIONS:
        return Classified("pointer-version-unknown", version=version_s)
    # (3) байтовые ограничения и грамматика версии 1 — один вердикт
    if len(data) > MAX_BYTES:
        return _invalid("over-max-bytes", version_s)
    if not all(c == 0x0A or 0x20 <= c <= 0x7E for c in data):
        return _invalid("byte-outside-ascii-lf", version_s)
    if not data.endswith(b"\n"):
        return _invalid("no-final-lf", version_s)
    lines = data[:-1].split(b"\n")   # байтовый разрез по LF; не splitlines()
    for ln in lines:
        if ln == b"":
            return _invalid("empty-line", version_s)
        if ln.endswith(b" "):
            return _invalid("trailing-space", version_s)
    if lines[0] != MAGIC_LINE:
        return _invalid("magic-line", version_s)
    if len(lines) < 2 or not lines[1].startswith(b"state "):
        return _invalid("no-state-line", version_s)
    state = lines[1][len(b"state "):].decode("ascii")
    if state not in POINTER_STATES:
        return _invalid("state-unknown", version_s)
    fields = {}
    last_pos = -1
    for ln in lines[2:]:
        sp = ln.find(b" ")
        if sp <= 0:
            return _invalid("field-line-form", version_s)
        name = ln[:sp].decode("ascii")
        value = ln[sp + 1:].decode("ascii")
        if name not in FIELD_ORDER:
            return _invalid("field-unknown", version_s)
        pos = FIELD_ORDER.index(name)
        if name in fields:
            return _invalid("field-duplicate", version_s)
        if pos < last_pos:
            return _invalid("field-order", version_s)
        last_pos = pos
        if not _full(name, value):
            return _invalid("field-grammar:" + name, version_s)
        fields[name] = value
    pres = PRESENCE[state]
    for name in FIELD_ORDER:
        if pres[name] == "R" and name not in fields:
            return _invalid("presence-required:" + name, version_s)
        if pres[name] == "X" and name in fields:
            return _invalid("presence-forbidden:" + name, version_s)
    # presence_extra (проза нормы): у unsaved при sha256 обязателен size
    if state == "unsaved" and "sha256" in fields and "size" not in fields:
        return _invalid("presence-extra:size", version_s)
    if "reason" in fields and fields["reason"] not in STATE_REASONS[state]:
        return _invalid("reason-not-of-state", version_s)
    if "key" in fields and fields["key"] != derive_key(fields.get("sha256", "")):
        return _invalid("key-derivation", version_s)
    return Classified("pointer", state=state, fields=fields, version=version_s)


def render(state, fields):
    """Детерминированная запись указателя версии 1: magic, state, поля строго в FIELD_ORDER.
    Одинаковый вход → одинаковые байты (правило merge §2.6/§8). Результат обязан разбираться
    обратно в тот же (state, fields) — иначе ValueError (вход вне нормы)."""
    if state not in POINTER_STATES:
        raise ValueError("состояние указателя вне нормы")
    extra = set(fields) - set(FIELD_ORDER)
    if extra:
        raise ValueError("поля вне нормы: %s" % ",".join(sorted(extra)))
    out = [MAGIC_LINE, b"state " + state.encode("ascii")]
    for name in FIELD_ORDER:
        if name in fields:
            v = fields[name]
            if not isinstance(v, str):
                raise ValueError("значение поля %s — не строка" % name)
            try:
                vb = v.encode("ascii")
            except UnicodeEncodeError:
                raise ValueError("значение поля %s — не ASCII" % name)
            out.append(name.encode("ascii") + b" " + vb)
    data = b"\n".join(out) + b"\n"
    c = classify(data)
    if c.kind != "pointer" or c.state != state or c.fields != dict(fields):
        raise ValueError("указатель вне грамматики нормы: %s" % (c.defect or c.kind))
    return data


# --------------------------------------------------------------------------- переходы §9.6
def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _t_pending_stored(o, ob, n, nb):
    # меняется только строка state; прочие строки побайтово те же
    return nb == ob.replace(b"\nstate pending\n", b"\nstate stored\n", 1)


def _t_pending_unsaved(o, ob, n, nb):
    exp = {k: v for k, v in o.fields.items() if k != "key"}
    exp["reason"] = "upload-failed"
    return n.fields == exp


def _t_unsaved_stored(o, ob, n, nb):
    for k in ("sha256", "size"):
        if k in o.fields and o.fields[k] != n.fields.get(k):
            return False
    return o.fields.get("source") == n.fields.get("source")


def _t_unsaved_git(o, ob, n, nb):
    return "sha256" not in o.fields or o.fields["sha256"] == _sha(nb)


def _t_to_withdrawn(o, ob, n, nb):
    return n.fields.get("reason") in STATE_REASONS["withdrawn"]


_RULES = {
    ("pending", "stored"): _t_pending_stored,
    ("pending", "unsaved"): _t_pending_unsaved,
    ("unsaved", "stored"): _t_unsaved_stored,
    ("unsaved", GIT_STATE): _t_unsaved_git,
    ("stored", "withdrawn"): _t_to_withdrawn,
    ("pending", "withdrawn"): _t_to_withdrawn,
    ("unsaved", "withdrawn"): _t_to_withdrawn,
    (GIT_STATE, "withdrawn"): _t_to_withdrawn,
}
if set(_RULES) != set(N.TRANSITIONS):
    raise NormDrift("правила переходов кода и states.transitions нормы разошлись")

# Проза нормы, которую код исполняет (а не читает): ключ -> sha256[:16] ТЕКСТА, против которого код написан.
# Смена СМЫСЛА правила (текст rule перехода, presence_extra, байтовые ограничения, правило отказа записи) —
# NormDrift при импорте: код пересматривается вместе с нормой, а не остаётся прежним молча.
IMPLEMENTED_PROSE = {
    ("transition", "pending", "stored"): "fa711dbfc85c9f95",
    ("transition", "pending", "unsaved"): "cd348f162503e767",
    ("transition", "unsaved", "stored"): "03fee70bcd70e1b6",
    ("transition", "unsaved", "git"): "721920df5dba7280",
    ("transition", "stored", "withdrawn"): "817654a8a7d93f2d",
    ("transition", "pending", "withdrawn"): "f5282dda20aba0ac",
    ("transition", "unsaved", "withdrawn"): "a522effb2b3f7eb4",
    ("transition", "git", "withdrawn"): "6bf5af1708df08d5",
    ("pointer", "presence_extra"): "edf7ffac8b3c211a",
    ("pointer", "encoding"): "7c367bab04382d94",
    ("states", "write_failure"): "41078fd0768ffc48",
    ("states", "pending_requires_durable_queue"): "c5691bd2afd1513a",
}


def prose_now():
    """Те же ключи -> sha256[:16] текста из сгенерированных реестров."""
    d = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]  # noqa: E731
    out = {("transition", f, t): d(r) for f, t, r in N.TRANSITION_RULES}
    out[("pointer", "presence_extra")] = d(N.POINTER_PRESENCE_EXTRA)
    out[("pointer", "encoding")] = d(N.POINTER_ENCODING)
    out[("states", "write_failure")] = d(N.WRITE_FAILURE_RULE)
    out[("states", "pending_requires_durable_queue")] = d(N.PENDING_REQUIRES_DURABLE_QUEUE)
    return out


_now = prose_now()
if _now != IMPLEMENTED_PROSE:
    raise NormDrift("смысл правил нормы сменился: %s" % sorted(
        "/".join(k) for k in set(_now) | set(IMPLEMENTED_PROSE) if _now.get(k) != IMPLEMENTED_PROSE.get(k)))


def state_of(c):
    if c.kind == "bytes":
        return GIT_STATE
    if c.kind == "pointer":
        return c.state
    return None


def check_transition(old_bytes, new_bytes):
    """Законна ли правка содержимого существующего пути old → new (один родитель, §2.6/§9.6).
    Возвращает (True, 'identity'|'<from>-><to>') либо (False, причина)."""
    if old_bytes == new_bytes:
        return True, "identity"
    o, n = classify(old_bytes), classify(new_bytes)
    so, sn = state_of(o), state_of(n)
    if so is None or sn is None:
        return False, "not-a-legal-carrier"
    rule = _RULES.get((so, sn))
    if rule is None:
        return False, "%s->%s not in states.transitions" % (so, sn)
    if not rule(o, old_bytes, n, new_bytes):
        return False, "%s->%s condition violated" % (so, sn)
    return True, "%s->%s" % (so, sn)
