"""Creative Brief Generator — Germain Step 3+4.

Generuje 4 paralelni creative briefy, kazdy s jinou emoci,
vizualnim stylem a psychologickym triggerem.
"""

import json
import os
import sys
from datetime import datetime

from .claude_client import call_claude, parse_json_from_response
from .config import DATA_DIR
from .voice import FERMATO_PRODUCTS, load_latest_profile

# Vizualni styly (Germain-inspired)
VISUAL_WORLDS = [
    {
        "name": "Monochromatic Bold",
        "description": "Jeden dominantni barevny svet. Produkt jako hrdina. Studio/flat lay, dramaticke svetlo.",
        "color_approach": "Jedna dominantni barva + jeji odstiny. Produkt kontrastuje.",
        "photography_style": "Studio/flat lay, dramaticke svetlo, cistota",
    },
    {
        "name": "Raw UGC / Anti-ad",
        "description": "Organicky post, ne reklama. Selfie styl, neupravene pozadi, autenticita > produkce.",
        "color_approach": "Prirozene barvy, zadne gradienty. Mobilni fotka estetika.",
        "photography_style": "Telefon-quality, lifestyle, in-situ",
    },
    {
        "name": "Visual Metaphor / Concept",
        "description": "Produkt v neocekavanem kontextu. Vizualni metafora, scroll-stop.",
        "color_approach": "Kontrast mezi metaforou a produktem. Surprize element.",
        "photography_style": "Konceptualni, surrealisticke elementy, vizualni humor",
    },
    {
        "name": "Data / Social Proof",
        "description": "Cisla, statistiky, recenze jako vizual. Trust-building.",
        "color_approach": "Ciste pozadi, vyrazne cisla. Kontrastni CTA.",
        "photography_style": "Infographic styl, screenshot-real recenze, split-screen",
    },
]

EMOTIONAL_ANGLES = [
    {
        "name": "Fear of Missing Out / Urgency",
        "trigger": "Strach ze zakaznik neco propasne. Casova omezenost. Exkluzivita.",
        "tone": "Nalehavy, energicky, prime",
    },
    {
        "name": "Identity / Aspiration",
        "trigger": "Zakaznik chce byt nekym. Produkt je symbol identity.",
        "tone": "Inspirativni, aspiracni, warm",
    },
    {
        "name": "Frustration / Problem-Solution",
        "trigger": "Zakaznik je nastvany na status quo. Produkt je vychodisko.",
        "tone": "Empaticky, pak resolutni. Problem → reseni.",
    },
    {
        "name": "Delight / Discovery",
        "trigger": "Zakaznik objevi neco noveho a je nadchazeny. WOW efekt.",
        "tone": "Vesely, prekvapeny, zvedly",
    },
]


def load_performance_summary(days=14):
    """Load Meta Ads performance for brief context."""
    try:
        from . import metrics
        if not os.environ.get("META_ADS_ACCESS_TOKEN"):
            return None
        raw_data = metrics.fetch_ad_insights(days)
        ads = [metrics.calculate_metrics(row) for row in raw_data]
        ads.sort(key=lambda x: x.get("roas", 0), reverse=True)

        total_spend = sum(a.get("spend", 0) for a in ads)
        return {
            "total_ads": len(ads),
            "avg_roas": round(sum(a.get("roas", 0) * a.get("spend", 0) for a in ads) / total_spend, 2) if total_spend else 0,
            "top_performers": [{
                "name": a.get("ad_name", "")[:60],
                "roas": round(a.get("roas", 0), 2),
                "hook_rate": round(a.get("hook_rate", 0), 1),
            } for a in ads[:5]],
            "worst_performers": [{
                "name": a.get("ad_name", "")[:60],
                "roas": round(a.get("roas", 0), 2),
            } for a in ads[-5:] if a.get("spend", 0) > 200],
        }
    except Exception as e:
        print(f"  WARN: Nelze nacist performance data: {e}", file=sys.stderr)
        return None


def load_component_insights():
    """Load component library insights for brief context."""
    try:
        from .component_db import get_db, get_top_components
        conn = get_db(readonly=True)
        top_hooks = get_top_components(conn, "hook", metric="hook_rate", limit=5)
        conn.close()
        return [{
            "ad_name": h.get("ad_name", "")[:40],
            "hook_rate": h.get("hook_rate"),
            "hook_type": (h.get("analysis") or {}).get("hook_type", "?"),
        } for h in top_hooks]
    except Exception:
        return []


