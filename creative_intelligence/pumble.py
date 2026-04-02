"""Pumble notification client."""

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import PUMBLE_CHANNEL, PUMBLE_API_BASE, REPO_ROOT

OUTPUT_DIR = REPO_ROOT / "data"


def send_pumble(text, channel=PUMBLE_CHANNEL):
    """Send message to Pumble channel via HTTP API."""
    token = os.environ.get("PUMBLE_API_TOKEN", "")
    if not token:
        print("WARN: PUMBLE_API_TOKEN neni nastaven, ukladam do souboru", file=sys.stderr)
        return _save_fallback(text, channel)

    try:
        req = urllib.request.Request(
            f"{PUMBLE_API_BASE}/listChannels",
            headers={"Api-Key": token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            channels = json.loads(resp.read())

        channel_id = None
        for item in channels:
            ch = item.get("channel", item)
            if ch.get("name", "").lower() == channel.lower():
                channel_id = ch["id"]
                break

        if not channel_id:
            print(f"WARN: Pumble kanal '{channel}' nenalezen", file=sys.stderr)
            return _save_fallback(text, channel)

        body = json.dumps({"channelId": channel_id, "text": text}).encode()
        req = urllib.request.Request(
            f"{PUMBLE_API_BASE}/sendMessage",
            data=body,
            method="POST",
            headers={"Api-Key": token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True

    except Exception as e:
        print(f"WARN: Pumble odeslani selhalo: {e}", file=sys.stderr)
        return _save_fallback(text, channel)


def _save_fallback(text, channel):
    """Fallback: save message to file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "pumble_notification.txt"
    path.write_text(
        json.dumps({"channel": channel, "text": text, "generated_at": datetime.now().isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    (OUTPUT_DIR / "pumble_notification_plain.txt").write_text(text, encoding="utf-8")
    return False
