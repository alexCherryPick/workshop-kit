#!/usr/bin/env python3
"""wrapper_predicate.py — СТРУКТУРНЫЙ предикат «тонкой обёртки» workflow-файла (D09 §2). Владелец — T1.

Не греп: файл читается строгим stdlib-лоадером (bot/yamlmini.py; дубль ключа — ошибка), затем
проверяется по allow-list'у из машиночитаемого контракта tg-bot.yaml (раздел thin_wrapper) —
allow-list живёт ТАМ, здесь копии нет. Применяется к bootstrap (T1), poller (T3), heartbeat (T5).

Использование:
  wrapper_predicate.py <workflow.yml> [--contract tg-bot.yaml] [--steps install-steps.yaml] [--require-hooks-path]
Вывод: строка `structure: PASS` либо `structure: FAIL <reason>[; <reason>…]` (причины — из
закрытого перечня failure_reasons контракта), затем `pins: filled` либо `pins: unfilled <n> …`.
Шаг checkout (`uses` из uses_prefixes): ключи `with` — только из checkout_with_keys контракта;
формы учётных данных — checkout_with_forms (каждый ключ — регэксп). Правило класса (В-4 «оба в
комплекте»): если секрет в `with.token` имеет `alternative` в реестре секретов, форма токена
ОБЯЗАНА нести фолбэк (иначе пустой секрет валит checkout) И альтернатива ОБЯЗАНА быть привязана
в том же шаге ключом ssh-key; секреты из `with` — только имена реестра.
rc: 0 — PASS и пины заполнены; 1 — PASS, но есть незаполненный пин (релизное состояние);
2 — FAIL структуры; 10 — сбой инструмента.
"""
import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import yamlmini  # noqa: E402

_CONTRACT_CANDIDATES = (
    "spec/09-tg-bot-time-line/tg-bot.yaml",
    "output/format-spec/09-tg-bot-time-line/tg-bot.yaml",
)
_SECRET_BINDING = re.compile(r"^\$\{\{\s*secrets\.([A-Z][A-Z0-9_]*)\s*\}\}$")
_STANDALONE_NUMBER = re.compile(r"(^|[\s=])-?[0-9]+(\.[0-9]+)?([\s]|$)")


def find_contract(explicit):
    if explicit:
        return explicit
    for c in _CONTRACT_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("контракт tg-bot.yaml не найден: укажи --contract")


def _keys_subset(mapping, allowed, reason, where, fails):
    for k in mapping.keys():
        if k not in allowed:
            fails.append("%s:%s@%s" % (reason, k, where))


def _check_env(env, where, secrets_allowed, fails):
    if env is None:
        return
    if not isinstance(env, dict):
        fails.append("env_not_secret_binding:%s" % where)
        return
    for k, v in env.items():
        m = _SECRET_BINDING.match(str(v)) if isinstance(v, str) else None
        if not m or m.group(1) != k:
            fails.append("env_not_secret_binding:%s@%s" % (k, where))
            continue
        if k not in secrets_allowed:
            fails.append("secret_not_in_registry:%s@%s" % (k, where))


def _check_run(run, where, run_forms, fails):
    if not isinstance(run, str):
        fails.append("run_not_single_call:%s" % where)
        return
    text = run.rstrip("\n")
    if "${{" in text:
        fails.append("expression_in_run:%s" % where)
        return
    if "\n" in text or "&&" in text or "||" in text or ";" in text or "|" in text or "`" in text or "$(" in text:
        fails.append("two_calls_in_run:%s" % where)
        return
    if re.search(r"(^|\s)(if|then|else|fi|case|for|while)(\s|$)", text):
        fails.append("if_in_step:%s" % where)
        return
    if _STANDALONE_NUMBER.search(text):
        fails.append("policy_literal_in_run:%s" % where)
        return
    for form in run_forms:
        if re.match(form["pattern"], text):
            return
    fails.append("run_not_single_call:%s" % where)


def _check_checkout_with(with_, where, al, secrets_by_name, fails):
    """`with` у шага checkout: ключи из allow-list; формы учётных данных; правило альтернативы."""
    if with_ is None:
        return
    if not isinstance(with_, dict):
        fails.append("checkout_with_key_not_allowed:not-a-mapping@%s" % where)
        return
    forms = dict((f["key"], re.compile(f["pattern"])) for f in al.get("checkout_with_forms") or [])
    for k in with_.keys():
        if k not in al["checkout_with_keys"]:
            fails.append("checkout_with_key_not_allowed:%s@%s" % (k, where))
    bound = {}
    for k, form in forms.items():
        if k not in with_:
            continue
        m = form.match(str(with_[k])) if isinstance(with_[k], str) else None
        if not m:
            fails.append("checkout_with_form_invalid:%s@%s" % (k, where))
            continue
        name = m.group("secret")
        if name not in secrets_by_name:
            fails.append("secret_not_in_registry:%s@%s" % (name, where))
            continue
        bound[k] = (name, bool(m.group("fallback")) if "fallback" in m.groupdict() else False)
    token_key = al.get("checkout_token_key")
    alt_key = al.get("checkout_alternative_key")
    if token_key in bound:
        name, has_fallback = bound[token_key]
        alt = secrets_by_name[name].get("alternative")
        if alt:
            if not has_fallback:
                fails.append("checkout_token_no_fallback:%s@%s" % (name, where))
            if alt_key not in bound or bound[alt_key][0] != alt:
                fails.append("checkout_alternative_not_bound:%s@%s" % (alt, where))


