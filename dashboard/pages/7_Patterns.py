"""Fermato Creative Intelligence — Patterns & Root Cause"""

import json
import sqlite3
import streamlit as st

st.set_page_config(page_title="Patterns", page_icon="🔬", layout="wide")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import check_password
if not check_password():
    st.stop()

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

.glossary-term { display: inline-block; background: #f0f9ff; border: 1px solid #bae6fd;
    border-radius: 6px; padding: 6px 10px; margin: 3px; font-size: 0.82em; }
.glossary-term strong { color: #0369a1; }
.glossary-term span { color: #475569; }

.pattern-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 16px 18px; margin: 8px 0; transition: box-shadow 0.12s ease; }
.pattern-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-color: #cbd5e1; }
.pattern-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.pattern-name  { font-weight: 700; font-size: 1.05em; color: #1a202c !important; }
.pattern-count { font-size: 0.75em; color: #6b7280 !important; background: #e2e8f0;
    padding: 2px 8px; border-radius: 10px; }
.pattern-desc { font-size: 0.84em; color: #374151 !important; line-height: 1.5; margin-bottom: 8px; }
.pattern-why  { font-size: 0.82em; color: #6b7280 !important; font-style: italic; margin-bottom: 8px; }

.example-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 10px 12px; margin: 4px 0; }
.example-brand { font-weight: 600; color: #0f766e; font-size: 0.88em; }
.example-insight { font-size: 0.82em; color: #475569; margin-top: 4px; line-height: 1.4; }
.example-link { display: inline-block; margin-top: 4px; font-size: 0.78em; font-weight: 600;
    color: #0d9488; text-decoration: none; padding: 2px 8px; background: #ccfbf1;
    border-radius: 4px; }
.example-link:hover { background: #99f6e4; color: #0f766e; }

.score-bar { height: 6px; border-radius: 3px; background: #e5e7eb; margin-top: 4px; }
.score-fill { height: 100%; border-radius: 3px; }
.score-fill-t { background: linear-gradient(90deg, #14b8a6, #0d9488); }
.score-fill-f { background: linear-gradient(90deg, #3b82f6, #1d4ed8); }
</style>""", unsafe_allow_html=True)

# ── Sidebar ──

with st.sidebar:
    st.markdown("### Patterns")
    st.caption("Root Cause + Pattern Library + Glossary")

# ── Database ──

DB_PATHS = [
    DATA_DIR / "competitor_intel.db",
    REPO_ROOT.parent / "projects" / "cmo" / "creative-intelligence" / "data" / "competitor_intel.db",
    Path.home() / "Chief-of-Staff" / "projects" / "cmo" / "creative-intelligence" / "data" / "competitor_intel.db",
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

    # Hook patterns (combined organic + paid) with examples
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

    # Hook pattern examples (organic with URLs)
    hook_examples = {}
    for r in conn.execute("""
        SELECT pa.hook_type, b.name as brand, op.post_url, pa.analysis_json,
               pa.transferability_score as t, pa.brand_fit_score as f,
               pa.energy_level, pa.visual_style, pa.format_type,
               pa.food_visible, pa.person_present
        FROM post_analysis pa
        JOIN organic_posts op ON pa.post_id = op.id
        JOIN brands b ON op.brand_id = b.id
        WHERE pa.hook_type IS NOT NULL
        ORDER BY (pa.transferability_score + pa.brand_fit_score) DESC
    """).fetchall():
        ht = r["hook_type"]
        if ht not in hook_examples:
            hook_examples[ht] = []
        analysis = json.loads(r["analysis_json"] or "{}")
        hook_examples[ht].append({
            "brand": r["brand"], "url": r["post_url"],
            "insight": analysis.get("key_insight", ""),
            "t": r["t"], "f": r["f"],
            "energy": r["energy_level"], "style": r["visual_style"],
            "format": r["format_type"],
            "food": r["food_visible"], "person": r["person_present"],
        })
    data["hook_examples"] = hook_examples

    # Pattern Library (full with examples)
    patterns = []
    for r in conn.execute("""
        SELECT name, pattern_type, slug, description, why_works, examples_json,
               example_count, avg_transferability, avg_brand_fit, status,
               performance_notes, cz_adaptation_notes
        FROM patterns ORDER BY example_count DESC
    """).fetchall():
        p = dict(r)
        p["examples"] = json.loads(p["examples_json"] or "[]")
        patterns.append(p)
    data["patterns"] = patterns

    # Stats for overview
    data["total_analyzed_organic"] = conn.execute(
        "SELECT COUNT(*) as c FROM post_analysis").fetchone()["c"]
    data["total_analyzed_paid"] = conn.execute(
        "SELECT COUNT(*) as c FROM competitor_ads WHERE analyzed_at IS NOT NULL").fetchone()["c"]
    data["total_patterns"] = conn.execute(
        "SELECT COUNT(*) as c FROM patterns").fetchone()["c"]

    conn.close()
    return data


# ══════════════════════════════════════════════════════
# GLOSSARY / LEGENDA
# ══════════════════════════════════════════════════════

st.markdown("## Patterns & Root Cause")
st.caption("Co odlisuje uspesne hooky od neuspesnych — analyza 187 video reklam + competitor intelligence")

with st.expander("Legenda pojmu", expanded=False):
    st.markdown("#### Hook typy")
    st.markdown("""
<div class="glossary-term"><strong>curiosity_gap</strong> <span>— Hook, ktery vytvari napeti a nutka divaka sledovat dal. Napr. "Tohle jsem necekal..." nebo bait-and-switch, personality quizy. Nejuspesnejsi typ — 45-58% hook rate.</span></div>
<div class="glossary-term"><strong>ugc_reaction</strong> <span>— Autentická reakce creatora na produkt ("Tenhle smell!", "Wait what?"). Buduje duveru pres social proof. 2. nejuspesnejsi typ.</span></div>
<div class="glossary-term"><strong>product_reveal</strong> <span>— Vizualni odhaleni produktu — unboxing, naliti, aplikace. Funguje dobre kdyz je spojeny s akci (pohyb, ruka).</span></div>
<div class="glossary-term"><strong>food_closeup</strong> <span>— Detailni zaber na jidlo/napoj. Silny vizualni appeal, vysoke skore kdyz jidlo vypada "craveable".</span></div>
<div class="glossary-term"><strong>recipe_demo</strong> <span>— Ukazka receptu s produktem. Edukativni hodnota + aspiracni lifestyle.</span></div>
<div class="glossary-term"><strong>before_after</strong> <span>— Srovnani pred/po pouziti produktu. Funguje hlavne u "problem-solution" frameworku.</span></div>
<div class="glossary-term"><strong>generic</strong> <span>— Bez jasneho hooku — logo, staticke foto, popisne texty. NEFUNGUJE — ~0% hook rate.</span></div>
""", unsafe_allow_html=True)

    st.markdown("#### Energy level")
    st.markdown("""
<div class="glossary-term"><strong>medium</strong> <span>— Pohyb v prvnich 2 sekundach (naliti, sypani, ruka se natahuje). 9/10 top performeru ma medium energy. Toto je sweet spot.</span></div>
<div class="glossary-term"><strong>high</strong> <span>— Rychly strih, hodne akce, dynamicke prechody. Funguje, ale neni nutnost.</span></div>
<div class="glossary-term"><strong>low</strong> <span>— Staticke, bez pohybu. NEFUNGUJE — vsech 6 bottom performeru ma low energy. Urcite se vyhnout.</span></div>
""", unsafe_allow_html=True)

    st.markdown("#### Skore")
    st.markdown("""
<div class="glossary-term"><strong>Transferability (T)</strong> <span>— Jak snadno lze koncept prevzit a adaptovat pro Fermato. 1-10, kde 8+ = primo pouzitelne.</span></div>
<div class="glossary-term"><strong>Brand Fit (F)</strong> <span>— Jak dobre koncept sedi k Fermato brandu (ceske FMCG, jidlo, soseky/zalivky). 1-10, kde 6+ = dobra shoda.</span></div>
""", unsafe_allow_html=True)

    st.markdown("#### Format")
    st.markdown("""
<div class="glossary-term"><strong>short_video</strong> <span>— Kratke video (Reels/Stories/TikTok). Hlavni format pro ads.</span></div>
<div class="glossary-term"><strong>carousel</strong> <span>— Vice snimku/slidu. Dobry pro storytelling a engagement.</span></div>
<div class="glossary-term"><strong>static_image</strong> <span>— Jednoduchy obrazek. Funguje pro retargeting a znacku, slabsi na top-of-funnel.</span></div>
""", unsafe_allow_html=True)

    st.markdown("#### Visual style")
    st.markdown("""
<div class="glossary-term"><strong>polished</strong> <span>— Profesionalne natocene a editovane. Neni to faktor uspechu — lo-fi i polished funguje.</span></div>
<div class="glossary-term"><strong>bright_clean</strong> <span>— Svetle, ciste prostredi, vysoka saturace. Funguje pro food obsah.</span></div>
<div class="glossary-term"><strong>lo-fi / UGC</strong> <span>— Autenticky, telefon-style. Funguje stejne dobre jako polished — rozhoduje KONCEPT, ne produkce.</span></div>
""", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════
# ROOT CAUSE — INSIGHT BANNER
# ══════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════
# HOOK PATTERNS
# ══════════════════════════════════════════════════════

data = load_pattern_data(db_path) if db_path else None

st.markdown("### Hook patterny (organic + paid)")

if data and data["hook_patterns"]:
    hp = data["hook_patterns"]

    # Sidebar filters
    with st.sidebar:
        st.markdown("---")
        st.markdown("#### Filtry")
        min_count = st.slider("Min. pocet vyskytu", 0, max(h["total"] for h in hp), 0)
        source_filter = st.radio("Zdroj", ["Vsechny", "Organic", "Paid"], horizontal=True)

    # Apply filters
    filtered = [h for h in hp if h["total"] >= min_count]
    if source_filter == "Organic":
        filtered = [h for h in filtered if h["organic"] > 0]
    elif source_filter == "Paid":
        filtered = [h for h in filtered if h["paid"] > 0]

    df = pd.DataFrame(filtered)
    df = df.rename(columns={
        "hook": "Hook typ", "total": "Celkem", "organic": "Organic",
        "paid": "Paid", "avg_t": "Avg Transfer", "avg_f": "Avg Fit"
    })

    # Bar chart
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Organic", y=[h["hook"] for h in filtered],
                         x=[h["organic"] for h in filtered],
                         orientation="h", marker_color="#14b8a6"))
    fig.add_trace(go.Bar(name="Paid", y=[h["hook"] for h in filtered],
                         x=[h["paid"] for h in filtered],
                         orientation="h", marker_color="#3b82f6"))
    fig.update_layout(barmode="stack", height=max(200, len(filtered) * 45),
                      margin=dict(l=0, r=0, t=10, b=0),
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

    # ── Hook detail expanders with examples ──
    st.markdown("#### Detail podle hook typu")
    st.caption("Klikni pro priklady s odkazy na konkretni posty")

    for h in filtered:
        hook_name = h["hook"]
        examples = data["hook_examples"].get(hook_name, [])
        label = f"{hook_name}  —  {h['total']}x  |  T: {h['avg_t']}  F: {h['avg_f']}"

        with st.expander(label, expanded=False):
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Organic", h["organic"])
            mc2.metric("Paid", h["paid"])
            mc3.metric("Celkem", h["total"])

            if examples:
                st.markdown("**Priklady:**")
                for ex in examples:
                    t_val = ex.get("t") or 0
                    f_val = ex.get("f") or 0
                    t_pct = int(t_val * 10)
                    f_pct = int(f_val * 10)
                    tags = []
                    if ex.get("energy"):
                        tags.append(f"energy: {ex['energy']}")
                    if ex.get("format"):
                        tags.append(ex["format"])
                    if ex.get("food"):
                        tags.append("food visible")
                    if ex.get("person"):
                        tags.append("osoba v zaberu")
                    tag_str = " · ".join(tags)

                    st.markdown(f"""<div class="example-card">
<span class="example-brand">{ex['brand']}</span>
<span style="font-size:0.75em;color:#9ca3af;margin-left:6px">{tag_str}</span>
<div style="display:flex;gap:16px;margin-top:4px">
<div style="flex:1"><span style="font-size:0.72em;color:#0d9488">Transfer {t_val:.0f}/10</span>
<div class="score-bar"><div class="score-fill score-fill-t" style="width:{t_pct}%"></div></div></div>
<div style="flex:1"><span style="font-size:0.72em;color:#3b82f6">Brand Fit {f_val:.0f}/10</span>
<div class="score-bar"><div class="score-fill score-fill-f" style="width:{f_pct}%"></div></div></div>
</div>
<div class="example-insight">{(ex.get('insight') or '')[:200]}</div>
<a class="example-link" href="{ex['url']}" target="_blank">Zobrazit post</a>
</div>""", unsafe_allow_html=True)
            else:
                st.caption("Zadne analyzovane organic priklady pro tento hook typ.")

else:
    if not db_path:
        st.warning("competitor_intel.db nenalezena.")
    else:
        st.info("Zadne hook patterny. Spust `competitor_analyzer.py`.")

st.divider()

# ══════════════════════════════════════════════════════
# PATTERN LIBRARY (interactive)
# ══════════════════════════════════════════════════════

st.markdown("### Pattern Library")

if data and data["patterns"]:
    # Stats
    st.caption(f"{len(data['patterns'])} patternu · "
               f"{sum(p['example_count'] for p in data['patterns'])} prikladu celkem")

    # Filter by status
    with st.sidebar:
        st.markdown("#### Pattern status")
        statuses = sorted(set(p["status"] or "draft" for p in data["patterns"]))
        selected_statuses = st.multiselect("Status", statuses, default=statuses)

    filtered_patterns = [p for p in data["patterns"]
                         if (p["status"] or "draft") in selected_statuses]

    for p in filtered_patterns:
        status = p["status"] or "draft"
        status_cls = {"draft": "ps-draft", "validated": "ps-validated",
                     "testing": "ps-testing", "proven": "ps-proven"}.get(status, "ps-draft")

        avg_t = p["avg_transferability"] or 0
        avg_f = p["avg_brand_fit"] or 0
        examples = p.get("examples", [])

        with st.expander(
            f"{p['name']}  —  {p['example_count']} prikladu  |  "
            f"T: {avg_t:.1f}  F: {avg_f:.1f}  |  {status}",
            expanded=False,
        ):
            # Header metrics
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("Priklady", p["example_count"])
            hc2.metric("Avg Transferability", f"{avg_t:.1f}")
            hc3.metric("Avg Brand Fit", f"{avg_f:.1f}")
            hc4.markdown(f'<span class="pattern-status {status_cls}" '
                         f'style="font-size:0.9em;padding:6px 12px">{status}</span>',
                         unsafe_allow_html=True)

            # Description
            if p.get("description"):
                st.markdown(f"**Popis:** {p['description']}")

            # Why it works
            if p.get("why_works"):
                why_lines = [l.strip() for l in (p["why_works"] or "").split(";") if l.strip()]
                if why_lines:
                    st.markdown("**Proc to funguje:**")
                    for line in why_lines:
                        st.markdown(f"- {line}")

            # CZ adaptation
            if p.get("cz_adaptation_notes"):
                st.info(f"Adaptace pro CZ: {p['cz_adaptation_notes']}")

            # Examples with links
            if examples:
                st.markdown(f"**Priklady ({len(examples)}):**")
                for ex in examples:
                    brand = ex.get("brand", "?")
                    url = ex.get("url", "")
                    insight = ex.get("insight", "")
                    link_html = (f' <a class="example-link" href="{url}" '
                                 f'target="_blank">Zobrazit</a>') if url else ""

                    st.markdown(f"""<div class="example-card">
<span class="example-brand">{brand}</span>{link_html}
<div class="example-insight">{insight[:250]}</div>
</div>""", unsafe_allow_html=True)
            else:
                st.caption("Zadne priklady.")

else:
    st.info("Pattern Library je prazdna. Spust `pattern_library.py detect`.")

# ── Brief Pravidla ──

st.divider()
st.markdown("### Pravidla pro brief")
st.markdown("""
| Pravidlo | Detail | Proc |
|----------|--------|------|
| **Hook typ** | curiosity_gap nebo ugc_reaction — NIKDY generic | 4x a 3x v top 10 performeru |
| **Energie** | Medium — pohyb v prvnich 2 sekundach | 9/10 top performeru, 0/6 bottom |
| **Prvni frame** | Jidlo viditelne, ruka/akce/naliti, NE staticke logo | 9/10 top ma food visible |
| **Styl** | Lo-fi i polished OK — rozhoduje koncept | Analyza 187 videi to potvrdila |
| **Text overlay** | Ano, ale nestaci sam o sobe | Vsichni ho maji — neni diferenciator |
""")
