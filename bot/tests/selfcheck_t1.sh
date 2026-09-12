#!/bin/bash
# selfcheck_t1.sh — прогон проверок verification таски T1 (D09) на СВОЁМ срезе. Владелец — T1.
# Запуск из корня среза (где лежат bot/ и output/): bash bot/tests/selfcheck_t1.sh
# Числа печатаются ПРОГОНОМ; ничего вне mktemp не пишется (кроме перегенерации инструкции — она
# обязана быть идемпотентной, и это отдельная проверка). Валидатор: BIN (дефолт — монорепо).
set -u
export LC_ALL=en_US.UTF-8
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 2
BIN="${BIN:-$HOME/repos/workshop/validator/target/release/workshop-validator}"
GOLDEN_TS="${GOLDEN_TS:-$HOME/repos/workshop/golden/valid/TIMESHEET-2026-08-dev1.md}"
# Каталог глав D09: в планировочном репо — output/format-spec/09-tg-bot-time-line; в монорепо —
# зеркало spec/09-tg-bot-time-line (D05 §6.1: spec/ — спека как данные). SPEC_DIR переопределяет.
SPEC_DIR="${SPEC_DIR:-}"
if [ -z "$SPEC_DIR" ]; then
  if [ -f spec/09-tg-bot-time-line/tg-bot.yaml ]; then SPEC_DIR=spec/09-tg-bot-time-line
  else SPEC_DIR=output/format-spec/09-tg-bot-time-line; fi
fi
CH="$SPEC_DIR/00-bot-contract-and-kit.md"
TW="$SPEC_DIR/tg-bot.yaml"
export SPEC_DIR
# Тождество зеркала: если рядом есть и оригинал планировочного репо, sha256 обязаны совпасть.
ORIG_DIR="${ORIG_DIR:-$HOME/Analytics/cherrypick/workshop/output/format-spec/09-tg-bot-time-line}"
if [ "$SPEC_DIR" != "$ORIG_DIR" ] && [ -f "$ORIG_DIR/tg-bot.yaml" ]; then
  for f in tg-bot.yaml 00-bot-contract-and-kit.md; do
    a=$(shasum -a 256 "$SPEC_DIR/$f" | cut -c1-16); b=$(shasum -a 256 "$ORIG_DIR/$f" | cut -c1-16)
    echo "  mirror identity $f: spec=$a orig=$b"
    [ "$a" = "$b" ] || { echo "  FAIL  зеркало spec/ расходится с оригиналом планировочного репо: $f"; exit 2; }
  done
fi
PY=python3
PASS_N=0; FAIL_N=0
ok()  { echo "  PASS  $1"; PASS_N=$((PASS_N+1)); }
bad() { echo "  FAIL  $1"; FAIL_N=$((FAIL_N+1)); }
WORK=$(mktemp -d); export WORK; trap 'rm -rf "$WORK"' EXIT
export PYTHONPATH="$ROOT/bot"

echo "== 0. окружение"
echo "  python3: $($PY --version 2>&1); git: $(git --version); валидатор: $BIN"
[ -x "$BIN" ] && ok "бинарь валидатора доступен" || bad "нет бинаря валидатора: $BIN"

echo "== 1. юнит-оракулы (python3 -m unittest discover -s bot/tests)"
UT=$($PY -m unittest discover -s bot/tests 2>&1 | tail -3)
echo "$UT" | sed 's/^/  /'
echo "$UT" | grep -q '^OK' && ok "unittest: OK" || bad "unittest: есть провалы"

echo "== 2. перечень исходов: ровно 20, пять полей, признак коммента, не коды валидатора"
"$BIN" --dump-identifiers --kind code < /dev/null > "$WORK/codes.txt"
echo "  дамп кодов валидатора: $(wc -l < "$WORK/codes.txt" | tr -d ' ') строк"
$PY - "$TW" "$WORK/codes.txt" <<'EOF' && ok "исходы: 20 позиций × 5 полей, признак у всех, ∩ дамп = ∅" || bad "исходы: см. выше"
import sys, yamlmini
tw = yamlmini.load_file(sys.argv[1]); codes = set(open(sys.argv[2]).read().split())
outs = tw["outcomes"]; ids = [o["id"] for o in outs]
print("  исходов в реестре: %d" % len(outs))
must = ["identical_repeat","recorded_with_warning","run_refused","tool_failure","non_input","session_opened",
        "session_closed_recorded","reask_start_already_open","reask_stop_without_open","session_stale","help_given","last_list_given"]
bad = []
if len(outs) != 20: bad.append("число исходов %d != 20" % len(outs))
if len(set(ids)) != 20: bad.append("дубли id")
if sorted(o["ordinal"] for o in outs) != list(range(1, 21)): bad.append("ординалы не 1..20")
for m in must:
    if m not in ids: bad.append("нет обязательного исхода %s" % m)
for o in outs:
    for f in ("reply","offset","transition","comment","address"):
        if not o.get(f): bad.append("исход %s: поле %s пусто" % (o["id"], f))
    if o["offset"] not in ("advance","hold","not_applicable"): bad.append("исход %s: offset %r" % (o["id"], o["offset"]))
    if not o["address"].startswith("00-bot-contract-and-kit.md §1 №исход-%d" % o["ordinal"]): bad.append("исход %s: адрес" % o["id"])
    if o["comment"] == "never" and o["id"] in ("recorded","recorded_with_warning","session_opened","session_closed_recorded"): bad.append("исход %s: признак коммента never" % o["id"])
    if o["comment"] != "never" and o["id"] not in ("recorded","recorded_with_warning","session_opened","session_closed_recorded"): bad.append("исход %s: признак коммента %r у нулевого по записи" % (o["id"], o["comment"]))
inter = set(ids) & codes
if inter: bad.append("исходы совпадают с кодами валидатора: %s" % sorted(inter))
print("  признаки коммента: " + ", ".join("%d=%s" % (o["ordinal"], o["comment"]) for o in outs if o["comment"] != "never"))
print("  offset hold у: " + ", ".join(str(o["ordinal"]) for o in outs if o["offset"] == "hold"))
for b in bad: print("  !! " + b)
sys.exit(1 if bad else 0)
EOF

echo "== 3. таблица переходов: декартово произведение {closed, open} × входы реестра"
$PY - "$TW" bot/kit/commands.yaml <<'EOF' && ok "переходы: все клетки определены" || bad "переходы: см. выше"
import sys, yamlmini
tw = yamlmini.load_file(sys.argv[1]); cmds = [c["id"] for c in yamlmini.load_file(sys.argv[2])["commands"]]
states = tw["session_states"]; cells = dict(((t["state"], t["input"]), t) for t in tw["transitions"])
ids = set(o["id"] for o in tw["outcomes"]); bad = []
expected = [(s, c) for s in states for c in cmds]
print("  состояний: %d, входов реестра: %d, клеток ожидается: %d, в таблице: %d" % (len(states), len(cmds), len(expected), len(cells)))
prec = tw["transition_precedence"]; update_ids = [o["id"] for o in tw["outcomes"] if o["source"] == "update" and o["id"] != "non_input"]
for key in expected:
    t = cells.get(key)
    if t is None: bad.append("клетка %s не определена" % (key,)); continue
    if not t.get("next_state") or not t.get("outcomes"): bad.append("клетка %s пуста" % (key,))
    for o in t["outcomes"]:
        if o not in ids: bad.append("клетка %s: неизвестный исход %s" % (key, o))
        if o not in prec: bad.append("клетка %s: исход %s вне transition_precedence" % (key, o))
