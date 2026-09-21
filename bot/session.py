# -*- coding: utf-8 -*-
"""session — ЧИСТАЯ машина состояний учёта. Владелец — T2 (план §0Б, §0В, §1–§7; контракт §1Б, §1).

Сигнатура: decide(record, parsed, person, config, last_titles=None) → Decision (dict).
  record   — запись файла состояния для человека (dict по схеме §1Б(б)) либо None («закрыт»);
  parsed   — выход parse.Parser.parse (kind='input');
  person   — {'handle': str, 'timezone': iana};
  config   — {'last_default_n': int, 'namespace': str|None};
  last_titles — список заголовков для start_n (порядок — lastn.py); None, если не подавался.
Ни сети, ни git, ни файловой системы: чтение/запись файла состояния — T3 (state_store.py); значения
времени — только из message.date (НИКОГДА момент прогона: в сигнатуре нет «сейчас»).

Decision:
  outcome      — имя исхода из закрытого перечня контракта §1 (tg-bot.yaml outcomes);
  new_record   — dict (открыть/обновить), None (закрыть) либо 'unchanged';
  lines        — [{'date','seconds','interval'|None,'title','k','identity','message_date'}] — заготовки
                 дневных строк (якорь по identity и k проставляет T3 через anchor.py на целевом файле);
  comments     — [{'identity','message_date','body': bytes,'k'}] — носители комментов (по одному
                 блоку на каждую строку k; коммент есть ⟺ у носителя есть хвост; тело — ПОЛНЫЕ байты
                 текста носителя, контракт §1Г(а));
  reply        — данные для ответа (T3 строит текст): title, hours, interval, reason, rule, …
Исходы, зависящие от файла/валидатора/git (identical_repeat по файлу, reask_invalid по rc,
conflict/retries/run_refused/tool_failure), назначает T3 после прогона валидатора; здесь —
«первичный» исход клетки таблицы переходов и переспросы, решаемые по значениям.
"""

import datetime
from zoneinfo import ZoneInfo

import line as line_mod

__all__ = ["decide", "UNCHANGED"]

UNCHANGED = "unchanged"
SCHEMA_VERSION = 1


def _local_dt(epoch, tz_name):
    return datetime.datetime.fromtimestamp(int(epoch), tz=ZoneInfo(tz_name))


def _epoch_of_local(date_iso, h, m, tz_name):
    """Местное время → инстант. Несуществующее местное время (весенний переход, D04 §3.3) → None;
    повторяющийся час (осенний переход) — ПЕРВЫЙ проход (fold=0; правило главы §1). 24:00 = полночь
    следующей даты."""
    y, mo, d = (int(x) for x in date_iso.split("-"))
    tz = ZoneInfo(tz_name)
    naive = datetime.datetime(y, mo, d) + datetime.timedelta(hours=h, minutes=m)
    aware = naive.replace(tzinfo=tz, fold=0)
    back = aware.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None)
    if back != naive:
        return None
    return int(aware.timestamp())


def _hours_sum(lines):
    """Сумма часов СТРОК в сотых (то, что записано), а не Н1 от суммы секунд (Н-4 раунда 2)."""
    cents = 0
    for l in lines:
        h = line_mod.n1_hours(l["seconds"])
        cents += int(h[:-3]) * 100 + int(h[-2:])
    return "%d.%02d" % divmod(cents, 100)


def _reask(outcome, reason, **extra):
    d = {"outcome": outcome, "new_record": UNCHANGED, "lines": [], "comments": [], "reply": {"reason": reason}}
    d["reply"].update(extra)
    return d


def _segments_to_lines(start, end, tz_name, title, identity, message_date):
    lines = []
    for seg_start, seg_end, k in line_mod.split_at_local_midnight(start, end, tz_name):
        lines.append({"date": line_mod.local_date(seg_start, tz_name), "seconds": seg_end - seg_start,
                      "interval": (seg_start, seg_end), "title": title, "k": k,
                      "identity": identity, "message_date": message_date})
    return lines


def _carriers(lines, carriers):
    """Комменты: на каждую строку k — блок от каждого носителя, У КОТОРОГО ЕСТЬ ХВОСТ (tail_rule);
    тело блока — ПОЛНЫЕ байты сообщения-носителя (контракт §1Г(а): хвост решает, есть ли коммент;
    тело — полный текст побайтово)."""
    out = []
    for c in carriers:
        if not c["tail"]:
            continue
        for ln in lines:
            out.append({"identity": c["identity"], "message_date": c["message_date"], "body": c["text"], "k": ln["k"]})
    return out


