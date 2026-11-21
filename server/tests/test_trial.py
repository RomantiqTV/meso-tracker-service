"""Free trial without a card: sign-up, the abuse limits, the clock that starts at first activation, session caps, expiry and conversion to a paid plan (app.trials + the routes), against the
in-memory fake of the DB layer from test_main_integration."""
import datetime
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_main_integration import FakeStore, fake_connect, fake_repo_for, security, main, trials, TestClient  # noqa: E402
from app import billing  # noqa: E402

UTC = datetime.timezone.utc
HW_A, HW_B = "a" * 64, "b" * 64


def now():
    return datetime.datetime.now(UTC)


class CanonTests(unittest.TestCase):
    def test_canon(self):
        c = trials.canon_email
        self.assertEqual(c("  Bob+spam@Example.com "), "bob@example.com")
        self.assertEqual(c("b.o.b@gmail.com"), "bob@gmail.com")
        self.assertEqual(c("b.o.b+x@googlemail.com"), "bob@gmail.com")
        self.assertEqual(c("a.b@corp.com"), "a.b@corp.com")                       # dots only mean nothing on gmail


class TrialBase(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        fake = fake_repo_for(self.store)
        orig = fake.get_subscription_for_customer
        fake.get_subscription_for_customer = lambda cur, cid: orig(cur, cid) or (
            {"status": "trialing", "current_period_end": self.store.trials[cid]["ends_at"]} if cid in self.store.trials else None)
        self.sent = []
        ps = [mock.patch.object(main, "repo", fake), mock.patch.object(trials, "repo", fake), mock.patch.object(billing, "repo", fake), mock.patch.object(main.db, "connect", fake_connect),
              mock.patch.object(main.email, "send_trial_welcome", lambda s, to, key, url, days: self.sent.append((to, key, days))),
              mock.patch.object(main.settings, "trial_enabled", True), mock.patch.object(main.settings, "trial_days", 5), mock.patch.object(main.settings, "trial_per_ip_per_day", 3)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        main.ratelimit._hits.clear()
        self.c = TestClient(main.app)

    def signup(self, email="new@example.com", ip="1.1.1.1"):
        return self.c.post("/v1/trial", json={"email": email}, headers={"x-forwarded-for": ip})

    def activate(self, email, key, hwid=HW_A):
        return self.c.post("/v1/activate", json={"email": email, "license_key": key, "hwid": hwid, "app_version": "1.3.7"})

    def status(self, email, key, hwid=HW_A):
        return self.c.post("/v1/status", json={"email": email, "license_key": key, "hwid": hwid, "app_version": "1.3.7"})

    def started(self, email="new@example.com"):
        self.assertEqual(self.signup(email).status_code, 200)
        return self.sent[-1][1]


class SignupTests(TrialBase):
    def test_signup_emails_a_key_and_creates_pending_trial(self):
        r = self.signup()
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "days": 5}))
        to, key, days = self.sent[0]
        self.assertEqual((to, days), ("new@example.com", 5))
        self.assertTrue(security.is_well_formed_key(key))
        t = self.store.trials[self.store.customers["new@example.com"]["id"]]
        self.assertIsNone(t["started_at"])                                      # the days have NOT started yet
        self.assertIsNone(self.store.customers["new@example.com"]["stripe_customer_id"])
        self.assertEqual(len(self.store.licenses), 1)

    def test_one_trial_per_mailbox(self):
        self.assertEqual(self.signup("bob@gmail.com").status_code, 200)
        for variant in ("bob@gmail.com", "b.o.b@gmail.com", "bob+two@gmail.com", "BOB@googlemail.com"):
            self.assertEqual(self.signup(variant, ip="2.2.2.2").status_code, 409, variant)
        self.assertEqual(len(self.sent), 1)

    def test_existing_customer_is_not_given_a_trial(self):
        self.store.add_customer("paid@example.com")
        self.assertEqual(self.signup("paid@example.com").status_code, 409)

    def test_disposable_mail_refused(self):
        self.assertEqual(self.signup("x@mailinator.com").status_code, 400)
        self.assertEqual(self.sent, [])

    def test_per_ip_daily_cap(self):
        codes = [self.signup(f"u{i}@example.com", ip="9.9.9.9").status_code for i in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        self.assertEqual(self.signup("other@example.com", ip="8.8.8.8").status_code, 200)

    def test_switched_off_is_503(self):
        with mock.patch.object(main.settings, "trial_enabled", False):
            self.assertEqual(self.signup().status_code, 503)

    def test_email_failure_is_a_retryable_502(self):
        with mock.patch.object(main.email, "send_trial_welcome", side_effect=RuntimeError("resend down")):
            self.assertEqual(self.signup().status_code, 502)

    def test_bad_address_is_422(self):
        self.assertEqual(self.c.post("/v1/trial", json={"email": "nope"}).status_code, 422)


class ActivationTests(TrialBase):
    def test_first_activation_starts_the_clock_and_reports_a_trial(self):
        key = self.started()
        r = self.activate("new@example.com", key)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["subscription_status"], "trialing")
        end = datetime.datetime.fromisoformat(body["current_period_end"])
        self.assertAlmostEqual((end - now()).total_seconds() / 86400, 5, delta=0.01)
        t = self.store.trials[self.store.customers["new@example.com"]["id"]]
        self.assertIsNotNone(t["started_at"])
        # a second activation (same PC) does not restart or extend it
        again = self.activate("new@example.com", key).json()
        self.assertEqual(again["current_period_end"], body["current_period_end"])

    def test_session_and_offline_grace_never_outlive_the_trial(self):
        key = self.started()
        self.activate("new@example.com", key)
        t = self.store.trials[self.store.customers["new@example.com"]["id"]]
        t["ends_at"] = now() + datetime.timedelta(hours=2)
        r = self.status("new@example.com", key).json()
        self.assertLessEqual(r["expires_in_hours"], 2.01)
        self.assertLessEqual(r["offline_grace_hours"], 2.01)
        payload = security.verify_session(main.settings.jwt_secret, r["session_token"])
        self.assertLessEqual(payload["exp"], int(now().timestamp()) + 2 * 3600 + 5)

    def test_early_in_the_trial_the_normal_session_applies(self):
        key = self.started()
        r = self.activate("new@example.com", key).json()
        self.assertEqual(r["expires_in_hours"], main.settings.session_ttl_hours)
        self.assertEqual(r["offline_grace_hours"], main.settings.offline_grace_hours)

    def test_expired_trial_is_refused_with_a_clear_402(self):
        key = self.started()
        self.activate("new@example.com", key)
        self.store.trials[self.store.customers["new@example.com"]["id"]]["ends_at"] = now() - datetime.timedelta(minutes=1)
        for call in (self.activate, self.status):
            r = call("new@example.com", key)
            self.assertEqual(r.status_code, 402)
            self.assertIn("free trial has ended", r.json()["detail"])

    def test_an_unstarted_trial_still_works_days_later(self):
        key = self.started()
        self.store.trials[self.store.customers["new@example.com"]["id"]]["created"] = now() - datetime.timedelta(days=30)
        self.assertEqual(self.activate("new@example.com", key).status_code, 200)

    def test_one_trial_per_pc(self):
        k1 = self.started("one@example.com")
        self.assertEqual(self.activate("one@example.com", k1).status_code, 200)
        k2 = self.started("two@example.com")
        r = self.activate("two@example.com", k2)                                 # same PC, a different mailbox
        self.assertEqual(r.status_code, 403)
        self.assertIn("already used a free trial", r.json()["detail"])
        self.assertIsNone(self.store.licenses[next(l for l in self.store.licenses if self.store.licenses[l]["customer_id"] == self.store.customers["two@example.com"]["id"])]["hwid"])
        self.assertIn("denied_trial_device", [e[1] for e in self.store.log])
        self.assertEqual(self.activate("two@example.com", k2, hwid=HW_B).status_code, 200)   # a different PC is fine

    def test_the_trial_can_move_to_another_pc_without_extending(self):
        key = self.started()
        first = self.activate("new@example.com", key).json()
        self.c.post("/v1/deactivate", json={"email": "new@example.com", "license_key": key})
        moved = self.activate("new@example.com", key, hwid=HW_B).json()
        self.assertEqual(moved["current_period_end"], first["current_period_end"])

    def test_paying_customers_are_untouched(self):
        cust = self.store.add_customer("buyer@example.com")
        self.store.active_customers.add(cust["id"])
        self.store.add_license(cust, "MESO-WXYZ-ABCD-EFGH-JKLM")
        r = self.activate("buyer@example.com", "MESO-WXYZ-ABCD-EFGH-JKLM").json()
        self.assertEqual(r["expires_in_hours"], main.settings.session_ttl_hours)
        self.assertEqual(r["offline_grace_hours"], main.settings.offline_grace_hours)


