# -*- coding: utf-8 -*-
"""attach.botapi — программный интерфейс адаптера вложений для бота (D20 T4; вызывающий — D18).

Владелец — D20 T4. Функции, которые D18 зовёт на событиях мессенджера:
    attachment_uuid(ident, message_date, k=0)        -> str  UUIDv7 вложения из идентичности сообщения (повтор — тот же)
    Incoming(data, *, ext, source, caption, ...)     — один файл события (байты или None, если источник их не отдал)
    save(record_dir, record_id, items, *, config, env=None, queue=None, dedupe_same_bytes=True) -> Saved
                                                     — одно вложение (items из одного), альбом (N), повтор после обрыва
                                                       (те же items: uuid тот же — путь тот же, переход судит адаптер)
    link(rel_path, caption, form)                    -> str  строка ссылки для текста записи (норма §4, link_forms)
    status(repo, config, env=None, verify=False, max_pointers=None) -> dict  факты /status (данные, не текст)
    complete_from_queue(path, queue, config, env=None) -> ItemResult  довод pending из устойчивой очереди
    FileQueue(directory)                             — устойчивая очередь писателя вне git (states.pending_requires_durable_queue)

ЧЕГО ЗДЕСЬ НЕТ (решение брифа §2): изъятия. withdraw остаётся под отдельной привязкой ключа человека (attach.core /
attach.repo, CLI с явным флагом); этот модуль его не импортирует и не реэкспортирует — проверено тестом и мутацией.

Контракт результата (Saved):
  * results — РОВНО один ItemResult на каждый элемент items, в том же порядке (index == позиция): без потерь, дублей и
    перестановок (инвариант сохранения брифа §3, проверка — при сборке результата; нарушение — AdapterFault);
  * одинаковые байты в одном вызове (одна запись) при dedupe_same_bytes — ОДНО вложение (норма routing.same_bytes:
    «байт-идентичные файлы СЛЕДУЕТ прикладывать одним вложением и ссылаться на него столько раз, сколько файл
    встретился»): у повторов same_as = индекс первого, путь первого, своя подпись и своя строка ссылки; без dedupe —
    N путей и N ссылок, объект хранилища один (key по содержимому);
  * staged — объединение путей для стейджинга В ОДНОМ коммите с текстом (один коммит — дело вызывающего; API не
    коммитит); пути абсолютные, порядок — порядок items, без повторов;
  * каждый несохранённый файл (state unsaved, либо собственная ошибка/ошибка входа на элементе) несёт reply —
    ДАННЫЕ для ответа отправителю (исход, причина, пометка нормы unsaved.reasons[].user_mark); текст ответа — D18;
  * queue_release — [{sha256, holder}] держателей очереди этого вызова, чьё вложение записано НЕ в pending; ПОСЛЕ своего
    коммита вызывающий зовёт queue.release(sha256, holder) — очередь удалит байты, только если их не требует ни один
    другой держатель (pending прежних вызовов с теми же байтами, незавершённый вызов) — FileQueue, R1 F2.
Путь вложения (path) — от каталога записи, ровно как в ссылке: `attachments/<record-id>/<имя>` без ведущего `./`
(адаптер отвергает компоненты «.» — в API путь строит сам). Имена `.<имя>.tmp-<12 hex>` в attachments/<record-id>/
зарезервированы адаптером (временные файлы атомарной записи, подметаются под блокировкой).
"""
import hashlib
import os
import re
import stat
import uuid as _uuid

from . import core as C
from . import norm as N
from . import pointer as P
from . import repo as R

__all__ = ["ATTACHMENT_DOMAIN", "LINK_FORMS", "Incoming", "ItemResult", "Saved", "attachment_uuid", "save", "link",
           "status", "complete_from_queue", "FileQueue", "QueueRefused"]

ATTACHMENT_DOMAIN = "workshop-d20-attachment-v1"   # домен соли, отличный от комментов (workshop-d09-comment-v1)
_IDENT_RE = re.compile(r"tg:-?[0-9]+:[0-9]+")

