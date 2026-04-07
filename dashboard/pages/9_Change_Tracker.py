"""Fermato Creative Intelligence — Change Tracker & Lift Measurement"""

import json
import sqlite3
import streamlit as st

st.set_page_config(page_title="Change Tracker", page_icon="📊", layout="wide")

import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    st.stop()

import pandas as pd

DASHBOARD_DIR = Path(__file__).parent.parent
REPO_ROOT = DASHBOARD_DIR.parent
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(DASHBOARD_DIR))
from shared_data import SHARED_CSS

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── CSS ──

st.markdown("""<style>
.change-card { border-radius: 10px; padding: 14px 16px; margin: 6px 0; border-left: 4px solid; }
.change-positive { background: #f0fdf4; border-left-color: #16a34a; }
.change-negative { background: #fef2f2; border-left-color: #dc2626; }
.change-neutral { background: #f8f9fb; border-left-color: #9ca3af; }
.change-pending { background: #eff6ff; border-left-color: #3b82f6; border-style: dashed; border-left-style: solid; }
.change-inconclusive { background: #fefce8; border-left-color: #d97706; }

.change-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.change-type { font-size: 0.72em; font-weight: 700; padding: 2px 8px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: 0.04em; }
.ct-status { background: #dbeafe; color: #1e40af; }
.ct-creative { background: #f3e8ff; color: #7c3aed; }
.ct-budget { background: #fef3c7; color: #92400e; }
.ct-spend { background: #ccfbf1; color: #0d9488; }
.ct-new { background: #dcfce7; color: #16a34a; }
.ct-stopped { background: #fef2f2; color: #dc2626; }

.change-ad { font-weight: 700; color: #1a202c; font-size: 0.92em; }
.change-campaign { font-size: 0.78em; color: #6b7280; }
.change-detail { font-size: 0.84em; color: #374151; margin: 4px 0; }
.change-lift { display: flex; gap: 16px; margin-top: 8px; font-size: 0.82em; }
.lift-pre { color: #6b7280; }
.lift-post { color: #374151; font-weight: 600; }
.lift-delta { font-weight: 700; padding: 2px 6px; border-radius: 4px; }
.lift-up { background: #dcfce7; color: #16a34a; }
.lift-down { background: #fef2f2; color: #dc2626; }
.lift-flat { background: #f3f4f6; color: #6b7280; }

.verdict-badge { font-size: 0.72em; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.v-positive { background: #dcfce7; color: #16a34a; }
.v-negative { background: #fef2f2; color: #dc2626; }
.v-neutral { background: #f3f4f6; color: #6b7280; }
.v-pending { background: #dbeafe; color: #3b82f6; }
.v-inconclusive { background: #fef3c7; color: #d97706; }

.learning-card { border-radius: 10px; padding: 14px 16px; margin: 6px 0; }
.learning-good { background: #f0fdf4; border: 1px solid #86efac; }
.learning-bad { background: #fef2f2; border: 1px solid #fca5a5; }
.learning-mixed { background: #f8f9fb; border: 1px solid #e5e7eb; }
</style>""", unsafe_allow_html=True)

# ── Sidebar ──

with st.sidebar:
    st.markdown("### Change Tracker")
    st.caption("Sledovani zmen v Meta Ads a mereni jejich dopadu")

# ── Database ──

ANALYSIS_DB = DATA_DIR / "creative_analysis.db"


