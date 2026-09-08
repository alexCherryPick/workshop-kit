# -*- coding: utf-8 -*-
"""lastn — список последних заголовков ЧЕЛОВЕКА как ЧТЕНИЕ его собственных контейнеров времени.
Владелец — T2 (план §0Г; контракт исход 20). Именованное исключение из REQ-057: читается ОДИН
собственный набор контейнеров `time/{ns-}TIMESHEET-*-<person>.md` в checkout, без агрегаций,
ярлыков и обратных ссылок; когда появится индекс (D08), СЛЕДУЕТ читать его, прямое чтение — фолбэк.

Порядок ОБЪЯВЛЕН И ДЕТЕРМИНИРОВАН: убывание по дате строки; при равной дате — обратный порядок
появления в файле; при полном совпадении заголовка остаётся первое (более позднее) вхождение,
дубликаты схлопываются. Нумерация не хранится: start_n пересчитывает тот же список в момент команды.
Разбор строк — по нормативному алгоритму чтения ядра 03.2.3 (первые два токена — дата и часы;
продолжения и пустые строки пропускаются); заголовок — свободный текст без токена якоря, ДОСЛОВНО
(снимается только токен и один ASCII-пробел перед ним; NBSP и прочие байты сохраняются).
Чтение — файловая система checkout'а (только чтение); ни сети, ни git.
"""

import os
import re

__all__ = ["own_containers", "titles"]

_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) +((?:0|[1-9][0-9]{0,2})\.[0-9]{2})(?: +(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z))?(?: +(.*))?$")   # свободный текст — остаток после СЕРИИ пробелов (ядро 03.2.3: один пробел — неканон, но запись)
_ANCHOR_RE = re.compile(r" ?<!--t:[0-9a-f]{8}-->$")   # снимается ТОЛЬКО токен якоря и один ASCII-пробел писателя перед ним; прочие байты заголовка дословно (ядро 03.2.1)


def own_containers(repo_root, person, namespace=None):
    """Пути контейнеров ЭТОГО человека, отсортированные по имени (стабильно)."""
    ns = (namespace + "-") if namespace else ""
    rx = re.compile(r"^%sTIMESHEET-\d{4}-\d{2}-%s\.md$" % (re.escape(ns), re.escape(person)))
    tdir = os.path.join(repo_root, "time")
    if not os.path.isdir(tdir):
        return []
    return sorted(os.path.join(tdir, f) for f in os.listdir(tdir) if rx.match(f))


def _body_lines(path):
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8", "replace")
    # тело — после второго `---` конверта
    parts = text.split("\n")
    if parts and parts[0].strip() == "---":
        try:
            end = parts.index("---", 1)
            parts = parts[end + 1:]
        except ValueError:
            return []
    return parts


def entries(repo_root, person, namespace=None):
    """[(date, order_in_file_desc_key, title)] — все записи человека."""
    out = []
    for path in own_containers(repo_root, person, namespace):
        for idx, raw in enumerate(_body_lines(path)):
            if not raw or raw[0] in " \t":
                continue
            m = _LINE_RE.match(raw.rstrip("\r"))
            if not m:
                continue
            free = m.group(4) or ""
            title = _ANCHOR_RE.sub("", free)
            out.append((m.group(1), path, idx, title))
    return out


def titles(repo_root, person, n, namespace=None):
    """Первые n заголовков по объявленному порядку; пустые заголовки не показываются."""
    seen = set()
    result = []
    ordered = sorted(entries(repo_root, person, namespace), key=lambda e: (e[0], e[1], e[2]), reverse=True)
    for date, path, idx, title in ordered:
        if not title or title in seen:
            continue
        seen.add(title)
        result.append(title)
        if len(result) >= n:
            break
    return result
