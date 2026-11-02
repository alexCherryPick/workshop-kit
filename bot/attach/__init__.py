# -*- coding: utf-8 -*-
"""attach — адаптер вложений git / S3-совместимого хранилища (D20 T2, интерфейсы — D20 T4).

API адаптера — attach.core; API для бота (D18) — attach.botapi (без изъятия); корпус, статус, один key — attach.repo;
CLI — attach.cli (`python3 -m bot.attach`, из комплекта заказчика `python3 .workshop/bot/attach`); машинно-читаемый
контракт (схема --json, исходы, коды выхода) — attach.contract и файл cli-output.schema.json.
Пакет разложен в комплект заказчика целиком (build_manifest._layout: bot/attach/*.py → .workshop/bot/attach/, роль
code; генератор gen_attach_norm.py — инструмент сборки, не ставится).
Модули: norm (СГЕНЕРИРОВАН из attachments.yaml), pointer (разбор/запись указателя, суд переходов),
s3 (SigV4-клиент на stdlib), fsio (носитель через дескрипторы), core (маршрут, запись, чтение, досохранение,
изъятие), repo, botapi, contract, cli."""
import os as _os
import sys as _sys

_BOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _BOT not in _sys.path:          # раскладка бота плоская: core берёт comment.uuid7_random
    _sys.path.append(_BOT)

from .core import (ADAPTER_FAULT, AdapterFault, ConfigError, AttachInputError, Config, Binding, Route,  # noqa: E402,F401
                   WriteResult, ReadResult, load_config, route, write_attachment, read_attachment, verify,
                   complete_pending, confirm_pending, fail_pending, late_save, withdraw, probe_storage, ensure_canary, CANARY_BODY,
                   save_bytes_outside_carriers, attachment_relpath, main)
