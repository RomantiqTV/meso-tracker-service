"""Exercises the real route logic in app.main end-to-end (FastAPI TestClient) against an in-memory fake of the DB layer, so the
auth / HWID-binding / subscription-gating control flow is actually tested - not just the pure security.py helpers.

No real Postgres, Stripe or Resend needed: app.db.connect and app.repo are monkeypatched to an in-memory store, and the Stripe
webhook signature is verified for real (it's pure local HMAC - Stripe publishes the exact scheme), just against a payload we built
ourselves instead of one from Stripe's network."""
import hashlib
import hmac
import os
import sys
import time
import unittest
import uuid
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(DATABASE_URL="x", STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_testsecret",
                  STRIPE_PRICE_ID="price_x", RESEND_API_KEY="re_x", JWT_SIGNING_SECRET="unit-test-jwt-secret",
                  LICENSE_KEY_PEPPER="unit-test-pepper").items():
    os.environ.setdefault(k, v)

from fastapi.testclient import TestClient  # noqa: E402

from app import main, security  # noqa: E402


class FakeStore:
    """A tiny in-memory stand-in for the Postgres tables repo.py reads and writes."""

    def __init__(self):
        self.customers = {}          # email -> row
        self.licenses = {}           # id -> row
        self.active_customers = set()
        self.log = []

    def add_customer(self, email):
        row = {"id": str(uuid.uuid4()), "email": email, "stripe_customer_id": "cus_" + email}
        self.customers[email] = row
        return row

    def add_license(self, customer, raw_key, max_activations=1):
        row = {"id": str(uuid.uuid4()), "customer_id": customer["id"],
               "key_hash": security.hash_key(raw_key, os.environ["LICENSE_KEY_PEPPER"]),
               "key_hint": security.key_hint(raw_key), "hwid": None, "max_activations": max_activations, "revoked_at": None}
        self.licenses[row["id"]] = row
        return row


def fake_repo_for(store):
    class R:
        @staticmethod
        def get_customer_by_email(cur, email):
            return store.customers.get(email)

        @staticmethod
        def get_license_by_key_hash(cur, email, key_hash):
            c = store.customers.get(email)
            if not c:
                return None
            return next((l for l in store.licenses.values() if l["customer_id"] == c["id"] and l["key_hash"] == key_hash
                         and l["revoked_at"] is None), None)

        @staticmethod
        def has_active_subscription(cur, customer_id):
            return customer_id in store.active_customers

        @staticmethod
        def bind_hwid(cur, license_id, hwid):
            store.licenses[license_id]["hwid"] = hwid

        @staticmethod
        def clear_hwid(cur, license_id):
            store.licenses[license_id]["hwid"] = None

        @staticmethod
        def log_activation(cur, license_id, event, hwid, ip, app_version):
            store.log.append((license_id, event, hwid, ip, app_version))

        @staticmethod
        def get_customer_by_stripe_id(cur, sid):
            return next((c for c in store.customers.values() if c["stripe_customer_id"] == sid), None)

        @staticmethod
        def create_customer(cur, email, sid):
            return store.add_customer(email)

        @staticmethod
        def create_license(cur, customer_id, key_hash, hint, max_act):
            raise AssertionError("not used in these tests")

        @staticmethod
        def upsert_subscription(cur, customer_id, sub_id, status, period_end):
            if status in ("active", "trialing"):
                store.active_customers.add(customer_id)
            else:
                store.active_customers.discard(customer_id)

    return R()


@contextmanager
def fake_connect():
    yield mock.MagicMock()


def stripe_sig_header(payload_bytes, secret):
    """Builds the header the way Stripe's own SDK verifies it: t=<ts>,v1=hmac_sha256_hex(f'{ts}.{payload}')."""
    ts = str(int(time.time()))
    signed = f"{ts}.{payload_bytes.decode()}".encode()
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


class LicenseFlowTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.customer = self.store.add_customer("buyer@example.com")
        self.store.active_customers.add(self.customer["id"])
        self.raw_key = "MESO-WXYZ-ABCD-EFGH-JKLM"
        self.lic = self.store.add_license(self.customer, self.raw_key)
        patcher1 = mock.patch.object(main, "repo", fake_repo_for(self.store))
        patcher2 = mock.patch.object(main.db, "connect", fake_connect)
        patcher1.start(); patcher2.start()
        self.addCleanup(patcher1.stop); self.addCleanup(patcher2.stop)
        self.client = TestClient(main.app)
        self.hwid_a, self.hwid_b = "a" * 64, "b" * 64

    def test_first_activation_binds_the_device_and_issues_a_session(self):
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                     "hwid": self.hwid_a, "app_version": "1.0"})
        self.assertEqual(r.status_code, 200, r.text)
        payload = security.verify_session(os.environ["JWT_SIGNING_SECRET"], r.json()["session_token"])
        self.assertEqual(payload["hwid"], self.hwid_a)
        self.assertEqual(self.lic["hwid"], self.hwid_a)

    def test_same_device_can_reactivate(self):
        self.lic["hwid"] = self.hwid_a
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                     "hwid": self.hwid_a, "app_version": "1.0"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_second_device_is_refused_with_a_clear_message(self):
        self.lic["hwid"] = self.hwid_a
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                     "hwid": self.hwid_b, "app_version": "1.0"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Deactivate this device", r.json()["detail"])
        self.assertEqual(self.store.licenses[self.lic["id"]]["hwid"], self.hwid_a)      # binding untouched by the refused attempt

    def test_deactivate_then_a_new_device_can_bind(self):
        self.lic["hwid"] = self.hwid_a
        r = self.client.post("/v1/deactivate", json={"email": "buyer@example.com", "license_key": self.raw_key})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.lic["hwid"])
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                     "hwid": self.hwid_b, "app_version": "1.0"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.lic["hwid"], self.hwid_b)

    def test_wrong_key_is_rejected_without_revealing_which_part_was_wrong(self):
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": "MESO-ZZZZ-ZZZZ-ZZZZ-ZZZZ",
                                                     "hwid": self.hwid_a, "app_version": "1.0"})
        self.assertEqual(r.status_code, 401)

    def test_unknown_email_is_rejected(self):
        r = self.client.post("/v1/activate", json={"email": "nobody@example.com", "license_key": self.raw_key,
                                                     "hwid": self.hwid_a, "app_version": "1.0"})
        self.assertEqual(r.status_code, 401)

    def test_canceled_subscription_blocks_activation_even_with_the_right_key(self):
        self.store.active_customers.discard(self.customer["id"])
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                     "hwid": self.hwid_a, "app_version": "1.0"})
        self.assertEqual(r.status_code, 402)

    def test_status_requires_the_same_device_that_is_bound(self):
        self.lic["hwid"] = self.hwid_a
        ok = self.client.post("/v1/status", json={"email": "buyer@example.com", "license_key": self.raw_key, "hwid": self.hwid_a})
        self.assertEqual(ok.status_code, 200, ok.text)
        wrong = self.client.post("/v1/status", json={"email": "buyer@example.com", "license_key": self.raw_key, "hwid": self.hwid_b})
        self.assertEqual(wrong.status_code, 409)

    def test_malformed_hwid_is_rejected_before_touching_the_database(self):
        r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                     "hwid": "not-hex", "app_version": "1.0"})
        self.assertEqual(r.status_code, 400)

    def test_outdated_client_is_refused_with_426_even_with_correct_credentials(self):
        with mock.patch.object(main.settings, "min_supported_version", "2.0.0"):
            r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                         "hwid": self.hwid_a, "app_version": "1.0.0"})
        self.assertEqual(r.status_code, 426)
        self.assertIsNone(self.lic["hwid"])                            # refused before touching the HWID binding

    def test_status_also_enforces_the_minimum_version(self):
        self.lic["hwid"] = self.hwid_a
        with mock.patch.object(main.settings, "min_supported_version", "2.0.0"):
            r = self.client.post("/v1/status", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                       "hwid": self.hwid_a, "app_version": "1.0.0"})
        self.assertEqual(r.status_code, 426)

    def test_new_enough_client_is_unaffected_by_the_minimum(self):
        with mock.patch.object(main.settings, "min_supported_version", "1.0.0"):
            r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                         "hwid": self.hwid_a, "app_version": "1.5.0"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_activate_and_status_responses_include_version_info(self):
        with mock.patch.object(main.settings, "latest_version", "1.5.0"), \
             mock.patch.object(main.settings, "download_url", "https://example.com/get"):
            r = self.client.post("/v1/activate", json={"email": "buyer@example.com", "license_key": self.raw_key,
                                                         "hwid": self.hwid_a, "app_version": "1.0.0"})
        self.assertEqual(r.json()["latest_version"], "1.5.0")
        self.assertEqual(r.json()["download_url"], "https://example.com/get")


class VersionEndpointTests(unittest.TestCase):
    def test_public_endpoint_needs_no_credentials(self):
        with mock.patch.object(main.settings, "latest_version", "1.5.0"), \
             mock.patch.object(main.settings, "min_supported_version", "1.0.0"), \
             mock.patch.object(main.settings, "release_notes", "Bug fixes"):
            r = TestClient(main.app).get("/v1/version")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"latest_version": "1.5.0", "min_supported_version": "1.0.0",
                                     "download_url": "", "release_notes": "Bug fixes"})


class WebhookSignatureTests(unittest.TestCase):
    def test_forged_signature_is_rejected(self):
        with mock.patch.object(main.db, "connect", fake_connect):
            client = TestClient(main.app)
            body = b'{"type": "customer.subscription.updated", "data": {"object": {}}}'
            r = client.post("/v1/webhooks/stripe", content=body, headers={"stripe-signature": "t=1,v1=deadbeef"})
            self.assertEqual(r.status_code, 400)

    def test_genuine_signature_with_unknown_customer_is_accepted_and_ignored(self):
        """A correctly-signed event for a Stripe customer we have no local record of (e.g. a race, or a stray event type) must
        be acknowledged (200) and simply skipped - never a 500, since Stripe retries on failure and could hammer the endpoint."""
        with mock.patch.object(main, "repo", fake_repo_for(FakeStore())), mock.patch.object(main.db, "connect", fake_connect):
            client = TestClient(main.app)
            body = b'{"id":"evt_1","type":"customer.subscription.updated","data":{"object":{"id":"sub_1","customer":"cus_ghost","status":"active"}}}'
            sig = stripe_sig_header(body, os.environ["STRIPE_WEBHOOK_SECRET"])
            r = client.post("/v1/webhooks/stripe", content=body, headers={"stripe-signature": sig, "content-type": "application/json"})
            self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
