#!/usr/bin/env python3
"""install.py — установщик/апдейтер комплекта, декларативно-тонкий. Владелец — T1 (D09 §1Д, §3).

Ничего не решает сам: манифест `kit/manifest.yaml` (генерируется build_manifest.py на гейте T6)
говорит «путь → sha256 → назначение», этот скрипт СВЕРЯЕТ и исполняет. Подкоманды — по одной
на шаг bootstrap-обёртки (предикат тонкой обёртки §2: один вызов на шаг, без аргументов-политик):

  check-kit-ref   HEAD checkout'а комплекта == kit.ref из kit/validator-release.yaml (пин комплекта) либо HEAD —
                  релизный коммит ровно над kit.ref, меняющий только релизный слой: пины (манифест релиза, обёртки,
                  манифест комплекта) и — у релиза заказчика R_c (D10 T7) — выходы генератора под его слой
                  (profiles/out/**, profiles/sources-manifest.yaml); при них манифест комплекта обязан совпадать с
                  манифестом kit.ref во всём, кроме sha256 изменённых источников и привязки customer_layer;
                  origin checkout'а == kit.repository; плейсхолдер вместо SHA — отказ «пин не заполнен», не пропуск
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
                  ИНСТРУКЦИИ ИИ-АГЕНТА (D10 T3): роль managed — профили .workshop-ai/* и standing AGENTS.md = CLAUDE.md
                  (выходы генератора, уже отрендеренные со слоем заказчика; незаполненный плейсхолдер {{вид: …}} в
                  источнике — отказ до мутаций; D10 T24: слой живёт в репозитории заказчика, манифест `customer_layer`
                  привязывает выходы к sha256 слоя — нет слоя в клоне или он другой — именованный отказ до мутаций,
                  образец .workshop-ai/customer-layer.example.yaml кладёт комплект) кладутся/обновляются ТОЛЬКО поверх своего прежнего содержимого: sha256
                  последней раскладки (kit-version.yaml `managed`) или известного прежнего (манифест `supersedes`);
                  иное — ИМЕНОВАННЫЙ конфликт (путь, ожидаемый и фактический SHA), файл не трогается. retire манифеста —
                  файл снимается с печатью диффа, только если его sha256 == ожидаемому манифеста ЛИБО отпечатку последней
                  раскладки этого пути комплектом (kit-version.yaml `managed`: прежнее назначение профиля после переезда
                  .workshop/ai/ → .workshop-ai/), иначе — именованный конфликт.
                  Конфликты собираются ВСЕ и дают отказ rc=2 до любой записи. Роль lines — .gitignore: недостающие
                  строки источника дописываются, чужие не трогаются (.workshop/me.yaml — личный файл агента).
  validator       скачать пиннованный релизный бинарь (только https, без небезопасного редиректа)
                  и СВЕРИТЬ sha256 по kit/validator-release.yaml; несовпадение, плейсхолдер или
                  нулевой дайджест — громкий отказ (rc=2); назначение — .workshop-bin/workshop-validator
                  в репозитории заказчика (каталог самоигнорируемый: .workshop-bin/.gitignore = `*`).
                  ВЕРСИЯ ПО МАНИФЕСТУ (D10 T23, валидатор 0.3.0): релиз манифеста, объявляющий interface_version,
                  сверяется ещё и исполнением — шапка отчёта бинаря (`-- interface_version: N; validator: V; …`)
                  обязана назвать ту же версию и тот же интерфейс, иначе отказ rc=2 до записи (sha256 ловит подмену
                  байт, но не ошибку разметки манифеста: дайджест 0.2.1 под меткой 0.3.0). Бинарь, не исполнимый на
                  хосте установки (цель ≠ хост), — именованная заметка «версия не сверена исполнением»; на цели
                  хоста неисполнимость — отказ
  check-people    .workshop/people.yaml разбирается строгим лоадером; поля; handle бота присутствует;
                  telegram_id/forge_login уникальны; есть хотя бы один role: admin с telegram_id;
                  форма запуска: явный `launch: daemon` в bot.yaml ∧ физически лежащая управляемая
                  обёртка из реестра kit-version.yaml → отказ rc=2 (два читателя курсора); отсутствие
                  поля/метаданных — мягкая заметка; несовпадение формы с последней раскладкой — заметка
  commit          закоммитить и (при наличии origin) запушить разложенный комплект; tracked-удаления
                  обёрток (daemon) захватываются точными путями, посторонний staged-файл — нет
  storage-init    (D20 T3) конфиг хранилища вложений .workshop/storage.yaml: без файла или без блока storage —
                  «хранилище не настроено», rc 0; иначе — проверка адаптерным attach.load_config, дописывание (один раз,
                  атомарно, под блокировкой каталога) недостающих credentials (ИМЕНА из реестра секретов), key_prefix
                  (os.urandom ≡ secrets.token_hex, 128 бит; секрет конфига — не печатается; есть — не трогается никогда) и
                  canary_key; затем канарейка ключом писателя (attach.ensure_canary) и статус пробы
  storage-status  (D20 T3) то же чтение и проверка без записи; статус пробы (attach.probe_storage)
  types-plan      (D10 T24, REQ-085) план правки .workshop/types.yaml — ТОЛЬКО для типов заказчика: стандартной поставки
                  типов нет (TASK, REQUEST и прочие формы ядра в конфиге не объявляются). Ничего не пишет: печатает
                  unified diff для `git apply` и итог. Без --from — снять объявления, затеняющие форму ядра (остаток
                  поставки T9.1; W-CFG-KERNEL-SHADOW валидатора, ядро §15.1). С --from <файл> — добавить объявления
                  типов заказчика из файла (`types:` — список отображений с первым ключом name): нет в конфиге — вставка в
                  конец types[], побайтово то же — «уже есть», иное — именованный конфликт rc 2; имя формы ядра во
                  входе — отказ rc 2. Набор форм ядра — от валидатора (check-config, бинарь .workshop-bin/workshop-validator
                  или --validator): своего перечня у установщика нет. Правка содержимого поднимает config_version на 1.
                  Инвариант: результат любого плана — валидный конфиг; самопроверка — печатаемый diff применяется
                  `git apply` к исходным байтам во временном репозитории, затем check-config применённого
                  (ошибки — отказ rc 2, план не выдан; неприменимый план — сбой rc 10); конфиг с ошибками до плана — отказ rc 2. Снято последнее
                  объявление — ключ types убирается целиком (в схеме он required: false).

Коды выхода: 0 — выполнено (у storage-* — и «хранилище не настроено»); 2 — отказ с названной причиной (ничего не
записано сверх сказанного); 10 — сбой самого инструмента (исключение; у storage-* — без текста исключения). Пути: --kit (по умолчанию каталог этого файла),
--repo (по умолчанию текущий каталог). Все опции необязательны — bootstrap зовёт без них.
"""
import argparse
import contextlib
import difflib
import hashlib
import os
import re
import subprocess
import sys
import time
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
_MANAGED_ROLE = "managed"      # D10: перезапись только поверх своего прежнего содержимого, иначе именованный конфликт
_LINES_ROLE = "lines"          # D10: .gitignore — дописать недостающие строки
_PLACEHOLDER = re.compile(r"\{\{[a-z][a-z_-]*: [^{}\n]*\}\}")
_TMP_PREFIX = ".workshop-kit-tmp-"   # единственный адрес префикса временных файлов раскладки (_LayoutTxn, сирота)
_TMP_ORPHAN = re.compile("^" + re.escape(_TMP_PREFIX) + r"[0-9]+-[0-9]+$")   # имя _LayoutTxn._tmp_write, ровно
# файлы, которыми релизный коммит МОЖЕТ отличаться от кодового коммита kit.ref (check-kit-ref): пины и — у релиза
# заказчика (decide 2026-11-02 d10-customer-layer-delivery) — выходы генератора профилей под его слой с их пиннингом;
# сами выходы раскладываются только через записи манифеста с sha256, код — тот самый K
RELEASE_LAYER_PATHS = ("bot/kit/validator-release.yaml", "bot/kit/workflows/bootstrap.yml",
                       "bot/kit/workflows/poller.yml", "bot/kit/workflows/heartbeat.yml",
                       "bot/kit/manifest.yaml", "profiles/sources-manifest.yaml")
RELEASE_LAYER_PREFIXES = ("profiles/out/",)


def _in_release_layer(path):
    return path in RELEASE_LAYER_PATHS or path.startswith(RELEASE_LAYER_PREFIXES)
_KEEP_ROLES = ("config", "state")
_MANUAL_ROLE = "manual"
_WORKFLOW_ROLE = "workflow"
LAUNCH_FORMS = ("ci", "daemon")          # закрытое множество значений bot.yaml launch (D15 §4.10); умолчание — ci
LAUNCH_DEFAULT = "ci"


class Refuse(Exception):
    """Отказ с названной причиной → rc=2."""


def stat_is_regular(path):
    """Обычный файл (не ссылка, не каталог) — по lstat."""
    import stat as _st
    try:
        return _st.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


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


def _manifest_at(kit_root, commit):
    r = subprocess.run(["git", "-C", kit_root, "show", "%s:bot/kit/manifest.yaml" % commit], capture_output=True)
    try:
        doc = yamlmini.loads(r.stdout.decode("utf-8")) if r.returncode == 0 else None
    except (UnicodeDecodeError, yamlmini.YamlError):
        doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
        raise Refuse("манифест комплекта bot/kit/manifest.yaml коммита %s не читается — маршрут выходов под слой заказчика не проверить" % commit[:12])
    return doc


