"""The shared market price list: validation of what the operator pushes, and the ETag clients revalidate with. Pure functions - no DB, no
network - so they are unit-tested directly (tests/test_prices.py). Storage is repo.put_prices / repo.get_prices (one row)."""
import datetime
import hashlib
import json

MAX_ITEMS = 20000
MIN_ITEMS = 100                  # a push smaller than this is a scraper failure, not a price list: refuse it rather than wipe the good one
MAX_NAME = 120
MAX_PRICE = 10 ** 12


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v < 0 or v > MAX_PRICE:                 # NaN, negative, absurd
        return None
    return int(v) if float(v).is_integer() else round(float(v), 2)


def compact(items):
    """The meso.watch list rows ({name, category, price, npc: {buy, sell}, sold}) or already-compact rows -> a de-duplicated list of
    {name, category, price, npc_buy, npc_sell, sold}. Rows without a usable name are dropped, bad numbers become None."""
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
            continue
        name = name.strip()
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        npc = it.get("npc") if isinstance(it.get("npc"), dict) else {}
        cat = it.get("category")
        out.append({"name": name, "category": cat if isinstance(cat, str) and len(cat) <= 40 else None,
                    "price": _num(it.get("price")),
                    "npc_buy": _num(npc.get("buy", it.get("npc_buy"))), "npc_sell": _num(npc.get("sell", it.get("npc_sell"))),
                    "sold": _num(it.get("sold")) or 0})
    return out


def parse_generated_at(v):
    """ISO-8601 text (with or without a zone; 'Z' accepted) -> an aware datetime; anything else -> now (UTC)."""
    if isinstance(v, str):
        try:
            d = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return datetime.datetime.now(datetime.timezone.utc)


def validate_push(body):
    """-> (generated_at, items) or raises ValueError with a message the operator's script prints."""
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise ValueError("body must be {generated_at, items: [...]}")
    if len(body["items"]) > MAX_ITEMS:
        raise ValueError(f"too many items (max {MAX_ITEMS})")
    items = compact(body["items"])
    if len(items) < MIN_ITEMS:
        raise ValueError(f"only {len(items)} usable items (need at least {MIN_ITEMS}); refusing to replace the stored list")
    priced = sum(1 for i in items if i["price"] is not None)
    if priced < len(items) // 4:
        raise ValueError(f"only {priced} of {len(items)} items have a market price; refusing to replace the stored list")
    return parse_generated_at(body.get("generated_at")), items


def etag(generated_at, count):
    h = hashlib.sha256(f"{generated_at.isoformat()}|{count}".encode()).hexdigest()[:16]
    return f'"{h}"'


def etag_matches(if_none_match, tag):
    """True when an If-None-Match header names `tag`. Render's proxy compresses the body and turns our strong ETag into the weak form W/"..." on the way out, so the
    client sends the weak form back: compare without the W/ prefix (a weak match is all a GET revalidation needs), and accept a comma-separated list or *."""
    for part in (if_none_match or "").split(","):
        part = part.strip()
        if part == "*" or (part[2:] if part.startswith("W/") else part) == tag:
            return True
    return False


def payload(generated_at, items):
    return {"generated_at": generated_at.isoformat(), "count": len(items), "items": items}


def dumps(items):
    return json.dumps(items, separators=(",", ":"), ensure_ascii=False)