# Формы ссылки, разрешаемые от каталога записи (link_forms.forms[base == record_directory]): эмбед и ссылка. Упоминание
# в бэктиках (база — корень репозитория, форма 02.1.4) ссылкой на вложение не является — API его не строит.
_PH_CAPTION = "<подпись>"
_PH_PATH = N.RESERVED_DIR + "/<id>/<имя>"
LINK_FORMS = tuple(f for f, _syn, base in N.LINK_FORMS if base == "record_directory")
_LINK_SYNTAX = dict((f, syn) for f, syn, base in N.LINK_FORMS if base == "record_directory")
for _f, _syn in _LINK_SYNTAX.items():
    if _syn.count(_PH_CAPTION) != 1 or _syn.count(_PH_PATH) != 1:
        raise P.NormDrift("link_forms.syntax %s вне формы «<подпись> … attachments/<id>/<имя>»" % _f)
if not LINK_FORMS:
    raise P.NormDrift("в link_forms нет форм с базой record_directory")
_ESCAPE = tuple(N.CAPTION_ESCAPE_CHARS)


# --------------------------------------------------------------------------- идентичность
def attachment_uuid(ident, message_date, k=0):
    """UUIDv7 вложения детерминированно из идентичности сообщения-носителя (`tg:<chat>:<message>`) и номера файла k в
    нём: повтор после обрыва (offset не сдвинут, то же сообщение) даёт ТОТ ЖЕ uuid — тот же путь (норма
    filename.components.uuid.retry_reuses_value). 48 бит времени — message.date·1000; версия 7; вариант 10."""
    if not isinstance(ident, str) or _IDENT_RE.fullmatch(ident) is None:
        raise C.AttachInputError("ident — tg:<chat>:<message>")
    if isinstance(message_date, bool) or not isinstance(message_date, int):
        raise C.AttachInputError("message_date — целое (секунды эпохи)")
    if isinstance(k, bool) or not isinstance(k, int) or k < 0:
        raise C.AttachInputError("k — целое >= 0")
    ts_ms = message_date * 1000
    if ts_ms < 0 or ts_ms >= (1 << 48):
        raise C.AttachInputError("message_date вне диапазона UUIDv7")
    h = hashlib.sha256(b"\x00".join([ATTACHMENT_DOMAIN.encode("ascii"), ident.encode("ascii"),
                                     str(k).encode("ascii")])).digest()
    rand_a = int.from_bytes(h[0:2], "big") & 0x0FFF
    rand_b = int.from_bytes(h[2:10], "big") & ((1 << 62) - 1)
    return str(_uuid.UUID(int=(ts_ms << 80) | (7 << 76) | (rand_a << 64) | (2 << 62) | rand_b))


# --------------------------------------------------------------------------- ссылка
def _check_caption(caption):
    if not isinstance(caption, str) or caption == "":
        # §3.4: исходное имя — подпись; без имени — описательная подпись («фото 3 из 10»); пустая у бота не бывает
        raise C.AttachInputError("caption — непустая строка (исходное имя или описание; текст выбирает вызывающий)")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in caption):
        raise C.AttachInputError("caption без управляющих символов (перевод строки в подписи невозможен по построению)")


def _escape(caption):
    return "".join("\\" + ch if ch in _ESCAPE else ch for ch in caption)


def link(rel_path, caption, form):
    """Строка ссылки нормы §4.1: синтаксис формы из link_forms (эмбед `![…](…)` или ссылка `[…](…)`), путь — от
    каталога записи, подпись экранирована по filename.original_name.escaping_required_chars. Состояние сохранения в
    строку не входит (link_forms.save_state_in_text: forbidden) — строка одна при байтах и при любом указателе."""
    if form not in _LINK_SYNTAX:
        raise C.AttachInputError("form — одна из %s" % " | ".join(LINK_FORMS))
    _check_caption(caption)
    if not isinstance(rel_path, str) or re.fullmatch(N.PATH_PATTERN, rel_path) is None:
        raise C.AttachInputError("путь ссылки — attachments/<record-id>/<имя> от каталога записи")
    return _LINK_SYNTAX[form].replace(_PH_PATH, rel_path).replace(_PH_CAPTION, _escape(caption))


