#!/usr/bin/env python3
"""
Fermato Customer Voice Mining — Germain Step 1
===============================================
Sbira zakaznicke recenze, diskuze a komentare z webu,
extrahuje psychologicky profil zakaznika pomoci Claude.

Pouziti:
    python customer_voice_mining.py                      # Fermato default produkty
    python customer_voice_mining.py --product "jerky"    # konkretni produkt
    python customer_voice_mining.py --category "zdrave snacky"
    python customer_voice_mining.py --json               # JSON output
    python customer_voice_mining.py --report             # zobraz posledni profily

Zdroje:
    - Heureka.cz recenze (web scrape)
    - Reddit diskuze (web search)
    - Diskuzni fora (web search)
    - Existujici creative_intelligence data (top ads = co rezonuje)

Vystup: Psychologicky profil zakaznika + slovnik zakaznickeho jazyka
"""

import json
import os
import re
import sqlite3
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

from claude_client import call_claude, parse_json_from_response, ANTHROPIC_API_KEY

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "customer_voice.db"
OUTPUT_DIR = SCRIPT_DIR.parent / "outputs"

# Fermato produktove kategorie a klicova slova
FERMATO_PRODUCTS = {
    # ── CORE BUSINESS ──
    "zalivka": {
        "name": "Fermato Salatova zalivka (fermentovana)",
        "search_terms": [
            "salátová zálivka recenze česko",
            "nejlepší salátový dresink",
            "fermato zálivka zkušenosti",
            "fermentovaná zálivka recenze",
            "zdravá salátová zálivka bez éček",
            "domácí dresink alternativa",
            "zálivka na salát umami",
            "prémiová salátová zálivka eshop",
            "clean label zálivka česko",
        ],
        "heureka_terms": ["salátová zálivka", "dresink", "fermato"],
        "competitors": ["Hellmanns", "Knorr", "Thomy", "Kalvita", "Spak"],
    },
    "chilli": {
        "name": "Fermato Chilli omacka (fermentovana)",
        "search_terms": [
            "chilli omáčka recenze česko",
            "fermentovaná chilli omáčka",
            "pálivá omáčka kvalitní",
            "hot sauce česko recenze",
            "craft chilli omáčka",
            "sriracha alternativa česko",
        ],
        "heureka_terms": ["chilli omáčka", "pálivá omáčka", "hot sauce"],
        "competitors": ["Sriracha", "Tabasco", "Cholula", "Encona", "Frank's RedHot"],
    },
    "crunch": {
        "name": "Fermato Crunch (fermentovany topping)",
        "search_terms": [
            "topping na salát recenze",
            "křupavý topping česko",
            "crunch topping jídlo",
            "zdravý topping bez lepku",
            "crispy topping salát zkušenosti",
        ],
        "heureka_terms": ["topping salát", "crunch topping"],
        "competitors": [],
    },
    "simrato": {
        "name": "Fermato Simrato (fermentovane koreni)",
        "search_terms": [
            "umami koření česko",
            "fermentované koření recenze",
            "náhrada soli zdravá",
            "umami seasoning",
            "přírodní koření bez glutamátu",
        ],
        "heureka_terms": ["umami koření", "fermentované koření"],
        "competitors": ["Ariosto", "Vegeta"],
    },
    "ocet": {
        "name": "Fermato Ocet (fermentovany)",
        "search_terms": [
            "fermentovaný ocet recenze",
            "prémiový ocet česko",
            "raw ocet zdraví",
            "kvalitní ocet na salát",
        ],
        "heureka_terms": ["fermentovaný ocet", "prémiový ocet"],
        "competitors": [],
    },
    "fermato_brand": {
        "name": "Fermato (brand celkove)",
        "search_terms": [
            "fermato recenze",
            "fermato.cz zkušenosti",
            "fermato zálivka hodnocení",
            "fermato eshop objednávka",
            "fermato salátová zálivka kde koupit",
            "fermato fermentované omáčky",
            "fermato Radim Stráník",
        ],
        "heureka_terms": ["fermato"],
        "competitors": ["Heinz", "Hellmanns", "Knorr", "Thomy"],
    },
    # ── SECONDARY BRANDS ──
    "naley": {
        "name": "Naley (vino)",
        "search_terms": [
            "víno online nákup česko zkušenosti",
            "kvalitní víno eshop recenze",
            "víno jako dárek",
            "moravské víno recenze reddit",
            "vino pro zacatecniky",
        ],
        "heureka_terms": ["víno", "moravské víno"],
        "competitors": ["Vinařství u Kapličky", "Sonberk", "Vinofol"],
    },
    "napivo": {
        "name": "NA pivo (nealkoholicke)",
        "search_terms": [
            "nealkoholické pivo recenze 2026",
            "bezalkoholové pivo nejlepší",
            "NA pivo zdravé životní styl",
            "nealko pivo chuť reddit",
            "nealkoholické pivo fitness",
        ],
        "heureka_terms": ["nealkoholické pivo", "nealko pivo"],
        "competitors": ["Birell", "Heineken 0.0", "Bernard Free"],
    },
}

