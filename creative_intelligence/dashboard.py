"""CI Dashboard Generator — single-file HTML dashboard.

Generates a visual dashboard inspired by Motion App with:
- Week at a glance (KPIs + WoW deltas)
- Performance shifts (Scaling/Declining/New/Paused)
- Creative leaderboard with rank tracking
- Funnel scores heatmap
- Comparative analysis (ad type, visual format, messaging)

Output: single HTML file with embedded Chart.js, dark theme.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import DB_PATH, DATA_DIR, AD_ACCOUNT_ID
from .funnel_scores import GRADES

# Meta Ads Manager link template
_ACT_ID = AD_ACCOUNT_ID.replace("act_", "")
ADS_MANAGER_URL = f"https://adsmanager.facebook.com/adsmanager/manage/ads?act={_ACT_ID}&selected_ad_ids="


def generate_dashboard(conn, days=14, output_path=None):
    """Generate complete HTML dashboard.

    Args:
        conn: SQLite connection to creative_analysis.db
        days: lookback period
        output_path: where to save HTML (default: data/ci-dashboard.html)

    Returns:
        path to generated HTML file
    """
    if output_path is None:
        output_path = DATA_DIR / "ci-dashboard.html"

    data = _collect_dashboard_data(conn, days)
    html = _render_html(data, days)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return str(output_path)


def _collect_dashboard_data(conn, days):
    """Collect all data needed for dashboard rendering."""
    ref = datetime.now().strftime("%Y-%m-%d")
    ref_dt = datetime.now()
    since = (ref_dt - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    prev_since = (ref_dt - timedelta(days=days * 2 - 1)).strftime("%Y-%m-%d")
    prev_until = (ref_dt - timedelta(days=days)).strftime("%Y-%m-%d")

    data = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "days": days}

    # ── Summary KPIs ──
    tw = conn.execute("""
        SELECT SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases, SUM(impressions) as impressions,
               COUNT(DISTINCT ad_id) as ad_count
        FROM ad_daily_snapshots WHERE snapshot_date BETWEEN ? AND ?
    """, (since, ref)).fetchone()

    lw = conn.execute("""
        SELECT SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases
        FROM ad_daily_snapshots WHERE snapshot_date BETWEEN ? AND ?
    """, (prev_since, prev_until)).fetchone()

    tw_spend = tw["spend"] or 0 if tw else 0
    lw_spend = lw["spend"] or 0 if lw else 0
    tw_rev = tw["revenue"] or 0 if tw else 0
    lw_rev = lw["revenue"] or 0 if lw else 0
    tw_roas = tw_rev / tw_spend if tw_spend > 0 else 0
    lw_roas = lw_rev / lw_spend if lw_spend > 0 else 0
    tw_purchases = tw["purchases"] or 0 if tw else 0

    data["summary"] = {
        "spend": round(tw_spend),
        "spend_delta": _pct(tw_spend, lw_spend),
        "roas": round(tw_roas, 2),
        "roas_delta": _pct(tw_roas, lw_roas),
        "purchases": tw_purchases,
        "ad_count": tw["ad_count"] if tw else 0,
    }

    # ── Performance Shifts ──
    try:
        from .performance_shifts import categorize_performance_shifts
        shifts = categorize_performance_shifts(conn, ref)
        data["shifts"] = {
            "scaling": [_trim_shift(s) for s in shifts["scaling"][:8]],
            "declining": [_trim_shift(s) for s in shifts["declining"][:8]],
            "newly_launched": shifts["newly_launched"][:8],
            "recently_paused": shifts["recently_paused"][:8],
            "counts": {
                "scaling": len(shifts["scaling"]),
                "declining": len(shifts["declining"]),
                "new": len(shifts["newly_launched"]),
                "paused": len(shifts["recently_paused"]),
            }
        }
    except Exception:
        data["shifts"] = {"scaling": [], "declining": [], "newly_launched": [],
                          "recently_paused": [], "counts": {}}

    # ── Leaderboard ──
    try:
        from .leaderboard import generate_leaderboard
        data["leaderboard"] = [_trim_lb(e) for e in generate_leaderboard(conn, days=days, limit=15)]
    except Exception:
        data["leaderboard"] = []

    # ── Funnel Scores ──
    try:
        has_tags = conn.execute(
            "SELECT count(*) as c FROM sqlite_master WHERE type='table' AND name='creative_tags'"
        ).fetchone()["c"] > 0

        if has_tags:
            scores = conn.execute("""
                SELECT fs.ad_id, fs.ad_name, fs.is_video,
                       fs.hook_score, fs.watch_score, fs.click_score, fs.convert_score, fs.overall_score,
                       fs.hook_grade, fs.watch_grade, fs.click_grade, fs.convert_grade, fs.overall_grade,
                       fs.roas, fs.spend,
                       ct.thumbnail_url, ct.visual_format, ct.messaging_angle
                FROM funnel_scores fs
                LEFT JOIN creative_tags ct ON fs.ad_id = ct.ad_id
                WHERE fs.snapshot_date = (SELECT MAX(snapshot_date) FROM funnel_scores)
                  AND fs.spend >= 100
                ORDER BY fs.overall_score DESC
                LIMIT 20
            """).fetchall()
        else:
            scores = conn.execute("""
                SELECT ad_id, ad_name, is_video,
                       hook_score, watch_score, click_score, convert_score, overall_score,
                       hook_grade, watch_grade, click_grade, convert_grade, overall_grade,
                       roas, spend
                FROM funnel_scores
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM funnel_scores)
                  AND spend >= 100
                ORDER BY overall_score DESC
                LIMIT 20
            """).fetchall()
        data["funnel_scores"] = [dict(r) for r in scores]
    except Exception:
        data["funnel_scores"] = []

    # ── Thumbnail map for leaderboard ──
    try:
        if has_tags:
            thumbs = conn.execute(
                "SELECT ad_id, thumbnail_url FROM creative_tags WHERE thumbnail_url IS NOT NULL"
            ).fetchall()
            data["thumbnails"] = {r["ad_id"]: r["thumbnail_url"] for r in thumbs}
        else:
            data["thumbnails"] = {}
    except Exception:
        data["thumbnails"] = {}

    # ── Ad Type Comparison ──
    try:
        from .comparative import compare_ad_types
        data["ad_types"] = compare_ad_types(conn, days)
    except Exception:
        data["ad_types"] = []

    # ── Visual Format Comparison ──
    try:
        from .comparative import compare_visual_formats
        data["visual_formats"] = compare_visual_formats(conn, days)
    except Exception:
        data["visual_formats"] = []

    # ── Messaging Angles ──
    try:
        from .comparative import compare_messaging_angles
        data["messaging_angles"] = compare_messaging_angles(conn, days)
    except Exception:
        data["messaging_angles"] = []

    # ── Top Hooks (video only) ──
    try:
        if has_tags:
            hooks = conn.execute("""
                SELECT fs.ad_id, fs.ad_name, fs.hook_score, fs.hook_grade,
                       fs.watch_score, fs.watch_grade,
                       fs.hook_rate, fs.hold_rate, fs.roas, fs.spend,
                       ct.thumbnail_url, ct.hook_type, ct.visual_format
                FROM funnel_scores fs
                LEFT JOIN creative_tags ct ON fs.ad_id = ct.ad_id
                WHERE fs.snapshot_date = (SELECT MAX(snapshot_date) FROM funnel_scores)
                  AND fs.is_video = 1 AND fs.spend >= 200 AND fs.hook_score IS NOT NULL
                ORDER BY fs.hook_score DESC
                LIMIT 15
            """).fetchall()
        else:
            hooks = conn.execute("""
                SELECT ad_id, ad_name, hook_score, hook_grade,
                       watch_score, watch_grade,
                       hook_rate, hold_rate, roas, spend
                FROM funnel_scores
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM funnel_scores)
                  AND is_video = 1 AND spend >= 200 AND hook_score IS NOT NULL
                ORDER BY hook_score DESC
                LIMIT 15
            """).fetchall()
        data["top_hooks"] = [dict(r) for r in hooks]
    except Exception:
        data["top_hooks"] = []

    # ── Landing Pages ──
    try:
        from .comparative import analyze_landing_pages
        data["landing_pages"] = analyze_landing_pages(conn, days)
    except Exception:
        data["landing_pages"] = []

    # ── Recommendations ──
    try:
        recs = conn.execute("""
            SELECT rec_type, description, details, created_at, status
            FROM recommendations
            WHERE status != 'dismissed'
            ORDER BY created_at DESC
            LIMIT 8
        """).fetchall()
        data["recommendations"] = [dict(r) for r in recs]
    except Exception:
        data["recommendations"] = []

    # ── Daily Spend Trend ──
    try:
        daily = conn.execute("""
            SELECT snapshot_date, SUM(spend) as spend, SUM(revenue) as revenue
            FROM ad_daily_snapshots
            WHERE snapshot_date >= date(?, '-30 days')
            GROUP BY snapshot_date
            ORDER BY snapshot_date
        """, (ref,)).fetchall()
        data["daily_trend"] = [
            {"date": r["snapshot_date"], "spend": round(r["spend"] or 0),
             "revenue": round(r["revenue"] or 0)}
            for r in daily
        ]
    except Exception:
        data["daily_trend"] = []

    return data


def _pct(current, previous):
    if previous and previous > 0 and current is not None:
        return round(((current - previous) / previous) * 100, 1)
    return None


def _trim_shift(s):
    return {k: s[k] for k in ("ad_id", "ad_name", "spend_delta", "roas_delta",
                                "this_week_spend", "this_week_roas") if k in s}


def _trim_lb(e):
    return {k: e[k] for k in ("rank", "ad_id", "ad_name", "ad_type", "spend", "spend_delta",
                                "roas", "roas_delta", "wks_on_board", "rank_change",
                                "is_new_entry", "overall_score", "purchases") if k in e}


# ══════════════════════════════════════════════════════
# HTML RENDERING
# ══════════════════════════════════════════════════════

def _render_html(data, days):
    """Render complete HTML dashboard."""
    d = data
    s = d.get("summary", {})
    shifts = d.get("shifts", {})
    counts = shifts.get("counts", {})

    # Delta formatters
    def delta_html(val, invert=False):
        if val is None:
            return '<span class="delta neutral">--</span>'
        cls = "positive" if (val >= 0) != invert else "negative"
        sign = "+" if val >= 0 else ""
        return f'<span class="delta {cls}">{sign}{val:.0f}%</span>'

    def grade_badge(score, grade):
        if score is None or grade is None:
            return '<span class="grade na">--</span>'
        color = GRADES.get(grade, GRADES["F"])["color"]
        return f'<span class="grade" style="background:{color};color:#000">{score}{grade}</span>'

    def ad_link(ad_id, ad_name, max_len=30):
        """Render ad name as clickable link to Ads Manager."""
        name = (ad_name or ad_id or "?")[:max_len]
        if ad_id:
            return f'<a href="{ADS_MANAGER_URL}{ad_id}" target="_blank" class="ad-link" title="{ad_name or ad_id}">{name}</a>'
        return name

    # Thumbnail map for all sections
    thumbs = d.get("thumbnails", {})

    # Build sections
    kpi_html = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Spend</div>
        <div class="kpi-value">{s.get('spend',0):,.0f} Kc</div>
        {delta_html(s.get('spend_delta'))}
      </div>
      <div class="kpi-card">
        <div class="kpi-label">ROAS</div>
        <div class="kpi-value">{s.get('roas',0):.2f}</div>
        {delta_html(s.get('roas_delta'))}
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Purchases</div>
        <div class="kpi-value">{s.get('purchases',0):,}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Active Ads</div>
        <div class="kpi-value">{s.get('ad_count',0)}</div>
      </div>
    </div>"""

    # Performance shifts
    shift_tabs = f"""
    <div class="shift-tabs">
      <button class="shift-tab active" onclick="showShift('scaling')">Scaling <span class="badge green">{counts.get('scaling',0)}</span></button>
      <button class="shift-tab" onclick="showShift('declining')">Declining <span class="badge red">{counts.get('declining',0)}</span></button>
      <button class="shift-tab" onclick="showShift('new')">New <span class="badge blue">{counts.get('new',0)}</span></button>
      <button class="shift-tab" onclick="showShift('paused')">Paused <span class="badge gray">{counts.get('paused',0)}</span></button>
    </div>"""

    def shift_cards(items, kind):
        if not items:
            return f'<div class="shift-panel" id="shift-{kind}"><p class="muted">No data</p></div>'
        cards = ""
        for item in items[:6]:
            aid = item.get("ad_id", "")
            name_link = ad_link(aid, item.get("ad_name"), 35)
            t_url = thumbs.get(aid, "")
            th = f'<img class="thumb" src="{t_url}" loading="lazy" onerror="this.style.display=\'none\'">' if t_url else ""
            if kind in ("scaling", "declining"):
                spend_d = delta_html(item.get("spend_delta"))
                roas_val = item.get("this_week_roas")
                roas_str = f"{roas_val:.2f}" if roas_val else "N/A"
                roas_d = delta_html(item.get("roas_delta"))
                cards += f"""<div class="shift-card">
                  <div class="ad-cell">{th}<div>
                    <div class="shift-name">{name_link}</div>
                    <div>Spend {spend_d} | ROAS {roas_str} {roas_d}</div>
                  </div></div>
                </div>"""
            elif kind == "new":
                spend = item.get("spend", 0)
                days_l = item.get("days_since_launch", "?")
                roas_val = item.get("roas")
                roas_str = f"ROAS {roas_val:.2f}" if roas_val else "no conv"
                cards += f"""<div class="shift-card">
                  <div class="ad-cell">{th}<div>
                    <div class="shift-name">{name_link}</div>
                    <div>{days_l}d | {spend:,.0f} Kc | {roas_str}</div>
                  </div></div>
                </div>"""
            else:
                days_s = item.get("days_since_seen", "?")
                cards += f"""<div class="shift-card">
                  <div class="ad-cell">{th}<div>
                    <div class="shift-name">{name_link}</div>
                    <div>Paused {days_s}d ago</div>
                  </div></div>
                </div>"""
        vis = "block" if kind == "scaling" else "none"
        return f'<div class="shift-panel" id="shift-{kind}" style="display:{vis}">{cards}</div>'

    shifts_html = shift_tabs + shift_cards(shifts.get("scaling", []), "scaling")
    shifts_html += shift_cards(shifts.get("declining", []), "declining")
    shifts_html += shift_cards(shifts.get("newly_launched", []), "new")
    shifts_html += shift_cards(shifts.get("recently_paused", []), "paused")

    # Leaderboard
    lb_rows = ""
    for e in d.get("leaderboard", []):
        rc = e.get("rank_change")
        if e.get("is_new_entry"):
            indicator = '<span class="badge blue">NEW</span>'
        elif rc and rc > 0:
            indicator = f'<span class="delta positive">&#9650;{rc}</span>'
        elif rc and rc < 0:
            indicator = f'<span class="delta negative">&#9660;{abs(rc)}</span>'
        else:
            indicator = '<span class="delta neutral">=</span>'

        roas = f"{e['roas']:.2f}" if e.get("roas") else "N/A"
        roas_d = delta_html(e.get("roas_delta"))
        spend_d = delta_html(e.get("spend_delta"))
        wks = e.get("wks_on_board", 1)
        wks_str = f"{wks}w" if wks <= 6 else "6w+"
        score = e.get("overall_score")
        score_html = f'<span class="score-pill">{score}</span>' if score else "--"

        thumb_html = ""
        t_url = thumbs.get(e.get("ad_id", ""))
        if t_url:
            thumb_html = f'<img class="thumb" src="{t_url}" loading="lazy" onerror="this.style.display=\'none\'">'

        lb_rows += f"""<tr>
          <td class="rank">{e['rank']}</td>
          <td><div class="ad-cell">{thumb_html}{ad_link(e.get('ad_id'), e.get('ad_name'))}</div></td>
          <td>{e.get('ad_type','?')[:3]}</td>
          <td>{wks_str}</td>
          <td class="num">{e.get('spend',0):,.0f} {spend_d}</td>
          <td class="num">{roas} {roas_d}</td>
          <td>{score_html}</td>
          <td>{indicator}</td>
        </tr>"""

    leaderboard_html = f"""
    <table class="data-table">
      <thead><tr>
        <th>#</th><th>Creative</th><th>Type</th><th>Wks</th>
        <th>Spend</th><th>ROAS</th><th>Score</th><th></th>
      </tr></thead>
      <tbody>{lb_rows}</tbody>
    </table>"""

    # Funnel scores heatmap
    fs_rows = ""
    for f in d.get("funnel_scores", []):
        name_link = ad_link(f.get("ad_id"), f.get("ad_name"))
        t_url = f.get("thumbnail_url") or thumbs.get(f.get("ad_id", ""))
        thumb_html = f'<img class="thumb" src="{t_url}" loading="lazy" onerror="this.style.display=\'none\'">' if t_url else ""
        vf = f.get("visual_format", "")
        ma = f.get("messaging_angle", "")
        tags_html = f'<div class="meta-tags">{vf.replace("_"," ")} / {ma.replace("_"," ")}</div>' if vf else ""
        cell = f'<div class="ad-cell">{thumb_html}<div>{name_link}{tags_html}</div></div>'
        h = grade_badge(f.get("hook_score"), f.get("hook_grade"))
        w = grade_badge(f.get("watch_score"), f.get("watch_grade"))
        c = grade_badge(f.get("click_score"), f.get("click_grade"))
        cv = grade_badge(f.get("convert_score"), f.get("convert_grade"))
        o = grade_badge(f.get("overall_score"), f.get("overall_grade"))
        roas = f"{f['roas']:.2f}" if f.get("roas") else "N/A"
        fs_rows += f"<tr><td>{cell}</td><td>{h}</td><td>{w}</td><td>{c}</td><td>{cv}</td><td>{o}</td><td class='num'>{roas}</td></tr>"

    funnel_html = f"""
    <table class="data-table">
      <thead><tr>
        <th>Creative</th><th>Hook</th><th>Watch</th><th>Click</th><th>Convert</th><th>Overall</th><th>ROAS</th>
      </tr></thead>
      <tbody>{fs_rows}</tbody>
    </table>"""

    # Ad type comparison chart data
    at_labels = json.dumps([t["ad_type"] for t in d.get("ad_types", [])])
    at_spend = json.dumps([t["total_spend"] for t in d.get("ad_types", [])])
    at_roas = json.dumps([t.get("avg_roas") or 0 for t in d.get("ad_types", [])])

    # Visual format chart data
    vf_labels = json.dumps([f["visual_format"].replace("_", " ") for f in d.get("visual_formats", [])][:10])
    vf_roas = json.dumps([f.get("avg_roas") or 0 for f in d.get("visual_formats", [])][:10])
    vf_count = json.dumps([f["count"] for f in d.get("visual_formats", [])][:10])

    # Daily trend
    dt_labels = json.dumps([t["date"][-5:] for t in d.get("daily_trend", [])])
    dt_spend = json.dumps([t["spend"] for t in d.get("daily_trend", [])])
    dt_revenue = json.dumps([t["revenue"] for t in d.get("daily_trend", [])])

    return f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Creative Intelligence Dashboard | Fermato</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg: #0a0a0f;
  --surface: #12121a;
  --surface2: #1a1a26;
  --border: #2a2a3a;
  --text: #e4e4ef;
  --text-muted: #8888a0;
  --accent: #6366f1;
  --green: #22c55e;
  --green-light: #86efac;
  --yellow: #facc15;
  --orange: #fb923c;
  --red: #ef4444;
  --blue: #3b82f6;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
  background: var(--bg);
  color: var(--text);
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  font-size: 13px;
  line-height: 1.5;
}}
h1 {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
h2 {{
  font-size: 14px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 1px; color: var(--accent); margin-bottom: 12px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border);
}}
.header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 24px; }}
.header .meta {{ color: var(--text-muted); font-size: 11px; }}
.section {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 20px; }}