def _same_manifest_route(kit_root, k, r, changed):
    def route(doc):
        d = dict(doc)
        d["entries"] = [dict(e, sha256=None) if isinstance(e, dict) and str(e.get("src")) in changed else e for e in doc["entries"]]
        if isinstance(d.get("customer_layer"), dict):
            d["customer_layer"] = dict(d["customer_layer"], sha256=None)
        return d
    mk, mr = route(_manifest_at(kit_root, k)), route(_manifest_at(kit_root, r))
    if mk != mr:
        ek, er = mk["entries"], mr["entries"]
        diff = [str((er[i] if i < len(er) else ek[i]).get("src")) for i in range(max(len(ek), len(er)))
                if i >= len(ek) or i >= len(er) or ek[i] != er[i]]
        diff += sorted(x for x in set(mk) | set(mr) if x != "entries" and mk.get(x) != mr.get(x))
        raise Refuse("релизный коммит %s несёт выходы под слой заказчика, а его манифест расходится с манифестом kit.ref %s не только sha256 изменённых файлов: %s — назначения и роли обязаны быть теми, что у K" % (r[:12], k[:12], ", ".join(diff[:8])))


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
        # ТОЛЬКО файлами релизного слоя: пины (манифест релиза, обёртки, манифест комплекта) и — у релиза
        # заказчика R_c — выходы генератора под его слой (profiles/out/**, profiles/sources-manifest.yaml).
        # Любой иной файл в R — отказ: код обязан быть тем самым K, который назван манифестом.
        parent = _git(kit_root, "rev-parse", "HEAD^")
        if parent.returncode != 0:
            shallow = _git(kit_root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
            if shallow:
                raise Refuse("пин комплекта: HEAD checkout'а %s без родителя (МЕЛКИЙ клон) — релизный слой над kit.ref %s не проверить; checkout комплекта обязан быть глубиной 2 (fetch-depth: 2 в обёртке)" % (actual[:12], expected[:12]))
            raise Refuse("пин комплекта расходится: HEAD checkout'а %s (корневой коммит), манифест релиза kit.ref %s" % (actual, expected))
        if parent.stdout.strip() != expected:
            raise Refuse("пин комплекта расходится: HEAD checkout'а %s, манифест релиза kit.ref %s (и HEAD не релизный слой над ним)" % (actual, expected))
        # --no-renames: переименование кода в путь релизного слоя называет ОБЕ стороны (иначе виден только новый путь)
        changed = _git(kit_root, "diff", "--name-only", "--no-renames", expected, actual).stdout.split()
        extra = sorted(p for p in set(changed) if not _in_release_layer(p))
        if extra:
            raise Refuse("релизный коммит %s меняет не только пины над kit.ref %s: %s — код обязан быть кодовым коммитом манифеста" % (actual[:12], expected[:12], ", ".join(extra)))
        # выходы под слой заказчика — НОВЫЕ байты над K, а манифест комплекта сам в релизном слое: без сверки маршрута
        # манифест R мог бы разложить их кодом или поверх кода. Манифест R обязан совпадать с манифестом K во всём, кроме
        # sha256 записей, чей источник изменён в R, и sha256 привязки customer_layer: назначения и роли — те, что у K
        if any(p.startswith(RELEASE_LAYER_PREFIXES) or p == "profiles/sources-manifest.yaml" for p in changed):
            _same_manifest_route(kit_root, expected, actual, set(changed))
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
    # D20 T3: условные секреты (required_when) и шаги (when_values[when].secrets_required_when) — по состоянию
    # хранилища вложений в репозитории заказчика; закрытое множество условий — _CONDITIONS
    when_values = _when_values(steps_doc)
    for s in secrets:
        if "required_when" in s and s["required_when"] not in _CONDITIONS:
            raise Refuse("реестр секретов: required_when %r у %s — не из %s" % (s["required_when"], s["name"], "|".join(_CONDITIONS)))
    storage = _storage_for_secrets(args, steps_doc)
    conds = {STORAGE_CONDITION: storage["configured"]}
    for n in storage["config_names"]:
        if n not in by_name:
            by_name[n] = {"name": n}
            _say("~ конфиг хранилища ссылается на секрет %s вне реестра — CI и демон комплекта привязывают имена реестра" % n)
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
    for n in storage["config_names"]:
        if all(n != s["name"] for s in secrets):
            _say("secret %s: %s (имя из конфига хранилища)" % (n, "present" if present[n] else "absent"))
    missing = []
    _say("storage: %s" % storage["note"])
    required = [s for s in secrets if s.get("required") or (s.get("required_when") and conds[s["required_when"]])]
    required += [by_name[n] for n in storage["config_names"] if all(n != r["name"] for r in required)]
    for s in required:
        got = satisfied(s["name"])
        if got is None:
            alt = s.get("alternative")
            missing.append(s["name"] + ((" (или %s)" % alt) if alt else ""))
        elif got != s["name"]:
            _say("secret %s: absent, but alternative %s present — ok" % (s["name"], got))
    # по шагам: поле required_secrets — имена из реестра secrets (второй копии имён нет)
    for st in steps_doc.get("steps") or []:
        req = st.get("required_secrets") or []
        if st.get("when") not in when_values:
            raise Refuse("реестр шагов: у шага %s when %r вне when_values" % (st.get("id"), st.get("when")))
        cond = when_values[st["when"]].get("secrets_required_when")
        if cond is not None and cond not in _CONDITIONS:
            raise Refuse("реестр шагов: when_values.%s.secrets_required_when %r — не из %s" % (st["when"], cond, "|".join(_CONDITIONS)))
        if cond is not None and not conds[cond]:
            for name in req:
                if name not in by_name:
                    raise Refuse("шаг %s требует секрет %s, которого нет в реестре secrets" % (st["id"], name))
                _say("step %s: %s %s — не требуется (%s: нет)" % (st["id"], name, "present" if present.get(name) else "absent", cond))
            continue
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
    _say("check-secrets: ok (%d имён в реестре)" % len(secrets))


# ------------------------------------------------------------------ хранилище вложений (D20 T3)
# Конфиг — ОТДЕЛЬНЫЙ файл .workshop/storage.yaml (роль манифеста config: создаётся из шаблона, дальше не трогается):
# хранилище читают не только бот, но и CLI и фронты, а файл несёт РОВНО факты attach.load_config (закрыт по ключам).
# Разбор — yamlmini (строгий, тот же, что у всех настроек комплекта), суд фактов — ТОЛЬКО адаптер (load_config): копии
# схемы здесь нет. Установщик дописывает три факта, которых заказчик не знает или не должен выбирать сам: credentials
# (имена секретов — из реестра install-steps.yaml), key_prefix (случайный, 128 бит), canary_key (фиксированное имя).
STORAGE_CONFIG_FILE = ".workshop/storage.yaml"
STORAGE_CONDITION = "storage_configured"
_CONDITIONS = (STORAGE_CONDITION,)        # закрытое множество условий реестра (required_when, secrets_required_when)
KEY_PREFIX_BYTES = 16                     # os.urandom(16).hex() ≡ secrets.token_hex(16) — 128 бит (alex 2026-10-09: «случайный по умолчанию»)
CANARY_KEY_DEFAULT = "workshop-canary"    # имя объекта-канарейки ПОД префиксом; не пересекается с sha256/<hex> нормы
GIT_HOST_FILE_LIMIT = 100 * 1024 * 1024   # soft_limit.host_hard_limit_note нормы: «у GitHub — 100 МиБ»; проверка — комплект
NOT_CONFIGURED = "хранилище не настроено — вложения выше порога: unsaved no-storage"
_HEADER_RE = re.compile(rb"storage:[ ]*(#.*)?")
TEST_HOOK_ENV = "WORKSHOP_KIT_TEST_HOOK_DIR"   # только тесты: пауза под блокировкой после чтения (held → release)


class _StorageFault(Exception):
    """Собственная ошибка установщика в storage-* — rc 10; наружу только имя класса исходной ошибки."""


def _attach():
    """Адаптер вложений — пакет attach рядом с установщиком: в монорепо и в checkout комплекта (bootstrap) это bot/attach/;
    у заказчика (.workshop/bot/kit/install.py) — .workshop/bot/attach/ после раскладки пакета (вход D20 T4)."""
    try:
        import attach.core as A
    except ImportError:
        raise Refuse("адаптер вложений (пакет attach) не найден или не импортируется рядом с установщиком (%s) — у заказчика пакет "
                     "раскладывается комплектом (D20 T4); до того запускайте из checkout комплекта" % os.path.dirname(_HERE))
    return A


def _when_values(steps_doc):
    wv = steps_doc.get("when_values")
    if not isinstance(wv, dict) or not wv or any(not isinstance(v, dict) for v in wv.values()):
        raise Refuse("реестр шагов: нет мэппинга when_values (закрытое множество значений when)")
    return wv


def _storage_cred_names(steps_doc, A):
    """{access_key_id: ИМЯ, secret_access_key: ИМЯ} из реестра секретов (поле storage_credential) — единственный адрес
    имён; множество ключей — из адаптера (attach.core._CRED_KEYS), форма имени — его же грамматика."""
    out = {}
    for s in steps_doc.get("secrets") or []:
        k = s.get("storage_credential")
        if k is None:
            continue
        if k not in A._CRED_KEYS or k in out:
            raise Refuse("реестр секретов: storage_credential %r у %s — не из %s или повтор" % (k, s.get("name"), "|".join(A._CRED_KEYS)))
        if not isinstance(s.get("name"), str) or not A._ENV_NAME_RE.fullmatch(s["name"]):
            raise Refuse("реестр секретов: имя %r не имя переменной окружения" % (s.get("name"),))
        out[k] = s["name"]
    if set(out) != set(A._CRED_KEYS):
        raise Refuse("реестр секретов: секреты хранилища неполны (storage_credential: %s)" % ", ".join(sorted(out) or ["нет"]))
    return out


def _env_secret_values(names):
    return [v for v in (os.environ.get(n) for n in names) if v and len(v) >= 4]


def _mask(text, redact):
    for v in sorted(set(redact), key=len, reverse=True):
        text = text.replace(v, "***")
    return text


def _storage_parse(raw):
    """Байты конфига → мэппинг. Сообщения разбора строк файла НЕ отражают (там может стоять значение) — только номер."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refuse("%s не UTF-8" % STORAGE_CONFIG_FILE)
    try:
        doc = yamlmini.loads(text)
    except yamlmini.YamlError as e:
        m = re.match(r"строка ([0-9]+)", str(e))
        raise Refuse("%s не разбирается строгим загрузчиком YAML%s (содержимое строки не печатается)"
                     % (STORAGE_CONFIG_FILE, (" — строка %s" % m.group(1)) if m else ""))
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise Refuse("%s: верхний уровень — не мэппинг фактов" % STORAGE_CONFIG_FILE)
    return doc


def _storage_load(A, mapping):
    try:
        return A.load_config(mapping)
    except A.ConfigError as e:
        raise Refuse("%s: %s — файл неверен, умолчание не подставляется" % (STORAGE_CONFIG_FILE, e))


def _secret_values_in(raw, names):
    """Положительный контракт «в конфиге только имена»: значение ни одного секрета хранилища (реестр ∪ имена конфига,
    если они есть в окружении) не встречается в байтах файла. Найдено — отказ; ни значение, ни строка не печатаются."""
    hit = sorted(n for n in names if os.environ.get(n) and len(os.environ[n]) >= 4 and os.environ[n].encode("utf-8") in raw)
    if hit:
        raise Refuse("в %s найдено ЗНАЧЕНИЕ секрета %s — в конфиге только имена переменных окружения; уберите значение "
                     "из файла и из истории git и перевыпустите ключ" % (STORAGE_CONFIG_FILE, ", ".join(hit)))


def _registry_storage_names(steps_doc):
    """Имена S3-секретов реестра (поле storage_credential) — без адаптера: нужны проверке значения в байтах файла
    ДО разбора; форму и полноту судит _storage_cred_names, когда адаптер нужен."""
    return [s["name"] for s in steps_doc.get("secrets") or [] if "storage_credential" in s and isinstance(s.get("name"), str)]


def _storage_raw(repo, names):
    """Без адаптера (D20 T3 R1, F2): -> (path, raw | None, mapping). Файла нет — raw None. Порядок: путь (safe_path:
    симлинки, .git), обычный файл, значение секрета в байтах, строгий разбор yamlmini."""
    path = safe_path(repo, STORAGE_CONFIG_FILE)
    if not os.path.lexists(path):
        return path, None, {}
    if not stat_is_regular(path):
        raise Refuse("%s — не обычный файл" % STORAGE_CONFIG_FILE)
    raw = _read(path)
    _secret_values_in(raw, names)
    mapping = _storage_parse(raw)
    cred = (mapping.get("storage") or {}).get("credentials") if isinstance(mapping.get("storage"), dict) else None
    if isinstance(cred, dict):
        _secret_values_in(raw, [v for v in cred.values() if isinstance(v, str)])
    return path, raw, mapping


def _has_facts(mapping):
    """Есть ли в файле хоть один активный факт (значение не null). Нет — «хранилище не настроено» без адаптера
    (шаблон как разложен, пустой файл, `storage:` без фактов); есть — суд фактов только адаптером: порог без блока
    storage тоже факт, и его неверный тип — отказ с причиной, а не тихое умолчание."""
    return any(v is not None for v in mapping.values())


def _storage_for_secrets(args, steps_doc):
    """Состояние хранилища для check-secrets: {configured, config_names, note}. Адаптер нужен только при активных фактах."""
    repo = os.path.abspath(args.repo)
    _p, raw, mapping = _storage_raw(repo, _registry_storage_names(steps_doc))
    if raw is None:
        return {"configured": False, "config_names": [], "note": "не настроено (%s нет) — секреты хранилища не требуются" % STORAGE_CONFIG_FILE}
    if not _has_facts(mapping):
        return {"configured": False, "config_names": [], "note": "не настроено (фактов в %s нет) — секреты хранилища не требуются" % STORAGE_CONFIG_FILE}
    A = _attach()
    _storage_cred_names(steps_doc, A)
    cfg = _storage_load(A, mapping)
    if cfg.binding is None:
        why = ("привязка неполна: нет %s" % ", ".join(cfg.binding_missing)) if cfg.binding_missing else "блока storage нет"
        return {"configured": False, "config_names": [], "note": "не настроено (%s) — секреты хранилища не требуются" % why}
    return {"configured": True, "config_names": list(cfg.binding.cred_names), "note": "настроено — секреты хранилища обязательны"}


@contextlib.contextmanager
def _dir_lock(d):
    """Исключительная блокировка каталога конфига (flock на дескрипторе каталога — inode стабилен при атомарной замене
    файла): два storage-init не создают два префикса — второй ждёт и видит уже записанный."""
    import fcntl
    fd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _test_hold():
    d = os.environ.get(TEST_HOOK_ENV)
    if not d:
        return
    with open(os.path.join(d, "held-%d" % os.getpid()), "wb"):
        pass
    deadline = time.monotonic() + 30
    while not os.path.exists(os.path.join(d, "release")) and time.monotonic() < deadline:
        time.sleep(0.01)


def _insert_after_header(raw, rendered):
    """Дописать строки в НАЧАЛО блочного мэппинга storage, не трогая ни одного прежнего байта: новый файл == raw[:pos] +
    вставка + raw[pos:], pos — конец строки заголовка `storage:`. Отступ — отступ первого факта блока."""
    lines = raw.split(b"\n")
    heads = [i for i, l in enumerate(lines) if _HEADER_RE.fullmatch(l)]
    if len(heads) != 1:
        raise Refuse("в %s блок storage не в блочной форме `storage:` с начала строки — допишите факты вручную "
                     "(credentials, key_prefix, canary_key) или приведите блок к блочной форме" % STORAGE_CONFIG_FILE)
    i = heads[0]
    ind = None
    for l in lines[i + 1:]:
        st = l.lstrip(b" ")
        if st == b"" or st.startswith(b"#"):
            continue
        ind = len(l) - len(st)
        break
    if not ind:
        raise Refuse("в %s у блока storage нет фактов с отступом — допишите факты вручную" % STORAGE_CONFIG_FILE)
    pos = sum(len(l) + 1 for l in lines[: i + 1])
    pad = b" " * ind
    ins = b"".join(pad * depth + text + b"\n" for depth, text in rendered)
    return raw[:pos] + ins + raw[pos:], pos, ins


_PREFIX_LINE_RE = re.compile(rb"(?m)^[ ]*key_prefix:")


def _git_history_with(repo, rel, pred):
    """Самый свежий коммит ЛЮБОЙ ветки/тега (--all), в чьём дереве файл rel есть и pred(байты) истинен.
    -> (sha | None, state, путь от toplevel — для `git show <sha>:<путь>`): state — "no-git" (не репозиторий: доказать нечего) | "shallow" (история неполна) | "full"."""
    if _git(repo, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        return None, "no-git", rel
    state = "shallow" if _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true" else "full"
    top = _git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    relp = os.path.relpath(os.path.join(os.path.realpath(repo), rel), os.path.realpath(top)).replace(os.sep, "/")
    # Два соглашения о путях (R2, F1-R2): pathspec `log` git разрешает от cwd (= --repo, может быть подкаталогом
    # toplevel), а `<sha>:<путь>` — от toplevel. relp — от toplevel, поэтому pathspec якорится магией :(top).
    for sha in _git(repo, "log", "--all", "--format=%H", "--", ":(top)" + relp).stdout.split():
        r = subprocess.run(["git", "-C", repo, "show", "%s:%s" % (sha, relp)], capture_output=True)
        if r.returncode == 0 and pred(r.stdout):
            return sha, state, relp
    return None, state, relp


def _prefix_history_guard(repo, say, new_storage):
    """R1, F1. Инвариант: key_prefix никогда не создаётся заново, если инструмент может доказать, что он уже был.
    Доказательство — коммит (любой ветки), в чьей версии конфига есть строка key_prefix: удалённый файл (rm, git rm),
    удалённая строка, история в другой ветке. Найден — отказ rc 2 с SHA и командой восстановления (значение не
    печатается); обход — только явный флаг процедуры смены хранилища --new-storage-prefix. Мелкий клон — история
    неполна: сказать. Не git-репозиторий — доказать нечего: генерировать."""
    sha, state, top_rel = _git_history_with(repo, STORAGE_CONFIG_FILE, lambda b: _PREFIX_LINE_RE.search(b) is not None)
    if state == "no-git":
        say("~ %s не в git-репозитории — прежний key_prefix по истории не проверить" % STORAGE_CONFIG_FILE)
    elif state == "shallow" and sha is None:
        say("! клон МЕЛКИЙ — история git неполна: прежний key_prefix мог остаться за границей клона; если хранилище уже "
            "использовалось, проверьте полную историю (git fetch --unshallow) до коммита нового префикса")
    if sha is None:
        return
    if not new_storage:
        raise Refuse("в истории git есть key_prefix конфига хранилища (коммит %s) — новый префикс сделал бы все сохранённые "
                     "вложения нечитаемыми. Верните строку из истории: git show %s:%s (значение здесь не печатается) "
                     "и запустите storage-init снова. Сознательная смена хранилища — storage-init --new-storage-prefix"
                     % (sha, sha, top_rel))
    say("! --new-storage-prefix: создаётся НОВЫЙ key_prefix; прежние вложения остаются под старым префиксом (коммит %s) "
        "и без процедуры смены хранилища (скопировать объекты под новый префикс, сверить адаптером) нечитаемы" % sha[:12])


def _storage_report(say, cfg, mapping):
    thr = cfg.git_threshold_bytes
    say("git_threshold_bytes: %d%s" % (thr, "" if "git_threshold_bytes" in mapping else " (порог нормы — строки в конфиге нет)"))
    if thr > GIT_HOST_FILE_LIMIT:
        say("! порог git %d выше жёсткого предела файла хостинга git (GitHub — %d байт): файл между пределом и порогом "
            "push отвергнет — держите порог не выше предела (норма soft_limit.host_hard_limit_note)" % (thr, GIT_HOST_FILE_LIMIT))


def cmd_storage_init(args):
    _storage_cmd(args, write=True)


def cmd_storage_status(args):
    _storage_cmd(args, write=False)


def _storage_cmd(args, write):
    name = "storage-init" if write else "storage-status"
    redact = []

    def say(msg):
        _say(_mask(msg, redact))
    try:
        _storage_cmd_body(args, write, name, say, redact)
    except Refuse as e:
        raise Refuse(_mask(str(e), redact))
    except _StorageFault:
        raise
    except Exception as e:  # noqa: BLE001 — собственный сбой: имя класса, без текста (там может быть значение)
        raise _StorageFault("%s: собственная ошибка установщика (%s)" % (name, type(e).__name__)) from None


def _storage_cmd_body(args, write, name, say, redact):
    steps_doc = yamlmini.load_file(os.path.join(args.kit, "install-steps.yaml"))
    reg_names = _registry_storage_names(steps_doc)
    redact += _env_secret_values(reg_names)
    repo = os.path.abspath(args.repo)
    path = safe_path(repo, STORAGE_CONFIG_FILE)
    if not os.path.lexists(path):
        say("%s: %s нет — %s (файл кладёт layout из шаблона комплекта)" % (name, STORAGE_CONFIG_FILE, NOT_CONFIGURED))
        return
    lock = _dir_lock(os.path.dirname(path)) if write else contextlib.nullcontext()
    with lock:
        _p, raw, mapping = _storage_raw(repo, reg_names)
        if not _has_facts(mapping):
            say("%s: %s" % (name, NOT_CONFIGURED))
            return
        A = _attach()                   # адаптер — только когда есть факты для суда (R1, F2)
        reg = _storage_cred_names(steps_doc, A)
        cfg = _storage_load(A, mapping)
        _test_hold() if write else None
        st = mapping.get("storage")
        if isinstance(st, dict) and isinstance(st.get("key_prefix"), str):
            redact.append(st["key_prefix"]) if len(st["key_prefix"]) >= 4 else None
        if isinstance(st, dict) and isinstance(st.get("credentials"), dict):
            redact += _env_secret_values(v for v in st["credentials"].values() if isinstance(v, str))
        _storage_report(say, cfg, mapping)
        if not isinstance(st, dict):
            say("%s: %s" % (name, NOT_CONFIGURED))
            return
        nulls = [k for k in ("credentials", "key_prefix", "canary_key") if k in st and st[k] is None]
        if nulls:
            raise Refuse("в %s факты storage.%s заданы пустым значением (null) — удалите строку (тогда %s допишет факт) "
                         "или задайте значение" % (STORAGE_CONFIG_FILE, ", storage.".join(nulls), "storage-init"))
        core_missing = [m for m in cfg.binding_missing if m != "storage.credentials" or not write]
        if core_missing:
            raise Refuse("в %s привязка неполна: нет %s — впишите факты%s" % (
                STORAGE_CONFIG_FILE, ", ".join(core_missing), "" if write else " и запустите storage-init"))
        missing_init = [k for k in ("key_prefix", "canary_key") if k not in st]
        if not write:
            if missing_init:
                raise Refuse("в %s нет storage.%s — их создаёт установщик: запустите storage-init"
                             % (STORAGE_CONFIG_FILE, ", storage.".join(missing_init)))
        else:
            rendered, added, new_vals = [], [], {}
            if "credentials" not in st:
                rendered += [(1, b"credentials:")] + [(2, ("%s: %s" % (k, reg[k])).encode("ascii")) for k in A._CRED_KEYS]
                added.append("credentials (имена из реестра секретов: %s)" % ", ".join(reg[k] for k in A._CRED_KEYS))
                new_vals["credentials"] = dict(reg)
            if "key_prefix" not in st:
                _prefix_history_guard(repo, say, getattr(args, "new_storage_prefix", False))
                # CSPRNG ОС — то же, на чём стоит secrets.token_hex stdlib; `import secrets` здесь НЕ годится: каталог
                # bot/ стоит первым в sys.path, и имя занял модуль бота bot/secrets.py
                prefix = os.urandom(KEY_PREFIX_BYTES).hex() + "/"
                redact.append(prefix)
                rendered += [(1, ("key_prefix: \"%s\"" % prefix).encode("ascii"))]
                added.append("key_prefix (создан: %d бит, значение не печатается)" % (KEY_PREFIX_BYTES * 8))
                new_vals["key_prefix"] = prefix
            if "canary_key" not in st:
                rendered += [(1, ("canary_key: %s" % CANARY_KEY_DEFAULT).encode("ascii"))]
                added.append("canary_key")
                new_vals["canary_key"] = CANARY_KEY_DEFAULT
            if rendered:
                rendered.insert(0, (1, "# дописано install.py storage-init (D20 T3): key_prefix — секрет конфига, не менять".encode("utf-8")))
                new_raw, pos, ins = _insert_after_header(raw, rendered)
                expected = dict(mapping)
                expected["storage"] = dict(st, **new_vals)
                try:
                    reparsed = _storage_parse(new_raw)
                except Refuse:
                    reparsed = None             # свой вывод не разобрался — собственная ошибка, не «файл заказчика неверен»
                if reparsed != expected or new_raw[:pos] + new_raw[pos + len(ins):] != raw:
                    raise _StorageFault("%s: собственная ошибка установщика (дописанный конфиг не равен ожидаемому)" % name)
                cfg = _storage_load(A, expected)
                if cfg.binding is None:
                    raise _StorageFault("%s: собственная ошибка установщика (привязка не собралась после дописывания)" % name)
                if _read(path) != raw:
                    raise Refuse("%s изменился во время storage-init — повторите" % STORAGE_CONFIG_FILE)
                _atomic_write(path, new_raw, os.stat(path).st_mode & 0o777)
                if _read(path) != new_raw:
                    raise _StorageFault("%s: собственная ошибка установщика (перечтение записанного не совпало)" % name)
                say("%s: %s дописан: %s" % (name, STORAGE_CONFIG_FILE, "; ".join(added)))
                say("  закоммитьте %s: key_prefix создан ОДИН раз и дальше не меняется (смена — процедура смены хранилища)"
                    % STORAGE_CONFIG_FILE)
            else:
                say("%s: %s: credentials, key_prefix, canary_key уже есть — файл не тронут" % (name, STORAGE_CONFIG_FILE))
    b = cfg.binding
    if b.key_prefix == "":
        say("! key_prefix пуст (задан заказчиком): физический ключ — sha256/<hex>, и знающий файл может проверить его "
            "наличие в бакете; случайный префикс создаётся только для привязки без строки key_prefix")
    else:
        say("key_prefix: есть (значение не печатается)")
    if b.allow_insecure_http:
        say("! allow_insecure_http: true — только для локального фейка (loopback); заказчику не нужен")
    say("credentials: %s" % ", ".join("%s → %s (%s)" % (k, n, "present" if os.environ.get(n) else "ABSENT")
                                      for k, n in zip(A._CRED_KEYS, b.cred_names)))
    if write:
        res = A.ensure_canary(cfg, env=os.environ)
        say("canary: %s%s" % (res["canary_outcome"], (" (%s)" % res["detail"]) if res["detail"] else ""))
        probe = {"storage_configured": res["storage_configured"], "storage_probe_outcome": res["storage_probe_outcome"],
                 "detail": res["probe_detail"]}
        if res["canary_outcome"] not in ("uploaded", "already-present"):
            _probe_say(say, probe)
            raise Refuse("канарейка не создана: %s%s" % (res["canary_outcome"], _probe_hint(res["detail"])))
    else:
        probe = A.probe_storage(cfg, env=os.environ)
    _probe_say(say, probe)
    if probe["storage_probe_outcome"] != "ok":
        raise Refuse("проба хранилища: %s (%s)%s" % (probe["storage_probe_outcome"], probe["detail"], _probe_hint(probe["detail"])))


def _probe_hint(detail):
    if detail == "credentials-absent":
        return " — значений ключа писателя нет в окружении: положите их в секреты CI / окружение демона под именами из credentials"
    return ""


def _probe_say(say, probe):
    say("storage_configured: %s" % ("true" if probe["storage_configured"] else "false"))
    say("storage_probe_outcome: %s%s" % (probe["storage_probe_outcome"] or "—", (" (%s)" % probe["detail"]) if probe["detail"] else ""))


# ------------------------------------------------------------------ layout
def _load_manifest(args):
    path = args.manifest or os.path.join(args.kit, "manifest.yaml")
    if not os.path.exists(path):
        raise Refuse("манифест комплекта отсутствует: %s (генерируется build_manifest.py на гейте T6)" % path)
    m = yamlmini.load_file(path)
    for k in ("schema_version", "kit_version", "kit_schema_version", "entries"):
        if k not in m:
            raise Refuse("манифест без поля %r: %s" % (k, path))
    for k, fields in (("retire", ("path", "sha256")), ("supersedes", ("path", "sha256"))):
        v = m.get(k, [])
        if not isinstance(v, list) or any(not isinstance(r, dict) or any(f not in r for f in fields) for r in v):
            raise Refuse("манифест: %s не список записей {%s}" % (k, ", ".join(fields)))
        for r in v:
            if not _HEX64.match(str(r["sha256"])):
                raise Refuse("манифест: %s %s — sha256 не дайджест: %r" % (k, r["path"], r["sha256"]))
    if "customer_layer" in m:
        cl = m["customer_layer"]
        if (not isinstance(cl, dict) or sorted(cl) != ["path", "sha256"] or not isinstance(cl["path"], str)
                or not _HEX64.match(str(cl["sha256"]))):
            raise Refuse("манифест: customer_layer не запись {path, sha256 (64 hex)}: %r" % (cl,))
    dsts = set(str(e["dst"]) for e in m["entries"])
    managed = set(str(e["dst"]) for e in m["entries"] if e["role"] == _MANAGED_ROLE)
    # «retire только при замене» гарантирует проекция build_manifest.py (replaced_by реестра kit/retire.yaml)
    for r in m.get("retire", []):
        if path_key(str(r["path"])) in set(path_key(d) for d in dsts):
            raise Refuse("манифест: retire %s совпадает с назначением — противоречие манифеста" % r["path"])
    for r in m.get("supersedes", []):
        if str(r["path"]) not in managed:
            raise Refuse("манифест: supersedes %s — не назначение роли managed" % r["path"])
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
    (роль manual — известны check-people и без манифеста) + sha256 разложенных файлов роли managed (D10: база для
    отличия «прежняя версия комплекта» от «локальная правка заказчика»; только если такие записи есть)."""
    doc = {"kit_version": m["kit_version"], "kit_schema_version": m["kit_schema_version"],
           "manifest_schema_version": m["schema_version"], "launch": launch,
           "workflow_destinations": sorted(set(destinations), key=lambda s: s.encode("utf-8")),
           "manual_destinations": sorted(_manual_destinations(m), key=lambda s: s.encode("utf-8"))}
    managed = [{"path": str(e["dst"]), "sha256": str(e["sha256"])} for e in m["entries"] if e["role"] == _MANAGED_ROLE]
    if managed:
        doc["managed"] = sorted(managed, key=lambda r: r["path"].encode("utf-8"))
    return yamlmini.dumps(doc).encode("utf-8")


def _installed_managed(installed):
    """sha256 последней раскладки файлов роли managed из kit-version.yaml -> {путь: sha}; повреждение — отказ."""
    if not isinstance(installed, dict) or "managed" not in installed:
        return {}
    v = installed["managed"]
    if not isinstance(v, list) or any(not isinstance(r, dict) or not isinstance(r.get("path"), str)
                                      or not _HEX64.match(str(r.get("sha256"))) for r in v):
        raise Refuse("%s: managed не список записей {path, sha256} — метаданные повреждены; повторите layout" % KIT_VERSION_FILE)
    return dict((r["path"], str(r["sha256"])) for r in v)


_WS = " \t"   # пробельные символы YAML; U+2028, U+2029, U+0085, VT, FF — НЕ пробел и не перевод строки


def _lf_lines(text):
    """Строки текста с концами, разрез ТОЛЬКО по LF — так режут разметка types[], git apply и источник. str.splitlines
    режет ещё по U+2028, U+2029, U+0085, VT, FF, CR, и печатаемый diff расходится с байтами источника (T24 R4O-04)."""
    out = re.split(r"(?<=\n)", text)
    return out[:-1] if out and out[-1] == "" else out


def _blank(line):
    """Пустая строка в смысле YAML: только пробелы и табы (не str.strip — тот снимает U+2028, U+0085, VT, FF)."""
    return line.strip(_WS) == ""


def _diff_text(old, new, dst):
    try:
        a = _lf_lines(old.decode("utf-8"))
        b = _lf_lines(new.decode("utf-8"))
    except UnicodeDecodeError:
        return ["  (бинарное содержимое: %s → %s)" % (sha256_bytes(old)[:12], sha256_bytes(new)[:12])]
    return ["  " + l.rstrip("\n") for l in difflib.unified_diff(a, b, "a/" + dst, "b/" + dst, n=1)]


# ------------------------------------------------------------------ транзакция раскладки (D10 R1: B7, B9)
class _LayoutTxn(object):
    """Мутации layout одной транзакцией. Инвариант: после ЛЮБОГО перехваченного исключения (IO, chmod, замена, удаление,
    отказ проверки после записи) дерево заказчика — байты, mode и наличие каждого затронутого пути — равно исходному.
    Порядок: (1) подготовка — все новые байты пишутся во временные файлы РЯДОМ с назначениями (новый inode, mode
    выставлен), недостающие каталоги создаются с записью в журнал; (2) фиксация — удаления, затем атомарные замены
    os.replace (назначение, разделяющее inode с чужим файлом через hard link, получает НОВЫЙ inode — сосед не меняется);
    (3) проверка после записи; (4) при исключении — откат журнала в обратном порядке."""

    TMP_PREFIX = _TMP_PREFIX

    def __init__(self):
        self.journal = []
        self.seq = 0

    def _snap(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        return data, os.stat(path).st_mode & 0o7777

    def _mkdirs(self, d):
        missing = []
        x = d
        while not os.path.isdir(x):
            missing.append(x)
            x = os.path.dirname(x)
        for md in reversed(missing):
            os.mkdir(md)
            self.journal.append(("mkdir", md))

    def _tmp_write(self, d, data, mode):
        self.seq += 1
        tmp = os.path.join(d, "%s%d-%d" % (self.TMP_PREFIX, os.getpid(), self.seq))
        self.journal.append(("tmp", tmp))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                view = view[n:]
        finally:
            os.close(fd)
        os.chmod(tmp, mode)
        return tmp

    def run(self, actions, removals, post_check=None):
        try:
            prepared = []
            for dst, data, mode in actions:
                self._mkdirs(os.path.dirname(dst))
                prepared.append((self._tmp_write(os.path.dirname(dst), data, int(mode, 8)), dst))
            for p in removals:
                data, mode = self._snap(p)
                self.journal.append(("removed", p, data, mode))
                os.remove(p)
            for tmp, dst in prepared:
                if os.path.lexists(dst):
                    data, mode = self._snap(dst)
                    self.journal.append(("replaced", dst, data, mode))
                else:
                    self.journal.append(("created", dst))
                os.replace(tmp, dst)
            if post_check is not None:
                post_check()
        except BaseException:
            self.rollback()
            raise
        self.journal = []

    def rollback(self):
        failed = []
        for rec in reversed(self.journal):
            try:
                kind, path = rec[0], rec[1]
                if kind == "tmp":
                    if os.path.lexists(path):
                        os.remove(path)
                elif kind == "created":
                    if os.path.lexists(path):
                        os.remove(path)
                elif kind in ("replaced", "removed"):
                    tmp = self._tmp_write(os.path.dirname(path), rec[2], rec[3])
                    os.replace(tmp, path)
                elif kind == "mkdir":
                    if os.path.isdir(path) and not os.listdir(path):
                        os.rmdir(path)
            except Exception as e:  # noqa: BLE001 — откат продолжается; невосстановленное называется поимённо
                failed.append("%s (%s: %s)" % (rec[1], type(e).__name__, e))
        self.journal = []
        if failed:
            _say("ОТКАТ НЕПОЛОН — восстановите вручную: %s" % "; ".join(failed))
        else:
            _say("откат: дерево заказчика возвращено к исходному состоянию (раскладка не применена)")


def _atomic_write(dst, data, mode):
    """Одиночная запись вне layout (validator): тот же механизм — новый inode и атомарная замена, откат при сбое."""
    _LayoutTxn().run([(dst, data, "%o" % mode)], [])


def _logical_lines(data):
    """Логические строки файла (терминатор LF или CRLF) — для сравнения; исходные байты не меняются (M1)."""
    return [l[:-1] if l.endswith(b"\r") else l for l in data.split(b"\n")]


def _ignore_lines_plan(old, new):
    """Роль lines (.gitignore): каждая обязательная строка ОБЯЗАНА действовать после раскладки. Нет строки — дописать в
    конец; есть, но после её последнего вхождения стоят отрицающие правила (`!…`), способные её отменить (последнее
    совпавшее правило git побеждает), — дописать ещё раз ПОСЛЕ них (B10). -> (новые байты | None, [дописанные строки])."""
    have = _logical_lines(old)
    add = []
    for req in [l for l in _logical_lines(new) if l.strip()]:
        idx = [i for i, l in enumerate(have) if l == req]
        if idx and not any(l.lstrip().startswith(b"!") for l in have[idx[-1] + 1:]):
            continue
        add.append(req)
    if not add:
        return None, []
    sep = b"" if not old or old.endswith(b"\n") else (b"\r\n" if old.endswith(b"\r") else b"\n")
    return old + sep + b"\n".join(add) + b"\n", add


def _check_ignored(repo, lines_entries, kit_root):
    """После записи: каждая обязательная строка-путь (без глоб-символов) роли lines действительно игнорируется —
    итог `git check-ignore`, не наличие байтов (B10). Иначе — отказ, транзакция откатывается."""
    for e in lines_entries:
        for req in [l for l in _logical_lines(_read(os.path.join(kit_root, e["src"]))) if l.strip()]:
            path = req.decode("utf-8").strip()
            if path.startswith(("#", "!")) or any(c in path for c in "*?[]\\"):
                continue
            r = _git(repo, "check-ignore", "-q", "--", path.lstrip("/"))
            if r.returncode == 128:
                raise Refuse("git check-ignore не отработал в %s (%s) — действие %s не проверить" % (repo, r.stderr.strip()[:200], e["dst"]))
            if r.returncode != 0:
                tracked = _git(repo, "ls-files", "--", path.lstrip("/")).stdout.strip()
                why = (" — файл в индексе git (git rm --cached %s)" % path) if tracked else \
                      " — правило перекрыто (вложенный .gitignore или иной источник правил с приоритетом выше)"
                raise Refuse("%s: после раскладки %s НЕ игнорируется (git check-ignore)%s; раскладка откатывается" % (e["dst"], path, why))


def _check_plan(repo, m, destinations, launch):
    """Единый план целей ДО первой мутации (B8): записи манифеста всех ролей, retire, служебный kit-version.yaml, реестр
    управляемых обёрток. Дубли (с точностью до регистра/нормализации), retire служебной цели/назначения/обёртки/
    ручного файла, физические алиасы (один inode под двумя целями) — отказ поимённо."""
    kinds = {}
    def add(rel, kind):
        k = path_key(rel)
        if k in kinds and not (kinds[k][1] == "workflow-registry" and kind == "entry:workflow") \
                and not (kinds[k][1] == "entry:workflow" and kind == "workflow-registry"):
            raise Refuse("план раскладки: цель %s дважды (%s и %s) — противоречие манифеста/метаданных" % (rel, kinds[k][1], kind))
        kinds.setdefault(k, (rel, kind))
    for e in m["entries"]:
        add(str(e["dst"]), "entry:" + e["role"])
    add(KIT_VERSION_FILE, "служебная запись")
    for d in destinations:
        add(d, "workflow-registry")
    for r in m.get("retire", []):
        add(str(r["path"]), "retire")
    seen = {}
    root = os.path.realpath(repo)
    for k, (rel, kind) in sorted(kinds.items()):
        p = os.path.join(root, *rel.split("/"))
        if not os.path.lexists(p):
            continue
        st = os.lstat(p)
        ino = (st.st_dev, st.st_ino)
        if ino in seen:
            raise Refuse("план раскладки: %s и %s — один физический файл (hard link/алиас) — отказ до мутаций" % (seen[ino], rel))
        seen[ino] = rel


def _check_customer_layer(repo, m):
    """D10 T24 (G-PROVIDER): инструкции агента (роль managed) собраны генератором под слой заказчика, и слой живёт в
    репозитории ЗАКАЗЧИКА (customer_layer.path, рядом с профилями), а не в комплекте. Привязка манифеста — sha256 байт
    слоя, под которые собраны выходы; layout сверяет её со слоем клона ДО мутаций. Нет слоя или он другой — именованный
    отказ rc 2 (комплект, собранный под чужой или образцовый слой, не ставится молча). Манифест без записей managed или
    без привязки — проверки нет."""
    cl = m.get("customer_layer")
    if not cl or not any(e["role"] == _MANAGED_ROLE for e in m["entries"]):
        return
    rel = cl["path"]
    p = safe_path(repo, rel)
    hint = ("образец — .workshop-ai/customer-layer.example.yaml (кладёт комплект) или bot/kit/ai/customer-layer.example.yaml "
            "в checkout комплекта; инструкции собираются под слой клона: "
            "profiles/build_profile.py --customer-layer <клон>/%s, затем build_manifest.py" % rel)
    if not os.path.lexists(p):
        raise Refuse("нет слоя заказчика %s: инструкции агента в комплекте собраны под слой sha256 %s — положите свой слой (%s); "
                     "установка отказана до мутаций" % (rel, cl["sha256"], hint))
    if not os.path.isfile(p):
        raise Refuse("слой заказчика %s — не обычный файл; установка отказана до мутаций" % rel)
    got = sha256_file(p)
    if got != cl["sha256"]:
        raise Refuse("слой заказчика %s (sha256 %s) не тот, под который собраны инструкции агента комплекта (sha256 %s) — "
                     "комплект собран под другой слой (%s); установка отказана до мутаций" % (rel, got, cl["sha256"], hint))
    _say("слой заказчика %s совпадает с привязкой манифеста (sha256 %s)" % (rel, got))


# ------------------------------------------------------------------ types-plan (D10 T24, REQ-085)
TYPES_CONFIG_FILE = ".workshop/types.yaml"
_TYPES_ITEM = re.compile(r"^  - name: (?P<name>[^ \t]+)[ \t]*$")
_ITEM_KEY_INDENT = 4        # отступ ключей элемента `  - name:` (колонка дефиса 2 + 2); сторож хвоста — та же граница
_SHADOW_LINE = re.compile(r"^WARNING\s+\S+?:(?P<line>\d+) W-CFG-KERNEL-SHADOW — .*?: (?P<name>[A-Z][A-Z0-9_]*) —")


def _types_layout(text, what):
    """Разметка блока types[] по строкам: -> (lines, i_types | None, flow_empty, [(name, start, end)], block_end).
    Поддержанная форма — ключ верхнего уровня `types:` и элементы `  - name: <ИМЯ>` с продолжением глубже двух
    пробелов, либо `types: []`. Перекрёстная сверка со строгим читателем: число и имена элементов == дереву, иначе
    «форма не поддержана» (отказ, а не догадка)."""
    lines = text.split("\n")
    tops = [i for i, l in enumerate(lines) if l.startswith("types:")]
    if len(tops) > 1:
        raise Refuse("%s: ключ types повторяется" % what)
    tree = yamlmini.loads(text) if not all(_blank(l) for l in text.split("\n")) else {}
    if not isinstance(tree, dict):
        raise Refuse("%s: не отображение верхнего уровня" % what)
    want = tree.get("types", None)
    if not tops:
        if want not in (None, []):
            raise Refuse("%s: форма types не поддержана" % what)
        return lines, None, False, [], len(lines)
    i = tops[0]
    rest = lines[i][len("types:"):].split("#", 1)[0].strip(_WS)
    if rest == "[]":
        if want != []:
            raise Refuse("%s: форма types не поддержана" % what)
        return lines, i, True, [], i + 1
    if rest:
        raise Refuse("%s: types — не блочный список (форма не поддержана: %r)" % (what, rest))
    names_at, j = [], i + 1
    while j < len(lines):
        l = lines[j]
        if l and not l.startswith(" ") and not l.startswith("#"):
            break
        m = _TYPES_ITEM.match(l)
        if m:
            names_at.append((m.group("name"), j))
        elif l.startswith("  - "):
            raise Refuse("%s:%d: элемент types без первого ключа name (форма не поддержана)" % (what, j + 1))
        j += 1
    stop = j
    content = _yaml_content_lines(lines, i + 1, stop)
    cont = [k for k in range(i + 1, stop) if content[k]]
    end = (cont[-1] + 1) if cont else i + 1
    items = []
    for k, (name, nl) in enumerate(names_at):
        nxt = names_at[k + 1][1] if k + 1 < len(names_at) else end
        last = max([x for x in range(nl, nxt) if content[x]] or [nl]) + 1
        # T24 R8O-02 (D10 T26): комментарий глубже колонки дефиса элемента (отступ ≥ отступа его ключей) после последнего
        # ключа — внутри отображения элемента, как комментарий между ключами: относится к элементу. Граница — `- name:`
        # следующего элемента, иначе конец блока types; пустые строки между ключом и таким комментарием — тоже элемента.
        lim = names_at[k + 1][1] if k + 1 < len(names_at) else stop
        for x in range(last, lim):
            if content[x]:
                break
            l = lines[x]
            if l.lstrip(_WS).startswith("#") and len(l) - len(l.lstrip(" ")) >= _ITEM_KEY_INDENT:
                last = x + 1
        items.append([name, nl, last, nl])
    for k, it in enumerate(items):
        floor = items[k - 1][2] if k else i + 1     # не заходить в хвост предыдущего элемента (R8O-02)
        start = it[3]
        while start - 1 >= floor and not content[start - 1] and lines[start - 1].lstrip(_WS).startswith("#"):
            start -= 1      # непрерывные комментарии прямо над `- name:` (без пустой строки) — этого элемента (R5F-02, R5O-06)
        it[1] = start
    if items:
        end = max(end, items[-1][2])                # хвостовой комментарий последнего элемента — внутри блока
    names = [str(e.get("name")) if isinstance(e, dict) else None for e in (want or [])]
    if names != [it[0] for it in items]:
        raise Refuse("%s: разметка types по строкам не совпала со строгим чтением (%s ≠ %s) — форма не поддержана"
                     % (what, [it[0] for it in items], names))
    return lines, i, False, [tuple(it) for it in items], end


_BLOCK_SCALAR = re.compile(r"^(?P<ind>[ ]*)(?P<dash>- )?(?:[^\s#\-][^:#]*|\"[^\"]*\"|'[^']*'):[ \t]+(?P<hdr>[|>][-+0-9]*)[ \t]*(?:#.*)?$")


def _yaml_content_lines(lines, lo, hi, owners=None):
    """Строки [lo, hi) — содержимое YAML (True) или нет (пустые и комментарии, False). Строка внутри блочного скаляра
    (`ключ: |` / `ключ: >`, строки глубже отступа ключа) — ДАННЫЕ, даже если начинается с `#` (T24 R5C-03): граница
    элемента — по YAML, а не по виду строки. -> {номер строки: bool}. owners (если дан) получает {строка данных
    блочного скаляра: строка его заголовка} — по нему видно chomping скаляра, которому принадлежит строка (R7O-02)."""
    out, key_ind, hdr = {}, None, None
    for k in range(lo, hi):
        l = lines[k]
        ind = len(l) - len(l.lstrip(" "))
        if key_ind is not None:
            if _blank(l):
                out[k] = False
                continue
            if ind > key_ind:
                out[k] = True
                if owners is not None:
                    owners[k] = hdr
                continue
            key_ind = None
        if _blank(l) or l.lstrip(_WS).startswith("#"):
            out[k] = False
            continue
        out[k] = True
        m = _BLOCK_SCALAR.match(l)
        if m:
            key_ind = len(m.group("ind")) + (2 if m.group("dash") else 0)
            hdr = k
    return out


def _keep_scalar_before(lines, content, owners, k):
    """Последняя строка-содержимое перед строкой k (пустые и комментарии пропускаются) — заголовок или данные блочного
    скаляра с chomping keep (`|+`, `>+`, с индикатором отступа тоже)? -> номер строки заголовка (с 0) или None.
    У такого скаляра хвостовые пустые строки до следующего содержимого — часть ЗНАЧЕНИЯ: правка сразу за ним меняет
    значение, сколько бы байт отрезка ни совпадало (T24 R7O-02 (б))."""
    j = k - 1
    while j >= 0 and not content.get(j, False):
        j -= 1
    if j < 0:
        return None
    h = owners.get(j, j)
    m = _BLOCK_SCALAR.match(lines[h])
    return h if m and "+" in m.group("hdr") else None


_KEEP_REFUSAL = ("%s:%d: блочный скаляр с chomping keep (`|+` / `>+`) кончается прямо %s — его хвостовые пустые строки "
                 "входят в значение, и план изменил бы значение; план не выдан. Уберите `+` у скаляра или поставьте после "
                 "него другой ключ того же элемента, и повторите")


def _check_config(validator, path):
    """Прогон `check-config` валидатора -> (строки ERROR, {номер строки: имя затенения}). Валидатор — единственный судья
    формы конфига: установщик не держит своей копии схемы."""
    try:
        p = subprocess.run([validator, "check-config", "--config", path], capture_output=True, text=True, timeout=120)
    except OSError as e:
        raise Refuse("валидатор не запускается (%s): %s — поставьте бинарь: install.py validator" % (validator, e))
    if "interface_version:" not in p.stdout:
        raise Refuse("валидатор %s не напечатал шапку отчёта — не тот бинарь" % validator)
    errors, shadows = [], {}
    for ln in p.stdout.split("\n"):
        if ln.startswith("ERROR"):
            errors.append(ln)
        m = _SHADOW_LINE.match(ln)
        if m:
            shadows[int(m.group("line"))] = m.group("name")
    if p.returncode == 2 and not errors:
        raise RuntimeError("check-config rc 2 без строк ERROR — отчёт валидатора не разобран")   # сбой инструмента — rc 10
    return errors, shadows


def _kernel_shadows(validator, path):
    """Имена объявлений, затеняющих форму ядра, по строкам W-CFG-KERNEL-SHADOW валидатора (номер строки -> имя)."""
    return _check_config(validator, path)[1]


def _plan_diff(text, new_text):
    """Печатаемый план — unified diff, применимый `git apply` к ИСХОДНЫМ байтам: строка без финального LF (у исходника
    или результата) получает маркер `\\ No newline at end of file`, иначе склеилась бы со следующей строкой плана."""
    out = []
    for ln in difflib.unified_diff(_lf_lines(text), _lf_lines(new_text),
                                   "a/" + TYPES_CONFIG_FILE, "b/" + TYPES_CONFIG_FILE):
        if ln.endswith("\n"):
            out.append(ln)
        else:
            out.append(ln + "\n")
            out.append("\\ No newline at end of file\n")
    return "".join(out)


def _segment(lines, start, end):
    """Байты отрезка [start, end) списка строк источника (text.split LF) — с LF там, где он был во входе."""
    out = "".join(l + "\n" for l in lines[start:end - 1]) + lines[end - 1]
    return out + "\n" if end < len(lines) else out


def _selfcheck_bytes(lines, kept, s_lines, added, new_text):
    """Инвариант байт (T24 R6O-03, правило §2: оракулу запрещён общий с писателем парсер — yamlmini не используется):
    байты каждого СОХРАНЯЕМОГО объявления результата == его отрезку во входе, каждого ДОБАВЛЕННОГО == его отрезку во входе
    --from, без каких-либо поправок (входы без финального LF до сюда не доходят — именованный отказ, R7O-02 (а)). Плюс
    сохранность хвоста: строки после конца элемента до следующего `- name:`, ключа верхнего уровня или конца файла,
    не вошедшие в элемент, — только пустые или комментарии мельче ключей элемента (отступ < 4): строку глубже (данные
    блочного скаляра) разметка не вправе отрезать. Нарушение — сбой инструмента rc 10, план не выдан."""
    def check(src, items, what):
        for it in items:
            name, start, end = it[0], it[1], it[2]
            seg = _segment(src, start, end)
            if seg not in new_text:
                raise RuntimeError("types-plan: байты объявления %s (%s) в результате не равны входу — план не выдан" % (name, what))
            k = end
            while k < len(src) and not src[k].startswith("  - ") and not (src[k] and not src[k].startswith((" ", "#"))):
                l = src[k]
                if l.strip(_WS) and not (l.lstrip(" ").startswith("#") and len(l) - len(l.lstrip(" ")) < 4):
                    raise RuntimeError("types-plan: после объявления %s (%s) осталась строка глубже ключей, не вошедшая в "
                                       "элемент (%d) — разметка отрезала данные; план не выдан" % (name, what, k + 1))
                k += 1
    check(lines, kept, "конфиг")
    if s_lines is not None:
        check(s_lines, added, "вход --from")


def _selfcheck_values(text, src, new_text, kept, added):
    """Инвариант значения (T24 R7O-02): дерево каждого сохраняемого объявления в результате == его дереву во входе,
    каждого добавленного == дереву во входе --from; прочие ключи верхнего уровня неизменны, config_version +1. Это
    страховка остатка домена после отказов (а)/(б): строгий читатель тот же, что у разметки, поэтому независимым оракулом
    она не считается — независимая сверка значений живёт в тестах (PyYAML). Расхождение — сбой инструмента rc 10."""
    old, new = yamlmini.loads(text), yamlmini.loads(new_text)

    def by_name(tree):
        return dict((str(e.get("name")), e) for e in ((tree or {}).get("types") or []) if isinstance(e, dict))

    def rest(tree):
        return dict((k, v) for k, v in tree.items() if k not in ("types", "config_version"))
    o, n = by_name(old), by_name(new)
    s = by_name(yamlmini.loads(src)) if src is not None else {}
    bad = [k for k in kept if n.get(k) != o.get(k)] + [k for k in added if n.get(k) != s.get(k)]
    if bad or rest(old) != rest(new) or new.get("config_version") != old.get("config_version") + 1:
        raise RuntimeError("types-plan: значение объявлений %s или ключей вне types в результате не равно входу — план "
                           "не выдан" % (bad or "вне types"))


def _selfcheck_plan(validator, raw, plan, new_text):
    """Инвариант плана (T24 R1F-01, R2C-01): результат ЛЮБОГО плана — валидный конфиг, и проверяется НАПЕЧАТАННЫЙ
    артефакт, а не задуманный текст. Во временном репозитории: исходные байты конфига, `git apply --check` печатаемого
    плана, `git apply`, байты результата == задуманному тексту, затем `check-config` валидатора на ПРИМЕНЁННОМ файле.
    План не применяется или применённый расходится с задуманным — сбой инструмента (rc 10, план не выдан); ошибки
    check-config — именованный отказ (rc 2, план не выдан); оставшееся затенение — сбой инструмента (rc 10)."""
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix=_TMP_PREFIX + "types-plan-")
    try:
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        os.makedirs(os.path.join(d, ".workshop"))
        path = os.path.join(d, TYPES_CONFIG_FILE)
        with open(path, "wb") as fh:
            fh.write(raw)
        pp = os.path.join(d, "types-plan-patch")
        with open(pp, "wb") as fh:
            fh.write(plan.encode("utf-8"))
        for extra in (["--check"], []):
            r = subprocess.run(["git", "-C", d, "apply"] + extra + [pp], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError("types-plan: печатаемый план не применяется к исходным байтам (git apply%s: %s)"
                                   % (" --check" if extra else "", r.stderr.strip()))
        got = _read(path)
        if got != new_text.encode("utf-8"):
            raise RuntimeError("types-plan: применённый план расходится с задуманным результатом")
        errors, shadows = _check_config(validator, path)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if errors:
        for ln in errors:
            _say("  " + ln)
        raise Refuse("план дал бы конфиг, который не проходит check-config (%d ошибок выше) — план не выдан; "
                     "исправьте объявления во входе (форма — схема конфига типов)" % len(errors))
    if shadows:
        raise RuntimeError("types-plan: в результате плана осталось затенение формы ядра %s" % sorted(shadows.values()))


def cmd_types_plan(args):
    repo = os.path.abspath(args.repo)
    cfg_path = safe_path(repo, TYPES_CONFIG_FILE)
    validator = args.validator or os.path.join(repo, VALIDATOR_BIN_DIR, VALIDATOR_BIN_NAME)
    if not os.path.exists(cfg_path):
        if args.from_file:
            raise Refuse("%s нет: стандартной поставки типов нет (REQ-085) — конфиг заказчика заводится его решением; "
                         "положите заготовку конфига (required_keys схемы конфига) и повторите" % TYPES_CONFIG_FILE)
        _say("types-plan: %s нет — стандартной поставки типов нет (REQ-085), формы ядра работают без конфига; "
             "ничего не записано" % TYPES_CONFIG_FILE)
        return
    raw = _read(cfg_path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refuse("%s: не UTF-8" % TYPES_CONFIG_FILE)
    if "\r" in text:
        raise Refuse("%s: CR в файле — форма не поддержана" % TYPES_CONFIG_FILE)
    if text.startswith("\ufeff"):
        raise Refuse("%s: BOM в начале файла — форма не поддержана (конфиг — UTF-8 без BOM)" % TYPES_CONFIG_FILE)
    if not os.path.isfile(validator):
        raise Refuse("нет бинаря валидатора %s — набор форм ядра установщик берёт у валидатора: install.py validator" % validator)
    lines, i_types, flow_empty, items, block_end = _types_layout(text, TYPES_CONFIG_FILE)
    pre_errors, shadows = _check_config(validator, cfg_path)
    if pre_errors:
        for ln in pre_errors:
            _say("  " + ln)
        raise Refuse("%s уже до плана не проходит check-config (%d ошибок выше) — план строится только от валидного "
                     "конфига; исправьте и повторите" % (TYPES_CONFIG_FILE, len(pre_errors)))
    remove = [it for it in items if shadows.get(it[3] + 1) == it[0]]
    unmatched = sorted(set(shadows.values()) - set(it[0] for it in remove))
    if unmatched:
        raise Refuse("валидатор назвал затенение %s, а разметка types его не нашла — форма не поддержана" % unmatched)
    add, same, conflicts = [], [], []
    if args.from_file:
        src_path = os.path.abspath(args.from_file)
        src = _read(src_path).decode("utf-8")
        s_lines, _si, _sf, s_items, _se = _types_layout(src, args.from_file)
        if not s_items:
            raise Refuse("%s: во входе нет объявлений types" % args.from_file)
        s_shadow = _kernel_shadows(validator, src_path)
        kern = sorted(set(s_shadow.values()))
        if kern:
            raise Refuse("во входе %s — формы ядра %s: их в конфиге не объявляют (REQ-085, ядро §14.1)" % (args.from_file, ", ".join(kern)))
        have = dict((it[0], it) for it in items)
        seen = set()
        for name, a, b, nl in s_items:
            if name in seen:
                raise Refuse("во входе %s тип %s дважды" % (args.from_file, name))
            seen.add(name)
            el = s_lines[a:b]                 # вставляется с комментарием над объявлением — он его (R5F-02)
            body = s_lines[nl:b]              # сравнение «то же / иное» — по самому объявлению, без комментария
            if name in have:
                h = have[name]
                cur = lines[h[3]:h[2]]
                (same if cur == body else conflicts).append((name, cur, body))
            else:
                add.append((name, el))
    if conflicts:
        for name, cur, el in conflicts:
            _say("КОНФЛИКТ: тип %s уже объявлен иначе:" % name)
            sys.stdout.write("".join(difflib.unified_diff([x + "\n" for x in cur], [x + "\n" for x in el],
                                                          TYPES_CONFIG_FILE + ":" + name, args.from_file + ":" + name)))
        raise Refuse("объявления %s в %s расходятся со входом — правка конфига решением заказчика, план не строится"
                     % (", ".join(c[0] for c in conflicts), TYPES_CONFIG_FILE))
    for name, _c, _e in same:
        _say("уже есть: %s" % name)
    if not remove and not add:
        _say("types-plan: без изменений (затенений формы ядра нет%s)" % (", новых типов нет" if args.from_file else ""))
        return
    # T24 R7O-02, решение окна: types-plan НИКОГДА не меняет значение сохраняемого или добавляемого объявления. Домен
    # сужен именованными отказами (rc 2, план не печатается): (а) затронутый файл не кончается LF; (б) скаляр keep на
    # границе правки. Остаток домена сторожит сверка значений после сборки (_selfcheck_values, сбой инструмента rc 10).
    if not text.endswith("\n"):
        raise Refuse("%s: файл не кончается переводом строки (LF), а план его правит — добавьте перевод строки в конец "
                     "файла и повторите" % TYPES_CONFIG_FILE)
    if add and not src.endswith("\n"):
        raise Refuse("%s: файл не кончается переводом строки (LF), а объявления из него вошли бы в план — добавьте "
                     "перевод строки в конец файла и повторите" % args.from_file)
    owners = {}
    content = _yaml_content_lines(lines, 0, len(lines), owners)
    points = [(it[1], "перед снимаемым объявлением %s" % it[0]) for it in remove]
    if add and not flow_empty:
        points.append((block_end, "перед вставкой новых объявлений") if i_types is not None
                      else (len(lines), "перед дописываемым блоком types"))
    if not add and i_types is not None and not flow_empty and len(remove) == len(items):
        points.append((i_types, "перед снимаемым ключом types"))
    for k, where in points:
        h = _keep_scalar_before(lines, content, owners, k)
        if h is not None:
            raise Refuse(_KEEP_REFUSAL % (TYPES_CONFIG_FILE, h + 1, where))
    if add:
        s_owners = {}
        s_content = _yaml_content_lines(s_lines, 0, len(s_lines), s_owners)
        added = set(n for n, _e in add)
        for name, _a, b, _nl in s_items:
            h = _keep_scalar_before(s_lines, s_content, s_owners, b) if name in added else None
            if h is not None:
                raise Refuse(_KEEP_REFUSAL % (args.from_file, h + 1, "в конце добавляемого объявления %s" % name))
    new = list(lines)
    drop = set()
    for _n, a, b, _nl in remove:
        drop.update(range(a, b))
    ins = [x for _n, el in add for x in el]
    if not flow_empty and i_types is not None and not ins and len(remove) == len(items):
        # Снято последнее объявление: ключ types убирается целиком вместе со своим блоком. Выбор по схеме конфига
        # (types-config-schema.yaml keys[name=types]: required: false) — отсутствующий ключ законен, а оставшийся
        # `types:` без элементов — null, E-CFG-KEY-FORM. `types: []` тоже законен, но это лишняя строка без смысла.
        drop.update(range(i_types, block_end))
    out = []
    for k, l in enumerate(new):
        if k in drop:
            continue
        if flow_empty and k == i_types and ins:
            out.append("types:")
            out.extend(ins)
            continue
        if not flow_empty and i_types is not None and k == block_end and ins:
            out.extend(ins)
        out.append(l)
    if not flow_empty and i_types is not None and block_end >= len(new) and ins:
        if out and out[-1] == "":
            out[-1:-1] = ins
        else:
            out.extend(ins)
    if i_types is None and ins:
        tail = [""] if out and out[-1] == "" else []
        if tail:
            out.pop()
        out += ["types:"] + ins + tail
    bumped = False
    for k, l in enumerate(out):
        m = re.match(r"^config_version: ([1-9][0-9]*)([ \t]*(?:#.*)?)$", l)
        if m:
            out[k] = "config_version: %d%s" % (int(m.group(1)) + 1, m.group(2))
            bumped = True
            break
    if not bumped:
        raise Refuse("%s: config_version не найден строкой верхнего уровня — форма не поддержана" % TYPES_CONFIG_FILE)
    new_text = "\n".join(out)
    if not new_text.endswith("\n"):
        raise RuntimeError("types-plan: результат без финального LF при входе с LF — сборка расходится с разметкой")
    check = yamlmini.loads(new_text)
    got = [str(e.get("name")) for e in (check.get("types") or [])]
    want = [it[0] for it in items if it not in remove] + [n for n, _e in add]
    if got != want:
        raise RuntimeError("types-plan: самопроверка плана не сошлась (%s ≠ %s)" % (got, want))   # сбой инструмента — rc 10
    _selfcheck_bytes(lines, [it for it in items if it not in remove], s_lines if args.from_file else None,
                     [it for it in (s_items if args.from_file else []) if it[0] in set(n for n, _e in add)], new_text)
    _selfcheck_values(text, src if args.from_file else None, new_text,
                      [it[0] for it in items if it not in remove], [n for n, _e in add])
    plan = _plan_diff(text, new_text)
    _selfcheck_plan(validator, raw, plan, new_text)
    for n, _a, _b, _nl in remove:
        _say("снять: %s — объявление формы ядра не читается (W-CFG-KERNEL-SHADOW), ядро побеждает" % n)
    for n, _e in add:
        _say("добавить: %s" % n)
    sys.stdout.write(plan)
    _say("types-plan: план выше — применить `git apply`, затем check-config; ничего не записано")


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
        # D10: инструкция агента с незаполненным плейсхолдером (шаблон не отрендерен) — отказ до мутаций
        if e["role"] == _MANAGED_ROLE:
            left = sorted(set(_PLACEHOLDER.findall(_read(src).decode("utf-8", "replace"))))
            if left:
                raise Refuse("незаполненный плейсхолдер %s в %s (источник %s) — инструкция не отрендерена, установка отказана до мутаций"
                             % (", ".join(left), e["dst"], e["src"]))
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
    _check_customer_layer(repo, m)
    for r in m.get("retire", []):
        _check_write_target(repo, str(r["path"]))
    _check_plan(repo, m, destinations, launch)
    laid_managed = _installed_managed(installed)
    supersedes = {}
    for r in m.get("supersedes", []):
        supersedes.setdefault(str(r["path"]), set()).add(str(r["sha256"]))
    # 2) план и дифф
    counts = {"create": 0, "update": 0, "same": 0, "keep": 0, "manual": 0, "remove": 0, "retire": 0, "tmp": 0}
    actions = []
    removals = []
    conflicts = []
    # 2а) временные файлы ПРЕРВАННОЙ раскладки (процесс убит между записью временного файла и заменой — журнал отката
    #     живёт только в памяти): снимаются ТОЛЬКО файлы точной формы имени этой транзакции (_LayoutTxn.TMP_PREFIX +
    #     <pid>-<seq>), ТОЛЬКО обычные файлы и ТОЛЬКО в каталогах целей этой раскладки; чужие файлы не трогаются
    #     (адверсарий B, m3). Снятие — в той же транзакции (откат вернёт и их).
    tmp_dirs = set(os.path.dirname(str(e["dst"])) for e in m["entries"] if e["role"] != _MANUAL_ROLE)
    tmp_dirs |= set(os.path.dirname(str(r["path"])) for r in m.get("retire", []))
    tmp_dirs |= set(os.path.dirname(d) for d in destinations) | {os.path.dirname(KIT_VERSION_FILE)}
    for rel_dir in sorted(tmp_dirs):
        d = os.path.join(os.path.realpath(repo), *[x for x in rel_dir.split("/") if x])
        # islink — страховка: каталог цели сюда симлинком не попадает (safe_path выше отверг ссылку в любой компоненте
        # каждого пути назначения/retire/обёртки/kit-version), поэтому мутант без неё эквивалентен (B2, H2)
        if not os.path.isdir(d) or os.path.islink(d):
            continue
        for name in sorted(os.listdir(d)):
            if not _TMP_ORPHAN.match(name):
                continue
            q = os.path.join(d, name)
            if not stat_is_regular(q):
                continue
            counts["tmp"] += 1
            _say("- %s (временный файл прерванной раскладки комплекта — снимается)" % "/".join(x for x in (rel_dir, name) if x))
            removals.append(q)
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
            if role == "config":
                # R1, F1: файл заказчика, которого нет на диске, но который есть в истории git, — скорее удалённая
                # настройка, чем первая установка; комплект кладёт шаблон, но громко называет, откуда вернуть своё
                was, _st, top_rel = _git_history_with(repo, str(e["dst"]), lambda b: True)
                if was:
                    _say("! %s: файл был в истории git (коммит %s) — кладётся ШАБЛОН; если это ваша настройка, верните её: "
                         "git show %s:%s" % (e["dst"], was[:12], was, top_rel))
            actions.append((dst, new, e["mode"]))
            continue
        old = _read(dst)
        if role == _MANAGED_ROLE:
            cur = sha256_bytes(old)
            if cur == e["sha256"]:
                counts["same"] += 1
                _say("  %s: без изменений" % e["dst"])
                continue
            known = set(supersedes.get(str(e["dst"]), ())) | ({laid_managed[str(e["dst"])]} if str(e["dst"]) in laid_managed else set())
            if cur not in known:
                conflicts.append("КОНФЛИКТ %s: локальная правка управляемого файла — ожидался sha256 %s, фактический %s; файл не тронут"
                                 % (e["dst"], " или ".join(sorted(known)) if known else "(прежней раскладки комплекта нет)", cur))
                continue
            counts["update"] += 1
            _say("~ %s (%s: прежнее содержимое комплекта %s)" % (e["dst"], role, cur[:12]))
            for l in _diff_text(old, new, e["dst"]):
                _say(l)
            actions.append((dst, new, e["mode"]))
            continue
        if role == _LINES_ROLE:
            merged, missing = _ignore_lines_plan(old, new)
            if merged is None:
                counts["same"] += 1
                _say("  %s: обязательные строки на месте и действуют (после них нет отрицаний)" % e["dst"])
                continue
            counts["update"] += 1
            _say("~ %s (%s: дописано строк %d — в конец, после чужих правил; чужие строки не тронуты)" % (e["dst"], role, len(missing)))
            for l in _diff_text(old, merged, e["dst"]):
                _say(l)
            actions.append((dst, merged, "%o" % (os.stat(dst).st_mode & 0o777)))
            continue
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
    # 2б) retire: снимается только файл с ожидаемым sha256 (с диффом); иной — именованный конфликт. Ожидаемых — до двух:
    #     отпечаток манифеста и отпечаток последней раскладки ЭТОГО пути комплектом (kit-version.yaml managed) — прежнее
    #     назначение managed, выпавшее из манифеста (переезд профилей), снимается в любой выданной версии; правка — конфликт
    for r in m.get("retire", []):
        p = safe_path(repo, str(r["path"]))
        if not os.path.exists(p):
            _say("  %s: retire — файла нет (снят раньше или не ставился)" % r["path"])
            continue
        cur = sha256_file(p)
        expected = [str(r["sha256"])]
        laid = laid_managed.get(str(r["path"]))
        if laid is not None and laid not in expected:
            expected.append(laid)
        if cur not in expected:
            conflicts.append("КОНФЛИКТ %s: локальная правка снимаемого файла — ожидался sha256 %s, фактический %s; файл не тронут"
                             % (r["path"], " или ".join(expected), cur))
            continue
        counts["retire"] += 1
        if cur == str(r["sha256"]):
            _say("- %s (retire: sha256 совпал с ожидаемым %s — снимается)" % (r["path"], str(r["sha256"])[:12]))
        else:
            _say("- %s (retire: sha256 совпал с последней раскладкой комплекта %s — снимается)" % (r["path"], cur[:12]))
        for l in _diff_text(_read(p), b"", str(r["path"])):
            _say(l)
        removals.append(p)
    if conflicts:
        for c in conflicts:
            _say(c)
        raise Refuse("конфликтов %d: локальные правки управляемых/снимаемых файлов — ничего не записано; перенесите правки в "
                     "свои файлы и верните/удалите названные файлы, затем повторите layout" % len(conflicts))
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
    if m.get("retire"):
        summary += " retire=%d" % counts["retire"]
    if counts["tmp"]:
        summary += " tmp=%d" % counts["tmp"]
    if args.dry_run:
        _say("layout (dry-run): %s" % summary)
        return
    lines_entries = [e for e in m["entries"] if e["role"] == _LINES_ROLE]
    _LayoutTxn().run(actions, removals, post_check=(lambda: _check_ignored(repo, lines_entries, kit_root)) if lines_entries else None)
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
    rel = _pinned_release(release_doc)
    if rel is not None:
        for a in rel.get("artifacts") or []:
            if a.get("target") == target:
                return pinned, a
        raise Refuse("в релизе %s нет артефакта для цели %s" % (pinned, target))
    raise Refuse("пиннованная версия %s отсутствует в validator-release.yaml" % pinned)


def _pinned_release(release_doc):
    pinned = str(release_doc.get("pinned_version"))
    for r in release_doc.get("releases") or []:
        if str(r.get("version")) == pinned:
            return r
    return None


_REPORT_HEADER = re.compile(r"^-- interface_version: ([0-9]+); validator: ([^;\s]+);")


def _binary_header(path, timeout_s=30):
    """(interface_version, validator) из шапки отчёта бинаря либо (None, причина). Вызов — форма, существующая во
    ВСЕХ выпущенных версиях (check-file пустого файла без конфига и пути): шапку печатает любой прогон, rc не важен."""
    import tempfile
    d = tempfile.mkdtemp(prefix=_TMP_PREFIX + "probe-")
    try:
        probe = os.path.join(d, "probe.md")
        with open(probe, "wb"):
            pass
        try:
            r = subprocess.run([path, "check-file", probe, "--no-config", "--no-path"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s)
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, "не исполняется на хосте установки (%s)" % type(e).__name__
        for line in r.stdout.decode("utf-8", "replace").split("\n"):
            m = _REPORT_HEADER.match(line)
            if m:
                return (m.group(1), m.group(2)), None
        return None, "шапка отчёта не найдена в выводе (rc=%d)" % r.returncode
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def _verify_version(data, release, version, target):
    """Сверка версии бинаря с релизом манифеста (обязательна для релизов, объявляющих interface_version)."""
    want_iv = release.get("interface_version") if release else None
    if want_iv is None:
        return
    import tempfile
    d = tempfile.mkdtemp(prefix=_TMP_PREFIX + "bin-")
    try:
        tmp = os.path.join(d, VALIDATOR_BIN_NAME)
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o755)
        got, why = _binary_header(tmp)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    if got is None:
        try:
            host = host_target()
        except Refuse:
            host = None
        if host is not None and host == target:
            raise Refuse("бинарь валидатора %s (%s) для цели хоста: %s — версию по манифесту сверить нельзя, установка отказана"
                         % (version, target, why))
        _say("~ версия бинаря %s (%s) не сверена исполнением: %s; цель ≠ хост установки — сверен только sha256"
             % (version, target, why))
        return
    if got != (str(want_iv), str(version)):
        raise Refuse("бинарь сообщает interface_version %s, validator %s; манифест — interface_version %s, версия %s: разметка "
                     "релиза расходится с бинарём — установка отказана" % (got[0], got[1], want_iv, version))
    _say("validator %s: версия и interface_version %s сверены по шапке отчёта бинаря" % (version, want_iv))


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
    _verify_version(data, _pinned_release(doc), version, args.target)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if ignore_file is not None and not os.path.exists(ignore_file):
        _atomic_write(ignore_file, b"*\n", 0o644)  # каталог самоигнорируемый: бинарь в коммит не попадает
    _atomic_write(dest, data, 0o755)             # новый inode + атомарная замена (hard link на бинарь не портит соседа)
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
    paths += [str(r["path"]) for r in m.get("retire", [])]      # D10: снятые retire-файлы — tracked-удаления в коммите установки
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
    p = sub.add_parser("storage-init")
    p.add_argument("--new-storage-prefix", action="store_true",
                   help="процедура смены хранилища: создать новый key_prefix, хотя в истории git прежний есть")
    sub.add_parser("storage-status")
    p = sub.add_parser("types-plan")
    p.add_argument("--from", dest="from_file", default=None, help="файл с объявлениями типов заказчика (types: […])")
    p.add_argument("--validator", default=None, help="бинарь валидатора (по умолчанию .workshop-bin/workshop-validator репозитория)")
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    try:
        {"check-kit-ref": cmd_check_kit_ref, "check-secrets": cmd_check_secrets, "layout": cmd_layout,
         "validator": cmd_validator, "check-people": cmd_check_people, "commit": cmd_commit,
         "storage-init": cmd_storage_init, "storage-status": cmd_storage_status,
         "types-plan": cmd_types_plan}[args.cmd](args)
    except _StorageFault as e:
        sys.stdout.write("TOOL_FAILURE %s\n" % e)
        return 10
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
