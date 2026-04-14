"""Visual Tagger — AI-powered creative classification.

Uses Claude Vision to automatically tag each ad with:
- Visual format (UGC, Product Shot, Lifestyle, etc.)
- Messaging angle (Price, Quality, Social Proof, etc.)
- Production quality, hook type, visual elements

Inspired by Motion App's AI Tagging feature.
"""

import base64
import json
import sqlite3
import sys
from datetime import datetime

from .claude_client import call_claude_vision, parse_json_from_response
from .config import DB_PATH
from .meta_client import meta_fetch


# ══════════════════════════════════════════════════════
# TAXONOMIES
# ══════════════════════════════════════════════════════

VISUAL_FORMATS = [
    "UGC_Testimonial",       # Real person talking about product
    "UGC_Recipe",            # UGC with recipe/usage
    "Product_Demo",          # Detailed product demonstration
    "Product_Shot_Static",   # Static product photography
    "Lifestyle_InUse",       # Product in real-life context
    "Carousel_Lookbook",     # Carousel with multiple products/variants
    "Before_After",          # Before/after comparison
    "How_To",                # Tutorial/how-to
    "Founder_Story",         # Founder narrative
    "Partnership_Collab",    # Influencer/brand partnership
    "Offer_Banner",          # Promotional/discount banner
    "Text_Overlay",          # Primarily text-based format
    "ASMR_Sensory",          # ASMR / sensory content
    "Montage",               # Multi-scene compilation
    "Comparison",            # vs. competitor comparison
    "Unboxing",              # Unboxing experience
]

MESSAGING_ANGLES = [
    "Price_Offer",           # Price point, discount, deal
    "Quality_Ingredients",   # Ingredient quality, clean label
    "Taste_Experience",      # Flavor, taste sensation
    "Health_Benefit",        # Health/wellness benefit
    "Social_Proof",          # Reviews, ratings, testimonials
    "Discovery_New",         # Discover something new, novelty
    "Urgency_Scarcity",      # Limited offer, running out
    "Lifestyle_Identity",    # Lifestyle match, identity
    "Education",             # Educational content
    "Emotional_Story",       # Emotional narrative
    "Versatility",           # Multiple uses, versatile product
]

HOOK_TYPES = [
    "Question",              # Opens with a question
    "Bold_Statement",        # Strong claim or statement
    "Visual_Surprise",       # Eye-catching visual
    "Social_Proof_Hook",     # Stars with review/testimonial
    "Problem_Setup",         # Presents a problem
    "Curiosity_Gap",         # Creates curiosity
    "Direct_Address",        # Speaks directly to viewer
]

PRODUCTION_QUALITIES = ["UGC", "Semi_Pro", "Professional"]


# ══════════════════════════════════════════════════════
# VISION PROMPT
# ══════════════════════════════════════════════════════

TAGGING_PROMPT = f"""Analyzuj tuto reklamu (thumbnail/screenshot) pro FMCG food/beverage brand Fermato.

Klasifikuj do následujících kategorií. Vrať POUZE platný JSON bez dalšího textu.

VISUAL_FORMATS (vyber 1 primární): {json.dumps(VISUAL_FORMATS)}
MESSAGING_ANGLES (vyber 1 primární): {json.dumps(MESSAGING_ANGLES)}
HOOK_TYPES (vyber 1, pouze pokud je to video): {json.dumps(HOOK_TYPES)}
PRODUCTION_QUALITY: {json.dumps(PRODUCTION_QUALITIES)}

Vrať JSON v tomto formátu:
{{
    "visual_format": "...",
    "visual_format_confidence": 0.85,
    "messaging_angle": "...",
    "messaging_confidence": 0.78,
    "hook_type": "..." nebo null,
    "production_quality": "...",
    "has_text_overlay": true/false,
    "has_person": true/false,
    "has_product": true/false,
    "dominant_color_hex": "#RRGGBB",
    "brief_description": "1 věta popis reklamy"
}}
"""

def _make_prompt_with_copy(ad_copy):
    """Build tagging prompt with ad copy included."""
    return f"Analyzuj tuto reklamu. K dispozici je i ad copy text:\n\nAD COPY:\n{ad_copy}\n\n{TAGGING_PROMPT}"


# ══════════════════════════════════════════════════════
# SCHEMA
# ══════════════════════════════════════════════════════

