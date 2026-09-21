# -*- coding: utf-8 -*-
"""aggregation — ЕДИНСТВЕННЫЙ продуктовый читатель сумм часов (D15 T3; контракт D15 §3, §4.4; D04 гл. 04 А1–А8,
гл. 05 правило Д; ядро 03.2.3–03.2.4). Владелец — D15-T3.

Чистое чтение checkout'а: ни сети, ни git, ни записи. Уровни сводки 1–2 — тот же читатель с фильтром человека,
уровень 3 — без фильтра. Прямое чтение табелей — ШТАТНЫЙ путь бота (alex 2026-09-20); индекс D08 обязан доказать
паритет с этим модулем (boundaries.handed_to), переход бота — МОЖЕТ.

Что делается и чем:
  * обход ВСЕХ контейнеров `time/**/*.md` (спутники `*.comments.md` — не контейнеры); `person` — ИЗ КОНВЕРТА (А3),
    не из имени файла; `ctx.cfg.namespace` (фильтр позиции last) сюда не переносится — namespaces репозитория объединяются;
  * карта людей канонизирует `handle ∪ aliases` → handle; person, которого нет в карте, остаётся ключом сам (WARNING);
  * логическая запись = строка-запись по грамматике строки (lastn._LINE_RE — общая с позицией last; дата и часы — только
    ASCII-цифры, `\\d` строкового regex Unicode-цифры пропускал бы) + ВСЕ строки до следующей строки-записи
    (ядро 03.2.3–03.2.5: продолжения с отступом и без, near-miss — WARNING, пустые строки принадлежат записи);
    сироты до первой записи — WARNING, ни в одну запись не входят; читатель не падает (§4.3, вариант (а));
  * правило Т ВНУТРИ контейнера: равные якоря → одно слагаемое, победитель — лексикографически меньшие полные
    байты записи (K7); безъякорные — каждая слагаемое; продолжение часов не несёт;
  * отзывы — продуктовым читателем undo (parse_sibling → active_retractions): строка с действующим retracts:t:
    исключена целиком (правило Д); ПРИВЯЗКА спутника — ПО ID (ядро 04.2.2): первая строка `<!-- comments-of: <id> -->`
    → контейнер с этим `id:` конверта, где бы спутник ни лежал (соседство по имени — не привязка; расхождение —
    WARNING); id без контейнера — сирота (WARNING, не действует); первая строка не по грамматике — спутник непригоден
    (WARNING); два спутника одного id — WARNING и объединение заголовков (ERROR корпуса — дело валидатора, А8);
  * конверт с повторным `person:`/`id:` — непригоден, контейнер пропущен (WARNING, §4.3: person не выдумывается);
    без `id:` — записи считаются, спутник не привязывается; повторный id у двух контейнеров — id неоднозначен,
    спутники этого id не привязываются (WARNING);
  * месяц — первые 7 байт даты СТРОКИ (А2); часы — целые сотые из текста (А1), плавающей точки нет; ничего не
    округляется (А6) и не хранится (REQ-059); пары с нулём не материализуются (А5).
Ошибка ввода-вывода или собственное исключение — наружу (tool_failure у вызывающего, hold, алярм); содержимое
файлов исключений не порождает.
"""

import datetime
import os
import re
import stat as stat_mod

import lastn
import undo as undo_mod

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — python < 3.9
    ZoneInfo = None

__all__ = ["summarize", "canonical_map", "render_tsv", "period_months", "render_reply", "person_of_envelope", "envelope_fields", "comments_of",
           "SCOPE_ME", "SCOPE_TEAM", "ELLIPSIS"]