if len(cells) != len(expected): bad.append("лишние клетки")
if len(prec) != len(set(prec)): bad.append("transition_precedence: дубли")
if set(prec) != set(update_ids): bad.append("transition_precedence != исходы update (без non_input): %s" % sorted(set(prec) ^ set(update_ids)))
notes = tw.get("transition_notes") or []
print("  порядок перехвата (transition_precedence): %d исходов; нот клеток: %d (%s)" % (len(prec), len(notes), "; ".join(n["cell"] for n in notes)))
if not any(n["cell"] == "open × stop" and "reask_invalid" in n["today"] and "alex" in n["open_question"] for n in notes): bad.append("нет ноты open × stop (reask_invalid; вопрос alex)")
for b in bad: print("  !! " + b)
sys.exit(1 if bad else 0)
EOF

echo "== 4. реестр команд — единственный источник; генератор детерминирован и чувствителен"
N_CMD=$($PY -c "import yamlmini;print(len(yamlmini.load_file('bot/kit/commands.yaml')['commands']))")
echo "  реестр команд: позиций $N_CMD"
[ "$N_CMD" -eq 8 ] && ok "реестр команд: ровно 8 позиций" || bad "реестр команд: $N_CMD позиций"
$PY -c "import yamlmini;c=yamlmini.load_file('bot/kit/commands.yaml')['commands'];import sys;sys.exit(0 if not [x for x in c if x['time_bearing'] and x['callback_allowed']] else 1)" \
  && ok "ни одна позиция time_bearing: true не исполнима кнопкой" || bad "time_bearing+callback_allowed найдены"
for sub in help short commands-block steps-block; do
  $PY bot/kit/build_help.py $sub > "$WORK/g1.txt"; $PY bot/kit/build_help.py $sub > "$WORK/g2.txt"
  cmp -s "$WORK/g1.txt" "$WORK/g2.txt" && ok "build_help $sub: два прогона побайтово равны ($(wc -c < "$WORK/g1.txt" | tr -d ' ') байт)" || bad "build_help $sub: недетерминирован"
done
cp bot/kit/commands.yaml "$WORK/cmd-mut.yaml"
printf '  - id: zz_probe\n    name: "/zzprobe"\n    token: "/zzprobe"\n    synopsis: ""\n    grammar: x\n    example: "/zzprobe"\n    time_bearing: false\n    callback_allowed: false\n    tail_rule: none\n    outcomes: [help_given]\n    help_text: проба\n    guide_text: |\n      проба\n' >> "$WORK/cmd-mut.yaml"
$PY bot/kit/build_help.py help --commands "$WORK/cmd-mut.yaml" > "$WORK/h-mut.txt"; $PY bot/kit/build_help.py help > "$WORK/h.txt"
$PY bot/kit/build_help.py commands-block --commands "$WORK/cmd-mut.yaml" > "$WORK/b-mut.txt"; $PY bot/kit/build_help.py commands-block > "$WORK/b.txt"
if ! cmp -s "$WORK/h.txt" "$WORK/h-mut.txt" && ! cmp -s "$WORK/b.txt" "$WORK/b-mut.txt" && grep -q zzprobe "$WORK/h-mut.txt" "$WORK/b-mut.txt"; then ok "добавленная позиция меняет ОБА выхода"; else bad "добавленная позиция не меняет оба выхода — где-то копия"; fi
$PY bot/kit/build_help.py render --guide bot/kit/docs/bot-user-guide.ru.md > "$WORK/guide-re.md"
cmp -s "$WORK/guide-re.md" bot/kit/docs/bot-user-guide.ru.md && ok "инструкция на диске == перегенерация (блоки не правлены руками)" || bad "инструкция расходится с перегенерацией"
# литералы команд вне реестра и вне сгенерированных блоков
$PY - <<'EOF' > "$WORK/tokens.txt"
import yamlmini
for c in yamlmini.load_file('bot/kit/commands.yaml')['commands']:
    t = c['token']
    if t and (t.startswith('/') or t.startswith('!')): print(t)
EOF
$PY - "$WORK/tokens.txt" <<'EOF' && ok "греп литералов команд вне реестра/сгенерированного пуст" || bad "литералы команд вне реестра найдены"
import os, sys, glob, re
tokens = [t for t in open(sys.argv[1]).read().split() if t]
files = glob.glob('bot/*.py') + glob.glob('bot/kit/*.py') + glob.glob('bot/kit/templates/*') + glob.glob('bot/kit/workflows/*') + [f for f in glob.glob('bot/tests/*') if os.path.isfile(f)]
hits = []
for f in files:
    text = open(f, encoding='utf-8').read()
    for t in tokens:
        for m in re.finditer(re.escape(t) + r'(?![A-Za-z0-9_])', text):
            hits.append("%s: %s" % (f, t))
guide = open('bot/kit/docs/bot-user-guide.ru.md', encoding='utf-8').read()
prose = re.sub(r'<!-- generated:commands:start -->.*?<!-- generated:commands:end -->', '', guide, flags=re.S)
prose = re.sub(r'<!-- generated:steps:start -->.*?<!-- generated:steps:end -->', '', prose, flags=re.S)
for t in tokens:
    if re.search(re.escape(t) + r'(?![A-Za-z0-9_])', prose): hits.append("guide prose: %s" % t)
print("  область: %d файлов + проза инструкции; токенов: %d; находок: %d" % (len(files), len(tokens), len(hits)))
for h in sorted(set(hits)): print("  !! " + h)
sys.exit(1 if hits else 0)
EOF

echo "== 5. инструкция: по-русски, маркеры, пять именованных разделов REQ-091"
G=bot/kit/docs/bot-user-guide.ru.md
CYR=$($PY -c "import re;print(len(re.findall('[А-Яа-яЁё]', open('$G',encoding='utf-8').read())))")
echo "  кириллических букв в инструкции: $CYR"
[ "$CYR" -gt 1000 ] && ok "инструкция по-русски" || bad "инструкция: мало кириллицы"
OPEN=$(grep -c 'generated:[a-z]*:start' "$G"); CLOSE=$(grep -c 'generated:[a-z]*:end' "$G")
echo "  маркеров start=$OPEN end=$CLOSE"
[ "$OPEN" -eq "$CLOSE" ] && [ "$OPEN" -eq 2 ] && ok "маркеры парные" || bad "маркеры непарные"
$PY - "$TW" "$G" <<'EOF' && ok "пять разделов REQ-091 присутствуют именованно" || bad "разделы инструкции"
import sys, yamlmini
secs = yamlmini.load_file(sys.argv[1])["guide_sections"]; g = open(sys.argv[2], encoding="utf-8").read()
missing = [s for s in secs if ("<!-- section: %s -->" % s) not in g]
print("  разделов в реестре: %d, найдено: %d" % (len(secs), len(secs) - len(missing)))
for m in missing: print("  !! нет раздела " + m)
sys.exit(1 if missing else 0)
EOF

echo "== 6. файл состояния: схема, строгий разбор шаблона, якоря нет"
$PY - "$TW" <<'EOF' && ok "шаблон файла состояния разбирается; поля схемы объявлены; якоря в схеме нет" || bad "файл состояния: см. выше"
import sys, yamlmini, re
tw = yamlmini.load_file(sys.argv[1]); doc = yamlmini.load_file("bot/kit/templates/bot-sessions.yaml")
fields = [f["name"] for f in tw["session_file"]["fields"]]
need = {"title","started_at","started_at_local","chat_id","start_update_id","schema_version"}
bad = []
if doc != {"sessions": {}}: bad.append("шаблон не пустой mapping sessions: %r" % (doc,))
if not need <= set(fields): bad.append("в схеме нет полей %s" % (need - set(fields)))
tmpl = open("bot/kit/templates/bot-sessions.yaml", encoding="utf-8").read()
if re.search(r"(?i)anchor|якор", tmpl): bad.append("в шаблоне упомянут якорь")
if any(re.search(r"(?i)anchor|якор", f) for f in fields): bad.append("якорь среди полей схемы")
print("  поля схемы (%d): %s; ключ: %s" % (len(fields), ", ".join(fields), tw["session_file"]["key"]))
for b in bad: print("  !! " + b)
sys.exit(1 if bad else 0)
EOF

