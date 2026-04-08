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

# ── Extra CSS ──
st.markdown("""<style>
.severity-critical { background:#fef2f2; border:2px solid #e53e3e; border-radius:12px; padding:16px 20px; margin-bottom:8px; }
.severity-off      { background:#fff7ed; border:2px solid #ed8936; border-radius:12px; padding:16px 20px; margin-bottom:8px; }
.severity-watch    { background:#fffff0; border:2px solid #d69e2e; border-radius:12px; padding:16px 20px; margin-bottom:8px; }
.severity-ok       { background:#f0fff4; border:2px solid #38a169; border-radius:12px; padding:16px 20px; margin-bottom:8px; }
.sev-title  { font-size:1.05em; font-weight:700; }
.sev-detail { font-size:0.86em; margin-top:4px; color:#374151; }

.median-diagnosis { background:#eef2ff; border-left:4px solid #6366f1; border-radius:8px;
    padding:12px 16px; font-size:0.87em; color:#3730a3; line-height:1.55; }

.adset-fail { display:inline-block; background:#fef2f2; color:#e53e3e;
    font-size:0.7em; font-weight:700; padding:1px 7px; border-radius:4px; }
.adset-ok   { display:inline-block; background:#f0fff4; color:#38a169;
    font-size:0.7em; font-weight:700; padding:1px 7px; border-radius:4px; }
.fatigue-tag { display:inline-block; background:#fff7ed; color:#c05621;
    font-size:0.7em; font-weight:700; padding:1px 7px; border-radius:4px; }

.callout-card { border-radius:10px; padding:12px 16px; margin:5px 0;
    border-left:4px solid; font-size:0.84em; line-height:1.5; }
.callout-ll   { background:#fef2f2; border-left-color:#e53e3e; }
.callout-fat  { background:#fff7ed; border-left-color:#ed8936; }
.callout-eff  { background:#f0fff4; border-left-color:#38a169; }

.prog-wrap { background:#e8ecf1; border-radius:6px; height:9px; overflow:hidden; margin:3px 0 8px; }
.prog-fill { height:9px; border-radius:6px; }

.goal-derived { background:#f0f4ff; border-radius:8px; padding:8px 12px;
    font-size:0.82em; color:#4338ca; margin-top:4px; }
</style>""", unsafe_allow_html=True)

# ── Standard sidebar ──
days, df_all, snaps, ai_data, show_low_conf = setup_sidebar()
min_conf = 0.0 if show_low_conf else 0.3

# ── Goal inputs in sidebar ──
with st.sidebar:
    st.divider()
    st.markdown("### 🎯 Cíle")

    target_roas = st.number_input(
        "Target ROAS", min_value=0.5, max_value=10.0, value=3.0, step=0.1,
        help="Cílový ROAS — říká jak agresivně škrtat a škálovat")
    aov = st.number_input(
        "AOV (Kč)", min_value=100, max_value=10000, value=1000, step=50,
        help="Průměrná hodnota objednávky")
    max_cpa_indicator = aov / target_roas
    st.markdown(
        f'<div class="goal-derived">→ Max CPA indikátor: <strong>{max_cpa_indicator:.0f} Kč</strong>'
        f'<br><small>= AOV {aov} ÷ ROAS {target_roas:.1f} — pokud je ROAS v cíli, vyšší CPA nevadí</small></div>',
        unsafe_allow_html=True)

    st.markdown("")
    monthly_order_goal = st.number_input(
        "Cíl objednávek / měsíc", min_value=0, value=0, step=10,
        help="Nech 0 pro přeskočení")
    monthly_budget = st.number_input(
        "Měsíční budget (Kč)", min_value=0, value=0, step=1000,
        help="Nech 0 pro přeskočení")


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


# ── Load ──
mtd = fetch_mtd()
learning_map = fetch_learning()

# ── Date math ──
today = datetime.now()
days_in_month = calendar.monthrange(today.year, today.month)[1]
days_elapsed = max(today.day, 1)
days_remaining = days_in_month - days_elapsed

mtd_roas = mtd["revenue"] / mtd["spend"] if mtd["spend"] > 0 else 0
daily_orders = mtd["purchases"] / days_elapsed
projected_orders = round(daily_orders * days_in_month)
daily_spend = mtd["spend"] / days_elapsed
projected_spend = daily_spend * days_in_month

# ── Enrich df ──
df_valid = df_all[df_all["spend"] >= 200].copy() if len(df_all) > 0 else pd.DataFrame()