SCOPE_ME, SCOPE_TEAM = "me", "team"
ELLIPSIS = "…"
_ANCHOR_IN_LINE = re.compile(r"<!--t:([0-9a-f]{8})-->[ \t]*$")
_ENV_KEY = re.compile(rb"^(person|id):(?:\s|$)")           # ключ конверта — считается независимо от разбора значения
_ENV_LINE = re.compile(rb"^(person|id):[ \t]+(.*)$")        # разделитель после двоеточия — пробел ИЛИ таб (YAML s-white)
_COMMENTS_OF = re.compile(rb"^<!-- comments-of: (\S+) -->$")
_DATE_CAL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
BOM = b"\xef\xbb\xbf"


def _strip_bom(data):
    """Ядро 01 §1.2: читатель ОБЯЗАН BOM переносить и молча снимать (W-FILE-BOM — предупреждение, не отказ)."""
    return data[3:] if data.startswith(BOM) else data


def _scalar(rest, ascii_only=False):
    """Значение скаляра конверта (ядро 01 §2.5: с кавычками и без — обе формы валидны; ` #` — комментарий YAML)
    → str либо None (пусто, пробелы внутри, незакрытая кавычка, escape/кавычка внутри кавычек, невалидный UTF-8,
    не-ASCII при ascii_only). Разбор побайтовый и консервативный: сомнительное — непригодно, не «как получится»."""
    v = rest.rstrip(b" \t")
    if v[:1] in (b'"', b"'"):
        q = v[:1]
        end = v.find(q, 1)                                 # закрывающая кавычка; дальше — только ` #комментарий` (T3 раунд 3)
        if end < 0:
            return None
        tail = v[end + 1:]
        if tail and not re.match(rb"^[ \t]+#", tail):
            return None
        v = v[1:end]
        if b"\\" in v:
            return None
    else:
        v = re.split(rb"[ \t]+#", v, maxsplit=1)[0].rstrip(b" \t")
    if not v or re.search(rb"\s", v):
        return None
    if ascii_only and not v.isascii():
        return None
    try:
        return v.decode("utf-8")
    except UnicodeDecodeError:
        return None
_COMMENTS_OF = re.compile(rb"^<!-- comments-of: (\S+) -->$")


# ------------------------------------------------------------------ карта людей
def canonical_map(people):
    """{handle_or_alias: canonical_handle} по списку записей карты людей (identity.people_list)."""
    canon = {}
    for p in people:
        h = str(p.get("handle"))
        canon[h] = h
        for a in p.get("aliases") or []:
            canon[str(a)] = h
    return canon


# ------------------------------------------------------------------ контейнер
def _envelope_span(data):
    """ЕДИНСТВЕННЫЙ предикат границ конверта продукта → (normalized_data, end) : end — индекс терминатора `\n---\n`
    (≥ 4) в нормализованных байтах, -1 — терминатора нет, None — конверта нет. Им пользуются envelope_fields, _body и
    построчный читатель головы (_read_head): голова кончается ровно там, где этот предикат впервые видит терминатор
    (T3-fix раунд 3: смешанные LF/CRLF и `---` второй строкой давали расхождение личного и командного режимов)."""
    data = _strip_bom(data)
    if data.startswith(b"---\r\n"):          # CRLF терпим (W-FILE-CRLF — предупреждение ядра, не отказ)
        data = data.replace(b"\r\n", b"\n")
    if not data.startswith(b"---\n"):
        return data, None
    return data, data.find(b"\n---\n", 4)


def envelope_fields(data):
    """{'person': str|None, 'id': str|None} из конверта (байты файла) либо None — конверт отсутствует или
    НЕПРИГОДЕН (повторный `person:`/`id:` — дубль ключа, ERROR валидатора; §4.3: person не выдумывается)."""
    data, end = _envelope_span(data)
    if end is None or end < 0:
        return None
    seen = {"person": 0, "id": 0}
    out = {"person": None, "id": None}
    for line in data[4:end].split(b"\n"):
        line = line.rstrip(b"\r")
        k = _ENV_KEY.match(line)
        if k:
            seen[k.group(1).decode("ascii")] += 1     # повтор ключа — с любым значением (пустым, с пробелами): дубль = ERROR
        m = _ENV_LINE.match(line)
        if m:
            key = m.group(1).decode("ascii")
            out[key] = _scalar(m.group(2), ascii_only=(key == "id"))   # id — форма uuid_canonical, только ASCII
    if seen["person"] > 1 or seen["id"] > 1:
        return None
    return out


