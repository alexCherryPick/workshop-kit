# -*- coding: utf-8 -*-
"""CLI адаптера (attach.cli): `python3 -m bot.attach …` (из корня монорепо), `python3 -m attach …` (bot/ в sys.path) или
`python3 .workshop/bot/attach …` из РАЗЛОЖЕННОГО комплекта заказчика — каталог пакета исполняется как скрипт: тогда
пакета нет (__package__ пуст), каталог пакета стоит в sys.path[0] и снимается (модули пакета не должны быть видны как
модули верхнего уровня), а каталог бота добавляется В КОНЕЦ sys.path (stdlib впереди: модуль бота secrets.py не
заслоняет одноимённый модуль stdlib)."""
import os
import sys

if __package__ in (None, ""):
    _PKG = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _PKG]
    sys.path.append(os.path.dirname(_PKG))
    from attach.cli import main
else:
    from .cli import main

sys.exit(main())
