#!/bin/bash
# workshop-bot-daemon — цикл поллера и сторожа на всегда-включённой машине заказчика.
# Тот же poll.py / heartbeat.py, что зовут CI-обёртки; ни одной политики бота здесь нет — пороги,
# длинный опрос (transport.long_poll_seconds) и ретраи читаются из .workshop/bot.yaml репозитория.
# Окружение (задаёт заказчик в compose / env-файле, значения секретов окно вендора не видит):
#   WORKSHOP_REPO_URL            https-адрес репозитория заказчика (обязателен)
#   WORKSHOP_REPO_BRANCH         ветка (умолчание main)
#   WORKSHOP_TG_BOT_TOKEN        токен бота мессенджера (секрет, обязателен)
#   WORKSHOP_FORGE_TOKEN         токен системного аккаунта с правом записи в репозиторий (секрет, обязателен)
#   WORKSHOP_DAEMON_PAUSE_SECONDS            пауза между проходами поллера (умолчание 2)
#   WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS  период сторожа (умолчание 7200 — как крон CI-обёртки)
#   WORKSHOP_DAEMON_FAILURE_BACKOFF_SECONDS  пауза после сбоя инструмента, rc=10 (умолчание 60)
# Токен форжи не пишется на диск: git берёт его из окружения через credential helper.
set -u -o pipefail
: "${WORKSHOP_REPO_URL:?WORKSHOP_REPO_URL не задан}"
: "${WORKSHOP_TG_BOT_TOKEN:?WORKSHOP_TG_BOT_TOKEN не задан}"
: "${WORKSHOP_FORGE_TOKEN:?WORKSHOP_FORGE_TOKEN не задан}"
BRANCH="${WORKSHOP_REPO_BRANCH:-main}"
PAUSE="${WORKSHOP_DAEMON_PAUSE_SECONDS:-2}"
HB_EVERY="${WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS:-7200}"
BACKOFF="${WORKSHOP_DAEMON_FAILURE_BACKOFF_SECONDS:-60}"
REPO=/repo
log() { printf '%s daemon %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
# все задержки и период — ASCII-десятичные положительные целые не длиннее 9 цифр (иначе sleep/арифметика bash молча
# ломаются или переполняются — ревью #840 W3)
for v in PAUSE:"$PAUSE" HB_EVERY:"$HB_EVERY" BACKOFF:"$BACKOFF"; do
  case "${v#*:}" in [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) log "${v%%:*}=${v#*:} не положительное целое (1..999999999) — отказ старта"; exit 10 ;; esac
done

# ОСТАНОВКА (ревью #840 W1/B3, раунды 1–5): PID 1 — init контейнера (compose init: true), он передаёт TERM этому bash.
# TERM/INT ставят stopping и уходят активному дочернему процессу; run() ОПРАШИВАЕТ живость ребёнка (kill -0) и при stopping
# посылает TERM заново каждые полсекунды (один сигнал теряется, если пришёл форку bash до exec), статус берёт wait после
# завершения; после stopping ни run(), ни nap() новых процессов не запускают; все внешние команды цикла (в т.ч. git) идут
# через run(). Остаточный риск конструкции: повторное использование PID между смертью ребёнка и опросом (последовательный
# демон в своём PID-namespace — практически недостижимо; ревью р.5 W6).
child=""; stopping=0
on_stop() { stopping=1; [ -n "$child" ] && kill -TERM "$child" 2>/dev/null; }
trap on_stop TERM INT
run() {
  [ "$stopping" -eq 1 ] && return 143
  "$@" & child=$!
  # Пока ребёнок жив: при stopping посылать TERM ЗАНОВО каждые полсекунды — один TERM теряется, если пришёл форку bash
  # до exec (обработчик родителя его «съедает», а exec сбрасывает); окно между проверкой и регистрацией PID (раунд 3 B3)
  # закрывается тем же циклом. Ожидание — опросом kill -0 (builtin), статус — wait по завершении (bash хранит его до wait).
  while kill -0 "$child" 2>/dev/null; do
    [ "$stopping" -eq 1 ] && kill -TERM "$child" 2>/dev/null
    sleep 0.5
  done
  local rc
  wait "$child"; rc=$?
  child=""
  return $rc
}
nap() { run sleep "$1"; }

git config --global credential.helper '!f() { echo username=x-access-token; echo "password=$WORKSHOP_FORGE_TOKEN"; }; f'
git config --global safe.directory "$REPO"
if [ ! -d "$REPO/.git" ]; then
  log "clone $WORKSHOP_REPO_URL ($BRANCH)"
  run git clone -q --branch "$BRANCH" "$WORKSHOP_REPO_URL" "$REPO" || { log "clone failed"; exit 10; }
fi
cd "$REPO" || exit 10
git config core.hooksPath .workshop/hooks

release_sig=""
ensure_validator() {
  # бинарь валидатора — пиннованный релиз из репозитория заказчика; перекачивается только при смене
  local sig
  sig=$(sha256sum .workshop/bot/kit/validator-release.yaml | cut -c1-64) || return 1
  if [ "$sig" != "$release_sig" ] || [ ! -x .workshop-bin/workshop-validator ]; then
    run python3 .workshop/bot/kit/install.py validator || return 1
    release_sig="$sig"
  fi
}

# ПРОВЕРКА НАСТРОЕК — одна функция для старта и для каждого обновления bot.yaml (ревью #840 B1/B2): период сторожа
# (обе величины точной арифметикой Python; 3 = не объявлен, не сверяется) И инвариант установщика (окно уведомление→отмена,
# период против cron при наличии обёртки, карта людей — install.py check-people, тот же, что у bootstrap).
PERIOD_CHECK=$(cat <<'PY'
import os, re, sys
sys.path.insert(0, ".workshop/bot")
import yamlmini
ev = os.environ.get("WORKSHOP_HB_EVERY", "")
if not re.fullmatch(r"[1-9][0-9]{0,8}", ev):
    print("WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS=%r не положительное целое (1..999999999)" % ev); sys.exit(10)
wd = yamlmini.load_file(".workshop/bot.yaml").get("watchdog") or {}
if "heartbeat_period_minutes" not in wd:
    print("watchdog.heartbeat_period_minutes не объявлен — период сторожа не сверяется (heartbeat_every=%ss)" % ev); sys.exit(3)
v = wd["heartbeat_period_minutes"]
if not (isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 999999):
    print("watchdog.heartbeat_period_minutes=%r не положительное целое (1..999999)" % (v,)); sys.exit(10)
if v * 60 != int(ev):
    print("watchdog.heartbeat_period_minutes=%d не совпадает с WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS=%s" % (v, ev)); sys.exit(10)
print("период сторожа сверен: %d мин" % v)
PY
)
check_settings() {
  # Python-проверка — тоже через run() (управляемая остановка, раунд 3 W5): stdin фоновому процессу недоступен, поэтому код —
  # аргументом -c; вывод — в приватный временный файл (mktemp, не общий путь)
  local tmpf prc
  tmpf=$(mktemp) || return 1
  WORKSHOP_HB_EVERY="$HB_EVERY" run python3 -c "$PERIOD_CHECK" > "$tmpf" 2>&1; prc=$?
  log "$(cat "$tmpf")"; rm -f "$tmpf"
  [ "$stopping" -eq 1 ] && return 1
  case "$prc" in 0|3) ;; *) return 1 ;; esac
  run python3 .workshop/bot/kit/install.py check-people || return 1
}