def person_of_envelope(data):
    """`person` из конверта либо None — контейнер без конверта/без person/с повторным ключом пропускается."""
    f = envelope_fields(data)
    return None if f is None else f["person"]


def comments_of(sibling):
    """id контейнера из ПЕРВОЙ строки спутника (ядро 04.2.1: ровно `<!-- comments-of: <id> -->`) либо None —
    спутник непригоден. Повторные строки comments-of ниже (подпись union-слияния заголовков) привязки не задают."""
    first = _strip_bom(sibling).split(b"\n", 1)[0].rstrip(b"\r")
    m = _COMMENTS_OF.match(first)
    return _scalar(m.group(1), ascii_only=True) if m else None


def _body(data):
    data, end = _envelope_span(data)
    if end is None:
        return b""
    return data[end + 5:] if end >= 0 else b""


_DATE_FIRST = re.compile(rb"^\d{4}-\d{2}-\d{2}(?: |$)")


def _record_line(raw):
    """Строка-запись по ядру 03.2.3 → (date, cents, anchor|None) либо None. Шаг 1: отступ — всегда продолжение;
    далее грамматика строки (общая с позицией last) с условием ASCII для даты и часов."""
    if raw[:1] in (b" ", b"\t"):
        return None
    text = raw.decode("utf-8", "replace")
    m = lastn._LINE_RE.match(text)
    if not m or not m.group(1).isascii() or not m.group(2).isascii():
        return None
    whole, frac = m.group(2).split(".")
    am = _ANCHOR_IN_LINE.search(text)
    return m.group(1), int(whole) * 100 + int(frac), (am.group(1) if am else None)


def _calendar_ok(date):
    """Дата-форма прошла грамматику; календарная валидность — диагностика (WARNING), не признак записи (03.2.3 шаг 6)."""
    m = _DATE_CAL.match(date)
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return True
    except (ValueError, AttributeError):
        return False


def _records(body, trace, rel):
    """[(date, cents, anchor|None, k7_bytes)] — логические записи контейнера по ядру 03.2.3–03.2.5: запись тянется до
    следующей строки-записи; всё между — её продолжения (с отступом и без; пустые строки — 03.2.5) и входит в K7
    через LF. Завершающий LF файла — терминатор, не строка. Сироты до первой записи в K7 не входят (WARNING)."""
    lines = body.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    out, cur = [], None
    for raw in lines:
        raw = raw.rstrip(b"\r")           # CRLF терпим: \r — не часть записи, не часть якоря и не часть байтов K7
        rec = _record_line(raw)
        if rec is None:
            if cur is None:
                if raw.strip():
                    trace("WARN", rel, "ORPHAN_CONTINUATION: продолжение до первой записи")
                continue
            if _DATE_FIRST.match(raw):     # 03.2.4 near-miss: первый токен — дата, но записью строка не стала
                trace("WARN", rel, "NEAR_MISS: продолжение с датой первым токеном")
            cur[3] += b"\n" + raw
            continue
        if cur is not None:
            out.append(tuple(cur))
        if not _calendar_ok(rec[0]):
            trace("WARN", rel, "DATE_INVALID: некалендарная дата %s (запись читается по А8, месяц — первые 7 байт)" % rec[0])
        cur = [rec[0], rec[1], rec[2], raw]
    if cur is not None:
        out.append(tuple(cur))
    return out


