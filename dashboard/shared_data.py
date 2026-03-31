"""Shared data loading, constants and helpers for all dashboard pages."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).parent
REPO_ROOT = DASHBOARD_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))

import creative_intelligence as ci

# ── Constants ──

COLORS = {"KILL": "#e53e3e", "SCALE": "#38a169", "ITERATE": "#d69e2e", "WATCH": "#3182ce", "OK": "#a0aec0", "INFO": "#cbd5e0"}
EMOJI = {"KILL": "🔴", "SCALE": "🟢", "ITERATE": "🟡", "WATCH": "🔵", "OK": "⚪", "INFO": "⚪"}
CZ = {"KILL": "Zastavit", "SCALE": "Skalovat", "ITERATE": "Upravit", "WATCH": "Sledovat", "OK": "OK", "INFO": "Info"}
CONF_DOT = {"vysoka": "●", "stredni": "◐", "nizka": "○"}

# ── Helpers ──

def kc(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "—"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.1f} M Kc"
    if abs(v) >= 1_000: return f"{v/1_000:.0f} K Kc"
    return f"{v:.0f} Kc"

def pct(v):
    return f"{v:.1f} %" if v is not None and not (isinstance(v, float) and pd.isna(v)) else "—"

def conf_badge(level):
    cls = {"vysoka": "conf-high", "stredni": "conf-med", "nizka": "conf-low"}.get(level, "conf-low")
    label = CONF_DOT.get(level, "○")
    return f'<span class="{cls}" title="Spolehlivost: {level}">{label}</span>'

# ── Data loading ──

@st.cache_data(ttl=1800, show_spinner="Nacitam data z Meta API...")
def load_data(days):
    raw = ci.fetch_ad_insights(days)
    metrics = [ci.calculate_metrics(row) for row in raw]
    for m in metrics:
        recs = ci.evaluate_creative(m)
        for p in ["KILL", "ITERATE", "SCALE", "WATCH", "OK", "INFO"]:
            if p in [r[0] for r in recs]:
                m["action"] = p
                m["action_reasons"] = [r[1] for r in recs if r[0] == p]
                break
        else:
            m["action"] = "OK"
            m["action_reasons"] = []
    return pd.DataFrame(metrics)

def load_snapshots():
    import duckdb
    db_path = DATA_DIR / "fermato_analytics.duckdb"
    if not db_path.exists(): return []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute("""
            SELECT data, created_at::VARCHAR[:10] as date
            FROM cache.snapshots
            WHERE name = 'creative_daily'
            ORDER BY created_at DESC
            LIMIT 30
        """).df()
        return [{"data": json.loads(row["data"]), "date": row["date"]} for _, row in df.iterrows()]
    except Exception:
        return []
    finally:
        con.close()

def load_ai():
    import duckdb, sqlite3
    # creative_analysis.db zustava v SQLite (neni soucasti migrace — separatni pipeline)
    p = DATA_DIR / "creative_analysis.db"
    if not p.exists(): return {}
    conn = sqlite3.connect(str(p)); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM creative_analyses ORDER BY analyzed_at DESC").fetchall()
    conn.close()
    out = {}
    for r in rows:
        if r["ad_id"] not in out:
            out[r["ad_id"]] = {
                "hook": json.loads(r["hook_analysis"]) if r["hook_analysis"] else None,
                "full": json.loads(r["full_analysis"]) if r["full_analysis"] else None,
                "transcript": r["transcript"],
                "creative_type": r["creative_type"],
                "at": r["analyzed_at"][:10],
            }
    return out

# ── Filters (shared sidebar) ──

def setup_sidebar():
    """Shared sidebar setup. Returns (days, df, snaps, ai_data)."""
    with st.sidebar:
        st.markdown("### 🎯 Creative Intelligence")
        days = st.selectbox("Obdobi", [7, 14, 30], index=1, format_func=lambda x: f"{x} dni", key="days_select")
        if st.button("Obnovit data", use_container_width=True, type="primary"):
            st.cache_data.clear(); st.rerun()
        st.divider()

    df = load_data(days)
    snaps = load_snapshots()
    ai_data = load_ai()

    camps = sorted(df["campaign_name"].unique())
    sel_camps = st.sidebar.multiselect("Kampane", camps, default=camps, key="camp_filter")
    df = df[df["campaign_name"].isin(sel_camps)]

    show_low_conf = st.sidebar.checkbox("Nizka spolehlivost", value=False, key="low_conf",
                                         help="Zobrazit i kreativy s nedostatkem dat")

    st.sidebar.divider()
    n_video = len(df[df["is_video"]])
    n_static = len(df[~df["is_video"]])
    st.sidebar.caption(f"🎬 {n_video} video · 📸 {n_static} statickych · {datetime.now().strftime('%d.%m. %H:%M')}")

    return days, df, snaps, ai_data, show_low_conf

# ── Shared CSS ──

SHARED_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

.block-container { padding-top: 1rem; max-width: 1200px; }
html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }

/* KPI karty — light theme, nebojuje se Streamlitem */
[data-testid="stMetric"] {
    background: #f8f9fb;
    border-radius: 10px; padding: 12px 14px;
    border: 1px solid #e8ecf1;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    overflow: visible !important;
}
[data-testid="stMetric"] label {
    color: #6b7280 !important; font-size: 0.72em !important;
    text-transform: uppercase; letter-spacing: 0.04em;
    white-space: nowrap !important; overflow: visible !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #1a202c !important; font-weight: 700;
    font-size: 1.5rem !important;
    white-space: nowrap !important; overflow: visible !important;
}
[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    white-space: nowrap !important; overflow: visible !important;
    font-size: 0.78em !important;
}

/* Spolehlivost badgy */
.conf-high { color: #38a169; font-weight: bold; }
.conf-med { color: #d69e2e; font-weight: bold; }
.conf-low { color: #999; }

/* Action karty */
.act-box {
    border-radius: 8px; padding: 10px 12px; margin: 5px 0;
    font-size: 0.84em; line-height: 1.45;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.act-box:hover { transform: translateY(-1px); box-shadow: 0 3px 10px rgba(0,0,0,0.08); }
.act-kill { background: #fff5f5; border-left: 3px solid #e53e3e; }
.act-scale { background: #f0fff4; border-left: 3px solid #38a169; }
.act-iterate { background: #fffff0; border-left: 3px solid #d69e2e; }

/* Info bannery */
.reliability-banner {
    background: #eef2ff;
    border-left: 4px solid #6366f1; border-radius: 8px;
    padding: 10px 14px; margin: 8px 0; font-size: 0.82em; color: #4338ca;
}

/* Health karty */
.health-card {
    background: #f8f9fb; border: 1px solid #e8ecf1;
    border-radius: 10px; padding: 16px 12px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.health-label { font-size: 0.78em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; }
.health-value { font-size: 1.8em; font-weight: 700; color: #1a202c; margin: 6px 0 4px; }
.health-sub { font-size: 0.82em; color: #9ca3af; }

/* Dropoff vizualizace */
.dropoff-bar {
    height: 32px; border-radius: 6px; display: inline-flex; align-items: center;
    padding: 0 12px; font-size: 0.8em; font-weight: 600; color: #fff; margin: 3px 0;
    min-width: 120px;
}
.dropoff-hook { background: linear-gradient(90deg, #e53e3e, #fc8181); }
.dropoff-mid { background: linear-gradient(90deg, #d69e2e, #f6e05e); color: #744210; }
.dropoff-cta { background: linear-gradient(90deg, #3182ce, #63b3ed); }
.dropoff-ok { background: linear-gradient(90deg, #38a169, #68d391); }

/* Clickbait alert */
.clickbait-alert {
    background: #fff5f5; border: 1px solid #feb2b2;
    border-radius: 8px; padding: 10px 14px; margin: 8px 0;
    font-size: 0.85em; color: #c53030;
}
</style>"""

