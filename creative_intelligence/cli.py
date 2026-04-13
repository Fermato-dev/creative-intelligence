"""Unified CLI entry point for Creative Intelligence v3.5."""

import json
import os
import sys
from datetime import datetime

from .config import DATA_DIR


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return

    command = args[0]

    if command in ("run", "report", "--days", "--json", "--csv"):
        _run_report(args if command != "run" else args[1:])
    elif command == "weekly":
        _run_weekly(args[1:])
    elif command == "decompose":
        _run_decompose(args[1:])
    elif command == "components":
        _show_components(args[1:])
    elif command == "recommend":
        _run_recommend(args[1:])
    elif command == "voice":
        _run_voice(args[1:])
    elif command == "briefs":
        _run_briefs(args[1:])
    elif command == "scores":
        _run_scores(args[1:])
    elif command == "shifts":
        _run_shifts(args[1:])
    elif command == "leaderboard":
        _run_leaderboard(args[1:])
    elif command == "tag":
        _run_tag(args[1:])
    elif command == "compare":
        _run_compare(args[1:])
    elif command == "dashboard":
        _run_dashboard(args[1:])
    else:
        # Default: treat as report args
        _run_report(args)


def _print_help():
    print("""
Creative Intelligence v3 — Fermato Meta Ads

Pouziti:
  python -m creative_intelligence [command] [options]

Commands:
  run [--days N] [--json] [--csv]   Spust analyzu a vygeneruj report (default)
  weekly [--days N] [--no-pumble]   Plny tydenni beh (report + decompose + recommend + pumble)
  decompose [--days N] [--limit N]  Rozloz videa na hook/body/CTA a uloz do knihovny
  components [--type hook|body|cta] Zobraz komponentni knihovnu
  recommend                         Vygeneruj kombinatoricka doporuceni
  voice [--product X]               Customer Voice Mining — psychologicky profil z recenzi
  briefs [--product X] [--with-mining]  Germain pipeline — 4 paralelni creative briefy
  scores [--days N]                 Funnel scores (Hook/Watch/Click/Convert 1-100)
  shifts [--days N]                 Performance shifts (Scaling/Declining/New/Paused)
  leaderboard [--days N] [--top N]  Creative leaderboard s rank tracking
  tag [--force]                     AI visual format tagging (Claude Vision)
  compare [--days N]                Comparative analysis (ad type, format, messaging)
  dashboard [--days N] [--open]     Generate HTML dashboard
  help                              Tato napoveda

Options:
  --days N          Pocet dni dat (default: 14 pro report, 7 pro weekly)
  --json            JSON output
  --csv             CSV output
  --no-pumble       Neposilej Pumble notifikaci
  --limit N         Max pocet kreativ k analyze
  --product X       Produkt (zalivka, chilli, crunch, simrato, naley, napivo)
  --with-mining     Spusti i voice mining pred generovanim briefu
""")


def _run_report(args):
    """Generate creative intelligence report."""
    from . import metrics, report

    days = 14
    output_format = "report"
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            output_format = "json"
            i += 1
        elif args[i] == "--csv":
            output_format = "csv"
            i += 1
        else:
            i += 1

    print(f"Stahuji ad-level data za poslednich {days} dni...", file=sys.stderr)
    raw_data = metrics.fetch_ad_insights(days)
    print(f"Stazeno {len(raw_data)} ad records.", file=sys.stderr)

    ads_metrics = [metrics.calculate_metrics(row) for row in raw_data]
    ads_metrics.sort(key=lambda x: x["spend"], reverse=True)

    if output_format == "json":
        from .rules import evaluate_creative
        for m in ads_metrics:
            m["recommendations"] = [
                {"action": a, "reason": r, "detail": d}
                for a, r, d in evaluate_creative(m)
            ]
        print(json.dumps(ads_metrics, indent=2, ensure_ascii=False))
    elif output_format == "csv":
        print(report.export_csv(ads_metrics))
    else:
        text = report.generate_report(ads_metrics)
        print(text)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / f"creative-intelligence-{datetime.now().strftime('%Y-%m-%d')}.txt"
        path.write_text(text, encoding="utf-8")
        print(f"\nReport ulozen: {path}", file=sys.stderr)


def _run_weekly(args):
    """Run full weekly pipeline."""
    from .runner import main as run_weekly

    days = 7
    do_pumble = True
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--no-pumble":
            do_pumble = False
            i += 1
        else:
            i += 1

    run_weekly(days=days, do_pumble=do_pumble)


