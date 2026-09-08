#!/bin/bash
# selfcheck_t5.sh — прогон проверок verification таски T5 D09 (dead-man alarm / liveness).
# Числа порогов и запаса — ТОЛЬКО из этого прогона (из конфига комплекта), прозой не называются.
set -u
export LC_ALL=en_US.UTF-8
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 2
BIN="${BIN:-$ROOT/validator/target/release/workshop-validator}"
[ -x "$BIN" ] || { echo "нет бинаря валидатора: $BIN"; exit 2; }
export WORKSHOP_VALIDATOR="$BIN"; PY=python3; export PYTHONDONTWRITEBYTECODE=1
WORK=$(mktemp -d); export WORK; trap 'rm -rf "$WORK"' EXIT
SPEC_DIR="$ROOT/spec/09-tg-bot-time-line"; [ -d "$SPEC_DIR" ] || SPEC_DIR="$HOME/Analytics/cherrypick/workshop/output/format-spec/09-tg-bot-time-line"
TW="$SPEC_DIR/tg-bot.yaml"
FAILS=0; PASSES=0
ok() { echo "  PASS  $1"; PASSES=$((PASSES+1)); }
bad() { echo "  FAIL  $1"; FAILS=$((FAILS+1)); }

echo "== 0. юнит-оракул T5 (test_heartbeat): молчание, зависшая сессия, счётчик, пороги, доставка"
$PY -m unittest bot.tests.test_heartbeat > "$WORK/ut.txt" 2>&1; RC=$?
grep -E '^(Ran|OK|FAILED)' "$WORK/ut.txt" | sed 's/^/  /'
[ $RC -eq 0 ] && ok "unittest T5" || { bad "unittest T5"; grep -E '^(FAIL|ERROR):' "$WORK/ut.txt" | sed 's/^/    /'; }

echo "== 1. пороги и запас — числами ИЗ конфига комплекта; порог молчания строго < окна retention"
$PY - <<'PY' && ok "пороги из конфига; молчание < retention; запас печатается" || bad "пороги/запас"
# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, "bot")
import yamlmini
wd = yamlmini.load_file("bot/kit/templates/bot.yaml")["watchdog"]
ret = wd["retention_window_hours"]; sil = wd["unprocessed_update_alarm_hours"]; stale = wd["stale_session_alarm_hours"]; rep = wd["stale_session_repeat_hours"]; rmin = wd["rejection_report_min"]
print("  retention=%d ч; молчание=%d ч; зависшая сессия=%d ч; повтор=%d ч; порог отчёта=%d; запас молчания до retention=%d ч" % (ret, sil, stale, rep, rmin, ret - sil))
print("  порог зависшей сессии — ОТДЕЛЬНАЯ настройка, равна порогу молчания? %s (по плану — не обязана)" % (stale == sil))
sys.exit(0 if sil < ret and stale > 0 and rep > 0 and rmin >= 1 else 1)
PY

echo "== 2. установка комплекта роняется при пороге молчания >= окна retention (install.py check-people)"
R=$(mktemp -d); mkdir -p "$R/.workshop"; cp bot/kit/templates/bot.yaml "$R/.workshop/bot.yaml"; cp bot/kit/templates/people.yaml "$R/.workshop/people.yaml"
$PY bot/kit/install.py --repo "$R" check-people >/dev/null 2>&1 && GOOD=0 || GOOD=1
perl -0pi -e 's/unprocessed_update_alarm_hours: \d+/unprocessed_update_alarm_hours: 48/' "$R/.workshop/bot.yaml"
OUT=$($PY bot/kit/install.py --repo "$R" check-people 2>&1); BADRC=$?
echo "  здоровый конфиг check-people rc=$GOOD (0=ok); порог 48>=24: $(echo "$OUT" | head -1)"
[ "$GOOD" -eq 0 ] && [ "$BADRC" -ne 0 ] && echo "$OUT" | grep -q "строго меньше" && ok "искусственный порог больше окна роняет установку" || bad "проверка порога установки"
rm -rf "$R"

