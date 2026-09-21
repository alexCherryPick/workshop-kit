#!/usr/bin/env python3
"""install.py — установщик/апдейтер комплекта, декларативно-тонкий. Владелец — T1 (D09 §1Д, §3).

Ничего не решает сам: манифест `kit/manifest.yaml` (генерируется build_manifest.py на гейте T6)
говорит «путь → sha256 → назначение», этот скрипт СВЕРЯЕТ и исполняет. Подкоманды — по одной
на шаг bootstrap-обёртки (предикат тонкой обёртки §2: один вызов на шаг, без аргументов-политик):

  check-kit-ref   HEAD checkout'а комплекта == kit.ref из kit/validator-release.yaml (пин комплекта);
                  плейсхолдер вместо SHA — отказ «пин не заполнен», не пропуск
  check-secrets   имена секретов из kit/install-steps.yaml присутствуют в окружении (значения не
                  печатаются): по реестру secrets И по шагам (поле required_secrets)
  layout          раскладка комплекта по манифесту: сверка sha256 источников, ДИФФ, запись;
                  роли config/state создаются только при отсутствии и далее не трогаются;
                  роль manual (bootstrap-обёртка, карта людей) никогда не пишется; пути назначений
                  проходят safe_path (без `..`, абсолютных, .git/ и симлинков).
                  ФОРМА ЗАПУСКА (D15 T4, REQ-100; контракт D15 §4.10): настройка `launch: ci|daemon`
                  верхнего уровня .workshop/bot.yaml (отсутствие поля = ci; иное значение — отказ до
                  мутаций). При daemon назначения роли workflow НЕ создаются, а лежащие УПРАВЛЯЕМЫЕ
                  (реестр workflow_destinations в kit-version.yaml ∪ назначения манифеста) удаляются —
                  bootstrap (роль manual) и чужие workflow не трогаются; удаления — в плане, диффе,
                  dry-run и коммите. kit-version.yaml несёт `launch` последней раскладки и реестр
                  `workflow_destinations` (не забывается после удаления)
  validator       скачать пиннованный релизный бинарь (только https, без небезопасного редиректа)
                  и СВЕРИТЬ sha256 по kit/validator-release.yaml; несовпадение, плейсхолдер или
                  нулевой дайджест — громкий отказ (rc=2); назначение — .workshop-bin/workshop-validator
                  в репозитории заказчика (каталог самоигнорируемый: .workshop-bin/.gitignore = `*`)
  check-people    .workshop/people.yaml разбирается строгим лоадером; поля; handle бота присутствует;
                  telegram_id/forge_login уникальны; есть хотя бы один role: admin с telegram_id;
                  форма запуска: явный `launch: daemon` в bot.yaml ∧ физически лежащая управляемая
                  обёртка из реестра kit-version.yaml → отказ rc=2 (два читателя курсора); отсутствие
                  поля/метаданных — мягкая заметка; несовпадение формы с последней раскладкой — заметка
  commit          закоммитить и (при наличии origin) запушить разложенный комплект; tracked-удаления
                  обёрток (daemon) захватываются точными путями, посторонний staged-файл — нет

Коды выхода: 0 — выполнено; 2 — отказ с названной причиной (ничего не записано сверх сказанного);
10 — сбой самого инструмента (исключение). Пути: --kit (по умолчанию каталог этого файла),
--repo (по умолчанию текущий каталог). Все опции необязательны — bootstrap зовёт без них.
"""
import argparse
import difflib
import hashlib
import os
import re
import subprocess
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402
import identity  # noqa: E402

KIT_VERSION_FILE = ".workshop/kit-version.yaml"
PEOPLE_FILE = ".workshop/people.yaml"
BOT_CONFIG_FILE = ".workshop/bot.yaml"
VALIDATOR_BIN_DIR = ".workshop-bin"
VALIDATOR_BIN_NAME = "workshop-validator"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_PERSON_HANDLE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")          # грамматика person имени файла (01-file-layout.md:139-145)
_AUTHOR_HANDLE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}$")        # грамматика author конверта (envelope-fields.yaml:213)
_OVERWRITE_ROLES = ("code", "hook", "policy", "workflow")
# файлы, которыми релизный коммит МОЖЕТ отличаться от кодового коммита kit.ref (check-kit-ref)
RELEASE_LAYER_PATHS = ("bot/kit/validator-release.yaml", "bot/kit/workflows/bootstrap.yml",
                       "bot/kit/workflows/poller.yml", "bot/kit/workflows/heartbeat.yml",
                       "bot/kit/manifest.yaml")
_KEEP_ROLES = ("config", "state")
_MANUAL_ROLE = "manual"
_WORKFLOW_ROLE = "workflow"
LAUNCH_FORMS = ("ci", "daemon")          # закрытое множество значений bot.yaml launch (D15 §4.10); умолчание — ci
LAUNCH_DEFAULT = "ci"