def _rule_t(recs, trace, rel):
    by_anchor, unanchored = {}, []
    for r in recs:
        if r[2] is None:
            unanchored.append(r); continue
        prev = by_anchor.get(r[2])
        if prev is not None and prev[3] != r[3]:   # правило Т: расхождение тождественных — WARNING (побайтовый дубль — нет)
            trace("WARN", rel, "якорь %s: расхождение записей, победитель — меньшие байты K7" % r[2])
        if prev is None or r[3] < prev[3]:
            by_anchor[r[2]] = r
    return list(by_anchor.values()) + unanchored


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _read_head(path):
    """Конверт контейнера ПОСТРОЧНО — до строки, на которой предикат `_envelope_span` впервые видит терминатор
    (граница РОВНО та же, что у полного чтения); без открывающего `---` — только первая строка; без терминатора — до EOF. Личные уровни (REQ-108 v10, решение alex 1(б)):
    у ЧУЖИХ контейнеров читается ровно конверт (обнаружение и привязка спутников по id), ни байта тела.
    IO-ошибка — наружу (владелец неизвестен ⇒ tool_failure, §4.3)."""
    with open(path, "rb") as fh:
        head = fh.readline()
        while True:
            _d, end = _envelope_span(head)                    # тот же предикат, что у envelope_fields/_body
            if end is None or end >= 0:
                return head                                   # конверта нет — контейнер пропускается с WARNING; либо терминатор найден
            line = fh.readline()
            if not line:
                return head                                   # без терминатора — до EOF (конверт непригоден, как и при полном чтении)
            head += line


def _read_first_line(path):
    """Первая строка спутника (привязка по id, ядро 04.2.1); тело чужого спутника в личном режиме не читается."""
    with open(path, "rb") as fh:
        return fh.readline()


def _utf8_check(data, trace, rel):
    """Ядро 01 §1.1: файл — UTF-8; невалидные байты — WARNING (файл читается по А8); BOM — W-FILE-BOM (снимается)."""
    if data.startswith(BOM):
        trace("WARN", rel, "W-FILE-BOM: BOM снят")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        trace("WARN", rel, "FILE_UTF8: невалидный UTF-8 в файле (распознаваемые записи читаются по А8)")


def _containers(root):
    """→ (контейнеры, спутники) — все `time/**/*.md`; спутники `*.comments.md` — не контейнеры."""
    tdir = os.path.join(root, "time")
    try:
        st = os.stat(tdir)                     # IO-ошибка (EACCES и т. п.) — наружу, не «пусто»: isdir глотал OSError (T3 раунд 2)
    except FileNotFoundError:
        return [], []                          # каталога нет — записей нет (законная пустота)
    if not stat_mod.S_ISDIR(st.st_mode):
        return [], []
    out, sibs = [], []

    def _raise(err):
        raise err                              # ошибка доступа к подкаталогу — собственный IO-сбой (tool_failure), не частичная сумма

    for dp, dn, fn in os.walk(tdir, onerror=_raise):
        for f in fn:
            if f.endswith(".comments.md"):
                sibs.append(os.path.join(dp, f))
            elif f.endswith(".md"):
                out.append(os.path.join(dp, f))
    return sorted(out), sorted(sibs)


