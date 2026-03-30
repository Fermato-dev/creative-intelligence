"""Fermato Creative Intelligence v2 — Bannery & staticke reklamy"""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Bannery & staticke", page_icon="📸", layout="wide")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared_data import *

st.markdown(SHARED_CSS, unsafe_allow_html=True)
days, df_all, snaps, ai_data, show_low_conf = setup_sidebar()
min_conf = 0.0 if show_low_conf else 0.5

df = df_all[~df_all["is_video"]].copy()

if len(df) == 0:
    st.warning("Zadne staticke kreativy v datech.")
    st.stop()

# ── Header ──

st.markdown("## 📸 Bannery & staticke reklamy")

total_spend = df["spend"].sum()
total_purch = df["purchases"].sum()
total_rev = df["revenue"].sum()
total_clicks = df["clicks"].sum()
roas = total_rev / total_spend if total_spend > 0 else 0
avg_cpa = total_spend / total_purch if total_purch > 0 else 0
avg_ctr = df["ctr"].mean()
static_cvr = (total_purch / total_clicks * 100) if total_clicks > 0 else 0
spend_share = total_spend / df_all["spend"].sum() * 100 if df_all["spend"].sum() > 0 else 0

st.caption(f"{len(df)} kreativ · {spend_share:.0f}% celkove utraty")

c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("ROAS", f"{roas:.2f}", delta=f"CVR {static_cvr:.1f} %", delta_color="off",
                    help="ROAS statickych kreativ")
with c2: st.metric("CTR", pct(avg_ctr), delta=f"CPA {kc(avg_cpa)}", delta_color="off",
                    help="Benchmark food&bev: >=1.5% dobre")
with c3: st.metric("Spend", kc(total_spend), delta=f"{int(total_purch)} nakupu", delta_color="off")
with c4: st.metric("Bannery", f"{len(df)}", delta=f"{spend_share:.0f} % spendu", delta_color="off")

st.divider()

# ── Clickbait & LP detekce ──

clickbait = df[(df["ctr"] > 2.0) & (df["cvr"].notna()) & (df["cvr"] < 0.5) & (df["spend"] > 200)]
lp_problem = df[(df["ctr"] > 1.5) & (df["cvr"].notna()) & (df["cvr"] < 1.0) & (df["spend"] > 200)]

