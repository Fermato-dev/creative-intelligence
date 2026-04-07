"""v3: Combinatorial Recommendations — hook × body × CTA optimization.

Analyzuje komponentní knihovnu a generuje doporučení:
- SWAP_HOOK: nahraď slabý hook lepším z knihovny
- SWAP_BODY: nahraď slabý body
- SWAP_CTA: nahraď slabé CTA
- NEW_COMBINATION: sestav novou kreativu z top komponent
- REFRESH_ALERT: hook/body fatigue, čas na refresh

Používá Thompson Sampling pro efektivní exploraci prostoru
hook×body×CTA (místo brute-force testování).
"""

import random
import sys
from datetime import datetime, timedelta

from .component_db import (
    get_db, get_top_components, get_all_components, count_components,
    is_combination_tested, save_recommendation, get_pending_recommendations,
)
from .config import TARGET_ROAS, TARGET_CPA, BENCHMARKS, SEASONAL_CAMPAIGN_PATTERNS


# ── Seasonal/flash campaign filter ──

def is_seasonal(comp):
    """Check if a component comes from a seasonal/flash campaign.

    Matches against campaign_name and ad_name using patterns from config.
    Components from seasonal campaigns should NOT be used in remix recommendations
    because their performance is inflated by time-limited context (holiday, promo).
    """
    campaign = (comp.get("campaign_name") or "").lower()
    ad_name = (comp.get("ad_name") or "").lower()
    text = campaign + " " + ad_name
    return any(p in text for p in SEASONAL_CAMPAIGN_PATTERNS)


# ── Thompson Sampling ──

def thompson_sample(successes, failures):
    """Sample from Beta(successes+1, failures+1) distribution.
    Higher = more likely to be good.
    """
    return random.betavariate(successes + 1, failures + 1)


def component_score(comp):
    """Score a component using Thompson Sampling approach.

    Uses multiple signals as "successes":
    - Hook: hook_rate (normalized), ROAS > target
    - Body: hold_rate (normalized), ROAS > target
    - CTA: cvr (normalized), ROAS > target

    Returns float 0-1 (higher = better).
    """
    comp_type = comp["component_type"]
    spend = comp.get("spend") or 0
    impressions = comp.get("impressions") or 0

    # More data = more confidence (trials)
    trials = min(spend / 500, 20)  # Cap at 20 "trials"

    if comp_type == "hook":
        hook_rate = comp.get("hook_rate") or 0
        # Normalize: 35% = ~1.0 success rate, <15% = ~0.0
        success_rate = max(0, min(1, (hook_rate - 15) / 20))

    elif comp_type == "body":
        hold_rate = comp.get("hold_rate") or 0
        success_rate = max(0, min(1, (hold_rate - 20) / 30))

    elif comp_type == "cta":
        cvr = comp.get("cvr") or 0
        success_rate = max(0, min(1, (cvr - 0.5) / 3))

    else:
        success_rate = 0.5

    # ROAS bonus
    roas = comp.get("roas") or 0
    if roas > TARGET_ROAS:
        success_rate = min(1, success_rate + 0.15)

    successes = int(trials * success_rate)
    failures = int(trials * (1 - success_rate))

    return thompson_sample(successes, failures)


# ── Recommendation generators ──

