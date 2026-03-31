#!/usr/bin/env python3
"""
Fermato Creative Vision — AI analyza Meta Ads kreativ
=====================================================
Stahne creative assety (video/obrazky) z Meta API,
extrahuje klicove framy (ffmpeg), transkribuje audio (whisper),
a analyzuje pres Claude Vision API.

Pouziti:
    python creative_vision.py                          # analyzuj top 20 dle priority
    python creative_vision.py --ad-id 120239068939820  # analyzuj konkretni ad
    python creative_vision.py --list-queue             # zobraz frontu k analyze
    python creative_vision.py --report                 # zobraz posledni analyzy

Vyzaduje:
    - META_ADS_ACCESS_TOKEN (v env)
    - ANTHROPIC_API_KEY (v env)
    - ffmpeg (v PATH)
"""

import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from meta_client import meta_fetch
from claude_client import call_claude_vision, parse_json_from_response

# ── Config ──

ACCESS_TOKEN = os.environ.get("META_ADS_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
ASSETS_DIR = DATA_DIR / "creative_assets"
DB_PATH = DATA_DIR / "creative_analysis.db"
WHISPER_MODEL = DATA_DIR / "models" / "ggml-base.bin"
WHISPER_MODEL_SHORT = "C:/whisper/model.bin"  # Short path for ffmpeg (avoids Windows path issues)
FB_PAGE_ID = "1334931808840161"  # Fermato Facebook Page ID

# Max days before re-analysis
REANALYSIS_DAYS = 7
# Max creatives per daily run
DEFAULT_MAX_CREATIVES = 20

# ── Database ──

def get_db():
    """Vraci SQLite spojeni."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS creative_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id TEXT NOT NULL,
            creative_id TEXT,
            video_id TEXT,
            creative_type TEXT NOT NULL,
            hook_analysis TEXT,
            full_analysis TEXT,
            transcript TEXT,
            performance_snapshot TEXT,
            recommendation TEXT,
            analyzed_at TEXT NOT NULL,
            cost_usd REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ca_ad_id ON creative_analyses(ad_id);
        CREATE INDEX IF NOT EXISTS idx_ca_analyzed_at ON creative_analyses(analyzed_at);
    """)
    conn.commit()


def get_last_analysis(conn, ad_id):
    """Vraci posledni analyzu pro dany ad_id."""
    row = conn.execute(
        "SELECT * FROM creative_analyses WHERE ad_id = ? ORDER BY analyzed_at DESC LIMIT 1",
        (ad_id,)
    ).fetchone()
    return dict(row) if row else None


