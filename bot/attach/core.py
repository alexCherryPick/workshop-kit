# -*- coding: utf-8 -*-
"""attach.core — адаптер вложений git / S3-совместимого хранилища (норма 04 §6, §9; контракт D20 T2).

Владелец — D20 T2. Python stdlib. Коммитов адаптер НЕ делает: он кладёт байты или указатель в рабочее
дерево по пути §2.1 и возвращает пути для стейджинга; атомарный коммит вместе с текстом — слой записи
вызывающего (норма §5). Повтор после сбоя — с тем же uuid и именем файла.

API (все — над байтами, без текстовых режимов):
    route(size, config, obtained=True, data_prefix=b"", env=None)          -> Route
    write_attachment(record_dir, record_id, data, *, ext, config, uuid=None, slug=None, source=None,
                     media_type=None, declared_size=None, durable_queue=False, defer_upload=False,
                     env=None)                                               -> WriteResult
    read_attachment(path, config, env=None)                                  -> ReadResult (data только при in-git | ok)
    verify(path, config, env=None)                                           -> ReadResult (без данных, потоково)
    complete_pending(path, data, config, env=None)                           -> WriteResult (меняется только строка state)
    fail_pending(path)                                                       -> WriteResult (pending -> unsaved upload-failed)
    late_save(path, data, config, env=None)                                  -> WriteResult (unsaved -> stored | git)
    withdraw(path, reason, config, withdraw_credentials, env=None)           -> WriteResult (отдельная привязка ключа изъятия)
    probe_storage(config, env=None)                                          -> dict (HEAD канарейки; статус для T4)
    ensure_canary(config, env=None)                                          -> dict (канарейка ключом писателя; T3)
    save_bytes_outside_carriers(out, data, source_path=None)                 -> None (единственная запись ВНЕ носителей)
    load_config(mapping)                                                     -> Config

Инварианты R1/R2 (протоколы адверсария Codex R1, R2 в папке T2):
  * ЕДИНЫЙ контроль записи в носитель: любая запись по пути под attachments/<record-id>/ идёт только через
    _Carrier.put (суд перехода §9.6, перечтение и разбор своего вывода). Запись вне носителей (CLI read --out) —
    save_bytes_outside_carriers, отказывающая в назначении под attachments/ и в алиасах.
  * Проверенный объект ФС и изменяемый — один и тот же: каталоги открываются цепочкой дескрипторов (O_NOFOLLOW),
    все чтения, создания и атомарные замены — через dir_fd (attach.fsio); строковый путь после проверки повторно
    не разрешается.
  * Переход атомарен: перечтение, проверки, сеть, запись — под flock дескриптора attachments/<record-id>/.
  * Проверки до сети: существующий носитель, sha256/size, допустимость операции — ДО любого PUT/DELETE.
  * Чтение — один открытый файл: классификация и выдача байт из него же.
  * Доступность одного объекта не доказывает отсутствие другого: 404 → отсутствие; 403 → storage-denied всегда
    (без ListBucket — деталь ambiguous-403-no-list). Запись после неоднозначного HEAD 403 идёт PUT'ом (ключ
    контентный, PUT идемпотентен). Канарейка — только проба ключа и статуса (probe_storage).
  * Ни одна строка хранилища не выходит наружу как есть: код ошибки — литерал закрытого перечня (attach.s3).

Исходы — только из реестров нормы (attach.norm: READ_OUTCOMES / WRITE_OUTCOMES). Собственная ошибка адаптера
(неожиданное исключение, порча конфига, сбой разбора собственного вывода, дрейф реестров) — ОТДЕЛЬНЫЙ
фатальный исход: исключение AdapterFault (исход ADAPTER_FAULT, в CLI — rc 3), никогда не смешивается с
исходами нормы. Ошибка входа вызывающего — AttachInputError (rc 2).

CLI: python3 -m bot.attach <команда> … — attach.cli (D20 T4); схема --json — attach.contract.
"""
import functools
import hashlib
import math
import os
import re
import sys

from . import norm as N
from . import pointer as P
from . import s3 as S3
from . import fsio as FS

__all__ = ["ADAPTER_FAULT", "AdapterFault", "ConfigError", "AttachInputError", "Config", "Binding", "Route",
           "WriteResult", "ReadResult", "load_config", "route", "write_attachment", "read_attachment", "verify",
           "complete_pending", "confirm_pending", "fail_pending", "late_save", "withdraw", "probe_storage", "ensure_canary",
           "CANARY_BODY", "save_bytes_outside_carriers", "attachment_relpath", "main"]

ADAPTER_FAULT = "adapter-fault"


class AdapterFault(RuntimeError):
    """Собственная ошибка адаптера — фатальный исход вне таблиц нормы."""
    outcome = ADAPTER_FAULT


class ConfigError(AdapterFault):
    """Порча конфига: присутствующий факт неверного типа или формы. Сообщение входных значений не отражает."""


class AttachInputError(ValueError):
    """Вход вызывающего вне контракта (путь, имя, причина, состояние) — адаптер не действует."""


READ = frozenset(N.READ_OUTCOMES)
WRITE = frozenset(N.WRITE_OUTCOMES)
if ADAPTER_FAULT in READ or ADAPTER_FAULT in WRITE:
    raise P.NormDrift("имя фатального исхода совпало с исходом нормы")
_USER_MARK = dict(N.UNSAVED_REASONS)
_CONFIRMED = ("uploaded", "already-present", "repaired")


def _ro(name):
    if name not in READ:
        raise AdapterFault("исход чтения вне нормы: %s" % name)
    return name


def _wo(name):
    if name not in WRITE:
        raise AdapterFault("исход записи вне нормы: %s" % name)
    return name


