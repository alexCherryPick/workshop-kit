# -*- coding: utf-8 -*-
"""undo — отзыв СОБСТВЕННОЙ дневной строки командой реестра и возврат отозванной в учёт. Владелец — T8
(план-дополнение v2; REQ-093; ядро 04.5 retracts:t: / retracts:; D04 гл. 05 I2 — отзыв, не правка).

Порядок проверок ФИКСИРОВАН (ревью T8 #2, #3, #5, #6):
  1. ПРАВИЛО Т — до выбора цели: id коммента из identity ЭТОГО сообщения (k=0) уже есть в спутниках
     человека → identical_repeat (повтор доставки после незапушенного/запушенного коммита).
  2. Выбор цели — ОДИН ключ порядка для обоих режимов: порядок lastn (дата ↓, файл ↓, порядок в файле ↓);
     только СВОИ контейнеры, только строки С ЯКОРЕМ (строка без якоря целью не становится и не
     перескакивается: reask_undo_not_found/target_unanchored);
       без N → новейшая НЕотозванная строка с якорем; переключения (возврата) у команды без номера нет;
       с N   → новейшая строка, чей заголовок — позиция N последнего списка заголовков; если она отозвана —
               возврат (retracts:<c-id> на КАЖДЫЙ действующий отзыв, тем же коммитом).
  3. Действие отзыва — ИДЕМПОТЕНТНОСТЬ ПО ЦЕЛИ на обоих уровнях (D04 гл. 05 §4.3; раунд 1 №6): коммент
     действует ⟺ на него нет ни одного действующего retracts:; строка отозвана ⟺ есть хотя бы один
     действующий retracts:t: на её якорь. Повторный отзыв строки после возврата — НОВЫЙ retracts:t:
     (не «отзыв возврата»); возврат — retracts:<c-id> на КАЖДЫЙ действующий отзыв тем же коммитом.
  4. Гонка (раунд 1 №4, №7): снимок = (путь, sha256) ВСЕХ своих контейнеров и спутников; после reconcile
     при изменении снимка цель проверяется ПО ЯКОРЮ (anchor_state): состояние цели изменилось → исход 23
     с причиной target_changed, записи нет (человек повторяет команду, видя актуальный список).
Тело коммента — ПОЛНЫЕ байты сообщения-команды (§1Г(а)); автор — handle ЧЕЛОВЕКА; заголовок — 04.3.1.
Чистые функции над байтами файлов checkout'а: ни сети, ни git (запись и коммит — poll.py).
"""

import os
import re

import comment as comment_mod
import lastn

__all__ = ["sibling_path", "parse_sibling", "line_is_retracted", "already_applied", "select_target", "build_blocks", "snapshot", "anchor_state", "titles_state"]

# грамматика заголовка коммента — по ядру 02.2.1: токен времени с ДОЛЯМИ секунд валиден как вход (другой писатель может
# их выдать; валидатор принимает) — бот обязан видеть такой отзыв (раунд 9 T8, Fable-2 B1)
_HDR_RE = re.compile(r"^### (%s) · ([A-Za-z0-9._-]{1,64}) <!--c:([0-9a-f-]{36}) (about:t:|retracts:t:|retracts:|corrects:|replies-to:)([0-9a-f-]{8,36})-->$" % comment_mod.TS_TOKEN)


def sibling_path(container_path):
    return container_path[:-3] + ".comments.md"


def _read(path):
    if not os.path.exists(path):
        return b""
    with open(path, "rb") as fh:
        return fh.read()


def parse_sibling(data):
    """[{'cid','link','target','author','ts'}] — заголовки комментов спутника в порядке файла (байты → строки;
    неразбираемые строки пропускаются: тела и заголовки чужих форм)."""
    out = []
    for raw in data.split(b"\n"):
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        m = _HDR_RE.match(line)
        if m:
            out.append({"ts": m.group(1), "author": m.group(2), "cid": m.group(3), "link": m.group(4), "target": m.group(5)})
    return out


def comment_active(cid, headers, _index=None):
    """Коммент ДЕЙСТВУЕТ ⟺ на него НЕТ ни одного действующего retracts:<cid> — идемпотентность по цели и для
    комментов (раунд 1, №6). Семантика рекурсивная (цикл — участник цикла не действует), ВЫЧИСЛЕНИЕ —
    итеративное с явным стеком (раунд 2, W3: цепочка «отзыв отзыва» любой глубины законна для валидатора и
    не должна ронять поллер RecursionError)."""
    if _index is None:
        _index = {}
        for h in headers:
            if h["link"] == "retracts:":
                _index.setdefault(h["target"], []).append(h["cid"])
    memo = {}
    # кадр: [узел, итератор отзывающих, найден_действующий_отзыв, затронут_циклом]
    stack = [[cid, iter(_index.get(cid, ())), False, False]]
    onpath = {cid}
    while stack:
        frame = stack[-1]
        node, it = frame[0], frame[1]
        child = next(it, None)
        if child is None:
            stack.pop(); onpath.discard(node)
            value = not frame[2]
            if not frame[3]:
                memo[node] = value
            if not stack:
                return value
            parent = stack[-1]
            if value:
                parent[2] = True
            if frame[3]:
                parent[3] = True
            continue
        if frame[2]:
            continue            # действующий отзыв уже найден — остальные не важны
        if child in onpath:
            frame[3] = True     # цикл: этот отзывающий не действует (по семантике), результат узла не мемоизируется
            continue
        if child in memo:
            if memo[child]:
                frame[2] = True
            continue
        onpath.add(child)
        stack.append([child, iter(_index.get(child, ())), False, False])
    return True


