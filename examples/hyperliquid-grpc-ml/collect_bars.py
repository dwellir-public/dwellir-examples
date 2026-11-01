"""Collect 1-minute bars for a list of coins from one of three sources.

    python collect_bars.py --hours 24 --out bars.parquet                          # gRPC replay
    python collect_bars.py --source index --start 2026-09-01 --end 2026-09-08     # Index fills
    python collect_bars.py --source candles --start 2026-07-01 --end 2026-10-01   # Index candles

grpc:    StreamFills replay, last few days only, full bar schema.
index:   allFillsByTime back to July 2025, full bar schema, 1 credit per fill.
candles: 1-minute candles back to July 2025, price, notional and trades only,
         1 credit per candle.

The gRPC replay stops when it reaches the time the script started.
"""

import argparse
import time

import pandas as pd


def from_grpc(coins, start_ms, stop_ms, bar_ms):
    from hl_stream import BarBuilder, stream_fills

    builder = BarBuilder(bar_ms=bar_ms)
    rows, fills, t0 = [], 0, time.time()
    for _, block_ms, _, fill in stream_fills(coins, start_ms):
        if block_ms >= stop_ms:
            break
        rows += builder.add(block_ms, fill)
        fills += 1
        if fills % 100_000 == 0:
            done = (block_ms - start_ms) / (stop_ms - start_ms)
            print(f"{done:6.1%}  {fills:,} fills  {len(rows):,} bars  {time.time() - t0:.0f}s", flush=True)
    return rows, fills


def from_index(coins, start_ms, stop_ms, bar_ms):
    from hl_index import index_fills
    from hl_stream import BarBuilder

    rows, fills, t0 = [], 0, time.time()
    for coin in coins:
        builder = BarBuilder(bar_ms=bar_ms)
        for fill in index_fills(coin, start_ms, stop_ms):
            rows += builder.add(fill["time"], fill)
            fills += 1
            if fills % 100_000 == 0:
                print(f"{coin}  {fills:,} fills  {len(rows):,} bars  {time.time() - t0:.0f}s", flush=True)
        rows += builder.flush()
    return rows, fills


def from_candles(coins, start_ms, stop_ms, bar_ms):
    from hl_index import index_candles

    interval = {1_000: "1s", 60_000: "1m", 300_000: "5m"}[bar_ms]
    parts = []
    for coin in coins:
        parts.append(index_candles(coin, interval, start_ms, stop_ms))
        print(f"{coin}  {len(parts[-1]):,} candles", flush=True)
    bars = pd.concat(parts, ignore_index=True)
    return bars, len(bars)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["grpc", "index", "candles"], default="grpc")
    ap.add_argument("--coins", default="BTC,ETH,SOL,HYPE,XRP,DOGE,SUI,BNB")
    ap.add_argument("--hours", type=float, default=24, help="grpc: replay this many hours back")
    ap.add_argument("--start", help="index/candles: UTC start, e.g. 2026-09-01")
    ap.add_argument("--end", help="index/candles: UTC end (exclusive)")
    ap.add_argument("--bar-seconds", type=int, default=60)
    ap.add_argument("--out", default="bars.parquet")
    args = ap.parse_args()

    coins = args.coins.split(",")
    bar_ms = args.bar_seconds * 1000
    if args.source == "grpc":
        stop_ms = int(time.time() * 1000)
        start_ms = stop_ms - int(args.hours * 3_600_000)
    else:
        start_ms = int(pd.Timestamp(args.start, tz="UTC").timestamp() * 1000)
        stop_ms = int(pd.Timestamp(args.end, tz="UTC").timestamp() * 1000)

    rows, n = {"grpc": from_grpc, "index": from_index, "candles": from_candles}[args.source](coins, start_ms, stop_ms, bar_ms)
    bars = pd.DataFrame(rows)
    if not pd.api.types.is_datetime64_any_dtype(bars["time"]):
        bars["time"] = pd.to_datetime(bars["time"], unit="ms", utc=True)
    bars.to_parquet(args.out, index=False)
    unit = "candles" if args.source == "candles" else "fills"
    print(f"{n:,} {unit} -> {len(bars):,} bars for {bars.coin.nunique()} coins -> {args.out}")


if __name__ == "__main__":
    main()
