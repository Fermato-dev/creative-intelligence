"""Fermato Creative Intelligence — Creative Diversity Dashboard"""

import streamlit as st
st.set_page_config(page_title="Creative Diversity", page_icon="🎯", layout="wide")

import sys
from math import log2
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    st.stop()

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from collections import Counter

DASHBOARD_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(DASHBOARD_DIR))
from shared_data import SHARED_CSS, load_creative_tags, kc, pct

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── Custom CSS ──
st.markdown("""<style>
.tl-card { border-radius: 10px; padding: 14px 16px; text-align: center;
    border: 1px solid #e8ecf1; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.tl-green { background: #f0fdf4; border-color: #86efac; }
.tl-yellow { background: #fefce8; border-color: #fde047; }
.tl-red { background: #fef2f2; border-color: #fca5a5; }
.tl-icon { font-size: 2em; margin-bottom: 4px; }
.tl-label { font-size: 0.72em; color: #6b7280; text-transform: uppercase;
    letter-spacing: 0.04em; font-weight: 600; }
.tl-value { font-size: 1.3em; font-weight: 700; color: #1a202c; margin: 4px 0; }
.tl-sub { font-size: 0.78em; color: #9ca3af; }

.rec-card { border-radius: 10px; padding: 14px 16px; margin: 6px 0; }
.rec-scale { background: #f0fdf4; border-left: 4px solid #38a169; }
.rec-iterate { background: #fefce8; border-left: 4px solid #d69e2e; }
.rec-kill { background: #fef2f2; border-left: 4px solid #e53e3e; }
.rec-title { font-weight: 700; font-size: 0.85em; margin-bottom: 4px; }
.rec-body { font-size: 0.84em; color: #374151; line-height: 1.5; }

.insight-box { background: linear-gradient(135deg, #eef9f7 0%, #f0fdf4 100%);
    border: 1px solid #99f6e4; border-radius: 10px; padding: 14px 18px; margin: 8px 0; }
.insight-box strong { color: #0f766e; }

.arch-table { width: 100%; border-collapse: collapse; font-size: 0.84em; }
.arch-table th { background: #f8f9fb; color: #6b7280; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.03em; font-size: 0.75em; padding: 8px 10px; text-align: left; border-bottom: 2px solid #e5e7eb; }
.arch-table td { padding: 8px 10px; border-bottom: 1px solid #f3f4f6; color: #374151; }
.arch-table tr:hover { background: #f8fafc; }
.arch-bar { height: 6px; border-radius: 3px; background: #e5e7eb; }
.arch-fill { height: 100%; border-radius: 3px; }

.cg-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 12px 0; }
@media (max-width: 768px) { .cg-grid { grid-template-columns: 1fr; } }
.cg-card { display: flex; gap: 12px; padding: 12px; border-radius: 10px;
    border: 1px solid #e8ecf1; background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04); transition: all 0.15s; }
.cg-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-color: #c7d2fe; transform: translateY(-1px); }
.cg-thumb { width: 80px; height: 80px; border-radius: 8px; object-fit: cover; flex-shrink: 0; background: #f1f5f9; }
.cg-thumb-placeholder { width: 80px; height: 80px; border-radius: 8px; flex-shrink: 0;
    background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
    display: flex; align-items: center; justify-content: center; font-size: 1.6em; color: #94a3b8; }
.cg-meta { flex: 1; min-width: 0; }
.cg-name { font-weight: 600; font-size: 0.82em; color: #1e293b; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
.cg-badges { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.cg-badge { font-size: 0.68em; padding: 2px 7px; border-radius: 4px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.03em; }
.cg-metrics { display: flex; gap: 8px; flex-wrap: wrap; font-size: 0.74em; color: #6b7280; }
.cg-metric { white-space: nowrap; }
.cg-metric b { color: #374151; }
.cg-copy { font-size: 0.72em; color: #9ca3af; margin-top: 4px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
.cg-link { display: inline-block; font-size: 0.7em; color: #6366f1; text-decoration: none;
    font-weight: 600; margin-top: 4px; }
.cg-link:hover { color: #4f46e5; text-decoration: underline; }
.cg-conf-hi { background: #dcfce7; color: #166534; }
.cg-conf-mid { background: #fef9c3; color: #854d0e; }
.cg-conf-lo { background: #fee2e2; color: #991b1b; }
</style>""", unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 🎯 Creative Diversity")
    st.caption("Diverzita archetypu, hooku a vizualu")
    if st.button("Obnovit data", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.divider()

# ── Load data ──
tags = load_creative_tags()

if len(tags) == 0:
    st.warning("Zadna creative diversity data. Spustte precise archetype tagger.")
    st.stop()

# Filter to ads with archetype
tags = tags[tags["archetype"].notna() & (tags["archetype"] != "unknown")]

with st.sidebar:
    min_spend = st.slider("Min. spend (CZK)", 0, 5000, 200, 100)
    tags = tags[tags["spend"] >= min_spend]
    gallery_sort = st.selectbox("Radit galerii dle", ["Spend", "ROAS", "Hook Rate", "CPA"], index=0)
    st.caption(f"{len(tags)} kreativ | Data: {tags['tagged_at'].max() if 'tagged_at' in tags.columns else '?'}")

# ══════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════

st.markdown("## Creative Diversity")
total_spend = tags["spend"].sum()
total_purchases = tags["purchases"].sum()
total_revenue = sum(r["spend"] * r["roas"] for _, r in tags.iterrows() if pd.notna(r.get("roas")) and pd.notna(r.get("spend")))

c1, c2, c3, c4, c5 = st.columns(5)
video_tags = tags[tags["hook_rate"].notna()]
avg_hook = video_tags["hook_rate"].mean() if len(video_tags) > 0 else 0
overall_roas = total_revenue / total_spend if total_spend > 0 else 0
overall_cpa = total_spend / total_purchases if total_purchases > 0 else 0

c1.metric("Kreativ", len(tags))
c2.metric("Avg Hook Rate", pct(avg_hook))
c3.metric("ROAS", f"{overall_roas:.2f}")
c4.metric("CPA", kc(overall_cpa))
c5.metric("Spend", kc(total_spend))

# ══════════════════════════════════════════════
# SECTION 1: TRAFFIC LIGHT DIAGNOSTIC
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Traffic Light Diagnostic")


def shannon_entropy_norm(series):
    counts = Counter(series.dropna())
    total = sum(counts.values())
    if total == 0 or len(counts) <= 1:
        return 0.0
    entropy = -sum((c/total) * log2(c/total) for c in counts.values() if c > 0)
    max_ent = log2(len(counts))
    return entropy / max_ent if max_ent > 0 else 0.0


def tl_status(val, green, yellow):
    if val >= green: return "green", "🟢"
    if val >= yellow: return "yellow", "🟡"
    return "red", "🔴"


# Compute 5 dimensions
arch_entropy = shannon_entropy_norm(tags["archetype"])
person_spend = tags[tags["person_present"] == "yes"]["spend"].sum() / total_spend * 100 if total_spend > 0 else 0
hook_types_with_spend = len([h for h, g in tags.groupby("hook_strategy") if g["spend"].sum() / total_spend > 0.05]) if "hook_strategy" in tags.columns else 0
has_lofi = tags[tags["production_quality"] == "amateur"]["spend"].sum() > total_spend * 0.1
has_pro = tags[tags["production_quality"] == "professional"]["spend"].sum() > total_spend * 0.1
prod_mix = 2 if (has_lofi and has_pro) else 1 if (has_lofi or has_pro) else 0
founder_pct = tags[tags["archetype"] == "founder_story"]["spend"].sum() / total_spend * 100 if total_spend > 0 else 0

dims = [
    ("Archetype Diversity", f"entropy {arch_entropy:.2f}", *tl_status(arch_entropy, 0.75, 0.55),
     f"{len(tags['archetype'].unique())} archetypu"),
    ("Person Coverage", f"{person_spend:.0f}% spendu", *tl_status(person_spend, 50, 30),
     "s osobou v kreative"),
    ("Hook Variety", f"{hook_types_with_spend} typu", *tl_status(hook_types_with_spend, 4, 2),
     "hook strategii > 5% spend"),
    ("Production Mix", f"{'oba' if prod_mix == 2 else 'jeden' if prod_mix == 1 else 'zadny'}", *tl_status(prod_mix, 2, 1),
     "lo-fi + professional"),
    ("Founder Story", f"{founder_pct:.0f}% spendu", *tl_status(founder_pct, 15, 5),
     "sweet spot archetyp"),
]

cols = st.columns(5)
worst_status = "green"
for col, (label, value, status, icon, sub) in zip(cols, dims):
    col.markdown(f"""
    <div class="tl-card tl-{status}">
        <div class="tl-icon">{icon}</div>
        <div class="tl-label">{label}</div>
        <div class="tl-value">{value}</div>
        <div class="tl-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)
    if status == "red": worst_status = "red"
    elif status == "yellow" and worst_status != "red": worst_status = "yellow"


# ══════════════════════════════════════════════
# SECTION 2: ARCHETYPE DISTRIBUTION
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Archetypy — distribuce a vykon")

# Compute per-archetype stats
arch_stats = []
for arch, group in tags.groupby("archetype"):
    video_group = group[group["hook_rate"].notna()]
    avg_h = video_group["hook_rate"].mean() if len(video_group) > 0 else 0
    t_spend = group["spend"].sum()
    t_rev = sum(r["spend"] * r["roas"] for _, r in group.iterrows() if pd.notna(r.get("roas")))
    t_purch = group["purchases"].sum()
    arch_roas = t_rev / t_spend if t_spend > 0 else 0
    arch_cpa = t_spend / t_purch if t_purch > 0 else 0
    arch_stats.append({
        "Archetyp": arch, "Pocet": len(group),
        "Podil": t_spend / total_spend * 100,
        "Spend": t_spend, "Hook Rate": avg_h,
        "ROAS": arch_roas, "CPA": arch_cpa,
    })

arch_df = pd.DataFrame(arch_stats).sort_values("Spend", ascending=False)

# Horizontal bar chart
fig_arch = go.Figure()
colors = {"founder_story": "#059669", "ugc_social_proof": "#0d9488", "lifestyle": "#6366f1",
          "product_demo": "#9ca3af", "problem_solution": "#d97706", "educational": "#ec4899",
          "curiosity_gap": "#8b5cf6"}

for _, row in arch_df.iterrows():
    color = colors.get(row["Archetyp"], "#94a3b8")
    fig_arch.add_trace(go.Bar(
        y=[row["Archetyp"]], x=[row["Spend"]],
        orientation="h", name=row["Archetyp"],
        marker_color=color, showlegend=False,
        text=f'{row["Podil"]:.0f}% | Hook {row["Hook Rate"]:.1f}% | ROAS {row["ROAS"]:.2f}',
        textposition="inside", textfont=dict(color="white", size=12),
        hovertemplate=f'<b>{row["Archetyp"]}</b><br>Spend: {kc(row["Spend"])}<br>'
                      f'Hook: {row["Hook Rate"]:.1f}%<br>ROAS: {row["ROAS"]:.2f}<br>CPA: {kc(row["CPA"])}<extra></extra>',
    ))

fig_arch.update_layout(
    height=280, margin=dict(l=0, r=0, t=10, b=0),
    xaxis_title="Spend (CZK)", yaxis=dict(autorange="reversed"),
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_arch, use_container_width=True)

# Performance table
st.markdown("""<table class="arch-table">
<tr><th>Archetyp</th><th>Pocet</th><th>Podil</th><th>Avg Hook</th><th>ROAS</th><th>CPA</th><th>Spend</th></tr>""" +
"".join(f"""<tr>
    <td><strong>{r['Archetyp']}</strong></td>
    <td>{r['Pocet']}</td>
    <td>{r['Podil']:.0f}%</td>
    <td>{r['Hook Rate']:.1f}%</td>
    <td>{r['ROAS']:.2f}</td>
    <td>{kc(r['CPA'])}</td>
    <td>{kc(r['Spend'])}</td>
</tr>""" for _, r in arch_df.iterrows()) +
"</table>", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# SECTION 2b: CREATIVE GALLERY — DRILL-DOWN
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Creative Gallery — proklik na kreativy")

ADS_MANAGER_URL = "https://business.facebook.com/adsmanager/manage/ads?act=346692147206629&selected_ad_ids="
SORT_MAP = {"Spend": ("spend", False), "ROAS": ("roas", False), "Hook Rate": ("hook_rate", False), "CPA": ("cpa", True)}
sort_col, sort_asc = SORT_MAP.get(gallery_sort, ("spend", False))

for arch in arch_df["Archetyp"].values:
    arch_group = tags[tags["archetype"] == arch].copy()
    if len(arch_group) == 0:
        continue

    # Sort
    if sort_col in arch_group.columns:
        arch_group = arch_group.sort_values(sort_col, ascending=sort_asc, na_position="last")

    arch_color = colors.get(arch, "#94a3b8")
    arch_row = arch_df[arch_df["Archetyp"] == arch].iloc[0]
    label = f"{arch} — {int(arch_row['Pocet'])} kreativ | ROAS {arch_row['ROAS']:.2f} | Hook {arch_row['Hook Rate']:.1f}%"

    with st.expander(label, expanded=False):
        cards_html = '<div class="cg-grid">'
        for _, ad in arch_group.iterrows():
            ad_id = ad.get("ad_id", "")
            ad_name = str(ad.get("ad_name", ""))[:60]
            thumb_url = ad.get("thumbnail_url") or ad.get("image_url") or ""
            hook = ad.get("hook_strategy", "")
            hook_rate = ad.get("hook_rate")
            roas = ad.get("roas")
            cpa = ad.get("cpa")
            spend = ad.get("spend", 0)
            conf = ad.get("archetype_confidence", 0) or 0
            copy_text = str(ad.get("ad_copy", ""))[:80]
            person = ad.get("person_type", "none")
            style = ad.get("visual_style", "")
            quality = ad.get("production_quality", "")

            # Thumbnail or placeholder
            if thumb_url:
                thumb_html = f'<img class="cg-thumb" src="{thumb_url}" alt="" onerror="this.outerHTML=\'<div class=cg-thumb-placeholder>&#x1f3ac;</div>\'">'
            else:
                thumb_html = '<div class="cg-thumb-placeholder">&#x1f3ac;</div>'

            # Confidence badge
            if conf >= 0.8:
                conf_cls = "cg-conf-hi"
            elif conf >= 0.6:
                conf_cls = "cg-conf-mid"
            else:
                conf_cls = "cg-conf-lo"

            # Hook badge color
            hook_colors = {
                "contradiction": "#7c3aed", "ugc_reaction": "#0d9488", "visual_reveal": "#2563eb",
                "statement": "#d97706", "product_hero": "#6b7280", "question": "#db2777",
                "problem_opening": "#ea580c", "curiosity_gap": "#8b5cf6",
            }
            hook_bg = hook_colors.get(hook, "#94a3b8")

            # Metrics
            metrics_parts = []
            if hook_rate is not None and pd.notna(hook_rate):
                metrics_parts.append(f'<span class="cg-metric"><b>{hook_rate:.1f}%</b> hook</span>')
            if roas is not None and pd.notna(roas):
                metrics_parts.append(f'<span class="cg-metric"><b>{roas:.2f}</b> ROAS</span>')
            if cpa is not None and pd.notna(cpa):
                metrics_parts.append(f'<span class="cg-metric"><b>{cpa:,.0f}</b> CPA</span>')
            metrics_parts.append(f'<span class="cg-metric"><b>{spend:,.0f}</b> CZK</span>')
            metrics_html = " ".join(metrics_parts)

            # Person/style info
            detail_badges = ""
            if person and person != "none":
                detail_badges += f'<span class="cg-badge" style="background:#e0f2fe;color:#0369a1">{person}</span>'
            if quality:
                q_colors = {"amateur": "#fef3c7", "professional": "#dbeafe", "semi_pro": "#f3e8ff", "raw_ugc": "#fce7f3"}
                q_bg = q_colors.get(quality, "#f1f5f9")
                detail_badges += f'<span class="cg-badge" style="background:{q_bg};color:#374151">{quality}</span>'

            cards_html += f'''<div class="cg-card">
                {thumb_html}
                <div class="cg-meta">
                    <div class="cg-name" title="{ad_name}">{ad_name}</div>
                    <div class="cg-badges">
                        <span class="cg-badge" style="background:{arch_color};color:#fff">{arch}</span>
                        <span class="cg-badge" style="background:{hook_bg};color:#fff">{hook}</span>
                        <span class="cg-badge {conf_cls}">{conf:.0%}</span>
                        {detail_badges}
                    </div>
                    <div class="cg-metrics">{metrics_html}</div>
                    <div class="cg-copy" title="{copy_text}">{copy_text}</div>
                    <a class="cg-link" href="{ADS_MANAGER_URL}{ad_id}" target="_blank">Otevrit v Ads Manager &#x2197;</a>
                </div>
            </div>'''

        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════
# SECTION 3: SIGNAL ANALYSIS
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Signaly — co ovlivnuje hook rate")


def signal_chart(df, column, title):
    """Creates a horizontal bar chart for a signal dimension."""
    stats = []
    for val, group in df.groupby(column):
        video_g = group[group["hook_rate"].notna()]
        if len(video_g) == 0:
            continue
        stats.append({
            "label": str(val), "count": len(group),
            "hook_rate": video_g["hook_rate"].mean(),
            "spend": group["spend"].sum(),
        })
    if not stats:
        return None
    stats_df = pd.DataFrame(stats).sort_values("hook_rate", ascending=True)

    fig = go.Figure(go.Bar(
        y=stats_df["label"], x=stats_df["hook_rate"],
        orientation="h",
        marker_color=[
            "#059669" if h >= 20 else "#d69e2e" if h >= 12 else "#9ca3af"
            for h in stats_df["hook_rate"]
        ],
        text=[f'{h:.1f}% (n={n})' for h, n in zip(stats_df["hook_rate"], stats_df["count"])],
        textposition="outside",
        hovertemplate='<b>%{y}</b><br>Hook: %{x:.1f}%<extra></extra>',
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        height=max(180, len(stats_df) * 35 + 60),
        margin=dict(l=0, r=60, t=35, b=0),
        xaxis=dict(title="Avg Hook Rate %", range=[0, max(stats_df["hook_rate"]) * 1.3]),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


tab1, tab2, tab3, tab4 = st.tabs(["Person Type", "Visual Style", "Hook Strategy", "Production Quality"])

with tab1:
    if "person_type" in tags.columns:
        fig = signal_chart(tags, "person_type", "Hook Rate dle osoby v kreative")
        if fig: st.plotly_chart(fig, use_container_width=True)
        st.markdown("""<div class="insight-box">
        <strong>Klicovy nalez:</strong> Kreativy s osobou maji 3x vyssi hook rate nez bez osoby.
        Zakaznik (38%) > UGC creator (24%) > founder (20%) > model (14%) > bez osoby (7%).
        </div>""", unsafe_allow_html=True)

with tab2:
    if "visual_style" in tags.columns:
        fig = signal_chart(tags, "visual_style", "Hook Rate dle vizualniho stylu")
        if fig: st.plotly_chart(fig, use_container_width=True)
        st.markdown("""<div class="insight-box">
        <strong>Klicovy nalez:</strong> Lo-fi styl (23.5%) drti polished (8.3%) a minimalist (3.4%).
        Autenticita = vyssi engagement.
        </div>""", unsafe_allow_html=True)

with tab3:
    if "hook_strategy" in tags.columns:
        fig = signal_chart(tags, "hook_strategy", "Hook Rate dle hook strategie")
        if fig: st.plotly_chart(fig, use_container_width=True)
        st.markdown("""<div class="insight-box">
        <strong>Klicovy nalez:</strong> Contradiction hook (43.8%) a ugc_reaction (26.3%) vyrazne
        prekonavaji product_hero (8.9%) a question (6.2%).
        </div>""", unsafe_allow_html=True)

with tab4:
    if "production_quality" in tags.columns:
        fig = signal_chart(tags, "production_quality", "Hook Rate dle produkce")
        if fig: st.plotly_chart(fig, use_container_width=True)
        st.markdown("""<div class="insight-box">
        <strong>Klicovy nalez:</strong> Amateur/lo-fi produkce (23.9%) prekonava professional (6.0%) 4x.
        Andromeda odmenuje autenticitu.
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# SECTION 4: PERFORMANCE MATRIX (Archetype × Hook)
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Performance Matrix — Archetyp × Hook")

if "hook_strategy" in tags.columns and "archetype" in tags.columns:
    video_tags = tags[tags["hook_rate"].notna()]
    if len(video_tags) > 0:
        pivot = video_tags.groupby(["archetype", "hook_strategy"]).agg(
            hook_rate=("hook_rate", "mean"),
            count=("hook_rate", "count"),
        ).reset_index()

        archetypes = sorted(pivot["archetype"].unique())
        hooks = sorted(pivot["hook_strategy"].unique())

        z_data = []
        text_data = []
        for arch in archetypes:
            row_z = []
            row_t = []
            for hook in hooks:
                cell = pivot[(pivot["archetype"] == arch) & (pivot["hook_strategy"] == hook)]
                if len(cell) > 0:
                    hr = cell.iloc[0]["hook_rate"]
                    n = int(cell.iloc[0]["count"])
                    row_z.append(hr)
                    row_t.append(f"{hr:.0f}%<br>n={n}")
                else:
                    row_z.append(None)
                    row_t.append("")
            z_data.append(row_z)
            text_data.append(row_t)

        fig_matrix = go.Figure(go.Heatmap(
            z=z_data, x=hooks, y=archetypes,
            text=text_data, texttemplate="%{text}",
            colorscale=[[0, "#fef2f2"], [0.3, "#fefce8"], [0.6, "#f0fdf4"], [1.0, "#059669"]],
            zmin=0, zmax=45,
            hoverongaps=False,
            colorbar=dict(title="Hook Rate %"),
        ))
        fig_matrix.update_layout(
            height=300, margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(side="top"),
        )
        st.plotly_chart(fig_matrix, use_container_width=True)
        st.caption("Barva = prumerny hook rate. n = pocet kreativ v kombinaci. Bile = zadna data.")


# ══════════════════════════════════════════════
# SECTION 5: RECOMMENDATIONS
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Doporuceni")

recs = []

# Founder story underutilized?
if founder_pct < 15:
    founder_data = arch_df[arch_df["Archetyp"] == "founder_story"]
    if len(founder_data) > 0:
        fr = founder_data.iloc[0]
        recs.append(("scale", "Skalovat Founder Story",
                      f'Pouze {fr["Podil"]:.0f}% portfolia, ale ROAS {fr["ROAS"]:.2f} a hook {fr["Hook Rate"]:.1f}%. '
                      f'Sweet spot — vysoky hook I vysoka konverze. Vyrobit 5-10 variant.'))

# Person coverage low?
if person_spend < 50:
    recs.append(("scale", "Vice kreativ s osobou",
                 f'Kreativy s osobou maji 3x vyssi hook rate. Aktualne pouze {person_spend:.0f}% spendu jde na kreativy s osobou.'))

# Lo-fi underutilized?
lofi_tags = tags[tags["production_quality"] == "amateur"]
pro_tags = tags[tags["production_quality"] == "professional"]
if len(pro_tags) > 0 and len(lofi_tags) > 0:
    lofi_hook = lofi_tags[lofi_tags["hook_rate"].notna()]["hook_rate"].mean()
    pro_hook = pro_tags[pro_tags["hook_rate"].notna()]["hook_rate"].mean()
    if lofi_hook > pro_hook * 1.5:
        recs.append(("iterate", "Presunout z professional na lo-fi",
                     f'Lo-fi hook {lofi_hook:.1f}% vs professional {pro_hook:.1f}%. '
                     f'Nove kreativy prednostne v autentickem stylu.'))

# Product demo too dominant?
pd_row = arch_df[arch_df["Archetyp"] == "product_demo"]
if len(pd_row) > 0 and pd_row.iloc[0]["Podil"] > 40:
    recs.append(("kill", "Snizit podil product_demo",
                 f'Product demo tvori {pd_row.iloc[0]["Podil"]:.0f}% portfolia s hook rate {pd_row.iloc[0]["Hook Rate"]:.1f}%. '
                 f'Presmerovavat spend do founder_story a UGC.'))

# Contradiction hook?
contra_tags = tags[tags["hook_strategy"] == "contradiction"]
if len(contra_tags) > 0:
    contra_video = contra_tags[contra_tags["hook_rate"].notna()]
    if len(contra_video) > 0:
        contra_hook = contra_video["hook_rate"].mean()
        if contra_hook > 30 and len(contra_video) < 5:
            recs.append(("scale", "Testovat contradiction hooky",
                         f'Contradiction hook ma {contra_hook:.0f}% hook rate na {len(contra_video)} kreativach. '
                         f'Maly vzorek, ale silny signal — testovat vice.'))

if not recs:
    recs.append(("scale", "Portfolio je vyvazene", "Zadne urgentni akce. Udrzovat stav."))

for rec_type, title, body in recs:
    css_class = {"scale": "rec-scale", "iterate": "rec-iterate", "kill": "rec-kill"}.get(rec_type, "rec-scale")
    emoji = {"scale": "🟢", "iterate": "🟡", "kill": "🔴"}.get(rec_type, "⚪")
    st.markdown(f"""<div class="rec-card {css_class}">
        <div class="rec-title">{emoji} {title}</div>
        <div class="rec-body">{body}</div>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# SECTION 6: TARGET COMPARISON
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Aktualni vs cilovy mix")

targets = {
    "product_demo": 25, "ugc_social_proof": 25, "founder_story": 20,
    "lifestyle": 15, "problem_solution": 10, "educational": 5,
}

comparison = []
for arch in targets:
    current = 0
    row = arch_df[arch_df["Archetyp"] == arch]
    if len(row) > 0:
        current = row.iloc[0]["Podil"]
    gap = targets[arch] - current
    comparison.append({"Archetyp": arch, "Aktualni": current, "Cil": targets[arch], "Gap": gap})

comp_df = pd.DataFrame(comparison)

fig_comp = go.Figure()
fig_comp.add_trace(go.Bar(
    x=comp_df["Archetyp"], y=comp_df["Aktualni"], name="Aktualni",
    marker_color="#94a3b8", text=[f'{v:.0f}%' for v in comp_df["Aktualni"]],
    textposition="outside",
))
fig_comp.add_trace(go.Bar(
    x=comp_df["Archetyp"], y=comp_df["Cil"], name="Cil",
    marker_color="#059669", opacity=0.3, text=[f'{v:.0f}%' for v in comp_df["Cil"]],
    textposition="outside",
))
fig_comp.update_layout(
    barmode="group", height=300,
    margin=dict(l=0, r=0, t=10, b=0),
    yaxis_title="% spendu", legend=dict(orientation="h", y=1.15),
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_comp, use_container_width=True)


# ══════════════════════════════════════════════
# SECTION 7: INSPIRACE — CO DELAJI JINAK JINDE
# ══════════════════════════════════════════════

st.markdown("---")
st.markdown("### Inspirace ze sveta — co delaji jinak?")

insp_tab1, insp_tab2, insp_tab3 = st.tabs(["Brandy & Taktiky", "Formaty k vyzkouseni", "Konkretni napady"])

with insp_tab1:
    st.markdown("""
<div class="insight-box">
<strong>Mid-Day Squares ($30M)</strong> — 3 zakladatele na kameru DENNE. Business behind-the-scenes, priznani chyb, osobni zranitelnost.
Factory vlog = 438K zhlednuti. <em>Pro Fermato: "The Fermato Show" — CEO 2-3x tydne, ne jen uspechy ale i prusery.</em>
</div>

<div class="insight-box">
<strong>Graza (olivovy olej, $50M+)</strong> — 9 mesicu BEZ reklam. Vzorky creatorum pres DM, zadne smlouvy.
Facebook ads = prepouzite TikTok klipy. Absurdisticky humor ("847 lzicek").
<em>Pro Fermato: Poslat zalivky 30 food micro-influencerum v CZ/HU. Prepouzit jejich obsah jako Meta Ads.</em>
</div>

<div class="insight-box">
<strong>The Ordinary — radikalni transparentnost</strong> — Produkty pojmenovane po slozkach. Zadne glamour.
Vzdelavaci obsah co produkt dela a co NEDELA.
<em>Pro Fermato: Split screen etiketa supermarket vs Fermato. "Co vase zalivka NEUMI je stejne dulezite."</em>
</div>

<div class="insight-box">
<strong>Fly By Jing (condiments)</strong> — Moderni dating jazyk: "No strings attached, just noods."
Zakladatelka na osobnim uctu sdili food filozofii.
<em>Pro Fermato: "Ghostujete svuj salat? Fermato vam pomuze najit The One."</em>
</div>

<div class="insight-box">
<strong>Liquid Death ($1.4B)</strong> — Collab s e.l.f. Cosmetics — vyprodano za 45 minut.
Negativni komentare = material pro dalsi content. Prvni spot za $1,500.
<em>Pro Fermato: Collab s necekany CZ brandem. Negativni komentare jako content.</em>
</div>

<div class="insight-box">
<strong>Siete Family Foods ($200M)</strong> — 7 clenu rodiny = brand. Kampan natocena in-house rodinou.
Z osobni potreby (autoimunitni onemocneni) = brand.
<em>Pro Fermato: Osobni pribeh zakladatele jako MOTOR kazde kampane, ne jen "O nas" stranka.</em>
</div>
""", unsafe_allow_html=True)

with insp_tab2:
    st.markdown("""
| Format | Inspirace | Effort | Proc funguje |
|--------|-----------|--------|-------------|
| **"Reality show" serie** | Mid-Day Squares | Low | Founder hook — nase data: ROAS 2.59 |
| **Srovnavaci reklama (etikety)** | The Ordinary | Low | Contradiction hook — nase data: 40.6% |
| **Behind-the-scenes vyroba** | Top DTC format 2026 | Low-Med | Transparentnost + curiosity |
| **Anti-ad / ugly ad** | 42% top DTC reklam je lo-fi | Low | Lo-fi — nase data: hook 23.5% |
| **Challenge content** | #FermatoChallenge | Low | UGC generator, viralni potencial |
| **Meme marketing** | Liquid Death, Fly By Jing | Low | 60% organicky engagement |
| **Customer stories** | Siete, Farmer's Dog | Med | Customer — nase data: hook 38.4% |
| **Podcast snippet** | AG1 ($2.2M/mes podcast ads) | Med | Anti-ad format, intimni |
| **Chef x Brand collab** | Liquid Death collab model | Med-High | Novy audience, sdilene publikum |
| **Vzdelavaci mini-serie** | The Ordinary | Low-Med | Educational — nase data: hook 26.3% |
""")

    st.markdown("""<div class="insight-box">
    <strong>Klicove:</strong> Kazdy format je propojen s nasimi daty. Necopirujeme slepe — testujeme to,
    co nase cisla naznacuji ze by mohlo fungovat (contradiction, lo-fi, osoba, founder).
    </div>""", unsafe_allow_html=True)

with insp_tab3:
    st.markdown("#### Quick wins (telefon, 1 osoba)")
    st.markdown("""
1. **"Tohle jsem nechtela nikomu rikat"** — Zakaznice selfie: "...ale dam tu zalivku doslova na vsechno." 15s Reel. Hook: curiosity_gap.
2. **"Srovnani — co je UVNITR"** — Split screen: supermarket vs Fermato etikety. 30s Reel. Hook: contradiction. *(The Ordinary)*
3. **"Zachrante veceri"** — POV hands-only. Poloprazdna lednice → zalivka = hotovy salat za 60s. Hook: problem_opening.
4. **"Ghostujete svuj salat?"** — Meme: "Ja: Budu jist zdraveji. Taky ja:" + leje zalivku na vsechno. 15s. *(Fly By Jing)*
""")

    st.markdown("#### Medium effort")
    st.markdown("""
5. **"847 pokusu"** — CEO pred horou lahvicek: "Ochutnali jsme 847 verzi." Flashbacky, skleby, posledni pokus = usmev. 15s. *(Graza)*
6. **"CEO Taste Test" (serial)** — Kazdy tyden zalivka na neco absurdniho (zmrzlina, chipsy). Realne reakce. 15-30s. *(Mid-Day Squares)*
7. **"3 generace, 1 salat"** — Babicka, dcera, vnucka: "Tento recept jsme zdedily. Zalivku ne." 30s. *(Siete)*
8. **"Ve vyrobne v 5 rano"** — Hodiny 5:00, alarm, realne zabery vyroby. Ambient + text overlay. 30-60s. *(BTS documentary)*
9. **"Pod poklickou" (5 dilu)** — Kazdy dil = 1 ingredience. "Vedeli jste ze...?" 30s. *(The Ordinary)*
""")

    st.markdown("#### Higher effort")
    st.markdown("""
10. **"Zalivkovy horoskop"** — Carousel 12 slidu. "Strelec — Chilli mango. Protoze zivot bez rizika neni zivot."
11. **"Dvojite rande"** — Fermato x cesky pivovar. Spolecny recept. 30s. *(Liquid Death collab)*
12. **"Nekam to nechod" (anti-ad)** — "Toto NENI reklama." Bezny salat, ochutna, oci se rozsiri. Zadny branding do posledni sekundy. 15s.
""")


# ══════════════════════════════════════════════
# FOOTER: CAVEATS
# ══════════════════════════════════════════════

st.markdown("---")
with st.expander("Cim si nejsem jisty"):
    st.markdown("""
- **Contradiction hook = maly vzorek** (3 kreativy) — 40.6% hook je silny signal ale statisticky nespolehlivy. Potreba vic dat.
- **ROAS != kreativa** — ROAS ovlivnuje produkt, cena, sezona, product page. Nepricitat zmeny vyhradne archetype mixu.
- **CZ/HU trh** — vetsina benchmarku z US. Andromeda efekty mohou byt na malych trzich (~5M/4M Meta useru) odlisne.
- **Person_type tagging** — Whisper transkript pomaha rozlisit kdo mluvi (founder vs UGC creator), ale person_type (founder/customer/model) se stale odhaduje primarne z vizualu. Pokud osoba nemluvi, kontext chybi.
""")