/* KPI Grid */
.kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
.kpi-card {{ background: var(--surface2); border-radius: 8px; padding: 16px; text-align: center; }}
.kpi-label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 24px; font-weight: 700; margin: 4px 0; }}

/* Deltas */
.delta {{ font-size: 12px; font-weight: 600; }}
.delta.positive {{ color: var(--green); }}
.delta.negative {{ color: var(--red); }}
.delta.neutral {{ color: var(--text-muted); }}

/* Badges */
.badge {{ font-size: 11px; padding: 2px 6px; border-radius: 10px; font-weight: 600; }}
.badge.green {{ background: rgba(34,197,94,0.15); color: var(--green); }}
.badge.red {{ background: rgba(239,68,68,0.15); color: var(--red); }}
.badge.blue {{ background: rgba(59,130,246,0.15); color: var(--blue); }}
.badge.gray {{ background: rgba(136,136,160,0.15); color: var(--text-muted); }}

/* Shift tabs */
.shift-tabs {{ display: flex; gap: 8px; margin-bottom: 12px; }}
.shift-tab {{
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text-muted); padding: 6px 14px; border-radius: 6px;
  cursor: pointer; font-family: inherit; font-size: 12px;
}}
.shift-tab.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
.shift-panel {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.shift-card {{
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; min-width: 200px; flex: 1;
}}
.shift-name {{ font-weight: 600; margin-bottom: 4px; font-size: 12px; }}

/* Tables */
.data-table {{ width: 100%; border-collapse: collapse; }}
.data-table th {{
  text-align: left; font-size: 11px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px;
  padding: 8px 10px; border-bottom: 1px solid var(--border);
}}
.data-table td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 12px; }}
.data-table tr:hover {{ background: var(--surface2); }}
.data-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.data-table .rank {{ font-weight: 700; width: 30px; }}