# --------------------------------------------------------------------------- guard
def _guard(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except (AttachInputError, AdapterFault):
            raise
        except P.NormDrift as e:
            raise AdapterFault("дрейф реестров нормы: %s" % e) from None
        except Exception as e:  # noqa: BLE001 — всё неожиданное — фатальный исход адаптера
            # from None: контекст исходного исключения (его текст — чужой и может нести что угодно) в
            # traceback фатального исхода не попадает; наружу — только имя класса
            raise AdapterFault("неожиданная ошибка адаптера: %s" % type(e).__name__) from None
    return wrapper


# --------------------------------------------------------------------------- конфиг
_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,127}")
_CRED_KEYS = ("access_key_id", "secret_access_key")
DEFAULT_REGION = "us-east-1"
_REQUIRED = ("storage.endpoint", "storage.bucket", "storage.credentials")   # «значения нет» → хранилище не настроено


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    """Конечное число (не bool): Infinity/NaN из JSON — неверная форма факта, ConfigError при загрузке."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _printable_ascii(v, allow_space=False):
    lo = 0x20 if allow_space else 0x21
    return all(lo <= ord(c) <= 0x7E for c in v)


def _object_key_ok(v):
    return (not any(ord(c) < 0x20 or ord(c) == 0x7F or 0xD800 <= ord(c) <= 0xDFFF for c in v)
            and len(v.encode("utf-8")) <= 512)


def _cred_ok(v):
    return (isinstance(v, dict) and set(v) == set(_CRED_KEYS)
            and all(isinstance(v[k], str) and _ENV_NAME_RE.fullmatch(v[k]) for k in _CRED_KEYS))


# Схема фактов: имя → (проверка ТИПА И ФОРМЫ присутствующего значения, умолчание при отсутствии).
# Отсутствие факта = ключа нет ИЛИ значение null. Любое иное значение (False, 0, "", [], {}) — ПРИСУТСТВУЕТ и
# судится проверкой до применения умолчания: ложное значение чужого типа — ConfigError, а не «нет значения».
# Факты нормы: storage_binding.config_facts; прочие — значения T2 (список для T3 — в отчёте и журнале).
_SCHEMA = {
    "git_threshold_bytes": (lambda v: _is_int(v) and v >= 0, None),                       # норма
    "storage.endpoint": (lambda v: isinstance(v, str) and v != "", None),                  # норма
    "storage.region": (lambda v: isinstance(v, str) and v != "" and _printable_ascii(v), DEFAULT_REGION),  # норма
    "storage.bucket": (lambda v: isinstance(v, str) and v != "", None),                    # норма
    "storage.key_prefix": (lambda v: isinstance(v, str) and _object_key_ok(v), ""),        # норма; "" — значение
    "storage.credentials": (_cred_ok, None),                                               # норма
    "storage.addressing": (lambda v: v in ("path", "virtual") and isinstance(v, str), "path"),
    "storage.timeout_s": (lambda v: _is_num(v) and v > 0, 30),
    "storage.deadline_s": (lambda v: _is_num(v) and v > 0, 600),
    "storage.allow_insecure_http": (lambda v: isinstance(v, bool), False),
    "storage.list_permission": (lambda v: isinstance(v, bool), False),
    "storage.canary_key": (lambda v: isinstance(v, str) and v != "" and _object_key_ok(v), None),
}
if not set(N.CONFIG_FACTS) <= set(_SCHEMA):
    raise P.NormDrift("факты конфига нормы вне схемы адаптера")
_T2_EXTRA = tuple(k for k in _SCHEMA if k not in N.CONFIG_FACTS)


class Binding(object):
    """repr не несёт key_prefix: префикс — секрет конфига (неизвестный снаружи, он закрывает пробу «есть ли файл
    с известным хешем» анонимным HEAD/GET), маскируется как ключи. Генерирует его установщик T3, не адаптер;
    пустой префикс адаптер принимает как значение нормы."""
    __slots__ = ("endpoint", "region", "bucket", "key_prefix", "cred_names", "addressing", "timeout_s",
                 "deadline_s", "allow_insecure_http", "list_permission", "canary_key")

    def __repr__(self):
        return "Binding(endpoint=%r, bucket=%r, region=%r, addressing=%r)" % (
            self.endpoint, self.bucket, self.region, self.addressing)


class Config(object):
    __slots__ = ("git_threshold_bytes", "binding", "binding_missing")

    def __init__(self, git_threshold_bytes=None, binding=None, binding_missing=()):
        self.git_threshold_bytes = N.GIT_THRESHOLD_DEFAULT if git_threshold_bytes is None else git_threshold_bytes
        self.binding = binding
        self.binding_missing = tuple(binding_missing)


def _cred_names(v, fact):
    if not _cred_ok(v):
        raise ConfigError("%s — объект с именами %s (имена переменных окружения)" % (fact, ", ".join(_CRED_KEYS)))
    return (v["access_key_id"], v["secret_access_key"])


@_guard
def load_config(mapping):
    """Объект с фактами storage_binding.config_facts нормы. Формат файла — D20 T3; здесь — словарь
    {"git_threshold_bytes": int, "storage": {"endpoint", "region", "bucket", "key_prefix",
    "credentials": {"access_key_id": ENV, "secret_access_key": ENV}, "addressing": "path"|"virtual",
    "timeout_s", "deadline_s", "allow_insecure_http", "list_permission", "canary_key"}}.
    Тип — ДО умолчания (_SCHEMA). Отсутствие обязательного факта привязки (endpoint, bucket, credentials) —
    «хранилище не настроено» (binding None, binding_missing называет отсутствующие). Присутствующий факт неверного
    типа или формы — ConfigError; сообщения значений не отражают."""
    if mapping is None:
        mapping = {}
    if not isinstance(mapping, dict):
        raise ConfigError("конфиг — объект")
    flat = {}
    storage_present = False
    for k, v in mapping.items():
        if not isinstance(k, str):
            raise ConfigError("ключ конфига — не строка")
        if k == "storage":
            if v is None:
                continue
            if not isinstance(v, dict):
                raise ConfigError("storage — объект")
            storage_present = True
            for k2, v2 in v.items():
                if not isinstance(k2, str):
                    raise ConfigError("ключ конфига — не строка")
                flat["storage." + k2] = v2
        else:
            flat[k] = v
    unknown = [k for k in flat if k not in _SCHEMA]
    if unknown:
        raise ConfigError("факты вне нормы: %d шт." % len(unknown))
    val = {}
    for fact, (ok, default) in _SCHEMA.items():
        if fact in flat and flat[fact] is not None:
            if not ok(flat[fact]):
                raise ConfigError("%s — значение неверного типа или формы" % fact)
            val[fact] = flat[fact]
        else:
            val[fact] = default
    thr = val["git_threshold_bytes"]
    if val["storage.endpoint"] is not None:
        try:
            S3.Endpoint(val["storage.endpoint"], val["storage.bucket"] or "probe-bucket", val["storage.addressing"],
                        val["storage.allow_insecure_http"])
        except S3.EndpointError as e:
            raise ConfigError("storage.endpoint: %s" % e) from None
    if val["storage.bucket"] is not None:
        try:
            S3.Endpoint("https://probe.invalid", val["storage.bucket"], "path")
        except S3.EndpointError as e:
            raise ConfigError("storage.bucket: %s" % e) from None
    if not storage_present:
        return Config(thr, None, ())
    missing = tuple(k for k in _REQUIRED if val[k] is None)
    if missing:
        return Config(thr, None, missing)
    b = Binding()
    b.endpoint, b.region, b.bucket = val["storage.endpoint"], val["storage.region"], val["storage.bucket"]
    b.key_prefix = val["storage.key_prefix"]
    b.cred_names = _cred_names(val["storage.credentials"], "storage.credentials")
    b.addressing, b.timeout_s, b.deadline_s = val["storage.addressing"], val["storage.timeout_s"], val["storage.deadline_s"]
    b.allow_insecure_http, b.list_permission = val["storage.allow_insecure_http"], val["storage.list_permission"]
    b.canary_key = val["storage.canary_key"]
    return Config(thr, b, ())


def _creds(names, env):
    env = os.environ if env is None else env
    a, s = env.get(names[0]), env.get(names[1])
    if not a or not s:
        return None
    return S3.Credentials(a, s)


def _client(binding, creds):
    ep = S3.Endpoint(binding.endpoint, binding.bucket, binding.addressing, binding.allow_insecure_http)
    return S3.S3Client(ep, binding.region, creds, timeout_s=binding.timeout_s, deadline_s=binding.deadline_s,
                       redact=(binding.key_prefix,))


def _storage_ready(config, env):
    """(client | None, причина). Нет привязки, привязка неполна или значений ключей нет в окружении —
    хранилище не настроено (storage_binding.config_facts: absent → «хранилище не настроено»). Причина громкая:
    неполная привязка называет отсутствующие факты."""
    b = config.binding
    if b is None:
        if config.binding_missing:
            return None, "binding-incomplete: нет " + ", ".join(config.binding_missing)
        return None, "no-binding"
    creds = _creds(b.cred_names, env)
    if creds is None:
        return None, "credentials-absent"
    return _client(b, creds), None


def _phys_key(config, key):
    return config.binding.key_prefix + key


# --------------------------------------------------------------------------- маршрут
class Route(object):
    __slots__ = ("target", "reason", "step", "detail")

    def __init__(self, target, reason, step, detail=None):
        self.target, self.reason, self.step, self.detail = target, reason, step, detail

    def __repr__(self):
        return "Route(%r, %r, step=%r, detail=%r)" % (self.target, self.reason, self.step, self.detail)

    def __eq__(self, o):
        return isinstance(o, Route) and (self.target, self.reason, self.step) == (o.target, o.reason, o.step)


_MAGIC = P.MAGIC_PREFIX
_PREFIX_LEN = max(len(P.MAGIC_PREFIX), len(P.LFS_PREFIX))   # шаг 2 судит по обеим сигнатурам: срез — по длиннейшей
# Предикаты шагов — по тексту `when` нормы (routing.steps); текст сменился — словарь не найдёт ключ, дрейф.
_ROUTE_PRED = {
    "not obtained": lambda r: not r["obtained"],
    "байты начинаются pointer.magic_prefix или lfs.signature_prefix":
        lambda r: r["prefix"].startswith(_MAGIC) or r["prefix"].startswith(P.LFS_PREFIX),
    "size <= threshold": lambda r: r["size"] is not None and r["size"] <= r["threshold"],
    "иначе": lambda r: True,
}
if set(_ROUTE_PRED) != set(w for _s, w, _o, _r in N.ROUTING_STEPS):
    raise P.NormDrift("предикаты маршрута и routing.steps нормы разошлись")
if N.THRESHOLD_COMPARISON != "greater_than":
    raise P.NormDrift("soft_limit.comparison сменился: %s" % N.THRESHOLD_COMPARISON)


def _storage_or_unsaved(config, env, step):
    client, why = _storage_ready(config, env)
    return Route("storage", None, step) if client is not None else Route("unsaved", "no-storage", step, why)


@_guard
def route(size, config, obtained=True, data_prefix=b"", env=None):
    """Маршрут §6.3: первый сработавший шаг routing.steps. target: git | storage | unsaved.
    size — фактический (obtained) либо объявленный источником; data_prefix — первые байты (шаг 2)."""
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
        raise AttachInputError("size — целое >= 0")
    if obtained and size is None:
        raise AttachInputError("при obtained размер известен")
    ctx = {"obtained": obtained, "prefix": bytes(data_prefix[: _PREFIX_LEN]), "size": size,
           "threshold": config.git_threshold_bytes}
    for step, when, outcome, reason in N.ROUTING_STEPS:
        if _ROUTE_PRED[when](ctx):
            if outcome == "storage_or_unsaved":
                return _storage_or_unsaved(config, env, step)
            if outcome == "unsaved":
                return Route("unsaved", reason, step)
            if outcome == "git":
                return Route("git", None, step)
            raise P.NormDrift("исход маршрута вне кода: %s" % outcome)
    raise P.NormDrift("ни один шаг маршрута не сработал")


_LFS = P.LFS_PREFIX


def _route_bytes(data, config, env, declared_size=None):
    """route() для писателя, державшего (или не получившего) байты. Байты с сигнатурой указателя этой главы или
    Git LFS в git не кладутся — это шаг 2 routing.steps нормы (поправка d20/norm-amend), не отступление."""
    if data is None:
        return route(declared_size, config, obtained=False, env=env)
    return route(len(data), config, obtained=True, data_prefix=data, env=env)


# --------------------------------------------------------------------------- путь, носитель, блокировка
def attachment_relpath(record_id, uuid, ext, slug=None):
    if not isinstance(ext, str) or re.fullmatch(N.EXT_PATTERN, ext) is None:
        raise AttachInputError("ext вне грамматики имени (нижний регистр, 1..8 [a-z0-9])")
    if slug is not None and (not isinstance(slug, str) or re.fullmatch(N.SLUG_PATTERN, slug) is None
                             or len(slug) > N.SLUG_MAX_LEN):
        raise AttachInputError("slug вне грамматики имени")
    if not isinstance(uuid, str) or not isinstance(record_id, str):
        raise AttachInputError("uuid и id записи — строки")
    name = uuid + ("-" + slug if slug else "") + "." + ext
    if re.fullmatch(N.FILENAME_PATTERN, name) is None:
        raise AttachInputError("имя вложения вне filename.pattern (uuid — канонический нижний регистр)")
    rel = N.RESERVED_DIR + "/" + record_id + "/" + name
    if re.fullmatch(N.PATH_PATTERN, rel) is None:
        raise AttachInputError("путь вне layout.path_pattern (id записи — канонический нижний регистр)")
    return rel


def _carrier_parts(path):
    """Строковый путь носителя → (каталог записи, record-id, имя) по грамматикам нормы. Форма пути (R3): компоненты
    «.», «..» и пустые запрещены ВО ВСЁМ пути (лексическая нормализация разошлась бы с ядром на «..» после symlink);
    последние три компонента — буквально attachments/<record-id>/<имя>. Корень записи — префикс пути без
    нормализации; разрешает его ядро (realpath) в attach.fsio. Файловая система здесь не трогается."""
    if not isinstance(path, (str, os.PathLike)):
        raise AttachInputError("путь — строка")
    path = os.fspath(path)
    if not isinstance(path, str) or "\x00" in path:
        raise AttachInputError("путь вне формы")
    parts = path.split(os.sep)
    body = parts[1:] if parts and parts[0] == "" else parts   # ведущий «/» абсолютного пути
    if not body or any(c in ("", ".", "..") for c in body):
        raise AttachInputError("в пути носителя запрещены компоненты «.», «..» и пустые")
    if len(body) < 3:
        raise AttachInputError("путь не под attachments/<record-id>/")
    rel = "/".join(body[-3:])
    if re.fullmatch(N.PATH_PATTERN, rel) is None or re.fullmatch(N.FILENAME_PATTERN, body[-1]) is None:
        raise AttachInputError("путь вне layout.path_pattern / filename.pattern")
    rest = parts[:-3]
    record_dir = os.sep.join(rest) if rest and rest != [""] else (os.sep if rest == [""] else ".")
    return record_dir, body[-2], body[-1]


class _Carrier(object):
    """Носитель под блокировкой: каталог attachments/<record-id>/ открыт цепочкой дескрипторов (O_NOFOLLOW),
    flock на нём; все чтения и записи — через этот дескриптор. path — строковый путь только для отчёта."""

    def __init__(self, record_dir, record_id, name, path, create):
        self.name, self.path = name, path
        self._cd = FS.CarrierDir(record_dir, N.RESERVED_DIR, record_id, create=create, lock=True)

    def __enter__(self):
        try:
            self._cd.__enter__()
        except FS.FsRefused as e:
            raise AttachInputError("носитель: %s; адаптер не действует" % e) from None
        return self

    def __exit__(self, *exc):
        return self._cd.__exit__(*exc)

    def read(self):
        try:
            return self._cd.read(self.name)
        except FS.FsRefused as e:
            raise AttachInputError("носитель: %s; адаптер не действует" % e) from None

    def exists(self):
        return self._cd.exists(self.name)

    def put(self, new):
        """ЕДИНСТВЕННАЯ запись в носитель. Существующее содержимое меняется только тождеством или законным
        переходом §9.6 — адаптер никогда не порождает E-ATT-CONTENT-MUTATED. Запись — renameat в каталоге-
        дескрипторе; после — перечтение через тот же дескриптор и разбор своего вывода (сбой — AdapterFault)."""
        old = self.read()
        if old is None and self.exists():
            raise AttachInputError("на месте носителя — не обычный файл")
        if old is not None:
            if old == new:
                return False
            ok, why = P.check_transition(old, new)
            if not ok:
                raise AttachInputError("по пути уже лежит иное содержимое; правка — не законный переход (%s)" % why)
        try:
            self._cd.write(self.name, new)
        except FS.FsRefused as e:
            raise AttachInputError("носитель: %s" % e) from None
        back = self.read()
        if back != new:
            raise AdapterFault("записанные байты не равны поданным")
        if new.startswith(P.MAGIC_PREFIX) and P.classify(back).kind != "pointer":
            raise AdapterFault("собственный указатель не разбирается")
        return True


def _carrier_at(path, create=False):
    record_dir, rid, name = _carrier_parts(path)
    return _Carrier(record_dir, rid, name, os.fspath(path), create)


def _check_out(out, source_path):
    try:
        FS.save_outside(out, None, N.RESERVED_DIR, source_path)
    except FS.FsRefused as e:
        raise AttachInputError("назначение: %s" % e) from None


@_guard
def save_bytes_outside_carriers(out, data, source_path=None):
    """Запись байт, выданных чтением, ВНЕ носителей (CLI read --out). Каталог назначения открывается пошагово
    (O_NOFOLLOW) и закрепляется дескриптором; отказ до открытия на запись, если он — attachments/ или
    attachments/<x>/, если имя назначения — symlink, не обычный файл, файл с несколькими жёсткими ссылками или
    сам источник. Замена — renameat в закреплённом каталоге: подмена компонентов пути после проверки запись
    не перенаправляет."""
    try:
        FS.save_outside(out, bytes(data), N.RESERVED_DIR, source_path)
    except FS.FsRefused as e:
        raise AttachInputError("назначение: %s" % e) from None


# --------------------------------------------------------------------------- media-type, source
def _sniff(data):
    """Тип по сигнатуре байт (норма: СЛЕДУЕТ по байтам). Таблица — эргономика писателя, не реестр нормы:
    сверки media-type с расширением норма не задаёт (REQ-076)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in (b"M4A ", b"M4B "):
            return "audio/mp4"
        return "video/mp4"
    return None


