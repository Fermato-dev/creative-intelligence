"""Fermato Creative Intelligence v3 — Video kreativy"""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Video kreativy", page_icon="🎬", layout="wide")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    import streamlit as st
    st.stop()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared_data import *

st.markdown(SHARED_CSS, unsafe_allow_html=True)
days, df_all, snaps, ai_data, show_low_conf = setup_sidebar()
min_conf = 0.0 if show_low_conf else 0.5

if len(df_all) == 0:
    st.warning("Meta API data nejsou dostupna.")
    st.stop()

df = df_all[df_all["is_video"]].copy()
if len(df) == 0:
    st.warning("Zadne video kreativy v datech.")
    st.stop()

st.markdown("## Video kreativy")

total_spend = df["spend"].sum()
total_purch = df["purchases"].sum()
total_clicks = df["clicks"].sum()
roas = df["revenue"].sum() / total_spend if total_spend > 0 else 0
avg_hook = df["hook_rate"].dropna().mean()
avg_hold = df["hold_rate"].dropna().mean()
video_cvr = (total_purch / total_clicks * 100) if total_clicks > 0 else 0

c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("ROAS", f"{roas:.2f}", delta=f"CVR {video_cvr:.1f} %", delta_color="off")
with c2: st.metric("Hook", pct(avg_hook), delta=f"Hold {pct(avg_hold)}", delta_color="off")
with c3: st.metric("Spend", kc(total_spend), delta=f"{int(total_purch)} nakupu", delta_color="off")
with c4: st.metric("Videa", f"{len(df)}", delta=f"CPA {kc(total_spend/total_purch) if total_purch else '—'}", delta_color="off")

st.divider()

# ── Video Drop-off Diagnoza ──

st.markdown("### Video Drop-off Diagnoza")

