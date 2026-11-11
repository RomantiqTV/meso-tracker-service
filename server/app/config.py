"""All configuration comes from environment variables (set in Render's dashboard, never committed to git). Nothing here is a secret
value - it's just where each secret is read FROM. See ../../SETUP.md for where each one comes from and how to generate it."""
import os
import secrets


def _require(name, default=None):
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing required environment variable: {name} (see SETUP.md)")
    return v


class Settings:
    def __init__(self):
        # Database (Render provides DATABASE_URL automatically when the web service is linked to a Render Postgres instance)
        self.database_url = _require("DATABASE_URL")

        # Stripe (dashboard.stripe.com -> Developers -> API keys / Webhooks)
        self.stripe_secret_key = _require("STRIPE_SECRET_KEY")
        self.stripe_webhook_secret = _require("STRIPE_WEBHOOK_SECRET")
        self.stripe_price_id = _require("STRIPE_PRICE_ID")          # the recurring $1.99/mo Price ID
        self.stripe_publishable_key = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")

        # Resend (resend.com -> API Keys) - transactional email: license key + download link after purchase
        self.resend_api_key = _require("RESEND_API_KEY")
        self.email_from = os.environ.get("EMAIL_FROM", "Meso Tracker <onboarding@resend.dev>")

        # Session tokens the app caches after a successful login (HS256 JWT, server-only secret - the client never needs this key)
        self.jwt_secret = _require("JWT_SIGNING_SECRET")
        self.session_ttl_hours = int(os.environ.get("SESSION_TTL_HOURS", "24"))
        self.offline_grace_hours = int(os.environ.get("OFFLINE_GRACE_HOURS", "72"))

        # A pepper mixed into the license-key hash (separate from jwt_secret, so rotating one doesn't invalidate the other)
        self.key_pepper = _require("LICENSE_KEY_PEPPER")

        # Where the website's Buy button sends people after Stripe Checkout, and where the app download lives
        self.site_url = os.environ.get("SITE_URL", "http://localhost:8000")
        self.download_url = os.environ.get("DOWNLOAD_URL", "")       # set once you have a Release asset URL (see SETUP.md)

        # Auto-update advisory: edit these three env vars in Render whenever you ship a new build - no redeploy needed,
        # every client sees it on its next phone-home. Leave LATEST_VERSION blank to disable the update check entirely.
        self.latest_version = os.environ.get("LATEST_VERSION", "")
        self.min_supported_version = os.environ.get("MIN_SUPPORTED_VERSION", "")   # clients older than this are refused (426)
        self.release_notes = os.environ.get("RELEASE_NOTES", "")

        # How many devices one license may be active on at once (self-serve deactivate frees a slot - see /v1/deactivate)
        self.max_activations = int(os.environ.get("MAX_ACTIVATIONS", "1"))


settings = Settings()


def gen_secret(nbytes=32):
    """For generating JWT_SIGNING_SECRET / LICENSE_KEY_PEPPER once at setup time: python -c "from app.config import gen_secret; print(gen_secret())" """
    return secrets.token_urlsafe(nbytes)