class Refuse(Exception):
    """Отказ с названной причиной → rc=2."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as fh:
        return sha256_bytes(fh.read())


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _say(msg):
    sys.stdout.write(msg + "\n")


def path_key(rel):
    """Ключ сравнения путей: NFC + casefold — на case-insensitive/NFD-нормализующих ФС (macOS APFS) разные написания
    одного файла суть один файл (T4 раунд 2: `.GitHub/…`, NFD-имя обходили сравнение с manual и уникальность).
    Консервативно: два написания, равные по ключу, считаются одним путём и на case-sensitive ФС."""
    import unicodedata
    return unicodedata.normalize("NFC", str(rel)).casefold()


def safe_path(root, relative):
    """Путь назначения внутри репозитория заказчика: относительный, без `..`, не в .git/, без
    симлинков на пути (существующих). Возвращает абсолютный путь; иначе Refuse."""
    rel = str(relative)
    parts = rel.split("/")
    # каноническая форма: без `./`, `//`, хвостового `/`, `..`, абсолютных и `~`; `.git` — в ЛЮБОЙ компоненте; без глобов и
    # magic pathspec git (`*?[]:` и `\`), без управляющих символов — иначе эквивалентное написание обходит сравнение путей
    # (manual, уникальность) и `git add -- <путь>` толкует путь как шаблон (T4 раунд 1, astra: BLOCKER ×3)
    keys = [path_key(p) for p in parts]
    root_abs = os.path.realpath(root)  # realpath: корень mktemp на macOS сам лежит за симлинком /var → /private/var
    try:
        name_max, path_max = os.pathconf(root_abs, "PC_NAME_MAX"), os.pathconf(root_abs, "PC_PATH_MAX")
    except (OSError, ValueError, AttributeError):
        name_max, path_max = 255, 1024
    abs_len = len(os.path.join(root_abs, *parts).encode("utf-8")) if parts and "" not in parts else 0
    bad = (rel == "" or os.path.isabs(rel) or rel.startswith("~") or ".." in parts or "." in parts or "" in parts
           or ".git" in keys or rel != os.path.normpath(rel) or any(c in rel for c in "*?[]:\\")
           or any(ord(c) < 32 or c == "\x7f" for c in rel)
           or any(len(p.encode("utf-8")) > name_max for p in parts) or abs_len >= path_max)   # лимиты ФС — АБСОЛЮТНОГО пути (T4 раунд 3)
    if bad:
        raise Refuse("небезопасный путь назначения в манифесте: %r (требуется каноническая относительная форма; запрещены `..`, `.`, абсолютные, `.git/` в любом регистре, глобы и magic pathspec; лимиты ФС: компонента ≤ %d байт, абсолютный путь < %d байт)" % (rel, name_max, path_max))
    dest = os.path.join(root_abs, *parts)
    probe = root_abs
    for p in parts:
        probe = os.path.join(probe, p)
        if os.path.islink(probe):
            raise Refuse("небезопасный путь назначения в манифесте: %r — симлинк на пути (%s)" % (rel, os.path.relpath(probe, root_abs)))
    if os.path.commonpath([root_abs, os.path.realpath(dest)]) != root_abs:
        raise Refuse("небезопасный путь назначения в манифесте: %r — выходит за корень репозитория" % rel)
    return dest


# ------------------------------------------------------------------ check-kit-ref
def _git(repo, *argv):
    return subprocess.run(["git", "-C", repo] + list(argv), capture_output=True, text=True)


def _kit_root(args):
    # манифест адресует источники как bot/<...>; корень комплекта — родитель каталога bot/
    return os.path.dirname(os.path.dirname(os.path.abspath(args.kit)))


def cmd_check_kit_ref(args):
    rel_path = args.release or os.path.join(args.kit, "validator-release.yaml")
    doc = yamlmini.load_file(rel_path)
    kit = doc.get("kit") if isinstance(doc, dict) else None
    if not isinstance(kit, dict) or not kit.get("repository") or not kit.get("ref"):
        raise Refuse("validator-release.yaml: нет блока kit {repository, ref} — пин комплекта не объявлен")
    expected = str(kit["ref"])
    if not _HEX40.match(expected):
        raise Refuse("пин комплекта не заполнен: kit.ref = %r не является полным SHA коммита — релиз обязан его заполнить, сверять не с чем" % expected)
    if expected == "0" * 40:
        raise Refuse("пин комплекта — нулевой SHA (%s): плейсхолдер печатью, а не пин" % expected)
    kit_root = args.kit_checkout or _kit_root(args)
    r = _git(kit_root, "rev-parse", "HEAD")
    if r.returncode != 0:
        raise Refuse("checkout комплекта %s не является git-репозиторием — пин не проверить: %s" % (kit_root, r.stderr.strip()))
    actual = r.stdout.strip()
    layer_note = ""
    if actual != expected:
        # РЕЛИЗНЫЙ СЛОЙ (находка живого прогона 2026-09-08): манифест не может назвать SHA собственного
        # коммита, поэтому релиз — это коммит R РОВНО НАД кодовым коммитом K = kit.ref, и R отличается от K
        # ТОЛЬКО файлами пинов (манифест релиза, обёртка с пинами, манифест комплекта). Любой иной файл в
        # R — отказ: код обязан быть тем самым K, который назван манифестом.
        parent = _git(kit_root, "rev-parse", "HEAD^")
        if parent.returncode != 0:
            shallow = _git(kit_root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
            if shallow:
                raise Refuse("пин комплекта: HEAD checkout'а %s без родителя (МЕЛКИЙ клон) — релизный слой над kit.ref %s не проверить; checkout комплекта обязан быть глубиной 2 (fetch-depth: 2 в обёртке)" % (actual[:12], expected[:12]))
            raise Refuse("пин комплекта расходится: HEAD checkout'а %s (корневой коммит), манифест релиза kit.ref %s" % (actual, expected))
        if parent.stdout.strip() != expected:
            raise Refuse("пин комплекта расходится: HEAD checkout'а %s, манифест релиза kit.ref %s (и HEAD не релизный слой над ним)" % (actual, expected))
        changed = _git(kit_root, "diff", "--name-only", expected, actual).stdout.split()
        extra = sorted(set(changed) - set(RELEASE_LAYER_PATHS))
        if extra:
            raise Refuse("релизный коммит %s меняет не только пины над kit.ref %s: %s — код обязан быть кодовым коммитом манифеста" % (actual[:12], expected[:12], ", ".join(extra)))
        layer_note = " (HEAD %s — релизный слой над kit.ref: изменены только %s)" % (actual[:12], ", ".join(changed) or "ничего")
    r = _git(kit_root, "remote", "get-url", "origin")
    if r.returncode == 0:
        url = r.stdout.strip()
        repo_name = str(kit["repository"])
        tail = url[:-4] if url.endswith(".git") else url
        if not (tail.endswith("/" + repo_name) or tail.endswith(":" + repo_name)):
            raise Refuse("репозиторий checkout'а комплекта (%s) не совпадает с kit.repository %s" % (url, repo_name))
        _say("check-kit-ref: ok — kit.ref %s, origin == kit.repository %s%s" % (expected, repo_name, layer_note))
    else:
        _say("check-kit-ref: ok — kit.ref %s (origin отсутствует — локальный прогон, репозиторий не сверялся)%s" % (expected, layer_note))


# ------------------------------------------------------------------ check-secrets
def cmd_check_secrets(args):
    steps_doc = yamlmini.load_file(os.path.join(args.kit, "install-steps.yaml"))
    secrets = steps_doc.get("secrets") or []
    by_name = dict((s["name"], s) for s in secrets)
    present = dict((n, bool(os.environ.get(n))) for n in by_name)

    def satisfied(name):
        if present.get(name):
            return name
        alt = by_name[name].get("alternative")
        if alt and present.get(alt):
            return alt
        return None

    for s in secrets:
        _say("secret %s: %s" % (s["name"], "present" if present[s["name"]] else "absent"))
    missing = []
    for s in secrets:
        if s.get("required"):
            got = satisfied(s["name"])
            if got is None:
                alt = s.get("alternative")
                missing.append(s["name"] + ((" (или %s)" % alt) if alt else ""))
            elif got != s["name"]:
                _say("secret %s: absent, but alternative %s present — ok" % (s["name"], got))
    # по шагам: поле required_secrets — имена из реестра secrets (второй копии имён нет)
    for st in steps_doc.get("steps") or []:
        req = st.get("required_secrets") or []
        for name in req:
            if name not in by_name:
                raise Refuse("шаг %s требует секрет %s, которого нет в реестре secrets" % (st["id"], name))
            got = satisfied(name)
            _say("step %s: %s %s" % (st["id"], name, ("present" if got == name else "alternative %s present" % got) if got else "ABSENT"))
            if got is None:
                entry = name + ((" (или %s)" % by_name[name]["alternative"]) if by_name[name].get("alternative") else "")
                if entry not in missing:
                    missing.append(entry)
    if missing:
        raise Refuse("отсутствуют обязательные секреты CI: %s" % ", ".join(missing))
    _say("check-secrets: ok (%d имён в реестре)" % len(by_name))


# ------------------------------------------------------------------ layout
def _load_manifest(args):
    path = args.manifest or os.path.join(args.kit, "manifest.yaml")
    if not os.path.exists(path):
        raise Refuse("манифест комплекта отсутствует: %s (генерируется build_manifest.py на гейте T6)" % path)
    m = yamlmini.load_file(path)
    for k in ("schema_version", "kit_version", "kit_schema_version", "entries"):
        if k not in m:
            raise Refuse("манифест без поля %r: %s" % (k, path))
    return m


def _installed_version(repo):
    p = os.path.join(repo, KIT_VERSION_FILE)
    if not os.path.exists(p):
        return None
    if os.path.isdir(p):
        raise Refuse("%s — каталог, а не файл метаданных установки; отказ до мутаций" % KIT_VERSION_FILE)
    return yamlmini.load_file(p)


# ------------------------------------------------------------------ форма запуска (D15 T4, REQ-100)
def explicit_launch(repo):
    """Явное значение `launch` из .workshop/bot.yaml: 'ci' | 'daemon' | None (нет файла или поля).
    Значение вне закрытого множества — отказ конфигурации (до любых мутаций)."""
    cfg_path = os.path.join(repo, BOT_CONFIG_FILE)
    if not os.path.exists(cfg_path):
        return None
    cfg = yamlmini.load_file(cfg_path)
    if not isinstance(cfg, dict) or "launch" not in cfg:
        return None
    v = cfg.get("launch")
    if v not in LAUNCH_FORMS:
        raise Refuse("в %s launch = %r — не %s (форма запуска поллера: ci — обёртки CI, daemon — демон заказчика)"
                     % (BOT_CONFIG_FILE, v, "|".join(LAUNCH_FORMS)))
    return v


def _manual_destinations(m):
    return set(str(e["dst"]) for e in m["entries"] if e["role"] == _MANUAL_ROLE)


def _check_manifest_destinations(m):
    """Назначения манифеста уникальны в канонической форме (повтор — противоречие манифеста, не «set» молча; T4 раунд 1);
    ни одно назначение не лежит ВНУТРИ другого как в каталоге (a и a/b — коллизия файла и каталога; T4 раунд 7)."""
    seen = set()
    for e in m["entries"]:
        d = str(e["dst"])
        k = path_key(d)
        if k in seen:
            raise Refuse("манифест: назначение %s повторяется (с точностью до регистра/нормализации) — противоречие манифеста" % d)
        seen.add(k)
    for k in seen:
        if any(o.startswith(k + "/") for o in seen):
            raise Refuse("манифест: назначение %s одновременно файл и каталог другого назначения — противоречие манифеста" % k)


def installed_launch_meta(repo, installed, manual_dsts):
    """Метаданные формы запуска последней раскладки из kit-version.yaml → (launch|None, [destinations]|None).
    Отсутствие файла/полей — (None, None): мягкая ветвь (старая установка). Синтаксически повреждённые поля
    или небезопасные пути — отказ проверки метаданных, не ветвь совместимости (§4.10). Ручные назначения —
    manual_dsts манифеста ∪ manual_destinations kit-version (защита bootstrap и без манифеста; T4 раунд 1)."""
    if installed is None or not isinstance(installed, dict):
        return None, None
    present = [k for k in ("launch", "workflow_destinations", "manual_destinations") if k in installed]
    if not present:
        return None, None                        # старая установка без новых полей — мягкая ветвь
    if len(present) != 3:                        # частичный набор — layout так не пишет: метаданные повреждены (T4 раунд 2)
        raise Refuse("%s: метаданные формы запуска неполны (есть %s) — повреждены; повторите layout" % (KIT_VERSION_FILE, ", ".join(present)))
    launch = installed.get("launch")
    dests = installed.get("workflow_destinations")
    stored_manual = installed.get("manual_destinations")
    if not isinstance(stored_manual, list) or not all(isinstance(d, str) and d for d in stored_manual):
        raise Refuse("%s: manual_destinations не список путей — метаданные повреждены; повторите layout" % KIT_VERSION_FILE)
    for d in stored_manual:
        safe_path(repo, d)
    manual_dsts = set(manual_dsts) | set(stored_manual)   # ручные файлы известны и без манифеста (установленный checkout)
    if launch not in LAUNCH_FORMS:
        raise Refuse("%s: launch = %r повреждён (ожидалось %s) — метаданные формы запуска не читаются; повторите layout" % (KIT_VERSION_FILE, launch, "|".join(LAUNCH_FORMS)))
    if not isinstance(dests, list) or not all(isinstance(d, str) and d for d in dests):
        raise Refuse("%s: workflow_destinations не список путей — метаданные обёрток повреждены; повторите layout" % KIT_VERSION_FILE)
    if len(set(dests)) != len(dests):
        raise Refuse("%s: workflow_destinations содержит повторы — метаданные обёрток повреждены" % KIT_VERSION_FILE)
    manual_keys = set(path_key(m) for m in manual_dsts)
    seen_keys = set()
    for d in dests:
        p = safe_path(repo, d)                   # относительность, .git/, `..`, симлинки, выход за корень
        k = path_key(d)
        if k in manual_keys:
            raise Refuse("%s: workflow_destinations называет ручной файл %s (роль manual, с учётом регистра/нормализации) — управляемым он быть не может" % (KIT_VERSION_FILE, d))
        if k in seen_keys:
            raise Refuse("%s: workflow_destinations содержит повторы с точностью до регистра/нормализации: %s" % (KIT_VERSION_FILE, d))
        seen_keys.add(k)
        _check_write_target(repo, d)           # каталог на диске/в индексе (в т. ч. скрытый файлом), родитель-файл — отказ (T4 раунды 3–6)
        for m in manual_dsts:                    # физический алиас (samefile) существующего ручного файла — тоже он
            mp = os.path.join(os.path.realpath(repo), *m.split("/"))
            if os.path.exists(p) and os.path.exists(mp) and os.path.samefile(p, mp):
                raise Refuse("%s: назначение %s физически совпадает с ручным файлом %s — управляемым оно быть не может" % (KIT_VERSION_FILE, d, m))
    return launch, list(dests)


def _kit_version_text(m, launch, destinations):
    """Текст kit-version.yaml: прежние поля версии + форма последней раскладки + реестр управляемых обёрток
    (уникальный, по байтам пути; сохраняется и после удаления файлов при daemon) + ручные назначения манифеста
    (роль manual — известны check-people и без манифеста)."""
    doc = {"kit_version": m["kit_version"], "kit_schema_version": m["kit_schema_version"],
           "manifest_schema_version": m["schema_version"], "launch": launch,
           "workflow_destinations": sorted(set(destinations), key=lambda s: s.encode("utf-8")),
           "manual_destinations": sorted(_manual_destinations(m), key=lambda s: s.encode("utf-8"))}
    return yamlmini.dumps(doc).encode("utf-8")


def _diff_text(old, new, dst):
    try:
        a = old.decode("utf-8").splitlines(True)
        b = new.decode("utf-8").splitlines(True)
    except UnicodeDecodeError:
        return ["  (бинарное содержимое: %s → %s)" % (sha256_bytes(old)[:12], sha256_bytes(new)[:12])]
    return ["  " + l.rstrip("\n") for l in difflib.unified_diff(a, b, "a/" + dst, "b/" + dst, n=1)]


def cmd_layout(args):
    m = _load_manifest(args)
    kit_root = _kit_root(args)
    repo = os.path.abspath(args.repo)
    installed = _installed_version(repo)
    if installed is not None and installed.get("kit_schema_version") != m["kit_schema_version"]:
        raise Refuse("несовместимая схема комплекта: установлена %r, в комплекте %r — миграция объявляется явно и автоматически не выполняется"
                     % (installed.get("kit_schema_version"), m["kit_schema_version"]))
    # 0) форма запуска — ДО мутаций: явная настройка заказчика; отсутствие поля = ci (умолчание шаблона)
    _check_manifest_destinations(m)
    manual_dsts = _manual_destinations(m)
    launch = explicit_launch(repo)
    if launch is None:
        _say("~ форма запуска: launch в %s не задан — раскладка ci (обёртки CI); для демона задайте launch: daemon" % BOT_CONFIG_FILE)
        launch = LAUNCH_DEFAULT
    prev_launch, prev_dests = installed_launch_meta(repo, installed, manual_dsts)
    manifest_wf = [str(e["dst"]) for e in m["entries"] if e["role"] == _WORKFLOW_ROLE]
    manual_keys = set(path_key(x) for x in manual_dsts)
    for d in manifest_wf:
        if path_key(d) in manual_keys:
            raise Refuse("манифест: назначение %s и роль workflow, и роль manual — противоречие манифеста" % d)
    # реестр УПРАВЛЯЕМЫХ обёрток: назначения манифеста ∪ сохранённые прежней установкой (не забываются после удаления)
    merged = {}
    for d in list(manifest_wf) + list(prev_dests or []):
        merged.setdefault(path_key(d), d)        # одно написание на ключ (регистр/нормализация)
    destinations = sorted(merged.values(), key=lambda s: s.encode("utf-8"))
    _say("форма запуска: %s%s; управляемых обёрток в реестре: %d" % (
        launch, ("" if prev_launch is None else " (последняя раскладка: %s)" % prev_launch), len(destinations)))
    # 1) целостность источников и безопасность назначений — ДО любой записи (в т. ч. длина путей: ENAMETOOLONG после
    #    удаления обёрток недопустим — T4 раунд 2)
    _check_write_target(repo, KIT_VERSION_FILE)   # служебное назначение — тем же предикатом (T4 раунд 6)
    for d in destinations:
        p = _check_write_target(repo, d)
        for mdst in manual_dsts:
            mp = os.path.join(os.path.realpath(repo), *mdst.split("/"))
            if os.path.exists(p) and os.path.exists(mp) and os.path.samefile(p, mp):
                raise Refuse("назначение %s физически совпадает с ручным файлом %s — удалять его нельзя" % (d, mdst))
    for e in m["entries"]:
        src = os.path.join(kit_root, e["src"])
        if not os.path.exists(src):
            raise Refuse("источник манифеста отсутствует в комплекте: %s" % e["src"])
        actual = sha256_file(src)
        if actual != e["sha256"]:
            raise Refuse("комплект не совпадает с манифестом: %s sha256 %s ≠ %s" % (e["src"], actual, e["sha256"]))
        if e["role"] != _MANUAL_ROLE:
            _check_write_target(repo, e["dst"])   # каталог на диске/в индексе, родитель-файл — отказ до мутаций
            if not isinstance(e.get("mode"), str) or not re.match(r"^0?[0-7]{3}$", e["mode"]):
                raise Refuse("манифест: mode %r у %s не строка восьмеричных цифр — отказ до мутаций" % (e.get("mode"), e["dst"]))
        else:
            safe_path(repo, e["dst"])
        # обёртка с НЕЗАПОЛНЕННЫМ пином ставиться НЕ ДОЛЖНА: в репозитории заказчика она даёт загадочный
        # отказ CI («unable to resolve action»), а не названную причину (живой прогон 2026-09-12).
        # Пины заполняет РЕЛИЗ (scripts/mirror_kit.sh, коммит релизного слоя), шаблон в монорепо их держит.
        if e["role"] == "workflow":
            body = _read(src).decode("utf-8", "replace")
            unfilled = sorted(set(re.findall(r"PIN-[A-Z0-9-]+", body)))
            if unfilled:
                if not getattr(args, "allow_unfilled_pins", False):
                    raise Refuse("обёртка %s несёт НЕЗАПОЛНЕННЫЕ пины %s — комплект НЕ ВЫПУЩЕН релизом; установка отказана (пины заполняет релизный коммит канала выдачи; для прогонов по шаблону монорепо — layout --allow-unfilled-pins)"
                                 % (e["src"], ", ".join(unfilled)))
                _say("! %s: НЕЗАПОЛНЕННЫЕ пины %s — прогон по ШАБЛОНУ (--allow-unfilled-pins); в репозиторий заказчика такой комплект не ставится"
                     % (e["src"], ", ".join(unfilled)))
    # 2) план и дифф
    counts = {"create": 0, "update": 0, "same": 0, "keep": 0, "manual": 0, "remove": 0}
    actions = []
    removals = []
    if launch == "daemon":
        # daemon: назначения роли workflow не создаются; лежащие УПРАВЛЯЕМЫЕ удаляются (только пути реестра —
        # bootstrap (manual) и чужие workflow не трогаются); удаление — в плане, диффе, dry-run и коммите
        for d in destinations:
            p = safe_path(repo, d)
            if os.path.exists(p):
                counts["remove"] += 1
                _say("- %s (workflow: удаляется — launch: daemon, второго читателя курсора рядом с демоном не будет)" % d)
                for l in _diff_text(_read(p), b"", d):
                    _say(l)
                removals.append(p)
            else:
                _say("  %s: обёртки нет (launch: daemon) — не создаётся" % d)
    for e in m["entries"]:
        src = os.path.join(kit_root, e["src"])
        dst = safe_path(repo, e["dst"])
        new = _read(src)
        exists = os.path.exists(dst)
        role = e["role"]
        if role == _MANUAL_ROLE:
            counts["manual"] += 1
            if not exists:
                _say("! %s: ручной файл, ОТСУТСТВУЕТ (его кладёт заказчик — шаг реестра install-steps.yaml)" % e["dst"])
            else:
                _say("! %s: ручной файл присутствует, комплект его не трогает (%s шаблону комплекта)"
                     % (e["dst"], "равен" if sha256_file(dst) == e["sha256"] else "не равен"))
            continue
        if role == _WORKFLOW_ROLE and launch == "daemon":
            continue                       # уже названо в плане удалений/несоздания выше
        if not exists:
            counts["create"] += 1
            _say("+ %s (%s)" % (e["dst"], role))
            actions.append((dst, new, e["mode"]))
            continue
        old = _read(dst)
        if role in _KEEP_ROLES:
            counts["keep"] += 1
            _say("= %s (%s: файл заказчика, не трогается)" % (e["dst"], role))
            continue
        if role not in _OVERWRITE_ROLES:
            raise Refuse("неизвестная роль манифеста %r у %s" % (role, e["dst"]))
        if old == new:
            counts["same"] += 1
            _say("  %s: без изменений" % e["dst"])
            continue
        counts["update"] += 1
        _say("~ %s (%s)" % (e["dst"], role))
        for l in _diff_text(old, new, e["dst"]):
            _say(l)
        actions.append((dst, new, e["mode"]))
    # 3) версия установки — тоже через дифф (форма последней раскладки + реестр управляемых обёрток)
    ver_text = _kit_version_text(m, launch, destinations)
    ver_path = safe_path(repo, KIT_VERSION_FILE)
    if not os.path.exists(ver_path) or _read(ver_path) != ver_text:
        _say(("+" if not os.path.exists(ver_path) else "~") + " %s" % KIT_VERSION_FILE)
        if os.path.exists(ver_path):
            for l in _diff_text(_read(ver_path), ver_text, KIT_VERSION_FILE):
                _say(l)
        actions.append((ver_path, ver_text, "0644"))
    summary = "create=%d update=%d same=%d keep=%d manual=%d remove=%d" % tuple(counts[k] for k in ("create", "update", "same", "keep", "manual", "remove"))
    if args.dry_run:
        _say("layout (dry-run): %s" % summary)
        return
    for p in removals:
        os.remove(p)
    for dst, data, mode in actions:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        os.chmod(dst, int(mode, 8))
    _say("layout: %s — %s" % (summary, "без изменений" if not actions and not removals
                                else "записано файлов: %d, удалено: %d" % (len(actions), len(removals))))


# ------------------------------------------------------------------ validator
def host_target():
    """Тройка бинаря для ХОСТА: CI заказчика — linux x86_64, клон подрядчика на macOS arm64 — darwin (пост-D09, paste-тест
    2026-09-14: установщик клал linux-бинарь на Mac → exec format error). Неизвестный хост — явный отказ, не молчаливый linux."""
    import platform
    m = platform.machine().lower(); s = sys.platform
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(m)
    if arch is None:
        raise Refuse("неизвестная архитектура хоста %r — укажите --target явно" % m)
    if s.startswith("linux"):
        return "%s-unknown-linux-gnu" % arch
    if s == "darwin":
        return "%s-apple-darwin" % arch
    raise Refuse("неизвестная ОС хоста %r — укажите --target явно" % s)


def _pick_artifact(release_doc, target):
    pinned = str(release_doc.get("pinned_version"))
    for r in release_doc.get("releases") or []:
        if str(r.get("version")) == pinned:
            for a in r.get("artifacts") or []:
                if a.get("target") == target:
                    return pinned, a
            raise Refuse("в релизе %s нет артефакта для цели %s" % (pinned, target))
    raise Refuse("пиннованная версия %s отсутствует в validator-release.yaml" % pinned)


def _fetch_https(url, timeout_s):
    if not url.startswith("https://"):
        raise Refuse("источник бинаря валидатора не https: %r — скачивание отказано" % url)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        final = resp.geturl()
        if not str(final).startswith("https://"):
            raise Refuse("небезопасный редирект при скачивании бинаря валидатора: %r → %r — отказано" % (url, final))
        return resp.read()


def cmd_validator(args):
    rel_path = args.release or os.path.join(args.kit, "validator-release.yaml")
    doc = yamlmini.load_file(rel_path)
    if not args.target:
        args.target = host_target()
    version, art = _pick_artifact(doc, args.target)
    for k in ("sha256", "purpose"):
        if k not in art:
            raise Refuse("артефакт %s/%s без поля %r" % (version, args.target, k))
    if "url" not in art and "path" not in art:
        raise Refuse("артефакт %s/%s без url и без path" % (version, args.target))
    expected = str(art["sha256"])
    if not _HEX64.match(expected):
        raise Refuse("validator-release.yaml: sha256 для %s/%s не является дайджестом (%r) — сверять не с чем, установка отказана"
                     % (version, args.target, expected))
    if expected == "0" * 64:
        raise Refuse("validator-release.yaml: sha256 для %s/%s — нулевой дайджест (%s): плейсхолдер печатью, сверять не с чем, установка отказана"
                     % (version, args.target, expected))
    repo = os.path.abspath(args.repo)
    if args.dest:
        dest = os.path.abspath(args.dest)
        ignore_file = None
    else:
        dest = safe_path(repo, VALIDATOR_BIN_DIR + "/" + VALIDATOR_BIN_NAME)
        ignore_file = safe_path(repo, VALIDATOR_BIN_DIR + "/.gitignore")
    if args.path:
        data = _read(args.path)
        source = args.path
    elif "path" in art and art["path"]:
        data = _read(os.path.join(os.path.dirname(rel_path), art["path"]))
        source = art["path"]
    else:
        source = art["url"]
        data = _fetch_https(source, args.timeout_s)
    actual = sha256_bytes(data)
    if actual != expected:
        raise Refuse("sha256 бинаря валидатора НЕ СОВПАЛ: ожидалось %s, получено %s (источник %s, версия %s) — без валидатора не продолжаем"
                     % (expected, actual, source, version))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if ignore_file is not None and not os.path.exists(ignore_file):
        with open(ignore_file, "wb") as fh:
            fh.write(b"*\n")  # каталог самоигнорируемый: бинарь в коммит не попадает, чужой .gitignore не трогается
    with open(dest, "wb") as fh:
        fh.write(data)
    os.chmod(dest, 0o755)
    _say("validator %s (%s): sha256 совпал (%s), положен в %s" % (version, args.target, actual, dest))


# ------------------------------------------------------------------ check-people
def _zone_ok(tz):
    return identity._zone_ok(str(tz))


def check_people_doc(doc, bot_handle):
    """Проверка формы карты — ОДНА на комплект: identity.validate_people_doc (поллер зовёт её же на каждом прогоне)."""
    try:
        return identity.validate_people_doc(doc, bot_handle, require_admin=True)
    except ValueError as e:
        raise Refuse(str(e))


def cron_period_minutes(workflow_text):
    """Период cron обёртки в минутах для форм `*/N` в поле минут или часов (`M */H * * *`); иная форма → None (не сверяется)."""
    import re as _re
    m = _re.search(r'cron:\s*"([^"]+)"', workflow_text)
    if not m:
        return None
    fields = m.group(1).split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:   # календарные ограничения (день/месяц/день недели) — период не постоянен (раунд 5 W3)
        return None
    minute, hour = fields[0], fields[1]
    dec = _re.compile(r"^[0-9]{1,2}$")   # ASCII-десятичные поля с диапазонами (раунд 6 Codex W2): минута 0–59, час 0–23, шаг в диапазоне поля
    if minute.startswith("*/") and dec.match(minute[2:]) and 1 <= int(minute[2:]) <= 59 and hour == "*":
        return int(minute[2:])
    if hour.startswith("*/") and dec.match(hour[2:]) and 1 <= int(hour[2:]) <= 23 and dec.match(minute) and 0 <= int(minute) <= 59:
        return int(hour[2:]) * 60
    return None


def cmd_check_people(args):
    repo = os.path.abspath(args.repo)
    people_path = os.path.join(repo, PEOPLE_FILE)
    cfg_path = os.path.join(repo, BOT_CONFIG_FILE)
    if not os.path.exists(people_path):
        raise Refuse("карты людей нет: %s — бот не знает, чьи часы; положите её из шаблона комплекта (ручной шаг people_map реестра install-steps.yaml)" % PEOPLE_FILE)
    if not os.path.exists(cfg_path):
        raise Refuse("настроек комплекта нет: %s" % BOT_CONFIG_FILE)
    cfg = yamlmini.load_file(cfg_path)
    bot_handle = cfg.get("bot_handle")
    if not bot_handle:
        raise Refuse("в %s нет bot_handle" % BOT_CONFIG_FILE)
    if cfg.get("self_registration") not in ("on", "off"):
        raise Refuse("в %s self_registration не on|off" % BOT_CONFIG_FILE)
    # форма запуска (D15 §4.10): источник набора управляемых обёрток — ТОЛЬКО kit-version.yaml установленного
    # checkout (манифеста у заказчика нет); строгий отказ — только явный daemon ∧ физически лежащая обёртка реестра
    launch = explicit_launch(repo)
    installed = _installed_version(repo)
    manual_dsts = set()
    manifest_path = args.manifest or os.path.join(args.kit, "manifest.yaml")
    if os.path.exists(manifest_path):
        try:
            manual_dsts = _manual_destinations(_load_manifest(args))
        except Refuse:
            manual_dsts = set()
    laid_launch, dests = installed_launch_meta(repo, installed, manual_dsts)
    if launch is None:
        _say("~ форма запуска: launch в %s не задан — умолчание ci (обёртки CI); для демона задайте launch: daemon" % BOT_CONFIG_FILE)
    if laid_launch is None:
        _say("~ метаданные формы запуска/обёрток отсутствуют в %s (старая установка) — требуется layout; ручным списком путей они не заменяются" % KIT_VERSION_FILE)
    else:
        present = [d for d in dests if os.path.exists(safe_path(repo, d))]
        if launch is not None and launch != laid_launch:
            _say("~ форма запуска изменена: %s launch: %s, последняя раскладка: %s — требуется layout" % (BOT_CONFIG_FILE, launch, laid_launch))
        if launch == "daemon" and present:
            raise Refuse("launch: daemon, но управляемые обёртки CI лежат в репозитории: %s — два читателя курсора рядом с демоном; выполните layout (при daemon он их удаляет) и закоммитьте удаление"
                         % ", ".join(present))
        _say("форма запуска: %s (раскладка: %s); управляемых обёрток в реестре %d, лежит %d" % (launch or "ci (умолчание)", laid_launch, len(dests), len(present)))
    if not _zone_ok(str(cfg.get("default_timezone"))):
        raise Refuse("в %s default_timezone не IANA-зона" % BOT_CONFIG_FILE)
    wd = cfg.get("watchdog") if isinstance(cfg.get("watchdog"), dict) else {}
    alarm_to = wd.get("alarm_to")
    if not (alarm_to == "admins" or (isinstance(alarm_to, int) and not isinstance(alarm_to, bool))):
        raise Refuse("в %s watchdog.alarm_to не `admins` и не chat_id (целое)" % BOT_CONFIG_FILE)
    def _posint(name):
        v = wd.get(name)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise Refuse("в %s watchdog.%s не положительное целое" % (BOT_CONFIG_FILE, name))
        return v
    ret = _posint("retention_window_hours"); silence = _posint("unprocessed_update_alarm_hours")
    _posint("stale_session_alarm_hours"); _posint("stale_session_repeat_hours")
    cm = wd.get("stale_session_cancel_minutes", 0)
    if not isinstance(cm, int) or isinstance(cm, bool) or cm < 0:
        raise Refuse("в %s watchdog.stale_session_cancel_minutes не целое >= 0 (минуты; 0 — без автоотмены)" % BOT_CONFIG_FILE)
    # уведомление о зависшей сессии обязано ПРЕДШЕСТВОВАТЬ автоотмене не меньше чем на период сторожа — иначе
    # предупреждение попадает лишь в часть прогонов, а отмена приходит без него (раунд 2 W2)
    if cm > 0:
        period = _posint("heartbeat_period_minutes")
        # период — не копия расписания, а сверяемое утверждение: при CI-форме источник — cron обёртки heartbeat
        # (демон сверяет свой период сам при старте; раунд 3 Codex W7)
        hb_wf = os.path.join(repo, ".github", "workflows", "workshop-bot-heartbeat.yml")
        if os.path.exists(hb_wf):
            cron_period = cron_period_minutes(open(hb_wf, encoding="utf-8").read())
            if cron_period is None:   # три исхода: сверено / расхождение / не сверяемо — последнее тоже отказ, не молчание (раунд 4 W6)
                raise Refuse("расписание обёртки сторожа (%s) не разобрано как `*/N` — период heartbeat_period_minutes не сверить" % os.path.relpath(hb_wf, repo))
            if cron_period != period:
                raise Refuse("в %s watchdog.heartbeat_period_minutes (%d) не совпадает с расписанием обёртки сторожа (%d мин по cron)" % (BOT_CONFIG_FILE, period, cron_period))
        else:
            _say("~ период сторожа: обёртки heartbeat нет (демон) — сверяет демон при старте")
        if wd.get("stale_session_alarm_hours", 0) * 60 + period > cm:
            raise Refuse("в %s окно watchdog.stale_session_alarm_hours (%d ч) → stale_session_cancel_minutes (%d мин) меньше периода сторожа heartbeat_period_minutes (%d): предупреждение не гарантировано" % (BOT_CONFIG_FILE, wd.get("stale_session_alarm_hours", 0), cm, period))
    ldn = cfg.get("last_default_n", 0)
    if not isinstance(ldn, int) or isinstance(ldn, bool) or ldn < 0:
        raise Refuse("в %s last_default_n не целое >= 0 (0 — все уникальные заголовки)" % BOT_CONFIG_FILE)
    rr = wd.get("rejection_report_min")
    if not isinstance(rr, int) or isinstance(rr, bool) or rr < 1:
        raise Refuse("в %s watchdog.rejection_report_min не целое >= 1" % BOT_CONFIG_FILE)
    # порог молчания ОБЯЗАН быть строго меньше окна retention — иначе алярм придёт после потери сообщений (T5)
    if not (silence < ret):
        raise Refuse("в %s watchdog.unprocessed_update_alarm_hours (%d) обязан быть строго меньше retention_window_hours (%d)" % (BOT_CONFIG_FILE, silence, ret))
    n, admins = check_people_doc(yamlmini.load_file(people_path), bot_handle)
    _say("check-people: ok — записей %d, handle бота %s присутствует, админов с telegram_id: %d" % (n, bot_handle, admins))


# ------------------------------------------------------------------ commit
def _check_write_target(repo, rel):
    """Единый предикат для КАЖДОЙ цели записи/удаления ДО мутаций (T4 раунды 3–6): каноничность (safe_path); не каталог на
    диске; не каталог в индексе git (в т. ч. скрытый файлом); ни одна существующая компонента-родитель — не регулярный файл."""
    p = safe_path(repo, rel)
    if os.path.isdir(p) and not os.path.islink(p):
        raise Refuse("назначение %s — каталог на диске, а файл комплекта — файл; отказ до мутаций" % rel)
    _tracked_file(repo, rel)
    root_abs = os.path.realpath(repo)
    probe = root_abs
    for part in rel.split("/")[:-1]:
        probe = os.path.join(probe, part)
        if os.path.exists(probe) and not os.path.isdir(probe):
            raise Refuse("родительская компонента %s назначения %s — не каталог; отказ до мутаций" % (os.path.relpath(probe, root_abs), rel))
    return p


def _tracked_file(repo, rel):
    """rel — файл индекса git РОВНО с этим путём (не каталог с потомками: `git ls-files -- dir` перечисляет вложенные файлы,
    а `git add -- dir` захватил бы их рекурсивно — T4 раунд 3). → True | False; каталог в индексе → Refuse."""
    r = _git(repo, "ls-files", "-z", "--", rel)
    names = [n for n in r.stdout.split("\0") if n]
    if not names:
        return False
    if names == [rel]:
        return True
    raise Refuse("путь %s — каталог в индексе git (%d вложенных файлов): рекурсивный захват в коммит установки недопустим" % (rel, len(names)))


def cmd_commit(args):
    m = _load_manifest(args)
    _check_manifest_destinations(m)
    repo = os.path.abspath(args.repo)
    installed = _installed_version(repo)
    _laid, dests = installed_launch_meta(repo, installed, _manual_destinations(m))
    # точные пути: назначения манифеста (кроме manual) + версия установки + реестр управляемых обёрток — последние
    # захватывают tracked-УДАЛЕНИЯ при daemon (фильтр по exists их потерял бы); посторонний staged-файл не захватывается
    paths = [str(e["dst"]) for e in m["entries"] if e["role"] != _MANUAL_ROLE] + [KIT_VERSION_FILE] + list(dests or [])
    for p in paths:
        ap = safe_path(repo, p)                # точные канонические пути: ни глобов, ни magic pathspec в `git add --`
        if os.path.isdir(ap) and not os.path.islink(ap):
            raise Refuse("путь %s — каталог: рекурсивный захват в коммит установки недопустим (T4 раунд 2)" % p)
    seen, ordered = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p); ordered.append(p)
    chosen = []
    for p in ordered:
        tracked = _tracked_file(repo, p)       # индекс сверяется ВСЕГДА: файл на диске может скрывать каталог в индексе (T4 раунд 4)
        if os.path.isfile(os.path.join(repo, p)) or tracked:
            chosen.append(p)
    if not chosen:                             # без единого пути git commit без pathspec взял бы чужой индекс (T4 раунд 4)
        _say("commit: путей комплекта нет ни на диске, ни в индексе — изменений нет")
        return
    r = _git(repo, "add", "--", *chosen)
    if r.returncode != 0:
        raise Refuse("git add: %s" % r.stderr.strip())
    r = _git(repo, "diff", "--cached", "--quiet", "--", *chosen)
    if r.returncode == 0:
        _say("commit: изменений нет")
        return
    removed = [p for p in chosen if not os.path.exists(os.path.join(repo, p))]
    if removed:
        _say("commit: удаления в коммите: %s" % ", ".join(removed))
    r = _git(repo, "-c", "user.name=workshop-bot-kit", "-c", "user.email=workshop-bot-kit@invalid",
             "commit", "-q", "-m", "workshop kit %s: установка/обновление комплекта" % m["kit_version"], "--", *chosen)
    if r.returncode != 0:
        raise Refuse("git commit: %s" % r.stderr.strip())
    _say("commit: создан коммит комплекта %s" % m["kit_version"])
    r = _git(repo, "remote", "get-url", "origin")
    if r.returncode != 0:
        _say("push: remote origin отсутствует — push пропущен (локальный прогон)")
        return
    r = _git(repo, "push", "-q", "origin", "HEAD")
    if r.returncode != 0:
        err = r.stderr.strip()
        hint = ""
        if "workflow" in err and ("scope" in err or "Personal Access Token" in err):
            hint = " — ПРИЧИНА: у токена CI нет права на workflow-файлы (комплект кладёт обёртки в .github/workflows/): классический токен нужен со scope repo И workflow, fine-grained — Contents: write И Workflows: write (шаг forge_credential_secret инструкции)"
        raise Refuse("git push: %s%s" % (err[:400], hint))
    _say("push: выполнен")


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="install.py")
    ap.add_argument("--kit", default=_HERE)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--manifest", default=None)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("check-kit-ref")
    p.add_argument("--release", default=None)
    p.add_argument("--kit-checkout", default=None, help="корень checkout'а комплекта (по умолчанию — родитель bot/)")
    sub.add_parser("check-secrets")
    p = sub.add_parser("layout")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-unfilled-pins", action="store_true",
                   help="разрешить раскладку обёрток с плейсхолдерами пинов — ТОЛЬКО для прогонов по шаблону монорепо; у заказчика комплект приходит выпущенным релизом")
    p = sub.add_parser("validator")
    p.add_argument("--release", default=None)
    p.add_argument("--target", default=None, help="целевая тройка бинаря; по умолчанию — хост (uname), см. host_target()")
    p.add_argument("--dest", default=None, help="куда положить (прогоны); по умолчанию — .workshop-bin/workshop-validator репозитория")
    p.add_argument("--path", default=None, help="локальный артефакт вместо скачивания (прогоны)")
    p.add_argument("--timeout-s", type=int, default=None)
    sub.add_parser("check-people")
    sub.add_parser("commit")
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    try:
        {"check-kit-ref": cmd_check_kit_ref, "check-secrets": cmd_check_secrets, "layout": cmd_layout,
         "validator": cmd_validator, "check-people": cmd_check_people, "commit": cmd_commit}[args.cmd](args)
    except Refuse as e:
        sys.stdout.write("FAIL %s: %s\n" % (args.cmd, e))
        return 2
    except yamlmini.YamlError as e:
        sys.stdout.write("FAIL %s: yaml: %s\n" % (args.cmd, e))
        return 2
    except Exception as e:  # noqa: BLE001 — собственный сбой инструмента: отдельный исход
        sys.stdout.write("TOOL_FAILURE %s: %s: %s\n" % (args.cmd, type(e).__name__, e))
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