/* Grade badges */
.grade {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-weight: 700; font-size: 11px; min-width: 36px; text-align: center;
}}
.grade.na {{ background: var(--surface2); color: var(--text-muted); }}
.score-pill {{
  background: var(--accent); color: white; padding: 2px 8px;
  border-radius: 10px; font-size: 11px; font-weight: 600;
}}

/* Charts */
.chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.chart-box {{ background: var(--surface2); border-radius: 8px; padding: 16px; }}
.chart-box h3 {{ font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }}
canvas {{ max-height: 260px; }}

.muted {{ color: var(--text-muted); font-style: italic; }}

/* Ad links */
.ad-link {{
  color: var(--text); text-decoration: none;
  border-bottom: 1px dotted var(--text-muted);
  transition: color 0.15s, border-color 0.15s;
}}
.ad-link:hover {{
  color: var(--accent); border-bottom-color: var(--accent);
}}

/* Thumbnails */
.thumb {{
  width: 40px; height: 40px; border-radius: 4px;
  object-fit: cover; vertical-align: middle; margin-right: 8px;
  border: 1px solid var(--border); background: var(--surface2);
}}
.thumb-lg {{
  width: 52px; height: 52px; border-radius: 6px;
  object-fit: cover; vertical-align: middle; margin-right: 10px;
  border: 1px solid var(--border); background: var(--surface2);
}}
.ad-cell {{ display: flex; align-items: center; gap: 8px; }}
.ad-cell .meta-tags {{ font-size: 10px; color: var(--text-muted); }}

