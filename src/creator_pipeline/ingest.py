"""Step 1 - ingest: copy each file's rows, untouched, into staging.

Files are identified by SHA-256, so re-ingesting the same file is a no-op.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from .config import PLATFORMS, UPLOADS_DIR
from .db import dumps, now_iso


def guess_platform_from_filename(name: str) -> str | None:
    low = name.lower()
    for p in PLATFORMS:
        if p in low:
            return p
    if "yt" in low.split("_"):
        return "youtube"
    if "ig" in low.split("_") or "insta" in low:
        return "instagram"
    return None


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def ingest_bytes(conn, data: bytes, file_name: str, platform_hint: str | None = None,
                 stored_path: str | None = None, upload_dir: Path | None = None) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    existing = conn.execute("SELECT batch_id, row_count FROM import_batches WHERE file_sha256 = ?", (sha,)).fetchone()
    if existing:
        return {"batch_id": existing["batch_id"], "rows": existing["row_count"], "skipped": True,
                "reason": "identical file already ingested"}

    platform_hint = platform_hint or guess_platform_from_filename(file_name)
    reader = csv.DictReader(io.StringIO(_decode(data)))
    columns = [c for c in (reader.fieldnames or [])]
    rows = list(reader)

    if stored_path is None and getattr(conn, "is_postgres", False):
        # no persistent disk on serverless hosts: keep the untouched copy in the company's own schema
        conn.execute("INSERT INTO upload_files (file_sha256, file_name, data, stored_at) VALUES (?,?,?,?)"
                     " ON CONFLICT DO NOTHING", (sha, Path(file_name).name, data, now_iso()))
        stored_path = f"db:upload_files/{sha}"
    elif stored_path is None:
        upload_dir = upload_dir or UPLOADS_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{sha[:10]}_{Path(file_name).name}"
        dest.write_bytes(data)
        stored_path = str(dest)

    batch_id = conn.execute(
        "INSERT INTO import_batches (file_name, stored_path, file_sha256, platform_hint, row_count, columns_json, ingested_at)"
        " VALUES (?,?,?,?,?,?,?) RETURNING batch_id",
        (Path(file_name).name, stored_path, sha, platform_hint, len(rows), dumps(columns), now_iso()),
    ).fetchone()[0]
    conn.executemany(
        "INSERT INTO staging_rows (batch_id, row_number, raw_json) VALUES (?,?,?)",
        [(batch_id, i + 1, dumps({k: v for k, v in r.items() if k is not None})) for i, r in enumerate(rows)],
    )
    return {"batch_id": batch_id, "rows": len(rows), "skipped": False, "platform_hint": platform_hint,
            "columns": columns}


def ingest_file(conn, path: Path, platform_hint: str | None = None) -> dict:
    """Ingest a file in place (used for raw_data/, which we read but never modify)."""
    return ingest_bytes(conn, path.read_bytes(), path.name, platform_hint, stored_path=str(path))


def ingest_upload(conn, data: bytes, file_name: str, platform_hint: str | None = None,
                  upload_dir: Path | None = None) -> dict:
    """Ingest an uploaded file; an untouched copy is kept in upload_dir (default data/uploads/),
    or in the upload_files table on Postgres."""
    return ingest_bytes(conn, data, file_name, platform_hint, upload_dir=upload_dir)


def remove_batch(conn, batch_id: int):
    """Undo an import: drop its staging rows (the stored file itself is kept). Re-run normalise afterwards."""
    conn.execute("DELETE FROM row_issues WHERE row_id IN (SELECT row_id FROM staging_rows WHERE batch_id = ?)",
                 (batch_id,))
    conn.execute("DELETE FROM staging_rows WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM import_batches WHERE batch_id = ?", (batch_id,))


def reset_database(db_path: Path):
    """Delete the SQLite file (raw_data/ and uploads are not touched)."""
    if db_path.exists():
        db_path.unlink()


__all__ = ["ingest_file", "ingest_upload", "guess_platform_from_filename", "remove_batch", "reset_database"]
