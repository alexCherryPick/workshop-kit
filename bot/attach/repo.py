# -*- coding: utf-8 -*-
"""attach.repo — корпус вложений репозитория заказчика и его конфиг хранилища (D20 T4).

Владелец — D20 T4. Над адаптером T2 (attach.core) и конфигом T3 (.workshop/storage.yaml):
    load_repo_config(repo)                          -> Config (файла нет — «хранилище не настроено»)
    corpus(repo)                                    -> список (путь от корня, Classified | None) по глобу нормы
    pointers_by_state(repo)                         -> счёт по состояниям (status_facts нормы §9.8)
    verify_corpus(repo, config, env, max_pointers)  -> сбои проверки stored/pending (object-missing, size-mismatch, sha-mismatch)
    status(repo, config, env, verify, max_pointers) -> факты статуса для /status бота (D18) и CLI — ДАННЫЕ, не текст
    paths_with_key(repo, key)                       -> все указатели с этим key (изъятие одним коммитом)
    withdraw_key_set(repo, path, reason, config, withdraw_credentials, env)
                                                    -> изъятие ВСЕХ указателей с key пути — ТОЛЬКО для человека (CLI);
                                                       API бота (attach.botapi) его не импортирует и не открывает

Корпус — файлы по глобу нормы layout.glob_all_attachment_bytes (`**/attachments/*/*`) в рабочем дереве: обход без
следования по symlink, `.git` и вложенные репозитории (каталог с `.git` внутри, например checkout комплекта
.workshop-kit/ в bootstrap) не входят. Классификация — attach.pointer.classify по первым max_bytes+1 байтам файла,
открытого с O_NOFOLLOW | O_NONBLOCK (FIFO и устройство не вешают обход; не обычный файл — не судится, считается).
"""
import os
import stat

from . import core as C
from . import fsio as FS
from . import norm as N
from . import pointer as P

__all__ = ["STORAGE_CONFIG_REL", "VERIFICATION_FAILURES", "PROBE_OUTCOMES", "load_repo_config", "corpus",
           "pointers_by_state", "verify_corpus", "status", "paths_with_key", "key_of", "withdraw_key_set"]

STORAGE_CONFIG_REL = ".workshop/storage.yaml"   # файл конфига T3 (роль config комплекта)

# §9.8 нормы: «сбои последней проверки (object-missing, size-mismatch, sha-mismatch)», исход пробы
# «ok · storage-denied · storage-unavailable». В реестре нормы эти подмножества названы прозой (status_facts —
# только имена фактов), поэтому здесь — подмножества, сверяемые с реестром исходов чтения при импорте.
VERIFICATION_FAILURES = ("object-missing", "size-mismatch", "sha-mismatch")
PROBE_OUTCOMES = ("ok", "storage-denied", "storage-unavailable")
NOT_JUDGED = (("pointer-invalid", "pointer-invalid"), ("pointer-version-unknown", "pointer-version-unknown"),
              ("lfs", "lfs-unsupported"))     # класс classify -> исход чтения нормы
if not (set(VERIFICATION_FAILURES) | set(PROBE_OUTCOMES) | set(o for _k, o in NOT_JUDGED)) <= set(N.READ_OUTCOMES):
    raise P.NormDrift("подмножества статуса вне adapter_outcomes.read нормы")
_STATUS_FACTS_CODE = ("storage_configured", "storage_probe_outcome", "pointers_by_state", "last_verification_failures")
if tuple(N.STATUS_FACTS) != _STATUS_FACTS_CODE:
    raise P.NormDrift("storage_binding.status_facts нормы и статус кода разошлись")
if N.GLOB_ALL_ATTACHMENTS != "**/" + N.RESERVED_DIR + "/*/*":
    raise P.NormDrift("layout.glob_all_attachment_bytes вне формы обхода кода")

_O_READ = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))


def plain_path(p):
    """Путь вызывающего без ведущих `./` (CLI и API бота; ядро T2 компоненты «.» отвергает — R3). `./x` и `x`
    разрешаются одинаково (`.` — сам текущий каталог), поэтому снятие — не лексическая нормализация: `..`, `//` и `.`
    внутри пути остаются и судятся ядром. «.» и «./» целиком — текущий каталог (абсолютный путь)."""
    if not isinstance(p, (str, os.PathLike)):
        return p
    p = os.fspath(p)
    if not isinstance(p, str):
        return p
    while p.startswith("./") and not p.startswith(".//"):
        p = p[2:]
    return os.getcwd() if p in ("", ".") else p


