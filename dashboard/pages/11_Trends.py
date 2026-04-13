"""Fermato Creative Intelligence — Trends & Performance Over Time"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Trends", page_icon="📈", layout="wide")

sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    st.stop()

DASHBOARD_DIR = Path(__file__).parent.parent
REPO_ROOT     = DASHBOARD_DIR.parent
DATA_DIR      = REPO_ROOT / "data"

sys.path.insert(0, str(DASHBOARD_DIR))
from shared_data import SHARED_CSS, kc, pct

st.markdown(SHARED_CSS, unsafe_allow_html=True)
st.markdown("""<style>
.trend-card {
    background:#1e293b; border:1px solid #334155; border-radius:10px;
    padding:14px 16px; text-align:center;
}
.trend-label {
    font-size:0.72em; color:#94a3b8 !important; text-transform:uppercase;
    letter-spacing:0.04em; font-weight:600;
}
.trend-value { font-size:1.5em; font-weight:700; color:#f1f5f9 !important; margin:4px 0; }
.trend-delta-up   { color:#4ade80 !important; font-size:0.82em; font-weight:600; }
.trend-delta-down { color:#f87171 !important; font-size:0.82em; font-weight:600; }
.trend-delta-flat { color:#64748b !important; font-size:0.82em; }
.section-note {
    background:#eef2ff; border-left:4px solid #6366f1; border-radius:8px;
    padding:10px 14px; font-size:0.83em; margin:6px 0 14px;
}
.section-note, .section-note * { color:#3730a3 !important; }
</style>""", unsafe_allow_html=True)


# ── Load snapshots ──

@st.cache_data(ttl=900, show_spinner="Načítám snapshot data...")
def load_snapshots():
    db = DATA_DIR / "creative_analysis.db"
    if not db.exists():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        df = pd.read_sql_query(
            "SELECT * FROM ad_daily_snapshots ORDER BY snapshot_date ASC", conn
        )
        conn.close()
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
        return df
    except Exception:
        return pd.DataFrame()


snap = load_snapshots()

# ── Sidebar ──
with st.sidebar:
    st.markdown("### Trends")
    if st.button("Obnovit data", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.divider()

    if len(snap) > 0:
        all_camps = sorted(snap["campaign_name"].dropna().unique())
        sel_camps = st.multiselect("Kampane", all_camps, default=all_camps, key="trend_camps")
        snap = snap[snap["campaign_name"].isin(sel_camps)]
        st.caption(f"Data: {snap['snapshot_date'].min().strftime('%d.%m.')} — {snap['snapshot_date'].max().strftime('%d.%m.')}")

# ── Page ──
st.markdown("## Trendy výkonu")

if len(snap) == 0:
    st.info("Žádná snapshot data — spusť runner alespoň dvakrát, aby se zobrazil trend.")
    st.stop()

# ── Daily account totals ──
daily = (
    snap.groupby("snapshot_date")
    .agg(spend=("spend", "sum"), purchases=("purchases", "sum"),
         revenue=("revenue", "sum"), ads=("ad_id", "nunique"))
    .reset_index()
)
daily["roas"] = daily["revenue"] / daily["spend"].replace(0, float("nan"))
daily["cpa"]  = daily["spend"]   / daily["purchases"].replace(0, float("nan"))
daily["date_str"] = daily["snapshot_date"].dt.strftime("%d.%m.")

# ── KPI delta cards (last day vs previous day) ──
st.markdown("### Denní srovnání (včera vs. předevčírem)")
if len(daily) >= 2:
    last  = daily.iloc[-1]
    prev  = daily.iloc[-2]

    def delta_html(cur, ref, fmt=".2f", higher_good=True):
        if ref == 0:
            return '<span class="trend-delta-flat">—</span>'
        d = (cur - ref) / ref * 100
        up = d > 0
        cls = ("trend-delta-up" if (up == higher_good) else "trend-delta-down")
        sign = "+" if d > 0 else ""
        return f'<span class="{cls}">{sign}{d:.1f}%</span>'

    c1, c2, c3, c4, c5 = st.columns(5)
    cards = [
        (c1, "Spend", kc(last["spend"]),   delta_html(last["spend"],     prev["spend"],     higher_good=False)),
        (c2, "Nákupy", int(last["purchases"]), delta_html(last["purchases"], prev["purchases"], higher_good=True)),
        (c3, "ROAS",   f"{last['roas']:.2f}" if pd.notna(last["roas"]) else "—",
                       delta_html(last["roas"] or 0, prev["roas"] or 0, higher_good=True)),
        (c4, "CPA",    kc(last["cpa"]),    delta_html(last["cpa"] or 0,  prev["cpa"] or 0,  higher_good=False)),
        (c5, "Aktivní reklamy", int(last["ads"]), delta_html(last["ads"], prev["ads"], higher_good=True)),
    ]
    for col, label, value, delta in cards:
        col.markdown(f"""<div class="trend-card">
<div class="trend-label">{label}</div>
<div class="trend-value">{value}</div>
{delta}</div>""", unsafe_allow_html=True)
else:
    st.info("Pro delta srovnání potřebuješ alespoň 2 dny dat.")

st.markdown("")

# ── ROAS & spend trend chart ──
st.markdown("### ROAS a spend — denní trend")

fig = go.Figure()
fig.add_trace(go.Bar(
    x=daily["date_str"], y=daily["spend"],
    name="Spend (Kč)", marker_color="#93c5fd",
    yaxis="y2", opacity=0.6,
))
fig.add_trace(go.Scatter(
    x=daily["date_str"], y=daily["roas"],
    name="ROAS", mode="lines+markers",
    line=dict(color="#4f46e5", width=2.5),
    marker=dict(size=7),
))
fig.update_layout(
    height=300, margin=dict(l=0, r=0, t=10, b=0),
    legend=dict(orientation="h", y=1.08),
    yaxis=dict(title="ROAS", rangemode="tozero"),
    yaxis2=dict(title="Spend (Kč)", overlaying="y", side="right", rangemode="tozero"),
    hovermode="x unified",
    plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb",
)
st.plotly_chart(fig, use_container_width=True)

# ── Purchases & CPA ──
st.markdown("### Nákupy a CPA — denní trend")

fig2 = go.Figure()
fig2.add_trace(go.Bar(
    x=daily["date_str"], y=daily["purchases"],
    name="Nákupy", marker_color="#86efac", opacity=0.8,
))
fig2.add_trace(go.Scatter(
    x=daily["date_str"], y=daily["cpa"],
    name="CPA (Kč)", mode="lines+markers",
    line=dict(color="#d97706", width=2.5),
    marker=dict(size=7),
    yaxis="y2",
))
fig2.update_layout(
    height=280, margin=dict(l=0, r=0, t=10, b=0),
    legend=dict(orientation="h", y=1.08),
    yaxis=dict(title="Nákupy", rangemode="tozero"),
    yaxis2=dict(title="CPA (Kč)", overlaying="y", side="right", rangemode="tozero"),
    hovermode="x unified",
    plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb",
)
st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Per-ad ROAS trend — top movers ──
st.markdown("### Největší pohyby reklam (ROAS)")

st.markdown(
    '<div class="section-note">Porovnání ROAS reklam mezi prvním a posledním dnem v datech. '
    'Ukazuje, které reklamy rostou nebo padají.</div>',
    unsafe_allow_html=True,
)

dates = sorted(snap["snapshot_date"].unique())
if len(dates) >= 2:
    first_day = dates[0]
    last_day  = dates[-1]

    first_df = snap[snap["snapshot_date"] == first_day][["ad_id", "ad_name", "campaign_name", "roas", "spend"]].copy()
    last_df  = snap[snap["snapshot_date"] == last_day][["ad_id", "roas", "spend", "purchases"]].copy()
    first_df.columns = ["ad_id", "ad_name", "campaign_name", "roas_first", "spend_first"]
    last_df.columns  = ["ad_id", "roas_last", "spend_last", "purch_last"]

    merged = first_df.merge(last_df, on="ad_id", how="inner")
    merged = merged[pd.notna(merged["roas_first"]) & pd.notna(merged["roas_last"])]
    merged["roas_delta"] = merged["roas_last"] - merged["roas_first"]
    merged["roas_delta_pct"] = merged["roas_delta"] / merged["roas_first"].replace(0, float("nan")) * 100

    merged = merged.sort_values("roas_delta", ascending=False)
    top_up   = merged.head(5)
    top_down = merged.tail(5).sort_values("roas_delta")

    col_up, col_down = st.columns(2)

    with col_up:
        st.markdown(f"**Nejvíce rostoucí** ({first_day.strftime('%d.%m.')} → {last_day.strftime('%d.%m.')})")
        for _, r in top_up.iterrows():
            d_str = f"+{r['roas_delta']:.2f}" if r['roas_delta'] > 0 else f"{r['roas_delta']:.2f}"
            st.markdown(f"""<div class="act-box act-scale">
<strong>{r['ad_name'][:30]}</strong><br>
ROAS {r['roas_first']:.2f} → {r['roas_last']:.2f} &nbsp;
<span style="color:#38a169;font-weight:700">{d_str}</span><br>
<small style="color:#6b7280">{r['campaign_name'][:25]} · spend {kc(r['spend_last'])}</small>
</div>""", unsafe_allow_html=True)

    with col_down:
        st.markdown(f"**Nejvíce klesající** ({first_day.strftime('%d.%m.')} → {last_day.strftime('%d.%m.')})")
        for _, r in top_down.iterrows():
            d_str = f"{r['roas_delta']:.2f}"
            st.markdown(f"""<div class="act-box act-kill">
<strong>{r['ad_name'][:30]}</strong><br>
ROAS {r['roas_first']:.2f} → {r['roas_last']:.2f} &nbsp;
<span style="color:#e53e3e;font-weight:700">{d_str}</span><br>
<small style="color:#6b7280">{r['campaign_name'][:25]} · spend {kc(r['spend_last'])}</small>
</div>""", unsafe_allow_html=True)

st.divider()

# ── Campaign-level ROAS trend ──
st.markdown("### ROAS podle kampaně — denní vývoj")

camp_daily = (
    snap.groupby(["snapshot_date", "campaign_name"])
    .agg(spend=("spend", "sum"), revenue=("revenue", "sum"))
    .reset_index()
)
camp_daily["roas"] = camp_daily["revenue"] / camp_daily["spend"].replace(0, float("nan"))
camp_daily["date_str"] = camp_daily["snapshot_date"].dt.strftime("%d.%m.")

fig3 = px.line(
    camp_daily, x="date_str", y="roas", color="campaign_name",
    markers=True,
    labels={"date_str": "", "roas": "ROAS", "campaign_name": "Kampaň"},
)
fig3.update_layout(
    height=300, margin=dict(l=0, r=0, t=10, b=0),
    legend=dict(orientation="h", y=1.12, font=dict(size=11)),
    plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb",
    hovermode="x unified",
)
st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ── Fatigue trend (frequency) ──
if "frequency" in snap.columns:
    st.markdown("### Frekvence — fatigue risk trend")
    freq_daily = (
        snap[snap["frequency"].notna()]
        .groupby("snapshot_date")
        .agg(avg_freq=("frequency", "mean"), max_freq=("frequency", "max"),
             ads_over_3=("frequency", lambda x: (x > 3).sum()))
        .reset_index()
    )
    freq_daily["date_str"] = freq_daily["snapshot_date"].dt.strftime("%d.%m.")

    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=freq_daily["date_str"], y=freq_daily["avg_freq"],
        name="Avg. frekvence", mode="lines+markers",
        line=dict(color="#6366f1", width=2),
    ))
    fig4.add_trace(go.Scatter(
        x=freq_daily["date_str"], y=freq_daily["max_freq"],
        name="Max. frekvence", mode="lines+markers",
        line=dict(color="#e53e3e", width=1.5, dash="dot"),
    ))
    fig4.add_trace(go.Bar(
        x=freq_daily["date_str"], y=freq_daily["ads_over_3"],
        name="Reklam s freq > 3", marker_color="#fcd34d", opacity=0.7,
        yaxis="y2",
    ))
    fig4.add_hline(y=3.0, line_dash="dash", line_color="#d97706",
                   annotation_text="Fatigue threshold 3.0", annotation_position="top right")
    fig4.update_layout(
        height=280, margin=dict(l=0, r=0, t=10, b=0),
        yaxis=dict(title="Frekvence"),
        yaxis2=dict(title="Počet reklam", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.08),
        hovermode="x unified",
        plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb",
    )
    st.plotly_chart(fig4, use_container_width=True)

st.markdown(
    '<div class="section-note">📌 Snapshot data jsou sbírána automaticky při každém spuštění runneru '
    '(<code>python -m creative_intelligence --days 1</code>). '
    f'Aktuálně {len(dates)} dní dat ({dates[0].strftime("%d.%m.")} – {dates[-1].strftime("%d.%m.")}).</div>',
    unsafe_allow_html=True,
)
