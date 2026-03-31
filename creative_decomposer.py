#!/usr/bin/env python3
"""
Fermato Creative Decomposer — Scene-level video analysis
=========================================================
Rozklada video kreativy na modulární komponenty (Hook/Body/CTA),
analyzuje kazdy segment pres Claude Vision a buduje komponentni knihovnu.

Pouziti:
    python creative_decomposer.py                          # decompose top 10 videi
    python creative_decomposer.py --ad-id 12023...         # konkretni ad
    python creative_decomposer.py --library                # vypis komponentni knihovnu
    python creative_decomposer.py --recommend              # doporuc nove kombinace
    python creative_decomposer.py --recommend --top 5      # top 5 doporuceni

Vyzaduje:
    - META_ADS_ACCESS_TOKEN (v env)
    - ANTHROPIC_API_KEY (v env)
    - ffmpeg (v PATH)
"""

import base64
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ──

ACCESS_TOKEN = os.environ.get("META_ADS_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_VERSION = "v23.0"
META_API_BASE = f"https://graph.facebook.com/{API_VERSION}"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "component_library.db"
ASSETS_DIR = DATA_DIR / "components"

# Segment boundaries (seconds)
HOOK_END = 3.0       # Hook = 0-3s
CTA_DURATION = 5.0   # CTA = last 5s

# ── Database ──

def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id TEXT NOT NULL,
            ad_name TEXT,
            campaign_name TEXT,
            component_type TEXT NOT NULL,  -- 'hook', 'body', 'cta'
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            duration_sec REAL NOT NULL,

            -- AI analysis
            analysis TEXT,          -- JSON: Claude Vision structured output
            transcript TEXT,        -- Whisper ASR for this segment
            thumbnail_path TEXT,    -- representative frame

            -- Performance (from parent ad)
            hook_rate REAL,
            hold_rate REAL,
            completion_rate REAL,
            ctr REAL,
            cvr REAL,
            roas REAL,
            cpa REAL,
            spend REAL,
            purchases INTEGER,
            confidence REAL,

            -- Metadata
            created_at TEXT NOT NULL,
            video_duration REAL,
            scene_count INTEGER      -- number of scenes in this segment
        );
        CREATE INDEX IF NOT EXISTS idx_comp_type ON components(component_type);
        CREATE INDEX IF NOT EXISTS idx_comp_ad ON components(ad_id);
        CREATE INDEX IF NOT EXISTS idx_comp_hook_rate ON components(hook_rate);
        CREATE INDEX IF NOT EXISTS idx_comp_roas ON components(roas);

        CREATE TABLE IF NOT EXISTS combinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hook_id INTEGER REFERENCES components(id),
            body_id INTEGER REFERENCES components(id),
            cta_id INTEGER REFERENCES components(id),
            expected_score REAL,
            reason TEXT,
            status TEXT DEFAULT 'suggested',  -- suggested, tested, rejected
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Meta API helpers (reuse from creative_vision.py) ──

def meta_fetch(endpoint, params=None):
    if params is None:
        params = {}
    params["access_token"] = ACCESS_TOKEN
    url = f"{META_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def get_video_source_url(video_id):
    try:
        data = meta_fetch(video_id, {"fields": "source,length,picture,description"})
        return data.get("source"), float(data.get("length", 30))
    except Exception as e:
        print(f"  WARN: Cannot get video source for {video_id}: {e}", file=sys.stderr)
        return None, 30


def get_video_thumbnails(video_id, max_thumbs=15):
    """Fetch thumbnails from Meta /thumbnails endpoint as fallback for video download.
    Meta generates ~20 thumbnails from different parts of the video in full resolution."""
    try:
        data = meta_fetch(f"{video_id}/thumbnails", {})
        thumbs = data.get("data", [])
        if not thumbs:
            return []
        total = len(thumbs)
        if total <= max_thumbs:
            indices = list(range(total))
        else:
            step = total / max_thumbs
            indices = [min(int(i * step), total - 1) for i in range(max_thumbs)]
            if 0 not in indices:
                indices[0] = 0
            if total - 1 not in indices:
                indices[-1] = total - 1
        return [{"uri": thumbs[i].get("uri"), "index": i, "total": total} for i in indices]
    except Exception as e:
        print(f"  WARN: Cannot get thumbnails for {video_id}: {e}", file=sys.stderr)
        return []