echo "== 7. установка в mktemp-репо: манифест генерируется, первый прогон ставит, второй — дифф пуст"
$PY bot/kit/build_manifest.py --out "$WORK/manifest1.yaml"; $PY bot/kit/build_manifest.py --out "$WORK/manifest2.yaml"
cmp -s "$WORK/manifest1.yaml" "$WORK/manifest2.yaml" && ok "build_manifest: два прогона побайтово равны ($(grep -c '^  - src:' "$WORK/manifest1.yaml") записей)" || bad "build_manifest недетерминирован"
REPO="$WORK/repo"; mkdir -p "$REPO/time" "$REPO/tickets"
git -C "$REPO" init -q; git -C "$REPO" config user.email t@invalid; git -C "$REPO" config user.name t
cp "$GOLDEN_TS" "$REPO/time/TIMESHEET-2026-09-dev1.md"; printf -- '---\nid: x\n---\n' > "$REPO/tickets/PROP-1.md"
git -C "$REPO" add -A; git -C "$REPO" commit -qm base
SHA_BEFORE=$(shasum -a 256 "$REPO/time/TIMESHEET-2026-09-dev1.md" | cut -d' ' -f1)
$PY bot/kit/install.py --repo "$REPO" --manifest "$WORK/manifest1.yaml" layout --allow-unfilled-pins > "$WORK/inst1.txt"; RC1=$?
tail -1 "$WORK/inst1.txt" | sed 's/^/  первый прогон: /'
[ $RC1 -eq 0 ] && ok "первый прогон установщика rc=0" || bad "первый прогон установщика rc=$RC1"
# правка 3 вердикта: карта людей — ручной шаг; после установки в репо нет ни файла карты, ни синтетических людей
SYN=$(grep -rl 'dev-one' "$REPO" --exclude-dir=.git | wc -l | tr -d ' ')
echo "  карта людей после layout: $([ -e "$REPO/.workshop/people.yaml" ] && echo 'ЕСТЬ' || echo 'отсутствует (ручной шаг)'); файлов с синтетическим handle dev-one: $SYN"
[ ! -e "$REPO/.workshop/people.yaml" ] && [ "$SYN" -eq 0 ] && grep -q 'people.yaml: ручной файл, ОТСУТСТВУЕТ' "$WORK/inst1.txt" && ok "установщик карту людей не ставит; синтетических людей в репо заказчика нет" || bad "синтетические люди/карта поставлены установщиком"
$PY bot/kit/install.py --repo "$REPO" check-people > "$WORK/cp0.txt"; RC=$?; echo "  check-people без карты: $(head -1 "$WORK/cp0.txt" | cut -c1-120) (rc=$RC)"
[ $RC -eq 2 ] && grep -q 'people_map' "$WORK/cp0.txt" && ok "check-people без карты — отказ с названной причиной и именем ручного шага" || bad "check-people без карты не отказал поимённо"
cp bot/kit/templates/people.yaml "$REPO/.workshop/people.yaml"   # ручной шаг people_map (имитация заказчика: копия шаблона)
$PY bot/kit/install.py --repo "$REPO" --manifest "$WORK/manifest1.yaml" commit > "$WORK/commit1.txt"; sed 's/^/  /' "$WORK/commit1.txt"
git -C "$REPO" add .workshop/people.yaml; git -C "$REPO" commit -qm "people map (manual step)"
$PY bot/kit/install.py --repo "$REPO" --manifest "$WORK/manifest1.yaml" layout --allow-unfilled-pins > "$WORK/inst2.txt"; RC2=$?
tail -1 "$WORK/inst2.txt" | sed 's/^/  второй прогон: /'
PORC=$(git -C "$REPO" status --porcelain | wc -l | tr -d ' ')
echo "  git status --porcelain после второго прогона: $PORC строк"
[ $RC2 -eq 0 ] && grep -q 'без изменений' "$WORK/inst2.txt" && [ "$PORC" -eq 0 ] && ok "второй прогон: дифф пуст, дерево чистое" || bad "второй прогон: rc=$RC2 porcelain=$PORC"
SHA_AFTER=$(shasum -a 256 "$REPO/time/TIMESHEET-2026-09-dev1.md" | cut -d' ' -f1)
[ "$SHA_BEFORE" = "$SHA_AFTER" ] && ok "файл заказчика в time/ не тронут (sha256 равны: ${SHA_BEFORE:0:16}…)" || bad "файл заказчика изменён"
$PY bot/kit/install.py --repo "$REPO" check-people > "$WORK/cp.txt"; sed 's/^/  /' "$WORK/cp.txt"
grep -q '^check-people: ok' "$WORK/cp.txt" && grep -q 'админов с telegram_id: [1-9]' "$WORK/cp.txt" && ok "check-people на установленном комплекте: handle бота и admin с telegram_id есть" || bad "check-people"

echo "== 8. .gitattributes: четыре значения check-attr, порядок текстовым предикатом, мутации"
cp "$REPO/time/TIMESHEET-2026-09-dev1.md" "$REPO/time/TIMESHEET-2026-09-dev1.comments.md" 2>/dev/null
for p in time/TIMESHEET-2026-09-dev1.md time/TIMESHEET-2026-09-dev1.comments.md .workshop/bot-sessions.yaml tickets/PROP-1.md; do
  echo "  $(git -C "$REPO" check-attr merge -- "$p")"
done
# ожидание check-attr — ИЗ машинного дубля контракта (session_file.merge_attr_expected / poll_state_file.merge_attr), не литералом
EXP_S=$($PY -c "import yamlmini;d=yamlmini.load_file('$TW');print(d['session_file']['merge_attr_expected'])"); EXP_P=$($PY -c "import yamlmini;d=yamlmini.load_file('$TW');print(d['poll_state_file']['merge_attr'])")
echo "  ожидание из tg-bot.yaml: session_file=$EXP_S poll_state_file=$EXP_P"
[ "$EXP_S" = "unset" ] && [ "$(git -C "$REPO" check-attr merge -- .workshop/bot-sessions.yaml | awk '{print $NF}')" = "$EXP_S" ] && ok "файл состояния учёта: merge $EXP_S (-merge: двусторонняя правка = конфликт) — как в tg-bot.yaml" || bad "файл состояния учёта: check-attr != tg-bot.yaml ($EXP_S)"
[ "$EXP_P" = "unset" ] && [ "$(git -C "$REPO" check-attr merge -- .workshop/bot-state.yaml | awk '{print $NF}')" = "$EXP_P" ] && ok "файл состояния прогона: merge $EXP_P — как в tg-bot.yaml" || bad "файл состояния прогона: check-attr != tg-bot.yaml ($EXP_P)"
[ "$(git -C "$REPO" check-attr merge -- time/TIMESHEET-2026-09-dev1.md | awk '{print $NF}')" = "union" ] && ok "табель: union (отрицательный контроль)" || bad "табель не union"
[ "$(git -C "$REPO" check-attr merge -- time/TIMESHEET-2026-09-dev1.comments.md | awk '{print $NF}')" = "union" ] && ok "спутник комментов: union" || bad "спутник не union"
[ "$(git -C "$REPO" check-attr merge -- tickets/PROP-1.md | awk '{print $NF}')" = "unspecified" ] && ok "тикет: unspecified" || bad "тикет под union"
order_pred() { # $1 файл; PASS если номер строки time/*.md < номер строки *.comments.md
  local a b; a=$(grep -n '^time/\*\.md merge=union$' "$1" | cut -d: -f1 | head -1); b=$(grep -n '^\*\.comments\.md merge=union$' "$1" | cut -d: -f1 | head -1)
  [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]; }
