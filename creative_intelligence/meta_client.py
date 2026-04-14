"""Meta Graph API client — retry logic, pagination, rate limit handling."""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

from .config import AD_ACCOUNT_ID, META_API_BASE

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def _get_token():
    token = os.environ.get("META_ADS_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("META_ADS_ACCESS_TOKEN env var is not set — check Railway environment variables")
    return token


def meta_fetch(endpoint, params=None, timeout=30):
    """Single API call with retry logic."""
    if params is None:
        params = {}
    url = f"{META_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {_get_token()}")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429 or e.code >= 500:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"  META API: HTTP {e.code}, retry za {wait}s (pokus {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
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
    """Paginated API call with retry logic."""
    if params is None:
        params = {}
    url = f"{META_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    token = _get_token()

    results = []
    page = 0
    while url and page < max_pages:
        last_error = None
        data = None

        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url)
                req.add_header("Authorization", f"Bearer {token}")
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

    if page >= max_pages and data and data.get("paging", {}).get("next"):
        print(f"  WARNING: Pagination truncated at {page} pages ({len(results)} records). "
              f"Increase max_pages to get all data.", file=sys.stderr)

    return results