def download_thumbnail(uri, dest_path):
    """Download a single thumbnail image."""
    try:
        req = urllib.request.Request(uri, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(dest_path, "wb") as f:
                f.write(resp.read())
        return dest_path if os.path.getsize(dest_path) > 500 else None
    except Exception:
        return None


def decompose_from_thumbnails(ad_id, video_id, video_length, performance_data=None):
    """Fallback: decompose using Meta thumbnails when video download unavailable.
    Splits thumbnails into hook/body/cta segments based on position."""
    thumbs = get_video_thumbnails(video_id, max_thumbs=15)
    if not thumbs:
        return None, 0, video_length

    total = thumbs[0]["total"] if thumbs else len(thumbs)
    n = len(thumbs)

    # Map thumbnail indices to video timeline
    # First ~20% = hook, last ~20% = CTA, middle = body
    hook_end_idx = max(1, int(n * 0.2))
    cta_start_idx = max(hook_end_idx + 1, int(n * 0.8))

    segments = {
        "hook": thumbs[:hook_end_idx],
        "body": thumbs[hook_end_idx:cta_start_idx],
        "cta": thumbs[cta_start_idx:],
    }

    prompts = {"hook": HOOK_PROMPT, "body": BODY_PROMPT, "cta": CTA_PROMPT}
    results = {}
    total_cost = 0

    for seg_type, seg_thumbs in segments.items():
        if not seg_thumbs:
            continue

        # Calculate approximate time range
        first_pct = seg_thumbs[0]["index"] / max(total, 1)
        last_pct = seg_thumbs[-1]["index"] / max(total, 1)
        start_sec = first_pct * video_length
        end_sec = last_pct * video_length

        print(f"    {seg_type.upper()} ({start_sec:.1f}s - {end_sec:.1f}s, {len(seg_thumbs)} thumbs)", file=sys.stderr)

        # Download thumbnails
        frames_b64 = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for j, t in enumerate(seg_thumbs):
                if not t.get("uri"):
                    continue
                dest = os.path.join(tmpdir, f"thumb_{j}.jpg")
                if download_thumbnail(t["uri"], dest):
                    with open(dest, "rb") as f:
                        frames_b64.append(base64.b64encode(f.read()).decode())

        if not frames_b64:
            continue

        # Analyze with Claude
        try:
            raw_text, cost = call_claude(frames_b64, prompts[seg_type])
            total_cost += cost
            json_match = re.search(r"\{[\s\S]*\}", raw_text)
            analysis = json.loads(json_match.group()) if json_match else {"raw": raw_text}
        except Exception as e:
            print(f"      WARN: Claude analysis failed: {e}", file=sys.stderr)
            analysis = {"error": str(e)}

        # Save representative thumbnail
        thumb_path = None
        if seg_thumbs and seg_thumbs[0].get("uri"):
            thumb_dir = ASSETS_DIR / ad_id
            thumb_dir.mkdir(parents=True, exist_ok=True)
            thumb_dest = str(thumb_dir / f"{seg_type}_thumb.jpg")
            if download_thumbnail(seg_thumbs[0]["uri"], thumb_dest):
                thumb_path = thumb_dest

        results[seg_type] = {
            "start": round(start_sec, 1),
            "end": round(end_sec, 1),
            "duration": round(end_sec - start_sec, 1),
            "analysis": analysis,
            "scene_count": len(seg_thumbs),
            "thumbnail": thumb_path,
        }

    return results, total_cost, video_length


# ── FFmpeg utilities ──

def get_video_duration(video_path):
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(video_path)],
            capture_output=True, text=True, timeout=30
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if match:
            h, m, s, ms = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100
    except Exception:
        pass
    return 30


def extract_segment_frames(video_path, start_sec, end_sec, count=4):
    """Extract evenly-spaced frames from a video segment."""
    duration = end_sec - start_sec
    if duration <= 0:
        return []

    if count == 1:
        timestamps = [start_sec + duration / 2]
    else:
        step = duration / (count - 1) if count > 1 else 0
        timestamps = [start_sec + i * step for i in range(count)]

    frames = []
    for i, ts in enumerate(timestamps):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            frame_path = tmp.name
        try:
            subprocess.run([
                "ffmpeg", "-ss", f"{ts:.2f}", "-i", str(video_path),
                "-frames:v", "1", "-vf", "scale=768:-1",
                "-q:v", "2", "-y", frame_path
            ], capture_output=True, timeout=30)
            if os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
                frames.append({"path": frame_path, "timestamp": ts})
            else:
                os.unlink(frame_path)
        except Exception:
            if os.path.exists(frame_path):
                os.unlink(frame_path)
    return frames


