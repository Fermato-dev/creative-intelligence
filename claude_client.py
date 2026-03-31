#!/usr/bin/env python3
"""
Fermato Claude API Client — sdileny modul
==========================================
Jednotne rozhrani pro volani Claude API (text i vision),
JSON parsing z odpovedi, a cost tracking.

Pouziti:
    from claude_client import call_claude, call_claude_vision, parse_json_from_response
"""

import json
import os
import re
import urllib.request

# ── Config ──

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Pricing per 1M tokens (Sonnet 4)
_INPUT_PRICE_PER_M = 3
_OUTPUT_PRICE_PER_M = 15


def _calculate_cost(usage):
    """Vypocita cost z usage dat."""
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return (input_tokens * _INPUT_PRICE_PER_M + output_tokens * _OUTPUT_PRICE_PER_M) / 1_000_000


def _extract_text(result):
    """Extrahuje text z Claude response."""
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block["text"]
    return text


def _make_request(body, timeout=120):
    """Posle request na Claude API a vrati (result_dict, cost)."""
    api_key = ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY neni nastaven")

    encoded = json.dumps(body).encode()
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


# ── Public API ──

def call_claude(prompt, max_tokens=4000, model=None):
    """Zavola Claude API s textovym promptem.

    Returns:
        tuple: (response_text, cost_usd)
    """
    body = {
        "model": model or CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    result, cost = _make_request(body)
    return _extract_text(result), cost


def call_claude_vision(images_b64, prompt, max_tokens=2000, model=None):
    """Zavola Claude Vision API s obrazky (base64).

    Args:
        images_b64: list of base64-encoded image strings (JPEG)
        prompt: textovy prompt
        max_tokens: max output tokens

    Returns:
        tuple: (response_text, cost_usd)
    """
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
    """Extrahuje JSON z Claude odpovedi (muze byt obaleny v markdown).

    Zkusi v poradi:
    1. Primo parse celeho textu
    2. Extrakce z ```json``` code blocku
    3. Hledani prvniho {...} objektu

    Returns:
        dict: parsed JSON, nebo {"raw_text": text, "_parse_error": True}
    """
    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. First JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {"raw_text": text, "_parse_error": True}