def active_retractions(anchor8, headers):
    """Действующие комменты-отзывы строки с этим якорем (их id) — в порядке файла."""
    return [h["cid"] for h in headers if h["link"] == "retracts:t:" and h["target"] == anchor8 and comment_active(h["cid"], headers)]


def line_is_retracted(anchor8, headers):
    """Идемпотентность по цели (D04 §4.3): хотя бы один действующий отзыв → строка отозвана."""
    return len(active_retractions(anchor8, headers)) >= 1


def already_applied(root, person, ident, namespace=None):
    """Правило Т для отзыва: id коммента, вычисленный из identity этого сообщения (k=0), уже стоит в
    каком-либо спутнике человека → повтор доставки, писать нечего. Дата в id не участвует в сравнении:
    сравниваются 12+62 бит соли — id с той же identity совпадает целиком при том же message.date, а при
    ином message.date (перепосылка того же update невозможна с иной датой) — не наш случай."""
    for cpath in lastn.own_containers(root, person, namespace):
        for h in parse_sibling(_read(sibling_path(cpath))):
            if h["author"] == person and _same_identity(h["cid"], ident, h["ts"]):
                return True
    return False


def _same_identity(cid, ident, ts):
    """id коммента детерминирован из (identity, k, message.date): сверка — пересчёт по message.date заголовка."""
    import calendar
    import time
    try:
        epoch = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return False
    for k in range(0, 8):
        if comment_mod.comment_id(ident, epoch, k) == cid:
            return True
    return False


def select_target(root, person, n, last_titles, namespace=None):
    """→ ('line', target) | ('reask', reason). target = {'path','anchor','date','hours','title','retracted',
    'retractions':[cid…]} — по ОДНОМУ ключу порядка lastn (новейшая первая)."""
    entries = []
    for cpath in lastn.own_containers(root, person, namespace):
        for idx, raw in enumerate(lastn._body_lines(cpath)):
            if not raw or raw[0] in " \t":
                continue
            m = lastn._LINE_RE.match(raw.rstrip("\r"))
            if not m:
                continue
            free = m.group(4) or ""
            am = re.search(r"<!--t:([0-9a-f]{8})-->$", free)
            entries.append({"date": m.group(1), "path": cpath, "idx": idx, "hours": m.group(2),
                            "title": lastn._ANCHOR_RE.sub("", free), "anchor": am.group(1) if am else None, "line": raw})
    ordered = sorted(entries, key=lambda e: (e["date"], e["path"], e["idx"]), reverse=True)
    if not ordered:
        return "reask", "no_line"
    sib_cache = {}

    def headers_of(path):
        if path not in sib_cache:
            sib_cache[path] = parse_sibling(_read(sibling_path(path)))
        return sib_cache[path]

    if n is None:
        for e in ordered:
            if e["anchor"] is None:
                return "reask", "target_unanchored"   # хвост без якоря — не перескакивается молча
            hs = headers_of(e["path"])
            if line_is_retracted(e["anchor"], hs):
                continue
            return "line", dict(e, retracted=False, retractions=[])
        return "reask", "no_line"
    if last_titles is None or n < 1 or n > len(last_titles):
        return "reask", "n_out_of_range"
    title = last_titles[n - 1]
    for e in ordered:
        if e["title"] != title:
            continue
        if e["anchor"] is None:
            return "reask", "target_unanchored"
        hs = headers_of(e["path"])
        rets = active_retractions(e["anchor"], hs)
        return "line", dict(e, retracted=len(rets) >= 1, retractions=rets)
    return "reask", "no_line"


def snapshot(root, person, namespace=None):
    """[(путь, sha256)] всех своих контейнеров и их спутников — область снимка = область ключа порядка (№7)."""
    import hashlib
    out = []
    for cpath in lastn.own_containers(root, person, namespace):
        for p in (cpath, sibling_path(cpath)):
            out.append((p, hashlib.sha256(_read(p)).hexdigest()))
    return out


def anchor_state(root, person, anchor8, namespace=None):
    """→ (found: bool, retracted: bool, retractions: [cid]) для строки с этим якорем среди своих контейнеров."""
    for cpath in lastn.own_containers(root, person, namespace):
        for raw in lastn._body_lines(cpath):
            if raw.rstrip("\r").endswith("<!--t:%s-->" % anchor8):
                hs = parse_sibling(_read(sibling_path(cpath)))
                rets = active_retractions(anchor8, hs)
                return True, len(rets) >= 1, rets
    return False, False, []


def titles_state(root, person, titles, namespace=None):
    """[bool] — для каждого заголовка списка последних: отозвана ли НОВЕЙШАЯ строка с ним (для пометки в
    ответе; повтор по номеру берёт заголовок как есть, пометка в текст не входит)."""
    out = []
    for i in range(len(titles)):
        kind, t = select_target(root, person, i + 1, titles, namespace)
        out.append(bool(kind == "line" and t["retracted"]))
    return out


def build_blocks(target, ident, message_date, body_bytes, person):
    """→ (outcome, [(sibling_rel_path, block_bytes, cid)]): отзыв — один блок retracts:t:<якорь>;
    возврат — по блоку retracts:<c-id> на КАЖДЫЙ действующий отзыв (k = порядковый номер)."""
    if not target["retracted"]:
        cid, head, block = comment_mod.build(ident, message_date, body_bytes, person, target["anchor"], 0, comment_mod.LINK_RETRACT_LINE)
        return "retracted", [(target["path"], block, cid)]
    out = []
    for k, rcid in enumerate(target["retractions"]):
        cid, head, block = comment_mod.build(ident, message_date, body_bytes, person, rcid, k, comment_mod.LINK_RETRACT_COMMENT)
        out.append((target["path"], block, cid))
    return "unretracted", out
