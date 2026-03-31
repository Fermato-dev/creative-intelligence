"""Fermato Creative Intelligence v2 — Prehled"""

import streamlit as st

st.set_page_config(page_title="Fermato · Creative Intelligence", page_icon="🎯", layout="wide")

from auth import check_password

if not check_password():
    st.stop()

import plotly.graph_objects as go

from shared_data import *

st.markdown(SHARED_CSS, unsafe_allow_html=True)
days, df, snaps, ai_data, show_low_conf = setup_sidebar()
min_conf = 0.0 if show_low_conf else 0.5

if len(df) == 0:
    st.warning("Meta API data nejsou dostupna. Zkontroluj META_ADS_ACCESS_TOKEN. Stranky Creative Briefs a dalsi jsou v postranim menu.")
    st.stop()

# ── Metriky ──

total_spend = df["spend"].sum()
total_purch = df["purchases"].sum()
total_rev = df["revenue"].sum()
total_clicks = df["clicks"].sum()
roas = total_rev / total_spend if total_spend > 0 else 0
avg_cpa = total_spend / total_purch if total_purch > 0 else 0
overall_cvr = (total_purch / total_clicks * 100) if total_clicks > 0 else 0

video_df = df[df["is_video"]]
static_df = df[~df["is_video"]]
avg_hook = video_df["hook_rate"].dropna().mean() if len(video_df) > 0 else 0

kill_spend = df[df["action"] == "KILL"]["spend"].sum()
waste_pct = kill_spend / total_spend * 100 if total_spend > 0 else 0

# Ad concentration
sorted_by_spend = df.sort_values("spend", ascending=False)
top5_spend = sorted_by_spend.head(5)["spend"].sum()
ad_concentration = (top5_spend / total_spend * 100) if total_spend > 0 else 0

# Deltas
d_roas = None
d_cvr = None
if len(snaps) >= 2:
    prev = snaps[1]["data"].get("meta_ads", {})
    if prev.get("overall_roas"):
        d_roas = round(roas - prev["overall_roas"], 2)
    if prev.get("overall_cvr"):
        d_cvr = round(overall_cvr - prev["overall_cvr"], 2)

# ── Header ──

st.markdown("## Fermato · Creative Intelligence v2")
st.caption(f"Poslednich {days} dni · {datetime.now().strftime('%d.%m.%Y %H:%M')} · target ROAS {ci.TARGET_ROAS} · target CPA {ci.TARGET_CPA} Kc")

# ── Data reliability banner ──

st.markdown("""<div class="reliability-banner">
<strong>Data reliability:</strong> ROAS = Meta 7-day click atribuce.
Skutecny inkrementalni dopad +/- 30-70% (studie Measured, Stella).
Pouzivej pro <strong>relativni srovnani</strong> kreativ, ne absolutni pravdu.
</div>""", unsafe_allow_html=True)

# ── KPI — 4 sloupce, citelne ──

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("ROAS", f"{roas:.2f}", delta=f"{d_roas:+.2f}" if d_roas else None,
              help="Navratnost investic (7-day click atribuce)")
with c2:
    st.metric("CVR", f"{overall_cvr:.2f} %", delta=f"{d_cvr:+.2f}pp" if d_cvr else None,
              help="Konverzni mira (purchases/clicks). Benchmark food&bev: >2% dobre, >3% vyborne")
with c3:
    st.metric("Spend", kc(total_spend), delta=f"{int(total_purch)} nakupu", delta_color="off")
with c4:
    st.metric("CPA", kc(avg_cpa), delta=f"Kill: {pct(waste_pct)}", delta_color="inverse",
              help="Prumerne naklady na nakup. Delta = % utraty na KILL reklamy")

st.divider()

# ── Co delat ted ──

st.markdown("### Co delat ted")
render_action_cards(df, min_conf)
st.divider()

# ── Portfolio Health ──

st.markdown("### Portfolio health")

h1, h2, h3, h4 = st.columns(4)

# Ad concentration
conc_color = "#e53e3e" if ad_concentration > 50 else "#d69e2e" if ad_concentration > 35 else "#38a169"
conc_label = "RIZIKO" if ad_concentration > 50 else "OK" if ad_concentration > 35 else "ZDRAVY"
with h1:
    st.markdown(f"""<div class="health-card">
    <div class="health-label">Koncentrace top 5</div>
    <div class="health-value" style="color:{conc_color}">{ad_concentration:.0f} %</div>
    <div class="health-sub">{conc_label}</div></div>""", unsafe_allow_html=True)

# Format split
video_spend = video_df["spend"].sum()
static_spend = static_df["spend"].sum()
video_roas = video_df["revenue"].sum() / video_spend if video_spend > 0 else 0
static_roas = static_df["revenue"].sum() / static_spend if static_spend > 0 else 0
with h2:
    st.markdown(f"""<div class="health-card">
    <div class="health-label">Video / Static ROAS</div>
    <div class="health-value">{video_roas:.2f} / {static_roas:.2f}</div>
    <div class="health-sub">{kc(video_spend)} / {kc(static_spend)}</div></div>""", unsafe_allow_html=True)

# Hook rate
hook_color = "#e53e3e" if avg_hook < 20 else "#d69e2e" if avg_hook < 25 else "#38a169"
with h3:
    st.markdown(f"""<div class="health-card">
    <div class="health-label">Hook Rate</div>
    <div class="health-value" style="color:{hook_color}">{avg_hook:.1f} %</div>
    <div class="health-sub">standard: 25 %+</div></div>""", unsafe_allow_html=True)

