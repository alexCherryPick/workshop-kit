# -*- coding: utf-8 -*-
"""gen_attach_norm.py — ДЕТЕРМИНИРОВАННЫЙ генератор `bot/attach/norm.py` из нормы вложений
`spec/03-spec-type-schemas/attachments.yaml` (D20 T2).

Зачем генерация, а не чтение нормы на прогоне: комплект заказчика — зеркало `bot/`, а каталога `spec/`
у заказчика нет; читать норму на прогоне значило бы класть в комплект ещё и attachments.yaml. Голая
рукописная копия реестров запрещена (правило сходимости §2), поэтому реестры — только выход этого
генератора, а файл несёт sha256 источника. Тест `bot/tests/test_attach_norm.py` роняет прогон, если
(1) sha256 текущей нормы не равен записанному, (2) перегенерация не равна файлу побайтово,
(3) независимый разбор нормы (PyYAML — НЕ yamlmini писателя) расходится с константами.

Инструмент сборки: в комплект не ставится (build_manifest._layout: прочие файлы bot/kit/ — None).

Использование:
    python3 bot/kit/gen_attach_norm.py            # перезаписать bot/attach/norm.py
    python3 bot/kit/gen_attach_norm.py --check    # rc 1, если файл устарел
    python3 bot/kit/gen_attach_norm.py --stdout   # вывести без записи
"""
import argparse
import hashlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_BOT)
sys.path.insert(0, _BOT)
import yamlmini  # noqa: E402

NORM_REL = "spec/03-spec-type-schemas/attachments.yaml"
OUT_REL = "bot/attach/norm.py"


def _extract(n):
    """Узлы нормы → упорядоченный список (имя константы, значение). Только реестры: перечни, таблицы,
    грамматики, числа. Проза нормы (правила строк переходов, байтовые ограничения) — в коде, по ключу из
    этих реестров."""
    ptr = n["pointer"]
    out = []
    add = lambda k, v: out.append((k, v))  # noqa: E731
    add("SPEC", n["spec"])
    add("CHAPTER", n["chapter"])
    add("SCHEMA_VERSION", n["schema_version"])
    # раскладка и имя
    add("PATH_GRAMMAR", n["layout"]["path_grammar"])
    add("PATH_PATTERN", n["layout"]["path_pattern"])
    add("RESERVED_DIR", n["layout"]["reserved_directory_name"])
    add("FILENAME_PATTERN", n["filename"]["pattern"])
    add("SLUG_PATTERN", n["filename"]["components"]["slug"]["pattern"])
    add("SLUG_MAX_LEN", n["filename"]["components"]["slug"]["max_len"])
    add("EXT_PATTERN", n["filename"]["components"]["ext"]["pattern"])
    # порог
    add("GIT_THRESHOLD_DEFAULT", n["soft_limit"]["bytes"])
    add("THRESHOLD_COMPARISON", n["soft_limit"]["comparison"])
    # маршрут
    add("ROUTING_STEPS", tuple((s["step"], s["when"], s["outcome"], s.get("reason")) for s in n["routing"]["steps"]))
    add("ROUTING_OUTCOMES", tuple(n["routing"]["outcome_meaning"].keys()))
    # указатель
    add("POINTER_MAGIC_PREFIX", ptr["magic_prefix"])
    add("POINTER_MAGIC_LINE", ptr["magic_line"])
    add("POINTER_FIRST_LINE_PATTERN", ptr["first_line_pattern"])
    add("POINTER_VERSION_PATTERN", ptr["version_pattern"])
    add("POINTER_KNOWN_VERSIONS", tuple(ptr["known_versions"]))
    add("POINTER_MAX_BYTES", ptr["max_bytes"])
    add("POINTER_ENCODING", ptr["encoding"])
    add("POINTER_FIELD_ORDER", tuple(ptr["field_order"]))
    add("POINTER_FIELD_PATTERNS", tuple((f["name"], f["pattern"]) for f in ptr["fields"]))
    add("POINTER_FIELD_MAX_LEN", tuple((f["name"], f["max_len"]) for f in ptr["fields"] if "max_len" in f))
    add("POINTER_PRESENCE", tuple((st, tuple((fld, ptr["presence"][st][fld]) for fld in ptr["field_order"]))
                                  for st in ptr["presence"]))
    add("POINTER_PRESENCE_EXTRA", ptr["presence_extra"])
    # ключ объекта
    add("OBJECT_KEY_DERIVATION", n["object_key"]["derivation"])
    # состояния
    add("STATES", tuple((s["state"], s["carrier"], tuple(s.get("reasons", ()))) for s in n["states"]["list"]))
    add("TRANSITIONS", tuple((t["from"], t["to"]) for t in n["states"]["transitions"]))
    add("TRANSITION_RULES", tuple((t["from"], t["to"], t["rule"]) for t in n["states"]["transitions"]))
    add("DIFF_PARENT_RULE", n["states"]["diff_parent_rule"])
    add("TERMINAL_STATES", tuple(n["states"]["terminal"]))
    add("PENDING_REQUIRES_DURABLE_QUEUE", n["states"]["pending_requires_durable_queue"])
    add("WRITE_FAILURE_RULE", n["states"]["write_failure"])
    add("UNSAVED_REASONS", tuple((r["reason"], r["user_mark"]) for r in n["unsaved"]["reasons"]))
    # исходы адаптера
    add("READ_ORDER", tuple(s.strip() for s in n["adapter_outcomes"]["read_order"].split("->")))
    add("READ_OUTCOMES", tuple(o["outcome"] for o in n["adapter_outcomes"]["read"]))
    add("WRITE_OUTCOMES", tuple(o["outcome"] for o in n["adapter_outcomes"]["write"]))
    add("VERIFICATION_REQUIRES_LOCAL_HASH", n["adapter_outcomes"]["verification_requires_local_hash"])
    # смысл исходов (D20 T4: описания контракта CLI/фронтов — из нормы, не переписаны)
    add("READ_OUTCOME_MEANINGS", tuple((o["outcome"], o["meaning"]) for o in n["adapter_outcomes"]["read"]))
    add("WRITE_OUTCOME_MEANINGS", tuple((o["outcome"], o["meaning"]) for o in n["adapter_outcomes"]["write"]))
    # привязка
    add("CONFIG_FACTS", tuple(f["fact"] for f in n["storage_binding"]["config_facts"]))
    add("STATUS_FACTS", tuple(n["storage_binding"]["status_facts"]))
    # ссылка из тела и подпись (D20 T4: строка ссылки API бота)
    add("LINK_FORMS", tuple((f["form"], f["syntax"], f["base"]) for f in n["link_forms"]["forms"]))
    add("CAPTION_ESCAPE_CHARS", tuple(n["filename"]["original_name"]["escaping_required_chars"]))
    add("GLOB_ALL_ATTACHMENTS", n["layout"]["glob_all_attachment_bytes"])
    # LFS
    add("LFS_SIGNATURE_PREFIX", n["lfs"]["signature_prefix"])
    return out


