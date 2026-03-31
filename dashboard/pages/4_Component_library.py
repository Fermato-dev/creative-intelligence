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
        # Join combinations with component details
        combos = combos.merge(
            comps[["id", "ad_name", "hook_rate", "analysis"]].rename(
                columns={"ad_name": "hook_ad", "hook_rate": "h_hook_rate", "analysis": "h_analysis"}),
            left_on="hook_id", right_on="id", how="left", suffixes=("", "_h")
        ).merge(
            comps[["id", "ad_name", "hold_rate", "analysis"]].rename(
                columns={"ad_name": "body_ad", "hold_rate": "b_hold_rate", "analysis": "b_analysis"}),
            left_on="body_id", right_on="id", how="left", suffixes=("", "_b")
        ).merge(
            comps[["id", "ad_name", "cvr", "analysis"]].rename(
                columns={"ad_name": "cta_ad", "cvr": "c_cvr", "analysis": "c_analysis"}),
            left_on="cta_id", right_on="id", how="left", suffixes=("", "_c")
        )
        return combos.sort_values("expected_score", ascending=False)
    except Exception:
        return pd.DataFrame()


def parse_analysis(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
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

with tab_combos:
    st.markdown("### Doporucene kombinace")
    st.caption("Hook x Body x CTA kombinace serazene dle expected score. "
               "Score = 35% hook_rate + 35% hold_rate + 30% CVR (normalizovane).")

    if combo_df.empty:
        st.info("Zadne kombinace. Spust `python creative_decomposer.py --recommend`.")
    else:
        for _, c in combo_df.head(10).iterrows():
            score = c.get("expected_score", 0) or 0
            # Color based on score
            if score >= 0.9:
                color = "#38a169"
                badge = "PRIORITA"
            elif score >= 0.6:
                color = "#d69e2e"
                badge = "ZKUSIT"
            else:
                color = "#3182ce"
                badge = "MOZNOST"

            h_analysis = parse_analysis(c.get("h_analysis"))
            b_analysis = parse_analysis(c.get("b_analysis"))
            c_analysis = parse_analysis(c.get("c_analysis"))

            hook_type = h_analysis.get("hook_type", "?")
            body_type = b_analysis.get("narrative_arc", "?")
            cta_type = c_analysis.get("cta_type", "?")

            h_rate = f"{c.get('h_hook_rate', 0) or 0:.1f}%"
            b_rate = f"{c.get('b_hold_rate', 0) or 0:.1f}%"
            c_rate = f"{c.get('c_cvr', 0) or 0:.2f}%"

            st.markdown(f"""<div style="border-radius:8px; padding:12px 14px; margin:8px 0;
                border-left:4px solid {color}; background:#f8f9fb;">
                <strong style="color:{color}">{badge}</strong> &nbsp; Score: {score:.3f}<br>
                <table style="width:100%; font-size:0.88em; margin-top:6px;">
                <tr><td style="width:33%"><strong>HOOK</strong> [{hook_type}]<br>{(c.get('hook_ad') or '')[:25]}<br>Hook rate: {h_rate}</td>
                <td style="width:33%"><strong>BODY</strong> [{body_type}]<br>{(c.get('body_ad') or '')[:25]}<br>Hold rate: {b_rate}</td>
                <td style="width:33%"><strong>CTA</strong> [{cta_type}]<br>{(c.get('cta_ad') or '')[:25]}<br>CVR: {c_rate}</td></tr>
                </table></div>""", unsafe_allow_html=True)

# ── Footer ──

st.divider()
st.caption(f"Component Library v1 — {len(comp_df)} komponent — data z {comp_df['created_at'].max()[:10] if not comp_df.empty else '?'}")