def evaluate(doc, contract, secrets_allowed, require_hooks_path=False, secrets_by_name=None):
    tw = contract["thin_wrapper"]
    al = tw["allow_list"]
    if secrets_by_name is None:
        secrets_by_name = dict((n, {}) for n in secrets_allowed)
    fails = []
    pins_unfilled = []
    pin_re = re.compile(tw["pin_pattern"])
    if not isinstance(doc, dict):
        return ["not_a_mapping"], pins_unfilled
    _keys_subset(doc, al["top_level_keys"], "unknown_top_key", "top", fails)
    on = doc.get("on")
    if not isinstance(on, dict) or not on:
        fails.append("unknown_on_key:on-missing@top")
    else:
        _keys_subset(on, al["on_keys"], "unknown_on_key", "on", fails)
    conc = doc.get("concurrency")
    if not isinstance(conc, dict) or conc.get("group") != tw["concurrency_group"]:
        fails.append("concurrency_group_mismatch:%r" % (conc.get("group") if isinstance(conc, dict) else conc,))
    elif conc.get("cancel-in-progress") not in (None, False):
        fails.append("concurrency_group_mismatch:cancel-in-progress")
    _check_env(doc.get("env"), "top", secrets_allowed, fails)
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        fails.append("no_jobs")
        return fails, pins_unfilled
    hooks_seen = False
    for jname, job in jobs.items():
        if not isinstance(job, dict):
            fails.append("unknown_job_key:not-a-mapping@%s" % jname)
            continue
        _keys_subset(job, al["job_keys"], "unknown_job_key", jname, fails)
        _check_env(job.get("env"), jname, secrets_allowed, fails)
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            fails.append("no_jobs:steps-empty@%s" % jname)
            continue
        for idx, step in enumerate(steps):
            where = "%s.steps[%d]" % (jname, idx)
            if not isinstance(step, dict):
                fails.append("unknown_step_key:not-a-mapping@%s" % where)
                continue
            if "if" in step:
                fails.append("if_in_step:%s" % where)
            _keys_subset(step, al["step_keys"], "unknown_step_key", where, fails)
            has_uses = "uses" in step
            has_run = "run" in step
            if has_uses == has_run:
                fails.append("run_not_single_call:uses-xor-run@%s" % where)
                continue
            if has_uses:
                uses = str(step["uses"])
                if not any(uses.startswith(p) for p in al["uses_prefixes"]):
                    fails.append("uses_not_allowed:%s@%s" % (uses, where))
                pin = uses.split("@", 1)[1] if "@" in uses else ""
                if not pin_re.match(pin):
                    pins_unfilled.append("%s uses=%s" % (where, uses))
                with_ = step.get("with")
                if isinstance(with_, dict) and "ref" in with_ and not pin_re.match(str(with_["ref"])):
                    pins_unfilled.append("%s with.ref=%s" % (where, with_["ref"]))
                _check_checkout_with(with_, where, al, secrets_by_name, fails)
            else:
                if "with" in step:
                    fails.append("unknown_step_key:with-without-uses@%s" % where)
                _check_run(step["run"], where, al["run_forms"], fails)
                if isinstance(step["run"], str) and re.match(tw["hooks_path_pattern"], step["run"].rstrip("\n")):
                    hooks_seen = True
    if require_hooks_path and not hooks_seen:
        fails.append("hooks_path_step_missing")
    return fails, pins_unfilled


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wrapper_predicate.py")
    ap.add_argument("workflow")
    ap.add_argument("--contract", default=None)
    ap.add_argument("--steps", default=os.path.join(_HERE, "install-steps.yaml"))
    ap.add_argument("--require-hooks-path", action="store_true")
    args = ap.parse_args(argv)
    try:
        contract = yamlmini.load_file(find_contract(args.contract))
        secrets_by_name = dict((s["name"], s) for s in (yamlmini.load_file(args.steps).get("secrets") or []))
        try:
            doc = yamlmini.load_file(args.workflow)
        except yamlmini.YamlError as e:
            sys.stdout.write("structure: FAIL yaml_not_strict:%s\npins: n/a\n" % e)
            return 2
        fails, pins = evaluate(doc, contract, set(secrets_by_name), args.require_hooks_path, secrets_by_name)
    except Exception as e:  # noqa: BLE001
        sys.stdout.write("TOOL_FAILURE: %s: %s\n" % (type(e).__name__, e))
        return 10
    if fails:
        sys.stdout.write("structure: FAIL %s\n" % "; ".join(fails))
    else:
        sys.stdout.write("structure: PASS\n")
    if pins:
        sys.stdout.write("pins: unfilled %d — %s\n" % (len(pins), "; ".join(pins)))
    else:
        sys.stdout.write("pins: filled\n")
    if fails:
        return 2
    return 1 if pins else 0


if __name__ == "__main__":
    sys.exit(main())
