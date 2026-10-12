#!/usr/bin/env python3
"""build_help.py — ЧИСТАЯ ПРОЕКЦИЯ реестров в тексты. Владелец — T1 (D09 §1А, §1Д(г)).

Входы (читаются на каждом прогоне, копий нет):
  kit/commands.yaml      — закрытый реестр команд  → справка, краткая справка, блок команд инструкции
  kit/install-steps.yaml — реестр ручных шагов     → блок шагов инструкции (и число N — счётом позиций)

Подкоманды:
  help          [--commands P]                 текст справки (исход 19)
  short         [--commands P]                 краткая справка (имя — что делает), без примеров
  commands-block [--commands P]                блок команд для инструкции (между маркерами)
  steps-block   [--steps P]                    блок ручных шагов для инструкции (между маркерами)
  render --guide P [--commands P] [--steps P] [--write]
                                               инструкция с перегенерированными блоками между маркерами;
                                               без --write — печать в stdout, с --write — запись на место
  count-steps   [--steps P]                    печатает N — число позиций реестра шагов

Детерминизм: выход зависит только от байтов входных реестров; порядок — порядок реестра.
Здесь нет ни одного литерала имени команды и ни одного литерала шага.
"""
import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402

MARK_COMMANDS_START = "<!-- generated:commands:start -->"
MARK_COMMANDS_END = "<!-- generated:commands:end -->"
MARK_STEPS_START = "<!-- generated:steps:start -->"
MARK_STEPS_END = "<!-- generated:steps:end -->"
MARK_CORR_START = "<!-- generated:correction-example:start -->"
MARK_CORR_END = "<!-- generated:correction-example:end -->"

_REQUIRED_COMMAND_FIELDS = ("id", "name", "token", "synopsis", "grammar", "example", "time_bearing",
                            "callback_allowed", "tail_rule", "outcomes", "help_text", "guide_text")
_REQUIRED_STEP_FIELDS = ("id", "title", "when", "guide", "verified_by")


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
    return doc


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
    example с отступом (каждая строка с отступом — сообщение, которое бот примет). Ошибка макета — HelpPageError."""
    ids = {c["id"] for c in doc["commands"]}
    page = doc["help_page"]
    if not isinstance(page, list):
        raise HelpPageError("макет справки: help_page — не список")
    out, shown = [], set()
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
            line = "  " + item["line"]
            if item.get("note"):
                line += " — " + _subst(doc, item["note"])
            out.append(line)
        elif "forms_block" in item:
            if forms_doc:
                out.extend("  " + e for e in _form_examples(forms_doc, item["forms_block"]))
                shown.add("free_text")
        elif "forms_line" in item:
            if forms_doc:
                out.append(_subst(doc, item.get("lead", "")) + " · ".join("«%s»" % e for e in _form_examples(forms_doc, item["forms_line"])))
        else:
            raise HelpPageError("макет справки: неизвестный элемент %r" % sorted(item))
    rest = [c for c in doc["commands"] if c["id"] not in shown]
    if rest:
        out.append("")
        for c in rest:
            out.append("%s — %s" % (c["name"], c["help_text"]))
            out.append("  %s" % c["example"])
    return "\n".join(out) + "\n"


def render_help(doc, forms_doc=None, strict=False):
    """Ответ на справку. С макетом help_page — по макету; испорченный макет: strict (CLI) — отказ, иначе (рантайм
    бота) — прежний перечень, чтобы поллер не останавливался на ошибке справки (D19 M2 R1-02)."""
    if doc.get("help_page"):
        try:
            return render_help_page(doc, forms_doc)
        except HelpPageError as e:
            if strict:
                raise SystemExit(str(e))
        except Exception as e:   # noqa: BLE001 — рантайм: любая порча макета не роняет цикл
            if strict:
                raise
    cmds = doc["commands"]
    out = ["Команды бота (позиций в реестре: %d):" % len(cmds)]
    for c in cmds:
        out.append("%s — %s" % (c["name"], c["help_text"]))
        out.append("  пример: %s" % c["example"])
    if forms_doc:
        out.append(forms_examples_line(forms_doc))
    out.append("Время в командах берётся из времени вашего сообщения; «записано» приходит после push.")
    out.append("Префикс подтверждения после находки секрета: %s" % doc["confirm_prefix"])
    return "\n".join(out) + "\n"


def render_short(doc):
    """Краткая справка (имя — что делает), без примеров. С T8 в ответ на непонятое НЕ отправляется
    (REQ-095: одна строка + указатель на справку); остаётся проекцией реестра для инструментов."""
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


def render_commands_block(doc, forms_doc=None):
    cmds = doc["commands"]
    out = ["Перечень команд (сгенерировано из реестра kit/commands.yaml; позиций: %d)." % len(cmds), ""]
    if forms_doc:
        out.append(forms_examples_line(forms_doc))
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
            alt = (" (альтернатива: `%s`)" % s["alternative"]) if s.get("alternative") else ""
            out.append("- `%s` — %s; %s%s" % (s["name"], s["purpose"], flag, alt))
        out.append("")
    for n, s in enumerate(steps, 1):
        when = "" if s["when"] == "always" else " *(только для групповых чатов)*"
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


def render_guide(guide_path, cmd_doc, steps_doc, forms_doc=None):
    if forms_doc is None:
        forms_doc = load_forms(os.path.join(_HERE, "duration-forms.yaml"))
    with open(guide_path, "rb") as fh:
        text = fh.read().decode("utf-8")
    text = replace_between(text, MARK_COMMANDS_START, MARK_COMMANDS_END, render_commands_block(cmd_doc, forms_doc))
    text = replace_between(text, MARK_STEPS_START, MARK_STEPS_END, render_steps_block(steps_doc))
    text = replace_between(text, MARK_CORR_START, MARK_CORR_END, correction_example(forms_doc), inline=True)
    return text


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_help.py")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("help", "short", "commands-block", "count-steps", "steps-block", "render", "forms-line"):
        p = sub.add_parser(name)
        p.add_argument("--commands", default=os.path.join(_HERE, "commands.yaml"))
        p.add_argument("--steps", default=os.path.join(_HERE, "install-steps.yaml"))
        p.add_argument("--forms", default=os.path.join(_HERE, "duration-forms.yaml"))
        if name == "render":
            p.add_argument("--guide", required=True)
            p.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    if args.cmd == "help":
        sys.stdout.write(render_help(load_commands(args.commands), load_forms(args.forms), strict=True))
    elif args.cmd == "short":
        sys.stdout.write(render_short(load_commands(args.commands)))
    elif args.cmd == "forms-line":
        sys.stdout.write(forms_examples_line(load_forms(args.forms)) + "\n")
    elif args.cmd == "commands-block":
        sys.stdout.write(render_commands_block(load_commands(args.commands), load_forms(args.forms)))
    elif args.cmd == "steps-block":
        sys.stdout.write(render_steps_block(load_steps(args.steps)))
    elif args.cmd == "count-steps":
        sys.stdout.write("%d\n" % len(load_steps(args.steps)["steps"]))
    elif args.cmd == "render":
        text = render_guide(args.guide, load_commands(args.commands), load_steps(args.steps), load_forms(args.forms))
        if args.write:
            with open(args.guide, "wb") as fh:
                fh.write(text.encode("utf-8"))
        else:
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
