"""Shared configuration — targets, benchmarks, API config."""

import os
from pathlib import Path

# ── Paths ──
PACKAGE_DIR = Path(__file__).parent
REPO_ROOT = PACKAGE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
ASSETS_DIR = DATA_DIR / "creative_assets"
DB_PATH = DATA_DIR / "creative_analysis.db"

# ── Meta Ads ──
AD_ACCOUNT_ID = "act_346692147206629"
META_API_VERSION = "v23.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

# ── Targets ──
TARGET_CPA = 250       # CZK
TARGET_ROAS = 2.5
MIN_SPEND_FOR_DECISION = 200   # CZK
MIN_IMPRESSIONS = 1000

# ── Benchmarks (research-backed) ──
BENCHMARKS = {
    "hook_rate": {"minimum": 20, "standard": 25, "good": 30, "elite": 35},
    "hold_rate": {"minimum": 30, "standard": 40, "good": 50, "elite": 60},
    "ctr": {"minimum": 1.0, "standard": 1.5, "good": 2.0},
    "cvr": {"good": 2.0, "excellent": 3.0},
    "frequency": {"cold_alert": 3.0, "cold_extreme": 5.0, "retarget_alert": 6.0},
}

# ── Vision ──
REANALYSIS_DAYS = 7
DEFAULT_MAX_CREATIVES = 20
WHISPER_MODEL_SHORT = os.environ.get("WHISPER_MODEL_PATH", "")
FB_PAGE_ID = "1334931808840161"

# ── Claude ──
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# ── Pumble ──
PUMBLE_CHANNEL = "meta-ads"
PUMBLE_API_BASE = "https://pumble-api-keys.addons.marketplace.cake.com"

# ── v3: Scene Decomposition ──
HOOK_DURATION = 3.0      # seconds — first 3s
CTA_DURATION = 5.0       # seconds — last 5s
MIN_SCENE_DURATION = 1.0 # seconds — minimum scene length
COMPONENT_REANALYSIS_DAYS = 14

# ── Remix filtr: sezonni/flash kampane vyloucene z doporuceni ──
# Patterny v campaign_name NEBO ad_name ktere oznacuji sezonni/flash obsah.
# Case-insensitive substring match.
SEASONAL_CAMPAIGN_PATTERNS = [
    "easter", "velikonoc", "valentyn", "valentine",
    "christmas", "vanoce", "xmas",
    "black friday", "bf ", "cyber monday",
    "flash", "seasonal", "sezonni",
    "halloween", "mothers day", "den matek",
    "fathers day", "den otcu",
    "new year", "novy rok", "silvestr",
]
