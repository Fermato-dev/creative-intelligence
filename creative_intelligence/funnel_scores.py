"""Funnel Scores — normalized 1-100 scoring in 4 dimensions.

Inspired by Motion App's Hook/Watch/Click/Convert scoring system.
Each ad gets a score 1-100 in each dimension, benchmarked within its campaign.

Grades:
  A (80-100): Top performer (dark green)
  B (60-79):  Solid (light green)
  C (40-59):  Average (yellow)
  D (20-39):  Below average (orange)
  F (0-19):   Poor (red)
"""

import sqlite3
from statistics import median, stdev

from .config import BENCHMARKS, TARGET_ROAS, TARGET_CPA


# ══════════════════════════════════════════════════════
# GRADE DEFINITIONS
# ══════════════════════════════════════════════════════

GRADES = {
    "A": {"min": 80, "color": "#22c55e", "label": "Top performer"},
    "B": {"min": 60, "color": "#86efac", "label": "Solid"},
    "C": {"min": 40, "color": "#facc15", "label": "Average"},
    "D": {"min": 20, "color": "#fb923c", "label": "Below average"},
    "F": {"min": 0,  "color": "#ef4444", "label": "Poor"},
}

MIN_ADS_FOR_CAMPAIGN_BENCH = 5  # fallback to absolute if fewer


def score_to_grade(score):
    """Convert 0-100 score to letter grade."""
    if score is None:
        return None
    for letter, info in GRADES.items():
        if score >= info["min"]:
            return letter
    return "F"


def grade_color(grade):
    """Get color hex for a grade."""
    return GRADES.get(grade, GRADES["F"])["color"]


# ══════════════════════════════════════════════════════
# PERCENTILE-BASED SCORING (within campaign)
# ══════════════════════════════════════════════════════

def _percentile_score(value, values_in_group, higher_is_better=True):
    """Calculate percentile-based score 0-100 within a group.

    If fewer than MIN_ADS_FOR_CAMPAIGN_BENCH values, returns None (use absolute).
    """
    if value is None or not values_in_group:
        return None

    valid = [v for v in values_in_group if v is not None]
    if len(valid) < MIN_ADS_FOR_CAMPAIGN_BENCH:
        return None

    if not higher_is_better:
        # Invert: lower is better (CPA, CPC)
        valid_max = max(valid) if valid else 1
        value = valid_max - value
        valid = [valid_max - v for v in valid]

    sorted_vals = sorted(valid)
    n = len(sorted_vals)

    # Count how many values are below this one
    below = sum(1 for v in sorted_vals if v < value)
    equal = sum(1 for v in sorted_vals if v == value)

    # Percentile rank (midpoint method)
    percentile = (below + equal / 2) / n * 100
    return round(min(max(percentile, 0), 100))


# ══════════════════════════════════════════════════════
# ABSOLUTE SCORING (fallback when campaign too small)
# ══════════════════════════════════════════════════════

def _absolute_score(value, poor, good, excellent, higher_is_better=True):
    """Score 0-100 based on absolute benchmarks.

    Linearly interpolates:
      <= poor     → 20
      poor→good   → 20-60
      good→excel  → 60-90
      > excel     → 90-100
    """
    if value is None:
        return None

    if not higher_is_better:
        # Invert scale for metrics where lower is better (CPA, CPC)
        value, poor, good, excellent = -value, -poor, -good, -excellent

    if value <= poor:
        return max(0, round(20 * value / poor)) if poor > 0 else 0
    elif value <= good:
        return round(20 + 40 * (value - poor) / (good - poor))
    elif value <= excellent:
        return round(60 + 30 * (value - good) / (excellent - good))
    else:
        return min(100, round(90 + 10 * (value - excellent) / (excellent * 0.5)))


# ══════════════════════════════════════════════════════
# DIMENSION SCORES
# ══════════════════════════════════════════════════════

def calculate_hook_score(ad, campaign_ads=None):
    """Hook Score — how well the ad stops the scroll.

    Inputs: hook_rate (video_views / impressions * 100)
    For static ads: uses CTR as proxy (lower weight).
    """
    if ad.get("is_video") and ad.get("hook_rate") is not None:
        hook_rate = ad["hook_rate"]
        # Try campaign percentile first
        if campaign_ads:
            group_values = [a.get("hook_rate") for a in campaign_ads if a.get("is_video")]
            score = _percentile_score(hook_rate, group_values)
            if score is not None:
                return score
        # Absolute fallback
        return _absolute_score(
            hook_rate,
            poor=BENCHMARKS["hook_rate"]["minimum"],      # 20
            good=BENCHMARKS["hook_rate"]["standard"],      # 25
            excellent=BENCHMARKS["hook_rate"]["elite"],     # 35
        )
    elif ad.get("ctr") is not None:
        # Static ads: use CTR as hook proxy (adjusted scale)
        ctr = ad["ctr"]
        if campaign_ads:
            group_values = [a.get("ctr") for a in campaign_ads if not a.get("is_video")]
            score = _percentile_score(ctr, group_values)
            if score is not None:
                return score
        return _absolute_score(ctr, poor=0.8, good=1.5, excellent=2.5)
    return None


