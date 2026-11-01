"""Features, labels, online regression, a Kalman hedge ratio and walk-forward PCA
on 1-minute Hyperliquid bars.

    python research.py bars.parquet --coin BTC --pair ETH

Bars built from fills (gRPC or Index) carry taker flow and use the flow
features. Bars from candles carry price, notional and trade count only, and
use price features instead.
"""

import argparse

import numpy as np
import pandas as pd

from mlkit import (ForwardLabels, KalmanBeta, RLS, forward_log_return, imbalance,
                   parkinson_vol, pca, score, walk_forward_pcr, zscore)

FLOWS = ["notional", "buy_ntl", "sell_ntl", "open_buy_ntl", "open_sell_ntl", "liq_long_ntl", "liq_short_ntl", "trades"]


def load(path, coin):
    bars = pd.read_parquet(path)
    return to_grid(bars[bars.coin == coin])


def to_grid(bars):
    """One coin's bars on a full minute grid. Quiet minutes carry the last price."""
    b = bars.set_index("time").sort_index()
    grid = pd.date_range(b.index[0], b.index[-1], freq="1min")
    b = b.reindex(grid)
    b["close"] = b["close"].ffill()
    for col in ["open", "high", "low", "vwap"]:
        b[col] = b[col].fillna(b["close"])
    flows = [c for c in FLOWS if c in b]
    b[flows] = b[flows].fillna(0.0)
    return b


def has_flow(b):
    return "buy_ntl" in b


def features(b):
    f = pd.DataFrame(index=b.index)
    if has_flow(b):
        f["flow_5"] = imbalance(b.buy_ntl, b.sell_ntl, 5)
        f["open_flow_15"] = imbalance(b.open_buy_ntl, b.open_sell_ntl, 15)
        f["liq_15"] = (b.liq_short_ntl - b.liq_long_ntl).rolling(15).sum() / b.notional.rolling(15).sum()
    f["ret_1"] = np.log(b.close).diff()
    f["ret_5"] = np.log(b.close).diff(5)
    f["ntl_z_60"] = zscore(np.log1p(b.notional), 60)
    f["ret_z_30"] = zscore(np.log(b.close), 30)
    f["vol_30"] = parkinson_vol(b.high, b.low, 30)
    return f


INPUTS = ["flow_5", "open_flow_15", "liq_15", "ret_z_30"]
PRICE_INPUTS = ["ret_1", "ret_5", "ret_z_30", "ntl_z_60"]  # for candle bars


def model_inputs(f, inputs=INPUTS):
    """Divide each input by its trailing 4-hour std so ridge treats them alike."""
    def scale(s):
        sd = s.rolling(240, min_periods=60).std()
        return (s / sd).mask(sd == 0, 0.0)  # an input that has not moved (no liquidations) is 0
    return f[inputs].apply(scale)


def section(title):
    print(f"\n== {title} " + "=" * (70 - len(title)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--pair", default="ETH")
    ap.add_argument("--h", type=int, default=5, help="label horizon in bars")
    args = ap.parse_args()

    b = load(args.bars, args.coin)
    f = features(b)
    h = args.h
    print(f"{args.coin}: {len(b):,} one-minute bars, {b.index[0]} to {b.index[-1]}")

    section("1. Rolling statistics")
    print(f.describe().T[["mean", "std", "min", "max"]].round(4))

    section("2. The lookahead trap")
    ret_now = np.log(b.close).diff()
    ret_next = forward_log_return(b.close, 1)
    signal = "flow_5" if has_flow(b) else "ret_z_30"
    print(f"corr({signal}, return of the same bar) = {f[signal].corr(ret_now):+.3f}   <- uses the future")
    print(f"corr({signal}, return of the next bar) = {f[signal].corr(ret_next):+.3f}   <- what you can trade")

    section(f"3. Online regression with {h}-bar labels")
    inputs = INPUTS if has_flow(b) else PRICE_INPUTS
    X = model_inputs(f, inputs)
    labels, model = ForwardLabels(h), RLS(len(inputs), forget=0.998, ridge=10)
    forecast = pd.Series(np.nan, index=b.index)
    for t, (x, px) in enumerate(zip(X.to_numpy(), b.close.to_numpy())):
        if not np.all(np.isfinite(x)):
            continue
        forecast.iloc[t] = model.predict(x)  # made before this bar's label exists
        done = labels.update(x, px)
        if done is not None:
            model.update(done[1], done[0])
    print("coefficients (intercept first):", np.round(model.w, 6))
    print(score(forecast, b.close).round(4))
    print("trading one bar after the forecast:")
    print(score(forecast, b.close, delay=1).round(4))

    section(f"4. Kalman hedge ratio: {args.pair} on {args.coin}")
    p = load(args.bars, args.pair).reindex(b.index).ffill()
    kf = KalmanBeta(delta=1e-8, obs_var=1e-7)
    y, x = np.log(p.close / p.close.iloc[0]), np.log(b.close / b.close.iloc[0])
    k = pd.DataFrame([kf.update(yi, xi) for yi, xi in zip(y, x)], index=b.index)
    k = k.iloc[120:]  # let the filter settle
    print(f"beta: start {k.beta.iloc[0]:.3f}, end {k.beta.iloc[-1]:.3f}, range {k.beta.min():.3f} to {k.beta.max():.3f}")
    print(f"z std {k.z.std():.2f}, |z| > 2 on {np.mean(np.abs(k.z) > 2):.1%} of bars")
    # If the spread mean-reverts, a high z is followed by the pair underperforming
    # the hedge it was priced against. Score -z on that hedged move, beta frozen at t.
    def hedged(n):
        return (forward_log_return(p.close, n) - k.beta * forward_log_return(b.close, n)).reindex(k.index)
    print("forecast = -z, scored on the hedged pair return that followed:")
    print(score(-k.z, None, fwd=hedged).round(4))
    print("the same, trading one bar after the signal:")
    print(score(-k.z, None, fwd=hedged, delay=1).round(4))

    section("5. Principal components across coins")
    coins = sorted(pd.read_parquet(args.bars, columns=["coin"]).coin.unique())
    rets = pd.DataFrame({c: np.log(load(args.bars, c).close).diff() for c in coins}).dropna()
    k = min(3, len(coins))
    pc = pca(rets.to_numpy(), k)
    print("share of variance:", np.round(pc["explained"], 3))
    print(pd.DataFrame(pc["loadings"], index=coins, columns=[f"PC{i + 1}" for i in range(k)]).round(3))

    section(f"6. Walk-forward PCA regression, {h}-bar labels")
    lags = [1, 2, 3, 5, 8, 13, 21, 34]
    if has_flow(b):
        ladder = pd.DataFrame({f"flow_{n}": imbalance(b.buy_ntl, b.sell_ntl, n) for n in lags})
    else:
        ladder = pd.DataFrame({f"ret_{n}": np.log(b.close).diff(n) for n in lags})
    for n in [5, 15, 30, 60]:
        ladder[f"ret_z_{n}"] = zscore(np.log(b.close), n)
    window, refit = 720, 60
    if len(ladder.dropna()) < window + h + refit:
        print(f"need at least {window + h + refit} bars for walk-forward; collect more hours")
        return
    pred, fits = walk_forward_pcr(ladder, b.close, h, window=window, k=3, refit=refit)
    print(f"{len(fits)} refits; PC1 share at first/last refit: {fits[0]['explained'][0]:.2f} / {fits[-1]['explained'][0]:.2f}")
    print(score(pred, b.close).round(4))
    print("trading one bar after the forecast:")
    print(score(pred, b.close, delay=1).round(4))


if __name__ == "__main__":
    main()
