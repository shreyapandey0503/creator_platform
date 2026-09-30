"""Step 2: clean staging rows into one record per platform account (rebuilds from staging)."""
import _bootstrap  # noqa: F401
from creator_pipeline import normalise
from creator_pipeline.db import session

with session() as conn:
    stats = normalise.run(conn)
    for k, v in stats.items():
        print(f"{k:<32} {v}")
    print("\nTop data-quality flags:")
    for r in conn.execute("SELECT issue, COUNT(*) n FROM row_issues GROUP BY issue ORDER BY n DESC"):
        print(f"  {r['issue']:<34} {r['n']}")