def calculate_watch_score(ad, campaign_ads=None):
    """Watch Score — how well the ad retains attention.

    Only for video ads. Uses hold_rate + completion_rate.
    Static ads return None.
    """
    if not ad.get("is_video"):
        return None

    hold_rate = ad.get("hold_rate")
    completion_rate = ad.get("completion_rate")

    if hold_rate is None:
        return None

    # Primary: hold_rate (thruplay / 3s views)
    if campaign_ads:
        group_values = [a.get("hold_rate") for a in campaign_ads if a.get("is_video")]
        score = _percentile_score(hold_rate, group_values)
        if score is not None:
            # Blend with completion if available
            if completion_rate is not None:
                comp_score = _absolute_score(completion_rate, poor=5, good=15, excellent=30)
                if comp_score is not None:
                    return round(score * 0.7 + comp_score * 0.3)
            return score

    # Absolute fallback
    base = _absolute_score(
        hold_rate,
        poor=BENCHMARKS["hold_rate"]["minimum"],      # 30
        good=BENCHMARKS["hold_rate"]["standard"],      # 40
        excellent=BENCHMARKS["hold_rate"]["elite"],     # 60
    )
    if base is not None and completion_rate is not None:
        comp_score = _absolute_score(completion_rate, poor=5, good=15, excellent=30)
        if comp_score is not None:
            return round(base * 0.7 + comp_score * 0.3)
    return base


def calculate_click_score(ad, campaign_ads=None):
    """Click Score — how well the ad drives clicks.

    Inputs: CTR + CPC (lower CPC = better).
    """
    ctr = ad.get("ctr")
    if ctr is None:
        return None

    if campaign_ads:
        group_ctr = [a.get("ctr") for a in campaign_ads]
        score = _percentile_score(ctr, group_ctr)
        if score is not None:
            return score

    return _absolute_score(
        ctr,
        poor=BENCHMARKS["ctr"]["minimum"],     # 1.0
        good=BENCHMARKS["ctr"]["standard"],     # 1.5
        excellent=BENCHMARKS["ctr"]["good"],    # 2.0
    )


def calculate_convert_score(ad, campaign_ads=None):
    """Convert Score — how well the ad converts.

    Inputs: ROAS (primary), CPA (secondary), CVR.
    """
    roas = ad.get("roas")
    cpa = ad.get("cpa")
    cvr = ad.get("cvr")

    if roas is None and cpa is None:
        return None

    # ROAS score (primary, 60% weight)
    roas_score = None
    if roas is not None:
        if campaign_ads:
            group_roas = [a.get("roas") for a in campaign_ads]
            roas_score = _percentile_score(roas, group_roas)
        if roas_score is None:
            roas_score = _absolute_score(roas, poor=1.0, good=TARGET_ROAS, excellent=TARGET_ROAS * 1.5)

    # CPA score (secondary, 40% weight — lower is better)
    cpa_score = None
    if cpa is not None:
        if campaign_ads:
            group_cpa = [a.get("cpa") for a in campaign_ads]
            cpa_score = _percentile_score(cpa, group_cpa, higher_is_better=False)
        if cpa_score is None:
            cpa_score = _absolute_score(
                cpa,
                poor=TARGET_CPA * 1.5,
                good=TARGET_CPA,
                excellent=TARGET_CPA * 0.5,
                higher_is_better=False,
            )

    # Blend
    if roas_score is not None and cpa_score is not None:
        return round(roas_score * 0.6 + cpa_score * 0.4)
    return roas_score or cpa_score


# ══════════════════════════════════════════════════════
# OVERALL SCORE
# ══════════════════════════════════════════════════════

def calculate_overall_score(hook, watch, click, convert):
    """Weighted overall score.

    Video:  Hook 25% + Watch 25% + Click 25% + Convert 25%
    Static: Click 50% + Convert 50% (Hook and Watch are N/A)
    """
    scores = {}
    if hook is not None:
        scores["hook"] = hook
    if watch is not None:
        scores["watch"] = watch
    if click is not None:
        scores["click"] = click
    if convert is not None:
        scores["convert"] = convert

    if not scores:
        return None

    if watch is not None:
        # Video: equal weights across available dimensions
        total = sum(scores.values())
        return round(total / len(scores))
    else:
        # Static: only click + convert
        click_convert = [v for k, v in scores.items() if k in ("click", "convert")]
        if click_convert:
            return round(sum(click_convert) / len(click_convert))
    return None