def save_analysis(conn, ad_id, creative_id, video_id, creative_type,
                  hook_analysis, full_analysis, transcript, performance, recommendation, cost):
    """Ulozi analyzu."""
    conn.execute("""
        INSERT INTO creative_analyses
        (ad_id, creative_id, video_id, creative_type, hook_analysis, full_analysis,
         transcript, performance_snapshot, recommendation, analyzed_at, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ad_id, creative_id, video_id, creative_type,
        json.dumps(hook_analysis, ensure_ascii=False) if hook_analysis else None,
        json.dumps(full_analysis, ensure_ascii=False) if full_analysis else None,
        transcript,
        json.dumps(performance, ensure_ascii=False) if performance else None,
        recommendation,
        datetime.now().isoformat(),
        cost,
    ))
    conn.commit()


# ── Meta API ──

def fetch_creative_assets(ad_ids):
    """Stahne creative metadata pro dane ad IDs."""
    # Fetch ads with creative details
    results = {}
    for ad_id in ad_ids:
        try:
            data = meta_fetch(ad_id, {
                "fields": "id,name,creative{id,name,title,body,image_url,thumbnail_url,video_id,object_type,call_to_action_type}"
            })
            creative = data.get("creative", {})
            results[ad_id] = {
                "ad_id": ad_id,
                "ad_name": data.get("name", ""),
                "creative_id": creative.get("id"),
                "title": creative.get("title", ""),
                "body": creative.get("body", ""),
                "image_url": creative.get("image_url"),
                "thumbnail_url": creative.get("thumbnail_url"),
                "video_id": creative.get("video_id"),
                "object_type": creative.get("object_type"),
                "cta": creative.get("call_to_action_type"),
            }
        except Exception as e:
            print(f"  WARN: Nelze stahnout creative pro ad {ad_id}: {e}", file=sys.stderr)
    return results


def get_video_source_url(video_id):
    """Ziska URL ke stazeni videa (expiruje za 1-6h!)."""
    try:
        data = meta_fetch(video_id, {"fields": "source,length,picture,description"})
        return {
            "source": data.get("source"),
            "length": data.get("length"),
            "picture": data.get("picture"),
            "description": data.get("description"),
        }
    except Exception as e:
        print(f"  WARN: Nelze ziskat video source pro {video_id}: {e}", file=sys.stderr)
        return None


def get_video_thumbnails(video_id, max_thumbs=10):
    """Stahne thumbnaily (framy) z videa pres Meta /thumbnails endpoint.
    Meta generuje ~20 thumbnails z ruznych casti videa v plnem rozliseni.
    Pouzijeme jako nahradu za ffmpeg frame extraction pokud video source neni dostupne."""
    try:
        data = meta_fetch(f"{video_id}/thumbnails", {})
        thumbs = data.get("data", [])
        if not thumbs:
            return []
        # Select evenly spaced thumbnails: first, ~25%, ~50%, ~75%, last
        total = len(thumbs)
        if total <= max_thumbs:
            indices = list(range(total))
        else:
            step = total / max_thumbs
            indices = [min(int(i * step), total - 1) for i in range(max_thumbs)]
            # Always include first and last
            if 0 not in indices:
                indices[0] = 0
            if total - 1 not in indices:
                indices[-1] = total - 1
        selected = []
        for idx in indices:
            t = thumbs[idx]
            selected.append({
                "uri": t.get("uri"),
                "width": t.get("width"),
                "height": t.get("height"),
                "index": idx,
                "total": total,
                "is_preferred": t.get("is_preferred", False),
            })
        return selected
    except Exception as e:
        print(f"  WARN: Nelze ziskat video thumbnails pro {video_id}: {e}", file=sys.stderr)
        return []


# ── Asset download ──

def download_file(url, dest_path):
    """Stahne soubor z URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    return dest_path


# ── FFmpeg frame extraction ──

def get_video_duration(video_path):
    """Vraci delku videa v sekundach."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(video_path)],
            capture_output=True, text=True, timeout=30
        )
        # Parse Duration from stderr
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if match:
            h, m, s, ms = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100
    except Exception:
        pass
    return 30  # default


def extract_frames(video_path, output_dir, timestamps=None):
    """Extrahuje framy z videa ve specifikovanych casech."""
    duration = get_video_duration(video_path)

    if timestamps is None:
        mid = duration / 2
        end = max(duration - 1, 0)
        timestamps = [0, 1, 3, mid, end]

    frames = []
    for i, ts in enumerate(timestamps):
        if ts > duration:
            continue
        frame_path = Path(output_dir) / f"frame_{i:02d}_{ts:.1f}s.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-ss", str(ts), "-i", str(video_path),
                "-frames:v", "1", "-vf", "scale=1024:-1",
                "-q:v", "2", "-y", str(frame_path)
            ], capture_output=True, timeout=30)
            if frame_path.exists() and frame_path.stat().st_size > 0:
                frames.append({"path": str(frame_path), "timestamp": ts})
        except Exception as e:
            print(f"  WARN: Frame extraction failed at {ts}s: {e}", file=sys.stderr)

    return frames


# ── Whisper transcription ──

def transcribe_audio_ffmpeg(video_path, output_dir, model_path):
    """Transkribuje audio z videa pres ffmpeg whisper filter.
    Pouziva escapovany Windows path pro model (C\\:/whisper/model.bin)."""
    transcript_path = Path(output_dir) / "transcript.txt"

    # Escape colon in Windows drive letter for ffmpeg filter syntax
    escaped_model = model_path.replace("C:", "C\\:")

    try:
        result = subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-af", f"whisper=model='{escaped_model}':language=cs:format=text:destination='{escaped_model.replace('model.bin', 'transcript.txt')}':use_gpu=false",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=300)

        # Check destination file
        dest_transcript = Path(model_path).parent / "transcript.txt"
        if dest_transcript.exists():
            text = dest_transcript.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                transcript_path.write_text(text, encoding="utf-8")
                # Cleanup temp
                dest_transcript.unlink(missing_ok=True)
                return text

        # Fallback: parse from stderr
        lines = []
        for line in (result.stderr or "").split("\n"):
            if "whisper" in line.lower() and "]" in line:
                text_part = line.split("]", 1)[-1].strip()
                if text_part and not text_part.startswith("[") and not text_part.startswith("run "):
                    lines.append(text_part)
        if lines:
            transcript = " ".join(lines)
            transcript_path.write_text(transcript, encoding="utf-8")
            return transcript

    except subprocess.TimeoutExpired:
        print("  WARN: Whisper timed out (>5 min)", file=sys.stderr)
    except Exception as e:
        print(f"  WARN: Whisper selhal: {e}", file=sys.stderr)
    return None


# ── Helpers ──

def encode_image_b64(path):
    """Nacte obrazek a zakoduje jako base64."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ── Analysis prompts ──

HOOK_ANALYSIS_PROMPT = """Analyzuj prvni 3 sekundy teto video reklamy na cesky e-commerce s jidlem a omackami (Fermato.cz).
Frame 1 = 0 sekund, Frame 2 = 1 sekunda, Frame 3 = 3 sekundy.

Odpovez POUZE v JSON formatu:
{
  "hook_type": "problem|curiosity|testimonial|product_reveal|shock|question|comparison|ugc_authentic|founder_story",
  "hook_description": "kratky popis co se deje v prvnich 3s",
  "attention_elements": ["person_face", "text_overlay", "motion", "color_contrast", "food_closeup", "product_pack", "emotion"],
  "text_overlays": ["extrahovany text z framu"],
  "food_appeal_score": 7,
  "production_quality": "professional|semi_pro|ugc|raw",
  "dominant_colors": ["#hex1", "#hex2"],
  "person_present": true,
  "hook_effectiveness": "strong|medium|weak",
  "why_effective_or_not": "kratke vysvetleni proc hook funguje nebo ne",
  "improvement_suggestions": ["konkretni navrh 1", "konkretni navrh 2"]
}"""

FULL_ANALYSIS_PROMPT_TEMPLATE = """Analyzuj celou video reklamu pro cesky food e-commerce (Fermato.cz — omacky, fermentovane produkty, olivovy olej).
Framy jsou v poradi: zacatek, 1s, 3s, stred, konec.
{transcript_section}
{performance_section}

Odpovez POUZE v JSON formatu:
{{
  "narrative_structure": "problem_solution|testimonial|product_demo|lifestyle|comparison|recipe|unboxing|listicle",
  "cta_present": true,
  "cta_text": "text CTA pokud je viditelne",
  "cta_type": "text_overlay|verbal|button|none",
  "product_visibility_score": 8,
  "brand_consistency_score": 7,
  "emotional_tone": "urgency|humor|trust|aspiration|educational|shock|warmth",
  "target_audience": "popis cilove skupiny",
  "strengths": ["co kreativa dela dobre"],
  "weaknesses": ["co nefunguje"],
  "creative_brief_for_iteration": "Konkretni brief pro dalsi verzi: co zachovat, co zmenit, jaky novy hook zkusit. Bud specificky — ne 'zlepsit hook' ale 'zacni produktem v ruce misto logo animace'."
}}"""

IMAGE_ANALYSIS_PROMPT = """Analyzuj tento STATICKY BANNER (obrazek, ne video) pro cesky food e-commerce Fermato.cz — omacky, fermentovane produkty, olivovy olej.

DULEZITE: Toto je staticka reklama (banner/obrazek). NEHODNOTIT hook rate, hold rate, ani nic co se tyka videa. Hodnotit vizual, text, kompozici, CTA.

Odpovez POUZE v JSON formatu:
{
  "ad_type": "product_shot|lifestyle|comparison|testimonial|promo_offer|carousel_card|text_based",
  "text_overlays": ["presne extrahovany text z obrazku"],
  "headline": "hlavni text/nadpis pokud existuje",
  "food_appeal_score": 7,
  "production_quality": "professional|semi_pro|ugc|template",
  "dominant_colors": ["#hex1", "#hex2", "#hex3"],
  "cta_present": true,
  "cta_text": "presny text CTA tlacitka/odkazu",
  "cta_effectiveness": "silne|stredni|slabe|chybi",
  "cta_effectiveness_why": "proc je CTA silne/slabe — velikost, kontrast, umisteni",
  "text_hierarchy_clear": true,
  "text_hierarchy_note": "je jasna hierarchie nadpis > benefit > CTA? Co zlepsit?",
  "product_visible": true,
  "product_description": "co presne je na obrazku viditelne",
  "brand_consistency_score": 7,
  "visual_composition": "popis kompozice — co priahuje oko jako prvni, layout",
  "strengths": ["konkretni silne stranky tohoto banneru"],
  "weaknesses": ["konkretni slabiny"],
  "improvement_suggestions": ["KONKRETNI navrh co zmenit — ne obecne 'zlepsit CTA' ale 'zvetsit CTA tlacitko na 2x, zmenit barvu na cervenou, pridat sipku'"],
  "ab_test_idea": "konkretni navrh A/B testu — co zmenit v dalsi variante a proc"
}"""


# ── Creative analysis pipeline ──

def analyze_video(ad_id, creative_info, performance, work_dir):
    """Kompletni analyza video kreativy.
    Strategie: 1) zkusi stahnout video a extrahovat framy + whisper,
    2) fallback na Meta /thumbnails endpoint (20+ framu z videa v plnem rozliseni),
    3) posledni moznost: single thumbnail z creative objektu."""
    video_id = creative_info["video_id"]
    total_cost = 0.0
    frames = []
    transcript = None
    source_method = "unknown"

    # === Strategy 1: Download video via yt-dlp (Facebook permalink) ===
    print(f"  Stahuji video {video_id}...", file=sys.stderr)
    video_data = get_video_source_url(video_id)
    video_path = Path(work_dir) / f"{ad_id}.mp4"

    # Try yt-dlp with Facebook permalink
    permalink = None
    try:
        pdata = meta_fetch(video_id, {"fields": "permalink_url"})
        permalink = pdata.get("permalink_url")
    except Exception:
        pass

    if permalink:
        fb_url = f"https://www.facebook.com{permalink}"
        try:
            result = subprocess.run(
                ["yt-dlp", fb_url, "-o", str(video_path), "--no-check-certificates", "--quiet", "--no-warnings"],
                capture_output=True, timeout=120
            )
            if video_path.exists() and video_path.stat().st_size > 0:
                print(f"  Video stazeno pres yt-dlp ({video_path.stat().st_size // 1024} KB)", file=sys.stderr)
                frames = extract_frames(video_path, work_dir)
                source_method = "yt_dlp"

                # Transcribe audio with ffmpeg whisper
                whisper_model_path = WHISPER_MODEL_SHORT if Path(WHISPER_MODEL_SHORT).exists() else None
                if not whisper_model_path and WHISPER_MODEL.exists():
                    whisper_model_path = str(WHISPER_MODEL)
                if whisper_model_path:
                    print(f"  Transkribuji audio (whisper)...", file=sys.stderr)
                    transcript = transcribe_audio_ffmpeg(video_path, work_dir, whisper_model_path)
        except subprocess.TimeoutExpired:
            print(f"  WARN: yt-dlp timeout", file=sys.stderr)
        except Exception as e:
            print(f"  WARN: yt-dlp selhal: {e}", file=sys.stderr)

    # Fallback: try Meta API source URL
    if not frames and video_data and video_data.get("source"):
        try:
            download_file(video_data["source"], str(video_path))
            frames = extract_frames(video_path, work_dir)
            source_method = "meta_api"
        except Exception as e:
            print(f"  WARN: Meta API video download selhal: {e}", file=sys.stderr)

    # === Strategy 2: Meta /thumbnails endpoint (multiple frames) ===
    if not frames:
        print(f"  Video source nedostupne — stahuji thumbnaily z Meta API...", file=sys.stderr)
        thumbs = get_video_thumbnails(video_id, max_thumbs=5)
        if thumbs:
            for i, t in enumerate(thumbs):
                thumb_path = Path(work_dir) / f"thumb_{i:02d}.jpg"
                try:
                    download_file(t["uri"], str(thumb_path))
                    if thumb_path.exists() and thumb_path.stat().st_size > 0:
                        # Approximate timestamp based on position in video
                        video_length = video_data.get("length", 30) if video_data else 30
                        approx_time = (t["index"] / max(t["total"] - 1, 1)) * float(video_length)
                        frames.append({"path": str(thumb_path), "timestamp": round(approx_time, 1)})
                except Exception as e:
                    pass
            if frames:
                source_method = "meta_thumbnails"
                print(f"  Stazeno {len(frames)} thumbnails (framu) z Meta API", file=sys.stderr)

    # === Strategy 3: Single thumbnail fallback ===
    if not frames:
        thumbnail_url = creative_info.get("thumbnail_url")
        if thumbnail_url:
            print(f"  Pouzivam single thumbnail...", file=sys.stderr)
            thumb_path = Path(work_dir) / f"{ad_id}_thumb.jpg"
            try:
                download_file(thumbnail_url, str(thumb_path))
                if thumb_path.exists() and thumb_path.stat().st_size > 0:
                    frames = [{"path": str(thumb_path), "timestamp": 0}]
                    source_method = "single_thumbnail"
            except Exception:
                pass

    if not frames:
        print(f"  WARN: Zadne framy k analyze", file=sys.stderr)
        return None, 0

    # === Claude Vision: Hook analysis ===
    # Use first ~30% of frames for hook (beginning of video)
    hook_count = max(1, len(frames) // 3)
    hook_frames = frames[:hook_count]
    print(f"  Claude Vision: hook analyza ({len(hook_frames)} framu, source: {source_method})...", file=sys.stderr)

    hook_images = [encode_image_b64(f["path"]) for f in hook_frames]
    hook_analysis = None

    prompt = HOOK_ANALYSIS_PROMPT
    if source_method == "meta_thumbnails":
        prompt = prompt.replace(
            "Frame 1 = 0 sekund, Frame 2 = 1 sekunda, Frame 3 = 3 sekundy.",
            f"Toto je {len(hook_images)} framu z prvni casti videa (extrahovanch z Meta API)."
        )
    elif source_method == "single_thumbnail":
        prompt = prompt.replace(
            "Frame 1 = 0 sekund, Frame 2 = 1 sekunda, Frame 3 = 3 sekundy.",
            "Toto je thumbnail videa. Analyzuj co ukazuje jako prvni dojem."
        )

    try:
        hook_text, cost = call_claude_vision(hook_images, prompt, max_tokens=1500)
        total_cost += cost
        hook_analysis = parse_json_from_response(hook_text)
    except Exception as e:
        print(f"  WARN: Hook analyza selhala: {e}", file=sys.stderr)

    # === Claude Vision: Full analysis ===
    print(f"  Claude Vision: plna analyza ({len(frames)} framu)...", file=sys.stderr)
    all_images = [encode_image_b64(f["path"]) for f in frames[:5]]

    transcript_section = ""
    if transcript:
        transcript_section = f"Audio transkript: \"{transcript}\""

    perf_section = ""
    if performance:
        perf_section = f"Performance data: Hook rate {performance.get('hook_rate', '?')}%, Hold rate {performance.get('hold_rate', '?')}%, ROAS {performance.get('roas', '?')}, CPA {performance.get('cpa', '?')} CZK"

    full_prompt = FULL_ANALYSIS_PROMPT_TEMPLATE.format(
        transcript_section=transcript_section,
        performance_section=perf_section,
    )

    if source_method == "meta_thumbnails":
        full_prompt = full_prompt.replace(
            "Framy jsou v poradi: zacatek, 1s, 3s, stred, konec.",
            f"Toto je {len(all_images)} framu z ruznych casti videa (rovnomerne rozlozene)."
        )
    elif source_method == "single_thumbnail":
        full_prompt = full_prompt.replace(
            "Framy jsou v poradi: zacatek, 1s, 3s, stred, konec.",
            "Toto je thumbnail videa. Analyzuj na zaklade tohoto nahledu a performance dat."
        )

    full_analysis = None
    try:
        full_text, cost = call_claude_vision(all_images, full_prompt, max_tokens=2000)
        total_cost += cost
        full_analysis = parse_json_from_response(full_text)
    except Exception as e:
        print(f"  WARN: Plna analyza selhala: {e}", file=sys.stderr)

    result = {
        "hook_analysis": hook_analysis,
        "full_analysis": full_analysis,
        "transcript": transcript,
        "video_length": video_data.get("length") if video_data else None,
        "frames_extracted": len(frames),
        "source": source_method,
    }

    return result, total_cost


def analyze_image(ad_id, creative_info, performance, work_dir):
    """Analyza staticke kreativy."""
    image_url = creative_info.get("image_url") or creative_info.get("thumbnail_url")
    if not image_url:
        return None, 0

    total_cost = 0.0

    # Download image
    print(f"  Stahuji obrazek...", file=sys.stderr)
    image_path = Path(work_dir) / f"{ad_id}.jpg"
    try:
        download_file(image_url, str(image_path))
    except Exception as e:
        print(f"  WARN: Download obrazku selhal: {e}", file=sys.stderr)
        return None, 0

    # Analyze with Claude Vision
    print(f"  Claude Vision: analyza obrazku...", file=sys.stderr)
    image_b64 = encode_image_b64(str(image_path))

    try:
        text, cost = call_claude_vision([image_b64], IMAGE_ANALYSIS_PROMPT, max_tokens=1500)
        total_cost += cost
        analysis = parse_json_from_response(text)
    except Exception as e:
        print(f"  WARN: Image analyza selhala: {e}", file=sys.stderr)
        return None, 0

    return {"full_analysis": analysis, "hook_analysis": None, "transcript": None}, total_cost


# ── Priority queue ──

def should_analyze(conn, ad_id, current_recommendation):
    """Rozhodne zda analyzovat kreativu."""
    last = get_last_analysis(conn, ad_id)
    if not last:
        return True, "new"

    # Re-analyze if recommendation changed
    if last["recommendation"] != current_recommendation:
        return True, "recommendation_changed"

    # Re-analyze if older than REANALYSIS_DAYS
    analyzed_at = datetime.fromisoformat(last["analyzed_at"])
    if datetime.now() - analyzed_at > timedelta(days=REANALYSIS_DAYS):
        return True, "periodic_refresh"

    return False, "already_analyzed"


def build_analysis_queue(ads_metrics, conn):
    """Sestavi prioritni frontu kreativ k analyze."""
    queue = []
    priority_map = {"KILL": 3, "ITERATE": 2, "SCALE": 1, "WATCH": 0, "OK": 0, "INFO": -1}

    for m in ads_metrics:
        recs = []
        # Import evaluate from creative_intelligence
        sys.path.insert(0, str(SCRIPT_DIR))
        import creative_intelligence as ci
        recs = ci.evaluate_creative(m)

        top_action = max(recs, key=lambda r: priority_map.get(r[0], 0))[0] if recs else "OK"
        needs, reason = should_analyze(conn, m["ad_id"], top_action)

        if needs:
            priority = priority_map.get(top_action, 0)
            # Boost priority for high-spend ads
            if m["spend"] > 10000:
                priority += 2
            elif m["spend"] > 5000:
                priority += 1

            queue.append({
                "ad_id": m["ad_id"],
                "ad_name": m["ad_name"],
                "priority": priority,
                "reason": reason,
                "recommendation": top_action,
                "spend": m["spend"],
                "roas": m["roas"],
                "hook_rate": m["hook_rate"],
                "hold_rate": m["hold_rate"],
                "is_video": m["is_video"],
                "performance": {
                    "spend": m["spend"],
                    "roas": m["roas"],
                    "cpa": m["cpa"],
                    "hook_rate": m["hook_rate"],
                    "hold_rate": m["hold_rate"],
                    "completion_rate": m["completion_rate"],
                    "ctr": m["ctr"],
                    "frequency": m["frequency"],
                },
            })

    # Sort by priority (highest first), then by spend
    queue.sort(key=lambda x: (x["priority"], x["spend"]), reverse=True)
    return queue


# ── Main entry points ──

def run_daily_analysis(ads_metrics, max_creatives=DEFAULT_MAX_CREATIVES):
    """Spusti denni AI analyzu — volano z creative_daily_runner.py."""
    if not ANTHROPIC_API_KEY:
        print("WARN: ANTHROPIC_API_KEY neni nastaven", file=sys.stderr)
        return 0

    conn = get_db()
    queue = build_analysis_queue(ads_metrics, conn)
    queue = queue[:max_creatives]

    if not queue:
        print("  Zadne kreativy k analyze", file=sys.stderr)
        return 0

    print(f"  Fronta: {len(queue)} kreativ k analyze", file=sys.stderr)

    # Fetch creative metadata for all ads in queue
    ad_ids = [item["ad_id"] for item in queue]
    creatives = fetch_creative_assets(ad_ids)

    analyzed = 0
    total_cost = 0.0

    for item in queue:
        ad_id = item["ad_id"]
        creative = creatives.get(ad_id)
        if not creative:
            continue

        print(f"\n  [{analyzed+1}/{len(queue)}] {item['ad_name'][:40]} (priority {item['priority']}, {item['reason']})", file=sys.stderr)

        # Create temp work directory
        work_dir = ASSETS_DIR / ad_id
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            is_video = creative.get("video_id") is not None

            if is_video:
                result, cost = analyze_video(ad_id, creative, item["performance"], str(work_dir))
            else:
                result, cost = analyze_image(ad_id, creative, item["performance"], str(work_dir))

            if result:
                save_analysis(
                    conn,
                    ad_id=ad_id,
                    creative_id=creative.get("creative_id"),
                    video_id=creative.get("video_id"),
                    creative_type="video" if is_video else "image",
                    hook_analysis=result.get("hook_analysis"),
                    full_analysis=result.get("full_analysis"),
                    transcript=result.get("transcript"),
                    performance=item["performance"],
                    recommendation=item["recommendation"],
                    cost=cost,
                )
                total_cost += cost
                analyzed += 1
                print(f"  OK — cost: ${cost:.4f}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
        finally:
            # Cleanup temp files
            try:
                shutil.rmtree(str(work_dir), ignore_errors=True)
            except Exception:
                pass

    print(f"\n  Analyzovano: {analyzed} kreativ | Celkova cena: ${total_cost:.4f}", file=sys.stderr)
    conn.close()
    return analyzed


def show_queue(ads_metrics):
    """Zobrazi frontu kreativ k analyze."""
    conn = get_db()
    queue = build_analysis_queue(ads_metrics, conn)
    conn.close()

    print(f"Fronta k analyze: {len(queue)} kreativ\n")
    print(f"{'#':>3} {'Priorita':>8} {'Duvod':<22} {'Akce':<8} {'Spend':>8} {'ROAS':>6} {'Hook':>6} {'Ad Name'}")
    print(f"{'':>3} {'':>8} {'':>22} {'':>8} {'':>8} {'':>6} {'':>6} {'-'*40}")

    for i, item in enumerate(queue[:30], 1):
        roas = f"{item['roas']:.2f}" if item['roas'] else "—"
        hook = f"{item['hook_rate']}%" if item['hook_rate'] else "—"
        vid = "V" if item["is_video"] else "I"
        print(f"{i:>3} {item['priority']:>8} {item['reason']:<22} {item['recommendation']:<8} {item['spend']:>7.0f} {roas:>6} {hook:>6} [{vid}] {item['ad_name'][:40]}")


def show_report():
    """Zobrazi posledni analyzy."""
    conn = get_db()
    rows = conn.execute("""
        SELECT ad_id, creative_type, recommendation, analyzed_at, cost_usd,
               hook_analysis, full_analysis, transcript
        FROM creative_analyses
        ORDER BY analyzed_at DESC LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        print("Zadne analyzy v databazi.")
        return

    print(f"Poslednich {len(rows)} analyz:\n")
    for row in rows:
        row = dict(row)
        print(f"{'='*60}")
        print(f"Ad ID: {row['ad_id']} | Type: {row['creative_type']} | {row['recommendation']}")
        print(f"Analyzed: {row['analyzed_at']} | Cost: ${row['cost_usd']:.4f}")

        if row["hook_analysis"]:
            hook = json.loads(row["hook_analysis"])
            if not hook.get("_parse_error"):
                print(f"\nHook: {hook.get('hook_type', '?')} — {hook.get('hook_effectiveness', '?')}")
                print(f"  {hook.get('hook_description', '')}")
                if hook.get("improvement_suggestions"):
                    for s in hook["improvement_suggestions"]:
                        print(f"  -> {s}")

        if row["full_analysis"]:
            full = json.loads(row["full_analysis"])
            if not full.get("_parse_error"):
                brief = full.get("creative_brief_for_iteration", "")
                if brief:
                    print(f"\nBrief: {brief}")
                strengths = full.get("strengths", [])
                weaknesses = full.get("weaknesses", [])
                if strengths:
                    print(f"Strengths: {', '.join(strengths)}")
                if weaknesses:
                    print(f"Weaknesses: {', '.join(weaknesses)}")

        if row["transcript"]:
            print(f"\nTranscript: {row['transcript'][:200]}...")
        print()


# ── CLI ──

def main():
    if not ACCESS_TOKEN:
        print("CHYBA: META_ADS_ACCESS_TOKEN neni nastaven", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]

    if "--report" in args:
        show_report()
        return

    # For queue and analysis, we need ad metrics
    sys.path.insert(0, str(SCRIPT_DIR))
    import creative_intelligence as ci

    days = 14
    for i, arg in enumerate(args):
        if arg == "--days" and i + 1 < len(args):
            days = int(args[i + 1])

    if "--list-queue" in args:
        print(f"Stahuji data za {days} dni...", file=sys.stderr)
        raw_data = ci.fetch_ad_insights(days)
        ads_metrics = [ci.calculate_metrics(row) for row in raw_data]
        show_queue(ads_metrics)
        return

    if "--ad-id" in args:
        idx = args.index("--ad-id")
        if idx + 1 < len(args):
            ad_id = args[idx + 1]
            if not ANTHROPIC_API_KEY:
                print("CHYBA: ANTHROPIC_API_KEY neni nastaven", file=sys.stderr)
                sys.exit(1)
            # Analyze single ad
            print(f"Stahuji data...", file=sys.stderr)
            raw_data = ci.fetch_ad_insights(days)
            ads_metrics = [ci.calculate_metrics(row) for row in raw_data]
            # Find the ad
            ad_metric = None
            for m in ads_metrics:
                if m["ad_id"] == ad_id:
                    ad_metric = m
                    break
            if not ad_metric:
                print(f"Ad {ad_id} nenalezen v poslednich {days} dnech", file=sys.stderr)
                sys.exit(1)
            # Run analysis
            analyzed = run_daily_analysis([ad_metric], max_creatives=1)
            if analyzed:
                show_report()
            return

    # Default: run full daily analysis
    if not ANTHROPIC_API_KEY:
        print("CHYBA: ANTHROPIC_API_KEY neni nastaven", file=sys.stderr)
        sys.exit(1)

    max_c = DEFAULT_MAX_CREATIVES
    for i, arg in enumerate(args):
        if arg == "--max" and i + 1 < len(args):
            max_c = int(args[i + 1])

    print(f"Stahuji data za {days} dni...", file=sys.stderr)
    raw_data = ci.fetch_ad_insights(days)
    ads_metrics = [ci.calculate_metrics(row) for row in raw_data]
    run_daily_analysis(ads_metrics, max_creatives=max_c)


if __name__ == "__main__":
    main()
