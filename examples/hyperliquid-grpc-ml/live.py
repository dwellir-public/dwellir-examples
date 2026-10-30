"""Warm a model on replayed history, then keep it learning on the live stream.

    python live.py --coin BTC --warmup-hours 6

StreamFills replays from the start time and then tails live data on the same
call, so the model crosses from history into the present without a second
data source. Each closed 1-minute bar prints a forecast of the next h-bar
return, and the return that followed the forecast made h bars ago.
"""

import argparse
import time

import numpy as np
import pandas as pd

from hl_stream import BarBuilder, stream_fills
from mlkit import ForwardLabels, RLS
from research import INPUTS, features, model_inputs, to_grid

TRAILING_BARS = 600  # enough history for the longest rolling window


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--warmup-hours", type=float, default=6)
    ap.add_argument("--h", type=int, default=5)
    args = ap.parse_args()

    live_from = pd.Timestamp.now(tz="UTC").floor("1min")
    start_ms = int(time.time() * 1000 - args.warmup_hours * 3_600_000)
    builder = BarBuilder()
    labels, model = ForwardLabels(args.h), RLS(len(INPUTS), forget=0.998, ridge=10)
    rows, history, last_t = [], [], None

    for _, block_ms, _, fill in stream_fills([args.coin], start_ms):
        for bar in builder.add(block_ms, fill):
            rows.append(bar)
        if not rows or (last_t is not None and pd.Timestamp(rows[-1]["time"], unit="ms", tz="UTC") <= last_t):
            continue
        rows = rows[-TRAILING_BARS:]
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        b = to_grid(df)
        X = model_inputs(features(b))
        new = X.index if last_t is None else X.index[X.index > last_t]
        for t in new:
            x, px = X.loc[t].to_numpy(), b.close.loc[t]
            if not np.all(np.isfinite(x)):
                continue
            forecast = model.predict(x)
            done = labels.update(x, px)
            if done is not None:
                model.update(done[1], done[0])
            history.append((t, forecast, px))
            if t >= live_from:
                then = history[-1 - args.h] if len(history) > args.h else None
                realized = f"{np.log(px / then[2]) * 1e4:+7.2f}" if then else "    n/a"
                said = f"{then[1] * 1e4:+7.2f}" if then else "    n/a"
                print(f"{t:%H:%M}  {args.coin} {px:>10,.1f}  next {args.h}m forecast {forecast * 1e4:+7.2f} bp"
                      f"  | {args.h}m ago said {said} bp, got {realized} bp", flush=True)
            elif len(history) % 60 == 0:
                print(f"replay {t:%Y-%m-%d %H:%M}  {len(history):,} bars learned", flush=True)
        last_t = new[-1] if len(new) else last_t


if __name__ == "__main__":
    main()
