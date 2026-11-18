"""Sign-in tokens issued before a user's cutoff are rejected."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt

from open_webui.utils.auth import (
    ALGORITHM,
    SESSION_SECRET,
    create_token,
    decode_token,
    get_user_from_token,
)


def _token(iat=None):
    payload = {"id": "alice"}
    if iat is not None:
        payload["iat"] = iat
    return jwt.encode(payload, SESSION_SECRET, algorithm=ALGORITHM)


class TokenCutoffTest(unittest.TestCase):
    def _lookup(self, cutoff):
        user = SimpleNamespace(id="alice", tokens_valid_after=cutoff)
        return patch("open_webui.utils.auth.Users.get_user_by_id", return_value=user)

    def test_create_token_records_issue_time(self):
        before = int(time.time())
        data = decode_token(create_token({"id": "alice"}))
        self.assertGreaterEqual(data["iat"], before)

    def test_no_cutoff_accepts_any_token(self):
        with self._lookup(None):
            self.assertIsNotNone(get_user_from_token(_token()))
            self.assertIsNotNone(get_user_from_token(_token(iat=1)))

    def test_token_before_cutoff_is_rejected(self):
        now = int(time.time())
        with self._lookup(now):
            self.assertIsNone(get_user_from_token(_token(iat=now - 60)))
            self.assertIsNone(get_user_from_token(_token()))  # no iat: pre-cutoff

    def test_token_at_or_after_cutoff_is_accepted(self):
        now = int(time.time())
        with self._lookup(now):
            self.assertIsNotNone(get_user_from_token(_token(iat=now)))
            self.assertIsNotNone(get_user_from_token(create_token({"id": "alice"})))

    def test_bad_token_is_rejected(self):
        with self._lookup(None):
            self.assertIsNone(get_user_from_token("not-a-token"))


if __name__ == "__main__":
    unittest.main()