if len(clickbait) > 0 or len(lp_problem) > 0:
    st.markdown("### Detekce problemu")

    if len(clickbait) > 0:
        cb_spend = clickbait["spend"].sum()
        st.markdown(f"""<div class="clickbait-alert">
        ⚠️ <strong>{len(clickbait)} clickbait kreativ</strong> — vysoky CTR ale miziva CVR.
        Celkem {kc(cb_spend)} zbytecneho spendu. Kreativa laka kliky ale neprodava.
        </div>""", unsafe_allow_html=True)

        rows = []
        for _, ad in clickbait.iterrows():
            rows.append({
                "Kreativa": ad["ad_name"][:30], "CTR %": ad["ctr"], "CVR %": ad["cvr"],
                "ROAS": ad["roas"], "Utrata": int(ad["spend"]), "Nakupy": int(ad["purchases"]),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={
                         "CTR %": st.column_config.NumberColumn(format="%.2f"),
                         "CVR %": st.column_config.NumberColumn(format="%.2f"),
                         "ROAS": st.column_config.NumberColumn(format="%.2f"),
                     })

    if len(lp_problem) > 0 and len(lp_problem) != len(clickbait):
        lp_only = lp_problem[~lp_problem.index.isin(clickbait.index)]
        if len(lp_only) > 0:
            st.markdown(f"**Landing page problem:** {len(lp_only)} kreativ s OK CTR ale nizkou CVR — kreativa funguje, LP nekonvertuje")

    st.divider()

# ── Co delat ted ──

st.markdown("### Co delat ted")
render_action_cards(df, min_conf)
st.divider()

# ── CVR vs CTR scatter (klicovy insight) ──

ch1, ch2 = st.columns(2)

with ch1:
    st.markdown("### CVR vs. CTR")
    st.caption("CTR = 4% ROI. CVR rozhoduje. Hledej vysoko na ose Y.")
    scat = df[(df["cvr"].notna()) & (df["ctr"].notna()) & (df["spend"] > 100)].copy()
    if len(scat) > 0:
        scat["label"] = scat["ad_name"].str[:20]
        scat["sz"] = scat["spend"].clip(lower=100)
        fig = px.scatter(scat, x="ctr", y="cvr", size="sz", color="action",
                         color_discrete_map=COLORS, hover_name="label",
                         hover_data={"ctr":":.2f","cvr":":.2f","roas":":.2f","spend":":,.0f","purchases":True,"sz":False},
                         labels={"ctr":"CTR %","cvr":"CVR %"})
        fig.add_hline(y=2.0, line_dash="dash", line_color="rgba(56,161,105,0.3)", annotation_text="CVR 2%")
        fig.add_vline(x=1.5, line_dash="dash", line_color="rgba(0,0,0,0.1)")
        # Clickbait zone annotation
        fig.add_annotation(x=3.0, y=0.2, text="Clickbait zona", showarrow=False,
                          font=dict(size=10, color="rgba(229,62,62,0.5)"))
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
                         hover_data={"ctr":":.2f","roas":":.2f","spend":":,.0f","purchases":True,"cpa":":.0f","sz":False},
                         labels={"ctr":"CTR %","roas":"ROAS"})
        fig2.add_hline(y=ci.TARGET_ROAS, line_dash="dash", line_color="rgba(0,0,0,0.15)")
        fig2.add_vline(x=1.5, line_dash="dash", line_color="rgba(0,0,0,0.1)", annotation_text="Dobre 1.5%")
        fig2.update_layout(height=380, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("Pravy horni = nejlepsi (CTR 1.5%+ a ROAS nad targetem)")

st.divider()

# ── Distribuce CTR a CVR ──

dh1, dh2 = st.columns(2)

with dh1:
    st.markdown("### Distribuce CTR")
    ctr_vals = df["ctr"].dropna()
    if len(ctr_vals) > 0:
        fig_h = px.histogram(ctr_vals, nbins=15, color_discrete_sequence=["#d69e2e"],
                             labels={"value":"CTR %","count":"Pocet"})
        fig_h.add_vline(x=1.0, line_dash="dash", line_color="#e53e3e", annotation_text="Min 1%")
        fig_h.add_vline(x=1.5, line_dash="dash", line_color="#d69e2e", annotation_text="Dobre 1.5%")
        fig_h.add_vline(x=2.0, line_dash="dash", line_color="#38a169", annotation_text="Elite 2%+")
        fig_h.update_layout(height=300, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig_h, use_container_width=True)

with dh2:
    st.markdown("### Distribuce CVR")
    cvr_vals = df[df["cvr"].notna()]["cvr"]
    if len(cvr_vals) > 0:
        fig_cvr = px.histogram(cvr_vals, nbins=15, color_discrete_sequence=["#38a169"],
                               labels={"value":"CVR %","count":"Pocet"})
        fig_cvr.add_vline(x=2.0, line_dash="dash", line_color="#d69e2e", annotation_text="Dobre 2%")
        fig_cvr.add_vline(x=3.0, line_dash="dash", line_color="#38a169", annotation_text="Vyborne 3%")
        fig_cvr.update_layout(height=300, margin=dict(t=10,b=10), showlegend=False)
        st.plotly_chart(fig_cvr, use_container_width=True)

st.divider()

# ── Tabulka ──

st.markdown("### Kreativy")
sort_opts = {"weighted_roas": "Vykon (ROAS x spolehlivost)", "spend": "Utrata", "ctr": "CTR",
             "cvr": "CVR", "roas": "ROAS", "cpa": "CPA"}
sc1, sc2 = st.columns([2, 1])
with sc1: sort_by = st.selectbox("Seradit", list(sort_opts.keys()), format_func=lambda x: sort_opts[x], label_visibility="collapsed", key="ssort")
with sc2: n_show = st.selectbox("Zobrazit", [20, 40], format_func=lambda x: f"{x} kreativ", label_visibility="collapsed", key="scount")

asc = sort_by in ("cpa",)
view = df[df["spend"] > 30].sort_values(sort_by, ascending=asc, na_position="last").head(n_show)

rows = []
for _, ad in view.iterrows():
    rows.append({
        "": f"{EMOJI.get(ad['action'],'')} {CONF_DOT.get(ad['confidence_level'], '○')}",
        "Kreativa": ad["ad_name"][:30], "Kampan": ad["campaign_name"][:18],
        "ROAS": ad["roas"], "CVR %": ad.get("cvr"), "CPA (Kc)": ad["cpa"], "CTR %": ad["ctr"],
        "Nakupy": int(ad["purchases"]), "Utrata": int(ad["spend"]),
        "Freq": ad["frequency"], "Spolehl.": ad["confidence"],
        "Akce": CZ.get(ad["action"], ad["action"]),
    })
tbl = pd.DataFrame(rows)
st.dataframe(tbl, hide_index=True, use_container_width=True, height=min(700, 35*len(tbl)+40),
             column_config={
                 "": st.column_config.Column(width=50),
                 "ROAS": st.column_config.NumberColumn(format="%.2f", width=65),
                 "CVR %": st.column_config.NumberColumn(format="%.2f", width=60),
                 "CPA (Kc)": st.column_config.NumberColumn(format="%.0f", width=70),
                 "CTR %": st.column_config.NumberColumn(format="%.2f", width=60),
                 "Spolehl.": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0f%%", width=75),
             })

# ── AI analyzy ──

analyzed = {k: v for k, v in ai_data.items() if k in df["ad_id"].values}
if analyzed:
    st.divider()
    st.markdown("### AI analyzy banneru")
    st.caption(f"{len(analyzed)} kreativ analyzovano pomoci Claude Vision")

    for ad_id, data in analyzed.items():
        ad_row = df[df["ad_id"] == ad_id]
        if len(ad_row) == 0: continue
        ad = ad_row.iloc[0]
        f = data.get("full") or {}

        with st.expander(f"{EMOJI.get(ad['action'],'')} {ad['ad_name'][:35]} — {data.get('at','?')}"):
            if f and not f.get("_parse_error"):
                col1, col2, col3, col4 = st.columns(4)
                with col1: st.markdown(f"**Typ:** {f.get('ad_type', '?')}")
                with col2: st.markdown(f"**Kvalita:** {f.get('production_quality', '?')}")
                with col3: st.markdown(f"**Food appeal:** {f.get('food_appeal_score', '?')}/10")
                with col4: st.markdown(f"**Brand:** {f.get('brand_consistency_score', '?')}/10")

                prod_desc = f.get("product_description", "")
                if prod_desc: st.caption(f"Na obrazku: {prod_desc}")

                cta_eff = f.get("cta_effectiveness", f.get("cta_present", "?"))
                cta_text = f.get("cta_text", "")
                cta_why = f.get("cta_effectiveness_why", "")
                if cta_eff in ("silne", True) and cta_text:
                    st.success(f"**CTA:** {cta_text} — {cta_why}")
                elif cta_eff in ("stredni",):
                    st.warning(f"**CTA:** {cta_text} — {cta_why}")
                elif cta_eff in ("slabe", "chybi", False):
                    st.error(f"**CTA: {'chybi' if not cta_text else cta_text}** — {cta_why or 'pridejte viditelne CTA'}")

                texts = f.get("text_overlays", [])
                headline = f.get("headline", "")
                if headline: st.markdown(f"**Nadpis:** {headline}")
                if texts: st.markdown(f"**Texty:** {' · '.join(texts[:5])}")

                colors = f.get("dominant_colors", [])
                if colors:
                    color_html = " ".join(f'<span style="display:inline-block;width:20px;height:20px;background:{c};border-radius:3px;margin:2px"></span>' for c in colors[:5])
                    st.markdown(f"**Barvy:** {color_html}", unsafe_allow_html=True)

                st.markdown("---")
                strengths = f.get("strengths", [])
                weaknesses = f.get("weaknesses", [])
                if strengths: st.markdown("**Silne stranky:** " + " · ".join(strengths[:4]))
                if weaknesses: st.markdown("**Slabiny:** " + " · ".join(weaknesses[:4]))

                suggestions = f.get("improvement_suggestions", [])
                if suggestions:
                    st.markdown("**Doporuceni:**")
                    for s in suggestions[:3]: st.markdown(f"  → {s}")

                ab_idea = f.get("ab_test_idea", "")
                if ab_idea: st.info(f"**A/B test:** {ab_idea}")
else:
    st.divider()
    st.info("Zadne AI analyzy pro staticke kreativy. Spust: `python creative_vision.py --days 14`")

# ── Fatigue ──

st.divider()
st.markdown("### Fatigue radar")
st.caption("Freq > 3.0 = akce, 2.0-3.0 = sledovat. Staticke bannery: sleduj CTR + CVR trend.")

fat = df[(df["frequency"] > 1.8) & (df["spend"] > 300)].copy()
fat["fatigue"] = fat["frequency"] * 20 - fat["ctr"].fillna(0) * 10
fat = fat.sort_values("fatigue", ascending=False).head(10)

if len(fat) > 0:
    fd = fat[["ad_name","frequency","ctr","cvr","spend","roas","purchases","action"]].copy()
    fd.columns = ["Kreativa","Freq","CTR %","CVR %","Utrata","ROAS","Nakupy","Akce"]
    fd["Kreativa"] = fd["Kreativa"].str[:28]
    fd["Akce"] = fd["Akce"].map(lambda x: f"{EMOJI.get(x,'')} {CZ.get(x,x)}")
    fd["Utrata"] = fd["Utrata"].map(kc)
    st.dataframe(fd, hide_index=True, use_container_width=True,
                 column_config={"Freq": st.column_config.NumberColumn(format="%.2f"),
                                "CTR %": st.column_config.NumberColumn(format="%.2f"),
                                "CVR %": st.column_config.NumberColumn(format="%.2f"),
                                "ROAS": st.column_config.NumberColumn(format="%.2f")})
else:
    st.success("Zadna staticka reklama nevykazuje znamky fatigue.")
