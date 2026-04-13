"""Fermato Creative Intelligence — Campaign Health & Goal Tracker"""

import calendar
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Campaign Health", page_icon="🏁", layout="wide")

# ── Auth & imports ──
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    st.stop()

from shared_data import *  # adds REPO_ROOT to sys.path

try:
    from creative_intelligence.meta_client import meta_fetch, meta_fetch_all, AD_ACCOUNT_ID
except ImportError:
    from meta_client import meta_fetch, meta_fetch_all, AD_ACCOUNT_ID

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── Extra CSS — explicit colors on everything so dark mode works ──
st.markdown("""<style>
/* ── Severity banners ── */
.severity-critical {
    background:#fef2f2; border:2px solid #dc2626; border-radius:12px;
    padding:16px 20px; margin-bottom:8px;
}
.severity-critical, .severity-critical * { color:#7f1d1d !important; }
.severity-critical .sev-detail { color:#991b1b !important; }

.severity-off {
    background:#fff7ed; border:2px solid #ea580c; border-radius:12px;
    padding:16px 20px; margin-bottom:8px;
}
.severity-off, .severity-off * { color:#7c2d12 !important; }
.severity-off .sev-detail { color:#9a3412 !important; }

.severity-watch {
    background:#fefce8; border:2px solid #ca8a04; border-radius:12px;
    padding:16px 20px; margin-bottom:8px;
}
.severity-watch, .severity-watch * { color:#713f12 !important; }
.severity-watch .sev-detail { color:#854d0e !important; }

.severity-ok {
    background:#f0fdf4; border:2px solid #16a34a; border-radius:12px;
    padding:16px 20px; margin-bottom:8px;
}
.severity-ok, .severity-ok * { color:#14532d !important; }
.severity-ok .sev-detail { color:#166534 !important; }

.sev-title  { font-size:1.05em; font-weight:700; }
.sev-detail { font-size:0.86em; margin-top:4px; opacity:0.85; }

/* ── Diagnosis & info boxes ── */
.median-diagnosis {
    background:#eef2ff; border-left:4px solid #6366f1; border-radius:8px;
    padding:12px 16px; font-size:0.87em; line-height:1.55;
}
.median-diagnosis, .median-diagnosis * { color:#3730a3 !important; }
.median-diagnosis strong { color:#312e81 !important; }

/* ── Callout cards ── */
.callout-card {
    border-radius:10px; padding:12px 16px; margin:5px 0;
    border-left:4px solid; font-size:0.84em; line-height:1.5;
}
.callout-card strong { font-weight:700; }

.callout-ll { background:#fef2f2; border-left-color:#dc2626; }
.callout-ll, .callout-ll * { color:#7f1d1d !important; }
.callout-ll strong { color:#7f1d1d !important; }

.callout-fat { background:#fff7ed; border-left-color:#ea580c; }
.callout-fat, .callout-fat * { color:#7c2d12 !important; }
.callout-fat strong { color:#7c2d12 !important; }

.callout-eff { background:#f0fdf4; border-left-color:#16a34a; }
.callout-eff, .callout-eff * { color:#14532d !important; }
.callout-eff strong { color:#14532d !important; }

.callout-seasonal { background:#faf5ff; border-left-color:#7c3aed; }
.callout-seasonal, .callout-seasonal * { color:#4c1d95 !important; }
.callout-seasonal strong { color:#4c1d95 !important; }

/* ── Progress bars ── */
.prog-wrap { background:#e2e8f0; border-radius:6px; height:9px; overflow:hidden; margin:3px 0 8px; }
.prog-fill { height:9px; border-radius:6px; }

/* ── Goal derived ── */
.goal-derived {
    background:#eef2ff; border-radius:8px; padding:8px 12px;
    font-size:0.82em; margin-top:4px;
}
.goal-derived, .goal-derived * { color:#3730a3 !important; }

/* ── Threshold info pill ── */
.watch-info {
    background:#1e293b; border-radius:6px; padding:5px 12px;
    font-size:0.78em; color:#94a3b8 !important;
    display:inline-block; margin-bottom:8px;
}
.watch-info strong { color:#e2e8f0 !important; }

/* ── Badge chips ── */
.adset-fail { display:inline-block; background:#dc2626; color:#fff !important;
    font-size:0.7em; font-weight:700; padding:1px 7px; border-radius:4px; }
.adset-ok   { display:inline-block; background:#16a34a; color:#fff !important;
    font-size:0.7em; font-weight:700; padding:1px 7px; border-radius:4px; }
.fatigue-tag { display:inline-block; background:#ea580c; color:#fff !important;
    font-size:0.7em; font-weight:700; padding:1px 7px; border-radius:4px; }
</style>""", unsafe_allow_html=True)

# ── Standard sidebar ──
days, df_all, snaps, ai_data, show_low_conf = setup_sidebar()
min_conf = 0.0 if show_low_conf else 0.3

