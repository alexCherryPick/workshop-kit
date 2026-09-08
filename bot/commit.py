# -*- coding: utf-8 -*-
"""commit — запись строки и спутника, файла состояния и карты людей ОДНИМ коммитом; pull непосредственно
перед коммитом; push с ретраями и reconcile; предикат Р1; трасса операций. Владелец — T3 (план §0Б–§0Д, §1–§5).

Инварианты, исполняемые здесь (контракт §1Г(д); план §0В):
  * один update-исход, порождающий запись, = РОВНО ОДИН коммит: все строки, все комменты, переход
    состояния и pending-запись карты — вместе;
  * check_line и check_pair зовутся ДО коммита, их rc пишутся в трассу;
  * pull — непосредственно перед коммитом (между записью `pull` и `commit` в трассе нет сетевых
    операций и файловых операций вне целевых файлов);
  * отвергнутый push → fetch+merge (П6; rebase/force запрещены) → ПЕРЕЧИТАТЬ состояние → пересчитать
    решение (callback) → повтор; предел попыток и бэкофф — из bot.yaml; исчерпание — исход 11;
  * конфликт слияния по файлу состояния — громкий отказ (исход 10); по спутнику — union без конфликта.
Трасса: список кортежей (op, target, rc/детали) — единица «одна операция» (контракт §8).
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anchor as anchor_mod  # noqa: E402
import comment as comment_mod  # noqa: E402
import line as line_mod  # noqa: E402

__all__ = ["Trace", "GitError", "git", "reconcile", "write_line_and_comments", "commit_paths", "push_with_retry", "p1_predicate"]


class GitError(Exception):
    def __init__(self, kind, detail):
        Exception.__init__(self, "%s: %s" % (kind, detail))
        self.kind = kind
        self.detail = detail


class Trace(object):
    """Упорядоченный журнал операций поллера."""

    def __init__(self):
        self.ops = []

    def add(self, op, target, rc=None, note=None):
        self.ops.append({"op": op, "target": target, "rc": rc, "note": note})

    def between(self, op_a, op_b):
        """Операции строго между ПОСЛЕДНИМ op_a и ПОСЛЕДНИМ op_b (для предиката «pull → commit»)."""
        ia = max((i for i, o in enumerate(self.ops) if o["op"] == op_a), default=-1)
        ib = max((i for i, o in enumerate(self.ops) if o["op"] == op_b), default=-1)
        if ia < 0 or ib < 0 or ib < ia:
            return None
        return self.ops[ia + 1:ib]

    def lines(self):
        return ["%-12s %-40s rc=%s %s" % (o["op"], o["target"], o["rc"], o["note"] or "") for o in self.ops]


def git(root, args, trace=None, op=None, check=True, env=None):
    r = subprocess.run(["git", "-C", root] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    if trace is not None and op:
        trace.add(op, " ".join(args[:2]), r.returncode)
    if check and r.returncode != 0:
        raise GitError("git " + args[0], err.strip()[:300])
    return r.returncode, out, err


# ------------------------------------------------------------------ Р1 (D04 §2.2)
def p1_predicate(base, ours, theirs):
    """Р1: (а) файл есть в базе; (б) конверт обеих сторон побайтово равен базе; (в) обе стороны — только
    добавленные строки после последней строки базы; (г) ни одна не изменила/удалила строку базы.
    Возвращает (True, None) либо (False, причина)."""
    if base is None:
        return False, "P1(a): файла нет в базе слияния (add/add)"
    def split(b):
        i = b.find(b"\n---\n", 4)
        if not b.startswith(b"---\n") or i < 0:
            return None, None
        return b[:i + 5], b[i + 5:]
    be, bb = split(base)
    if be is None:
        return False, "P1: база без конверта"
    for name, side in (("ours", ours), ("theirs", theirs)):
        se, sb = split(side)
        if se is None or se != be:
            return False, "P1(b): конверт %s отличается от базы" % name
        if not sb.startswith(bb):
            return False, "P1(в/г): %s изменил или удалил строки базы" % name
    return True, None


# ------------------------------------------------------------------ reconcile
def _show_bytes(root, spec):
    r = subprocess.run(["git", "-C", root, "show", spec], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout if r.returncode == 0 else None


def p1_gate(root, remote, branch, trace):
    """Р1 применяется МАШИННО ДО слияния к каждому табелю, изменённому ОБЕИМИ сторонами относительно базы
    слияния (D04 §2.2/§2.3: union молчит о правке конверта — бот обязан не сливать). Возвращает None либо
    'p1_unmet:<путь>:<причина>'. Спутники (*.comments.md) — union без Р1 (законная пара)."""
    theirs_ref = "%s/%s" % (remote, branch)
    base = git(root, ["merge-base", "HEAD", theirs_ref], check=False)[1].strip()
    if not base:
        return None
    ours_changed = set(git(root, ["diff", "--name-only", base, "HEAD"])[1].split("\n")) - {""}
    theirs_changed = set(git(root, ["diff", "--name-only", base, theirs_ref])[1].split("\n")) - {""}
    for path in sorted(ours_changed & theirs_changed):
        if not (path.startswith("time/") and path.endswith(".md") and not path.endswith(".comments.md")):
            continue
        ok, why = p1_predicate(_show_bytes(root, "%s:%s" % (base, path)), _show_bytes(root, "HEAD:%s" % path), _show_bytes(root, "%s:%s" % (theirs_ref, path)))
        trace.add("p1", path, 0 if ok else 1, why)
        if not ok:
            return "p1_unmet:%s:%s" % (path, why)
    return None


def reconcile(root, trace, remote="origin", branch=None, author="workshop_bot"):
    """fetch + гейт Р1 + merge (П6). Возвращает 'clean' | 'conflict:<paths>' | 'p1_unmet:<path>:<why>' |
    'merge_failed:<stderr>'. Force и rebase не используются; при отказе Р1 слияние НЕ выполняется.
    Идентичность merge-коммита задаётся явно (в эфемерном клоне CI user.name/email не настроены)."""
    git(root, ["fetch", "-q", remote], trace, "fetch")
    branch = branch or git(root, ["rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    refused = p1_gate(root, remote, branch, trace)
    if refused:
        return refused
    ident = ["-c", "user.name=%s" % author, "-c", "user.email=%s@bot.invalid" % author]
    rc, out, err = git(root, ident + ["merge", "-q", "--no-edit", "%s/%s" % (remote, branch)], trace, "merge", check=False)
    if rc == 0:
        return "clean"
    conflicted = git(root, ["diff", "--name-only", "--diff-filter=U"])[1].split()
    if conflicted:
        return "conflict:" + ",".join(conflicted)
    return "merge_failed:" + err.strip()[:200]


def abort_merge(root, trace):
    git(root, ["merge", "--abort"], trace, "merge-abort", check=False)


# ------------------------------------------------------------------ запись файлов
def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _ensure_trailing_lf(data):
    return data if data.endswith(b"\n") else data + b"\n"


def write_line_and_comments(root, line_specs, comment_specs, person, tz_name, bot_handle, namespace, trace, mint_id):
    """Дописывает строки в контейнеры (ленивое создание с полным конвертом) и блоки комментов в спутники.
    line_specs — из session.decide (date, seconds, interval, title, k, identity); comment_specs — носители.
    mint_id() — минт UUIDv7 контейнера при создании. Возвращает (written_paths, lines_written[(path, line)],
    comment_blocks[(path, block)]). Якорь — remint по существующим якорям цели; тождество → строка пропускается."""
    written = []
    lines_written = []
    blocks_written = []
    for spec in line_specs:
        rel = line_mod.route(spec["date"], person, namespace)
        path = os.path.join(root, rel)
        exists = os.path.exists(path)
        body = _read_bytes(path) if exists else b""
        env = None
        if not exists:
            env = line_mod.envelope(mint_id(), person, spec["date"], tz_name, bot_handle, spec["date"], namespace)
            container_id = mint_id_from_env(env)
        else:
            container_id = container_id_of(body)
        candidate = line_mod.build_line(spec["date"], spec["seconds"], spec["title"], "00000000", spec["interval"])
        candidate_wo = candidate[: -len(" <!--t:00000000-->")]
        existing = anchor_mod.existing_anchors(body) if exists else {}
        a8, step, identical = anchor_mod.remint(spec["identity"], spec["k"], existing, candidate_wo)
        full = line_mod.build_line(spec["date"], spec["seconds"], spec["title"], a8, spec["interval"])
        if identical:
            trace.add("identical", rel, 0, "правило Т: строка уже в файле")
            continue
        new = (env.encode("utf-8") if env else _ensure_trailing_lf(body)) + full.encode("utf-8") + b"\n"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(new)
        trace.add("write", rel, 0, "line k=%d anchor=%s step=%d" % (spec["k"], a8, step))
        written.append(rel)
        lines_written.append((rel, full, container_id, spec["k"], a8))
        for c in [c for c in comment_specs if c["k"] == spec["k"]]:
            built = comment_mod.build(c["identity"], c["message_date"], c["body"], person, a8, c["k"])
            if built is None:
                continue
            cid, head, block = built
            srel = rel[:-3] + ".comments.md"
            spath = os.path.join(root, srel)
            if os.path.exists(spath):
                sb = _read_bytes(spath)
                if block in sb:
                    trace.add("identical", srel, 0, "правило Т для комментов: блок уже есть")
                    continue
                sb = _ensure_trailing_lf(sb) + block
            else:
                sb = (comment_mod.comments_of_header(container_id) + "\n\n").encode("utf-8") + block
            with open(spath, "wb") as fh:
                fh.write(sb)
            trace.add("write", srel, 0, "comment id=%s k=%d" % (cid, c["k"]))
            if srel not in written:
                written.append(srel)
            blocks_written.append((srel, block, cid))
    return written, lines_written, blocks_written


def container_id_of(body):
    for raw in body.split(b"\n")[:20]:
        if raw.startswith(b"id: "):
            return raw[4:].decode("ascii", "replace").strip()
    return None


def mint_id_from_env(env_text):
    for ln in env_text.split("\n"):
        if ln.startswith("id: "):
            return ln[4:].strip()
    return None


# ------------------------------------------------------------------ коммит и push
def commit_paths(root, paths, message, author_name, author_email, trace, env=None):
    """git add явными путями + один коммит. Возвращает sha либо None, если индекс пуст."""
    if not paths:
        return None
    git(root, ["add", "--"] + list(paths), trace, "add", env=env)
    staged = git(root, ["diff", "--cached", "--name-only"])[1].strip()
    if not staged:
        trace.add("commit", "(nothing)", 0, "индекс пуст")
        return None
    e = dict(os.environ if env is None else env)
    e.update({"GIT_AUTHOR_NAME": author_name, "GIT_AUTHOR_EMAIL": author_email, "GIT_COMMITTER_NAME": author_name, "GIT_COMMITTER_EMAIL": author_email})
    git(root, ["commit", "-q", "-m", message], trace, "commit", env=e)
    return git(root, ["rev-parse", "HEAD"])[1].strip()


def push_with_retry(root, trace, attempts, backoff_seconds, on_rejected, sleeper=time.sleep, remote="origin"):
    """push с пределом попыток; отвергнутый push → on_rejected() (reconcile + перечитать + пересчитать) → повтор.
    Возвращает ('pushed', n) | ('exhausted', n) | ('refused', reason). Суммарное время бэкоффа печатает вызывающий."""
    total = 0
    for n in range(1, int(attempts) + 1):
        rc, out, err = git(root, ["push", "-q", remote, "HEAD"], trace, "push", check=False)
        if rc == 0:
            return "pushed", n, total
        if n == attempts:
            break
        verdict = on_rejected()
        if verdict != "retry":
            return "refused", n, verdict
        wait = int(backoff_seconds[min(n - 1, len(backoff_seconds) - 1)]) if isinstance(backoff_seconds, list) else int(backoff_seconds)
        total += wait
        sleeper(wait)
    return "exhausted", attempts, total