class BillingTests(TrialBase):
    def test_billing_portal_for_a_trial_customer_points_at_the_plans(self):
        key = self.started()
        r = self.c.post("/v1/billing-portal", json={"email": "new@example.com", "license_key": key})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["url"].endswith("/#pricing"))

    def test_paying_after_a_trial_keeps_the_same_licence(self):
        key = self.started()
        self.activate("new@example.com", key)
        cid = self.store.customers["new@example.com"]["id"]
        n_lic = len(self.store.licenses)
        converted = []
        event = {"type": "checkout.session.completed", "data": {"object": {"customer_details": {"email": "new@example.com"}, "customer": "cus_real", "subscription": None}}}
        with mock.patch.object(billing.email, "send_trial_converted", lambda s, to: converted.append(to)), \
                mock.patch.object(billing.email, "send_welcome", side_effect=AssertionError("must not issue a second key")):
            out = billing.handle_event(main.settings, mock.MagicMock(), event)
        self.assertIn("kept their licence", out)
        self.assertEqual(len(self.store.licenses), n_lic)
        self.assertEqual(self.store.trials[cid]["status"], "converted")
        self.assertEqual(converted, ["new@example.com"])

    def test_a_brand_new_buyer_still_gets_a_key(self):
        sent = []
        event = {"type": "checkout.session.completed", "data": {"object": {"customer_details": {"email": "fresh@example.com"}, "customer": "cus_f", "subscription": None}}}
        with mock.patch.object(billing.email, "send_welcome", lambda s, to, key, url: sent.append((to, key))):
            billing.handle_event(main.settings, mock.MagicMock(), event)
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(self.store.licenses), 1)


if __name__ == "__main__":
    unittest.main()
