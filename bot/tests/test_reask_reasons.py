# -*- coding: utf-8 -*-
"""Оракул фраз переспроса (ЭРРАТА D10 «А», заявки В1–В3; контракт §1А(б), §1 №исход-4 и №исход-23).

В1 — ПОЛНОТА. Множество имён причин, которые порождает КОД разбора и отзыва, оракул берёт из самого кода — своим
разбором AST (`ast`), без импорта писателей и без общего хелпера с build_help.py; множество имён реестра — своим
построчным чтением реестра фраз `kit/reask-phrases.yaml` (не yamlmini; позиции, токены и примеры для
подстановок — построчно из `kit/commands.yaml`). По каждому исходу (4 `reask_unparsed`, 23 `reask_undo_not_found`)
множества ОБЯЗАНЫ совпасть: имя кода без фразы — FAIL; фраза без имени в коде (мёртвая) — FAIL. Источник причины,
который оракул не умеет разрешить до литерала, — собственная ошибка оракула, тоже FAIL (не пропуск).

Правила сбора (общие формы вызова, не список мест):
  R1 `<…>._unparsed(base, X)` — причина разбора → исход 4; X — литерал, `"имя:%s" % …` (имя до «:») либо имя
     переменной, распакованной из вызова функции F (`a, b, X = self.forms.find(…)`) — тогда литералы той же позиции
     кортежей `return` функции F;
  R2 `_reask("<исход>", X, …)` — первичный переспрос машины состояний; учитываются исходы 4 и 23;
  R3 `reply_text(ctx, "<исход>", {"reply": {"reason": X}}, …)` — ответ поллера; X — литерал; `<имя>.get("reason")` —
     пересылка причины разбора (R1); имя переменной из распаковки вызова F (`kind, X = undo_mod.select_target(…)`) —
     литералы позиции X в `return "reask", …` функции F; `str(e)` из `except ValueError as e` — литералы
     `raise ValueError("…")` функций, вызванных в теле этого try;
  R4 `return "reask", X` — отказ выбора цели отзыва → исход 23.

В2 — ОТВЕТ. Каждая причина кода → ответ поллера `poll.reply_text`: ОДНА строка ≤160 символов (бюджет v8, число —
из спеки, не из кода), токен справки из реестра, НИ машинного имени причины, НИ любого имени вида `слово_слово`,
без обрезания «…», ровно «<фраза реестра>. <указатель>» (подстановки оракул делает сам); имя причины — в трассе.
Матрица мутаций оракула — пакетом (§5 правила сходимости), с обратным контролем законной перестановки."""
import ast
import os
import re
import sys
import tempfile
import unittest
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.abspath(os.path.join(HERE, ".."))
REG = os.path.join(BOT, "kit", "commands.yaml")
PHRASES = os.path.join(BOT, "kit", "reask-phrases.yaml")    # R3-fix: фразы — отдельный реестр комплекта
FORMS = os.path.join(BOT, "kit", "duration-forms.yaml")
SPEC_REPLY_MAX = 160            # контракт §1 №исход-4: «ОДНА строка ≤160 символов» (бюджет v8)
OUTCOMES = ("reask_unparsed", "reask_undo_not_found")
PRODUCER_GLOB = "bot/*.py"       # область сбора — ВСЕ модули бота, не список файлов


# ------------------------------------------------------------------ независимое чтение реестров
def _dq(raw):
    raw = raw.strip()
    m = re.match(r'^"((?:[^"\\]|\\.)*)"\s*(?:#.*)?$', raw)
    if not m:
        raise AssertionError("оракул: скаляр реестра не в двойных кавычках: %r" % raw)
    if "\\" in m.group(1):
        raise AssertionError("оракул: escape во фразе не поддержан оракулом: %r" % raw)
    return m.group(1)


def registry_reasons(text):
    """{исход: {имя: фраза}}, фраза-заглушка — построчно из текста реестра фраз (kit/reask-phrases.yaml)."""
    out, cur, section, fallback = {}, None, False, None
    for ln in text.split("\n"):
        if ln.startswith("reask_reasons:"):
            section = True; continue
        if ln.startswith("reask_reason_fallback:"):
            fallback = _dq(ln.split(":", 1)[1]); section = False; continue
        if ln and not ln.startswith(" ") and not ln.startswith("#"):
            section = False
        if not section or not ln.strip() or ln.lstrip().startswith("#"):
            continue
        m = re.match(r"^  ([a-z0-9_]+):\s*$", ln)
        if m:
            cur = m.group(1)
            if cur in out:
                raise AssertionError("оракул: дубль исхода %s" % cur)
            out[cur] = {}; continue
        m = re.match(r"^    ([a-z0-9_]+):(.*)$", ln)
        if m and cur:
            if m.group(1) in out[cur]:
                raise AssertionError("оракул: дубль причины %s.%s" % (cur, m.group(1)))
            out[cur][m.group(1)] = _dq(m.group(2)); continue
        raise AssertionError("оракул: строка узла reask_reasons не разобрана: %r" % ln)
    return out, fallback


