# -*- coding: utf-8 -*-
"""attach.fsio — файловые операции адаптера относительно ДЕСКРИПТОРОВ проверенных каталогов (R2, находка 2/3).

Инвариант: проверенный объект ФС и изменяемый — один и тот же. Строковый путь разрешается РОВНО ОДИН раз — в
начале (realpath корня записи или каталога назначения); дальше цепочка каталогов открывается пошагово от «/»
с O_NOFOLLOW | O_DIRECTORY, и все чтения, создания, атомарные замены и удаления идут через dir_fd этого
дескриптора. Подмена любого компонента (symlink, rename) после открытия не перенаправляет запись: дескриптор
держит исходный inode каталога; symlink на месте компонента при открытии — отказ (FsRefused).

Никакой политики формата здесь нет: имена и грамматики проверяет attach.core.
"""
import errno
import fcntl
import os
import re
import stat

__all__ = ["FsRefused", "CarrierDir", "open_real_dir", "open_for_read", "save_outside", "TEST_HOOK"]

_O_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
# Предки — ТОЛЬКО обход (право x, как у POSIX-разрешения пути ядром): O_PATH (Linux) | O_SEARCH (macOS).
# Честный фолбэк, если нет ни того, ни другого: O_RDONLY (тогда предку нужно ещё право r) — TRAVERSE_ONLY False.
_TRAVERSE_FLAG = getattr(os, "O_PATH", None) or getattr(os, "O_SEARCH", None)
TRAVERSE_ONLY = _TRAVERSE_FLAG is not None
_O_TRAVERSE = ((_TRAVERSE_FLAG if TRAVERSE_ONLY else os.O_RDONLY) | getattr(os, "O_DIRECTORY", 0) | _O_NOFOLLOW
               | _O_CLOEXEC)

# Точка синхронизации для тестов гонок (события, не задержки): TEST_HOOK(stage, **ctx) | None.
TEST_HOOK = None


def _hook(stage, **ctx):
    if TEST_HOOK is not None:
        TEST_HOOK(stage, **ctx)


class FsRefused(Exception):
    """Компонент пути — symlink, не каталог, не обычный файл или алиас: операция отказана без побочных эффектов."""


def _step(dirfd, name, create):
    """Открыть подкаталог name относительно dirfd без следования symlink (создать при create)."""
    if name in ("", ".", "..") or os.sep in name:
        raise FsRefused("компонент пути вне формы")
    try:
        return os.open(name, _O_DIR, dir_fd=dirfd)
    except FileNotFoundError:
        if not create:
            raise FsRefused("каталога нет") from None
        try:
            os.mkdir(name, 0o755, dir_fd=dirfd)
        except FileExistsError:
            pass
        try:
            return os.open(name, _O_DIR, dir_fd=dirfd)
        except OSError:
            raise FsRefused("созданный каталог подменён") from None
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
            raise FsRefused("компонент пути — symlink или не каталог") from None
        raise


def _traverse(dirfd, name, create):
    """Промежуточный компонент: открыть только для обхода (без права чтения каталога); symlink — отказ.
    Нет каталога и create — создаётся и открывается обычным шагом."""
    if name in ("", ".", "..") or os.sep in name:
        raise FsRefused("компонент пути вне формы")
    try:
        return os.open(name, _O_TRAVERSE, dir_fd=dirfd)
    except FileNotFoundError:
        if not create:
            raise FsRefused("каталога нет") from None
        return _step(dirfd, name, create)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
            raise FsRefused("компонент пути — symlink или не каталог") from None
        raise


def open_real_dir(path, create=False, traverse_last=False):
    """Дескриптор каталога realpath(path), открытого пошагово от «/» с O_NOFOLLOW. Предки — только обход
    (O_PATH/O_SEARCH); последний компонент — на чтение, либо тоже только обход (traverse_last). Возвращает (fd, real).
    realpath — единственное строковое разрешение; дальше — только дескрипторы."""
    real = os.path.realpath(os.path.abspath(os.fspath(path)))
    comps = [c for c in real.split(os.sep) if c]
    fd = os.open("/", _O_TRAVERSE)
    try:
        for i, comp in enumerate(comps):
            last = i == len(comps) - 1
            nfd = _step(fd, comp, create) if (last and not traverse_last) else _traverse(fd, comp, create)
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd, real


def _lstat_at(dirfd, name):
    try:
        return os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _open_file_at(dirfd, name):
    """Обычный файл name: открытие НЕБЛОКИРУЮЩЕЕ (FIFO не ждёт писателя), затем fstat + S_ISREG, затем блокирующий
    режим. FIFO, сокет, устройство, каталог — FsRefused без зависания; symlink — FsRefused."""
    try:
        fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC | _O_NONBLOCK, dir_fd=dirfd)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK):
            raise FsRefused("файл — symlink") from None
        if e.errno in (errno.ENXIO, errno.EOPNOTSUPP, errno.ENODEV, errno.EISDIR, errno.EWOULDBLOCK):
            raise FsRefused("не обычный файл") from None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise FsRefused("не обычный файл")
        os.set_blocking(fd, True)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "rb")


