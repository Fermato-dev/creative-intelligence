#!/usr/bin/env python3
"""
GA4 Bridge — Google Analytics data pro attribution check a channel mix.
======================================================================
Wrappuje tools/cos/ga4_analytics.py pro potreby Creative Intelligence dashboardu.

Pouziti:
    from ga4_bridge import fetch_ga4_attribution
    data = fetch_ga4_attribution(days=14)
"""

import sys
from pathlib import Path

# Pridej repo root do path pro tools.cos import
REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

META_SOURCES = [
    "facebook",
    "fb",
    "instagram",
    "ig",
    "m.facebook.com",
    "l.facebook.com",
    "lm.facebook.com",
    "instagram.com",
]


def _is_meta_source(source: str) -> bool:
    """Rozhodne jestli source je Meta (Facebook/Instagram)."""
    src = (source or "").lower().strip()
    return any(ms in src for ms in META_SOURCES)


def fetch_ga4_attribution(days=14, site="cz"):
    """Stahne GA4 data pro attribution check.

    Returns:
        dict: {
            "channel_mix": [...],  # vsechny kanaly s revenue
            "meta_ga4": {...},     # souhrn za Meta (fb+ig)
            "google_ga4": {...},   # souhrn za Google paid
            "devices": [...],      # desktop/mobile/tablet
            "daily": [...],        # denni ecommerce data
            "totals": {...},       # celkove souhrny
        }
    """
    from tools.cos.ga4_analytics import GA4Analytics
    ga = GA4Analytics()

    # Ecommerce by source
    ecom_src = ga.ecommerce_by_source(site, days=days)

    # Devices
    devices = ga.devices(site, days=days)

    # Daily ecommerce
    daily = ga.ecommerce(site, days=days)

    # --- Agregace ---

    # Channel mix: seskupit podle source/medium
    channel_mix = []
    meta_purchases = 0
    meta_revenue = 0
    meta_sessions = 0
    google_paid_purchases = 0
    google_paid_revenue = 0
    google_paid_sessions = 0
    total_purchases = 0
    total_revenue = 0
    total_sessions = 0

    for row in ecom_src:
        src = row.get("sessionSource", "")
        med = row.get("sessionMedium", "")
        purch = row.get("ecommercePurchases", 0)
        rev = row.get("totalRevenue", 0)
        sess = row.get("sessions", 0)
        cvr = row.get("purchaserConversionRate", 0)

        total_purchases += purch
        total_revenue += rev
        total_sessions += sess

        # Meta agregace
        if _is_meta_source(src):
            meta_purchases += purch
            meta_revenue += rev
            meta_sessions += sess

        # Google paid
        if src == "google" and med == "cpc":
            google_paid_purchases += purch
            google_paid_revenue += rev
            google_paid_sessions += sess

        channel_mix.append({
            "source": src,
            "medium": med,
            "sessions": sess,
            "purchases": purch,
            "revenue": round(rev),
            "cvr": round(cvr * 100, 2) if cvr < 1 else round(cvr, 2),  # GA4 vraci 0.05 nebo 5.0
            "is_meta": _is_meta_source(src),
        })

    # Sort by revenue desc
    channel_mix.sort(key=lambda x: x["revenue"], reverse=True)

    # iOS/Android z devices
    mobile_data = next((d for d in devices if d.get("deviceCategory") == "mobile"), {})
    desktop_data = next((d for d in devices if d.get("deviceCategory") == "desktop"), {})

    return {
        "channel_mix": channel_mix[:15],  # top 15
        "meta_ga4": {
            "purchases": meta_purchases,
            "revenue": round(meta_revenue),
            "sessions": meta_sessions,
            "share_purchases_pct": round(meta_purchases / total_purchases * 100, 1) if total_purchases else 0,
            "share_revenue_pct": round(meta_revenue / total_revenue * 100, 1) if total_revenue else 0,
        },
        "google_paid": {
            "purchases": google_paid_purchases,
            "revenue": round(google_paid_revenue),
            "sessions": google_paid_sessions,
        },
        "devices": [
            {
                "device": d.get("deviceCategory", "?"),
                "sessions": d.get("sessions", 0),
                "revenue": round(d.get("totalRevenue", 0)),
                "cvr": round(d.get("purchaserConversionRate", 0) * 100, 2) if d.get("purchaserConversionRate", 0) < 1 else round(d.get("purchaserConversionRate", 0), 2),
                "conversions": d.get("conversions", 0),
            }
            for d in devices
        ],
        "daily": [
            {
                "date": d.get("date", ""),
                "sessions": d.get("sessions", 0),
                "purchases": d.get("ecommercePurchases", 0),
                "revenue": round(d.get("totalRevenue", 0)),
                "cvr": round(d.get("purchaserConversionRate", 0) * 100, 2) if d.get("purchaserConversionRate", 0) < 1 else round(d.get("purchaserConversionRate", 0), 2),
            }
            for d in daily
        ],
        "totals": {
            "purchases": total_purchases,
            "revenue": round(total_revenue),
            "sessions": total_sessions,
        },
        "mobile_pct": round(mobile_data.get("sessions", 0) / total_sessions * 100, 1) if total_sessions else 0,
    }


# ── CLI ──

if __name__ == "__main__":
    days = 14
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])

    print(f"Stahuji GA4 data za {days} dni...", file=sys.stderr)
    data = fetch_ga4_attribution(days)

    m = data["meta_ga4"]
    t = data["totals"]
    print(f"\nGA4 souhrn ({days} dni):")
    print(f"  Celkem: {t['purchases']} purchases, {t['revenue']:,} CZK, {t['sessions']} sessions")
    print(f"  Meta:   {m['purchases']} purchases ({m['share_purchases_pct']}%), {m['revenue']:,} CZK ({m['share_revenue_pct']}%)")
    print(f"  Mobile: {data['mobile_pct']}% sessions")

    print(f"\nTop kanaly:")
    for ch in data["channel_mix"][:8]:
        meta_flag = " [META]" if ch["is_meta"] else ""
        print(f"  {ch['source']}/{ch['medium']}: {ch['purchases']} purch, {ch['revenue']:,} CZK, CVR {ch['cvr']}%{meta_flag}")
