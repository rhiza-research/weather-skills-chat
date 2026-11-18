"""Sign-in tokens issued before a user's cutoff are rejected."""

from __future__ import annotations

import time
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt

from open_webui.utils.auth import (
    ALGORITHM,
    MAX_TOKEN_LIFETIME,
    SESSION_SECRET,
    create_token,
    decode_token,
    get_user_from_token,
    token_lifetime,
)


def _token(iat=None, exp=None):
    payload = {"id": "alice", "exp": exp or int(time.time()) + 600}
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

    def test_token_without_expiry_is_rejected(self):
        unlimited = jwt.encode({"id": "alice"}, SESSION_SECRET, algorithm=ALGORITHM)
        with self._lookup(None):
            self.assertIsNone(get_user_from_token(unlimited))

    def test_lifetime_is_capped_at_90_days(self):
        self.assertEqual(token_lifetime("30d"), timedelta(days=30))
        self.assertEqual(token_lifetime("-1"), MAX_TOKEN_LIFETIME)
        self.assertEqual(token_lifetime("0"), MAX_TOKEN_LIFETIME)
        self.assertEqual(token_lifetime("52w"), MAX_TOKEN_LIFETIME)

    def test_create_token_never_exceeds_cap(self):
        cap = int(time.time() + MAX_TOKEN_LIFETIME.total_seconds())
        for token in (
            create_token({"id": "alice"}),
            create_token({"id": "alice"}, expires_delta=timedelta(days=365)),
            create_token({"id": "alice", "exp": int(time.time()) + 10**8}),
        ):
            self.assertLessEqual(decode_token(token)["exp"], cap + 1)

    def test_bad_token_is_rejected(self):
        with self._lookup(None):
            self.assertIsNone(get_user_from_token("not-a-token"))


if __name__ == "__main__":
    unittest.main()
