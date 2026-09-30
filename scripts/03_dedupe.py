"""Step 3: find accounts that belong to the same creator; auto-link safe ones, queue the rest."""
import _bootstrap  # noqa: F401
from creator_pipeline import dedupe
from creator_pipeline.db import session

with session() as conn:
    for k, v in dedupe.run(conn).items():
        print(f"{k:<28} {v}")
    print("\nLinked / queued pairs:")
    for r in conn.execute("""
        SELECT d.status, d.score, a.name_clean na, a.platform pa, b.name_clean nb, b.platform pb
        FROM dedupe_candidates d JOIN accounts a ON a.account_id=d.account_a JOIN accounts b ON b.account_id=d.account_b
        ORDER BY d.status, d.score DESC"""):
        print(f"  {r['status']:<12} {r['score']:.2f}  {r['na']} ({r['pa']})  <->  {r['nb']} ({r['pb']})")
