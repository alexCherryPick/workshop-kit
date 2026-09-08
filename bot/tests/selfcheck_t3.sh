#!/bin/bash
# selfcheck_t3.sh — прогон проверок verification таски T3 D09 (поллер, offset, цикл коммита) + матрица
# мутаций ПАКЕТОМ (§5 пре-флайта dualverify-poller-commit-cycle.md — 20 мутаций, объявлены ДО кода).
# Запуск из корня монорепо: BIN=... bash bot/tests/selfcheck_t3.sh ; все числа — из этого прогона.
set -u
export LC_ALL=en_US.UTF-8
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 2
BIN="${BIN:-$ROOT/validator/target/release/workshop-validator}"
[ -x "$BIN" ] || { echo "нет бинаря валидатора: $BIN"; exit 2; }
export WORKSHOP_VALIDATOR="$BIN"
PY=python3; export PYTHONDONTWRITEBYTECODE=1
WORK=$(mktemp -d); export WORK; trap 'rm -rf "$WORK"' EXIT
SPEC_DIR="$ROOT/spec/09-tg-bot-time-line"; [ -d "$SPEC_DIR" ] || SPEC_DIR="$HOME/Analytics/cherrypick/workshop/output/format-spec/09-tg-bot-time-line"; export SPEC_DIR
TW="$SPEC_DIR/tg-bot.yaml"
FAILS=0; PASSES=0
ok() { echo "  PASS  $1"; PASSES=$((PASSES+1)); }
bad() { echo "  FAIL  $1"; FAILS=$((FAILS+1)); }

echo "== 0. юнит-оракулы T3 (test_poll, test_state_store, test_commit) + таблица offset по 20 исходам"
D09_OFFSET_TABLE="$WORK/offset-table.txt" $PY -m unittest bot.tests.test_poll bot.tests.test_state_store bot.tests.test_commit > "$WORK/ut.txt" 2>&1; RC=$?
grep -E '^(Ran|OK|FAILED)' "$WORK/ut.txt" | sed 's/^/  /'
[ $RC -eq 0 ] && ok "unittest T3" || { bad "unittest T3"; grep -E '^(FAIL|ERROR):' "$WORK/ut.txt" | sed 's/^/    /'; }
[ -f "$WORK/offset-table.txt" ] && cat "$WORK/offset-table.txt" | sed 's/^/  /'
N_ADV=$(grep -c 'advances=advance' "$WORK/offset-table.txt" 2>/dev/null); N_HOLD=$(grep -c 'advances=hold' "$WORK/offset-table.txt" 2>/dev/null); N_NA=$(grep -c 'неприменимо' "$WORK/offset-table.txt" 2>/dev/null)
echo "  таблица: advance=$N_ADV hold=$N_HOLD неприменимо=$N_NA (всего $((N_ADV+N_HOLD+N_NA)))"
[ $((N_ADV+N_HOLD+N_NA)) -eq 20 ] && [ "$N_HOLD" -eq 4 ] && ok "двадцать исходов исполнены; hold ровно у 10–13" || bad "таблица offset неполна"

echo "== 1. пиннованные фикстуры батчей: манифест (путь, sha256) — режим сверки; каждый батч через стенд"
$PY - <<'PY' && ok "фикстуры: манифест сверен, ожидания исходов и число коммитов-записей совпали" || bad "фикстуры"
# -*- coding: utf-8 -*-
import hashlib, json, os, re, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll
from botrepo import Stand, FakeTransport, git
D = "bot/tests/fixtures/t3"; bad = 0
entries = [(m.group(1), m.group(2)) for m in (re.match(r"^  - \{path: (\S+), sha256: ([0-9a-f]{64})\}", l) for l in open(os.path.join(D, "manifest.yaml"), encoding="utf-8")) if m]
jsons = sorted(f for f in os.listdir(D) if f.endswith(".json"))
if sorted(e[0] for e in entries) != jsons:
    print("  манифест не покрывает фикстуры: %s vs %s" % ([e[0] for e in entries], jsons)); bad = 1