@st.cache_data(ttl=900)
def load_change_data(_db_path):
    if not _db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    data = {}

    # Check if tables exist
    tables = [t[0] for t in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "change_events" not in tables:
        conn.close()
        return None

    # KPIs
    data["total_changes"] = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    data["positive"] = conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE verdict = 'positive'").fetchone()[0]
    data["negative"] = conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE verdict = 'negative'").fetchone()[0]
    data["pending"] = conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE lift_status = 'pending'").fetchone()[0]
    data["measured"] = conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE lift_status = 'measured'").fetchone()[0]

    # Snapshots count
    data["total_snapshots"] = conn.execute("SELECT COUNT(*) FROM ad_daily_snapshots").fetchone()[0]
    data["snapshot_days"] = conn.execute(
        "SELECT COUNT(DISTINCT snapshot_date) FROM ad_daily_snapshots").fetchone()[0]

    # Recent changes (last 30 days)
    data["changes"] = [dict(r) for r in conn.execute("""
        SELECT * FROM change_events
        ORDER BY detected_date DESC, id DESC
        LIMIT 100
    """).fetchall()]

    # Learnings
    data["learnings"] = [dict(r) for r in conn.execute("""
        SELECT * FROM learnings WHERE status = 'active'
        ORDER BY sample_size DESC
    """).fetchall()]

    # Daily snapshot summary for timeline
    data["daily_summary"] = [dict(r) for r in conn.execute("""
        SELECT snapshot_date, COUNT(*) as ads, SUM(spend) as total_spend,
               SUM(purchases) as total_purchases, SUM(revenue) as total_revenue
        FROM ad_daily_snapshots
        GROUP BY snapshot_date
        ORDER BY snapshot_date
    """).fetchall()]

    conn.close()
    return data


# ── Load data ──

data = load_change_data(ANALYSIS_DB)

st.markdown("## Change Tracker")

if not data:
    st.warning("Change tracking tabulky zatim neexistuji. Spust `python scripts/collect_daily_snapshots.py` pro sber dat.")
    st.markdown("""
    ### Jak to funguje
    1. **Denny sber** — skript stahuje denni ad-level metriky z Meta API
    2. **Detekce zmen** — porovnava dnesek vs. vcerejsek (status, creative, budget, spend)
    3. **Mereni liftu** — po 8 dnech spocita before/after dopad zmeny
    4. **Learnings** — akumuluje poznatky z mereni (co funguje, co ne)

    Pro spusteni na PC2: `python scripts/collect_daily_snapshots.py --backfill 14`
    """)
    st.stop()

st.caption(f"{data['snapshot_days']} dni dat · {data['total_snapshots']} snapshotu · "
           f"posledni zmena: {data['changes'][0]['detected_date'] if data['changes'] else '—'}")

# ── KPIs ──

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Celkem zmen", data["total_changes"])
k2.metric("Pozitivni", data["positive"])
k3.metric("Negativni", data["negative"])
k4.metric("Cekajici", data["pending"])
k5.metric("Zmereno", data["measured"])

st.divider()

# ── Sidebar filters ──

with st.sidebar:
    st.markdown("---")
    st.markdown("#### Filtry")

    change_types = sorted(set(c["change_type"] for c in data["changes"]))
    selected_types = st.multiselect("Typ zmeny", change_types, default=[])

    verdicts = ["positive", "negative", "neutral", "pending", "inconclusive"]
    selected_verdicts = st.multiselect("Verdict", verdicts, default=[])

# ── Timeline ──

if data["changes"] and any(c.get("roas_lift") is not None for c in data["changes"]):
    st.markdown("### Timeline")
    measured = [c for c in data["changes"] if c.get("roas_lift") is not None]
    if measured:
        import plotly.graph_objects as go
        colors = {"positive": "#16a34a", "negative": "#dc2626", "neutral": "#9ca3af", "inconclusive": "#d97706"}
        fig = go.Figure()
        for verdict, color in colors.items():
            vdata = [c for c in measured if c["verdict"] == verdict]
            if vdata:
                fig.add_trace(go.Scatter(
                    x=[c["detected_date"] for c in vdata],
                    y=[c["roas_lift"] for c in vdata],
                    mode="markers",
                    marker=dict(color=color, size=10),
                    name=verdict,
                    text=[f"{c['ad_name']}: {c['change_type']}" for c in vdata],
                    hovertemplate="%{text}<br>ROAS lift: %{y:.1f}%<extra></extra>",
                ))
        fig.add_hline(y=0, line_dash="dash", line_color="#9ca3af")
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          yaxis_title="ROAS Lift %",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig, use_container_width=True)
    st.divider()

# ── Change Feed ──

st.markdown("### Zmeny a jejich dopad")

changes = data["changes"]
if selected_types:
    changes = [c for c in changes if c["change_type"] in selected_types]
if selected_verdicts:
    changes = [c for c in changes if (c.get("verdict") or "pending") in selected_verdicts]

TYPE_CSS = {
    "STATUS_CHANGE": "ct-status", "CREATIVE_SWAP": "ct-creative",
    "BUDGET_CHANGE": "ct-budget", "SPEND_SPIKE": "ct-spend", "SPEND_DROP": "ct-spend",
    "NEW_AD": "ct-new", "AD_STOPPED": "ct-stopped", "OPTIMIZATION_CHANGE": "ct-status",
}

VERDICT_CSS = {
    "positive": "v-positive", "negative": "v-negative", "neutral": "v-neutral",
    "pending": "v-pending", "inconclusive": "v-inconclusive",
}