order_pred bot/kit/templates/gitattributes && ok "порядок строк шаблона: time/*.md (строка $(grep -n '^time/' bot/kit/templates/gitattributes | cut -d: -f1)) выше *.comments.md (строка $(grep -n '^\*\.comments' bot/kit/templates/gitattributes | cut -d: -f1))" || bad "порядок строк шаблона"
grep -v '^#' bot/kit/templates/gitattributes | tac > "$WORK/ga-swap"; order_pred "$WORK/ga-swap" && bad "перестановка строк НЕ роняет предикат" || ok "негативный контроль: перестановка роняет предикат порядка"
cp "$REPO/.gitattributes" "$WORK/ga-keep"
# негативная мутация 1: снятие строк -merge → дефолтный (unspecified) режим 3-way тихо слил бы файл состояния
grep -v -- '-merge' "$WORK/ga-keep" > "$REPO/.gitattributes"
[ "$(git -C "$REPO" check-attr merge -- .workshop/bot-sessions.yaml | awk '{print $NF}')" = "unspecified" ] && ok "негативная мутация: снятие -merge → файл состояния unspecified (тихое авто-слияние) → проверка роняется" || bad "мутация -merge не воспроизвелась"
cp "$WORK/ga-keep" "$REPO/.gitattributes"
# негативная мутация 2: .workshop/* merge=union делает файл состояния union
printf '.workshop/* merge=union\n' >> "$REPO/.gitattributes"
[ "$(git -C "$REPO" check-attr merge -- .workshop/bot-sessions.yaml | awk '{print $NF}')" = "union" ] && ok "негативная мутация: .workshop/* merge=union делает файл состояния union → проверка роняется" || bad "мутация union не воспроизвелась"
cp "$WORK/ga-keep" "$REPO/.gitattributes"

echo "== 9. предикат тонкой обёртки: bootstrap PASS, обе формы учётных данных, восемь мутаций FAIL поимённо, hooksPath принят"
$PY bot/kit/wrapper_predicate.py bot/kit/workflows/bootstrap.yml --contract "$TW" --require-hooks-path > "$WORK/wp.txt"; RC=$?
sed 's/^/  /' "$WORK/wp.txt"; echo "  rc=$RC"
grep -q '^structure: PASS' "$WORK/wp.txt" && ok "bootstrap: структура PASS (rc=$RC; пины — состояние релиза)" || bad "bootstrap: структура FAIL"
# правка 1 вердикта: обе формы учётных данных В-4 в шаге checkout — токен с фолбэком И ssh-key (положительный контроль)
$PY - "$TW" <<'EOF' && ok "checkout заказчика несёт обе формы В-4: token с фолбэком и ssh-key (предикат принял)" || bad "формы учётных данных В-4 в bootstrap"
import sys, yamlmini, re
tw = yamlmini.load_file(sys.argv[1]); bs = yamlmini.load_file("bot/kit/workflows/bootstrap.yml")
forms = dict((f["key"], re.compile(f["pattern"])) for f in tw["thin_wrapper"]["allow_list"]["checkout_with_forms"])
step = bs["jobs"]["bootstrap"]["steps"][0]; w = step.get("with") or {}
mt = forms["token"].match(str(w.get("token", ""))); ms = forms["ssh-key"].match(str(w.get("ssh-key", "")))
print("  шаг 0 with: token=%r ssh-key=%r" % (w.get("token"), w.get("ssh-key")))
print("  token: секрет %s, фолбэк %s; ssh-key: секрет %s" % (mt and mt.group("secret"), bool(mt and mt.group("fallback")), ms and ms.group("secret")))
sys.exit(0 if mt and mt.group("fallback") and ms and ms.group("secret") == "WORKSHOP_DEPLOY_KEY" else 1)
EOF
$PY - "$TW" <<'EOF'
import sys, yamlmini, os
base = open("bot/kit/workflows/bootstrap.yml", encoding="utf-8").read(); w = os.environ["WORK"]
muts = {
 "if_in_step": base.replace("      - name: check secrets\n", "      - name: check secrets\n        if: always()\n"),
 "policy_literal_in_run": base.replace("install.py layout\n", "install.py layout --retries 20\n"),
 "two_calls_in_run": base.replace("install.py layout\n", "install.py layout && echo done\n"),
 "unknown_top_key": base.replace("permissions:\n", "defaults: {}\npermissions:\n"),
 "uses_not_allowed": base.replace("      - name: check secrets\n        run: python3 .workshop-kit/bot/kit/install.py check-secrets\n", "      - name: setup\n        uses: some-org/setup-thing@0123456789012345678901234567890123456789\n"),
 "checkout_token_no_fallback": base.replace("token: ${{ secrets.WORKSHOP_FORGE_TOKEN || github.token }}", "token: ${{ secrets.WORKSHOP_FORGE_TOKEN }}"),
 "checkout_alternative_not_bound": base.replace("          ssh-key: ${{ secrets.WORKSHOP_DEPLOY_KEY }}\n", ""),
 "checkout_with_key_not_allowed": base.replace("          fetch-depth: 0\n", "          fetch-depth: 0\n          submodules: true\n"),
}
for k, v in muts.items():
    assert v != base, k
    open(os.path.join(w, "mut-%s.yml" % k), "w", encoding="utf-8").write(v)
print("  мутаций построено: %d (реестр: %d)" % (len(muts), len(yamlmini.load_file(sys.argv[1])["thin_wrapper"]["mutations"])))
EOF
for m in if_in_step policy_literal_in_run two_calls_in_run unknown_top_key uses_not_allowed checkout_token_no_fallback checkout_alternative_not_bound checkout_with_key_not_allowed; do
  OUT=$($PY bot/kit/wrapper_predicate.py "$WORK/mut-$m.yml" --contract "$TW" --require-hooks-path); RC=$?
  echo "  мутация $m → $(echo "$OUT" | head -1 | cut -c1-110) (rc=$RC)"
  [ $RC -eq 2 ] && echo "$OUT" | grep -q "$m" && ok "мутация $m роняет гейт поимённо" || bad "мутация $m не роняет гейт поимённо"
done
$PY - "$TW" <<'EOF' && ok "env bootstrap ⊆ реестр секретов; concurrency group = контракт" || bad "env/concurrency bootstrap"
import sys, yamlmini
tw = yamlmini.load_file(sys.argv[1]); bs = yamlmini.load_file("bot/kit/workflows/bootstrap.yml")
secrets = set(s["name"] for s in yamlmini.load_file("bot/kit/install-steps.yaml")["secrets"])
env = set(bs["env"].keys()); print("  env-ключей: %d, секретов в реестре: %d, группа: %s" % (len(env), len(secrets), bs["concurrency"]["group"]))
sys.exit(0 if env <= secrets and bs["concurrency"]["group"] == tw["thin_wrapper"]["concurrency_group"] else 1)
EOF

echo "== 9б. полнота РАНТАЙМА комплекта: скрипты из run обёрток и импорты разложенных модулей — в раскладке"
$PY - <<'EOF2' && ok "рантайм комплекта полон: скрипты обёрток и импорты разложенных модулей — все в раскладке" || bad "рантайм комплекта неполон (скрипт обёртки или импорт вне раскладки)"
# -*- coding: utf-8 -*-
import glob, re, sys
sys.path.insert(0, "bot")
import yamlmini
dsts = {e["dst"] for e in yamlmini.load_file("bot/kit/manifest.yaml")["entries"]}
bad = []
for w in sorted(glob.glob("bot/kit/workflows/*.yml")):
    doc = yamlmini.load_file(w)
    for job in (doc.get("jobs") or {}).values():
        for st in job.get("steps") or []:
            run = st.get("run")
            if not run:
                continue
            m = re.match(r"^python3 (\S+\.py)", run)
            if not m:
                continue
            path = m.group(1)
            if path.startswith(".workshop-kit/"):
                continue
            if path not in dsts:
                bad.append("%s: %s" % (w.split("/")[-1], path))
