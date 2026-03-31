#!/usr/bin/env python3
"""
Fermato Creative Brief Generator — Germain Step 3+4
====================================================
Generuje 4 paralelni creative briefy, kazdy s jinou emoci,
vizualnim stylem a psychologickym triggerem.

Napojuje se na:
- customer_voice_mining.py (zakaznicky profil + jazyk)
- creative_intelligence.py (performance data — co funguje, co ne)
- creative_vision.py DB (AI analyza existujicich kreativ)

Pouziti:
    python creative_brief_generator.py                          # default: jerky
    python creative_brief_generator.py --product napivo         # konkretni produkt
    python creative_brief_generator.py --product naley --json   # JSON output
    python creative_brief_generator.py --with-mining            # spusti i voice mining

Vystup: 4 creative briefy s ad copy, vizualnim smerem a CTA
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from claude_client import call_claude, parse_json_from_response, ANTHROPIC_API_KEY

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = SCRIPT_DIR.parent / "outputs"

VOICE_DB_PATH = DATA_DIR / "customer_voice.db"
VISION_DB_PATH = DATA_DIR / "creative_analysis.db"

# Vizualni styly pro briefy (inspirovano Germainem)
VISUAL_WORLDS = [
    {
        "name": "Monochromatic Bold",
        "description": "Jeden dominantni barevny svet. Produkt jako hrdina. Minimalisticke, cisty background. Art-directed flat lay nebo lifestyle.",
        "color_approach": "Jedna dominantni barva + jeji odstiny. Produkt kontrastuje.",
        "photography_style": "Studio/flat lay, dramaticke svetlo, cistota",
        "reference": "Germain 'Ditch the shelf' styl — zlata monochromaticka, bold text overlay",
    },
    {
        "name": "Raw UGC / Anti-ad",
        "description": "Vypada jako organicky post, ne jako reklama. Selfie styl, neupravene pozadi, rucne psany text. Autenticita > produkce.",
        "color_approach": "Prirozene barvy, zadne gradienty. Mobilni fotka estetika.",
        "photography_style": "Telefon-quality, lifestyle, in-situ",
        "reference": "Germain UGC angle — 'tvuj shelf te podvedl' casual tone",
    },
    {
        "name": "Visual Metaphor / Concept",
        "description": "Produkt vsazen do neocekavaneho kontextu. Vizualni metafora ktera dela scroll-stop. Konceptualni, ne doslovne.",
        "color_approach": "Kontrast mezi metaforou a produktem. Surprize element.",
        "photography_style": "Konceptualni, surrealisticke elementy, vizualni humor",
        "reference": "Germain 'Welcome to Vanilla Paradise' — produkt jako vstup do jineho sveta",
    },
    {
        "name": "Data / Social Proof",
        "description": "Cisla, statistiky, recenze jako hlavni vizual. 'X lidi uz vyzkouselo'. Screenshot-style dukazy. Trust-building.",
        "color_approach": "Ciste pozadi, vyrazne cisla. Kontrastni CTA.",
        "photography_style": "Infographic styl, screenshot-real recenze, split-screen",
        "reference": "Germain 'Real ingredients, Zero guesswork' — fakta jako hook",
    },
]

# Emocionalni uhly
EMOTIONAL_ANGLES = [
    {
        "name": "Fear of Missing Out / Urgency",
        "trigger": "Strach ze zakaznik neco propasne. Casova omezenost. Exkluzivita.",
        "tone": "Nalehavy, energicky, prime",
    },
    {
        "name": "Identity / Aspiration",
        "trigger": "Zakaznik chce byt nekym. Produkt je symbol identity. 'Lide jako ty...'",
        "tone": "Inspirativni, aspiracni, warm",
    },
    {
        "name": "Frustration / Problem-Solution",
        "trigger": "Zakaznik je nastvany na status quo. Produkt je vychodisko. 'Uz te nebavi...'",
        "tone": "Empaticky, pak resolutni. Problem → reseni.",
    },
    {
        "name": "Delight / Discovery",
        "trigger": "Zakaznik objevi neco noveho a je nadchazeny. WOW efekt. Curiosity gap.",
        "tone": "Vesely, prekvapeny, zvedly",
    },
]


# ── Data Loading ──

def load_customer_profile(product_key):
    """Nacte posledni customer voice profil z DB."""
    if not VOICE_DB_PATH.exists():
        return None

    try:
        conn = sqlite3.connect(str(VOICE_DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT profile_json FROM customer_profiles "
                "WHERE product_key = ? ORDER BY created_at DESC LIMIT 1",
                (product_key,)
            ).fetchone()
            if row:
                return json.loads(row["profile_json"])
        finally:
            conn.close()
    except Exception as e:
        print(f"  WARN: Nelze nacist customer profil: {e}", file=sys.stderr)
    return None


def load_creative_analysis():
    """Nacte posledni AI analyzy kreativ z creative_vision DB."""
    if not VISION_DB_PATH.exists():
        return []

    try:
        conn = sqlite3.connect(str(VISION_DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ad_id, creative_type, hook_analysis, full_analysis, recommendation "
                "FROM creative_analyses ORDER BY analyzed_at DESC LIMIT 20"
            ).fetchall()
            analyses = []
            for row in rows:
                analyses.append({
                    "ad_id": row["ad_id"],
                    "type": row["creative_type"],
                    "hook": json.loads(row["hook_analysis"]) if row["hook_analysis"] else None,
                    "full": json.loads(row["full_analysis"]) if row["full_analysis"] else None,
                    "recommendation": row["recommendation"],
                })
            return analyses
        finally:
            conn.close()
    except Exception as e:
        print(f"  WARN: Nelze nacist creative analyzy: {e}", file=sys.stderr)
        return []


def load_performance_data(days=14):
    """Nacte aktualni performance metriky z creative_intelligence."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import creative_intelligence as ci

        if not os.environ.get("META_ADS_ACCESS_TOKEN"):
            return None

        raw_data = ci.fetch_ad_insights(days)
        ads = [ci.calculate_metrics(row) for row in raw_data]
        ads.sort(key=lambda x: x.get("roas", 0), reverse=True)

        # Sumarizuj
        total_spend = sum(a.get("spend", 0) for a in ads)
        total_purchases = sum(a.get("purchases", 0) for a in ads)
        avg_roas = sum(a.get("roas", 0) * a.get("spend", 0) for a in ads) / total_spend if total_spend else 0

        top_5 = [{
            "name": a.get("ad_name", "")[:60],
            "roas": round(a.get("roas", 0), 2),
            "hook_rate": round(a.get("hook_rate", 0), 1),
            "spend": round(a.get("spend", 0)),
        } for a in ads[:5]]

        worst_5 = [{
            "name": a.get("ad_name", "")[:60],
            "roas": round(a.get("roas", 0), 2),
            "hook_rate": round(a.get("hook_rate", 0), 1),
        } for a in ads[-5:] if a.get("spend", 0) > 200]

        return {
            "total_ads": len(ads),
            "total_spend": round(total_spend),
            "total_purchases": total_purchases,
            "avg_roas": round(avg_roas, 2),
            "top_performers": top_5,
            "worst_performers": worst_5,
        }
    except Exception as e:
        print(f"  WARN: Nelze nacist performance data: {e}", file=sys.stderr)
        return None