# --------------------------------------------------------------------------- конфиг заказчика
@C._guard
def load_repo_config(repo):
    """.workshop/storage.yaml репозитория (формат T3: подмножество YAML yamlmini) -> Config адаптера. Файла нет —
    «хранилище не настроено» (load_config({})). Не обычный файл, не UTF-8, не разбирается — ConfigError: сообщения
    содержимого файла не отражают (там может стоять значение). Суд фактов — только load_config T2."""
    import yamlmini
    path = os.path.join(os.fspath(repo), *STORAGE_CONFIG_REL.split("/"))
    d = os.path.dirname(path)
    if os.path.islink(d):     # как safe_path установщика T3: каталог настроек комплекта — не symlink
        raise C.ConfigError("%s — symlink" % os.path.dirname(STORAGE_CONFIG_REL))
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return C.load_config({})
    except OSError as e:
        raise C.ConfigError("%s не читается: %s" % (STORAGE_CONFIG_REL, type(e).__name__)) from None
    if not stat.S_ISREG(st.st_mode):
        raise C.ConfigError("%s — не обычный файл" % STORAGE_CONFIG_REL)
    try:
        fd = os.open(path, _O_READ)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise C.ConfigError("%s — не обычный файл" % STORAGE_CONFIG_REL)
            raw = f.read()
    except OSError as e:
        raise C.ConfigError("%s не читается: %s" % (STORAGE_CONFIG_REL, type(e).__name__)) from None
    try:
        doc = yamlmini.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise C.ConfigError("%s не UTF-8" % STORAGE_CONFIG_REL) from None
    except Exception:   # noqa: BLE001 — сообщение разбора может отражать строку файла: только класс
        raise C.ConfigError("%s не разбирается строгим загрузчиком YAML" % STORAGE_CONFIG_REL) from None
    if doc is None:
        doc = {}
    return C.load_config(doc)


# --------------------------------------------------------------------------- корпус
def _read_head(path):
    """Первые max_bytes+1 байт обычного файла (O_NOFOLLOW | O_NONBLOCK, затем fstat S_ISREG) или None."""
    try:
        fd = os.open(path, _O_READ)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        os.set_blocking(fd, True)
        out = b""
        while len(out) < P.MAX_BYTES + 1:
            chunk = os.read(fd, P.MAX_BYTES + 1 - len(out))
            if not chunk:
                break
            out += chunk
        return out
    finally:
        os.close(fd)


def _walk(repo):
    """Пути от корня (POSIX) файлов по глобу `**/attachments/*/*`, отсортированы. Без следования по symlink; .git и
    вложенные репозитории не входят."""
    repo = os.fspath(repo)
    out = []
    for root, dirs, files in os.walk(repo, topdown=True, followlinks=False):
        rel_root = os.path.relpath(root, repo)
        keep = []
        for d in dirs:
            if d == ".git":
                continue
            if os.path.lexists(os.path.join(root, d, ".git")):   # вложенный репозиторий (checkout комплекта и т. п.)
                continue
            keep.append(d)
        dirs[:] = sorted(keep)
        parts = [] if rel_root == "." else rel_root.split(os.sep)
        if len(parts) >= 2 and parts[-2] == N.RESERVED_DIR:
            # attachments/<x>/<имя>: файлы и прочие не-каталоги (symlink, FIFO) — в корпус; каталоги глубже глобом
            # нормы не покрываются (вложенность запрещена) — обход их не продолжает
            # имена `.<имя>.tmp-<12 hex>` зарезервированы адаптером (временные файлы атомарной записи, подметаются
            # под блокировкой) — не вложения
            out += ["/".join(parts + [f]) for f in files if FS._TMP_RE.fullmatch(f) is None]
            dirs[:] = []
    return sorted(out)


@C._guard
def corpus(repo):
    """[(путь от корня, Classified | None)]; None — не обычный файл (symlink, FIFO, каталог, устройство)."""
    out = []
    for rel in _walk(repo):
        head = _read_head(os.path.join(os.fspath(repo), *rel.split("/")))
        out.append((rel, None if head is None else P.classify(head)))
    return out


def _counts(items):
    by_state = dict((s, 0) for s in P.POINTER_STATES)
    not_judged = dict((o, 0) for _k, o in NOT_JUDGED)
    kind_to_outcome = dict(NOT_JUDGED)
    git_bytes = non_regular = 0
    for _rel, c in items:
        if c is None:
            non_regular += 1
        elif c.kind == "pointer":
            by_state[c.state] += 1
        elif c.kind == "bytes":
            git_bytes += 1
        else:
            not_judged[kind_to_outcome[c.kind]] += 1
    return by_state, git_bytes, not_judged, non_regular


