-- Free trial without a card (see app/trials.py). A trial is an ordinary customer + licence + a subscriptions row with status 'trialing' and a synthetic id ('trial_<trial id>'),
-- so every existing "may this licence run" query keeps working. The 5 days start at the first activation (current_period_end is NULL until then), not at sign-up.

CREATE TABLE trials (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID NOT NULL UNIQUE REFERENCES customers(id) ON DELETE CASCADE,
    email_canon   TEXT NOT NULL UNIQUE,         -- lower-cased, +tag removed, gmail dots removed: one trial per real mailbox
    ip            TEXT,
    started_at    TIMESTAMPTZ,                  -- NULL = key issued but the app has not been opened yet
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_trials_ip ON trials(ip, created_at DESC);

-- Every PC (hwid) that has ever run a trial: a second trial licence on the same PC is refused.
CREATE TABLE trial_devices (
    hwid        TEXT PRIMARY KEY,
    trial_id    UUID NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now()
);