# --------------------------------------------------------------------------- вход
class Incoming(object):
    """Один файл события мессенджера.
    data          — байты; None — источник их не отдал (облачный Bot API выше предела скачивания и т. п.)
    ext           — расширение (нижний регистр, грамматика нормы); без исходного имени — по типу (норма), неизвестный — bin
    source        — адрес исходного сообщения (https) ОБЯЗАТЕЛЕН: unsaved и pending несут его, адаптер URL не выдумывает
    caption       — подпись ссылки (исходное имя; без имени или у внешнего человека — описание): текст выбирает D18
    uuid          — uuid вложения; ЛИБО ident (+ message_date, k) — тогда attachment_uuid (повтор — тот же uuid)
    declared_size — размер, объявленный источником (для data None)
    media_type    — объявленный тип (байты судятся первыми)
    form          — markdown_embed | markdown_link (выбор авторский, норма §4.1)"""
    __slots__ = ("data", "ext", "source", "caption", "uuid", "declared_size", "media_type", "form")

    def __init__(self, data, *, ext, source, caption, uuid=None, ident=None, message_date=None, k=0,
                 declared_size=None, media_type=None, form="markdown_link"):
        if data is not None and not isinstance(data, (bytes, bytearray)):
            raise C.AttachInputError("data — байты или None")
        if (uuid is None) == (ident is None):
            raise C.AttachInputError("ровно одно из uuid и ident (без них повтор после обрыва дал бы второе вложение)")
        if uuid is None:
            uuid = attachment_uuid(ident, message_date, k)
        if source is None:
            raise C.AttachInputError("source обязателен (адрес исходного сообщения)")
        C._check_source(source)
        _check_caption(caption)
        if form not in _LINK_SYNTAX:
            raise C.AttachInputError("form — одна из %s" % " | ".join(LINK_FORMS))
        C.attachment_relpath("0" * 8 + "-0000-7000-8000-" + "0" * 12, uuid, ext)   # грамматика uuid/ext до записи
        if declared_size is not None and (isinstance(declared_size, bool) or not isinstance(declared_size, int)
                                          or declared_size < 0):
            raise C.AttachInputError("declared_size — целое >= 0")
        C._media_type(None, media_type)          # грамматика объявленного типа — до записи
        self.data = None if data is None else bytes(data)
        self.ext, self.source, self.caption, self.uuid = ext, source, caption, uuid
        self.declared_size, self.media_type, self.form = declared_size, media_type, form


# --------------------------------------------------------------------------- результат
class ItemResult(object):
    """Исход одного элемента. state — состояние нормы после вызова (git | stored | pending | unsaved | withdrawn) или
    None при ошибке элемента; write_outcome — исход записи нормы (adapter_outcomes.write) или None (git, unsaved без
    обращения к хранилищу); error — None | "input" | "adapter-fault" (собственная ошибка — отдельно от исходов нормы)."""
    __slots__ = ("index", "uuid", "path", "staged", "state", "write_outcome", "reason", "detail", "link", "form",
                 "same_as", "error", "sha256", "reply")

    def as_dict(self):
        return dict((k, getattr(self, k)) for k in self.__slots__)

    def __repr__(self):
        return "ItemResult(%r)" % (self.as_dict(),)


class Saved(object):
    __slots__ = ("results", "staged", "queue_release", "replies")

    def as_dict(self):
        return {"results": [r.as_dict() for r in self.results], "staged": list(self.staged),
                "queue_release": list(self.queue_release), "replies": list(self.replies)}


_MARK = dict(N.UNSAVED_REASONS)


def _reply(state, reason, write_outcome, error):
    """Данные ответа отправителю — на КАЖДЫЙ несохранённый файл (норма unsaved.reply). Текст — D18."""
    if error is not None:
        return {"state": None, "reason": None, "write_outcome": None, "error": error, "user_mark": None}
    if state != "unsaved":
        return None
    return {"state": state, "reason": reason, "write_outcome": write_outcome, "error": None,
            "user_mark": _MARK.get(reason)}


