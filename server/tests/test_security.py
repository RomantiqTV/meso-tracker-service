"""Pure-function tests - no DB, no Stripe, no network. Run: cd server && python -m unittest discover -s tests -v"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import security  # noqa: E402


class LicenseKeyTests(unittest.TestCase):
    def test_generated_key_is_well_formed(self):
        for _ in range(200):
            k = security.generate_license_key()
            self.assertTrue(security.is_well_formed_key(k), k)
            random_part = k.split("-", 1)[1]              # the literal "MESO" prefix legitimately contains an O
            for bad_char in "01OI":
                self.assertNotIn(bad_char, random_part)

    def test_malformed_keys_are_rejected(self):
        for bad in ("", "MESO-1234", "meso-oooo-bbbb-cccc-dddd", "NOTM-ESOX-WXYZ-ABCD-WXYZ", "MESO-WXYZ-ABCD-EFGH-JKL",
                    "MESO-0000-ABCD-EFGH-JKLM", "MESO-OOOO-ABCD-EFGH-JKLM", "MESO-1111-ABCD-EFGH-JKLM", "MESO-IIII-ABCD-EFGH-JKLM"):
            self.assertFalse(security.is_well_formed_key(bad), bad)
        self.assertTrue(security.is_well_formed_key(" meso-wxyz-abcd-efgh-jklm "))      # case/whitespace tolerant

    def test_hash_is_deterministic_and_keyed(self):
        k = security.generate_license_key()
        self.assertEqual(security.hash_key(k, "pepperA"), security.hash_key(k.lower(), "pepperA"))   # case-insensitive
        self.assertNotEqual(security.hash_key(k, "pepperA"), security.hash_key(k, "pepperB"))          # pepper matters
        self.assertNotEqual(security.hash_key(k, "pepperA"), k)                                        # never the raw key itself

    def test_hint_is_last_four_chars(self):
        self.assertEqual(security.key_hint("MESO-ABCD-EFGH-JKLM-NPQR"), "NPQR")


class HwidFormatTests(unittest.TestCase):
    def test_accepts_64_hex_chars_only(self):
        self.assertTrue(security.is_well_formed_hwid("a" * 64))
        self.assertTrue(security.is_well_formed_hwid("A" * 64))        # case-insensitive
        self.assertFalse(security.is_well_formed_hwid("a" * 63))
        self.assertFalse(security.is_well_formed_hwid("z" * 64))       # not hex
        self.assertFalse(security.is_well_formed_hwid(""))
        self.assertFalse(security.is_well_formed_hwid(None))


class SessionTokenTests(unittest.TestCase):
    def test_round_trip(self):
        tok = security.issue_session("sekret", "cust-1", "lic-1", "a" * 64, ttl_hours=1)
        payload = security.verify_session("sekret", tok)
        self.assertEqual((payload["cid"], payload["lid"], payload["hwid"]), ("cust-1", "lic-1", "a" * 64))

    def test_wrong_secret_is_rejected(self):
        tok = security.issue_session("sekret", "cust-1", "lic-1", "a" * 64, ttl_hours=1)
        with self.assertRaises(security.TokenError):
            security.verify_session("different", tok)

    def test_tampered_payload_is_rejected(self):
        tok = security.issue_session("sekret", "cust-1", "lic-1", "a" * 64, ttl_hours=1)
        h, p, s = tok.split(".")
        forged = h + "." + p[:-2] + ("Q" if p[-2] != "Q" else "R") + p[-1] + "." + s
        with self.assertRaises(security.TokenError):
            security.verify_session("sekret", forged)

    def test_expired_token_is_rejected(self):
        tok = security.issue_session("sekret", "cust-1", "lic-1", "a" * 64, ttl_hours=-1)
        with self.assertRaises(security.TokenError):
            security.verify_session("sekret", tok)

    def test_malformed_token_is_rejected(self):
        with self.assertRaises(security.TokenError):
            security.verify_session("sekret", "not-a-jwt")


if __name__ == "__main__":
    unittest.main()
