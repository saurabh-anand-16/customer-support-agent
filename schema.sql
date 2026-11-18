-- schema.sql : the database layout (SQLite). Run by scripts/04_build_db.py.
-- Dates are stored as ISO text 'YYYY-MM-DD' (SQLite has no date type; ISO text sorts correctly).

PRAGMA foreign_keys = ON;

-- One row of settings. 'today' is fixed, so every answer is reproducible.
CREATE TABLE config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- What each policy type allows. Transcribed from the policy pages.
CREATE TABLE return_rules (
    policy_code               TEXT PRIMARY KEY,
    policy_label              TEXT NOT NULL,
    window_days               INTEGER NOT NULL,      -- 0 = no change-of-mind return
    defect_report_window_days INTEGER NOT NULL,
    buyer_remorse_return      INTEGER NOT NULL CHECK (buyer_remorse_return IN (0,1)),
    exchange_size_colour      INTEGER NOT NULL CHECK (exchange_size_colour IN (0,1)),
    resolution_damaged_wrong  TEXT NOT NULL,
    resolution_defective      TEXT NOT NULL,
    -- machine-readable resolutions, '|' separated: refund | replacement | exchange | brand_service
    -- ('brand_service' = guidance only, no return record). 'none' = not allowed by the policy.
    resolutions_damaged_wrong TEXT NOT NULL,
    resolutions_defective     TEXT NOT NULL,
    resolutions_changed_mind  TEXT NOT NULL,
    source_file               TEXT NOT NULL
);

-- Our INFERRED mapping of each category path to a policy type (review it).
CREATE TABLE category_policy_map (
    category_path TEXT PRIMARY KEY,
    n_products    INTEGER NOT NULL,
    policy_code   TEXT NOT NULL REFERENCES return_rules(policy_code),
    confidence    TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
    rule_id       TEXT NOT NULL,
    basis         TEXT NOT NULL
);

CREATE TABLE products (
    product_id                TEXT PRIMARY KEY,
    product_name              TEXT NOT NULL,
    category_path             TEXT NOT NULL REFERENCES category_policy_map(category_path),
    category_top              TEXT NOT NULL,
    category_leaf             TEXT NOT NULL,
    discounted_price_inr      REAL NOT NULL CHECK (discounted_price_inr > 0),
    actual_price_inr          REAL NOT NULL,
    discount_pct              REAL,
    rating                    REAL,                   -- NULL for the one product with a bad value
    rating_count              INTEGER,
    about_product             TEXT,
    img_link                  TEXT,
    product_link              TEXT,
    policy_code               TEXT NOT NULL REFERENCES return_rules(policy_code),
    window_days               INTEGER NOT NULL,       -- copied from return_rules for convenience
    defect_report_window_days INTEGER NOT NULL
);

-- SYNTHETIC customers.
CREATE TABLE customers (
    customer_id            TEXT PRIMARY KEY,
    account_created_at     TEXT NOT NULL,
    account_standing       TEXT NOT NULL CHECK (account_standing IN ('good','restricted')),
    returns_last_12_months INTEGER NOT NULL
);

-- SYNTHETIC orders. fulfilled_by is always 'Amazon' in this scope (seller-fulfilled is out of scope).
CREATE TABLE orders (
    order_id        TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    ordered_at      TEXT NOT NULL,
    payment_type    TEXT NOT NULL CHECK (payment_type IN ('prepaid','pay_on_delivery')),
    payment_method  TEXT NOT NULL,
    is_emi          INTEGER NOT NULL CHECK (is_emi IN (0,1)),
    fulfilled_by    TEXT NOT NULL CHECK (fulfilled_by = 'Amazon'),
    order_total_inr REAL NOT NULL
);

-- One row per product line. delivered_at is NULL until the item is delivered.
-- test_scenario is for TESTS ONLY (how the date was generated); the agent must never read it.
CREATE TABLE order_items (
    item_id              TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL REFERENCES orders(order_id),
    product_id           TEXT NOT NULL REFERENCES products(product_id),
    quantity             INTEGER NOT NULL CHECK (quantity >= 1),
    unit_price_paid_inr  REAL NOT NULL,
    line_total_inr       REAL NOT NULL,
    item_status          TEXT NOT NULL CHECK (item_status IN ('delivered','shipped','processing','cancelled')),
    delivered_at         TEXT,
    expected_delivery_at TEXT,
    cancelled_at         TEXT,
    test_scenario        TEXT
);