# Google search via SerpAPI or fallback
SERP_API_KEY = os.environ.get("SERP_API_KEY", "")


# ── Database ──

def get_db():
    """Vraci SQLite spojeni pro customer voice data."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS voice_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT,
            raw_content TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS customer_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            voice_vocabulary TEXT NOT NULL,
            source_count INTEGER,
            created_at TEXT NOT NULL,
            cost_usd REAL
        );

        CREATE INDEX IF NOT EXISTS idx_voice_product ON voice_sources(product_key);
        CREATE INDEX IF NOT EXISTS idx_profile_product ON customer_profiles(product_key);
    """)
    conn.commit()


# ── Web Search ──

def search_web(query, num_results=10):
    """Hleda na webu pres Google Custom Search nebo fallback."""
    results = []

    # Metoda 1: SerpAPI (pokud je klic)
    if SERP_API_KEY:
        try:
            params = urllib.parse.urlencode({
                "q": query,
                "api_key": SERP_API_KEY,
                "num": num_results,
                "hl": "cs",
                "gl": "cz",
            })
            url = f"https://serpapi.com/search?{params}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            for r in data.get("organic_results", [])[:num_results]:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                })
            return results
        except Exception as e:
            print(f"  WARN: SerpAPI selhalo: {e}", file=sys.stderr)

    # Metoda 2: DuckDuckGo HTML fallback
    try:
        encoded_q = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Parse results from DDG HTML
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:td|div)',
            html, re.DOTALL
        ):
            href, title, snippet = match.groups()
            # DDG wraps URLs
            actual_url = urllib.parse.unquote(
                re.sub(r".*uddg=([^&]+).*", r"\1", href)
            ) if "uddg=" in href else href
            results.append({
                "title": re.sub(r"<[^>]+>", "", title).strip(),
                "url": actual_url,
                "snippet": re.sub(r"<[^>]+>", "", snippet).strip(),
            })
            if len(results) >= num_results:
                break
        return results
    except Exception as e:
        print(f"  WARN: DuckDuckGo selhalo: {e}", file=sys.stderr)
        return []


def fetch_page_text(url, max_chars=8000):
    """Stahne textovy obsah stranky (stripne HTML tagy)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Strip scripts, styles, tags
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"\s+", " ", html).strip()
        return html[:max_chars]
    except Exception as e:
        print(f"  WARN: Nelze stahnout {url}: {e}", file=sys.stderr)
        return ""


# ── Voice Collection ──

def collect_voices(product_key, max_sources=15):
    """Sbira zakaznicke hlasy z webu pro dany produkt."""
    config = FERMATO_PRODUCTS.get(product_key)
    if not config:
        print(f"CHYBA: Neznamy produkt '{product_key}'", file=sys.stderr)
        return []

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"CUSTOMER VOICE MINING: {config['name']}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    all_voices = []
    db = get_db()

    # 1. Web search — hlavni zdroj
    for term in config["search_terms"]:
        print(f"\n  Hledam: '{term}'...", file=sys.stderr)
        results = search_web(term, num_results=5)

        for r in results:
            url = r["url"]
            # Skip nerelevantni domeny
            if any(skip in url for skip in ["youtube.com", "facebook.com", "instagram.com", ".pdf"]):
                continue

            print(f"    -> {r['title'][:60]}...", file=sys.stderr)

            # Fetch full page text
            page_text = fetch_page_text(url)
            if len(page_text) < 100:
                continue

            # Kombinuj snippet + page text
            content = f"Zdroj: {r['title']}\nURL: {url}\nSnippet: {r['snippet']}\n\nObsah:\n{page_text}"

            # Uloz do DB
            db.execute(
                "INSERT INTO voice_sources (product_key, source_type, source_url, raw_content, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (product_key, "web_search", url, content, datetime.now().isoformat())
            )
            all_voices.append(content)

            if len(all_voices) >= max_sources:
                break
        if len(all_voices) >= max_sources:
            break

    # 2. Heureka-specificke hledani
    for term in config.get("heureka_terms", [])[:2]:
        heureka_query = f"site:heureka.cz {term} recenze"
        print(f"\n  Heureka: '{heureka_query}'...", file=sys.stderr)
        results = search_web(heureka_query, num_results=3)

        for r in results:
            page_text = fetch_page_text(r["url"])
            if len(page_text) < 100:
                continue

            content = f"[HEUREKA RECENZE] {r['title']}\nURL: {r['url']}\n\n{page_text}"
            db.execute(
                "INSERT INTO voice_sources (product_key, source_type, source_url, raw_content, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (product_key, "heureka", r["url"], content, datetime.now().isoformat())
            )
            all_voices.append(content)

    # 3. Reddit-specificke hledani
    reddit_query = f"site:reddit.com {config['search_terms'][0]}"
    print(f"\n  Reddit: '{reddit_query}'...", file=sys.stderr)
    results = search_web(reddit_query, num_results=3)
    for r in results:
        page_text = fetch_page_text(r["url"])
        if len(page_text) < 100:
            continue
        content = f"[REDDIT] {r['title']}\nURL: {r['url']}\n\n{page_text}"
        db.execute(
            "INSERT INTO voice_sources (product_key, source_type, source_url, raw_content, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (product_key, "reddit", r["url"], content, datetime.now().isoformat())
        )
        all_voices.append(content)

    db.commit()
    db.close()

    print(f"\n  Celkem sebrano {len(all_voices)} zdroju.", file=sys.stderr)
    return all_voices


# ── AI Profile Generation ──

def build_customer_profile(product_key, voices, competitor_names=None):
    """Generuje psychologicky profil zakaznika z nasbiraných hlasu."""
    config = FERMATO_PRODUCTS.get(product_key, {})
    product_name = config.get("name", product_key)
    competitors = competitor_names or config.get("competitors", [])

    # Truncate voices to fit context
    combined_voices = "\n\n---\n\n".join(voices[:12])
    if len(combined_voices) > 60000:
        combined_voices = combined_voices[:60000] + "\n\n[... zkraceno ...]"

    prompt = f"""Jsi expert na consumer psychology a copywriting pro e-commerce.

