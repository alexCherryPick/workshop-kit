# -*- coding: utf-8 -*-
"""attach.contract — машинно-читаемый контракт интерфейса адаптера (D20 T4): схема JSON вывода CLI, перечни исходов,
коды выхода. Для потребителей: CLI комплекта, бот (D18), будущие фронты D07/D12 (они реализуют норму сами; здесь —
описание интерфейса, не вторая реализация).

ВЫВОД ИЗ НОРМЫ, а не рукописная копия: все перечни (исходы чтения и записи с их смыслом, состояния, причины, пометки
unsaved, цели маршрута, факты статуса) берутся из attach.norm (генерация из attachments.yaml) и из подмножеств кода,
сверенных с нормой при импорте (attach.repo). Литералов исходов, состояний и причин в этом модуле нет — проверяется
AST-тестом (test_attach_api.ContractFromNorm) и мутацией «схема переписана руками».

Схема — JSON Schema (подмножество ключевых слов: type, enum, const, properties, required, additionalProperties, items,
oneOf, $ref, $defs, minimum), чтобы её проверял любой валидатор, в т. ч. независимый мини-валидатор теста.
Файл `bot/attach/cli-output.schema.json` — сериализация build_schema() (python3 -m bot.attach schema); тест роняет
прогон при расхождении файла и генерации.
"""
import json

from . import norm as N
from . import pointer as P
from . import repo as R

__all__ = ["OUTPUT_SCHEMA_VERSION", "EXIT_CODES", "COMMANDS", "ADAPTER_FAULT", "INPUT_ERROR", "build_schema",
           "schema_bytes", "outcomes_registry"]

OUTPUT_SCHEMA_VERSION = 1      # версия схемы ВЫВОДА CLI (не версия нормы): меняется при любой несовместимой правке формы
SCHEMA_ID = "urn:cherrypick-workshop:attach-cli-output:%d" % OUTPUT_SCHEMA_VERSION
from .core import ADAPTER_FAULT  # noqa: E402 — собственный фатальный исход адаптера, вне таблиц нормы
INPUT_ERROR = "input"              # ошибка входа вызывающего: адаптер не действовал (не исход нормы)

# Коды выхода — ЗАКРЫТЫЙ перечень. Отрицательный исход нормы (storage-denied, sha-mismatch, unsaved …) — rc 0: команда
# исполнена, исход — в выводе; вызывающий судит по полю, а не по rc.
EXIT_CODES = (
    (0, "executed", "команда исполнена; исход нормы — в полях вывода (outcome / state / storage_probe_outcome …)"),
    (2, INPUT_ERROR, "вход вне контракта (аргументы, путь, состояние по пути); адаптер не действовал"),
    (3, ADAPTER_FAULT, "собственная ошибка адаптера (неожиданное исключение, порча конфига, сбой разбора своего вывода, "
                       "дрейф реестров нормы) — фатальный исход вне таблиц нормы"),
)

# Подкоманды CLI и форма их результата (ключ $defs).
COMMANDS = (
    ("route", "route"),
    ("write", "write_result"),
    ("read", "read_result"),
    ("verify", "read_result"),
    ("classify", "classify"),
    ("fail-pending", "write_result"),
    ("complete-pending", "write_result"),
    ("late-save", "write_result"),
    ("withdraw", "write_result"),
    ("withdraw-key-set", "withdraw_key_set"),
    ("key-paths", "key_paths"),
    ("probe", "probe"),
    ("status", "status"),
)


def _states():
    return [s for s, _c, _r in N.STATES]


def _reasons():
    out = []
    for _s, _c, rs in N.STATES:
        out += [r for r in rs if r not in out]
    return out


def _route_targets():
    out = []
    for o in N.ROUTING_OUTCOMES:          # составной исход маршрута storage_or_unsaved раскрывается в свои части
        out += [p for p in o.split("_or_") if p not in out]
    return out


def _classify_kinds():
    out = []
    for _s, carrier, _r in N.STATES:     # носители нормы: bytes (git) и pointer — классы содержимого, которые судятся
        out += [carrier] if carrier not in out else []
    return out + [k for k, _o in R.NOT_JUDGED]


def _nullable(d):
    return {"oneOf": [{"type": "null"}, d]}


def _str():
    return {"type": "string"}


def _int():
    return {"type": "integer", "minimum": 0}


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": sorted(required if required is not None else props),
            "additionalProperties": False}


def _envelope(command_const, outcome_schema):
    return {"output_schema_version": {"const": OUTPUT_SCHEMA_VERSION}, "command": command_const,
            "outcome": outcome_schema}