def registry_positions(text):
    """[{id, token, example, example_dated, grammar}] — построчно из списка commands:."""
    rows, cur, inside = [], None, False
    for ln in text.split("\n"):
        if ln.startswith("commands:"):
            inside = True; continue
        if not inside:
            continue
        m = re.match(r"^  - id: (\S+)$", ln)
        if m:
            cur = {"id": m.group(1)}; rows.append(cur); continue
        m = re.match(r"^    (token|example|example_dated|grammar):(.*)$", ln)
        if m and cur is not None:
            cur[m.group(1)] = _dq(m.group(2))
    return rows


def forms_examples(text):
    out, cur, inside = {}, None, False
    for ln in text.split("\n"):
        if ln.startswith("forms:"):
            inside = True; continue
        if inside and ln and not ln.startswith(" ") and not ln.startswith("#"):
            break
        m = re.match(r"^  - id: (\S+)$", ln)
        if inside and m:
            cur = m.group(1); continue
        m = re.match(r"^    example:(.*)$", ln)
        if inside and m and cur:
            out[cur] = m.group(1)        # сырой скаляр: разбирается, только если фраза на него ссылается
    return out


def oracle_render(phrase, positions, forms):
    by_id = {p["id"]: p for p in positions}

    def sub(m):
        kind, ident = m.group(1), m.group(2)
        if kind == "form":
            return _dq(forms[ident])
        return by_id[ident][kind]
    return re.sub(r"\{(token|example|example_dated|form):([A-Za-z0-9_]+)\}", sub, phrase)


def help_token(positions):
    toks = [p["token"] for p in positions if p.get("grammar", "").endswith("#grammar-help")]
    assert len(toks) == 1, "оракул: позиция справки не единственна"
    return toks[0]


# ------------------------------------------------------------------ сбор причин из кода (AST)
class OracleError(AssertionError):
    pass


def _const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _callee_name(call):
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _functions(trees):
    """{имя функции: [FunctionDef]} по всем модулям — для разрешения F в распаковке и в try."""
    out = {}
    for tree in trees.values():
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(n.name, []).append(n)
    return out


def _parents(tree):
    par = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            par[c] = n
    return par


def _enclosing(node, par, types):
    while node in par:
        node = par[node]
        if isinstance(node, types):
            return node
    return None


def _returns_at(funcs, name, index):
    """Литералы позиции index в кортежах `return` функции name. Если у F есть возвраты с первым элементом «reask»
    (форма «вид, значение»), берутся только они — остальные виды несут не причину; иначе — все возвраты, где на
    позиции None — «причины нет». Нелитерал на позиции причины — OracleError."""
    if name not in funcs:
        raise OracleError("оракул: функция %r (источник причины) не найдена" % name)
    rets = []
    for fn in funcs[name]:
        stack = [c for c in fn.body if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))]
        while stack:                              # возвраты САМОЙ F (вложенные функции — не её)
            n = stack.pop()
            stack.extend(c for c in ast.iter_child_nodes(n) if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)))
            if not isinstance(n, ast.Return):
                continue
            # R2: форма возврата, которую оракул не читает (список, имя, вызов, условное…), — его собственная ошибка,
            # а не молчаливый пропуск ветви (иначе скрытый производитель проходит незамеченным)
            if not isinstance(n.value, ast.Tuple) or len(n.value.elts) <= index:
                raise OracleError("оракул: %s возвращает форму, которую оракул не разрешает: %s" % (name, ast.dump(n.value)[:120] if n.value else "return"))
            rets.append(n.value.elts)
    tagged = [e for e in rets if _const(e[0]) == "reask"]
    out = set()
    for elts in (tagged or rets):
        v = elts[index]
        if isinstance(v, ast.Constant) and v.value is None:
            continue
        if _const(v) is None:
            raise OracleError("оракул: %s возвращает нелитеральную причину на позиции %d" % (name, index))
        out.add(_const(v))
    if not out:
        raise OracleError("оракул: у %s нет литеральных причин на позиции %d" % (name, index))
    return out