# ── Goal inputs in sidebar ──
with st.sidebar:
    st.divider()
    st.markdown("### Cíle")

    target_roas = st.number_input(
        "Target ROAS", min_value=0.5, max_value=10.0, value=3.0, step=0.1,
        help="Cílový ROAS — říká jak agresivně škrtat a škálovat")
    aov = st.number_input(
        "AOV (Kč)", min_value=100, max_value=10000, value=1000, step=50,
        help="Průměrná hodnota objednávky")
    max_cpa = aov / target_roas
    st.markdown(
        f'<div class="goal-derived">→ Max CPA indikátor: <strong>{max_cpa:.0f} Kč</strong>'
        f'<br><small>= AOV {aov} ÷ ROAS {target_roas:.1f}</small></div>',
        unsafe_allow_html=True)

    st.markdown("")
    monthly_order_goal = st.number_input(
        "Cíl objednávek / měsíc", min_value=0, value=0, step=10,
        help="Nech 0 pro přeskočení")
    monthly_budget = st.number_input(
        "Měsíční budget (Kč)", min_value=0, value=0, step=1000,
        help="Nech 0 pro přeskočení")

    # Seasonal campaign selector
    st.divider()
    st.markdown("### Sezónní / akce")
    seasonal_camps = []
    if len(df_all) > 0:
        all_camps = sorted(df_all["campaign_name"].unique())
        seasonal_camps = st.multiselect(
            "Časově omezené kampaně",
            all_camps,
            default=[],
            help="Kampaně kratší než týden nebo flash akce — zobrazí se zvlášť, jiná pravidla",
            key="seasonal_select",
        )


# ── API helpers ──

@st.cache_data(ttl=900, show_spinner="Načítám MTD data...")
def fetch_mtd():
    try:
        resp = meta_fetch(f"{AD_ACCOUNT_ID}/insights", {
            "fields": "spend,actions,action_values",
            "date_preset": "this_month",
            "level": "account",
        })
        d = (resp.get("data") or [{}])[0]
        spend = float(d.get("spend", 0))
        purchases, revenue = 0, 0.0
        for a in d.get("actions", []):
            if a["action_type"] in ("purchase", "omni_purchase"):
                purchases = max(purchases, int(float(a["value"])))
        for a in d.get("action_values", []):
            if a["action_type"] in ("purchase", "omni_purchase"):
                revenue = max(revenue, float(a["value"]))
        return {"spend": spend, "purchases": purchases, "revenue": revenue, "ok": True}
    except Exception as e:
        return {"spend": 0, "purchases": 0, "revenue": 0, "ok": False, "error": str(e)}


@st.cache_data(ttl=900, show_spinner="Načítám learning stage...")
def fetch_learning():
    try:
        adsets = meta_fetch_all(f"{AD_ACCOUNT_ID}/adsets", {
            "fields": "id,name,effective_status,learning_stage_info",
            "effective_status": '["ACTIVE"]',
            "limit": "100",
        })
        return {str(a["id"]): (a.get("learning_stage_info") or {}).get("status", "unknown")
                for a in adsets}
    except Exception:
        return {}


@st.cache_data(ttl=900, show_spinner="Načítám statusy reklam...")
def fetch_ad_statuses():
    """Returns dict of ad_id -> effective_status for all non-deleted ads."""
    try:
        ads = meta_fetch_all(f"{AD_ACCOUNT_ID}/ads", {
            "fields": "id,effective_status",
            "limit": "200",
        })
        return {str(a["id"]): a.get("effective_status", "UNKNOWN") for a in ads}
    except Exception:
        return {}


# ── Re-evaluation engine (volume-first, percentile-based) ──

