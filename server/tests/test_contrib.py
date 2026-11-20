"""Opt-in failed-read contributions: validation, caps, auth and deletion (app.contrib + the /v1/contrib routes), against an in-memory store."""
import base64
import os
import struct
import sys
import time
import unittest
import zlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(DATABASE_URL="x", STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_testsecret",
                  STRIPE_PRICE_ID="price_x", RESEND_API_KEY="re_x", JWT_SIGNING_SECRET="unit-test-jwt-secret",
                  LICENSE_KEY_PEPPER="unit-test-pepper").items():
    os.environ.setdefault(k, v)

from fastapi.testclient import TestClient  # noqa: E402

from app import contrib, main, ratelimit, security  # noqa: E402


def make_png(w=120, h=20, seed=0):
    """A real, tiny grayscale PNG (the server only reads the header, but make it decodable anyway)."""
    raw = b"".join(b"\x00" + bytes(((x * 7 + y + seed) % 256) for x in range(w)) for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return contrib.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def item(seed=0, kind="unread", **kw):
    png = kw.pop("png", None) or make_png(seed=seed)
    return {"kind": kind, "png": base64.b64encode(png).decode(), "meta": kw.pop("meta", {"why": "decoder abstained", "app_version": "1.3.6"})}


class FakeStore:
    def __init__(self):
        self.rows = {}          # sha -> (who, kind, meta, png, ts)

    def usage(self, who):
        day = sum(1 for r in self.rows.values() if r[0] == who and time.time() - r[4] < 86400)
        return day, sum(len(r[3]) for r in self.rows.values())

    def insert(self, who, rows):
        n = 0
        for sha, kind, meta, png in rows:
            if sha not in self.rows:
                self.rows[sha] = (who, kind, meta, png, time.time())
                n += 1
        return n

    def delete_all(self, who):
        gone = [s for s, r in self.rows.items() if r[0] == who]
        for s in gone:
            del self.rows[s]
        return len(gone)


class ValidateTests(unittest.TestCase):
    def test_good_item(self):
        kind, png, meta, sha = contrib.validate_item(item(kind="name_unresolved"))
        self.assertEqual(kind, "name_unresolved")
        self.assertEqual(meta["app_version"], "1.3.6")
        self.assertEqual(len(sha), 64)

    def test_refuses_bad_input(self):
        for bad in ({"kind": "other", "png": item()["png"]}, {"kind": "unread", "png": "!!notb64"}, {"kind": "unread", "png": base64.b64encode(b"hello world" * 10).decode()},
                    item(png=make_png(w=1400, h=700)), item(png=make_png(w=8, h=2)), item(png=make_png(w=1700, h=20)), "string", {"kind": "unread"}):
            with self.assertRaises(ValueError, msg=str(bad)[:60]):
                contrib.validate_item(bad)

    def test_size_cap(self):
        big = contrib.PNG_MAGIC + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 100, 20) + b"\x08\x00\x00\x00\x00" + b"\x00" * (contrib.MAX_PNG_BYTES + 5)
        with self.assertRaises(ValueError):
            contrib.validate_item(item(png=big))

    def test_meta_whitelist(self):
        m = contrib.clean_meta({"why": "x" * 500, "evil": "drop me", "client_w": 1366, "client_h": "no", "qty": True, "raw": "Red Potion\x00\n", "tab": 5})
        self.assertEqual(set(m), {"why", "client_w", "raw"})
        self.assertEqual(len(m["why"]), 80)
        self.assertEqual(m["raw"], "Red Potion")


