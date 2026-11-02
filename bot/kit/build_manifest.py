#!/usr/bin/env python3
"""build_manifest.py — ДЕТЕРМИНИРОВАННЫЙ генератор манифеста комплекта `kit/manifest.yaml`.

Владелец генератора — T1 (D09 §3); сам файл манифеста генерируется на гейте T6, когда все
компоненты комплекта существуют (T3/T4/T5 дописывают свои). Ручного редактирования манифеста
нет ни у кого: манифест = проекция дерева `bot/` через таблицу раскладки ниже.

Форма манифеста: «путь → sha256 → назначение → версия схемы» (REQ-084):
  schema_version, kit_version, kit_schema_version, workflows_dir, [customer_layer{path, sha256}], entries[{src, dst, role, sha256, mode}]
  [customer_layer — D10 T24: привязка выходов роли managed к слою заказчика, под который их собрал генератор: путь слоя
     в репозитории заказчика и sha256 его байт из пиннинга profiles/sources-manifest.yaml; есть, если есть записи managed
     и пиннинг называет слой; install.py layout сверяет со слоем клона]
  [+ retire[{path, sha256}], supersedes[{path, sha256}] — проекция kit/retire.yaml: retire — только если его замена
     есть среди назначений; замена — РОВНО одно из полей реестра (в манифест не идут): replaced_by_profile — id профиля,
     назначение читается из profiles/profiles.yaml (единственный адрес назначений профилей), или replaced_by — путь
     назначения не-профиля; supersedes — только для назначений managed]
Роли (install.py исполняет их, а не решает):
  code      — модули и реестры, читаемые ботом на прогоне; при обновлении ПЕРЕЗАПИСЫВАЮТСЯ
  hook      — git-хук; перезаписывается, ставится исполняемым
  policy    — .gitattributes (владелец — комплект, ядро 04.7.1); перезаписывается
  managed   — инструкции ИИ-агента (D10): профили (назначения — profiles/profiles.yaml), standing AGENTS.md = CLAUDE.md — выходы генератора
              profiles/build_profile.py (profiles/out/<destination>, пиннинг profiles/sources-manifest.yaml);
              перезаписываются ТОЛЬКО поверх своего прежнего содержимого (sha256 последней раскладки из
              kit-version.yaml или известного прежнего из supersedes), иначе — именованный конфликт
  lines     — .gitignore заказчика: недостающие строки источника ДОПИСЫВАЮТСЯ, чужие строки не трогаются
  workflow  — обёртки поллера/сторожа; перезаписываются (путь провайдер-специфичен: workflows_dir)
  config    — .workshop/bot.yaml, .workshop/storage.yaml (D20 T3): создаётся, если нет; ДАЛЬШЕ НЕ ТРОГАЕТСЯ (настройки заказчика)
  state     — .workshop/bot-sessions.yaml: создаётся пустым, если нет; ДАЛЬШЕ НЕ ТРОГАЕТСЯ (мутирует поллер)
  manual    — bootstrap-обёртка и карта людей .workshop/people.yaml: НИКОГДА не пишутся установщиком
              (их кладёт заказчик — шаги реестра install-steps.yaml, §1Д; шаблон карты людей —
              синтетические примеры, в репозиторий заказчика не попадают)

Использование: build_manifest.py [--kit DIR] [--kit-version V] [--out PATH] [--require-profiles]
  без --out печатает манифест в stdout. Два прогона на одном срезе — побайтово равный вывод.
  Выходы генератора профилей берутся из <корень комплекта>/profiles/ (profiles.yaml — назначения, sources-manifest.yaml —
  пиннинг, out/ — байты). Нет манифеста пиннинга — записей профилей нет (примечание в stderr);
  --require-profiles (релиз) делает это отказом rc=2. Выход, расходящийся с пиннингом, — всегда отказ.
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
# D10 T24 (G-PROVIDER): слой заказчика живёт в репозитории ЗАКАЗЧИКА рядом с профилями, комплект кладёт только образец.
# Профили и standing собираются генератором под слой клона; манифест несёт привязку `customer_layer` (путь у заказчика
# + sha256 байт слоя, под которые собраны выходы роли managed — из пиннинга profiles/sources-manifest.yaml), install.py
# layout сверяет её со слоем клона до мутаций. Узел пути — единственный: здесь.
CUSTOMER_LAYER_DST = ".workshop-ai/customer-layer.yaml"
CUSTOMER_LAYER_EXAMPLE = "customer-layer.example.yaml"
# логическое имя слоя в пиннинге генератора (при любом источнике байт — образец или слой клона). Пиннинг, собранный до
# T24 (слой лежал в комплекте под иным именем), привязки не даёт: такие выходы — прежнего мира, перепин (T24 M6) её создаёт
CUSTOMER_LAYER_LOGICAL = ("bot/kit/ai/" + CUSTOMER_LAYER_EXAMPLE,)

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
    if parts[0] == "attach":
        # D20 T4: адаптер вложений — ПАКЕТ, разложенный целиком (роль code): его импортируют install.py (storage-*,
        # check-secrets), бот (D18) и CLI заказчика `python3 .workshop/bot/attach …`. Только модули пакета; схема вывода
        # (cli-output.schema.json) — контракт для разработчиков фронтов, у заказчика её печатает `… attach schema`;
        # генератор реестров gen_attach_norm.py лежит в kit/ и не ставится (инструмент сборки)
        if len(parts) == 2 and name.endswith(".py"):
            return ("code", ".workshop/bot/attach/" + name, "0644")
        return None
    if parts[0] != "kit":
        return None
    if len(parts) == 2:
        if name == "retire.yaml":
            return None  # реестр снимаемых файлов — вход сборки манифеста (retire/supersedes), у заказчика не ставится
        if name in ("commands.yaml", "secret-patterns.yaml", "people_handles.py", "duration-forms.yaml", "reask-phrases.yaml"):   # R3-fix: реестр фраз — отдельно от команд
              # T8: реестр форм — читается парсером на прогоне
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
    if sub == "ai":
        # D10 T24: образец слоя заказчика кладётся рядом с профилями (.workshop-ai/, раскладка профилей агента), чтобы
        # заказчик скопировал его в свой слой; перезаписывается (роль code). Настоящий слой .workshop-ai/customer-layer.yaml
        # — файл заказчика, комплект его НЕ пишет; standing.md.tmpl — вход генератора, в репо не ставится
        if len(parts) == 3 and name == CUSTOMER_LAYER_EXAMPLE:
            return ("code", ".workshop-ai/" + name, "0644")
        return None
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
        if name == "gitignore":
            # D10 (глава 02 §2): .workshop/me.yaml — личный файл агента, в git не попадает; строки ДОПИСЫВАЮТСЯ в .gitignore
            return ("lines", ".gitignore", "0644")
        if name == "people.yaml":
            return ("manual", ".workshop/people.yaml", "0644")
        if name == "bot.yaml":
            return ("config", ".workshop/bot.yaml", "0644")
        if name == "storage.yaml":
            # D20 T3: конфиг хранилища вложений — отдельный файл (его читают бот, CLI и фронты, не только бот);
            # создаётся, если нет, дальше НЕ трогается (key_prefix заказчика переживает обновление комплекта)
            return ("config", ".workshop/storage.yaml", "0644")
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


class Refuse(Exception):
    pass


def _profile_entries(kit_root, require):
    """Записи роли managed: выходы генератора profiles/out/<destination> (назначения — profiles/profiles.yaml, байты
    сверены с пиннингом profiles/sources-manifest.yaml). -> (записи, примечание | None)."""
    reg = os.path.join(kit_root, "profiles", "profiles.yaml")
    pin = os.path.join(kit_root, "profiles", "sources-manifest.yaml")
    if not os.path.isfile(pin):
        note = "записей профилей агента нет: profiles/sources-manifest.yaml отсутствует (генератор профилей не собирал)"
        if require:
            raise Refuse(note + " — --require-profiles")
        return [], note, None
    if not os.path.isfile(reg):
        raise Refuse("есть манифест пиннинга профилей, но нет profiles/profiles.yaml")
    prof = yamlmini.load_file(reg)
    pin_doc = yamlmini.load_file(pin)
    pinned = dict((str(o["path"]), str(o["sha256"])) for o in (pin_doc.get("outputs") or []))
    layers = [(str(o["path"]), str(o["sha256"])) for o in (pin_doc.get("inputs") or []) if str(o["path"]) in CUSTOMER_LAYER_LOGICAL]
    if len(layers) > 1:
        raise Refuse("манифест пиннинга профилей называет слой заказчика дважды: %s" % ", ".join(p for p, _ in layers))
    dests = []
    for rec in list(prof.get("profiles") or []) + list(prof.get("artifacts") or []):
        for d in str(rec.get("destination") or "").split():
            dests.append(d)
    out = []
    for d in dests:
        logical = "profiles/out/" + d
        path = os.path.join(kit_root, "profiles", "out", *d.split("/"))
        if logical not in pinned:
            raise Refuse("назначение %s не названо в манифесте пиннинга профилей" % d)
        if not os.path.isfile(path):
            raise Refuse("выход генератора %s отсутствует" % logical)
        got = sha256_file(path)
        if got != pinned[logical]:
            raise Refuse("выход генератора %s расходится с пиннингом (%s ≠ %s) — пересоберите профили" % (logical, got, pinned[logical]))
        out.append({"src": logical, "dst": d, "role": "managed", "sha256": got, "mode": "0644"})
    binding = {"path": CUSTOMER_LAYER_DST, "sha256": layers[0][1]} if (out and layers) else None
    return out, None, binding


def _profile_destinations(kit_root):
    """id профиля -> назначение из profiles/profiles.yaml (единственный адрес назначений профилей); нет реестра — None."""
    reg = os.path.join(kit_root, "profiles", "profiles.yaml")
    if not os.path.isfile(reg):
        return None
    out = {}
    for rec in yamlmini.load_file(reg).get("profiles") or []:
        pid = str(rec.get("id"))
        if pid in out:
            raise Refuse("profiles/profiles.yaml: профиль %s дважды" % pid)
        out[pid] = str(rec.get("destination") or "")
    return out


def _replacement(r, prof_dests):
    """Назначение, заменяющее снимаемый файл: РОВНО одно из replaced_by_profile (id профиля -> destination реестра
    профилей) и replaced_by (путь назначения не-профиля). -> (путь | None, примечание | None)."""
    has_p, has_d = "replaced_by_profile" in r, "replaced_by" in r
    if has_p == has_d:
        raise Refuse("retire %s: замена задаётся ровно одним из replaced_by_profile / replaced_by (задано: %s)"
                     % (r.get("path"), "оба" if has_p else "ни одного"))
    if has_d:
        return str(r["replaced_by"]), None
    pid = str(r["replaced_by_profile"])
    if prof_dests is None:
        return None, "retire %s не проецируется: реестра профилей нет (замена — профиль %s)" % (r["path"], pid)
    if pid not in prof_dests:
        raise Refuse("retire %s: replaced_by_profile %s — нет такого профиля в profiles/profiles.yaml" % (r["path"], pid))
    dest = prof_dests[pid]
    if len(dest.split()) != 1:
        raise Refuse("retire %s: у профиля %s не одно назначение (%r)" % (r["path"], pid, dest))
    return dest, None


RETIRE_ORIGINS = ("customer_live", "kit_output")   # закрытое множество происхождений отпечатка retire (kit/retire.yaml)


def _check_origin(r):
    """Происхождение отпечатка — закрытое множество: неизвестное или отсутствующее origin — отказ (иначе запись выпала бы
    из сверки отпечатков молча); kit_output требует origin_ref «<ревизия>:<путь>», у customer_live его нет."""
    origin = r.get("origin")
    if origin not in RETIRE_ORIGINS:
        raise Refuse("retire %s: origin %r — не из %s" % (r.get("path"), origin, "|".join(RETIRE_ORIGINS)))
    ref = r.get("origin_ref")
    if origin == "kit_output" and (not isinstance(ref, str) or ":" not in ref or ref.startswith(":") or ref.endswith(":")):
        raise Refuse("retire %s: origin kit_output без origin_ref «<ревизия>:<путь>» (%r)" % (r.get("path"), ref))
    if origin == "customer_live" and ref is not None:
        raise Refuse("retire %s: origin customer_live не несёт origin_ref" % r.get("path"))


def _retire(kit_dir, entries, prof_dests=None):
    """Проекция kit/retire.yaml: retire — только при замене в манифесте; supersedes — только для назначений роли managed."""
    path = os.path.join(kit_dir, "retire.yaml")
    if not os.path.isfile(path):
        return [], [], []
    doc = yamlmini.load_file(path)
    dsts = set(e["dst"] for e in entries)
    managed = set(e["dst"] for e in entries if e["role"] == "managed")
    retire, supers, notes = [], [], []
    seen = set()
    for r in doc.get("retire") or []:
        if str(r["path"]) in seen:
            raise Refuse("retire %s дважды в kit/retire.yaml" % r["path"])
        seen.add(str(r["path"]))
        _check_origin(r)
        if str(r["path"]) in dsts:
            raise Refuse("retire %s совпадает с назначением манифеста — противоречие" % r["path"])
        repl, note = _replacement(r, prof_dests)
        if note:
            notes.append(note)
        elif repl in dsts:
            retire.append({"path": str(r["path"]), "sha256": str(r["sha256"])})
        else:
            notes.append("retire %s не проецируется: замены %s в манифесте нет" % (r["path"], repl))
    for r in doc.get("supersedes") or []:
        if str(r["path"]) in managed:
            supers.append({"path": str(r["path"]), "sha256": str(r["sha256"])})
        else:
            notes.append("supersedes %s не проецируется: назначения роли managed нет" % r["path"])
    return retire, supers, notes


def build(bot_dir, kit_version, require_profiles=False):
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
    kit_root = os.path.dirname(bot_dir)
    prof_entries, note, binding = _profile_entries(kit_root, require_profiles)
    entries += prof_entries
    entries.sort(key=lambda e: e["src"])
    retire, supers, notes = _retire(os.path.join(bot_dir, "kit"), entries, _profile_destinations(kit_root))
    for n in ([note] if note else notes):          # без выходов генератора причина одна — она и печатается
        sys.stderr.write("build_manifest: %s\n" % n)
    dsts = [e["dst"] for e in entries]
    if len(dsts) != len(set(dsts)):
        dup = sorted(d for d in dsts if dsts.count(d) > 1)
        raise SystemExit("манифест: два источника на одно назначение: %s" % dup)
    doc = {
        "schema_version": 1,
        "kit_version": kit_version,
        "kit_schema_version": KIT_SCHEMA_VERSION,
        "workflows_dir": WORKFLOWS_DIR,
    }
    if binding:
        doc["customer_layer"] = binding
    doc["entries"] = entries
    if retire:
        doc["retire"] = retire
    if supers:
        doc["supersedes"] = supers
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_manifest.py")
    ap.add_argument("--kit", default=_HERE, help="каталог bot/kit (по умолчанию — рядом с генератором)")
    ap.add_argument("--kit-version", default="0.1.0")
    ap.add_argument("--out", default=None)
    ap.add_argument("--require-profiles", action="store_true",
                    help="релиз: без выходов генератора профилей (profiles/sources-manifest.yaml) — отказ, а не примечание")
    args = ap.parse_args(argv)
    bot_dir = os.path.dirname(os.path.abspath(args.kit))
    try:
        manifest = build(bot_dir, args.kit_version, args.require_profiles)
    except Refuse as e:
        sys.stdout.write("FAIL build_manifest: %s\n" % e)
        return 2
    text = yamlmini.dumps(manifest)
    if args.out:
        with open(args.out, "wb") as fh:
            fh.write(text.encode("utf-8"))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