def re_evaluate_health(df, target_roas, max_cpa):
    """
    Evaluates ads with volume-first logic:
    - Kill only clear losers (absolute or bottom-percentile)
    - Watch zone = 2.0–2.6 (relative to account median)
    - Scale = ROAS 20%+ above target with confidence
    - Iterate = fixable issues
    Returns df with h_action, h_reasons columns + p10_roas, account_median, watch_lower scalars.
    """
    if len(df) == 0:
        return df.copy(), 0.0, 0.0, 2.0

    df = df.copy()
    roas_vals = df["roas"].dropna()
    n = len(roas_vals)

    p10_roas       = float(roas_vals.quantile(0.10)) if n >= 5 else 1.0
    account_median = float(roas_vals.median())       if n >= 2 else target_roas
    # Watch lower boundary: relative to account median but never below 2.0
    watch_lower    = max(2.0, account_median * 0.70)
    watch_upper    = 2.6

    actions  = []
    reasons  = []

    for _, ad in df.iterrows():
        roas      = float(ad.get("roas") or 0)
        cpa_val   = float(ad.get("cpa") or 0)
        spend     = float(ad.get("spend") or 0)
        purchases = int(ad.get("purchases") or 0)
        ctr       = float(ad.get("ctr") or 0)
        cvr       = ad.get("cvr")
        freq      = float(ad.get("frequency") or 0)
        confidence = float(ad.get("confidence") or 0)
        is_video  = bool(ad.get("is_video"))
        hook_rate = ad.get("hook_rate")
        hold_rate = ad.get("hold_rate")

        action = "OK"
        rsns   = []

        # ── HARD KILLS (absolute) ──
        if roas > 0 and roas < 1.0 and spend >= 500:
            action = "KILL"
            rsns   = [f"ROAS {roas:.2f} — pod 1.0, prokazatelně ztrátové"]

        elif spend >= max_cpa * 3 and purchases == 0 and spend >= 1000:
            action = "KILL"
            rsns   = [f"0 nákupů po {kc(spend)} spend — víc než 3× max CPA bez výsledku"]

        elif freq > 5.0 and ctr < 1.0 and spend >= 500:
            action = "KILL"
            rsns   = [f"Extrémní ad fatigue — freq {freq:.1f}, CTR {ctr:.1f}%"]

        elif ctr > 2.0 and cvr is not None and float(cvr) < 0.5 and spend >= 1000:
            action = "KILL"
            rsns   = [f"Clickbait — CTR {ctr:.1f}% ale CVR {float(cvr):.1f}% — zásadní LP problém"]

        # ── SOFT KILL (percentile — bottom 10% + low absolute ROAS) ──
        elif (roas > 0 and roas < p10_roas and roas < 1.5
              and spend >= 1000 and purchases < 3):
            action = "KILL"
            rsns   = [
                f"Bottom 10 % účtu (P10 = {p10_roas:.2f}) + ROAS {roas:.2f} + jen {purchases} nákupy"
            ]

        # ── SCALE ──
        elif roas >= target_roas * 1.2 and confidence >= 0.5:
            action = "SCALE"
            rsns   = [f"ROAS {roas:.2f} — 20 %+ nad cílem {target_roas:.1f}"]
        elif roas >= target_roas and confidence >= 0.7:
            action = "SCALE"
            rsns   = [f"ROAS {roas:.2f} na cíli, vysoká spolehlivost"]

        # ── WATCH zone ──
        elif roas > 0 and watch_lower <= roas < watch_upper:
            action = "WATCH"
            rsns   = [f"ROAS {roas:.2f} ve watch zóně ({watch_lower:.1f}–{watch_upper:.1f})"]

        # ── ITERATE — fixable issues ──
        else:
            iter_rsns = []
            if roas > 0 and roas < watch_lower:
                iter_rsns.append(f"ROAS {roas:.2f} pod watch zónou ({watch_lower:.1f}) — analyzuj příčinu")
            if is_video and hook_rate is not None and float(hook_rate) < 25:
                iter_rsns.append(f"Hook rate {float(hook_rate):.0f} % pod benchmarkem 25 %")
            if is_video and hook_rate is not None and hold_rate is not None:
                if float(hook_rate) >= 30 and float(hold_rate) < 40:
                    iter_rsns.append(f"Dobrý hook {float(hook_rate):.0f} %, slabý hold {float(hold_rate):.0f} % — uprav střed")
            if ctr > 2.0 and roas > 0 and roas < target_roas * 0.7:
                iter_rsns.append(f"CTR {ctr:.1f} % ale ROAS {roas:.2f} — disconnect kreativa/LP")
            if cvr is not None and float(cvr) < 1.0 and ctr > 1.5:
                iter_rsns.append(f"CTR {ctr:.1f} % ale CVR {float(cvr):.1f} % — LP problém")
            if not is_video and ctr < 1.0 and spend >= 500:
                iter_rsns.append(f"CTR {ctr:.1f} % — slabý vizuál nebo headline")
            if iter_rsns:
                action = "ITERATE"
                rsns   = iter_rsns

        # ── WATCH signals (overlay — frequency growing) ──
        if action == "OK":
            if freq >= 2.0:
                action = "WATCH"
                rsns   = [f"Frekvence {freq:.1f} roste — připrav refresh kreativy"]
            elif roas > 0 and roas < target_roas:
                action = "WATCH"
                rsns   = [f"ROAS {roas:.2f} pod cílem {target_roas:.1f}, ale bez jasného kill signálu"]

        actions.append(action)
        reasons.append(rsns)

    df["h_action"]  = actions
    df["h_reasons"] = reasons
    return df, p10_roas, account_median, watch_lower