def decide(record, parsed, person, config, last_titles=None, tail_of=None):
    if parsed.get("kind") != "input":
        raise ValueError("decide принимает только kind='input'")
    pos = parsed["position"]
    tz = person["timezone"]
    state_open = record is not None
    # П-6: позиция, зависящая от момента, кнопкой не исполняется — у нажатия нет времени
    if parsed.get("is_callback") and parsed.get("time_bearing"):
        return _reask("reask_unparsed", "callback_time_bearing", position=pos)
    if parsed.get("is_callback") and not parsed.get("callback_allowed"):
        return _reask("reask_unparsed", "callback_not_allowed", position=pos)

    if pos in ("start_title", "start_n"):
        if pos == "start_n":
            if last_titles is None:
                return _reask("reask_unparsed", "last_list_unavailable", n=parsed["n"])
            n = parsed["n"]
            if n < 1 or n > len(last_titles):
                return _reask("reask_unparsed", "n_out_of_range", n=n, available=len(last_titles))
            title = last_titles[n - 1]
        else:
            title = parsed["title"]
        if state_open:
            if record.get("start_update_id") == parsed.get("update_id"):
                return _reask("identical_repeat", "same_start_update", title=record.get("title"))
            return _reask("reask_start_already_open", "already_open", title=record.get("title"),
                          started_at=record.get("started_at"), started_at_local=record.get("started_at_local"))
        started = int(parsed["message_date"])
        new_record = {"title": title, "start_text": parsed["text"].decode("utf-8"), "started_at": started,
                      "started_at_local": _local_dt(started, tz).isoformat(), "chat_id": parsed["chat_id"],
                      "start_message_id": parsed["message_id"], "start_update_id": parsed["update_id"],
                      "schema_version": SCHEMA_VERSION}
        return {"outcome": "session_opened", "new_record": new_record, "lines": [], "comments": [],
                "reply": {"title": title, "started_at_local": new_record["started_at_local"]}}

    if pos == "stop":
        if not state_open:
            return _reask("reask_stop_without_open", "no_open_session")
        start = int(record["started_at"])
        end = int(parsed["message_date"])
        if parsed.get("stop_time"):
            # конец = ПОСЛЕДНЕЕ такое местное время не позже момента сообщения (REQ-104): сегодня по
            # местной дате сообщения (в повторяющийся час осеннего перехода — ПОЗДНИЙ проход, если он не позже
            # сообщения; иначе ранний), а если ещё не наступило — вчера. Несуществующее местное время — переспрос.
            h, mi = parsed["stop_time"]
            date_iso = line_mod.local_date(end, tz)
            today = _local_passes(date_iso, h, mi, tz)
            if not today:
                return _reask("reask_unparsed", "nonexistent_local_time")
            fit = [ts for ts in today if ts <= end]
            if not fit:
                fit = _local_passes(_prev_date(date_iso), h, mi, tz)
                if not fit:
                    return _reask("reask_unparsed", "nonexistent_local_time")
            end = max(fit)
        if end <= start:
            # интервал невыразим (ноль или отрицательная длительность): переспрос по правилу HOURS_RANGE
            return _reask("reask_invalid", "end_not_after_start", rule="HOURS_RANGE", started_at=start, ended_at=end)
        lines = _segments_to_lines(start, end, tz, record["title"], parsed["identity"], end)
        start_text = _as_bytes(record.get("start_text", ""))
        opening_identity = "tg:%d:%d" % (int(record["chat_id"]), int(record["start_message_id"]))
        if tail_of is None:
            raise ValueError("decide: при закрытии нужен tail_of (Parser.tail_of) — правило хвоста носителя открытия читается из реестра, не копией")
        carriers = [{"identity": opening_identity, "message_date": start, "tail": tail_of(start_text), "text": start_text},
                    {"identity": parsed["identity"], "message_date": end, "tail": parsed["tail"], "text": parsed["text"]}]
        return {"outcome": "session_closed_recorded", "new_record": None, "lines": lines,
                "comments": _carriers(lines, carriers),
                "reply": {"title": record["title"], "seconds_total": end - start,
                          "hours_total": _hours_sum(lines), "segments": len(lines)}}

    if pos in ("track", "free_text"):
        if pos == "track" and parsed.get("n"):
            # <N> вместо заголовка (REQ-105) — разрешение тем же списком и с теми же переспросами, что у start_n
            if last_titles is None:
                return _reask("reask_unparsed", "last_list_unavailable", n=parsed["n"])
            n = parsed["n"]
            if n < 1 or n > len(last_titles):
                return _reask("reask_unparsed", "n_out_of_range", n=n, available=len(last_titles))
            parsed = dict(parsed); parsed["title"] = last_titles[n - 1]
        date_iso = parsed.get("date") or line_mod.local_date(parsed["message_date"], tz)
        t = parsed["time"]
        if t["kind"] == "duration":
            lines = [{"date": date_iso, "seconds": int(t["seconds"]), "interval": None, "title": parsed["title"],
                      "k": 0, "identity": parsed["identity"], "message_date": parsed["message_date"]}]
        else:
            start = _epoch_of_local(date_iso, t["from"][0], t["from"][1], tz)
            end = _epoch_of_local(date_iso, t["to"][0], t["to"][1], tz)
            if start is None or end is None:   # местного времени в этот день НЕ БЫЛО (дыра DST) — переспрос, не фабрикация
                return _reask("reask_unparsed", "nonexistent_local_time")
            if end == start:                    # равные концы — как у таймера: HOURS_RANGE, не «сутки»
                return _reask("reask_invalid", "end_equals_start", rule="HOURS_RANGE")
            if end < start:  # «23:00-01:00» — конец на СЛЕДУЮЩЕЙ местной дате (не +86400: на дне DST сутки не 24 ч)
                end = _epoch_of_local(_next_date(date_iso), t["to"][0], t["to"][1], tz)
                if end is None:
                    return _reask("reask_unparsed", "nonexistent_local_time")
            lines = _segments_to_lines(start, end, tz, parsed["title"], parsed["identity"], parsed["message_date"])
        carriers = [{"identity": parsed["identity"], "message_date": parsed["message_date"], "tail": parsed["tail"], "text": parsed["text"]}]
        return {"outcome": "recorded", "new_record": UNCHANGED, "lines": lines, "comments": _carriers(lines, carriers),
                "reply": {"title": parsed["title"], "date": date_iso, "segments": len(lines),
                          "hours_total": _hours_sum(lines)}}

    if pos == "last":
        # без N — ВСЕ уникальные заголовки (REQ-106): last_default_n: 0 = «все» в пределах last_max_n (предел ставит поллер)
        n = parsed.get("n") or int(config.get("last_default_n", 0) or 0) or len(last_titles or [])
        return {"outcome": "last_list_given", "new_record": UNCHANGED, "lines": [], "comments": [],
                "reply": {"n": n, "titles": (last_titles or [])[:n] if last_titles is not None else None}}

    if pos == "help":
        return {"outcome": "help_given", "new_record": UNCHANGED, "lines": [], "comments": [], "reply": {}}

    if pos == "summary":
        # D15 (REQ-108): сводка часов — чистое чтение табелей (bot/aggregation.py, считает поллер); состояние учёта
        # не трогается в обоих состояниях; охват и период — из разбора (парсер), «сейчас» — message.date отправителя
        return {"outcome": "summary_given", "new_record": UNCHANGED, "lines": [], "comments": [],
                "reply": {"scope": parsed.get("scope", "me"), "period": parsed.get("period", "current")}}

    if pos == "undo":
        # T8: клетка {closed, open} × undo — состояние учёта НЕ трогается; сам исход (retracted / unretracted /
        # reask_undo_not_found / identical_repeat) зависит от файлов и решается писателем (poll._handle_undo,
        # undo.py); здесь — первичный исход клетки таблицы переходов и признак «решает писатель».
        return {"outcome": "retracted", "new_record": UNCHANGED, "lines": [], "comments": [], "reply": {"decided_by": "undo"}}

    raise ValueError("позиция вне таблицы переходов: %r" % pos)


def _as_bytes(text):
    return text.encode("utf-8") if isinstance(text, str) else bytes(text)


def _local_passes(date_iso, h, m, tz_name):
    """Все инстанты с этим местным временем в этот день (0 — не существует: весенняя дыра; 1 — обычно;
    2 — повторяющийся час осеннего перехода). Существование — тем же круговым тестом, что _epoch_of_local."""
    y, mo, d = (int(x) for x in date_iso.split("-"))
    tz = ZoneInfo(tz_name)
    naive = datetime.datetime(y, mo, d) + datetime.timedelta(hours=h, minutes=m)
    out = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        ts = int(aware.timestamp())
        if datetime.datetime.fromtimestamp(ts, tz).replace(tzinfo=None) == naive and ts not in out:
            out.append(ts)
    return out


def _prev_date(date_iso):
    y, m, d = (int(x) for x in date_iso.split("-"))
    return (datetime.date(y, m, d) - datetime.timedelta(days=1)).isoformat()


def _next_date(date_iso):
    y, m, d = (int(x) for x in date_iso.split("-"))
    return (datetime.date(y, m, d) + datetime.timedelta(days=1)).isoformat()


