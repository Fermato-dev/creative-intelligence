"""Fermato Creative Intelligence v3 — Component Library & Recommendations"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

st.set_page_config(page_title="Component Library", page_icon="🧩", layout="wide")

from auth import check_password

if not check_password():
    st.stop()

import json
import os
import plotly.graph_objects as go
import pandas as pd

from shared_data import SHARED_CSS, REPO_ROOT, DATA_DIR

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── Data loading ──

EXPORTS_DIR = REPO_ROOT / "data" / "exports"
COMP_PARQUET = EXPORTS_DIR / "components.parquet"
COMBO_PARQUET = EXPORTS_DIR / "combinations.parquet"


@st.cache_data(ttl=300)
def load_components():
    if not COMP_PARQUET.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(str(COMP_PARQUET))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_combinations():
    if not COMBO_PARQUET.exists() or not COMP_PARQUET.exists():
        return pd.DataFrame()
    try:
        combos = pd.read_parquet(str(COMBO_PARQUET))
        comps = pd.read_parquet(str(COMP_PARQUET))
        valid_ids = set(comps["id"].tolist())
        # Filter out stale combos referencing deleted components
        combos = combos[
            combos["hook_id"].isin(valid_ids)
            & combos["body_id"].isin(valid_ids)
            & combos["cta_id"].isin(valid_ids)
        ].copy()
        if combos.empty:
            return combos
        # Join with component details (drop duplicate 'id' cols from merge)
        hook_cols = comps[["id", "ad_name", "hook_rate", "analysis"]].rename(
            columns={"id": "h_id", "ad_name": "hook_ad", "hook_rate": "h_hook_rate", "analysis": "h_analysis"})
        body_cols = comps[["id", "ad_name", "hold_rate", "analysis"]].rename(
            columns={"id": "b_id", "ad_name": "body_ad", "hold_rate": "b_hold_rate", "analysis": "b_analysis"})
        cta_cols = comps[["id", "ad_name", "cvr", "analysis"]].rename(
            columns={"id": "c_id", "ad_name": "cta_ad", "cvr": "c_cvr", "analysis": "c_analysis"})
        combos = (combos
            .merge(hook_cols, left_on="hook_id", right_on="h_id", how="left")
            .merge(body_cols, left_on="body_id", right_on="b_id", how="left")
            .merge(cta_cols, left_on="cta_id", right_on="c_id", how="left")
            .drop(columns=["h_id", "b_id", "c_id"], errors="ignore")
        )
        return combos.sort_values("expected_score", ascending=False)
    except Exception:
        return pd.DataFrame()


def parse_analysis(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


# ── Page ──

comp_df = load_components()
combo_df = load_combinations()

if comp_df.empty:
    st.warning("Komponentni knihovna je prazdna. Spust `python creative_decomposer.py` pro naplneni.")
    st.stop()

st.markdown("## Component Library")
st.caption(f"{len(comp_df)} komponent z {comp_df['ad_id'].nunique()} kreativ")

# ── Summary metrics ──

hooks = comp_df[comp_df["component_type"] == "hook"]
bodies = comp_df[comp_df["component_type"] == "body"]
ctas = comp_df[comp_df["component_type"] == "cta"]

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Hooks", len(hooks))
with c2:
    st.metric("Bodies", len(bodies))
with c3:
    st.metric("CTAs", len(ctas))
with c4:
    st.metric("Doporucene kombinace", len(combo_df))

st.divider()

# ── Tabs ──

tab_hooks, tab_bodies, tab_ctas, tab_combos = st.tabs(["Hooks", "Bodies", "CTAs", "Kombinace"])


def render_component_table(df, key_metric, key_label):
    if df.empty:
        st.info("Zadne komponenty.")
        return

    rows = []
    for _, r in df.iterrows():
        a = parse_analysis(r.get("analysis"))
        # Get type tag from analysis
        type_tag = a.get("hook_type", a.get("narrative_arc", a.get("cta_type", "—")))
        rows.append({
            "Kreativa": (r.get("ad_name") or "")[:30],
            "Kampan": (r.get("campaign_name") or "")[:20],
            "Typ": type_tag,
            key_label: r.get(key_metric),
            "ROAS": r.get("roas"),
            "CVR %": r.get("cvr"),
            "Spend": r.get("spend"),
            "Conf": r.get("confidence"),
        })

    tdf = pd.DataFrame(rows)
    if key_metric in tdf.columns or key_label in tdf.columns:
        sort_col = key_label
        asc = True if key_metric == "cpa" else False
        tdf = tdf.sort_values(sort_col, ascending=asc, na_position="last")

    st.dataframe(tdf, hide_index=True, use_container_width=True,
                 column_config={
                     key_label: st.column_config.NumberColumn(format="%.1f"),
                     "ROAS": st.column_config.NumberColumn(format="%.2f"),
                     "CVR %": st.column_config.NumberColumn(format="%.2f"),
                     "Spend": st.column_config.NumberColumn(format="%.0f"),
                     "Conf": st.column_config.NumberColumn(format="%.2f"),
                 })

    # Distribution chart
    metric_data = df[key_metric].dropna()
    if len(metric_data) > 2:
        fig = go.Figure(go.Histogram(x=metric_data, nbinsx=15,
                                     marker_color="#6c63ff", opacity=0.8))
        fig.update_layout(height=220, margin=dict(t=10, b=30, l=40, r=10),
                         xaxis_title=key_label, yaxis_title="Pocet")
        st.plotly_chart(fig, use_container_width=True)


with tab_hooks:
    st.markdown("### Hooks (prvni 3 sekundy)")
    st.caption("Serazeno dle hook rate. Typ = AI klasifikace vizualniho stylu hooku.")
    render_component_table(hooks, "hook_rate", "Hook Rate %")

    # Detail expander for each hook
    if not hooks.empty and st.checkbox("Zobrazit detaily analyz", key="hook_details"):
        for _, r in hooks.nlargest(10, "hook_rate", "all").iterrows():
            a = parse_analysis(r.get("analysis"))
            with st.expander(f"{r['ad_name'][:40]} — hook rate {r.get('hook_rate', '?')}%"):
                cols = st.columns(2)
                with cols[0]:
                    st.json(a)
                with cols[1]:
                    if r.get("thumbnail_path") and Path(r["thumbnail_path"]).exists():
                        st.image(r["thumbnail_path"], width=300)

with tab_bodies:
    st.markdown("### Bodies (stredni cast)")
    st.caption("Serazeno dle hold rate. Ukazuje jak dobre stred videa drzi pozornost.")
    render_component_table(bodies, "hold_rate", "Hold Rate %")

with tab_ctas:
    st.markdown("### CTAs (posledni sekce)")
    st.caption("Serazeno dle CVR. Ukazuje jak efektivne CTA konvertuje divaky na zakazniky.")
    render_component_table(ctas, "cvr", "CVR %")

def _safe_str(v, maxlen=25):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return str(v)[:maxlen]


def _safe_pct(v, fmt=".1f"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:{fmt}}%"


with tab_combos:
    st.markdown("### Doporucene kombinace")
    st.caption("Hook x Body x CTA kombinace serazene dle expected score. "
               "Score = 35% hook_rate/40 + 35% hold_rate/50 + 30% CVR/3 (normalizovane na ~1.0).")

    if combo_df.empty:
        st.info("Zadne kombinace (bud nebyly vygenerovany, nebo odkazuji na smazane komponenty). "
                "Spust `python creative_decomposer.py --recommend` pro regeneraci.")
    else:
        # Score-based ranking with percentile thresholds
        scores = combo_df["expected_score"].dropna()
        p66 = scores.quantile(0.66) if len(scores) > 2 else 0.9
        p33 = scores.quantile(0.33) if len(scores) > 2 else 0.6

        for rank, (_, c) in enumerate(combo_df.head(10).iterrows(), 1):
            score = c.get("expected_score", 0) or 0
            if score >= p66:
                color, badge = "#38a169", "PRIORITA"
            elif score >= p33:
                color, badge = "#d69e2e", "ZKUSIT"
            else:
                color, badge = "#3182ce", "MOZNOST"

            h_analysis = parse_analysis(c.get("h_analysis"))
            b_analysis = parse_analysis(c.get("b_analysis"))
            c_analysis = parse_analysis(c.get("c_analysis"))

            hook_type = h_analysis.get("hook_type", "?")
            body_type = b_analysis.get("narrative_arc", "?")
            cta_type = c_analysis.get("cta_type", "?")

            h_rate = _safe_pct(c.get('h_hook_rate'))
            b_rate = _safe_pct(c.get('b_hold_rate'))
            c_rate = _safe_pct(c.get('c_cvr'), ".2f")
            h_name = _safe_str(c.get('hook_ad'))
            b_name = _safe_str(c.get('body_ad'))
            c_name = _safe_str(c.get('cta_ad'))

            # Highlight when components come from different ads
            ads_used = {h_name, b_name, c_name} - {"—"}
            mix_note = f"Mix z {len(ads_used)} kreativ" if len(ads_used) > 1 else "Vsechny z jedne kreativy"

            st.markdown(f"""<div style="border-radius:8px; padding:12px 14px; margin:8px 0;
                border-left:4px solid {color}; background:#f8f9fb;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span><strong style="color:{color}">#{rank} {badge}</strong>
                    &nbsp;<span style="color:#6b7280; font-size:0.82em">{mix_note}</span></span>
                    <span style="font-size:0.82em; color:#6b7280">Score: <strong>{score:.2f}</strong></span>
                </div>
                <table style="width:100%; font-size:0.88em; margin-top:8px; border-collapse:collapse;">
                <tr>
                    <td style="width:33%; padding:6px 8px; background:#f0fff4; border-radius:6px 0 0 6px;">
                        <strong>HOOK</strong> <span style="color:#6b7280">[{hook_type}]</span><br>
                        <span style="font-size:0.92em">{h_name}</span><br>
                        <strong style="color:#38a169">{h_rate}</strong> hook rate</td>
                    <td style="width:33%; padding:6px 8px; background:#fffff0;">
                        <strong>BODY</strong> <span style="color:#6b7280">[{body_type}]</span><br>
                        <span style="font-size:0.92em">{b_name}</span><br>
                        <strong style="color:#d69e2e">{b_rate}</strong> hold rate</td>
                    <td style="width:33%; padding:6px 8px; background:#ebf8ff; border-radius:0 6px 6px 0;">
                        <strong>CTA</strong> <span style="color:#6b7280">[{cta_type}]</span><br>
                        <span style="font-size:0.92em">{c_name}</span><br>
                        <strong style="color:#3182ce">{c_rate}</strong> CVR</td>
                </tr></table></div>""", unsafe_allow_html=True)

# ── Footer ──

st.divider()
st.caption(f"Component Library v1 — {len(comp_df)} komponent — data z {str(comp_df['created_at'].max())[:10] if not comp_df.empty else '?'}")