_MT_RE = re.compile(dict(N.POINTER_FIELD_PATTERNS)["media-type"])
_SRC_RE = re.compile(dict(N.POINTER_FIELD_PATTERNS)["source"])
_SRC_MAX = dict(N.POINTER_FIELD_MAX_LEN).get("source")
_OCTET = "application/octet-stream"


def _media_type(data, declared):
    if declared is not None and (not isinstance(declared, str) or _MT_RE.fullmatch(declared) is None):
        raise AttachInputError("media_type вне грамматики указателя (RFC 6838, нижний регистр, без параметров)")
    if data is not None:
        return _sniff(data) or declared or _OCTET
    return declared or _OCTET


def _check_source(source):
    if source is None:
        return
    if not isinstance(source, str) or _SRC_RE.fullmatch(source) is None or (_SRC_MAX and len(source) > _SRC_MAX):
        raise AttachInputError("source вне грамматики указателя (https без query/порта/учётных данных либо urn:uuid)")


# --------------------------------------------------------------------------- загрузка (идемпотентная)
def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _cls_to_outcome(cls):
    return {"denied": "storage-denied", "unavailable": "storage-unavailable"}[cls]


def _fetch_equal(client, pkey, sha, size):
    """GET + локальный sha256: (True|False|None, resp). True — объект ровно эти байты; None — ответ не 2xx."""
    h = hashlib.sha256()
    r = client.get(pkey, read_limit=size, expect_len=size, sink=h.update)
    if r.cls != "ok":
        return None, r
    if r.detail in ("length-differs", "over-limit") or r.length != size:
        return False, r
    return h.hexdigest() == sha, r


