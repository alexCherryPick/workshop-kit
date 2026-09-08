# -*- coding: utf-8 -*-
"""Генератор bot-fixtures-manifest.tsv (D09 T6): путь<TAB>sha256 пиннованных фикстур, реальные разделители.
Режим сверки — harness/bot_gate.sh (блок «фикстурный манифест»). Запуск из корня монорепо:
  python3 bot/tests/fixtures/build_fixtures_manifest.py [--check]"""
import hashlib, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(ROOT, "spec", "09-tg-bot-time-line", "bot-fixtures-manifest.tsv")
def rows():
    out = []
    for d, _, fs in os.walk(os.path.join(ROOT, "bot", "tests", "fixtures")):
        for f in sorted(fs):
            if f in ("manifest.yaml",) or f.endswith(".py"):
                continue
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out.append((os.path.relpath(p, ROOT), hashlib.sha256(fh.read()).hexdigest()))
    stub = os.path.join(ROOT, "harness", "fixtures", "d09", "reconciler-STUB.yml")
    if os.path.exists(stub):
        with open(stub, "rb") as fh:
            out.append((os.path.relpath(stub, ROOT), hashlib.sha256(fh.read()).hexdigest()))
    return sorted(out)
def render(rs):
    head = ["# Пиннованные фикстуры D09 — путь\tsha256 (режим СВЕРКИ в harness/bot_gate.sh; CLAUDE.md:135).",
            "# Генератор: python3 bot/tests/fixtures/build_fixtures_manifest.py; сверка: --check."]
    return "\n".join(head + ["%s\t%s" % r for r in rs]) + "\n"
def main():
    text = render(rows())
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        bad = [l for l in cur.splitlines() if l and not l.startswith("#") and "\t" not in l]
        if bad or cur != text:
            sys.stdout.write("fixtures manifest: РАСХОЖДЕНИЕ (строк без TAB: %d; содержимое %s)\n" % (len(bad), "устарело" if not bad else "не TSV"))
            return 1
        sys.stdout.write("fixtures manifest: сверен, записей %d\n" % (len(text.splitlines()) - 2)); return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    sys.stdout.write("fixtures manifest: записан, записей %d\n" % (len(text.splitlines()) - 2)); return 0
if __name__ == "__main__":
    sys.exit(main())
