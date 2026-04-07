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

.totest-links { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.totest-link { display: inline-flex; align-items: center; gap: 4px; font-size: 0.78em;
    font-weight: 600; padding: 4px 10px; border-radius: 6px; text-decoration: none;
    transition: all 0.12s ease; }
.totest-link:hover { transform: translateY(-1px); }
.link-post { background: #ccfbf1; color: #0d9488; border: 1px solid #5eead4; }
.link-post:hover { background: #99f6e4; color: #0f766e; }
.link-video { background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
.link-video:hover { background: #bfdbfe; color: #1e3a8a; }
.link-thumb { background: #fef3c7; color: #d97706; border: 1px solid #fcd34d; }
.link-thumb:hover { background: #fde68a; color: #b45309; }
.link-landing { background: #f3f4f6; color: #6b7280; border: 1px solid #d1d5db; }
.link-landing:hover { background: #e5e7eb; color: #374151; }

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

.thumb-preview { width: 80px; height: 80px; object-fit: cover; border-radius: 6px;
    border: 1px solid #e5e7eb; float: right; margin-left: 10px; }
</style>""", unsafe_allow_html=True)

# ── Sidebar ──

with st.sidebar:
    st.markdown("### Creative Radar")
    st.caption("Competitor Intelligence — organic + paid")

# ── Database ──

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

    # To test — organic (with full URLs)
    to_test = []
    for r in conn.execute("""
        SELECT 'organic' as source, op.post_url as url, b.name as brand, b.tier,
               pa.hook_type, pa.format_type, pa.transferability_score as t,
               pa.brand_fit_score as f, pa.analysis_json, op.platform, op.likes,
               op.media_url, NULL as thumbnail_url, NULL as media_url_paid,
               NULL as ad_url_landing, NULL as days_running
        FROM post_analysis pa
        JOIN organic_posts op ON pa.post_id = op.id
        JOIN brands b ON op.brand_id = b.id
        WHERE pa.transferability_score >= 6 AND pa.brand_fit_score >= 6
        ORDER BY (pa.transferability_score + pa.brand_fit_score) DESC LIMIT 15
    """).fetchall():
        analysis = json.loads(r["analysis_json"] or "{}")
        to_test.append(dict(r) | {
            "insight": analysis.get("key_insight", ""),
            "adaptation": analysis.get("cz_adaptation_notes", ""),
        })

    # To test — paid (with media URLs from Foreplay)
    for r in conn.execute("""
        SELECT 'paid' as source, ca.ad_url as url, b.name as brand, b.tier,
               ca.hook_type, ca.format_type, ca.transferability_score as t,
               ca.brand_fit_score as f, ca.analysis_json, 'meta_ads' as platform,
               ca.days_running as likes,
               NULL as media_url,
               ca.thumbnail_url, ca.media_url as media_url_paid,
               ca.ad_url as ad_url_landing, ca.days_running
        FROM competitor_ads ca
        JOIN brands b ON ca.brand_id = b.id
        WHERE ca.transferability_score >= 6 AND ca.brand_fit_score >= 6
        ORDER BY (ca.transferability_score + ca.brand_fit_score) DESC LIMIT 15
    """).fetchall():
        analysis = json.loads(r["analysis_json"] or "{}")
        to_test.append(dict(r) | {
            "insight": analysis.get("key_insight", ""),
            "adaptation": analysis.get("cz_adaptation_notes", ""),
        })

    to_test.sort(key=lambda x: (x["t"] or 0) + (x["f"] or 0), reverse=True)
    data["to_test"] = to_test[:15]

    # All organic posts for browsing
    data["all_organic"] = [dict(r) for r in conn.execute("""
        SELECT op.post_url, b.name as brand, b.tier, op.platform, op.likes, op.comments,
               op.post_type, op.caption,
               pa.hook_type, pa.format_type, pa.energy_level, pa.visual_style,
               pa.transferability_score as t, pa.brand_fit_score as f,
               pa.food_visible, pa.person_present, pa.analysis_json
        FROM organic_posts op
        LEFT JOIN post_analysis pa ON pa.post_id = op.id
        LEFT JOIN brands b ON op.brand_id = b.id
        ORDER BY op.likes DESC
    """).fetchall()]

    # All paid ads for browsing
    data["all_paid"] = [dict(r) for r in conn.execute("""
        SELECT ca.ad_url, ca.media_url, ca.thumbnail_url, b.name as brand, b.tier,
               ca.hook_type, ca.format_type, ca.transferability_score as t,
               ca.brand_fit_score as f, ca.days_running, ca.first_seen, ca.last_seen,
               ca.is_longevity_winner, ca.analysis_json
        FROM competitor_ads ca
        LEFT JOIN brands b ON ca.brand_id = b.id
        ORDER BY ca.days_running DESC
    """).fetchall()]

    # Brand activity
    data["brand_activity"] = [dict(r) for r in conn.execute("""
        SELECT b.name, b.tier, b.ig_handle, b.website,
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

# ── Sidebar filters ──

with st.sidebar:
    st.markdown("---")
    st.markdown("#### Filtry")
    brand_names = sorted(set(
        [i["brand"] for i in data["to_test"]] +
        [i["brand"] for i in data["all_organic"]] +
        [i["brand"] for i in data["all_paid"]]
    ))
    selected_brands = st.multiselect("Brandy", brand_names, default=[])
    source_filter = st.radio("Zdroj", ["Vsechny", "Organic", "Paid"], horizontal=True)
    min_score = st.slider("Min. skore (T+F)", 0, 20, 12)

# ── KPIs ──

k1, k2, k3, k4 = st.columns(4)
k1.metric("Organic posty", data["organic"])
k2.metric("Paid ads (Foreplay)", data["paid"])
k3.metric("Analyzovano", data["analyzed_organic"] + data["analyzed_paid"])
k4.metric("Vysoky Brand Fit", data["high_fit"])

st.divider()

# ══════════════════════════════════════════════════════
# K OTESTOVANI — top concepts with prominent links
# ══════════════════════════════════════════════════════

st.markdown("### K otestovani")
st.caption("Koncepty od konkurence s vysokym transferability + brand fit skore — klikni na odkazy pro ukazky")

if data["to_test"]:
    # Apply filters
    items = data["to_test"]
    if selected_brands:
        items = [i for i in items if i["brand"] in selected_brands]
    if source_filter == "Organic":
        items = [i for i in items if i["source"] == "organic"]
    elif source_filter == "Paid":
        items = [i for i in items if i["source"] == "paid"]
    items = [i for i in items if ((i["t"] or 0) + (i["f"] or 0)) >= min_score]

    for item in items:
        source_cls = "source-organic" if item["source"] == "organic" else "source-paid"
        source_lbl = "organic" if item["source"] == "organic" else "paid"

        t_score = item["t"] or 0
        f_score = item["f"] or 0
        t_cls = "score-high" if t_score >= 8 else "score-mid" if t_score >= 6 else "score-low"
        f_cls = "score-high" if f_score >= 8 else "score-mid" if f_score >= 6 else "score-low"

        hook = item.get("hook_type") or "—"
        insight = (item.get("insight") or "")[:200]
        adaptation = (item.get("adaptation") or "")[:200]

        # Build link buttons
        links_html = '<div class="totest-links">'

        if item["source"] == "organic":
            url = item.get("url") or ""
            if url:
                links_html += (f'<a class="totest-link link-post" href="{url}" '
                               f'target="_blank">&#x1f517; Instagram post</a>')
        else:
            # Paid ad — multiple links available
            media = item.get("media_url_paid") or ""
            thumb = item.get("thumbnail_url") or ""
            landing = item.get("ad_url_landing") or ""
            days = item.get("days_running") or 0

            if media:
                links_html += (f'<a class="totest-link link-video" href="{media}" '
                               f'target="_blank">&#x25b6; Video/kreativa</a>')
            if thumb:
                links_html += (f'<a class="totest-link link-thumb" href="{thumb}" '
                               f'target="_blank">&#x1f5bc; Thumbnail</a>')
            if landing:
                links_html += (f'<a class="totest-link link-landing" href="{landing}" '
                               f'target="_blank">&#x1f310; Landing page</a>')

        links_html += '</div>'

        # Days running badge for paid
        days_html = ""
        if item["source"] == "paid" and item.get("days_running"):
            days = item["days_running"]
            days_html = (f'<span style="font-size:0.72em;color:#6b7280;margin-left:6px">'
                         f'{days} dni aktivni</span>')

        # Thumbnail preview for paid
        thumb_img = ""
        if item["source"] == "paid" and item.get("thumbnail_url"):
            thumb_img = (f'<img class="thumb-preview" src="{item["thumbnail_url"]}" '
                         f'alt="preview" onerror="this.style.display=\'none\'">')

        st.markdown(f"""<div class="totest-card">
{thumb_img}
<span class="source-badge {source_cls}">{source_lbl}</span>
<span class="totest-brand">{item['brand']}</span>
<span class="totest-hook">{hook}</span>
<span class="score-pill {t_cls}">T{t_score:.0f}</span>
<span class="score-pill {f_cls}">F{f_score:.0f}</span>
{days_html}
<div class="totest-insight">{insight}</div>
{f'<div class="totest-adapt">Adaptace CZ: {adaptation}</div>' if adaptation else ''}
{links_html}
</div>""", unsafe_allow_html=True)

    if not items:
        st.info("Zadne vysledky pro zvolene filtry.")
else:
    st.info("Zadne koncepty s dostatecnym skore. Spust `competitor_analyzer.py`.")

st.divider()

# ══════════════════════════════════════════════════════
# BROWSE ALL — tabulky s prokliky
# ══════════════════════════════════════════════════════

tab1, tab2 = st.tabs(["Organic posty", "Paid ads"])

with tab1:
    st.markdown("#### Vsechny organic posty")
    organic = data["all_organic"]
    if selected_brands:
        organic = [o for o in organic if o["brand"] in selected_brands]

    if organic:
        rows = []
        for o in organic:
            analysis = json.loads(o.get("analysis_json") or "{}")
            rows.append({
                "Brand": o["brand"],
                "Hook": o.get("hook_type") or "—",
                "Format": o.get("format_type") or "—",
                "Energy": o.get("energy_level") or "—",
                "T": o.get("t") or 0,
                "F": o.get("f") or 0,
                "Likes": o.get("likes") or 0,
                "Post": o["post_url"] or "",
            })

        df_org = pd.DataFrame(rows)
        st.dataframe(
            df_org, use_container_width=True, hide_index=True,
            column_config={
                "T": st.column_config.NumberColumn("Transfer", format="%.0f", width="small"),
                "F": st.column_config.NumberColumn("Brand Fit", format="%.0f", width="small"),
                "Likes": st.column_config.NumberColumn(format="%d"),
                "Post": st.column_config.LinkColumn("Odkaz", display_text="Zobrazit"),
            },
        )
    else:
        st.info("Zadne organic posty.")

with tab2:
    st.markdown("#### Vsechny paid ads (Foreplay)")
    paid = data["all_paid"]
    if selected_brands:
        paid = [p for p in paid if p["brand"] in selected_brands]

    if paid:
        rows = []
        for p in paid:
            rows.append({
                "Brand": p["brand"],
                "Hook": p.get("hook_type") or "—",
                "Format": p.get("format_type") or "—",
                "T": p.get("t") or 0,
                "F": p.get("f") or 0,
                "Dni": p.get("days_running") or 0,
                "Od": (p.get("first_seen") or "")[:10],
                "Kreativa": p.get("media_url") or "",
                "Thumbnail": p.get("thumbnail_url") or "",
                "Landing": p.get("ad_url") or "",
            })

        df_paid = pd.DataFrame(rows)
        st.dataframe(
            df_paid, use_container_width=True, hide_index=True,
            column_config={
                "T": st.column_config.NumberColumn("Transfer", format="%.0f", width="small"),
                "F": st.column_config.NumberColumn("Brand Fit", format="%.0f", width="small"),
                "Dni": st.column_config.NumberColumn("Dni aktivni", format="%d"),
                "Kreativa": st.column_config.LinkColumn("Video/img", display_text="Prehrat"),
                "Thumbnail": st.column_config.LinkColumn("Thumb", display_text="Zobrazit"),
                "Landing": st.column_config.LinkColumn("Landing", display_text="Web"),
            },
        )
    else:
        st.info("Zadne paid ads.")

st.divider()

# ══════════════════════════════════════════════════════
# BRAND ACTIVITY
# ══════════════════════════════════════════════════════

st.markdown("### Aktivita brandu")

if data["brand_activity"]:
    rows = []
    for b in data["brand_activity"]:
        tier = b["tier"]
        tier_lbl = {"us_dtc": "US DTC", "eu": "EU", "cz": "CZ"}.get(tier, tier)
        ig = b.get("ig_handle") or ""
        ig_link = f"https://instagram.com/{ig}" if ig else ""
        rows.append({
            "Brand": b["name"],
            "Tier": tier_lbl,
            "Organic": b["organic"],
            "Paid": b["paid"],
            "Likes": b["likes"],
            "Instagram": ig_link,
            "Web": b.get("website") or "",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Likes": st.column_config.NumberColumn(format="%d"),
                     "Instagram": st.column_config.LinkColumn("IG", display_text="Profil"),
                     "Web": st.column_config.LinkColumn("Web", display_text="Web"),
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

    cols[-1].markdown(f"""<div class="radar-stat">
<div class="radar-stat-label">Foreplay</div>
<div class="radar-stat-value">{data['paid']}</div>
<div style="font-size:0.75em;color:#6b7280">paid ads</div>
</div>""", unsafe_allow_html=True)
