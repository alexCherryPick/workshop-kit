# -*- coding: utf-8 -*-
"""poll — поллер getUpdates: цикл «получить → разрешить отправителя → просканировать → записать →
закоммитить → запушить → подтвердить» по семантике D04 §2.3 и контракту §1 (двадцать исходов).
Владелец — T3. Запуск обёрткой без аргументов: `python3 .workshop/bot/poll.py` из корня репозитория
заказчика; всё остальное — файлы (.workshop/bot.yaml, people.yaml, bot-sessions.yaml, bot-state.yaml)
и один секрет в окружении (WORKSHOP_TG_BOT_TOKEN). Бинарь валидатора — .workshop-bin/workshop-validator
(install.py validator) либо WORKSHOP_VALIDATOR.

Инварианты, исполняемые здесь:
  * обновления обрабатываются СТРОГО по возрастанию update_id; результат батча [A,B] тождествен
    прогонам [A] и [B] подряд (состояние переносится внутри прогона);
  * ХРАНИМЫЙ offset (bot-state.yaml) — единственный авторитет подтверждения: getUpdates зовётся с
    ним, а продвигается он только после успешного push коммита, несущего запись (или, для исходов
    без записи, коммитом состояния в конце батча) — серверное подтверждение никогда не опережает push;
  * один порождающий запись исход = ровно один коммит (строки + комменты + состояние + карта людей);
  * pull непосредственно перед коммитом; после отвергнутого push — reconcile, ПЕРЕЧИТАТЬ, ПЕРЕСЧИТАТЬ;
  * исходы 10–13 держат offset и ОСТАНАВЛИВАЮТ батч (следующие update ждут следующего прогона);
    алярм — через tg.py адресатам из карты людей; rc процесса = 2 (обёртка падает — громкий отказ).
Коды выхода: 0 — прогон состоялся (в том числе с переспросами); 2 — исход класса 10–13; 10 — сбой самого поллера.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
import yamlmini, tg, parse as parse_mod, session as session_mod, lastn, line as line_mod, identity as identity_mod  # noqa: E402
import secrets as secrets_mod, state_store as ss, commit as commit_mod, build_help  # noqa: E402
import comment as comment_mod  # noqa: E402 — раскладка UUIDv7 одна (id контейнера при ленивом создании)

HOLD_OUTCOMES = ("conflict_p1_unmet", "retries_exhausted", "run_refused", "tool_failure")
RECORD_OUTCOMES = ("recorded", "recorded_with_warning", "session_opened", "session_closed_recorded")


class Ctx(object):
    def __init__(self, root, transport, cfg, validator_bin, mint_id=None, sleeper=None, bot_username=None):
        self.root = root
        self.transport = transport
        self.cfg = cfg
        self.validator_bin = validator_bin
        self.mint_id = mint_id or comment_mod.uuid7_random   # id контейнера — СЛУЧАЙНЫЙ UUIDv7 (раскладка бит одна, в comment.py)
        self.sleeper = sleeper or (lambda s: __import__("time").sleep(s))
        self.bot_username = bot_username
        self.trace = commit_mod.Trace()
        self.log = []
        self.outgoing = []  # (chat_id, text) — для трассы/тестов; отправка — через transport
        self.registry = parse_mod.Parser(os.path.join(_HERE, "kit", "commands.yaml"), bot_username)
        self.commands_doc = yamlmini.load_file(os.path.join(_HERE, "kit", "commands.yaml"))
        self.patterns = secrets_mod.load_patterns(yamlmini.load_file(os.path.join(_HERE, "kit", "secret-patterns.yaml")))
        self.people_path = os.path.join(root, ".workshop", "people.yaml")

    # ---------------------------------------------------------------- ввод-вывод
    def say(self, chat_id, text, reply_to=None):
        self.outgoing.append((chat_id, text))
        self.transport.send_message(chat_id, text, reply_to_message_id=reply_to)
        self.trace.add("send", "chat:%s" % chat_id, 0)

    def alarm(self, text, people):
        for t in identity_mod.alarm_targets(people, (self.cfg.get("watchdog") or {}).get("alarm_to", "admins")):
            try:
                self.say(t, "⚠ сторож бота: " + text)
            except tg.TransportError as e:
                self.log.append("alarm недоставлен %s: %s" % (t, e))

    def short_help(self):
        return build_help.render_short(self.commands_doc)

    def full_help(self):
        return build_help.render_help(self.commands_doc)


def load_people(ctx):
    return identity_mod.people_list(yamlmini.load_file(ctx.people_path)), yamlmini.load_file(ctx.people_path)


def token_of(ctx, pos_id):
    return ctx.registry.by_id[pos_id]["token"]


# -------------------------------------------------------------------- ответы (T3 — тексты)
def _states_line():
    return "принято мессенджером ✓ · закоммичено ✓ · запушено ✓"


def reply_text(ctx, outcome, decision, parsed, extra=None):
    r = decision.get("reply", {}) if decision else {}
    extra = extra or {}
    if outcome == "recorded" or outcome == "recorded_with_warning":
        t = "записано: %s · %s ч · «%s» — %s" % (r.get("date", ""), r.get("hours_total", ""), r.get("title", ""), _states_line())
        if r.get("segments", 1) > 1:
            t += "\nстрок: %d (сессия перешла местную полночь)" % r["segments"]
        if outcome == "recorded_with_warning":
            t += "\nпредупреждение валидатора: %s" % extra.get("rule", "")
        return t + extra.get("note", "")
    if outcome == "session_opened":
        return "учёт пошёл: «%s» с %s. Закрыть — %s%s" % (r.get("title"), r.get("started_at_local"), token_of(ctx, "stop"), extra.get("note", ""))
    if outcome == "session_closed_recorded":
        t = "записано: %s ч · «%s» — %s" % (r.get("hours_total"), r.get("title"), _states_line())
        if r.get("segments", 1) > 1:
            t += "\nстрок: %d (сессия перешла местную полночь)" % r["segments"]
        if extra.get("rule"):
            t += "\nпредупреждение валидатора: %s" % extra["rule"]
        return t + extra.get("note", "")
    if outcome == "reask_unparsed":
        return "не понял: %s\n\n%s" % (r.get("reason", ""), ctx.short_help())
    if outcome == "reask_invalid":
        return "не записал: валидатор отверг строку — правило %s. Поправь и пришли снова." % extra.get("rule", r.get("rule", ""))
    if outcome == "reask_correction":
        return "исправление уже записанных часов делается в приложении, не через бота (И5). В табель ничего не записано."
    if outcome == "reask_start_already_open":
        return "учёт уже открыт: «%s» с %s. Закрой командой %s" % (r.get("title"), r.get("started_at_local"), token_of(ctx, "stop"))
    if outcome == "reask_stop_without_open":
        return "открытого учёта нет.\n\n%s" % ctx.short_help()
    if outcome == "rejected_unknown_sender":
        return "тебя нет в карте людей (твой id в мессенджере: %s) — попроси администратора добавить тебя." % extra.get("from_id")
    if outcome == "rejected_secret":
        return "в сообщении есть похожее на секрет: %s. Не записал. Если это не секрет — пришли то же сообщение с префиксом %s" % (extra.get("names"), ctx.registry.confirm_prefix)
    if outcome == "help_given":
        return ctx.full_help()
    if outcome == "last_list_given":
        titles = r.get("titles") or []
        if not titles:
            return "записей пока нет."
        return "последние заголовки:\n" + "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(titles)) + "\nповторить: %s <N>" % token_of(ctx, "start_n")
    return outcome


def last_keyboard(ctx, titles):
    rows = [[{"text": "%d" % (i + 1), "switch_inline_query_current_chat": "%s %d" % (token_of(ctx, "start_n"), i + 1)}] for i in range(len(titles))]
    return {"inline_keyboard": rows} if rows else None


# -------------------------------------------------------------------- цикл
def _read_bytes(root, rel):
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        return b""
    with open(p, "rb") as fh:
        return fh.read()


def _snapshot_base(ctx, root, state_doc):
    """Снимок файлов состояния В ТОМ ВИДЕ, в каком они прочитаны в память (или записаны этим прогоном):
    против него после reconcile распознаётся ОДНОСТОРОННЯЯ чужая правка (git сливает её тривиально, -merge
    конфликтует лишь при двусторонней) — верификатор приёмки Fable, BLOCKER-1."""
    ctx.base = {"sessions": _read_bytes(root, ss.SESSIONS_PATH), "state": _read_bytes(root, ss.STATE_PATH), "state_doc": state_doc}


def _merge_state_after_remote_change(base_doc, mem_doc, fresh_doc):
    """Файл прогона изменился удалённо: авторитет — диск; поверх него — ДЕЛЬТА этого батча (записи списков,
    накопленные с момента снимка), offset = max(диск, память). Ни один факт с авторитета не теряется."""
    out = dict(fresh_doc)
    out["offset"] = max(int(fresh_doc.get("offset", 0)), int(mem_doc.get("offset", 0)))
    for k in ("unknown_rejections", "self_registrations", "secret_rejections"):
        delta = list(mem_doc.get(k, []))[len(base_doc.get(k, [])):]
        out[k] = (list(fresh_doc.get(k, [])) + delta)[-ss.LIST_CAP:]
    return out


def _clean_worktree(ctx, root):
    """Прогон начинается с чистой рабочей копии СВОИХ путей: недописанное прошлым прогоном (смерть до
    коммита) — мусор, писатель этих файлов один; в эфемерном клоне CI это no-op. Чужие пути не трогаются."""
    commit_mod.git(root, ["checkout", "-q", "--", "."], ctx.trace, "clean", check=False)
    commit_mod.git(root, ["clean", "-fq", "--", "time"], check=False)


def run_once(ctx):
    root = ctx.root
    _clean_worktree(ctx, root)
    state = ss.read_state(root)
    sessions = ss.read_sessions(root)
    people, people_doc = load_people(ctx)
    bot_handle = ctx.cfg.get("bot_handle")
    if not identity_mod.bot_author_present(people, bot_handle):
        return _fatal(ctx, "tool_failure", "handle бота %r отсутствует в карте людей (W-AUTHOR-UNKNOWN)" % bot_handle, people)
    tr = ctx.cfg.get("transport") or {}
    # offset для getUpdates — от АВТОРИТЕТА (origin после fetch), не от локальной копии: незапушенный коммит
    # прошлого прогона (исчерпание ретраев) offset не подтверждает — его update придут снова и лягут по правилу Т
    commit_mod.git(root, ["fetch", "-q", "origin"], ctx.trace, "fetch")
    branch = commit_mod.git(root, ["rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    auth = ss.authority_offset(root, "origin/%s" % branch)
    if auth is None and commit_mod.git(root, ["rev-parse", "--verify", "-q", "origin/%s" % branch], check=False)[0] == 0:
        auth = 0                          # ветка в origin есть, файла состояния в ней нет — подтверждено ничего
    if auth is not None and auth < state["offset"]:
        ctx.trace.add("offset", "authority", 0, "local %d > origin %d — берётся origin" % (state["offset"], auth))
        state = ss.set_offset(state, auth)
    _snapshot_base(ctx, root, state)
    updates = ctx.transport.get_updates(offset=state["offset"], limit=100, timeout_s=tr.get("long_poll_seconds", 0), allowed_updates=["message", "callback_query"])
    ctx.trace.add("getUpdates", "offset=%d" % state["offset"], 0, "%d update(s)" % len(updates))
    updates = sorted(updates, key=lambda u: u.get("update_id", 0))   # авторитет порядка — update_id
    result = {"processed": 0, "outcomes": [], "held": None, "commits": []}
    pending_state_only = False
    for u in updates:
        uid = u.get("update_id")
        if uid is None:
            continue
        if uid < state["offset"]:
            ctx.trace.add("identical", "update:%s" % uid, 0, "ниже водяного знака offset")
            result["outcomes"].append((uid, "identical_repeat"))
            continue
        outcome, state, sessions, people_doc, people, held = _handle(ctx, u, state, sessions, people_doc, people, result)
        result["outcomes"].append((uid, outcome))
        result["processed"] += 1
        if held:
            result["held"] = (uid, outcome)
            break
        state = ss.set_offset(state, uid + 1)
        pending_state_only = pending_state_only or outcome not in RECORD_OUTCOMES
    # состояние прогона (offset и счётчики после НЕпишущих исходов) — один коммит в конце батча;
    # авторитет «что уже закоммичено» — файл на диске (пишущие исходы пишут его сами)
    on_disk = ss.read_state(root)
    sha = None
    if on_disk != state:
        ss.write_state(root, state)
        sha = commit_mod.commit_paths(root, [ss.STATE_PATH], "workshop-bot: состояние прогона (offset %d)" % state["offset"], bot_handle, bot_handle + "@bot.invalid", ctx.trace)
        _snapshot_base(ctx, root, state)
    # незапушенное (коммит состояния либо коммиты прошлого прогона после исчерпания ретраев) — push с ретраями
    ahead = commit_mod.git(root, ["rev-list", "--count", "origin/%s..HEAD" % branch], check=False)[1].strip()
    if sha or (ahead.isdigit() and int(ahead) > 0 and not result["held"]):
        verdict = commit_mod.push_with_retry(root, ctx.trace, ctx.cfg["retry"]["push_max_attempts"], ctx.cfg["retry"]["push_backoff_seconds"], lambda: _reconcile_for_retry(ctx, root, people), ctx.sleeper)
        result["commits"].append(("state", sha, verdict[0]))
        if verdict[0] != "pushed":
            ctx.alarm("не удалось запушить состояние прогона (%s)" % verdict[0], people)
            result["held"] = result["held"] or (None, "retries_exhausted")
    return result


def _fatal(ctx, outcome, text, people):
    ctx.trace.add(outcome, "run", 10, text)
    ctx.alarm(text, people)
    return {"processed": 0, "outcomes": [(None, outcome)], "held": (None, outcome), "commits": []}


def _reconcile_for_retry(ctx, root, people):
    """Отвергнутый push: fetch+merge; конфликт по файлам состояния — громкий отказ; по спутнику union
    сливает сам; по табелю — Р1 проверяется предикатом (конфликт под union быть не должен)."""
    v = commit_mod.reconcile(root, ctx.trace, author=ctx.cfg.get("bot_handle") or "workshop_bot")
    if v == "clean":
        # наш коммит ничего не добавил к авторитету (параллельный прогон/клон уже записал то же — тождество по
        # якорю и id): дерево HEAD == дерево origin → вернуться к origin, лишних коммитов не оставлять
        branch = commit_mod.git(root, ["rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
        ours = commit_mod.git(root, ["rev-parse", "HEAD^{tree}"])[1].strip()
        theirs = commit_mod.git(root, ["rev-parse", "origin/%s^{tree}" % branch])[1].strip()
        if ours == theirs:
            commit_mod.git(root, ["reset", "-q", "--hard", "origin/%s" % branch], ctx.trace, "reset-to-origin")
        return "retry"
    if v.startswith("p1_unmet:"):
        return "conflict_" + v            # слияния не было — нечего откатывать
    if v.startswith("merge_failed:"):
        commit_mod.abort_merge(root, ctx.trace)
        return v
    paths = v.split(":", 1)[1].split(",")
    if any(p in (ss.SESSIONS_PATH, ss.STATE_PATH) for p in paths):
        commit_mod.abort_merge(root, ctx.trace)
        return "conflict_state_file"
    for p in paths:
        base = _show(root, ":1:" + p); ours = _show(root, ":2:" + p); theirs = _show(root, ":3:" + p)
        ok, why = commit_mod.p1_predicate(base, ours, theirs)
        if not ok:
            commit_mod.abort_merge(root, ctx.trace)
            return "conflict_p1_unmet:" + why
        merged = _p1_resolve(base, ours, theirs)
        with open(os.path.join(root, p), "wb") as fh:
            fh.write(merged)
        commit_mod.git(root, ["add", "--", p], ctx.trace, "add")
    commit_mod.git(root, ["-c", "user.name=%s" % ctx.cfg.get("bot_handle"), "-c", "user.email=%s@bot.invalid" % ctx.cfg.get("bot_handle"), "commit", "-q", "--no-edit"], ctx.trace, "merge-commit")
    return "retry"


def _show(root, spec):
    import subprocess
    r = subprocess.run(["git", "-C", root, "show", spec], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout if r.returncode == 0 else b""   # байты, без текстового пайплайна


def _p1_resolve(base, ours, theirs):
    return base + ours[len(base):] + theirs[len(base):]


def _handle(ctx, u, state, sessions, people_doc, people, result):
    root = ctx.root
    parsed = ctx.registry.parse(u)
    uid = u["update_id"]
    if parsed["kind"] == "non_input":
        ctx.trace.add("non_input", "update:%s" % uid, 0, parsed.get("reason"))
        return "non_input", state, sessions, people_doc, people, False
    if parsed.get("is_callback"):
        try:
            ctx.transport.answer_callback_query(parsed.get("callback_query_id"))
        except tg.TransportError:
            pass
    chat_id = parsed["chat_id"]
    reply_to = None if parsed.get("is_callback") else parsed.get("message_id")
    # --- атрибуция (T4) — ДО разбора исхода: незнакомому не показывается даже справка
    res = identity_mod.resolve(people, parsed["from_id"], parsed.get("from_name"), ctx.cfg)
    note = ""
    if res["kind"] == "rejected":
        addressed = parsed["chat_type"] == "private" or parsed.get("position") not in (None, "free_text") \
            or parsed.get("wrapped_by") or parsed["text"][:1] == b"/"
        state = ss.record_rejection(state, parsed["from_id"], parsed.get("message_date") or 0)
        if addressed:
            ctx.say(chat_id, reply_text(ctx, "rejected_unknown_sender", None, parsed, {"from_id": parsed["from_id"]}), reply_to)
        return "rejected_unknown_sender", state, sessions, people_doc, people, False
    if parsed["kind"] == "unparsed":
        ctx.say(chat_id, reply_text(ctx, "reask_unparsed", {"reply": {"reason": parsed.get("reason")}}, parsed), reply_to)
        return "reask_unparsed", state, sessions, people_doc, people, False
    person = res["person"]
    new_people_doc = people_doc
    if res["kind"] == "pending_new":
        _scrub_pending_name(ctx, res["new_entry"])
        new_people_doc = identity_mod.append_entry(people_doc, res["new_entry"])
        note = "\nзаписал, тебя сверит админ (твой id в мессенджере: %d, временный handle %s)" % (parsed["from_id"], person["handle"])
    # --- скан секретов (T4) — до записи; подтверждение только после находки того же отправителя
    if parsed["position"] not in ("help", "last"):
        scan_text = parsed["text"]
        if parsed.get("confirmed"):
            inner = parsed.get("confirm_inner_text", parsed["text"])
            if secrets_mod.confirmation_allowed(state.get("secret_rejections"), inner, parsed["from_id"]):
                scan_text = None
            else:
                scan_text = inner
        if scan_text is not None:
            findings = secrets_mod.scan(ctx.patterns, scan_text)
            if findings:
                state = ss.record_secret_rejection(state, secrets_mod.rejection_record(scan_text, parsed["from_id"], parsed.get("message_date") or 0))
                ctx.say(chat_id, reply_text(ctx, "rejected_secret", None, parsed, {"names": ", ".join("%s (%s)" % (f["name"], f.get("describe", "")) for f in findings)}), reply_to)
                return "rejected_secret", state, sessions, people_doc, people, False
    # --- машина состояний (T2)
    handle = person["handle"]
    tz = person["timezone"]
    last_titles = None
    if parsed["position"] in ("last", "start_n"):
        n = parsed.get("n") or int(ctx.cfg.get("last_default_n", 5))
        last_titles = lastn.titles(root, handle, max(n, 1) if parsed["position"] == "last" else 10 ** 6, ctx.cfg.get("namespace"))
    d = session_mod.decide(sessions["sessions"].get(handle), parsed, {"handle": handle, "timezone": tz}, ctx.cfg, last_titles, tail_of=ctx.registry.tail_of)
    outcome = d["outcome"]
    if outcome not in RECORD_OUTCOMES:
        if outcome == "last_list_given":
            ctx.transport.send_message(chat_id, reply_text(ctx, outcome, d, parsed), reply_markup=last_keyboard(ctx, d["reply"].get("titles") or []), reply_to_message_id=reply_to)
            ctx.outgoing.append((chat_id, "last_list"))
        elif outcome == "identical_repeat":
            ctx.trace.add("identical", "update:%s" % uid, 0, d["reply"].get("reason"))
        else:
            ctx.say(chat_id, reply_text(ctx, outcome, d, parsed), reply_to)
        return outcome, state, sessions, people_doc, people, False
    # --- ПИШУЩИЙ ИСХОД: pull непосредственно перед коммитом → перечитать → пересчитать
    v = commit_mod.reconcile(root, ctx.trace, author=ctx.cfg.get("bot_handle") or "workshop_bot")
    if v != "clean":
        if not v.startswith("p1_unmet:"):
            commit_mod.abort_merge(root, ctx.trace)
        ctx.say(chat_id, "конфликт при слиянии перед записью — запись отложена, сообщение не потеряно", reply_to)
        ctx.alarm("конфликт слияния перед записью: %s" % v, people)
        return "conflict_p1_unmet", state, sessions, people_doc, people, True
    ctx.trace.add("pull", "reconcile", 0)
    # `-merge` защищает файлы состояния только от ДВУСТОРОННЕЙ правки (конфликт → громкий отказ выше).
    # ОДНОСТОРОННЮЮ чужую правку (только в origin; локально файл с момента снимка не менялся, потому что
    # поллер пишет состояние лишь после reconcile) git сливает тривиально — поэтому после чистого reconcile
    # файлы состояния сравниваются со снимком, и если они приехали изменёнными: ПЕРЕЧИТАТЬ → слить ДЕЛЬТУ
    # этого батча (не снимок — иначе теряется telemetry) → ПЕРЕСЧИТАТЬ решение (глава 02 §0Б; верификатор
    # приёмки Fable, BLOCKER-1). Ни один факт с авторитета не теряется; мутация к записи, которой на
    # авторитете уже нет, не применяется.
    if _read_bytes(root, ss.SESSIONS_PATH) != ctx.base["sessions"] or _read_bytes(root, ss.STATE_PATH) != ctx.base["state"]:
        ctx.trace.add("reread", "state files", 0, "односторонняя чужая правка приехала в reconcile — перечитано, решение пересчитано")
        state = _merge_state_after_remote_change(ctx.base["state_doc"], state, ss.read_state(root))
        sessions = ss.read_sessions(root)
        _snapshot_base(ctx, root, state)
        if parsed["position"] in ("last", "start_n"):
            last_titles = lastn.titles(root, handle, 10 ** 6, ctx.cfg.get("namespace"))
        d = session_mod.decide(sessions["sessions"].get(handle), parsed, {"handle": handle, "timezone": tz}, ctx.cfg, last_titles, tail_of=ctx.registry.tail_of)
        outcome = d["outcome"]
        if outcome not in RECORD_OUTCOMES:   # например, чужое закрытие приехало — наше закрытие стало переспросом
            if outcome != "identical_repeat":
                ctx.say(chat_id, reply_text(ctx, outcome, d, parsed), reply_to)
            return outcome, state, sessions, people_doc, people, False
    # Карта людей union'ом НЕ покрыта и могла приехать 3-way merge'ом — её перечитываем и переминчиваем pending.
    people, people_doc = load_people(ctx)
    new_people_doc = people_doc
    if res["kind"] == "pending_new":
        res = identity_mod.resolve(people, parsed["from_id"], parsed.get("from_name"), ctx.cfg)  # карта могла приехать в merge
        person = res["person"]; handle = person["handle"]; tz = person["timezone"]
        if res["kind"] == "pending_new":
            _scrub_pending_name(ctx, res["new_entry"])
            new_people_doc = identity_mod.append_entry(people_doc, res["new_entry"])
    # --- запись файлов
    paths = []
    rule = None
    if d["lines"]:
        pre_exists = {}
        for l in d["lines"]:
            rel0 = line_mod.route(l["date"], handle, ctx.cfg.get("namespace"))
            pre_exists[rel0] = os.path.exists(os.path.join(root, rel0))
        seen_rel = set()
        written, lines_written, blocks = commit_mod.write_line_and_comments(root, d["lines"], d["comments"], handle, tz, ctx.cfg.get("bot_handle"), ctx.cfg.get("namespace"), ctx.trace, ctx.mint_id)
        paths += written
        # валидатор ДО коммита: check_line на каждой строке (цель — файл БЕЗ этой строки), check_pair на каждой паре
        for rel, full, cid, k, a8 in lines_written:
            target = os.path.join(root, rel)
            data = open(target, "rb").read()
            prev = data[: data.rfind((full + "\n").encode("utf-8"))]
            tmp = target + ".prev"
            open(tmp, "wb").write(prev)
            present = pre_exists.get(rel, True) or rel in seen_rel   # первая строка в ленивом контейнере — target-absent
            seen_rel.add(rel)
            rc, rep = line_mod.check_line_rc(ctx.validator_bin, full, rel, tmp if present else None)
            os.remove(tmp)
            ctx.trace.add("check_line", rel, rc)
            oc, rl = line_mod.rc_to_outcome(rc, rep)
            if oc == "recorded_with_warning":
                rule = rl
            elif oc != "recorded":
                _revert(root, paths, ctx)
                if oc == "reask_invalid":
                    ctx.say(chat_id, reply_text(ctx, "reask_invalid", d, parsed, {"rule": rl}), reply_to)
                    return "reask_invalid", state, sessions, people_doc, people, False
                ctx.alarm("валидатор: %s (rc=%d) на %s" % (oc, rc, rel), people)
                return oc, state, sessions, people_doc, people, True
        for srel, block, cid in blocks:
            host = srel[:-len(".comments.md")] + ".md"
            args = ["check-pair", os.path.join(root, host), "--comments", os.path.join(root, srel), "--path", host, "--comments-path", srel, "--git-root", root, "--no-config"]
            rc, rep = _run_validator(ctx.validator_bin, args)
            ctx.trace.add("check_pair", srel, rc)
            oc, rl = line_mod.rc_to_outcome(rc, rep)
            if oc == "recorded_with_warning":
                rule = rule or rl
            elif oc != "recorded":
                _revert(root, paths, ctx)
                if oc == "reask_invalid":
                    ctx.say(chat_id, reply_text(ctx, "reask_invalid", d, parsed, {"rule": rl}), reply_to)
                    return "reask_invalid", state, sessions, people_doc, people, False
                ctx.alarm("валидатор (check_pair): %s rc=%d на %s" % (oc, rc, srel), people)
                return oc, state, sessions, people_doc, people, True
        if not lines_written:   # все строки тождественны — правило Т
            return "identical_repeat", state, sessions, people_doc, people, False
    # состояние учёта, карта людей, offset — тем же коммитом
    if d["new_record"] is None:
        sessions = ss.close_session(sessions, handle)
    elif d["new_record"] != session_mod.UNCHANGED:
        sessions = ss.open_session(sessions, handle, d["new_record"])
    ss.write_sessions(root, sessions); paths.append(ss.SESSIONS_PATH)
    if new_people_doc is not people_doc:
        with open(ctx.people_path, "wb") as fh:
            fh.write(yamlmini.dumps(new_people_doc).encode("utf-8"))
        paths.append(".workshop/people.yaml"); people_doc = new_people_doc; people = identity_mod.people_list(people_doc)
        state = ss.record_self_registration(state, handle, parsed.get("message_date") or 0)
    state = ss.set_offset(state, uid + 1)
    ss.write_state(root, state); paths.append(ss.STATE_PATH)
    env = dict(os.environ)
    if parsed.get("confirmed"):
        # обход хука — ТОЛЬКО для этого коммита (env одного subprocess) и только по именам находок подтверждённого текста
        inner = parsed.get("confirm_inner_text", parsed["text"])
        env["WORKSHOP_SECRET_CONFIRMED"] = ",".join(sorted(f["name"] for f in secrets_mod.scan(ctx.patterns, inner))) or "-"
    sha = commit_mod.commit_paths(root, sorted(set(paths)), "workshop-bot: %s (update %s)" % (outcome, uid), ctx.cfg.get("bot_handle"), ctx.cfg.get("bot_handle") + "@bot.invalid", ctx.trace, env=env)
    _snapshot_base(ctx, root, state)
    result["commits"].append((outcome, sha, "local"))
    verdict = commit_mod.push_with_retry(root, ctx.trace, ctx.cfg["retry"]["push_max_attempts"], ctx.cfg["retry"]["push_backoff_seconds"], lambda: _reconcile_for_retry(ctx, root, people), ctx.sleeper)
    if verdict[0] == "pushed":
        final = "recorded_with_warning" if (rule and outcome == "recorded") else outcome
        ctx.say(chat_id, reply_text(ctx, final, d, parsed, {"rule": rule, "note": note}), reply_to)
        result["commits"][-1] = (outcome, sha, "pushed")
        return final, state, sessions, people_doc, people, False
    if verdict[0] == "exhausted":
        ctx.say(chat_id, "запись закоммичена, но не запушена после %d попыток — повторю в следующем прогоне, сообщение не потеряно" % verdict[1], reply_to)
        ctx.alarm("исчерпан предел ретраев push (%d попыток, бэкофф суммарно %d с)" % (verdict[1], verdict[2]), people)
        # в память возвращается состояние С ДИСКА (локальный коммит): продвинутый offset живёт только в незапушенном
        # коммите и в конце батча НЕ коммитится отдельно — авторитет (origin) offset не получил
        return "retries_exhausted", ss.read_state(root), ss.read_sessions(root), people_doc, people, True
    # громкий отказ: локальный коммит НЕ пушится и НЕ доживает до следующего прогона — рабочая копия
    # возвращается к авторитету (origin), offset авторитета не продвинут, сообщение придёт снова
    branch = commit_mod.git(root, ["rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    commit_mod.git(root, ["reset", "-q", "--hard", "origin/%s" % branch], ctx.trace, "reset-to-origin")
    ctx.say(chat_id, "конфликт в файле состояния или табеле при слиянии — запись отложена, ветка не тронута, сообщение не потеряно", reply_to)
    ctx.alarm("громкий отказ при reconcile: %s" % verdict[2], people)
    people, people_doc = load_people(ctx)
    return "conflict_p1_unmet", ss.read_state(root), ss.read_sessions(root), people_doc, people, True


def _scrub_pending_name(ctx, entry):
    """Второй источник байтов в репозиторий — имя из мессенджера (T4 §3(а)): сканируется тем же реестром;
    находка → в карту идёт временный handle вместо имени (значение не печатается и не пишется)."""
    if secrets_mod.scan(ctx.patterns, str(entry.get("name", "")).encode("utf-8")):
        entry["name"] = entry["handle"]


def _run_validator(bin_path, args):
    import subprocess
    try:
        r = subprocess.run([bin_path] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        return 127, str(e)
    rc = r.returncode if r.returncode >= 0 else 128 - r.returncode
    return rc, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def _revert(root, paths, ctx):
    for p in paths:
        rc, out, err = commit_mod.git(root, ["checkout", "-q", "--", p], check=False)
        if rc != 0 and os.path.exists(os.path.join(root, p)):
            os.remove(os.path.join(root, p))
    ctx.trace.add("revert", ",".join(paths), 0)


# -------------------------------------------------------------------- вход обёртки
def main():
    root = os.getcwd()
    cfg = yamlmini.load_file(os.path.join(root, ".workshop", "bot.yaml"))
    token = os.environ.get("WORKSHOP_TG_BOT_TOKEN", "")
    validator_bin = os.environ.get("WORKSHOP_VALIDATOR") or os.path.join(root, ".workshop-bin", "workshop-validator")
    tr = cfg.get("transport") or {}
    transport = tg.Transport(token, tr.get("http_timeout_seconds"))
    try:
        me = transport.call("getMe", {})
        username = me.get("username")
    except tg.TransportError as e:
        sys.stdout.write("TOOL_FAILURE getMe: %s\n" % e)
        return 10
    ctx = Ctx(root, transport, cfg, validator_bin, bot_username=username)
    try:
        result = run_once(ctx)
    except (ss.StateError, commit_mod.GitError, yamlmini.YamlError, OSError, ValueError) as e:  # ValueError — форма карты людей
        sys.stdout.write("TOOL_FAILURE %s\n" % e)
        return 10
    sys.stdout.write("\n".join(ctx.trace.lines()) + "\n")
    sys.stdout.write("processed=%d outcomes=%s held=%s\n" % (result["processed"], result["outcomes"], result["held"]))
    return 2 if result["held"] else 0


if __name__ == "__main__":
    sys.exit(main())
