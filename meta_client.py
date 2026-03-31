#!/usr/bin/env python3
"""
Fermato Meta API Client — sdileny modul
========================================
Jednotne rozhrani pro volani Meta Graph API
s retry logikou a rate limit handlingem.

Pouziti:
    from meta_client import meta_fetch, meta_fetch_all, AD_ACCOUNT_ID
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# ── Config ──

ACCESS_TOKEN = os.environ.get("META_ADS_ACCESS_TOKEN", "")
AD_ACCOUNT_ID = "act_346692147206629"
API_VERSION = "v23.0"
API_BASE = f"https://graph.facebook.com/{API_VERSION}"

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds, exponential: 2, 4, 8


def _get_token():
    """Vraci aktualni access token (refreshne z env pokud se zmenil)."""
    return ACCESS_TOKEN or os.environ.get("META_ADS_ACCESS_TOKEN", "")


def meta_fetch(endpoint, params=None, timeout=30):
    """Single API call s retry logikou.

    Automaticky handluje:
    - HTTP 429 (rate limit) — exponential backoff
    - HTTP 5xx (server error) — retry
    - Timeout — retry

    Returns:
        dict: parsed JSON response
    """
    if params is None:
        params = {}
    params["access_token"] = _get_token()
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429 or e.code >= 500:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"  META API: HTTP {e.code}, retry za {wait}s (pokus {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise  # 4xx (krome 429) neni retry-able
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"  META API: {type(e).__name__}, retry za {wait}s (pokus {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise

    raise last_error


def meta_fetch_all(endpoint, params=None, max_pages=10, timeout=30):
    """Paginated API call s retry logikou.

    Returns:
        list: vsechna data ze vsech stranek
    """
    if params is None:
        params = {}
    params["access_token"] = _get_token()
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)

    results = []
    page = 0
    while url and page < max_pages:
        last_error = None
        data = None

        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code == 429 or e.code >= 500:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    print(f"  META API: HTTP {e.code}, retry za {wait}s (page {page}, pokus {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
                    time.sleep(wait)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    print(f"  META API: {type(e).__name__}, retry za {wait}s (page {page}, pokus {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
                    time.sleep(wait)
                    continue
                raise

        if data is None:
            raise last_error

        results.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        page += 1

    return results