def recommend_hook_swaps(conn, min_spend=200, max_results=5):
    """Find ads where swapping the hook would likely improve performance.

    Logic: ads with low hook_rate but OK ROAS → good body/CTA, bad hook.
    Suggest replacing with top hooks from library.
    """
    recommendations = []

    # Get weak hooks (low hook_rate, but some spend) — exclude seasonal
    weak_hooks = [dict(r) for r in conn.execute("""
        SELECT * FROM components
        WHERE component_type = 'hook'
          AND hook_rate IS NOT NULL
          AND hook_rate < 25
          AND spend >= ?
          AND roas IS NOT NULL
          AND roas > 1.0
        ORDER BY spend DESC
        LIMIT 20
    """, (min_spend,)).fetchall() if not is_seasonal(dict(r))]

    # Get top hooks for replacement — exclude seasonal
    top_hooks = [h for h in get_top_components(conn, "hook", metric="hook_rate", limit=10, min_spend=min_spend)
                 if not is_seasonal(h)]

    for weak in weak_hooks:
        for strong in top_hooks:
            if strong["ad_id"] == weak["ad_id"]:
                continue
            if (strong.get("hook_rate") or 0) <= (weak.get("hook_rate") or 0):
                continue

            improvement = (strong["hook_rate"] or 0) - (weak.get("hook_rate") or 0)
            recommendations.append({
                "type": "SWAP_HOOK",
                "target_ad": weak["ad_name"],
                "target_ad_id": weak["ad_id"],
                "current_hook_rate": weak.get("hook_rate"),
                "current_roas": weak.get("roas"),
                "suggested_from_ad": strong["ad_name"],
                "suggested_from_ad_id": strong["ad_id"],
                "suggested_hook_rate": strong["hook_rate"],
                "expected_improvement": f"+{improvement:.1f}pp hook rate",
                "confidence": "stredni" if weak.get("spend", 0) > 1000 else "nizka",
                "reason": f"Ad ma ROAS {weak.get('roas'):.2f} ale hook jen {weak.get('hook_rate'):.1f}% — dobry obsah, spatny zacatek",
            })

            if len(recommendations) >= max_results:
                return recommendations

    return recommendations


def recommend_body_swaps(conn, min_spend=200, max_results=5):
    """Find ads where body is the weak link.

    Logic: good hook_rate (>25%) but low hold_rate (<40%) → hook works, body doesn't.
    """
    recommendations = []

    weak_bodies = [dict(r) for r in conn.execute("""
        SELECT * FROM components
        WHERE component_type = 'body'
          AND hold_rate IS NOT NULL
          AND hold_rate < 40
          AND hook_rate IS NOT NULL
          AND hook_rate >= 25
          AND spend >= ?
        ORDER BY spend DESC
        LIMIT 20
    """, (min_spend,)).fetchall() if not is_seasonal(dict(r))]

    top_bodies = [b for b in get_top_components(conn, "body", metric="hold_rate", limit=10, min_spend=min_spend)
                  if not is_seasonal(b)]

    for weak in weak_bodies:
        for strong in top_bodies:
            if strong["ad_id"] == weak["ad_id"]:
                continue
            if (strong.get("hold_rate") or 0) <= (weak.get("hold_rate") or 0):
                continue

            improvement = (strong["hold_rate"] or 0) - (weak.get("hold_rate") or 0)
            recommendations.append({
                "type": "SWAP_BODY",
                "target_ad": weak["ad_name"],
                "target_ad_id": weak["ad_id"],
                "current_hold_rate": weak.get("hold_rate"),
                "current_hook_rate": weak.get("hook_rate"),
                "suggested_from_ad": strong["ad_name"],
                "suggested_from_ad_id": strong["ad_id"],
                "suggested_hold_rate": strong["hold_rate"],
                "expected_improvement": f"+{improvement:.1f}pp hold rate",
                "reason": f"Hook funguje ({weak.get('hook_rate'):.1f}%) ale body ztraci lidi (hold {weak.get('hold_rate'):.1f}%)",
            })

            if len(recommendations) >= max_results:
                return recommendations

    return recommendations