@C._guard
def pointers_by_state(repo):
    by_state, git_bytes, not_judged, non_regular = _counts(corpus(repo))
    return {"pointers_by_state": by_state, "bytes_in_git": git_bytes, "not_judged": not_judged,
            "non_regular": non_regular}


@C._guard
def verify_corpus(repo, config, env=None, max_pointers=None, items=None):
    """attach.verify по каждому stored/pending указателю корпуса (в порядке путей). -> {checked, outcomes{исход: n},
    failures[{path, outcome}] (только VERIFICATION_FAILURES), truncated, input_errors}. Байты не удерживаются."""
    if max_pointers is not None and (isinstance(max_pointers, bool) or not isinstance(max_pointers, int)
                                     or max_pointers < 0):
        raise C.AttachInputError("max_pointers — целое >= 0")
    items = corpus(repo) if items is None else items
    todo = [rel for rel, c in items if c is not None and c.kind == "pointer" and c.state in ("stored", "pending")]
    truncated = max_pointers is not None and len(todo) > max_pointers
    if truncated:
        todo = todo[:max_pointers]
    outcomes, failures, input_errors = {}, [], 0
    for rel in todo:
        try:
            r = C.verify(os.path.join(os.fspath(repo), *rel.split("/")), config, env)
        except C.AttachInputError:
            input_errors += 1          # путь сменился между обходом и проверкой, symlink-компонент и т. п.
            continue
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
        if r.outcome in VERIFICATION_FAILURES:
            failures.append({"path": rel, "outcome": r.outcome})
    return {"checked": len(todo), "outcomes": outcomes, "failures": failures, "truncated": truncated,
            "input_errors": input_errors}


@C._guard
def status(repo, config, env=None, verify=False, max_pointers=None):
    """Факты статуса нормы §9.8 (storage_binding.status_facts) — данные для /status бота и CLI, не текст ответа.
    last_verification_failures — сбои проверки, выполненной ЭТИМ вызовом (verify=True); без проверки — None
    (сохранённого «последнего» результата нет: кеш — дело вызывающего)."""
    probe = C.probe_storage(config, env)
    items = corpus(repo)
    by_state, git_bytes, not_judged, non_regular = _counts(items)
    ver = verify_corpus(repo, config, env, max_pointers=max_pointers, items=items) if verify else None
    return {"storage_configured": probe["storage_configured"],
            "storage_probe_outcome": probe["storage_probe_outcome"],
            "probe_detail": probe["detail"],
            "pointers_by_state": by_state,
            "bytes_in_git": git_bytes,
            "not_judged": not_judged,
            "non_regular": non_regular,
            "last_verification_failures": None if ver is None else ver["failures"],
            "verification": None if ver is None else {k: ver[k] for k in ("checked", "outcomes", "truncated",
                                                                          "input_errors")}}


# --------------------------------------------------------------------------- один key — один коммит
@C._guard
def key_of(path):
    """key указателя stored/pending по пути (иначе AttachInputError)."""
    C._carrier_parts(path)
    head = _read_head(os.fspath(path))
    if head is None:
        raise C.AttachInputError("по пути нет обычного файла")
    c = P.classify(head)
    if c.kind != "pointer" or "key" not in c.fields:
        raise C.AttachInputError("по пути не указатель с key (stored | pending)")
    return c.fields["key"]


@C._guard
def paths_with_key(repo, key):
    """Все указатели корпуса с этим key (immutability.secret_in_storage_object: «перевести ВСЕ указатели с этим key в
    withdrawn одним коммитом») и, для сведения, unsaved с тем же sha256 (key у них нет). -> {key, paths, unsaved_same_sha256}."""
    if not isinstance(key, str) or not P._full("key", key):
        raise C.AttachInputError("key вне грамматики указателя")
    sha = key[len(P.KEY_PREFIX):]
    paths, related = [], []
    for rel, c in corpus(repo):
        if c is None or c.kind != "pointer":
            continue
        if c.fields.get("key") == key:
            paths.append(rel)
        elif c.state == "unsaved" and c.fields.get("sha256") == sha:
            related.append(rel)
    return {"key": key, "paths": paths, "unsaved_same_sha256": related}