diagnosed = df[df["video_dropoff"].notna() & (df["spend"] > 200)].copy()
if len(diagnosed) > 0:
    counts = diagnosed["video_dropoff"].value_counts()
    total_diagnosed = len(diagnosed)

    dc1, dc2, dc3, dc4 = st.columns(4)
    for col, dtype, label, css_class in [
        (dc1, "SPATNY_HOOK", "Hook (0-3s)", "dropoff-hook"),
        (dc2, "MIDDLE_SAG", "Stred (25-50%)", "dropoff-mid"),
        (dc3, "POZDNI_CTA", "CTA (75-100%)", "dropoff-cta"),
        (dc4, "ZDRAVY_FUNNEL", "Zdravy", "dropoff-ok"),
    ]:
        c = counts.get(dtype, 0)
        pct_val = (c / total_diagnosed * 100) if total_diagnosed > 0 else 0
        with col:
            st.markdown(f"""<div class="dropoff-bar {css_class}" style="width:{max(pct_val, 15):.0f}%">
            {label}: {c}</div>""", unsafe_allow_html=True)

    hook_problems = diagnosed[diagnosed["video_dropoff"] == "SPATNY_HOOK"].nlargest(5, "spend")
    if len(hook_problems) > 0:
        st.markdown("**Spatny hook** — zmen 1. frame, pridej text/movement v prvnich 2s")
        rows = [{"Kreativa": ad["ad_name"][:30], "Hook %": ad["hook_rate"],
                 "ROAS": ad["roas"], "Utrata": int(ad["spend"]),
                 "p25 %": ad.get("retention_p25"), "p50 %": ad.get("retention_p50")}
                for _, ad in hook_problems.iterrows()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
else:
    st.info("Nedostatek dat pro drop-off diagnozu.")

st.divider()

# ── Co delat ──

st.markdown("### Co delat ted")
render_action_cards(df, min_conf)
st.divider()

# ── Hook vs ROAS + Hold vs ROAS ──

ch1, ch2 = st.columns(2)

with ch1:
    st.markdown("### Hook rate vs. ROAS")
    s = df[(df["hook_rate"].notna()) & (df["roas"].notna()) & (df["spend"] > 100)].copy()
    if len(s) > 0:
        s["label"] = s["ad_name"].str[:20]
        s["sz"] = s["spend"].clip(lower=100)
        fig = px.scatter(s, x="hook_rate", y="roas", size="sz", color="action",
                         color_discrete_map=COLORS, hover_name="label",
                         labels={"hook_rate":"Hook rate %","roas":"ROAS"})
        fig.add_hline(y=TARGET_ROAS, line_dash="dash", line_color="rgba(0,0,0,0.15)")
        fig.add_vline(x=25, line_dash="dash", line_color="rgba(214,158,46,0.4)", annotation_text="Standard 25%")
        fig.add_vline(x=35, line_dash="dash", line_color="rgba(56,161,105,0.4)", annotation_text="Elite 35%")
        fig.update_layout(height=350, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

with ch2:
    st.markdown("### Hold rate vs. ROAS")
    sh = df[(df["hold_rate"].notna()) & (df["roas"].notna()) & (df["spend"] > 100)].copy()
    if len(sh) > 0:
        sh["label"] = sh["ad_name"].str[:20]
        sh["sz"] = sh["spend"].clip(lower=100)
        fig_hold = px.scatter(sh, x="hold_rate", y="roas", size="sz", color="action",
                              color_discrete_map=COLORS, hover_name="label",
                              labels={"hold_rate":"Hold rate %","roas":"ROAS"})
        fig_hold.add_hline(y=TARGET_ROAS, line_dash="dash", line_color="rgba(0,0,0,0.15)")
        fig_hold.add_vline(x=40, line_dash="dash", line_color="rgba(214,158,46,0.4)", annotation_text="Standard 40%")
        fig_hold.update_layout(height=350, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig_hold, use_container_width=True)

st.divider()

# ── Tabulka ──

st.markdown("### Kreativy")
sort_opts = {"weighted_roas": "Vykon", "spend": "Utrata", "hook_rate": "Hook rate", "cvr": "CVR", "roas": "ROAS"}
sc1, sc2 = st.columns([2, 1])
with sc1: sort_by = st.selectbox("Seradit", list(sort_opts.keys()), format_func=lambda x: sort_opts[x], label_visibility="collapsed", key="vsort")
with sc2: n_show = st.selectbox("Zobrazit", [20, 40, 80], format_func=lambda x: f"{x} kreativ", label_visibility="collapsed", key="vcount")

view = df[df["spend"] > 50].sort_values(sort_by, ascending=False, na_position="last").head(n_show)
rows = []
for _, ad in view.iterrows():
    dropoff = ad.get("video_dropoff", "")
    dropoff_label = {"SPATNY_HOOK": "Hook", "MIDDLE_SAG": "Stred", "POZDNI_CTA": "CTA", "ZDRAVY_FUNNEL": "OK"}.get(dropoff, "—")
    rows.append({
        "": f"{EMOJI.get(ad['action'],'')} {CONF_DOT.get(ad['confidence_level'], '○')}",
        "Kreativa": ad["ad_name"][:30], "Kampan": ad["campaign_name"][:18],
        "ROAS": ad["roas"], "CVR %": ad.get("cvr"), "CPA (Kc)": ad["cpa"],
        "Hook %": ad["hook_rate"], "Hold %": ad["hold_rate"],
        "Drop-off": dropoff_label,
        "Nakupy": int(ad["purchases"]), "Utrata": int(ad["spend"]),
        "Akce": CZ.get(ad["action"], ad["action"]),
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
             column_config={
                 "": st.column_config.Column(width=50),
                 "ROAS": st.column_config.NumberColumn(format="%.2f", width=65),
                 "CVR %": st.column_config.NumberColumn(format="%.2f", width=60),
                 "Hook %": st.column_config.NumberColumn(format="%.1f", width=60),
                 "Hold %": st.column_config.NumberColumn(format="%.1f", width=60),
             })

# ── AI analyzy ──

analyzed = {k: v for k, v in ai_data.items() if k in df["ad_id"].values and v.get("creative_type") == "video"}
if analyzed:
    st.divider()
    st.markdown("### AI analyzy videi")
    for ad_id, data in analyzed.items():
        ad_row = df[df["ad_id"] == ad_id]
        if len(ad_row) == 0: continue
        ad = ad_row.iloc[0]
        h = data.get("hook") or {}
        f = data.get("full") or {}
        with st.expander(f"{EMOJI.get(ad['action'],'')} {ad['ad_name'][:35]} — {data.get('at','?')}"):
            if h and not h.get("_parse_error"):
                st.markdown(f"**Hook:** {h.get('hook_type','?')} · efektivita: **{h.get('hook_effectiveness','?')}**")
                st.caption(h.get("hook_description", ""))
                for s in h.get("improvement_suggestions", [])[:3]:
                    st.markdown(f"  -> {s}")
            if f and not f.get("_parse_error"):
                brief = f.get("creative_brief_for_iteration", "")
                if brief: st.info(f"**Brief:** {brief}")
