"""Оракул build_help.py. Реестр читается НЕЗАВИСИМЫМ читателем (регэксп по сырому тексту), а не
yamlmini, — оракул не делит с генератором parser. Проверяются: полнота проекции (каждая позиция
реестра — в справке, в краткой справке и в блоке инструкции), детерминизм (два прогона побайтово
равны), чувствительность (добавленная позиция меняет ОБА выхода), маркеры инструкции, N."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KIT = os.path.join(_BOT, "kit")
GEN = os.path.join(_KIT, "build_help.py")
COMMANDS = os.path.join(_KIT, "commands.yaml")
STEPS = os.path.join(_KIT, "install-steps.yaml")
GUIDE = os.path.join(_KIT, "docs", "bot-user-guide.ru.md")
PY = sys.executable


def run(*argv):
    p = subprocess.run([PY, GEN] + list(argv), capture_output=True)
    return p.returncode, p.stdout.decode("utf-8")


def registry_names(path):
    """Независимый читатель: имена позиций из сырого текста (строки `    name: "..."` внутри commands:)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("\ncommands:\n", 1)[1]
    return re.findall(r'^    name: "(.*)"$', body, re.M)


def steps_count(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("\nsteps:\n", 1)[1]
    return len(re.findall(r"^  - id: ", body, re.M))


class ProjectionTests(unittest.TestCase):
    def test_registry_has_eight_positions(self):
        self.assertEqual(len(registry_names(COMMANDS)), 8)

    def test_help_short_block_cover_every_position(self):
        names = registry_names(COMMANDS)
        for sub in ("help", "short", "commands-block"):
            rc, out = run(sub)
            self.assertEqual(rc, 0, out)
            for n in names:
                self.assertIn(n, out, "%s: нет позиции %r" % (sub, n))
        rc, out = run("help")
        self.assertIn("позиций в реестре: 8", out)

    def test_deterministic(self):
        for sub in ("help", "short", "commands-block", "steps-block"):
            self.assertEqual(run(sub), run(sub))

    def test_added_position_changes_both_outputs(self):
        tmp = tempfile.mkdtemp(prefix="bh-")
        try:
            p = os.path.join(tmp, "commands.yaml")
            with open(COMMANDS, encoding="utf-8") as fh:
                text = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text + (
                    "  - id: zz_probe\n    name: \"/zzprobe\"\n    token: \"/zzprobe\"\n    synopsis: \"\"\n"
                    "    grammar: x\n    example: \"/zzprobe\"\n    time_bearing: false\n    callback_allowed: false\n"
                    "    tail_rule: none\n    outcomes: [help_given]\n    help_text: проба\n    guide_text: |\n      проба\n"))
            for sub in ("help", "commands-block"):
                rc, base = run(sub)
                rc2, mut = run(sub, "--commands", p)
                self.assertEqual((rc, rc2), (0, 0))
                self.assertNotEqual(base, mut)
                self.assertIn("/zzprobe", mut)
                self.assertNotIn("/zzprobe", base)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_steps_block_and_count(self):
        n = steps_count(STEPS)
        rc, out = run("count-steps")
        self.assertEqual(out.strip(), str(n))
        rc, block = run("steps-block")
        self.assertIn("N = %d" % n, block)
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", block, re.M)), n)
        tmp = tempfile.mkdtemp(prefix="st-")
        try:
            p = os.path.join(tmp, "steps.yaml")
            with open(STEPS, encoding="utf-8") as fh:
                text = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text + "  - id: zz_probe\n    title: проба\n    when: always\n    guide: проба\n    verified_by: проба\n")
            rc, out2 = run("count-steps", "--steps", p)
            self.assertEqual(out2.strip(), str(n + 1))
            rc, block2 = run("steps-block", "--steps", p)
            self.assertNotEqual(block, block2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_guide_markers_and_render_idempotent(self):
        with open(GUIDE, encoding="utf-8") as fh:
            guide = fh.read()
        for tag in ("commands", "steps"):
            self.assertEqual(guide.count("<!-- generated:%s:start -->" % tag), 1)
            self.assertEqual(guide.count("<!-- generated:%s:end -->" % tag), 1)
        rc, rendered = run("render", "--guide", GUIDE)
        self.assertEqual(rc, 0)
        self.assertEqual(rendered, guide, "инструкция на диске не равна перегенерированной: блоки правлены руками?")
        for n in registry_names(COMMANDS):
            self.assertIn(n, guide)
        # проза вне сгенерированных блоков не называет команд литералами
        prose = re.sub(r"<!-- generated:commands:start -->.*?<!-- generated:commands:end -->", "", guide, flags=re.S)
        prose = re.sub(r"<!-- generated:steps:start -->.*?<!-- generated:steps:end -->", "", prose, flags=re.S)
        for n in registry_names(COMMANDS):
            tok = n.split(" ")[0]
            if tok.startswith("/") or tok.startswith("!"):
                self.assertNotIn(tok, prose, "литерал команды в прозе инструкции: %s" % tok)


if __name__ == "__main__":
    unittest.main()
