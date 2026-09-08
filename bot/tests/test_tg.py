"""Оракул tg.py — фальшивый opener, ни одного общего helper'а с транспортом; проверяется форма
вызовов (хост, метод, JSON-тело), маскирование токена и отсутствие политики в модуле (грепом
по исходнику)."""
import json
import os
import re
import sys
import unittest

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BOT)
import tg  # noqa: E402

TOKEN = "1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class _Fake(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, data, timeout_s):
        self.calls.append((url, data, timeout_s))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TransportTests(unittest.TestCase):
    def test_get_updates_url_and_body(self):
        fake = _Fake([b'{"ok":true,"result":[{"update_id":7}]}'])
        t = tg.Transport(TOKEN, 17, opener=fake)
        res = t.get_updates(offset=8, limit=100, timeout_s=0, allowed_updates=["message", "callback_query"])
        self.assertEqual(res, [{"update_id": 7}])
        url, data, timeout = fake.calls[0]
        self.assertEqual(url, "https://api.telegram.org/bot%s/getUpdates" % TOKEN)
        self.assertEqual(json.loads(data.decode("utf-8")), {"offset": 8, "limit": 100, "timeout": 0, "allowed_updates": ["message", "callback_query"]})
        self.assertEqual(timeout, 17)

    def test_send_message_addressee_is_parameter(self):
        fake = _Fake([b'{"ok":true,"result":{"message_id":1}}', b'{"ok":true,"result":{"message_id":2}}'])
        t = tg.Transport(TOKEN, 5, opener=fake)
        t.send_message(111, "a")
        t.send_message(-222, "b", reply_to_message_id=9)
        bodies = [json.loads(c[1].decode("utf-8")) for c in fake.calls]
        self.assertEqual(bodies[0], {"chat_id": 111, "text": "a"})
        self.assertEqual(bodies[1], {"chat_id": -222, "text": "b", "reply_to_message_id": 9})
        self.assertTrue(all(c[0].endswith("/sendMessage") for c in fake.calls))

    def test_answer_callback_query(self):
        fake = _Fake([b'{"ok":true,"result":true}'])
        t = tg.Transport(TOKEN, 5, opener=fake)
        self.assertTrue(t.answer_callback_query("cb-1", text="ok"))
        self.assertTrue(fake.calls[0][0].endswith("/answerCallbackQuery"))
        self.assertEqual(json.loads(fake.calls[0][1].decode("utf-8")), {"callback_query_id": "cb-1", "text": "ok"})

    def test_api_error_raises_without_token(self):
        fake = _Fake([('{"ok":false,"error_code":400,"description":"Bad Request: chat not found %s"}' % TOKEN).encode("utf-8")])
        t = tg.Transport(TOKEN, 5, opener=fake)
        with self.assertRaises(tg.TransportError) as cm:
            t.send_message(1, "x")
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertEqual(cm.exception.error_code, 400)
        self.assertNotIn(TOKEN, t.last_url)

    def test_non_json_and_network_errors(self):
        t = tg.Transport(TOKEN, 5, opener=_Fake([b"<html>"]))
        with self.assertRaises(tg.TransportError):
            t.get_updates()
        t = tg.Transport(TOKEN, 5, opener=_Fake([tg.TransportError("network error: boom " + TOKEN)]))
        with self.assertRaises(tg.TransportError) as cm:
            t.get_updates()
        self.assertNotIn(TOKEN, str(cm.exception))

    def test_unicode_text_bytes(self):
        fake = _Fake([b'{"ok":true,"result":{}}'])
        tg.Transport(TOKEN, 5, opener=fake).send_message(1, "записано · 2ч")
        self.assertIn("записано · 2ч".encode("utf-8"), fake.calls[0][1])

    def test_empty_token_refused(self):
        with self.assertRaises(tg.TransportError):
            tg.Transport("", 5, opener=_Fake([]))


class ThinnessTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_BOT, "tg.py"), "rb") as fh:
            self.src = fh.read().decode("utf-8")
        self.code = "\n".join(l for l in self.src.split("\n") if not l.strip().startswith("#") and not l.strip().startswith('"""'))

    def test_single_host(self):
        hosts = set(re.findall(r"[a-z0-9-]+\.telegram\.org", self.src))
        self.assertEqual(hosts, {"api.telegram.org"})
        self.assertEqual(tg.API_HOST, "api.telegram.org")

    def test_no_policy_literals(self):
        # ни порогов, ни пределов ретраев, ни таймаутов по умолчанию: числовых констант в КОДЕ нет
        # (докстринги и строки — не код; проверяется по AST, независимо от текста модуля)
        import ast
        tree = ast.parse(self.src)
        numbers = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)]
        self.assertEqual(numbers, [], "числовые константы в tg.py: %r" % numbers)
        defaults = [d for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) for d in f.args.defaults
                    if isinstance(d, ast.Constant) and d.value is not None]
        self.assertEqual(defaults, [], "дефолты-политики в сигнатурах tg.py: %r" % [d.value for d in defaults])
        body = self.src.split('"""', 2)[2]
        for word in ("retry", "retries", "threshold", "sleep(", "backoff"):
            self.assertNotIn(word, body)


if __name__ == "__main__":
    unittest.main()
