# -*- coding: utf-8 -*-
"""Оракул коммента: id пересчитан hashlib/uuid в тесте по формуле контракта; заголовочная строка
разбирается СОБСТВЕННЫМ регэкспом грамматики 04.3.1; тело сравнивается байтами."""
import hashlib, os, re, sys, unittest, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comment  # noqa: E402

GRAMMAR = re.compile(r"^### (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) · ([A-Za-z0-9._-]{1,64}) <!--c:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}) about:t:([0-9a-f]{8})-->$")


def ref_id(identity, date, k):
    h = hashlib.sha256(b"\x00".join([b"workshop-d09-comment-v1", identity.encode(), str(k).encode()])).digest()
    v = (date * 1000 << 80) | (7 << 76) | ((int.from_bytes(h[:2], "big") & 0xFFF) << 64) | (2 << 62) | (int.from_bytes(h[2:10], "big") & ((1 << 62) - 1))
    return str(uuid.UUID(int=v))


class CommentTests(unittest.TestCase):
    def test_id_formula_version_and_domains(self):
        i = "tg:100000001:4123"
        cid = comment.comment_id(i, 1788790990)
        self.assertEqual(cid, ref_id(i, 1788790990, 0))
        self.assertEqual(uuid.UUID(cid).version, 7)
        self.assertEqual(comment.comment_id(i, 1788790990), cid)                 # повтор — тот же id
        self.assertNotEqual(comment.comment_id(i, 1788790990, 1), cid)           # k входит в id
        self.assertNotEqual(comment.comment_id("tg:100000001:41230", 1788790990), cid)
        # домены соли различны: якорь того же сообщения не подстрока id и не равен ему
        a = hashlib.sha256(b"\x00".join([b"workshop-d09-anchor-v1", i.encode(), b"0", b"0"])).hexdigest()[:8]
        self.assertNotIn(a, cid)

    def test_header_grammar_and_middle_dot(self):
        cid = comment.comment_id("tg:1:2", 1757239200)
        head = comment.header_line(1757239200, "dev-one", cid, "3f2a9c1e")
        m = GRAMMAR.match(head)
        self.assertIsNotNone(m, head)
        self.assertEqual(m.group(1), "2025-09-07T10:00:00Z")
        self.assertEqual(ord(head[head.index("·")]), 0xB7); self.assertEqual(head[24:27], " · ")
        self.assertEqual(head.count("about:t:"), 1)
        for bad in (head.replace(" · ", " - "), head.replace("-->", " replies-to:x-->"), head.replace("dev-one", "dev one")):
            self.assertIsNone(GRAMMAR.match(bad))
        with self.assertRaises(ValueError):
            comment.header_line(1, "dev one", cid, "3f2a9c1e")

    def test_body_bytes_verbatim_and_none_when_empty(self):
        body = "строка 1\r\nстрока 2 🚀\n\nконец без LF".encode("utf-8")
        res = comment.build("tg:1:2", 1757239200, body, "dev-one", "3f2a9c1e")
        cid, head, block = res
        self.assertTrue(block.startswith(head.encode() + b"\n"))
        hb = len(head.encode("utf-8"))  # заголовок содержит многобайтовый MIDDLE DOT — считаем байты
        self.assertEqual(block[hb + 1:-1], body)         # тело побайтово, один финальный LF
        self.assertTrue(block.endswith(b"\n") and not block.endswith(b"\n\n"))
        res2 = comment.build("tg:1:2", 1757239200, body + b"\n", "dev-one", "3f2a9c1e")
        self.assertEqual(res2[2][hb + 1:], body + b"\n")  # уже кончается LF — второй не добавляется
        self.assertIsNone(comment.build("tg:1:2", 1757239200, b"", "dev-one", "3f2a9c1e"))
        self.assertIsNone(comment.build("tg:1:2", 1757239200, None, "dev-one", "3f2a9c1e"))
        with self.assertRaises(TypeError):
            comment.build("tg:1:2", 1757239200, "str", "dev-one", "3f2a9c1e")

    def test_comments_of_header(self):
        self.assertEqual(comment.comments_of_header("019550fa-1ea0-773c-b820-1e2b73ab4901"), "<!-- comments-of: 019550fa-1ea0-773c-b820-1e2b73ab4901 -->")


if __name__ == "__main__":
    unittest.main()