/* Recommendations */
.recs-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }}
.rec-card {{
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; border-left: 3px solid var(--accent);
}}
.rec-swap {{ border-left-color: var(--yellow); }}
.rec-new {{ border-left-color: var(--green); }}
.rec-alert {{ border-left-color: var(--orange); }}
.rec-type {{ font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 4px; }}
.rec-desc {{ font-size: 12px; line-height: 1.4; }}

@media (max-width: 768px) {{
  .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .chart-grid {{ grid-template-columns: 1fr; }}
  .shift-panel {{ flex-direction: column; }}
}}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Creative Intelligence Dashboard</h1>
    <span class="meta">Fermato CZ | Last {days} days | {d['generated_at']}</span>
  </div>
</div>

<div class="section">
  <h2>This Week at a Glance</h2>
  {kpi_html}
</div>

<div class="section">
  <h2>Performance Shifts</h2>
  {shifts_html}
</div>

<div class="section">
  <h2>Creative Leaderboard</h2>
  {leaderboard_html}
</div>

<div class="section">
  <h2>Funnel Scores</h2>
  {funnel_html}
</div>

<div class="section">
  <h2>Comparative Analysis</h2>
  <div class="chart-grid">
    <div class="chart-box">
      <h3>Ad Type — Spend vs ROAS</h3>
      <canvas id="chartAdType"></canvas>
    </div>
    <div class="chart-box">
      <h3>Visual Format — ROAS</h3>
      <canvas id="chartVisualFormat"></canvas>
    </div>
    <div class="chart-box" style="grid-column: span 2">
      <h3>Daily Spend & Revenue (30d)</h3>
      <canvas id="chartDailyTrend"></canvas>
    </div>
  </div>