def _lit(v, ind=0):
    """Детерминированный литерал Python: кортежи — построчно, строки — repr (ASCII-эскейп не нужен,
    файл UTF-8)."""
    pad = "    " * (ind + 1)
    if isinstance(v, tuple):
        if not v:
            return "()"
        if all(not isinstance(x, tuple) for x in v) and len(repr(v)) <= 100:
            return repr(v)
        inner = "".join(pad + _lit(x, ind + 1) + ",\n" for x in v)
        return "(\n" + inner + "    " * ind + ")"
    if isinstance(v, (str, int, bool)) or v is None:
        return repr(v)
    raise TypeError("тип вне генератора: %r" % type(v))


def render(norm_bytes):
    n = yamlmini.loads(norm_bytes.decode("utf-8"))
    digest = hashlib.sha256(norm_bytes).hexdigest()
    lines = [
        "# -*- coding: utf-8 -*-",
        "# СГЕНЕРИРОВАНО bot/kit/gen_attach_norm.py из %s — НЕ ПРАВИТЬ РУКАМИ." % NORM_REL,
        "# Перегенерация: python3 bot/kit/gen_attach_norm.py; проверка: bot/tests/test_attach_norm.py.",
        '"""Реестры нормы вложений (D20 T1) для адаптера D20 T2 — только данные, без логики."""',
        "",
        "SOURCE_PATH = %r" % NORM_REL,
        "SOURCE_SHA256 = %r" % digest,
    ]
    for k, v in _extract(n):
        lines.append("%s = %s" % (k, _lit(v)))
    return ("\n".join(lines) + "\n").encode("utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gen_attach_norm.py")
    ap.add_argument("--root", default=_ROOT)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    with open(os.path.join(a.root, NORM_REL), "rb") as f:
        src = f.read()
    data = render(src)
    out = os.path.join(a.root, OUT_REL)
    if a.stdout:
        sys.stdout.buffer.write(data)
        return 0
    if a.check:
        try:
            with open(out, "rb") as f:
                cur = f.read()
        except OSError:
            cur = None
        if cur != data:
            print("attach/norm.py УСТАРЕЛ относительно %s" % NORM_REL)
            return 1
        print("attach/norm.py == генерация из %s sha256 %s" % (NORM_REL, hashlib.sha256(src).hexdigest()))
        return 0
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    print("записан %s из %s sha256 %s" % (OUT_REL, NORM_REL, hashlib.sha256(src).hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
