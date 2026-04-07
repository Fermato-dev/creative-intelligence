"""Fermato Creative Intelligence v3 — Bannery & staticke reklamy"""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Bannery & staticke", page_icon="📸", layout="wide")

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

df = df_all[~df_all["is_video"]].copy()
if len(df) == 0:
    st.warning("Zadne staticke kreativy v datech.")
    st.stop()

st.markdown("## Bannery & staticke reklamy")

total_spend = df["spend"].sum()
total_purch = df["purchases"].sum()
total_rev = df["revenue"].sum()
total_clicks = df["clicks"].sum()
roas = total_rev / total_spend if total_spend > 0 else 0
avg_cpa = total_spend / total_purch if total_purch > 0 else 0
avg_ctr = df["ctr"].mean()
static_cvr = (total_purch / total_clicks * 100) if total_clicks > 0 else 0

c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("ROAS", f"{roas:.2f}", delta=f"CVR {static_cvr:.1f} %", delta_color="off")
with c2: st.metric("CTR", pct(avg_ctr), delta=f"CPA {kc(avg_cpa)}", delta_color="off")
with c3: st.metric("Spend", kc(total_spend), delta=f"{int(total_purch)} nakupu", delta_color="off")
with c4: st.metric("Bannery", f"{len(df)}")

st.divider()

# ── Clickbait detekce ──

clickbait = df[(df["ctr"] > 2.0) & (df["cvr"].notna()) & (df["cvr"] < 0.5) & (df["spend"] > 200)]
if len(clickbait) > 0:
    cb_spend = clickbait["spend"].sum()
    st.markdown(f"""<div class="clickbait-alert">
    <strong>{len(clickbait)} clickbait kreativ</strong> — vysoky CTR ale miziva CVR. Celkem {kc(cb_spend)} zbytecneho spendu.
    </div>""", unsafe_allow_html=True)
    st.divider()

# ── Co delat ──

st.markdown("### Co delat ted")
render_action_cards(df, min_conf)
st.divider()

# ── CVR vs CTR scatter ──

ch1, ch2 = st.columns(2)
with ch1:
    st.markdown("### CVR vs. CTR")
    scat = df[(df["cvr"].notna()) & (df["ctr"].notna()) & (df["spend"] > 100)].copy()
    if len(scat) > 0:
        scat["label"] = scat["ad_name"].str[:20]
        scat["sz"] = scat["spend"].clip(lower=100)
        fig = px.scatter(scat, x="ctr", y="cvr", size="sz", color="action",
                         color_discrete_map=COLORS, hover_name="label",
                         labels={"ctr":"CTR %","cvr":"CVR %"})
        fig.add_hline(y=2.0, line_dash="dash", line_color="rgba(56,161,105,0.3)", annotation_text="CVR 2%")
        fig.update_layout(height=380, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

with ch2:
    st.markdown("### CTR vs. ROAS")
    scat2 = df[(df["roas"].notna()) & (df["spend"] > 100)].copy()
    if len(scat2) > 0:
        scat2["label"] = scat2["ad_name"].str[:20]
        scat2["sz"] = scat2["spend"].clip(lower=100)
        fig2 = px.scatter(scat2, x="ctr", y="roas", size="sz", color="action",
                         color_discrete_map=COLORS, hover_name="label",
                         labels={"ctr":"CTR %","roas":"ROAS"})
        fig2.add_hline(y=TARGET_ROAS, line_dash="dash", line_color="rgba(0,0,0,0.15)")
        fig2.update_layout(height=380, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Tabulka ──

st.markdown("### Kreativy")
sort_opts = {"weighted_roas": "Vykon", "spend": "Utrata", "ctr": "CTR", "cvr": "CVR", "roas": "ROAS"}
sort_by = st.selectbox("Seradit", list(sort_opts.keys()), format_func=lambda x: sort_opts[x], label_visibility="collapsed", key="ssort")

view = df[df["spend"] > 30].sort_values(sort_by, ascending=sort_by=="cpa", na_position="last").head(30)
rows = []
for _, ad in view.iterrows():
    rows.append({
        "": f"{EMOJI.get(ad['action'],'')}",
        "Kreativa": ad["ad_name"][:30],
        "ROAS": ad["roas"], "CVR %": ad.get("cvr"), "CTR %": ad["ctr"],
        "CPA (Kc)": ad["cpa"], "Nakupy": int(ad["purchases"]), "Utrata": int(ad["spend"]),
        "Akce": CZ.get(ad["action"], ad["action"]),
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
