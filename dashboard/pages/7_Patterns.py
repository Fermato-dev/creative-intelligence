"""Fermato Creative Intelligence — Patterns & Root Cause"""

import json
import sqlite3
import streamlit as st

st.set_page_config(page_title="Patterns", page_icon="🔬", layout="wide")

import sys
from pathlib import Path

import pandas as pd

DASHBOARD_DIR = Path(__file__).parent.parent
REPO_ROOT = DASHBOARD_DIR.parent
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(DASHBOARD_DIR))
from shared_data import SHARED_CSS

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── Custom CSS ──

st.markdown("""<style>
.rc-card { border-radius: 10px; padding: 16px; margin: 6px 0; }
.rc-good { background: #f0fdf4; border: 1px solid #86efac; }
.rc-bad { background: #fef2f2; border: 1px solid #fca5a5; }
.rc-neutral { background: #f8f9fb; border: 1px solid #e5e7eb; }
.rc-title { font-weight: 700; font-size: 0.85em; margin-bottom: 8px; text-transform: uppercase;
    letter-spacing: 0.06em; }
.rc-good .rc-title { color: #16a34a; }
.rc-bad .rc-title { color: #dc2626; }
.rc-neutral .rc-title { color: #6b7280; }
.rc-item { font-size: 0.84em; padding: 3px 0; display: flex; justify-content: space-between; color: #374151; }
.rc-item .val { color: #6b7280; font-weight: 500; }

.pattern-status { font-size: 0.68em; font-weight: 700; padding: 2px 7px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: 0.04em; }
.ps-draft { background: #f3f4f6; color: #6b7280; }
.ps-validated { background: #dcfce7; color: #16a34a; }
.ps-testing { background: #fef3c7; color: #d97706; }
.ps-proven { background: #ccfbf1; color: #0d9488; }

.insight-banner { background: linear-gradient(135deg, #eef9f7 0%, #f0fdf4 100%);
    border: 1px solid #99f6e4; border-radius: 10px; padding: 16px 20px; margin-bottom: 12px; }
.insight-banner strong { color: #0f766e; }
</style>""", unsafe_allow_html=True)

# ── Sidebar ──

with st.sidebar:
    st.markdown("### Patterns")
    st.caption("Root Cause + Pattern Library")

# ── Database ──

DB_PATHS = [
    DATA_DIR / "competitor_intel.db",
    REPO_ROOT.parent / "projects" / "cmo" / "creative-intelligence" / "data" / "competitor_intel.db",
    Path("C:/Users/rstra/Chief_of_Staff/Chief-of-Staff/projects/cmo/creative-intelligence/data/competitor_intel.db"),
    Path("C:/Users/ferma/Chief_of_Staff/Chief-of-Staff/projects/cmo/creative-intelligence/data/competitor_intel.db"),
]

db_path = None
for p in DB_PATHS:
    if p.exists():
        db_path = p
        break


