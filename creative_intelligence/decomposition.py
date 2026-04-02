"""v3: Scene Decomposition — rozklad videa na hook/body/CTA segmenty.

Kazde video se rozlozi na 3 komponenty:
- HOOK (0-3s): prvni dojem, attention grab
- BODY (3s-Ns): hlavni obsah, story arc
- CTA (posledni 5s): vyzva k akci

Kazda komponenta se analyzuje zvlast pres Claude Vision + Whisper ASR.
"""

import base64
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import (
    HOOK_DURATION, CTA_DURATION, MIN_SCENE_DURATION,
    ASSETS_DIR, WHISPER_MODEL_SHORT,
)
from .meta_client import meta_fetch
from .claude_client import call_claude_vision, parse_json_from_response


# ── Video utilities ──

def get_video_duration(video_path):
    """Get video duration in seconds via ffmpeg."""
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
    return 30  # default


def extract_segment(video_path, output_path, start, end):
    """Extract video segment [start, end] seconds."""
    duration = end - start
    if duration <= 0:
        return None
    try:
        subprocess.run([
            "ffmpeg", "-ss", str(start), "-i", str(video_path),
            "-t", str(duration), "-c", "copy", "-y", str(output_path)
        ], capture_output=True, timeout=60)
        if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
            return output_path
    except Exception as e:
        print(f"  WARN: Segment extraction failed [{start}-{end}]: {e}", file=sys.stderr)
    return None


def extract_frames_at(video_path, timestamps, output_dir):
    """Extract frames at specific timestamps."""
    frames = []
    duration = get_video_duration(video_path)
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
        except Exception:
            pass
    return frames


def detect_scenes(video_path):
    """Detect scene changes using ffmpeg scene filter.
    Returns list of timestamps where scenes change."""
    try:
        result = subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-vf", "select='gt(scene,0.3)',showinfo",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=120)

        scenes = [0.0]
        for line in result.stderr.split("\n"):
            match = re.search(r"pts_time:(\d+\.?\d*)", line)
            if match:
                ts = float(match.group(1))
                if ts - scenes[-1] >= MIN_SCENE_DURATION:
                    scenes.append(ts)
        return scenes
    except Exception as e:
        print(f"  WARN: Scene detection failed: {e}", file=sys.stderr)
        return [0.0]


def transcribe_segment(video_path, output_dir):
    """Transcribe audio from video segment using Whisper."""
    if not Path(WHISPER_MODEL_SHORT).exists():
        return None

    escaped_model = WHISPER_MODEL_SHORT.replace("C:", "C\\:")
    try:
        subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-af", f"whisper=model='{escaped_model}':language=cs:format=text:use_gpu=false",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=120)

        transcript_path = Path(WHISPER_MODEL_SHORT).parent / "transcript.txt"
        if transcript_path.exists():
            text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
            transcript_path.unlink(missing_ok=True)
            return text if text else None
    except Exception:
        pass
    return None


def encode_image_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ── Analysis prompts per component type ──

HOOK_PROMPT = """Analyzuj HOOK (prvni 3 sekundy) video reklamy pro Fermato.cz (cesky food e-commerce).
{frame_info}

Odpovez POUZE v JSON:
{{
  "hook_type": "visual_appeal|ugc_reaction|problem_statement|curiosity|product_reveal|shock|question|founder_story|testimonial",
  "hook_description": "co se deje v prvnich 3s",
  "attention_elements": ["person_face", "text_overlay", "motion", "color_contrast", "food_closeup", "product_pack", "emotion", "sound_effect"],
  "text_overlays": ["extrahovany text"],
  "audio_hook": "popis zvuku/hlasu v prvnich 3s pokud je znam",
  "food_appeal_score": 7,
  "production_quality": "professional|semi_pro|ugc|raw",
  "dominant_colors": ["#hex1", "#hex2"],
  "person_present": true,
  "effectiveness": "strong|medium|weak",
  "why": "proc hook funguje/nefunguje",
  "improvement_suggestions": ["konkretni navrh 1", "konkretni navrh 2"],
  "similar_to": "popis jakeho typu reklam tento hook pripomina"
}}"""