def render_health_action_cards(df, min_conf, p10_roas, watch_lower):
    """Render KILL/SCALE/ITERATE columns using h_action column."""
    is_active = df.get("is_active", pd.Series(True, index=df.index))

    # KILL: only active ads need action; already-paused ones are informational
    kill_active = df[(df["h_action"] == "KILL") & (df["confidence"] >= min_conf) & is_active]
    kill_paused = df[(df["h_action"] == "KILL") & (df["confidence"] >= min_conf) & ~is_active]
    kill_df  = kill_active.nlargest(5, "spend")
    scale_df = df[(df["h_action"] == "SCALE")   & (df["confidence"] >= min_conf)].nlargest(5, "roas")
    iter_df  = df[(df["h_action"] == "ITERATE") & (df["confidence"] >= min_conf)].nlargest(5, "spend")

    n_kill  = len(kill_active)
    n_paused_kill = len(kill_paused)
    n_scale = len(df[(df["h_action"] == "SCALE") & (df["confidence"] >= min_conf)])
    n_iter  = len(df[(df["h_action"] == "ITERATE") & (df["confidence"] >= min_conf)])
    waste   = kill_active["spend"].sum()

    a1, a2, a3 = st.columns(3)

    with a1:
        st.markdown(f"**Zastavit** · {n_kill} aktivních reklam · {kc(waste)}")
        if n_paused_kill > 0:
            st.markdown(
                f'<div style="font-size:0.78em;color:#9ca3af;margin:-4px 0 6px">'
                f'+ {n_paused_kill} dalších už zastaveno ({kc(kill_paused["spend"].sum())} historický spend)</div>',
                unsafe_allow_html=True)
        for _, ad in kill_df.iterrows():
            rsns = ad.get("h_reasons") or []
            r    = rsns[0][:60] if rsns else ""
            cvr_str = f" · CVR {ad['cvr']:.1f}%" if pd.notna(ad.get('cvr')) else ""
            st.markdown(f"""<div class="act-box act-kill">
{conf_badge(ad['confidence_level'])} <strong>{ad['ad_name'][:28]}</strong><br>
{kc(ad['spend'])} · ROAS {ad['roas'] or 0:.2f}{cvr_str} · {int(ad['purchases'])} nákupů<br>
<small style="color:#888">{r}</small></div>""", unsafe_allow_html=True)

    with a2:
        st.markdown(f"**Skalovat** · {n_scale} reklam")
        for _, ad in scale_df.iterrows():
            cvr_str = f" · CVR {ad['cvr']:.1f}%" if pd.notna(ad.get('cvr')) else ""
            rsns    = ad.get("h_reasons") or []
            r       = rsns[0][:55] if rsns else ""
            st.markdown(f"""<div class="act-box act-scale">
{conf_badge(ad['confidence_level'])} <strong>{ad['ad_name'][:28]}</strong><br>
ROAS {ad['roas'] or 0:.2f} · CPA {kc(ad['cpa'])}{cvr_str} · {int(ad['purchases'])} nákupů<br>
<small style="color:#2d6a4f">{r}</small></div>""", unsafe_allow_html=True)

    with a3:
        st.markdown(f"**Upravit** · {n_iter} reklam")
        for _, ad in iter_df.iterrows():
            rsns = ad.get("h_reasons") or []
            r    = rsns[0][:60] if rsns else ""
            st.markdown(f"""<div class="act-box act-iterate">
{conf_badge(ad['confidence_level'])} <strong>{ad['ad_name'][:28]}</strong><br>
{kc(ad['spend'])} · ROAS {ad['roas'] or 0:.2f} · {int(ad['purchases'])} nákupů<br>
<small style="color:#888">{r}</small></div>""", unsafe_allow_html=True)


# ── Load ──
mtd            = fetch_mtd()
learning_map   = fetch_learning()
ad_status_map  = fetch_ad_statuses()

# Statuses considered "still running" — everything else is already stopped
ACTIVE_STATUSES = {"ACTIVE", "CAMPAIGN_PAUSED", "ADSET_PAUSED"}
# Only ACTIVE means the ad itself is on; CAMPAIGN_PAUSED / ADSET_PAUSED means
# the ad creative is live but blocked at a higher level — still relevant to review.
# PAUSED / ARCHIVED / DELETED = user already stopped it → skip from KILL cards.

# ── Date math ──
today          = datetime.now()
days_in_month  = calendar.monthrange(today.year, today.month)[1]
days_elapsed   = max(today.day, 1)
days_remaining = days_in_month - days_elapsed

mtd_roas         = mtd["revenue"] / mtd["spend"] if mtd["spend"] > 0 else 0
daily_orders     = mtd["purchases"] / days_elapsed
projected_orders = round(daily_orders * days_in_month)
daily_spend      = mtd["spend"] / days_elapsed
projected_spend  = daily_spend * days_in_month

# ── Enrich df & split seasonal ──
df_valid = df_all[df_all["spend"] >= 200].copy() if len(df_all) > 0 else pd.DataFrame()

# Split seasonal from main
df_seasonal = pd.DataFrame()
df_main     = df_valid.copy()
if len(df_valid) > 0 and seasonal_camps:
    df_seasonal = df_valid[df_valid["campaign_name"].isin(seasonal_camps)].copy()
    df_main     = df_valid[~df_valid["campaign_name"].isin(seasonal_camps)].copy()