def extract_segment_audio(video_path, start_sec, end_sec):
    """Extract audio from a video segment as WAV."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name
    try:
        subprocess.run([
            "ffmpeg", "-ss", f"{start_sec:.2f}", "-t", f"{end_sec - start_sec:.2f}",
            "-i", str(video_path), "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1", "-y", audio_path
        ], capture_output=True, timeout=30)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            return audio_path
    except Exception:
        pass
    if os.path.exists(audio_path):
        os.unlink(audio_path)
    return None


def detect_scenes(video_path, threshold=0.3):
    """Detect scene boundaries using ffmpeg scene filter.
    Returns list of timestamps where scene changes occur."""
    try:
        result = subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=60)

        scenes = [0.0]
        for line in result.stderr.split("\n"):
            match = re.search(r"pts_time:(\d+\.?\d*)", line)
            if match:
                t = float(match.group(1))
                if t > 0.1:
                    scenes.append(t)
        return sorted(set(scenes))
    except Exception:
        return [0.0]


def download_video(url, dest_dir):
    """Download video from URL to temp file."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "video.mp4"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    return str(dest)


# ── Claude Vision API ──

def call_claude(images_b64, prompt, max_tokens=1500, retries=3):
    """Call Claude Vision API with images. Retries on 429/5xx."""
    import time
    content = []
    for img in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img}
        })
    content.append({"type": "text", "text": prompt})

    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}]
    }).encode()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())

            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]

            usage = result.get("usage", {})
            cost = (usage.get("input_tokens", 0) * 3 + usage.get("output_tokens", 0) * 15) / 1_000_000
            return text, cost

        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < retries - 1:
                wait = (attempt + 1) * 8
                print(f"      Rate limited, cekam {wait}s...", file=sys.stderr)
                time.sleep(wait)
            elif e.code >= 500 and attempt < retries - 1:
                time.sleep(5)
            else:
                raise


def frames_to_b64(frame_paths):
    """Convert frame file paths to base64 strings."""
    b64_list = []
    for fp in frame_paths:
        path = fp if isinstance(fp, str) else fp["path"]
        with open(path, "rb") as f:
            b64_list.append(base64.b64encode(f.read()).decode())
    return b64_list


# ── Component Analysis Prompts ──

HOOK_PROMPT = """Analyzuj HOOK (prvni 3 sekundy) teto video reklamy na jidlo/napoje.
Framy jsou v chronologickem poradi z prvnich 3 sekund.

Vrat JSON (zadny jiny text):
{
  "hook_type": "visual_appeal|ugc_reaction|product_demo|humor|problem_statement|testimonial|question|shock_value|before_after|social_proof",
  "opening_element": "co divak vidi v prvni sekunde",
  "text_overlay": "text na obrazovce (nebo null)",
  "has_face": true/false,
  "has_product": true/false,
  "energy_level": "low|medium|high",
  "color_mood": "warm|cool|neutral|vibrant",
  "audio_cue": "music|voice|sfx|silence (odhad z vizualu)",
  "attention_hooks": ["seznam konkretních prvku co zaujmou"],
  "weakness": "co by slo zlepsit",
  "similar_to": "popis jakeho stylu/brandu to pripomina"
}"""

BODY_PROMPT = """Analyzuj BODY (stredni cast) teto video reklamy na jidlo/napoje.
Framy jsou z prostredni casti videa, za hookem a pred CTA.

Vrat JSON (zadny jiny text):
{
  "narrative_arc": "problem_solution|demonstration|storytelling|listicle|comparison|lifestyle|educational",
  "scenes_described": ["popis kazde viditeline sceny"],
  "pacing": "slow|medium|fast",
  "scene_count_estimate": 3,
  "product_visibility": "prominent|background|absent",
  "value_proposition": "hlavni sdeleni/benefit",
  "emotional_tone": "fun|serious|aspirational|relatable|urgent",
  "retention_risk": "kde divak pravdepodobne ztrati zajem a proc",
  "strength": "co drzi divaky",
  "weakness": "co zpusobuje dropout"
}"""

