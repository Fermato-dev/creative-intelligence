"""Claude API client — text, vision, JSON parsing, cost tracking."""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from .config import CLAUDE_MODEL

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

_INPUT_PRICE_PER_M = 3
_OUTPUT_PRICE_PER_M = 15


def _calculate_cost(usage):
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return (input_tokens * _INPUT_PRICE_PER_M + output_tokens * _OUTPUT_PRICE_PER_M) / 1_000_000


def _extract_text(result):
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block["text"]
    return text


def _make_request(body, timeout=120, max_retries=3):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY neni nastaven")

    encoded = json.dumps(body).encode()
    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                ANTHROPIC_API_URL,
                data=encoded,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_API_VERSION,
                    "content-type": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())

            cost = _calculate_cost(result.get("usage", {}))
            return result, cost
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 529) or e.code >= 500:
                wait = 2 ** (attempt + 1)
                print(f"  CLAUDE API: HTTP {e.code}, retry za {wait}s ({attempt + 1}/{max_retries})",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  CLAUDE API: {type(e).__name__}, retry za {wait}s ({attempt + 1}/{max_retries})",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise last_error


def call_claude(prompt, max_tokens=4000, model=None):
    """Text prompt -> (response_text, cost_usd)."""
    body = {
        "model": model or CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    result, cost = _make_request(body)
    return _extract_text(result), cost


def call_claude_vision(images_b64, prompt, max_tokens=2000, model=None):
    """Vision prompt with base64 images -> (response_text, cost_usd)."""
    content = []
    for img in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img}
        })
    content.append({"type": "text", "text": prompt})

    body = {
        "model": model or CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}]
    }
    result, cost = _make_request(body, timeout=60)
    return _extract_text(result), cost


def parse_json_from_response(text):
    """Extract JSON from Claude response (handles markdown code blocks)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {"raw_text": text, "_parse_error": True}