def render_action_cards(df, min_conf, show_label=""):
    """Renders KILL/SCALE/ITERATE action columns."""
    kill_df = df[(df["action"] == "KILL") & (df["confidence"] >= min_conf)].nlargest(4, "spend")
    scale_df = df[(df["action"] == "SCALE") & (df["confidence"] >= min_conf)].nlargest(4, "weighted_roas")
    iter_df = df[(df["action"] == "ITERATE") & (df["confidence"] >= min_conf)].nlargest(4, "spend")

    a1, a2, a3 = st.columns(3)
    with a1:
        n = len(df[(df["action"] == "KILL") & (df["confidence"] >= min_conf)])
        waste = df[(df["action"] == "KILL") & (df["confidence"] >= min_conf)]["spend"].sum()
        st.markdown(f"**🔴 Zastavit** · {n} kreativ · {kc(waste)}")
        for _, ad in kill_df.iterrows():
            reasons = ad.get("action_reasons", [])
            r = reasons[0][:55] if reasons else ""
            typ = "🎬" if ad["is_video"] else "📸"
            cvr_str = f" · CVR {ad['cvr']:.1f}%" if pd.notna(ad.get('cvr')) else ""
            st.markdown(f"""<div class="act-box act-kill">
{conf_badge(ad['confidence_level'])} {typ} <strong>{ad['ad_name'][:26]}</strong><br>
{kc(ad['spend'])} · ROAS {ad['roas'] or 0:.2f}{cvr_str} · {int(ad['purchases'])} nakupu<br>
<small style="color:#888">{r}</small></div>""", unsafe_allow_html=True)

    with a2:
        n = len(df[(df["action"] == "SCALE") & (df["confidence"] >= min_conf)])
        st.markdown(f"**🟢 Skalovat** · {n} kreativ")
        for _, ad in scale_df.iterrows():
            typ = "🎬" if ad["is_video"] else "📸"
            cvr_str = f" · CVR {ad['cvr']:.1f}%" if pd.notna(ad.get('cvr')) else ""
            st.markdown(f"""<div class="act-box act-scale">
{conf_badge(ad['confidence_level'])} {typ} <strong>{ad['ad_name'][:26]}</strong><br>
ROAS {ad['roas'] or 0:.2f} · CPA {kc(ad['cpa'])}{cvr_str} · {int(ad['purchases'])} nakupu</div>""", unsafe_allow_html=True)

    with a3:
        n = len(df[(df["action"] == "ITERATE") & (df["confidence"] >= min_conf)])
        st.markdown(f"**🟡 Upravit** · {n} kreativ")
        for _, ad in iter_df.iterrows():
            reasons = ad.get("action_reasons", [])
            r = reasons[0][:55] if reasons else ""
            typ = "🎬" if ad["is_video"] else "📸"
            st.markdown(f"""<div class="act-box act-iterate">
{conf_badge(ad['confidence_level'])} {typ} <strong>{ad['ad_name'][:26]}</strong><br>
{kc(ad['spend'])} · {int(ad['purchases'])} nakupu<br>
<small style="color:#888">{r}</small></div>""", unsafe_allow_html=True)