def generate_briefs(product_key, customer_profile=None, performance=None, component_insights=None):
    """Generate 4 parallel creative briefs."""
    config = FERMATO_PRODUCTS.get(product_key, {"name": product_key})

    # Build context
    profile_context = ""
    if customer_profile:
        vocab = customer_profile.get("voice_vocabulary", {})
        segments = customer_profile.get("customer_segments", [])
        triggers = customer_profile.get("emotional_triggers", {})
        drivers = customer_profile.get("purchase_drivers", {})
        profile_context = f"""
ZAKAZNICKY PROFIL ({config.get('name', product_key)}):
Segmenty: {json.dumps(segments, indent=2, ensure_ascii=False)}
Emocionalni triggery: {json.dumps(triggers, indent=2, ensure_ascii=False)}
Zakaznicky jazyk (PRESNE FRAZE — pouzij je!): {json.dumps(vocab, indent=2, ensure_ascii=False)}
Purchase drivers: {json.dumps(drivers, indent=2, ensure_ascii=False)}
"""

    perf_context = ""
    if performance:
        perf_context = f"""
AKTUALNI PERFORMANCE DATA:
- {performance['total_ads']} aktivnich reklam, prumerny ROAS: {performance['avg_roas']}
- Top: {json.dumps(performance['top_performers'], ensure_ascii=False)}
- Worst: {json.dumps(performance['worst_performers'], ensure_ascii=False)}
"""

    comp_context = ""
    if component_insights:
        comp_context = f"""
TOP HOOKS (z component library):
{json.dumps(component_insights, indent=2, ensure_ascii=False)}
"""

    worlds_desc = "\n".join([
        f"SVET {i+1}: {w['name']}\n  {w['description']}\n  Barvy: {w['color_approach']}"
        for i, w in enumerate(VISUAL_WORLDS)
    ])
    angles_desc = "\n".join([
        f"UHEL {i+1}: {a['name']}\n  Trigger: {a['trigger']}\n  Ton: {a['tone']}"
        for i, a in enumerate(EMOTIONAL_ANGLES)
    ])

    prompt = f"""Jsi senior creative director v performance marketing agenture.
Tvuj ukol: vytvorit 4 KOMPLETNE ODLISNE creative briefy pro Meta Ads (Facebook + Instagram).

PRODUKT: {config.get('name', product_key)}
BRAND: Fermato (fermato.cz) — ceska premium znacka fermentovanych omacek a zalivek.
  Core produkt: salatova zalivka z 6 mesicu fermentovanych rajcat (umami, 6 ingredienci vs 20+ u prumyslovych).
  Positioning: clean label, bez ecek, premium kvalita, founder-led.
  Discovery brand — zakaznici nas neznaji, musi nas objevit pres reklamu.
KANAL: Meta Ads (Facebook feed, Instagram feed, Stories, Reels)
CIL: Purchase (ROAS > 2.5, CPA < 250 CZK)

{profile_context}
{perf_context}
{comp_context}

VIZUALNI SVETY (kazdy brief MUSI pouzit jiny):
{worlds_desc}

EMOCIONALNI UHLY (kazdy brief MUSI pouzit jiny):
{angles_desc}

Vytvor 4 briefy. Odpovez POUZE jako JSON:

{{
    "product": "{config.get('name', product_key)}",
    "generated_at": "{datetime.now().isoformat()}",
    "briefs": [
        {{
            "brief_number": 1,
            "brief_name": "interni nazev briefu",
            "visual_world": "nazev vizualniho sveta",
            "emotional_angle": "nazev emocionalniho uhlu",
            "target_segment": "ktery zakaznicky segment cilime",
            "concept": {{
                "one_liner": "jedna veta co reklama rika",
                "story_arc": "hook → body → cta",
                "key_insight": "zakaznicka pravda"
            }},
            "ad_copy": {{
                "primary_text": "max 125 znaku",
                "headline": "max 40 znaku",
                "description": "max 30 znaku",
                "cta_button": "SHOP_NOW | LEARN_MORE | GET_OFFER"
            }},
            "visual_direction": {{
                "hero_shot": "popis hlavniho vizualu",
                "color_palette": ["#hex1", "#hex2", "#hex3"],
                "text_overlay": "text na obrazku",
                "mood": "atmosfera",
                "format_recommendation": "static | video | carousel"
            }},
            "hooks": {{
                "scroll_stop_element": "co zastavy palec",
                "first_3_seconds": "co se stane v prvnich 3s",
                "curiosity_gap": "co pritahne dal"
            }},
            "why_this_works": "1-2 vety"
        }}
    ],
    "testing_plan": {{
        "budget_split": "jak rozdelit budget",
        "success_metrics": "co merit",
        "kill_criteria": "kdy zabit",
        "iteration_plan": "co s vitezem"
    }}
}}

KRITICKA PRAVIDLA:
1. Kazdy brief MUSI pouzivat JINY vizualni svet a JINY emocionalni uhel
2. Ad copy MUSI pouzivat zakaznicky jazyk — NE marketingovy zargon
3. Briefy musi vypadat jako od 4 RUZNYCH agentur
4. HEADLINES max 40 znaku, PRIMARY TEXT max 125 znaku
5. Barvy jako hex kody. Vse v CESTINE."""

    print(f"  Generuji 4 creative briefy ({config.get('name', product_key)})...", file=sys.stderr)
    response, cost = call_claude(prompt, max_tokens=6000)
    briefs = parse_json_from_response(response)
    print(f"  Briefy vygenerovany. Cost: ${cost:.4f}", file=sys.stderr)
    return briefs, cost