Analyzuj nasledujici zakaznicke recenze, diskuze a komentare o produktu "{product_name}" a jeho kategorii.
Konkurenti: {', '.join(competitors)}

ZAKAZNICKE HLASY:
{combined_voices}

Vytvor PODROBNY psychologicky profil zakaznika. Odpovez POUZE jako JSON:

{{
    "product": "{product_name}",
    "analyzed_at": "{datetime.now().isoformat()}",
    "source_count": {len(voices)},

    "customer_segments": [
        {{
            "name": "nazev segmentu",
            "percentage_estimate": 40,
            "description": "popis",
            "primary_motivation": "co je zene/muze k nakupu",
            "pain_points": ["bolest 1", "bolest 2"],
            "desires": ["touha 1", "touha 2"]
        }}
    ],

    "emotional_triggers": {{
        "fear": ["cim se boji — konkretnich veci z recenzi"],
        "aspiration": ["cim chteji byt"],
        "frustration": ["co je stve na soucasnych produktech"],
        "delight": ["co je potesi, proc daji 5 hvezd"],
        "social_proof": ["co rikaji ostatnim, proc doporucuji"]
    }},

    "voice_vocabulary": {{
        "exact_phrases": ["doslovna slova zakazniku — min 15 frazi"],
        "power_words": ["slova ktera zakaznici pouzivaji casto a s emoci"],
        "objections": ["pochybnosti pred nakupem — doslovna citace"],
        "praise_patterns": ["jak chvali — doslovna citace"],
        "comparison_language": ["jak srovnavaji s konkurenci"]
    }},

    "purchase_drivers": {{
        "rational": ["logicke duvody — cena, kvalita, slozeni"],
        "emotional": ["emocionalni duvody — pocit, status, identita"],
        "contextual": ["kdy nakupuji — situace, prilezitost"]
    }},

    "anti_patterns": {{
        "turnoffs": ["co zakaznika odtlaci — z negativnich recenzi"],
        "failed_promises": ["co konkurence slibuje a neplni"],
        "price_sensitivity": "jak vnimaji cenu — citat"
    }},

    "ad_copy_recommendations": {{
        "headline_hooks": ["5 headline navrhu PRESNYMI slovy zakazniku"],
        "body_angles": ["4 uhly pro body copy — kazdy jina emoce"],
        "cta_variations": ["3 CTA varianty v zakaznickem jazyce"]
    }}
}}

