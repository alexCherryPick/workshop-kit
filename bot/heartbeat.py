# -*- coding: utf-8 -*-
"""heartbeat — сторож (dead-man alarm) D09 T5. Отдельная cron-джоба в CI ЗАКАЗЧИКА, в ОДНОЙ
concurrency-группе с поллером (одновременно не бегают). Предмет наблюдения — не «бегал ли
workflow», а ВОЗРАСТ НЕОБРАБОТАННОГО СООБЩЕНИЯ (D04 02-multi-writer-policy.md:1110-1115): успешно
отработавший, но ничего не записавший поллер и МЁРТВЫЙ поллер по «бегал ли» неразличимы.

Три предмета (пороги — .workshop/bot.yaml watchdog, числа печатает прогон, прозой не называются):
  1. МОЛЧАНИЕ: getUpdates(offset=ХРАНИМЫЙ, timeout=0) — читает, НО НЕ ПОДТВЕРЖДАЕТ (offset не
     продвигает, состояние курсора не трогает); возраст самого старого ожидающего update больше
     unprocessed_update_alarm_hours → алярм админам. Порог строго меньше окна retention (проверка
     установки). Здоровый поллер алярма НЕ поднимает (отрицательный контроль).
  2. ЗАВИСШАЯ СЕССИЯ (REQ-089): возраст открытой записи .workshop/bot-sessions.yaml больше
     stale_session_alarm_hours → исход 18: уведомление В ЧАТ ЧЕЛОВЕКА с заголовком, временем начала и
     шаблоном записи задним числом; сессия НЕ закрывается (время конца не придумывается). Повтор о ТОЙ ЖЕ
     сессии — не чаще stale_session_repeat_hours (иначе сторож учит игнорировать себя).
     АВТООТМЕНА (REQ-103, исход 24): при stale_session_cancel_minutes > 0 запись старше порога (в минутах)
     ОТМЕНЯЕТСЯ — единственный случай, когда файл состояния пишет не поллер: запись снимается одним коммитом,
     дневных строк НОЛЬ, человеку — подсказка с готовой строкой записи задним числом. Правило публикации то же,
     что у записи («записано» — после push): отвергнутый push → откат коммита, человеку ничего, админам алярм;
     недоставленная подсказка → долг в собственном состоянии (pending_notices), досылается следующим прогоном.
     Мутация только при рабочей копии, равной origin и чистой по файлу состояния. 0 — режим уведомления.
     Порог уведомления обязан быть раньше порога отмены (проверка установки) — исход 18 предупреждает об отмене.
  3. СЧЁТЧИК ОТКЛОНЕНИЙ (REQ-090): число отклонений неизвестных с прошлого отчёта и число разных
     отправителей; >= rejection_report_min → в отчёт админам.

Собственное состояние — .workshop/bot-heartbeat.yaml (last_stale_alarm, last_rejection_report_at):
файл курсора не трогается, коммитится только он. Отправка — через общий tg.py (владелец T1).
Коды выхода: 0 — прогон состоялся (с алярмами или без); 10 — сбой самого сторожа.

НЕПОКРЫВАЕМЫЙ КЛАСС — ГРАНИЦА БЕЗ АДРЕСАТА: «СМЕРТЬ ПЛАНИРОВЩИКА». Сторож живёт в том же кроне CI,
что и поллер; отключённое расписание / приостановленный / исчерпавший квоту CI убивают ОБОИХ молча,
и изнутри системы класс не наблюдаем. Единственная защита — внешний наблюдатель заказчика (вне v1).
"""

import copy
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
import yamlmini, tg, identity as identity_mod, state_store as ss, commit as commit_mod  # noqa: E402

HEARTBEAT_PATH = ".workshop/bot-heartbeat.yaml"
HB_SCHEMA = 1


def empty_hb():
    return {"schema_version": HB_SCHEMA, "last_stale_alarm": {}, "last_rejection_report_at": 0, "pending_notices": {}}


