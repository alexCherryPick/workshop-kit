#!/usr/bin/env python3
"""build_help.py — ЧИСТАЯ ПРОЕКЦИЯ реестров в тексты. Владелец — T1 (D09 §1А, §1Д(г)).

Входы (читаются на каждом прогоне, копий нет):
  kit/commands.yaml      — закрытый реестр команд  → справка, краткая справка, блок команд инструкции
  kit/install-steps.yaml — реестр ручных шагов     → блок шагов инструкции (и число N — счётом позиций)
  kit/reask-phrases.yaml — реестр фраз переспроса → проверка перед каждой справкой; поллер читает его ОТДЕЛЬНО
                           от реестра команд (порча фраз — деградация справки/переспроса, не остановка приёма)

Подкоманды:
  help          [--commands P] [--phrases P]   текст справки (исход 19) — по макету help_page реестра команд (D19 M2;
                                               испорченный макет — отказ, rc 1); прогон проверяет фразы переспроса
  reasons       [--commands P] [--forms P]     фразы переспроса по исходу и причине (исходы 4, 23) с длиной ответа
  short         [--commands P] [--forms P]     краткая справка (имя — что делает), без примеров
  commands-block [--commands P]                блок команд для инструкции (между маркерами)
  steps-block   [--steps P]                    блок ручных шагов для инструкции (между маркерами)
  render --guide P [--commands P] [--steps P] [--write]
                                               инструкция с перегенерированными блоками между маркерами;
                                               без --write — печать в stdout, с --write — запись на место
  count-steps   [--steps P]                    печатает N — число позиций реестра шагов
  render-storage --guide P [--steps P] [--write]
                                               инструкция хранилища вложений (docs/storage-setup.ru.md): блоки имён
                                               секретов ключа писателя и строк credentials — из реестра шагов

Проекции справки (help, short, commands-block, render) и reasons сначала проверяют ЦЕЛУЮ таблицу фраз переспроса
(check_reask: замкнутость по причинам КОДА, форма фраз и заглушки, бюджет). Коды выхода: 0 — выход напечатан;
1 — реестр не читается / нет обязательного поля; 3 — нарушен реестр фраз переспроса (имена нарушений — в stderr);
4 — собственная ошибка сборщика причин кода (фатально, не пропуск).

Детерминизм: выход зависит только от байтов входных реестров; порядок — порядок реестра.
Здесь нет ни одного литерала имени команды и ни одного литерала шага.
"""
import argparse
import ast
import builtins
import hashlib
import os
import re
import stat
import sys
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402

MARK_COMMANDS_START = "<!-- generated:commands:start -->"
MARK_COMMANDS_END = "<!-- generated:commands:end -->"
MARK_STEPS_START = "<!-- generated:steps:start -->"
MARK_STEPS_END = "<!-- generated:steps:end -->"
MARK_CORR_START = "<!-- generated:correction-example:start -->"
MARK_CORR_END = "<!-- generated:correction-example:end -->"
MARK_DATED_START = "<!-- generated:dated-example:start -->"
MARK_DATED_END = "<!-- generated:dated-example:end -->"

# Бюджет однострочного переспроса (T8, REQ-095; v8): одна строка не длиннее этого — единственное место числа,
# поллер берёт его отсюда (poll.SHORT_REPLY_MAX)
SHORT_REPLY_MAX = 160

_REQUIRED_COMMAND_FIELDS = ("id", "name", "token", "synopsis", "grammar", "example", "time_bearing",
                            "callback_allowed", "tail_rule", "outcomes", "help_text", "guide_text")
# необязательные поля позиции (ЭРРАТА D10 «А», §1А(б)): example_dated — пример записи ЗАДНИМ ЧИСЛОМ с явной датой
_OPTIONAL_COMMAND_FIELDS = ("example_dated",)
_REQUIRED_STEP_FIELDS = ("id", "title", "when", "guide", "verified_by")
# подстановки фраз переспроса: {token:<id>} {example:<id>} {example_dated:<id>} — поля позиции; {form:<id>} — пример формы
_PLACEHOLDER_KINDS = ("token", "example", "example_dated", "form")


def load_commands(path):
    doc = yamlmini.load_file(path)
    if not isinstance(doc, dict) or doc.get("registry") != "commands":
        raise SystemExit("реестр команд: не тот файл (registry != commands): %s" % path)
    cmds = doc.get("commands")
    if not isinstance(cmds, list) or not cmds:
        raise SystemExit("реестр команд пуст: %s" % path)
    seen = set()
    for c in cmds:
        for f in _REQUIRED_COMMAND_FIELDS:
            if f not in c:
                raise SystemExit("реестр команд: у позиции %r нет поля %r" % (c.get("id"), f))
        if c["id"] in seen:
            raise SystemExit("реестр команд: дубль id %r" % c["id"])
        seen.add(c["id"])
        for f in _OPTIONAL_COMMAND_FIELDS:
            if f in c and not (isinstance(c[f], str) and c[f].strip()):
                raise SystemExit("реестр команд: у позиции %r поле %r пусто" % (c.get("id"), f))
    return doc


def load_steps(path):
    doc = yamlmini.load_file(path)
    if not isinstance(doc, dict) or doc.get("registry") != "install_steps":
        raise SystemExit("реестр шагов: не тот файл (registry != install_steps): %s" % path)
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        raise SystemExit("реестр шагов пуст: %s" % path)
    for s in steps:
        for f in _REQUIRED_STEP_FIELDS:
            if f not in s:
                raise SystemExit("реестр шагов: у позиции %r нет поля %r" % (s.get("id"), f))
    # D20 T3: значения when — закрытое множество реестра when_values (метки печатаются отсюда, копии в коде нет)
    wv = doc.get("when_values")
    if not isinstance(wv, dict) or not wv or any(not isinstance(v, dict) for v in wv.values()):
        raise SystemExit("реестр шагов: нет мэппинга when_values (закрытое множество значений when): %s" % path)
    for s in steps:
        if s["when"] not in wv:
            raise SystemExit("реестр шагов: у позиции %r when %r вне when_values" % (s.get("id"), s["when"]))
    return doc


def load_forms(path):
    """Реестр форм длительности (T8): справка и инструкция печатают ПРИМЕРЫ отсюда; списка форм в коде нет."""
    doc = yamlmini.load_file(path)
    if not isinstance(doc, dict) or doc.get("registry") != "duration_forms":
        raise SystemExit("реестр форм длительности: не тот файл (registry != duration_forms): %s" % path)
    forms = doc.get("forms")
    if not isinstance(forms, list) or not forms:
        raise SystemExit("реестр форм длительности пуст: %s" % path)
    for f in forms:
        for k in ("id", "example", "expected_seconds", "expected_title"):
            if k not in f:
                raise SystemExit("реестр форм: у формы %r нет поля %r" % (f.get("id"), k))
        if "expected_date" in f and not (isinstance(f["expected_date"], str) and f["expected_date"].strip()):
            raise SystemExit("реестр форм: у формы %r поле expected_date пусто" % f.get("id"))
    return doc


PHRASES_PATH = os.path.join(_HERE, "reask-phrases.yaml")
_PHRASE_KEYS = ("reask_reasons", "reask_reason_fallback")


PHRASES_MAX_BYTES = 256 * 1024     # предел реестра фраз (сейчас ~7 КиБ): больше — нарушение, а не чтение без конца