# ══════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════

def calculate_funnel_scores(ad_metrics, all_ads_metrics=None):
    """Calculate funnel scores for a single ad.

    Args:
        ad_metrics: dict with calculated metrics for one ad
        all_ads_metrics: list of all ads (for campaign-relative scoring)

    Returns:
        dict with hook_score, watch_score, click_score, convert_score,
        overall_score, grades, and colors
    """
    # Group by campaign for relative scoring
    campaign_ads = None
    if all_ads_metrics:
        campaign = ad_metrics.get("campaign_name", "")
        campaign_ads = [a for a in all_ads_metrics if a.get("campaign_name") == campaign]
        if len(campaign_ads) < MIN_ADS_FOR_CAMPAIGN_BENCH:
            campaign_ads = all_ads_metrics  # fallback to all ads

    hook = calculate_hook_score(ad_metrics, campaign_ads)
    watch = calculate_watch_score(ad_metrics, campaign_ads)
    click = calculate_click_score(ad_metrics, campaign_ads)
    convert = calculate_convert_score(ad_metrics, campaign_ads)
    overall = calculate_overall_score(hook, watch, click, convert)

    hook_grade = score_to_grade(hook)
    watch_grade = score_to_grade(watch)
    click_grade = score_to_grade(click)
    convert_grade = score_to_grade(convert)
    overall_grade = score_to_grade(overall)

    return {
        "hook_score": hook,
        "watch_score": watch,
        "click_score": click,
        "convert_score": convert,
        "overall_score": overall,
        "hook_grade": hook_grade,
        "watch_grade": watch_grade,
        "click_grade": click_grade,
        "convert_grade": convert_grade,
        "overall_grade": overall_grade,
        "hook_color": grade_color(hook_grade) if hook_grade else None,
        "watch_color": grade_color(watch_grade) if watch_grade else None,
        "click_color": grade_color(click_grade) if click_grade else None,
        "convert_color": grade_color(convert_grade) if convert_grade else None,
        "overall_color": grade_color(overall_grade) if overall_grade else None,
    }


def score_all_ads(ads_metrics):
    """Calculate funnel scores for all ads. Returns list of dicts with scores merged in."""
    results = []
    for ad in ads_metrics:
        scores = calculate_funnel_scores(ad, ads_metrics)
        merged = {**ad, **scores}
        results.append(merged)
    return results


# ══════════════════════════════════════════════════════
# DB PERSISTENCE
# ══════════════════════════════════════════════════════

FUNNEL_SCORES_SCHEMA = """
CREATE TABLE IF NOT EXISTS funnel_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    ad_id TEXT NOT NULL,
    ad_name TEXT,
    campaign_name TEXT,
    is_video BOOLEAN,
    hook_score INTEGER,
    watch_score INTEGER,
    click_score INTEGER,
    convert_score INTEGER,
    overall_score INTEGER,
    hook_grade TEXT,
    watch_grade TEXT,
    click_grade TEXT,
    convert_grade TEXT,
    overall_grade TEXT,
    -- Raw metrics for reference
    hook_rate REAL,
    hold_rate REAL,
    ctr REAL,
    roas REAL,
    cpa REAL,
    spend REAL,
    UNIQUE(snapshot_date, ad_id)
);
CREATE INDEX IF NOT EXISTS idx_fs_date ON funnel_scores(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_fs_overall ON funnel_scores(overall_score);
"""


def init_funnel_scores_schema(conn):
    """Create funnel_scores table if missing."""
    conn.executescript(FUNNEL_SCORES_SCHEMA)
    conn.commit()


def save_funnel_scores(conn, scored_ads, date_str):
    """Save funnel scores to DB."""
    saved = 0
    for ad in scored_ads:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO funnel_scores (
                    snapshot_date, ad_id, ad_name, campaign_name, is_video,
                    hook_score, watch_score, click_score, convert_score, overall_score,
                    hook_grade, watch_grade, click_grade, convert_grade, overall_grade,
                    hook_rate, hold_rate, ctr, roas, cpa, spend
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str, ad["ad_id"], ad.get("ad_name"), ad.get("campaign_name"),
                ad.get("is_video"),
                ad.get("hook_score"), ad.get("watch_score"),
                ad.get("click_score"), ad.get("convert_score"), ad.get("overall_score"),
                ad.get("hook_grade"), ad.get("watch_grade"),
                ad.get("click_grade"), ad.get("convert_grade"), ad.get("overall_grade"),
                ad.get("hook_rate"), ad.get("hold_rate"),
                ad.get("ctr"), ad.get("roas"), ad.get("cpa"), ad.get("spend"),
            ))
            saved += 1
        except Exception as e:
            import sys
            print(f"  WARN: save funnel score {ad.get('ad_id')}: {e}", file=sys.stderr)

    conn.commit()
    return saved