def _resolve(expr, fn, funcs, par, where):
    """Выражение причины → множество имён; неразрешимое — OracleError."""
    c = _const(expr)
    if c is not None:
        return {c.split(":", 1)[0]}
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod) and _const(expr.left) is not None:
        return {_const(expr.left).split(":", 1)[0]}
    if isinstance(expr, ast.Name) and fn is not None:
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Tuple) \
                    and isinstance(n.value, ast.Call):
                names = [e.id if isinstance(e, ast.Name) else None for e in n.targets[0].elts]
                if expr.id in names:
                    return _returns_at(funcs, _callee_name(n.value), names.index(expr.id))
    if isinstance(expr, ast.Call) and _callee_name(expr) == "str" and len(expr.args) == 1 and isinstance(expr.args[0], ast.Name):
        var = expr.args[0].id
        handler = _enclosing(expr, par, (ast.ExceptHandler,))
        if handler is not None and handler.name == var:
            tr = par.get(handler)
            out = set()
            for n in ast.walk(ast.Module(body=tr.body, type_ignores=[])):
                if isinstance(n, ast.Call) and _callee_name(n) in funcs:
                    for f in funcs[_callee_name(n)]:
                        for r in ast.walk(f):
                            if isinstance(r, ast.Raise) and isinstance(r.exc, ast.Call) and _callee_name(r.exc) == "ValueError" \
                                    and r.exc.args and _const(r.exc.args[0]) is not None:
                                out.add(_const(r.exc.args[0]))
            if out:
                return out
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "get" \
            and expr.args and _const(expr.args[0]) == "reason":
        return set()            # пересылка причины разбора: её имена собраны правилом R1
    raise OracleError("оракул: неразрешимый источник причины в %s: %s" % (where, ast.dump(expr)[:160]))


def code_reasons(sources):
    """sources: {имя модуля: текст} → {исход: {имя причины}}."""
    trees = {k: ast.parse(v) for k, v in sources.items()}
    funcs = _functions(trees)
    out = {o: set() for o in OUTCOMES}
    for mod, tree in trees.items():
        par = _parents(tree)
        for n in ast.walk(tree):
            fn = _enclosing(n, par, (ast.FunctionDef, ast.AsyncFunctionDef))
            where = "%s:%d" % (mod, getattr(n, "lineno", 0))
            if isinstance(n, ast.Call):
                name = _callee_name(n)
                if name == "_unparsed" and len(n.args) >= 2:                                        # R1
                    out["reask_unparsed"] |= _resolve(n.args[1], fn, funcs, par, where)
                elif name == "_reask" and len(n.args) >= 2 and _const(n.args[0]) in OUTCOMES:       # R2
                    out[_const(n.args[0])] |= _resolve(n.args[1], fn, funcs, par, where)
                elif name == "reply_text" and len(n.args) >= 3 and _const(n.args[1]) in OUTCOMES:   # R3
                    d = n.args[2]
                    reply = None
                    if isinstance(d, ast.Dict):
                        for k, v in zip(d.keys, d.values):
                            if _const(k) == "reply":
                                reply = v
                    if not isinstance(reply, ast.Dict):
                        raise OracleError("оракул: %s — ответ переспроса без литерального {'reply': {...}}" % where)
                    for k, v in zip(reply.keys, reply.values):
                        if _const(k) == "reason":
                            out[_const(n.args[1])] |= _resolve(v, fn, funcs, par, where)
            elif isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple) and len(n.value.elts) == 2 \
                    and _const(n.value.elts[0]) == "reask":                                         # R4
                out["reask_undo_not_found"] |= _resolve(n.value.elts[1], fn, funcs, par, where)
    return out


def bot_sources():
    out = {}
    for name in sorted(os.listdir(BOT)):
        if name.endswith(".py"):
            with open(os.path.join(BOT, name), encoding="utf-8") as fh:
                out[name] = fh.read()
    return out


def closure_diff(code, reg):
    """[(исход, имя, что не так)] — пусто ⟺ множества совпадают по каждому исходу."""
    bad = []
    for o in OUTCOMES:
        for name in sorted(code.get(o, set()) - set(reg.get(o, {}))):
            bad.append((o, name, "имя кода без фразы реестра"))
        for name in sorted(set(reg.get(o, {})) - code.get(o, set())):
            bad.append((o, name, "фраза реестра без имени в коде (мёртвая)"))
        for name, phrase in (reg.get(o) or {}).items():
            if not phrase.strip():
                bad.append((o, name, "пустая фраза"))
    for o in sorted(set(reg) - set(OUTCOMES)):
        bad.append((o, "*", "исход вне 4/23"))
    return bad