def _upload(client, pkey, data, sha, size, list_permission):
    """Протокол создания без ListBucket:
    HEAD 200 → размер совпал: GET + sha256 → already-present | иначе PUT → repaired (ТОЛЬКО при однозначном 200);
    HEAD 404 → PUT → uploaded;
    HEAD 403 → при list_permission — storage-denied; без него 403 неоднозначен (AWS отвечает 403 на отсутствующий
      объект ключу без ListBucket) → PUT: ключ контентный, PUT идемпотентен; PUT 403 → storage-denied;
    после PUT — проверка GET + sha256 локально → uploaded. Без LIST и без DELETE. Возвращает (исход, detail)."""
    h = client.head(pkey)
    repair = False
    note = None
    if h.cls == "ok":
        if h.length == size:
            eq, r = _fetch_equal(client, pkey, sha, size)
            if eq is None:
                if r.cls == "not-found":
                    eq = False
                else:
                    return _wo(_cls_to_outcome(r.cls)), r.detail
            if eq:
                return _wo("already-present"), None
        repair = True
    elif h.cls == "denied" and h.status == 403 and not list_permission:
        note = "head-403-ambiguous-put"
    elif h.cls != "not-found":
        return _wo(_cls_to_outcome(h.cls)), h.detail
    p = client.put(pkey, data)
    if p.cls == "not-found":
        return _wo("storage-unavailable"), "put http 404"
    if p.cls != "ok":
        return _wo(_cls_to_outcome(p.cls)), p.detail
    eq, r = _fetch_equal(client, pkey, sha, size)
    if eq is None:
        if r.cls == "not-found":
            return _wo("storage-unavailable"), "verify: object absent after put"
        return _wo(_cls_to_outcome(r.cls)), r.detail
    if not eq:
        return _wo("storage-unavailable"), "verify: stored bytes differ"
    return _wo("repaired" if repair else "uploaded"), note


# --------------------------------------------------------------------------- результаты
class WriteResult(object):
    __slots__ = ("state", "outcome", "staged", "path", "reason", "user_mark", "detail", "route")

    def __init__(self, state, outcome, staged, path, reason=None, detail=None, route=None):
        self.state = state
        self.outcome = None if outcome is None else _wo(outcome)
        self.staged = list(staged)
        self.path = path
        self.reason = reason
        self.user_mark = _USER_MARK.get(reason) if state == "unsaved" else None
        self.detail = detail
        self.route = route

    def as_dict(self):
        return {"state": self.state, "outcome": self.outcome, "staged": self.staged, "path": self.path,
                "reason": self.reason, "user_mark": self.user_mark, "detail": self.detail,
                "route": None if self.route is None else {"target": self.route.target, "reason": self.route.reason,
                                                          "step": self.route.step}}

    def __repr__(self):
        return "WriteResult(%r)" % (self.as_dict(),)