if len(df_main) > 0:
    total_spend_14d  = df_main["spend"].sum()
    total_purch_14d  = max(df_main["purchases"].sum(), 1)

    df_main["spend_share"]    = df_main["spend"] / total_spend_14d
    df_main["purchase_share"] = df_main["purchases"] / total_purch_14d
    df_main["efficiency_ratio"] = (
        df_main["purchase_share"] / df_main["spend_share"].replace(0, float("nan"))
    )

    if "adset_id" in df_main.columns:
        df_main["learning_status"] = df_main["adset_id"].astype(str).map(
            lambda aid: learning_map.get(aid, "unknown")
        )
    else:
        df_main["learning_status"] = "unknown"

    # Join current delivery status
    if "ad_id" in df_main.columns:
        df_main["effective_status"] = df_main["ad_id"].astype(str).map(
            lambda x: ad_status_map.get(x, "UNKNOWN")
        )
    else:
        df_main["effective_status"] = "UNKNOWN"
    df_main["is_active"] = df_main["effective_status"].isin(ACTIVE_STATUSES)

    # Run custom evaluation
    df_main, p10_roas, account_median, watch_lower = re_evaluate_health(df_main, target_roas, max_cpa)

    below_target       = len(df_main[df_main["roas"] < target_roas])
    total_ads          = len(df_main)
    below_pct          = below_target / total_ads * 100 if total_ads > 0 else 0
    top5_concentration = df_main.nlargest(5, "spend")["spend"].sum() / total_spend_14d * 100
    kill_waste         = df_main[df_main["h_action"] == "KILL"]["spend"].sum()
    scale_ads          = df_main[df_main["h_action"] == "SCALE"]
    learning_limited   = df_main[df_main["learning_status"] == "FAIL"]
    fatigued           = df_main[df_main["frequency"] > 3.0] if "frequency" in df_main.columns else pd.DataFrame()
else:
    p10_roas = account_median = watch_lower = 0.0
    below_pct = total_ads = top5_concentration = kill_waste = 0
    scale_ads = learning_limited = fatigued = pd.DataFrame()

# ── MTD severity ──
roas_gap_pct = (mtd_roas - target_roas) / target_roas * 100 if target_roas > 0 else 0

if mtd_roas > 0 and mtd_roas < 1.0:
    severity = "critical"
elif roas_gap_pct < -40 or (monthly_order_goal > 0 and projected_orders < monthly_order_goal * 0.6):
    severity = "critical"
elif roas_gap_pct < -15 or (monthly_order_goal > 0 and projected_orders < monthly_order_goal * 0.9):
    severity = "off"
elif roas_gap_pct < -5:
    severity = "watch"
else:
    severity = "ok"

SEVERITY = {
    "critical": ("Kritická situace", "severity-critical",
                 "ROAS výrazně pod cílem. Zastavit ztrátové, prioritizuj cashflow."),
    "off":      ("Pod targetem",     "severity-off",
                 "Pod targetem — zastavit prokazatelné ztráty, škálovat ověřené."),
    "watch":    ("Sledovat",         "severity-watch",
                 "Lehce pod cílem. Standardní přístup, sleduj trend."),
    "ok":       ("Na trati",         "severity-ok",
                 "Výkon odpovídá cíli. Fokus na objem a škálování winners."),
}

# ════════════════════════════════
#  PAGE
# ════════════════════════════════

st.markdown("## Campaign Health")

# ── Severity banner ──
sev_label, sev_css, sev_hint = SEVERITY[severity]
order_str = (f" · proj. {projected_orders} obj. vs. cíl {monthly_order_goal}"
             if monthly_order_goal > 0 else "")
st.markdown(f"""<div class="{sev_css}">
<div class="sev-title">{sev_label} &nbsp;·&nbsp; MTD ROAS {mtd_roas:.2f} vs. cíl {target_roas:.1f} ({roas_gap_pct:+.0f}%){order_str}</div>
<div class="sev-detail">{sev_hint}</div>
</div>""", unsafe_allow_html=True)

if not mtd["ok"]:
    st.warning(f"MTD data se nepodařilo načíst: {mtd.get('error', '?')}")

# ── MTD KPIs ──
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    delta_spend = f"z {kc(monthly_budget)}" if monthly_budget > 0 else f"proj. {kc(projected_spend)}"
    st.metric("MTD Spend", kc(mtd["spend"]), delta=delta_spend, delta_color="off")
with k2:
    delta_orders = f"z {monthly_order_goal}" if monthly_order_goal > 0 else f"proj. {projected_orders}"
    st.metric("MTD Objednávky", str(mtd["purchases"]), delta=delta_orders, delta_color="off")
with k3:
    st.metric("MTD ROAS", f"{mtd_roas:.2f}",
              delta=f"cíl {target_roas:.1f}",
              delta_color="normal" if mtd_roas >= target_roas else "inverse")
with k4:
    st.metric("Denní tempo", f"{daily_orders:.1f} obj./den",
              delta=f"proj. {projected_orders}", delta_color="off")
