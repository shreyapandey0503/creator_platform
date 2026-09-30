"""Write the pipeline's layers out as CSVs (for Excel / sharing / sanity checks)."""
from __future__ import annotations

import pandas as pd

from .config import ENRICHED_DIR, PROCESSED_DIR, REVIEW_DIR, STAGING_DIR

QUERIES = {
    STAGING_DIR / "staging_rows.csv": """
        SELECT s.row_id, b.file_name, s.row_number, s.raw_json,
               (SELECT group_concat(issue, '; ') FROM row_issues i WHERE i.row_id = s.row_id) AS issues
        FROM staging_rows s JOIN import_batches b USING (batch_id) ORDER BY s.row_id""",
    PROCESSED_DIR / "accounts_clean.csv": """
        SELECT a.*, ca.creator_id FROM accounts a LEFT JOIN creator_accounts ca USING (account_id)
        ORDER BY platform, followers DESC""",
    PROCESSED_DIR / "creators.csv": """
        SELECT c.*, (SELECT group_concat(account_id, ' | ') FROM creator_accounts x
                     WHERE x.creator_id = c.creator_id) AS accounts
        FROM creators c ORDER BY total_followers DESC""",
    PROCESSED_DIR / "rejected_rows.csv": """
        SELECT i.row_id, i.issue, s.raw_json FROM row_issues i JOIN staging_rows s USING (row_id)
        WHERE i.severity = 'rejected'""",
    REVIEW_DIR / "dedupe_candidates.csv": """
        SELECT d.status, d.kind, d.score, a.name_clean AS name_a, d.account_a, b.name_clean AS name_b, d.account_b,
               d.reasons_json, d.decided_by, d.decided_at
        FROM dedupe_candidates d JOIN accounts a ON a.account_id = d.account_a
        JOIN accounts b ON b.account_id = d.account_b ORDER BY d.status, d.score DESC""",
    ENRICHED_DIR / "stat_snapshots.csv": "SELECT * FROM stat_snapshots ORDER BY account_id, fetched_at",
    ENRICHED_DIR / "youtube_channels.csv": "SELECT * FROM youtube_channels",
}


def run(conn) -> dict:
    out = {}
    for path, sql in QUERIES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.read_sql_query(sql, conn)
        df.to_csv(path, index=False, encoding="utf-8-sig")  # BOM so Excel shows Hindi/emoji correctly
        out[str(path.relative_to(path.parents[1]))] = len(df)
    return out
