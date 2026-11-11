"""The Meso Tracker licence server. Run locally:  uvicorn app.main:app --reload --port 8000  (from server/, with env vars set -
see ../../SETUP.md). On Render, render.yaml points at this same app."""
import logging

import stripe
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from . import billing, db, ratelimit, repo, security, versioning
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


@app.post("/v1/checkout")
def checkout(body: CheckoutBody, request: Request):
    if not ratelimit.allow("checkout:" + _client_ip(request), max_per_window=10, window_s=60):
        raise HTTPException(429, "Too many requests, try again shortly")
    url = billing.create_checkout_session(settings, body.email)
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
        raise HTTPException(402, "Your subscription isn't active - update your payment method and try again")
    return customer, lic


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
        conn.commit()
    token = security.issue_session(settings.jwt_secret, str(customer["id"]), str(lic["id"]), body.hwid, settings.session_ttl_hours)
    return {"session_token": token, "expires_in_hours": settings.session_ttl_hours, "offline_grace_hours": settings.offline_grace_hours,
            **_version_info()}


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
    token = security.issue_session(settings.jwt_secret, str(customer["id"]), str(lic["id"]), body.hwid, settings.session_ttl_hours)
    return {"session_token": token, "expires_in_hours": settings.session_ttl_hours, "offline_grace_hours": settings.offline_grace_hours,
            **_version_info()}


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
