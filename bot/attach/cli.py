# -*- coding: utf-8 -*-
"""attach.cli — CLI адаптера вложений (D20 T4; тонкий CLI T2 — его подмножество).

Запуск: `python3 -m bot.attach …` (монорепо), `python3 -m attach …` (bot/ в sys.path) и из РАЗЛОЖЕННОГО комплекта
заказчика — `python3 .workshop/bot/attach …` (каталог пакета исполняется как скрипт, см. __main__.py).

Режимы вывода: по умолчанию — человекочитаемый (строки «поле: значение»); `--json` — ОДИН JSON-объект на прогон по
схеме attach.contract (поле output_schema_version; схема — `schema`, файл bot/attach/cli-output.schema.json).
Поле outcome — исход нормы (adapter_outcomes.read | .write) либо собственный adapter-fault; других значений нет.
Коды выхода — закрытый перечень attach.contract.EXIT_CODES: 0 исполнено (исход — в выводе), 2 ошибка входа (адаптер не
действовал; в т. ч. ошибка разбора аргументов), 3 собственная ошибка адаптера.

Конфиг: `--repo DIR` (по умолчанию текущий каталог) — .workshop/storage.yaml репозитория (формат T3); `--config FILE` —
JSON с фактами storage_binding (прогоны T2/T6). Оба сразу — ошибка входа. Значения ключей — только из окружения по
ИМЕНАМ конфига; ни значение, ни key_prefix в вывод не попадают (маскирование клиента T2 + проверка теста).

Изъятие — только человеком: `withdraw` / `withdraw-key-set` требуют явного флага --confirm-withdraw и ИМЁН переменных
окружения ключа изъятия, отличных от имён ключа писателя конфига (ключ бота DELETE не получает).
"""
import argparse
import json
import os
import sys

from . import contract as K
from . import core as C
from . import pointer as P
from . import repo as R

__all__ = ["main"]


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):            # ошибка разбора аргументов — rc 2 закрытого перечня, в форме вывода режима
        raise _UsageError(message)


