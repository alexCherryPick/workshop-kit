#!/usr/bin/env python3
"""people_handles.py — экспортёр плоского списка handle И aliases для `--people` валидатора.
Владелец — T1 (D09 §4). Валидатор читает «handle по строке» (validator/cli/src/main.rs:515-518);
карта людей остаётся единственной правдой, второго реестра нет — этот скрипт лишь проекция.

Использование: people_handles.py <.workshop/people.yaml>   → stdout: по одному handle/alias на строку,
порядок — порядок карты (сначала handle записи, затем её aliases), без дублей. Ошибка формы карты — rc=2.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402


def export(doc):
    people = doc.get("people") if isinstance(doc, dict) else None
    if not isinstance(people, list):
        raise ValueError("карта людей: нет списка people")
    out = []
    seen = set()
    for p in people:
        h = p.get("handle")
        if not h:
            raise ValueError("карта людей: запись без handle")
        for token in [h] + list(p.get("aliases") or []):
            token = str(token)
            if token not in seen:
                seen.add(token)
                out.append(token)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.stdout.write("usage: people_handles.py <people.yaml>\n")
        return 2
    try:
        lines = export(yamlmini.load_file(argv[0]))
    except (ValueError, yamlmini.YamlError) as e:
        sys.stdout.write("FAIL people_handles: %s\n" % e)
        return 2
    sys.stdout.write("".join(l + "\n" for l in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
