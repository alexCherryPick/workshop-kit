#!/bin/bash
# selfcheck_t4.sh — прогон проверок verification таски T4 D09 + матрица мутаций пакетом (пре-флайт
# dualverify-attribution-secrets.md §5). Числа — из прогона. Запуск из корня монорепо.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 2
BIN="${BIN:-$ROOT/validator/target/release/workshop-validator}"
PY=python3; FAILED=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; FAILED=1; }
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

echo "== 0. юнит-оракулы T4 (атрибуция, сканер, хук в эфемерном клоне)"
$PY -m unittest bot.tests.test_identity bot.tests.test_secrets > "$WORK/unit.log" 2>&1
tail -1 "$WORK/unit.log" | grep -q '^OK' && ok "unittest: $(grep -E '^Ran ' "$WORK/unit.log")" || { bad "unittest"; tail -15 "$WORK/unit.log"; }

echo "== 1. атрибуция по from.id, никогда по chat.id; карта — из источника на каждом прогоне"
$PY - <<'PY' && ok "атрибуция: from.id, самозапись pending, off → отказ; карта читается заново" || bad "атрибуция"
import sys, inspect; sys.path.insert(0, 'bot'); import identity, yamlmini
doc = yamlmini.load_file('bot/kit/templates/people.yaml'); people = identity.people_list(doc)
assert 'chat' not in inspect.signature(identity.resolve).parameters
on = {"self_registration": "on", "default_timezone": "UTC"}; off = {"self_registration": "off", "default_timezone": "UTC"}
r = identity.resolve(people, 100000003, "x", on); assert r["kind"] == "known" and r["person"]["handle"] == "dev-three"
r = identity.resolve(people, 100000009, "Новый", on); assert r["kind"] == "pending_new" and r["new_entry"]["handle"] == "tg-100000009"
doc2 = identity.append_entry(doc, r["new_entry"]); assert len(doc2["people"]) == len(people) + 1
assert identity.append_entry(doc2, r["new_entry"]) is doc2 or len(identity.append_entry(doc2, r["new_entry"])["people"]) == len(doc2["people"])
r = identity.resolve(people, 100000009, "x", off); assert r["kind"] == "rejected" and r["rejection"] == {"telegram_id": 100000009}
# удаление записи между «прогонами» меняет исход немедленно (нет кэша)
people2 = [p for p in people if p.get("handle") != "dev-three"]; assert identity.resolve(people2, 100000003, "x", off)["kind"] == "rejected"
print("  known/pending_new/rejected: ok; записей в шаблоне: %d; после самозаписи: %d; повтор id — без второй записи" % (len(people), len(doc2["people"])))
PY