def _judge_member(repo, rel, key):
    """Суд элемента набора ДО любого DELETE: путь — грамматика носителя (ядро: layout.path_pattern, filename.pattern,
    без «.»/«..»), обычный файл, указатель stored | pending с ЭТИМ key. -> (None, None) | ("input", причина)."""
    full = os.path.join(os.fspath(repo), *rel.split("/"))
    try:
        C._carrier_parts(full)
    except C.AttachInputError as e:
        return "input", str(e)
    head = _read_head(full)
    if head is None:
        return "input", "по пути нет обычного файла"
    c = P.classify(head)
    if c.kind != "pointer" or c.state not in ("stored", "pending") or c.fields.get("key") != key:
        return "input", "по пути не указатель stored | pending с этим key (%s)" % (P.state_of(c) or c.kind)
    return None, None


def _key_set_candidates(repo, key):
    """Все файлы корпуса, относящиеся к key: указатели с этим key (по содержимому, ЛЮБОЕ имя — нарушитель раскладки
    тоже) и файлы с сигнатурой указателя, чьи байты называют этот key, но не разбираются (битый указатель)."""
    line = b"\nkey " + key.encode("ascii") + b"\n"
    out = []
    for rel in _walk(repo):
        head = _read_head(os.path.join(os.fspath(repo), *rel.split("/")))
        if head is None:
            continue
        c = P.classify(head)
        if (c.kind == "pointer" and c.fields.get("key") == key) or (head.startswith(P.MAGIC_PREFIX) and line in head):
            out.append(rel)
    return out


@C._guard
def withdraw_key_set(repo, path, reason, config, withdraw_credentials, env=None, _candidates=None):
    """Изъятие объекта и ВСЕХ указателей с его key — для ОДНОГО коммита вызывающего. Только для человека: ключ изъятия —
    его (withdraw_credentials — имена переменных окружения), бот этой функции не получает (attach.botapi).

    Инвариант (R1 F1): ни одно необратимое действие (DELETE) не исполняется, пока ВЕСЬ набор не прошёл суд: причина и
    имена ключа; каждый элемент — грамматика пути, обычный файл, указатель stored | pending с этим key (_judge_member).
    Набор — все указатели с key по содержимому (любое имя) и битые указатели, называющие key. Хоть один элемент не
    прошёл суд — ничего не изымается: complete=False, у элемента error/detail, staged пуст. Ошибка элемента — его
    результат, а не исключение набора (CLI rc 0, исход — в выводе).
    Исполнение: пути по порядку; первый DELETE удаляет объект, следующие получают 404 (законно). Отказ хранилища ДО
    первого успешного изъятия — остановка, ничего не изменено. После первого изъятия объект удалён — остальные элементы
    переводятся до конца; сбой элемента — его error/outcome, complete=False, staged — то, что изменено (повтор — с путём
    любого оставшегося stored | pending). -> {key, results[{path, error, detail, result}], staged, complete,
    unsaved_same_sha256}. _candidates — только тесты (набор, изменившийся между сбором и судом)."""
    if reason not in P.STATE_REASONS["withdrawn"]:
        raise C.AttachInputError("reason изъятия — %s" % " | ".join(P.STATE_REASONS["withdrawn"]))
    try:
        C._cred_names(withdraw_credentials, "withdraw_credentials")
    except C.ConfigError as e:
        raise C.AttachInputError(str(e)) from None
    key = key_of(path)
    related = paths_with_key(repo, key)["unsaved_same_sha256"]
    members = sorted(_candidates if _candidates is not None else _key_set_candidates(repo, key))
    judged = [(rel,) + _judge_member(repo, rel, key) for rel in members]
    results = [{"path": rel, "error": err, "detail": why, "result": None} for rel, err, why in judged]
    if any(err is not None for _r, err, _w in judged) or not members:
        return {"key": key, "results": results, "staged": [], "complete": False, "unsaved_same_sha256": related}
    staged, complete, deleted = [], True, False
    for item in results:
        full = os.path.join(os.fspath(repo), *item["path"].split("/"))
        try:
            r = C.withdraw(full, reason, config, withdraw_credentials, env)
        except C.AttachInputError as e:
            item["error"], item["detail"] = "input", str(e)
            complete = False
            if not deleted:
                break
            continue
        item["result"] = r
        if r.outcome is not None:
            complete = False
            if not deleted:
                break               # DELETE не исполнен — ничего не изменено
            continue
        deleted = deleted or r.state == "withdrawn"
        staged += [x for x in r.staged if x not in staged]
    for item in results:
        if item["result"] is None and item["error"] is None:
            item["detail"] = "not-attempted"
    return {"key": key, "results": results, "staged": staged, "complete": complete, "unsaved_same_sha256": related}