CTA_PROMPT = """Analyzuj CTA (posledni cast, call-to-action) teto video reklamy na jidlo/napoje.
Framy jsou z poslednich sekund videa.

Vrat JSON (zadny jiny text):
{
  "cta_type": "shop_now|learn_more|swipe_up|discount_code|limited_offer|none",
  "cta_text": "presny text CTA (nebo null)",
  "urgency": "none|low|medium|high",
  "offer": "konkretni nabidka (sleva, doprava zdarma, apod.) nebo null",
  "visual_clarity": "clear|cluttered|subtle",
  "brand_visible": true/false,
  "ending_style": "abrupt|smooth_fade|logo_card|product_shot",
  "strength": "co funguje",
  "weakness": "co zlepsit"
}"""


# ── Core decomposition ──

def decompose_and_analyze(ad_id, video_path, performance_data=None):
    """Decompose video into Hook/Body/CTA and analyze each segment."""
    duration = get_video_duration(video_path)
    scenes = detect_scenes(video_path)

    # Define segments
    hook_end = min(HOOK_END, duration)
    cta_start = max(duration - CTA_DURATION, hook_end + 1)
    body_start = hook_end
    body_end = cta_start

    segments = {
        "hook": (0, hook_end),
        "body": (body_start, body_end),
        "cta": (cta_start, duration),
    }

    prompts = {
        "hook": HOOK_PROMPT,
        "body": BODY_PROMPT,
        "cta": CTA_PROMPT,
    }

    frame_counts = {"hook": 6, "body": 5, "cta": 4}
    results = {}
    total_cost = 0

    for seg_type, (start, end) in segments.items():
        if end - start < 0.5:
            continue

        print(f"    {seg_type.upper()} ({start:.1f}s - {end:.1f}s)", file=sys.stderr)

        # Extract frames
        frames = extract_segment_frames(video_path, start, end, count=frame_counts[seg_type])
        if not frames:
            print(f"      WARN: No frames extracted for {seg_type}", file=sys.stderr)
            continue

        # Analyze with Claude Vision
        b64 = frames_to_b64(frames)
        try:
            raw_text, cost = call_claude(b64, prompts[seg_type])
            total_cost += cost

            # Parse JSON from response
            json_match = re.search(r"\{[\s\S]*\}", raw_text)
            analysis = json.loads(json_match.group()) if json_match else {"raw": raw_text}
        except Exception as e:
            print(f"      WARN: Claude analysis failed: {e}", file=sys.stderr)
            analysis = {"error": str(e)}

        # Count scenes in this segment
        seg_scenes = [s for s in scenes if start <= s < end]

        # Save thumbnail (first frame of segment)
        thumb_path = None
        if frames:
            thumb_dir = ASSETS_DIR / ad_id
            thumb_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            thumb_dest = thumb_dir / f"{seg_type}_thumb.jpg"
            shutil.copy2(frames[0]["path"], str(thumb_dest))
            thumb_path = str(thumb_dest)

        results[seg_type] = {
            "start": start,
            "end": end,
            "duration": end - start,
            "analysis": analysis,
            "scene_count": len(seg_scenes),
            "thumbnail": thumb_path,
        }

        # Cleanup temp frames
        for f in frames:
            try:
                os.unlink(f["path"])
            except Exception:
                pass

    return results, total_cost, duration