CREATIVE_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS creative_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id TEXT NOT NULL UNIQUE,
    ad_name TEXT,
    campaign_name TEXT,
    visual_format TEXT,
    visual_format_confidence REAL,
    messaging_angle TEXT,
    messaging_confidence REAL,
    ad_type TEXT,
    hook_type TEXT,
    production_quality TEXT,
    has_text_overlay BOOLEAN,
    has_person BOOLEAN,
    has_product BOOLEAN,
    dominant_color TEXT,
    brief_description TEXT,
    thumbnail_url TEXT,
    ad_copy TEXT,
    destination_url TEXT,
    tagged_at TEXT NOT NULL,
    tagged_by TEXT DEFAULT 'claude_vision'
);
CREATE INDEX IF NOT EXISTS idx_ct_format ON creative_tags(visual_format);
CREATE INDEX IF NOT EXISTS idx_ct_angle ON creative_tags(messaging_angle);
CREATE INDEX IF NOT EXISTS idx_ct_quality ON creative_tags(production_quality);
"""


def init_creative_tags_schema(conn):
    """Create creative_tags table if missing, and migrate if needed."""
    conn.executescript(CREATIVE_TAGS_SCHEMA)
    # Migration: add columns if they don't exist (for DBs created before v3.5.1)
    for col, coltype in [("thumbnail_url", "TEXT"), ("ad_copy", "TEXT"), ("destination_url", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE creative_tags ADD COLUMN {col} {coltype}")
        except Exception:
            pass  # column already exists
    conn.commit()


# ══════════════════════════════════════════════════════
# THUMBNAIL FETCHING
# ══════════════════════════════════════════════════════

def fetch_ad_thumbnail_url(ad_id):
    """Fetch thumbnail URL for an ad from Meta API."""
    try:
        data = meta_fetch(f"{ad_id}", {"fields": "creative{thumbnail_url,image_url}"})
        creative = data.get("creative", {})
        return creative.get("thumbnail_url") or creative.get("image_url")
    except Exception as e:
        print(f"  WARN: fetch thumbnail {ad_id}: {e}", file=sys.stderr)
        return None


def fetch_thumbnail_as_b64(url):
    """Download image from URL and convert to base64."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FermatoCIBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
            return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        print(f"  WARN: download thumbnail: {e}", file=sys.stderr)
        return None


# ══════════════════════════════════════════════════════
# TAGGING
# ══════════════════════════════════════════════════════

def tag_creative(ad_id, thumbnail_b64, ad_copy=None, ad_type="Image"):
    """Tag a single creative using Claude Vision.

    Args:
        ad_id: Meta ad ID
        thumbnail_b64: base64-encoded JPEG/PNG
        ad_copy: optional ad copy text
        ad_type: "Video", "Image", or "Carousel"

    Returns:
        dict with tags or None on failure
    """
    if not thumbnail_b64:
        return None

    prompt = _make_prompt_with_copy(ad_copy) if ad_copy else TAGGING_PROMPT

    try:
        response_text, cost = call_claude_vision([thumbnail_b64], prompt, max_tokens=500)
        tags = parse_json_from_response(response_text)

        if not tags or not isinstance(tags, dict):
            return None

        # Validate and normalize
        vf = tags.get("visual_format", "")
        if vf not in VISUAL_FORMATS:
            # Find closest match
            vf_lower = vf.lower().replace(" ", "_")
            for valid in VISUAL_FORMATS:
                if valid.lower() == vf_lower:
                    tags["visual_format"] = valid
                    break

        ma = tags.get("messaging_angle", "")
        if ma not in MESSAGING_ANGLES:
            ma_lower = ma.lower().replace(" ", "_")
            for valid in MESSAGING_ANGLES:
                if valid.lower() == ma_lower:
                    tags["messaging_angle"] = valid
                    break

        tags["ad_type"] = ad_type
        return tags

    except Exception as e:
        print(f"  WARN: tag creative {ad_id}: {e}", file=sys.stderr)
        return None


