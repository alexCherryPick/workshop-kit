# workshop-bot-daemon — образ ДЕМОНА поллера для всегда-включённой машины заказчика (вторая форма
# запуска рядом с CI-обёртками kit/workflows; D09 §1Д, вердикт alex 2026-09-12: VM заказчика,
# не CI-крон). Образ НЕ несёт комплекта: комплект уже установлен bootstrap-обёрткой в репозиторий
# заказчика (.workshop/bot/*), а демон лишь держит его клон и гоняет poll.py в цикле с длинным
# опросом. Что в образе: python3 (stdlib достаточно), git, сертификаты. Пинов здесь нет — пин
# комплекта и валидатора живёт в репозитории заказчика (validator-release.yaml), демон его читает.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /usr/local/bin/workshop-bot-daemon
RUN chmod 0755 /usr/local/bin/workshop-bot-daemon
WORKDIR /repo
ENTRYPOINT ["/usr/local/bin/workshop-bot-daemon"]
