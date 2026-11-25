"""The Meso Tracker licence server. Run locally:  uvicorn app.main:app --reload --port 8000  (from server/, with env vars set -
see ../../SETUP.md). On Render, render.yaml points at this same app."""
import logging
import time

import stripe
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from . import billing, contrib, db, email, prices, ratelimit, repo, security, trials, versioning
from .config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("meso.server")

app = FastAPI(title="Meso Tracker Licence Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.site_url, "null"],      # "null" = file:// during local testing of the static site
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def _startup():
    db.run_migrations()


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _version_info():
    return {"latest_version": settings.latest_version, "min_supported_version": settings.min_supported_version,
            "download_url": settings.download_url, "release_notes": settings.release_notes}


@app.get("/v1/version")
def version():
    """Public, no login needed - the app checks this before showing the login window too, so even someone who downloaded
    an old installer months ago and hasn't activated yet finds out immediately. Edit LATEST_VERSION/MIN_SUPPORTED_VERSION/
    RELEASE_NOTES in Render's env vars whenever you ship a build; no redeploy needed, this just reads them each request."""
    return _version_info()


# ---------------------------------------------------------------------------------------------------------------------- checkout
class CheckoutBody(BaseModel):
    email: EmailStr | None = None
    plan: str = "monthly"       # "monthly" | "6mo" | "yearly" - see billing.PLAN_PRICE_ATTR


@app.post("/v1/checkout")
def checkout(body: CheckoutBody, request: Request):
    if not ratelimit.allow("checkout:" + _client_ip(request), max_per_window=10, window_s=60):
        raise HTTPException(429, "Too many requests, try again shortly")
    if body.plan not in billing.PLAN_PRICE_ATTR:
        raise HTTPException(400, "Unknown plan")
    try:
        url = billing.create_checkout_session(settings, body.email, body.plan)
    except ValueError:
        raise HTTPException(503, "That plan isn't available yet - try Monthly, or try again later")
    return {"url": url}


class PortalBody(BaseModel):
    email: EmailStr
    license_key: str


@app.post("/v1/billing-portal")
def billing_portal(body: PortalBody):
    """Requires the licence key too (not just the email) so a billing-portal link can't be generated for someone else's account
    just by guessing their email address."""
    with db.connect() as conn:
        cur = conn.cursor()
        customer = repo.get_customer_by_email(cur, body.email.strip().lower())
        lic = repo.get_license_by_key_hash(cur, body.email.strip().lower(), security.hash_key(body.license_key, settings.key_pepper)) \
            if customer else None
        if not customer or not lic:
            raise HTTPException(401, "Invalid email or licence key")
    if not customer["stripe_customer_id"]:                  # a free-trial customer has no Stripe customer yet: "Manage billing" leads to the plans instead
        return {"url": settings.site_url + "/#pricing"}
    return {"url": billing.create_billing_portal_session(settings, customer["stripe_customer_id"])}


# ---------------------------------------------------------------------------------------------------------------------- webhook
@app.post("/v1/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="stripe-signature")):
    payload = await request.body()
    try:
        event = billing.verify_and_parse(settings, payload, stripe_signature)
    except (stripe.error.SignatureVerificationError, ValueError):
        raise HTTPException(400, "Invalid signature")
    with db.connect() as conn:
        result = billing.handle_event(settings, conn, event)
    log.info("stripe webhook %s: %s", event["type"], result)
    return {"received": True}


# ---------------------------------------------------------------------------------------------------------------------- licensing
class ActivateBody(BaseModel):
    email: EmailStr
    license_key: str
    hwid: str
    app_version: str = ""


def _client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else request.client.host) or "unknown"


def _authenticate(cur, email, license_key, app_version=""):
    """-> license row, or raises HTTPException. Shared by /activate and /status. A client reporting a version older than
    settings.min_supported_version is refused with 426 (the standard "Upgrade Required" status) - this is REAL
    enforcement of a required update, not just a UI suggestion: an old client simply can't get a session token."""
    if versioning.is_older(app_version, settings.min_supported_version):
        raise HTTPException(426, f"This version of Meso Tracker is no longer supported. Please download the latest "
                                  f"version from {settings.download_url}")
    if not security.is_well_formed_key(license_key):
        raise HTTPException(401, "Invalid email or licence key")
    customer = repo.get_customer_by_email(cur, email)
    if not customer:
        raise HTTPException(401, "Invalid email or licence key")
    lic = repo.get_license_by_key_hash(cur, email, security.hash_key(license_key, settings.key_pepper))
    if not lic:
        raise HTTPException(401, "Invalid email or licence key")
    if not repo.has_active_subscription(cur, customer["id"]):
        trial = repo.get_trial(cur, customer["id"])
        if trial and trial["status"] == "trialing":             # a trial row that is still 'trialing' but no longer live = its days ran out
            raise HTTPException(402, trials.ended_message(settings))
        raise HTTPException(402, "Your subscription isn't active - update your payment method and try again")
    return customer, lic


def _account_info(cur, customer_id):
    """Shown in the app's Settings > Account tab: subscription status and when the current period ends."""
    sub = repo.get_subscription_for_customer(cur, customer_id)
    if not sub:
        return {"subscription_status": None, "current_period_end": None}
    end = sub["current_period_end"]
    return {"subscription_status": sub["status"], "current_period_end": end.isoformat() if end else None}


@app.post("/v1/activate")
def activate(body: ActivateBody, request: Request):
    ip = _client_ip(request)
    if not ratelimit.allow("activate:" + ip, max_per_window=20, window_s=60):
        raise HTTPException(429, "Too many attempts, try again shortly")
    if not security.is_well_formed_hwid(body.hwid):
        raise HTTPException(400, "Malformed hardware id")
    email = body.email.strip().lower()
    with db.connect() as conn:
        cur = conn.cursor()
        customer, lic = _authenticate(cur, email, body.license_key, body.app_version)
        if lic["hwid"] is None:
            try:
                trials.on_bind(settings, cur, customer["id"], body.hwid)       # free trial: one PC per trial, and the first activation starts the clock
            except trials.TrialError as e:
                repo.log_activation(cur, lic["id"], "denied_trial_device", body.hwid, ip, body.app_version)
                conn.commit()
                raise HTTPException(e.status, e.message)
            repo.bind_hwid(cur, lic["id"], body.hwid)
            event = "activate"
        elif lic["hwid"] == body.hwid:
            event = "reactivate"
        else:
            repo.log_activation(cur, lic["id"], "denied_hwid_mismatch", body.hwid, ip, body.app_version)
            conn.commit()
            raise HTTPException(409, "This licence is already active on another PC. Open the app on that PC and choose "
                                      "'Deactivate this device' in Settings, then try again here.")
        repo.log_activation(cur, lic["id"], event, body.hwid, ip, body.app_version)
        account = _account_info(cur, customer["id"])
        ttl, grace = trials.session_limits(settings, cur, customer["id"])
        conn.commit()
    token = security.issue_session(settings.jwt_secret, str(customer["id"]), str(lic["id"]), body.hwid, ttl)
    return {"session_token": token, "expires_in_hours": ttl, "offline_grace_hours": grace, **account, **_version_info()}


class StatusBody(BaseModel):
    email: EmailStr
    license_key: str
    hwid: str
    app_version: str = ""


@app.post("/v1/status")
def status(body: StatusBody, request: Request):
    """Re-validate a device that's already activated (periodic phone-home, no HWID binding change). Also what the app calls right
    after a cancellation to confirm it should stop working, and - since every running copy calls this periodically - where a
    required-update refusal (426) actually reaches people who are already logged in, not just new activations."""
    ip = _client_ip(request)
    if not ratelimit.allow("status:" + ip, max_per_window=30, window_s=60):
        raise HTTPException(429, "Too many attempts, try again shortly")
    email = body.email.strip().lower()
    with db.connect() as conn:
        cur = conn.cursor()
        customer, lic = _authenticate(cur, email, body.license_key, body.app_version)
        if lic["hwid"] != body.hwid:
            raise HTTPException(409, "This licence is active on a different PC")
        account = _account_info(cur, customer["id"])
        ttl, grace = trials.session_limits(settings, cur, customer["id"])
    token = security.issue_session(settings.jwt_secret, str(customer["id"]), str(lic["id"]), body.hwid, ttl)
    return {"session_token": token, "expires_in_hours": ttl, "offline_grace_hours": grace, **account, **_version_info()}


class TrialBody(BaseModel):
    email: EmailStr


@app.post("/v1/trial")
def start_trial(body: TrialBody, request: Request):
    """Free trial, no card: creates a customer + licence + trial and EMAILS the key (the email is the verification). The TRIAL_DAYS clock starts when the app is first opened with that key."""
    ip = _client_ip(request)
    mail = body.email.strip().lower()
    if not ratelimit.allow("trial:" + ip, max_per_window=6, window_s=3600) or not ratelimit.allow("trialmail:" + mail, max_per_window=3, window_s=3600):
        raise HTTPException(429, "Too many attempts, try again later")
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            raw_key = trials.sign_up(settings, cur, mail, ip)
        except trials.TrialError as e:
            raise HTTPException(e.status, e.message)
        except Exception as e:                                       # e.g. a race on the unique email / mailbox constraints
            if type(e).__name__ == "UniqueViolation":
                raise HTTPException(409, "That email has already had a free trial or has an account.")
            raise
        try:
            email.send_trial_welcome(settings, mail, raw_key, settings.download_url, settings.trial_days)
        except Exception:
            conn.rollback()                                          # nothing was created: they can simply try again
            log.exception("trial welcome email did not send")
            raise HTTPException(502, "We couldn't send the email just now. Please try again in a minute.")
        conn.commit()
    return {"ok": True, "days": settings.trial_days}


class DeactivateBody(BaseModel):
    email: EmailStr
    license_key: str


@app.post("/v1/deactivate")
def deactivate(body: DeactivateBody, request: Request):
    """Frees this licence's device slot (e.g. moving to a new PC). Knowing the e-mail + licence key is the only credential - same
    as every other endpoint here - so this can't be used to kick someone else off their own device."""
    with db.connect() as conn:
        cur = conn.cursor()
        customer, lic = _authenticate(cur, body.email.strip().lower(), body.license_key)
        repo.clear_hwid(cur, lic["id"])
        repo.log_activation(cur, lic["id"], "deactivate", lic["hwid"], _client_ip(request), "")
        conn.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------------------------------------------------- opt-in failed-read contributions
class ContribBody(BaseModel):
    items: list[dict]


def _contrib_who(authorization):
    """Bearer session token (the one /v1/activate and /v1/status hand out) -> the uploader's keyed-hash id. 401 on anything wrong."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Missing session token")
    try:
        payload = security.verify_session(settings.jwt_secret, token.strip())
    except (security.TokenError, ValueError):
        raise HTTPException(401, "Invalid or expired session")
    return contrib.contributor_id(settings.key_pepper, payload.get("lid", ""))


@app.post("/v1/contrib")
def contrib_upload(body: ContribBody, authorization: str = Header(default="")):
    """Stores crops of failed pickup-line reads from customers who opted in (contrib.py). 503 when the feature is not configured."""
    store = contrib.get_store()
    if store is None:
        raise HTTPException(503, "Contributions are not enabled")
    who = _contrib_who(authorization)
    if not ratelimit.allow("contrib:" + who, max_per_window=12, window_s=60):
        raise HTTPException(429, "Too many uploads, try again shortly")
    return contrib.accept(store, who, body.items)


@app.post("/v1/contrib/delete")
def contrib_delete(authorization: str = Header(default="")):
    """Deletes everything this licence ever contributed (the app's "Delete my contributed data" button)."""
    store = contrib.get_store()
    if store is None:
        raise HTTPException(503, "Contributions are not enabled")
    who = _contrib_who(authorization)
    return {"deleted": store.delete_all(who)}


# ---------------------------------------------------------------------------------------------------------------------- shared market price list
@app.get("/v1/prices")
def get_market_prices(response: Response, authorization: str = Header(default=""), if_none_match: str = Header(default="")):
    """The latest market price list (items: name, category, price, npc_buy, npc_sell, sold), for licensed apps only (same session token as /v1/contrib). Sends an
    ETag, so the app's startup / hourly refresh costs a 304 when nothing changed. 503 until the operator's push has delivered a first list."""
    who = _contrib_who(authorization)
    if not ratelimit.allow("prices:" + who, max_per_window=30, window_s=60):
        raise HTTPException(429, "Too many requests, try again shortly")
    with db.connect() as conn:
        row = repo.get_prices(conn.cursor())
    if not row:
        raise HTTPException(503, "No price list yet")
    tag = prices.etag(row["generated_at"], row["item_count"])
    if if_none_match.strip() == tag:
        return Response(status_code=304, headers={"ETag": tag})
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = "private, max-age=60"
    return prices.payload(row["generated_at"], row["items"])


@app.post("/v1/admin/prices")
def push_market_prices(body: dict, x_push_key: str = Header(default="")):
    """The operator's hourly push (tools/push_prices.py on the PC that holds the meso.watch session): replaces the stored list. Disabled (404) unless
    PRICES_PUSH_KEY is set in the environment and matches; a list with too few items or too few prices is refused (400), never stored."""
    import hmac
    if not settings.prices_push_key or not hmac.compare_digest(x_push_key.encode(), settings.prices_push_key.encode()):
        raise HTTPException(404)
    try:
        generated_at, items = prices.validate_push(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    with db.connect() as conn:
        repo.put_prices(conn.cursor(), generated_at, items)
        conn.commit()
    return {"stored": len(items), "generated_at": generated_at.isoformat()}


# ---------------------------------------------------------------------------------------------------------------------- one-off admin
@app.post("/v1/admin/broadcast-update")
def broadcast_update(request: Request, x_admin_key: str = Header(default="")):
    """Manual, one-off tool: emails every currently-active/trialing customer the update announcement (see
    email.send_update_announcement). Disabled unless ADMIN_KEY is set in the environment; set it in Render only for
    the duration of this task, call this once with ?dry_run=true to sanity-check the recipient count, then once for
    real, then clear ADMIN_KEY again. Never exposed to the website or the app - admin-only, by design."""
    if not settings.admin_key or x_admin_key != settings.admin_key:
        raise HTTPException(404)
    with db.connect() as conn:
        cur = conn.cursor()
        emails = repo.get_current_userbase_emails(cur)
    if request.query_params.get("dry_run") == "true":
        return {"recipients": len(emails), "sample": emails[:5]}
    sent, failed = [], []
    for to in emails:
        try:
            email.send_update_announcement(settings, to, settings.download_url)
            sent.append(to)
        except Exception as exc:
            failed.append({"email": to, "error": str(exc)})
        time.sleep(0.3)
    return {"sent": len(sent), "failed": failed}
