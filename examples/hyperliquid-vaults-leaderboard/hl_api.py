"""Read helpers for Hyperliquid vault and leaderboard data.

Three sources, one module:

- Dwellir's Hyperliquid Info proxy for the per-user queries it serves
  (clearinghouseState, batchClearinghouseStates, userVaultEquities, leadingVaults, ...).
- Hyperliquid's public Info endpoint for the two vault queries the proxy does not serve
  (vaultDetails, portfolio). Checked on 5 November 2026.
- The stats-data feeds behind app.hyperliquid.xyz: /Mainnet/vaults (every vault, about
  14 MB) and /Mainnet/leaderboard (every ranked trader, about 40 MB). Both are cached on
  disk because you want to download them once per run, not once per lookup.
"""

import json
import os
import time
from pathlib import Path

import httpx

API_KEY = os.environ.get("DWELLIR_API_KEY", "")
DWELLIR_INFO = f"https://api-hyperliquid-mainnet-info.n.dwellir.com/{API_KEY}/info"
PUBLIC_INFO = "https://api.hyperliquid.xyz/info"
STATS_BASE = "https://stats-data.hyperliquid.xyz/Mainnet"

# Info types the Dwellir proxy answers with 403 "type not allowed". Route these
# to the public endpoint. Everything else goes through Dwellir.
PUBLIC_ONLY = {"vaultDetails", "portfolio"}

CACHE_DIR = Path(__file__).parent / ".cache"


def info(query: dict, timeout: float = 30.0):
    """POST one Info query to the right host and return the parsed JSON."""
    if query["type"] in PUBLIC_ONLY or not API_KEY:
        url = PUBLIC_INFO
    else:
        url = DWELLIR_INFO
    resp = httpx.post(url, json=query, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def feed(name: str, max_age_s: int = 600):
    """Download /Mainnet/<name> once and reuse it for max_age_s seconds."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_s:
        return json.loads(path.read_text())
    resp = httpx.get(f"{STATS_BASE}/{name}", timeout=120.0)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return resp.json()


def windows(pairs):
    """Turn Hyperliquid's [["day", {...}], ["week", {...}]] lists into a dict."""
    return {name: value for name, value in pairs}


def usd(value) -> str:
    """Format a numeric string as a dollar amount with thousands separators."""
    return f"${float(value):,.0f}"


def pct(value, signed: bool = True) -> str:
    """Format a fraction (0.12 = 12%) as a percentage, signed for returns."""
    return f"{float(value) * 100:{'+' if signed else ''}.1f}%"
