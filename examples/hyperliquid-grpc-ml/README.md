# Machine learning on Hyperliquid gRPC fills

Build a training set from Hyperliquid fills or candles, learn from it one bar at a time, and score the forecasts honestly. The data comes from three Dwellir sources that produce the same bars:

- **gRPC `StreamFills`** replays the last few days and then keeps streaming live on the same call, so the same code builds the history and runs live.
- **Hyperliquid Index fills** (`allFillsByTime`) serve the same fills back to 27 July 2025.
- **Hyperliquid Index candles** serve `1s`, `1m` and `5m` OHLCV back to 27 July 2025, for long price-only tests.

- Chain: Hyperliquid mainnet (HyperCore)
- Language: Python 3.10 or newer
- Difficulty: Intermediate
- Dependencies: `grpcio`, `grpcio-tools`, `numpy`, `pandas`, `pyarrow`
- Needs: a Dwellir API key. The gRPC replay and `live.py` also need the Hyperliquid gRPC add-on; the Index paths do not.

Companion blog post: [Machine learning on Hyperliquid data](https://www.dwellir.com/blog/hyperliquid-machine-learning-grpc).

## What is in here

| File | What it does |
|------|--------------|
| `hl_stream.py` | Connects to the gRPC gateway, streams fills with resume-from-cursor, rolls taker fills into bars |
| `hl_index.py` | Pages indexed fills (with liquidations joined) and candle ranges from the Hyperliquid Index, and reads dashboard full-history exports |
| `collect_bars.py` | Writes 1-minute bars to Parquet from `--source grpc` (last N hours), `index` (fills for any dates) or `candles` |
| `mlkit.py` | Rolling statistics, forward labels, recursive least squares, forecast scoring with Newey-West t, a Kalman hedge ratio, PCA and walk-forward PCA regression |
| `research.py` | Runs all of the above on the bars and prints each result |
| `live.py` | Warms the online model on replayed history, then keeps it learning on live fills |

Each bar built from fills holds OHLC and VWAP from taker fills, taker buy and sell notional, the part of that flow that opened new positions (from each fill's `dir`), liquidation notional split into long and short, and the trade count. Bars from candles hold OHLC, VWAP, notional and trade count only, because a candle does not record the aggressor side; `research.py` detects that and switches to price inputs.

## Quick start

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/hyperliquid-grpc-ml
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

curl -fsSLo v3.proto https://www.dwellir.com/docs/hyperliquid/grpc/v3.proto
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. v3.proto

export DWELLIR_API_KEY=your-api-key
python collect_bars.py --hours 24 --out bars.parquet
python research.py bars.parquet --coin BTC --pair ETH
python live.py --coin BTC --warmup-hours 6
```

Older dates from the Index, no gRPC stubs needed:

```bash
python collect_bars.py --source index --coins BTC,ETH --start 2026-09-01 --end 2026-09-08 --out bars_sep.parquet
python collect_bars.py --source candles --start 2026-07-29 --end 2026-10-27 --out candles90.parquet
python research.py candles90.parquet --coin BTC --pair ETH
```

A full-history candle export from the dashboard (`btc-1m-full.parquet` or `.csv.gz`) loads with `hl_index.load_export(path)`.

A 24-hour replay of 8 coins took 4 minutes and a 72-hour replay 12 minutes. The filtered stream sends one message per block with a matching fill, and each message costs 1 API credit. For these 8 coins that was 10,216 messages in one hour.

## Which source to use

| | gRPC `StreamFills` | Index `allFillsByTime` | Index candles |
|---|---|---|---|
| History | About 96 hours back, then live | Back to 27 July 2025 | Back to 27 July 2025 |
| Bar columns | All | All (liquidations from `liquidationFillsByTime`) | OHLC, notional, trades |
| Cost | 1 credit per block with a matching fill | 1 credit per fill (both sides of each match) | 1 credit per candle |
| Measured | 72 h of 8 coins in 12 min | About 1,000 fills/s; BTC 23,696 fills in a quiet hour, 94,772 in a liquidation-heavy one | 90 days of 8 coins (1.03M candles) in 5 min |

On 25 October 2026 `StreamFills` replayed about 96 hours; a start time before that returns `NOT_FOUND: Data for provided timestamp is pruned`. Use gRPC inside that window, Index fills for older flow data, and candles when price and volume are enough.

The three agree. On 28 October 2026, bars built from Index fills for BTC and ETH, 12:00 to 13:00 UTC on 23 October, matched the gRPC bars exactly on every column, and candles matched on OHLC, notional and trade count. For BTC 15:00 to 16:00 UTC on 24 October, the Index liquidation columns ($34.3M of long liquidations) matched too.

For raw files, the [Hyperliquid historical data archive](https://www.dwellir.com/docs/hyperliquid/historical-data) has the `node_fills_by_block` data the Index is built from.

## Example output

```text
$ python research.py bars.parquet   # 72 hours, 8 coins, run on 25 October 2026
BTC: 4,320 one-minute bars, 2026-10-22 19:44:00+00:00 to 2026-10-25 19:43:00+00:00

== 2. The lookahead trap =================================================
corr(flow_5, return of the same bar) = +0.162   <- uses the future
corr(flow_5, return of the next bar) = +0.007   <- what you can trade

== 3. Online regression with 5-bar labels ================================
coefficients (intercept first): [ 1.1e-05  3.3e-05 -2.6e-05 -2.1e-05  2.0e-05]
        ic     hit       t     n
h                               
1  -0.0425  0.4859 -2.6540  4225
5  -0.0671  0.4869 -2.4449  4221
15 -0.0690  0.4961 -1.6811  4211
trading one bar after the forecast:
        ic     hit       t     n
h                               
1  -0.0387  0.4858 -2.3272  4224
5  -0.0546  0.4897 -2.0062  4220
15 -0.0593  0.4955 -1.4542  4210

== 4. Kalman hedge ratio: ETH on BTC =====================================
beta: start 0.990, end 1.378, range 0.980 to 1.384
z std 0.98, |z| > 2 on 4.0% of bars
forecast = -z, scored on the hedged pair return that followed:
        ic     hit       t     n
h                               
1   0.0991  0.5461  3.3886  4199
5   0.0702  0.5246  1.9623  4195
15  0.0597  0.5390  1.0648  4185
the same, trading one bar after the signal:
        ic     hit       t     n
h                               
1   0.0130  0.5050  0.4169  4198
5   0.0164  0.5123  0.4297  4194
15  0.0240  0.5250  0.3907  4184

== 6. Walk-forward PCA regression, 5-bar labels ==========================
59 refits; PC1 share at first/last refit: 0.52 / 0.53
        ic     hit       t     n
h                               
1  -0.0061  0.5062 -0.3106  3535
5   0.0100  0.5134  0.3092  3531
15  0.0102  0.5091  0.2357  3521
```

90 days of 1-minute candles, 29 July to 27 October 2026 (price inputs, since candles have no flow):

```text
$ python research.py candles90.parquet --coin BTC --pair ETH
BTC: 129,600 one-minute bars, 2026-07-29 00:00:00+00:00 to 2026-10-26 23:59:00+00:00

== 2. The lookahead trap =================================================
corr(ret_z_30, return of the same bar) = +0.319   <- uses the future
corr(ret_z_30, return of the next bar) = -0.000   <- what you can trade

== 3. Online regression with 5-bar labels ================================
        ic     hit       t       n
1  -0.0074  0.4943 -1.1774  129475
trading one bar after the forecast:
1  -0.0111  0.4948 -1.9697  129474

== 4. Kalman hedge ratio: ETH on BTC =====================================
beta: start 0.916, end 1.319, range 0.916 to 1.361
1   0.0623  0.5401  3.1882  129479
the same, trading one bar after the signal:
1   0.0117  0.5071  0.8592  129478

== 6. Walk-forward PCA regression, 5-bar labels ==========================
2146 refits; PC1 share at first/last refit: 0.62 / 0.62
1  -0.0109  0.4982 -0.9388  128715
```

Read the output as a set of warnings, not a strategy. Flow correlates with the return of its own bar and not with the next one. The online model is significantly wrong because its inputs flip sign from day to day. The Kalman pairs signal disappears once you trade one bar later, which means it came from bid-ask bounce in the last trade price. Walk-forward PCA regression finds nothing. Add information the price does not already contain (book depth, wallet flows, liquidation levels) before you reach for a bigger model.

## Notes

- Every match produces one fill per side. The bars count only the taker side (`crossed: true`), so each trade counts once and the side shows who was aggressive.
- The stream sends no heartbeats. A filtered stream on a quiet coin can be silent and healthy. `hl_stream.py` resumes from the last block on `UNAVAILABLE`, `DEADLINE_EXCEEDED`, `DATA_LOSS` and `RESOURCE_EXHAUSTED`.
- `RLS` re-symmetrizes its covariance after each update. Without that, rounding drift on the 90-day run grew until one forecast hit -14,416 and the t-statistics reached 200.
- `mlkit.py` uses numpy and pandas only, so you can read every model in a few lines. Rolling statistics follow pandas conventions (variance divides by n - 1).