</div>

<div class="section">
  <h2>Top Hooks (Video)</h2>
  <p class="muted" style="margin-bottom:12px">Best-performing video hooks — first 3 seconds that stop the scroll</p>
  <table class="data-table">
    <thead><tr>
      <th>Creative</th><th>Hook Score</th><th>Watch Score</th>
      <th>Hook Rate</th><th>Hold Rate</th><th>ROAS</th><th>Spend</th>
    </tr></thead>
    <tbody>""" + "".join(
        (lambda hk: f"""<tr>
          <td><div class="ad-cell">{f'<img class="thumb" src="{hk["thumbnail_url"]}" loading="lazy" onerror="this.style.display=&apos;none&apos;">' if hk.get("thumbnail_url") else ""}<div>{ad_link(hk.get("ad_id"), hk.get("ad_name"))}{f'<div class="meta-tags">{(hk.get("hook_type") or "").replace("_"," ")}{" / " + (hk.get("visual_format") or "").replace("_"," ") if hk.get("visual_format") else ""}</div>' if hk.get("hook_type") or hk.get("visual_format") else ""}</div></div></td>
          <td>{grade_badge(hk.get("hook_score"), hk.get("hook_grade"))}</td>
          <td>{grade_badge(hk.get("watch_score"), hk.get("watch_grade"))}</td>
          <td class="num">{f'{hk["hook_rate"]:.1f}%' if hk.get("hook_rate") else 'N/A'}</td>
          <td class="num">{f'{hk["hold_rate"]:.1f}%' if hk.get("hold_rate") else 'N/A'}</td>
          <td class="num">{f'{hk["roas"]:.2f}' if hk.get("roas") else 'N/A'}</td>
          <td class="num">{hk.get("spend",0):,.0f} Kc</td>
        </tr>""")(hk)
        for hk in d.get("top_hooks", [])
    ) + f"""</tbody>
  </table>
