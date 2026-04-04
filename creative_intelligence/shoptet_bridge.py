"""Shoptet Bridge — denni objednavky a trzby pro attribution check."""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

API_BASE = "https://api.myshoptet.com/api"


def _get_token():
    token = os.environ.get("SHOPTET_API_TOKEN")
    if not token:
        raise RuntimeError("SHOPTET_API_TOKEN neni nastaven")
    return token


def shoptet_fetch(endpoint, params=None):
    token = _get_token()
    url = f"{API_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Shoptet-Private-API-Token": token})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_orders_for_date(date_str):
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
        page_count = data.get("data", {}).get("paginator", {}).get("pageCount", 1)
        if page >= page_count or page > 25:
            break
        page += 1
    return all_orders


def fetch_daily_summary(days=14):
    results = []
    today = datetime.now()
    for i in range(days):
        date = today - timedelta(days=i + 1)
        date_str = date.strftime("%Y-%m-%d")
        try:
            orders = fetch_orders_for_date(date_str)
            total_revenue = sum(float(o.get("price", {}).get("withVat", 0)) for o in orders)
            paid_count = sum(1 for o in orders if o.get("paid"))
            order_count = len(orders)
            results.append({
                "date": date_str, "orders": order_count,
                "revenue": round(total_revenue),
                "aov": round(total_revenue / order_count) if order_count > 0 else 0,
                "paid": paid_count,
            })
        except Exception as e:
            results.append({"date": date_str, "orders": 0, "revenue": 0, "aov": 0, "paid": 0, "error": str(e)})
    results.sort(key=lambda x: x["date"])

    total_orders = sum(d["orders"] for d in results)
    total_revenue = sum(d["revenue"] for d in results)
    return {
        "daily": results,
        "totals": {
            "orders": total_orders,
            "revenue": total_revenue,
            "aov": round(total_revenue / total_orders) if total_orders > 0 else 0,
            "paid": sum(d["paid"] for d in results),
            "days": len(results),
        },
    }
