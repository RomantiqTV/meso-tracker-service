"""Opt-in contributions of failed reads: small crops of ONE pickup-feed line (item name / quantity / tab) that the app could not decode,
sent by customers who switched "Help improve Meso Tracker" on, so the decoders can be trained on more people's data.

Storage is a SEPARATE Postgres database (env CONTRIB_DATABASE_URL, a second free Neon project) so crop bytes never touch or fill the licence database. With the variable unset the
whole feature answers 503 and the app backs off. Nothing here identifies a person: the uploader is stored only as a keyed hash of the licence id (deletable on request), the payload is
a PNG of a few rows of pickup text plus a short whitelisted metadata dict. Hard caps (per uploader per day, and total stored bytes) keep the free tier from filling.
"""
import base64
import hashlib
import hmac
import json
import os
import struct

MAX_ITEMS = 20                  # crops per request
MAX_PNG_BYTES = 40_000          # one line strip is 1-3 KB; anything bigger is not what the app sends
MAX_W, MAX_H = 1600, 120        # a pickup-line strip: wide and short. A screenshot-sized image is refused
MIN_W, MIN_H = 16, 4
KINDS = ("unread", "decoder_abstain", "name_unresolved")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_TEXT_KEYS = {"why": 80, "app_version": 20, "tab": 12, "raw": 80, "decoder_status": 20, "decoder_kind": 12, "decoder_reason": 80, "path": 40}
_INT_KEYS = {"client_w": (200, 8000), "client_h": (200, 8000), "qty": (0, 1_000_000_000), "alpha_pct": (0, 100)}


def contributor_id(pepper, license_id):
    """Keyed hash of the licence id: stable (so one person's daily cap and a deletion request work) but not reversible to a licence without the pepper."""
    return hmac.new(pepper.encode(), ("contrib:" + str(license_id)).encode(), hashlib.sha256).hexdigest()


def png_size(data):
    """-> (width, height) of a PNG, or None when the bytes are not a well-formed PNG header."""
    if len(data) < 33 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def clean_meta(meta):
    """Whitelist: only known keys, correct types, bounded length; everything else is dropped silently."""
    out = {}
    if not isinstance(meta, dict):
        return out
    for k, n in _TEXT_KEYS.items():
        v = meta.get(k)
        if isinstance(v, str) and v:
            out[k] = "".join(c for c in v if c.isprintable())[:n]
    for k, (lo, hi) in _INT_KEYS.items():
        v = meta.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = v
    return out


def validate_item(item):
    """item: {"kind": str, "png": base64 str, "meta": dict}. -> (kind, png_bytes, meta, sha256) or raises ValueError(reason)."""
    if not isinstance(item, dict):
        raise ValueError("not an object")
    kind = item.get("kind")
    if kind not in KINDS:
        raise ValueError("bad kind")
    try:
        png = base64.b64decode(item.get("png") or "", validate=True)
    except Exception:
        raise ValueError("bad base64")
    if not png or len(png) > MAX_PNG_BYTES:
        raise ValueError("bad size")
    wh = png_size(png)
    if wh is None:
        raise ValueError("not a png")
    if not (MIN_W <= wh[0] <= MAX_W and MIN_H <= wh[1] <= MAX_H):
        raise ValueError("not a line strip")
    return kind, png, clean_meta(item.get("meta")), hashlib.sha256(png).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS contrib_crops (
    id          BIGSERIAL PRIMARY KEY,
    sha256      TEXT UNIQUE NOT NULL,
    contributor TEXT NOT NULL,
    kind        TEXT NOT NULL,
    meta        JSONB NOT NULL,
    png         BYTEA NOT NULL,
    size        INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS contrib_crops_contributor ON contrib_crops (contributor, created_at);
"""


class Store:
    """Postgres access for the contribution database. One short connection per call (Neon scales to zero; the free tier has a small connection cap)."""

    def __init__(self, dsn):
        self.dsn = dsn
        self._ready = False

    def _connect(self):
        import psycopg
        conn = psycopg.connect(self.dsn, autocommit=False)
        if not self._ready:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            conn.commit()
            self._ready = True
        return conn

    def usage(self, who):
        """-> (rows this uploader stored in the last 24 h, total bytes stored)."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM contrib_crops WHERE contributor = %s AND created_at > now() - interval '1 day'", (who,))
            day = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(sum(size), 0) FROM contrib_crops")
            return int(day), int(cur.fetchone()[0])

    def insert(self, who, rows):
        """rows: [(sha, kind, meta, png)]. -> number newly stored (a sha already present is skipped)."""
        n = 0
        with self._connect() as conn, conn.cursor() as cur:
            for sha, kind, meta, png in rows:
                cur.execute("INSERT INTO contrib_crops (sha256, contributor, kind, meta, png, size) VALUES (%s, %s, %s, %s::jsonb, %s, %s) ON CONFLICT (sha256) DO NOTHING",
                            (sha, who, kind, json.dumps(meta), png, len(png)))
                n += cur.rowcount
            conn.commit()
        return n

    def delete_all(self, who):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM contrib_crops WHERE contributor = %s", (who,))
            n = cur.rowcount
            conn.commit()
        return n


_store = None


def get_store():
    """-> the Store, or None when CONTRIB_DATABASE_URL is not set (feature off)."""
    global _store
    dsn = os.environ.get("CONTRIB_DATABASE_URL", "")
    if not dsn:
        return None
    if _store is None or _store.dsn != dsn:
        _store = Store(dsn)
    return _store


def limits():
    return {"per_day": int(os.environ.get("CONTRIB_PER_DAY", "300")), "max_bytes": int(float(os.environ.get("CONTRIB_MAX_MB", "300")) * 1024 * 1024)}


def accept(store, who, items):
    """Validates and stores one upload. -> {"accepted", "duplicates", "rejected", "full"}. full=True tells the app to stop for now (daily or total cap)."""
    lim = limits()
    day, total = store.usage(who)
    room_rows, room_bytes = max(0, lim["per_day"] - day), max(0, lim["max_bytes"] - total)
    good, rejected, seen = [], 0, set()
    for it in items[:MAX_ITEMS]:
        try:
            kind, png, meta, sha = validate_item(it)
        except ValueError:
            rejected += 1
            continue
        if sha in seen:
            continue
        seen.add(sha)
        if len(good) >= room_rows or sum(len(g[3]) for g in good) + len(png) > room_bytes:
            break
        good.append((sha, kind, meta, png))
    stored = store.insert(who, good) if good else 0
    full = room_rows - len(good) <= 0 or room_bytes - sum(len(g[3]) for g in good) < MAX_PNG_BYTES
    return {"accepted": stored, "duplicates": len(good) - stored, "rejected": rejected + max(0, len(items) - MAX_ITEMS), "full": bool(full)}