</div>

<div class="section">
  <h2>Recommendations</h2>""" + (
    "<div class='recs-grid'>" + "".join(
        f"""<div class="rec-card {'rec-swap' if r.get('rec_type','') == 'SWAP_HOOK' else 'rec-new' if 'NEW' in r.get('rec_type','') else 'rec-alert'}">
          <div class="rec-type">{r.get('rec_type','').replace('_',' ')}</div>
          <div class="rec-desc">{(r.get('description') or '')[:120]}</div>
        </div>"""
        for r in d.get("recommendations", [])[:6]
    ) + "</div>" if d.get("recommendations") else '<p class="muted">No recommendations yet. Run: python -m creative_intelligence recommend</p>'
    ) + f"""
</div>

<div class="section">
  <h2>Landing Page Analysis</h2>
  <table class="data-table">
    <thead><tr>
      <th>Landing Page</th><th>Ads</th><th>Spend</th><th>ROAS</th><th>CPA</th><th>Purchases</th>
    </tr></thead>
    <tbody>""" + "".join(
        f"""<tr>
          <td><a href="https://{lp['landing_page']}" target="_blank" class="ad-link">{lp['landing_page'][:45]}</a></td>
          <td>{lp['count']}</td>
          <td class="num">{lp['total_spend']:,.0f} Kc</td>
          <td class="num">{f"{lp['avg_roas']:.2f}" if lp.get('avg_roas') else 'N/A'}</td>
          <td class="num">{f"{lp['avg_cpa']:,.0f} Kc" if lp.get('avg_cpa') else 'N/A'}</td>
          <td class="num">{lp.get('total_purchases', 0)}</td>
        </tr>"""
        for lp in d.get("landing_pages", [])[:10]
    ) + f"""</tbody>
  </table>