def build_schema():
    """Схема вывода CLI (--json): один JSON-объект на прогон; oneOf по форме команды и двум формам ошибки."""
    states = _states()
    defs = {
        "read_outcome": {"enum": list(N.READ_OUTCOMES), "x-meanings": dict(N.READ_OUTCOME_MEANINGS)},
        "write_outcome": {"enum": list(N.WRITE_OUTCOMES), "x-meanings": dict(N.WRITE_OUTCOME_MEANINGS)},
        "state": {"enum": states},
        "reason": {"enum": _reasons()},
        "user_mark": {"enum": [m for _r, m in N.UNSAVED_REASONS], "x-reasons": dict((m, r) for r, m in N.UNSAVED_REASONS)},
        "probe_outcome": {"enum": list(R.PROBE_OUTCOMES)},
        "verification_failure": {"enum": list(R.VERIFICATION_FAILURES)},
        "route_target": {"enum": _route_targets()},
        "route_obj": _obj({"target": {"$ref": "#/$defs/route_target"},
                           "reason": _nullable({"$ref": "#/$defs/reason"}),
                           "step": _int()}),
        "write_fields": _obj({"state": {"$ref": "#/$defs/state"},
                              "outcome": _nullable({"$ref": "#/$defs/write_outcome"}),
                              "staged": {"type": "array", "items": _str()},
                              "path": _str(),
                              "reason": _nullable({"$ref": "#/$defs/reason"}),
                              "user_mark": _nullable({"$ref": "#/$defs/user_mark"}),
                              "detail": _nullable(_str()),
                              "route": _nullable({"$ref": "#/$defs/route_obj"})}),
    }
    per = {}
    per["route"] = dict(_envelope({"const": "route"}, {"type": "null"}),
                        target={"$ref": "#/$defs/route_target"}, reason=_nullable({"$ref": "#/$defs/reason"}),
                        step=_int())
    write_props = dict(defs["write_fields"]["properties"])
    write_props.pop("outcome")
    per["write_result"] = dict(_envelope({"enum": [c for c, f in COMMANDS if f == "write_result"]},
                                         _nullable({"$ref": "#/$defs/write_outcome"})), **write_props)
    per["read_result"] = dict(_envelope({"enum": [c for c, f in COMMANDS if f == "read_result"]},
                                        {"$ref": "#/$defs/read_outcome"}),
                              state=_nullable({"$ref": "#/$defs/state"}), reason=_nullable({"$ref": "#/$defs/reason"}),
                              source=_nullable(_str()), detail=_nullable(_str()), size=_nullable(_int()))
    per["classify"] = dict(_envelope({"const": "classify"}, {"type": "null"}),
                           kind={"enum": _classify_kinds()}, state=_nullable({"$ref": "#/$defs/state"}),
                           version=_nullable(_str()), defect=_nullable(_str()))
    per["probe"] = dict(_envelope({"const": "probe"}, {"type": "null"}),
                        storage_configured={"type": "boolean"},
                        storage_probe_outcome=_nullable({"$ref": "#/$defs/probe_outcome"}), detail=_nullable(_str()))
    counts_states = _obj(dict((s, _int()) for s in P.POINTER_STATES))
    counts_nj = _obj(dict((o, _int()) for _k, o in R.NOT_JUDGED))
    per["status"] = dict(
        _envelope({"const": "status"}, {"type": "null"}),
        storage_configured={"type": "boolean"},
        storage_probe_outcome=_nullable({"$ref": "#/$defs/probe_outcome"}),
        probe_detail=_nullable(_str()),
        pointers_by_state=counts_states,
        bytes_in_git=_int(),
        not_judged=counts_nj,
        non_regular=_int(),
        last_verification_failures=_nullable({"type": "array", "items": _obj(
            {"path": _str(), "outcome": {"$ref": "#/$defs/verification_failure"}})}),
        verification=_nullable(_obj({"checked": _int(),
                                     "outcomes": _obj(dict((o, _int()) for o in N.READ_OUTCOMES), required=[]),
                                     "truncated": {"type": "boolean"}, "input_errors": _int()})))
    per["key_paths"] = dict(_envelope({"const": "key-paths"}, {"type": "null"}),
                            key=_str(), paths={"type": "array", "items": _str()},
                            unsaved_same_sha256={"type": "array", "items": _str()})
    per["withdraw_key_set"] = dict(_envelope({"const": "withdraw-key-set"}, {"type": "null"}),
                                   key=_str(),
                                   results={"type": "array", "items": _obj({
                                       "path": _str(), "error": _nullable({"const": INPUT_ERROR}),
                                       "detail": _nullable(_str()),
                                       "result": _nullable({"$ref": "#/$defs/write_fields"})})},
                                   staged={"type": "array", "items": _str()}, complete={"type": "boolean"},
                                   unsaved_same_sha256={"type": "array", "items": _str()})
    all_commands = {"enum": [c for c, _f in COMMANDS]}
    per["input_error"] = dict(_envelope(_nullable(all_commands), {"type": "null"}), error={"const": INPUT_ERROR},
                              detail=_str())
    per["adapter_fault"] = dict(_envelope(_nullable(all_commands), {"const": ADAPTER_FAULT}), error=_str())
    for name, props in per.items():
        defs["cmd_" + name] = _obj(props)
    return {
        "$id": SCHEMA_ID,
        "$comment": "JSON Schema (draft 2020-12, подмножество ключевых слов). СГЕНЕРИРОВАНО attach.contract.build_schema "
                    "из реестров нормы %s (sha256 %s) — не править руками." % (N.SOURCE_PATH, N.SOURCE_SHA256),
        "title": "workshop attach CLI --json output",
        "x-output-schema-version": OUTPUT_SCHEMA_VERSION,
        "x-norm": {"spec": N.SPEC, "chapter": N.CHAPTER, "schema_version": N.SCHEMA_VERSION,
                   "source_sha256": N.SOURCE_SHA256},
        "x-exit-codes": [{"rc": rc, "name": name, "meaning": m} for rc, name, m in EXIT_CODES],
        "x-commands": dict(COMMANDS),
        "x-status-facts": list(N.STATUS_FACTS),
        "oneOf": [{"$ref": "#/$defs/cmd_" + name} for name in sorted(per)],
        "$defs": defs,
    }


def schema_bytes():
    """Каноническая сериализация (файл bot/attach/cli-output.schema.json): ключи отсортированы, отступ 1, LF в конце."""
    return (json.dumps(build_schema(), ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def outcomes_registry():
    """Перечни исходов для потребителей (то же, что в схеме): {read, write, fatal, probe, verification_failures}."""
    return {"read": list(N.READ_OUTCOMES), "write": list(N.WRITE_OUTCOMES), "fatal": ADAPTER_FAULT,
            "probe": list(R.PROBE_OUTCOMES), "verification_failures": list(R.VERIFICATION_FAILURES)}