# ------------------------------------------------------------------ тесты
class ClosureTests(unittest.TestCase):
    def setUp(self):
        with open(PHRASES, encoding="utf-8") as fh:
            self.reg_text = fh.read()
        self.reg, self.fallback = registry_reasons(self.reg_text)
        self.src = bot_sources()

    def test_v1_code_reasons_equal_registry_names(self):
        code = code_reasons(self.src)
        sys.stderr.write("\n[В1] причин кода: %s\n" % ", ".join("%s=%d" % (o, len(code[o])) for o in OUTCOMES))
        self.assertTrue(code["reask_unparsed"] and code["reask_undo_not_found"], "оракул не нашёл ни одной причины — сбор сломан")
        self.assertEqual(closure_diff(code, self.reg), [])
        self.assertTrue(self.fallback and self.fallback.strip())

    def test_v1_mutation_matrix_batch(self):
        """Каждая мутация ОБЯЗАНА дать непустое расхождение (или отказ оракула); законная перестановка — пустое."""
        src = self.src
        reg_text = self.reg_text

        def run(sources=None, reg=None):
            try:
                return closure_diff(code_reasons(sources or src), registry_reasons(reg or reg_text)[0])
            except OracleError as e:
                return [("oracle", "error", str(e))]

        def patch(mod, old, new):
            s = dict(src)
            self.assertIn(old, s[mod], "мутация %s: якорь не найден" % mod)
            s[mod] = s[mod].replace(old, new, 1)
            return s
        first_reason = next(iter(self.reg["reask_unparsed"]))
        lines = reg_text.split("\n")
        i1 = next(i for i, ln in enumerate(lines) if ln.startswith("    %s:" % first_reason))
        swapped = list(lines); swapped[i1], swapped[i1 + 1] = swapped[i1 + 1], swapped[i1]
        cases = [
            ("R1 новая причина разбора без фразы", run(patch("parse.py", 'return self._unparsed(base, "not_utf8")', 'return self._unparsed(base, "zz_new_reason")')), True),
            ("R1 динамическое имя «имя:%s»", run(patch("parse.py", '"unknown_command:%s" % cmd', '"zz_dyn:%s" % cmd')), True),
            ("R1 через распаковку find()", run(patch("parse.py", 'return None, s, "free_text_without_time"\n', 'return None, s, "zz_find_reason"\n')), True),
            ("R2 новый переспрос машины состояний", run(patch("session.py", '_reask("reask_unparsed", "nonexistent_local_time")', '_reask("reask_unparsed", "zz_sess")')), True),
            ("R3 литерал в ответе поллера", run(patch("poll.py", '{"reply": {"reason": "confirm_not_allowed"}}', '{"reply": {"reason": "zz_poll"}}')), True),
            ("R3 неразрешимый источник", run(patch("poll.py", '{"reply": {"reason": "confirm_not_allowed"}}', '{"reply": {"reason": uid}}')), True),
            ("R3 str(e) ← raise ValueError", run(patch("aggregation.py", 'raise ValueError("summary_period_out_of_range")', 'raise ValueError("zz_period")')), True),
            ("R4 новый отказ выбора цели", run(patch("undo.py", 'return "reask", "n_out_of_range"', 'return "reask", "zz_undo"')), True),
            ("реестр: потеря фразы", run(reg="\n".join(lines[:i1] + lines[i1 + 1:])), True),
            ("реестр: мёртвое имя", run(reg=reg_text.replace("  reask_undo_not_found:\n", "  reask_undo_not_found:\n    zz_dead: \"мёртвая\"\n", 1)), True),
            ("реестр: пустая фраза", run(reg=re.sub(r'(?m)^(    %s:) ".*"$' % first_reason, r'\1 ""', reg_text, count=1)), True),
            ("реестр: исход вне 4/23", run(reg=reg_text.replace("  reask_undo_not_found:\n", "  reask_zz:\n    no_line: \"x\"\n  reask_undo_not_found:\n", 1)), True),
            ("обратный контроль: законная перестановка строк реестра", run(reg="\n".join(swapped)), False),
        ]
        rows = []
        for name, diff, must_fail in cases:
            ok = bool(diff) == must_fail
            rows.append("  %s  %-55s → %s" % ("PASS" if ok else "FAIL", name, diff[:1] or "совпадает"))
            self.assertEqual(bool(diff), must_fail, name)
        sys.stderr.write("\n[В1 мутации] %d:\n%s\n" % (len(rows), "\n".join(rows)))


