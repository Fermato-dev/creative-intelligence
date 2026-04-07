"""Fermato Creative Intelligence — Remix Studio"""

import json
import sqlite3
import streamlit as st

st.set_page_config(page_title="Remix Studio", page_icon="🎬", layout="wide")

import sys
from pathlib import Path

import pandas as pd

DASHBOARD_DIR = Path(__file__).parent.parent
REPO_ROOT = DASHBOARD_DIR.parent
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(DASHBOARD_DIR))
sys.path.insert(0, str(REPO_ROOT))
from shared_data import SHARED_CSS

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── CSS ──

st.markdown("""<style>
.drive-banner { background: linear-gradient(135deg, #1a1f36 0%, #2d1b69 50%, #1a3a4a 100%);
    border-radius: 12px; padding: 20px 24px; margin-bottom: 16px; color: #fff; }
.drive-banner h3 { color: #fff; margin: 0 0 6px; font-size: 1.1em; }
.drive-banner p { color: #94a3b8; font-size: 0.85em; margin: 0; }
.drive-btn { display: inline-block; background: #4285f4; color: #fff !important; font-weight: 700;
    font-size: 0.88em; padding: 8px 20px; border-radius: 8px; text-decoration: none;
    margin-top: 10px; transition: background 0.12s; }
.drive-btn:hover { background: #3367d6; color: #fff !important; }

.remix-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 14px 16px; margin: 6px 0; transition: all 0.12s ease; }
.remix-card:hover { border-color: #a5b4fc; box-shadow: 0 2px 8px rgba(99,102,241,0.1);
    transform: translateY(-1px); }
.remix-name { font-weight: 700; font-size: 1.0em; color: #1a202c; }
.remix-part { display: inline-block; font-size: 0.78em; font-weight: 600; padding: 3px 8px;
    border-radius: 5px; margin: 2px 2px; }
.remix-hook { background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }
.remix-body { background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
.remix-cta { background: #ccfbf1; color: #0d9488; border: 1px solid #5eead4; }
.remix-link { display: inline-flex; align-items: center; gap: 4px; font-size: 0.82em;
    font-weight: 600; color: #4285f4; text-decoration: none; padding: 4px 10px;
    background: #eef2ff; border-radius: 6px; margin-top: 6px; }
.remix-link:hover { background: #dbeafe; }

.matrix-cell { text-align: center; padding: 6px 8px; border-radius: 6px; font-size: 0.78em;
    font-weight: 600; }
.matrix-tested { background: #dcfce7; color: #16a34a; }
.matrix-pending { background: #fef3c7; color: #d97706; }
.matrix-untested { background: #f3f4f6; color: #9ca3af; }

.rec-card { border-radius: 10px; padding: 14px 16px; margin: 6px 0; }
.rec-swap-hook { background: #fef3c7; border: 1px solid #fcd34d; }
.rec-swap-body { background: #dbeafe; border: 1px solid #93c5fd; }
.rec-new-combo { background: #f0fdf4; border: 1px solid #86efac; }
.rec-refresh { background: #fef2f2; border: 1px solid #fca5a5; }
.rec-type { font-size: 0.72em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; margin-bottom: 4px; }
.rec-desc { font-size: 0.88em; color: #374151; margin-bottom: 6px; }
.rec-detail { font-size: 0.78em; color: #6b7280; }

.stat-card { background: #f8f9fb; border: 1px solid #e8ecf1; border-radius: 10px;
    padding: 12px; text-align: center; }
.stat-value { font-size: 1.6em; font-weight: 700; color: #1a202c; }
.stat-label { font-size: 0.72em; color: #6b7280; text-transform: uppercase;
    letter-spacing: 0.04em; }
</style>""", unsafe_allow_html=True)

# ── Constants ──

DRIVE_FOLDER_ID = "1SkeWFTQ5cH8esaxqbFzWaSo5NCKyPlNz"
DRIVE_FOLDER_URL = f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}"
DRIVE_FILE_URL = "https://drive.google.com/file/d/{file_id}/view"

# ── Sidebar ──

with st.sidebar:
    st.markdown("### Remix Studio")
    st.caption("Kombinace hooku + body + CTA z nasich nejlepsich reklam")

# ── Load data ──

ANALYSIS_DB = DATA_DIR / "creative_analysis.db"
REMIXES_JSON = DATA_DIR / "drive_remixes.json"


