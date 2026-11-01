"""Pull Hyperliquid fills and candles from Dwellir's Hyperliquid Index.

The gRPC replay reaches back a few days. The Index serves the same fills and
1s/1m/5m candles back to 27 July 2025, over plain HTTPS with the same API key.

- index_fills():   every fill for one coin, paged through allFillsByTime.
                   Feed them to hl_stream.BarBuilder for the full bar schema.
- index_candles(): 1s/1m/5m OHLCV candles from the candle range endpoint.
                   Candles have no buy/sell split, so the bars carry price,
                   notional and trade count only.
- load_export():   the same candles from a dashboard full-history export
                   (.csv.gz or .parquet).
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

HOST = os.environ.get("DWELLIR_INDEX_HOST", "https://api-hyperliquid-index.n.dwellir.com")
HOUR_MS = 3_600_000
PAGE = 2000


def _url(path):
    return f"{HOST}/{os.environ['DWELLIR_API_KEY']}{path}"


def _request(url, body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json", "user-agent": "dwellir-examples/hyperliquid-grpc-ml"}
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


def _by_time(kind, start_ms, end_ms, coin=None):
    """Page a *ByTime fills method one hour at a time, oldest first.

    /info returns a bare array, so the cursor is built from the last fill as
    time_txIndex. A page shorter than the limit ends the hour.
    """
    for hour in range(start_ms, end_ms, HOUR_MS):
        body = {"type": kind, "startTime": hour, "endTime": min(hour + HOUR_MS, end_ms), "limit": PAGE}
        if coin:
            body["coin"] = coin
        while True:
            fills = _request(_url("/info"), body)
            yield from fills
            if len(fills) < PAGE:
                break
            body.pop("startTime", None)
            body["cursor"] = f"{fills[-1]['time']}_{fills[-1]['txIndex']}"


def index_fills(coin, start_ms, end_ms):
    """Yield every fill for `coin` in [start_ms, end_ms), oldest first.

    allFillsByTime returns both sides of each match, like StreamFills, but
    without the `liquidation` field. That comes from liquidationFillsByTime and
    is joined back on the trade id, so BarBuilder sees the same fill shape as
    on the gRPC path. Each fill returned costs 1 API credit.
    """
    for hour in range(start_ms, end_ms, HOUR_MS):
        stop = min(hour + HOUR_MS, end_ms)
        liq = {f["tid"]: f["liquidation"] for f in _by_time("liquidationFillsByTime", hour, stop, coin)}
        for fill in _by_time("allFillsByTime", hour, stop, coin):
            if fill.get("tid") in liq:
                fill["liquidation"] = liq[fill["tid"]]
            yield fill


def _iso(ms):
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def index_candles(market, interval, start_ms, end_ms):
    """Candles for one market in [start_ms, end_ms) as bars. Times must align to the interval."""
    params = {"market": market, "interval": interval, "start": _iso(start_ms), "end": _iso(end_ms), "limit": 5000}
    rows = []
    while True:
        page = _request(_url("/v1/candles/range?" + urllib.parse.urlencode(params)))
        rows += page["data"]
        if not page.get("hasMore"):
            break
        params.pop("start", None)
        params["cursor"] = page["nextCursor"]
    return candles_to_bars(pd.DataFrame(rows))


def load_export(path):
    """Read a full-history export ({market}-{interval}-full.csv.gz or .parquet) as bars."""
    return candles_to_bars(pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path))


def candles_to_bars(c):
    """Map the candle schema (s, t, o, h, l, c, v, q, n) to the bar columns research.py reads.

    Flow columns (buy_ntl, open_buy_ntl, liq_*) are absent, because a candle
    does not say which side was the aggressor.
    """
    if c.empty:
        return pd.DataFrame(columns=["time", "coin", "open", "high", "low", "close", "notional", "trades", "vwap"])
    num = {k: pd.to_numeric(c[k]) for k in ["o", "h", "l", "c", "v", "q"]}
    return pd.DataFrame({
        "time": pd.to_datetime(c["t"], unit="ms", utc=True),
        "coin": c["s"].astype(str),
        "open": num["o"], "high": num["h"], "low": num["l"], "close": num["c"],
        "notional": num["q"], "trades": c["n"].astype(int), "vwap": num["q"] / num["v"],
    })
