"""Every SQL statement the server runs, in one place, all parameterized (no string-built SQL anywhere, so request data can never
be interpreted as SQL)."""


def get_customer_by_email(cur, email):
    cur.execute("SELECT * FROM customers WHERE email = %s", (email,))
    return cur.fetchone()


def get_customer_by_stripe_id(cur, stripe_customer_id):
    cur.execute("SELECT * FROM customers WHERE stripe_customer_id = %s", (stripe_customer_id,))
    return cur.fetchone()


def create_customer(cur, email, stripe_customer_id):
    cur.execute(
        "INSERT INTO customers (email, stripe_customer_id) VALUES (%s, %s) "
        "ON CONFLICT (email) DO UPDATE SET stripe_customer_id = EXCLUDED.stripe_customer_id RETURNING *",
        (email, stripe_customer_id),
    )
    return cur.fetchone()


def upsert_subscription(cur, customer_id, stripe_subscription_id, status, current_period_end):
    cur.execute(
        "INSERT INTO subscriptions (customer_id, stripe_subscription_id, status, current_period_end) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (stripe_subscription_id) DO UPDATE "
        "SET status = EXCLUDED.status, current_period_end = EXCLUDED.current_period_end, updated_at = now()",
        (customer_id, stripe_subscription_id, status, current_period_end),
    )


# "May this subscription run right now?" Paid: status active. Free trial: status trialing AND not past its end (NULL end = the 5 days have not started: the app has not been opened yet).
LIVE_SUB = "(s.status = 'active' OR (s.status = 'trialing' AND (s.current_period_end IS NULL OR s.current_period_end > now())))"


def get_current_userbase_emails(cur):
    """Distinct emails of every customer with a currently active or trialing subscription - the people actually
    running the app right now, as opposed to past/canceled customers who shouldn't be re-contacted."""
    cur.execute(
        "SELECT DISTINCT c.email FROM customers c JOIN subscriptions s ON s.customer_id = c.id "
        "WHERE " + LIVE_SUB + " ORDER BY c.email"
    )
    return [r["email"] for r in cur.fetchall()]


def has_active_subscription(cur, customer_id):
    cur.execute(
        "SELECT 1 FROM subscriptions s WHERE s.customer_id = %s AND " + LIVE_SUB + " LIMIT 1",
        (customer_id,),
    )
    return cur.fetchone() is not None


def get_subscription_for_customer(cur, customer_id):
    """The subscription to show in the app's account info: prefers an active/trialing one, else the most recently
    updated row (so a just-canceled subscription still reports its real current_period_end instead of nothing)."""
    cur.execute(
        "SELECT * FROM subscriptions s WHERE s.customer_id = %s ORDER BY " + LIVE_SUB + " DESC, "
        "s.updated_at DESC LIMIT 1",
        (customer_id,),
    )
    return cur.fetchone()


def create_license(cur, customer_id, key_hash, key_hint_, max_activations):
    cur.execute(
        "INSERT INTO licenses (customer_id, key_hash, key_hint, max_activations) VALUES (%s, %s, %s, %s) RETURNING *",
        (customer_id, key_hash, key_hint_, max_activations),
    )
    return cur.fetchone()


def get_license_by_key_hash(cur, email, key_hash):
    cur.execute(
        "SELECT l.* FROM licenses l JOIN customers c ON c.id = l.customer_id "
        "WHERE c.email = %s AND l.key_hash = %s AND l.revoked_at IS NULL",
        (email, key_hash),
    )
    return cur.fetchone()


def bind_hwid(cur, license_id, hwid):
    cur.execute("UPDATE licenses SET hwid = %s WHERE id = %s", (hwid, license_id))


def clear_hwid(cur, license_id):
    cur.execute("UPDATE licenses SET hwid = NULL WHERE id = %s", (license_id,))


def log_activation(cur, license_id, event, hwid, ip, app_version):
    cur.execute(
        "INSERT INTO activation_log (license_id, event, hwid, ip, app_version) VALUES (%s, %s, %s, %s, %s)",
        (license_id, event, hwid, ip, app_version),
    )