@st.cache_data(ttl=1800)
def load_remixes():
    if REMIXES_JSON.exists():
        return json.loads(REMIXES_JSON.read_text(encoding="utf-8"))
    return {"remixes": [], "folder_url": DRIVE_FOLDER_URL}


@st.cache_data(ttl=1800)
def load_components():
    if not ANALYSIS_DB.exists():
        return None
    conn = sqlite3.connect(f"file:{ANALYSIS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    data = {}

    # Components by type
    for ctype in ("hook", "body", "cta"):
        data[ctype] = [dict(r) for r in conn.execute("""
            SELECT ad_id, ad_name, component_type, hook_rate, hold_rate, completion_rate,
                   roas, cpa, cvr, spend, analysis, analyzed_at
            FROM components WHERE component_type = ?
            ORDER BY CASE ? WHEN 'hook' THEN hook_rate
                           WHEN 'body' THEN hold_rate
                           WHEN 'cta' THEN cvr END DESC
        """, (ctype, ctype)).fetchall()]

    # Recommendations
    data["recommendations"] = [dict(r) for r in conn.execute("""
        SELECT id, rec_type, description, details, created_at, status
        FROM recommendations ORDER BY id DESC
    """).fetchall()]

    # Tested combos
    data["tested"] = conn.execute(
        "SELECT COUNT(*) FROM tested_combinations").fetchone()[0]

    conn.close()
    return data


remixes_data = load_remixes()
comp_data = load_components()

# ══════════════════════════════════════════════════════
# HEADER + DRIVE LINK
# ══════════════════════════════════════════════════════

st.markdown("## Remix Studio")

st.markdown(f"""<div class="drive-banner">
<h3>Video Remixes na Google Drive</h3>
<p>{len(remixes_data.get('remixes', []))} remixu hotovych · kombinace nejlepsich hooku, body a CTA z nasich reklam</p>
<a class="drive-btn" href="{DRIVE_FOLDER_URL}" target="_blank">
Otevrit slozku na Google Drive</a>
</div>""", unsafe_allow_html=True)

# ── KPIs ──

hooks = comp_data["hook"] if comp_data else []
bodies = comp_data["body"] if comp_data else []
ctas = comp_data["cta"] if comp_data else []
recs = comp_data["recommendations"] if comp_data else []
remixes = remixes_data.get("remixes", [])

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Remixy (Drive)", len(remixes))
k2.metric("Hooky v knihovne", len(hooks))
k3.metric("Body v knihovne", len(bodies))
k4.metric("CTA v knihovne", len(ctas))
k5.metric("Doporuceni", len(recs))

st.divider()

# ══════════════════════════════════════════════════════
# EXISTING REMIXES FROM GOOGLE DRIVE
# ══════════════════════════════════════════════════════

st.markdown("### Hotove remixy")
st.caption("Videa na Google Drive — klikni pro prehrani nebo stazeni")

with st.sidebar:
    st.markdown("---")
    st.markdown("#### Filtry")
    hook_ads = sorted(set(r["hook"]["ad"] for r in remixes))
    selected_hooks = st.multiselect("Hook z reklamy", hook_ads, default=[])

filtered_remixes = remixes
if selected_hooks:
    filtered_remixes = [r for r in remixes if r["hook"]["ad"] in selected_hooks]

if filtered_remixes:
    for rmx in filtered_remixes:
        file_url = DRIVE_FILE_URL.format(file_id=rmx["file_id"])
        duration = rmx.get("duration", "")
        dur_str = f' · {duration}' if duration else ""

        st.markdown(f"""<div class="remix-card">
<span class="remix-name">{rmx['name']}</span>{dur_str}
<div style="margin-top:6px">
<span class="remix-part remix-hook">Hook: {rmx['hook']['ad']} ({rmx['hook']['metric']})</span>
<span class="remix-part remix-body">Body: {rmx['body']['ad']} ({rmx['body']['metric']})</span>
<span class="remix-part remix-cta">CTA: {rmx['cta']['ad']} ({rmx['cta']['metric']})</span>
</div>
<a class="remix-link" href="{file_url}" target="_blank">&#x25b6; Prehrat na Google Drive</a>
</div>""", unsafe_allow_html=True)
else:
    st.info("Zadne remixy pro zvolene filtry.")

st.divider()

# ══════════════════════════════════════════════════════
# COMPONENT MATRIX
# ══════════════════════════════════════════════════════

st.markdown("### Kombinacni matice")
st.caption("Hooky x Body — ktere kombinace jsou hotove, ktere cekaji")

if hooks and bodies:
    # Build matrix: which hook+body combos exist in remixes
    remix_combos = set()
    for rmx in remixes:
        remix_combos.add((rmx["hook"]["ad"], rmx["body"]["ad"]))

    hook_names = sorted(set(h["ad_name"].split(" - ")[0].split(" Copy")[0].strip() for h in hooks))
    body_names = sorted(set(b["ad_name"].split(" - ")[0].split(" Copy")[0].strip() for b in bodies))

    # Short names for display
    def short_name(name):
        parts = name.split()
        if len(name) > 15:
            return parts[0][:8] + ("" if len(parts) < 2 else " " + parts[1][:4])
        return name

    # Matrix as dataframe
    matrix_data = {}
    for body in body_names:
        row = {}
        for hook in hook_names:
            # Check if any remix uses this combo (fuzzy match)
            found = False
            for combo in remix_combos:
                if (combo[0].lower() in hook.lower() or hook.lower() in combo[0].lower()) and \
                   (combo[1].lower() in body.lower() or body.lower() in combo[1].lower()):
                    found = True
                    break
            row[short_name(hook)] = "Hotovo" if found else "—"
        matrix_data[short_name(body)] = row

    df_matrix = pd.DataFrame(matrix_data).T
    df_matrix.index.name = "Body \\ Hook"

    st.dataframe(df_matrix, use_container_width=True,
                 column_config={col: st.column_config.TextColumn(width="small")
                                for col in df_matrix.columns})

    total_possible = len(hook_names) * len(body_names)
    done = sum(1 for body in matrix_data.values() for v in body.values() if v == "Hotovo")
    st.caption(f"{done}/{total_possible} kombinaci hotovo · "
               f"{total_possible - done} volnych slotu pro dalsi remixy")

st.divider()

# ══════════════════════════════════════════════════════
# COMPONENT LIBRARY SUMMARY
# ══════════════════════════════════════════════════════

st.markdown("### Knihovna komponent")

tab_h, tab_b, tab_c = st.tabs(["Hooky", "Body", "CTA"])

with tab_h:
    if hooks:
        rows = []
        for h in hooks:
            analysis = json.loads(h["analysis"] or "{}")
            rows.append({
                "Reklama": h["ad_name"],
                "Hook Rate": f"{h['hook_rate']:.1f}%",
                "ROAS": f"{h['roas']:.2f}",
                "CPA": f"{h['cpa']:.0f} CZK",
                "Spend": f"{h['spend']:,.0f} CZK",
                "Hook typ": analysis.get("hook_type", "?"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Zadne hooky v knihovne.")

with tab_b:
    if bodies:
        rows = []
        for b in bodies:
            analysis = json.loads(b["analysis"] or "{}")
            rows.append({
                "Reklama": b["ad_name"],
                "Hold Rate": f"{b['hold_rate']:.1f}%",
                "ROAS": f"{b['roas']:.2f}",
                "Spend": f"{b['spend']:,.0f} CZK",
                "Narrative": analysis.get("narrative_structure", "?"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tab_c:
    if ctas:
        rows = []
        for c in ctas:
            analysis = json.loads(c["analysis"] or "{}")
            rows.append({
                "Reklama": c["ad_name"],
                "CVR": f"{c['cvr']:.2f}%",
                "ROAS": f"{c['roas']:.2f}",
                "Spend": f"{c['spend']:,.0f} CZK",
                "CTA typ": analysis.get("cta_type", "?"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════
# RECOMMENDATIONS
# ══════════════════════════════════════════════════════

st.markdown("### Doporuceni pro nove remixy")
st.caption("AI-generovane navrhy kombinaci na zaklade Thompson Sampling")

# Generate button
if comp_data and ANALYSIS_DB.exists():
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        generate = st.button("Generovat nova doporuceni", type="primary")
    with col_info:
        st.caption("Spusti Thompson Sampling pres existujici data v knihovne. "
                    "Netreba API klice — pocita z jiz analyzovanych komponent.")

    if generate:
        try:
            from creative_intelligence.component_db import get_db
            from creative_intelligence.combinator import generate_all_recommendations, \
                format_recommendations_report
            conn = get_db(readonly=False)
            new_recs = generate_all_recommendations(conn)
            report = format_recommendations_report(new_recs)

            # Save report
            from datetime import date
            report_path = DATA_DIR / f"recommendations-{date.today()}.txt"
            report_path.write_text(report, encoding="utf-8")
            conn.close()

            st.success(f"Vygenerovano {len(new_recs)} novych doporuceni!")
            st.rerun()
        except Exception as e:
            st.error(f"Chyba pri generovani: {e}")

# Show existing recommendations grouped by type
if recs:
    rec_types = {
        "NEW_COMBINATION": ("Nove kombinace", "rec-new-combo"),
        "SWAP_HOOK": ("Vymena hooku", "rec-swap-hook"),
        "SWAP_BODY": ("Vymena body", "rec-swap-body"),
        "REFRESH_ALERT": ("Refresh alert", "rec-refresh"),
    }

    # Group by type
    grouped = {}
    for r in recs:
        rt = r["rec_type"]
        if rt not in grouped:
            grouped[rt] = []
        grouped[rt].append(r)

    for rec_type, (label, css_cls) in rec_types.items():
        items = grouped.get(rec_type, [])
        if not items:
            continue

        with st.expander(f"{label} ({len(items)})", expanded=(rec_type == "NEW_COMBINATION")):
            for r in items:
                details = json.loads(r["details"] or "{}")
                desc = r["description"]
                status = r["status"]

                detail_parts = []
                if rec_type == "NEW_COMBINATION":
                    h = details.get("hook", {})
                    b = details.get("body", {})
                    c = details.get("cta", {})
                    score = details.get("combined_score", 0)
                    detail_parts.append(
                        f'<span class="remix-part remix-hook">Hook: {h.get("from_ad","?")} '
                        f'({h.get("hook_rate",0):.0f}%)</span>'
                        f'<span class="remix-part remix-body">Body: {b.get("from_ad","?")} '
                        f'(hold {b.get("hold_rate",0):.0f}%)</span>'
                        f'<span class="remix-part remix-cta">CTA: {c.get("from_ad","?")} '
                        f'(CVR {c.get("cvr",0):.1f}%)</span>'
                        f'<span style="font-size:0.75em;color:#6b7280;margin-left:6px">'
                        f'score: {score:.3f}</span>'
                    )
                elif rec_type in ("SWAP_HOOK", "SWAP_BODY"):
                    target = details.get("target_ad", "?")
                    suggested = details.get("suggested_from_ad", "?")
                    improvement = details.get("expected_improvement", "")
                    detail_parts.append(
                        f'<span style="font-size:0.82em">'
                        f'{target} &larr; pouzij z {suggested}'
                        f'{f" ({improvement})" if improvement else ""}</span>'
                    )

                detail_html = " ".join(detail_parts)
                st.markdown(f"""<div class="rec-card {css_cls}">
<div class="rec-type">{label} · {status}</div>
<div class="rec-desc">{desc}</div>
{f'<div>{detail_html}</div>' if detail_html else ''}
</div>""", unsafe_allow_html=True)
else:
    st.info("Zadna doporuceni. Klikni 'Generovat' nebo spust weekly pipeline.")

st.divider()

# ══════════════════════════════════════════════════════
# WORKFLOW GUIDE
# ══════════════════════════════════════════════════════

st.markdown("### Jak vytvorit remix")
st.markdown("""
| Krok | Co | Kdo |
|------|-----|-----|
| 1. | AI analyzuje komponenty (hook/body/CTA) z aktivnich reklam | Automaticky (weekly pipeline) |
| 2. | Thompson Sampling doporuci nejlepsi kombinace | Automaticky (tlacitko vyse) |
| 3. | Strihac sestavi video podle doporuceni | Tim (manualne) |
| 4. | Upload remixu na Google Drive | Tim |
| 5. | Nasazeni jako nova reklama v Meta Ads | Performance tym |
| 6. | AI vyhodnoti vykon remixu v dalsim cyklu | Automaticky |
""")

st.markdown(f"""
**Uzitecne odkazy:**
- [Google Drive — video remixes]({DRIVE_FOLDER_URL})
- Doporuceni se generuji z dat v `creative_analysis.db` (8 reklam, 24 komponent)
- Weekly pipeline bezi kazdou nedeli a aktualizuje knihovnu
""")