def summarize(root, people, only_person=None, trace=None):
    """→ [(canonical_person, 'YYYY-MM', cents)] по всем контейнерам; only_person — канонический handle (уровни 1–2).
    trace(kind, rel_path, note) — необязательный приёмник WARNING.
    Охват чтения (REQ-108 v10, решение alex 1(б) 2026-09-21): принадлежность — по `person` конверта, не по имени файла,
    поэтому конверты ВСЕХ контейнеров и первая строка ВСЕХ спутников читаются всегда (обнаружение, привязка по id);
    тела контейнеров, проверка UTF-8 и заголовки спутников в личном режиме читаются ТОЛЬКО у собственных контейнеров
    (handle + aliases) — чужие тела не читаются и WARNING по ним не выдаются; уровень 3 читает всё."""
    trace = trace or (lambda *a: None)
    canon = canonical_map(people)
    sums = {}
    paths, sibs = _containers(root)
    personal = only_person is not None
    # 1) контейнеры: конверт → (who, id, записи после правила Т); id → контейнер для привязки спутников
    containers = []                            # [(path, who, recs)]; recs None — чужой контейнер в личном режиме (тело не читалось)
    by_id = {}                                 # id → индекс контейнера | None (id неоднозначен)
    for path in paths:
        rel = os.path.relpath(path, root)
        data = _read_head(path) if personal else _read(path)
        if not personal:
            _utf8_check(data, trace, rel)
        fields = envelope_fields(data)
        if fields is None or fields["person"] is None:
            trace("WARN", rel, "контейнер без конверта/person или с повторным ключом конверта пропущен")
            continue
        person = fields["person"]
        who = canon.get(person)
        if who is None:
            trace("WARN", rel, "person %s не в карте людей — остаётся ключом" % person)
            who = person
        cid = fields["id"]
        if cid is None:
            trace("WARN", rel, "контейнер без id: спутник не привязывается")
        elif cid in by_id:
            trace("WARN", rel, "повторный id контейнера %s — id неоднозначен, спутники этого id не привязываются" % cid)
            by_id[cid] = None
        else:
            by_id[cid] = len(containers)
        if personal and who != only_person:
            containers.append((path, who, None))          # чужой: конверт прочитан, тело — нет
            continue
        if personal:
            data = _read(path)                            # собственный контейнер — целиком
            _utf8_check(data, trace, rel)
        containers.append((path, who, _rule_t(_records(_body(data), trace, rel), trace, rel)))
    # 2) спутники: привязка ПО ID (ядро 04.2.2) через comments-of; заголовки — читателем undo (CRLF снят там же)
    bound = {}                                 # индекс контейнера → [заголовки]
    for sib in sibs:
        rel = os.path.relpath(sib, root)
        if personal:
            first = _read_first_line(sib)
            cid = comments_of(first)
            idx = by_id.get(cid) if cid is not None else None
            if idx is not None and containers[idx][2] is None:
                continue                                  # спутник чужого контейнера: тело не читается
            data = _read(sib) if (cid is not None and idx is not None) else first
        else:
            data = _read(sib)
            cid = comments_of(data)
        _utf8_check(data, trace, rel)
        if cid is None:
            trace("WARN", rel, "спутник непригоден (первая строка не comments-of)")
            continue
        idx = by_id.get(cid)
        if idx is None:
            trace("WARN", rel, "спутник-сирота (id %s без контейнера)" % cid)
            continue
        if undo_mod.sibling_path(containers[idx][0]) != sib:
            trace("WARN", rel, "пара разъехалась по имени: спутник принадлежит %s (по id)" % os.path.relpath(containers[idx][0], root))
        if idx in bound:
            trace("WARN", rel, "два спутника одного id %s: заголовки объединяются" % cid)
        hdrs = undo_mod.parse_sibling(data)
        lines = [l.rstrip(b"\r") for l in _strip_bom(data).split(b"\n")]
        n_hdr_like = sum(1 for l in lines if l.startswith(b"### "))
        if n_hdr_like != len(hdrs):
            trace("WARN", rel, "HEADER_MALFORMED: строк вида `### ` %d, разобрано заголовков %d — неразобранные не действуют" % (n_hdr_like, len(hdrs)))
        if not hdrs:
            trace("WARN", rel, "SIBLING_EMPTY: спутник без единого заголовка коммента (04.2.3: файл создаётся первым комментом)")
        first_hdr = next((i for i, l in enumerate(lines) if l.startswith(b"### ")), len(lines))
        if any(l.strip() for l in lines[1:first_hdr]):
            trace("WARN", rel, "SIBLING_PREAMBLE: непустой текст между первой строкой и первым заголовком — вне тела коммента")
        bound.setdefault(idx, []).extend(hdrs)
    # 3) суммы: действующие отзывы — читателем undo над объединёнными заголовками контейнера
    for idx, (path, who, recs) in enumerate(containers):
        if recs is None or (only_person is not None and who != only_person):
            continue
        hdrs = bound.get(idx)
        gone = set()
        if hdrs:
            for date, cents, anchor, _full in recs:
                if anchor is not None and undo_mod.line_is_retracted(anchor, hdrs):
                    gone.add(anchor)
        for date, cents, anchor, _full in recs:
            if anchor is not None and anchor in gone:
                continue
            key = (who, date[:7])
            sums[key] = sums.get(key, 0) + cents
    rows = [(p, m, c) for (p, m), c in sums.items() if c > 0]
    rows.sort(key=lambda r: (r[0].encode("utf-8"), r[1]))
    return rows


