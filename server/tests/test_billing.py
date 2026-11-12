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

from app.billing import _period_end  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