if len(df_valid) > 0:
    total_spend_14d = df_valid["spend"].sum()
    total_purch_14d = max(df_valid["purchases"].sum(), 1)

    df_valid["spend_share"] = df_valid["spend"] / total_spend_14d
    df_valid["purchase_share"] = df_valid["purchases"] / total_purch_14d
    df_valid["efficiency_ratio"] = (
        df_valid["purchase_share"] / df_valid["spend_share"].replace(0, float("nan"))
    )

    if "adset_id" in df_valid.columns:
        df_valid["learning_status"] = df_valid["adset_id"].astype(str).map(
            lambda aid: learning_map.get(aid, "unknown")
        )
    else:
        df_valid["learning_status"] = "unknown"

    account_median_roas = df_valid["roas"].dropna().median()
    total_ads = len(df_valid)
    below_target = len(df_valid[df_valid["roas"] < target_roas])
    below_pct = below_target / total_ads * 100 if total_ads > 0 else 0
    top5_concentration = df_valid.nlargest(5, "spend")["spend"].sum() / total_spend_14d * 100
    kill_waste = df_valid[df_valid["action"] == "KILL"]["spend"].sum()
    scale_ads = df_valid[df_valid["action"] == "SCALE"]
    learning_limited = df_valid[df_valid["learning_status"] == "FAIL"]
    fatigued = df_valid[(df_valid.get("frequency", pd.Series(dtype=float)) > 3.0)] if "frequency" in df_valid.columns else pd.DataFrame()
else:
    account_median_roas = 0
    total_ads = below_pct = top5_concentration = kill_waste = 0
    scale_ads = learning_limited = fatigued = pd.DataFrame()

# ── Severity ──
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
    "critical": ("🔴 Kritická situace", "severity-critical",
                 "ROAS výrazně pod cílem. Škrtej agresivně, prioritizuj cashflow."),
    "off":      ("🟠 Pod targetem",     "severity-off",
                 "Pod targetem — zastavit ztrátové, škálovat ověřené."),
    "watch":    ("🟡 Sledovat",         "severity-watch",
                 "Lehce pod cílem. Standardní přístup, sleduj trend."),
    "ok":       ("🟢 Na trati",         "severity-ok",
                 "Výkon odpovídá cíli. Fokus na škálování winners."),
}

# ════════════════════════════════
#  PAGE
# ════════════════════════════════

st.markdown("## 🏁 Campaign Health")

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
    delta_spend = f"z {kc(monthly_budget)}" if monthly_budget > 0 else f"→ proj. {kc(projected_spend)}"
    st.metric("MTD Spend", kc(mtd["spend"]), delta=delta_spend, delta_color="off")
with k2:
    delta_orders = f"z {monthly_order_goal}" if monthly_order_goal > 0 else f"→ proj. {projected_orders}"
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
st.markdown("### Median účtu (posledních {d} dní)".format(d=days))

if len(df_valid) > 0:
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Median ROAS", f"{account_median_roas:.2f}",
                  delta=f"cíl {target_roas:.1f}",
                  delta_color="normal" if account_median_roas >= target_roas else "inverse")
    with m2:
        st.metric("Pod targetem", f"{int(below_pct)}% reklam",
                  delta=f"{int(below_target)} z {total_ads}")
    with m3:
        st.metric("Burn (KILL)", kc(kill_waste),
                  delta=f"{len(df_valid[df_valid['action']=='KILL'])} reklam", delta_color="inverse")
    with m4:
        st.metric("Konc. top 5", f"{top5_concentration:.0f}%",
                  delta="spend share", delta_color="off")

    # Diagnosis
    if below_pct > 60:
        diag = (f"Median táhne dolů <strong>plošně slabý výkon</strong> — {below_pct:.0f} % reklam je pod "
                f"targetem {target_roas:.1f}. Nejde o pár špatných kreativ, je to strukturální problém. "
                f"Zkontroluj targeting, sezónní kontext nebo samotnou nabídku.")
    elif below_pct > 35:
        diag = (f"Median snižuje <strong>cluster špatných reklam</strong> — {below_pct:.0f} % pod targetem. "
                f"Zastavení nejslabších by mediánu výrazně pomohlo — není to systémový problém.")
    else:
        diag = (f"Median je relativně zdravý — jen {below_pct:.0f} % reklam pod targetem {target_roas:.1f}. "
                f"Jde o pár konkrétních případů, ne o systémový problém.")

    if top5_concentration > 80:
        diag += (f" ⚠ Top 5 reklam tvoří <strong>{top5_concentration:.0f} % veškerého spend</strong> "
                 f"— vysoká koncentrace, malá diverzifikace.")

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

