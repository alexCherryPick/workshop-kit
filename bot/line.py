# -*- coding: utf-8 -*-
"""line — сборка дневной строки, нормализация Н1, разрез по местной полуночи, маршрутизация и
конверт при ленивом создании, вызов валидатора до коммита. Владелец — T2 (план §1–§5, §7).
Чистые функции над значениями; единственный побочный эффект — вызов бинаря валидатора
(check_line) в `check_line_rc`, вынесенный отдельно и параметризованный путём бинаря.

Н1 (D04 гл. 03 §4.1): часы = (s·100 + 1800) div 3600 сотых на ЦЕЛЫХ секундах; плавающая запрещена.
Края (§4.5): 0.00 и > 24.00 не пишутся — их отвергает валидатор (HOURS_RANGE) в check_line.
Разрез (ядро 03.5.3): местная полночь в timezone человека; сутки [00:00, 24:00).
Маршрут (D04 гл. 01 §4.3): time/{namespace-}TIMESHEET-{YYYY-MM}-{person}.md.
"""

import datetime
import re
import subprocess
from zoneinfo import ZoneInfo

HOURS_RE = re.compile(r"^(?:0|[1-9][0-9]{0,2})\.[0-9]{2}$")
PERSON_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

__all__ = ["n1_hours", "iso_z", "local_date", "split_at_local_midnight", "route", "envelope",
           "build_line", "check_line_rc", "rc_to_outcome"]


def n1_hours(seconds):
    """Часы по Н1 строкой с двумя знаками. seconds — целое неотрицательное."""
    s = int(seconds)
    if s < 0:
        raise ValueError("длительность отрицательна")
    hundredths = (s * 100 + 1800) // 3600
    return "%d.%02d" % (hundredths // 100, hundredths % 100)


def iso_z(epoch):
    return datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_date(epoch, tz_name):
    return datetime.datetime.fromtimestamp(int(epoch), tz=ZoneInfo(tz_name)).date().isoformat()


def local_midnight_after(epoch, tz_name):
    """Инстант ближайшей местной полуночи СТРОГО ПОСЛЕ epoch (целые секунды)."""
    tz = ZoneInfo(tz_name)
    d = datetime.datetime.fromtimestamp(int(epoch), tz=tz).date() + datetime.timedelta(days=1)
    midnight = datetime.datetime(d.year, d.month, d.day, tzinfo=tz)
    return int(midnight.timestamp())


def split_at_local_midnight(start, end, tz_name):
    """[(seg_start, seg_end, k)] — сегменты по полуоткрытым местным суткам. end > start."""
    start, end = int(start), int(end)
    if end <= start:
        raise ValueError("конец не позже начала")
    out = []
    cur = start
    k = 0
    while True:
        m = local_midnight_after(cur, tz_name)
        if m >= end:
            out.append((cur, end, k))
            return out
        out.append((cur, m, k))
        cur = m
        k += 1
        if k > 400:
            raise ValueError("сессия длиннее 400 суток")


def route(date_iso, person, namespace=None):
    if not DATE_RE.match(date_iso):
        raise ValueError("дата не по форме: %r" % date_iso)
    if not PERSON_RE.match(person):
        raise ValueError("person не по грамматике имени файла: %r" % person)
    if namespace is not None and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", namespace):
        raise ValueError("namespace не по грамматике: %r" % namespace)
    ns = (namespace + "-") if namespace else ""
    return "time/%sTIMESHEET-%s-%s.md" % (ns, date_iso[:7], person)


def envelope(container_id, person, date_iso, tz_name, author_handle, created_date_iso, namespace=None):
    """Полный конверт при ленивом создании (line-forms.yaml containers.timesheet; ядро 03.3.4)."""
    y, m = int(date_iso[:4]), int(date_iso[5:7])
    first = datetime.date(y, m, 1)
    last = (datetime.date(y + (m // 12), (m % 12) + 1, 1) - datetime.timedelta(days=1))
    lines = ["---", "id: %s" % container_id, "type: TIMESHEET", "line_form: daily_time_v1",
             "title: табель %s %s" % (person, date_iso[:7]), "person: %s" % person,
             "period_start: %s" % first.isoformat(), "period_end: %s" % last.isoformat(),
             "timezone: %s" % tz_name, "created: %s" % created_date_iso, "author: %s" % author_handle,
             "version: 1", "---"]
    if namespace:
        lines.insert(2, "namespace: %s" % namespace)
    return "\n".join(lines) + "\n"


def build_line(date_iso, seconds, title, anchor8, interval=None):
    """Дневная строка (ядро 03.5.1): <дата> <часы>[ <интервал>]  <текст> <!--t:якорь-->.
    title — первая строка сообщения (str), может быть пустой; interval — (start_epoch, end_epoch) или None."""
    if not DATE_RE.match(date_iso):
        raise ValueError("дата не по форме")
    hours = n1_hours(seconds)
    parts = [date_iso, hours]
    if interval is not None:
        parts.append("%s/%s" % (iso_z(interval[0]), iso_z(interval[1])))
    head = " ".join(parts)
    title = title.replace("\r", "").replace("\n", " ") if title else ""
    title = title.strip(" \t")  # ведущие пробелы поглощает разделитель (03.2.1); внутри — дословно
    tail = (title + " " if title else "") + "<!--t:%s-->" % anchor8
    return head + "  " + tail


def check_line_rc(validator_bin, line, target_path, target_file=None):
    """Вызов формы check_line (D05 §2.1): rc и текст отчёта. target_file — существующий контейнер
    (present) либо None (absent — ленивое создание, precondition-запись легальна).
    Оба класса сбоя инструмента различаются вызывающим по rc (10) и по «не запустился» (126/127/сигнал)."""
    args = [validator_bin, "check-line", line, "--target", target_path, "--no-config"]
    if target_file:
        args += ["--target-file", target_file]
    else:
        args += ["--target-absent"]
    try:
        r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:  # бинарь не запустился (ENOENT/EACCES) — класс 126/127
        return 127, "validator not executable: %s" % e
    rc = r.returncode
    if rc < 0:
        rc = 128 + (-rc)
    return rc, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def rc_to_outcome(rc, report):
    """rc валидатора → имя исхода контракта §1 и имя правила (для переспроса)."""
    if rc == 0:
        return "recorded", None
    if rc == 1:
        return "recorded_with_warning", _first_rule(report)
    if rc == 2:
        return "reask_invalid", _first_rule(report)
    if rc == 3:
        return "run_refused", None
    return "tool_failure", None  # 10, 126, 127, 128+n


def _first_rule(report):
    for ln in report.split("\n"):
        s = ln.strip()
        if s.startswith(("ERROR", "WARNING")):
            m = re.search(r"\b([A-Z][A-Z0-9_]{3,}|[EW]-[A-Z0-9-]+|§\S+ №\S+)\b", s.split(":", 1)[-1])
            return m.group(1) if m else s
    return None