class ReadResult(object):
    __slots__ = ("outcome", "data", "state", "reason", "source", "detail", "fields")

    def __init__(self, outcome, data=None, state=None, reason=None, source=None, detail=None, fields=None):
        self.outcome = _ro(outcome)
        if data is not None and outcome not in ("in-git", "ok"):
            raise AdapterFault("байты выдаются только при in-git | ok")
        self.data = data
        self.state = state
        self.reason = reason
        self.source = source
        self.detail = detail
        self.fields = dict(fields or {})

    def as_dict(self):
        return {"outcome": self.outcome, "state": self.state, "reason": self.reason, "source": self.source,
                "detail": self.detail, "size": None if self.data is None else len(self.data)}

    def __repr__(self):
        return "ReadResult(%r)" % (self.as_dict(),)


# --------------------------------------------------------------------------- переходы (под блокировкой)
def _pointer(state, **fields):
    f = {k.replace("_", "-"): v for k, v in fields.items() if v is not None}
    try:
        return P.render(state, f)
    except ValueError as e:
        raise AttachInputError("указатель не собирается из входа: %s" % e) from None


def _rel_of(path):
    parts = os.path.normpath(os.fspath(path)).split(os.sep)
    return "/".join(parts[-3:])


def _bytes_match(c, data):
    """Поданные байты против записанных sha256/size указателя (что записано — то и сверяется)."""
    if "sha256" in c.fields and c.fields["sha256"] != _sha(data):
        return False
    if "sha256" in c.fields and c.fields.get("size") != str(len(data)):
        return False
    return True


def _complete_locked(car, old, c, data, config, env, durable_queue=True, after_upload=None):
    """pending → stored (меняется только строка state). Проверки — до сети."""
    rel = _rel_of(car.path)
    if not _bytes_match(c, data):
        return WriteResult("pending", "bytes-mismatch", [], rel)
    client, why = _storage_ready(config, env)
    if client is None:
        return WriteResult("pending", "storage-not-configured", [], rel, detail=why)
    outcome, detail = _upload(client, _phys_key(config, c.fields["key"]), data, c.fields["sha256"], len(data),
                              config.binding.list_permission)
    if after_upload is not None:
        after_upload(outcome)
    if outcome in _CONFIRMED:
        new = old.replace(b"\nstate pending\n", b"\nstate stored\n", 1)
        car.put(new)
        return WriteResult("stored", outcome, [car.path], rel, detail=detail)
    if durable_queue:
        return WriteResult("pending", outcome, [], rel, detail=detail)
    # states.write_failure: без устойчивой очереди — unsaved upload-failed (pending → unsaved законен)
    f = {k: v for k, v in c.fields.items() if k != "key"}
    f["reason"] = "upload-failed"
    car.put(P.render("unsaved", f))
    return WriteResult("unsaved", outcome, [car.path], rel, reason="upload-failed", detail=detail)


def _late_locked(car, old, c, data, config, env, after_upload=None):
    """unsaved → stored | git по маршруту на момент досохранения. Проверки sha256/size — до сети."""
    rel = _rel_of(car.path)
    reason = c.fields["reason"]
    sha = _sha(data)
    if "sha256" in c.fields and c.fields["sha256"] != sha:
        return WriteResult("unsaved", "bytes-mismatch", [], rel, reason=reason)
    r = _route_bytes(data, config, env)
    if r.target == "storage" and "size" in c.fields and c.fields["size"] != str(len(data)):
        # unsaved -> stored: sha256 и size, если были, ОБЯЗАНЫ совпасть (у unsaved -> git — только sha256)
        return WriteResult("unsaved", "bytes-mismatch", [], rel, reason=reason, route=r)
    if r.target == "git":
        car.put(data)
        return WriteResult(P.GIT_STATE, None, [car.path], rel, route=r)
    if r.target != "storage":
        return WriteResult("unsaved", "storage-not-configured", [], rel, reason=reason, route=r, detail=r.detail)
    client, why = _storage_ready(config, env)
    if client is None:
        raise AdapterFault("привязка исчезла между маршрутом и загрузкой")
    key = P.derive_key(sha)
    outcome, detail = _upload(client, _phys_key(config, key), data, sha, len(data), config.binding.list_permission)
    if after_upload is not None:
        after_upload(outcome)
    if outcome not in _CONFIRMED:
        return WriteResult("unsaved", outcome, [], rel, reason=reason, detail=detail, route=r)
    mt = _sniff(data) or c.fields.get("media-type") or _OCTET
    new = P.render("stored", {"key": key, "sha256": sha, "size": str(len(data)), "media-type": mt,
                              "source": c.fields["source"]})
    car.put(new)
    return WriteResult("stored", outcome, [car.path], rel, detail=detail, route=r)


def _load_locked(car, want_states):
    old = car.read()
    if old is None:
        raise AttachInputError("по пути нет файла")
    c = P.classify(old)
    st = P.state_of(c)
    if st not in want_states:
        raise AttachInputError("состояние по пути — %s, ожидалось %s" % (st or c.kind, "|".join(want_states)))
    return old, c


# --------------------------------------------------------------------------- запись
@_guard
def write_attachment(record_dir, record_id, data, *, ext, config, uuid=None, slug=None, source=None,
                     media_type=None, declared_size=None, durable_queue=False, defer_upload=False, env=None,
                     _after_upload=None):
    """Записать вложение в рабочее дерево по маршруту §6.3.

    data — байты (bytes) либо None, если источник байт не отдал (маршрут шаг 1 → unsaved source-refused).
    uuid — заминченный ранее id вложения (повтор — с прежним uuid и slug/ext); None — минт UUIDv7.
    source — адрес исходного сообщения (https) или квитанция urn:uuid; ОБЯЗАТЕЛЕН для любого маршрута,
      кроме git (указатель unsaved / pending обязан его нести, URL адаптер не выдумывает).
    durable_queue — у вызывающего есть устойчивая очередь с полными байтами (states.pending_requires_durable_queue);
      тогда отказ хранилища даёт pending, иначе unsaved upload-failed.
    defer_upload — офлайн-писатель: не ходить в сеть, сразу pending (требует durable_queue).
    Повтор по существующему пути — переход от ТЕКУЩЕГО содержимого, судимый ДО сети: тождество → без изменений
    (detail already-recorded); иные байты → bytes-mismatch, ноль сетевых изменений; pending → довод загрузки;
    unsaved → досохранение; withdrawn и не-носитель — AttachInputError.
    Возврат: WriteResult(state, outcome записи | None, staged=[абсолютный путь], path=относительный от record_dir)."""
    if data is not None and not isinstance(data, (bytes, bytearray)):
        raise AttachInputError("data — байты или None")
    if declared_size is not None and (isinstance(declared_size, bool) or not isinstance(declared_size, int)
                                      or declared_size < 0):
        raise AttachInputError("declared_size — целое >= 0")
    if defer_upload and not durable_queue:
        raise AttachInputError("defer_upload без устойчивой очереди: pending писать запрещено")
    if not isinstance(config, Config):
        raise AttachInputError("config — результат load_config")
    if uuid is None:
        import comment as _comment  # раскладка UUIDv7 бота одна (comment.uuid7_random)
        uuid = _comment.uuid7_random()
    rel = attachment_relpath(record_id, uuid, ext, slug)
    _check_source(source)
    data = None if data is None else bytes(data)
    size = len(data) if data is not None else declared_size
    r = _route_bytes(data, config, env, declared_size=size)
    if r.target != "git" and source is None:
        raise AttachInputError("маршрут %s требует source (unsaved и pending несут его обязательно)" % r.target)
    full = os.path.join(os.fspath(record_dir), *rel.split("/"))
    mt = _media_type(data, media_type)
    _rd, rid, name = _carrier_parts(full)
    with _Carrier(os.fspath(record_dir), rid, name, full, create=True) as car:
        if car.exists():
            res = _retry_locked(car, rel, data, r, mt, size, source, config, env, durable_queue, defer_upload,
                                _after_upload)
            res.staged = [full]   # носитель по пути есть: вызывающий стейджит его вместе с текстом
            return res
        return _fresh_locked(car, rel, data, r, mt, size, source, config, env, durable_queue, defer_upload,
                             _after_upload)


