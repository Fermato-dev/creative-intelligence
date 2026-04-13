"""Shared data loading, constants and helpers for all dashboard pages."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).parent
REPO_ROOT = DASHBOARD_DIR.parent
DATA_DIR = REPO_ROOT / "data"

# Import from creative_intelligence package
sys.path.insert(0, str(REPO_ROOT))
from creative_intelligence.metrics import fetch_ad_insights, calculate_metrics
from creative_intelligence.rules import evaluate_creative
from creative_intelligence.config import TARGET_ROAS, TARGET_CPA, MIN_SPEND_FOR_DECISION

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
    try:
        raw = fetch_ad_insights(days)
    except Exception as e:
        st.warning(f"Meta API nedostupne: {e}")
        return pd.DataFrame()
    metrics = [calculate_metrics(row) for row in raw]
    for m in metrics:
        recs = evaluate_creative(m)
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
    """Load snapshots — returns empty list if duckdb not available (Railway)."""
    try:
        import duckdb
    except ImportError:
        return []
    db_path = DATA_DIR / "fermato_analytics.duckdb"
    if not db_path.exists():
        return []
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        df = con.execute("""
            SELECT data, created_at::VARCHAR[:10] as date
            FROM cache.snapshots
            WHERE name = 'creative_daily'
            ORDER BY created_at DESC
            LIMIT 30
        """).df()
        con.close()
        return [{"data": json.loads(row["data"]), "date": row["date"]} for _, row in df.iterrows()]
    except Exception as e:
        print(f"WARN: snapshot load failed: {e}", file=sys.stderr)
        return []

def load_ai():
    """Load component library data (v3 schema)."""
    import sqlite3
    p = DATA_DIR / "creative_analysis.db"
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        # v3: read from components table
        rows = conn.execute(
            "SELECT * FROM components ORDER BY analyzed_at DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    out = {}
    for r in rows:
        ad_id = r["ad_id"]
        comp_type = r["component_type"]
        if ad_id not in out:
            out[ad_id] = {}
        analysis = None
        if r["analysis"]:
            try:
                analysis = json.loads(r["analysis"])
            except json.JSONDecodeError:
                pass
        out[ad_id][comp_type] = {
            "analysis": analysis,
            "transcript": r["transcript"],
            "roas": r["roas"],
            "hook_rate": r["hook_rate"],
            "hold_rate": r["hold_rate"],
            "spend": r["spend"],
            "at": r["analyzed_at"][:10] if r["analyzed_at"] else None,
        }
    return out

# ── Creative Diversity Tags ──

@st.cache_data(ttl=1800, show_spinner="Nacitam creative tags...")
def load_creative_tags():
    """Load creative diversity tags from SQLite (fallback: JSON).
    Returns DataFrame with archetype, hook_strategy, visual_style, etc."""
    import sqlite3 as _sql

    db = DATA_DIR / "creative_analysis.db"
    if db.exists():
        try:
            conn = _sql.connect(f"file:{db}?mode=ro", uri=True)
            df = pd.read_sql_query("SELECT * FROM creative_tags", conn)
            # v3.5 compat: add aliases
            if "visual_format" in df.columns and "archetype" not in df.columns:
                df["archetype"] = df["visual_format"].str.replace("_", " ")
            if "hook_type" in df.columns and "hook_strategy" not in df.columns:
                df["hook_strategy"] = df["hook_type"].str.replace("_", " ")
            if "production_quality" in df.columns and "visual_style" not in df.columns:
                df["visual_style"] = df["production_quality"]
            # More v3.5 compat aliases
            if "has_person" in df.columns and "person_present" not in df.columns:
                df["person_present"] = df["has_person"].map({1: "yes", True: "yes", 0: "no", False: "no"}).fillna("unknown")
            if "visual_format_confidence" in df.columns and "archetype_confidence" not in df.columns:
                df["archetype_confidence"] = df["visual_format_confidence"]
            if "production_quality" in df.columns:
                # Map Semi_Pro -> semi_professional, UGC -> amateur, Professional -> professional
                pq_map = {"UGC": "amateur", "Semi_Pro": "semi_professional", "Professional": "professional"}
                df["production_quality"] = df["production_quality"].map(pq_map).fillna(df["production_quality"])
            # Join performance
            try:
                perf = pd.read_sql_query(
                    "SELECT ad_id, SUM(spend) as spend, SUM(revenue) as revenue, "
                    "SUM(purchases) as purchases, AVG(hook_rate) as hook_rate, "
                    "AVG(hold_rate) as hold_rate, "
                    "CASE WHEN SUM(spend)>0 THEN SUM(revenue)/SUM(spend) ELSE NULL END as roas, "
                    "CASE WHEN SUM(purchases)>0 THEN SUM(spend)/SUM(purchases) ELSE NULL END as cpa "
                    "FROM ad_daily_snapshots WHERE snapshot_date >= date('now','-14 days') "
                    "GROUP BY ad_id", conn)
                if len(perf) > 0:
                    df = df.merge(perf, on="ad_id", how="left", suffixes=("","_p"))
                    for c in ["spend","revenue","purchases","hook_rate","hold_rate","roas","cpa"]:
                        if c+"_p" in df.columns:
                            df[c] = df[c+"_p"].combine_first(df.get(c))
                            df.drop(columns=[c+"_p"], inplace=True)
            except Exception:
                pass
            if len(df) > 0:
                # Ensure spend column exists with default
                for col in ["spend","revenue","purchases","hook_rate","hold_rate","roas","cpa"]:
                    if col not in df.columns:
                        df[col] = 0 if col in ("spend","revenue","purchases") else None
                conn.close()
                return df
            conn.close()
        except Exception:
            pass

    # Fallback: search for JSON files
    search_dirs = [
        DATA_DIR,
        REPO_ROOT.parent / "Chief-of-Staff" / "scripts" / "analysis",
        Path.home() / "Chief-of-Staff" / "scripts" / "analysis",
    ]
    for d in search_dirs:
        if d.exists():
            for f in sorted(d.glob("*precise_tags_output*.json"), reverse=True):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    return pd.DataFrame(data)
                except Exception:
                    continue

    return pd.DataFrame()


# ── Filters (shared sidebar) ──

def setup_sidebar():
    """Shared sidebar setup. Returns (days, df, snaps, ai_data, show_low_conf)."""
    with st.sidebar:
        st.markdown("### Creative Intelligence")
        days = st.selectbox("Obdobi", [7, 14, 30], index=1, format_func=lambda x: f"{x} dni", key="days_select")
        if st.button("Obnovit data", use_container_width=True, type="primary"):
            st.cache_data.clear(); st.rerun()
        st.divider()

    df = load_data(days)
    snaps = load_snapshots()
    ai_data = load_ai()

    if len(df) == 0:
        return days, df, snaps, ai_data, False

    camps = sorted(df["campaign_name"].unique())
    sel_camps = st.sidebar.multiselect("Kampane", camps, default=camps, key="camp_filter")
    df = df[df["campaign_name"].isin(sel_camps)]

    show_low_conf = st.sidebar.checkbox("Nizka spolehlivost", value=False, key="low_conf",
                                         help="Zobrazit i kreativy s nedostatkem dat")

    st.sidebar.divider()
    n_video = len(df[df["is_video"]])
    n_static = len(df[~df["is_video"]])
    st.sidebar.caption(f"{n_video} video · {n_static} statickych · {datetime.now().strftime('%d.%m. %H:%M')}")

    return days, df, snaps, ai_data, show_low_conf

# ── Shared CSS ──

SHARED_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

.block-container { padding-top: 1rem; max-width: 1200px; }
html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }

[data-testid="stMetric"] {
    background: #f8f9fb; border-radius: 10px; padding: 12px 14px;
    border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    overflow: visible !important;
}
[data-testid="stMetric"] label { color: #6b7280 !important; font-size: 0.72em !important;
    text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap !important; overflow: visible !important; }
[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #1a202c !important; font-weight: 700;
    font-size: 1.5rem !important; white-space: nowrap !important; overflow: visible !important; }
[data-testid="stMetric"] [data-testid="stMetricDelta"] { white-space: nowrap !important; overflow: visible !important; font-size: 0.78em !important; }

.conf-high { color: #38a169; font-weight: bold; }
.conf-med  { color: #d69e2e; font-weight: bold; }
.conf-low  { color: #999; }

/* ── Action cards — self-contained colors, no inheritance ── */
.act-box {
    border-radius: 8px; padding: 10px 14px; margin: 5px 0;
    font-size: 0.84em; line-height: 1.5;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.act-box:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.10); }

.act-kill {
    background: #fef2f2; border-left: 3px solid #dc2626;
    color: #1a202c !important;
}
.act-kill strong { color: #111827 !important; }
.act-kill small  { color: #6b7280 !important; }
.act-kill *      { color: inherit; }

.act-scale {
    background: #f0fdf4; border-left: 3px solid #16a34a;
    color: #1a202c !important;
}
.act-scale strong { color: #111827 !important; }
.act-scale small  { color: #166534 !important; }
.act-scale *      { color: inherit; }

.act-iterate {
    background: #fefce8; border-left: 3px solid #ca8a04;
    color: #1a202c !important;
}
.act-iterate strong { color: #111827 !important; }
.act-iterate small  { color: #6b7280 !important; }
.act-iterate *      { color: inherit; }

/* ── Reliability / info banners ── */
.reliability-banner {
    background: #eef2ff; border-left: 4px solid #6366f1; border-radius: 8px;
    padding: 10px 14px; margin: 8px 0; font-size: 0.82em;
    color: #3730a3 !important;
}
.reliability-banner * { color: #3730a3 !important; }
.reliability-banner strong { color: #312e81 !important; }

/* ── Health cards ── */
.health-card {
    background: #f8f9fb; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 16px 12px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.health-label { font-size: 0.78em; color: #6b7280 !important; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; }
.health-value { font-size: 1.8em; font-weight: 700; color: #1a202c !important; margin: 6px 0 4px; }
.health-sub   { font-size: 0.82em; color: #9ca3af !important; }

/* ── Video dropoff bars — no white on yellow ── */
.dropoff-bar {
    height: 32px; border-radius: 6px; display: inline-flex; align-items: center;
    padding: 0 12px; font-size: 0.8em; font-weight: 600; margin: 3px 0; min-width: 120px;
}
.dropoff-hook { background: #dc2626; color: #fff !important; }
.dropoff-mid  { background: #d97706; color: #fff !important; }
.dropoff-cta  { background: #2563eb; color: #fff !important; }
.dropoff-ok   { background: #16a34a; color: #fff !important; }

.clickbait-alert {
    background: #fef2f2; border: 1px solid #fca5a5; border-radius: 8px;
    padding: 10px 14px; margin: 8px 0; font-size: 0.85em;
    color: #b91c1c !important;
}
.clickbait-alert * { color: #b91c1c !important; }
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
        st.markdown(f"**Zastavit** · {n} kreativ · {kc(waste)}")
        for _, ad in kill_df.iterrows():
            reasons = ad.get("action_reasons", [])
            r = reasons[0][:55] if reasons else ""
            cvr_str = f" · CVR {ad['cvr']:.1f}%" if pd.notna(ad.get('cvr')) else ""
            st.markdown(f"""<div class="act-box act-kill">
{conf_badge(ad['confidence_level'])} <strong>{ad['ad_name'][:26]}</strong><br>
{kc(ad['spend'])} · ROAS {ad['roas'] or 0:.2f}{cvr_str} · {int(ad['purchases'])} nakupu<br>
<small style="color:#888">{r}</small></div>""", unsafe_allow_html=True)

    with a2:
        n = len(df[(df["action"] == "SCALE") & (df["confidence"] >= min_conf)])
        st.markdown(f"**Skalovat** · {n} kreativ")
        for _, ad in scale_df.iterrows():
            cvr_str = f" · CVR {ad['cvr']:.1f}%" if pd.notna(ad.get('cvr')) else ""
            st.markdown(f"""<div class="act-box act-scale">
{conf_badge(ad['confidence_level'])} <strong>{ad['ad_name'][:26]}</strong><br>
ROAS {ad['roas'] or 0:.2f} · CPA {kc(ad['cpa'])}{cvr_str} · {int(ad['purchases'])} nakupu</div>""", unsafe_allow_html=True)

    with a3:
        n = len(df[(df["action"] == "ITERATE") & (df["confidence"] >= min_conf)])
        st.markdown(f"**Upravit** · {n} kreativ")
        for _, ad in iter_df.iterrows():
            reasons = ad.get("action_reasons", [])
            r = reasons[0][:55] if reasons else ""
            st.markdown(f"""<div class="act-box act-iterate">
{conf_badge(ad['confidence_level'])} <strong>{ad['ad_name'][:26]}</strong><br>
{kc(ad['spend'])} · {int(ad['purchases'])} nakupu<br>
<small style="color:#888">{r}</small></div>""", unsafe_allow_html=True)