if len(df_valid) > 0:
    # Severity context note
    if severity == "critical":
        st.error("🔴 Kritický režim — škrtáme i hraniční reklamy. Priorita: cashflow nad expanzí.")
    elif severity == "off":
        st.warning("🟠 Pod targetem — kill vše pod ROAS 2.0, škáluj jen ověřené.")

    render_action_cards(df_valid, min_conf)

    # ── Enhanced detail table ──
    st.markdown("#### Přehled reklam")

    ACTION_ORDER = {"KILL": 0, "ITERATE": 1, "WATCH": 2, "OK": 3, "SCALE": 4, "INFO": 5}
    view = (df_valid[df_valid["spend"] >= 200]
            .copy()
            .assign(_ord=lambda d: d["action"].map(ACTION_ORDER).fillna(5))
            .sort_values(["_ord", "spend"], ascending=[True, False])
            .head(50))

    rows = []
    for _, ad in view.iterrows():
        freq = float(ad.get("frequency") or 0)
        eff  = ad.get("efficiency_ratio")
        ls   = ad.get("learning_status", "unknown")

        fatigue = ("⚠ FATIGUE" if freq > 5.0
                   else f"freq {freq:.1f}" if freq > 3.0
                   else "")
        learning = ("❌ LL" if ls == "FAIL"
                    else "✓" if ls == "SUCCESS"
                    else "")
        flags = " ".join(filter(None, [fatigue, learning]))

        rows.append({
            "": f"{EMOJI.get(ad['action'], '⚪')} {'🎬' if ad.get('is_video') else '📸'}",
            "Reklama":   ad["ad_name"][:32],
            "Kampaň":    ad["campaign_name"][:16],
            "ROAS":      ad.get("roas"),
            "CPA (Kč)":  ad.get("cpa"),
            "CVR %":     ad.get("cvr"),
            "Freq":      freq if freq > 0 else None,
            "Efic.×":    round(eff, 2) if pd.notna(eff) else None,
            "Nákupy":    int(ad["purchases"]),
            "Spend (Kč)": int(ad["spend"]),
            "Flags":     flags,
            "Akce":      CZ.get(ad["action"], ad["action"]),
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
                "Flags":      st.column_config.Column(width=110),
            }
        )

    # ── Callout cards ──
    st.markdown("")

    if len(learning_limited) > 0:
        ll_spend = learning_limited["spend"].sum()
        ll_names = ", ".join(learning_limited["adset_name"].unique()[:4]) if "adset_name" in learning_limited.columns else ""
        st.markdown(
            f'<div class="callout-card callout-ll">'
            f'<strong>❌ Learning Limited — {len(learning_limited)} reklam · {kc(ll_spend)} burn</strong><br>'
            f'Tyto reklamy jsou v adsetech, které nemohou opustit learning phase (nedostatek konverzí/týden). '
            f'Budget se plýtvá bez možnosti optimalizace. '
            f'{"Adsety: " + ll_names if ll_names else ""}'
            f'</div>',
            unsafe_allow_html=True)

    if "frequency" in df_valid.columns:
        fat_high = df_valid[df_valid["frequency"] > 5.0]
        fat_med  = df_valid[(df_valid["frequency"] > 3.0) & (df_valid["frequency"] <= 5.0)]
        if len(fat_high) > 0:
            names = ", ".join(fat_high["ad_name"].str[:25].tolist()[:3])
            st.markdown(
                f'<div class="callout-card callout-fat">'
                f'<strong>⚠ Extrémní fatigue — {len(fat_high)} reklam (freq > 5.0)</strong><br>'
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

    top_eff = df_valid[df_valid.get("efficiency_ratio", pd.Series(dtype=float)) > 1.5] if "efficiency_ratio" in df_valid.columns else pd.DataFrame()
    if len(top_eff) > 0:
        best = top_eff.nlargest(3, "efficiency_ratio")
        names = ", ".join(best["ad_name"].str[:22].tolist())
        st.markdown(
            f'<div class="callout-card callout-eff">'
            f'<strong>💡 Podhodnocené reklamy (eficience > 1.5×) — {len(top_eff)} reklam</strong><br>'
            f'Tyto reklamy přinášejí více nákupů než odpovídá jejich spend share — kandidáti na více budget: {names}'
            f'</div>',
            unsafe_allow_html=True)

st.divider()

# ── Closing diagnosis ──
st.markdown("### Shrnutí")

if len(df_valid) > 0:
    kills_n = len(df_valid[df_valid["action"] == "KILL"])
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
            f"Zastavení {kills_n} reklam uvolní **{kc(kill_waste)}** za období, "
            f"které může přejít na {scales_n} ověřených reklam"
            + (f" s průměrným ROAS {avg_scale_roas:.2f}." if scales_n > 0 else ".")
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
    f'📌 <strong>Data reliability:</strong> ROAS = Meta 7-day click atribuce. '
    f'Skutečný inkrementální dopad může být ±30–70 %. '
    f'Max CPA indikátor <strong>{max_cpa_indicator:.0f} Kč</strong> je odvozen z AOV {aov} Kč ÷ target ROAS {target_roas:.1f}. '
    f'Pokud je ROAS nad targetem, vysoké CPA není problém.'
    f'</div>',
    unsafe_allow_html=True)