# КЛАСС (живой прогон 2026-09-12): рантайм не ограничен вызовами из обёрток — разложенный модуль
# импортирует другие модули комплекта, и КАЖДЫЙ такой импорт обязан быть разложен тоже, иначе
# прогон падает ModuleNotFoundError уже у заказчика. Проверяется по AST, не грепом.
import ast, os
laid = {e["dst"]: e["src"] for e in yamlmini.load_file("bot/kit/manifest.yaml")["entries"]}
importable = {os.path.basename(d)[:-3] for d in laid if d.endswith(".py")}
stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"yamlmini"}
missing = []
for dst, src in sorted(laid.items()):
    if not dst.endswith(".py"):
        continue
    tree = ast.parse(open(src, encoding="utf-8").read(), src)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    for n in sorted(names):
        if n in stdlib or n in importable:
            continue
        if os.path.exists(os.path.join("bot", n + ".py")) or os.path.exists(os.path.join("bot", "kit", n + ".py")):
            missing.append("%s импортирует %s — модуль есть в комплекте, но НЕ разложен" % (dst, n))
print("  вызовов скриптов в обёртках: отсутствующих в манифесте %d %s; импортов разложенных модулей вне раскладки: %d %s" % (len(bad), bad, len(missing), missing))
sys.exit(1 if (bad or missing) else 0)
EOF2

echo "== 10. ручные шаги: N из реестра, блок инструкции, чувствительность"
N_DECL=$($PY bot/kit/build_help.py count-steps)
N_GUIDE=$(sed -n '/generated:steps:start/,/generated:steps:end/p' "$G" | grep -cE '^[0-9]+\. \*\*')
N_LINE=$(sed -n '/generated:steps:start/,/generated:steps:end/p' "$G" | grep -oE 'N = [0-9]+' | head -1)
echo "  объявленное N (счёт позиций install-steps.yaml): ${N_DECL}; шагов в сгенерированном блоке инструкции: ${N_GUIDE}; строка блока: «${N_LINE}»"
[ "$N_DECL" = "$N_GUIDE" ] && [ "$N_LINE" = "N = $N_DECL" ] && ok "N совпадает во всех трёх местах прогона" || bad "N расходится"
grep -qE 'N := число позиций' "$CH" && ok "глава объявляет N явной строкой-формулой, не числом" || bad "в главе нет явной строки объявления N"
grep -nE '\bN\s*=\s*[0-9]+' "$CH" > /dev/null && bad "в главе N назван числом" || ok "в главе N числом не назван"
cp bot/kit/install-steps.yaml "$WORK/steps-mut.yaml"; printf '  - id: zz_probe\n    title: проба\n    when: always\n    guide: проба\n    verified_by: проба\n' >> "$WORK/steps-mut.yaml"
N_MUT=$($PY bot/kit/build_help.py count-steps --steps "$WORK/steps-mut.yaml")
$PY bot/kit/build_help.py steps-block --steps "$WORK/steps-mut.yaml" > "$WORK/sb-mut.txt"; $PY bot/kit/build_help.py steps-block > "$WORK/sb.txt"
[ "$N_MUT" -eq $((N_DECL+1)) ] && ! cmp -s "$WORK/sb.txt" "$WORK/sb-mut.txt" && ok "добавленный шаг меняет и N (${N_DECL}→$N_MUT), и блок инструкции" || bad "добавленный шаг не меняет N/блок"
echo "  упоминаний ручного файла bootstrap.yml в главе: $(grep -c 'workflows/bootstrap.yml' "$CH")"
grep -q 'bot/kit/workflows/bootstrap.yml' "$CH" && ok "глава называет ручной файл bootstrap.yml" || bad "ручной файл не назван"

echo "== 11. манифест релизного бинаря: форма, пин комплекта, сверка (плейсхолдер/нулевой дайджест падают, подмена байта падает, совпадение проходит)"
$PY - <<'EOF' && ok "validator-release.yaml: форма версия → url/path → sha256 → назначение; блок kit; url только https" || bad "validator-release.yaml форма"
import yamlmini, sys, re
d = yamlmini.load_file("bot/kit/validator-release.yaml"); bad = []
for r in d["releases"]:
    for a in r["artifacts"]:
        for k in ("target","sha256","purpose"):
            if k not in a: bad.append("%s/%s без %s" % (r["version"], a.get("target"), k))
        if "url" not in a and "path" not in a: bad.append("нет url/path")
        if "url" in a and not str(a["url"]).startswith("https://"): bad.append("url не https: %s" % a["url"])
kit = d.get("kit") or {}
for k in ("repository", "ref", "channel"):
    if k not in kit: bad.append("kit без %s" % k)
bs = yamlmini.load_file("bot/kit/workflows/bootstrap.yml")["jobs"]["bootstrap"]["steps"][1]["with"]
# релизный слой: kit.ref — КОДОВЫЙ коммит K; клиентская копия bootstrap.yml (ассет релиза) пинит релизный коммит R над K;
# шаблон в репо держит плейсхолдер. Здесь сверяется репозиторий и форма ref (плейсхолдер либо полный SHA).
if bs.get("repository") != kit.get("repository"): bad.append("bootstrap with.repository != kit.repository")
if not (str(bs.get("ref")) == "PIN-KIT-COMMIT-SHA" or re.match(r"^[0-9a-f]{40}$", str(bs.get("ref")))): bad.append("bootstrap with.ref не плейсхолдер и не SHA")
print("  пиннованная версия: %s; артефактов: %d; kit: %s @ %s (%s); bootstrap checkout kit: %s @ %s" % (d["pinned_version"], sum(len(r["artifacts"]) for r in d["releases"]), kit.get("repository"), kit.get("ref"), kit.get("channel"), bs.get("repository"), bs.get("ref")))
sys.exit(1 if bad else 0)
EOF
# правка 5 вердикта: check-kit-ref в mktemp-checkout — расхождение и плейсхолдер дают отказ с названной причиной, совпадение проходит
KCO="$WORK/kitco"; mkdir -p "$KCO"; git -C "$KCO" init -q; printf 'x\n' > "$KCO/x"; git -C "$KCO" add -A; git -C "$KCO" -c user.name=t -c user.email=t@invalid commit -qm kit
KHEAD=$(git -C "$KCO" rev-parse HEAD)
$PY bot/kit/install.py check-kit-ref --kit-checkout "$KCO" > "$WORK/kr0.txt"; RC=$?; echo "  check-kit-ref (поставляемый манифест): $(head -1 "$WORK/kr0.txt" | cut -c1-120) (rc=$RC)"
KITREF=$($PY -c "import yamlmini;print(yamlmini.load_file('bot/kit/validator-release.yaml')['kit']['ref'])")
if echo "$KITREF" | grep -qE '^[0-9a-f]{40}$'; then
  [ $RC -eq 2 ] && grep -q 'расходится' "$WORK/kr0.txt" && ok "пин комплекта ЗАПОЛНЕН ($KITREF): чужой checkout — отказ «расходится», не пропуск" || bad "заполненный пин не поймал чужой checkout (rc=$RC)"
else
  [ $RC -eq 2 ] && grep -q 'не заполнен' "$WORK/kr0.txt" && ok "пин комплекта до релиза — отказ «не заполнен», не пропуск" || bad "плейсхолдер пина прошёл (rc=$RC)"