def _run_decompose(args):
    """Run scene decomposition on top video ads."""
    from . import metrics
    from .decomposition import download_and_decompose
    from .component_db import get_db, build_library_from_analysis, print_library_summary
    from .meta_client import meta_fetch

    days = 7
    limit = 10
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1

    print(f"Stahuji data za {days} dni...", file=sys.stderr)
    raw_data = metrics.fetch_ad_insights(days)
    ads_metrics = [metrics.calculate_metrics(row) for row in raw_data]

    video_ads = sorted(
        [ad for ad in ads_metrics if ad["is_video"] and ad["spend"] > 200],
        key=lambda x: x["spend"], reverse=True
    )[:limit]

    print(f"Decomposing {len(video_ads)} videi...", file=sys.stderr)
    conn = get_db()
    decomposed = 0

    for ad in video_ads:
        try:
            data = meta_fetch(ad["ad_id"], {"fields": "creative{video_id}"})
            video_id = data.get("creative", {}).get("video_id")
            if not video_id:
                continue

            print(f"\n  {ad['ad_name'][:40]} (spend {ad['spend']:,.0f}, ROAS {ad['roas']})...", file=sys.stderr)
            result = download_and_decompose(ad["ad_id"], video_id, performance=ad)
            if result:
                build_library_from_analysis(conn, ad["ad_id"], result, ad)
                decomposed += 1
                print(f"  OK", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)

    print(f"\nDecomposed: {decomposed}/{len(video_ads)}", file=sys.stderr)
    print_library_summary(conn)
    conn.close()


def _show_components(args):
    """Show component library."""
    from .component_db import get_db, get_top_components, print_library_summary

    comp_type = None
    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            comp_type = args[i + 1]
            i += 2
        else:
            i += 1

    conn = get_db()
    print_library_summary(conn)

    if comp_type:
        print(f"\nTop {comp_type}s (by {'hook_rate' if comp_type == 'hook' else 'hold_rate' if comp_type == 'body' else 'cvr'}):")
        metric = "hook_rate" if comp_type == "hook" else "hold_rate" if comp_type == "body" else "cvr"
        top = get_top_components(conn, comp_type, metric=metric, limit=15)
        for i, c in enumerate(top, 1):
            val = c.get(metric)
            val_str = f"{val:.1f}" if val else "—"
            roas = f"{c['roas']:.2f}" if c.get('roas') else "—"
            print(f"  {i:>3}. {c['ad_name'][:35]:<35} {metric}={val_str:>6} ROAS={roas:>6} spend={c.get('spend', 0):>8,.0f}")

    conn.close()


def _run_recommend(args):
    """Generate combinatorial recommendations."""
    from .component_db import get_db
    from .combinator import generate_all_recommendations, format_recommendations_report

    conn = get_db()
    results = generate_all_recommendations(conn)
    text = format_recommendations_report(results)
    print(text)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"recommendations-{datetime.now().strftime('%Y-%m-%d')}.txt"
    path.write_text(text, encoding="utf-8")
    print(f"\nUlozeno: {path}", file=sys.stderr)

    conn.close()


def _run_voice(args):
    """Run Customer Voice Mining."""
    from .voice import run_voice_mining

    product = "zalivka"
    output_format = "text"
    i = 0
    while i < len(args):
        if args[i] == "--product" and i + 1 < len(args):
            product = args[i + 1]
            i += 2
        elif args[i] == "--json":
            output_format = "json"
            i += 1
        else:
            i += 1

    profile, cost = run_voice_mining(product, output_format)
    if profile and output_format == "json":
        print(json.dumps(profile, indent=2, ensure_ascii=False))
    elif profile:
        print(f"\nProfil vygenerovan pro '{product}'. Cost: ${cost:.4f}", file=sys.stderr)


def _run_briefs(args):
    """Run Germain Creative Briefs pipeline."""
    from .briefs import run_briefs_pipeline

    product = "zalivka"
    with_mining = False
    i = 0
    while i < len(args):
        if args[i] == "--product" and i + 1 < len(args):
            product = args[i + 1]
            i += 2
        elif args[i] == "--with-mining":
            with_mining = True
            i += 1
        else:
            i += 1

    briefs, cost = run_briefs_pipeline(product, with_mining=with_mining)
    if briefs:
        from .briefs import format_briefs_report
        print(format_briefs_report(briefs))


