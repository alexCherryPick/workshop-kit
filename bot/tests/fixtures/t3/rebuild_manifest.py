# -*- coding: utf-8 -*-
"""Пересобрать manifest.yaml фикстур T3 (после осознанной правки фикстуры)."""
import hashlib, os
D = os.path.dirname(os.path.abspath(__file__))
names = sorted(f for f in os.listdir(D) if f.endswith(".json"))
with open(os.path.join(D, "manifest.yaml"), "w", encoding="utf-8") as fh:
    fh.write("# Манифест пиннованных фикстур батчей T3 (путь, sha256) — режим СВЕРКИ в selfcheck_t3.sh (правило §2: пиннинг — манифест, не печать дайджеста).\n# Пересборка: python3 bot/tests/fixtures/t3/rebuild_manifest.py (после осознанной правки фикстуры).\nschema_version: 1\nentries:\n")
    for n in names:
        with open(os.path.join(D, n), "rb") as f:
            fh.write("  - {path: %s, sha256: %s}\n" % (n, hashlib.sha256(f.read()).hexdigest()))