def _parser():
    ap = _Parser(prog="python3 -m bot.attach", description="адаптер вложений (D20 T2/T4)")
    ap.add_argument("--json", action="store_true", help="один JSON-объект по схеме вывода (attach.contract)")
    ap.add_argument("--repo", help="корень репозитория заказчика (.workshop/storage.yaml); по умолчанию текущий каталог")
    ap.add_argument("--config", help="JSON с фактами storage_binding (прогоны T2/T6) вместо .workshop/storage.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

    def add(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        return p
    p = add("route")
    p.add_argument("--size", type=int)
    p.add_argument("--data")
    p.add_argument("--not-obtained", action="store_true")
    p = add("write", help="записать вложение по маршруту нормы (git | хранилище | не сохранено)",
            description="Записать вложение в рабочее дерево по маршруту нормы. Пути в выводе: path — путь вложения "
                        "ОТНОСИТЕЛЬНО КАТАЛОГА ЗАПИСИ (attachments/<id записи>/<имя>), ровно в форме ссылки в тексте "
                        "записи; staged — пути файловой системы для коммита вместе с текстом. read, verify, "
                        "withdraw и key-paths ждут путь файловой системы — берите его из staged, не из path.")
    p.add_argument("--record-dir", required=True, help="каталог файла записи (комменты лежат там же)")
    p.add_argument("--record-id", required=True)
    p.add_argument("--uuid")
    p.add_argument("--slug")
    p.add_argument("--ext", required=True)
    p.add_argument("--data", help="файл с байтами; без него — источник не отдал байты")
    p.add_argument("--declared-size", type=int)
    p.add_argument("--media-type")
    p.add_argument("--source")
    p.add_argument("--durable-queue", action="store_true")
    p.add_argument("--defer-upload", action="store_true")
    for name in ("read", "verify", "fail-pending", "classify", "key-paths"):
        p = add(name)
        p.add_argument("path")
        if name == "read":
            p.add_argument("--out", help="куда положить байты (только при in-git | ok; не под attachments/)")
    for name in ("complete-pending", "late-save"):
        p = add(name)
        p.add_argument("path")
        p.add_argument("--data", required=True)
    for name in ("withdraw", "withdraw-key-set"):
        p = add(name)
        p.add_argument("path")
        p.add_argument("--reason", required=True)
        p.add_argument("--withdraw-key-id-env", required=True, help="ИМЯ переменной окружения человека (не значение)")
        p.add_argument("--withdraw-secret-env", required=True, help="ИМЯ переменной окружения человека (не значение)")
        p.add_argument("--confirm-withdraw", action="store_true",
                       help="явное подтверждение: изъятие удаляет объект и необратимо переводит указатель в withdrawn")
    add("probe")
    p = add("status")
    p.add_argument("--verify", action="store_true", help="проверить stored/pending (GET + sha256) — сбои последней проверки")
    p.add_argument("--max-pointers", type=int)
    add("schema")
    return ap


def _bytes(fp):
    with open(fp, "rb") as f:
        return f.read()


def _config(a):
    if a.config is not None and a.repo is not None:
        raise C.AttachInputError("--config и --repo вместе: источник конфига один")
    if a.config is not None:
        try:
            with open(a.config, "rb") as f:
                m = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            raise C.ConfigError("конфиг не читается: %s" % type(e).__name__) from None
        return C.load_config(m)
    return R.load_repo_config(a.repo if a.repo is not None else os.getcwd())


def _withdraw_names(a, cfg):
    if not a.confirm_withdraw:
        raise C.AttachInputError("изъятие необратимо: нужен явный флаг --confirm-withdraw")
    wc = {"access_key_id": a.withdraw_key_id_env, "secret_access_key": a.withdraw_secret_env}
    if cfg.binding is not None and set(wc.values()) & set(cfg.binding.cred_names):
        raise C.AttachInputError("ключ изъятия — ключ человека: имена переменных не совпадают с ключом писателя конфига")
    return wc


def _run(a):
    """-> dict полей результата — без конверта. Пути аргументов — без ведущих `./` (R.plain_path)."""
    for k in ("path", "record_dir", "out", "repo"):
        if getattr(a, k, None) is not None:
            setattr(a, k, R.plain_path(getattr(a, k)))
    cmd = a.cmd
    if cmd == "classify":
        c = P.classify(_bytes(a.path))
        return {"kind": c.kind, "state": P.state_of(c), "version": c.version, "defect": c.defect}
    cfg = _config(a)
    if cmd == "route":
        data = _bytes(a.data) if a.data else b""
        size = len(data) if a.data else a.size
        r = C.route(size, cfg, obtained=not a.not_obtained, data_prefix=data)
        return {"target": r.target, "reason": r.reason, "step": r.step}
    if cmd == "write":
        data = _bytes(a.data) if a.data else None
        return C.write_attachment(a.record_dir, a.record_id, data, ext=a.ext, config=cfg, uuid=a.uuid, slug=a.slug,
                                  source=a.source, media_type=a.media_type, declared_size=a.declared_size,
                                  durable_queue=a.durable_queue, defer_upload=a.defer_upload).as_dict()
    if cmd in ("read", "verify"):
        if cmd == "read" and a.out:
            C._guard(C._check_out)(a.out, a.path)   # назначение судится ДО чтения: отказ не зависит от исхода
        res = (C.read_attachment if cmd == "read" else C.verify)(a.path, cfg)
        if cmd == "read" and a.out and res.data is not None:
            C.save_bytes_outside_carriers(a.out, res.data, source_path=a.path)
        return res.as_dict()
    if cmd == "fail-pending":
        return C.fail_pending(a.path).as_dict()
    if cmd == "complete-pending":
        return C.complete_pending(a.path, _bytes(a.data), cfg).as_dict()
    if cmd == "late-save":
        return C.late_save(a.path, _bytes(a.data), cfg).as_dict()
    if cmd == "withdraw":
        return C.withdraw(a.path, a.reason, cfg, _withdraw_names(a, cfg)).as_dict()
    if cmd == "withdraw-key-set":
        wc = _withdraw_names(a, cfg)
        res = R.withdraw_key_set(a.repo if a.repo is not None else os.getcwd(), a.path, a.reason, cfg, wc)
        items = [dict(it, result=None if it["result"] is None else it["result"].as_dict()) for it in res["results"]]
        return {"key": res["key"], "results": items, "staged": res["staged"], "complete": res["complete"],
                "unsaved_same_sha256": res["unsaved_same_sha256"]}
    if cmd == "key-paths":
        return R.paths_with_key(a.repo if a.repo is not None else os.getcwd(), R.key_of(a.path))
    if cmd == "probe":
        return C.probe_storage(cfg)
    if cmd == "status":
        return R.status(a.repo if a.repo is not None else os.getcwd(), cfg, verify=a.verify,
                        max_pointers=a.max_pointers)
    raise C.AdapterFault("команда вне CLI")


def _envelope(cmd, fields):
    out = {"output_schema_version": K.OUTPUT_SCHEMA_VERSION, "command": cmd}
    if "outcome" not in fields:
        out["outcome"] = None
    out.update(fields)
    return out


def _human(obj, stream):
    for k in sorted(obj):
        v = obj[k]
        if k == "output_schema_version":
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, sort_keys=True)
        elif v is None:
            v = "—"
        elif v is True or v is False:
            v = "true" if v else "false"
        stream.write("%s: %s\n" % (k, v))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    cmd = None
    try:
        a = _parser().parse_args(argv)
        cmd = a.cmd
        as_json = bool(getattr(a, "json", False)) or as_json
        if cmd == "schema":
            sys.stdout.buffer.write(K.schema_bytes())
            sys.stdout.flush()
            return 0
        out, rc = _envelope(cmd, _run(a)), 0
    except _UsageError as e:
        out, rc = _envelope(cmd, {"error": K.INPUT_ERROR, "detail": "аргументы: %s" % e}), 2
    except C.AdapterFault as e:
        out, rc = _envelope(cmd, {"outcome": C.ADAPTER_FAULT, "error": str(e)}), 3
    except C.AttachInputError as e:
        out, rc = _envelope(cmd, {"error": K.INPUT_ERROR, "detail": str(e)}), 2
    except OSError as e:
        out, rc = _envelope(cmd, {"error": K.INPUT_ERROR, "detail": type(e).__name__}), 2
    except Exception as e:  # noqa: BLE001 — последняя сеть: фатальный исход, без текста исключения
        out, rc = _envelope(cmd, {"outcome": C.ADAPTER_FAULT, "error": "неожиданная ошибка: %s" % type(e).__name__}), 3
    if as_json:
        sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        _human(out, sys.stdout)
    return rc
