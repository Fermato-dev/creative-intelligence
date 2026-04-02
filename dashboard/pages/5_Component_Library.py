"""Fermato Creative Intelligence v3 — Component Library & Recommendations"""

import json
import streamlit as st

st.set_page_config(page_title="Component Library", page_icon="🧩", layout="wide")

import sys
from datetime import datetime
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parent.parent
REPO_ROOT = DASHBOARD_DIR.parent
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(DASHBOARD_DIR))
sys.path.insert(0, str(REPO_ROOT))
from shared_data import SHARED_CSS

st.markdown(SHARED_CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Component Library")
    st.caption("v3: Hook × Body × CTA knihovna")

st.markdown("## Component Library & Recommendations")
st.caption("v3: Modulární analýza kreativ — hook/body/CTA komponenty s kombinatorickými doporučeními")

# ── Load component DB ──

try:
    from creative_intelligence.component_db import (
        get_db, get_top_components, count_components, get_all_components,
        get_pending_recommendations,
    )
    conn = get_db()
    has_db = True
except Exception as e:
    has_db = False
    st.warning(f"Component DB neni dostupna: {e}")

if not has_db:
    st.info("Spust `python -m creative_intelligence decompose` pro naplneni komponentni knihovny.")
    st.stop()

# ── Summary ──

counts = count_components(conn)
total = sum(c["count"] for c in counts.values())

if total == 0:
    st.info("Knihovna je prazdna. Spust `python -m creative_intelligence decompose --days 14` pro analyzu videi.")
    conn.close()
    st.stop()

c1, c2, c3, c4 = st.columns(4)
for col, comp_type, label in [
    (c1, "hook", "Hooky"),
    (c2, "body", "Bodies"),
    (c3, "cta", "CTAs"),
]:
    c = counts.get(comp_type, {"count": 0, "avg_hook_rate": None, "avg_roas": None})
    with col:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">{label}</div>
        <div class="health-value">{c['count']}</div>
        <div class="health-sub">avg ROAS: {c['avg_roas']:.2f if c['avg_roas'] else '—'}</div>
        </div>""", unsafe_allow_html=True)

with c4:
    st.markdown(f"""<div class="health-card">
    <div class="health-label">Celkem</div>
    <div class="health-value">{total}</div>
    <div class="health-sub">komponent</div>
    </div>""", unsafe_allow_html=True)

st.divider()

# ── Tabs ──

tab_hooks, tab_bodies, tab_ctas, tab_recs = st.tabs(["Top Hooks", "Top Bodies", "Top CTAs", "Recommendations"])

with tab_hooks:
    st.markdown("### Top Hooks (by hook rate)")
    st.caption("Hooky s nejvyssi hook rate — prvnich 3 sekund videa")
    top_hooks = get_top_components(conn, "hook", metric="hook_rate", limit=20)
    if top_hooks:
        rows = []
        for h in top_hooks:
            analysis = h.get("analysis") or {}
            rows.append({
                "Ad": (h.get("ad_name") or "")[:35],
                "Hook Rate %": h.get("hook_rate"),
                "ROAS": h.get("roas"),
                "CPA": h.get("cpa"),
                "Spend": h.get("spend"),
                "Hook Type": analysis.get("hook_type", "—"),
                "Effectiveness": analysis.get("effectiveness", analysis.get("hook_effectiveness", "—")),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("Zadne hook komponenty.")

with tab_bodies:
    st.markdown("### Top Bodies (by hold rate)")
    st.caption("Stredni cast videa s nejlepsim hold rate")
    top_bodies = get_top_components(conn, "body", metric="hold_rate", limit=20)
    if top_bodies:
        rows = []
        for b in top_bodies:
            analysis = b.get("analysis") or {}
            rows.append({
                "Ad": (b.get("ad_name") or "")[:35],
                "Hold Rate %": b.get("hold_rate"),
                "ROAS": b.get("roas"),
                "Spend": b.get("spend"),
                "Narrative": analysis.get("narrative_structure", "—"),
                "Pacing": analysis.get("pacing", "—"),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("Zadne body komponenty.")

with tab_ctas:
    st.markdown("### Top CTAs (by CVR)")
    st.caption("CTA segmenty s nejvyssi konverzni mirou")
    top_ctas = get_top_components(conn, "cta", metric="cvr", limit=20)
    if top_ctas:
        rows = []
        for c in top_ctas:
            analysis = c.get("analysis") or {}
            rows.append({
                "Ad": (c.get("ad_name") or "")[:35],
                "CVR %": c.get("cvr"),
                "ROAS": c.get("roas"),
                "Spend": c.get("spend"),
                "CTA Type": analysis.get("cta_type", "—"),
                "Urgency": analysis.get("urgency_level", "—"),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("Zadne CTA komponenty.")

with tab_recs:
    st.markdown("### Kombinatoricka doporuceni")
    st.caption("Thompson Sampling: top hook × top body × top CTA — nikdy netestovane kombinace")

    # Load recommendations from file
    rec_files = sorted(DATA_DIR.glob("recommendations-*.txt"), reverse=True)
    if rec_files:
        latest = rec_files[0]
        st.markdown(f"**Posledni report:** `{latest.name}`")
        with st.expander("Zobrazit doporuceni", expanded=True):
            st.text(latest.read_text(encoding="utf-8"))
    else:
        # Try generating on-the-fly
        pending = get_pending_recommendations(conn, limit=10)
        if pending:
            for rec in pending:
                rec_type = rec.get("rec_type", "?")
                desc = rec.get("description", "")
                details = rec.get("details") or {}

                if rec_type == "SWAP_HOOK":
                    st.markdown(f"""<div class="act-box act-iterate">
                    <strong>SWAP HOOK:</strong> {desc}<br>
                    <small>{details.get('target_ad', '?')[:30]} → hook z {details.get('suggested_from_ad', '?')[:30]}</small>
                    </div>""", unsafe_allow_html=True)
                elif rec_type == "NEW_COMBINATION":
                    h = details.get("hook", {})
                    b = details.get("body", {})
                    c = details.get("cta", {})
                    st.markdown(f"""<div class="act-box act-scale">
                    <strong>NOVA KOMBINACE</strong> (score: {details.get('combined_score', '?')})<br>
                    Hook: {h.get('from_ad', '?')[:25]} ({h.get('hook_rate', '?')}%) +
                    Body: {b.get('from_ad', '?')[:25]} (hold {b.get('hold_rate', '?')}%) +
                    CTA: {c.get('from_ad', '?')[:25]} (CVR {c.get('cvr', '?')}%)
                    </div>""", unsafe_allow_html=True)
                elif rec_type == "REFRESH_ALERT":
                    st.markdown(f"""<div class="act-box act-kill">
                    <strong>REFRESH:</strong> {details.get('ad_name', '?')[:30]} — {details.get('days_active', '?')} dni aktivni
                    </div>""", unsafe_allow_html=True)
        else:
            st.info("Zatim zadna doporuceni. Spust `python -m creative_intelligence recommend`.")

    if st.button("Vygenerovat nova doporuceni", type="primary"):
        try:
            from creative_intelligence.combinator import generate_all_recommendations, format_recommendations_report
            results = generate_all_recommendations(conn)
            report = format_recommendations_report(results)
            st.text(report)

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path = DATA_DIR / f"recommendations-{datetime.now().strftime('%Y-%m-%d')}.txt"
            path.write_text(report, encoding="utf-8")
            st.success(f"Ulozeno: {path.name}")
        except Exception as e:
            st.error(f"Chyba: {e}")

conn.close()