def _fresh_locked(car, rel, data, r, mt, size, source, config, env, durable_queue, defer_upload, after_upload):
    if r.target == "git":
        car.put(data)
        return WriteResult(P.GIT_STATE, None, [car.path], rel, route=r)
    if r.target == "unsaved" and data is None:
        ptr = _pointer("unsaved", size=None if size is None else str(size), media_type=mt, reason=r.reason,
                       source=source)
        car.put(ptr)
        return WriteResult("unsaved", None, [car.path], rel, reason=r.reason, route=r)
    sha = _sha(data)
    key = P.derive_key(sha)
    if r.target == "unsaved":   # no-storage: писатель держал байты — sha256 и size пишутся
        ptr = _pointer("unsaved", sha256=sha, size=str(size), media_type=mt, reason=r.reason, source=source)
        car.put(ptr)
        return WriteResult("unsaved", None, [car.path], rel, reason=r.reason, route=r, detail=r.detail)
    if defer_upload:
        ptr = _pointer("pending", key=key, sha256=sha, size=str(size), media_type=mt, source=source)
        car.put(ptr)
        return WriteResult("pending", None, [car.path], rel, detail="deferred", route=r)
    client, _why = _storage_ready(config, env)
    if client is None:   # route уже проверил готовность; гонка окружения — порча
        raise AdapterFault("привязка исчезла между маршрутом и загрузкой")
    outcome, detail = _upload(client, _phys_key(config, key), data, sha, size, config.binding.list_permission)
    if after_upload is not None:
        after_upload(outcome)   # точка инъекции сбоя «загружено, указатель не записан» для тестов
    if outcome in _CONFIRMED:
        ptr = _pointer("stored", key=key, sha256=sha, size=str(size), media_type=mt, source=source)
        car.put(ptr)
        return WriteResult("stored", outcome, [car.path], rel, detail=detail, route=r)
    # states.write_failure: с устойчивой очередью — pending; без неё — unsaved upload-failed
    if durable_queue:
        ptr = _pointer("pending", key=key, sha256=sha, size=str(size), media_type=mt, source=source)
        car.put(ptr)
        return WriteResult("pending", outcome, [car.path], rel, detail=detail, route=r)
    ptr = _pointer("unsaved", sha256=sha, size=str(size), media_type=mt, reason="upload-failed", source=source)
    car.put(ptr)
    return WriteResult("unsaved", outcome, [car.path], rel, reason="upload-failed", detail=detail, route=r)


def _retry_locked(car, rel, data, r, mt, size, source, config, env, durable_queue, defer_upload, after_upload):
    """Повтор по существующему пути. Всё, что можно решить без сети, решается до неё."""
    full = car.path
    old = car.read()
    if old is None:
        raise AttachInputError("на месте носителя — не обычный файл")
    c = P.classify(old)
    st = P.state_of(c)
    if st is None:
        raise AttachInputError("по пути %s — адаптер не действует" % c.kind)
    if st == "withdrawn":
        raise AttachInputError("по пути withdrawn — состояние терминально; новое вложение — новый uuid")
    if data is None:
        want = _pointer("unsaved", size=None if size is None else str(size), media_type=mt, reason=r.reason,
                        source=source) if r.target == "unsaved" else None
        if want == old:
            return WriteResult("unsaved", None, [full], rel, reason=r.reason, route=r, detail="already-recorded")
        raise AttachInputError("повтор без байт не меняет существующее вложение (состояние %s)" % st)
    if st == P.GIT_STATE:
        if old == data:
            return WriteResult(P.GIT_STATE, None, [full], rel, route=r, detail="already-recorded")
        return WriteResult(P.GIT_STATE, "bytes-mismatch", [], rel, route=r)
    if st in ("stored", "pending") and not _bytes_match(c, data):
        return WriteResult(st, "bytes-mismatch", [], rel, route=r)
    if st == "stored":
        return WriteResult("stored", None, [full], rel, route=r, detail="already-recorded")
    if st == "pending":
        if defer_upload:
            return WriteResult("pending", None, [full], rel, route=r, detail="already-recorded")
        return _complete_locked(car, old, c, data, config, env, durable_queue=durable_queue, after_upload=after_upload)
    if r.target == "unsaved":   # unsaved и маршрут снова не даёт хранилища: тождество — без изменений
        want = _pointer("unsaved", sha256=_sha(data), size=str(len(data)), media_type=mt, reason=r.reason,
                        source=source)
        if want == old:
            return WriteResult("unsaved", None, [full], rel, reason=r.reason, route=r, detail="already-recorded")
    return _late_locked(car, old, c, data, config, env, after_upload=after_upload)   # unsaved


@_guard
def complete_pending(path, data, config, env=None):
    """Довести pending: загрузить байты из устойчивой очереди и сменить ТОЛЬКО строку state (pending → stored).
    Байты не дают sha256/size указателя — bytes-mismatch, ничего не записано и не загружено. Отказ хранилища —
    указатель не меняется (очередь вызывающего жива)."""
    if not isinstance(data, (bytes, bytearray)):
        raise AttachInputError("data — байты из устойчивой очереди")
    with _carrier_at(path) as car:
        old, c = _load_locked(car, ("pending",))
        return _complete_locked(car, old, c, bytes(data), config, env, durable_queue=True)


