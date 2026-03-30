#!/usr/bin/env python3
"""
Shoptet Bridge — denni objednavky a trzby pro attribution check
===============================================================
Stahuje denni order data ze Shoptet REST API.
Pouziva denni dotazy (ne mesicni) kvuli limitu 2500 obj.

Pouziti:
    from shoptet_bridge import fetch_daily_orders
    data = fetch_daily_orders(days=14)
    # [{"date": "2026-03-14", "orders": 85, "revenue": 92340, "aov": 1086, "paid": 80}, ...]
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

# ── Config ──

SHOPTET_TOKEN = os.environ.get("SHOPTET_API_TOKEN")
API_BASE = "https://api.myshoptet.com/api"


def shoptet_fetch(endpoint, params=None):
    """Vola Shoptet REST API s autentizaci."""
    if not SHOPTET_TOKEN:
        raise RuntimeError("SHOPTET_API_TOKEN neni nastaven v environment variables")

    url = f"{API_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={
        "Shoptet-Private-API-Token": SHOPTET_TOKEN,
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_orders_for_date(date_str):
    """Stahne vsechny objednavky pro jeden den. Paginuje pokud je jich vic nez 100.

    Args:
        date_str: datum ve formatu YYYY-MM-DD

    Returns:
        list of order dicts
    """
    all_orders = []
    page = 1

    while True:
        data = shoptet_fetch("orders", {
            "creationTimeFrom": f"{date_str}T00:00:00+0100",
            "creationTimeTo": f"{date_str}T23:59:59+0100",
            "itemsPerPage": 100,
            "page": page,
        })

        orders = data.get("data", {}).get("orders", [])
        all_orders.extend(orders)

        paginator = data.get("data", {}).get("paginator", {})
        page_count = paginator.get("pageCount", 1)
        if page >= page_count:
            break
        page += 1
        if page > 25:  # safety limit
            break

    return all_orders


def fetch_daily_orders(days=14):
    """Stahne denni souhrny objednavek za poslednich N dni.

    Pouziva denni dotazy — kazdy den samostatne, aby se obesel
    limit 2500 objednavek v jednom API callu.

    Returns:
        list of dicts: [{"date", "orders", "revenue", "aov", "paid"}, ...]
    """
    results = []
    today = datetime.now()

    for i in range(days):
        date = today - timedelta(days=i + 1)  # vcera az days zpet
        date_str = date.strftime("%Y-%m-%d")

        try:
            orders = fetch_orders_for_date(date_str)

            total_revenue = sum(
                float(o.get("price", {}).get("withVat", 0))
                for o in orders
            )
            paid_count = sum(1 for o in orders if o.get("paid"))
            order_count = len(orders)
            aov = round(total_revenue / order_count) if order_count > 0 else 0

            results.append({
                "date": date_str,
                "orders": order_count,
                "revenue": round(total_revenue),
                "aov": aov,
                "paid": paid_count,
            })
        except Exception as e:
            print(f"WARN: Shoptet fetch pro {date_str} selhal: {e}")
            results.append({
                "date": date_str,
                "orders": 0,
                "revenue": 0,
                "aov": 0,
                "paid": 0,
                "error": str(e),
            })

    # Seradit chronologicky (nejstarsi first)
    results.sort(key=lambda x: x["date"])
    return results


def fetch_daily_summary(days=14):
    """Stahne denni data a vypocita souhrne metriky.

    Returns:
        dict: {
            "daily": [...],
            "totals": {"orders", "revenue", "aov", "paid", "days"},
        }
    """
    daily = fetch_daily_orders(days)

    total_orders = sum(d["orders"] for d in daily)
    total_revenue = sum(d["revenue"] for d in daily)
    total_paid = sum(d["paid"] for d in daily)

    return {
        "daily": daily,
        "totals": {
            "orders": total_orders,
            "revenue": total_revenue,
            "aov": round(total_revenue / total_orders) if total_orders > 0 else 0,
            "paid": total_paid,
            "days": len(daily),
        },
    }


def attribution_check(meta_purchases, meta_revenue, meta_spend, shoptet_data):
    """Porovna Meta atribuovane nakupy vs Shoptet skutecne objednavky.

    Args:
        meta_purchases: pocet nakupu dle Meta (7-day click)
        meta_revenue: trzba dle Meta atribuce
        meta_spend: celkova utrata na Meta
        shoptet_data: vysledek z fetch_daily_summary()

    Returns:
        dict s attribution metriky
    """
    shoptet_totals = shoptet_data["totals"]
    shoptet_orders = shoptet_totals["orders"]
    shoptet_revenue = shoptet_totals["revenue"]

    # Attribution share: kolik % Shoptet objednavek si Meta pripisuje
    attr_share = (meta_purchases / shoptet_orders * 100) if shoptet_orders > 0 else 0

    # Revenue gap: rozdil mezi Meta-reportovanou a skutecnou trzbu
    revenue_gap = meta_revenue - shoptet_revenue
    revenue_gap_pct = (revenue_gap / shoptet_revenue * 100) if shoptet_revenue > 0 else 0

    # Skutecny ROAS: Shoptet revenue / Meta spend
    true_roas = shoptet_revenue / meta_spend if meta_spend > 0 else 0

    # Meta ROAS: Meta revenue / Meta spend
    meta_roas = meta_revenue / meta_spend if meta_spend > 0 else 0

    # ROAS gap
    roas_gap = meta_roas - true_roas
    roas_gap_pct = (roas_gap / true_roas * 100) if true_roas > 0 else 0

    # Zdravi attribution share
    # 30-50% = zdravy rozsah pro primarni akvizicni kanal
    # > 70% = Meta si pripisuje prilis
    if attr_share > 70:
        health = "INFLACE"
        health_detail = "Meta si pripisuje >70% objednavek — pravdepodobne inflace"
    elif attr_share > 50:
        health = "VYSOKA"
        health_detail = "Meta si pripisuje 50-70% — na hrane, overit view-through podil"
    elif attr_share > 30:
        health = "ZDRAVA"
        health_detail = "Meta si pripisuje 30-50% — ocekavany rozsah pro primarni kanal"
    else:
        health = "NIZKA"
        health_detail = "Meta si pripisuje <30% — bud podhodnocuje, nebo jsou silne jine kanaly"

    return {
        "meta": {
            "purchases": meta_purchases,
            "revenue": round(meta_revenue),
            "spend": round(meta_spend),
            "roas": round(meta_roas, 2),
        },
        "shoptet": {
            "orders": shoptet_orders,
            "revenue": shoptet_revenue,
            "aov": shoptet_totals["aov"],
            "paid": shoptet_totals["paid"],
        },
        "attribution": {
            "share_pct": round(attr_share, 1),
            "health": health,
            "health_detail": health_detail,
            "revenue_gap": round(revenue_gap),
            "revenue_gap_pct": round(revenue_gap_pct, 1),
            "true_roas": round(true_roas, 2),
            "meta_roas": round(meta_roas, 2),
            "roas_gap": round(roas_gap, 2),
            "roas_gap_pct": round(roas_gap_pct, 1),
        },
        "daily": shoptet_data.get("daily", []),
    }


# ── CLI ──

if __name__ == "__main__":
    import sys

    days = 14
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])

    print(f"Stahuji Shoptet data za {days} dni...", file=sys.stderr)
    data = fetch_daily_summary(days)

    t = data["totals"]
    print(f"\nShoptet souhrn ({days} dni):")
    print(f"  Objednavky: {t['orders']}")
    print(f"  Trzba:      {t['revenue']:,} CZK")
    print(f"  AOV:        {t['aov']} CZK")
    print(f"  Zaplaceno:  {t['paid']}")

    print(f"\nDenni data:")
    for d in data["daily"]:
        err = " (ERROR)" if d.get("error") else ""
        print(f"  {d['date']}: {d['orders']} obj, {d['revenue']:,} CZK, AOV {d['aov']} CZK{err}")

    if "--json" in sys.argv:
        print(json.dumps(data, indent=2, ensure_ascii=False))