DULEZITE:
- Pouzivej PRESNE slova zakazniku z recenzi, ne marketingovy jazyk
- Cituj doslova tam kde to jde (cudzovky)
- Kazdy segment musi byt podlozeny konkretnimi recenzemi
- Min 15 exact_phrases z realnych recenzi
- Profil musi byt v CESTINE"""

    print(f"\n  Generuji psychologicky profil ({product_name})...", file=sys.stderr)
    response, cost = call_claude(prompt, max_tokens=4000)
    profile = parse_json_from_response(response)

    # Uloz do DB
    db = get_db()
    vocab_json = json.dumps(profile.get("voice_vocabulary", {}), ensure_ascii=False)
    db.execute(
        "INSERT INTO customer_profiles (product_key, profile_json, voice_vocabulary, source_count, created_at, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (product_key, json.dumps(profile, ensure_ascii=False), vocab_json,
         len(voices), datetime.now().isoformat(), cost)
    )
    db.commit()
    db.close()

    print(f"  Profil vygenerovan. Cost: ${cost:.4f}", file=sys.stderr)
    return profile, cost


# ── Competitor Ad Analysis (from existing data) ──

def load_top_performing_ads(days=14):
    """Nacte top a worst performing ads z creative_intelligence dat."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import creative_intelligence as ci

        if not os.environ.get("META_ADS_ACCESS_TOKEN"):
            print("  WARN: META_ADS_ACCESS_TOKEN neni nastaven, preskakuji ad data", file=sys.stderr)
            return None, None

        raw_data = ci.fetch_ad_insights(days)
        ads_metrics = [ci.calculate_metrics(row) for row in raw_data]
        ads_metrics.sort(key=lambda x: x.get("roas", 0), reverse=True)

        top_ads = []
        for m in ads_metrics[:10]:
            recs = ci.evaluate_creative(m)
            top_ads.append({
                "ad_name": m.get("ad_name", ""),
                "roas": m.get("roas", 0),
                "cpa": m.get("cpa", 0),
                "cvr": m.get("cvr", 0),
                "hook_rate": m.get("hook_rate", 0),
                "spend": m.get("spend", 0),
                "action": recs[0][0] if recs else "unknown",
            })

        worst_ads = []
        for m in ads_metrics[-10:]:
            recs = ci.evaluate_creative(m)
            worst_ads.append({
                "ad_name": m.get("ad_name", ""),
                "roas": m.get("roas", 0),
                "cpa": m.get("cpa", 0),
                "hook_rate": m.get("hook_rate", 0),
                "action": recs[0][0] if recs else "unknown",
            })

        return top_ads, worst_ads
    except Exception as e:
        print(f"  WARN: Nelze nacist ad data: {e}", file=sys.stderr)
        return None, None


# ── Report Output ──

def format_profile_report(profile, product_key):
    """Formatuje profil jako citelny text report."""
    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"CUSTOMER VOICE PROFILE: {profile.get('product', product_key)}")
    lines.append(f"Datum: {profile.get('analyzed_at', 'N/A')}")
    lines.append(f"Zdroju: {profile.get('source_count', 0)}")
    lines.append(f"{'='*70}")

    # Segments
    lines.append("\n## ZAKAZNICKE SEGMENTY\n")
    for seg in profile.get("customer_segments", []):
        lines.append(f"### {seg.get('name', '?')} (~{seg.get('percentage_estimate', '?')}%)")
        lines.append(f"  Popis: {seg.get('description', '')}")
        lines.append(f"  Motivace: {seg.get('primary_motivation', '')}")
        lines.append(f"  Pain points: {', '.join(seg.get('pain_points', []))}")
        lines.append(f"  Desires: {', '.join(seg.get('desires', []))}")
        lines.append("")

    # Emotional triggers
    triggers = profile.get("emotional_triggers", {})
    lines.append("\n## EMOCIONALNI TRIGGERY\n")
    for key, values in triggers.items():
        emoji = {"fear": "STRACH", "aspiration": "ASPIRACE", "frustration": "FRUSTRACE",
                 "delight": "NADCHAZENI", "social_proof": "SOCIAL PROOF"}.get(key, key.upper())
        lines.append(f"### {emoji}")
        for v in (values if isinstance(values, list) else [values]):
            lines.append(f"  - {v}")
        lines.append("")

    # Voice vocabulary
    vocab = profile.get("voice_vocabulary", {})
    lines.append("\n## ZAKAZNICKY JAZYK (VOICE OF CUSTOMER)\n")
    for key in ["exact_phrases", "power_words", "objections", "praise_patterns", "comparison_language"]:
        lines.append(f"### {key.replace('_', ' ').upper()}")
        for v in vocab.get(key, []):
            lines.append(f'  - "{v}"')
        lines.append("")

    # Purchase drivers
    drivers = profile.get("purchase_drivers", {})
    lines.append("\n## PURCHASE DRIVERS\n")
    for key, values in drivers.items():
        lines.append(f"### {key.upper()}")
        for v in (values if isinstance(values, list) else [values]):
            lines.append(f"  - {v}")
        lines.append("")

    # Ad copy recommendations
    recs = profile.get("ad_copy_recommendations", {})
    lines.append("\n## AD COPY DOPORUCENI (v zakaznickem jazyce)\n")
    for key in ["headline_hooks", "body_angles", "cta_variations"]:
        lines.append(f"### {key.replace('_', ' ').upper()}")
        for v in recs.get(key, []):
            lines.append(f"  - {v}")
        lines.append("")

    return "\n".join(lines)


