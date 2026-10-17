# -*- coding: utf-8 -*-
"""Автообслуживание git в одноразовых репо тестов выключено (D19, флейк 2026-10-14): фоновый `git maintenance`
создаёт и удаляет `maintenance.lock` в клоне, пока тест сносит его `shutil.rmtree` → FileNotFoundError (2 из 24
при 8 параллельных прогонах). Через окружение (GIT_CONFIG_COUNT/KEY/VALUE) — наследуют ВСЕ дочерние git: тестов,
установщика и продукта в стенде. Идемпотентно: повторный импорт не дублирует ключи. Тот же класс закрыт на main
в bot/tests/test_install_ai.py (_quiet_git_env, адверсарий B, m2)."""
import os

_KEYS = (("maintenance.auto", "false"), ("gc.auto", "0"))


def quiet():
    n = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
    have = {os.environ.get("GIT_CONFIG_KEY_%d" % i) for i in range(n)}
    for k, v in _KEYS:
        if k in have:
            continue
        os.environ["GIT_CONFIG_KEY_%d" % n] = k
        os.environ["GIT_CONFIG_VALUE_%d" % n] = v
        n += 1
    os.environ["GIT_CONFIG_COUNT"] = str(n)


quiet()
