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
                  проходят safe_path (без `..`, абсолютных, .git/ и симлинков)
  validator       скачать пиннованный релизный бинарь (только https, без небезопасного редиректа)
                  и СВЕРИТЬ sha256 по kit/validator-release.yaml; несовпадение, плейсхолдер или
                  нулевой дайджест — громкий отказ (rc=2); назначение — .workshop-bin/workshop-validator
                  в репозитории заказчика (каталог самоигнорируемый: .workshop-bin/.gitignore = `*`)
  check-people    .workshop/people.yaml разбирается строгим лоадером; поля; handle бота присутствует;
                  telegram_id/forge_login уникальны; есть хотя бы один role: admin с telegram_id
  commit          закоммитить и (при наличии origin) запушить разложенный комплект

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
RELEASE_LAYER_PATHS = ("bot/kit/validator-release.yaml", "bot/kit/workflows/bootstrap.yml", "bot/kit/manifest.yaml")
_KEEP_ROLES = ("config", "state")
_MANUAL_ROLE = "manual"


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


def safe_path(root, relative):
    """Путь назначения внутри репозитория заказчика: относительный, без `..`, не в .git/, без
    симлинков на пути (существующих). Возвращает абсолютный путь; иначе Refuse."""
    rel = str(relative)
    parts = rel.split("/")
    if rel == "" or os.path.isabs(rel) or rel.startswith("~") or ".." in parts or "" in parts or parts[0] == ".git":
        raise Refuse("небезопасный путь назначения в манифесте: %r (запрещены `..`, абсолютные, `.git/`)" % rel)
    root_abs = os.path.realpath(root)  # realpath: корень mktemp на macOS сам лежит за симлинком /var → /private/var
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
    return yamlmini.load_file(p)


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
    # 1) целостность источников и безопасность назначений — ДО любой записи
    for e in m["entries"]:
        src = os.path.join(kit_root, e["src"])
        if not os.path.exists(src):
            raise Refuse("источник манифеста отсутствует в комплекте: %s" % e["src"])
        actual = sha256_file(src)
        if actual != e["sha256"]:
            raise Refuse("комплект не совпадает с манифестом: %s sha256 %s ≠ %s" % (e["src"], actual, e["sha256"]))
        safe_path(repo, e["dst"])
    # 2) план и дифф
    counts = {"create": 0, "update": 0, "same": 0, "keep": 0, "manual": 0}
    actions = []
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
    # 3) версия установки — тоже через дифф
    ver_text = yamlmini.dumps({"kit_version": m["kit_version"], "kit_schema_version": m["kit_schema_version"],
                               "manifest_schema_version": m["schema_version"]}).encode("utf-8")
    ver_path = safe_path(repo, KIT_VERSION_FILE)
    if not os.path.exists(ver_path) or _read(ver_path) != ver_text:
        _say(("+" if not os.path.exists(ver_path) else "~") + " %s" % KIT_VERSION_FILE)
        actions.append((ver_path, ver_text, "0644"))
    if args.dry_run:
        _say("layout (dry-run): create=%d update=%d same=%d keep=%d manual=%d" % tuple(counts[k] for k in ("create", "update", "same", "keep", "manual")))
        return
    for dst, data, mode in actions:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        os.chmod(dst, int(mode, 8))
    _say("layout: create=%d update=%d same=%d keep=%d manual=%d — %s" % (
        counts["create"], counts["update"], counts["same"], counts["keep"], counts["manual"],
        "без изменений" if not actions else "записано файлов: %d" % len(actions)))


# ------------------------------------------------------------------ validator
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
    if not _zone_ok(str(cfg.get("default_timezone"))):
        raise Refuse("в %s default_timezone не IANA-зона" % BOT_CONFIG_FILE)
    wd = cfg.get("watchdog") if isinstance(cfg.get("watchdog"), dict) else {}
    alarm_to = wd.get("alarm_to")
    if not (alarm_to == "admins" or (isinstance(alarm_to, int) and not isinstance(alarm_to, bool))):
        raise Refuse("в %s watchdog.alarm_to не `admins` и не chat_id (целое)" % BOT_CONFIG_FILE)
    def _posint(name):
        v = wd.get(name)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise Refuse("в %s watchdog.%s не положительное целое (часы)" % (BOT_CONFIG_FILE, name))
        return v
    ret = _posint("retention_window_hours"); silence = _posint("unprocessed_update_alarm_hours")
    _posint("stale_session_alarm_hours"); _posint("stale_session_repeat_hours")
    rr = wd.get("rejection_report_min")
    if not isinstance(rr, int) or isinstance(rr, bool) or rr < 1:
        raise Refuse("в %s watchdog.rejection_report_min не целое >= 1" % BOT_CONFIG_FILE)
    # порог молчания ОБЯЗАН быть строго меньше окна retention — иначе алярм придёт после потери сообщений (T5)
    if not (silence < ret):
        raise Refuse("в %s watchdog.unprocessed_update_alarm_hours (%d) обязан быть строго меньше retention_window_hours (%d)" % (BOT_CONFIG_FILE, silence, ret))
    n, admins = check_people_doc(yamlmini.load_file(people_path), bot_handle)
    _say("check-people: ok — записей %d, handle бота %s присутствует, админов с telegram_id: %d" % (n, bot_handle, admins))


# ------------------------------------------------------------------ commit
def cmd_commit(args):
    m = _load_manifest(args)
    repo = os.path.abspath(args.repo)
    paths = [e["dst"] for e in m["entries"] if e["role"] != _MANUAL_ROLE] + [KIT_VERSION_FILE]
    existing = [p for p in paths if os.path.exists(os.path.join(repo, p))]
    r = _git(repo, "add", "--", *existing)
    if r.returncode != 0:
        raise Refuse("git add: %s" % r.stderr.strip())
    r = _git(repo, "diff", "--cached", "--quiet")
    if r.returncode == 0:
        _say("commit: изменений нет")
        return
    r = _git(repo, "-c", "user.name=workshop-bot-kit", "-c", "user.email=workshop-bot-kit@invalid",
             "commit", "-q", "-m", "workshop kit %s: установка/обновление комплекта" % m["kit_version"])
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
    p = sub.add_parser("validator")
    p.add_argument("--release", default=None)
    p.add_argument("--target", default="x86_64-unknown-linux-gnu")
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
