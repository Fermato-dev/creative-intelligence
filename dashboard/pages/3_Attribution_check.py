"""Fermato Creative Intelligence v3 — Attribution Check (Meta vs GA4 vs Shoptet)"""

import plotly.graph_objects as go
import streamlit as st
import pandas as pd
import os
import sys
from pathlib import Path

st.set_page_config(page_title="Attribution Check", page_icon="🔍", layout="wide")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    import streamlit as st
    st.stop()

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared_data import *

st.markdown(SHARED_CSS, unsafe_allow_html=True)
days, df, snaps, ai_data, show_low_conf = setup_sidebar()

if len(df) == 0:
    st.warning("Meta API data nejsou dostupna.")
    st.stop()

st.markdown("## Attribution Check — 3 zdroje, 1 pravda")
st.caption(f"Meta Ads vs GA4 vs Shoptet — poslednich {days} dni")

st.markdown("""<div class="reliability-banner">
<strong>Proc 3 zdroje:</strong> Meta reportuje vlastni atribuci (inflacni incentiv).
GA4 vidi vsechny kanaly nezavisle. Shoptet ma absolutni pravdu o objednavkach.
Trojuhelnik ukazuje kde je realita.
</div>""", unsafe_allow_html=True)

# ── Meta data ──

meta_purchases = int(df["purchases"].sum())
meta_revenue = df["revenue"].sum()
meta_spend = df["spend"].sum()
meta_roas = meta_revenue / meta_spend if meta_spend > 0 else 0

# ── GA4 data ──

ga4_data = None
ga4_error = None
try:
    from creative_intelligence.ga4_bridge import fetch_ga4_attribution

    @st.cache_data(ttl=3600, show_spinner="Nacitam GA4 data...")
    def load_ga4(d):
        return fetch_ga4_attribution(d)

    ga4_data = load_ga4(days)
except Exception as e:
    ga4_error = str(e)

# ── Shoptet data (NEZAVISLE na GA4) ──

shoptet_data = None
shoptet_error = None
shoptet_token = os.environ.get("SHOPTET_API_TOKEN")
if shoptet_token:
    try:
        from creative_intelligence.shoptet_bridge import fetch_daily_summary

        @st.cache_data(ttl=3600, show_spinner="Nacitam Shoptet data...")
        def load_shoptet(d):
            return fetch_daily_summary(d)

        shoptet_data = load_shoptet(days)
    except Exception as e:
        shoptet_error = str(e)
        import traceback
        shoptet_error = f"{e}\n{traceback.format_exc()}"

# ══════════════════════════════
# HLAVNI SROVNANI — vzdy zobrazit
# ══════════════════════════════

st.divider()
st.markdown("### Kolik nakupu vidi kazdy zdroj?")

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown(f"""<div class="health-card">
    <div class="health-label">Meta Ads (self-report)</div>
    <div class="health-value">{meta_purchases:,}</div>
    <div class="health-sub">{meta_revenue:,.0f} CZK · ROAS {meta_roas:.2f}</div></div>""", unsafe_allow_html=True)

with c2:
    if ga4_data:
        ga4_meta = ga4_data["meta_ga4"]
        ga4_color = "#38a169" if ga4_meta["purchases"] < meta_purchases * 0.7 else "#d69e2e"
        st.markdown(f"""<div class="health-card">
        <div class="health-label">GA4 (z Meta zdroju)</div>
        <div class="health-value" style="color:{ga4_color}">{ga4_meta['purchases']:,}</div>
        <div class="health-sub">{ga4_meta['revenue']:,} CZK · {ga4_meta['share_purchases_pct']}% vsech nakupu</div></div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">GA4</div>
        <div class="health-value" style="color:#ccc">—</div>
        <div class="health-sub">Chyba: {(ga4_error or 'Neznama')[:60]}</div></div>""", unsafe_allow_html=True)

