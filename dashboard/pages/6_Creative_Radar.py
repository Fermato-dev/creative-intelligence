"""Fermato Creative Intelligence — Creative Radar (Competitor Intelligence)"""

import json
import sqlite3
import streamlit as st

st.set_page_config(page_title="Creative Radar", page_icon="📡", layout="wide")

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

DASHBOARD_DIR = Path(__file__).parent.parent
REPO_ROOT = DASHBOARD_DIR.parent
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(DASHBOARD_DIR))
from shared_data import SHARED_CSS

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── Custom CSS ──

st.markdown("""<style>
.totest-card {
    background: linear-gradient(135deg, #eef9f7 0%, #f0fdf4 100%);
    border: 1px solid #99f6e4;
    border-radius: 10px;
    padding: 14px 16px;
    margin: 6px 0;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.totest-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(20,184,166,0.15);
}
.totest-brand { font-weight: 700; color: #0f766e; font-size: 0.95em; }
.totest-hook { display: inline-block; background: #dbeafe; color: #1e40af; font-size: 0.72em;
    font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px; }
.totest-insight { font-size: 0.82em; color: #4b5563; margin-top: 6px; line-height: 1.45; }
.totest-adapt { font-size: 0.78em; color: #6b7280; margin-top: 4px; font-style: italic; }

.score-pill { display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 22px; border-radius: 5px; font-size: 0.78em; font-weight: 700; }
.score-high { background: #ccfbf1; color: #0d9488; border: 1px solid #5eead4; }
.score-mid { background: #dcfce7; color: #16a34a; border: 1px solid #86efac; }
.score-low { background: #fef3c7; color: #d97706; border: 1px solid #fcd34d; }

.tier-badge { font-size: 0.68em; font-weight: 700; padding: 2px 7px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: 0.06em; }
.tier-us { background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
.tier-eu { background: #ccfbf1; color: #0d9488; border: 1px solid #5eead4; }
.tier-cz { background: #fef3c7; color: #d97706; border: 1px solid #fcd34d; }

.source-badge { font-size: 0.68em; font-weight: 600; padding: 2px 7px; border-radius: 4px; }
.source-organic { background: #dcfce7; color: #16a34a; }
.source-paid { background: #dbeafe; color: #1e40af; }

.radar-stat { background: #f8f9fb; border: 1px solid #e8ecf1; border-radius: 10px;
    padding: 10px 12px; text-align: center; }
.radar-stat-value { font-size: 1.5em; font-weight: 700; color: #1a202c; }
.radar-stat-label { font-size: 0.72em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.04em; }
</style>""", unsafe_allow_html=True)

# ── Sidebar ──

with st.sidebar:
    st.markdown("### Creative Radar")
    st.caption("Competitor Intelligence — organic + paid")

# ── Database ──

# Try multiple paths for competitor_intel.db
DB_PATHS = [
    DATA_DIR / "competitor_intel.db",
    REPO_ROOT.parent / "projects" / "cmo" / "creative-intelligence" / "data" / "competitor_intel.db",
    Path("C:/Users/rstra/Chief_of_Staff/Chief-of-Staff/projects/cmo/creative-intelligence/data/competitor_intel.db"),
    Path("C:/Users/ferma/Chief_of_Staff/Chief-of-Staff/projects/cmo/creative-intelligence/data/competitor_intel.db"),
]

db_path = None
for p in DB_PATHS:
    if p.exists():
        db_path = p
        break

if not db_path:
    st.warning("competitor_intel.db nenalezena. Spust `init_db.py --seed` a `competitor_scraper.py`.")
    st.info(f"Hledano v: {', '.join(str(p) for p in DB_PATHS[:2])}")
    st.stop()


