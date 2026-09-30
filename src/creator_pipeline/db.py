"""SQLite storage. One file (data/creators.db) holds every layer of the pipeline.

Layers:
  import_batches, staging_rows      raw, append-only, never edited
  accounts, account_sources         normalised platform accounts + lineage back to raw rows
  stat_snapshots                    append-only, timestamped metrics per account and source
  dedupe_candidates                 pairs that may be the same creator, with a human decision
  creators, creator_accounts        creator (person/brand) = group of linked accounts
  youtube_*                         API resolutions, channel metadata, recent videos
  api_calls                         quota ledger
The schema mirrors what would later live in Postgres.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_batches (
    batch_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name     TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    file_sha256   TEXT NOT NULL UNIQUE,
    platform_hint TEXT,
    row_count     INTEGER,
    columns_json  TEXT,
    ingested_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_rows (
    row_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id   INTEGER NOT NULL REFERENCES import_batches(batch_id),
    row_number INTEGER NOT NULL,
    raw_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS row_issues (
    row_id   INTEGER NOT NULL,
    severity TEXT NOT NULL,          -- 'rejected' | 'warning'
    issue    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    account_id        TEXT PRIMARY KEY,   -- '<platform>:<channel id or lowercase handle>'
    platform          TEXT NOT NULL,
    platform_key      TEXT NOT NULL,
    handle            TEXT,
    channel_id        TEXT,
    display_name_raw  TEXT,
    name_clean        TEXT,
    name_key          TEXT,
    handle_core       TEXT,
    profile_url       TEXT,
    followers         INTEGER,
    er_pct            REAL,
    potential_reach   INTEGER,
    avg_views         REAL,
    stats_source      TEXT,               -- source of the latest snapshot
    stats_as_of       TEXT,               -- fetched_at of the latest snapshot
    country           TEXT,
    city              TEXT,
    state             TEXT,
    topics_json       TEXT,
    categories_json   TEXT,
    tags_json         TEXT,
    entity_type       TEXT,
    entity_reason     TEXT,
    region            TEXT,
    city_tier         TEXT,
    age               INTEGER,
    gender            TEXT,
    languages_json    TEXT,
    rate_reel_inr     INTEGER,
    rate_story_inr    INTEGER,
    rate_video_inr    INTEGER,
    brands_json       TEXT,
    flags_json        TEXT,
    n_source_rows     INTEGER,
    updated_at        TEXT
);
CREATE TABLE IF NOT EXISTS account_sources (
    account_id TEXT NOT NULL,
    row_id     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stat_snapshots (
    snapshot_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    source        TEXT NOT NULL,          -- 'csv_import' | 'youtube_api' | ...
    followers     INTEGER,
    er_pct        REAL,
    avg_views     REAL,
    avg_likes     REAL,
    avg_comments  REAL,
    total_views   INTEGER,
    media_count   INTEGER,
    staging_row_id INTEGER,
    raw_json      TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_account ON stat_snapshots(account_id, fetched_at);
CREATE TABLE IF NOT EXISTS dedupe_candidates (
    pair_id     TEXT PRIMARY KEY,         -- '<account_a>|<account_b>' sorted
    account_a   TEXT NOT NULL,
    account_b   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    score       REAL NOT NULL,
    reasons_json TEXT,
    status      TEXT NOT NULL,            -- auto_linked | pending | linked | rejected
    decided_by  TEXT,
    decided_at  TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creators (
    creator_id         TEXT PRIMARY KEY,
    display_name       TEXT,
    entity_type        TEXT,
    primary_account_id TEXT,
    platforms_json     TEXT,
    n_accounts         INTEGER,
    total_followers    INTEGER,
    categories_json    TEXT,
    updated_at         TEXT
);
CREATE TABLE IF NOT EXISTS creator_accounts (
    creator_id TEXT NOT NULL,
    account_id TEXT NOT NULL PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS youtube_resolutions (
    input_key   TEXT PRIMARY KEY,         -- 'handle:<h>' | 'username:<u>'
    channel_id  TEXT,
    status      TEXT NOT NULL,            -- 'resolved' | 'not_found'
    resolved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id       TEXT PRIMARY KEY,
    title            TEXT,
    description      TEXT,
    custom_url       TEXT,
    country          TEXT,
    published_at     TEXT,
    thumbnail_url    TEXT,
    uploads_playlist TEXT,
    topic_categories_json TEXT,
    keywords         TEXT,
    subscribers_hidden INTEGER,
    fetched_at       TEXT
);
CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id     TEXT PRIMARY KEY,
    channel_id   TEXT NOT NULL,
    title        TEXT,
    published_at TEXT,
    duration     TEXT,
    views        INTEGER,
    likes        INTEGER,
    comments     INTEGER,
    fetched_at   TEXT
);
CREATE TABLE IF NOT EXISTS api_calls (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at TEXT NOT NULL,
    api       TEXT NOT NULL,
    endpoint  TEXT NOT NULL,
    units     INTEGER NOT NULL,
    ok        INTEGER NOT NULL,
    note      TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Columns added after the first version: added in place to existing databases.
MIGRATIONS = {"accounts": {"region": "TEXT", "city_tier": "TEXT", "age": "INTEGER", "gender": "TEXT",
                           "languages_json": "TEXT", "rate_reel_inr": "INTEGER", "rate_story_inr": "INTEGER",
                           "rate_video_inr": "INTEGER", "brands_json": "TEXT"}}


def connect(path=None) -> sqlite3.Connection:
    """Open (and create/migrate) a creator database. Default: the shared DB_PATH; the SaaS passes a per-company file."""
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(s, default=None):
    if s in (None, ""):
        return default if default is not None else []
    return json.loads(s)
