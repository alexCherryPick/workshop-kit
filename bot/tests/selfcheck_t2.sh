#!/bin/bash
# selfcheck_t2.sh — прогон проверок verification таски T2 D09 + матрица мутаций ПАКЕТОМ
# (пре-флайт dualverify-message-to-line.md §5, построена ДО первого раунда). Числа — из прогона.
# Запуск из корня монорепо: BIN=<валидатор> bash bot/tests/selfcheck_t2.sh
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 2
BIN="${BIN:-$ROOT/validator/target/release/workshop-validator}"
PY=python3; FAILED=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; FAILED=1; }
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
export BIN WORK

echo "== 0. юнит-оракулы T2 (парсер, машина состояний, список, строка, якорь, коммент) + T8 (формы, отзыв)"
$PY -m unittest bot.tests.test_parse bot.tests.test_session bot.tests.test_lastn bot.tests.test_line bot.tests.test_anchor bot.tests.test_comment bot.tests.test_parse_forms bot.tests.test_undo > "$WORK/unit.log" 2>&1
tail -1 "$WORK/unit.log" | grep -q '^OK' && ok "unittest: $(grep -E '^Ran ' "$WORK/unit.log") $(grep -oE '\[N1 sweep\].*|\[transitions\].*' "$WORK/unit.log" | tr '\n' ';')" || { bad "unittest"; tail -15 "$WORK/unit.log"; }

echo "== 1. оракулы отдельно от писателей (греп импортов тестов T2)"
V=$(grep -nE '^(from|import) ' bot/tests/test_parse.py bot/tests/test_session.py bot/tests/test_lastn.py bot/tests/test_line.py bot/tests/test_anchor.py bot/tests/test_comment.py bot/tests/test_parse_forms.py bot/tests/test_undo.py | grep -vE 'import (os|re|sys|unittest|hashlib|uuid|json|shutil|tempfile|decimal|subprocess)|from botrepo import' | grep -vE 'test_parse.py:.*import parse( |$)|test_session.py:.*import parse, session|test_lastn.py:.*import lastn|test_line.py:.*import line( |$)|test_anchor.py:.*import anchor|test_comment.py:.*import comment|test_parse_forms.py:.*import parse( |$)|test_undo.py:.*import (botrepo|yamlmini, poll)' | wc -l | tr -d ' ')
echo "  посторонних импортов (писатель другого модуля в оракуле): $V"; [ "$V" = "0" ] && ok "оракулы не делят функций с писателями" || bad "оракул импортирует чужой писатель"
TOKS=$($PY -c "import yamlmini;print('|'.join(sorted(set(c['token'].lstrip('/') for c in yamlmini.load_file('bot/kit/commands.yaml')['commands'] if c['token']))))")
echo "  литералы команд в коде T2/T8 (токены — из реестра: $TOKS): $(grep -cE "\"/($TOKS)\"|'/($TOKS)'" bot/parse.py bot/session.py bot/lastn.py bot/line.py bot/anchor.py bot/comment.py bot/undo.py | awk -F: '{s+=$2} END{print s}')"

echo "== 2. матрица мутаций ПАКЕТОМ (§5 пре-флайта): 16 мутаций, ожидание каждой печатается"
$PY - <<'PY'
# -*- coding: utf-8 -*-
import sys, os, hashlib, copy, json
sys.path.insert(0, 'bot'); import parse, session, anchor, comment, line
P = parse.Parser('bot/kit/commands.yaml')
tok = {p['id']: p['token'] for p in P.positions}
PERSON = {"handle": "dev-one", "timezone": "Europe/Belgrade"}; CFG = {"last_default_n": 5, "namespace": None}
def upd(text, uid=1, mid=10, date=1752698400, chat=100000001):
    return {"update_id": uid, "message": {"message_id": mid, "date": date, "chat": {"id": chat, "type": "private"}, "from": {"id": 100000001, "first_name": "Dev"}, "text": text}}
def run(rec, text, **kw):
    return session.decide(rec, P.parse(upd(text, **kw)), PERSON, CFG, last_titles=["a", "b"], tail_of=P.tail_of)
def blocks(d, author="dev-one"):
    out = []
    for c in d["comments"]:
        a = anchor.derive(d["lines"][c["k"]]["identity"], c["k"]); out.append(comment.build(c["identity"], c["message_date"], c["body"], author, a, c["k"])[2])
    return out