# ── Brief Generation ──

def generate_briefs(product_key, customer_profile=None, performance=None, creative_analyses=None):
    """Generuje 4 paralelni creative briefy."""

    # Importuj product config z voice mining
    sys.path.insert(0, str(SCRIPT_DIR))
    from customer_voice_mining import FERMATO_PRODUCTS
    config = FERMATO_PRODUCTS.get(product_key, {"name": product_key})

    # Build context blocks
    profile_context = ""
    if customer_profile:
        vocab = customer_profile.get("voice_vocabulary", {})
        segments = customer_profile.get("customer_segments", [])
        triggers = customer_profile.get("emotional_triggers", {})
        drivers = customer_profile.get("purchase_drivers", {})

        profile_context = f"""
ZAKAZNICKY PROFIL ({config.get('name', product_key)}):

Segmenty:
{json.dumps(segments, indent=2, ensure_ascii=False)}

Emocionalni triggery:
{json.dumps(triggers, indent=2, ensure_ascii=False)}

Zakaznicky jazyk (PRESNE FRAZE — pouzij je!):
{json.dumps(vocab, indent=2, ensure_ascii=False)}

Purchase drivers:
{json.dumps(drivers, indent=2, ensure_ascii=False)}
"""

    perf_context = ""
    if performance:
        perf_context = f"""
AKTUALNI PERFORMANCE DATA:
- Celkem {performance['total_ads']} aktivnich reklam
- Prumerny ROAS: {performance['avg_roas']}
- Top performers (co funguje): {json.dumps(performance['top_performers'], indent=2, ensure_ascii=False)}
- Worst performers (ceho se vyvarovat): {json.dumps(performance['worst_performers'], indent=2, ensure_ascii=False)}
"""

    vision_context = ""
    if creative_analyses:
        vision_summary = []
        for a in creative_analyses[:8]:
            hook = a.get("hook", {})
            if isinstance(hook, dict):
                vision_summary.append({
                    "type": a["type"],
                    "hook_type": hook.get("hook_type", "?"),
                    "recommendation": a.get("recommendation", ""),
                })
        if vision_summary:
            vision_context = f"""
AI ANALYZA EXISTUJICICH KREATIV:
{json.dumps(vision_summary, indent=2, ensure_ascii=False)}
"""

    # Build visual worlds description
    worlds_desc = "\n".join([
        f"SVET {i+1}: {w['name']}\n  {w['description']}\n  Barvy: {w['color_approach']}\n  Fotografie: {w['photography_style']}"
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
  Dalsi produkty: chilli omacka, Crunch topping, Simrato koreni, ocet — vsechno fermentovane.
  Positioning: clean label, bez ecek, premium kvalita, founder-led (Radim Stranik).
  Discovery brand — zakaznici nas neznaaji, musi nas objevit pres reklamu.
KANAL: Meta Ads (Facebook feed, Instagram feed, Stories, Reels)
CIL: Purchase (ROAS > 2.5, CPA < 250 CZK)

{profile_context}

{perf_context}

{vision_context}

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
                "story_arc": "hook → body → cta popis",
                "key_insight": "zakaznicka pravda na ktere stavime"
            }},

            "ad_copy": {{
                "primary_text": "hlavni text reklamy (max 125 znaku nad obrazkem)",
                "headline": "headline pod obrazkem (max 40 znaku)",
                "description": "popisek (max 30 znaku)",
                "cta_button": "SHOP_NOW | LEARN_MORE | GET_OFFER"
            }},

            "visual_direction": {{
                "hero_shot": "popis hlavniho vizualu",
                "color_palette": ["#hex1", "#hex2", "#hex3"],
                "text_overlay": "text na obrazku (pokud je)",
                "mood": "atmosfera — 2-3 slova",
                "format_recommendation": "static | video | carousel"
            }},

            "hooks": {{
                "scroll_stop_element": "co zastavy palec",
                "first_3_seconds": "co se stane v prvnich 3s (pro video)",
                "curiosity_gap": "co zakaznika pritahne dal"
            }},

            "why_this_works": "1-2 vety proc tento pristup funguje pro tento segment"
        }}
    ],

    "testing_plan": {{
        "budget_split": "jak rozdelit budget mezi 4 briefy",
        "success_metrics": "co merici — ROAS, hook rate, CTR",
        "kill_criteria": "kdy brief zabit",
        "iteration_plan": "co delat s vitezem"
    }}
}}

