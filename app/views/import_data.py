import io
import subprocess
import sys

import pandas as pd
import streamlit as st

from common import FLAG_HELP, ROOT, conn, js, q, rebuild
from creator_pipeline.config import DB_PATH, RAW_DIR
from creator_pipeline.ingest import ingest_file, ingest_upload, remove_batch
from creator_pipeline.normalise import map_columns

st.title("Import & clean")
st.caption("Upload any creator sheet. Columns are detected by name (e.g. 'Creator Name', 'Profile Link', "
           "'Followers', 'City'). The file is stored untouched; cleaning runs on a staging copy.")


def show_report(batch_id: int):
    b = q("SELECT * FROM import_batches WHERE batch_id = ?", (batch_id,))
    if b.empty:
        return
    b = b.iloc[0]
    rows = int(b.row_count)
    rej = q("""SELECT i.issue, COUNT(*) n FROM row_issues i JOIN staging_rows s USING(row_id)
               WHERE s.batch_id=? AND i.severity='rejected' GROUP BY i.issue""", (batch_id,))
    warn = q("""SELECT i.issue, COUNT(*) n FROM row_issues i JOIN staging_rows s USING(row_id)
                WHERE s.batch_id=? AND i.severity='warning' GROUP BY i.issue ORDER BY n DESC""", (batch_id,))
    acc = q("""SELECT a.account_id, a.n_source_rows,
                      (SELECT MIN(s2.batch_id) FROM account_sources x JOIN staging_rows s2 USING(row_id)
                       WHERE x.account_id = a.account_id) AS first_batch
               FROM accounts a WHERE a.account_id IN (
                   SELECT x.account_id FROM account_sources x JOIN staging_rows s USING(row_id) WHERE s.batch_id=?)""",
            (batch_id,))
    new_accounts = int((acc.first_batch == batch_id).sum())
    c = st.columns(5)
    c[0].metric("Rows in file", rows)
    c[1].metric("Rejected", int(rej.n.sum()) if not rej.empty else 0)
    c[2].metric("Accounts touched", len(acc))
    c[3].metric("New accounts", new_accounts)
    c[4].metric("Matched existing / duplicate rows", rows - (int(rej.n.sum()) if not rej.empty else 0) - new_accounts)
    mapping = map_columns(js(b.columns_json))
    st.markdown("**Detected columns:** " + ", ".join(f"`{v}` → {k}" for k, v in mapping.items()))
    unmapped = [col for col in js(b.columns_json) if col not in mapping.values() and col != "#"]
    if unmapped:
        st.caption("Ignored columns: " + ", ".join(unmapped))
    l, r = st.columns(2)
    with l:
        st.markdown("**Rejected rows**")
        if rej.empty:
            st.write("None")
        else:
            detail = q("""SELECT s.row_number AS row, i.issue, s.raw_json FROM row_issues i JOIN staging_rows s USING(row_id)
                          WHERE s.batch_id=? AND i.severity='rejected'""", (batch_id,))
            st.dataframe(detail, hide_index=True, width="stretch")
    with r:
        st.markdown("**Fixes & warnings**")
        warn["meaning"] = warn["issue"].map(FLAG_HELP).fillna("")
        st.dataframe(warn, hide_index=True, width="stretch")


tab_up, tab_batches, tab_admin = st.tabs(["Upload a file", "Imported files", "Admin"])

with tab_up:
    up = st.file_uploader("CSV file", type=["csv"])
    hint = st.selectbox("Platform (if the file has no platform column / links)",
                        ["auto-detect", "instagram", "youtube", "threads", "tiktok"])
    if up is not None:
        data = up.getvalue()
        try:
            preview = pd.read_csv(io.BytesIO(data), dtype=str, nrows=8, encoding="utf-8-sig")
            st.markdown("**Preview**")
            st.dataframe(preview, hide_index=True, width="stretch")
            mapping = map_columns(list(preview.columns))
            st.markdown("**Column mapping:** " + (", ".join(f"`{v}` → {k}" for k, v in mapping.items()) or "none found"))
            if not ({"name", "handle", "url"} & set(mapping)):
                st.error("No name / handle / link column found - rename a column to e.g. 'Name' or 'Profile Link'.")
        except Exception as e:  # noqa: BLE001
            st.warning(f"Could not preview: {e}")
        if st.button("Ingest and run cleaning", type="primary"):
            c = conn()
            try:
                res = ingest_upload(c, data, up.name, None if hint == "auto-detect" else hint)
                if res["skipped"]:
                    st.info("This exact file was already imported - nothing to do.")
                else:
                    with st.spinner("Cleaning, de-duplicating, exporting..."):
                        rebuild(c)
                    st.session_state["last_batch"] = res["batch_id"]
            finally:
                c.close()

    sample = ROOT / "data" / "samples" / "SYNTHETIC_agency_upload.csv"
    with st.expander("No file handy? Load the synthetic messy test sheet"):
        st.markdown("150 rows written the way agency sheets look: tracking params in URLs, `@handles`, "
                    "`12,00,000` / `1.2 lakh`, Bombay/Bangalore, duplicates, typos and broken rows. "
                    "**Cities in it are random** - it's a test fixture. Remove it afterwards under *Imported files*.")
        if st.button("Load synthetic sample"):
            if not sample.exists():
                subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sample_upload.py")], check=True)
            c = conn()
            try:
                res = ingest_file(c, sample)
                if not res["skipped"]:
                    with st.spinner("Cleaning..."):
                        rebuild(c)
                st.session_state["last_batch"] = res["batch_id"]
            finally:
                c.close()

    if "last_batch" in st.session_state:
        st.divider()
        st.subheader("Import report")
        show_report(st.session_state["last_batch"])

with tab_batches:
    batches = q("SELECT batch_id, file_name, platform_hint, row_count, ingested_at, stored_path FROM import_batches")
    if batches.empty:
        st.info("Nothing imported yet.")
    else:
        st.dataframe(batches, hide_index=True, width="stretch")
        pick = st.selectbox("Show report for", batches.batch_id, format_func=lambda b: f"#{b} {batches.set_index('batch_id').file_name[b]}")
        show_report(int(pick))
        if st.button(f"Remove import #{pick}", help="Deletes its staging rows and rebuilds. The stored file is kept."):
            c = conn()
            try:
                remove_batch(c, int(pick))
                rebuild(c)
                st.session_state.pop("last_batch", None)
            finally:
                c.close()
            st.rerun()

with tab_admin:
    st.markdown("**Load the raw Kaggle files** from `raw_data/` (skipped if already loaded).")
    if st.button("Load raw_data/*.csv"):
        c = conn()
        try:
            out = [f"{f.name}: {'already loaded' if ingest_file(c, f)['skipped'] else 'loaded'}"
                   for f in sorted(RAW_DIR.glob("*.csv"))]
            rebuild(c)
            st.success(" · ".join(out))
        finally:
            c.close()
    st.markdown("**Re-run cleaning & dedupe** on everything in staging (after changing a rule).")
    if st.button("Rebuild"):
        c = conn()
        try:
            st.json(rebuild(c))
        finally:
            c.close()
    st.markdown("**Reset** - deletes the database (including review decisions and API snapshots). "
                "Raw files are not touched.")
    if st.checkbox("I understand") and st.button("Reset database", type="secondary"):
        DB_PATH.unlink(missing_ok=True)
        st.cache_data.clear()
        st.session_state.clear()
        st.rerun()