for name, digest in entries:
    with open(os.path.join(D, name), "rb") as fh:
        data = fh.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != digest:
        print("  %s: sha256 %s ≠ манифест %s" % (name, actual[:12], digest[:12])); bad = 1; continue
    doc = json.loads(data.decode("utf-8"))
    s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml"))
    try:
        t = FakeTransport(doc["updates"]); ctx = poll.Ctx(s.root, t, cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
        r = poll.run_once(ctx)
        outs = [o[1] for o in r["outcomes"]]
        log = git(s.root, "log", "--format=%s")
        rec = sum(1 for l in log.split("\n") if l.startswith("workshop-bot: ") and l.split(" ")[1] in poll.RECORD_OUTCOMES)
        state_commits = sum(1 for l in log.split("\n") if l.startswith("workshop-bot: состояние"))
        print("  %-36s исходы=%s коммитов-записей=%d состояния=%d offset=%s" % (name, outs, rec, state_commits, botrepo.git(s.origin, "show", "main:.workshop/bot-state.yaml").count("offset")))
        if outs != doc["expect"]["outcomes"] or rec != doc["expect"]["record_commits"] or state_commits > 1:
            print("    ОЖИДАЛОСЬ %s / %d" % (doc["expect"]["outcomes"], doc["expect"]["record_commits"])); bad = 1
        if name.startswith("batch-start-stop-midnight-month"):
            files = sorted(f for f in os.listdir(os.path.join(s.root, "time")))
            stat = git(s.root, "show", "--stat", "--format=", "HEAD~1") if state_commits else git(s.root, "show", "--stat", "--format=", "HEAD")
            print("    файлы: %s; коммит закрытия: %s" % (files, [l.split("|")[0].strip() for l in stat.split("\n") if "|" in l]))
            if len([f for f in files if f.endswith(".comments.md")]) != 2 or len(files) != 4:
                print("    ОЖИДАЛОСЬ 2 табеля + 2 спутника"); bad = 1
    finally:
        s.close()
sys.exit(bad)
PY

echo "== 2. матрица мутаций ПАКЕТОМ (§5: 20 мутаций, ожидание каждой печатается)"
cp -R bot "$WORK/bot-base"
mutant() { # $1 имя, $2 файл, $3 perl-выражение, $4 тест — ожидание: тест ПАДАЕТ на мутанте
  rm -rf "$WORK/mut"; cp -R "$WORK/bot-base" "$WORK/mut"
  perl -0pi -e "$3" "$WORK/mut/$2"
  if cmp -s "$WORK/mut/$2" "$WORK/bot-base/$2"; then echo "  FAIL m$1: мутация не применилась"; return 1; fi
  (cd "$WORK/mut" && WORKSHOP_VALIDATOR="$BIN" $PY -m unittest "$4" > "$WORK/mut-$1.txt" 2>&1); rc=$?
  if [ $rc -ne 0 ]; then echo "  PASS $1 $5 — оракул РОНЯЕТ мутанта ($4)"; return 0; else echo "  FAIL $1 $5 — мутант прошёл оракул"; return 1; fi
}
MRES=0
$PY - <<'PY' > "$WORK/matrix.txt" 2>&1; MRES=$?
# -*- coding: utf-8 -*-
import hashlib, json, os, re, shutil, sys, time, unittest
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll, state_store
from botrepo import Stand, FakeTransport, msg, callback, git, TOK, ADMIN_ID, DEV3_ID, UNKNOWN_ID
FAILS = 0
def m(name, cond, detail):
    global FAILS
    print("  %-4s %-44s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond: FAILS += 1
def run(s, cfg, ups, transport=None, validator=None, sleeper=None):
    t = transport or FakeTransport(ups)
    ctx = poll.Ctx(s.root, t, cfg, validator or botrepo.VALIDATOR, bot_username="x", sleeper=sleeper or (lambda x: None))
    return poll.run_once(ctx), t, ctx
def stand():
    s = Stand(); return s, yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml"))
def origin_offset(s):
    r = git(s.origin, "show", "main:.workshop/bot-state.yaml", check=False); mm = re.search(r"^offset: (\d+)$", r, re.M); return int(mm.group(1)) if mm else 0
def sha(b): return hashlib.sha256(b).hexdigest()[:12]
def strip_id(b): return re.sub(rb"^id: .*$", b"id: X", b, count=1, flags=re.M)
def delegated(name, test_id, label):
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    res = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    m(name, res.wasSuccessful() and res.testsRun > 0, "%s: тестов %d, провалов %d" % (label, res.testsRun, len(res.failures) + len(res.errors)))
TS = "time/TIMESHEET-2026-09-dev-one.md"; T0 = 1788790990

# 1 потеря update из батча
s, cfg = stand()
u1, u2, u3 = msg("1ч а"), msg("1ч б"), msg("1ч в")
r, t, _ = run(s, cfg, [u1, u3])
m("1 потеря update (пропуск update_id)", [o[1] for o in r["outcomes"]] == ["recorded", "recorded"] and origin_offset(s) == u3["update_id"] + 1, "исходы %s; offset=%d=%d+1" % ([o[1] for o in r["outcomes"]], origin_offset(s), u3["update_id"]))
s.close()

# 2 перестановка открытия и закрытия во входе, расходящиеся времена
s, cfg = stand(); a = msg(TOK["start_title"] + " ремонт", date=T0); b = msg(TOK["stop"], date=T0 + 5400)
r, t, _ = run(s, cfg, [b, a])           # во входе — закрытие первым, update_id — открытие первым
one = (strip_id(s.read(TS)), s.read(".workshop/bot-sessions.yaml"), s.commits()); s.close()
s2, cfg2 = stand(); r2, _, _ = run(s2, cfg2, [a, b]); two = (strip_id(s2.read(TS)), s2.read(".workshop/bot-sessions.yaml"), s2.commits()); s2.close()
m("2 перестановка во входе при тех же update_id", [o[1] for o in r["outcomes"]] == ["session_opened", "session_closed_recorded"] and one == two, "исходы %s; табель/состояние/коммиты cmp-равны: %s" % ([o[1] for o in r["outcomes"]], one == two))

# 3 дубликат update: в одном батче и в двух прогонах
s, cfg = stand(); u = msg("1ч 30м дубль\nхвост")
r, t, _ = run(s, cfg, [u, dict(u)])
files = (s.read(TS), s.read(TS[:-3] + ".comments.md"), s.commits())
t2 = FakeTransport([u]); t2.get_updates = lambda **kw: [u]
r2, _, _ = run(s, cfg, [u], transport=t2)
m("3 дубликат update (батч / два прогона)", [o[1] for o in r["outcomes"]] == ["recorded", "identical_repeat"] and r2["outcomes"][0][1] == "identical_repeat" and files == (s.read(TS), s.read(TS[:-3] + ".comments.md"), s.commits()), "исходы %s + %s; файлы и число коммитов cmp-равны" % ([o[1] for o in r["outcomes"]], r2["outcomes"][0][1]))
s.close()

# 4 суффиксная подмена update_id (…5 → …50) с иным message_id
s, cfg = stand(); u = msg("1ч подмена", update_id=900100005, message_id=5005); u50 = msg("1ч подмена", update_id=900100050, message_id=5050)
r, _, _ = run(s, cfg, [u, u50]); anchors = re.findall(rb"<!--t:([0-9a-f]{8})-->", s.read(TS))
m("4 суффиксная подмена update_id", [o[1] for o in r["outcomes"]] == ["recorded", "recorded"] and len(set(anchors)) == 2 and origin_offset(s) == 900100051, "иной update, якоря %s, offset=%d" % ([a.decode() for a in anchors], origin_offset(s)))
s.close()

# 5 обнуление файла состояния между открытием и закрытием
s, cfg = stand(); run(s, cfg, [msg(TOK["start_title"] + " x", date=T0)])
with open(os.path.join(s.root, ".workshop", "bot-sessions.yaml"), "wb") as fh: fh.write(b"sessions: {}\n")
git(s.root, "commit", "-qam", "wipe"); git(s.root, "push", "-q", "origin", "HEAD")
r, t, _ = run(s, cfg, [msg(TOK["stop"], date=T0 + 600)])
m("5 обнуление файла состояния между открытием и закрытием", r["outcomes"][0][1] == "reask_stop_without_open" and r["held"] is None, "исход %s, громкой порчи нет" % r["outcomes"][0][1])
s.close()

# 6 подмена started_at при сохранении длины
s, cfg = stand(); run(s, cfg, [msg(TOK["start_title"] + " y", date=T0)])
p = os.path.join(s.root, ".workshop", "bot-sessions.yaml")
with open(p, "rb") as fh: b = fh.read()
with open(p, "wb") as fh: fh.write(b.replace(b"started_at: %d" % T0, b"started_at: %d" % (T0 - 600)))
git(s.root, "commit", "-qam", "shift"); git(s.root, "push", "-q", "origin", "HEAD")
r, t, ctx = run(s, cfg, [msg(TOK["stop"], date=T0 + 3000)])
hrs = re.search(rb"^2026-09-07 (\d+\.\d\d) ", s.read(TS), re.M)
ops = [o["op"] for o in ctx.trace.ops]
m("6 подмена started_at при сохранении длины", hrs and hrs.group(1) == b"1.00" and "fetch" in ops and ops.index("fetch") < ops.index("commit"), "часы %s (3000+600 с = 1.00, не 0.83); трасса: fetch до commit" % (hrs.group(1).decode() if hrs else None))
s.close()

# 8 законная перестановка независимых update разных людей
sA, cA = stand(); x = msg("1ч один"); y = msg("2ч три", from_id=DEV3_ID)
run(sA, cA, [x, y]); one = (strip_id(sA.read(TS)), strip_id(sA.read("time/TIMESHEET-2026-09-dev-three.md"))); sA.close()
sB, cB = stand(); run(sB, cB, [y, x]); two = (strip_id(sB.read(TS)), strip_id(sB.read("time/TIMESHEET-2026-09-dev-three.md"))); sB.close()
m("8 законная перестановка (обратный контроль)", one == two, "файлы обоих людей cmp-равны при обратном порядке")

# 9 масштабный вход: 500 update, 20 людей (самозапись), 10 открытых сессий — дренаж циклами
# (getUpdates отдаёт не более limit=100 за прогон, как Telegram; крон гоняет прогон повторно до опустошения)
s, cfg = stand(); ups = []
for i in range(500):
    pid = 100000100 + (i % 20)
    if i < 10: ups.append(msg(TOK["start_title"] + " сессия %d" % i, from_id=pid, date=T0 + i))
    else: ups.append(msg("%dм работа %d" % (5 + i % 50, i), from_id=pid, date=T0 + i))
t0 = time.time(); processed = 0; rec_outcomes = 0; cycles = 0; held = None
while True:
    t = FakeTransport(ups); ctx = poll.Ctx(s.root, t, cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
    r = poll.run_once(ctx); cycles += 1
    processed += r["processed"]; rec_outcomes += sum(1 for o in r["outcomes"] if o[1] in poll.RECORD_OUTCOMES)
    if r["held"]: held = r["held"]; break
    if r["processed"] == 0: break
dt = time.time() - t0
log = git(s.root, "log", "--format=%s"); rec = sum(1 for l in log.split("\n") if l.startswith("workshop-bot: ") and l.split(" ")[1] in poll.RECORD_OUTCOMES)
m("9 масштабный вход (500 update, 20 людей, 10 сессий)", processed == 500 and rec == rec_outcomes and held is None and cycles == 6, "%.1f с, %d циклов по ≤100 (5 дренажных + 1 подтверждающий пустой); обработано %d; коммитов-записей %d = порождающих исходов; открытых сессий: %d" % (dt, cycles, processed, rec, len(state_store.read_sessions(s.root)["sessions"])))
s.close()

# 10 краевая локаль: сессия через местную полночь на границе месяца
s, cfg = stand(); r, _, _ = run(s, cfg, [msg(TOK["start_title"] + " ночная\nхвост", date=1790803800), msg(TOK["stop"], date=1790808300)])  # Belgrade 30.09 23:30 → 01.10 00:45
files = sorted(os.listdir(os.path.join(s.root, "time"))); stat = git(s.root, "show", "--stat", "--format=", "HEAD"); n_in_commit = len([l for l in stat.split("\n") if "|" in l])
m("10 краевая локаль: полночь на границе месяца", len(files) == 4 and r["outcomes"][1][1] == "session_closed_recorded" and s.commits() == "3", "файлы %s; в коммите закрытия путей: %d; коммитов всего %s (seed+2)" % (files, n_in_commit, s.commits()))
s.close()

# 11 смерть между commit и push
s, cfg = stand(); u = msg("1ч смерть после коммита\nхвост"); s.deny_push(True)
r, _, _ = run(s, cfg, [u]); line1 = s.read(TS)
s.deny_push(False); r2, _, _ = run(s, cfg, [u])
m("11 смерть между commit и push", r["held"][1] == "retries_exhausted" and r2["outcomes"][0][1] == "identical_repeat" and s.read(TS) == line1 and s.read(TS).count(b"<!--t:") == 1 and s.origin_head() == s.head(), "повтор переиспользует ПРЕЖНЮЮ строку (cmp), второй нет; запушено")
s.close()

# 12 смерть до commit
s, cfg = stand(); u = msg("1ч смерть до коммита\nхвост")
orig = poll.commit_mod.commit_paths
def die(*a, **k): raise KeyboardInterrupt
poll.commit_mod.commit_paths = die
try:
    try: run(s, cfg, [u])
    except KeyboardInterrupt: pass
finally: poll.commit_mod.commit_paths = orig
partial = (s.read(TS), s.read(TS[:-3] + ".comments.md"))
r, _, ctx = run(s, cfg, [u]); again = (s.read(TS), s.read(TS[:-3] + ".comments.md"))
m("12 смерть до commit", r["outcomes"][0][1] == "recorded" and strip_id(partial[0]) == strip_id(again[0]) and re.sub(rb"comments-of: \S+", b"", partial[1]) == re.sub(rb"comments-of: \S+", b"", again[1]) and "clean" in [o["op"] for o in ctx.trace.ops], "побайтово та же строка/коммент (тот же якорь и id); новый id контейнера при пересоздании незапушенного файла — легален (глава §4)")
s.close()

delegated("13 конфликт файла состояния в merge", "test_poll.TestRaces.test_sessions_conflict_is_loud", "громкий отказ (10), origin не тронут, алярм, offset")
delegated("14 чужой коммент к той же строке в merge", "test_poll.TestRaces.test_push_rejected_then_retry_union", "union, оба c:<id>, comments-of один")
delegated("17 обрезанный финальный LF спутника", "test_commit.WriterTests.test_trailing_lf_is_completed_before_append", "писатель дозавершает")
delegated("18 callback по time_bearing позиции", "test_poll.TestCycle.test_callback_last_and_time_bearing", "не исполняется; подтверждение нажатия через tg.py")

# 19 rc=10 и бинарь 126/127 → исход 13, отличим от «нашлись ошибки»; алярм через tg.py
fake = os.path.join(os.environ["WORK"], "fake10"); open(fake, "w").write("#!/bin/sh\necho 'io error'\nexit 10\n"); os.chmod(fake, 0o755)
noexec = os.path.join(os.environ["WORK"], "fake-noexec"); open(noexec, "w").write("#!/bin/sh\nexit 0\n"); os.chmod(noexec, 0o644)
res = []
for v in (fake, noexec, os.path.join(os.environ["WORK"], "no-such")):
    s, cfg = stand(); r, t, _ = run(s, cfg, [msg("1ч сбой")], validator=v)
    res.append((r["held"][1] if r["held"] else r["outcomes"][0][1], any("сторож" in x[1] for x in t.sent))); s.close()
s, cfg = stand(); fake2 = os.path.join(os.environ["WORK"], "fake2"); open(fake2, "w").write("#!/bin/sh\necho 'ERROR X: SOME_RULE'\nexit 2\n"); os.chmod(fake2, 0o755)
r2, _, _ = run(s, cfg, [msg("1ч ошибки")], validator=fake2); s.close()
m("19 сбой инструмента: rc=10 / 126 / 127", all(o == "tool_failure" and a for o, a in res) and r2["outcomes"][0][1] == "reask_invalid", "исходы %s (алярм у каждого); rc=2 → %s (отличим)" % ([o for o, a in res], r2["outcomes"][0][1]))

# 15 — подтверждение offset при неуспешном push (оракульная сторона; код-мутант — в bash ниже)
delegated("15 порядок подтверждения offset (оракул)", "test_poll.TestRaces.test_retries_exhausted", "следующий прогон подтверждает offset авторитета")
delegated("16 check_pair ДО commit (оракул трассы)", "test_poll.TestCycle.test_record_one_commit_two_files_state", "check_line и check_pair до commit")
print("  matrix(python): провалов %d" % FAILS)
sys.exit(1 if FAILS else 0)
PY
cat "$WORK/matrix.txt" | grep -v "ResourceWarning\|tracemalloc\|^  [a-z_ ]*= " 
[ $MRES -eq 0 ] && ok "матрица (данные): 1–6, 8–14, 17–19" || bad "матрица (данные)"
# код-мутанты: 2 (сортировка по message.date), 7 (недетерминированный дампер), 15 (offset из локальной копии), 16 (без check_pair)
CM=0
mutant 2 poll.py 's/key=lambda u: u\.get\("update_id", 0\)/key=lambda u: (u.get("message") or {}).get("date", 0)/' tests.test_poll.TestCycle.test_batch_order_equals_sequential "сортировка по message.date вместо update_id" || CM=1
mutant 7 yamlmini.py 's/def dumps\(obj, sort_keys=False\):/import random as _r\ndef dumps(obj, sort_keys=False):\n    return _dumps0(obj, sort_keys) + "# %d\\n" % _r.randrange(10**9)\ndef _dumps0(obj, sort_keys=False):/' tests.test_state_store.StateStoreTests.test_state_fields_match_contract_and_bytes_are_deterministic "дампер недетерминирован (два write того же doc не cmp-равны)" || CM=1
mutant 15 poll.py 's/if auth is not None and auth < state\["offset"\]:/if False:/' tests.test_poll.TestRaces.test_retries_exhausted "offset подтверждается из локальной копии, не из origin" || CM=1
mutant 16 poll.py 's/            ctx\.trace\.add\("check_pair", srel, rc\)\n//' tests.test_poll.TestCycle.test_record_one_commit_two_files_state "запись check_pair удалена из трассы" || CM=1
[ $CM -eq 0 ] && ok "матрица (код-мутанты 2, 7, 15, 16): каждый пойман оракулом" || bad "код-мутанты"
echo "  20 force-push: $(grep -rnE 'push[^|]*(--force|--force-with-lease|(^| )-f( |$)|\+refs/)' bot/*.py bot/kit/workflows/ harness/bot_p1_refuse.sh | wc -l | tr -d ' ') находок (ожидание 0)"
[ "$(grep -rnE 'push[^|]*(--force|--force-with-lease|(^| )-f( |$)|\+refs/)' bot/*.py bot/kit/workflows/ harness/bot_p1_refuse.sh | wc -l | tr -d ' ')" = "0" ] && ok "20 force-push в коде/обёртках/harness отсутствует" || bad "20 force-push найден"
grep -n 'def dumps' bot/yamlmini.py > /dev/null || echo "  (проверка сигнатуры dumps для мутанта 7)"

echo "== 3. трасса операций: pull → (write/check_line/check_pair/add) → commit; ретраи — числа из прогона"
$PY - <<'PY' && ok "трасса напечатана; между pull и commit нет сетевых/чужих файловых операций; ретраи < окна retention" || bad "трасса/ретраи"
# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll
from botrepo import Stand, FakeTransport, msg
s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml"))
bad = 0
try:
    t = FakeTransport([msg("2ч 40м созвон\nхвост")]); ctx = poll.Ctx(s.root, t, cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None)
    poll.run_once(ctx)
    for l in ctx.trace.lines(): print("    " + l)
    between = ctx.trace.between("pull", "commit")
    net = [o for o in between if o["op"] in ("getUpdates", "push", "send", "fetch", "merge")]
    foreign = [o for o in between if o["op"] == "write" and not (o["target"].startswith("time/") or o["target"].startswith(".workshop/"))]
    ops = [o["op"] for o in ctx.trace.ops]
    print("  между pull и commit: операций %d, сетевых %d, чужих файловых %d; check_line<commit: %s; check_pair<commit: %s" % (len(between), len(net), len(foreign), ops.index("check_line") < ops.index("commit"), ops.index("check_pair") < ops.index("commit")))
    if net or foreign or not (ops.index("check_line") < ops.index("commit") < ops.index("push")): bad = 1
finally:
    s.close()
# ретраи с дефолтным бэкоффом конфига комплекта — числа из прогона
tpl = yamlmini.load_file("bot/kit/templates/bot.yaml"); attempts = tpl["retry"]["push_max_attempts"]; backoff = tpl["retry"]["push_backoff_seconds"]; retention_h = 24
s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml")); cfg["retry"] = tpl["retry"]; s.deny_push(True); waits = []
try:
    t = FakeTransport([msg("1ч ретраи")]); ctx = poll.Ctx(s.root, t, cfg, botrepo.VALIDATOR, bot_username="x", sleeper=waits.append)
    r = poll.run_once(ctx)
    pushes = len([o for o in ctx.trace.ops if o["op"] == "push"])
    print("  ретраи: попыток %d (конфиг %d), интервалы бэкоффа %s, суммарно %d с; окно retention ~%d ч = %d с; строго меньше: %s; исход %s" % (pushes, attempts, waits, sum(waits), retention_h, retention_h * 3600, sum(waits) < retention_h * 3600, r["held"][1]))
    if not (pushes == attempts and sum(waits) < retention_h * 3600 and r["held"][1] == "retries_exhausted"): bad = 1
finally:
    s.close()
sys.exit(bad)
PY

echo "== 4. обёртка поллера тонкая: предикат T1 + шаг hooksPath; пять негативных мутаций"
$PY bot/kit/wrapper_predicate.py bot/kit/workflows/poller.yml --contract "$TW" --require-hooks-path > "$WORK/wp.txt"; RC=$?
sed 's/^/  /' "$WORK/wp.txt"
grep -q '^structure: PASS' "$WORK/wp.txt" && [ $RC -le 1 ] && ok "poller.yml: structure PASS (pins — заполняет релиз), hooksPath принят" || bad "poller.yml предикат"
$PY - <<'PY' > "$WORK/pm.txt"
import re
base = open("bot/kit/workflows/poller.yml", encoding="utf-8").read()
muts = {
 "if_in_step": base.replace("      - name: poll\n", "      - name: poll\n        if: always()\n"),
 "policy_literal_in_run": base.replace("run: python3 .workshop/bot/poll.py\n", "run: python3 .workshop/bot/poll.py --retries 20\n"),
 "two_calls_in_run": base.replace("run: python3 .workshop/bot/poll.py\n", "run: python3 .workshop/bot/poll.py && git push\n"),
 "hooks_path_step_missing": base.replace("      - name: hooks path\n        run: git config core.hooksPath .workshop/hooks\n", ""),
 "unknown_top_key": base.replace("permissions:\n", "defaults:\n  run:\n    shell: bash\npermissions:\n"),
}
for k, v in muts.items():
    assert v != base, k
    open("%s/pm-%s.yml" % (__import__("os").environ["WORK"], k), "w", encoding="utf-8").write(v)
print("\n".join(muts))
PY
PM=0
for mname in $(cat "$WORK/pm.txt"); do
  OUT=$($PY bot/kit/wrapper_predicate.py "$WORK/pm-$mname.yml" --contract "$TW" --require-hooks-path); RC=$?
  echo "  мутация $mname → $(echo "$OUT" | head -1) (rc=$RC)"
  echo "$OUT" | grep -q "^structure: FAIL.*$mname" && [ $RC -eq 2 ] || PM=1
done
[ $PM -eq 0 ] && ok "пять негативных мутаций poller.yml → FAIL поимённо" || bad "негативные мутации poller.yml"

echo "== 5. Р1: положительная сторона (harness/bot_vs_client.sh, не правится) и отказ (harness/bot_p1_refuse.sh)"
BIN="$BIN" bash harness/bot_vs_client.sh > "$WORK/bvc.txt" 2>&1; RC=$?; tail -1 "$WORK/bvc.txt" | sed 's/^/  /'
[ $RC -eq 0 ] && grep -q "ВСЕ ЧЕТЫРЕ ВЕТВИ PASS" "$WORK/bvc.txt" && [ -z "$(git diff --stat harness/bot_vs_client.sh)" ] && ok "bot_vs_client.sh: ВСЕ ЧЕТЫРЕ ВЕТВИ PASS, файл не изменён" || bad "bot_vs_client.sh rc=$RC"
BIN="$BIN" bash harness/bot_p1_refuse.sh > "$WORK/p1.txt" 2>&1; RC=$?; grep -E '^\(|^  (PASS|FAIL)|^Р1' "$WORK/p1.txt" | sed 's/^/  /'
[ $RC -eq 0 ] && grep -q "ВСЕ ВЕТВИ PASS" "$WORK/p1.txt" && ok "bot_p1_refuse.sh: отказ Р1 — не сливает, отвечает, алярм, origin не тронут" || bad "bot_p1_refuse.sh rc=$RC"

echo "== 6. идемпотентность и наложение: батч дважды подряд и из двух клонов — sha256 табеля и число коммитов как у однократного"
$PY - <<'PY' && ok "идемпотентность: два прогона подряд cmp-равны; наложение двух клонов сходится на табеле (1 строка, тот же sha)" || bad "идемпотентность"
# -*- coding: utf-8 -*-
import hashlib, json, os, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll
from botrepo import Stand, FakeTransport, git
FIXED = "019550fa-1ea0-773c-b820-1e2b73ab4901"   # фиксированный минт: id контейнера детерминирован, sha табеля сравним между стендами (якоря/id комментов и так детерминированы из identity)
doc = json.load(open("bot/tests/fixtures/t3/batch-start-stop.json", encoding="utf-8")); ups = doc["updates"]
TS = "time/TIMESHEET-2026-09-dev-one.md"
def run(root, cfg, transport): poll.run_once(poll.Ctx(root, transport, cfg, botrepo.VALIDATOR, mint_id=lambda: FIXED, bot_username="x", sleeper=lambda x: None))
def full(transport): transport.get_updates = lambda **kw: list(ups); return transport
s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml"))
try:
    run(s.root, cfg, FakeTransport(ups)); once = (hashlib.sha256(s.read(TS)).hexdigest()[:12], git(s.origin, "rev-list", "--count", "main").strip())
    run(s.root, cfg, full(FakeTransport(ups)))
    twice = (hashlib.sha256(s.read(TS)).hexdigest()[:12], git(s.origin, "rev-list", "--count", "main").strip())
    # НАЛОЖЕНИЕ двух клонов на ОДИН origin тем же батчем (случай, который concurrency-группа D09 запрещает
    # по построению — §1Б(г) случай 1): проверяем, что даже без неё ДУРАБЛЬНЫЙ след — табель — сходится:
    # одна строка, тот же sha (якорь из identity закрытия детерминирован; union дедуплицирует байт-идентичное).
    s2 = Stand(); cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
    try:
        c2 = s2.other_clone(); run(s2.root, cfg2, FakeTransport(ups)); run(c2, cfg2, full(FakeTransport(ups)))
        git(s2.root, "pull", "-q", "origin", "main")
        overlap = (hashlib.sha256(s2.read(TS)).hexdigest()[:12], s2.read(TS).count(b"<!--t:"))
    finally: s2.close()
    print("  однократно: sha %s, коммитов %s; дважды подряд: sha %s, коммитов %s; наложение клонов: sha %s, строк %d" % (once + twice + overlap))
    seq_ok = once == twice                                    # два прогона подряд — cmp-равны (табель И число коммитов)
    overlap_ok = overlap == (once[0], 1)                      # наложение — тот же табель, одна строка (число коммитов расходится — это и есть гонка, снимаемая concurrency-группой)
    sys.exit(0 if seq_ok and overlap_ok else 1)
finally: s.close()
PY

echo "== 7. второго писателя нет: callback не даёт времени; ожидание из состояния читается после pull"
CBD=$(grep -cE 'callback_query.*"date"|cq\.get\("date"\)' bot/parse.py bot/poll.py | awk -F: '{s+=$2} END {print s}')
echo "  чтений времени из callback_query: $CBD"
[ "$CBD" = "0" ] && ok "время из callback_query не читается (греп)" || bad "время из callback читается"

echo "== ИТОГ"
echo "SELFCHECK T3: PASS=$PASSES FAIL=$FAILS"
[ $FAILS -eq 0 ] && echo "SELFCHECK T3: ALL PASS" || echo "SELFCHECK T3: FAILURES PRESENT"
exit $FAILS
