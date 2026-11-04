"""Read a wallet's fills and the candles around them from Dwellir's Hyperliquid Index.

- user_fills(): every fill for one wallet in a time window, paged through
                userFillsByTime. Each fill returned costs 1 API credit.
- candles():    1s or 1m OHLCV for one market from the candle range endpoint.
                Each candle returned costs 1 API credit, so results are cached
                on disk and a second run of the same window costs nothing.

Both cover history back to 27 July 2025.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HOST = os.environ.get("DWELLIR_INDEX_HOST", "https://api-hyperliquid-index.n.dwellir.com")
CACHE = Path(os.environ.get("POSTMORTEM_CACHE", ".cache"))
FILL_PAGE = 2000
CANDLE_PAGE = 5000
INTERVAL_MS = {"1s": 1_000, "1m": 60_000}
CANDLE_COLS = ["t", "o", "h", "l", "c", "v", "n"]


def _url(path):
    key = os.environ.get("DWELLIR_API_KEY")
    if not key:
        raise RuntimeError("Set DWELLIR_API_KEY to your Dwellir API key")
    return f"{HOST}/{key}{path}"


def _request(url, body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json", "user-agent": "dwellir-examples/hyperliquid-trade-postmortem"}
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise RuntimeError(f"{err.code}: {err.read().decode()[:300]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt)


def user_fills(user, start_ms, end_ms, coin=None):
    """All fills for `user` in [start_ms, end_ms), oldest first, as a DataFrame.

    /info returns a bare array, so the next page starts from a cursor built
    from the last fill as time_txIndex. A page shorter than the limit is the
    last one.
    """
    body = {"type": "userFillsByTime", "user": user.lower(), "startTime": int(start_ms), "endTime": int(end_ms), "limit": FILL_PAGE}
    if coin:
        body["coin"] = coin
    rows = []
    while True:
        page = _request(_url("/info"), body)
        rows += page
        if len(page) < FILL_PAGE:
            break
        body.pop("startTime", None)
        body["cursor"] = f"{page[-1]['time']}_{page[-1]['txIndex']}"
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ["px", "sz", "startPosition", "closedPnl", "fee"]:
        df[col] = pd.to_numeric(df[col])
    # tid is a random trade id. Fills in one block are ordered by txIndex.
    return df.sort_values(["time", "txIndex"], kind="stable").reset_index(drop=True)


def _iso(ms):
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_candles(market, interval, start_ms, end_ms):
    params = {"market": market, "interval": interval, "start": _iso(start_ms), "end": _iso(end_ms), "limit": CANDLE_PAGE}
    rows = []
    while True:
        page = _request(_url("/v1/candles/range?" + urllib.parse.urlencode(params)))
        rows += page["data"]
        if not page.get("hasMore"):
            break
        params.pop("start", None)
        params["cursor"] = page["nextCursor"]
    df = pd.DataFrame(rows, columns=["s", "i", "t", "T", "o", "h", "l", "c", "v", "q", "n", "x"])
    df = df[CANDLE_COLS].copy()
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = pd.to_numeric(df[col])
    return df


def candles(market, interval, start_ms, end_ms):
    """Candles for `market` with open time in [start_ms, end_ms).

    The window is widened to whole intervals and clipped to the last finished
    bucket, because the endpoint rejects unaligned or in-progress ranges.
    Candles are sparse: a bucket with no trades is missing, not zero.
    Results are cached per market, interval and window in POSTMORTEM_CACHE.
    """
    step = INTERVAL_MS[interval]
    start = start_ms // step * step
    last_done = (int(time.time() * 1000) // step - 1) * step
    end = min(-(-end_ms // step) * step, last_done)
    if end <= start:
        return pd.DataFrame(columns=CANDLE_COLS)
    path = CACHE / f"{market.replace(':', '_').replace('@', 'at')}-{interval}-{start}-{end}.csv.gz"
    if path.exists():
        return pd.read_csv(path)
    df = _fetch_candles(market, interval, start, end)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df
