import streamlit as st

from common import PLATFORM_ICON, PLATFORM_LABEL, conn, fmt_num, invalidate, js, q
from creator_pipeline import dedupe, export

st.title("Review queue")
st.caption("Possible matches the system is not sure about. Nothing fuzzy is merged until a person says so. "
           "Safe matches (same handle on Instagram & Threads) are linked automatically and listed at the bottom.")

KIND_LABEL = {
    "cross_platform_fuzzy": "Similar name/handle on different platforms",
    "cross_platform_exact_handle": "Same handle on different platforms, names differ",
    "cross_platform_exact_handle_and_name": "Same handle and name on different platforms",
    "ig_threads_same_handle": "Same handle on Instagram & Threads",
    "same_platform_similar": "Two accounts on the same platform with near-identical names",
}

cand = q("""
    SELECT d.*, a.platform pa, a.name_clean na, a.display_name_raw ra, a.handle ha, a.profile_url ua,
           a.followers fa, a.er_pct ea, a.categories_json ca, a.entity_type ta,
           b.platform pb, b.name_clean nb, b.display_name_raw rb, b.handle hb, b.profile_url ub,
           b.followers fb, b.er_pct eb, b.categories_json cb, b.entity_type tb
    FROM dedupe_candidates d JOIN accounts a ON a.account_id = d.account_a
    JOIN accounts b ON b.account_id = d.account_b ORDER BY d.score DESC""")


def decide(pair_id: str, status: str):
    c = conn()
    try:
        dedupe.decide(c, pair_id, status)
        c.commit()
        export.run(c)
    finally:
        c.close()
    invalidate()


def side(col, p, n, raw, h, url, f, e, cats, t, acct):
    h = h if isinstance(h, str) else None
    raw = raw if isinstance(raw, str) else None
    with col:
        st.markdown(f"#### {PLATFORM_ICON.get(p, '')} {n}")
        st.caption(f"{PLATFORM_LABEL.get(p, p)} · `{acct}`")
        if raw and raw != n:
            st.caption(f"as written in the source: *{raw}*")
        st.markdown(f"**Handle:** [{('@' + h) if h else '—'}]({url})  \n"
                    f"**Followers:** {fmt_num(f)} · **ER:** {'—' if e is None or e != e else f'{e:.2f}%'}  \n"
                    f"**Categories:** {', '.join(js(cats)) or '—'}  \n**Type (guess):** {t}")


pending = cand[cand.status == "pending"]
done = cand[cand.status.isin(["linked", "rejected"])]
auto = cand[cand.status == "auto_linked"]

c = st.columns(3)
c[0].metric("Waiting for review", len(pending))
c[1].metric("Decided by a person", len(done))
c[2].metric("Auto-linked by rule", len(auto))

if pending.empty:
    st.success("Queue is empty.")
for _, r in pending.iterrows():
    with st.container(border=True):
        top = st.columns([3, 1])
        top[0].markdown(f"**{KIND_LABEL.get(r.kind, r.kind)}** · match score **{r.score:.0%}**")
        top[0].caption("Why: " + "; ".join(js(r.reasons_json)))
        a, b = st.columns(2)
        side(a, r.pa, r.na, r.ra, r.ha, r.ua, r.fa, r.ea, r.ca, r.ta, r.account_a)
        side(b, r.pb, r.nb, r.rb, r.hb, r.ub, r.fb, r.eb, r.cb, r.tb, r.account_b)
        btn = st.columns([1, 1, 3])
        if btn[0].button("✅ Same creator", key=f"l_{r.pair_id}", type="primary"):
            decide(r.pair_id, "linked")
            st.rerun()
        if btn[1].button("❌ Different", key=f"r_{r.pair_id}"):
            decide(r.pair_id, "rejected")
            st.rerun()

if not done.empty:
    st.subheader("Decisions")
    for _, r in done.iterrows():
        cols = st.columns([5, 1])
        verdict = "✅ linked" if r.status == "linked" else "❌ kept separate"
        cols[0].markdown(f"{verdict} — **{r.na}** ({PLATFORM_LABEL[r.pa]}) ↔ **{r.nb}** ({PLATFORM_LABEL[r.pb]}) "
                         f"· {r.decided_by}, {str(r.decided_at)[:16].replace('T', ' ')}")
        if cols[1].button("Undo", key=f"u_{r.pair_id}"):
            decide(r.pair_id, "pending")
            st.rerun()

with st.expander(f"Auto-linked by rule ({len(auto)})"):
    for _, r in auto.iterrows():
        st.markdown(f"- **{r.na}** ({PLATFORM_LABEL[r.pa]} @{r.ha}) ↔ **{r.nb}** ({PLATFORM_LABEL[r.pb]} @{r.hb}) — "
                    f"{KIND_LABEL.get(r.kind, r.kind)}")