# ---------------------------------------------------------------------------------------------------------------------- free trial (no card; see trials.py)
def get_live_license_for_customer(cur, customer_id):
    cur.execute("SELECT * FROM licenses WHERE customer_id = %s AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1", (customer_id,))
    return cur.fetchone()


def get_trial_by_canon(cur, email_canon):
    cur.execute("SELECT * FROM trials WHERE email_canon = %s", (email_canon,))
    return cur.fetchone()


def count_trials_from_ip(cur, ip, hours=24):
    cur.execute("SELECT count(*) AS n FROM trials WHERE ip = %s AND created_at > now() - make_interval(hours => %s)", (ip, hours))
    return cur.fetchone()["n"]


def create_trial(cur, customer_id, email_canon, ip):
    """The trials row plus its subscriptions row (status trialing, no end yet)."""
    cur.execute("INSERT INTO trials (customer_id, email_canon, ip) VALUES (%s, %s, %s) RETURNING *", (customer_id, email_canon, ip))
    t = cur.fetchone()
    upsert_subscription(cur, customer_id, "trial_" + str(t["id"]), "trialing", None)
    return t


def get_trial(cur, customer_id):
    """-> {id, started_at, status, ends_at} or None. status is the trial subscription's: 'trialing' (running, or expired when ends_at is past) | 'converted' | 'canceled'."""
    cur.execute(
        "SELECT t.id, t.started_at, s.status, s.current_period_end AS ends_at FROM trials t "
        "JOIN subscriptions s ON s.stripe_subscription_id = 'trial_' || t.id::text WHERE t.customer_id = %s",
        (customer_id,),
    )
    return cur.fetchone()


def start_trial(cur, trial_id, days):
    """Starts the clock (first activation only). -> the trial's end timestamp."""
    cur.execute("UPDATE trials SET started_at = now() WHERE id = %s AND started_at IS NULL", (trial_id,))
    cur.execute(
        "UPDATE subscriptions SET current_period_end = now() + make_interval(days => %s), updated_at = now() "
        "WHERE stripe_subscription_id = 'trial_' || %s::text AND current_period_end IS NULL RETURNING current_period_end",
        (days, str(trial_id)),
    )
    row = cur.fetchone()
    return row["current_period_end"] if row else None


def trial_device_owner(cur, hwid):
    cur.execute("SELECT trial_id FROM trial_devices WHERE hwid = %s", (hwid,))
    row = cur.fetchone()
    return row["trial_id"] if row else None


def add_trial_device(cur, hwid, trial_id):
    cur.execute("INSERT INTO trial_devices (hwid, trial_id) VALUES (%s, %s) ON CONFLICT (hwid) DO NOTHING", (hwid, trial_id))


def convert_trial(cur, customer_id):
    """The customer paid: the trial's subscription row stops counting (their real Stripe subscription takes over)."""
    cur.execute(
        "UPDATE subscriptions SET status = 'converted', updated_at = now() "
        "WHERE customer_id = %s AND stripe_subscription_id LIKE 'trial%%' AND status = 'trialing'",
        (customer_id,),
    )
    return cur.rowcount


def put_prices(cur, generated_at, items):
    """Replaces the one stored market price list."""
    from psycopg.types.json import Jsonb
    cur.execute(
        "INSERT INTO price_snapshot (id, generated_at, received_at, item_count, items) VALUES (1, %s, now(), %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET generated_at = EXCLUDED.generated_at, received_at = now(), item_count = EXCLUDED.item_count, items = EXCLUDED.items",
        (generated_at, len(items), Jsonb(items)),
    )


def get_prices(cur):
    """-> {generated_at, received_at, item_count, items} or None when nothing was ever pushed."""
    cur.execute("SELECT generated_at, received_at, item_count, items FROM price_snapshot WHERE id = 1")
    return cur.fetchone()
