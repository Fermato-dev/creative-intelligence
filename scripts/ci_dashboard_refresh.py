#!/usr/bin/env python3
"""CI Dashboard Refresh — daily pipeline for Hetzner cron.

Runs all v3.5 features:
1. Collect daily snapshots (change_tracker)
2. Calculate funnel scores
3. Save thumbnail URLs
4. Generate HTML dashboard
5. Copy to dashboard repo + git push

Usage:
    python scripts/ci_dashboard_refresh.py
    python scripts/ci_dashboard_refresh.py --days 14 --skip-push

Autor: Claude Code + CEO
Datum: 2026-04-13
"""

import os
import shutil
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# Setup path
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from creative_intelligence.config import DB_PATH, DATA_DIR
from creative_intelligence.component_db import get_db

DASHBOARD_REPO = Path("/home/fermato/fermato-ci-dashboard")
DASHBOARD_HTML_NAME = "ci-dashboard.html"


def main(days=14, skip_push=False):
    ts = lambda: datetime.now().strftime("%H:%M:%S")
    print(f"[{ts()}] CI Dashboard Refresh v3.5")

    conn = get_db()

    # ── 1. Daily snapshots ──
    try:
        from creative_intelligence.change_tracker import (
            init_change_tracking_schema, fetch_daily_snapshots,
            fetch_ad_states, save_daily_snapshots, detect_changes,
        )
        init_change_tracking_schema(conn)

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"[{ts()}] Collecting snapshots for {yesterday}...")

        insights = fetch_daily_snapshots(yesterday)
        states = fetch_ad_states()
        saved = save_daily_snapshots(conn, insights, states, yesterday)
        changes = detect_changes(conn, yesterday)
        print(f"[{ts()}] Snapshots: {saved} ads, {changes} changes detected")
    except Exception as e:
        print(f"[{ts()}] Snapshot collection failed: {e}")
        traceback.print_exc()

    # ── 2. Funnel scores ──
    try:
        from creative_intelligence.metrics import fetch_ad_insights, calculate_metrics
        from creative_intelligence.funnel_scores import score_all_ads, save_funnel_scores, init_funnel_scores_schema

        print(f"[{ts()}] Calculating funnel scores...")
        raw = fetch_ad_insights(days)
        ads = [calculate_metrics(r) for r in raw]
        scored = score_all_ads(ads)

        init_funnel_scores_schema(conn)
        date_str = datetime.now().strftime("%Y-%m-%d")
        fs_saved = save_funnel_scores(conn, scored, date_str)
        print(f"[{ts()}] Funnel scores: {fs_saved} ads")
    except Exception as e:
        print(f"[{ts()}] Funnel scores failed: {e}")
        traceback.print_exc()

    # ── 3. Thumbnail URLs ──
    try:
        from creative_intelligence.metrics import fetch_ad_creatives
        from creative_intelligence.visual_tagger import save_thumbnail_urls, init_creative_tags_schema

        print(f"[{ts()}] Saving thumbnail URLs...")
        init_creative_tags_schema(conn)
        creatives = fetch_ad_creatives()
        active = [c for c in creatives if c.get("effective_status") == "ACTIVE"]
        thumb_saved = save_thumbnail_urls(conn, active)
        print(f"[{ts()}] Thumbnails: {thumb_saved}")
    except Exception as e:
        print(f"[{ts()}] Thumbnails failed: {e}")
        traceback.print_exc()

    # ── 4. Leaderboard ──
    try:
        from creative_intelligence.leaderboard import generate_leaderboard, save_leaderboard, init_leaderboard_schema

        print(f"[{ts()}] Updating leaderboard...")
        init_leaderboard_schema(conn)
        lb = generate_leaderboard(conn, days=7, limit=15)
        week_start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        save_leaderboard(conn, lb, week_start)
        print(f"[{ts()}] Leaderboard: {len(lb)} entries")
    except Exception as e:
        print(f"[{ts()}] Leaderboard failed: {e}")
        traceback.print_exc()

    # ── 5. Generate HTML dashboard ──
    try:
        from creative_intelligence.dashboard import generate_dashboard

        print(f"[{ts()}] Generating HTML dashboard...")
        dash_path = generate_dashboard(conn, days=days)
        print(f"[{ts()}] Dashboard: {dash_path}")
    except Exception as e:
        print(f"[{ts()}] Dashboard generation failed: {e}")
        traceback.print_exc()
        conn.close()
        return

    conn.close()

    # ── 6. Copy to dashboard repo + push ──
    if not skip_push and DASHBOARD_REPO.exists():
        try:
            # Copy HTML
            dest_html = DASHBOARD_REPO / DASHBOARD_HTML_NAME
            shutil.copy2(dash_path, dest_html)

            # Copy DB
            dest_db = DASHBOARD_REPO / "creative_analysis.db"
            shutil.copy2(str(DB_PATH), str(dest_db))

            # Git push
            import subprocess
            os.chdir(str(DASHBOARD_REPO))
            subprocess.run(["git", "add", "-A"], check=True)
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                capture_output=True
            )
            if result.returncode != 0:  # there are changes
                subprocess.run(
                    ["git", "commit", "-m",
                     f"auto: dashboard refresh {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                    check=True
                )
                subprocess.run(["git", "push"], check=True, timeout=60)
                print(f"[{ts()}] Pushed to dashboard repo")
            else:
                print(f"[{ts()}] No changes to push")
        except Exception as e:
            print(f"[{ts()}] Push failed: {e}")
            traceback.print_exc()
    elif skip_push:
        print(f"[{ts()}] Push skipped (--skip-push)")
    else:
        print(f"[{ts()}] Dashboard repo not found at {DASHBOARD_REPO}")

    print(f"[{ts()}] Done")


if __name__ == "__main__":
    args = sys.argv[1:]
    days = 14
    skip_push = "--skip-push" in args
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
    main(days=days, skip_push=skip_push)
