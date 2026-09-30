"""Step 5: export every layer to CSV under data/ (staging, processed, review, enriched)."""
import _bootstrap  # noqa: F401
from creator_pipeline import export
from creator_pipeline.db import session

with session() as conn:
    for path, n in export.run(conn).items():
        print(f"{path:<40} {n} rows")
