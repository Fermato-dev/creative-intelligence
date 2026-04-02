"""GA4 Bridge — Google Analytics data pro attribution check a channel mix.

Na Railway bez OAuth tokenu vraci graceful error.
Lokalne vyzaduje google-analytics-data package + OAuth token.
"""

import sys
from pathlib import Path

META_SOURCES = [
    "facebook", "fb", "instagram", "ig",
    "m.facebook.com", "l.facebook.com", "lm.facebook.com", "instagram.com",
]


def _is_meta_source(source: str) -> bool:
    src = (source or "").lower().strip()
    return any(ms in src for ms in META_SOURCES)


def _get_ga4_client():
    """Try to initialize GA4Analytics. Raises ImportError if not available."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        raise ImportError("google-analytics-data package neni nainstalovany. Spust: pip install google-analytics-data google-auth-oauthlib")

    SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
    # Try multiple token locations
    token_paths = [
        Path(__file__).parent.parent / "data" / ".ga4_token.json",
        Path(__file__).parent.parent / "config" / ".ga4_token.json",
        Path.home() / ".ga4_token.json",
    ]

    creds = None
    for tp in token_paths:
        if tp.exists():
            creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    tp.write_text(creds.to_json())
                except Exception:
                    creds = None
            break

    if not creds or not creds.valid:
        raise RuntimeError("GA4 OAuth token neni dostupny. Spust lokalne: python -m creative_intelligence.ga4_setup")

    return BetaAnalyticsDataClient(credentials=creds)


PROPERTIES = {"cz": "properties/324170506", "hu": "properties/526504776"}


def fetch_ga4_attribution(days=14, site="cz"):
    """Fetch GA4 data for attribution check.

    Returns dict with channel_mix, meta_ga4, devices, daily, totals, mobile_pct.
    Raises ImportError/RuntimeError if GA4 not available.
    """
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest, OrderBy,
    )

    client = _get_ga4_client()
    prop = PROPERTIES.get(site, PROPERTIES["cz"])
    date_range = DateRange(
        start_date=f"{days}daysAgo",
        end_date="yesterday",
    )

    # ── Ecommerce by source/medium ──
    ecom_resp = client.run_report(RunReportRequest(
        property=prop,
        date_ranges=[date_range],
        dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="ecommercePurchases"),
            Metric(name="totalRevenue"),
            Metric(name="purchaserConversionRate"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalRevenue"), desc=True)],
        limit=50,
    ))

    ecom_src = []
    for row in ecom_resp.rows:
        ecom_src.append({
            "sessionSource": row.dimension_values[0].value,
            "sessionMedium": row.dimension_values[1].value,
            "sessions": int(row.metric_values[0].value),
            "ecommercePurchases": int(row.metric_values[1].value),
            "totalRevenue": float(row.metric_values[2].value),
            "purchaserConversionRate": float(row.metric_values[3].value),
        })

    # ── Devices ──
    dev_resp = client.run_report(RunReportRequest(
        property=prop,
        date_ranges=[date_range],
        dimensions=[Dimension(name="deviceCategory")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalRevenue"),
            Metric(name="purchaserConversionRate"),
        ],
    ))

    devices = []
    for row in dev_resp.rows:
        devices.append({
            "deviceCategory": row.dimension_values[0].value,
            "sessions": int(row.metric_values[0].value),
            "totalRevenue": float(row.metric_values[1].value),
            "purchaserConversionRate": float(row.metric_values[2].value),
        })

    # ── Daily ──
    daily_resp = client.run_report(RunReportRequest(
        property=prop,
        date_ranges=[date_range],
        dimensions=[Dimension(name="date")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="ecommercePurchases"),
            Metric(name="totalRevenue"),
            Metric(name="purchaserConversionRate"),
        ],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
    ))

    daily = []
    for row in daily_resp.rows:
        daily.append({
            "date": row.dimension_values[0].value,
            "sessions": int(row.metric_values[0].value),
            "ecommercePurchases": int(row.metric_values[1].value),
            "totalRevenue": float(row.metric_values[2].value),
            "purchaserConversionRate": float(row.metric_values[3].value),
        })

    # ── Aggregate ──
    channel_mix = []
    meta_purchases = meta_revenue = meta_sessions = 0
    total_purchases = total_revenue = total_sessions = 0

    for row in ecom_src:
        src = row["sessionSource"]
        purch = row["ecommercePurchases"]
        rev = row["totalRevenue"]
        sess = row["sessions"]
        cvr = row["purchaserConversionRate"]

        total_purchases += purch
        total_revenue += rev
        total_sessions += sess

        if _is_meta_source(src):
            meta_purchases += purch
            meta_revenue += rev
            meta_sessions += sess

        channel_mix.append({
            "source": src,
            "medium": row["sessionMedium"],
            "sessions": sess,
            "purchases": purch,
            "revenue": round(rev),
            "cvr": round(cvr * 100, 2) if cvr < 1 else round(cvr, 2),
            "is_meta": _is_meta_source(src),
        })

    channel_mix.sort(key=lambda x: x["revenue"], reverse=True)

    mobile_data = next((d for d in devices if d["deviceCategory"] == "mobile"), {})

    return {
        "channel_mix": channel_mix[:15],
        "meta_ga4": {
            "purchases": meta_purchases,
            "revenue": round(meta_revenue),
            "sessions": meta_sessions,
            "share_purchases_pct": round(meta_purchases / total_purchases * 100, 1) if total_purchases else 0,
            "share_revenue_pct": round(meta_revenue / total_revenue * 100, 1) if total_revenue else 0,
        },
        "devices": [
            {
                "device": d["deviceCategory"],
                "sessions": d["sessions"],
                "revenue": round(d["totalRevenue"]),
                "cvr": round(d["purchaserConversionRate"] * 100, 2) if d["purchaserConversionRate"] < 1 else round(d["purchaserConversionRate"], 2),
            }
            for d in devices
        ],
        "daily": [
            {
                "date": d["date"],
                "sessions": d["sessions"],
                "purchases": d["ecommercePurchases"],
                "revenue": round(d["totalRevenue"]),
                "cvr": round(d["purchaserConversionRate"] * 100, 2) if d["purchaserConversionRate"] < 1 else round(d["purchaserConversionRate"], 2),
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
