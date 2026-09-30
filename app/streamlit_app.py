"""Creator Intelligence - data layer prototype.

    streamlit run app/streamlit_app.py
"""
import streamlit as st

st.set_page_config(page_title="Creator Intelligence", page_icon="📊", layout="wide")

pages = st.navigation({
    "Data": [
        st.Page("views/overview.py", title="Overview", icon="📊", default=True),
        st.Page("views/import_data.py", title="Import & clean", icon="📥"),
        st.Page("views/review.py", title="Review queue", icon="🔍"),
    ],
    "Creators": [
        st.Page("views/creators.py", title="Search creators", icon="👤"),
    ],
    "Enrichment": [
        st.Page("views/youtube.py", title="YouTube API", icon="▶️"),
    ],
})
pages.run()