BODY_PROMPT = """Analyzuj BODY (stredni cast) video reklamy pro Fermato.cz.
{frame_info}
{transcript_info}

Odpovez POUZE v JSON:
{{
  "narrative_structure": "problem_solution|testimonial|product_demo|lifestyle|comparison|recipe|unboxing|listicle|educational",
  "scene_count": 3,
  "scenes": [
    {{"description": "co se deje", "duration_estimate": "5s", "energy": "high|medium|low"}}
  ],
  "pacing": "fast|medium|slow",
  "pacing_score": 7,
  "story_arc_present": true,
  "product_visibility_score": 8,
  "emotional_tone": "urgency|humor|trust|aspiration|educational|shock|warmth",
  "retention_signals": ["co drzi pozornost"],
  "dropout_risks": ["kde lidi pravdepodobne odchazeji a proc"],
  "strengths": ["silne stranky body casti"],
  "weaknesses": ["slabiny"]
}}"""

CTA_PROMPT = """Analyzuj CTA (posledni 5 sekund) video reklamy pro Fermato.cz.
{frame_info}
{transcript_info}

Odpovez POUZE v JSON:
{{
  "cta_type": "text_overlay|verbal|button|animated|none",
  "cta_text": "presny text CTA pokud existuje",
  "urgency_level": "high|medium|low|none",
  "urgency_mechanism": "scarcity|time_limit|social_proof|exclusive|none",
  "offer_present": true,
  "offer_description": "popis nabidky pokud existuje",
  "cta_visibility_score": 7,
  "cta_clarity_score": 8,
  "strengths": ["co CTA dela dobre"],
  "weaknesses": ["co nefunguje"],
  "improvement_suggestions": ["konkretni navrh"]
}}"""


# ── Decomposition pipeline ──

