"""Unified CLI entry point for Creative Intelligence v3."""

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