def _run_scores(args):
    """Calculate and display funnel scores."""
    from . import metrics
    from .funnel_scores import score_all_ads, save_funnel_scores, init_funnel_scores_schema
    from .component_db import get_db

    days = _parse_arg(args, "--days", 14)

    print(f"Stahuji data za {days} dni...", file=sys.stderr)
    raw_data = metrics.fetch_ad_insights(days)
    ads_metrics = [metrics.calculate_metrics(row) for row in raw_data]

    scored = score_all_ads(ads_metrics)
    scored.sort(key=lambda x: x.get("overall_score") or 0, reverse=True)

    # Save to DB
    conn = get_db()
    init_funnel_scores_schema(conn)
    date_str = datetime.now().strftime("%Y-%m-%d")
    saved = save_funnel_scores(conn, scored, date_str)
    conn.close()

    # Print
    print(f"\n{'Ad Name':<35} {'Hook':>5} {'Watch':>6} {'Click':>6} {'Conv':>5} {'Score':>6}  {'ROAS':>6} {'Spend':>10}")
    print("-" * 90)
    for ad in scored[:25]:
        if ad["spend"] < 100:
            continue
        h = f"{ad['hook_score']:>3}{ad['hook_grade']}" if ad.get("hook_score") is not None else "  --"
        w = f"{ad['watch_score']:>3}{ad['watch_grade']}" if ad.get("watch_score") is not None else "   --"
        cl = f"{ad['click_score']:>3}{ad['click_grade']}" if ad.get("click_score") is not None else "   --"
        cv = f"{ad['convert_score']:>3}{ad['convert_grade']}" if ad.get("convert_score") is not None else "  --"
        ov = f"{ad['overall_score']:>3}{ad['overall_grade']}" if ad.get("overall_score") is not None else "   --"
        roas = f"{ad['roas']:.2f}" if ad.get("roas") else "N/A"
        print(f"{ad['ad_name'][:35]:<35} {h:>5} {w:>6} {cl:>6} {cv:>5} {ov:>6}  {roas:>6} {ad['spend']:>10,.0f}")

    print(f"\nScores saved: {saved}", file=sys.stderr)


def _run_shifts(args):
    """Show performance shifts."""
    from .performance_shifts import categorize_performance_shifts, format_shifts_report
    from .component_db import get_db
    from .change_tracker import init_change_tracking_schema

    conn = get_db()
    init_change_tracking_schema(conn)
    shifts = categorize_performance_shifts(conn)
    print(format_shifts_report(shifts))
    conn.close()


def _run_leaderboard(args):
    """Show creative leaderboard."""
    from .leaderboard import generate_leaderboard, save_leaderboard, format_leaderboard_report, init_leaderboard_schema
    from .component_db import get_db

    days = _parse_arg(args, "--days", 7)
    top = _parse_arg(args, "--top", 15)

    conn = get_db()
    init_leaderboard_schema(conn)
    lb = generate_leaderboard(conn, days=days, limit=top)

    # Save
    week_start = (datetime.now() - __import__("datetime").timedelta(days=days - 1)).strftime("%Y-%m-%d")
    save_leaderboard(conn, lb, week_start)

    print(format_leaderboard_report(lb, top_n=top))
    conn.close()


def _run_tag(args):
    """Run AI visual format tagging."""
    from . import metrics
    from .visual_tagger import batch_tag_creatives, init_creative_tags_schema, get_format_distribution
    from .component_db import get_db

    force = "--force" in args

    limit = _parse_arg(args, "--limit", 30)
    print("Stahuji creative metadata...", file=sys.stderr)
    creatives = metrics.fetch_ad_creatives()
    # Filter to ACTIVE only for cost efficiency
    active = [c for c in creatives if c.get("effective_status") == "ACTIVE"]
    creatives_to_tag = active[:limit] if active else creatives[:limit]
    print(f"Nalezeno {len(creatives)} ads, tagging {len(creatives_to_tag)} (active, limit {limit}).", file=sys.stderr)

    conn = get_db()
    init_creative_tags_schema(conn)
    tagged = batch_tag_creatives(conn, creatives_to_tag, force=force)
    print(f"\nTagged: {tagged} ads", file=sys.stderr)

    # Show distribution
    dist = get_format_distribution(conn)
    if dist:
        print("\nVisual Format Distribution:")
        for d in dist:
            print(f"  {d['visual_format']}: {d['count']} ads")

    conn.close()


def _run_compare(args):
    """Run comparative analysis."""
    from .comparative import (
        compare_ad_types, compare_visual_formats,
        compare_messaging_angles, compare_ad_lengths,
        analyze_landing_pages, format_comparative_report,
    )
    from .component_db import get_db

    days = _parse_arg(args, "--days", 14)

    conn = get_db()
    ad_types = compare_ad_types(conn, days)
    visual_formats = compare_visual_formats(conn, days)
    messaging_angles = compare_messaging_angles(conn, days)
    ad_lengths = compare_ad_lengths(conn, days)
    landing_pages = analyze_landing_pages(conn, days)

    print(format_comparative_report(ad_types, visual_formats, messaging_angles, ad_lengths, landing_pages))
    conn.close()


def _run_dashboard(args):
    """Generate HTML dashboard."""
    from .dashboard import generate_dashboard
    from .component_db import get_db

    days = _parse_arg(args, "--days", 14)
    do_open = "--open" in args

    conn = get_db()
    path = generate_dashboard(conn, days=days)
    conn.close()

    print(f"Dashboard generated: {path}", file=sys.stderr)
    if do_open:
        import webbrowser
        webbrowser.open(f"file:///{path}")


def _parse_arg(args, flag, default):
    """Parse a CLI argument with a default value."""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return int(args[i + 1])
    return default