with c3:
    if shoptet_data:
        st_totals = shoptet_data["totals"]
        st.markdown(f"""<div class="health-card">
        <div class="health-label">Shoptet (realita)</div>
        <div class="health-value">{st_totals['orders']:,}</div>
        <div class="health-sub">{st_totals['revenue']:,} CZK · AOV {st_totals['aov']} CZK</div></div>""", unsafe_allow_html=True)
    elif not shoptet_token:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">Shoptet</div>
        <div class="health-value" style="color:#ccc">—</div>
        <div class="health-sub">Neni SHOPTET_API_TOKEN env var</div></div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">Shoptet</div>
        <div class="health-value" style="color:#e53e3e">ERR</div>
        <div class="health-sub">Viz chyba nize</div></div>""", unsafe_allow_html=True)

# ── Shoptet error detail ──
if shoptet_token and shoptet_error:
    st.error(f"**Shoptet API chyba:** {shoptet_error}")

# ── Shoptet denni data (nezavisle na GA4) ──
if shoptet_data:
    st.divider()
    st.markdown("### Shoptet — denni objednavky")
    daily = shoptet_data.get("daily", [])
    if daily:
        dates = [d["date"] for d in daily]
        fig_st = go.Figure()
        fig_st.add_trace(go.Bar(x=dates, y=[d["orders"] for d in daily],
                                name="Objednavky", marker_color="rgba(56,161,105,0.6)"))
        fig_st.add_trace(go.Scatter(x=dates, y=[d["revenue"] for d in daily],
                                    name="Revenue (CZK)", yaxis="y2",
                                    line=dict(color="#6c63ff", width=2), mode="lines+markers"))
        fig_st.update_layout(
            height=300, margin=dict(t=10, b=30),
            yaxis=dict(title="Objednavky"), yaxis2=dict(title="Revenue", overlaying="y", side="right"),
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_st, use_container_width=True)

        # Errors in daily data
        errors = [d for d in daily if d.get("error")]
        if errors:
            st.warning(f"Shoptet API chyby pro {len(errors)} dni: {errors[0].get('error', '?')[:80]}")

# ══════════════════════════════
# GA4 detaily (pokud dostupne)
# ══════════════════════════════

if ga4_data:
    ga4_meta = ga4_data["meta_ga4"]
    ga4_totals = ga4_data["totals"]

    # ── Attribution gap ──
    st.divider()
    st.markdown("### Attribution gap")

    gap_ratio = meta_purchases / ga4_meta["purchases"] if ga4_meta["purchases"] > 0 else 0
    gap_pct = ((meta_purchases - ga4_meta["purchases"]) / ga4_meta["purchases"] * 100) if ga4_meta["purchases"] > 0 else 0
    true_roas_ga4 = ga4_meta["revenue"] / meta_spend if meta_spend > 0 else 0

    g1, g2, g3, g4 = st.columns(4)

    gap_color = "#e53e3e" if gap_pct > 100 else "#d69e2e" if gap_pct > 50 else "#38a169"
    with g1:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">Meta vs GA4 gap</div>
        <div class="health-value" style="color:{gap_color}">{gap_ratio:.1f}x</div>
        <div class="health-sub">Meta si pripisuje {gap_ratio:.1f}x vic</div></div>""", unsafe_allow_html=True)

    with g2:
        tr_color = "#38a169" if true_roas_ga4 >= TARGET_ROAS else "#d69e2e" if true_roas_ga4 >= 1.5 else "#e53e3e"
        st.markdown(f"""<div class="health-card">
        <div class="health-label">GA4-based ROAS</div>
        <div class="health-value" style="color:{tr_color}">{true_roas_ga4:.2f}</div>
        <div class="health-sub">GA4 Meta revenue / Meta spend</div></div>""", unsafe_allow_html=True)

    with g3:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">Meta share (GA4)</div>
        <div class="health-value">{ga4_meta['share_revenue_pct']:.0f} %</div>
        <div class="health-sub">z celkove GA4 revenue</div></div>""", unsafe_allow_html=True)

    with g4:
        st.markdown(f"""<div class="health-card">
        <div class="health-label">Mobile traffic</div>
        <div class="health-value">{ga4_data['mobile_pct']:.0f} %</div>
        <div class="health-sub">vyssi = vice iOS modelovani</div></div>""", unsafe_allow_html=True)

    # ── Srovnavaci tabulka ──
    st.divider()
    st.markdown("### Cisla vedle sebe")

    comp_rows = [
        {"Zdroj": "Meta Ads (self-report)", "Nakupy": f"{meta_purchases:,}",
         "Revenue (CZK)": f"{int(meta_revenue):,}", "ROAS": f"{meta_roas:.2f}"},
        {"Zdroj": "GA4 (Meta sources)", "Nakupy": f"{ga4_meta['purchases']:,}",
         "Revenue (CZK)": f"{ga4_meta['revenue']:,}", "ROAS": f"{true_roas_ga4:.2f}"},
    ]
    if shoptet_data:
        st_t = shoptet_data["totals"]
        st_roas = st_t["revenue"] / meta_spend if meta_spend > 0 else 0
        comp_rows.append({"Zdroj": "Shoptet (vsechny kanaly)", "Nakupy": f"{st_t['orders']:,}",
                         "Revenue (CZK)": f"{st_t['revenue']:,}", "ROAS": f"{st_roas:.2f}"})
    comp_rows.append({"Zdroj": "GA4 (vsechny kanaly)", "Nakupy": f"{ga4_totals['purchases']:,}",
                      "Revenue (CZK)": f"{ga4_totals['revenue']:,}", "ROAS": "—"})

    st.dataframe(pd.DataFrame(comp_rows), hide_index=True, use_container_width=True)

    # ── Channel Mix ──
    st.divider()
    st.markdown("### Channel Mix (GA4)")

    ch_data = ga4_data["channel_mix"]
    if ch_data:
        ch_df = pd.DataFrame(ch_data)
        ch_df["label"] = ch_df["source"] + " / " + ch_df["medium"]
        ch_top = ch_df.head(10)

        colors = ["#e53e3e" if r["is_meta"] else "#6c63ff" if r["source"] == "google" and r["medium"] == "cpc"
                  else "#38a169" if r["medium"] == "email" else "#a0aec0"
                  for _, r in ch_top.iterrows()]

        fig_ch = go.Figure(go.Bar(
            y=ch_top["label"], x=ch_top["revenue"], orientation="h",
            marker_color=colors,
            text=[f"{p} nakupu · CVR {c}%" for p, c in zip(ch_top["purchases"], ch_top["cvr"])],
            textposition="inside", textfont_size=11,
        ))
        fig_ch.update_layout(height=350, margin=dict(t=10, b=10, l=5), showlegend=False,
                            xaxis_title="Revenue (CZK)", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_ch, use_container_width=True)
        st.caption("Cervena = Meta (FB/IG) | Fialova = Google Ads | Zelena = Email | Seda = ostatni")

    # ── Devices ──
    st.divider()
    st.markdown("### Zarizeni")

    dev_data = ga4_data["devices"]
    if dev_data:
        dc1, dc2, dc3 = st.columns(3)
        for col, dev in zip([dc1, dc2, dc3], dev_data[:3]):
            icon = {"mobile": "📱", "desktop": "💻", "tablet": "📋"}.get(dev["device"], "?")
            with col:
                st.markdown(f"""<div class="health-card">
                <div class="health-label">{icon} {dev['device']}</div>
                <div class="health-value">{dev['sessions']:,}</div>
                <div class="health-sub">Revenue: {dev['revenue']:,} CZK · CVR: {dev['cvr']}%</div></div>""", unsafe_allow_html=True)

    # ── Denni trend GA4 ──
    daily_ga4 = ga4_data.get("daily", [])
    if daily_ga4 and len(daily_ga4) > 1:
        st.divider()
        st.markdown("### Denni trend (GA4)")
        dates = [d["date"][:4]+"-"+d["date"][4:6]+"-"+d["date"][6:8] if len(d["date"])==8 else d["date"] for d in daily_ga4]
        fig_daily = go.Figure()
        fig_daily.add_trace(go.Bar(x=dates, y=[d["purchases"] for d in daily_ga4],
                                   name="Nakupy", marker_color="rgba(108,99,255,0.5)"))
        fig_daily.add_trace(go.Scatter(x=dates, y=[d["revenue"] for d in daily_ga4],
                                       name="Revenue (CZK)", yaxis="y2",
                                       line=dict(color="#38a169", width=2), mode="lines+markers"))
        fig_daily.update_layout(
            height=320, margin=dict(t=10, b=30),
            yaxis=dict(title="Nakupy"), yaxis2=dict(title="Revenue", overlaying="y", side="right"),
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_daily, use_container_width=True)

    # ── Interpretace ──
    st.divider()
    st.markdown("### Jak cist tato data")
    gap_ratio_val = meta_purchases / ga4_data["meta_ga4"]["purchases"] if ga4_data["meta_ga4"]["purchases"] > 0 else 0
    st.markdown(f"""
