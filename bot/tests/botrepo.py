# -*- coding: utf-8 -*-
"""Стенд T3: одноразовый «репозиторий заказчика» с bare-origin, раскладкой комплекта и фейковым
транспортом. Оракульный хелпер — НЕ импортирует писателей ради ожиданий: ожидания тестов считаются
из байтов файлов и git-журнала, а не из функций bot/. Использует stdlib + git."""
import os, re, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.abspath(os.path.join(HERE, ".."))
MONO = os.path.abspath(os.path.join(BOT, ".."))
VALIDATOR = os.environ.get("WORKSHOP_VALIDATOR") or os.path.join(MONO, "validator", "target", "release", "workshop-validator")

# Карта людей стенда — ШАБЛОН комплекта как есть (dev-one admin, dev-three, dev-two без мессенджера, бот);
# ids — синтетические значения шаблона (положительный контракт PII test_identity).
ADMIN_ID = 100000001
DEV3_ID = 100000003
UNKNOWN_ID = 100000009
CHAT = -1000000000001


def git(root, *args, check=True, env=None, binary=False):
    r = subprocess.run(["git", "-C", root] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if check and r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")))
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


class Stand(object):
    def __init__(self, self_registration="on"):
        self.tmp = tempfile.mkdtemp(prefix="d09-t3-")
        self.origin = os.path.join(self.tmp, "origin.git")
        self.root = os.path.join(self.tmp, "work")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.root], check=True, stderr=subprocess.DEVNULL)
        git(self.root, "config", "user.name", "seed"); git(self.root, "config", "user.email", "seed@example.invalid")
        git(self.root, "checkout", "-q", "-b", "main")
        ws = os.path.join(self.root, ".workshop")
        os.makedirs(os.path.join(ws, "hooks"))
        shutil.copytree(BOT, os.path.join(ws, "bot"), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        shutil.copy(os.path.join(BOT, "kit", "templates", "gitattributes"), os.path.join(self.root, ".gitattributes"))
        shutil.copy(os.path.join(BOT, "kit", "templates", "bot-sessions.yaml"), os.path.join(ws, "bot-sessions.yaml"))
        with open(os.path.join(BOT, "kit", "templates", "bot.yaml"), encoding="utf-8") as fh:
            cfg = fh.read()
        cfg = cfg.replace("self_registration: on", "self_registration: %s" % self_registration)
        cfg = cfg.replace("push_backoff_seconds: 20", "push_backoff_seconds: 1")
        with open(os.path.join(ws, "bot.yaml"), "w", encoding="utf-8") as fh:
            fh.write(cfg)
        shutil.copy(os.path.join(BOT, "kit", "templates", "people.yaml"), os.path.join(ws, "people.yaml"))
        shutil.copy(os.path.join(BOT, "kit", "hooks", "pre-commit"), os.path.join(ws, "hooks", "pre-commit"))
        os.chmod(os.path.join(ws, "hooks", "pre-commit"), 0o755)
        git(self.root, "config", "core.hooksPath", ".workshop/hooks")
        git(self.root, "add", "-A"); git(self.root, "commit", "-q", "-m", "seed")
        git(self.root, "push", "-q", "-u", "origin", "main")

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- второй писатель (фронт/человек) — отдельный клон
    def other_clone(self):
        path = os.path.join(self.tmp, "other-%d" % len(os.listdir(self.tmp)))
        subprocess.run(["git", "clone", "-q", self.origin, path], check=True, stderr=subprocess.DEVNULL)
        git(path, "config", "user.name", "front"); git(path, "config", "user.email", "front@example.invalid")
        return path

    def commits(self, root=None):
        return git(root or self.root, "rev-list", "--count", "HEAD").strip()

    def origin_head(self):
        return git(self.origin, "rev-parse", "main").strip()

    def head(self):
        return git(self.root, "rev-parse", "HEAD").strip()

    def read(self, rel):
        with open(os.path.join(self.root, rel), "rb") as fh:
            return fh.read()

    def deny_push(self, on=True):
        hook = os.path.join(self.origin, "hooks", "pre-receive")
        if on:
            open(hook, "w").write("#!/bin/sh\necho denied >&2\nexit 1\n"); os.chmod(hook, 0o755)
        elif os.path.exists(hook):
            os.remove(hook)


class FakeTransport(object):
    """Транспорт-двойник: очередь update, журнал исходящих; тот же интерфейс, что tg.Transport."""
    def __init__(self, updates=None):
        self.updates = list(updates or [])
        self.sent = []          # (chat_id, text, reply_markup)
        self.answered = []
        self.calls = []
        self.offsets = []

    def call(self, method, params):
        self.calls.append(method)
        if method == "getMe":
            return {"username": "cp_workshop_test_bot"}
        raise RuntimeError(method)

    def get_updates(self, offset=None, limit=None, timeout_s=None, allowed_updates=None):
        self.calls.append("getUpdates")
        self.offsets.append(offset)          # что поллер ПОДТВЕРДИЛ серверу — предмет предиката порядка подтверждения
        return [u for u in self.updates if offset is None or u["update_id"] >= offset][: (limit or 100)]

    def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, disable_notification=None):
        self.calls.append("sendMessage")
        self.sent.append((chat_id, text, reply_markup))
        return {"message_id": 1}

    def answer_callback_query(self, callback_query_id, text=None, show_alert=None):
        self.calls.append("answerCallbackQuery")
        self.answered.append(callback_query_id)
        return True


def registry_tokens():
    """{id: token} из bot/kit/commands.yaml построчным регэкспом — литералов команд в оракулах нет."""
    tok, cur = {}, None
    for ln in open(os.path.join(BOT, "kit", "commands.yaml"), encoding="utf-8"):
        m = re.match(r"^  - id: (\S+)", ln)
        if m:
            cur = m.group(1); continue
        m = re.match(r'^    token: "(.*)"$', ln)
        if m and cur:
            tok[cur] = m.group(1)
    return tok


TOK = registry_tokens()
_N = [0]


def msg(text, from_id=ADMIN_ID, date=1788790990, chat_id=CHAT, chat_type="supergroup", update_id=None, message_id=None):
    _N[0] += 1
    uid = update_id if update_id is not None else 900000000 + _N[0]
    mid = message_id if message_id is not None else 4000 + _N[0]
    return {"update_id": uid, "message": {"message_id": mid, "date": date, "chat": {"id": chat_id, "type": chat_type},
                                          "from": {"id": from_id, "first_name": "T"}, "text": text}}


def callback(data, from_id=ADMIN_ID, chat_id=CHAT, update_id=None):
    _N[0] += 1
    uid = update_id if update_id is not None else 900000000 + _N[0]
    return {"update_id": uid, "callback_query": {"id": "cq%d" % _N[0], "from": {"id": from_id, "first_name": "T"},
                                                 "message": {"message_id": 3000 + _N[0], "chat": {"id": chat_id, "type": "supergroup"}},
                                                 "data": data}}