with k5:
    st.metric("Zbývá dní", str(days_remaining), delta=f"z {days_in_month}", delta_color="off")

# Progress bars
if monthly_budget > 0 or monthly_order_goal > 0:
    pb1, pb2 = st.columns(2)
    if monthly_budget > 0:
        with pb1:
            pct_spend = min(mtd["spend"] / monthly_budget * 100, 100)
            bar_col = "#e53e3e" if pct_spend > 95 else "#d69e2e" if pct_spend > 80 else "#4299e1"
            st.markdown(
                f'<div style="font-size:.82em;color:#6b7280">Budget: {pct_spend:.0f}% '
                f'({kc(mtd["spend"])} z {kc(monthly_budget)})</div>'
                f'<div class="prog-wrap"><div class="prog-fill" style="width:{pct_spend:.0f}%;background:{bar_col}"></div></div>',
                unsafe_allow_html=True)
    if monthly_order_goal > 0:
        with pb2:
            pct_ord = min(mtd["purchases"] / monthly_order_goal * 100, 100)
            bar_col2 = "#38a169" if pct_ord >= 85 else "#d69e2e" if pct_ord >= 60 else "#e53e3e"
            st.markdown(
                f'<div style="font-size:.82em;color:#6b7280">Objednávky: {pct_ord:.0f}% '
                f'({mtd["purchases"]} z {monthly_order_goal})</div>'
                f'<div class="prog-wrap"><div class="prog-fill" style="width:{pct_ord:.0f}%;background:{bar_col2}"></div></div>',
                unsafe_allow_html=True)

st.divider()

# ── Account median & diagnosis ──
st.markdown(f"### Median účtu (posledních {days} dní)")

if len(df_main) > 0:
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Median ROAS", f"{account_median:.2f}",
                  delta=f"cíl {target_roas:.1f}",
                  delta_color="normal" if account_median >= target_roas else "inverse")
    with m2:
        st.metric("Pod targetem", f"{int(below_pct)}% reklam",
                  delta=f"{below_target} z {total_ads}")
    with m3:
        n_kill_total = len(df_main[df_main["h_action"] == "KILL"])
        st.metric("Prokazatelné ztráty", kc(kill_waste),
                  delta=f"{n_kill_total} reklam", delta_color="inverse")
    with m4:
        st.metric("Konc. top 5", f"{top5_concentration:.0f}%",
                  delta="spend share", delta_color="off")

    # Diagnosis
    if below_pct > 60:
        diag = (f"Median táhne dolů <strong>plošně slabý výkon</strong> — {below_pct:.0f} % reklam je pod "
                f"targetem {target_roas:.1f}. Nejde o pár špatných kreativ, je to strukturální problém. "
                f"Zkontroluj targeting, sezónní kontext nebo samotnou nabídku.")
    elif below_pct > 35:
        diag = (f"Median snižuje <strong>cluster slabších reklam</strong> — {below_pct:.0f} % pod targetem. "
                f"Zastavení nejslabších by mediánu výrazně pomohlo — není to systémový problém.")
    else:
        diag = (f"Median je relativně zdravý — jen {below_pct:.0f} % reklam pod targetem {target_roas:.1f}. "
                f"Jde o pár konkrétních případů, ne o systémový problém.")

    if top5_concentration > 80:
        diag += (f" ⚠ Top 5 reklam tvoří <strong>{top5_concentration:.0f} % veškerého spend</strong> "
                 f"— vysoká koncentrace, nízká diverzifikace.")

    if len(learning_limited) > 0:
        ll_spend = learning_limited["spend"].sum()
        diag += (f" {len(learning_limited)} reklam je v <strong>learning limited adsetech</strong> "
                 f"({kc(ll_spend)} spend) — nemohou optimalizovat bez ohledu na výkon.")

    st.markdown(f'<div class="median-diagnosis">📊 {diag}</div>', unsafe_allow_html=True)

else:
    st.info("Žádná data — zkontroluj Meta API token nebo rozšiř časové okno.")

st.divider()

# ── Recommendations ──
st.markdown("### Co dělat teď")