-- Returns that already exist. The agent writes new rows here.
CREATE TABLE returns (
    return_id            TEXT PRIMARY KEY,
    item_id              TEXT NOT NULL REFERENCES order_items(item_id),
    requested_at         TEXT NOT NULL,
    reason_code          TEXT NOT NULL CHECK (reason_code IN
                           ('damaged','defective','wrong_item','not_as_described','changed_mind')),
    resolution_requested TEXT NOT NULL CHECK (resolution_requested IN ('refund','replacement','exchange')),
    return_status        TEXT NOT NULL,
    refund_method        TEXT,
    refund_amount_inr    REAL
);
-- One return request per item: the database itself refuses a second one.
CREATE UNIQUE INDEX ux_returns_item ON returns(item_id);

CREATE TABLE refund_timelines (
    order_type     TEXT NOT NULL CHECK (order_type IN ('prepaid','pay_on_delivery')),
    refund_method  TEXT NOT NULL,
    time_value     INTEGER NOT NULL,
    time_unit      TEXT NOT NULL,           -- hours / business_days / working_days, as written by Amazon
    is_upper_bound INTEGER NOT NULL,        -- 1 when the page says "up to"
    source_text    TEXT NOT NULL,
    source_file    TEXT NOT NULL,
    PRIMARY KEY (order_type, refund_method)
);

CREATE TABLE policy_facts (
    fact_key    TEXT PRIMARY KEY,
    fact_value  TEXT,
    unit        TEXT,
    source_file TEXT NOT NULL,
    note        TEXT
);

-- The window arithmetic, in one place. This is the reference answer the agent's code
-- must agree with. Delivery day = day 1, so day_number = days since delivery + 1.
CREATE VIEW v_item_return_window AS
SELECT
    oi.item_id,
    oi.order_id,
    o.customer_id,
    oi.product_id,
    p.policy_code,
    p.window_days,
    p.defect_report_window_days,
    oi.item_status,
    oi.delivered_at,
    CASE WHEN oi.delivered_at IS NULL THEN NULL
         ELSE CAST(julianday(c.value) - julianday(oi.delivered_at) AS INTEGER) + 1 END AS day_number
FROM order_items oi
JOIN orders   o ON o.order_id   = oi.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN config   c ON c.key = 'today';

CREATE VIEW v_item_eligibility AS
SELECT
    v.*,
    CASE WHEN day_number IS NULL THEN NULL ELSE window_days - day_number END AS days_left_to_return,
    CASE WHEN day_number IS NULL THEN 0
         WHEN window_days > 0 AND day_number <= window_days THEN 1 ELSE 0 END AS in_return_window,
    CASE WHEN day_number IS NULL THEN 0
         WHEN day_number <= defect_report_window_days THEN 1 ELSE 0 END AS in_defect_window
FROM v_item_return_window v;

-- Phase 5a: the review queue. One row per case a person must look at. It has no foreign keys on purpose: the queue
-- never changes orders or return requests, and a case must still be stored if the item it names is gone.
-- agent/review_queue.py reads the block between the two markers below to create the table in a database that was
-- built before this phase, so the text is written once, here.
-- review_items:begin
CREATE TABLE IF NOT EXISTS review_items (
    id            TEXT PRIMARY KEY,                 -- the reference the customer sees, e.g. REV-0001
    created_at    TEXT NOT NULL,                    -- ISO time, UTC
    customer_id   TEXT NOT NULL,                    -- stored as data; never in a model prompt or tool schema
    order_item_id TEXT,                             -- the item the case is about; NULL when there is none
    kind          TEXT NOT NULL,                    -- why it was sent (the kinds are the keys of [review.reasons] in config/agent.toml)
    reason        TEXT NOT NULL,                    -- one plain sentence written by code from the tool result
    excerpt       TEXT,                             -- JSON list of the last messages: {"role": customer|agent, "text"}
    eligibility   TEXT,                             -- JSON of the eligibility result, when one exists
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','declined')),   -- 5a writes only 'open'
    decision_note TEXT,                             -- empty in 5a (phase 5b)
    decided_at    TEXT,                             -- empty in 5a (phase 5b)
    decided_by    TEXT                              -- empty in 5a (phase 5b)
);
CREATE INDEX IF NOT EXISTS ix_review_items_case ON review_items(customer_id, order_item_id, kind, status);
-- review_items:end