def _read_regular_bounded(path, limit):
    """→ (байты | None, нарушение | None). Открытие БЕЗ ожидания (O_NONBLOCK: FIFO без писателя не вешает open), тип —
    fstat ОТКРЫТОГО дескриптора (цель ссылки уже разрешена, гонки «проверил-открыл» нет): не обычный файл (FIFO,
    устройство, каталог, сокет) — нарушение без единого read; обычный — O_NONBLOCK снимается, чтение не больше
    limit + 1 байт."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError as e:
        return None, ("reask.phrases_missing", path, "реестр фраз не открывается: %s" % e)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            kind = next((k for k, f in (("FIFO", stat.S_ISFIFO), ("символьное устройство", stat.S_ISCHR),
                                        ("блочное устройство", stat.S_ISBLK), ("каталог", stat.S_ISDIR),
                                        ("сокет", stat.S_ISSOCK)) if f(st.st_mode)), "не обычный файл")
            return None, ("reask.phrases_not_regular", path, "реестр фраз — %s, а не обычный файл: не читается" % kind)
        if st.st_size > limit:
            return None, ("reask.phrases_too_large", path, "реестр фраз %d байт > предела %d" % (st.st_size, limit))
        try:
            import fcntl
            fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
        except (ImportError, OSError, AttributeError):
            pass                       # у обычного файла O_NONBLOCK чтение не меняет — снятие флага лишь чистота
        chunks, total = [], 0
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
            total += len(b)
            if total > limit:          # файл рос во время чтения — предел держится по фактическим байтам
                return None, ("reask.phrases_too_large", path, "реестр фраз больше предела %d байт" % limit)
        return b"".join(chunks), None
    except OSError as e:
        return None, ("reask.phrases_missing", path, "реестр фраз не читается: %s" % e)
    finally:
        os.close(fd)


def load_phrases(path=None):
    """Реестр фраз переспроса (R3-fix, Q-01; R4-fix, B-R4-01) → (документ, [нарушения]). НИКОГДА не бросает и НЕ ЖДЁТ:
    нет файла, не обычный файл (FIFO/устройство/каталог — в т.ч. цель ссылки), больше предела, пуст, не читается как
    UTF-8/YAML (дубль ключа, неизвестный escape, незакрытая кавычка, отступ/табуляция…), не тот registry — именованное
    нарушение и пустой документ. Реестр команд читается отдельно (парсер, приём) — байты фраз на него не влияют."""
    path = path or PHRASES_PATH
    raw, bad = _read_regular_bounded(path, PHRASES_MAX_BYTES)
    if bad is not None:
        return {}, [bad]
    if not raw.strip():
        return {}, [("reask.phrases_empty", path, "реестр фраз пуст")]
    try:
        doc = yamlmini.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, yamlmini.YamlError, ValueError, RecursionError) as e:
        return {}, [("reask.phrases_yaml", path, "реестр фраз не разбирается: %s" % e)]
    if not isinstance(doc, dict) or doc.get("registry") != "reask_phrases":
        return {}, [("reask.phrases_registry", path, "не реестр фраз (registry != reask_phrases)")]
    return doc, []


def _default_forms():
    return load_forms(os.path.join(_HERE, "duration-forms.yaml"))


def backdate_examples(doc, forms_doc):
    """Примеры записи ЗАДНИМ ЧИСЛОМ (ЭРРАТА D10 «А», §1А(б)) — ДАННЫЕ реестров, литералов здесь нет: поле
    `example_dated` позиций реестра команд (порядок реестра) и примеры форм с `expected_date` реестра форм.
    Справка ОБЯЗАНА показывать оба вида: нет позиции грамматики track с `example_dated` либо нет формы с
    датой — отказ прогона, а не справка без способа записать прошлый день."""
    cmd = [c["example_dated"] for c in doc["commands"] if c.get("example_dated")]
    if not any(c.get("example_dated") and str(c.get("grammar", "")).endswith("#grammar-track") for c in doc["commands"]):
        raise SystemExit("реестр команд: у позиции грамматики track нет example_dated — справке нечем показать запись за прошлый день")
    forms = [f["example"] for f in forms_doc["forms"] if f.get("expected_date")]
    if not forms:
        raise SystemExit("реестр форм: нет формы с expected_date — справке нечем показать «дата + длительность»")
    return cmd + forms


def backdate_line(doc, forms_doc):
    return "Запись за прошлый день (дата ГГГГ-ММ-ДД — первой): %s" % "; ".join(backdate_examples(doc, forms_doc))


def forms_examples_line(forms_doc):
    return "Формы длительности (примеры из реестра, позиций: %d): %s" % (len(forms_doc["forms"]), "; ".join("«%s»" % f["example"] for f in forms_doc["forms"]))


# ------------------------------------------------------------------ проекции
_SUBST_RE = re.compile(r"\{(token:[a-z_]+|confirm_prefix)\}")


class HelpPageError(ValueError):
    """Испорченный макет справки. CLI (`help`) — отказ; рантайм бота — прежний перечень (D19 M2 R1-02)."""


def _subst(doc, text):
    """Подстановки макета справки: {token:<id>} и {confirm_prefix} — из реестра (литералов команд в макете нет)."""
    if not isinstance(text, str):
        raise HelpPageError("макет справки: ожидалась строка, получено %r" % (text,))
    by_id = {c["id"]: c for c in doc["commands"]}

    def one(m):
        key = m.group(1)
        if key == "confirm_prefix":
            return doc["confirm_prefix"]
        pid = key.split(":", 1)[1]
        if pid not in by_id or not by_id[pid]["token"]:
            raise HelpPageError("макет справки: подстановка {%s} — нет позиции с токеном" % key)
        return by_id[pid]["token"]
    out = _SUBST_RE.sub(one, text)
    if "{" in out or "}" in out:
        raise HelpPageError("макет справки: неразобранная подстановка в %r" % text)
    return out


def _form_examples(forms_doc, ids):
    if not isinstance(ids, list):
        raise HelpPageError("макет справки: список форм — не список: %r" % (ids,))
    by_id = {f["id"]: f for f in forms_doc["forms"]}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HelpPageError("макет справки: форм нет в реестре длительности: %s" % ", ".join(map(str, missing)))
    return [by_id[i]["example"] for i in ids]


def render_help_page(doc, forms_doc=None):
    """Справка по макету help_page (D19 M2): примеры первым экраном, команды — сценариями. Без реестра форм
    (forms_doc=None) строки форм пропускаются. Позиция без примера в макете — в конце: «name — help_text» и её
    example с отступом (каждая строка с отступом — сообщение, которое бот примет). Ошибка макета — HelpPageError.
    С реестром форм (перенос на kernel-v2, ЭРРАТА D10 «А», §1А(б)): каждый example_dated позиций и пример каждой
    формы с expected_date обязаны быть строкой-примером справки — иначе макет испорчен (справки без способа записать
    прошлый день нет: CLI отказывает, рантайм печатает прежний перечень со строкой записи за прошлый день)."""
    ids = {c["id"] for c in doc["commands"]}
    page = doc["help_page"]
    if not isinstance(page, list):
        raise HelpPageError("макет справки: help_page — не список")
    out, shown, messages = [], set(), set()
    for item in page:
        if not isinstance(item, dict):
            raise HelpPageError("макет справки: элемент — не отображение: %r" % (item,))
        if "text" in item:
            out.append(_subst(doc, item["text"]))
        elif "ex" in item:
            if item["ex"] not in ids:
                raise HelpPageError("макет справки: позиции %r нет в реестре" % (item["ex"],))
            if not isinstance(item.get("line"), str) or not item["line"]:
                raise HelpPageError("макет справки: у примера %r нет line" % (item["ex"],))
            shown.add(item["ex"])
            messages.add(item["line"])
            line = "  " + item["line"]
            if item.get("note"):
                line += " — " + _subst(doc, item["note"])
            out.append(line)
        elif "forms_block" in item:
            if forms_doc:
                examples = _form_examples(forms_doc, item["forms_block"])
                messages.update(examples)
                out.extend("  " + e for e in examples)
                shown.add("free_text")
        elif "forms_line" in item:
            if forms_doc:
                out.append(_subst(doc, item.get("lead", "")) + " · ".join("«%s»" % e for e in _form_examples(forms_doc, item["forms_line"])))
        else:
            raise HelpPageError("макет справки: неизвестный элемент %r" % sorted(item))
    if forms_doc:
        dated = [c["example_dated"] for c in doc["commands"] if c.get("example_dated")] + \
                [f["example"] for f in forms_doc["forms"] if f.get("expected_date")]
        lost = [e for e in dated if e not in messages]
        if lost:
            raise HelpPageError("макет справки: нет примера записи за прошлый день из реестров: %s" % "; ".join(lost))
    rest = [c for c in doc["commands"] if c["id"] not in shown]
    if rest:
        out.append("")
        for c in rest:
            out.append("%s — %s" % (c["name"], c["help_text"]))
            out.append("  %s" % c["example"])
    return "\n".join(out) + "\n"


def render_help(doc, forms_doc=None, phrases_path=None, strict=False):
    """Ответ на справку. Сначала — проверка целой таблицы фраз (§1А(б): нарушение — RegistryViolation, отказ справки
    и в CLI, и в Ctx.full_help). С макетом help_page — по макету (D19 M2); испорченный макет: strict (CLI) — отказ,
    иначе (рантайм бота) — прежний перечень, чтобы поллер не останавливался на ошибке справки (D19 M2 R1-02)."""
    if forms_doc is None:
        forms_doc = _default_forms()
    check_reask(doc, forms_doc, phrases_path=phrases_path)          # §1А(б): порченый реестр фраз — отказ ДО выдачи справки (и Ctx.full_help)
    if doc.get("help_page"):
        try:
            return render_help_page(doc, forms_doc)
        except HelpPageError as e:
            if strict:
                raise SystemExit(str(e))
        except Exception:   # noqa: BLE001 — рантайм: любая порча макета не роняет цикл
            if strict:
                raise
    cmds = doc["commands"]
    out = ["Команды бота (позиций в реестре: %d):" % len(cmds)]
    for c in cmds:
        out.append("%s — %s" % (c["name"], c["help_text"]))
        out.append("  пример: %s" % c["example"])
    out.append(backdate_line(doc, forms_doc))
    out.append(forms_examples_line(forms_doc))
    out.append("Время в командах берётся из времени вашего сообщения; «записано» приходит после push.")
    out.append("Префикс подтверждения после находки секрета: %s" % doc["confirm_prefix"])
    return "\n".join(out) + "\n"


def render_short(doc, forms_doc=None, phrases_path=None):
    """Краткая справка (имя — что делает), без примеров. С T8 в ответ на непонятое НЕ отправляется
    (REQ-095: одна строка + указатель на справку); остаётся проекцией реестра для инструментов."""
    check_reask(doc, forms_doc, phrases_path=phrases_path)          # та же проверка целой таблицы фраз, что у полной справки
    cmds = doc["commands"]
    out = ["Команды:"]
    for c in cmds:
        out.append("%s — %s" % (c["name"], c["help_text"]))
    return "\n".join(out) + "\n"


def help_token(doc):
    """Токен позиции справки — из реестра (для однострочного переспроса T8), не литералом."""
    for c in doc["commands"]:
        if c["grammar"].endswith("#grammar-help"):
            return c["token"]
    raise SystemExit("реестр команд: позиции со справкой (grammar-help) нет")


def help_hint(doc):
    """Однострочный указатель на справку в каждом переспросе (T8, REQ-095): токен — из реестра."""
    return "%s — команды и примеры" % help_token(doc)


# ------------------------------------------------------------------ фразы переспроса (ЭРРАТА D10 «А»)
class PhraseError(ValueError):
    pass


def reason_key(reason):
    """Имя причины для поиска фразы: до первого «:» (`unknown_command:<токен>` → `unknown_command`)."""
    return str(reason).split(":", 1)[0]


def render_phrase(doc, forms_doc, template):
    """Подстановки фразы — из реестров; неизвестный вид, id или пустое значение — PhraseError (не молчаливый текст)."""
    by_id = {c["id"]: c for c in doc["commands"]}
    forms = {f["id"]: f for f in forms_doc["forms"]}

    def sub(m):
        kind, ident = m.group(1), m.group(2)
        if kind not in _PLACEHOLDER_KINDS:
            raise PhraseError("неизвестная подстановка {%s:%s}" % (kind, ident))
        src = forms if kind == "form" else by_id
        if ident not in src:
            raise PhraseError("подстановка {%s:%s}: такого id в реестре нет" % (kind, ident))
        val = src[ident].get("example" if kind == "form" else kind)
        if not isinstance(val, str) or not val:
            raise PhraseError("подстановка {%s:%s}: поле пусто" % (kind, ident))
        return val
    out = re.sub(r"\{([a-z_]+):([A-Za-z0-9_]+)\}", sub, str(template))
    if "{" in out or "}" in out:
        raise PhraseError("неразобранная подстановка во фразе: %r" % template)
    return out


# ------------------------------------------------------------------ замкнутость реестра фраз (R1-fix, класс B-01)
# Норма §1А(б): «отсутствие фразы для причины — отказ прогона справки». Инвариант, который держит ВАЛИДАТОР ниже, —
# на ЦЕЛОЙ таблице, до выдачи любой справки и до первого переспроса поллера:
#   (1) ключи узла reask_reasons РАВНЫ множеству REASK_PHRASE_OUTCOMES (исходов, чья причина говорится фразой);
#   (2) по каждому такому исходу множество имён реестра РАВНО множеству причин, которые порождает КОД бота, —
#       множество кода собирается из самого кода (AST модулей bot/*.py) на каждом прогоне, второго ручного списка
#       нет: нет потерянных (имя кода без фразы), нет лишних (фраза без производителя), подменённое имя = потеря + лишнее;
#   (3) каждая фраза и фраза-заглушка: строка, непустая, подстановки только допустимые и разрешимые по реестрам,
#       ОДНА строка без управляющих символов, без машинного имени (ни имени причины, ни `слово_слово`), и ответ
#       поллера «<фраза>. <указатель справки>» на фактических значениях подстановок ≤ SHORT_REPLY_MAX.
# Нарушение — RegistryViolation (rc 3, имя нарушения); собственная ошибка сборщика причин кода (неразрешимый источник
# причины, неоднозначный сток, модуль не разобран) — ReasonScanError (rc 4): отдельный фатальный исход, не «пропуск».
# Внешний независимый оракул — bot/tests/test_reask_reasons.py (свой AST-сбор, своё чтение реестра): общего кода
# с этим валидатором у него нет.

# Исходы, чья причина говорится человеку ФРАЗОЙ реестра: единственное место — его читают ответ поллера
# (poll.reply_text) и валидатор; ключи узла reask_reasons обязаны совпасть с ним множеством.
REASK_PHRASE_OUTCOMES = ("reask_unparsed", "reask_undo_not_found")
RC_REGISTRY_VIOLATION = 3
RC_SCAN_ERROR = 4
_BOT_DIR = os.path.dirname(_HERE)
_REASON_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_MACHINE_RE = re.compile(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+")


class RegistryViolation(ValueError):
    """Отказ: реестр фраз переспроса нарушает инвариант. violations — [(имя нарушения, где, что не так)]."""
    rc = RC_REGISTRY_VIOLATION

    def __init__(self, violations):
        self.violations = list(violations)
        ValueError.__init__(self, "; ".join("[%s] %s: %s" % v for v in self.violations))

    @property
    def names(self):
        return sorted(set(v[0] for v in self.violations))


class ReasonScanError(RegistryViolation):
    """Собственная ошибка сборщика причин кода — фатальный исход инструмента, а не пропуск причины."""
    rc = RC_SCAN_ERROR


def reask_reply(phrase, hint):
    """Форма ответа поллера на исходы REASK_PHRASE_OUTCOMES — одна на двоих: её печатает poll.reply_text, её длину
    меряет валидатор (бюджет считается по тому, что уходит человеку, а не по копии формулы). Без указателя справки
    (реестр без позиции справки — деградация Q-01) — только фраза с точкой."""
    return "%s. %s" % (phrase, hint) if hint else "%s." % phrase


# Встроенная резервная фраза переспроса — ПОСЛЕДНИЙ РУБЕЖ (Q-01, решение alex 2026-09-26): говорится, только если
# заглушка реестра сама не прошла проверку. Не замена реестра: при её употреблении поллер шлёт алярм с именем нарушения.
SAFE_REASK_FALLBACK = "не понял сообщение"


def bot_sources(bot_dir=None):
    """{имя модуля: байты} — ВСЕ модули бота (bot/*.py; у заказчика .workshop/bot/*.py), не список файлов."""
    d = bot_dir or _BOT_DIR
    out = {}
    for name in sorted(os.listdir(d)):
        if name.endswith(".py") and os.path.isfile(os.path.join(d, name)):
            with open(os.path.join(d, name), "rb") as fh:
                out[name] = fh.read()
    if not out:
        raise ReasonScanError([("reask.scan_error", d, "модулей бота нет — множество причин кода не собрать")])
    return out


class _ReasonScan(object):
    """Сборщик причин кода по ДАННЫМ, а не по списку мест. Причина — значение ключа "reason" словаря-литерала:
      * {"kind": K, "reason": V}               — разбор вида K (V — параметр функции ⇒ функция-сток вида K);
      * {"outcome": O, "reply": {"reason": V}} — решение машины состояний (O/V — параметры ⇒ функция-сток решения);
      * вызов с литералом исхода из REASK_PHRASE_OUTCOMES и словарём {"reply": {"reason": V}} — прямой ответ;
        V = X.get("reason") | X["reason"] — ПЕРЕСЫЛКА: вид берётся из охраны `if X["kind"] == K` вокруг вызова,
        и причины вида K (все его производители) приписываются этому исходу.
    Значение V разрешается до имён: литерал; `"имя:%s" % …`; f-строка с литеральной головой до «:»; условное
    выражение — обе ветви; имя переменной — ВСЕ её связывания в функции (_bindings: только `x = …` и распаковка
    `…, x, … = …`, любая иная форма — ошибка); распаковка — по ВСЕМ путям значения источника (_seqs: кортеж/список
    нужной длины, условное, локальное имя, вызов функции бота — КАЖДЫЙ её return), с фильтром по охране
    `if <соседняя переменная> ==/is <литерал>`; `str(e)` из `except T as e` — литералы `raise T(…)` (T, подклассы
    из кода бота и встроенные подклассы) в теле try и в функциях бота, вызываемых из него транзитивно; raise
    переменной/результата функции — ошибка. Запись причины мимо словаря-литерала (`x["reason"] = …`, reason=… в
    dict/update/setdefault) — ошибка. Вызов с литералом исхода-фразы, не являющийся ни стоком, ни ответом с причиной,
    — ошибка. Инвариант R2: ни одна форма не пропускается молча — либо учтена, либо ReasonScanError (rc 4)."""

    def __init__(self, sources):
        self.errors = []
        self.trees, self.mod_of, self.parent, self.defs, self.classes = {}, {}, {}, {}, {}
        for mod in sorted(sources):
            raw = sources[mod]
            try:
                self.trees[mod] = ast.parse(raw.decode("utf-8") if isinstance(raw, bytes) else raw, filename=mod)
            except (SyntaxError, UnicodeDecodeError, ValueError) as e:
                self.errors.append(("reask.scan_error", mod, "модуль не разобран: %s" % e))
        for mod, tree in self.trees.items():
            for n in ast.walk(tree):
                self.mod_of[n] = mod
                for c in ast.iter_child_nodes(n):
                    self.parent[c] = n
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.defs.setdefault(n.name, []).append(n)
                elif isinstance(n, ast.ClassDef):
                    self.classes.setdefault(n.name, set()).update(self._name_of(b) for b in n.bases)

    # ---------------------------------------------------------- мелочи
    def where(self, node):
        return "%s:%d" % (self.mod_of.get(node, "?"), getattr(node, "lineno", 0))

    def err(self, node, text):
        self.errors.append(("reask.scan_error", self.where(node), text))

    @staticmethod
    def _name_of(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    @staticmethod
    def _str(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def _fn(self, node):
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    @staticmethod
    def _params(fn):
        return [a.arg for a in fn.args.posonlyargs + fn.args.args] if fn is not None else []

    def _param_index(self, fn, expr):
        if isinstance(expr, ast.Name) and expr.id in self._params(fn):
            return self._params(fn).index(expr.id)
        return None

    def _arg(self, call, fdef, idx):
        """Выражение аргумента вызова call для параметра idx функции fdef (с учётом self/cls у метода)."""
        params = self._params(fdef)
        static = any(self._name_of(d) == "staticmethod" for d in fdef.decorator_list)
        shift = 1 if (isinstance(call.func, ast.Attribute) and not static and params and params[0] in ("self", "cls")) else 0
        pos = idx - shift
        if any(isinstance(a, ast.Starred) for a in call.args[:pos + 1]) or any(k.arg is None for k in call.keywords):
            return None
        if 0 <= pos < len(call.args):
            return call.args[pos]
        for k in call.keywords:
            if k.arg == params[idx]:
                return k.value
        return None

    @staticmethod
    def _dict(node):
        if not isinstance(node, ast.Dict):
            return None
        return {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}

    def _in_body_of(self, node, anc):
        """node лежит в ветке body (а не orelse) условного anc."""
        cur = node
        while cur in self.parent and self.parent[cur] is not anc:
            cur = self.parent[cur]
        return cur in getattr(anc, "body", [])

    def _guards(self, node, stop):
        """Условия охватывающих `if` (ветка body) от node вверх до функции stop: список Compare-конъюнктов."""
        out, cur = [], node
        while cur in self.parent and cur is not stop:
            anc = self.parent[cur]
            if isinstance(anc, ast.If) and cur in anc.body:
                tests = anc.test.values if isinstance(anc.test, ast.BoolOp) and isinstance(anc.test.op, ast.And) else [anc.test]
                out.extend(t for t in tests if isinstance(t, ast.Compare) and len(t.ops) == 1)
            cur = anc
        return out

    # ---------------------------------------------------------- разрешение значения причины
    def names(self, expr, site, depth=0):
        """Выражение причины → [(имя, где)]; неразрешимое — запись в errors и пустой список."""
        if depth > 8:
            self.err(site, "цепочка разрешения причины длиннее 8 — не разрешена")
            return []
        s = self._str(expr)
        if s is not None:
            return self._named(s, expr)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod) and self._str(expr.left) is not None:
            if ":" not in self._str(expr.left):
                self.err(expr, "динамическая причина без литерального имени до «:»: %r" % self._str(expr.left))
                return []
            return self._named(self._str(expr.left), expr)
        if isinstance(expr, ast.JoinedStr) and expr.values and self._str(expr.values[0]) is not None \
                and ":" in self._str(expr.values[0]):
            return self._named(self._str(expr.values[0]), expr)
        if isinstance(expr, ast.Call) and self._name_of(expr.func) == "str" and len(expr.args) == 1 \
                and isinstance(expr.args[0], ast.Name):
            return self._raised(expr.args[0].id, expr, depth)
        if isinstance(expr, ast.IfExp):
            return self.names(expr.body, site, depth + 1) + self.names(expr.orelse, site, depth + 1)
        if isinstance(expr, ast.Name):
            return self._assigned(expr, site, depth)
        self.err(expr, "неразрешимый источник причины: %s" % ast.dump(expr)[:160])
        return []

    def _named(self, literal, node):
        name = literal.split(":", 1)[0]
        if not _REASON_NAME_RE.match(name):
            self.err(node, "причина не машинное имя: %r" % literal)
            return []
        return [(name, self.where(node))]

    def _own(self, fn):
        """Узлы тела функции fn БЕЗ вложенных функций, лямбд и классов (их return/связывания — не её)."""
        nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        todo = [c for c in (fn.body if fn is not None else []) if not isinstance(c, nested)]
        out = []
        while todo:
            n = todo.pop()
            out.append(n)
            todo.extend(c for c in ast.iter_child_nodes(n) if not isinstance(c, nested))
        return out

    def _bindings(self, fn, var, at):
        """ВСЕ связывания имени var в функции fn → [("value", выражение) | ("unpack", цель, выражение)]. Любая форма,
        кроме `var = …` и `…, var, … = …` (параметр, for, with-as, except-as, :=, +=, аннотация, del, import,
        global/nonlocal, comprehension), — ошибка сборщика: связывание не пропускается молча."""
        if fn is None:
            self.err(at, "имя %r вне функции" % var)
            return []
        if var in self._params(fn) or var in (fn.args.vararg.arg if fn.args.vararg else None,
                                               fn.args.kwarg.arg if fn.args.kwarg else None) \
                or var in [a.arg for a in fn.args.kwonlyargs]:
            self.err(at, "имя %r — параметр функции %s (не сток): вызовы не разрешаются" % (var, fn.name))
            return []
        out = []
        for n in ast.walk(fn):
            if n is not fn and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == var \
                    and self._fn(n) is fn:
                self.err(n, "имя %r связано определением функции/класса — не разрешается" % var)
        for n in self._own(fn):
            if isinstance(n, (ast.Global, ast.Nonlocal)) and var in n.names:
                self.err(n, "имя %r объявлено global/nonlocal — не разрешается" % var)
            elif isinstance(n, ast.ExceptHandler) and n.name == var:
                self.err(n, "имя %r связано except-as — не источник значения" % var)
            elif isinstance(n, (ast.Import, ast.ImportFrom)) and any((a.asname or a.name.split(".")[0]) == var for a in n.names):
                self.err(n, "имя %r связано import — не разрешается" % var)
            elif isinstance(n, ast.Name) and n.id == var and isinstance(n.ctx, (ast.Store, ast.Del)):
                par = self.parent.get(n)
                if isinstance(par, ast.Assign) and n in par.targets:
                    out.append(("value", par.value))
                elif isinstance(par, (ast.Tuple, ast.List)) and isinstance(self.parent.get(par), ast.Assign) \
                        and par in self.parent[par].targets and not any(isinstance(e, ast.Starred) for e in par.elts):
                    out.append(("unpack", par, self.parent[par].value))
                else:
                    self.err(n, "имя %r связано формой %s — сборщик её не разрешает" % (var, type(par).__name__))
        if not out and not any(e[1] == self.where(at) for e in self.errors):
            self.err(at, "у имени %r нет присваивания в %s" % (var, fn.name))
        return out

    def _assigned(self, name_node, site, depth):
        out = []
        for b in self._bindings(self._fn(name_node), name_node.id, name_node):
            if b[0] == "value":
                out += self.names(b[1], b[1], depth + 1)
            else:
                out += self._unpacked(b[1], name_node.id, b[2], site, depth)
        return out

    def _seqs(self, expr, n, depth):
        """Выражение, которое распаковывается в n имён → [список из n выражений-элементов] по ВСЕМ путям значения:
        кортеж/список-литерал длины n; условное выражение — обе ветви; имя — все его связывания в функции; вызов
        функции бота — ВСЕ её return. Любая иная форма (другая длина, звёздочка, None, генератор, чужая функция,
        неизвестная форма) — ошибка сборщика, а не пропуск."""
        if depth > 12:
            self.err(expr, "цепочка источника распаковки длиннее 12 — не разрешена")
            return []
        if isinstance(expr, (ast.Tuple, ast.List)):
            if any(isinstance(e, ast.Starred) for e in expr.elts) or len(expr.elts) != n:
                self.err(expr, "источник распаковки: последовательность длины %d/со звёздочкой вместо %d" % (len(expr.elts), n))
                return []
            return [list(expr.elts)]
        if isinstance(expr, ast.IfExp):
            return self._seqs(expr.body, n, depth + 1) + self._seqs(expr.orelse, n, depth + 1)
        if isinstance(expr, ast.Name):
            out = []
            for b in self._bindings(self._fn(expr), expr.id, expr):
                if b[0] == "value":
                    out += self._seqs(b[1], n, depth + 1)
                else:
                    self.err(b[1], "источник распаковки %r сам получен распаковкой — не разрешается" % expr.id)
            return out
        if isinstance(expr, ast.Call):
            callee = self._name_of(expr.func)
            if callee not in self.defs:
                self.err(expr, "источник распаковки — вызов %r вне кода бота" % callee)
                return []
            out = []
            for fdef in self.defs[callee]:
                own = self._own(fdef)
                if any(isinstance(x, (ast.Yield, ast.YieldFrom)) for x in own):
                    self.err(fdef, "источник распаковки %s — генератор" % callee)
                    continue
                rets = [x for x in own if isinstance(x, ast.Return)]
                if not rets:
                    self.err(fdef, "у источника распаковки %s нет return" % callee)
                for r in rets:
                    if r.value is None:
                        self.err(r, "return без значения в источнике распаковки %s" % callee)
                    else:
                        out += self._seqs(r.value, n, depth + 1)
            return out
        self.err(expr, "источник распаковки неразрешим: %s" % ast.dump(expr)[:160])
        return []

    def _unpacked(self, tgt, var, value, site, depth):
        if any(isinstance(e, ast.Starred) for e in tgt.elts):
            self.err(tgt, "распаковка причины %r со звёздочкой — не разрешается" % var)
            return []
        names = [e.id if isinstance(e, ast.Name) else None for e in tgt.elts]
        idx = names.index(var)
        before = len(self.errors)
        seqs = self._seqs(value, len(names), depth + 1)
        if len(self.errors) > before:
            return []
        # охрана вокруг места использования: `if <соседняя переменная распаковки> ==/is/!=/is not <литерал>`
        for g in self._guards(site, self._fn(site)):
            if isinstance(g.left, ast.Name) and g.left.id in names and g.left.id != var and isinstance(g.comparators[0], ast.Constant):
                k, c, op = names.index(g.left.id), g.comparators[0].value, g.ops[0]
                if isinstance(op, (ast.Eq, ast.Is)):
                    seqs = [e for e in seqs if not isinstance(e[k], ast.Constant) or e[k].value == c]
                elif isinstance(op, (ast.NotEq, ast.IsNot)):
                    seqs = [e for e in seqs if not isinstance(e[k], ast.Constant) or e[k].value != c]
        out = []
        for elts in seqs:
            v = elts[idx]
            if isinstance(v, ast.Constant) and v.value is None:
                continue                         # на этом пути причины нет (успех)
            out += self.names(v, v, depth + 1)
        if not out:
            self.err(value, "у источника распаковки нет причин на позиции %d (%s)" % (idx, var))
        return out

    def _is_exc_class(self, name):
        b = getattr(builtins, name or "", None)
        return name in self.classes or (isinstance(b, type) and issubclass(b, BaseException))

    def _caught_by(self, name, caught):
        """Тип name пойман одним из caught: совпадение, подкласс из кода бота (цепочка баз) или встроенный подкласс."""
        seen, todo = set(), [name]
        while todo:
            n = todo.pop()
            if n in caught:
                return True
            if n in seen:
                continue
            seen.add(n)
            b = getattr(builtins, n or "", None)
            if isinstance(b, type) and any(isinstance(getattr(builtins, c or "", None), type) and issubclass(b, getattr(builtins, c)) for c in caught):
                return True
            todo.extend(self.classes.get(n, ()))
        return False

    def _raised(self, var, site, depth):
        handler = site
        while handler in self.parent and not (isinstance(handler, ast.ExceptHandler) and handler.name == var):
            handler = self.parent[handler]
        if not isinstance(handler, ast.ExceptHandler) or handler.type is None:
            self.err(site, "str(%s): нет охватывающего `except <тип> as %s`" % (var, var))
            return []
        types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        caught = set(self._name_of(t) for t in types)
        tr = self.parent[handler]
        todo, seen, out = [ast.Module(body=tr.body, type_ignores=[])], set(), []
        while todo:
            node = todo.pop()
            for n in ast.walk(node):
                if isinstance(n, ast.Raise) and n.exc is not None:
                    exc = n.exc
                    name = self._name_of(exc.func) if isinstance(exc, ast.Call) else self._name_of(exc)
                    if not self._is_exc_class(name):
                        # raise переменной или результата функции — тип не виден: пойман ли он, сборщик не знает
                        self.err(n, "raise %s: тип исключения не разрешается статически" % (name or ast.dump(exc)[:60]))
                    elif not self._caught_by(name, caught):
                        continue
                    elif not isinstance(exc, ast.Call) or not exc.args:
                        self.err(n, "raise %s без причины" % name)
                    else:
                        out += self.names(exc.args[0], n, depth + 1)
                elif isinstance(n, ast.Call) and self._name_of(n.func) in self.defs:
                    for fdef in self.defs[self._name_of(n.func)]:
                        if fdef not in seen:
                            seen.add(fdef); todo.append(fdef)
        if not out:
            self.err(site, "str(%s): в теле try и вызываемых функциях бота нет raise пойманного типа" % var)
        return out

    # ---------------------------------------------------------- сбор
    def run(self):
        """→ {исход: {имя: [где]}} по REASK_PHRASE_OUTCOMES; ошибки сборщика — ReasonScanError."""
        out = {o: {} for o in REASK_PHRASE_OUTCOMES}

        def add(outcome, pairs):
            for name, where in pairs:
                out[outcome].setdefault(name, []).append(where)
        kind_sinks, decision_sinks, kind_direct = {}, {}, []
        for tree in self.trees.values():
            for d in ast.walk(tree):
                keys = self._dict(d)
                if keys is None:
                    continue
                fn = self._fn(d)
                if "kind" in keys and "reason" in keys and self._str(keys["kind"]) is not None:
                    p = self._param_index(fn, keys["reason"])
                    if p is not None:
                        kind_sinks.setdefault(fn.name, []).append((fn, self._str(keys["kind"]), p))
                    else:
                        kind_direct.append((self._str(keys["kind"]), keys["reason"], d))
                reply = self._dict(keys.get("reply"))
                if "outcome" in keys:
                    o_const = self._str(keys["outcome"])
                    po = self._param_index(fn, keys["outcome"])
                    if reply is None or "reason" not in reply:
                        if o_const in REASK_PHRASE_OUTCOMES:
                            self.err(d, "решение исхода %s без литерального {'reply': {'reason': …}}" % o_const)
                        continue
                    pv = self._param_index(fn, reply["reason"])
                    if po is not None or pv is not None:
                        decision_sinks.setdefault(fn.name, []).append((fn, po, keys["outcome"], pv, reply["reason"]))
                    elif o_const in REASK_PHRASE_OUTCOMES:
                        add(o_const, self.names(reply["reason"], d))
                    elif o_const is None:
                        self.err(d, "исход решения не литерал и не параметр")
        for sinks in (kind_sinks, decision_sinks):
            for name, rows in sinks.items():
                if len(self.defs.get(name, [])) != len(set(r[0] for r in rows)):
                    self.err(rows[0][0], "сток %s неоднозначен: одноимённые функции без того же стока" % name)
        # формы записи причины МИМО словаря-литерала: сборщик их не разрешает — ошибка, а не молчаливый пропуск производителя
        for tree in self.trees.values():
            for n in ast.walk(tree):
                if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and self._str(n.slice) == "reason":
                    self.err(n, "причина записывается присваиванием по ключу [\"reason\"] — форма не разрешается")
                elif isinstance(n, ast.Call) and any(k.arg == "reason" for k in n.keywords) \
                        and self._name_of(n.func) in ("dict", "update", "setdefault"):
                    self.err(n, "причина передаётся reason=… в %s — форма не разрешается" % self._name_of(n.func))
                elif isinstance(n, ast.Call) and self._name_of(n.func) in ("setdefault", "__setitem__") and n.args \
                        and self._str(n.args[0]) == "reason":
                    self.err(n, "причина записывается %s(\"reason\", …) — форма не разрешается" % self._name_of(n.func))
        kinds, forwards = {}, []
        for tree in self.trees.values():
            for c in ast.walk(tree):
                if not isinstance(c, ast.Call):
                    continue
                callee = self._name_of(c.func)
                if callee in kind_sinks:
                    for fdef, kind, p in kind_sinks[callee]:
                        a = self._arg(c, fdef, p)
                        if a is None:
                            self.err(c, "вызов стока %s: аргумент причины не найден" % callee)
                        else:
                            kinds.setdefault(kind, []).extend(self.names(a, c))
                    continue
                if callee in decision_sinks:
                    for fdef, po, o_expr, pv, v_expr in decision_sinks[callee]:
                        oe = self._arg(c, fdef, po) if po is not None else o_expr
                        o = self._str(oe) if oe is not None else None
                        if o is None:
                            self.err(c, "вызов стока %s: исход не литерал" % callee)
                            continue
                        if o not in REASK_PHRASE_OUTCOMES:
                            continue
                        ve = self._arg(c, fdef, pv) if pv is not None else v_expr
                        if ve is None:
                            self.err(c, "вызов стока %s: аргумент причины не найден" % callee)
                        else:
                            add(o, self.names(ve, c))
                    continue
                args = list(c.args) + [k.value for k in c.keywords]
                phrase_outcomes = [self._str(a) for a in args if self._str(a) in REASK_PHRASE_OUTCOMES]
                if not phrase_outcomes:
                    continue
                if len(set(phrase_outcomes)) != 1:
                    self.err(c, "в вызове два разных исхода-фразы")
                    continue
                o = phrase_outcomes[0]
                reasons = [self._dict(r).get("reason") for r in (self._dict(a).get("reply") for a in args if self._dict(a) is not None)
                           if self._dict(r) is not None and "reason" in self._dict(r)]
                if len(reasons) != 1:
                    self.err(c, "вызов с исходом %s без единственного литерального {'reply': {'reason': …}}" % o)
                    continue
                v = reasons[0]
                fwd = None
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "get" \
                        and v.args and self._str(v.args[0]) == "reason" and isinstance(v.func.value, ast.Name):
                    fwd = v.func.value.id
                elif isinstance(v, ast.Subscript) and self._str(getattr(v, "slice", None)) == "reason" and isinstance(v.value, ast.Name):
                    fwd = v.value.id
                if fwd is None:
                    add(o, self.names(v, c))
                    continue
                guard = self._kind_guard(c, fwd)
                if not guard:
                    self.err(c, "пересылка причины %s без охраны `if %s[\"kind\"] == …`" % (fwd, fwd))
                forwards.append((guard, o, c))
        for guard, o, c in forwards:
            for kind in sorted(guard):
                pairs = list(kinds.get(kind, []))
                for k, v, d in kind_direct:
                    if k == kind:
                        pairs += self.names(v, d)
                if not pairs:
                    self.err(c, "пересылаемый вид %r не имеет ни одного производителя причины" % kind)
                add(o, pairs)
        for o in REASK_PHRASE_OUTCOMES:
            if not out[o] and not self.errors:
                self.errors.append(("reask.scan_error", "bot/*.py", "сборщик не нашёл ни одной причины исхода %s" % o))
        if self.errors:
            raise ReasonScanError(self.errors)
        return out

    def _kind_guard(self, node, var):
        """Виды из ближайшей охраны `if var["kind"] == K` / `var.get("kind") in (K, …)` (ветка body)."""
        for g in self._guards(node, self._fn(node)):
            left = g.left
            is_kind = (isinstance(left, ast.Subscript) and isinstance(left.value, ast.Name) and left.value.id == var
                       and self._str(getattr(left, "slice", None)) == "kind") or \
                      (isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute) and left.func.attr == "get"
                       and isinstance(left.func.value, ast.Name) and left.func.value.id == var and left.args
                       and self._str(left.args[0]) == "kind")
            if not is_kind:
                continue
            op, rhs = g.ops[0], g.comparators[0]
            if isinstance(op, ast.Eq) and self._str(rhs) is not None:
                return {self._str(rhs)}
            if isinstance(op, ast.In) and isinstance(rhs, (ast.Tuple, ast.List, ast.Set)) and all(self._str(e) is not None for e in rhs.elts):
                return set(self._str(e) for e in rhs.elts)
        return set()


_SCAN_CACHE = {}
_TABLE_CACHE = {}


def code_reasons(sources=None):
    """{исход: {имя причины: [где порождается]}} — множество причин КОДА (авторитетный источник замкнутости)."""
    src = sources if sources is not None else bot_sources()
    key = hashlib.sha256(b"\0".join(k.encode("utf-8") + b"\0" + (v if isinstance(v, bytes) else v.encode("utf-8"))
                                    for k, v in sorted(src.items()))).hexdigest()
    if key not in _SCAN_CACHE:
        _SCAN_CACHE[key] = _ReasonScan(src).run()
    return _SCAN_CACHE[key]


class ReaskTable(object):
    """Проверенная целиком таблица фраз: только её читают справка и поллер."""

    def __init__(self, phrases, fallback, hint):
        self.phrases, self.fallback, self.hint = phrases, fallback, hint
        self.builtin_fallback = False      # True — заглушка реестра не прошла проверку, говорит SAFE_REASK_FALLBACK

    def phrase(self, outcome, reason):
        """→ (фраза, найдена ли). Не найдена — только для причины, которой нет в замкнутом множестве кода (её породил
        путь, не видимый сборщику): проверенная заглушка, вызывающий обязан пометить это в трассе и журнале."""
        p = (self.phrases.get(outcome) or {}).get(reason_key(reason))
        return (p, True) if p else (self.fallback, False)

    def rows(self):
        return [(o, n, p, len(reask_reply(p, self.hint))) for o, t in self.phrases.items() for n, p in t.items()]


def _phrase_violations(doc, forms_doc, label, tpl, hint, machine_names):
    """Проверка одной фразы (фразы причины либо заглушки) → (фраза | None, [нарушения])."""
    if not isinstance(tpl, str):
        return None, [("reask.phrase_not_string", label, "фраза не строка: %r" % (tpl,))]
    if not tpl.strip():
        return None, [("reask.phrase_empty", label, "фраза пуста")]
    try:
        phrase = render_phrase(doc, forms_doc, tpl)
    except PhraseError as e:
        return None, [("reask.placeholder", label, str(e))]
    bad = []
    if len(phrase.splitlines()) != 1 or any(unicodedata.category(ch) == "Cc" for ch in phrase):
        bad.append(("reask.not_one_line", label, "фраза не одна строка либо с управляющим символом: %r" % phrase))
    hits = sorted(set(m.group(0) for m in _MACHINE_RE.finditer(phrase)) |
                  set(n for n in machine_names if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(n), phrase)))
    if hits:
        bad.append(("reask.machine_name", label, "машинное имя во фразе: %s" % ", ".join(hits)))
    n = len(reask_reply(phrase, hint))
    if n > SHORT_REPLY_MAX:
        bad.append(("reask.budget", label, "ответ %d символов > %d" % (n, SHORT_REPLY_MAX)))
    return phrase, bad


def _evaluate_reask(doc, forms_doc, sources, pdoc, load_bad):
    """Одна проверка ЦЕЛОЙ таблицы → (ReaskTable из прошедших проверку фраз, [нарушения], ошибка сборщика ли).
    Таблица строится и при нарушениях: в неё входят только фразы, прошедшие проверку формы, и заглушка — реестровая,
    если прошла ту же проверку, иначе встроенная SAFE_REASK_FALLBACK (последний рубеж, Q-01). Строгий путь (справка)
    при любом нарушении отказывает; поллер пользуется таблицей в деградации (degraded_reask)."""
    bad, scan_failed = list(load_bad), False
    for k in _PHRASE_KEYS:
        if k in doc:
            bad.append(("reask.phrases_in_commands", "commands.%s" % k, "узел фраз в реестре команд — место ему в kit/reask-phrases.yaml"))
    try:
        code = code_reasons(sources)
    except ReasonScanError as e:
        code, scan_failed = None, True
        bad += e.violations
    reasons = pdoc.get("reask_reasons")
    try:
        hint = help_hint(doc)
    except SystemExit as e:
        hint = ""
        bad.append(("reask.hint_missing", "commands", str(e)))
    if not isinstance(reasons, dict) or not reasons:
        if not load_bad:
            bad.append(("reask.node_missing", "reask_reasons", "узла нет либо он пуст — переспросу нечем объяснить причину"))
        reasons = {}
    known = set()
    for c in doc["commands"]:
        known.update(c.get("outcomes") or [])
    for o in sorted(set(reasons) - set(REASK_PHRASE_OUTCOMES)):
        bad.append(("reask.outcome_extra", "reask_reasons.%s" % o, "исход не из REASK_PHRASE_OUTCOMES %s%s" % (
            list(REASK_PHRASE_OUTCOMES), "" if o in known else " и не из перечня исходов позиций реестра")))
    for o in REASK_PHRASE_OUTCOMES:
        if reasons and o not in reasons:
            bad.append(("reask.outcome_missing", "reask_reasons.%s" % o, "исхода-фразы нет в узле"))
        elif o in reasons and o not in known:
            bad.append(("reask.outcome_unknown", "reask_reasons.%s" % o, "исход не из перечня исходов позиций реестра"))
    machine = set(REASK_PHRASE_OUTCOMES)
    if code is not None:
        machine |= set(n for t in code.values() for n in t)
    for t in reasons.values():
        if isinstance(t, dict):
            machine.update(str(n) for n in t)
    phrases = {}
    for o in REASK_PHRASE_OUTCOMES:
        table = reasons.get(o)
        phrases[o] = {}
        if o in reasons and not isinstance(table, dict):
            bad.append(("reask.table_not_mapping", "reask_reasons.%s" % o, "не отображение имя → фраза"))
            continue
        table = table or {}
        if code is not None and not load_bad:     # файл фраз не прочитан — имена не сравниваются, корень уже назван
            for name in sorted(set(code[o]) - set(table)):
                bad.append(("reask.reason_lost", "reask_reasons.%s.%s" % (o, name),
                            "имя причины кода без фразы (порождается: %s)" % ", ".join(code[o][name][:3])))
            for name in sorted(set(table) - set(code[o])):
                bad.append(("reask.reason_extra", "reask_reasons.%s.%s" % (o, name), "фраза без производителя в коде"))
        for name, tpl in table.items():
            phrase, v = _phrase_violations(doc, forms_doc, "reask_reasons.%s.%s" % (o, name), tpl, hint, machine)
            bad += v
            if phrase is not None and not v:
                phrases[o][name] = phrase
    fb, v = _phrase_violations(doc, forms_doc, "reask_reason_fallback", pdoc.get("reask_reason_fallback"), hint, machine)
    if not load_bad:           # файл не прочитан — заглушки в нём нет, это уже названо нарушением загрузки
        bad += [(n.replace("reask.", "reask.fallback_", 1), w, t) for n, w, t in v]
    table = ReaskTable(phrases, fb, hint)
    if fb is None or v:
        table.fallback, table.builtin_fallback = SAFE_REASK_FALLBACK, True
    return table, bad, scan_failed


def _reask_key(doc, forms_doc, sources, pdoc, load_bad):
    src = sources if sources is not None else bot_sources()
    return (repr(pdoc.get("reask_reasons")), repr(pdoc.get("reask_reason_fallback")), repr(load_bad),
            repr([doc.get(k) for k in _PHRASE_KEYS]),
            repr([(c.get("id"), c.get("token"), c.get("example"), c.get("example_dated"), c.get("grammar"), c.get("outcomes"))
                  for c in doc["commands"]]),
            repr([(f.get("id"), f.get("example")) for f in forms_doc["forms"]]),
            hashlib.sha256(repr(sorted(src.items())).encode("utf-8")).hexdigest()), src


def degraded_reask(doc, forms_doc=None, sources=None, phrases_path=None):
    """→ (ReaskTable, RegistryViolation | None). Путь ПОЛЛЕРА (Q-01, решение alex 2026-09-26: приём часов изолирован
    от реестра фраз): НИКОГДА не отказывает — ни на семантической, ни на синтаксической порче фраз (реестр фраз
    читается отдельно, load_phrases), ни на собственной ошибке оценки (reask.internal); при нарушении таблица содержит
    только проверенные фразы и проверенную заглушку (либо встроенную), нарушение возвращается вызывающему — для
    алярма и пометки в трассе."""
    try:
        if forms_doc is None:
            forms_doc = _default_forms()
        pdoc, load_bad = load_phrases(phrases_path)
        key, src = _reask_key(doc, forms_doc, sources, pdoc, load_bad)
        if key not in _TABLE_CACHE:
            _TABLE_CACHE[key] = _evaluate_reask(doc, forms_doc, src, pdoc, load_bad)
        table, bad, scan_failed = _TABLE_CACHE[key]
    except Exception as e:           # noqa: BLE001 — последний рубеж изоляции: ошибка оценки фраз не останавливает приём
        try:
            hint = help_hint(doc)
        except BaseException:        # noqa: BLE001 — реестр без позиции справки: ответ без указателя
            hint = ""
        table = ReaskTable({o: {} for o in REASK_PHRASE_OUTCOMES}, SAFE_REASK_FALLBACK, hint)
        table.builtin_fallback = True
        return table, RegistryViolation([("reask.internal", "build_help", "%s: %s" % (type(e).__name__, e))])
    if not bad:
        return table, None
    return table, (ReasonScanError(bad) if scan_failed else RegistryViolation(bad))


def check_reask(doc, forms_doc=None, sources=None, phrases_path=None):
    """ЕДИНЫЙ продуктовый валидатор ЦЕЛОЙ таблицы reask_reasons + reask_reason_fallback реестра kit/reask-phrases.yaml
    (инвариант — в шапке раздела) → ReaskTable; нарушение — RegistryViolation (все нарушения разом, с именами, включая
    нечитаемый файл фраз), ошибка сборщика — ReasonScanError. СТРОГИЙ путь: вызывается ДО выдачи справки всеми
    проекциями (render_help, render_short, render_commands_block → render_guide), CLI и Ctx.full_help. Поллер для
    переспроса берёт degraded_reask (та же проверка, без отказа)."""
    table, violation = degraded_reask(doc, forms_doc, sources, phrases_path)
    if violation is not None:
        raise violation
    return table


def reask_phrase(doc, forms_doc, outcome, reason, phrases_path=None):
    """→ (фраза, найдена ли) по ПРОВЕРЕННОЙ таблице. Порченый реестр — RegistryViolation (не молчаливая заглушка);
    пустая фраза найденной не бывает (валидатор её не пропускает)."""
    return check_reask(doc, forms_doc, phrases_path=phrases_path).phrase(outcome, reason)


def reask_table(doc, forms_doc, phrases_path=None):
    """[(исход, имя, фраза, длина ответа)] проверенной таблицы — подкоманда reasons."""
    return check_reask(doc, forms_doc, phrases_path=phrases_path).rows()


def render_commands_block(doc, forms_doc=None, phrases_path=None):
    check_reask(doc, forms_doc, phrases_path=phrases_path)          # блок инструкции (и render_guide) — после проверки целой таблицы фраз
    cmds = doc["commands"]
    out = ["Перечень команд (сгенерировано из реестра kit/commands.yaml; позиций: %d)." % len(cmds), ""]
    if forms_doc:
        out.append(forms_examples_line(forms_doc))
        out.append("")
        out.append(backdate_line(doc, forms_doc) + ".")
        out.append("")
    for c in cmds:
        out.append("### `%s`" % c["name"])
        out.append("")
        out.append("*%s.* Зависит от момента отправки: %s. Кнопкой исполняется сразу: %s." % (
            c["help_text"], "да" if c["time_bearing"] else "нет", "да" if c["callback_allowed"] else "нет (кнопка лишь подставляет команду)"))
        out.append("")
        body = c["guide_text"].rstrip("\n")
        out.append(body)
        out.append("")
        out.append("Пример: `%s`" % c["example"])
        out.append("")
        if c.get("example_dated"):
            out.append("Пример за прошлый день: `%s`" % c["example_dated"])
            out.append("")
    out.append("Префикс подтверждения после находки секрета: `%s`." % doc["confirm_prefix"])
    return "\n".join(out) + "\n"


def render_steps_block(doc):
    steps = doc["steps"]
    secrets = doc.get("secrets") or []
    out = ["Ручные шаги заказчика (сгенерировано из реестра kit/install-steps.yaml; объявленное число шагов N = %d)." % len(steps), ""]
    if secrets:
        out.append("Секреты CI, которые кладёт заказчик:")
        for s in secrets:
            flag = "обязателен" if s.get("required") else "необязателен"
            if not s.get("required") and s.get("required_when") == "storage_configured":
                flag += " (обязателен, если хранилище вложений настроено)"
            alt = (" (альтернатива: `%s`)" % s["alternative"]) if s.get("alternative") else ""
            out.append("- `%s` — %s; %s%s" % (s["name"], s["purpose"], flag, alt))
        out.append("")
    for n, s in enumerate(steps, 1):
        label = (doc.get("when_values") or {}).get(s["when"], {}).get("label")
        when = " *(%s)*" % label if label else ""
        out.append("%d. **%s**%s" % (n, s["title"], when))
        out.append("")
        out.append("   " + s["guide"].rstrip("\n").replace("\n", "\n   "))
        out.append("")
        req = s.get("required_secrets") or []
        if req:
            out.append("   Секреты этого шага: %s" % ", ".join("`%s`" % r for r in req))
            out.append("")
        out.append("   Чем проверяется: %s" % s["verified_by"])
        out.append("")
    return "\n".join(out) + "\n"


MARK_STORAGE_SECRETS_START = "<!-- generated:storage-secrets:start -->"
MARK_STORAGE_SECRETS_END = "<!-- generated:storage-secrets:end -->"
MARK_STORAGE_CREDS_START = "<!-- generated:storage-credentials:start -->"
MARK_STORAGE_CREDS_END = "<!-- generated:storage-credentials:end -->"


def _storage_secrets(doc):
    """Секреты хранилища вложений из реестра (поле storage_credential) в порядке реестра — единственный адрес имён."""
    out = [s for s in doc.get("secrets") or [] if s.get("storage_credential")]
    if not out:
        raise SystemExit("реестр шагов: секретов хранилища (storage_credential) нет — инструкции нечего печатать")
    return out


def render_storage_secrets_block(doc):
    """Блок инструкции хранилища (bot/kit/docs/storage-setup.ru.md): имена секретов ключа писателя из реестра."""
    out = ["Имена секретов ключа писателя (сгенерировано из реестра kit/install-steps.yaml):", ""]
    for s in _storage_secrets(doc):
        out.append("- `%s` — %s" % (s["name"], s["purpose"]))
    return "\n".join(out) + "\n"


def render_storage_credentials_block(doc):
    """Строки, которые storage-init дописывает в блок storage: credentials — ИМЕНА из реестра (значений нет)."""
    out = ["```yaml", "  credentials:"]
    for s in _storage_secrets(doc):
        out.append("    %s: %s" % (s["storage_credential"], s["name"]))
    out.append("```")
    return "\n".join(out) + "\n"


def render_storage_guide(guide_path, steps_doc):
    with open(guide_path, "rb") as fh:
        text = fh.read().decode("utf-8")
    text = replace_between(text, MARK_STORAGE_SECRETS_START, MARK_STORAGE_SECRETS_END, render_storage_secrets_block(steps_doc))
    text = replace_between(text, MARK_STORAGE_CREDS_START, MARK_STORAGE_CREDS_END, render_storage_credentials_block(steps_doc))
    return text


def replace_between(text, start, end, block, inline=False):
    a = text.count(start)
    b = text.count(end)
    if a != 1 or b != 1:
        raise SystemExit("маркеры %s/%s: ожидалось по одному, найдено %d/%d" % (start, end, a, b))
    i = text.index(start) + len(start)
    j = text.index(end)
    if j < i:
        raise SystemExit("маркер конца раньше маркера начала: %s" % end)
    return text[:i] + ("" if inline else "\n") + block + text[j:]


def correction_example(forms_doc):
    """Первый пример формы исправления из реестра — единственный пример исхода 6 в прозе инструкции (раунд 2, W4)."""
    ex = (forms_doc or {}).get("correction_examples") or []
    if not ex:
        raise SystemExit("реестр форм: correction_examples пуст — инструкции нечего печатать")
    return "«%s»" % ex[0]


def dated_free_text_example(forms_doc):
    """Первый пример формы «дата + длительность» (expected_date) — пример свободной записи за прошлый день в прозе
    инструкции (ЭРРАТА D10 «А», А4); литерала в прозе нет."""
    ex = [f["example"] for f in (forms_doc or {}).get("forms") or [] if f.get("expected_date")]
    if not ex:
        raise SystemExit("реестр форм: нет формы с expected_date — инструкции нечего печатать")
    return "«%s»" % ex[0]


def render_guide(guide_path, cmd_doc, steps_doc, forms_doc=None, phrases_path=None):
    if forms_doc is None:
        forms_doc = load_forms(os.path.join(_HERE, "duration-forms.yaml"))
    with open(guide_path, "rb") as fh:
        text = fh.read().decode("utf-8")
    text = replace_between(text, MARK_COMMANDS_START, MARK_COMMANDS_END, render_commands_block(cmd_doc, forms_doc, phrases_path))
    text = replace_between(text, MARK_STEPS_START, MARK_STEPS_END, render_steps_block(steps_doc))
    text = replace_between(text, MARK_CORR_START, MARK_CORR_END, correction_example(forms_doc), inline=True)
    text = replace_between(text, MARK_DATED_START, MARK_DATED_END, dated_free_text_example(forms_doc), inline=True)
    return text


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_help.py")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("help", "short", "commands-block", "count-steps", "steps-block", "render", "forms-line", "reasons",
                 "render-storage"):
        p = sub.add_parser(name)
        p.add_argument("--commands", default=os.path.join(_HERE, "commands.yaml"))
        p.add_argument("--steps", default=os.path.join(_HERE, "install-steps.yaml"))
        p.add_argument("--forms", default=os.path.join(_HERE, "duration-forms.yaml"))
        p.add_argument("--phrases", default=PHRASES_PATH)
        if name in ("render", "render-storage"):
            p.add_argument("--guide", required=True)
            p.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    try:
        return _dispatch(args)
    except RegistryViolation as e:
        # отказ прогона — ИМЕНОВАННЫЙ (имя нарушения, где, что), без трассировки; rc 3 — реестр, rc 4 — сборщик
        sys.stderr.write("build_help: ОТКАЗ ПРОГОНА СПРАВКИ — %s, нарушений %d:\n" % (
            "собственная ошибка сборщика причин кода" if isinstance(e, ReasonScanError) else "реестр фраз переспроса нарушен",
            len(e.violations)))
        for name, where, what in e.violations:
            sys.stderr.write("  [%s] %s: %s\n" % (name, where, what))
        return e.rc
    except yamlmini.YamlError as e:
        sys.stderr.write("build_help: ОТКАЗ ПРОГОНА — [registry.yaml] реестр не читается: %s\n" % e)
        return 1


def _dispatch(args):
    if args.cmd in ("help", "short", "commands-block", "render", "reasons"):
        # прогон справки проверяет ЦЕЛУЮ таблицу фраз переспроса (§1А(б), R1-fix): порча — именованный отказ, а не справка;
        # те же проекции проверяют её и сами (check_reask внутри render_*), так что обходного пути нет
        rows = reask_table(load_commands(args.commands), load_forms(args.forms), args.phrases)
        backdate_examples(load_commands(args.commands), load_forms(args.forms))   # Б1/Б2: оба примера обязательны
    if args.cmd == "reasons":
        for outcome, name, phrase, n in rows:
            sys.stdout.write("%s\t%s\t%d\t%s\n" % (outcome, name, n, phrase))
    elif args.cmd == "help":
        sys.stdout.write(render_help(load_commands(args.commands), load_forms(args.forms), args.phrases, strict=True))
    elif args.cmd == "short":
        sys.stdout.write(render_short(load_commands(args.commands), load_forms(args.forms), args.phrases))
    elif args.cmd == "forms-line":
        sys.stdout.write(forms_examples_line(load_forms(args.forms)) + "\n")
    elif args.cmd == "commands-block":
        sys.stdout.write(render_commands_block(load_commands(args.commands), load_forms(args.forms), args.phrases))
    elif args.cmd == "steps-block":
        sys.stdout.write(render_steps_block(load_steps(args.steps)))
    elif args.cmd == "count-steps":
        sys.stdout.write("%d\n" % len(load_steps(args.steps)["steps"]))
    elif args.cmd == "render-storage":
        text = render_storage_guide(args.guide, load_steps(args.steps))
        if args.write:
            with open(args.guide, "wb") as fh:
                fh.write(text.encode("utf-8"))
        else:
            sys.stdout.write(text)
    elif args.cmd == "render":
        text = render_guide(args.guide, load_commands(args.commands), load_steps(args.steps), load_forms(args.forms), args.phrases)
        if args.write:
            with open(args.guide, "wb") as fh:
                fh.write(text.encode("utf-8"))
        else:
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