@_guard
def confirm_pending(path, config, env=None):
    """pending → stored БЕЗ байтов (D20 T4, R1 F2): объект уже есть в хранилище и проверен — GET и sha256 локально,
    размер равен size (adapter_outcomes.verification_requires_local_hash). Тогда меняется ТОЛЬКО строка state
    (законный переход pending → stored), исход записи already-present: «объект с теми же size и sha256 уже есть;
    записи не было». Объекта нет, байты иные, хранилище отказало — указатель не меняется (state pending; outcome —
    storage-denied | storage-unavailable либо None с detail object-absent | object-differs). Для довода pending, когда
    байтов в очереди нет, а тот же объект загрузил другой вызов (общий key)."""
    with _carrier_at(path) as car:
        old, c = _load_locked(car, ("pending",))
        rel = _rel_of(car.path)
        client, why = _storage_ready(config, env)
        if client is None:
            return WriteResult("pending", "storage-not-configured", [], rel, detail=why)
        eq, r = _fetch_equal(client, _phys_key(config, c.fields["key"]), c.fields["sha256"], int(c.fields["size"]))
        if eq is None:
            if r.cls == "not-found":
                return WriteResult("pending", None, [], rel, detail="object-absent")
            return WriteResult("pending", _cls_to_outcome(r.cls), [], rel, detail=r.detail)
        if not eq:
            return WriteResult("pending", None, [], rel, detail="object-differs")
        car.put(old.replace(b"\nstate pending\n", b"\nstate stored\n", 1))
        return WriteResult("stored", "already-present", [car.path], rel, detail="confirmed-without-bytes")


@_guard
def fail_pending(path):
    """pending → unsaved (reason upload-failed): key снят, прочие поля побайтово те же. Писатель СЛЕДУЕТ
    ответить отправителю (unsaved.reply_on_later_transition) — это дело вызывающего."""
    with _carrier_at(path) as car:
        old, c = _load_locked(car, ("pending",))
        f = {k: v for k, v in c.fields.items() if k != "key"}
        f["reason"] = "upload-failed"
        car.put(P.render("unsaved", f))
        return WriteResult("unsaved", None, [car.path], _rel_of(car.path), reason="upload-failed")


@_guard
def late_save(path, data, config, env=None):
    """Досохранение unsaved → stored | git (§9.6) по маршруту на момент досохранения. Записанные sha256/size
    обязаны совпасть — иначе bytes-mismatch (до сети). Хранилища нет и маршрут не git — storage-not-configured,
    указатель не меняется."""
    if not isinstance(data, (bytes, bytearray)):
        raise AttachInputError("data — байты")
    with _carrier_at(path) as car:
        old, c = _load_locked(car, ("unsaved",))
        return _late_locked(car, old, c, bytes(data), config, env)


@_guard
def withdraw(path, reason, config, withdraw_credentials, env=None):
    """Изъятие (§9.6 → withdrawn): reason secret | erasure. Объект (stored/pending) удаляется ОТДЕЛЬНОЙ
    привязкой ключа изъятия withdraw_credentials = {"access_key_id": ENV, "secret_access_key": ENV} —
    ключ писателя (put/get/head) для DELETE не используется никогда. Указатели других вложений с тем же
    key вызывающий переводит тем же коммитом (immutability.secret_in_storage_object). Состояние и причина
    судятся под блокировкой ДО DELETE."""
    if reason not in P.STATE_REASONS["withdrawn"]:
        raise AttachInputError("reason изъятия — %s" % " | ".join(P.STATE_REASONS["withdrawn"]))
    _carrier_parts(path)
    try:
        names = _cred_names(withdraw_credentials, "withdraw_credentials")
    except ConfigError as e:
        raise AttachInputError(str(e)) from None
    with _carrier_at(path) as car:
        path = car.path
        old = car.read()
        if old is None:
            raise AttachInputError("по пути нет файла")
        c = P.classify(old)
        st = P.state_of(c)
        rel = _rel_of(path)
        if st is None:
            raise AttachInputError("по пути %s — адаптер не действует" % c.kind)
        if st == "withdrawn":
            if c.fields.get("reason") == reason:
                return WriteResult("withdrawn", None, [], rel, reason=reason, detail="already-withdrawn")
            raise AttachInputError("withdrawn терминален")
        detail = None
        if st in ("stored", "pending"):
            if config.binding is None:
                _c, why = _storage_ready(config, env)
                return WriteResult(st, "storage-not-configured", [], rel, detail=why)
            creds = _creds(names, env)
            if creds is None:
                return WriteResult(st, "storage-not-configured", [], rel, detail="withdraw-credentials-absent")
            client = _client(config.binding, creds)
            d = client.delete(_phys_key(config, c.fields["key"]))
            if d.cls not in ("ok", "not-found"):
                return WriteResult(st, _cls_to_outcome(d.cls), [], rel, detail=d.detail)
            detail = "object-deleted"
        car.put(P.render("withdrawn", {"reason": reason}))
        return WriteResult("withdrawn", None, [path], rel, reason=reason, detail=detail)


# --------------------------------------------------------------------------- канарейка и статус
def _canary(client, config):
    """HEAD объекта-канарейки (storage.canary_key, создаёт установщик T3): 'valid' | 'denied' | 'missing' |
    'unavailable' | None (канарейка не настроена)."""
    ck = config.binding.canary_key
    if not ck:
        return None
    # GET, а не HEAD: у HEAD нет тела, и 404 NoSuchBucket неотличим от отсутствия канарейки (R3)
    h = client.get(config.binding.key_prefix + ck, read_limit=4096)
    if h.cls == "ok":
        return "valid"
    if h.cls == "not-found":
        return "missing"
    if h.detail == S3.NO_SUCH_BUCKET:
        return "no-such-bucket"
    return h.cls


@_guard
def probe_storage(config, env=None):
    """Статус хранилища для /status и установщика (норма §9.8 status_facts: storage_probe_outcome
    ok | storage-denied | storage-unavailable) — HEAD канарейки. Без канарейки исход не выводим (None)."""
    client, why = _storage_ready(config, env)
    if client is None:
        return {"storage_configured": False, "storage_probe_outcome": None, "detail": why}
    v = _canary(client, config)
    if v is None:
        return {"storage_configured": True, "storage_probe_outcome": None, "detail": "no-canary"}
    out = {"valid": "ok", "denied": "storage-denied", "missing": "storage-denied",
           "unavailable": "storage-unavailable", "no-such-bucket": "storage-unavailable"}[v]
    return {"storage_configured": True, "storage_probe_outcome": out,
            "detail": S3.NO_SUCH_BUCKET if v == "no-such-bucket" else "canary-" + v}


# Тело объекта-канарейки (D20 T3). ФИКСИРОВАННОЕ: имя — storage.canary_key конфига, тело — эта константа; повтор PUT
# кладёт те же байты (идемпотентен), проба (_canary) судит только 2xx GET. Не по содержимому: проба читает канарейку
# по имени из конфига, контентный ключ ничего не добавил бы — имя всё равно пришлось бы хранить в конфиге.
CANARY_BODY = b"workshop-storage-canary 1\n"


