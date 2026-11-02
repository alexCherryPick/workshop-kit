# -*- coding: utf-8 -*-
"""T24 R5 (R5O-01 = R5C-01): рецепт вложения из профиля исполним на ВСЕХ ветвях маршрута attachments.yaml#routing.
Команда — ровно по профилю (`attach write --record-dir … --record-id … --ext … --data …`), вне git — с `--source` по
правилу профиля (https-адрес исходного сообщения или urn:uuid квитанции своей копии вне git). Сценарии: файл больше
8 000 000 без хранилища; то же с хранилищем; порог заказчика 0; малый файл в git. Обратный контроль: без `--source`
вне git команда отказывает именованно (то, чего профиль раньше не говорил)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

_TESTS = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.dirname(_TESTS)
_ROOT = os.path.dirname(_BOT)
sys.path.insert(0, _TESTS)
sys.path.insert(0, _BOT)
from test_attach import CANARY, ENV, RID, make_fake  # noqa: E402

LIMIT = 8000000          # attachments.yaml soft_limit.bytes — читается ниже из нормы, литерал только для размера файла
URN = "urn:uuid:%s" % uuid.UUID("0199a8c0-1a00-7a00-8a00-0000000009aa")
HTTPS = "https://t.me/c/1000000001/901"


def norm_limit():
    import yaml
    with open(os.path.join(_ROOT, "spec", "03-spec-type-schemas", "attachments.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)["soft_limit"]["bytes"]


class ProfileRecipeRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t24-route-")
        self.rd = os.path.join(self.tmp, "time")
        os.makedirs(self.rd)
        self.assertEqual(norm_limit(), LIMIT, "порог нормы изменился — сценарии меряют не ту границу")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def data(self, n, name):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as fh:
            fh.write(os.urandom(n))
        return p

    def config(self, threshold, fk=None):
        m = {"git_threshold_bytes": threshold}
        if fk is not None:
            m["storage"] = {"endpoint": fk.endpoint, "bucket": fk.state.bucket, "allow_insecure_http": True, "timeout_s": 5,
                            "canary_key": CANARY, "list_permission": False,
                            "credentials": {"access_key_id": "WORKSHOP_S3_ACCESS_KEY_ID_DEV",
                                            "secret_access_key": "WORKSHOP_S3_SECRET_ACCESS_KEY_DEV"}}
        p = os.path.join(self.tmp, "cfg.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(m, fh)
        return p

    def write(self, cfg, data, source=None):
        cmd = [sys.executable, "-m", "bot.attach", "--json", "--config", cfg, "write", "--record-dir", self.rd,
               "--record-id", RID, "--ext", "bin", "--data", data]
        if source:
            cmd += ["--source", source]
        r = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, env=dict(os.environ, **ENV))
        return r.returncode, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}), r.stdout + r.stderr

    def test_over_limit_without_storage(self):
        d = self.data(LIMIT + 1, "big.bin")
        rc, out, raw = self.write(self.config(LIMIT), d)
        self.assertEqual(rc, 2, raw)                        # без --source — именованный отказ (почему профиль его называет)
        self.assertIn("source", raw)
        rc, out, raw = self.write(self.config(LIMIT), d, URN)
        self.assertEqual(rc, 0, raw)
        self.assertEqual((out.get("state"), out.get("reason")), ("unsaved", "no-storage"), raw)
        self.assertTrue(out.get("path") and out.get("staged"), raw)

    def test_over_limit_with_storage(self):
        with make_fake("yandex") as fk:
            d = self.data(LIMIT + 1, "big.bin")
            rc, out, raw = self.write(self.config(LIMIT, fk), d, HTTPS)
            self.assertEqual(rc, 0, raw)
            self.assertEqual(out.get("state"), "stored", raw)
            self.assertTrue(out.get("path") and out.get("staged"), raw)

    def test_threshold_zero(self):
        d = self.data(10, "small.bin")
        rc, out, raw = self.write(self.config(0), d)
        self.assertEqual(rc, 2, raw)                        # порог 0: даже малый файл вне git — без --source отказ
        rc, out, raw = self.write(self.config(0), d, URN)
        self.assertEqual(rc, 0, raw)
        self.assertEqual((out.get("state"), out.get("reason")), ("unsaved", "no-storage"), raw)

    def test_small_file_in_git(self):
        d = self.data(1000, "small.bin")
        rc, out, raw = self.write(self.config(LIMIT), d)   # в git --source не нужен
        self.assertEqual(rc, 0, raw)
        self.assertTrue(out.get("path") and out.get("staged"), raw)
        self.assertNotIn(out.get("state"), ("unsaved", "stored", "pending"), raw)
        with open(os.path.join(self.rd, out["path"]) if not os.path.isabs(out["path"]) else out["path"], "rb") as fh:
            self.assertNotEqual(fh.read(27), b"workshop-attachment-pointer", "малый файл обязан лечь байтами, не указателем")


if __name__ == "__main__":
    unittest.main()