def decompose_video(video_path, work_dir):
    """Decompose video into hook/body/CTA segments.

    Returns:
        dict with keys: hook, body, cta — each containing segment path,
        frames, and timestamps.
    """
    duration = get_video_duration(video_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    hook_end = min(HOOK_DURATION, duration)
    cta_start = max(duration - CTA_DURATION, hook_end)
    body_start = hook_end
    body_end = cta_start

    result = {"duration": duration, "scenes": detect_scenes(video_path)}

    # Extract segments
    hook_path = work_dir / "hook.mp4"
    body_path = work_dir / "body.mp4"
    cta_path = work_dir / "cta.mp4"

    extract_segment(video_path, hook_path, 0, hook_end)
    if body_end > body_start + MIN_SCENE_DURATION:
        extract_segment(video_path, body_path, body_start, body_end)
    if duration > hook_end + MIN_SCENE_DURATION:
        extract_segment(video_path, cta_path, cta_start, duration)

    # Extract frames for each segment
    hook_timestamps = [0, 0.5, 1.0, 1.5, 2.0, 2.5]
    body_mid = (body_start + body_end) / 2
    body_timestamps = [body_start, body_start + 2, body_mid, body_end - 2, body_end]
    cta_timestamps = [cta_start, cta_start + 1, cta_start + 2, duration - 1]

    hook_dir = work_dir / "hook_frames"
    body_dir = work_dir / "body_frames"
    cta_dir = work_dir / "cta_frames"

    for d in [hook_dir, body_dir, cta_dir]:
        d.mkdir(exist_ok=True)

    result["hook"] = {
        "path": str(hook_path) if hook_path.exists() else None,
        "start": 0, "end": hook_end,
        "frames": extract_frames_at(video_path, hook_timestamps, hook_dir),
    }
    result["body"] = {
        "path": str(body_path) if body_path.exists() else None,
        "start": body_start, "end": body_end,
        "frames": extract_frames_at(video_path, body_timestamps, body_dir),
    }
    result["cta"] = {
        "path": str(cta_path) if cta_path.exists() else None,
        "start": cta_start, "end": duration,
        "frames": extract_frames_at(video_path, cta_timestamps, cta_dir),
    }

    # Transcribe each segment
    for segment_name in ["hook", "body", "cta"]:
        seg = result[segment_name]
        if seg["path"] and Path(seg["path"]).exists():
            seg["transcript"] = transcribe_segment(seg["path"], work_dir / f"{segment_name}_audio")

    return result


def analyze_component(component_type, frames, transcript=None, performance=None):
    """Analyze a single component (hook/body/CTA) via Claude Vision.

    Returns: (analysis_dict, cost_usd)
    """
    if not frames:
        return None, 0

    images_b64 = [encode_image_b64(f["path"]) for f in frames[:5]]
    frame_info = f"Toto je {len(images_b64)} framu z {component_type.upper()} casti videa."
    transcript_info = f'Audio transkript: "{transcript}"' if transcript else "Audio transkript neni k dispozici."

    prompts = {"hook": HOOK_PROMPT, "body": BODY_PROMPT, "cta": CTA_PROMPT}
    prompt = prompts[component_type].format(
        frame_info=frame_info,
        transcript_info=transcript_info,
    )

    if performance:
        perf_str = f"\nPerformance: Hook rate {performance.get('hook_rate', '?')}%, Hold rate {performance.get('hold_rate', '?')}%, ROAS {performance.get('roas', '?')}"
        prompt += perf_str

    try:
        text, cost = call_claude_vision(images_b64, prompt, max_tokens=1500)
        analysis = parse_json_from_response(text)
        return analysis, cost
    except Exception as e:
        print(f"  WARN: {component_type} analysis failed: {e}", file=sys.stderr)
        return None, 0


def decompose_and_analyze(ad_id, video_path, performance=None):
    """Full pipeline: decompose video + analyze each component.

    Returns:
        dict: {hook_analysis, body_analysis, cta_analysis, decomposition, total_cost}
    """
    work_dir = ASSETS_DIR / f"decomp_{ad_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    total_cost = 0.0

    try:
        # Decompose
        print(f"  Decomposing video {ad_id}...", file=sys.stderr)
        decomp = decompose_video(video_path, work_dir)

        result = {"decomposition": {
            "duration": decomp["duration"],
            "scenes": decomp["scenes"],
            "hook_range": [0, decomp["hook"]["end"]],
            "body_range": [decomp["body"]["start"], decomp["body"]["end"]],
            "cta_range": [decomp["cta"]["start"], decomp["cta"]["end"]],
        }}

        # Analyze each component
        for comp_name in ["hook", "body", "cta"]:
            comp = decomp[comp_name]
            if comp["frames"]:
                print(f"  Analyzing {comp_name} ({len(comp['frames'])} frames)...", file=sys.stderr)
                analysis, cost = analyze_component(
                    comp_name,
                    comp["frames"],
                    transcript=comp.get("transcript"),
                    performance=performance,
                )
                result[f"{comp_name}_analysis"] = analysis
                total_cost += cost

        result["total_cost"] = total_cost
        return result

    finally:
        # Cleanup
        try:
            shutil.rmtree(str(work_dir), ignore_errors=True)
        except Exception:
            pass


def download_and_decompose(ad_id, video_id, performance=None):
    """Download video from Meta API, decompose and analyze.

    Tries: 1) yt-dlp, 2) Meta API source URL, 3) Meta thumbnails fallback.
    Returns full analysis result or None.
    """
    work_dir = ASSETS_DIR / f"dl_{ad_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    video_path = work_dir / f"{ad_id}.mp4"

    try:
        # Try yt-dlp
        try:
            pdata = meta_fetch(video_id, {"fields": "permalink_url"})
            permalink = pdata.get("permalink_url")
            if permalink:
                fb_url = f"https://www.facebook.com{permalink}"
                subprocess.run(
                    ["yt-dlp", fb_url, "-o", str(video_path), "--no-check-certificates", "--quiet"],
                    capture_output=True, timeout=120
                )
        except Exception:
            pass

        # Fallback: Meta API source
        if not video_path.exists() or video_path.stat().st_size == 0:
            try:
                data = meta_fetch(video_id, {"fields": "source"})
                source_url = data.get("source")
                if source_url:
                    import urllib.request
                    req = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        with open(video_path, "wb") as f:
                            import shutil as sh
                            sh.copyfileobj(resp, f)
            except Exception:
                pass

        if video_path.exists() and video_path.stat().st_size > 0:
            return decompose_and_analyze(ad_id, str(video_path), performance)

        print(f"  WARN: Could not download video for {ad_id}", file=sys.stderr)
        return None

    finally:
        try:
            shutil.rmtree(str(work_dir), ignore_errors=True)
        except Exception:
            pass
