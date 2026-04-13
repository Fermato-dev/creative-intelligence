"""CI v3.5 Dashboard — Motion-inspired visual dashboard."""

import streamlit as st
from pathlib import Path
import streamlit.components.v1 as components

st.set_page_config(page_title="CI v3.5 Dashboard", page_icon="📊", layout="wide")

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dashboard.auth import check_password
if not check_password():
    st.stop()

DASHBOARD_PATH = Path(__file__).parent.parent.parent / "data" / "ci-dashboard.html"

st.markdown("## CI v3.5 — Motion-Inspired Dashboard")
st.caption("Funnel Scores · Performance Shifts · Leaderboard · Hooks · Landing Pages")

if DASHBOARD_PATH.exists():
    html_content = DASHBOARD_PATH.read_text(encoding="utf-8")
    components.html(html_content, height=4000, scrolling=True)
else:
    st.warning("Dashboard HTML not found. Run: python scripts/ci_dashboard_refresh.py")
    st.info(f"Expected at: {DASHBOARD_PATH}")