def _write_atomic_at(dirfd, name, data):
    """Временный файл (O_EXCL|O_NOFOLLOW) + renameat в ТОМ ЖЕ каталоге-дескрипторе. Заменяется запись каталога,
    не inode: жёсткие ссылки на прежний файл не меняются; symlink на месте имени заменяется сам, цель не трогается."""
    st = _lstat_at(dirfd, name)
    if st is not None and stat.S_ISDIR(st.st_mode):
        raise FsRefused("на месте файла — каталог")
    tmp = ".%s.tmp-%s" % (name, os.urandom(6).hex())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC, 0o644, dir_fd=dirfd)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _hook("tmp-written", tmp=tmp)
        os.rename(tmp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
    finally:
        if _lstat_at(dirfd, tmp) is not None:
            os.unlink(tmp, dir_fd=dirfd)


# Временный файл адаптера: «.<имя>.tmp-<12 hex>». После SIGKILL между созданием и renameat он остаётся; его
# подметает следующая операция ПОД БЛОКИРОВКОЙ каталога (живого писателя в этот момент нет — все пишут под ней),
# иначе `git add -A` бота подхватит мусор вне filename.pattern.
_TMP_RE = re.compile(r"\A\.[^/]+\.tmp-[0-9a-f]{12}\Z")


def _sweep_tmp(dirfd):
    swept = []
    for entry in os.listdir(dirfd):
        if _TMP_RE.match(entry):
            st = _lstat_at(dirfd, entry)
            if st is not None and stat.S_ISREG(st.st_mode):
                os.unlink(entry, dir_fd=dirfd)
                swept.append(entry)
    return swept


class CarrierDir(object):
    """Каталог attachments/<record-id>/ записи, открытый цепочкой дескрипторов: корень записи (realpath) →
    attachments (O_NOFOLLOW) → <record-id> (O_NOFOLLOW). lock=True — flock на дескрипторе <record-id>/
    (межпроцессная сериализация перехода). Все операции — через dir_fd."""

    def __init__(self, record_dir, reserved, record_id, create=False, lock=False):
        self.record_dir, self.reserved, self.record_id = record_dir, reserved, record_id
        self.create, self.lock = create, lock
        self.fd = None

    def __enter__(self):
        # корень записи и attachments/ — только обход; <record-id>/ — на чтение (листинг, flock, renameat)
        rfd, _real = open_real_dir(self.record_dir, create=self.create, traverse_last=True)
        try:
            afd = _traverse(rfd, self.reserved, self.create)
        finally:
            os.close(rfd)
        try:
            self.fd = _step(afd, self.record_id, self.create)
        finally:
            os.close(afd)
        try:
            if self.lock:
                fcntl.flock(self.fd, fcntl.LOCK_EX)
                self.swept = _sweep_tmp(self.fd)
            _hook("carrier-opened", carrier=self)
        except BaseException:
            os.close(self.fd)
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.lock:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
        return False

    def exists(self, name):
        return _lstat_at(self.fd, name) is not None

    def read(self, name):
        """Полное содержимое обычного файла name или None (нет файла); symlink — FsRefused."""
        f = _open_file_at(self.fd, name)
        if f is None:
            return None
        with f:
            return f.read()

    def write(self, name, data):
        _write_atomic_at(self.fd, name, data)


def open_for_read(record_dir, reserved, record_id, name):
    """Один открытый файл носителя (через цепочку дескрипторов, без блокировки): классификация и выдача байт
    читаются из него же. None — файла нет."""
    with CarrierDir(record_dir, reserved, record_id, create=False, lock=False) as cd:
        return _open_file_at(cd.fd, name)


def save_outside(out, data, reserved, source_path=None):
    """Запись вне носителей. Каталог назначения открывается пошагово (realpath, O_NOFOLLOW); отказ, если он
    (по именам ОТКРЫТОЙ цепочки) — reserved/ или reserved/<x>/; если имя назначения — symlink, не обычный файл,
    файл с несколькими жёсткими ссылками или тот же inode, что источник. Замена — renameat в открытом каталоге."""
    out = os.fspath(out)
    base = os.path.basename(out)
    if not base or base in (".", ".."):
        raise FsRefused("назначение — не имя файла")
    dfd, real = open_real_dir(os.path.dirname(os.path.abspath(out)), create=False)
    try:
        comps = [c for c in real.split(os.sep) if c]
        if reserved in comps[-2:]:
            raise FsRefused("назначение под %s/ — запись в носитель только переходом" % reserved)
        _hook("out-dir-opened", fd=dfd, real=real)
        st = _lstat_at(dfd, base)
        if st is not None:
            if not stat.S_ISREG(st.st_mode):
                raise FsRefused("назначение — symlink или не обычный файл")
            if st.st_nlink > 1:
                raise FsRefused("назначение имеет несколько жёстких ссылок")
            if source_path is not None:
                try:
                    ss = os.stat(source_path, follow_symlinks=False)
                except FileNotFoundError:
                    ss = None
                if ss is not None and (ss.st_dev, ss.st_ino) == (st.st_dev, st.st_ino):
                    raise FsRefused("назначение — сам источник")
        if data is not None:
            _write_atomic_at(dfd, base, data)
    finally:
        os.close(dfd)