def batch_tag_creatives(conn, ads_with_creatives, force=False):
    """Tag all ads that haven't been tagged yet.

    Args:
        conn: SQLite connection
        ads_with_creatives: list of dicts with {ad_id, ad_name, campaign_name, is_video, ...}
                           from metrics.fetch_ad_creatives()
        force: re-tag even if already tagged

    Returns:
        number of ads tagged
    """
    init_creative_tags_schema(conn)
    tagged = 0

    for ad in ads_with_creatives:
        ad_id = ad.get("id") or ad.get("ad_id")
        if not ad_id:
            continue

        # Skip if already tagged (unless force)
        if not force:
            existing = conn.execute(
                "SELECT 1 FROM creative_tags WHERE ad_id = ?", (ad_id,)
            ).fetchone()
            if existing:
                continue

        # Get thumbnail
        creative = ad.get("creative", {})
        thumb_url = creative.get("thumbnail_url") or creative.get("image_url")
        if not thumb_url:
            thumb_url = fetch_ad_thumbnail_url(ad_id)
        if not thumb_url:
            continue

        thumb_b64 = fetch_thumbnail_as_b64(thumb_url)
        if not thumb_b64:
            continue

        # Determine ad type
        video_id = creative.get("video_id")
        object_type = creative.get("object_type", "")
        if video_id:
            ad_type = "Video"
        elif "CAROUSEL" in object_type.upper() if object_type else False:
            ad_type = "Carousel"
        else:
            ad_type = "Image"

        # Get ad copy
        ad_copy = creative.get("body") or creative.get("title")

        # Tag
        tags = tag_creative(ad_id, thumb_b64, ad_copy=ad_copy, ad_type=ad_type)
        if not tags:
            continue

        # Save
        now = datetime.now().isoformat()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO creative_tags (
                    ad_id, ad_name, campaign_name,
                    visual_format, visual_format_confidence,
                    messaging_angle, messaging_confidence,
                    ad_type, hook_type, production_quality,
                    has_text_overlay, has_person, has_product,
                    dominant_color, brief_description,
                    thumbnail_url, ad_copy, destination_url,
                    tagged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ad_id, ad.get("name") or ad.get("ad_name"),
                ad.get("campaign_name") or "",
                tags.get("visual_format"), tags.get("visual_format_confidence"),
                tags.get("messaging_angle"), tags.get("messaging_confidence"),
                tags.get("ad_type", ad_type),
                tags.get("hook_type"),
                tags.get("production_quality"),
                tags.get("has_text_overlay"),
                tags.get("has_person"),
                tags.get("has_product"),
                tags.get("dominant_color_hex"),
                tags.get("brief_description"),
                thumb_url,
                ad_copy,
                None,  # destination_url — will be populated separately
                now,
            ))
            conn.commit()
            tagged += 1
            print(f"  Tagged {ad_id}: {tags.get('visual_format')} / {tags.get('messaging_angle')}")
        except Exception as e:
            print(f"  WARN: save tag {ad_id}: {e}", file=sys.stderr)

    return tagged


# ══════════════════════════════════════════════════════
# QUERIES
# ══════════════════════════════════════════════════════

def save_thumbnail_urls(conn, ads_with_creatives):
    """Save thumbnail URLs for all ads (no Vision API call, just metadata).

    This is cheap — just stores URLs from Meta API for dashboard display.
    """
    init_creative_tags_schema(conn)
    saved = 0
    for ad in ads_with_creatives:
        ad_id = ad.get("id") or ad.get("ad_id")
        if not ad_id:
            continue

        creative = ad.get("creative", {})
        thumb_url = creative.get("thumbnail_url") or creative.get("image_url")
        if not thumb_url:
            continue

        # Only update thumbnail_url if row exists but has no thumbnail,
        # or create minimal row if doesn't exist
        existing = conn.execute(
            "SELECT thumbnail_url FROM creative_tags WHERE ad_id = ?", (ad_id,)
        ).fetchone()

        if existing and existing["thumbnail_url"]:
            continue  # already has thumbnail

        if existing:
            conn.execute(
                "UPDATE creative_tags SET thumbnail_url = ? WHERE ad_id = ?",
                (thumb_url, ad_id)
            )
        else:
            # Create minimal row with just thumbnail
            ad_name = ad.get("name") or ad.get("ad_name", "")
            video_id = creative.get("video_id")
            obj_type = creative.get("object_type", "")
            if video_id:
                ad_type = "Video"
            elif "CAROUSEL" in obj_type.upper() if obj_type else False:
                ad_type = "Carousel"
            else:
                ad_type = "Image"

            conn.execute("""
                INSERT OR IGNORE INTO creative_tags (
                    ad_id, ad_name, ad_type, thumbnail_url, tagged_at, tagged_by
                ) VALUES (?, ?, ?, ?, ?, 'metadata_only')
            """, (ad_id, ad_name, ad_type, thumb_url, datetime.now().isoformat()))
        saved += 1

    conn.commit()
    return saved


def get_format_distribution(conn):
    """Get distribution of visual formats across tagged ads."""
    rows = conn.execute("""
        SELECT visual_format, COUNT(*) as count,
               GROUP_CONCAT(ad_name, ' | ') as examples
        FROM creative_tags
        GROUP BY visual_format
        ORDER BY count DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_messaging_distribution(conn):
    """Get distribution of messaging angles across tagged ads."""
    rows = conn.execute("""
        SELECT messaging_angle, COUNT(*) as count,
               GROUP_CONCAT(ad_name, ' | ') as examples
        FROM creative_tags
        GROUP BY messaging_angle
        ORDER BY count DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_tags_for_ad(conn, ad_id):
    """Get all tags for a specific ad."""
    row = conn.execute(
        "SELECT * FROM creative_tags WHERE ad_id = ?", (ad_id,)
    ).fetchone()
    return dict(row) if row else None