@_guard
def ensure_canary(config, env=None):
    """Объект-канарейка под префиксом — ключом ПИСАТЕЛЯ (put/get/head; list и delete не нужны) — D20 T3.
    GET канарейки: 2xx с телом CANARY_BODY — 'already-present' (без PUT); иначе (нет, 403 без ListBucket у AWS, чужие
    байты, сбой) — PUT CANARY_BODY ('uploaded' при 2xx). Исход — из adapter_outcomes.write нормы (_wo): uploaded |
    already-present | storage-denied | storage-unavailable | storage-not-configured. После подтверждённого исхода —
    проба (probe_storage). -> dict {canary_outcome, detail, storage_configured, storage_probe_outcome, probe_detail}."""
    client, why = _storage_ready(config, env)
    if client is None:
        return {"storage_configured": False, "canary_outcome": _wo("storage-not-configured"), "detail": why,
                "storage_probe_outcome": None, "probe_detail": why}
    ck = config.binding.canary_key
    if not ck:
        raise AttachInputError("storage.canary_key не задан — канарейке некуда лечь")
    pkey = config.binding.key_prefix + ck
    g = client.get(pkey, read_limit=len(CANARY_BODY))
    if g.cls == "ok" and g.body == CANARY_BODY:
        outcome, detail = _wo("already-present"), None
    else:
        p = client.put(pkey, CANARY_BODY)
        if p.cls == "ok":
            v = client.get(pkey, read_limit=len(CANARY_BODY))   # как _upload: подтверждение после PUT — GET и сверка байт
            if v.cls == "ok" and v.body == CANARY_BODY:
                outcome, detail = _wo("uploaded"), None
            elif v.cls == "ok" or v.cls == "not-found":
                outcome, detail = _wo("storage-unavailable"), "verify: canary bytes differ or absent after put"
            else:
                outcome, detail = _wo(_cls_to_outcome(v.cls)), v.detail
        elif p.cls == "not-found":
            outcome, detail = _wo("storage-unavailable"), "put http 404"
        else:
            outcome, detail = _wo(_cls_to_outcome(p.cls)), p.detail
        if outcome != "uploaded":
            return {"storage_configured": True, "canary_outcome": outcome, "detail": detail,
                    "storage_probe_outcome": None, "probe_detail": None}
    pr = probe_storage(config, env)
    return {"storage_configured": True, "canary_outcome": outcome, "detail": detail,
            "storage_probe_outcome": pr["storage_probe_outcome"], "probe_detail": pr["detail"]}


# --------------------------------------------------------------------------- чтение
class _Stop(Exception):
    def __init__(self, result):
        self.result = result


def _read_steps(path, config, env, keep):
    """Порядок adapter_outcomes.read_order — шаги исполняются РОВНО в порядке реестра нормы."""
    record_dir, rid, fname = _carrier_parts(path)
    st = {"path": os.fspath(path)}

    def parse(s):
        # Инвариант R2: классификация и выдача байт — из ОДНОГО открытого файла (цепочка дескрипторов, O_NOFOLLOW).
        try:
            f = FS.open_for_read(record_dir, N.RESERVED_DIR, rid, fname)
        except FS.FsRefused as e:
            raise AttachInputError("носитель: %s; адаптер не действует" % e) from None
        if f is None:
            raise AttachInputError("по пути нет файла")
        with f:
            head = f.read(P.MAX_BYTES + 1)   # для суда достаточно первых max_bytes+1 байт
            c = P.classify(head)
            s["c"] = c
            FS._hook("read-classified", kind=c.kind, path=s["path"])
            if c.kind == "bytes":
                data = None
                if keep:
                    data = head + f.read()   # дочитывается ТОТ ЖЕ файл: замена по пути после открытия не видна
                raise _Stop(ReadResult("in-git", data=data, state=P.GIT_STATE))
        if c.kind == "lfs":
            raise _Stop(ReadResult("lfs-unsupported"))
        if c.kind == "pointer-version-unknown":
            raise _Stop(ReadResult("pointer-version-unknown", detail="version " + str(c.version)))
        if c.kind == "pointer-invalid":
            raise _Stop(ReadResult("pointer-invalid", detail=c.defect))

    def state(s):
        c = s["c"]
        if c.state == "unsaved":
            raise _Stop(ReadResult("not-stored", state="unsaved", reason=c.fields["reason"],
                                   source=c.fields["source"], fields=c.fields))
        if c.state == "withdrawn":
            raise _Stop(ReadResult("withdrawn", state="withdrawn", reason=c.fields["reason"], fields=c.fields))

    def binding(s):
        client, why = _storage_ready(config, env)
        if client is None:
            raise _Stop(ReadResult("storage-not-configured", state=s["c"].state, detail=why, fields=s["c"].fields))
        s["client"] = client

    def absent(s):
        out = "pending-upload" if s["c"].state == "pending" else "object-missing"
        raise _Stop(ReadResult(out, state=s["c"].state, fields=s["c"].fields))

    def access(s):
        c = s["c"]
        size = int(c.fields["size"])
        h = hashlib.sha256()
        buf = [] if keep else None

        def sink(chunk):
            h.update(chunk)
            if buf is not None:
                buf.append(chunk)
        r = s["client"].get(_phys_key(config, c.fields["key"]), read_limit=size, expect_len=size, sink=sink)
        s["resp"], s["hash"], s["buf"], s["size"] = r, h, buf, size
        if r.cls == "unavailable":
            raise _Stop(ReadResult("storage-unavailable", state=c.state, detail=r.detail, fields=c.fields))
        if r.cls == "denied":
            # Инвариант R2: доступность одного объекта никогда не доказывает отсутствие другого. 403 на целевом —
            # storage-denied ВСЕГДА; без ListBucket (AWS отвечает 403 и на отсутствующий объект) — честное
            # «неизвестно» деталью. Канарейка в классификацию чтения не входит — только проба ключа (probe_storage).
            detail = r.detail if config.binding.list_permission else "ambiguous-403-no-list"
            raise _Stop(ReadResult("storage-denied", state=c.state, detail=detail, fields=c.fields))

    def presence(s):
        if s["resp"].cls == "not-found":   # 404 — объекта нет, во всех режимах провайдера
            absent(s)

    def size_step(s):
        r = s["resp"]
        if r.detail in ("length-differs", "over-limit") or r.length != s["size"]:
            raise _Stop(ReadResult("size-mismatch", state=s["c"].state, detail="object %s bytes" % r.length,
                                   fields=s["c"].fields))

    def sha_step(s):
        if s["hash"].hexdigest() != s["c"].fields["sha256"]:
            raise _Stop(ReadResult("sha-mismatch", state=s["c"].state, fields=s["c"].fields))
        data = b"".join(s["buf"]) if keep else None
        if keep and _sha(data) != s["c"].fields["sha256"]:
            raise AdapterFault("буфер разошёлся с потоковым хешем")
        raise _Stop(ReadResult("ok", data=data, state=s["c"].state, fields=s["c"].fields))

    handlers = {"разобрать файл по пути": parse, "состояние": state, "привязка": binding,
                "доступность": access, "наличие": presence, "размер": size_step, "sha256": sha_step}
    if list(handlers) != list(N.READ_ORDER):
        raise P.NormDrift("шаги чтения кода и adapter_outcomes.read_order нормы разошлись")
    try:
        for name in N.READ_ORDER:
            handlers[name](st)
    except _Stop as stop:
        return stop.result
    raise AdapterFault("порядок чтения исчерпан без исхода")


@_guard
def read_attachment(path, config, env=None):
    """Исход чтения (adapter_outcomes.read) и байты — ТОЛЬКО при in-git или ok (после локального sha256)."""
    return _read_steps(path, config, env, keep=True)


@_guard
def verify(path, config, env=None):
    """Тот же суд, что read_attachment, без удержания байт (потоковый sha256; git-файл не читается целиком)."""
    return _read_steps(path, config, env, keep=False)


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    """CLI адаптера — attach.cli (D20 T4): человекочитаемый вывод по умолчанию, --json по схеме attach.contract."""
    from .cli import main as _main
    return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
