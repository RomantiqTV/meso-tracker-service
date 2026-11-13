"""_period_end is pure (no Stripe/network/DB), so it's tested directly rather than through a webhook round-trip."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(DATABASE_URL="x", STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_testsecret",
                  STRIPE_PRICE_ID="price_x", RESEND_API_KEY="re_x", JWT_SIGNING_SECRET="unit-test-jwt-secret",
                  LICENSE_KEY_PEPPER="unit-test-pepper").items():
    os.environ.setdefault(k, v)

from app.billing import _period_end, price_id_for  # noqa: E402
from app.config import Settings  # noqa: E402


class PeriodEndTests(unittest.TestCase):
    TS = 1800000000  # an arbitrary fixed Unix timestamp

    def test_top_level_field_pre_basil_shape(self):
        self.assertEqual(_period_end({"current_period_end": self.TS}),
                          datetime.datetime.fromtimestamp(self.TS, tz=datetime.timezone.utc))

    def test_falls_back_to_the_first_subscription_item_basil_shape(self):
        sub = {"items": {"data": [{"current_period_end": self.TS}]}}
        self.assertEqual(_period_end(sub), datetime.datetime.fromtimestamp(self.TS, tz=datetime.timezone.utc))

    def test_no_period_end_anywhere_is_none(self):
        self.assertIsNone(_period_end({"items": {"data": [{}]}}))
        self.assertIsNone(_period_end({}))

    def test_object_attribute_access_also_falls_back(self):
        class Item:
            current_period_end = self.TS

        class Items:
            data = [Item()]

        class Sub:
            items = Items()

        self.assertEqual(_period_end(Sub()), datetime.datetime.fromtimestamp(self.TS, tz=datetime.timezone.utc))


class PlanPriceTests(unittest.TestCase):
    """price_id_for is pure too (just an attribute lookup) - the actual Stripe call is exercised manually against a
    test-mode account, same as the rest of checkout."""

    def test_monthly_is_always_configured(self):
        self.assertEqual(price_id_for(Settings(), "monthly"), "price_x")

    def test_longer_plan_not_set_up_in_stripe_yet_is_falsy_not_an_error(self):
        self.assertFalse(price_id_for(Settings(), "6mo"))      # env var defaults to "" until the Price is created

    def test_unknown_plan_key_returns_none(self):
        self.assertIsNone(price_id_for(Settings(), "weekly"))

    def test_configured_longer_plan_is_read_back(self):
        os.environ["STRIPE_PRICE_ID_YEARLY"] = "price_year"
        try:
            self.assertEqual(price_id_for(Settings(), "yearly"), "price_year")
        finally:
            del os.environ["STRIPE_PRICE_ID_YEARLY"]


if __name__ == "__main__":
    unittest.main()