def recommend_new_combinations(conn, min_spend=200, max_results=5):
    """Generate new hook×body×CTA combinations from top components.

    Uses Thompson Sampling to balance exploitation (best known)
    and exploration (untested combinations).
    """
    recommendations = []

    hooks = get_all_components(conn, "hook")
    bodies = get_all_components(conn, "body")
    ctas = get_all_components(conn, "cta")

    if not hooks or not bodies or not ctas:
        return []

    # Score all components via Thompson Sampling — exclude seasonal/flash campaigns
    scored_hooks = [(h, component_score(h)) for h in hooks
                    if (h.get("spend") or 0) >= min_spend and not is_seasonal(h)]
    scored_bodies = [(b, component_score(b)) for b in bodies
                     if (b.get("spend") or 0) >= min_spend and not is_seasonal(b)]
    scored_ctas = [(c, component_score(c)) for c in ctas
                   if (c.get("spend") or 0) >= min_spend and not is_seasonal(c)]

    # Sort by score (Thompson sample)
    scored_hooks.sort(key=lambda x: x[1], reverse=True)
    scored_bodies.sort(key=lambda x: x[1], reverse=True)
    scored_ctas.sort(key=lambda x: x[1], reverse=True)

    # Try combinations of top components
    for h, h_score in scored_hooks[:7]:
        for b, b_score in scored_bodies[:5]:
            for c, c_score in scored_ctas[:3]:
                # Skip same-ad combinations (already exist)
                if h["ad_id"] == b["ad_id"] == c["ad_id"]:
                    continue

                # Skip already tested
                if is_combination_tested(conn, h.get("id"), b.get("id"), c.get("id")):
                    continue

                combined_score = (h_score + b_score + c_score) / 3

                recommendations.append({
                    "type": "NEW_COMBINATION",
                    "combined_score": round(combined_score, 3),
                    "hook": {
                        "from_ad": h["ad_name"],
                        "ad_id": h["ad_id"],
                        "hook_rate": h.get("hook_rate"),
                        "hook_type": (h.get("analysis") or {}).get("hook_type", "?"),
                    },
                    "body": {
                        "from_ad": b["ad_name"],
                        "ad_id": b["ad_id"],
                        "hold_rate": b.get("hold_rate"),
                        "narrative": (b.get("analysis") or {}).get("narrative_structure", "?"),
                    },
                    "cta": {
                        "from_ad": c["ad_name"],
                        "ad_id": c["ad_id"],
                        "cvr": c.get("cvr"),
                        "cta_type": (c.get("analysis") or {}).get("cta_type", "?"),
                    },
                    "reason": f"Top hook ({h.get('hook_rate', '?')}%) + top body (hold {b.get('hold_rate', '?')}%) + top CTA (CVR {c.get('cvr', '?')}%) — nikdy netestovano spolu",
                })

                if len(recommendations) >= max_results * 3:
                    break
            if len(recommendations) >= max_results * 3:
                break
        if len(recommendations) >= max_results * 3:
            break

    # Sort by combined Thompson score, return top N
    recommendations.sort(key=lambda x: x["combined_score"], reverse=True)
    return recommendations[:max_results]


def recommend_refresh_alerts(conn, fatigue_days=10, min_spend=500):
    """Detect components that are likely fatigued and need refresh.

    Based on research: hook fatigue ~7-14 days.
    """
    recommendations = []
    cutoff = (datetime.now() - timedelta(days=fatigue_days)).isoformat()

    # Find old hooks with high spend (likely fatigued)
    old_components = conn.execute("""
        SELECT * FROM components
        WHERE analyzed_at < ?
          AND spend >= ?
          AND component_type = 'hook'
        ORDER BY spend DESC
        LIMIT 20
    """, (cutoff, min_spend)).fetchall()

    for comp in old_components:
        comp = dict(comp)
        if is_seasonal(comp):
            continue
        age_days = (datetime.now() - datetime.fromisoformat(comp["analyzed_at"])).days

        # Find alternative hooks — exclude seasonal
        alternatives = [dict(a) for a in conn.execute("""
            SELECT ad_name, hook_rate, roas, campaign_name FROM components
            WHERE component_type = 'hook'
              AND ad_id != ?
              AND hook_rate IS NOT NULL
              AND spend >= 200
            ORDER BY hook_rate DESC
            LIMIT 10
        """, (comp["ad_id"],)).fetchall() if not is_seasonal(dict(a))]
        alternatives = alternatives[:3]

        alt_names = [f"{a['ad_name'][:30]} (hook {a['hook_rate']}%)" for a in alternatives]

        recommendations.append({
            "type": "REFRESH_ALERT",
            "component_type": "hook",
            "ad_name": comp["ad_name"],
            "ad_id": comp["ad_id"],
            "days_active": age_days,
            "current_hook_rate": comp.get("hook_rate"),
            "spend": comp.get("spend"),
            "alternatives": alt_names,
            "reason": f"Hook bezi {age_days} dni (fatigue ~7-14 dni) — priprav novy hook",
        })

    return recommendations


# ── Main recommendation pipeline ──