def show_latest_profiles():
    """Zobrazi posledni profily z DB."""
    db = get_db()
    rows = db.execute(
        "SELECT product_key, profile_json, source_count, created_at, cost_usd "
        "FROM customer_profiles ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    db.close()

    if not rows:
        print("Zadne profily zatim neexistuji. Spust mining nejdrive.")
        return

    for row in rows:
        profile = json.loads(row["profile_json"])
        print(format_profile_report(profile, row["product_key"]))
        print(f"\n  [Cost: ${row['cost_usd']:.4f} | Created: {row['created_at']}]")
        print()


# ── Main ──

def main():
    product_key = "zalivka"  # default — core Fermato produkt
    output_format = "text"
    show_report = False
    custom_category = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--product" and i + 1 < len(args):
            product_key = args[i + 1]
            i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            custom_category = args[i + 1]
            i += 2
        elif args[i] == "--json":
            output_format = "json"
            i += 1
        elif args[i] == "--report":
            show_report = True
            i += 1
        elif args[i] == "--all":
            product_key = "all"
            i += 1
        else:
            i += 1

    if show_report:
        show_latest_profiles()
        return

    if not ANTHROPIC_API_KEY:
        print("CHYBA: ANTHROPIC_API_KEY neni nastaven", file=sys.stderr)
        sys.exit(1)

    # Custom category — vytvori docasny config
    if custom_category:
        FERMATO_PRODUCTS["custom"] = {
            "name": custom_category,
            "search_terms": [
                f"{custom_category} recenze česko",
                f"{custom_category} zkušenosti",
                f"{custom_category} nejlepší reddit",
                f"{custom_category} srovnání",
            ],
            "heureka_terms": [custom_category],
            "competitors": [],
        }
        product_key = "custom"

    # Run pro jeden nebo vsechny produkty
    products_to_run = list(FERMATO_PRODUCTS.keys()) if product_key == "all" else [product_key]

    total_cost = 0
    all_profiles = {}

    for pkey in products_to_run:
        if pkey not in FERMATO_PRODUCTS:
            print(f"WARN: Neznamy produkt '{pkey}', preskakuji", file=sys.stderr)
            continue

        # 1. Sbere zakaznicke hlasy
        voices = collect_voices(pkey)
        if not voices:
            print(f"  Zadne zdroje nalezeny pro {pkey}", file=sys.stderr)
            continue

        # 2. Nacte performance data (pokud dostupne)
        top_ads, worst_ads = load_top_performing_ads()
        if top_ads:
            # Pridame ad performance kontext do voices
            ad_context = f"\n\n[PERFORMANCE DATA - TOP ADS]\n{json.dumps(top_ads[:5], indent=2, ensure_ascii=False)}"
            ad_context += f"\n\n[PERFORMANCE DATA - WORST ADS]\n{json.dumps(worst_ads[:5], indent=2, ensure_ascii=False)}"
            voices.append(ad_context)

        # 3. Vygeneruj profil
        profile, cost = build_customer_profile(pkey, voices)
        total_cost += cost
        all_profiles[pkey] = profile

    # Output
    if output_format == "json":
        print(json.dumps(all_profiles, indent=2, ensure_ascii=False))
    else:
        for pkey, profile in all_profiles.items():
            report = format_profile_report(profile, pkey)
            print(report)

    # Save to outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    for pkey, profile in all_profiles.items():
        report = format_profile_report(profile, pkey)
        report_path = OUTPUT_DIR / f"customer-voice-{pkey}-{date_str}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport ulozen: {report_path}", file=sys.stderr)

    json_path = OUTPUT_DIR / f"customer-voice-profiles-{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=2, ensure_ascii=False)
    print(f"JSON ulozen: {json_path}", file=sys.stderr)
    print(f"\nCelkovy cost: ${total_cost:.4f}", file=sys.stderr)


if __name__ == "__main__":
    main()
