"""License keys and session tokens.

License key: a 128-bit random token the customer gets ONCE by email, formatted like a product key (MESO-XXXX-XXXX-XXXX-XXXX) so it's
easy to read back over support chat. Only its HMAC is ever stored (same idea as a password hash, but an HMAC is enough here because
the key itself already has far more entropy than any human-chosen password could - there's nothing for a slow hash like bcrypt to
protect against that a fast keyed hash doesn't already cover, and it keeps every login near-instant).

Session token: a short-lived signed JWT the app caches locally after a successful /v1/activate or /v1/status call, so it isn't
forced to hit the network on every single use - but it still expires (SESSION_TTL_HOURS) and the app re-validates before then.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # no 0/O/1/I - unambiguous when read aloud or typed from an email
KEY_RE = re.compile(r"^MESO(?:-[A-HJ-NP-Z2-9]{4}){4}$")   # same exclusions as KEY_ALPHABET, so a typo'd 0/O/1/I is rejected early
HWID_RE = re.compile(r"^[0-9a-f]{64}$")                    # a hex sha256 - see the client's hwid.py for how it's derived


def generate_license_key():
    """-> 'MESO-XXXX-XXXX-XXXX-XXXX' raw key (give this to the customer once; never store it)."""
    chars = [secrets.choice(KEY_ALPHABET) for _ in range(16)]
    groups = ["".join(chars[i:i + 4]) for i in range(0, 16, 4)]
    return "MESO-" + "-".join(groups)


def normalize_key(raw):
    return (raw or "").strip().upper()


def is_well_formed_key(raw):
    return bool(KEY_RE.match(normalize_key(raw)))


def hash_key(raw, pepper):
    """HMAC-SHA256(pepper, key) as a hex digest - deterministic (so it can be looked up by equality), but the pepper means a leaked
    database alone can't be brute-forced into keys (and a leaked pepper alone is useless without the database)."""
    return hmac.new(pepper.encode(), normalize_key(raw).encode(), hashlib.sha256).hexdigest()


def key_hint(raw):
    return normalize_key(raw)[-4:]


def is_well_formed_hwid(hwid):
    return bool(HWID_RE.match((hwid or "").lower()))


# ---------------------------------------------------------------------------------------------------------------------- session JWT
def _b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _b64u_json(obj):
    return _b64u(json.dumps(obj, separators=(",", ":")).encode())


def issue_session(secret, customer_id, license_id, hwid, ttl_hours):
    """-> opaque session token string. Hand-rolled HS256 JWT (header.payload.signature, base64url) so the server has zero extra
    dependency for something this small; the client never decodes it, just stores and resends it."""
    now = int(time.time())
    header = _b64u_json({"alg": "HS256", "typ": "JWT"})
    payload = _b64u_json({"cid": customer_id, "lid": license_id, "hwid": hwid, "iat": now, "exp": now + ttl_hours * 3600})
    signing_input = header + b"." + payload
    sig = _b64u(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + sig).decode()


class TokenError(Exception):
    pass


def verify_session(secret, token):
    """-> payload dict, or raises TokenError (bad signature / malformed / expired)."""
    try:
        header_b64, payload_b64, sig_b64 = token.encode().split(b".")
    except ValueError:
        raise TokenError("malformed token")
    signing_input = header_b64 + b"." + payload_b64
    expected = _b64u(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig_b64):
        raise TokenError("bad signature")

    def _pad(b):
        return b + b"=" * (-len(b) % 4)

    payload = json.loads(base64.urlsafe_b64decode(_pad(payload_b64)))
    if payload.get("exp", 0) < time.time():
        raise TokenError("expired")
    return payload
