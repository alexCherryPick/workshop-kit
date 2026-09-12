#!/usr/bin/env python3
"""build_manifest.py — ДЕТЕРМИНИРОВАННЫЙ генератор манифеста комплекта `kit/manifest.yaml`.

Владелец генератора — T1 (D09 §3); сам файл манифеста генерируется на гейте T6, когда все
компоненты комплекта существуют (T3/T4/T5 дописывают свои). Ручного редактирования манифеста
нет ни у кого: манифест = проекция дерева `bot/` через таблицу раскладки ниже.

Форма манифеста: «путь → sha256 → назначение → версия схемы» (REQ-084):
  schema_version, kit_version, kit_schema_version, workflows_dir, entries[{src, dst, role, sha256, mode}]
Роли (install.py исполняет их, а не решает):
  code      — модули и реестры, читаемые ботом на прогоне; при обновлении ПЕРЕЗАПИСЫВАЮТСЯ
  hook      — git-хук; перезаписывается, ставится исполняемым
  policy    — .gitattributes (владелец — комплект, ядро 04.7.1); перезаписывается
  workflow  — обёртки поллера/сторожа; перезаписываются (путь провайдер-специфичен: workflows_dir)
  config    — .workshop/bot.yaml: создаётся, если нет; ДАЛЬШЕ НЕ ТРОГАЕТСЯ (настройки заказчика)
  state     — .workshop/bot-sessions.yaml: создаётся пустым, если нет; ДАЛЬШЕ НЕ ТРОГАЕТСЯ (мутирует поллер)
  manual    — bootstrap-обёртка и карта людей .workshop/people.yaml: НИКОГДА не пишутся установщиком
              (их кладёт заказчик — шаги реестра install-steps.yaml, §1Д; шаблон карты людей —
              синтетические примеры, в репозиторий заказчика не попадают)

Использование: build_manifest.py [--kit DIR] [--kit-version V] [--out PATH]
  без --out печатает манифест в stdout. Два прогона на одном срезе — побайтово равный вывод.
"""
import argparse
import hashlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402

KIT_SCHEMA_VERSION = 1
WORKFLOWS_DIR = ".github/workflows"

# Таблица раскладки: (предикат по относительному пути внутри bot/, роль, функция назначения).
# Порядок значим: первое совпадение побеждает. Пути — POSIX, относительно каталога bot/.
def _layout(rel):
    parts = rel.split("/")
    name = parts[-1]
    if "__pycache__" in parts or name.endswith(".pyc"):
        return None
    if parts[0] == "tests":
        return None
    if len(parts) == 1 and name.endswith(".py"):
        return ("code", ".workshop/bot/" + name, "0644")
    if parts[0] != "kit":
        return None
    if len(parts) == 2:
        if name in ("commands.yaml", "secret-patterns.yaml", "people_handles.py"):
            return ("code", ".workshop/bot/kit/" + name, "0644")
        if name in ("install.py", "install-steps.yaml", "validator-release.yaml", "build_help.py"):
            # РАНТАЙМ комплекта у заказчика: обёртки поллера и сторожа зовут `install.py validator`
            # каждый прогон (бинарь валидатора в коммит не попадает — каталог самоигнорируемый),
            # install.py читает реестр шагов и манифест релиза, а poll.py импортирует build_help
            # (справка рендерится из реестра команд). Без них прогон падает «can't open file» либо
            # ModuleNotFoundError (живой прогон 2026-09-12).
            return ("code", ".workshop/bot/kit/" + name, "0644" if name != "install.py" else "0755")
        return None  # build_manifest.py, wrapper_predicate.py, manifest.yaml — инструменты СБОРКИ, в репо не ставятся
    sub = parts[1]
    if sub == "daemon":
        # обёртка-демон (Dockerfile, entrypoint, compose-фрагмент, пример env) — вторая форма запуска
        # поллера на машине ЗАКАЗЧИКА; кладётся в его инфраструктурный репозиторий (compose), а не в
        # репозиторий трекера, поэтому в раскладку install.py не входит — выдаётся ассетами релиза
        return None
    if sub == "docs":
        return ("code", ".workshop/bot/kit/docs/" + name, "0644")
    if sub == "hooks":
        return ("hook", ".workshop/hooks/" + name, "0755")
    if sub == "templates":
        if name == "gitattributes":
            return ("policy", ".gitattributes", "0644")
        if name == "people.yaml":
            return ("manual", ".workshop/people.yaml", "0644")
        if name == "bot.yaml":
            return ("config", ".workshop/bot.yaml", "0644")
        if name == "bot-sessions.yaml":
            return ("state", ".workshop/bot-sessions.yaml", "0644")
        return None
    if sub == "workflows":
        if name == "bootstrap.yml":
            return ("manual", WORKFLOWS_DIR + "/workshop-bot-bootstrap.yml", "0644")
        return ("workflow", WORKFLOWS_DIR + "/workshop-bot-" + name, "0644")
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build(bot_dir, kit_version):
    entries = []
    for root, dirs, files in os.walk(bot_dir):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = os.path.relpath(full, bot_dir).replace(os.sep, "/")
            lay = _layout(rel)
            if lay is None:
                continue
            role, dst, mode = lay
            entries.append({"src": "bot/" + rel, "dst": dst, "role": role, "sha256": sha256_file(full), "mode": mode})
    entries.sort(key=lambda e: e["src"])
    dsts = [e["dst"] for e in entries]
    if len(dsts) != len(set(dsts)):
        dup = sorted(d for d in dsts if dsts.count(d) > 1)
        raise SystemExit("манифест: два источника на одно назначение: %s" % dup)
    return {
        "schema_version": 1,
        "kit_version": kit_version,
        "kit_schema_version": KIT_SCHEMA_VERSION,
        "workflows_dir": WORKFLOWS_DIR,
        "entries": entries,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_manifest.py")
    ap.add_argument("--kit", default=_HERE, help="каталог bot/kit (по умолчанию — рядом с генератором)")
    ap.add_argument("--kit-version", default="0.1.0")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    bot_dir = os.path.dirname(os.path.abspath(args.kit))
    manifest = build(bot_dir, args.kit_version)
    text = yamlmini.dumps(manifest)
    if args.out:
        with open(args.out, "wb") as fh:
            fh.write(text.encode("utf-8"))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