# Fatigue
freq_high = len(df[(df["frequency"] > 3.0) & (df["spend"] > 200)])
freq_warn = len(df[(df["frequency"] > 2.0) & (df["frequency"] <= 3.0) & (df["spend"] > 200)])
fat_color = "#e53e3e" if freq_high > 5 else "#d69e2e" if freq_high > 0 else "#38a169"
with h4:
    st.markdown(f"""<div class="health-card">
    <div class="health-label">Fatigue (freq 3+)</div>
    <div class="health-value" style="color:{fat_color}">{freq_high}</div>
    <div class="health-sub">+ {freq_warn} sledovat</div></div>""", unsafe_allow_html=True)

# Clickbait detection
clickbait = df[(df["ctr"] > 2.0) & (df["cvr"].notna()) & (df["cvr"] < 0.5) & (df["spend"] > 200)]
if len(clickbait) > 0:
    cb_spend = clickbait["spend"].sum()
    st.markdown(f"""<div class="clickbait-alert">
    ⚠️ <strong>Clickbait detekce:</strong> {len(clickbait)} kreativ s vysokym CTR ale mizivou CVR — celkem {kc(cb_spend)} zbytecneho spendu.
    Kreativa laka kliky ale neprodava.
    </div>""", unsafe_allow_html=True)

st.divider()

# ── Kampane ──

st.markdown("### Kampane")
cd = df.groupby("campaign_name").agg(spend=("spend","sum"), revenue=("revenue","sum"),
                                      purchases=("purchases","sum"), clicks=("clicks","sum"),
                                      ads=("ad_id","count")).reset_index()
cd["roas"] = (cd["revenue"] / cd["spend"]).round(2)
cd["cvr"] = ((cd["purchases"] / cd["clicks"]) * 100).round(2).where(cd["clicks"] > 0)
cd = cd.sort_values("spend", ascending=False)

fig_c = go.Figure(go.Bar(
    y=cd["campaign_name"], x=cd["spend"], orientation="h",
    marker_color=[COLORS["SCALE"] if r >= ci.TARGET_ROAS else COLORS["KILL"] for r in cd["roas"]],
    text=[f"ROAS {r}  ·  CVR {c:.1f}%  ·  {p} nakupu" for r, c, p in zip(cd["roas"], cd["cvr"].fillna(0), cd["purchases"])],
    textposition="inside", textfont_size=11,
))
fig_c.update_layout(height=300, margin=dict(t=10, b=10, l=5), showlegend=False,
                    xaxis_title="Utrata (Kc)", yaxis=dict(autorange="reversed"))
st.plotly_chart(fig_c, use_container_width=True)

# ── CVR Leaders (top performers kteri PRODAVAJI) ──

st.divider()
st.markdown("### CVR Leaders — kreativy co prodavaji")
st.caption("CTR = 4% ROI. Kreativa (a CVR) = 56% ROI. Tady jsou kreativy s nejvyssi konverzni mirou.")

cvr_df = df[(df["cvr"].notna()) & (df["purchases"] >= 3)].nlargest(8, "cvr")
if len(cvr_df) > 0:
    rows = []
    for _, ad in cvr_df.iterrows():
        typ = "🎬" if ad["is_video"] else "📸"
        rows.append({
            "": typ,
            "Kreativa": ad["ad_name"][:30],
            "CVR %": ad["cvr"],
            "CTR %": ad["ctr"],
            "ROAS": ad["roas"],
            "CPA (Kc)": ad["cpa"],
            "Nakupy": int(ad["purchases"]),
            "Utrata": int(ad["spend"]),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={
                     "": st.column_config.Column(width=35),
                     "CVR %": st.column_config.NumberColumn(format="%.2f", width=70),
                     "CTR %": st.column_config.NumberColumn(format="%.2f", width=70),
                     "ROAS": st.column_config.NumberColumn(format="%.2f", width=65),
                     "CPA (Kc)": st.column_config.NumberColumn(format="%.0f", width=70),
                 })

# ── Trend ──

if len(snaps) >= 2:
    st.divider()
    st.markdown("### Trend")
    td = [{"Datum": s["date"],
           "ROAS": s["data"].get("meta_ads",{}).get("overall_roas",0),
           "CVR %": s["data"].get("meta_ads",{}).get("overall_cvr",0),
           "Hook %": s["data"].get("meta_ads",{}).get("avg_hook_rate",0)} for s in reversed(snaps)]
    tdf = pd.DataFrame(td)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=tdf["Datum"], y=tdf["ROAS"], name="ROAS",
                             line=dict(color="#6c63ff", width=3), mode="lines+markers"))
    fig.add_trace(go.Scatter(x=tdf["Datum"], y=tdf["CVR %"], name="CVR %",
                             yaxis="y2", line=dict(color="#38a169", width=2), mode="lines+markers"))
    fig.add_trace(go.Scatter(x=tdf["Datum"], y=tdf["Hook %"], name="Hook %",
                             yaxis="y2", line=dict(color="#e53e3e", width=2, dash="dot"), mode="lines+markers"))
    fig.add_hline(y=ci.TARGET_ROAS, line_dash="dash", line_color="rgba(0,0,0,0.15)")
    fig.update_layout(yaxis=dict(title="ROAS"), yaxis2=dict(title="CVR % / Hook %", overlaying="y", side="right"),
                      height=280, margin=dict(t=10, b=30), legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, use_container_width=True)

# ── Footer ──

st.divider()
st.caption(f"Fermato Creative Intelligence v2 · {len(df)} kreativ · {days} dni · {datetime.now().strftime('%d.%m.%Y %H:%M')}")
