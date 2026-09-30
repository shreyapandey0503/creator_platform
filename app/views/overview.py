import pandas as pd
import plotly.express as px
import streamlit as st

from common import FLAG_HELP, PLATFORM_LABEL, SOURCE_LABEL, ago, fmt_num, js, q

st.title("Creator data layer")
st.caption("Raw files → staging → cleaned accounts → deduplicated creators → enriched snapshots. "
           "Raw files are never modified; every number carries its source and timestamp.")

counts = q("""SELECT
    (SELECT COUNT(*) FROM staging_rows) raw_rows,
    (SELECT COUNT(DISTINCT row_id) FROM row_issues WHERE severity='rejected') rejected,
    (SELECT COUNT(*) FROM accounts) accounts,
    (SELECT COUNT(*) FROM creators) creators,
    (SELECT COUNT(*) FROM creators WHERE n_accounts > 1) multi,
    (SELECT COUNT(*) FROM dedupe_candidates WHERE status='pending') pending,
    (SELECT COUNT(*) FROM accounts WHERE stats_source='youtube_api') enriched,
    (SELECT COUNT(*) FROM import_batches) batches""").iloc[0]

if counts.raw_rows == 0:
    st.info("No data yet. Go to **Import & clean** to load the raw files, or run `python scripts/run_pipeline.py`.")
    st.stop()

c = st.columns(6)
c[0].metric("Raw rows", f"{counts.raw_rows:,}", help=f"from {counts.batches} file(s)")
c[1].metric("Rejected rows", f"{counts.rejected:,}", help="No usable platform/handle - see Import & clean")
c[2].metric("Clean accounts", f"{counts.accounts:,}", help="One per platform account after exact de-duplication")
c[3].metric("Creators", f"{counts.creators:,}", help="Accounts grouped into people/brands")
c[4].metric("Pending reviews", f"{counts.pending:,}", help="Possible matches waiting for a human decision")
c[5].metric("YouTube-enriched", f"{counts.enriched:,}")

left, right = st.columns(2)
with left:
    st.subheader("Pipeline funnel")
    dup = q("SELECT COALESCE(SUM(n_source_rows - 1),0) n FROM accounts").iloc[0].n
    linked = counts.accounts - counts.creators
    funnel = pd.DataFrame({
        "stage": ["Raw rows", "− rejected", "− exact duplicates merged", "= clean accounts",
                  "− accounts linked to another", "= creators"],
        "rows": [counts.raw_rows, -counts.rejected, -dup, counts.accounts, -linked, counts.creators]})
    st.dataframe(funnel, hide_index=True, width="stretch")
    plat = q("SELECT platform, COUNT(*) accounts, SUM(followers) followers FROM accounts GROUP BY platform")
    plat["platform"] = plat["platform"].map(PLATFORM_LABEL)
    st.plotly_chart(px.bar(plat, x="platform", y="accounts", text="accounts", title="Accounts by platform",
                           height=300).update_layout(margin=dict(t=40, b=0)), width="stretch")

with right:
    st.subheader("Categories")
    cats = q("SELECT categories_json FROM accounts")
    s = pd.Series([c for x in cats.categories_json for c in js(x)]).value_counts()
    uncategorised = int((cats.categories_json.map(lambda x: len(js(x))) == 0).sum())
    cat_df = s.rename_axis("category").reset_index(name="accounts")
    st.plotly_chart(px.bar(cat_df.head(15), y="category", x="accounts", orientation="h", height=420,
                           title=f"Top categories ({uncategorised} accounts uncategorised)")
                    .update_layout(yaxis=dict(autorange="reversed"), margin=dict(t=40, b=0)),
                    width="stretch")

st.subheader("Data quality flags")
st.caption("Warnings raised while cleaning. Nothing is silently dropped - every fix is recorded per row.")
flags = q("""SELECT issue AS flag, COUNT(*) AS rows FROM row_issues WHERE severity='warning'
             GROUP BY issue ORDER BY rows DESC""")
flags["what it means"] = flags["flag"].map(FLAG_HELP).fillna("")
st.dataframe(flags, hide_index=True, width="stretch")

st.subheader("Freshness")
fr = q("SELECT platform, stats_source, MAX(stats_as_of) newest, MIN(stats_as_of) oldest, COUNT(*) n "
       "FROM accounts GROUP BY platform, stats_source")
fr["source"] = fr["stats_source"].map(SOURCE_LABEL).fillna(fr["stats_source"])
fr["platform"] = fr["platform"].map(PLATFORM_LABEL)
fr["newest"] = fr["newest"].map(ago)
fr["oldest"] = fr["oldest"].map(ago)
st.dataframe(fr[["platform", "source", "n", "newest", "oldest"]], hide_index=True, width="stretch")
st.caption("CSV-import stats are dated by when the file was loaded, not by when the numbers were measured "
           "(the Kaggle source is a 2024 snapshot). API refreshes replace them with timestamped live numbers.")

st.subheader("Biggest creators")
top = q("SELECT display_name, entity_type, platforms_json, n_accounts, total_followers FROM creators "
        "ORDER BY total_followers DESC LIMIT 15")
top["platforms"] = top["platforms_json"].map(lambda x: ", ".join(PLATFORM_LABEL[p] for p in js(x)))
top["followers (all platforms)"] = top["total_followers"].map(fmt_num)
st.dataframe(top[["display_name", "entity_type", "platforms", "n_accounts", "followers (all platforms)"]],
             hide_index=True, width="stretch")
