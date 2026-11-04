# Hyperliquid trade post-mortem

Review every closed perp trade from one Hyperliquid wallet against the price path it lived through. For each trade, the notebook asks six questions:

1. Would it have been better not to open it?
2. Should it have been stopped out?
3. Should it have taken profit?
4. Should it have kept holding?
5. Would it have been better to close and reopen?
6. Would it have been better not to add to it?

It then replays stop, target, trailing, time and no-adding rules on the same trades, and checks whether the rule that wins on your earlier trades still helps on your later ones.

- Chain: Hyperliquid mainnet (HyperCore perps, including HIP-3 markets)
- Language: Python 3.10 or newer
- Difficulty: Intermediate
- Dependencies: `numpy`, `pandas`, `matplotlib`, `jupyter`
- Needs: a Dwellir API key. No gRPC add-on.

Companion guide: [Hyperliquid trade post-mortem](https://www.dwellir.com/guides/hyperliquid-trade-postmortem).

## What is in here

| File | What it does |
|------|--------------|
| `hl_index.py` | Pages a wallet's fills from `userFillsByTime` and loads 1s/1m candles from the candle range endpoint, cached on disk |
| `trades.py` | Rebuilds round-trip trades from fills, using each fill's `startPosition`, and handles flips such as `Long > Short` |
| `analysis.py` | MFE, MAE, capture and post-exit moves per trade; the rule replay engine; the six-question diagnosis; rule tests split into earlier and later halves |
| `postmortem.py` | Command-line report, and the `run()` function the notebook calls |
| `plots.py` | Trade chart, excursion scatter, lessons bar, rules bar |
| `postmortem.ipynb` | The notebook |

## Quick start

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/hyperliquid-trade-postmortem
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DWELLIR_API_KEY=your-api-key
python postmortem.py 0xYourWallet --days 30
```

Or open the notebook:

```bash
WALLET=0xYourWallet jupyter notebook postmortem.ipynb
```

Pick dates instead of a lookback, set your own stop and target sizes, or save the per-trade table:

```bash
python postmortem.py 0xYourWallet --start 2026-10-05 --end 2026-11-04 --stop 0.005 --take 0.01 --csv trades.csv
```

## How it works

**Trades from fills.** Every Hyperliquid fill carries `startPosition`, the signed position before the fill. A trade starts when the position leaves zero and ends when it returns to zero. Fills inside one block share a timestamp and are ordered by `txIndex` (`tid` is a random id, so sorting on it scrambles the sequence). If the running position ever disagrees with `startPosition`, the code resyncs and drops the trade it cannot account for, so trades already open when the window starts are skipped.

**Price paths.** For each trade we load 1s candles for the entry minute and the exit minute, and 1m candles from entry to 24 hours after the exit. Overlapping windows for one coin are merged into one request.

**Excursions.** MFE is the best move in your favour while the trade was open, MAE the worst move against you, both in % of your average entry. Capture is the share of the MFE that the exit kept.

**Rule replay.** `simulate()` walks the trade bar by bar. Your real entries and exits happen as they did. When a rule fires, it closes the rest of the position at the rule's price. Stops and time exits also pay 5 bps of slippage, and every synthetic fill pays your own average fee rate. A rule that never fires returns your real PnL. If a stop and a target both fall inside one 1m bar, that minute's 1s candles decide which traded first.

**Stop and target sizes.** By default both come from your own trades. The stop is set where 80% of your winning trades never went further against you. The target is the median best move on your winners. Both are clamped to 0.2% to 5%. Override them with `--stop` and `--take`.

**Lessons.** Each trade gets the one lesson that would have saved the most money:

| Lesson | When it applies |
|--------|-----------------|
| `skip` | The trade lost, and its best move was smaller than its fees plus 0.2%. It never offered a real chance |
| `stop` | A stop at your stop size would have saved the most |
| `take` | A target at your target size would have saved the most |
| `hold` | Price kept moving your way by at least 0.5%, by more than the trade made, and was still there 4 hours later |
| `reenter` | Stopping out, then buying back after a half-stop bounce off the low, would have saved the most |
| `no_adds` | The same exits without the entries placed after the first minute would have saved the most |
| `fine` | No alternative was worth more than 0.1% of the trade's notional |

**Earlier and later halves.** `test_rules()` scores every rule on the first and second half of your trades separately. If you pick the rule that won on the first half and it does not help on the second, it was fitted to your history rather than fixing a habit.

## What it costs

Fills and candles are billed per object returned. A 30-day review of a wallet with 1,118 fills and 64 trades used about 44,000 API credits: 1,118 fills, 37,931 1m candles and 4,834 1s candles. It took 54 seconds. Candles are cached in `.cache/`, so re-running the same window costs only the fills.

## Limits

- PnL excludes funding. Hyperliquid's `closedPnl` excludes it too, so every comparison is like for like, but a trade held through several funding hours had a different real result.
- The Index covers fills and candles back to 27 July 2025.
- Spot (`@123`) and HIP-4 outcome (`#123`) markets are skipped.
- Liquidations are scored like any other exit. Fills from `userFillsByTime` do not mark them.
- The rule replay works on 1m bars between the entry and exit minutes, so it assumes your fills inside a minute happened before that minute's high or low. Tight stops on very short trades are the least reliable.
