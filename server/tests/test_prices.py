"""The shared market price list: validation of the operator's push (app/prices.py) and the two routes (GET /v1/prices for licensed apps,
POST /v1/admin/prices for the hourly push). The DB layer is replaced by an in-memory one-row store, as in test_main_integration."""
import datetime
import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(DATABASE_URL="x", STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_testsecret",
                  STRIPE_PRICE_ID="price_x", RESEND_API_KEY="re_x", JWT_SIGNING_SECRET="unit-test-jwt-secret",
                  LICENSE_KEY_PEPPER="unit-test-pepper").items():
    os.environ.setdefault(k, v)

from fastapi.testclient import TestClient  # noqa: E402

from app import main, prices, ratelimit, repo, security  # noqa: E402


def rows(n=150, priced=True):
    return [{"name": f"Item {i}", "category": "Etc", "price": (100 + i) if priced else None, "npc": {"buy": 10, "sell": 5}, "sold": 3} for i in range(n)]


class CompactTests(unittest.TestCase):
    def test_meso_watch_rows_become_flat_rows(self):
        out = prices.compact([{"name": " Iron Ore ", "category": "Etc", "price": 300.0, "npc": {"buy": None, "sell": 40}, "sold": 7}])
        self.assertEqual(out, [{"name": "Iron Ore", "category": "Etc", "price": 300, "npc_buy": None, "npc_sell": 40, "sold": 7}])

    def test_already_flat_rows_pass_through(self):
        out = prices.compact([{"name": "A", "price": 1.5, "npc_buy": 2, "npc_sell": 1}])
        self.assertEqual((out[0]["price"], out[0]["npc_buy"], out[0]["npc_sell"]), (1.5, 2, 1))

    def test_bad_rows_and_numbers(self):
        out = prices.compact([{"name": ""}, {"name": 5}, "x", None, {"name": "N", "price": -1}, {"name": "Nan", "price": float("nan")},
                              {"name": "Big", "price": 10 ** 15}, {"name": "T", "price": True}, {"name": "n"}, {"name": "N"}])
        self.assertEqual([o["name"] for o in out], ["N", "Nan", "Big", "T"])         # "n" is a duplicate of "N" (case-folded)
        self.assertTrue(all(o["price"] is None for o in out))


class ValidateTests(unittest.TestCase):
    def test_good_push(self):
        gen, items = prices.validate_push({"generated_at": "2026-11-25T10:00:00Z", "items": rows()})
        self.assertEqual(len(items), 150)
        self.assertEqual(gen, datetime.datetime(2026, 11, 25, 10, 0, tzinfo=datetime.timezone.utc))

    def test_refuses_tiny_or_unpriced_lists(self):
        for body in ({"items": rows(20)}, {"items": rows(150, priced=False)}, {"items": "x"}, [], {"nope": 1}):
            with self.assertRaises(ValueError):
                prices.validate_push(body)

    def test_refuses_oversize(self):
        with self.assertRaises(ValueError):
            prices.validate_push({"items": [{"name": f"i{i}", "price": 1} for i in range(prices.MAX_ITEMS + 1)]})

    def test_missing_or_garbage_timestamp_means_now(self):
        gen, _ = prices.validate_push({"generated_at": "not a date", "items": rows()})
        self.assertLess(abs((datetime.datetime.now(datetime.timezone.utc) - gen).total_seconds()), 5)

    def test_etag_changes_with_the_list(self):
        t = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        self.assertEqual(prices.etag(t, 5), prices.etag(t, 5))
        self.assertNotEqual(prices.etag(t, 5), prices.etag(t, 6))
        self.assertNotEqual(prices.etag(t, 5), prices.etag(t + datetime.timedelta(hours=1), 5))


class EtagMatchTests(unittest.TestCase):
    def test_strong_weak_list_and_star(self):
        t = '"abc"'
        self.assertTrue(prices.etag_matches('"abc"', t))
        self.assertTrue(prices.etag_matches('W/"abc"', t))                 # what a client sends back after Render's proxy weakened the tag
        self.assertTrue(prices.etag_matches('"zzz", W/"abc"', t))
        self.assertTrue(prices.etag_matches("*", t))
        for bad in ("", None, '"abd"', 'W/"abd"', "abc"):
            self.assertFalse(prices.etag_matches(bad, t), bad)