fi
printf 'schema_version: 1\nkit:\n  repository: alexCherryPick/workshop-kit\n  ref: %s\n  channel: public\npinned_version: "t"\nreleases: []\n' "$KHEAD" > "$WORK/rel-kit.yaml"
$PY bot/kit/install.py check-kit-ref --release "$WORK/rel-kit.yaml" --kit-checkout "$KCO" > "$WORK/kr1.txt"; RC=$?; echo "  check-kit-ref (ref == HEAD): $(head -1 "$WORK/kr1.txt" | cut -c1-120) (rc=$RC)"
[ $RC -eq 0 ] && ok "совпадающий пин комплекта проходит (rc=0)" || bad "совпадающий пин не прошёл (rc=$RC)"
printf 'schema_version: 1\nkit:\n  repository: alexCherryPick/workshop-kit\n  ref: %s\n  channel: public\npinned_version: "t"\nreleases: []\n' "ffffffffffffffffffffffffffffffffffffffff" > "$WORK/rel-kit2.yaml"
$PY bot/kit/install.py check-kit-ref --release "$WORK/rel-kit2.yaml" --kit-checkout "$KCO" > "$WORK/kr2.txt"; RC=$?; echo "  check-kit-ref (ref != HEAD): $(head -1 "$WORK/kr2.txt" | cut -c1-140) (rc=$RC)"
[ $RC -eq 2 ] && grep -q 'расходится' "$WORK/kr2.txt" && ok "расхождение пина комплекта — отказ с названной причиной (rc=2)" || bad "расхождение пина не поймано (rc=$RC)"
$PY bot/kit/install.py validator --path "$BIN" > "$WORK/vr0.txt"; RC=$?; sed 's/^/  /' "$WORK/vr0.txt" | cut -c1-160
[ $RC -eq 2 ] && grep -qE 'не является дайджестом|НЕ СОВПАЛ' "$WORK/vr0.txt" && ok "поставляемый манифест против ЧУЖОГО бинаря — отказ при сверке (rc=2: плейсхолдер до релиза / несовпадение sha256 после)" || bad "чужой бинарь прошёл сверку (rc=$RC)"
REAL=$(shasum -a 256 "$BIN" | cut -d' ' -f1)
printf 'schema_version: 1\npinned_version: "t"\nreleases:\n  - version: "t"\n    artifacts:\n      - target: local\n        path: bin\n        sha256: "%s"\n        purpose: p\n' "$REAL" > "$WORK/rel.yaml"
cp "$BIN" "$WORK/bin"
$PY bot/kit/install.py validator --release "$WORK/rel.yaml" --target local --dest "$WORK/vbin" > "$WORK/vr1.txt"; RC=$?; sed 's/^/  /' "$WORK/vr1.txt" | cut -c1-160
[ $RC -eq 0 ] && [ -x "$WORK/vbin" ] && ok "совпавшая сумма проходит (rc=0), бинарь положен исполняемым" || bad "совпавшая сумма не прошла (rc=$RC)"
$PY -c "import sys;p='$WORK/bin';b=bytearray(open(p,'rb').read());b[100]^=1;open(p,'wb').write(b)"
rm -f "$WORK/vbin"; $PY bot/kit/install.py validator --release "$WORK/rel.yaml" --target local --dest "$WORK/vbin" > "$WORK/vr2.txt"; RC=$?; sed 's/^/  /' "$WORK/vr2.txt" | cut -c1-200
[ $RC -eq 2 ] && [ ! -e "$WORK/vbin" ] && ok "подмена одного байта — громкий отказ с обоими дайджестами (rc=2), бинарь не положен" || bad "подмена байта не поймана (rc=$RC)"
# правка 6 вердикта: нулевой дайджест — явный отказ (не «64 hex — сверяем»); url не https — отказ до скачивания
printf 'schema_version: 1\npinned_version: "z"\nreleases:\n  - version: "z"\n    artifacts:\n      - target: local\n        path: bin\n        sha256: "%s"\n        purpose: p\n' "$(printf '0%.0s' $(seq 1 64))" > "$WORK/rel-zero.yaml"
$PY bot/kit/install.py validator --release "$WORK/rel-zero.yaml" --target local --dest "$WORK/vbin0" > "$WORK/vr3.txt"; RC=$?; sed 's/^/  /' "$WORK/vr3.txt" | cut -c1-160
[ $RC -eq 2 ] && grep -q 'нулевой дайджест' "$WORK/vr3.txt" && [ ! -e "$WORK/vbin0" ] && ok "нулевой дайджест — явный отказ поимённо (rc=2)" || bad "нулевой дайджест не отвергнут явно (rc=$RC)"
printf 'schema_version: 1\npinned_version: "h"\nreleases:\n  - version: "h"\n    artifacts:\n      - target: local\n        url: "http://example.invalid/bin"\n        sha256: "%s"\n        purpose: p\n' "$REAL" > "$WORK/rel-http.yaml"
$PY bot/kit/install.py validator --release "$WORK/rel-http.yaml" --target local --dest "$WORK/vbinh" > "$WORK/vr4.txt"; RC=$?; sed 's/^/  /' "$WORK/vr4.txt" | cut -c1-160
[ $RC -eq 2 ] && grep -q 'не https' "$WORK/vr4.txt" && ok "источник не https — отказ до скачивания (rc=2)" || bad "http-источник не отвергнут (rc=$RC)"
# правка 7 вердикта: назначение по умолчанию — .workshop-bin/workshop-validator в репо заказчика; каталог самоигнорируемый, дерево чистое
cp "$BIN" "$WORK/bin"
git -C "$REPO" status --porcelain > "$WORK/porc-before.txt"
$PY bot/kit/install.py --repo "$REPO" validator --release "$WORK/rel.yaml" --target local > "$WORK/vr5.txt"; RC=$?; sed 's/^/  /' "$WORK/vr5.txt" | cut -c1-200
git -C "$REPO" status --porcelain > "$WORK/porc-after.txt"
PORC2=$(diff "$WORK/porc-before.txt" "$WORK/porc-after.txt" | grep -c '^[<>]'); echo "  git status --porcelain: новых строк после установки бинаря — $PORC2; $(git -C "$REPO" check-ignore -q .workshop-bin/workshop-validator && echo 'бинарь игнорируется git' || echo 'бинарь НЕ игнорируется')"
[ $RC -eq 0 ] && [ -x "$REPO/.workshop-bin/workshop-validator" ] && [ "$PORC2" -eq 0 ] && git -C "$REPO" check-ignore -q .workshop-bin/workshop-validator && ok "бинарь положен в объявленный путь .workshop-bin/workshop-validator; в porcelain ничего не добавил (самоигнорируемый каталог)" || bad "назначение бинаря/чистота дерева (rc=$RC новых строк porcelain=$PORC2)"

