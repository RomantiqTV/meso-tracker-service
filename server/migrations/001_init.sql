-- Core schema. No plaintext secrets are ever stored: license keys are kept only as an HMAC, never the raw value
-- (same principle as a password hash - this table being read does not let anyone log in as a customer).

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE customers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               CITEXT UNIQUE NOT NULL,
    stripe_customer_id  TEXT UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id             UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    stripe_subscription_id  TEXT UNIQUE NOT NULL,
    status                  TEXT NOT NULL,              -- mirrors Stripe: active | trialing | past_due | canceled | unpaid ...
    current_period_end      TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_subscriptions_customer ON subscriptions(customer_id);

CREATE TABLE licenses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id         UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    key_hash            TEXT UNIQUE NOT NULL,            -- HMAC-SHA256(pepper, raw key) - the raw key is shown ONCE, by email, never stored
    key_hint            TEXT NOT NULL,                   -- last 4 chars, plaintext, just so a human can confirm "...WXYZ" in support chat
    hwid                TEXT,                             -- bound on first activation; NULL = not yet activated on any device
    max_activations     INT NOT NULL DEFAULT 1,
    revoked_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_licenses_customer ON licenses(customer_id);

CREATE TABLE activation_log (
    id          BIGSERIAL PRIMARY KEY,
    license_id  UUID NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,                           -- activate | reactivate | deactivate | denied_hwid_mismatch | denied_inactive_sub
    hwid        TEXT,
    ip          TEXT,
    app_version TEXT,
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_activation_log_license ON activation_log(license_id, at DESC);