@st.cache_data(ttl=1800)
def load_radar_data(_db_path):
    conn = sqlite3.connect(f"file:{_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    data = {}

    # KPIs
    data["organic"] = conn.execute("SELECT COUNT(*) as c FROM organic_posts").fetchone()["c"]
    data["paid"] = conn.execute("SELECT COUNT(*) as c FROM competitor_ads").fetchone()["c"]
    data["analyzed_organic"] = conn.execute("SELECT COUNT(*) as c FROM post_analysis").fetchone()["c"]
    data["analyzed_paid"] = conn.execute(
        "SELECT COUNT(*) as c FROM competitor_ads WHERE analyzed_at IS NOT NULL").fetchone()["c"]
    data["high_fit"] = conn.execute(
        "SELECT COUNT(*) as c FROM post_analysis WHERE transferability_score >= 6 AND brand_fit_score >= 6"
    ).fetchone()["c"]
    data["high_fit"] += conn.execute(
        "SELECT COUNT(*) as c FROM competitor_ads WHERE transferability_score >= 6 AND brand_fit_score >= 6"
    ).fetchone()["c"]
    data["brands"] = conn.execute("SELECT COUNT(*) as c FROM brands WHERE active=1").fetchone()["c"]

    # Last scrape
    last = conn.execute("SELECT MAX(finished_at) as t FROM scrape_runs").fetchone()["t"]
    data["last_scrape"] = last[:16] if last else "—"

    # To test — organic
    to_test = []
    for r in conn.execute("""
        SELECT 'organic' as source, op.post_url as url, b.name as brand, b.tier,
               pa.hook_type, pa.format_type, pa.transferability_score as t,
               pa.brand_fit_score as f, pa.analysis_json, op.platform, op.likes
        FROM post_analysis pa
        JOIN organic_posts op ON pa.post_id = op.id
        JOIN brands b ON op.brand_id = b.id
        WHERE pa.transferability_score >= 6 AND pa.brand_fit_score >= 6
        ORDER BY (pa.transferability_score + pa.brand_fit_score) DESC LIMIT 10
    """).fetchall():
        analysis = json.loads(r["analysis_json"] or "{}")
        to_test.append(dict(r) | {
            "insight": analysis.get("key_insight", ""),
            "adaptation": analysis.get("cz_adaptation_notes", ""),
        })

    # To test — paid
    for r in conn.execute("""
        SELECT 'paid' as source, ca.ad_url as url, b.name as brand, b.tier,
               ca.hook_type, ca.format_type, ca.transferability_score as t,
               ca.brand_fit_score as f, ca.analysis_json, 'meta_ads' as platform,
               ca.days_running as likes
        FROM competitor_ads ca
        JOIN brands b ON ca.brand_id = b.id
        WHERE ca.transferability_score >= 6 AND ca.brand_fit_score >= 6
        ORDER BY (ca.transferability_score + ca.brand_fit_score) DESC LIMIT 10
    """).fetchall():
        analysis = json.loads(r["analysis_json"] or "{}")
        to_test.append(dict(r) | {
            "insight": analysis.get("key_insight", ""),
            "adaptation": analysis.get("cz_adaptation_notes", ""),
        })

    to_test.sort(key=lambda x: (x["t"] or 0) + (x["f"] or 0), reverse=True)
    data["to_test"] = to_test[:10]

    # Brand activity
    data["brand_activity"] = [dict(r) for r in conn.execute("""
        SELECT b.name, b.tier,
               COUNT(DISTINCT op.id) as organic,
               COUNT(DISTINCT ca.id) as paid,
               COALESCE(SUM(DISTINCT op.likes), 0) as likes
        FROM brands b
        LEFT JOIN organic_posts op ON b.id = op.brand_id
        LEFT JOIN competitor_ads ca ON b.id = ca.brand_id
        WHERE b.active = 1
        GROUP BY b.id
        ORDER BY (COUNT(DISTINCT op.id) + COUNT(DISTINCT ca.id)) DESC
    """).fetchall()]

    # Scraper health
    data["health"] = [dict(r) for r in conn.execute("""
        SELECT platform, MAX(finished_at) as last_run, SUM(posts_new) as total_new,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures
        FROM scrape_runs GROUP BY platform
    """).fetchall()]

    conn.close()
    return data


data = load_radar_data(db_path)

# ── Header ──

st.markdown("## Creative Radar")
st.caption(f"Competitor Intelligence — {data['brands']} brandu · posledni scrape: {data['last_scrape']}")

# ── KPIs ──

k1, k2, k3, k4 = st.columns(4)
k1.metric("Organic posty", data["organic"])
k2.metric("Paid ads (Foreplay)", data["paid"])
k3.metric("Analyzovano", data["analyzed_organic"] + data["analyzed_paid"])
k4.metric("Vysoky Brand Fit", data["high_fit"])

st.divider()

# ── K Otestovani ──

st.markdown("### K otestovani")
st.caption("Koncepty od konkurence s vysokym transferability + brand fit skore")

if data["to_test"]:
    for item in data["to_test"]:
        source_cls = "source-organic" if item["source"] == "organic" else "source-paid"
        source_lbl = "organic" if item["source"] == "organic" else "paid"

        t_score = item["t"] or 0
        f_score = item["f"] or 0
        t_cls = "score-high" if t_score >= 8 else "score-mid" if t_score >= 6 else "score-low"
        f_cls = "score-high" if f_score >= 8 else "score-mid" if f_score >= 6 else "score-low"

        hook = item.get("hook_type") or "—"
        insight = (item.get("insight") or "")[:120]
        adaptation = (item.get("adaptation") or "")[:120]
        url = item.get("url") or ""
        link = f' · <a href="{url}" target="_blank" style="color:#0d9488;font-size:0.78em">odkaz</a>' if url else ""

        st.markdown(f"""<div class="totest-card">
<span class="source-badge {source_cls}">{source_lbl}</span>
<span class="totest-brand">{item['brand']}</span>
<span class="totest-hook">{hook}</span>
<span class="score-pill {t_cls}">T{t_score:.0f}</span>
<span class="score-pill {f_cls}">F{f_score:.0f}</span>
{link}
<div class="totest-insight">{insight}</div>
{f'<div class="totest-adapt">Adaptace CZ: {adaptation}</div>' if adaptation else ''}
</div>""", unsafe_allow_html=True)
else:
    st.info("Zadne koncepty s dostatecnym skore. Spust `competitor_analyzer.py`.")

st.divider()

# ── Brand Activity ──

st.markdown("### Aktivita brandu")

if data["brand_activity"]:
    rows = []
    for b in data["brand_activity"]:
        tier = b["tier"]
        tier_cls = {"us_dtc": "tier-us", "eu": "tier-eu", "cz": "tier-cz"}.get(tier, "")
        tier_lbl = {"us_dtc": "US DTC", "eu": "EU", "cz": "CZ"}.get(tier, tier)
        rows.append({
            "Brand": b["name"],
            "Tier": tier_lbl,
            "Organic": b["organic"],
            "Paid": b["paid"],
            "Likes": b["likes"],
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Likes": st.column_config.NumberColumn(format="%d"),
                 })

st.divider()

# ── Scraper Health ──

st.markdown("### Pipeline status")

if data["health"]:
    cols = st.columns(len(data["health"]) + 1)
    for i, h in enumerate(data["health"]):
        status = "OK" if h["failures"] == 0 else f"WARN ({h['failures']} failures)"
        cols[i].markdown(f"""<div class="radar-stat">
<div class="radar-stat-label">{h['platform']}</div>
<div class="radar-stat-value">{h['total_new'] or 0}</div>
<div style="font-size:0.75em;color:#6b7280">{status}</div>
<div style="font-size:0.68em;color:#9ca3af">{(h['last_run'] or '')[:16]}</div>
</div>""", unsafe_allow_html=True)

    # Foreplay card
    cols[-1].markdown(f"""<div class="radar-stat">
<div class="radar-stat-label">Foreplay</div>
<div class="radar-stat-value">{data['paid']}</div>
<div style="font-size:0.75em;color:#6b7280">paid ads</div>
</div>""", unsafe_allow_html=True)