def generate_all_recommendations(conn, min_spend=200, save=True):
    """Run all recommendation generators and return combined results.

    Returns:
        dict with keys: swap_hooks, swap_bodies, new_combinations, refresh_alerts
    """
    results = {
        "swap_hooks": recommend_hook_swaps(conn, min_spend),
        "swap_bodies": recommend_body_swaps(conn, min_spend),
        "new_combinations": recommend_new_combinations(conn, min_spend),
        "refresh_alerts": recommend_refresh_alerts(conn, min_spend=min_spend),
        "generated_at": datetime.now().isoformat(),
    }

    total = sum(len(v) for k, v in results.items() if isinstance(v, list))
    print(f"\nVygenerovano {total} doporuceni:", file=sys.stderr)
    print(f"  SWAP_HOOK:        {len(results['swap_hooks'])}", file=sys.stderr)
    print(f"  SWAP_BODY:        {len(results['swap_bodies'])}", file=sys.stderr)
    print(f"  NEW_COMBINATION:  {len(results['new_combinations'])}", file=sys.stderr)
    print(f"  REFRESH_ALERT:    {len(results['refresh_alerts'])}", file=sys.stderr)

    # Save to DB
    if save:
        for category in ["swap_hooks", "swap_bodies", "new_combinations", "refresh_alerts"]:
            for rec in results[category]:
                save_recommendation(conn, rec["type"], rec.get("reason", ""), rec)

    return results


def format_recommendations_report(results):
    """Format recommendations as human-readable text report."""
    lines = []
    lines.append("=" * 60)
    lines.append("  CREATIVE INTELLIGENCE v3 — COMBINATORIAL RECOMMENDATIONS")
    lines.append(f"  {results.get('generated_at', datetime.now().isoformat())}")
    lines.append("=" * 60)

    # Swap hooks
    if results["swap_hooks"]:
        lines.append(f"\n## SWAP HOOK — nahrad spatny hook lepsim")
        for i, r in enumerate(results["swap_hooks"], 1):
            lines.append(f"\n  {i}. {r['target_ad'][:40]}")
            lines.append(f"     Soucasny hook: {r['current_hook_rate']}% | ROAS: {r['current_roas']}")
            lines.append(f"     Nahrad hookem z: {r['suggested_from_ad'][:40]} ({r['suggested_hook_rate']}%)")
            lines.append(f"     Ocekavany dopad: {r['expected_improvement']}")
            lines.append(f"     Duvod: {r['reason']}")

    # Swap bodies
    if results["swap_bodies"]:
        lines.append(f"\n## SWAP BODY — nahrad slaby stred videa")
        for i, r in enumerate(results["swap_bodies"], 1):
            lines.append(f"\n  {i}. {r['target_ad'][:40]}")
            lines.append(f"     Hook: {r['current_hook_rate']}% (OK) | Hold: {r['current_hold_rate']}% (slaby)")
            lines.append(f"     Nahrad body z: {r['suggested_from_ad'][:40]} (hold {r['suggested_hold_rate']}%)")
            lines.append(f"     Duvod: {r['reason']}")

    # New combinations
    if results["new_combinations"]:
        lines.append(f"\n## NOVE KOMBINACE — nikdy netestovane")
        for i, r in enumerate(results["new_combinations"], 1):
            h = r["hook"]
            b = r["body"]
            c = r["cta"]
            lines.append(f"\n  {i}. Score: {r['combined_score']}")
            lines.append(f"     Hook: {h['from_ad'][:30]} — {h['hook_type']} ({h['hook_rate']}%)")
            lines.append(f"     Body: {b['from_ad'][:30]} — {b['narrative']} (hold {b['hold_rate']}%)")
            lines.append(f"     CTA:  {c['from_ad'][:30]} — {c['cta_type']} (CVR {c['cvr']}%)")
            lines.append(f"     Duvod: {r['reason']}")

    # Refresh alerts
    if results["refresh_alerts"]:
        lines.append(f"\n## REFRESH ALERT — hook fatigue")
        for i, r in enumerate(results["refresh_alerts"], 1):
            lines.append(f"\n  {i}. {r['ad_name'][:40]} — {r['days_active']} dni")
            lines.append(f"     Hook rate: {r['current_hook_rate']}% | Spend: {r['spend']:,.0f} CZK")
            if r["alternatives"]:
                lines.append(f"     Alternativy: {', '.join(r['alternatives'][:3])}")

    if not any(results[k] for k in ["swap_hooks", "swap_bodies", "new_combinations", "refresh_alerts"]):
        lines.append("\n  Zadna doporuceni — komponentni knihovna je prazdna nebo prilis mala.")
        lines.append("  Spust nejdrive: python -m creative_intelligence decompose")

    lines.append(f"\n{'='*60}")
    return "\n".join(lines)
