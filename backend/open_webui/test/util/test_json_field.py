"""JSONField codec must support SQLite TEXT and Postgres JSON/JSONB."""

from __future__ import annotations

import json
import unittest

from open_webui.internal.json_codec import decode_json_field, encode_json_field


class JSONFieldBothBackendsTest(unittest.TestCase):
    def test_none_roundtrip(self):
        self.assertIsNone(encode_json_field(None))
        self.assertIsNone(decode_json_field(None))

    def test_sqlite_text_read(self):
        raw = '{"skills": []}'
        self.assertEqual(decode_json_field(raw), {"skills": []})

    def test_sqlite_text_write(self):
        self.assertEqual(encode_json_field({"skills": []}), '{"skills": []}')

    def test_postgres_json_dict_read(self):
        self.assertEqual(decode_json_field({"skills": []}), {"skills": []})

    def test_postgres_json_list_read(self):
        self.assertEqual(decode_json_field([{"name": "a"}]), [{"name": "a"}])

    def test_postgres_json_scalars_read(self):
        self.assertTrue(decode_json_field(True) is True)
        self.assertEqual(decode_json_field(0), 0)
        self.assertEqual(decode_json_field(1.5), 1.5)

    def test_bytes_read(self):
        self.assertEqual(decode_json_field(b'{"a": 1}'), {"a": 1})

    def test_bind_then_sqlite_decode_matches_postgres_decode(self):
        payload = {"skills": [], "access": {"read": {"group_ids": []}}}
        sqlite_value = encode_json_field(payload)
        self.assertIsInstance(sqlite_value, str)
        self.assertEqual(decode_json_field(sqlite_value), payload)
        self.assertEqual(decode_json_field(payload), payload)
        self.assertEqual(json.loads(sqlite_value), payload)


if __name__ == "__main__":
    unittest.main()