if len(df_main) > 0:
    # Show thresholds used
    st.markdown(
        f'<span class="watch-info">Kill: ROAS &lt; 1.0 nebo P10 ({p10_roas:.2f}) &nbsp;·&nbsp; '
        f'Watch: {watch_lower:.1f}–2.6 &nbsp;·&nbsp; Scale: ROAS ≥ {target_roas * 1.2:.1f}</span>',
        unsafe_allow_html=True)

    render_health_action_cards(df_main, min_conf, p10_roas, watch_lower)

    # ── Enhanced detail table ──
    st.markdown("#### Přehled reklam")

    ACTION_ORDER = {"KILL": 0, "ITERATE": 1, "WATCH": 2, "OK": 3, "SCALE": 4}
    view = (df_main[df_main["spend"] >= 200]
            .copy()
            .assign(_ord=lambda d: d["h_action"].map(ACTION_ORDER).fillna(3))
            .sort_values(["_ord", "spend"], ascending=[True, False])
            .head(60))

    rows = []
    for _, ad in view.iterrows():
        freq = float(ad.get("frequency") or 0)
        eff  = ad.get("efficiency_ratio")
        ls   = ad.get("learning_status", "unknown")

        fatigue  = ("FATIGUE" if freq > 5.0
                    else f"freq {freq:.1f}" if freq > 3.0
                    else "")
        learning = ("❌ LL" if ls == "FAIL"
                    else "✓" if ls == "SUCCESS"
                    else "")
        eff_status = ad.get("effective_status", "UNKNOWN")
        paused_tag = "" if eff_status in ("ACTIVE", "UNKNOWN") else f"[{eff_status}]"
        flags    = " ".join(filter(None, [paused_tag, fatigue, learning]))
        h_act    = ad.get("h_action", "OK")

        rows.append({
            "": f"{EMOJI.get(h_act, '⚪')} {'🎬' if ad.get('is_video') else '📸'}",
            "Reklama":    ad["ad_name"][:32],
            "Kampaň":     ad["campaign_name"][:16],
            "ROAS":       ad.get("roas"),
            "CPA (Kč)":   ad.get("cpa"),
            "CVR %":      ad.get("cvr"),
            "Freq":        freq if freq > 0 else None,
            "Efic.×":     round(eff, 2) if pd.notna(eff) else None,
            "Nákupy":     int(ad["purchases"]),
            "Spend (Kč)": int(ad["spend"]),
            "Flags":      flags,
            "Akce":       CZ.get(h_act, h_act),
        })

    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "":           st.column_config.Column(width=55),
                "ROAS":       st.column_config.NumberColumn(format="%.2f", width=70),
                "CPA (Kč)":   st.column_config.NumberColumn(format="%.0f", width=80),
                "CVR %":      st.column_config.NumberColumn(format="%.1f", width=60),
                "Freq":       st.column_config.NumberColumn(format="%.1f", width=55),
                "Efic.×":     st.column_config.NumberColumn(format="%.2f", width=65,
                                                             help="Podíl nákupů ÷ podíl spend. >1 = výkonnější než kolik stojí."),
                "Spend (Kč)": st.column_config.NumberColumn(format="%d", width=80),
                "Flags":      st.column_config.Column(width=100),
            }
        )

    # ── Callout cards ──
    st.markdown("")

    if len(learning_limited) > 0:
        ll_spend = learning_limited["spend"].sum()
        ll_names = (", ".join(learning_limited["adset_name"].unique()[:4])
                    if "adset_name" in learning_limited.columns else "")
        st.markdown(
            f'<div class="callout-card callout-ll">'
            f'<strong>❌ Learning Limited — {len(learning_limited)} reklam · {kc(ll_spend)} burn</strong><br>'
            f'Adsety nemohou opustit learning phase (nedostatek konverzí/týden). '
            f'Budget se plýtvá bez možnosti optimalizace. '
            f'{"Adsety: " + ll_names if ll_names else ""}'
            f'</div>',
            unsafe_allow_html=True)

    if "frequency" in df_main.columns:
        fat_high = df_main[df_main["frequency"] > 5.0]
        fat_med  = df_main[(df_main["frequency"] > 3.0) & (df_main["frequency"] <= 5.0)]
        if len(fat_high) > 0:
            names = ", ".join(fat_high["ad_name"].str[:25].tolist()[:3])
            st.markdown(
                f'<div class="callout-card callout-fat">'
                f'<strong>⚠ Extrémní fatigue — {len(fat_high)} reklam (freq &gt; 5.0)</strong><br>'
                f'Vysoká frekvence + klesající CTR = přesycená audience. Zastavit nebo obměnit kreativu: {names}'
                f'</div>',
                unsafe_allow_html=True)
        elif len(fat_med) > 0:
            st.markdown(
                f'<div class="callout-card callout-fat">'
                f'<strong>Sleduj fatigue — {len(fat_med)} reklam (freq 3–5)</strong><br>'
                f'Frekvence roste, připrav varianty kreativy pro příští týden.'
                f'</div>',
                unsafe_allow_html=True)

    if "efficiency_ratio" in df_main.columns:
        top_eff = df_main[df_main["efficiency_ratio"] > 1.5]
        if len(top_eff) > 0:
            best  = top_eff.nlargest(3, "efficiency_ratio")
            names = ", ".join(best["ad_name"].str[:22].tolist())
            st.markdown(
                f'<div class="callout-card callout-eff">'
                f'<strong>💡 Podhodnocené reklamy (eficience &gt; 1.5×) — {len(top_eff)} reklam</strong><br>'
                f'Přinášejí více nákupů než odpovídá jejich spend share — kandidáti na více budget: {names}'
                f'</div>',
                unsafe_allow_html=True)