</div>

<script>
// Shift tabs
function showShift(kind) {{
  document.querySelectorAll('.shift-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.shift-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('shift-' + kind).style.display = 'flex';
  event.target.classList.add('active');
}}

// Chart defaults
Chart.defaults.color = '#8888a0';
Chart.defaults.borderColor = '#2a2a3a';
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size = 11;

// Ad Type chart
new Chart(document.getElementById('chartAdType'), {{
  type: 'bar',
  data: {{
    labels: {at_labels},
    datasets: [
      {{ label: 'Spend (Kc)', data: {at_spend}, backgroundColor: 'rgba(99,102,241,0.6)', yAxisID: 'y' }},
      {{ label: 'ROAS', data: {at_roas}, type: 'line', borderColor: '#22c55e', pointBackgroundColor: '#22c55e', yAxisID: 'y1' }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      y: {{ position: 'left', grid: {{ color: '#1a1a26' }} }},
      y1: {{ position: 'right', grid: {{ display: false }}, min: 0 }}
    }}
  }}
}});

// Visual Format chart
new Chart(document.getElementById('chartVisualFormat'), {{
  type: 'bar',
  data: {{
    labels: {vf_labels},
    datasets: [
      {{ label: 'ROAS', data: {vf_roas}, backgroundColor: 'rgba(34,197,94,0.6)' }},
      {{ label: 'Ad count', data: {vf_count}, backgroundColor: 'rgba(99,102,241,0.3)' }}
    ]
  }},
  options: {{
    responsive: true,
    indexAxis: 'y',
    scales: {{ x: {{ grid: {{ color: '#1a1a26' }} }} }}
  }}
}});

// Daily trend
new Chart(document.getElementById('chartDailyTrend'), {{
  type: 'line',
  data: {{
    labels: {dt_labels},
    datasets: [
      {{ label: 'Spend', data: {dt_spend}, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.3 }},
      {{ label: 'Revenue', data: {dt_revenue}, borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{ y: {{ grid: {{ color: '#1a1a26' }} }} }},
    plugins: {{ legend: {{ position: 'top' }} }}
  }}
}});
</script>

</body>
</html>"""