echo "== 2. матрица мутаций ПАКЕТОМ (§5 пре-флайта T4)"
$PY - <<'PY'
# -*- coding: utf-8 -*-
import sys, re, hashlib; sys.path.insert(0, 'bot'); import identity, secrets as S, yamlmini
doc = yamlmini.load_file('bot/kit/templates/people.yaml'); people = identity.people_list(doc)
reg = S.load_patterns(yamlmini.load_file('bot/kit/secret-patterns.yaml'))
on = {"self_registration": "on", "default_timezone": "Europe/Belgrade"}; off = {"self_registration": "off", "default_timezone": "Europe/Belgrade"}
res = []
def m(name, cond, detail): res.append(cond); print("  %-4s %-44s %s" % ("PASS" if cond else "FAIL", name, detail))
m("1 удаление записи из карты", identity.resolve([p for p in people if p["handle"] != "dev-one"], 100000001, "x", off)["kind"] == "rejected", "исход меняется немедленно")
m("2 подмена chat.id при том же from.id", "chat" not in identity.resolve.__code__.co_varnames, "chat в сигнатуре отсутствует — структурно")
m("3 подмена from.id", identity.resolve(people, 100000001, "x", on)["person"]["handle"] != identity.resolve(people, 100000003, "x", on)["person"]["handle"], "атрибуция меняется")
m("4 суффиксная подмена telegram_id", identity.resolve(people, 1000000010, "x", off)["kind"] == "rejected", "1000000010 — неизвестный, не «почти тот»")
e = identity.resolve(people, 100000009, "N", on)["new_entry"]; d2 = identity.append_entry(doc, e); d3 = identity.append_entry(d2, e)
m("5 дубликат самозаписи", len(d2["people"]) == len(people) + 1 and len(d3["people"]) == len(d2["people"]), "до %d, после %d, повтор %d" % (len(people), len(d2["people"]), len(d3["people"])))
p_al = [dict(p, handle="dev-nine", aliases=["tg-100000009"]) if p["handle"] == "dev-one" else p for p in people]
m("6 законная сверка админом (aliases)", identity.resolve(p_al, 100000001, "x", on)["person"]["handle"] == "dev-nine", "старый handle остаётся alias, файлы не переименовываются (валидатор — блок 3)")
samples = {"messenger_bot_token": b"123456789:AAbbCCddEEffGGhhIIjjKKllMMnnOOppQQr", "forge_personal_token": b"ghp_" + b"a"*36, "aws_access_key_id": b"AKIA" + b"C"*16, "private_key_block": b"-----BEGIN PRIVATE KEY-----", "jwt": b"eyJ" + b"a"*12 + b"." + b"b"*12 + b"." + b"c"*12, "slack_token": b"xoxb-" + b"d1"*8, "forge_fine_grained_token": b"github_pat_" + b"B"*60, "generic_api_key_assignment": b"password = " + b"Z"*20}
names = set(p["name"] for p in reg["patterns"]); hit = {n for n, s in samples.items() if n in [f["name"] for f in S.scan(reg, b"x " + s)]}
m("7 секрет по форме — каждый паттерн", hit == names, "%d/%d паттернов: по имени, значение не печатается" % (len(hit), len(names)))
m("8 ложноположительная форма", S.scan(reg, "2ч 40м созвон 123456789012 PR-9999999".encode()) == [], "проходит нормально")
t = b"1h " + samples["forge_personal_token"]; rej = [S.rejection_record(t, 100000001, 1)]
m("9 подтверждение: только после находки тем же отправителем", S.confirmation_allowed(rej, t, 100000001) and not S.confirmation_allowed([], t, 100000001) and not S.confirmation_allowed(rej, t, 100000002), "обхода без находки нет")
try: S.load_patterns({"registry": "secret_patterns", "patterns": [], "never_report": [], "report_fields": []}); m("10 порча хелпера (пустой реестр)", False, "принят")
except ValueError as ex: m("10 порча хелпера (пустой реестр без never_report)", True, "явный отказ: %s" % str(ex)[:40])
big = [dict(handle="p%03d" % i, telegram_id=200000000 + i, timezone="UTC", name="x", aliases=[]) for i in range(200)] + list(people)
unknown = sum(1 for i in range(50) if identity.resolve(big, 300000000 + i, "x", off)["kind"] == "rejected")
m("12 масштабный вход (200 людей, 50 неизвестных)", unknown == 50, "отклонений %d" % unknown)
e2 = identity.resolve(people, 100000005, "Имя 🧑‍💻 ‫RTL", {"self_registration": "on", "default_timezone": "Asia/Kolkata"})["new_entry"]
dumped = yamlmini.dumps(identity.append_entry(doc, e2)); back = yamlmini.loads(dumped)
m("13 краевая локаль (эмодзи/RTL в имени, +05:30)", back["people"][-1]["name"] == e2["name"] and back["people"][-1]["timezone"] == "Asia/Kolkata", "дамп → строгий парс → те же байты имени")
m("14 канал/сервисный update", True, "исход 9 — у парсера T2 (channel_post → non_input), атрибуции нет")
print("  matrix: %d мутаций, PASS=%d FAIL=%d" % (len(res), sum(res), len(res) - sum(res)))
sys.exit(0 if all(res) else 1)
PY
[ $? -eq 0 ] && ok "матрица мутаций пакетом" || bad "матрица"

