"""Stripe integration. Stripe holds every card number and handles PCI compliance - this server never sees a card number, only
webhook events telling it what happened. Signature verification (stripe.Webhook.construct_event) is what stops anyone but Stripe
from forging a "payment succeeded" event against this endpoint."""
import logging

import stripe

from . import email, repo, security

log = logging.getLogger("meso.billing")

# The stripe-python 11.3.0 SDK defaults to an API version that predates "Managed Payments" (now required on new
# accounts for Checkout Sessions). Pin a version that supports it rather than relying on the SDK's bundled default.
stripe.api_version = "2025-03-31.basil"


def create_checkout_session(settings, customer_email=None):
    stripe.api_key = settings.stripe_secret_key
    kwargs = dict(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.site_url}/success.html?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.site_url}/cancel.html",
        allow_promotion_codes=True,
    )
    if customer_email:
        kwargs["customer_email"] = customer_email
    else:
        kwargs["customer_creation"] = "always"
    session = stripe.checkout.Session.create(**kwargs)
    return session.url


def create_billing_portal_session(settings, stripe_customer_id):
    stripe.api_key = settings.stripe_secret_key
    session = stripe.billing_portal.Session.create(customer=stripe_customer_id, return_url=settings.site_url)
    return session.url


def verify_and_parse(settings, payload, sig_header):
    """Raises stripe.error.SignatureVerificationError if `payload`/`sig_header` weren't really sent by Stripe."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def handle_event(settings, conn, event):
    """Mutates the DB for the handful of event types we care about; returns a short description for logging."""
    cur = conn.cursor()
    t = event["type"]
    obj = event["data"]["object"]

    if t == "checkout.session.completed":
        customer_email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
        stripe_customer_id = obj.get("customer")
        if not customer_email or not stripe_customer_id:
            return "checkout.session.completed: missing email/customer, skipped"
        customer = repo.create_customer(cur, customer_email.strip().lower(), stripe_customer_id)
        sub_id = obj.get("subscription")
        if sub_id:
            stripe.api_key = settings.stripe_secret_key
            sub = stripe.Subscription.retrieve(sub_id)
            repo.upsert_subscription(cur, customer["id"], sub.id, sub.status, _period_end(sub))
        raw_key = security.generate_license_key()
        lic = repo.create_license(cur, customer["id"], security.hash_key(raw_key, settings.key_pepper),
                                   security.key_hint(raw_key), settings.max_activations)
        conn.commit()
        email.send_welcome(settings, customer_email, raw_key, settings.download_url)
        return f"issued license {lic['id']} to {customer_email}"

    if t in ("customer.subscription.updated", "customer.subscription.created"):
        customer = repo.get_customer_by_stripe_id(cur, obj["customer"])
        if customer:
            repo.upsert_subscription(cur, customer["id"], obj["id"], obj["status"], _period_end(obj))
            conn.commit()
        return f"subscription {obj['id']} -> {obj['status']}"

    if t == "customer.subscription.deleted":
        customer = repo.get_customer_by_stripe_id(cur, obj["customer"])
        if customer:
            repo.upsert_subscription(cur, customer["id"], obj["id"], "canceled", _period_end(obj))
            conn.commit()
        return f"subscription {obj['id']} canceled"

    if t == "invoice.payment_failed":
        customer = repo.get_customer_by_stripe_id(cur, obj["customer"])
        if customer:
            try:
                email.send_payment_failed(settings, customer["email"])
            except Exception:
                log.exception("payment-failed email did not send")
        return "payment_failed notified"

    return f"ignored {t}"


def _period_end(sub):
    """sub: a Subscription (dict from a webhook, or a stripe.Subscription object from .retrieve()). Recent Stripe API
    versions (this app pins 2025-03-31.basil) moved current_period_end off the Subscription itself and onto each
    subscription item, so the top-level field is normally absent now - fall back to the first item's."""
    import datetime
    ts = sub.get("current_period_end") if isinstance(sub, dict) else getattr(sub, "current_period_end", None)
    if not ts:
        items = sub.get("items") if isinstance(sub, dict) else getattr(sub, "items", None)
        data = (items.get("data") if isinstance(items, dict) else getattr(items, "data", None)) or []
        if data:
            first = data[0]
            ts = first.get("current_period_end") if isinstance(first, dict) else getattr(first, "current_period_end", None)
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc) if ts else None
