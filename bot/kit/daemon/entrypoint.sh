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
log "start: branch=$BRANCH pause=${PAUSE}s heartbeat_every=${HB_EVERY}s"
while :; do
  git pull -q --ff-only origin "$BRANCH" 2>/dev/null || log "pull --ff-only не прошёл: локальная копия впереди origin, поллер разберётся сам"
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
