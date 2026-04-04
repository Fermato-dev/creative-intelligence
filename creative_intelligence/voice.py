"""Customer Voice Mining — Germain Step 1.

Sbira zakaznicke recenze a diskuze z webu, extrahuje psychologicky
profil zakaznika pomoci Claude. Vysledky uklada do customer_voice.db.
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

from .claude_client import call_claude, parse_json_from_response
from .config import DATA_DIR

DB_PATH = DATA_DIR / "customer_voice.db"

SERP_API_KEY = os.environ.get("SERP_API_KEY", "")

# Fermato produktove kategorie
FERMATO_PRODUCTS = {
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
        ],
        "heureka_terms": ["fermato"],
        "competitors": ["Heinz", "Hellmanns", "Knorr", "Thomy"],
    },
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


# ── Database ──

def get_voice_db(readonly=False):
    if readonly:
        if not DB_PATH.exists():
            raise FileNotFoundError(f"Voice DB not found: {DB_PATH}")
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_voice_schema(conn)
    return conn


def _init_voice_schema(conn):
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
    results = []

    if SERP_API_KEY:
        try:
            params = urllib.parse.urlencode({
                "q": query, "api_key": SERP_API_KEY,
                "num": num_results, "hl": "cs", "gl": "cz",
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

    # DuckDuckGo HTML fallback
    try:
        encoded_q = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:td|div)',
            html, re.DOTALL
        ):
            href, title, snippet = match.groups()
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
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
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
    config = FERMATO_PRODUCTS.get(product_key)
    if not config:
        print(f"CHYBA: Neznamy produkt '{product_key}'", file=sys.stderr)
        return []

    print(f"\n  CUSTOMER VOICE MINING: {config['name']}", file=sys.stderr)
    all_voices = []
    db = get_voice_db()

    for term in config["search_terms"]:
        print(f"  Hledam: '{term}'...", file=sys.stderr)
        results = search_web(term, num_results=5)
        for r in results:
            url = r["url"]
            if any(skip in url for skip in ["youtube.com", "facebook.com", "instagram.com", ".pdf"]):
                continue
            page_text = fetch_page_text(url)
            if len(page_text) < 100:
                continue
            content = f"Zdroj: {r['title']}\nURL: {url}\nSnippet: {r['snippet']}\n\nObsah:\n{page_text}"
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

    # Heureka
    for term in config.get("heureka_terms", [])[:2]:
        heureka_query = f"site:heureka.cz {term} recenze"
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

    # Reddit
    reddit_query = f"site:reddit.com {config['search_terms'][0]}"
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
    print(f"  Celkem sebrano {len(all_voices)} zdroju.", file=sys.stderr)
    return all_voices


# ── AI Profile Generation ──

def build_customer_profile(product_key, voices):
    config = FERMATO_PRODUCTS.get(product_key, {})
    product_name = config.get("name", product_key)
    competitors = config.get("competitors", [])

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
        "fear": ["cim se boji"],
        "aspiration": ["cim chteji byt"],
        "frustration": ["co je stve"],
        "delight": ["co je potesi"],
        "social_proof": ["co rikaji ostatnim"]
    }},
    "voice_vocabulary": {{
        "exact_phrases": ["min 15 frazi — doslovna slova zakazniku"],
        "power_words": ["slova ktera zakaznici pouzivaji casto"],
        "objections": ["pochybnosti pred nakupem"],
        "praise_patterns": ["jak chvali"],
        "comparison_language": ["jak srovnavaji s konkurenci"]
    }},
    "purchase_drivers": {{
        "rational": ["logicke duvody"],
        "emotional": ["emocionalni duvody"],
        "contextual": ["kdy nakupuji"]
    }},
    "anti_patterns": {{
        "turnoffs": ["co odtlaci"],
        "failed_promises": ["co konkurence slibuje a neplni"],
        "price_sensitivity": "jak vnimaji cenu"
    }},
    "ad_copy_recommendations": {{
        "headline_hooks": ["5 headline navrhu PRESNYMI slovy zakazniku"],
        "body_angles": ["4 uhly pro body copy"],
        "cta_variations": ["3 CTA varianty"]
    }}
}}

DULEZITE:
- Pouzivej PRESNE slova zakazniku z recenzi, ne marketingovy jazyk
- Min 15 exact_phrases z realnych recenzi
- Vse v CESTINE"""

    print(f"  Generuji psychologicky profil ({product_name})...", file=sys.stderr)
    response, cost = call_claude(prompt, max_tokens=4000)
    profile = parse_json_from_response(response)

    db = get_voice_db()
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


def load_latest_profile(product_key):
    """Load latest customer profile from DB."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT profile_json FROM customer_profiles "
            "WHERE product_key = ? ORDER BY created_at DESC LIMIT 1",
            (product_key,)
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row["profile_json"])
    except Exception:
        pass
    return None


def run_voice_mining(product_key="zalivka", output_format="text"):
    """Main entry point for voice mining pipeline."""
    config = FERMATO_PRODUCTS.get(product_key, {"name": product_key})

    voices = collect_voices(product_key)
    if not voices:
        print(f"Zadne zdroje nalezeny pro {product_key}", file=sys.stderr)
        return None, 0

    profile, cost = build_customer_profile(product_key, voices)

    # Save outputs
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    json_path = DATA_DIR / f"customer-voice-{product_key}-{date_str}.json"
    json_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON ulozen: {json_path}", file=sys.stderr)

    return profile, cost