class ReplyMatrixTests(unittest.TestCase):
    """В2: каждая причина кода → ответ без машинного имени, ≤160, одна строка, с токеном справки; имя — в трассе."""

    def setUp(self):
        sys.path.insert(0, BOT)
        import poll  # noqa: E402 — писатель ответа, предмет проверки
        self.poll = poll
        self.tmp = tempfile.mkdtemp(prefix="reask-")
        with open(PHRASES, encoding="utf-8") as fh:
            self.reg, self.fallback = registry_reasons(fh.read())
        with open(REG, encoding="utf-8") as fh:
            self.positions = registry_positions(fh.read())
        with open(FORMS, encoding="utf-8") as fh:
            self.forms = forms_examples(fh.read())
        self.help = help_token(self.positions)
        self.code = code_reasons(bot_sources())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self):
        return self.poll.Ctx(self.tmp, None, {}, "/nonexistent", bot_username="x")

    def reply(self, outcome, reason):
        ctx = self.ctx()
        text = self.poll.reply_text(ctx, outcome, {"reply": {"reason": reason}}, {})
        notes = [o["note"] for o in ctx.trace.ops if o["op"] == "reask_reason" and o["target"] == outcome]
        return text, notes

    def check_shape(self, text):
        self.assertEqual(len(text.splitlines()), 1, text)
        self.assertIsNone(re.search("[\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]", text), text)
        self.assertLessEqual(len(text), SPEC_REPLY_MAX, text)
        self.assertIn(self.help, text)
        self.assertNotIn("…", text, "фраза реестра обрезана бюджетом: %r" % text)
        self.assertIsNone(re.search(r"\b[a-z]+(?:_[a-z0-9]+)+\b", text), "машинное имя в ответе: %r" % text)

    def test_v2_every_code_reason_matrix(self):
        rows = []
        for outcome in OUTCOMES:
            for name in sorted(self.code[outcome]):
                text, notes = self.reply(outcome, name)
                want = oracle_render(self.reg[outcome][name], self.positions, self.forms)
                ok = (name not in text and text.startswith(want + ". ") and notes == [name] and len(text) <= SPEC_REPLY_MAX)
                rows.append("  %s  %-22s %-28s → %3d симв. %r" % ("PASS" if ok else "FAIL", outcome, name, len(text), text))
                self.check_shape(text)
                self.assertNotIn(name, text)
                self.assertTrue(text.startswith(want + ". "), (name, text, want))
                self.assertEqual(notes, [name], "имя причины не в трассе: %s" % name)
        sys.stderr.write("\n[В2 матрица] %d:\n%s\n" % (len(rows), "\n".join(rows)))

    def test_v2_dynamic_and_unknown_reasons(self):
        # хвост причины — текст человека: ни в ответ, ни в трассу
        text, notes = self.reply("reask_unparsed", "unknown_command:/zzq\r\nещё\x1cтекст")
        self.check_shape(text)
        self.assertNotIn("zzq", text); self.assertNotIn("unknown_command", text)
        self.assertEqual(notes, ["unknown_command"])
        # причина вне реестра — фраза-заглушка, машинного имени в ответе нет, в трассе — имя с пометкой
        for outcome in OUTCOMES:
            text, notes = self.reply(outcome, "zz_unmapped_reason")
            self.check_shape(text)
            self.assertTrue(text.startswith(self.fallback + ". "), text)
            self.assertEqual(len(notes), 1); self.assertTrue(notes[0].startswith("zz_unmapped_reason "), notes)
        # длинная причина вне реестра (прежний сценарий G16: 300 символов) — ответ в бюджете, имени нет
        text, _ = self.reply("reask_unparsed", "з" * 300)
        self.check_shape(text); self.assertNotIn("зззз", text)

    def test_v2_claim_snapshot_track_with_dotted_date(self):
        """Снимок заявки В2: `<track> 20.09 1.5 часа тест` (грамматика не расширяется — бэклог) → переспрос без имени."""
        sys.path.insert(0, BOT)
        import parse  # noqa: E402
        track = next(p for p in self.positions if p.get("grammar", "").endswith("#grammar-track"))
        P = parse.Parser(REG)
        upd = {"update_id": 1, "message": {"message_id": 1, "date": 1789188000, "chat": {"id": 5, "type": "private"},
                                           "from": {"id": 5, "first_name": "A"}, "text": track["token"] + " 20.09 1.5 часа тест"}}
        r = P.parse(upd)
        self.assertEqual(r["kind"], "unparsed")
        text, notes = self.reply("reask_unparsed", r["reason"])
        self.check_shape(text)
        self.assertEqual(notes, [r["reason"]])
        self.assertIn(track["example_dated"], text, "переспрос не показывает, как записать за прошлый день")


if __name__ == "__main__":
    unittest.main()
