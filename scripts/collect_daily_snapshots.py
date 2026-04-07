"""
Ucel: Denny sber ad-level snapshotu z Meta API + detekce zmen + lift mereni.
Autor: Claude Code + CEO
Datum: 2026-04-07
Zdroj dat: Meta Graph API (ad insights + ad states)

Spousteni: python scripts/collect_daily_snapshots.py [--date YYYY-MM-DD] [--backfill N]
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from creative_intelligence.change_tracker import (
    init_change_tracking_schema,
    fetch_daily_snapshots,
    fetch_ad_states,
    save_daily_snapshots,
    detect_changes,
    measure_lift,
)
from creative_intelligence.config import DB_PATH


def main():
    parser = argparse.ArgumentParser(description="Collect daily Meta Ads snapshots")
    parser.add_argument("--date", help="Date to collect (YYYY-MM-DD, default: yesterday)")
    parser.add_argument("--backfill", type=int, help="Backfill N days from --date backwards")
    parser.add_argument("--skip-lift", action="store_true", help="Skip lift measurement")
    args = parser.parse_args()

    # Determine date(s)
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        target = datetime.now() - timedelta(days=1)

    dates = []
    if args.backfill:
        for i in range(args.backfill, -1, -1):
            dates.append((target - timedelta(days=i)).strftime("%Y-%m-%d"))
    else:
        dates.append(target.strftime("%Y-%m-%d"))

    # Connect to DB
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    init_change_tracking_schema(conn)

    # Fetch ad states once (current state)
    print("Fetching ad states...")
    try:
        ad_states = fetch_ad_states()
        print(f"  {len(ad_states)} ads found")
    except Exception as e:
        print(f"  ERROR fetching ad states: {e}", file=sys.stderr)
        ad_states = []

    # Process each date
    for date_str in dates:
        print(f"\n=== {date_str} ===")

        # Check if already collected
        existing = conn.execute(
            "SELECT COUNT(*) as c FROM ad_daily_snapshots WHERE snapshot_date = ?",
            (date_str,)).fetchone()["c"]
        if existing > 0:
            print(f"  Already have {existing} snapshots, skipping fetch")
        else:
            # Fetch daily insights
            print(f"  Fetching daily insights...")
            try:
                insights = fetch_daily_snapshots(date_str)
                saved = save_daily_snapshots(conn, insights, ad_states, date_str)
                print(f"  Saved {saved} snapshots")
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                continue

        # Detect changes
        print(f"  Detecting changes...")
        try:
            changes = detect_changes(conn, date_str)
            print(f"  {changes} changes detected")
        except Exception as e:
            print(f"  ERROR detecting changes: {e}", file=sys.stderr)

    # Measure lift for pending events
    if not args.skip_lift:
        print("\nMeasuring lift for pending events...")
        try:
            measured = measure_lift(conn)
            print(f"  {measured} events measured")
        except Exception as e:
            print(f"  ERROR measuring lift: {e}", file=sys.stderr)

    # Summary
    total_snaps = conn.execute("SELECT COUNT(*) FROM ad_daily_snapshots").fetchone()[0]
    total_changes = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    total_measured = conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE lift_status = 'measured'").fetchone()[0]
    print(f"\nSummary: {total_snaps} snapshots, {total_changes} changes, {total_measured} measured")

    conn.close()


if __name__ == "__main__":
    main()
