"""Free trial without a card. A trial is a normal customer + licence + a subscriptions row (status 'trialing', synthetic id 'trial_<id>'), so the existing licence checks need no special case;
only the END is new: repo.LIVE_SUB counts a trialing row only while its current_period_end is in the future.

Flow: website form -> POST /v1/trial (email) -> the licence key is EMAILED (that is the email verification: no mailbox, no key) -> the customer enters it in the app -> the first activation
starts the TRIAL_DAYS clock. Paying later (Stripe checkout, same email) keeps the same licence key (see billing.handle_event).

Abuse limits, all server-side: one trial per mailbox (email_canon: +tags and gmail dots ignored), one per PC (trial_devices, the app's hwid), a few sign-ups per IP per day, throwaway-mail
domains refused. None of this stops a determined person with many mailboxes AND many PCs; it stops the casual repeat. The session token and offline grace given to a trial are capped to
the time it has left (session_limits), so a copy that never reaches the server still stops on time.
"""
import datetime

from . import repo, security

DISPOSABLE = {"mailinator.com", "guerrillamail.com", "guerrillamail.net", "sharklasers.com", "10minutemail.com", "tempmail.com", "temp-mail.org", "yopmail.com", "trashmail.com", "getnada.com",
              "dispostable.com", "maildrop.cc", "throwawaymail.com", "fakeinbox.com", "mintemail.com", "mailnesia.com", "tempmailo.com", "emailondeck.com", "mohmal.com", "moakt.com"}


class TrialError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def canon_email(email):
    """One key per real mailbox: lower-case, drop a +tag, and for gmail ignore dots (a.b@gmail.com == ab@gmail.com)."""
    e = (email or "").strip().lower()
    local, _, domain = e.rpartition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def sign_up(settings, cur, email, ip):
    """Creates the customer, trial and licence rows (NOT committed). -> the raw licence key, to be emailed by the caller, who commits only once the mail is sent."""
    if not settings.trial_enabled:
        raise TrialError(503, "Free trials are not available right now")
    email = email.strip().lower()
    domain = email.rpartition("@")[2]
    if domain in DISPOSABLE:
        raise TrialError(400, "Please use a real email address - the licence key is sent there")
    canon = canon_email(email)
    if repo.get_customer_by_email(cur, email) or repo.get_trial_by_canon(cur, canon):
        raise TrialError(409, "That email has already had a free trial or has an account. Subscribe below to keep using Meso Tracker.")
    if repo.count_trials_from_ip(cur, ip, 24) >= settings.trial_per_ip_per_day:
        raise TrialError(429, "Too many free trials started from this network today. Try again tomorrow.")
    customer = repo.create_customer(cur, email, None)
    repo.create_trial(cur, customer["id"], canon, ip)
    raw_key = security.generate_license_key()
    repo.create_license(cur, customer["id"], security.hash_key(raw_key, settings.key_pepper), security.key_hint(raw_key), settings.max_activations)
    return raw_key


def on_bind(settings, cur, customer_id, hwid):
    """Called when a licence binds to a PC (first activation, or after "Deactivate this device"). For a trial customer: refuse a PC that already ran another trial, remember this PC, and
    on the very first activation start the clock. No-op for everyone else."""
    t = repo.get_trial(cur, customer_id)
    if not t or t["status"] != "trialing":
        return
    owner = repo.trial_device_owner(cur, hwid)
    if owner is not None and str(owner) != str(t["id"]):
        raise TrialError(403, "This PC has already used a free trial. Subscribe at %s/#pricing to keep using Meso Tracker." % settings.site_url)
    repo.add_trial_device(cur, hwid, t["id"])
    if t["started_at"] is None:
        repo.start_trial(cur, t["id"], settings.trial_days)


def ended_message(settings):
    return "Your free trial has ended. Subscribe at %s/#pricing to keep using Meso Tracker - your licence key stays the same." % settings.site_url


def session_limits(settings, cur, customer_id, now=None):
    """-> (session_ttl_hours, offline_grace_hours). Normal customers get the configured values; a running trial is capped to the time it has left, so neither a cached session nor
    the offline grace can carry a copy past the end."""
    ttl, grace = settings.session_ttl_hours, settings.offline_grace_hours
    t = repo.get_trial(cur, customer_id)
    if t and t["status"] == "trialing" and t["ends_at"]:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        left_h = max(0.0, (t["ends_at"] - now).total_seconds() / 3600.0)
        ttl, grace = max(min(ttl, left_h), 1 / 60), min(grace, left_h)
    return ttl, grace