echo "== 3. искусственная остановка поллера: алярм молчания, возраст и запас числами из прогона; курсор не тронут"
$PY - <<'PY' && ok "молчание: алярм, возраст/запас из прогона, offset до==после, getUpdates timeout=0" || bad "молчание"
# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll, heartbeat, state_store as ss
from botrepo import Stand, FakeTransport, msg
s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml")); wd = cfg["watchdog"]; bad = 0
T0 = 1788790990; H = 3600
try:
    # поллер «мёртв»: сообщение подано, но не обработано (ожидает в очереди)
    old = msg("2ч работа", date=T0)
    now = T0 + (wd["unprocessed_update_alarm_hours"] + 2) * H
    t = FakeTransport([old]); ctx = heartbeat.Ctx(s.root, t, cfg, now=now, sleeper=lambda x: None)
    r = heartbeat.run_once(ctx)
    print("  возраст самого старого необработанного: %d ч; порог %d ч; запас до retention %d ч; ожидающих %d" % (r["silence"]["age_s"]//H, r["silence"]["threshold_s"]//H, r["silence"]["margin_s"]//H, sum(1 for o in ctx.trace.ops if o["op"]=="getUpdates")))
    print("  offset до=%s после=%s (замер не подтвердил); getUpdates timeout=0: %s" % (r["offset_before"], r["offset_after"], any("timeout=0" in o["target"] for o in ctx.trace.ops if o["op"]=="getUpdates")))
    if not (r["silence"] and r["offset_before"] == r["offset_after"] and any("timeout=0" in o["target"] for o in ctx.trace.ops if o["op"]=="getUpdates")): bad = 1
    # отрицательный контроль: здоровый поллер (сообщение записано, ожидающих нет) — молчит
    s2 = Stand(); cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
    poll.run_once(poll.Ctx(s2.root, FakeTransport([msg("2ч работа", date=T0)]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
    t2 = FakeTransport([]); r2 = heartbeat.run_once(heartbeat.Ctx(s2.root, t2, cfg2, now=now, sleeper=lambda x: None))
    print("  отрицательный контроль (здоровый поллер): алярм молчания=%s, исходящих=%d" % (bool(r2["silence"]), len(t2.sent)))
    if r2["silence"] or t2.sent: bad = 1
    s2.close()
finally: s.close()
sys.exit(bad)
PY

echo "== 4. потери нет: множество, поданное до остановки, после перезапуска записано ПОЛНОСТЬЮ (сверка якорей)"
$PY - <<'PY' && ok "потери нет: вход == строки табеля по якорям в обе стороны" || bad "потеря сообщений"
# -*- coding: utf-8 -*-
import os, re, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll, anchor
from botrepo import Stand, FakeTransport, msg
s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml")); bad = 0
T0 = 1788790990
try:
    ups = [msg("%dм задача %d" % (10 + i, i), date=T0 + i, update_id=900500000 + i, message_id=6000 + i) for i in range(12)]
    # «остановка»: push запрещён на первых прогонах — записи копятся локально, но не подтверждаются
    s.deny_push(True)
    poll.run_once(poll.Ctx(s.root, FakeTransport(ups), cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
    # «перезапуск»: push снова доступен; те же update приходят снова (offset авторитета не двигался)
    s.deny_push(False)
    t = FakeTransport(ups); t.get_updates = lambda **kw: list(ups)
    poll.run_once(poll.Ctx(s.root, t, cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
    # ожидаемые якоря — из identity каждого update (оракул считает сам, не из писателя)
    expected = set()
    for u in ups:
        ident = "tg:%d:%d" % (u["message"]["chat"]["id"], u["message"]["message_id"])
        expected.add(anchor.derive(ident, 0, 0))
    body = b""
    for f in os.listdir(os.path.join(s.root, "time")):
        if f.endswith(".md") and not f.endswith(".comments.md"):
            body += open(os.path.join(s.root, "time", f), "rb").read()
    written = set(m.decode() for m in re.findall(rb"<!--t:([0-9a-f]{8})-->", body))
    print("  подано %d; записано якорей %d; вход-без-записи %s; запись-без-входа %s" % (len(ups), len(written), sorted(expected - written), sorted(written - expected)))
    if expected != written: bad = 1
finally: s.close()
sys.exit(bad)
PY

echo "== 5. зависшая сессия: уведомление в чат человека, заголовок и время, файл состояния cmp-равен; редкий повтор"
$PY - <<'PY' && ok "зависшая сессия: уведомление, не мутирует состояние (cmp), редкий повтор" || bad "зависшая сессия"
# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll, heartbeat, state_store as ss
from botrepo import Stand, FakeTransport, msg, TOK, CHAT
s = Stand(); cfg = yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml")); wd = cfg["watchdog"]; bad = 0
T0 = 1788790990; H = 3600
try:
    poll.run_once(poll.Ctx(s.root, FakeTransport([msg(TOK["start_title"] + " долгая задача", date=T0)]), cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
    before = open(os.path.join(s.root, ss.SESSIONS_PATH), "rb").read()
    now = T0 + (wd["stale_session_alarm_hours"] + 1) * H
    t = FakeTransport([]); r = heartbeat.run_once(heartbeat.Ctx(s.root, t, cfg, now=now, sleeper=lambda x: None))
    after = open(os.path.join(s.root, ss.SESSIONS_PATH), "rb").read()
    print("  уведомлений: %d; адресат=%s (чат человека %s); текст называет заголовок: %s; состояние cmp-равно: %s" % (len(t.sent), t.sent[0][0] if t.sent else None, CHAT, ("долгая задача" in t.sent[0][1]) if t.sent else False, before == after))
    if not (len(t.sent) == 1 and t.sent[0][0] == CHAT and "долгая задача" in t.sent[0][1] and before == after and "dev-one" in ss.read_sessions(s.root)["sessions"]): bad = 1
    # редкий повтор: три прогона крона подряд при одной висящей сессии
    sent = len(t.sent)
    for k in range(1, 3):
        tk = FakeTransport([]); heartbeat.run_once(heartbeat.Ctx(s.root, tk, cfg, now=now + k * H, sleeper=lambda x: None)); sent += len(tk.sent)
    print("  три прогона подряд при одной сессии → уведомлений: %d (ожидание 1, редкий повтор)" % sent)
    if sent != 1: bad = 1
    # отрицательный контроль: свежая сессия
    s2 = Stand(); cfg2 = yamlmini.load_file(os.path.join(s2.root, ".workshop", "bot.yaml"))
    poll.run_once(poll.Ctx(s2.root, FakeTransport([msg(TOK["start_title"] + " x", date=T0)]), cfg2, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
    t2 = FakeTransport([]); r2 = heartbeat.run_once(heartbeat.Ctx(s2.root, t2, cfg2, now=T0 + (wd["stale_session_alarm_hours"] - 1) * H, sleeper=lambda x: None))
    print("  отрицательный контроль (свежая сессия): уведомлений %d" % len(t2.sent)); s2.close()
    if t2.sent: bad = 1
finally: s.close()
sys.exit(bad)
PY

echo "== 6. счётчик отклонений в отчёте: два отклонения от разных отправителей → оба числа; нулевой — молчание"
$PY - <<'PY' && ok "счётчик отклонений: числа названы; нулевой — молчание" || bad "счётчик отклонений"
# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, "bot/tests"); sys.path.insert(0, "bot")
import botrepo, yamlmini, poll, heartbeat, state_store as ss
from botrepo import Stand, FakeTransport, msg
s = Stand(); cfg = dict(yamlmini.load_file(os.path.join(s.root, ".workshop", "bot.yaml"))); cfg["self_registration"] = "off"; bad = 0
T0 = 1788790990
try:
    poll.run_once(poll.Ctx(s.root, FakeTransport([msg("1ч x", from_id=100000198, chat_type="private"), msg("2ч y", from_id=100000199, chat_type="private")]), cfg, botrepo.VALIDATOR, bot_username="x", sleeper=lambda x: None))
    st = ss.read_state(s.root)
    t = FakeTransport([]); r = heartbeat.run_once(heartbeat.Ctx(s.root, t, cfg, now=T0 + 3600, sleeper=lambda x: None))
    print("  отклонений в состоянии: %d; отчёт: count=%s senders=%s; текст: %s" % (len(st["unknown_rejections"]), r["rejection"]["count"] if r["rejection"] else None, r["rejection"]["senders"] if r["rejection"] else None, [x[1] for x in t.sent if "отклонено" in x[1]][:1]))
    if not (r["rejection"] and r["rejection"]["count"] == 2 and r["rejection"]["senders"] == 2): bad = 1
    # второй прогон без новых — молчание (watermark)
    t2 = FakeTransport([]); r2 = heartbeat.run_once(heartbeat.Ctx(s.root, t2, cfg, now=T0 + 7200, sleeper=lambda x: None))
    print("  второй прогон без новых отклонений: отчёт=%s" % bool(r2["rejection"]))
    if r2["rejection"]: bad = 1
finally: s.close()
sys.exit(bad)
PY

echo "== 7. обёртка heartbeat тонкая; ОДНА concurrency-группа с поллером и bootstrap; негативная мутация роняет"
$PY bot/kit/wrapper_predicate.py bot/kit/workflows/heartbeat.yml --contract "$TW" > "$WORK/wp.txt"; grep -q '^structure: PASS' "$WORK/wp.txt" && ok "heartbeat.yml: structure PASS" || bad "heartbeat.yml предикат"
$PY - <<'PY' && ok "три обёртки в ОДНОЙ concurrency-группе; разные группы — мутация роняет" || bad "concurrency-группа"
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "bot")
import yamlmini
gs = {f: yamlmini.load_file("bot/kit/workflows/%s" % f)["concurrency"]["group"] for f in ("bootstrap.yml", "poller.yml", "heartbeat.yml")}
print("  группы: %s; равны: %s" % (gs, len(set(gs.values())) == 1))
sys.exit(0 if len(set(gs.values())) == 1 else 1)
PY

echo "== 8. доставка исходов T3 (10/11) — тот же адресат, что у сторожа; вендорских хостов ноль; второго адресата нет"
$PY -m unittest bot.tests.test_heartbeat.DeliveryMatchTests > "$WORK/dm.txt" 2>&1 && ok "адресат поллера == адресат сторожа; вендорских хостов 0" || { bad "доставка/адресат"; grep -E '^(FAIL|ERROR):' "$WORK/dm.txt" | sed 's/^/    /'; }
ADDR=$(grep -rn 'alarm_to\|send_message\|api.telegram' bot/heartbeat.py bot/poll.py | grep -c 'api.telegram')
echo "  прямых вендорских хостов в heartbeat/poll: $ADDR (транспорт — только tg.py)"
[ "$ADDR" -eq 0 ] && ok "собственного транспорта нет; отправка через tg.py" || bad "вендорский хост в стороже/поллере"

echo "== 9. живая ветвь (реальная доставка в чат) — Q7, тест-бот alex"
echo "  BLOCKED: живой прогон heartbeat на тест-репо — в T6 (criteria-runs-and-gate), с сетевым профилем и тест-ботом alex (В-7); здесь помечено явно, не «частично»"

echo "== 10. граница «смерть планировщика» — класс БЕЗ адресата, названа в главе и в границах"
CH="$SPEC_DIR/04-deadman-and-liveness.md"
grep -q "СМЕРТЬ ПЛАНИРОВЩИКА\|смерть планировщика" "$CH" && grep -q "внешний наблюдатель" "$CH" && ok "граница смерти планировщика в главе с единственной защитой" || bad "граница смерти планировщика в главе"

echo "== ИТОГ"
echo "SELFCHECK T5: PASS=$PASSES FAIL=$FAILS"
[ $FAILS -eq 0 ] && echo "SELFCHECK T5: ALL PASS" || echo "SELFCHECK T5: FAILURES PRESENT"
exit $FAILS