class AcceptTests(unittest.TestCase):
    def test_stores_dedupes_and_counts_rejects(self):
        s = FakeStore()
        r = contrib.accept(s, "u1", [item(1), item(1), item(2), {"kind": "bad"}])
        self.assertEqual((r["accepted"], r["rejected"], r["full"]), (2, 1, False))
        again = contrib.accept(s, "u2", [item(1)])               # same crop from someone else: already stored
        self.assertEqual((again["accepted"], again["duplicates"]), (0, 1))

    def test_daily_cap(self):
        s = FakeStore()
        with mock.patch.dict(os.environ, {"CONTRIB_PER_DAY": "3"}):
            r = contrib.accept(s, "u1", [item(i) for i in range(10)])
            self.assertEqual(r["accepted"], 3)
            self.assertTrue(r["full"])
            self.assertEqual(contrib.accept(s, "u1", [item(50)])["accepted"], 0)
            self.assertEqual(contrib.accept(s, "u2", [item(51)])["accepted"], 1)     # another uploader is unaffected

    def test_total_bytes_cap(self):
        s = FakeStore()
        one = len(make_png(seed=0))
        with mock.patch.dict(os.environ, {"CONTRIB_MAX_MB": str(one * 2.5 / 1048576)}):
            r = contrib.accept(s, "u1", [item(i) for i in range(6)])
            self.assertEqual(r["accepted"], 2)
            self.assertTrue(r["full"])

    def test_batch_limit(self):
        r = contrib.accept(FakeStore(), "u1", [item(i) for i in range(contrib.MAX_ITEMS + 5)])
        self.assertEqual(r["accepted"], contrib.MAX_ITEMS)
        self.assertEqual(r["rejected"], 5)


class RouteTests(unittest.TestCase):
    def setUp(self):
        ratelimit._hits.clear()
        self.c = TestClient(main.app)
        self.store = FakeStore()
        self.tok = security.issue_session(main.settings.jwt_secret, "cust-1", "lic-1", "a" * 64, 24)
        self.h = {"Authorization": "Bearer " + self.tok}

    def post(self, items, headers=None, store="default"):
        st = self.store if store == "default" else store
        with mock.patch.object(contrib, "get_store", lambda: st):
            return self.c.post("/v1/contrib", json={"items": items}, headers=self.h if headers is None else headers)

    def test_upload_and_delete(self):
        r = self.post([item(1), item(2)])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["accepted"], 2)
        who = contrib.contributor_id(main.settings.key_pepper, "lic-1")
        self.assertTrue(all(v[0] == who for v in self.store.rows.values()))         # stored under the keyed hash, never the licence id
        self.assertNotIn("lic-1", repr([v[:3] for v in self.store.rows.values()]))
        with mock.patch.object(contrib, "get_store", lambda: self.store):
            d = self.c.post("/v1/contrib/delete", headers=self.h)
        self.assertEqual(d.json(), {"deleted": 2})
        self.assertEqual(self.store.rows, {})

    def test_auth_required(self):
        self.assertEqual(self.post([item(1)], headers={}).status_code, 401)
        self.assertEqual(self.post([item(1)], headers={"Authorization": "Bearer nope"}).status_code, 401)
        expired = security.issue_session(main.settings.jwt_secret, "c", "l", "a" * 64, -1)
        self.assertEqual(self.post([item(1)], headers={"Authorization": "Bearer " + expired}).status_code, 401)
        forged = self.tok[:-3] + ("AAA" if not self.tok.endswith("AAA") else "BBB")
        self.assertEqual(self.post([item(1)], headers={"Authorization": "Bearer " + forged}).status_code, 401)
        self.assertEqual(self.store.rows, {})

    def test_disabled_without_database(self):
        self.assertEqual(self.post([item(1)], store=None).status_code, 503)
        with mock.patch.object(contrib, "get_store", lambda: None):
            self.assertEqual(self.c.post("/v1/contrib/delete", headers=self.h).status_code, 503)

    def test_rate_limit(self):
        codes = [self.post([item(100 + i)]).status_code for i in range(14)]
        self.assertEqual(codes[:12], [200] * 12)
        self.assertEqual(codes[12:], [429, 429])

    def test_get_store_off_when_unset(self):
        with mock.patch.dict(os.environ, {"CONTRIB_DATABASE_URL": ""}):
            self.assertIsNone(contrib.get_store())


if __name__ == "__main__":
    unittest.main()