KRITICKA PRAVIDLA:
1. Kazdy brief MUSI pouzivat JINY vizualni svet a JINY emocionalni uhel
2. Ad copy MUSI pouzivat zakaznicky jazyk (z profilu) — NE marketingovy zargon
3. Briefy musi vypadat jako od 4 RUZNYCH agentur — uplne odlisne pristupy
4. HEADLINES max 40 znaku, PRIMARY TEXT max 125 znaku — Meta limity
5. Barvy jako hex kody, ne slovni popis
6. Vse v CESTINE
7. Hook je nejdulezitejsi cast — 80% uspechu je v prvnich 3 sekundach"""

    print(f"\n  Generuji 4 creative briefy ({config.get('name', product_key)})...", file=sys.stderr)
    response, cost = call_claude(prompt, max_tokens=6000)
    briefs = parse_json_from_response(response)

    print(f"  Briefy vygenerovany. Cost: ${cost:.4f}", file=sys.stderr)
    return briefs, cost


# ── Report Formatting ──

def format_briefs_report(briefs_data):
    """Formatuje briefy jako citelny Markdown report."""
    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"CREATIVE BRIEFS: {briefs_data.get('product', '?')}")
    lines.append(f"Generated: {briefs_data.get('generated_at', 'N/A')}")
    lines.append(f"{'='*70}")

    for brief in briefs_data.get("briefs", []):
        lines.append(f"\n{'─'*70}")
        lines.append(f"## BRIEF #{brief.get('brief_number', '?')}: {brief.get('brief_name', '?')}")
        lines.append(f"{'─'*70}")
        lines.append(f"Visual World: {brief.get('visual_world', '?')}")
        lines.append(f"Emotional Angle: {brief.get('emotional_angle', '?')}")
        lines.append(f"Target Segment: {brief.get('target_segment', '?')}")

        concept = brief.get("concept", {})
        lines.append(f"\n### CONCEPT")
        lines.append(f"  One-liner: {concept.get('one_liner', '?')}")
        lines.append(f"  Story arc: {concept.get('story_arc', '?')}")
        lines.append(f"  Key insight: {concept.get('key_insight', '?')}")

        copy = brief.get("ad_copy", {})
        lines.append(f"\n### AD COPY")
        lines.append(f"  Primary text: {copy.get('primary_text', '?')}")
        lines.append(f"  Headline: {copy.get('headline', '?')}")
        lines.append(f"  Description: {copy.get('description', '?')}")
        lines.append(f"  CTA: {copy.get('cta_button', '?')}")

        visual = brief.get("visual_direction", {})
        lines.append(f"\n### VISUAL DIRECTION")
        lines.append(f"  Hero shot: {visual.get('hero_shot', '?')}")
        lines.append(f"  Palette: {', '.join(visual.get('color_palette', []))}")
        lines.append(f"  Text overlay: {visual.get('text_overlay', 'zadny')}")
        lines.append(f"  Mood: {visual.get('mood', '?')}")
        lines.append(f"  Format: {visual.get('format_recommendation', '?')}")

        hooks = brief.get("hooks", {})
        lines.append(f"\n### HOOKS")
        lines.append(f"  Scroll-stop: {hooks.get('scroll_stop_element', '?')}")
        lines.append(f"  First 3s: {hooks.get('first_3_seconds', '?')}")
        lines.append(f"  Curiosity gap: {hooks.get('curiosity_gap', '?')}")

        lines.append(f"\n  WHY: {brief.get('why_this_works', '?')}")

    # Testing plan
    plan = briefs_data.get("testing_plan", {})
    if plan:
        lines.append(f"\n{'='*70}")
        lines.append(f"## TESTING PLAN")
        lines.append(f"{'='*70}")
        lines.append(f"  Budget split: {plan.get('budget_split', '?')}")
        lines.append(f"  Success metrics: {plan.get('success_metrics', '?')}")
        lines.append(f"  Kill criteria: {plan.get('kill_criteria', '?')}")
        lines.append(f"  Iteration: {plan.get('iteration_plan', '?')}")

    return "\n".join(lines)


# ── Main ──

def main():
    product_key = "zalivka"  # default — core Fermato produkt
    output_format = "text"
    with_mining = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--product" and i + 1 < len(args):
            product_key = args[i + 1]
            i += 2
        elif args[i] == "--json":
            output_format = "json"
            i += 1
        elif args[i] == "--with-mining":
            with_mining = True
            i += 1
        else:
            i += 1

    if not ANTHROPIC_API_KEY:
        print("CHYBA: ANTHROPIC_API_KEY neni nastaven", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"CREATIVE BRIEF GENERATOR: {product_key}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 1. Pokud --with-mining, spusti customer voice mining nejdrive
    if with_mining:
        print("\n  [1/4] Customer Voice Mining...", file=sys.stderr)
        from customer_voice_mining import collect_voices, build_customer_profile
        voices = collect_voices(product_key)
        if voices:
            build_customer_profile(product_key, voices)

    # 2. Nacti customer profil
    print("\n  [2/4] Nacitam customer profil...", file=sys.stderr)
    customer_profile = load_customer_profile(product_key)
    if customer_profile:
        print(f"    -> Profil nalezen ({customer_profile.get('source_count', 0)} zdroju)", file=sys.stderr)
    else:
        print(f"    -> Zadny profil. Pouzij --with-mining nebo spust customer_voice_mining.py", file=sys.stderr)

    # 3. Nacti performance data
    print("\n  [3/4] Nacitam performance data...", file=sys.stderr)
    performance = load_performance_data()
    if performance:
        print(f"    -> {performance['total_ads']} ads, ROAS {performance['avg_roas']}", file=sys.stderr)
    else:
        print(f"    -> Bez performance dat (META_ADS_ACCESS_TOKEN?)", file=sys.stderr)

    # 4. Nacti AI analyzy kreativ
    creative_analyses = load_creative_analysis()
    if creative_analyses:
        print(f"    -> {len(creative_analyses)} AI analyzovanych kreativ", file=sys.stderr)

    # 5. Generuj briefy
    print("\n  [4/4] Generuji 4 creative briefy...", file=sys.stderr)
    briefs, cost = generate_briefs(product_key, customer_profile, performance, creative_analyses)

    # Output (Windows cp1250 safe)
    if output_format == "json":
        sys.stdout.buffer.write(json.dumps(briefs, indent=2, ensure_ascii=False).encode("utf-8"))
    else:
        report = format_briefs_report(briefs)
        sys.stdout.buffer.write(report.encode("utf-8"))

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    report = format_briefs_report(briefs)
    report_path = OUTPUT_DIR / f"creative-briefs-{product_key}-{date_str}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport ulozen: {report_path}", file=sys.stderr)

    json_path = OUTPUT_DIR / f"creative-briefs-{product_key}-{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(briefs, f, indent=2, ensure_ascii=False)
    print(f"JSON ulozen: {json_path}", file=sys.stderr)
    print(f"\nCelkovy cost: ${cost:.4f}", file=sys.stderr)


if __name__ == "__main__":
    main()