echo "== 12. форма бот-коммента: образец главы разбирается предикатом; мутации; check-pair бинарём"
SAMPLE=$(grep -m1 -E '^### 20[0-9]{2}-' "$CH")
echo "  образец: $SAMPLE"
$PY - "$SAMPLE" <<'EOF' && ok "образец разобран: таймстемп 02.2.1, MIDDLE DOT, автор-токен, ровно один about:t:" || bad "образец не разобран"
import sys, re
s = sys.argv[1]
G = re.compile(r"^### (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) (·) ([A-Za-z0-9._-]{1,64}) <!--c:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})((?: (?:about:t:|retracts:t:|corrects:|retracts:|replies-to:)[0-9a-f-]+)*)-->$")
m = G.match(s)
if not m: print("  !! не по грамматике 04.3.1"); sys.exit(1)
links = m.group(5).split()
print("  разделитель: U+%04X; таймстемп %s; автор %s; связочных токенов: %d (%s); id версия %s" % (ord(m.group(2)), m.group(1), m.group(3), len(links), links, m.group(4)[14]))
ok = len(links) == 1 and links[0].startswith("about:t:") and m.group(4)[14] == "7"
muts = {
 "dash_separator": s.replace(" · ", " - "),
 "two_link_tokens": s.replace("-->", " retracts:t:00000000-->"),
 "no_c_id": re.sub(r"c:[0-9a-f-]{36} ", "", s),
 "space_in_author": s.replace("dev-one", "dev one"),
}
for k, v in muts.items():
    mm = G.match(v); fail = (mm is None) or (len(mm.group(5).split()) != 1) if mm else True
    print("  мутация %s → %s" % (k, "FAIL (роняет)" if fail else "PASS (!!)"))
    ok = ok and fail
sys.exit(0 if ok else 1)
EOF
PAIRDIR="$WORK/pair"; mkdir -p "$PAIRDIR/time"; cp "$GOLDEN_TS" "$PAIRDIR/time/TIMESHEET-2026-08-dev1.md"
GID=$(awk '/^id:/{print $2; exit}' "$GOLDEN_TS"); echo "  id golden-контейнера: $GID"
printf '<!-- comments-of: %s -->\n\n### 2026-08-14T10:00:00Z \xc2\xb7 dev1 <!--c:01991f9a-6f50-7a1e-8c4b-2d5e7f8a9b0c about:t:0a1b2c3d-->\nработа по стенду с десяти до четверти второго\nподробности вторым абзацем\n' "$GID" > "$PAIRDIR/time/TIMESHEET-2026-08-dev1.comments.md"
git -C "$PAIRDIR" init -q; cp bot/kit/templates/gitattributes "$PAIRDIR/.gitattributes"
OUT=$(cd "$PAIRDIR" && "$BIN" check-pair time/TIMESHEET-2026-08-dev1.md --comments time/TIMESHEET-2026-08-dev1.comments.md --path time/TIMESHEET-2026-08-dev1.md --comments-path time/TIMESHEET-2026-08-dev1.comments.md --git-root . --no-config 2>&1); RC=$?
echo "  check-pair валидная пара: $(echo "$OUT" | tail -1) (rc=$RC)"
[ $RC -eq 0 ] && ok "пара «golden + спутник с бот-комментом» валидна: rc=0" || bad "check-pair rc=$RC: $OUT"
sed -i '' 's/about:t:0a1b2c3d/about:t:deadbeef/' "$PAIRDIR/time/TIMESHEET-2026-08-dev1.comments.md"
OUT=$(cd "$PAIRDIR" && "$BIN" check-pair time/TIMESHEET-2026-08-dev1.md --comments time/TIMESHEET-2026-08-dev1.comments.md --path time/TIMESHEET-2026-08-dev1.md --comments-path time/TIMESHEET-2026-08-dev1.comments.md --git-root . --no-config 2>&1); RC=$?
echo "  check-pair about:t: на несуществующий якорь: $(echo "$OUT" | grep -o 'ORPHAN_ANNOTATION' | head -1) (rc=$RC)"
[ $RC -eq 1 ] && ok "отрицательный контроль: сирота-связка → WARNING, rc=1" || bad "сирота-связка не поймана (rc=$RC)"

echo "== 13. правило id коммента vs якорь: разные домены соли, повтор даёт то же"
$PY - <<'EOF' && ok "id и якорь не равны, не подстроки друг друга, повтор детерминирован, id — UUIDv7" || bad "правило id/якоря"
import hashlib, re, sys
def identity(chat_id, message_id): return ("tg:%d:%d" % (chat_id, message_id)).encode("ascii")
def anchor(ident, k=0, step=0): return hashlib.sha256(b"workshop-d09-anchor-v1\0" + ident + b"\0" + str(k).encode() + b"\0" + str(step).encode()).hexdigest()[:8]
def comment_id(ident, date, k=0):
    h = hashlib.sha256(b"workshop-d09-comment-v1\0" + ident + b"\0" + str(k).encode()).digest()
    ms = date * 1000; ra = int.from_bytes(h[0:2], "big") & 0x0FFF; rb = int.from_bytes(h[2:10], "big") & ((1 << 62) - 1)
    v = (ms << 80) | (0x7 << 76) | (ra << 64) | (0b10 << 62) | rb
    x = "%032x" % v; return "%s-%s-%s-%s-%s" % (x[:8], x[8:12], x[12:16], x[16:20], x[20:])
i = identity(100000001, 4242); a = anchor(i); c = comment_id(i, 1788790990)
print("  identity=%s\n  anchor   =%s\n  commentid=%s" % (i.decode(), a, c))
ok = a != c and a not in c and c.replace("-", "")[:8] != a and comment_id(i, 1788790990) == c and anchor(i) == a
ok = ok and re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", c) is not None
print("  повтор: anchor==%s commentid==%s; step=1 anchor=%s (id не меняется: %s)" % (anchor(i) == a, comment_id(i, 1788790990) == c, anchor(i, 0, 1), comment_id(i, 1788790990) == c))
sys.exit(0 if ok else 1)
EOF

