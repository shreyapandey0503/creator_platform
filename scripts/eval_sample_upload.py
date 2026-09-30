"""Check the pipeline against the synthetic upload's ground truth, on a throwaway COPY of the database.

    python scripts/make_sample_upload.py && python scripts/eval_sample_upload.py
"""
import csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tmp = Path(tempfile.mkdtemp()) / "eval.db"
shutil.copy(ROOT / "data" / "creators.db", tmp)
os.environ["DB_PATH"] = str(tmp)  # must be set before config is imported
sys.path.insert(0, str(ROOT / "src"))

from creator_pipeline import dedupe, ingest, normalise  # noqa: E402
from creator_pipeline.db import session  # noqa: E402

sample = ROOT / "data" / "samples" / "SYNTHETIC_agency_upload.csv"
truth = list(csv.DictReader(open(sample.with_name("SYNTHETIC_agency_upload_truth.csv"), encoding="utf-8")))

with session() as conn:
    batch = ingest.ingest_bytes(conn, sample.read_bytes(), sample.name, stored_path=str(sample))["batch_id"]
    print("normalise:", normalise.run(conn))
    print("dedupe:   ", dedupe.run(conn))
    got = dict(conn.execute("SELECT s.row_number, a.account_id FROM staging_rows s LEFT JOIN account_sources a"
                            " USING (row_id) WHERE s.batch_id = ?", (batch,)).fetchall())
    why = dict(conn.execute("SELECT s.row_number, i.issue FROM row_issues i JOIN staging_rows s USING (row_id)"
                            " WHERE s.batch_id = ? AND i.severity = 'rejected'", (batch,)).fetchall())

correct = 0
for t in truth:
    n, expected = int(t["row_number"]), t["expected_account_id"] or None
    if got.get(n) == expected:
        correct += 1
    else:
        print(f"  row {n}: expected {expected}, got {got.get(n)} ({why.get(n)}) - {t['mess']}")
print(f"\n{correct}/{len(truth)} rows mapped to the correct account (or correctly rejected)")
shutil.rmtree(tmp.parent, ignore_errors=True)