def read_hb_text(text):
    doc = yamlmini.loads(text)
    if not isinstance(doc, dict) or doc.get("schema_version") != HB_SCHEMA:
        raise ss.StateError("%s@origin: schema_version не %d" % (HEARTBEAT_PATH, HB_SCHEMA))
    doc.setdefault("last_stale_alarm", {})
    doc.setdefault("last_rejection_report_at", 0)
    doc.setdefault("pending_notices", {})
    return doc


def read_hb(root):
    path = os.path.join(root, HEARTBEAT_PATH)
    if not os.path.exists(path):
        return empty_hb()
    doc = yamlmini.load_file(path)
    if not isinstance(doc, dict) or doc.get("schema_version") != HB_SCHEMA:
        raise ss.StateError("%s: schema_version не %d" % (HEARTBEAT_PATH, HB_SCHEMA))
    doc.setdefault("last_stale_alarm", {})
    doc.setdefault("last_rejection_report_at", 0)
    doc.setdefault("pending_notices", {})
    return doc


def write_hb(root, doc):
    path = os.path.join(root, HEARTBEAT_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(yamlmini.dumps(doc, sort_keys=True).encode("utf-8"))


def _track_token():
    """Токен позиции записи задним числом — из реестра команд (литерала команды в коде нет)."""
    reg = yamlmini.load_file(os.path.join(_HERE, "kit", "commands.yaml"))
    for c in reg["commands"]:
        if c["id"] == "track":
            return c["token"]
    raise ss.StateError("реестр команд: позиции track нет")


def _stop_token():
    reg = yamlmini.load_file(os.path.join(_HERE, "kit", "commands.yaml"))
    for c in reg["commands"]:
        if c["id"] == "stop":
            return c["token"]
    raise ss.StateError("реестр команд: позиции stop нет")


def _title_looks_like_n(title):
    """Заголовок из ОДНОЙ лексемы, похожей на номер, после подстановки в команду записи задним числом
    разрешился бы как номер списка (REQ-105) — чужой заголовок. Классификация — та же, что у парсера."""
    import parse as parse_mod
    lx = parse_mod._lexemes(title)
    return len(lx) == 1 and parse_mod._number_like(lx[0][0])[0]


def track_template(rec):
    """Готовая строка записи задним числом по записи сессии: дата и время начала — из started_at_local
    (местное время человека), конец — заполнитель. Заголовок-число (round-trip через команду дал бы номер
    списка) — формой свободной строки с интервалом (та же дата/интервал, без токена команды)."""
    local = str(rec.get("started_at_local", ""))
    date_iso, hhmm = (local[:10], local[11:16]) if len(local) >= 16 else ("ГГГГ-ММ-ДД", "ЧЧ:ММ")
    title = str(rec.get("title", ""))
    body = "%s %s-ЧЧ:ММ %s" % (date_iso, hhmm, title)
    return body if _title_looks_like_n(title) else "%s %s" % (_track_token(), body)


def _sync_state(root, ref):
    """Рабочая копия пригодна для транзакции сторожа ⟺ HEAD == origin (ни ahead, ни behind) И ни одного
    изменения tracked-файлов — ни в индексе, ни в дереве (раунд 3 Codex B2/W3: `git commit` забирает ВЕСЬ
    индекс, а откат `reset --hard` стирает чужие правки; чистота одного файла учёта этого не покрывает).
    Посторонние untracked-файлы допустимы — их ни коммит, ни откат не трогают."""
    ahead = commit_mod.git(root, ["rev-list", "--count", "%s..HEAD" % ref], check=False)[1].strip()
    behind = commit_mod.git(root, ["rev-list", "--count", "HEAD..%s" % ref], check=False)[1].strip()
    dirty = commit_mod.git(root, ["status", "--porcelain", "--untracked-files=no"], check=False)[1].strip()
    return (ahead == "0" and behind == "0" and not dirty), "ahead=%s behind=%s dirty=%s" % (ahead, behind, bool(dirty))


def _bot_author(ctx):
    """Та же идентичность, что у коммитов состояния сторожа (одна на бота, не третья)."""
    handle = ctx.cfg.get("bot_handle", "workshop_bot")
    return handle, handle + "@bot.invalid"


def _deliver_pending(ctx, hb, persistable, why=""):
    """Долг уведомлений прошлых прогонов (B2 адверсария): досылается до новых уведомлений; успех снимает долг.
    Досылка только когда снятие долга будет опубликовано этим прогоном — рабочая копия РАВНА origin (ahead — коммит
    не запушится, behind — снятие легло бы на устаревший снимок; раунд 2 W3, раунд 3 W1); непригодный долг (нет chat_id)
    снимается с трассой, а не удерживается молча (W7)."""
    if not persistable and hb["pending_notices"]:
        ctx.trace.add("notice", "pending", 0, "долг уведомлений (%d) ждёт: рабочая копия не равна origin (%s), снятие не опубликуется" % (len(hb["pending_notices"]), why))
        return
    for key, note in sorted(hb["pending_notices"].items()):
        chat, text = note.get("chat_id"), note.get("text", "")
        if not (isinstance(chat, int) and text):
            del hb["pending_notices"][key]
            ctx.trace.add("notice", key, 0, "долг уведомления непригоден (нет chat_id/текста) — снят")
            continue
        if ctx.say(chat, text, from_part=int(note.get("from_part", 0) or 0)):
            del hb["pending_notices"][key]
            ctx.trace.add("notice", key, 0, "долг уведомления доставлен")
        elif ctx.last_delivered_parts > int(note.get("from_part", 0) or 0):
            note["from_part"] = ctx.last_delivered_parts   # прогресс частичной доставки — в долг, доставленное не повторяется


def _cancel_session(ctx, root, ref, handle, rec, session_age, cancel_min, hb, admins, result):
    """Исход session_cancelled: снять запись одним коммитом, опубликовать, затем уведомить. Порядок обязателен —
    «отменён» человеку только после push (иначе CI-клон отменит второй раз, а закрытие между прогонами
    запишет строку — дубль часов)."""
    ok, why = _sync_state(root, ref)
    if not ok:
        ctx.trace.add("cancel", handle, 0, "возраст %d мин > порога отмены, но рабочая копия непригодна для коммита (%s) — отложено до следующего прогона" % (session_age // 60, why))
        return "deferred"
    doc = ss.read_sessions(root)
    if handle not in doc["sessions"]:
        return "superseded"
    base = commit_mod.git(root, ["rev-parse", "HEAD"])[1].strip()
    chat = rec.get("chat_id")
    tpl = track_template(rec)
    how = "Запиши реальное время одной строкой (подставь конец)"
    if isinstance(chat, int) and chat < 0 and not tpl.startswith(_track_token()):
        how += " — в группе ответом на это сообщение или с обращением к боту, иначе бот строку не увидит"   # privacy-mode (раунд 2 W4)
    text = "⚠ учёт «%s» открыт с %s — дольше %s и не закрыт: отменён, ничего не записано. %s:\n%s" % (
        rec.get("title", ""), rec.get("started_at_local", rec.get("started_at")), _minutes_human(cancel_min), how, tpl)
    key = "%s@%s" % (handle, rec.get("started_at", 0))   # ключ долга — сессия, не человек (раунд 2 W6)
    # ТРАНЗАКЦИЯ: снятие записи И долг уведомления — одним коммитом (раунд 3 Codex B1): уведомление становится
    # обязательством ровно в момент публикации отмены; доставка ниже лишь гасит долг, потеря долга невозможна.
    hb_before = copy.deepcopy(hb)   # откат — ДЕЛЬТОЙ этой транзакции, не перечитыванием файла: прогресс прогона (погашенные долги,
    #                                   уведомления другим людям) при отказе push не теряется (раунд 4 W1)
    ss.write_sessions(root, ss.close_session(doc, handle))
    hb["last_stale_alarm"].pop(handle, None)
    if isinstance(chat, int):
        hb["pending_notices"][key] = {"chat_id": chat, "text": text}
    write_hb(root, hb)
    name, email = _bot_author(ctx)
    started_at = int(rec.get("started_at", 0))

    def on_rejected():
        # норма commit.py: reconcile → ПЕРЕЧИТАТЬ → ПЕРЕСЧИТАТЬ (раунд 4 W2). Если на авторитете этой сессии уже нет
        # (второй писатель закрыл её командой остановки — строка записана), наша отмена беспредметна: «отменён, ничего
        # не записано» было бы ложью → superseded, откат без алярма.
        if commit_mod.reconcile(root, ctx.trace) != "clean":
            return "conflict"
        cur = ss.read_sessions_at(root, ref)["sessions"].get(handle)
        if not cur or int(cur.get("started_at", 0)) != started_at:
            return "superseded"
        return "retry"
    try:
        sha = commit_mod.commit_paths(root, [ss.SESSIONS_PATH, HEARTBEAT_PATH], "workshop-bot: session_cancelled (%s)" % handle, name, email, ctx.trace)
        verdict = commit_mod.push_with_retry(root, ctx.trace, ctx.cfg["retry"]["push_max_attempts"], ctx.cfg["retry"]["push_backoff_seconds"],
                                             on_rejected, ctx.sleeper) if sha else ("refused", 0, "no_commit")
    except (commit_mod.GitError, OSError) as e:   # исключение внутри ретраев (fetch в reconcile) — тот же исход, что отвергнутый push (раунд 3 W2)
        verdict = ("failed", 0, str(e)[:160])
    if verdict[0] != "pushed":
        # не опубликовано — значит не отменено: откат к базе (и долга тоже), человеку ничего; админам — алярм, кроме
        # беспредметной отмены (superseded: сессию закрыл другой писатель — это не сбой)
        commit_mod.git(root, ["reset", "-q", "--hard", base], ctx.trace, "rollback", check=False)
        if commit_mod.git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False)[0] == 0:
            commit_mod.abort_merge(root, ctx.trace)
        hb.clear(); hb.update(hb_before)
        superseded = verdict[0] == "refused" and len(verdict) > 2 and verdict[2] == "superseded"
        ctx.trace.add("cancel", handle, 0, ("сессия уже закрыта другим писателем — отмена беспредметна, откат" if superseded else "push отмены не удался (%s) — коммит откачен, отмена отложена" % (verdict,)))
        if not superseded:
            for t in admins:
                ctx.say(t, "⚠ сторож: автоотмена учёта «%s» не опубликована (push: %s) — откачена, повтор следующим прогоном" % (handle, verdict[0]))
        return "superseded" if superseded else "deferred"
    delivered = isinstance(chat, int) and ctx.say(chat, text)
    if delivered:
        hb["pending_notices"].pop(key, None)   # долг погашен; снятие публикуется коммитом состояния сторожа в конце прогона
    elif isinstance(chat, int) and ctx.last_delivered_parts:
        hb["pending_notices"][key]["from_part"] = ctx.last_delivered_parts
    result["stale"].append({"handle": handle, "age_s": session_age, "notified": bool(delivered), "cancelled": True})
    return "cancelled"


def _minutes_human(minutes):
    h, m = divmod(int(minutes), 60)
    return "%d ч %02d мин" % (h, m) if m else "%d ч" % h


class Ctx(object):
    def __init__(self, root, transport, cfg, now=None, sleeper=None):
        self.root = root
        self.transport = transport
        self.cfg = cfg
        self.wd = cfg.get("watchdog") or {}
        self.now = now if now is not None else time.time()
        self.sleeper = sleeper or time.sleep
        self.trace = commit_mod.Trace()
        self.sent = []
        self.people_path = os.path.join(root, ".workshop", "people.yaml")

    def say(self, chat_id, text, from_part=0):
        """Недоставленное уведомление (бот заблокирован, сеть) — НЕ сбой инструмента (правило poll.Ctx.say):
        отказ в трассе, возвращается False — вызывающий решает, что делать с долгом. Текст режется по строкам тем же
        резаком и пределом, что ответы поллера (раунд 3 W4); from_part — с какой части продолжать (частичная доставка —
        раунд 4 W3): число доставленных частей всегда в self.last_delivered_parts."""
        import poll as poll_mod
        parts = poll_mod._chunks(text, poll_mod.TG_TEXT_MAX)
        self.last_delivered_parts = min(int(from_part), len(parts))
        try:
            for part in parts[self.last_delivered_parts:]:
                self.transport.send_message(chat_id, part)
                self.last_delivered_parts += 1
        except tg.TransportError as e:
            self.trace.add("send_failed", "chat:%s" % chat_id, 0, "часть %d/%d: %s" % (self.last_delivered_parts + 1, len(parts), str(e)[:100]))
            return False
        self.sent.append((chat_id, text))
        self.trace.add("send", "chat:%s" % chat_id, 0)
        return True


def _hours(x):
    return int(x) * 3600


def _oldest_pending_age(ctx, offset):
    """Возраст (сек) самого старого НЕОБРАБОТАННОГО сообщения: getUpdates с ХРАНИМЫМ offset и
    timeout=0 — читает, НЕ подтверждает; берётся min(message.date) среди update с id >= offset.
    Курсор не трогается: offset не пишется, состояние не меняется. None — ожидающих сообщений нет."""
    ups = ctx.transport.get_updates(offset=offset, limit=100, timeout_s=0, allowed_updates=["message", "callback_query"])
    ctx.trace.add("getUpdates", "offset=%d timeout=0 (замер, без подтверждения)" % offset, 0, "%d ожидающих" % len(ups))
    dates = [u["message"]["date"] for u in ups if u.get("update_id", -1) >= offset and isinstance(u.get("message"), dict) and isinstance(u["message"].get("date"), int)]
    if not dates:
        return None, len(ups)
    return int(ctx.now) - min(dates), len(ups)


def run_once(ctx):
    root = ctx.root
    # АВТОРИТЕТ — ветка origin, не рабочая копия (тройная верификация приёмки, Codex B1): локальная копия
    # может быть ahead (незапушенный коммит поллера с продвинутым offset — передать его в getUpdates значило
    # бы ПОДТВЕРДИТЬ неопубликованное) или behind (устаревший клон не видит зависшую сессию). Поэтому:
    # fetch ОБЯЗАН удаться (иначе — сбой инструмента, не «всё здорово»), а offset, сессии, карта людей и
    # собственное состояние сторожа читаются из блобов origin/<branch>; рабочая копия не сливается.
    rc, out, err = commit_mod.git(root, ["fetch", "-q", "origin"], ctx.trace, "fetch", check=False)
    if rc != 0:
        raise commit_mod.GitError("fetch origin", "сторож не получил авторитет: %s" % err.strip()[:200])
    branch = commit_mod.git(root, ["rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    ref = "origin/%s" % branch
    has_origin = commit_mod.git(root, ["rev-parse", "--verify", "-q", ref], check=False)[0] == 0
    if not has_origin:
        raise commit_mod.GitError("authority", "ветки %s в origin нет — авторитета для замера нет" % ref)
    ctx.trace.add("authority", ref, 0, "состояние читается из origin, не из рабочей копии")
    state = ss.read_state_at(root, ref)
    sessions = ss.read_sessions_at(root, ref)["sessions"]
    people_text = ss._text_at_ref(root, ref, ".workshop/people.yaml")
    people_doc = yamlmini.loads(people_text) if people_text is not None else yamlmini.load_file(ctx.people_path)
    people = identity_mod.people_list(people_doc)
    hb_text = ss._text_at_ref(root, ref, HEARTBEAT_PATH)
    hb = read_hb_text(hb_text) if hb_text is not None else empty_hb()
    admins = identity_mod.alarm_targets(people, ctx.wd.get("alarm_to", "admins"))
    result = {"silence": None, "stale": [], "rejection": None}
    offset_before = state["offset"]

    # 1. МОЛЧАНИЕ
    age, pending = _oldest_pending_age(ctx, offset_before)
    silence_s = _hours(ctx.wd["unprocessed_update_alarm_hours"])
    retention_s = _hours(ctx.wd["retention_window_hours"])
    if age is not None and age > silence_s:
        margin = retention_s - age
        for t in admins:
            ctx.say(t, "⚠ сторож: самое старое необработанное сообщение старше порога — возраст %d ч, порог %d ч, запас до окна хранения %d ч. Поллер, вероятно, не пишет (мёртв, протухли учётные данные, исчерпаны ретраи)." % (age // 3600, silence_s // 3600, margin // 3600))
        result["silence"] = {"age_s": age, "threshold_s": silence_s, "margin_s": margin}

    # 2. ЗАВИСШИЕ СЕССИИ
    stale_s = _hours(ctx.wd["stale_session_alarm_hours"])
    repeat_s = _hours(ctx.wd["stale_session_repeat_hours"])
    cancel_min = int(ctx.wd.get("stale_session_cancel_minutes", 0) or 0)
    cancel_s = cancel_min * 60
    ok_now, why_now = _sync_state(root, ref)
    _deliver_pending(ctx, hb, persistable=ok_now, why=why_now)
    for handle, rec in sorted(sessions.items()):
        started = int(rec.get("started_at", 0))
        session_age = int(ctx.now) - started
        if cancel_s > 0 and session_age > cancel_s:
            # каждая отмена — свой коммит и push; пригодность рабочей копии проверяется заново перед каждой
            fate = _cancel_session(ctx, root, ref, handle, rec, session_age, cancel_min, hb, admins, result)
            if fate != "deferred":
                continue   # cancelled — сделано; superseded — сессии уже нет, исход 18 о ней ложен (раунд 5 W1)
            # отложенная отмена — человек всё равно предупреждается по правилу исхода 18 ниже
        if session_age <= stale_s:
            continue
        last = hb["last_stale_alarm"].get(handle, 0)
        if int(ctx.now) - int(last) < repeat_s:
            ctx.trace.add("stale", handle, 0, "возраст %d ч > порога, но повтор рано (< %d ч)" % (session_age // 3600, repeat_s // 3600))
            result["stale"].append({"handle": handle, "age_s": session_age, "notified": False})
            continue
        chat = rec.get("chat_id")
        if isinstance(chat, int):
            if cancel_s > 0:
                fate = ("иначе он будет отменён без записи следующим прогоном сторожа (порог %s после начала уже пройден)" % _minutes_human(cancel_min)) if session_age > cancel_s \
                    else ("иначе через %s после начала он будет отменён без записи" % _minutes_human(cancel_min))
            else:
                fate = "или он останется открытым (я его не закрываю сам)"
            ctx.say(chat, "⚠ учёт «%s» открыт с %s — дольше %d ч и не закрыт. Закрой командой остановки (можно с временем конца: %s ЧЧ:ММ), %s. Либо запиши задним числом одной строкой:\n%s" % (rec.get("title", ""), rec.get("started_at_local", ""), stale_s // 3600, _stop_token(), fate, track_template(rec)))
        hb["last_stale_alarm"][handle] = int(ctx.now)
        result["stale"].append({"handle": handle, "age_s": session_age, "notified": True})

    # 3. СЧЁТЧИК ОТКЛОНЕНИЙ
    since = int(hb.get("last_rejection_report_at", 0))
    fresh = [r for r in state.get("unknown_rejections", []) if int(r.get("at", 0)) > since]
    rmin = int(ctx.wd["rejection_report_min"])
    if len(fresh) >= rmin:
        senders = len({r.get("telegram_id") for r in fresh})
        for t in admins:
            ctx.say(t, "⚠ сторож: с прошлого отчёта отклонено сообщений от неизвестных: %d (разных отправителей: %d). Возможно, чужой в чате или человек, забытый в карте людей (тихая потеря часов)." % (len(fresh), senders))
        hb["last_rejection_report_at"] = int(ctx.now)
        result["rejection"] = {"count": len(fresh), "senders": senders}

    # ПЕРСИСТ собственного состояния — НЕ трогая курсор; коммитится только bot-heartbeat.yaml.
    # Если рабочая копия ВПЕРЕДИ origin (незапушенный коммит поллера после исчерпания ретраев), push сторожа
    # опубликовал бы чужой курсор — публикация записи есть дело поллера; в этот прогон состояние сторожа не
    # персистится (следующий прогон его пересчитает по авторитету), причина — в трассе.
    ok_end, why_end = _sync_state(root, ref)
    if not ok_end:
        # тот же предикат, что у транзакции отмены: коммит забрал бы чужой индекс (раунд 3 Codex B2), а копия впереди origin не запушится
        ctx.trace.add("hb-state", HEARTBEAT_PATH, 0, "не персистится: рабочая копия непригодна для коммита (%s)" % why_end)
        result["offset_before"] = offset_before
        result["offset_after"] = ss.read_state_at(root, ref)["offset"]
        return result
    before = None
    if os.path.exists(os.path.join(root, HEARTBEAT_PATH)):
        with open(os.path.join(root, HEARTBEAT_PATH), "rb") as fh:
            before = fh.read()
    write_hb(root, hb)
    with open(os.path.join(root, HEARTBEAT_PATH), "rb") as fh:
        after = fh.read()
    if before != after:
        name, email = _bot_author(ctx)
        sha = commit_mod.commit_paths(root, [HEARTBEAT_PATH], "workshop-bot: сторож (состояние уведомлений)", name, email, ctx.trace)
        if sha:
            commit_mod.push_with_retry(root, ctx.trace, ctx.cfg["retry"]["push_max_attempts"], ctx.cfg["retry"]["push_backoff_seconds"], lambda: "retry" if commit_mod.reconcile(root, ctx.trace) == "clean" else "conflict", ctx.sleeper)
    # ОТ курсора ничего не отвалилось: offset после == offset до (замер не подтверждает)
    result["offset_before"] = offset_before
    result["offset_after"] = ss.read_state_at(root, ref)["offset"]
    return result


def main():
    root = os.getcwd()
    cfg = yamlmini.load_file(os.path.join(root, ".workshop", "bot.yaml"))
    token = os.environ.get("WORKSHOP_TG_BOT_TOKEN", "")
    tr = cfg.get("transport") or {}
    transport = tg.Transport(token, tr.get("http_timeout_seconds"))
    ctx = Ctx(root, transport, cfg)
    try:
        r = run_once(ctx)
    except (ss.StateError, commit_mod.GitError, yamlmini.YamlError, tg.TransportError, OSError, ValueError) as e:
        sys.stdout.write("TOOL_FAILURE %s\n" % e)
        return 10
    sys.stdout.write("\n".join(ctx.trace.lines()) + "\n")
    sys.stdout.write("silence=%s stale=%d cancelled=%d rejection=%s offset %s→%s\n" % (bool(r["silence"]), len([x for x in r["stale"] if x["notified"] and not x.get("cancelled")]), len([x for x in r["stale"] if x.get("cancelled")]), bool(r["rejection"]), r["offset_before"], r["offset_after"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