echo "== 14. грепы по главе: атомарность, гонка, кнопка-время, фрагмент-предикат, граница учётных данных"
grep -nE 'отдельным коммитом|вторым коммитом' "$CH" > /dev/null && bad "глава допускает отдельный коммит коммента" || ok "нет формулировок «отдельным/вторым коммитом»"
grep -q 'один коммит' "$CH" && perl -0 -ne 'exit(/число коммитов на одну\s+запись с текстом = \*\*1\*\*/ ? 0 : 1)' "$CH" && ok "атомарность названа числом и формулировкой" || bad "атомарность не названа числом"
grep -nEi 'разреша[а-яё]* автоматически|автоматическ[а-яё]* разреш|автослияни[а-яё]* файла состояния' "$CH" | grep -v 'нет по' > /dev/null && bad "в главе есть «разрешаем автоматически» про файл состояния" || ok "нет «разрешаем автоматически» применительно к файлу состояния"
grep -c 'Два прогона поллера\|Отвергнутый push\|Бот против фронта' "$CH" | xargs -I{} echo "  случаев правила гонки в главе: {}"
grep -rnE 'callback_query.*message\.date|message\.date.*callback_query' bot/*.py bot/kit/*.py "$SPEC_DIR"/*.md > /dev/null && bad "чтение времени из нажатия найдено" || ok "греп «время из callback_query» по коду и главам пуст"
grep -n 'встречается ли фрагмент' "$CH" > /dev/null && bad "фрагмент-предикат в главе" || ok "предикат «встречается ли фрагмент» в главе отсутствует"
grep -q 'write-path-blueprint.md:861-874' "$CH" && ok "граница учётных данных (PAT/device flow) названа с цитатой write-path-blueprint.md:861-874" || bad "нет цитаты границы учётных данных"
grep -q 'provider-wrappers:start' "$CH" && grep -q 'provider-wrappers:end' "$CH" && ok "маркеры provider-wrappers присутствуют" || bad "маркеров provider-wrappers нет"
$PY - "$CH" <<'EOF' && ok "C2: hard-токены форж вне маркеров отсутствуют" || bad "C2: hard-токен вне маркеров"
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
outside = re.sub(r"<!-- provider-wrappers:start -->.*?<!-- provider-wrappers:end -->", "", t, flags=re.S)
hits = [w for w in ("github","gitlab","bitbucket","gerrit","gitea","codeberg","azure devops") if re.search(r"\b%s\b" % w, outside, re.I)]
soft = [w for w in ("Actions","Pipelines","Workflows") if re.search(r"\b%s\b" % w, outside)]
print("  hard-находок вне маркеров: %d %s; soft (с заглавной): %d %s" % (len(hits), hits, len(soft), soft))
sys.exit(1 if hits or soft else 0)
EOF

echo "== 15. анти-минт двумя пространствами по главам D09"
$PY - "$TW" "$WORK/codes.txt" <<'EOF' && ok "анти-минт: оба грепа против дампа пусты" || bad "анти-минт: находки"
import os, re, sys, glob, yamlmini
codes = set(open(sys.argv[2]).read().split()); allow = set(yamlmini.load_file(sys.argv[1])["anti_mint"]["allow_list"])
text = "".join(open(f, encoding="utf-8").read() for f in glob.glob(os.environ["SPEC_DIR"] + "/*.md"))
ew = set(re.findall(r"\b[EW]-[A-Z0-9-]+\b", text)) - codes
# второе пространство считается после снятия токенов первого (иначе W-AUTHOR-UNKNOWN даёт «AUTHOR», «UNKNOWN»)
stripped = re.sub(r"\b[EW]-[A-Z0-9-]+\b", " ", text)
caps = set(re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", stripped)) - codes - allow
print("  глав: %d; E/W-токенов вне дампа: %d %s; CAPS-токенов вне дампа и allow-list: %d %s" % (len(glob.glob(os.environ["SPEC_DIR"] + "/*.md")), len(ew), sorted(ew), len(caps), sorted(caps)))
sys.exit(1 if ew or caps else 0)
EOF

echo "== 16. карта владения: каждый путь ровно один раз (глава и дубль), bot/tests и harness не дублируются"
sed -n '/^## 10\./,/^## 11\./p' "$CH" | awk -F'|' '/^\| `/{gsub(/[` ]/,"",$2); print $2}' | sort > "$WORK/own-ch.txt"
$PY -c "import yamlmini;[print(e['path']) for e in yamlmini.load_file('$TW')['file_ownership']]" | sort > "$WORK/own-tw.txt"
DUP_CH=$(uniq -d "$WORK/own-ch.txt" | wc -l | tr -d ' '); DUP_TW=$(uniq -d "$WORK/own-tw.txt" | wc -l | tr -d ' ')
echo "  путей в таблице главы: $(wc -l < "$WORK/own-ch.txt" | tr -d ' '); в дубле: $(wc -l < "$WORK/own-tw.txt" | tr -d ' '); дублей: глава $DUP_CH, дубль $DUP_TW"
[ "$DUP_CH" -eq 0 ] && [ "$DUP_TW" -eq 0 ] && cmp -s "$WORK/own-ch.txt" "$WORK/own-tw.txt" && ok "карта владения: без пересечений, глава == дубль" || bad "карта владения: дубли или расхождение"
grep -E '^(bot/tests/|harness/)' "$WORK/own-ch.txt" | uniq -d | grep . > /dev/null && bad "bot/tests|harness путь назван дважды" || ok "ни один путь bot/tests/* и harness/* не назван дважды ($(grep -cE '^(bot/tests/|harness/)' "$WORK/own-ch.txt") путей)"
for t in T1 T2 T3 T4 T5 T6 T7; do grep -q "| $t |" "$CH" || bad "владелец $t не встречается"; done; ok "владельцы T1–T7 присутствуют"

echo "== 17. карта людей → валидатор --people (команда дословно), второго реестра нет"
R=$(mktemp -d); P=$(mktemp)
$PY bot/kit/people_handles.py "$REPO/.workshop/people.yaml" > "$P"
echo "  экспорт handle+aliases: $(tr '\n' ' ' < "$P")"
(cd ~/repos/workshop && ./validator/target/release/workshop-validator check-corpus --root "$R" --people "$P" --no-config < /dev/null > "$WORK/cc.txt" 2>&1); RC=$?; echo "  check-corpus --people: $(tail -1 "$WORK/cc.txt") rc=$RC"
[ $RC -le 1 ] && grep -q '^workshop_bot$' "$P" && ok "валидатор принял плоский список (rc=$RC); handle бота в списке" || bad "check-corpus rc=$RC"
rm -rf "$R" "$P"
# второй реестр = поле telegram_id как КЛЮЧ данных вне карты людей, либо код, читающий КАРТУ, кроме резолвера
# identity.py (T4, контракт §4) и install.py (check-people делегирует identity.validate_people_doc). Поля записей
# СОСТОЯНИЯ с id отправителя (secrets.rejection_record, state_store.record_rejection — T4 §3(б), T3 §3) картой не являются.
KEYS=$(grep -rlE '^\s*telegram_id:' bot/ "$TW" --include='*.yaml' --include='*.yml' --include='*.py' --include='*.sh' | grep -vE 'templates/people.yaml|test_|tests/botrepo.py' | wc -l | tr -d ' ')
CODE=$(grep -l 'telegram_id' bot/*.py bot/kit/*.py | grep -vE 'install.py|identity.py|secrets.py|state_store.py|heartbeat.py' | wc -l | tr -d ' ')
echo "  файлов с ключом telegram_id: вне карты и тестов — $KEYS; кода, читающего карту по telegram_id, кроме identity/install (и полей состояния secrets/state_store) — $CODE"
[ "$KEYS" -eq 0 ] && [ "$CODE" -eq 0 ] && ok "второго реестра людей в дереве нет (ключ telegram_id только в карте; карту читает только identity.py, install.py — через него)" || bad "telegram_id вне карты: $(grep -rlE '^\s*telegram_id:' bot/ "$TW" --include='*.yaml' --include='*.yml' --include='*.py' --include='*.sh' | grep -vE 'templates/people.yaml|test_|tests/botrepo.py' | tr '\n' ' ') $(grep -l 'telegram_id' bot/*.py bot/kit/*.py | grep -vE 'install.py|identity.py|secrets.py|state_store.py|heartbeat.py' | tr '\n' ' ')"

echo "== 18. транспорт tg.py тонкий"
$PY - <<'EOF' && ok "tg.py: ноль числовых констант в коде, один хост" || bad "tg.py: политика найдена"
import ast, re, sys
src = open("bot/tg.py", encoding="utf-8").read(); tree = ast.parse(src)
nums = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)]
hosts = set(re.findall(r"[a-z0-9.-]+\.telegram\.org", src))
print("  числовых констант: %d; хостов: %d %s; строк кода: %d" % (len(nums), len(hosts), sorted(hosts), len(src.splitlines())))
sys.exit(0 if not nums and len(hosts) == 1 else 1)
EOF

echo "== 19. единицы корпусов и факты инварианта объявлены"
$PY - "$TW" <<'EOF' && ok "единицы корпусов и факты инварианта с источником для timezone/id/title/period/person/author" || bad "единицы/факты"
import sys, yamlmini
tw = yamlmini.load_file(sys.argv[1]); cu = tw["corpus_units"]; facts = tw["invariant_facts"]
print("  корпусов с единицей: %d; фактов инварианта: %d (слои: %s)" % (len(cu), len(facts), sorted(set(f["layer"] for f in facts))))
targets = " ".join(f["target"] + " " + f["source"] for f in facts)
need = ["timezone", "id контейнера", "title", "period", "person", "author"]
missing = [n for n in need if n not in targets]
bad = [u for u in cu if not u.get("unit")] + missing
for f in facts:
    for k in ("source","target","multiplicity","order"):
        if not f.get(k): bad.append("факт без %s: %r" % (k, f))
if missing: print("  !! нет источника для: %s" % missing)
sys.exit(1 if bad else 0)
EOF

echo
echo "ИТОГ selfcheck T1: PASS=$PASS_N FAIL=$FAIL_N"
[ "$FAIL_N" -eq 0 ] && exit 0 || exit 1
