"""Unit tests for usage parsing and cap messages."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from open_webui.models.usage import (
    ORG_LIMIT_MESSAGE,
    USER_LIMIT_MESSAGE,
    UsageLimitExceeded,
    current_period,
    parse_provider_usage,
)
from open_webui.utils.usage import check_usage_caps


class ParseProviderUsageTest(unittest.TestCase):
    def test_openai_tokens_and_cost(self):
        parsed = parse_provider_usage(
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cost": 0.0123,
                "prompt_tokens_details": {"cached_tokens": 40},
            }
        )
        self.assertEqual(parsed["prompt_tokens"], 100)
        self.assertEqual(parsed["completion_tokens"], 20)
        self.assertEqual(parsed["total_tokens"], 120)
        self.assertEqual(parsed["cached_tokens"], 40)
        self.assertEqual(parsed["uncached_tokens"], 60)
        self.assertEqual(parsed["cost_usd"], 0.0123)
        self.assertTrue(parsed["has_cost"])

    def test_upstream_inference_cost_without_top_level_cost(self):
        parsed = parse_provider_usage(
            {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "cost_details": {"upstream_inference_cost": 0.004},
            }
        )
        self.assertEqual(parsed["cost_usd"], 0.004)
        self.assertTrue(parsed["has_cost"])
        self.assertEqual(parsed["total_tokens"], 12)

    def test_missing_cost_is_zero_not_estimated(self):
        parsed = parse_provider_usage({"prompt_tokens": 50, "completion_tokens": 10})
        self.assertEqual(parsed["cost_usd"], 0.0)
        self.assertFalse(parsed["has_cost"])
        self.assertEqual(parsed["uncached_tokens"], 50)

    def test_empty_usage(self):
        parsed = parse_provider_usage({})
        self.assertEqual(parsed["prompt_tokens"], 0)
        self.assertFalse(parsed["has_cost"])
        self.assertEqual(parsed["cost_usd"], 0.0)


class CurrentPeriodTest(unittest.TestCase):
    def test_utc_yyyy_mm(self):
        from datetime import datetime, timezone

        self.assertEqual(
            current_period(datetime(2026, 9, 21, 23, tzinfo=timezone.utc)),
            "2026-09",
        )


class CheckUsageCapsTest(unittest.TestCase):
    def test_unlimited_org_skips(self):
        org = MagicMock(monthly_limit_usd=None)
        with patch(
            "open_webui.utils.usage.Organizations.get_organization_by_id",
            return_value=org,
        ), patch(
            "open_webui.utils.usage.Organizations.get_member", return_value=None
        ):
            check_usage_caps("org", "user")

    def test_org_cap_blocks_first(self):
        org = MagicMock(monthly_limit_usd=10.0)
        member = MagicMock(monthly_limit_usd=1.0)
        org_row = MagicMock(cost_usd=10.0)
        user_row = MagicMock(cost_usd=0.0)
        with patch(
            "open_webui.utils.usage.Organizations.get_organization_by_id",
            return_value=org,
        ), patch(
            "open_webui.utils.usage.Organizations.get_member", return_value=member
        ), patch(
            "open_webui.utils.usage.Usage.get_month",
            side_effect=[org_row, user_row],
        ):
            with self.assertRaises(UsageLimitExceeded) as ctx:
                check_usage_caps("org", "user")
            self.assertEqual(ctx.exception.detail, ORG_LIMIT_MESSAGE)

    def test_user_cap_blocks_after_org(self):
        org = MagicMock(monthly_limit_usd=300.0)
        member = MagicMock(monthly_limit_usd=5.0)
        org_row = MagicMock(cost_usd=1.0)
        user_row = MagicMock(cost_usd=5.0)
        with patch(
            "open_webui.utils.usage.Organizations.get_organization_by_id",
            return_value=org,
        ), patch(
            "open_webui.utils.usage.Organizations.get_member", return_value=member
        ), patch(
            "open_webui.utils.usage.Usage.get_month",
            side_effect=[org_row, user_row],
        ):
            with self.assertRaises(UsageLimitExceeded) as ctx:
                check_usage_caps("org", "user")
            self.assertEqual(ctx.exception.detail, USER_LIMIT_MESSAGE)

    def test_zero_org_cap_blocks_immediately(self):
        org = MagicMock(monthly_limit_usd=0.0)
        org_row = MagicMock(cost_usd=0.0)
        with patch(
            "open_webui.utils.usage.Organizations.get_organization_by_id",
            return_value=org,
        ), patch(
            "open_webui.utils.usage.Usage.get_month", return_value=org_row
        ):
            with self.assertRaises(UsageLimitExceeded) as ctx:
                check_usage_caps("org", "user")
            self.assertEqual(ctx.exception.detail, ORG_LIMIT_MESSAGE)


if __name__ == "__main__":
    unittest.main()