# ── Seasonal campaigns ──
if len(df_seasonal) > 0:
    st.divider()
    st.markdown("### Sezónní / časově omezené kampaně")
    st.markdown(
        '<div class="callout-card callout-seasonal">'
        '<strong>⏱ Jiná pravidla platí pro flash akce</strong><br>'
        'Tyto kampaně jsou časově omezené — cílem je maximalizovat obrat v krátkém okně. '
        'Neaplikujeme percentile kill logiku. Zastavujeme jen prokazatelně ztrátové (ROAS &lt; 1.0 nebo 0 nákupů po 3× CPA).'
        '</div>',
        unsafe_allow_html=True)

    if "adset_id" in df_seasonal.columns:
        df_seasonal["learning_status"] = df_seasonal["adset_id"].astype(str).map(
            lambda aid: learning_map.get(aid, "unknown")
        )

    rows_s = []
    for _, ad in df_seasonal.sort_values("spend", ascending=False).iterrows():
        roas    = float(ad.get("roas") or 0)
        spend   = float(ad.get("spend") or 0)
        purch   = int(ad.get("purchases") or 0)
        freq    = float(ad.get("frequency") or 0)

        # Simplified: only hard kills
        if roas > 0 and roas < 1.0 and spend >= 500:
            flag = "KILL"
        elif spend >= max_cpa * 3 and purch == 0 and spend >= 1000:
            flag = "KILL"
        elif roas >= target_roas:
            flag = "SCALE"
        else:
            flag = "WATCH"

        rows_s.append({
            "": f"{EMOJI.get(flag, '⚪')} {'🎬' if ad.get('is_video') else '📸'}",
            "Reklama":    ad["ad_name"][:32],
            "Kampaň":     ad["campaign_name"][:18],
            "ROAS":       ad.get("roas"),
            "Nákupy":     purch,
            "Spend (Kč)": int(spend),
            "Freq":        freq if freq > 0 else None,
            "Akce":       CZ.get(flag, flag),
        })

    if rows_s:
        st.dataframe(
            pd.DataFrame(rows_s),
            hide_index=True,
            use_container_width=True,
            column_config={
                "ROAS":       st.column_config.NumberColumn(format="%.2f"),
                "Freq":       st.column_config.NumberColumn(format="%.1f"),
                "Spend (Kč)": st.column_config.NumberColumn(format="%d"),
            }
        )

st.divider()

# ── Closing diagnosis ──
st.markdown("### Shrnutí")

if len(df_main) > 0:
    kills_n  = len(df_main[df_main["h_action"] == "KILL"])
    scales_n = len(scale_ads)
    avg_scale_roas = scale_ads["roas"].mean() if scales_n > 0 else 0

    parts = []

    if severity == "critical":
        parts.append(f"Účet je v **kritické situaci** — MTD ROAS {mtd_roas:.2f} je výrazně pod cílem {target_roas:.1f}.")
    elif severity == "off":
        parts.append(f"Výkon je **pod targetem** ({roas_gap_pct:+.0f} % od cíle) a vyžaduje aktivní zásah.")
    elif severity == "watch":
        parts.append(f"Výkon je mírně pod cílem ({roas_gap_pct:+.0f} %) — sleduj trend, zatím není třeba drasticky zasahovat.")
    else:
        parts.append(f"Účet je **na trati** — MTD ROAS {mtd_roas:.2f} odpovídá cíli {target_roas:.1f}.")

    if kills_n > 0 and kill_waste > 0:
        parts.append(
            f"Zastavení {kills_n} prokazatelně ztrátových reklam uvolní **{kc(kill_waste)}**"
            + (f", které může přejít na {scales_n} ověřených reklam s průměrným ROAS {avg_scale_roas:.2f}."
               if scales_n > 0 else ".")
        )

    if days_remaining <= 5 and monthly_order_goal > 0:
        gap = monthly_order_goal - mtd["purchases"]
        if gap > 0:
            parts.append(
                f"S {days_remaining} dny do konce měsíce chybí **{gap} objednávek** — "
                f"optimalizace kampaní to nezmění, prioritizuj existující winners."
            )

    st.markdown(" ".join(parts))

st.markdown(
    f'<div class="reliability-banner">'
    f'📌 <strong>Metodika:</strong> ROAS = Meta 7-day click atribuce. '
    f'Kill logika = absolutní (ROAS &lt; 1.0, 0 nákupů po 3× max CPA, extrémní fatigue) + percentilová (bottom 10 % = P10 {p10_roas:.2f}). '
    f'Watch zóna = {watch_lower:.1f}–2.6 (odvozeno od mediánu účtu {account_median:.2f}). '
    f'Max CPA indikátor <strong>{max_cpa:.0f} Kč</strong> = AOV {aov} Kč ÷ target ROAS {target_roas:.1f}.'
    f'</div>',
    unsafe_allow_html=True)