def run_briefs_pipeline(product_key="zalivka", with_mining=False):
    """Full briefs pipeline: voice mining (optional) + profile + performance + generate."""
    total_cost = 0

    # 1. Voice mining (optional)
    if with_mining:
        print("  [1/4] Customer Voice Mining...", file=sys.stderr)
        from .voice import collect_voices, build_customer_profile
        voices = collect_voices(product_key)
        if voices:
            _, cost = build_customer_profile(product_key, voices)
            total_cost += cost

    # 2. Load customer profile
    print("  [2/4] Nacitam customer profil...", file=sys.stderr)
    customer_profile = load_latest_profile(product_key)
    if customer_profile:
        print(f"    -> Profil nalezen ({customer_profile.get('source_count', 0)} zdroju)", file=sys.stderr)
    else:
        print(f"    -> Zadny profil. Pouzij --with-mining.", file=sys.stderr)

    # 3. Load performance + components
    print("  [3/4] Nacitam performance data...", file=sys.stderr)
    performance = load_performance_summary()
    component_insights = load_component_insights()

    # 4. Generate briefs
    print("  [4/4] Generuji 4 creative briefy...", file=sys.stderr)
    briefs, cost = generate_briefs(product_key, customer_profile, performance, component_insights)
    total_cost += cost

    # Save
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    json_path = DATA_DIR / f"creative-briefs-{product_key}-{date_str}.json"
    json_path.write_text(json.dumps(briefs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  JSON ulozen: {json_path}", file=sys.stderr)

    md_path = DATA_DIR / f"creative-briefs-{product_key}-{date_str}.md"
    md_path.write_text(format_briefs_report(briefs), encoding="utf-8")
    print(f"  Report ulozen: {md_path}", file=sys.stderr)
    print(f"  Celkovy cost: ${total_cost:.4f}", file=sys.stderr)

    return briefs, total_cost


def format_briefs_report(briefs_data):
    lines = [
        f"{'='*70}",
        f"CREATIVE BRIEFS: {briefs_data.get('product', '?')}",
        f"Generated: {briefs_data.get('generated_at', 'N/A')}",
        f"{'='*70}",
    ]
    for brief in briefs_data.get("briefs", []):
        lines.append(f"\n{'─'*70}")
        lines.append(f"## BRIEF #{brief.get('brief_number', '?')}: {brief.get('brief_name', '?')}")
        lines.append(f"Visual: {brief.get('visual_world', '?')} | Emotion: {brief.get('emotional_angle', '?')}")
        lines.append(f"Segment: {brief.get('target_segment', '?')}")

        concept = brief.get("concept", {})
        lines.append(f"\n  One-liner: {concept.get('one_liner', '?')}")
        lines.append(f"  Story arc: {concept.get('story_arc', '?')}")
        lines.append(f"  Insight: {concept.get('key_insight', '?')}")

        copy = brief.get("ad_copy", {})
        lines.append(f"\n  Primary: {copy.get('primary_text', '?')}")
        lines.append(f"  Headline: {copy.get('headline', '?')}")
        lines.append(f"  CTA: {copy.get('cta_button', '?')}")

        visual = brief.get("visual_direction", {})
        lines.append(f"\n  Hero: {visual.get('hero_shot', '?')}")
        lines.append(f"  Palette: {', '.join(visual.get('color_palette', []))}")
        lines.append(f"  Format: {visual.get('format_recommendation', '?')}")

        hooks = brief.get("hooks", {})
        lines.append(f"\n  Scroll-stop: {hooks.get('scroll_stop_element', '?')}")
        lines.append(f"  WHY: {brief.get('why_this_works', '?')}")

    plan = briefs_data.get("testing_plan", {})
    if plan:
        lines.append(f"\n{'='*70}")
        lines.append(f"TESTING PLAN")
        lines.append(f"  Budget: {plan.get('budget_split', '?')}")
        lines.append(f"  Kill: {plan.get('kill_criteria', '?')}")

    return "\n".join(lines)