@st.cache_data(ttl=1800)
def load_pattern_data(_db_path):
    if not _db_path:
        return None
    conn = sqlite3.connect(f"file:{_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    data = {}

    # Hook patterns (combined organic + paid)
    hook_organic = {}
    for r in conn.execute("""
        SELECT hook_type, COUNT(*) as cnt, AVG(transferability_score) as avg_t,
               AVG(brand_fit_score) as avg_f
        FROM post_analysis WHERE hook_type IS NOT NULL GROUP BY hook_type
    """).fetchall():
        hook_organic[r["hook_type"]] = dict(r)

    hook_paid = {}
    for r in conn.execute("""
        SELECT hook_type, COUNT(*) as cnt, AVG(transferability_score) as avg_t,
               AVG(brand_fit_score) as avg_f
        FROM competitor_ads WHERE hook_type IS NOT NULL GROUP BY hook_type
    """).fetchall():
        hook_paid[r["hook_type"]] = dict(r)

    all_hooks = set(list(hook_organic.keys()) + list(hook_paid.keys()))
    combined = []
    for h in all_hooks:
        org = hook_organic.get(h, {"cnt": 0, "avg_t": 0, "avg_f": 0})
        paid = hook_paid.get(h, {"cnt": 0, "avg_t": 0, "avg_f": 0})
        total = (org["cnt"] or 0) + (paid["cnt"] or 0)
        combined.append({
            "hook": h, "total": total,
            "organic": org["cnt"] or 0, "paid": paid["cnt"] or 0,
            "avg_t": round(((org["avg_t"] or 0) * (org["cnt"] or 0) +
                           (paid["avg_t"] or 0) * (paid["cnt"] or 0)) / max(total, 1), 1),
            "avg_f": round(((org["avg_f"] or 0) * (org["cnt"] or 0) +
                           (paid["avg_f"] or 0) * (paid["cnt"] or 0)) / max(total, 1), 1),
        })
    combined.sort(key=lambda x: x["total"], reverse=True)
    data["hook_patterns"] = combined

    # Pattern Library
    data["patterns"] = [dict(r) for r in conn.execute("""
        SELECT name, pattern_type, example_count, avg_transferability, avg_brand_fit, status
        FROM patterns ORDER BY example_count DESC
    """).fetchall()]

    conn.close()
    return data


# ── Root Cause (hardcoded from sprint) ──

st.markdown("## Patterns & Root Cause")
st.caption("Co odlisuje uspesne hooky od neuspesnych — analyza 187 video reklam")

st.markdown("""<div class="insight-banner">
<strong>Bottleneck = kreativni koncept, ne exekuce.</strong>
curiosity_gap + ugc_reaction hooky = 45-58% hook rate. Genericke hooky = ~0%.
Medium energy (pohyb v prvnich 2s) = 9/10 top performeru.
Lo-fi i polished funguje — rozhoduje KONCEPT, ne produkce.
</div>""", unsafe_allow_html=True)

# Root cause columns
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("""<div class="rc-card rc-good">
<div class="rc-title">Funguje</div>
<div class="rc-item"><span>curiosity_gap</span><span class="val">4x v top 10</span></div>
<div class="rc-item"><span>ugc_reaction</span><span class="val">3x v top 10</span></div>
<div class="rc-item"><span>medium energy</span><span class="val">9/10 top</span></div>
<div class="rc-item"><span>food viditelny</span><span class="val">9/10 top</span></div>
</div>""", unsafe_allow_html=True)

with c2:
    st.markdown("""<div class="rc-card rc-bad">
<div class="rc-title">Nefunguje</div>
<div class="rc-item"><span>generic hook</span><span class="val">3/6 bottom</span></div>
<div class="rc-item"><span>low energy</span><span class="val">6/6 bottom</span></div>
<div class="rc-item"><span>bez pohybu</span><span class="val">staticke</span></div>
<div class="rc-item"><span>product shot only</span><span class="val">~0% hook</span></div>
</div>""", unsafe_allow_html=True)

with c3:
    st.markdown("""<div class="rc-card rc-neutral">
<div class="rc-title">Neni faktor</div>
<div class="rc-item"><span>lo-fi vs polished</span><span class="val">oba fungujou</span></div>
<div class="rc-item"><span>text overlay</span><span class="val">vsichni ho maji</span></div>
<div class="rc-item"><span>osoba v zaberu</span><span class="val">mixovane</span></div>
</div>""", unsafe_allow_html=True)

st.divider()

# ── Hook Patterns ──

data = load_pattern_data(db_path) if db_path else None

st.markdown("### Hook patterny (organic + paid)")

if data and data["hook_patterns"]:
    hp = data["hook_patterns"]
    df = pd.DataFrame(hp)
    df = df.rename(columns={
        "hook": "Hook typ", "total": "Celkem", "organic": "Organic",
        "paid": "Paid", "avg_t": "Avg Transfer", "avg_f": "Avg Fit"
    })

    # Bar chart
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Organic", y=[h["hook"] for h in hp],
                         x=[h["organic"] for h in hp],
                         orientation="h", marker_color="#14b8a6"))
    fig.add_trace(go.Bar(name="Paid", y=[h["hook"] for h in hp],
                         x=[h["paid"] for h in hp],
                         orientation="h", marker_color="#3b82f6"))
    fig.update_layout(barmode="stack", height=300, margin=dict(l=0, r=0, t=10, b=0),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      xaxis=dict(title="Pocet", gridcolor="#e5e7eb"),
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    # Table
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Avg Transfer": st.column_config.NumberColumn(format="%.1f"),
                     "Avg Fit": st.column_config.NumberColumn(format="%.1f"),
                 })
else:
    if not db_path:
        st.warning("competitor_intel.db nenalezena.")
    else:
        st.info("Zadne hook patterny. Spust `competitor_analyzer.py`.")

st.divider()

# ── Pattern Library ──

st.markdown("### Pattern Library")

if data and data["patterns"]:
    for p in data["patterns"]:
        status = p["status"] or "draft"
        status_cls = {"draft": "ps-draft", "validated": "ps-validated",
                     "testing": "ps-testing", "proven": "ps-proven"}.get(status, "ps-draft")

        avg_t = p["avg_transferability"] or 0
        avg_f = p["avg_brand_fit"] or 0

        st.markdown(f"""
**{p['name']}** <span class="pattern-status {status_cls}">{status}</span>
· {p['example_count']} prikladu
· Transfer: {avg_t:.1f}
· Fit: {avg_f:.1f}
""", unsafe_allow_html=True)
else:
    st.info("Pattern Library je prazdna. Spust `pattern_library.py detect`.")

# ── Brief Pravidla ──

st.divider()
st.markdown("### Pravidla pro brief")
st.markdown("""
| Pravidlo | Detail |
|----------|--------|
| **Hook typ** | curiosity_gap nebo ugc_reaction — NIKDY generic |
| **Energie** | Medium — pohyb v prvnich 2 sekundach |
| **Prvni frame** | Jidlo viditelne, ruka/akce/naliti, NE staticke logo |
| **Styl** | Lo-fi i polished OK — rozhoduje koncept |
| **Text overlay** | Ano, ale nestaci sam o sobe |
""")
