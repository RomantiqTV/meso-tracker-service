"""The welcome email's install options: one direct installer button without a Store link, both ways to install with one."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(DATABASE_URL="x", STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_testsecret",
                  STRIPE_PRICE_ID="price_x", RESEND_API_KEY="re_x", JWT_SIGNING_SECRET="unit-test-jwt-secret",
                  LICENSE_KEY_PEPPER="unit-test-pepper").items():
    os.environ.setdefault(k, v)

from app import email  # noqa: E402
from app.config import Settings  # noqa: E402

DL = "https://github.com/RomantiqTV/meso-tracker-service/releases/download/v1.3.5/MesoTracker-Setup-1.3.5.exe"
STORE = "https://apps.microsoft.com/detail/9PJVJFVFP7XL"


def sent_html(store_url):
    s = SimpleNamespace(site_url="https://mesotracker.pro", store_url=store_url, email_from="x", resend_api_key="k")
    with mock.patch.object(email, "send") as send:
        email.send_welcome(s, "a@b.co", "MESO-AAAA-BBBB-CCCC-DDDD", DL)
    args = send.call_args[0]
    return args[2], args[3]                                       # subject, html


class TestWelcomeEmail(unittest.TestCase):
    def test_without_a_store_link_it_is_the_single_installer_button_as_before(self):
        subject, html = sent_html("")
        self.assertEqual(subject, "Your Meso Tracker licence key")
        self.assertIn(DL, html)
        self.assertIn("Download Meso Tracker", html)
        self.assertNotIn("Microsoft Store", html)
        self.assertNotIn("Two ways to install", html)

    def test_with_a_store_link_both_ways_are_offered_with_their_windows_versions(self):
        _, html = sent_html(STORE)
        self.assertIn("Two ways to install", html)
        self.assertIn('href="%s"' % STORE, html)
        self.assertIn('href="%s"' % DL, html)
        store_at, direct_at = html.index("1. Microsoft Store"), html.index("2. Direct installer")
        self.assertLess(store_at, direct_at)                                          # the Store is option 1
        self.assertIn("(Windows 10 and 11)", html[store_at:direct_at])
        self.assertIn("(Windows 10)", html[direct_at:html.index("Download the installer")])

    def test_the_key_and_the_manage_link_are_still_in_the_email(self):
        for store in ("", STORE):
            _, html = sent_html(store)
            self.assertIn("MESO-AAAA-BBBB-CCCC-DDDD", html)
            self.assertIn("https://mesotracker.pro/billing?email=a@b.co", html)

    def test_a_settings_object_without_the_attribute_still_works(self):
        s = SimpleNamespace(site_url="https://x", email_from="x", resend_api_key="k")      # (an older Settings / a test double)
        self.assertNotIn("Microsoft Store", email.install_options_html(s, DL))

    def test_store_url_comes_from_the_environment_and_defaults_to_blank(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STORE_URL", None)
            self.assertEqual(Settings().store_url, "")
        with mock.patch.dict(os.environ, {"STORE_URL": STORE}):
            self.assertEqual(Settings().store_url, STORE)


if __name__ == "__main__":
    unittest.main()