def _item(index, it, rel_record, full, w=None, error=None, detail=None, same_as=None, sha=None):
    r = ItemResult()
    r.index, r.uuid, r.form, r.same_as, r.error, r.sha256 = index, it.uuid, it.form, same_as, error, sha
    r.path = rel_record
    r.link = link(rel_record, it.caption, it.form)
    if w is not None:
        r.staged = [full] if w.staged else []
        r.state, r.write_outcome, r.reason, r.detail = w.state, w.outcome, w.reason, w.detail
    else:
        r.staged, r.state, r.write_outcome, r.reason, r.detail = [], None, None, None, detail
    r.reply = _reply(r.state, r.reason, r.write_outcome, error)
    return r


# --------------------------------------------------------------------------- очередь
class QueueRefused(C.AttachInputError):
    """Очередь не устойчива по норме (эфемерная CI-джоба, каталог в рабочем дереве git)."""


class FileQueue(object):
    """Устойчивая очередь писателя ВНЕ git (норма states.pending_requires_durable_queue): байты — файл <sha256> в
    каталоге, запись — временный файл + fsync + rename + fsync каталога. Отказ при создании: эфемерная CI-джоба
    (GITHUB_ACTIONS=true — «эфемерная CI-джоба очередью не является») и каталог внутри рабочего дерева git (байты
    попали бы в коммит или пропали бы с клоном). Честность «переживает перезапуск» дальше — на вызывающем (демон с
    томом).

    ДЕРЖАТЕЛИ (R1 F2). Инвариант: байты живут, пока на них ссылается хоть один pending корпуса или незавершённый вызов.
    Байты одного sha256 нужны нескольким вложениям (key по содержимому), поэтому снятие — не «удалить файл», а «снять
    своего держателя»: put(sha, data, holder) регистрирует абсолютный путь носителя ДО записи pending (незавершённый
    вызов — держатель, чей файл ещё не pending); release(sha, holder) снимает этого держателя и затем удаляет байты,
    только если не осталось ни одного держателя, который их ещё может требовать. Держатель нужен, если файла по его пути
    НЕТ (вызов не завершён или упал до записи — сохранить безопаснее: утечка, не потеря) или там pending с этим sha256;
    иначе (stored, unsaved, git, withdrawn, чужие байты) — снимается при любом release этого sha. Довод: держатели
    судятся по корпусу (сам указатель — истина), а не по счётчику, который разошёлся бы с корпусом после сбоя; счётчик
    без проверки корпуса снял бы байты при ошибке учёта, проверка корпуса без держателей не видит незавершённый вызов.
    Все операции — под flock каталога очереди."""
    durable = True

    def __init__(self, directory, env=None):
        env = os.environ if env is None else env
        if env.get("GITHUB_ACTIONS") == "true":
            raise QueueRefused("эфемерная CI-джоба очередью не является (норма) — без очереди: unsaved upload-failed")
        d = os.path.realpath(os.fspath(directory))
        probe = d
        while True:
            if os.path.lexists(os.path.join(probe, ".git")):
                raise QueueRefused("каталог очереди внутри рабочего дерева git — очередь обязана быть вне git")
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        os.makedirs(d, mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(os.lstat(d).st_mode):
            raise QueueRefused("каталог очереди — не каталог")
        self.dir = d

    def _p(self, sha):
        if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
            raise C.AttachInputError("sha256 — 64 hex")
        return os.path.join(self.dir, sha)

    def _lock(self):
        import contextlib
        import fcntl

        @contextlib.contextmanager
        def held():
            fd = os.open(self.dir, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)
        return held()

    def _fsync_dir(self):
        dfd = os.open(self.dir, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def _write(self, path, data):
        tmp = path + ".tmp-%d" % os.getpid()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            view = memoryview(data)
            while view:                         # os.write может записать меньше — пишем до конца
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        self._fsync_dir()

    def holders(self, sha):
        try:
            with open(self._p(sha) + ".holders", "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return []
        return [h for h in raw.decode("utf-8").split("\n") if h]

    def _set_holders(self, sha, hs):
        hp = self._p(sha) + ".holders"
        if hs:
            self._write(hp, ("\n".join(hs) + "\n").encode("utf-8"))
        else:
            try:
                os.remove(hp)
            except FileNotFoundError:
                pass

    @staticmethod
    def _holder_path(holder):
        h = os.fspath(holder)
        if not os.path.isabs(h) or "\n" in h:
            raise C.AttachInputError("holder — абсолютный путь носителя")
        return h

    @staticmethod
    def _needed(holder, sha):
        if not os.path.lexists(holder):
            return True                         # вызов не завершён / упал до записи: держать (утечка, не потеря)
        head = R._read_head(holder)
        if head is None:
            return False
        c = P.classify(head)
        return c.kind == "pointer" and c.state == "pending" and c.fields.get("sha256") == sha

    def put(self, sha, data, holder):
        p = self._p(sha)
        if hashlib.sha256(data).hexdigest() != sha:
            raise C.AttachInputError("байты не дают sha256 очереди")
        h = self._holder_path(holder)
        with self._lock():
            if self.get(sha) is None:
                self._write(p, bytes(data))
            hs = self.holders(sha)
            if h not in hs:
                self._set_holders(sha, hs + [h])

    def get(self, sha):
        try:
            with open(self._p(sha), "rb") as f:
                data = f.read()
        except FileNotFoundError:
            return None
        return data if hashlib.sha256(data).hexdigest() == sha else None

    def release(self, sha, holder):
        """Снять держателя holder; байты удаляются, только если ни один оставшийся держатель их не требует.
        -> True, если байты удалены."""
        h = self._holder_path(holder)
        with self._lock():
            keep = [x for x in self.holders(sha) if x != h and self._needed(x, sha)]
            self._set_holders(sha, keep)
            if keep:
                return False
            try:
                os.remove(self._p(sha))
            except FileNotFoundError:
                pass
            self._fsync_dir()
            return True


def _check_queue(queue):
    if queue is None:
        return
    if getattr(queue, "durable", False) is not True or not all(callable(getattr(queue, m, None))
                                                              for m in ("put", "get", "release")):
        raise C.AttachInputError("queue — устойчивая очередь (durable=True, put(sha, data, holder)/get/release(sha, "
                                 "holder)); иначе queue=None")


# --------------------------------------------------------------------------- сохранение
@C._guard
def save(record_dir, record_id, items, *, config, env=None, queue=None, dedupe_same_bytes=True):
    """Сохранить файлы одного события (одно вложение, альбом, повтор после обрыва) в рабочее дерево записи.
    record_dir — каталог файла записи (комменты лежат там же — ссылка из коммента та же); record_id — id записи.
    Вход судится ЦЕЛИКОМ до первой записи (элементы — Incoming, uuid без повторов). Дальше элементы независимы:
    ошибка элемента (ошибка входа на носителе, собственная ошибка адаптера) даёт ЕГО результат с error и reply, прочие
    сохраняются. Повтор с теми же элементами — те же пути и ссылки; переход судит адаптер (тождество — already-recorded,
    pending — довод, unsaved — досохранение)."""
    if not isinstance(config, C.Config):
        raise C.AttachInputError("config — результат load_config / load_repo_config")
    record_dir = R.plain_path(record_dir)      # ведущий `./` и «.» — снимаются здесь (ядро их отвергает)
    if not isinstance(items, (list, tuple)) or any(not isinstance(it, Incoming) for it in items):
        raise C.AttachInputError("items — список Incoming")
    uuids = [it.uuid for it in items]
    if len(set(uuids)) != len(uuids):
        raise C.AttachInputError("два элемента с одним uuid — два файла легли бы в один путь")
    _check_queue(queue)
    for it in items:   # путь до записи: грамматика id записи и имени
        C.attachment_relpath(record_id, it.uuid, it.ext)
    results, first_of = [], {}
    release = []
    for i, it in enumerate(items):
        rel = C.attachment_relpath(record_id, it.uuid, it.ext)
        full = os.path.join(os.fspath(record_dir), *rel.split("/"))
        holder = full if os.path.isabs(full) else os.path.join(os.getcwd(), full)   # без нормализации (ядро судит)
        sha = None if it.data is None else hashlib.sha256(it.data).hexdigest()
        if dedupe_same_bytes and sha is not None and sha in first_of:
            j = first_of[sha]
            src = results[j]
            r = ItemResult()
            for k in ItemResult.__slots__:
                setattr(r, k, getattr(src, k))
            r.index, r.uuid, r.form, r.same_as = i, src.uuid, it.form, j
            r.link = link(src.path, it.caption, it.form)
            r.staged = list(src.staged)
            r.reply = None if src.reply is None else dict(src.reply)
            results.append(r)
            continue
        if sha is not None:
            first_of.setdefault(sha, i)
        queued = False
        try:
            if queue is not None and it.data is not None:
                if C.route(len(it.data), config, data_prefix=it.data, env=env).target == "storage":
                    queue.put(sha, it.data, holder)   # байты и держатель — ДО pending (норма: полные байты в очереди)
                    queued = True
            w = C.write_attachment(record_dir, record_id, it.data, ext=it.ext, config=config, uuid=it.uuid,
                                   source=it.source, media_type=it.media_type, declared_size=it.declared_size,
                                   durable_queue=queued, env=env)
        except (C.AttachInputError, C.AdapterFault) as e:
            err = "input" if isinstance(e, C.AttachInputError) else C.ADAPTER_FAULT
            results.append(_item(i, it, rel, full, error=err, detail=str(e), sha=sha))
            continue                    # байты в очереди остаются: по пути мог лежать прежний pending
        if w.path != rel:
            raise C.AdapterFault("путь записи адаптера разошёлся с путём API")
        res = _item(i, it, rel, full, w=w, sha=sha)
        results.append(res)
        if queued and w.state != "pending":
            release.append({"sha256": sha, "holder": holder})
    out = Saved()
    out.results = results
    staged = []
    for r in results:      # абсолютные: стейджинг не зависит от cwd вызывающего (без нормализации — путь судило ядро)
        r.staged = [x if os.path.isabs(x) else os.path.join(os.getcwd(), x) for x in r.staged]
        staged += [x for x in r.staged if x not in staged]
    out.staged = staged
    out.queue_release = release
    out.replies = [r.index for r in results if r.reply is not None]
    _check_preservation(items, out)
    return out


def _check_preservation(items, out):
    """Инвариант сохранения: N элементов -> ровно N результатов, index i у позиции i, uuid позиции — её (или первого
    при same_as), ссылка — на путь результата. Нарушение — собственная ошибка, не исход."""
    if len(out.results) != len(items):
        raise C.AdapterFault("результатов не столько, сколько элементов")
    for i, (it, r) in enumerate(zip(items, out.results)):
        if r.index != i:
            raise C.AdapterFault("порядок результатов нарушен")
        if r.same_as is None and r.uuid != it.uuid:
            raise C.AdapterFault("результат не своего элемента")
        if r.same_as is not None and (r.same_as >= i or out.results[r.same_as].same_as is not None):
            raise C.AdapterFault("same_as не на первый экземпляр")
        if "](" + r.path + ")" not in r.link:
            raise C.AdapterFault("ссылка не на путь результата")


@C._guard
def complete_from_queue(path, queue, config, env=None):
    """Довод pending из устойчивой очереди (повтор загрузки демоном). Байтов в очереди нет — довод по факту объекта
    (attach.core.confirm_pending: объект есть и проверен → stored, already-present; иначе pending не меняется —
    вызывающий решает fail_pending и ответ отправителю, unsaved.reply_on_later_transition). -> WriteResult адаптера.
    После stored и своего коммита — queue.release(sha256, путь)."""
    _check_queue(queue)
    if queue is None:
        raise C.AttachInputError("queue обязателен")
    head = R._read_head(os.fspath(path))
    c = P.classify(head) if head is not None else None
    if c is None or c.kind != "pointer" or c.state != "pending":
        raise C.AttachInputError("по пути не pending")
    data = queue.get(c.fields["sha256"])
    if data is None:
        # байтов нет (сняты или потеряны): довод по факту объекта — GET + sha256 локально; ok → pending → stored
        return C.confirm_pending(path, config, env)
    return C.complete_pending(path, data, config, env)


def status(repo, config, env=None, verify=False, max_pointers=None):
    """Факты статуса нормы §9.8 для /status бота — данные; текст ответа — D18 (attach.repo.status)."""
    return R.status(repo, config, env=env, verify=verify, max_pointers=max_pointers)
