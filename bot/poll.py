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
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
import yamlmini, tg, parse as parse_mod, session as session_mod, lastn, line as line_mod, identity as identity_mod  # noqa: E402
import secrets as secrets_mod, state_store as ss, commit as commit_mod, build_help  # noqa: E402
import comment as comment_mod  # noqa: E402 — раскладка UUIDv7 одна (id контейнера при ленивом создании)
import undo as undo_mod  # noqa: E402 — T8: отзыв своей строки / возврат (правило Т, выбор цели, чётность)

HOLD_OUTCOMES = ("conflict_p1_unmet", "retries_exhausted", "run_refused", "tool_failure")
RECORD_OUTCOMES = ("recorded", "recorded_with_warning", "session_opened", "session_closed_recorded")
UNDO_OUTCOMES = ("retracted", "unretracted")   # T8: пишущие исходы без дневной строки (блок в спутник)
SHORT_REPLY_MAX = 160                          # T8 (REQ-095): переспрос — одна строка не длиннее этого
TG_TEXT_MAX = 4096                             # предел одного сообщения мессенджера (Bot API); длиннее — частями


def _chunks(text, limit):
    """Части ≤ limit символов, по границам строк, где возможно; без пустых частей."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                out.append(cur); cur = ""
            out.append(line[:limit]); line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            out.append(cur); cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        out.append(cur)
    return out
def _one_line(text):
    """Репертуар «одной строки» = границы str.splitlines() (LF, CR, CRLF, VT, FF, FS, GS, RS, NEL, LS, PS) — тот же предикат,
    которым однострочность и проверяется (раунд 7 W1, раунд 8 W1: ручной список расходился с предикатом); серии границ →
    один пробел; хранимые байты не трогаются."""
    return " ".join(part for part in text.splitlines() if part != "") if text.splitlines() else text


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
    def say(self, chat_id, text, reply_to=None, reply_markup=None):
        """Ответ в чат (раунд 7 Fable, B2): текст длиннее предела мессенджера режется на части по строкам; недоставленный
        ответ (бот заблокирован, чат недоступен, сеть) НЕ становится сбоем инструмента — исход update стоит, offset
        продвигается, отказ пишется в трассу и журнал (иначе один заблокировавший бота человек останавливает всех)."""
        self.outgoing.append((chat_id, text))
        parts = _chunks(text, TG_TEXT_MAX)
        for k, part in enumerate(parts):
            try:
                self.transport.send_message(chat_id, part, reply_to_message_id=reply_to if k == 0 else None,
                                            reply_markup=reply_markup if k == len(parts) - 1 else None)
                self.trace.add("send", "chat:%s" % chat_id, 0)
            except tg.TransportError as e:
                self.trace.add("send_failed", "chat:%s" % chat_id, 0, str(e)[:120])
                self.log.append("ответ недоставлен %s: %s" % (chat_id, e))
                return

    def alarm(self, text, people):
        for t in identity_mod.alarm_targets(people, (self.cfg.get("watchdog") or {}).get("alarm_to", "admins")):
            try:
                self.say(t, "⚠ сторож бота: " + text)
            except tg.TransportError as e:
                self.log.append("alarm недоставлен %s: %s" % (t, e))

    def short_help(self):
        return build_help.render_short(self.commands_doc)

    def full_help(self):
        return build_help.render_help(self.commands_doc, self.forms_doc)

    @property
    def forms_doc(self):
        if not hasattr(self, "_forms_doc"):
            self._forms_doc = build_help.load_forms(os.path.join(_HERE, "kit", "duration-forms.yaml"))
        return self._forms_doc

    def help_hint(self):
        """Однострочный указатель на справку (T8, REQ-095): токен позиции справки — из реестра."""
        return "%s — команды и примеры" % build_help.help_token(self.commands_doc)


def load_people(ctx):
    return identity_mod.people_list(yamlmini.load_file(ctx.people_path)), yamlmini.load_file(ctx.people_path)


def token_of(ctx, pos_id):
    return ctx.registry.by_id[pos_id]["token"]


# -------------------------------------------------------------------- ответы (T3 — тексты)
def _states_line():
    return "принято мессенджером ✓ · закоммичено ✓ · запушено ✓"


def _short(parts, tail=""):
    """Переспрос — одна строка ≤ SHORT_REPLY_MAX (T8, REQ-095). parts — строка либо список сегментов: str
    (фиксированный) или (str, True) (переменный: причина/правило/заголовок). Бюджет обрезания — ТОЛЬКО на
    переменных сегментах (раунд 1 №2, раунд 2 W2: фиксированные части ПОСЛЕ переменной — время начала,
    подсказка закрытия, «поправь и пришли снова» — обязаны уцелеть), хвост-указатель на справку цел;
    обрезанное помечается «…»; LF → пробел."""
    if isinstance(parts, str):
        parts = [parts]
    segs = [(p[0], True) if isinstance(p, tuple) else (p, False) for p in parts]
    segs = [(_one_line(t), v) for t, v in segs]
    tail = _one_line(tail)
    room = SHORT_REPLY_MAX - (len(tail) + 1 if tail else 0) - sum(len(t) for t, v in segs if not v)
    if room < 0:
        # контракт шаблона (раунд 3, R2): фиксированные части + хвост ОБЯЗАНЫ умещаться — это ошибка автора
        # шаблона, а не входа; фиксированный текст никогда не режется
        raise ValueError("шаблон переспроса длиннее SHORT_REPLY_MAX на %d: %r" % (-room, "".join(t for t, _ in segs)))
    n_var = sum(1 for _, v in segs if v)
    out = []
    for t, v in segs:
        if not v:
            out.append(t); continue
        share = room // n_var
        if len(t) > share:
            t = (t[:share - 1] + "…") if share >= 1 else ""     # нулевой бюджет — переменная опускается, без «…»
        room -= len(t); n_var -= 1
        out.append(t)
    body = "".join(out)
    return (body + " " + tail) if tail else body


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
    # --- переспросы (T8, REQ-095): ОДНА строка ≤ SHORT_REPLY_MAX — причина + указатель на справку, без перечня команд
    if outcome == "reask_unparsed":
        return _short(["не понял (", (r.get("reason", ""), True), ")."], ctx.help_hint())
    if outcome == "reask_invalid":
        return _short(["не записал: валидатор отверг строку — правило ", (extra.get("rule", r.get("rule", "")) or "", True), ". Поправь и пришли снова."], ctx.help_hint())
    if outcome == "reask_correction":
        return _short("часы на месте бот не правит: отозвать строку — %s, поправить — в приложении. Не записано." % token_of(ctx, "undo"), ctx.help_hint())
    if outcome == "reask_start_already_open":
        return _short(["учёт уже открыт: «", (r.get("title") or "", True), "» с %s. Закрыть — %s." % (r.get("started_at_local"), token_of(ctx, "stop"))], ctx.help_hint())
    if outcome == "reask_stop_without_open":
        return _short("открытого учёта нет.", ctx.help_hint())
    if outcome == "reask_undo_not_found":
        return _short(["нечего отзывать (", (r.get("reason", ""), True), ")."], ctx.help_hint())
    if outcome == "retracted":
        return "отозвано: %s · %s ч · «%s» — %s" % (r.get("date", ""), r.get("hours", ""), r.get("title", ""), _states_line())
    if outcome == "unretracted":
        return "возвращено в учёт: %s · %s ч · «%s» — %s" % (r.get("date", ""), r.get("hours", ""), r.get("title", ""), _states_line())
    if outcome == "rejected_unknown_sender":
        return "тебя нет в карте людей (твой id в мессенджере: %s) — попроси администратора добавить тебя." % extra.get("from_id")
    if outcome == "rejected_secret":
        return "в сообщении есть похожее на секрет: %s. Не записал. Если это не секрет — пришли то же сообщение с префиксом %s" % (extra.get("names"), ctx.registry.confirm_prefix)
    if outcome == "help_given":
        return ctx.full_help()
    if outcome == "last_list_given":
        titles = r.get("titles") or []
        marks = r.get("retracted") or []
        if not titles:
            return "записей пока нет."
        rows = ["%d. %s%s" % (i + 1, t, " — отозвано" if i < len(marks) and marks[i] else "") for i, t in enumerate(titles)]
        return "последние заголовки:\n" + "\n".join(rows) + "\nповторить: %s <N>; отозвать/вернуть: %s <N>" % (token_of(ctx, "start_n"), token_of(ctx, "undo"))
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
    # чтения свежие (раунд 9 T8, Fable-2 B1: чужой отзыв невидим списку до ближайшей записи): если локальная копия не
    # ушла вперёд origin (нет незапушенного коммита), она fast-forward'ится до origin ДО обработки батча; незапушенный
    # коммит (исчерпание ретраев) не трогается — его сольёт reconcile перед записью
    if commit_mod.git(root, ["rev-parse", "--verify", "-q", "origin/%s" % branch], check=False)[0] == 0 and \
            commit_mod.git(root, ["merge-base", "--is-ancestor", "HEAD", "origin/%s" % branch], check=False)[0] == 0:
        commit_mod.git(root, ["merge", "-q", "--ff-only", "origin/%s" % branch], ctx.trace, "ff", check=False)
        state = ss.read_state(root)
        sessions = ss.read_sessions(root)
        people, people_doc = load_people(ctx)
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
    # T8 (REQ-095) ГРУППА: реплика не адресована боту, не команда и не разобрана → это не вход бота
    # (исход 9 non_input, запись в трассу, ответа нет). С privacy-mode такие update не приходят вовсе;
    # при выключенном (бот-админ — вне поддержки) правило делает поведение одинаковым.
    if parsed["chat_type"] != "private" and parsed["kind"] in ("unparsed", "correction") and not parsed.get("addressed") and parsed["text"][:1] != b"/":
        ctx.trace.add("non_input", "update:%s" % uid, 0, "группа: не адресовано боту (%s)" % parsed.get("reason"))
        return "non_input", state, sessions, people_doc, people, False
    if parsed["kind"] == "unparsed":
        ctx.say(chat_id, reply_text(ctx, "reask_unparsed", {"reply": {"reason": parsed.get("reason")}}, parsed), reply_to)
        return "reask_unparsed", state, sessions, people_doc, people, False
    if parsed["kind"] == "correction":   # T8: исход 6 получил продюсера — маркеры исправления реестра форм
        ctx.say(chat_id, reply_text(ctx, "reask_correction", {"reply": {"reason": parsed.get("reason")}}, parsed), reply_to)
        return "reask_correction", state, sessions, people_doc, people, False
    # --- гейты кнопки — ДО ЛЮБОЙ диспетчеризации (раунд 7 Fable, B1: отзыв кнопкой миновал гейт машины состояний и
    #     падал в TOOL_FAILURE с застрявшим offset); П-6: у нажатия нет времени; callback_allowed — реестр команд
    if parsed.get("is_callback") and parsed.get("time_bearing"):
        ctx.say(chat_id, reply_text(ctx, "reask_unparsed", {"reply": {"reason": "callback_time_bearing"}}, parsed), reply_to)
        return "reask_unparsed", state, sessions, people_doc, people, False
    if parsed.get("is_callback") and not parsed.get("callback_allowed"):
        ctx.say(chat_id, reply_text(ctx, "reask_unparsed", {"reply": {"reason": "callback_not_allowed"}}, parsed), reply_to)
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
    # --- отзыв своей строки (T8): собственный пишущий путь без дневной строки
    if parsed["position"] == "undo":
        return _handle_undo(ctx, parsed, uid, person, res, state, sessions, people_doc, people, result, reply_to, note)
    # --- машина состояний (T2)
    handle = person["handle"]
    tz = person["timezone"]
    last_titles = None
    if parsed["position"] in ("last", "start_n"):
        n = min(parsed.get("n") or int(ctx.cfg.get("last_default_n", 5)), int(ctx.cfg.get("last_max_n", 50)))   # раунд 7 B2: предел списка
        # список для повтора по N — ТОТ ЖЕ предел last_max_n, что у показа: номер, которого человек увидеть не мог,
        # не адресует строку (раунд 8 T8, Fable W1)
        last_titles = lastn.titles(root, handle, max(n, 1) if parsed["position"] == "last" else int(ctx.cfg.get("last_max_n", 50)), ctx.cfg.get("namespace"))
    d = session_mod.decide(sessions["sessions"].get(handle), parsed, {"handle": handle, "timezone": tz}, ctx.cfg, last_titles, tail_of=ctx.registry.tail_of)
    outcome = d["outcome"]
    if outcome not in RECORD_OUTCOMES:
        if outcome == "last_list_given":
            # T8: заголовки, чья новейшая строка отозвана, помечаются в ответе (текст заголовка не меняется)
            d["reply"]["retracted"] = undo_mod.titles_state(root, handle, d["reply"].get("titles") or [], ctx.cfg.get("namespace"))
            ctx.say(chat_id, reply_text(ctx, outcome, d, parsed), reply_to, reply_markup=last_keyboard(ctx, d["reply"].get("titles") or []))
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
            last_titles = lastn.titles(root, handle, int(ctx.cfg.get("last_max_n", 50)), ctx.cfg.get("namespace"))
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


def _handle_undo(ctx, parsed, uid, person, res, state, sessions, people_doc, people, result, reply_to, note):
    """T8 — отзыв/возврат своей строки: правило Т → выбор цели → reconcile → пересчёт цели при чужой
    правке спутника/контейнера → блок(и) в спутник → check-pair → ОДИН коммит (спутник + состояние +
    карта людей при самозаписи) → push → ответ. Дневная строка не пишется и не правится."""
    root = ctx.root
    chat_id = parsed["chat_id"]
    handle = person["handle"]
    ns = ctx.cfg.get("namespace")
    ident = parsed["identity"]
    # 1. ПРАВИЛО Т — до выбора цели (ревью #2): повтор доставки после незапушенного/запушенного коммита
    if undo_mod.already_applied(root, handle, ident, ns):
        ctx.trace.add("identical", "update:%s" % uid, 0, "правило Т для отзыва: коммент этого сообщения уже в спутнике")
        return "identical_repeat", state, sessions, people_doc, people, False
    # 2. цель — один ключ порядка (lastn); по N — заголовок последнего списка
    n = parsed.get("n")
    last_titles = lastn.titles(root, handle, int(ctx.cfg.get("last_max_n", 50)), ns) if n is not None else None   # предел = предел показа (раунд 8, W1)
    kind, target = undo_mod.select_target(root, handle, n, last_titles, ns)
    if kind == "reask":
        ctx.say(chat_id, reply_text(ctx, "reask_undo_not_found", {"reply": {"reason": target}}, parsed), reply_to)
        return "reask_undo_not_found", state, sessions, people_doc, people, False
    snap = undo_mod.snapshot(root, handle, ns)   # ВСЕ свои контейнеры и спутники (раунд 1, №7)
    # 3. pull непосредственно перед коммитом; чужая правка файлов состояния — перечитать (как в _handle)
    v = commit_mod.reconcile(root, ctx.trace, author=ctx.cfg.get("bot_handle") or "workshop_bot")
    if v != "clean":
        if not v.startswith("p1_unmet:"):
            commit_mod.abort_merge(root, ctx.trace)
        ctx.say(chat_id, "конфликт при слиянии перед записью — отзыв отложен, сообщение не потеряно", reply_to)
        ctx.alarm("конфликт слияния перед отзывом: %s" % v, people)
        return "conflict_p1_unmet", state, sessions, people_doc, people, True
    ctx.trace.add("pull", "reconcile", 0)
    if _read_bytes(root, ss.SESSIONS_PATH) != ctx.base["sessions"] or _read_bytes(root, ss.STATE_PATH) != ctx.base["state"]:
        ctx.trace.add("reread", "state files", 0, "односторонняя чужая правка приехала в reconcile — перечитано")
        state = _merge_state_after_remote_change(ctx.base["state_doc"], state, ss.read_state(root))
        sessions = ss.read_sessions(root)
        _snapshot_base(ctx, root, state)
    # 4. чужая правка своих файлов приехала в reconcile → цель проверяется ПО ЯКОРЮ (раунд 1, №4): состояние
    #    цели изменилось (отозвана/возвращена/исчезла) — исход 23 target_changed, записи нет; то же — при
    #    повторе доставки, чей коммент приехал (правило Т)
    if undo_mod.snapshot(root, handle, ns) != snap:
        ctx.trace.add("reread", "own files", 0, "контейнеры/спутники изменились в reconcile — цель отзыва проверена по якорю")
        if undo_mod.already_applied(root, handle, ident, ns):
            return "identical_repeat", state, sessions, people_doc, people, False
        found, retracted, rets = undo_mod.anchor_state(root, handle, target["anchor"], ns)
        # состояние цели — якорь, отозванность и МНОЖЕСТВО действующих отзывов (раунд 5, W4: законная перестановка
        # блоков спутника состояние не меняет; порядок блоков не семантичен — гл. 01 §9 п.3)
        if not found or retracted != target["retracted"] or set(rets) != set(target["retractions"]):
            ctx.say(chat_id, reply_text(ctx, "reask_undo_not_found", {"reply": {"reason": "target_changed"}}, parsed), reply_to)
            return "reask_undo_not_found", state, sessions, people_doc, people, False
    people, people_doc = load_people(ctx)
    new_people_doc = people_doc
    if res["kind"] == "pending_new":
        res = identity_mod.resolve(people, parsed["from_id"], parsed.get("from_name"), ctx.cfg)
        person = res["person"]; handle = person["handle"]
        if res["kind"] == "pending_new":
            _scrub_pending_name(ctx, res["new_entry"])
            new_people_doc = identity_mod.append_entry(people_doc, res["new_entry"])
    # 5. блок(и) в спутник — тело = ПОЛНЫЕ байты сообщения (ревью #1)
    outcome, blocks = undo_mod.build_blocks(target, ident, parsed["message_date"], parsed["text"], handle)
    host_rel = os.path.relpath(target["path"], root)
    srel = os.path.relpath(undo_mod.sibling_path(target["path"]), root)
    spath = os.path.join(root, srel)
    sb = _read_bytes(root, srel)
    if not sb:
        container_id = commit_mod.container_id_of(_read_bytes(root, host_rel))
        sb = (comment_mod.comments_of_header(container_id) + "\n\n").encode("utf-8")
    elif not sb.endswith(b"\n"):
        sb += b"\n"
    for _p, block, _cid in blocks:
        sb += block
    with open(spath, "wb") as fh:
        fh.write(sb)
    ctx.trace.add("write", srel, 0, "%s: %d блок(ов) %s" % (outcome, len(blocks), target["anchor"]))
    paths = [srel]
    args = ["check-pair", os.path.join(root, host_rel), "--comments", spath, "--path", host_rel, "--comments-path", srel, "--git-root", root, "--no-config"]
    rc, rep = _run_validator(ctx.validator_bin, args)
    ctx.trace.add("check_pair", srel, rc)
    oc, rl = line_mod.rc_to_outcome(rc, rep)
    rule = rl if oc == "recorded_with_warning" else None
    if oc not in ("recorded", "recorded_with_warning"):
        _revert(root, paths, ctx)
        if oc == "reask_invalid":
            ctx.say(chat_id, reply_text(ctx, "reask_invalid", None, parsed, {"rule": rl}), reply_to)
            return "reask_invalid", state, sessions, people_doc, people, False
        ctx.alarm("валидатор (check_pair, отзыв): %s rc=%d на %s" % (oc, rc, srel), people)
        return oc, state, sessions, people_doc, people, True
    # 6. состояние, карта людей, offset — тем же коммитом
    if new_people_doc is not people_doc:
        with open(ctx.people_path, "wb") as fh:
            fh.write(yamlmini.dumps(new_people_doc).encode("utf-8"))
        paths.append(".workshop/people.yaml"); people_doc = new_people_doc; people = identity_mod.people_list(people_doc)
        state = ss.record_self_registration(state, handle, parsed.get("message_date") or 0)
    state = ss.set_offset(state, uid + 1)
    ss.write_state(root, state); paths.append(ss.STATE_PATH)
    env = dict(os.environ)
    if parsed.get("confirmed"):
        inner = parsed.get("confirm_inner_text", parsed["text"])
        env["WORKSHOP_SECRET_CONFIRMED"] = ",".join(sorted(f["name"] for f in secrets_mod.scan(ctx.patterns, inner))) or "-"
    sha = commit_mod.commit_paths(root, sorted(set(paths)), "workshop-bot: %s (update %s)" % (outcome, uid), ctx.cfg.get("bot_handle"), ctx.cfg.get("bot_handle") + "@bot.invalid", ctx.trace, env=env)
    _snapshot_base(ctx, root, state)
    result["commits"].append((outcome, sha, "local"))
    verdict = commit_mod.push_with_retry(root, ctx.trace, ctx.cfg["retry"]["push_max_attempts"], ctx.cfg["retry"]["push_backoff_seconds"], lambda: _reconcile_for_retry(ctx, root, people), ctx.sleeper)
    reply = {"reply": {"date": target["date"], "hours": target["hours"], "title": target["title"]}}
    if verdict[0] == "pushed":
        ctx.say(chat_id, reply_text(ctx, outcome, reply, parsed, {"rule": rule, "note": note}) + (("\nпредупреждение валидатора: %s" % rule) if rule else ""), reply_to)
        result["commits"][-1] = (outcome, sha, "pushed")
        return outcome, state, sessions, people_doc, people, False
    if verdict[0] == "exhausted":
        ctx.say(chat_id, "отзыв закоммичен, но не запушен после %d попыток — повторю в следующем прогоне, сообщение не потеряно" % verdict[1], reply_to)
        ctx.alarm("исчерпан предел ретраев push (%d попыток, бэкофф суммарно %d с)" % (verdict[1], verdict[2]), people)
        return "retries_exhausted", ss.read_state(root), ss.read_sessions(root), people_doc, people, True
    branch = commit_mod.git(root, ["rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    commit_mod.git(root, ["reset", "-q", "--hard", "origin/%s" % branch], ctx.trace, "reset-to-origin")
    ctx.say(chat_id, "конфликт при слиянии — отзыв отложен, ветка не тронута, сообщение не потеряно", reply_to)
    ctx.alarm("громкий отказ при reconcile (отзыв): %s" % verdict[2], people)
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
def _emergency_alarm(transport, cfg, people, text):
    """Аварийный алярм без Ctx (раунд 4 W1, раунд 5 W1): адресаты — по карте людей (прочитана заранее) либо по явному
    watchdog.alarm_to; нужен только транспорт. Контур ЗАМКНУТ относительно собственных ошибок: порченая секция
    watchdog (строка/список/число) → адресаты «admins»; любой сбой подготовки или отправки печатается, наружу не выходит."""
    try:
        wd = cfg.get("watchdog") if isinstance(cfg, dict) else None
        alarm_to = wd.get("alarm_to", "admins") if isinstance(wd, dict) else "admins"
        try:
            targets = identity_mod.alarm_targets(people if isinstance(people, list) else [], alarm_to)
        except Exception as e:
            sys.stdout.write("alarm: адресаты не разрешены (%s) — по карте admins\n" % e)
            targets = identity_mod.alarm_targets(people if isinstance(people, list) else [], "admins")
        for t in targets:
            try:
                transport.send_message(t, "⚠ сторож бота: " + text)
            except Exception as e:
                sys.stdout.write("alarm недоставлен %s: %s\n" % (t, e))
    except Exception as e:
        sys.stdout.write("alarm: сбой аварийного контура: %s\n" % e)


def main():
    """Один контур фатальной ошибки (раунд 2 W3, раунд 3 W1/R3, раунд 4 W1): ЛЮБОЕ исключение на любом шаге — конфиг,
    транспорт, getMe, карта, прогон — печатает TOOL_FAILURE <тип>: <текст>, rc=10, offset не продвигается; алярм уходит,
    как только есть транспорт и конфиг (карта людей читается ДО getMe и прогона; без карты — явный адресат)."""
    root = os.getcwd()
    cfg = transport = None
    people = []
    try:
        cfg = yamlmini.load_file(os.path.join(root, ".workshop", "bot.yaml"))
        token = os.environ.get("WORKSHOP_TG_BOT_TOKEN", "")
        validator_bin = os.environ.get("WORKSHOP_VALIDATOR") or os.path.join(root, ".workshop-bin", "workshop-validator")
        tr = cfg.get("transport") or {}
        transport = tg.Transport(token, tr.get("http_timeout_seconds"))
        try:
            people = identity_mod.people_list(yamlmini.load_file(os.path.join(root, ".workshop", "people.yaml")))
        except Exception:
            people = []           # карты нет/порчена — алярм пойдёт по явному адресату, если он есть
        me = transport.call("getMe", {})
        ctx = Ctx(root, transport, cfg, validator_bin, bot_username=me.get("username"))
        result = run_once(ctx)
    except Exception as e:
        sys.stdout.write("TOOL_FAILURE %s: %s\n" % (type(e).__name__, e))
        if transport is not None and cfg is not None:
            _emergency_alarm(transport, cfg, people, "сбой поллера (%s): %s" % (type(e).__name__, str(e)[:200]))
        return 10
    sys.stdout.write("\n".join(ctx.trace.lines()) + "\n")
    sys.stdout.write("processed=%d outcomes=%s held=%s\n" % (result["processed"], result["outcomes"], result["held"]))
    return 2 if result["held"] else 0


if __name__ == "__main__":
    sys.exit(main())
