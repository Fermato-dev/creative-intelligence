"""Fermato Creative Intelligence v2 — Customer Voice & Creative Briefs"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

st.set_page_config(page_title="Creative Briefs", page_icon="💡", layout="wide")

from auth import check_password

if not check_password():
    st.stop()

import json
import sqlite3
from datetime import datetime

from shared_data import SHARED_CSS, DATA_DIR

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# Lightweight sidebar — tato stranka nepotrebuje Meta API
with st.sidebar:
    st.markdown("### Creative Briefs")
    st.caption("Customer Voice + 4 paralelni briefy")

# ── Paths ──

VOICE_DB = DATA_DIR / "customer_voice.db"
OUTPUT_DIR = DATA_DIR / "briefs"  # data/briefs/ in fermato-dev repo

# ── Custom CSS ──

st.markdown("""<style>
.brief-card {
    background: #f8f9fb; border: 1px solid #e8ecf1;
    border-radius: 12px; padding: 20px; margin: 10px 0;
    box-shadow: 0 2px 6px rgba(0,0,0,0.04);
    transition: transform 0.15s ease;
}
.brief-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.brief-header {
    font-size: 1.15em; font-weight: 700; color: #1a202c;
    margin-bottom: 8px; display: flex; align-items: center; gap: 8px;
}
.brief-tag {
    display: inline-block; font-size: 0.72em; font-weight: 600;
    padding: 2px 8px; border-radius: 4px; text-transform: uppercase;
    letter-spacing: 0.03em;
}
.tag-visual { background: #eef2ff; color: #4338ca; }
.tag-emotion { background: #fef3c7; color: #92400e; }
.tag-segment { background: #ecfdf5; color: #065f46; }
.tag-format { background: #fce7f3; color: #9d174d; }
.brief-oneliner { font-size: 0.95em; color: #4a5568; margin: 8px 0; font-style: italic; }
.brief-section { margin-top: 12px; }
.brief-section-title { font-size: 0.78em; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
.brief-copy {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 12px; font-size: 0.88em; line-height: 1.5;
}
.brief-copy strong { color: #1a202c; }
.color-swatch {
    display: inline-block; width: 24px; height: 24px; border-radius: 6px;
    margin-right: 4px; vertical-align: middle; border: 1px solid #e2e8f0;
}
.voice-phrase {
    display: inline-block; background: #eef2ff; color: #3730a3;
    padding: 3px 10px; border-radius: 16px; font-size: 0.82em;
    margin: 3px 2px; font-weight: 500;
}
.voice-trigger {
    display: inline-block; padding: 3px 10px; border-radius: 16px;
    font-size: 0.82em; margin: 3px 2px; font-weight: 500;
}
.trigger-fear { background: #fff5f5; color: #c53030; }
.trigger-aspiration { background: #f0fff4; color: #276749; }
.trigger-frustration { background: #fffff0; color: #975a16; }
.trigger-delight { background: #ebf8ff; color: #2b6cb0; }
.trigger-social { background: #faf5ff; color: #6b21a8; }
.segment-card {
    background: #fff; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 14px; margin: 6px 0;
}
.segment-name { font-weight: 700; color: #1a202c; font-size: 1em; }
.segment-pct { color: #6b7280; font-size: 0.85em; }
.segment-detail { font-size: 0.85em; color: #4a5568; margin-top: 4px; line-height: 1.5; }
.testing-plan {
    background: #f0fdf4; border: 1px solid #bbf7d0;
    border-radius: 10px; padding: 16px; margin-top: 16px;
}
</style>""", unsafe_allow_html=True)

# ── Header ──

st.markdown("## Customer Voice & Creative Briefs")
st.caption("Psychologicky profil zakazniku z recenzi + 4 paralelni creative briefy (Germain pipeline)")

# ── Data Loading ──

def load_voice_profiles():
    """Nacte customer voice profily z DB nebo JSON."""
    profiles = []
    # Try SQLite first
    if VOICE_DB.exists():
        try:
            conn = sqlite3.connect(str(VOICE_DB))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT product_key, profile_json, source_count, created_at, cost_usd "
                "FROM customer_profiles ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            conn.close()
            profiles = [dict(r) for r in rows]
        except Exception:
            pass
    # Fallback: JSON files in data/briefs/
    if not profiles and OUTPUT_DIR.exists():
        for f in sorted(OUTPUT_DIR.glob("customer-voice-profiles-*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for product_key, profile in data.items():
                    profiles.append({
                        "product_key": product_key,
                        "profile_json": json.dumps(profile, ensure_ascii=False),
                        "source_count": profile.get("source_count", 0),
                        "created_at": profile.get("analyzed_at", f.stem[-10:]),
                        "cost_usd": 0,
                    })
            except Exception:
                pass
    return profiles


def load_briefs_json():
    """Nacte creative briefs z JSON souboru."""
    briefs = []
    if OUTPUT_DIR.exists():
        for f in sorted(OUTPUT_DIR.glob("creative-briefs-*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                briefs.append({"file": f.name, "data": data})
            except Exception:
                pass
    return briefs


profiles = load_voice_profiles()
briefs_files = load_briefs_json()

if not profiles and not briefs_files:
    st.info("Zatim zadna data. Spust `python customer_voice_mining.py` a `python creative_brief_generator.py` na lokalnim stroji a commitni JSON vystupy do `data/briefs/`.")
    st.stop()

# ── Tab layout ──

tab_briefs, tab_voice, tab_history = st.tabs(["Creative Briefs", "Customer Voice", "Historie"])

# ══════════════════════════════════════════════════════════════
# TAB 1: Creative Briefs
# ══════════════════════════════════════════════════════════════

with tab_briefs:
    if not briefs_files:
        st.info("Zadne briefy. Commitni JSON do `data/briefs/`.")
    else:
        brief_options = [f["file"] for f in briefs_files]
        selected_brief_file = st.selectbox("Brief set", brief_options, index=0, key="brief_select")
        brief_data = next((f["data"] for f in briefs_files if f["file"] == selected_brief_file), {})

        product_name = brief_data.get("product", "?")
        generated_at = brief_data.get("generated_at", "?")
        st.markdown(f"**Produkt:** {product_name} · **Vygenerovano:** {generated_at[:16] if len(generated_at) > 16 else generated_at}")

        briefs_list = brief_data.get("briefs", [])

        if not briefs_list:
            st.warning("Brief soubor je prazdny nebo neplatny.")
        else:
            # Overview grid
            cols = st.columns(len(briefs_list))
            for idx, (col, brief) in enumerate(zip(cols, briefs_list)):
                with col:
                    visual = brief.get("visual_direction", {})
                    palette = visual.get("color_palette", [])
                    format_rec = visual.get("format_recommendation", "?")
                    format_emoji = {"video": "🎬", "static": "📸", "carousel": "🎠"}.get(format_rec, "📎")
                    swatches = "".join([f'<span class="color-swatch" style="background:{c}"></span>' for c in palette[:3]])

                    st.markdown(f"""<div class="brief-card">
<div class="brief-header">#{brief.get('brief_number', idx+1)} {brief.get('brief_name', '?')}</div>
<span class="brief-tag tag-visual">{brief.get('visual_world', '?')[:25]}</span>
<span class="brief-tag tag-emotion">{brief.get('emotional_angle', '?')[:25]}</span><br>
<span class="brief-tag tag-segment">{brief.get('target_segment', '?')[:25]}</span>
<span class="brief-tag tag-format">{format_emoji} {format_rec}</span>
<div class="brief-oneliner">{brief.get('concept', {}).get('one_liner', '')}</div>
<div class="brief-section">
<div class="brief-section-title">Palette</div>
{swatches}
</div>
</div>""", unsafe_allow_html=True)

            st.divider()

            # Detailed view
            st.markdown("### Detail briefu")
            brief_names = [f"#{b.get('brief_number', i+1)}: {b.get('brief_name', '?')}" for i, b in enumerate(briefs_list)]
            selected_idx = st.selectbox("Vyber brief", range(len(brief_names)), format_func=lambda i: brief_names[i], key="brief_detail")
            b = briefs_list[selected_idx]

            d1, d2 = st.columns(2)

            with d1:
                concept = b.get("concept", {})
                st.markdown("#### Concept")
                st.markdown(f"""<div class="brief-copy">
<strong>One-liner:</strong> {concept.get('one_liner', '-')}<br>
<strong>Story arc:</strong> {concept.get('story_arc', '-')}<br>
<strong>Key insight:</strong> {concept.get('key_insight', '-')}
</div>""", unsafe_allow_html=True)

                copy = b.get("ad_copy", {})
                st.markdown("#### Ad Copy")
                st.markdown(f"""<div class="brief-copy">
<strong>Primary text:</strong><br>{copy.get('primary_text', '-')}<br><br>
<strong>Headline:</strong> {copy.get('headline', '-')}<br>
<strong>Description:</strong> {copy.get('description', '-')}<br>
<strong>CTA:</strong> {copy.get('cta_button', '-')}
</div>""", unsafe_allow_html=True)

            with d2:
                visual = b.get("visual_direction", {})
                palette = visual.get("color_palette", [])
                swatches = " ".join([f'<span class="color-swatch" style="background:{c}"></span><code>{c}</code>' for c in palette])
                st.markdown("#### Visual Direction")
                st.markdown(f"""<div class="brief-copy">
<strong>Hero shot:</strong> {visual.get('hero_shot', '-')}<br>
<strong>Palette:</strong> {swatches}<br>
<strong>Text overlay:</strong> {visual.get('text_overlay', 'zadny')}<br>
<strong>Mood:</strong> {visual.get('mood', '-')}<br>
<strong>Format:</strong> {visual.get('format_recommendation', '-')}
</div>""", unsafe_allow_html=True)

                hooks = b.get("hooks", {})
                st.markdown("#### Hooks")
                st.markdown(f"""<div class="brief-copy">
<strong>Scroll-stop:</strong> {hooks.get('scroll_stop_element', '-')}<br>
<strong>First 3s:</strong> {hooks.get('first_3_seconds', '-')}<br>
<strong>Curiosity gap:</strong> {hooks.get('curiosity_gap', '-')}
</div>""", unsafe_allow_html=True)

            st.markdown(f"""<div style="background:#eef2ff;border-radius:8px;padding:12px 16px;margin:12px 0;font-size:0.9em">
<strong>Proc to funguje:</strong> {b.get('why_this_works', '-')}</div>""", unsafe_allow_html=True)

        plan = brief_data.get("testing_plan", {})
        if plan:
            st.markdown(f"""<div class="testing-plan">
<strong>Testing Plan</strong><br>
<strong>Budget split:</strong> {plan.get('budget_split', '-')}<br>
<strong>Success metrics:</strong> {plan.get('success_metrics', '-')}<br>
<strong>Kill criteria:</strong> {plan.get('kill_criteria', '-')}<br>
<strong>Iteration:</strong> {plan.get('iteration_plan', '-')}
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# TAB 2: Customer Voice
# ══════════════════════════════════════════════════════════════

with tab_voice:
    if not profiles:
        st.info("Zadne customer voice profily.")
    else:
        profile_options = [f"{p['product_key']} ({str(p['created_at'])[:10]})" for p in profiles]
        sel_profile_idx = st.selectbox("Profil", range(len(profile_options)), format_func=lambda i: profile_options[i], key="voice_select")
        p = profiles[sel_profile_idx]
        profile = json.loads(p["profile_json"]) if isinstance(p["profile_json"], str) else p["profile_json"]

        st.markdown(f"**Produkt:** {profile.get('product', p['product_key'])} · "
                    f"**Zdroju:** {p['source_count']}")

        # Segments
        st.markdown("### Zakaznicke segmenty")
        segments = profile.get("customer_segments", [])
        seg_cols = st.columns(min(len(segments), 3)) if segments else []
        for idx, (col, seg) in enumerate(zip(seg_cols, segments)):
            with col:
                pains = "".join([f"<li>{pp}</li>" for pp in seg.get("pain_points", [])])
                desires = "".join([f"<li>{d}</li>" for d in seg.get("desires", [])])
                st.markdown(f"""<div class="segment-card">
<div class="segment-name">{seg.get('name', '?')}</div>
<div class="segment-pct">~{seg.get('percentage_estimate', '?')}% zakazniku</div>
<div class="segment-detail">
<strong>Motivace:</strong> {seg.get('primary_motivation', '-')}<br>
<strong>Pain points:</strong><ul>{pains}</ul>
<strong>Desires:</strong><ul>{desires}</ul>
</div>
</div>""", unsafe_allow_html=True)

        st.divider()

        # Emotional Triggers
        st.markdown("### Emocionalni triggery")
        triggers = profile.get("emotional_triggers", {})
        trigger_map = {
            "fear": ("Strach", "trigger-fear"),
            "aspiration": ("Aspirace", "trigger-aspiration"),
            "frustration": ("Frustrace", "trigger-frustration"),
            "delight": ("Nadchazeni", "trigger-delight"),
            "social_proof": ("Social Proof", "trigger-social"),
        }
        for key, values in triggers.items():
            label, css_class = trigger_map.get(key, (key, "trigger-fear"))
            items = values if isinstance(values, list) else [values]
            tags = "".join([f'<span class="voice-trigger {css_class}">{v}</span>' for v in items])
            st.markdown(f"**{label}:** {tags}", unsafe_allow_html=True)

        st.divider()

        # Voice Vocabulary
        st.markdown("### Voice of Customer — presne fraze")
        vocab = profile.get("voice_vocabulary", {})

        v1, v2 = st.columns(2)
        with v1:
            st.markdown("**Exact phrases**")
            phrases = vocab.get("exact_phrases", [])
            tags = "".join([f'<span class="voice-phrase">"{ph}"</span>' for ph in phrases])
            st.markdown(tags, unsafe_allow_html=True)

            st.markdown("**Power words**")
            words = vocab.get("power_words", [])
            tags = "".join([f'<span class="voice-phrase">{w}</span>' for w in words])
            st.markdown(tags, unsafe_allow_html=True)

        with v2:
            st.markdown("**Objections (pred nakupem)**")
            for obj in vocab.get("objections", []):
                st.markdown(f'- _{obj}_')

            st.markdown("**Praise patterns**")
            for pr in vocab.get("praise_patterns", []):
                st.markdown(f'- "{pr}"')

            st.markdown("**Comparison language**")
            for c in vocab.get("comparison_language", []):
                st.markdown(f'- {c}')

        st.divider()

        # Purchase Drivers
        st.markdown("### Purchase Drivers")
        drivers = profile.get("purchase_drivers", {})
        dr1, dr2, dr3 = st.columns(3)
        with dr1:
            st.markdown("**Racionalni**")
            for d in drivers.get("rational", []):
                st.markdown(f"- {d}")
        with dr2:
            st.markdown("**Emocionalni**")
            for d in drivers.get("emotional", []):
                st.markdown(f"- {d}")
        with dr3:
            st.markdown("**Kontextualni**")
            for d in drivers.get("contextual", []):
                st.markdown(f"- {d}")

        # Ad Copy Recs
        recs = profile.get("ad_copy_recommendations", {})
        if recs:
            st.divider()
            st.markdown("### Ad Copy doporuceni (v zakaznickem jazyce)")
            r1, r2, r3 = st.columns(3)
            with r1:
                st.markdown("**Headline hooks**")
                for h in recs.get("headline_hooks", []):
                    st.markdown(f"- {h}")
            with r2:
                st.markdown("**Body angles**")
                for b_angle in recs.get("body_angles", []):
                    st.markdown(f"- {b_angle}")
            with r3:
                st.markdown("**CTA variations**")
                for c in recs.get("cta_variations", []):
                    st.markdown(f"- {c}")


# ══════════════════════════════════════════════════════════════
# TAB 3: Historie
# ══════════════════════════════════════════════════════════════

with tab_history:
    st.markdown("### Historie voice profilingu a briefu")

    if profiles:
        st.markdown("**Customer Voice profily:**")
        for p in profiles:
            profile_data = json.loads(p["profile_json"]) if isinstance(p["profile_json"], str) else p["profile_json"]
            n_segments = len(profile_data.get("customer_segments", []))
            n_phrases = len(profile_data.get("voice_vocabulary", {}).get("exact_phrases", []))
            st.markdown(
                f"- **{p['product_key']}** · {str(p['created_at'])[:10]} · "
                f"{p['source_count']} zdroju · {n_segments} segmentu · {n_phrases} frazi"
            )

    if briefs_files:
        st.markdown("**Creative Briefs:**")
        for bf in briefs_files:
            data = bf["data"]
            n_briefs = len(data.get("briefs", []))
            product = data.get("product", "?")
            generated = data.get("generated_at", "?")[:10]
            st.markdown(f"- **{product}** · {generated} · {n_briefs} briefu · `{bf['file']}`")

    # List files
    st.divider()
    st.markdown("**Output soubory v data/briefs/:**")
    if OUTPUT_DIR.exists():
        for f in sorted(OUTPUT_DIR.glob("*.*"), reverse=True)[:15]:
            size_kb = f.stat().st_size / 1024
            st.caption(f"`{f.name}` · {size_kb:.0f} KB")
