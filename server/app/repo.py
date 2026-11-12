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


def has_active_subscription(cur, customer_id):
    cur.execute(
        "SELECT 1 FROM subscriptions WHERE customer_id = %s AND status IN ('active', 'trialing') LIMIT 1",
        (customer_id,),
    )
    return cur.fetchone() is not None


def get_subscription_for_customer(cur, customer_id):
    """The subscription to show in the app's account info: prefers an active/trialing one, else the most recently
    updated row (so a just-canceled subscription still reports its real current_period_end instead of nothing)."""
    cur.execute(
        "SELECT * FROM subscriptions WHERE customer_id = %s ORDER BY (status IN ('active', 'trialing')) DESC, "
        "updated_at DESC LIMIT 1",
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
