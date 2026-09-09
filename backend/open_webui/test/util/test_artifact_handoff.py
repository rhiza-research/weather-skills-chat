"""One-time artifact links.

A nonce is claimed with one GETDEL call, so it can be redeemed once. An expired, unknown, spent, or
malformed nonce all return None, so a caller cannot tell those cases apart.
"""

import unittest
from unittest.mock import MagicMock, patch

from open_webui.utils.artifact_handoff import (
    HANDOFF_TTL_SECONDS,
    KEY_PREFIX,
    NONCE_BYTES,
    handoff_available,
    mint,
    redeem,
)

SESSION = "b2c3d4e5-0000-4000-8000-000000000000"
RELPATH = "plots/rain.png"


class AvailabilityTest(unittest.TestCase):
    def test_no_configured_store_means_unavailable(self):
        with patch("open_webui.utils.artifact_handoff.REDIS_URL", ""):
            self.assertFalse(handoff_available())

    def test_whitespace_is_not_a_store(self):
        with patch("open_webui.utils.artifact_handoff.REDIS_URL", "   "):
            self.assertFalse(handoff_available())

    def test_a_configured_store_means_available(self):
        with patch(
            "open_webui.utils.artifact_handoff.REDIS_URL", "redis://localhost:6379/0"
        ):
            self.assertTrue(handoff_available())

    def test_minting_without_a_store_raises_rather_than_returning_a_dead_link(self):
        with patch("open_webui.utils.artifact_handoff.REDIS_URL", ""):
            with self.assertRaises(RuntimeError):
                mint(SESSION, RELPATH)


class MintTest(unittest.TestCase):
    def mint(self):
        client = MagicMock()
        with patch(
            "open_webui.utils.artifact_handoff.REDIS_URL", "redis://localhost:6379/0"
        ), patch("open_webui.utils.artifact_handoff._client", return_value=client):
            nonce = mint(SESSION, RELPATH)
        return nonce, client

    def test_the_nonce_is_long_enough_to_be_the_credential(self):
        nonce, _ = self.mint()
        # token_urlsafe expands, so the encoded form is longer than the byte count asked for.
        self.assertGreaterEqual(len(nonce), NONCE_BYTES)

    def test_two_mints_do_not_collide(self):
        first, _ = self.mint()
        second, _ = self.mint()
        self.assertNotEqual(first, second)

    def test_the_claim_is_namespaced_and_expires(self):
        nonce, client = self.mint()
        key, ttl, _value = client.setex.call_args.args
        self.assertTrue(key.startswith(KEY_PREFIX))
        self.assertIn(nonce, key)
        self.assertEqual(ttl, HANDOFF_TTL_SECONDS)

    def test_the_session_and_path_are_stored_together(self):
        # Redeeming returns the artifact stored with the nonce, not one named by the caller.
        _nonce, client = self.mint()
        stored = client.setex.call_args.args[2]
        self.assertIn(SESSION, stored)
        self.assertIn(RELPATH, stored)


class RedeemTest(unittest.TestCase):
    def redeem(self, stored, nonce="tok"):
        client = MagicMock()
        client.getdel.return_value = stored
        with patch(
            "open_webui.utils.artifact_handoff.REDIS_URL", "redis://localhost:6379/0"
        ), patch("open_webui.utils.artifact_handoff._client", return_value=client):
            return redeem(nonce), client

    def test_a_live_claim_returns_its_session_and_path(self):
        claimed, _ = self.redeem(f"{SESSION}\n{RELPATH}")
        self.assertEqual(claimed, (SESSION, RELPATH))

    def test_the_claim_is_read_and_removed_in_one_call(self):
        # GETDEL reads and removes in one call, so only one of two concurrent redeems gets the claim.
        _claimed, client = self.redeem(f"{SESSION}\n{RELPATH}")
        client.getdel.assert_called_once()

    def test_an_unknown_nonce_answers_nothing(self):
        claimed, _ = self.redeem(None)
        self.assertIsNone(claimed)

    def test_a_spent_nonce_answers_the_same_nothing(self):
        claimed, _ = self.redeem("")
        self.assertIsNone(claimed)

    def test_a_malformed_claim_answers_the_same_nothing(self):
        claimed, _ = self.redeem("no separator here")
        self.assertIsNone(claimed)

    def test_an_empty_nonce_answers_nothing_without_reaching_the_store(self):
        client = MagicMock()
        with patch(
            "open_webui.utils.artifact_handoff.REDIS_URL", "redis://localhost:6379/0"
        ), patch("open_webui.utils.artifact_handoff._client", return_value=client):
            self.assertIsNone(redeem(""))
        client.getdel.assert_not_called()

    def test_a_store_that_errors_answers_the_same_nothing(self):
        client = MagicMock()
        client.getdel.side_effect = RuntimeError("store down")
        with patch(
            "open_webui.utils.artifact_handoff.REDIS_URL", "redis://localhost:6379/0"
        ), patch("open_webui.utils.artifact_handoff._client", return_value=client):
            self.assertIsNone(redeem("tok"))

    def test_redeeming_without_a_store_answers_nothing(self):
        with patch("open_webui.utils.artifact_handoff.REDIS_URL", ""):
            self.assertIsNone(redeem("tok"))


if __name__ == "__main__":
    unittest.main()