def save_components(conn, ad_id, ad_name, campaign_name, decomposition, performance, video_duration):
    """Save decomposed components to database."""
    perf = performance or {}
    for comp_type, data in decomposition.items():
        conn.execute("""
            INSERT INTO components
            (ad_id, ad_name, campaign_name, component_type, start_sec, end_sec, duration_sec,
             analysis, thumbnail_path,
             hook_rate, hold_rate, completion_rate, ctr, cvr, roas, cpa, spend, purchases, confidence,
             created_at, video_duration, scene_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ad_id, ad_name, campaign_name, comp_type,
            data["start"], data["end"], data["duration"],
            json.dumps(data["analysis"], ensure_ascii=False),
            data.get("thumbnail"),
            perf.get("hook_rate"), perf.get("hold_rate"), perf.get("completion_rate"),
            perf.get("ctr"), perf.get("cvr"), perf.get("roas"), perf.get("cpa"),
            perf.get("spend"), perf.get("purchases"), perf.get("confidence"),
            datetime.now().isoformat(), video_duration, data.get("scene_count", 0),
        ))
    conn.commit()


# ── Component Library ──

def get_top_components(conn, component_type, metric="hook_rate", limit=10, min_confidence=0.3):
    """Get top components by metric."""
    valid_metrics = {"hook_rate", "hold_rate", "roas", "cvr", "cpa", "spend", "ctr"}
    if metric not in valid_metrics:
        metric = "hook_rate"

    order = "ASC" if metric == "cpa" else "DESC"
    rows = conn.execute(f"""
        SELECT * FROM components
        WHERE component_type = ? AND confidence >= ? AND {metric} IS NOT NULL
        ORDER BY {metric} {order}
        LIMIT ?
    """, (component_type, min_confidence, limit)).fetchall()
    return [dict(r) for r in rows]


def recommend_combinations(conn, top_n=10):
    """Recommend untested hook×body×cta combinations from top performers."""
    # Top hooks by hook_rate
    top_hooks = conn.execute("""
        SELECT id, ad_id, ad_name, hook_rate, roas, analysis
        FROM components WHERE component_type='hook' AND hook_rate IS NOT NULL AND confidence >= 0.3
        ORDER BY hook_rate DESC LIMIT 5
    """).fetchall()

    # Top bodies by hold_rate
    top_bodies = conn.execute("""
        SELECT id, ad_id, ad_name, hold_rate, roas, analysis
        FROM components WHERE component_type='body' AND hold_rate IS NOT NULL AND confidence >= 0.3
        ORDER BY hold_rate DESC LIMIT 5
    """).fetchall()

    # Top CTAs by CVR
    top_ctas = conn.execute("""
        SELECT id, ad_id, ad_name, cvr, roas, analysis
        FROM components WHERE component_type='cta' AND cvr IS NOT NULL AND confidence >= 0.3
        ORDER BY cvr DESC LIMIT 5
    """).fetchall()

    if not top_hooks or not top_bodies or not top_ctas:
        return []

    # Generate combinations (skip same-ad combinations — those already exist)
    existing = conn.execute("SELECT hook_id, body_id, cta_id FROM combinations").fetchall()
    existing_set = {(r["hook_id"], r["body_id"], r["cta_id"]) for r in existing}

    combos = []
    for h in top_hooks:
        for b in top_bodies:
            for c in top_ctas:
                # Skip if all from same ad
                if h["ad_id"] == b["ad_id"] == c["ad_id"]:
                    continue
                # Skip if already suggested
                if (h["id"], b["id"], c["id"]) in existing_set:
                    continue

                # Score: weighted average of component metrics
                h_score = (h["hook_rate"] or 0) / 40  # normalize to ~1.0 for 40% hook rate
                b_score = (b["hold_rate"] or 0) / 50   # normalize to ~1.0 for 50% hold rate
                c_score = (c["cvr"] or 0) / 3           # normalize to ~1.0 for 3% CVR
                score = h_score * 0.35 + b_score * 0.35 + c_score * 0.30

                h_analysis = json.loads(h["analysis"]) if h["analysis"] else {}
                b_analysis = json.loads(b["analysis"]) if b["analysis"] else {}
                c_analysis = json.loads(c["analysis"]) if c["analysis"] else {}

                reason_parts = []
                reason_parts.append(f"Hook: {h['ad_name'][:25]} (rate {h['hook_rate']:.1f}%, {h_analysis.get('hook_type', '?')})")
                reason_parts.append(f"Body: {b['ad_name'][:25]} (hold {b['hold_rate']:.1f}%, {b_analysis.get('narrative_arc', '?')})")
                reason_parts.append(f"CTA: {c['ad_name'][:25]} (CVR {c['cvr']:.2f}%, {c_analysis.get('cta_type', '?')})")

                combos.append({
                    "hook_id": h["id"], "body_id": b["id"], "cta_id": c["id"],
                    "score": round(score, 3),
                    "reason": " | ".join(reason_parts),
                    "hook_ad": h["ad_name"], "body_ad": b["ad_name"], "cta_ad": c["ad_name"],
                    "hook_rate": h["hook_rate"], "hold_rate": b["hold_rate"], "cvr": c["cvr"],
                })

    # Sort by score, return top
    combos.sort(key=lambda x: x["score"], reverse=True)

    # Save top suggestions to DB
    now = datetime.now().isoformat()
    for combo in combos[:top_n]:
        conn.execute("""
            INSERT INTO combinations (hook_id, body_id, cta_id, expected_score, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (combo["hook_id"], combo["body_id"], combo["cta_id"],
              combo["score"], combo["reason"], now))
    conn.commit()

    return combos[:top_n]


def print_library(conn):
    """Print component library summary."""
    print("=" * 70)
    print("  COMPONENT LIBRARY")
    print("=" * 70)

    for comp_type in ["hook", "body", "cta"]:
        rows = conn.execute("""
            SELECT COUNT(*) as cnt,
                   AVG(hook_rate) as avg_hook, AVG(hold_rate) as avg_hold,
                   AVG(roas) as avg_roas, AVG(cvr) as avg_cvr
            FROM components WHERE component_type = ?
        """, (comp_type,)).fetchone()

        print(f"\n  {comp_type.upper()}S: {rows['cnt']} v knihovne")

        if rows['cnt'] > 0:
            metric = {"hook": "hook_rate", "body": "hold_rate", "cta": "cvr"}[comp_type]
            order = "DESC"
            top = get_top_components(conn, comp_type, metric=metric, limit=5)
            if top:
                print(f"  {'Ad Name':<30} {'Hook%':>6} {'Hold%':>6} {'CVR%':>6} {'ROAS':>6} {'Spend':>8}")
                print(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")
                for c in top:
                    analysis = json.loads(c["analysis"]) if c["analysis"] else {}
                    type_tag = analysis.get("hook_type", analysis.get("narrative_arc", analysis.get("cta_type", "?")))
                    hr = f"{c['hook_rate']:.1f}" if c['hook_rate'] else "—"
                    ho = f"{c['hold_rate']:.1f}" if c['hold_rate'] else "—"
                    cv = f"{c['cvr']:.2f}" if c['cvr'] else "—"
                    ro = f"{c['roas']:.2f}" if c['roas'] else "—"
                    sp = f"{c['spend']:.0f}" if c['spend'] else "—"
                    name = f"{c['ad_name'][:22]} [{type_tag[:8]}]"
                    print(f"  {name:<30} {hr:>6} {ho:>6} {cv:>6} {ro:>6} {sp:>8}")


def print_recommendations(combos):
    """Print combination recommendations."""
    print("\n" + "=" * 70)
    print("  DOPORUCENE KOMBINACE (hook × body × cta)")
    print("=" * 70)

    if not combos:
        print("\n  Nedostatek dat — nejdrive spust decompose pro vice kreativ.")
        return

    for i, c in enumerate(combos, 1):
        print(f"\n  #{i} (score: {c['score']:.3f})")
        print(f"    HOOK:  {c['hook_ad'][:35]} — hook rate {c['hook_rate']:.1f}%")
        print(f"    BODY:  {c['body_ad'][:35]} — hold rate {c['hold_rate']:.1f}%")
        print(f"    CTA:   {c['cta_ad'][:35]} — CVR {c['cvr']:.2f}%")
        print(f"    Duvod: {c['reason'][:80]}")


# ── Main pipeline ──

def run_decomposition(ad_ids_with_data, max_ads=10):
    """Run decomposition pipeline for multiple ads."""
    conn = get_db()

    # Skip already decomposed
    existing = {r["ad_id"] for r in conn.execute(
        "SELECT DISTINCT ad_id FROM components"
    ).fetchall()}

    to_process = [(aid, data) for aid, data in ad_ids_with_data if aid not in existing]
    to_process = to_process[:max_ads]

    if not to_process:
        print("Vsechny kreativy uz byly dekomponovany.", file=sys.stderr)
        return

    print(f"Decompose fronta: {len(to_process)} kreativ", file=sys.stderr)
    total_cost = 0

    for i, (ad_id, perf) in enumerate(to_process, 1):
        ad_name = perf.get("ad_name", "?")
        video_id = perf.get("video_id")

        if not video_id:
            # Fetch creative to get video_id
            try:
                ad_data = meta_fetch(ad_id, {
                    "fields": "creative{video_id}"
                })
                video_id = ad_data.get("creative", {}).get("video_id")
            except Exception:
                pass

        if not video_id:
            print(f"  [{i}/{len(to_process)}] {ad_name[:40]} — neni video, skip", file=sys.stderr)
            continue

        print(f"  [{i}/{len(to_process)}] {ad_name[:40]}", file=sys.stderr)

        # Try video download first, fallback to thumbnails
        source_url, api_length = get_video_source_url(video_id)

        if source_url:
            # Full video path: download + ffmpeg decompose
            with tempfile.TemporaryDirectory() as tmpdir:
                try:
                    print(f"    Stahuji video {video_id}...", file=sys.stderr)
                    video_path = download_video(source_url, tmpdir)
                    print(f"    Analyzuji segmenty...", file=sys.stderr)
                    decomposition, cost, duration = decompose_and_analyze(ad_id, video_path, perf)
                    total_cost += cost
                    save_components(conn, ad_id, ad_name,
                                  perf.get("campaign_name", ""),
                                  decomposition, perf, duration)
                    print(f"    OK — {len(decomposition)} segmentu, ${cost:.4f}", file=sys.stderr)
                except Exception as e:
                    print(f"    CHYBA: {e}", file=sys.stderr)
        else:
            # Fallback: use Meta thumbnails
            print(f"    Video URL nedostupna, pouzivam thumbnails...", file=sys.stderr)
            try:
                decomposition, cost, duration = decompose_from_thumbnails(
                    ad_id, video_id, api_length, perf)
                if decomposition:
                    total_cost += cost
                    save_components(conn, ad_id, ad_name,
                                  perf.get("campaign_name", ""),
                                  decomposition, perf, duration)
                    print(f"    OK (thumbs) — {len(decomposition)} segmentu, ${cost:.4f}", file=sys.stderr)
                else:
                    print(f"    WARN: Zadne thumbnaily dostupne", file=sys.stderr)
            except Exception as e:
                print(f"    CHYBA: {e}", file=sys.stderr)

    print(f"\nCelkovy cost: ${total_cost:.4f}", file=sys.stderr)
    conn.close()


# ── CLI ──

def main():
    if not ACCESS_TOKEN:
        print("CHYBA: Nastav META_ADS_ACCESS_TOKEN", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]
    conn = get_db()

    if "--library" in args:
        print_library(conn)
        conn.close()
        return

    if "--recommend" in args:
        top_n = 10
        if "--top" in args:
            idx = args.index("--top")
            if idx + 1 < len(args):
                top_n = int(args[idx + 1])
        combos = recommend_combinations(conn, top_n)
        print_library(conn)
        print_recommendations(combos)
        conn.close()
        return

    # Default: decompose mode
    # Import creative_intelligence for data
    sys.path.insert(0, str(SCRIPT_DIR / "scripts"))
    sys.path.insert(0, str(SCRIPT_DIR))
    import creative_intelligence as ci

    if "--ad-id" in args:
        idx = args.index("--ad-id")
        target_ids = [args[idx + 1]] if idx + 1 < len(args) else []
    else:
        target_ids = None

    max_ads = 10
    if "--max" in args:
        idx = args.index("--max")
        if idx + 1 < len(args):
            max_ads = int(args[idx + 1])

    days = 14
    if "--days" in args:
        idx = args.index("--days")
        if idx + 1 < len(args):
            days = int(args[idx + 1])

    # Fetch ad data
    print(f"Stahuji ad data za {days} dni...", file=sys.stderr)
    raw = ci.fetch_ad_insights(days)
    metrics = [ci.calculate_metrics(row) for row in raw]

    # Filter to video ads with enough data
    video_ads = [m for m in metrics if m["is_video"] and m["spend"] > 200 and m["impressions"] > 1000]
    video_ads.sort(key=lambda x: x["spend"], reverse=True)

    if target_ids:
        video_ads = [m for m in video_ads if m["ad_id"] in target_ids]

    ads_with_data = [(m["ad_id"], m) for m in video_ads]
    run_decomposition(ads_with_data, max_ads=max_ads)

    # After decomposition, show library and recommendations
    conn = get_db()
    print_library(conn)
    combos = recommend_combinations(conn, top_n=5)
    print_recommendations(combos)
    conn.close()


if __name__ == "__main__":
    main()