if changes:
    for c in changes[:50]:
        verdict = c.get("verdict") or "pending"
        card_css = {
            "positive": "change-positive", "negative": "change-negative",
            "neutral": "change-neutral", "pending": "change-pending",
            "inconclusive": "change-inconclusive",
        }.get(verdict, "change-neutral")

        ct_css = TYPE_CSS.get(c["change_type"], "ct-status")
        v_css = VERDICT_CSS.get(verdict, "v-pending")

        # Change detail
        detail = ""
        if c.get("field_changed") and c.get("old_value") and c.get("new_value"):
            mag = f" ({c['change_magnitude']:+.0f}%)" if c.get("change_magnitude") else ""
            detail = f'{c["field_changed"]}: {c["old_value"]} → {c["new_value"]}{mag}'

        # Lift section
        lift_html = ""
        if c.get("lift_status") == "measured" and c.get("pre_roas") is not None:
            pre_roas = c["pre_roas"] or 0
            post_roas = c["post_roas"] or 0
            roas_lift = c.get("roas_lift")
            pre_cpa = c.get("pre_cpa") or 0
            post_cpa = c.get("post_cpa") or 0
            cpa_lift = c.get("cpa_lift")

            roas_cls = "lift-up" if roas_lift and roas_lift > 5 else "lift-down" if roas_lift and roas_lift < -5 else "lift-flat"
            cpa_cls = "lift-down" if cpa_lift and cpa_lift > 5 else "lift-up" if cpa_lift and cpa_lift < -5 else "lift-flat"

            lift_html = f"""<div class="change-lift">
<span class="lift-pre">Pred: ROAS {pre_roas:.2f} · CPA {pre_cpa:.0f}</span>
<span class="lift-post">Po: ROAS {post_roas:.2f} · CPA {post_cpa:.0f}</span>
<span class="lift-delta {roas_cls}">ROAS {roas_lift:+.0f}%</span>
{f'<span class="lift-delta {cpa_cls}">CPA {cpa_lift:+.0f}%</span>' if cpa_lift else ''}
</div>"""
        elif c.get("lift_status") == "pending":
            lift_html = '<div style="font-size:0.78em;color:#3b82f6;margin-top:4px">Lift se meri... (7 dni po zmene)</div>'

        conf_html = ""
        if c.get("confidence_score") is not None:
            conf = c["confidence_score"]
            dot = "●" if conf >= 0.5 else "◐" if conf >= 0.3 else "○"
            conf_html = f'<span style="font-size:0.72em;color:#9ca3af;margin-left:8px">{dot} {conf:.0%}</span>'

        st.markdown(f"""<div class="change-card {card_css}">
<div class="change-header">
<span class="change-type {ct_css}">{c['change_type']}</span>
<span class="verdict-badge {v_css}">{verdict}</span>
{conf_html}
<span style="font-size:0.75em;color:#9ca3af">{c['detected_date']}</span>
</div>
<span class="change-ad">{c.get('ad_name', '?')}</span>
<span class="change-campaign"> · {c.get('campaign_name', '')}</span>
{f'<div class="change-detail">{detail}</div>' if detail else ''}
{lift_html}
</div>""", unsafe_allow_html=True)
else:
    st.info("Zadne zmeny pro zvolene filtry.")

st.divider()

# ── Learnings ──

st.markdown("### Learnings")

if data["learnings"]:
    for l in data["learnings"]:
        ltype = l.get("learning_type", "")
        css = "learning-good" if ltype == "best_practice" else "learning-bad" if ltype == "warning" else "learning-mixed"
        conf = l.get("confidence", "?")
        n = l.get("sample_size", 0)
        avg_roas = l.get("avg_roas_lift")
        roas_str = f" · avg ROAS lift {avg_roas:+.0f}%" if avg_roas else ""

        st.markdown(f"""<div class="learning-card {css}">
<strong>{l['description']}</strong>
<div style="font-size:0.78em;color:#6b7280;margin-top:4px">
{n} pozorovani · spolehlivost: {conf}{roas_str}
</div>
</div>""", unsafe_allow_html=True)
else:
    st.caption("Zatim zadne learnings — potrebuji alespon 3 zmerene zmeny stejneho typu.")

# ── Daily summary ──

if data["daily_summary"]:
    st.divider()
    st.markdown("### Denni prehled")
    df = pd.DataFrame(data["daily_summary"])
    df["roas"] = df["total_revenue"] / df["total_spend"].replace(0, float("nan"))
    st.dataframe(df.rename(columns={
        "snapshot_date": "Datum", "ads": "Aktivnich reklam",
        "total_spend": "Spend (CZK)", "total_purchases": "Nakupy",
        "total_revenue": "Revenue (CZK)", "roas": "ROAS",
    }), use_container_width=True, hide_index=True,
    column_config={
        "Spend (CZK)": st.column_config.NumberColumn(format="%.0f"),
        "Revenue (CZK)": st.column_config.NumberColumn(format="%.0f"),
        "ROAS": st.column_config.NumberColumn(format="%.2f"),
    })
