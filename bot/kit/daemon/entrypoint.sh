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
set -u
: "${WORKSHOP_REPO_URL:?WORKSHOP_REPO_URL не задан}"
: "${WORKSHOP_TG_BOT_TOKEN:?WORKSHOP_TG_BOT_TOKEN не задан}"
: "${WORKSHOP_FORGE_TOKEN:?WORKSHOP_FORGE_TOKEN не задан}"
BRANCH="${WORKSHOP_REPO_BRANCH:-main}"
PAUSE="${WORKSHOP_DAEMON_PAUSE_SECONDS:-2}"
HB_EVERY="${WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS:-7200}"
BACKOFF="${WORKSHOP_DAEMON_FAILURE_BACKOFF_SECONDS:-60}"
REPO=/repo
log() { printf '%s daemon %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

git config --global credential.helper '!f() { echo username=x-access-token; echo "password=$WORKSHOP_FORGE_TOKEN"; }; f'
git config --global safe.directory "$REPO"
if [ ! -d "$REPO/.git" ]; then
  log "clone $WORKSHOP_REPO_URL ($BRANCH)"
  git clone -q --branch "$BRANCH" "$WORKSHOP_REPO_URL" "$REPO" || { log "clone failed"; exit 10; }
fi
cd "$REPO" || exit 10
git config core.hooksPath .workshop/hooks

release_sig=""
ensure_validator() {
  # бинарь валидатора — пиннованный релиз из репозитория заказчика; перекачивается только при смене пина
  local sig
  sig=$(sha256sum .workshop/bot/kit/validator-release.yaml | cut -c1-64)
  if [ "$sig" != "$release_sig" ] || [ ! -x .workshop-bin/workshop-validator ]; then
    python3 .workshop/bot/kit/install.py validator || return 1
    release_sig="$sig"
  fi
}

last_hb=0
# сверка периода сторожа: обе величины — ASCII-десятичные положительные целые, сравнение точной арифметикой Python
# (bash `[` при переполнении/нечисле молча даёт ложь — раунд 6 Codex W1); коды: 0 сверено, 3 не объявлен (не сверяется), иначе отказ
pmsg=$( (cd "$REPO" && WORKSHOP_HB_EVERY="$HB_EVERY" python3 - <<'PY'
import os, re, sys
sys.path.insert(0, ".workshop/bot")
import yamlmini
ev = os.environ.get("WORKSHOP_HB_EVERY", "")
if not re.fullmatch(r"[1-9][0-9]{0,8}", ev):
    print("WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS=%r не положительное целое (1..999999999) — отказ старта" % ev); sys.exit(10)
wd = yamlmini.load_file(".workshop/bot.yaml").get("watchdog") or {}
if "heartbeat_period_minutes" not in wd:
    print("watchdog.heartbeat_period_minutes не объявлен — период сторожа не сверяется (heartbeat_every=%ss)" % ev); sys.exit(3)
v = wd["heartbeat_period_minutes"]
if not (isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 999999):
    print("watchdog.heartbeat_period_minutes=%r не положительное целое (1..999999) — отказ старта" % (v,)); sys.exit(10)
if v * 60 != int(ev):
    print("watchdog.heartbeat_period_minutes=%d не совпадает с WORKSHOP_DAEMON_HEARTBEAT_EVERY_SECONDS=%s — отказ старта" % (v, ev)); sys.exit(10)
print("период сторожа сверен: %d мин" % v)
PY
) 2>&1); prc=$?
log "$pmsg"
case "$prc" in 0|3) ;; *) exit 10 ;; esac
# инвариант настроек сторожа (окно уведомление→отмена, период, карта людей) — тем же установщиком, что bootstrap (install.py check-people):
# один источник правила для обеих форм запуска; ветка «период не объявлен» его не обходит (раунд 7 Codex W2)
(cd "$REPO" && python3 .workshop/bot/kit/install.py check-people) || { log "check-people: настройки сторожа/карта людей не прошли проверку — отказ старта"; exit 10; }
log "start: branch=$BRANCH pause=${PAUSE}s heartbeat_every=${HB_EVERY}s"
cfg_seen=$(cd "$REPO" && git rev-parse HEAD:.workshop/bot.yaml 2>/dev/null || echo none)
while :; do
  git pull -q --ff-only origin "$BRANCH" 2>/dev/null || log "pull --ff-only не прошёл: локальная копия впереди origin, поллер разберётся сам"
  # действующий снимок настроек после обновления — тем же инвариантом, что при старте (раунд 8 Codex W1): изменился bot.yaml → check-people заново;
  # непрошедший снимок не потребляется (ни поллером, ни сторожем) до следующего обновления
  cfg_now=$(git rev-parse HEAD:.workshop/bot.yaml 2>/dev/null || echo none)
  if [ "$cfg_now" != "$cfg_seen" ]; then
    if python3 .workshop/bot/kit/install.py check-people; then cfg_seen="$cfg_now"; log "настройки обновлены и проверены ($cfg_now)"
    else log "check-people: обновлённые настройки не прошли проверку — цикл пропущен, backoff ${BACKOFF}s"; sleep "$BACKOFF"; continue; fi
  fi
  if ! ensure_validator; then log "validator: сбой установки, backoff ${BACKOFF}s"; sleep "$BACKOFF"; continue; fi
  python3 .workshop/bot/poll.py; rc=$?
  case "$rc" in
    0|2) : ;;
    *) log "poll rc=$rc — сбой инструмента, backoff ${BACKOFF}s"; sleep "$BACKOFF" ;;
  esac
  now=$(date +%s)
  if [ $((now - last_hb)) -ge "$HB_EVERY" ]; then
    python3 .workshop/bot/heartbeat.py || log "heartbeat rc=$? — сбой инструмента"
    last_hb=$now
  fi
  sleep "$PAUSE"
done
