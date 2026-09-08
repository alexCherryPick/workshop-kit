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
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402

MARK_COMMANDS_START = "<!-- generated:commands:start -->"
MARK_COMMANDS_END = "<!-- generated:commands:end -->"
MARK_STEPS_START = "<!-- generated:steps:start -->"
MARK_STEPS_END = "<!-- generated:steps:end -->"

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


# ------------------------------------------------------------------ проекции
def render_help(doc):
    cmds = doc["commands"]
    out = ["Команды бота (позиций в реестре: %d):" % len(cmds)]
    for c in cmds:
        out.append("%s — %s" % (c["name"], c["help_text"]))
        out.append("  пример: %s" % c["example"])
    out.append("Время в командах берётся из времени вашего сообщения; «записано» приходит после push.")
    out.append("Префикс подтверждения после находки секрета: %s" % doc["confirm_prefix"])
    return "\n".join(out) + "\n"


def render_short(doc):
    cmds = doc["commands"]
    out = ["Не понял сообщение. Команды:"]
    for c in cmds:
        out.append("%s — %s" % (c["name"], c["help_text"]))
    return "\n".join(out) + "\n"


def render_commands_block(doc):
    cmds = doc["commands"]
    out = ["Перечень команд (сгенерировано из реестра kit/commands.yaml; позиций: %d)." % len(cmds), ""]
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


def replace_between(text, start, end, block):
    a = text.count(start)
    b = text.count(end)
    if a != 1 or b != 1:
        raise SystemExit("маркеры %s/%s: ожидалось по одному, найдено %d/%d" % (start, end, a, b))
    i = text.index(start) + len(start)
    j = text.index(end)
    if j < i:
        raise SystemExit("маркер конца раньше маркера начала: %s" % end)
    return text[:i] + "\n" + block + text[j:]


def render_guide(guide_path, cmd_doc, steps_doc):
    with open(guide_path, "rb") as fh:
        text = fh.read().decode("utf-8")
    text = replace_between(text, MARK_COMMANDS_START, MARK_COMMANDS_END, render_commands_block(cmd_doc))
    text = replace_between(text, MARK_STEPS_START, MARK_STEPS_END, render_steps_block(steps_doc))
    return text


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_help.py")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("help", "short", "commands-block", "count-steps", "steps-block", "render"):
        p = sub.add_parser(name)
        p.add_argument("--commands", default=os.path.join(_HERE, "commands.yaml"))
        p.add_argument("--steps", default=os.path.join(_HERE, "install-steps.yaml"))
        if name == "render":
            p.add_argument("--guide", required=True)
            p.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    if args.cmd == "help":
        sys.stdout.write(render_help(load_commands(args.commands)))
    elif args.cmd == "short":
        sys.stdout.write(render_short(load_commands(args.commands)))
    elif args.cmd == "commands-block":
        sys.stdout.write(render_commands_block(load_commands(args.commands)))
    elif args.cmd == "steps-block":
        sys.stdout.write(render_steps_block(load_steps(args.steps)))
    elif args.cmd == "count-steps":
        sys.stdout.write("%d\n" % len(load_steps(args.steps)["steps"]))
    elif args.cmd == "render":
        text = render_guide(args.guide, load_commands(args.commands), load_steps(args.steps))
        if args.write:
            with open(args.guide, "wb") as fh:
                fh.write(text.encode("utf-8"))
        else:
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