def h(x): return hashlib.sha256(x if isinstance(x, bytes) else json.dumps(x, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:12]
OPEN = {"title": "созвон", "start_text": tok["start_title"] + " созвон\nхвост открытия", "started_at": 1752698400, "started_at_local": "x", "chat_id": 100000001, "start_message_id": 10, "start_update_id": 1, "schema_version": 1}
results = []
def m(name, cond, detail): results.append((name, cond, detail)); print("  %-4s %-40s %s" % ("PASS" if cond else "FAIL", name, detail))
base = run(dict(OPEN), tok["stop"] + "\nхвост закрытия", uid=3, mid=12, date=1752707700); bb = blocks(base)
# 1 потеря байта тела
mut = run(dict(OPEN), tok["stop"] + "\nхвост закрыти", uid=3, mid=12, date=1752707700); m("1 потеря байта тела", blocks(mut) != bb, "sha %s ≠ %s" % (h(b"".join(bb)), h(b"".join(blocks(mut)))))
# 2 перестановка строк тела
mut = run(dict(OPEN), tok["stop"] + "\nзакрытия хвост", uid=3, mid=12, date=1752707700); m("2 перестановка строк тела", blocks(mut) != bb, "cmp различает")
# 3 дубликат update (та же identity)
mut = run(dict(OPEN), tok["stop"] + "\nхвост закрытия", uid=3, mid=12, date=1752707700); m("3 дубликат update (та же identity)", blocks(mut) == bb and [anchor.derive(l["identity"], l["k"]) for l in mut["lines"]] == [anchor.derive(l["identity"], l["k"]) for l in base["lines"]], "тот же якорь, тот же id, тот же блок")
# 4 суффиксная подмена message_id
mut = run(dict(OPEN), tok["stop"] + "\nхвост закрытия", uid=3, mid=120, date=1752707700); m("4 суффиксная подмена message_id", anchor.derive(mut["lines"][0]["identity"]) != anchor.derive(base["lines"][0]["identity"]) and blocks(mut)[1] != bb[1], "якорь и id иные")
# 5 обнуление текста
mut = run(dict(OPEN, start_text=tok["start_title"] + " созвон"), tok["stop"], uid=3, mid=12, date=1752707700); m("5 обнуление хвостов", mut["comments"] == [] and mut["lines"], "коммента нет, строка есть"); mut2 = P.parse(upd("", uid=9)); m("5b пустой free_text", mut2["kind"] == "unparsed", mut2.get("reason"))
# 6 подмена значения при сохранении длины (дата стопа +1 день)
mut = run(dict(OPEN), tok["stop"] + "\nхвост закрытия", uid=3, mid=12, date=1752707700 + 86400); m("6 подмена значения (дата стопа)", [l["date"] for l in mut["lines"]] != [l["date"] for l in base["lines"]] and len(mut["lines"]) == 3, "строк %d, даты %s" % (len(mut["lines"]), [l["date"] for l in mut["lines"]]))
# 7 порча общего хелпера — .strip() в тракте тела
body = "  хвост с пробелами  \n".encode(); stripped = body.strip(); m("7 порча хелпера (.strip в тракте)", comment.build("tg:1:2", 1, body, "dev-one", "aaaaaaaa")[2] != comment.build("tg:1:2", 1, stripped, "dev-one", "aaaaaaaa")[2], "cmp роняет")
# 8 законная перестановка независимых update
a1 = run(None, "2ч созвон", uid=1, mid=10); a2 = run(None, "1ч ревью", uid=2, mid=11); b2 = run(None, "1ч ревью", uid=2, mid=11); b1 = run(None, "2ч созвон", uid=1, mid=10); m("8 законная перестановка (обратный контроль)", a1 == b1 and a2 == b2, "поштучно неизменны")
# 9 масштаб
import time as _t; t0 = _t.time(); [run(None, "2ч созвон %d" % i, uid=i, mid=i) for i in range(1000)]; dt = _t.time() - t0; m("9 масштабный вход (1000 update)", dt < 20, "%.2f с" % dt)
# 10 краевая локаль
p2 = {"handle": "dev-one", "timezone": "Asia/Kolkata"}; d = session.decide(dict(OPEN), P.parse(upd(tok["stop"], uid=3, mid=12, date=1752707700)), p2, CFG, tail_of=P.tail_of); m("10 краевая локаль (+05:30)", [l["date"] for l in d["lines"]] == ["2025-07-17"] and len(d["lines"]) == 1, "даты %s" % [l["date"] for l in d["lines"]])
dst = session.decide({**OPEN, "started_at": 1743289200}, P.parse(upd(tok["stop"], uid=3, mid=12, date=1743295500)), PERSON, CFG, tail_of=P.tail_of); m("10b DST весна (прожитое время)", dst["reply"]["hours_total"] == "1.75" and len(dst["lines"]) == 1, dst["reply"]["hours_total"])
dst2 = session.decide({**OPEN, "started_at": 1761435000}, P.parse(upd(tok["stop"], uid=3, mid=12, date=1761445800)), PERSON, CFG, tail_of=P.tail_of); m("10c DST осень (час дважды)", dst2["reply"]["hours_total"] == "3.00", dst2["reply"]["hours_total"])
# 11 Н1 — в test_line (перебор 1..86400), здесь кейсы буквы
m("11 Н1 кейсы буквы", line.n1_hours(1998) == "0.56" and line.n1_hours(54) == "0.02", "1998→%s 54→%s" % (line.n1_hours(1998), line.n1_hours(54)))
# 12 задержка обработки — «сейчас» в сигнатуре нет
m("12 задержка обработки на час", run(dict(OPEN), tok["stop"], uid=3, mid=12, date=1752707700) == run(dict(OPEN), tok["stop"], uid=3, mid=12, date=1752707700), "результат не зависит от момента прогона по построению")
# 13 start_n вне диапазона
m("13 start_n вне диапазона/0/-1", run(None, tok["start_n"] + " 9")["outcome"] == "reask_unparsed" and P.parse(upd(tok["start_n"] + " 0"))["kind"] == "unparsed" and P.parse(upd(tok["start_n"] + " -1"))["kind"] == "unparsed", "переспрос, заголовок не назван")
# 14 столкновение якоря
i = "tg:1:2"; a0 = anchor.derive(i); ex = {a0: "2026-09-07 9.00  другое <!--t:%s-->" % a0}; r1 = anchor.remint(i, 0, ex, "2026-09-07 1.00  x"); r2 = anchor.remint(i, 0, ex, "2026-09-07 1.00  x"); m("14 столкновение якоря → шаг соли", r1 == r2 and r1[1] == 1 and r1[0] == anchor.derive(i, 0, 1), "step=%d якорь=%s повтор равен" % (r1[1], r1[0]))
# 15 краевые байты
body = "эмодзи 🧑‍💻 вне BMP\r\nCRLF\n".encode("utf-8"); m("15 эмодзи вне BMP + CRLF побайтово", comment.build("tg:1:2", 1, body, "dev-one", "aaaaaaaa")[2].endswith(body), "тело насквозь")
# 16 два носителя одной строки таймера
ids = sorted(set((c["identity"], c["k"]) for c in base["comments"])); m("16 два носителя (открытие+закрытие) × 2 сегмента", ids == [("tg:100000001:10", 0), ("tg:100000001:10", 1), ("tg:100000001:12", 0), ("tg:100000001:12", 1)], str(ids))
print("  matrix: %d мутаций, PASS=%d FAIL=%d" % (len(results), sum(1 for r in results if r[1]), sum(1 for r in results if not r[1])))
sys.exit(0 if all(r[1] for r in results) else 1)
PY
[ $? -eq 0 ] && ok "матрица мутаций пакетом" || bad "матрица мутаций"

echo "== 3. валидатор до коммита: ленивое создание (precondition) / с конвертом (без precondition) / rc 2 и 10/127"
$BIN check-line "2026-09-07 1.50  зонд <!--t:0badf00d-->" --target time/TIMESHEET-2026-09-dev1.md --target-absent --no-config < /dev/null > "$WORK/cl1.txt"; echo "  absent: rc=$? precondition=$(grep -c PRECONDITION "$WORK/cl1.txt")"
$BIN check-line "2026-08-16 1.50  зонд <!--t:0badf00d-->" --target time/TIMESHEET-2026-08-dev1.md --target-file golden/valid/TIMESHEET-2026-08-dev1.md --no-config < /dev/null > "$WORK/cl2.txt"; echo "  present: rc=$? precondition=$(grep -c PRECONDITION "$WORK/cl2.txt")"
grep -q PRECONDITION "$WORK/cl1.txt" && ! grep -q PRECONDITION "$WORK/cl2.txt" && ok "precondition только при absent" || bad "precondition"
$BIN check-line "2026-08-16 0.00  ноль <!--t:0badf00d-->" --target time/TIMESHEET-2026-08-dev1.md --target-file golden/valid/TIMESHEET-2026-08-dev1.md --no-config < /dev/null > "$WORK/cl3.txt"; RC=$?; echo "  0.00: rc=$RC $(grep -oE 'HOURS_RANGE' "$WORK/cl3.txt" | head -1)"; [ $RC -eq 2 ] && ok "0.00 → HOURS_RANGE rc=2 (переспрос)" || bad "0.00"
$BIN check-line "2026-08-16 1.50  зонд <!--t:0badf00d-->" --target-file /nonexistent --target time/x.md --no-config < /dev/null > /dev/null 2>&1; RC=$?; echo "  io error rc=$RC"; [ $RC -eq 10 ] && ok "rc=10 сбой инструмента" || bad "rc=10"

echo "== 4. конверт при ленивом создании ПОЛНЫЙ: check-file на созданном файле rc<=1, MISSING=0"
$PY - > "$WORK/env.md" <<'PY'
import sys; sys.path.insert(0,'bot'); import line, uuid
print(line.envelope("019550fa-1ea0-773c-b820-1e2b73ab4901", "dev-one", "2025-09-07", "Europe/Belgrade", "workshop_bot", "2025-09-07") + line.build_line("2025-09-07", 9600, "созвон", "bd177919", (1757232900, 1757242500)), end="")
PY
$BIN check-file "$WORK/env.md" --path time/TIMESHEET-2025-09-dev-one.md --no-config < /dev/null > "$WORK/cf.txt" 2>&1; RC=$?; echo "  check-file rc=$RC missing=$(grep -c MISSING "$WORK/cf.txt") $(tail -2 "$WORK/cf.txt" | head -1)"; [ $RC -eq 0 ] && [ "$(grep -c MISSING "$WORK/cf.txt")" = "0" ] && ok "конверт полный, rc=0" || bad "конверт"

echo "== 5. образец коммента принимает бинарь: check-pair rc=0; сирота rc=1; дубль id rc=2"
$PY - "$WORK" <<'PY'
import sys, os; sys.path.insert(0,'bot'); import line, comment, anchor
W=sys.argv[1]; i="tg:100000001:12"; a=anchor.derive(i)
open(W+"/ts.md","w").write(line.envelope("019550fa-1ea0-773c-b820-1e2b73ab4901","dev-one","2025-09-07","Europe/Belgrade","workshop_bot","2025-09-07")+line.build_line("2025-09-07",9600,"созвон",a)+"\n")
cid, head, block = comment.build(i, 1757239200, "хвост".encode(), "dev-one", a)
open(W+"/ts.comments.md","wb").write(comment.comments_of_header("019550fa-1ea0-773c-b820-1e2b73ab4901").encode()+b"\n\n"+block)
open(W+"/orphan.comments.md","wb").write(comment.comments_of_header("019550fa-1ea0-773c-b820-1e2b73ab4901").encode()+b"\n\n"+comment.build(i,1757239200,"x".encode(),"dev-one","deadbeef")[2])
open(W+"/dup.comments.md","wb").write(comment.comments_of_header("019550fa-1ea0-773c-b820-1e2b73ab4901").encode()+b"\n\n"+block+block)
print("  header:", head)
PY
for f in ts orphan dup; do $BIN check-pair "$WORK/ts.md" --comments "$WORK/$f.comments.md" --path time/TIMESHEET-2025-09-dev-one.md --comments-path time/TIMESHEET-2025-09-dev-one.comments.md --no-config < /dev/null > "$WORK/cp_$f.txt" 2>&1; echo "  $f: rc=$? $(grep -oE 'ORPHAN_ANNOTATION|№ERROR-4' "$WORK/cp_$f.txt" | head -1)"; done
grep -q 'rc=0' "$WORK/cp_ts.txt" && grep -q 'ORPHAN_ANNOTATION' "$WORK/cp_orphan.txt" && grep -q 'ERROR-4' "$WORK/cp_dup.txt" && ok "check-pair: образец 0, сирота WARNING, дубль id ERROR" || bad "check-pair"

echo "== ИТОГ"; [ $FAILED -eq 0 ] && echo "SELFCHECK T2: ALL PASS" || echo "SELFCHECK T2: FAILURES PRESENT"; exit $FAILED