log "start: branch=$BRANCH pause=${PAUSE}s heartbeat_every=${HB_EVERY}s backoff=${BACKOFF}s"
cfg_seen=""        # blob bot.yaml, прошедший проверку; пустой — ещё не проверялся (первый проход — после pull, чтобы
                   # исправленные настройки доезжали и при рестарте контейнера, а не проверялся вечно старый клон — B1)
last_hb=0
while [ "$stopping" -eq 0 ]; do
  run git pull -q --ff-only origin "$BRANCH" 2>/dev/null; prc=$?
  [ "$stopping" -eq 1 ] && break                       # проверка остановки — после КАЖДОГО шага, независимо от его rc (раунд 3 W5)
  [ "$prc" -ne 0 ] && log "pull --ff-only не прошёл: локальная копия впереди origin, поллер разберётся сам"
  cfg_now=$(git rev-parse HEAD:.workshop/bot.yaml 2>/dev/null || echo none)
  if [ "$cfg_now" != "$cfg_seen" ]; then
    if check_settings; then cfg_seen="$cfg_now"; log "настройки проверены ($cfg_now)"
    else [ "$stopping" -eq 1 ] && break; log "настройки ($cfg_now) не прошли проверку — поллер и сторож не запускаются, повтор после pull через ${BACKOFF}s"; nap "$BACKOFF"; continue; fi
  fi
  [ "$stopping" -eq 1 ] && break
  if ! ensure_validator; then [ "$stopping" -eq 1 ] && break; log "validator: сбой установки, backoff ${BACKOFF}s"; nap "$BACKOFF"; continue; fi
  run python3 .workshop/bot/poll.py; rc=$?
  [ "$stopping" -eq 1 ] && break
  case "$rc" in
    0|2) : ;;
    *) log "poll rc=$rc — сбой инструмента, backoff ${BACKOFF}s"; nap "$BACKOFF" ;;
  esac
  [ "$stopping" -eq 1 ] && break
  if [ $(( $(date +%s) - last_hb )) -ge "$HB_EVERY" ]; then
    hb_started=$(date +%s)
    if run python3 .workshop/bot/heartbeat.py; then last_hb=$hb_started
    else rc=$?; [ "$stopping" -eq 1 ] && break; log "heartbeat rc=$rc — сбой инструмента, повтор через ${BACKOFF}s"; last_hb=$(( $(date +%s) - HB_EVERY + BACKOFF )); fi   # повтор через backoff ОТ МОМЕНТА ошибки, не от начала попытки (W2)
  fi
  nap "$PAUSE"
done
log "stop: сигнал получен, цикл завершён"