class FakeDb:
    def __init__(self):
        self.row = None
        self.commits = 0

    @contextmanager
    def connect(self):
        outer = self

        class Conn:
            def cursor(self):
                return object()

            def commit(self):
                outer.commits += 1
        yield Conn()

    def put(self, _cur, generated_at, items):
        self.row = {"generated_at": generated_at, "received_at": generated_at, "item_count": len(items), "items": items}

    def get(self, _cur):
        return self.row


class RouteTests(unittest.TestCase):
    def setUp(self):
        ratelimit._hits.clear()
        self.db = FakeDb()
        self.c = TestClient(main.app)
        self.tok = security.issue_session(main.settings.jwt_secret, "cust-1", "lic-1", "a" * 64, 24)
        self.h = {"Authorization": "Bearer " + self.tok}
        self.patches = [mock.patch.object(main.db, "connect", self.db.connect), mock.patch.object(repo, "put_prices", self.db.put),
                        mock.patch.object(repo, "get_prices", self.db.get), mock.patch.object(main.settings, "prices_push_key", "push-secret")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def push(self, body=None, key="push-secret"):
        return self.c.post("/v1/admin/prices", json=body if body is not None else {"generated_at": "2026-11-25T10:00:00Z", "items": rows()},
                           headers={"X-Push-Key": key} if key is not None else {})

    def test_push_then_get(self):
        r = self.push()
        self.assertEqual((r.status_code, r.json()["stored"]), (200, 150))
        self.assertEqual(self.db.commits, 1)
        g = self.c.get("/v1/prices", headers=self.h)
        self.assertEqual(g.status_code, 200)
        j = g.json()
        self.assertEqual((j["count"], j["items"][0]["name"], j["items"][0]["npc_sell"]), (150, "Item 0", 5))
        self.assertTrue(g.headers["etag"])

    def test_get_revalidates_with_etag(self):
        self.push()
        tag = self.c.get("/v1/prices", headers=self.h).headers["etag"]
        r = self.c.get("/v1/prices", headers={**self.h, "If-None-Match": tag})
        self.assertEqual((r.status_code, r.content), (304, b""))
        self.push({"generated_at": "2026-11-25T11:00:00Z", "items": rows()})
        self.assertEqual(self.c.get("/v1/prices", headers={**self.h, "If-None-Match": tag}).status_code, 200)

    def test_get_revalidates_with_the_weak_etag_the_proxy_produces(self):
        self.push()
        tag = self.c.get("/v1/prices", headers=self.h).headers["etag"]
        self.assertEqual(self.c.get("/v1/prices", headers={**self.h, "If-None-Match": "W/" + tag}).status_code, 304)

    def test_get_needs_a_session(self):
        self.push()
        self.assertEqual(self.c.get("/v1/prices").status_code, 401)
        self.assertEqual(self.c.get("/v1/prices", headers={"Authorization": "Bearer nope"}).status_code, 401)

    def test_get_before_any_push_is_503(self):
        self.assertEqual(self.c.get("/v1/prices", headers=self.h).status_code, 503)

    def test_push_needs_the_key(self):
        for key in (None, "", "wrong", "push-secret "):
            self.assertEqual(self.push(key=key).status_code, 404, key)
        self.assertIsNone(self.db.row)

    def test_push_disabled_when_key_unset(self):
        with mock.patch.object(main.settings, "prices_push_key", ""):
            self.assertEqual(self.push(key="").status_code, 404)

    def test_bad_push_is_refused_and_keeps_the_old_list(self):
        self.push()
        r = self.push({"items": rows(10)})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.db.row["item_count"], 150)

    def test_get_rate_limit(self):
        self.push()
        codes = [self.c.get("/v1/prices", headers=self.h).status_code for _ in range(32)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30:], [429, 429])


if __name__ == "__main__":
    unittest.main()