def render_tsv(rows):
    """Машинная форма §4.4: person<TAB>YYYY-MM<TAB>cents<LF>, без заголовка/BOM/CR; пустой результат — 0 байт."""
    return b"".join(("%s\t%s\t%d\n" % r).encode("utf-8") for r in rows)


# ------------------------------------------------------------------ период
def _ym(year, month):
    return "%04d-%02d" % (year, month)


def _shift(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    y, m = divmod(idx, 12)
    return y, m + 1


def period_months(message_date, tz_name, spec):
    """spec: 'current' | 'all' | N (int ≥ 1) → (first_ym, last_ym) либо None для 'all'.
    «Сейчас» — message.date в timezone ОТПРАВИТЕЛЯ; N предыдущих ПОЛНЫХ месяцев без текущего (календарно,
    через границу года). За пределами календаря → ValueError('summary_period_out_of_range')."""
    if spec == "all":
        return None
    local = datetime.datetime.fromtimestamp(int(message_date), ZoneInfo(tz_name))
    y, m = local.year, local.month
    if spec == "current":
        return _ym(y, m), _ym(y, m)
    n = int(spec)
    if n < 1:
        raise ValueError("summary_bad_argument")
    fy, fm = _shift(y, m, -n)
    ly, lm = _shift(y, m, -1)
    if fy < datetime.MINYEAR:
        raise ValueError("summary_period_out_of_range")
    return _ym(fy, fm), _ym(ly, lm)


def select(rows, rng):
    """Строки внутри диапазона [first, last] (месяцы сравниваются как байты YYYY-MM); rng None — все."""
    if rng is None:
        return list(rows)
    a, b = rng
    return [r for r in rows if a <= r[1] <= b]


# ------------------------------------------------------------------ ответ
def _hours(cents):
    return "%d.%02d" % (cents // 100, cents % 100)


def render_reply(rows, scope, rng, requested_all):
    """Логический ответ §4.4 (чистая функция от строк TSV + охват + диапазон): строки через LF, без завершающего LF.
    rows — уже отфильтрованные по охвату и диапазону; rng — (first, last) либо None (all)."""
    s = "мои часы" if scope == SCOPE_ME else "команда"
    if not rows:
        if requested_all:
            return "%s за все месяцы: записей нет" % s
        return "%s за %s: записей нет" % (s, _range_text(rng))
    if rng is None:
        months = sorted(set(r[1] for r in rows))
        rng = (months[0], months[-1])
    out = ["%s за %s" % (s, _range_text(rng))]
    if scope == SCOPE_ME:
        for _p, month, cents in rows:
            out.append("%s — %s ч" % (month, _hours(cents)))
        return "\n".join(out)
    cur = None
    for person, month, cents in rows:
        if person != cur:
            out.append(person); cur = person
        out.append("%s — %s ч" % (month, _hours(cents)))
    return "\n".join(out)


def _range_text(rng):
    a, b = rng
    return a if a == b else "%s%s%s" % (a, ELLIPSIS, b)

