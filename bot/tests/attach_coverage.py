# -*- coding: utf-8 -*-
"""attach_coverage — таблица «исход нормы → тест(ы)» адаптера вложений (D20 T2), печатается ИЗ attachments.yaml.

Строки таблицы — adapter_outcomes.read и adapter_outcomes.write нормы (PyYAML, порядок нормы); тесты —
метки, которые test_attach.py ставит в каждом assert исхода (Base.seen) при ATTACH_COVERAGE_OUT. Строка
без теста — rc 1. Исход, помеченный тестом, но отсутствующий в норме, — тоже rc 1 (закрытое множество).

Запуск из корня: python3 bot/tests/attach_coverage.py
"""
import collections
import json
import os
import subprocess
import sys
import tempfile

import yaml

_TESTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_TESTS))
NORM = os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml")


def main():
    with open(NORM, "rb") as f:
        n = yaml.safe_load(f.read().decode("utf-8"))
    fd, out = tempfile.mkstemp(prefix="attach-cov-", suffix=".json")
    os.close(fd)
    try:
        env = dict(os.environ, ATTACH_COVERAGE_OUT=out)
        r = subprocess.run([sys.executable, "-m", "unittest", "test_attach"], cwd=_TESTS, env=env,
                           capture_output=True)
        tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        with open(out, "r", encoding="utf-8") as f:
            marks = json.load(f)
    finally:
        os.unlink(out)
    seen = collections.defaultdict(set)
    for kind, outcome, test in marks:
        seen[(kind, outcome)].add(test.split(".", 1)[1])
    rc = 0 if r.returncode == 0 else 1
    print("прогон test_attach: rc=%d %s" % (r.returncode, " ".join(tail)))
    norm_keys = set()
    for kind in ("read", "write"):
        print("\n| исход %s (attachments.yaml adapter_outcomes.%s) | тестов | тесты |" % ("чтения" if kind == "read" else "записи", kind))
        print("|---|---|---|")
        for o in n["adapter_outcomes"][kind]:
            name = o["outcome"]
            norm_keys.add((kind, name))
            tests = sorted(seen.get((kind, name), ()))
            if not tests:
                rc = 1
            print("| `%s` | %d | %s |" % (name, len(tests), ", ".join(tests) if tests else "**НЕТ ТЕСТА**"))
    stray = sorted(k for k in seen if k not in norm_keys)
    if stray:
        rc = 1
        print("\nметки вне нормы: %s" % stray)
    total = len(norm_keys)
    covered = sum(1 for k in norm_keys if seen.get(k))
    print("\nпокрыто %d из %d строк таблиц нормы; rc=%d" % (covered, total, rc))
    return rc


if __name__ == "__main__":
    sys.exit(main())