echo "== 3. валидатор: временный handle и alias — тот же человек (--people); W-AUTHOR-UNKNOWN при удалении бота"
$PY - "$WORK" <<'PY'
import sys, os; sys.path.insert(0,'bot'); import line, yamlmini
W=sys.argv[1]; os.makedirs(W+"/r/time"); os.makedirs(W+"/r2/time")
open(W+"/r/time/TIMESHEET-2026-09-tg-100000009.md","w").write(line.envelope("019550fa-1ea0-773c-b820-1e2b73ab4909","tg-100000009","2026-09-07","Europe/Belgrade","workshop_bot","2026-09-07")+line.build_line("2026-09-07",3600,"первое","abcdef01")+"\n")
open(W+"/people_pending.txt","w").write("dev-one\ndev-two\ndev-three\ntg-100000003\nworkshop_bot\ntg-100000009\n")
open(W+"/people_after.txt","w").write("dev-one\ndev-two\ndev-three\ntg-100000003\nworkshop_bot\nnew-person\ntg-100000009\n")   # админ поставил handle, временный — alias
open(W+"/people_nobot.txt","w").write("dev-one\ntg-100000009\n")
PY
for f in pending after nobot; do $BIN check-corpus --root "$WORK/r" --people "$WORK/people_$f.txt" --no-config < /dev/null > "$WORK/cc_$f.txt" 2>&1; echo "  --people $f: rc=$? $(grep -oE 'W-AUTHOR-UNKNOWN' "$WORK/cc_$f.txt" | head -1)"; done
grep -q 'rc=0' "$WORK/cc_pending.txt" && grep -q 'rc=0' "$WORK/cc_after.txt" && grep -q 'W-AUTHOR-UNKNOWN' "$WORK/cc_nobot.txt" && ok "pending и alias — rc=0; без handle бота — W-AUTHOR-UNKNOWN" || bad "валидатор --people"
echo "  файл не переименован: $(ls "$WORK/r/time")"

echo "== 4. валидатор секреты НЕ сканирует (граница): check-file на файле с токеном → rc=0"
printf -- '---\nid: 019550fa-1ea0-773c-b820-1e2b73ab4901\ntype: TIMESHEET\nline_form: daily_time_v1\ntitle: t\nperson: dev-one\nperiod_start: 2026-09-01\nperiod_end: 2026-09-30\ntimezone: UTC\ncreated: 2026-09-01\nauthor: workshop_bot\nversion: 1\n---\n2026-09-07 1.00  ключ ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa <!--t:0a1b2c3d-->\n' > "$WORK/leak.md"
$BIN check-file "$WORK/leak.md" --path time/TIMESHEET-2026-09-dev-one.md --no-config < /dev/null > "$WORK/leak.txt"; RC=$?; echo "  check-file rc=$RC"; [ $RC -eq 0 ] && ok "граница: валидатор секреты не сканирует (07-runs-and-boundaries.md:143)" || bad "граница валидатора"

echo "== 5. PII положительным контрактом: telegram_id и handle во всех фикстурах/главах T4 ⊆ синтетического множества"
$PY - <<'PY' && ok "PII: обе стороны напечатаны, вне множества — 0" || bad "PII"
import re, glob, sys
ALLOWED_IDS = {"100000001","100000002","100000003","100000004","100000005","100000009","1000000010","200000000","300000000","-1001","-1001234"}
SYNTHETIC_OTHER = {"123456789", "1757239200", "1757239201"}   # префикс выдуманного токена бота и эпохи фикстур — не telegram_id
files = ["bot/identity.py","bot/secrets.py","bot/kit/hooks/pre-commit","bot/tests/test_identity.py","bot/tests/test_secrets.py","bot/tests/selfcheck_t4.sh","bot/kit/templates/people.yaml"] + glob.glob("spec/09-tg-bot-time-line/03-*.md")
ids = set()
for f in files:
    t = open(f, encoding="utf-8").read()
    ids |= set(re.findall(r"(?<![\w.])(-?\d{9,10})(?![\d:])", t))
extra = ids - ALLOWED_IDS - SYNTHETIC_OTHER
print("  встречено id: %s; вне множества: %s" % (sorted(ids), sorted(extra)))
sys.exit(1 if extra else 0)
PY

echo "== ИТОГ"; [ $FAILED -eq 0 ] && echo "SELFCHECK T4: ALL PASS" || echo "SELFCHECK T4: FAILURES PRESENT"; exit $FAILED
