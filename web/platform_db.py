"""Platform database: accounts, companies, sessions, campaigns, tracking, billing.

Creator data is NOT here - each company gets its own private creator DB (data/orgs/org_<id>/creators.db,
or Postgres schema org_<id> when DATABASE_URL is set), so one client's rate cards and notes can never leak
into another client's workspace.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from creator_pipeline import db as creator_db, postgres
from creator_pipeline.config import DATABASE_URL, ORGS_DIR, PLATFORM_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    pw_hash     TEXT NOT NULL,
    pw_salt     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_login  TEXT
);
CREATE TABLE IF NOT EXISTS orgs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    industry      TEXT,
    size          TEXT,
    gstin         TEXT,
    billing_email TEXT,
    address       TEXT,
    fee_per_creator INTEGER,          -- NULL = platform default
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id   INTEGER NOT NULL REFERENCES users(id),
    org_id    INTEGER NOT NULL REFERENCES orgs(id),
    role      TEXT NOT NULL,          -- owner | admin | member (permissions)
    job_title TEXT,                   -- what the person does (Brand manager, Founder...)
    PRIMARY KEY (user_id, org_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    org_id     INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL,
    name        TEXT NOT NULL,
    brand       TEXT,
    product     TEXT,
    objective   TEXT,
    deliverable TEXT,
    budget      REAL,
    brief_json  TEXT,
    scope_json  TEXT,                 -- which of the company's imports the campaign drew from
    status      TEXT NOT NULL,        -- draft | active | completed | cancelled
    start_date  TEXT,
    end_date    TEXT,
    created_by  INTEGER,
    created_at  TEXT NOT NULL,
    launched_at TEXT,
    closed_at   TEXT
);
CREATE TABLE IF NOT EXISTS campaign_creators (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    creator_id  TEXT NOT NULL,
    name        TEXT, handle TEXT, platform TEXT, profile_url TEXT, city TEXT, niche TEXT,
    followers   INTEGER, er REAL, est_views REAL, fit REAL, reasons_json TEXT,
    quoted_fee  REAL,                 -- rate card at the time it was added
    agreed_fee  REAL,                 -- what was actually negotiated
    status      TEXT NOT NULL,        -- shortlisted | contacted | negotiating | confirmed | submitted | live | completed | dropped
    due_date    TEXT,
    post_url    TEXT,
    notes       TEXT,
    billed      INTEGER NOT NULL DEFAULT 0,
    added_at    TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (campaign_id, creator_id)
);
CREATE TABLE IF NOT EXISTS post_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cc_id       INTEGER NOT NULL REFERENCES campaign_creators(id),
    recorded_at TEXT NOT NULL,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER,
    source      TEXT NOT NULL,        -- manual | youtube_api
    recorded_by INTEGER
);
CREATE TABLE IF NOT EXISTS invoices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL,
    campaign_id INTEGER,
    number      TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL,        -- issued | paid | void
    issued_at   TEXT NOT NULL,
    due_at      TEXT,
    paid_at     TEXT,
    subtotal    REAL NOT NULL,
    tax_rate    REAL NOT NULL,
    tax         REAL NOT NULL,
    total       REAL NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'INR',
    bill_to_json TEXT
);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id),
    description TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    unit_price  REAL NOT NULL,
    amount      REAL NOT NULL,
    detail_json TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id),
    amount      REAL NOT NULL,
    method      TEXT NOT NULL,        -- test | razorpay | bank_transfer
    reference   TEXT,
    paid_at     TEXT NOT NULL,
    paid_by     INTEGER
);
CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL,
    campaign_id INTEGER,
    user_id     INTEGER,
    at          TEXT NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cc_campaign ON campaign_creators(campaign_id);
CREATE INDEX IF NOT EXISTS ix_pm_cc ON post_metrics(cc_id, recorded_at);
CREATE INDEX IF NOT EXISTS ix_act_org ON activity(org_id, at);
"""

PIPELINE = ["shortlisted", "contacted", "negotiating", "confirmed", "submitted", "live", "completed"]
STATUS_LABEL = {"shortlisted": "Shortlisted", "contacted": "Contacted", "negotiating": "Negotiating",
                "confirmed": "Confirmed", "submitted": "Content submitted", "live": "Live",
                "completed": "Completed", "dropped": "Dropped"}
COMMITTED = {"confirmed", "submitted", "live", "completed"}   # creators we're paying


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect():
    if DATABASE_URL:
        return postgres.connect(DATABASE_URL, "platform", SCHEMA)
    PLATFORM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(PLATFORM_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def org_db_path(org_id: int):
    return ORGS_DIR / f"org_{int(org_id)}" / "creators.db"


def org_connect(org_id: int):
    """The company's private creator database: its own SQLite file, or its own Postgres schema."""
    if DATABASE_URL:
        return creator_db.connect(schema=f"org_{int(org_id)}")
    return creator_db.connect(org_db_path(org_id))


def org_upload_dir(org_id: int):
    return ORGS_DIR / f"org_{int(org_id)}" / "uploads"


def log(conn, org_id: int, text: str, user_id: int | None = None, campaign_id: int | None = None):
    conn.execute("INSERT INTO activity (org_id, campaign_id, user_id, at, text) VALUES (?,?,?,?,?)",
                 (org_id, campaign_id, user_id, now_iso(), text))


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def loads(s, default=None):
    if not s:
        return default
    return json.loads(s)
