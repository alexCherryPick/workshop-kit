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
  2. ЗАВИСШАЯ СЕССИЯ (REQ-089): читает .workshop/bot-sessions.yaml (НЕ мутируя), возраст открытой
     записи больше stale_session_alarm_hours → исход 18: уведомление В ЧАТ ЧЕЛОВЕКА с заголовком и
     временем начала; сессия НЕ закрывается (время конца не придумывается). Повтор о ТОЙ ЖЕ сессии —
     не чаще stale_session_repeat_hours (иначе сторож учит игнорировать себя).
  3. СЧЁТЧИК ОТКЛОНЕНИЙ (REQ-090): число отклонений неизвестных с прошлого отчёта и число разных
     отправителей; >= rejection_report_min → в отчёт админам.

Собственное состояние — .workshop/bot-heartbeat.yaml (last_stale_alarm, last_rejection_report_at):
файл курсора не трогается, коммитится только он. Отправка — через общий tg.py (владелец T1).
Коды выхода: 0 — прогон состоялся (с алярмами или без); 10 — сбой самого сторожа.

НЕПОКРЫВАЕМЫЙ КЛАСС — ГРАНИЦА БЕЗ АДРЕСАТА: «СМЕРТЬ ПЛАНИРОВЩИКА». Сторож живёт в том же кроне CI,
что и поллер; отключённое расписание / приостановленный / исчерпавший квоту CI убивают ОБОИХ молча,
и изнутри системы класс не наблюдаем. Единственная защита — внешний наблюдатель заказчика (вне v1).
"""

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
    return {"schema_version": HB_SCHEMA, "last_stale_alarm": {}, "last_rejection_report_at": 0}


def read_hb_text(text):
    doc = yamlmini.loads(text)
    if not isinstance(doc, dict) or doc.get("schema_version") != HB_SCHEMA:
        raise ss.StateError("%s@origin: schema_version не %d" % (HEARTBEAT_PATH, HB_SCHEMA))
    doc.setdefault("last_stale_alarm", {})
    doc.setdefault("last_rejection_report_at", 0)
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
    return doc


def write_hb(root, doc):
    path = os.path.join(root, HEARTBEAT_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(yamlmini.dumps(doc, sort_keys=True).encode("utf-8"))


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

    def say(self, chat_id, text):
        self.sent.append((chat_id, text))
        self.transport.send_message(chat_id, text)
        self.trace.add("send", "chat:%s" % chat_id, 0)


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
    for handle, rec in sorted(sessions.items()):
        started = int(rec.get("started_at", 0))
        session_age = int(ctx.now) - started
        if session_age <= stale_s:
            continue
        last = hb["last_stale_alarm"].get(handle, 0)
        if int(ctx.now) - int(last) < repeat_s:
            ctx.trace.add("stale", handle, 0, "возраст %d ч > порога, но повтор рано (< %d ч)" % (session_age // 3600, repeat_s // 3600))
            result["stale"].append({"handle": handle, "age_s": session_age, "notified": False})
            continue
        chat = rec.get("chat_id")
        if isinstance(chat, int):
            ctx.say(chat, "⚠ учёт «%s» открыт с %s — дольше %d ч и не закрыт. Закрой командой остановки или он останется открытым (я его не закрываю сам)." % (rec.get("title", ""), rec.get("started_at_local", ""), stale_s // 3600))
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
    ahead = commit_mod.git(root, ["rev-list", "--count", "%s..HEAD" % ref], check=False)[1].strip()
    if ahead.isdigit() and int(ahead) > 0:
        ctx.trace.add("hb-state", HEARTBEAT_PATH, 0, "не персистится: рабочая копия впереди origin на %s коммит(ов) поллера" % ahead)
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
        sha = commit_mod.commit_paths(root, [HEARTBEAT_PATH], "workshop-bot: сторож (состояние уведомлений)", ctx.cfg.get("bot_handle", "workshop_bot"), ctx.cfg.get("bot_handle", "workshop_bot") + "@bot.invalid", ctx.trace)
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
    sys.stdout.write("silence=%s stale=%d rejection=%s offset %s→%s\n" % (bool(r["silence"]), len([x for x in r["stale"] if x["notified"]]), bool(r["rejection"]), r["offset_before"], r["offset_after"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
