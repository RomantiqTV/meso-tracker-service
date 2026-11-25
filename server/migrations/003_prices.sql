-- The shared market price list (see app/prices.py): ONE row, replaced as a whole by the hourly push from the operator's PC and served to
-- licensed apps by GET /v1/prices. items = a compact list of {name, category, price, npc_buy, npc_sell, sold}.
CREATE TABLE price_snapshot (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    generated_at  TIMESTAMPTZ NOT NULL,          -- when the source list was scraped (not when it was received)
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    item_count    INTEGER NOT NULL,
    items         JSONB NOT NULL
);