**Meta si pripisuje {gap_ratio_val:.1f}x vic nakupu** nez GA4 vidi z Meta zdroju.

| Gap | Interpretace |
|---|---|
| **1.0-1.3x** | Zdravy — maly view-through podil |
| **1.3-2.0x** | Stredni — znacny view-through, ale jeste prijatelne |
| **2.0-3.0x** | Vysoky — Meta vyznamne nadfukuje |
| **3.0x+** | Extremni — zkontroluj attribution window |

**Doporuceni:**
- Pro relativni srovnani kreativ pouzivej **Meta data**
- Pro celkovou ROAS kanalu pouzivej **GA4 cisla**
- Pro absolutni pravdu o objednavkach pouzivej **Shoptet**
""")

else:
    st.warning(f"**GA4 neni dostupna:** {ga4_error or 'Neznama chyba'}. Zobrazuji pouze Meta + Shoptet data.")

# ── Debug info ──
with st.expander("Debug info", expanded=False):
    st.text(f"SHOPTET_API_TOKEN: {'set (' + shoptet_token[:8] + '...)' if shoptet_token else 'NOT SET'}")
    st.text(f"GA4: {'OK' if ga4_data else f'ERROR: {ga4_error}'}")
    st.text(f"Shoptet: {'OK — ' + str(shoptet_data.get('totals', {}).get('orders', 0)) + ' orders' if shoptet_data else f'ERROR: {shoptet_error}' if shoptet_error else 'No token'}")
    st.text(f"Meta: {meta_purchases} purchases, {meta_spend:,.0f} CZK spend")

st.divider()
st.caption(f"Attribution Check · {days} dni · {datetime.now().strftime('%d.%m.%Y %H:%M')}")
