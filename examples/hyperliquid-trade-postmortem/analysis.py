"""Score each trade against the price path it lived through, then replay rules.

For every trade we load the candles from the first entry to `after_hours`
past the last exit:

- 1s candles for the entry minute and the exit minute, so the first and last
  prices are the ones the trade actually saw, not the whole minute's range;
- 1m candles in between and after the exit.

From that path we measure how far price ran for and against the trade (MFE
and MAE), how much of the best move the exit kept, and what price did after
the exit. Then `simulate()` replays the trade's own entries and exits under a
rule (stop loss, take profit, trailing stop, time stop, no adding, stop and
re-enter) and returns the PnL the rule would have produced.

All PnL here is before funding. Hyperliquid's closedPnl excludes funding and
so does every counterfactual, so the comparison is like for like.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

import hl_index

MIN = 60_000
HOUR = 3_600_000


# ---------------------------------------------------------------- price paths

class Prices:
    """Fetches and caches candles per coin, merging overlapping trade windows."""

    def __init__(self, trades, after_hours=24):
        self.after = int(after_hours * HOUR)
        self.minute = {}
        for coin in {t.coin for t in trades}:
            spans = sorted((t.open_time // MIN * MIN, t.close_time + self.after) for t in trades if t.coin == coin)
            merged = []
            for s, e in spans:
                if merged and s <= merged[-1][1] + MIN:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])
            parts = [hl_index.candles(coin, "1m", s, e) for s, e in merged]
            df = pd.concat(parts).drop_duplicates("t").sort_values("t")
            self.minute[coin] = df.set_index("t")

    def seconds(self, coin, minute_ms):
        return hl_index.candles(coin, "1s", minute_ms, minute_ms + MIN).set_index("t")

    def path(self, trade, until=None):
        """Bars from the first entry to `until` (default: last exit + after_hours).

        Returns a frame indexed by bar open time with o, h, l, c and `t_end`
        (bar close time): 1s bars in the entry and exit minutes, 1m bars
        everywhere else.
        """
        until = until or trade.close_time + self.after
        m = self.minute[trade.coin]
        entry_min = trade.open_time // MIN * MIN
        exit_min = trade.close_time // MIN * MIN
        open_sec = trade.open_time // 1000 * 1000
        edge = [self.seconds(trade.coin, entry_min)]
        if exit_min != entry_min:
            edge.append(self.seconds(trade.coin, exit_min))
        sec = pd.concat(edge)
        sec = sec[(sec.index >= open_sec) & (sec.index < until)]
        mins = m[(m.index > entry_min) & (m.index != exit_min) & (m.index < until)]
        bars = pd.concat([sec.assign(t_end=sec.index + 999), mins.assign(t_end=mins.index + MIN - 1)])
        return bars[["o", "h", "l", "c", "t_end"]].sort_index()


# ---------------------------------------------------------------- excursions

def excursions(trade, prices):
    """MFE, MAE, capture and post-exit moves for one trade, in % of avg entry."""
    bars = prices.path(trade)
    held = bars[bars.index <= trade.close_time]
    after = bars[bars.index > trade.close_time]
    s, entry, exit_ = trade.side, trade.avg_entry, trade.avg_exit
    if held.empty:
        return {}
    best = held["h"].max() if s > 0 else held["l"].min()
    worst = held["l"].min() if s > 0 else held["h"].max()
    mfe = s * (best - entry) / entry
    mae = s * (worst - entry) / entry
    realized = s * (exit_ - entry) / entry
    best_t = (held["h"].idxmax() if s > 0 else held["l"].idxmin())
    out = {
        "mfe_pct": 100 * mfe,
        "mae_pct": 100 * mae,
        "realized_pct": 100 * realized,
        "capture": realized / mfe if mfe > 0 else np.nan,
        "mins_to_mfe": (best_t - trade.open_time) / MIN,
    }
    for h in (1, 4, 24):
        window = after[after.index <= trade.close_time + h * HOUR]
        if window.empty:
            out[f"after_{h}h_best_pct"] = out[f"after_{h}h_close_pct"] = np.nan
            continue
        run = window["h"].max() if s > 0 else window["l"].min()
        out[f"after_{h}h_best_pct"] = 100 * s * (run - exit_) / exit_
        out[f"after_{h}h_close_pct"] = 100 * s * (window["c"].iloc[-1] - exit_) / exit_
    return {k: float(v) for k, v in out.items()}


# ---------------------------------------------------------------- replay rules

@dataclass
class Rule:
    name: str
    stop: float = None        # fraction against the current average entry, e.g. 0.02
    take: float = None        # fraction in favour of the current average entry
    trail: float = None       # fraction back from the best price since entry
    max_hours: float = None   # close everything this long after the first entry
    no_adds: bool = False     # ignore entries placed more than a minute after the first
    reenter: float = None     # after a stop, buy back once price bounces this far off the low


ACTUAL = Rule("actual")


def taker_rate(trades):
    """The wallet's own average fee as a fraction of notional."""
    fees = sum(t.fees for t in trades)
    volume = sum(sum(e[1] * e[2] for e in t.entries) + sum(x[1] * x[2] for x in t.exits) for t in trades)
    return fees / volume if volume else 0.00045


def simulate(trade, prices, rule, fee_rate, slippage=0.0005):
    """Net PnL of `trade` had it been managed by `rule`.

    The trade's real entries and exits are replayed bar by bar. While the rule
    has not fired, real exits close the same fraction of the simulated
    position as they did of the real one, so a rule that never fires returns
    the real result. When the rule fires, the rest of the position closes at
    the rule's price; stops and time exits pay `slippage` as well as fees.
    Later entries are skipped unless the rule re-enters after a stop.
    If a stop and a target both fall inside one 1m bar, that minute's 1s
    candles decide which traded first.
    """
    if rule.name == "actual":
        return trade.net_pnl
    s = trade.side
    bars = prices.path(trade, until=trade.close_time + 1)
    fills = sorted([(e[0], 0, e) for e in trade.entries] + [(x[0], 1, x) for x in trade.exits], key=lambda f: (f[0], f[1]))
    deadline = trade.open_time + rule.max_hours * HOUR if rule.max_hours else None
    real_pos = pos = avg = pnl = 0.0
    best = None          # best price since the simulated position opened, for trailing stops
    waiting = None       # stopped out with re-entry on: the extreme price since the stop
    ratio = 1.0          # simulated size / real size when the stop fired
    done = False         # the rule has closed the trade for good
    fi = 0

    for t, bar in bars.iterrows():
        # 1) real fills inside this bar
        while fi < len(fills) and fills[fi][0] <= bar["t_end"]:
            ft, is_exit, f = fills[fi]
            fi += 1
            if not is_exit:
                real_pos += f[2]
                if done or waiting is not None or (rule.no_adds and ft - trade.open_time > MIN):
                    continue
                avg = (avg * pos + f[1] * f[2]) / (pos + f[2])
                pos += f[2]
                pnl -= f[3]
            else:
                share = f[2] / real_pos
                real_pos -= f[2]
                if pos > 0:
                    size = pos if real_pos <= 1e-12 else pos * share
                    pnl += s * (f[1] - avg) * size - f[3] * size / f[2]
                    pos -= size
                if real_pos <= 1e-12:
                    waiting, done = None, True     # the real trade is over
        if done or (pos <= 0 and waiting is None):
            continue
        hi, lo = bar["h"], bar["l"]

        # 2) stopped out, waiting for a bounce to buy back in
        if waiting is not None:
            waiting = min(waiting, lo) if s > 0 else max(waiting, hi)
            trigger = waiting * (1 + s * rule.reenter)
            if (s > 0 and hi >= trigger) or (s < 0 and lo <= trigger):
                avg, pos, best, waiting = trigger, real_pos * ratio, trigger, None
                pnl -= fee_rate * trigger * pos
            continue

        # 3) does the rule fire in this bar?
        if best is None:
            best = hi if s > 0 else lo
        else:
            best = max(best, hi) if s > 0 else min(best, lo)
        stops = []
        if rule.stop:
            stops.append(avg * (1 - s * rule.stop))
        if rule.trail:
            stops.append(best * (1 - s * rule.trail))
        stops = [px for px in stops if (s > 0 and lo <= px) or (s < 0 and hi >= px)]
        stop_px = (max(stops) if s > 0 else min(stops)) if stops else None
        tp = avg * (1 + s * rule.take) if rule.take else None
        hit_tp = tp is not None and ((s > 0 and hi >= tp) or (s < 0 and lo <= tp))
        if stop_px is not None and hit_tp:
            if _stop_first(prices, trade.coin, t, bar, stop_px, tp, s):
                hit_tp = False
            else:
                stop_px = None

        if stop_px is not None:
            # a bar that opens through the stop fills at the open
            px = (min(stop_px, bar["o"]) if s > 0 else max(stop_px, bar["o"])) * (1 - s * slippage)
            ratio = pos / real_pos if real_pos else 1.0
            pnl += s * (px - avg) * pos - fee_rate * px * pos
            pos = 0.0
            if rule.reenter:
                waiting = px
            else:
                done = True
        elif hit_tp:
            pnl += s * (tp - avg) * pos - fee_rate * tp * pos
            pos, done = 0.0, True
        elif deadline and bar["t_end"] >= deadline:
            px = bar["c"] * (1 - s * slippage)
            pnl += s * (px - avg) * pos - fee_rate * px * pos
            pos, done = 0.0, True
    return pnl


def _stop_first(prices, coin, t, bar, stop_px, tp, s):
    """Use the minute's 1s candles to see whether the stop or the target traded first."""
    if bar["t_end"] - t < MIN - 1:
        return True                   # already a 1s bar: assume the worse case
    for _, b in prices.seconds(coin, int(t)).iterrows():
        stop_hit = (s > 0 and b["l"] <= stop_px) or (s < 0 and b["h"] >= stop_px)
        tp_hit = (s > 0 and b["h"] >= tp) or (s < 0 and b["l"] <= tp)
        if stop_hit or tp_hit:
            return stop_hit
    return True


# ---------------------------------------------------------------- the six questions

QUESTIONS = {
    "skip": "Better not to open it",
    "stop": "Should have stopped out",
    "take": "Should have taken profit",
    "hold": "Should have kept holding",
    "reenter": "Better to close and reopen",
    "no_adds": "Better not to add",
}


def diagnose(trade, prices, fee_rate, stop=0.02, take=0.03, hold_hours=4, bounce=0.01):
    """Dollar improvement each of the six alternatives would have made on this trade.

    skip     not trading at all (worth -net_pnl, so positive only for losers)
    stop     a stop `stop` below the average entry
    take     a target `take` above the average entry
    hold     exiting `hold_hours` after the real exit, at that bar's close
    reenter  the same stop, then buying back after a `bounce` rebound off the low
    no_adds  the same exits, without the entries placed after the first minute
    """
    actual = trade.net_pnl
    out = {"skip": -actual}
    out["stop"] = simulate(trade, prices, Rule("s", stop=stop), fee_rate) - actual
    out["take"] = simulate(trade, prices, Rule("t", take=take), fee_rate) - actual
    out["reenter"] = simulate(trade, prices, Rule("r", stop=stop, reenter=bounce), fee_rate) - actual
    out["no_adds"] = (simulate(trade, prices, Rule("n", no_adds=True), fee_rate) - actual) if trade.adds else 0.0
    later = prices.path(trade)
    later = later[(later.index > trade.close_time) & (later.index <= trade.close_time + hold_hours * HOUR)]
    if later.empty:
        out["hold"] = 0.0
    else:
        px = later["c"].iloc[-1]
        exited = sum(x[2] for x in trade.exits)
        out["hold"] = trade.side * (px - trade.avg_exit) * exited
    return out


def levels(ex, net_pnl):
    """Stop and target sizes taken from the wallet's own trades, as fractions.

    stop: 80% of winning trades never went further against you than this, so
          a stop here cuts losers while rarely touching a trade that worked.
    take: the median best move on winning trades.
    Both are clamped to 0.2%-5% so a handful of trades cannot produce a
    silly level.
    """
    win = ex[net_pnl > 0]
    if len(win) < 5:
        return 0.02, 0.03
    stop = float(np.clip((-win["mae_pct"]).quantile(0.8) / 100, 0.002, 0.05))   # mae_pct is negative
    take = float(np.clip(win["mfe_pct"].median() / 100, 0.002, 0.05))
    return stop, take


def label(row, min_usd=None):
    """The question whose answer would have saved the most on this trade.

    skip  wins when the trade lost and never offered a real chance: its best
          move was smaller than its fees plus 0.2%.
    hold  only counts when price kept going your way, at least 0.5% and more
          than the trade itself made, and was still there four hours later.
          A single trade's next four hours are mostly noise; `exit_timing()`
          tests early exits across all trades instead.
    Otherwise the largest saving among the other fixes is the lesson, if it
    beats `min_usd` (default 0.1% of the trade's notional); if not, "fine".
    """
    min_usd = min_usd if min_usd is not None else 0.001 * row["notional"]
    if row["net_pnl"] < 0 and row["mfe_pct"] < row["fee_pct"] + 0.2:
        return "skip"
    fixes = {k: row[f"fix_{k}"] for k in QUESTIONS if k != "skip"}
    if not (row["after_4h_close_pct"] > max(0.5, row["realized_pct"])):
        fixes.pop("hold")
    best = max(fixes, key=fixes.get)
    return best if fixes[best] > min_usd else "fine"


def analyse(trades, prices, stop=None, take=None, **kw):
    """One row per trade: the trade, its excursions, the six fixes and the lesson.

    Leave `stop` and `take` empty to size them from the wallet (`levels()`).
    The levels used are kept in `df.attrs`.
    """
    from trades import trades_frame
    df = trades_frame(trades)
    rate = taker_rate(trades)
    ex = pd.DataFrame([excursions(t, prices) for t in trades])
    auto_stop, auto_take = levels(ex, df["net_pnl"])
    stop, take = stop or auto_stop, take or auto_take
    fx = pd.DataFrame([diagnose(t, prices, rate, stop=stop, take=take, **kw) for t in trades]).add_prefix("fix_")
    df = pd.concat([df, ex, fx], axis=1)
    df["fee_pct"] = 100 * df["fees"] / df["notional"]
    df["lesson"] = df.apply(label, axis=1)
    df.attrs.update(stop=stop, take=take, fee_rate=rate)
    return df


def lessons(df):
    """Trades and dollars per lesson, the answer to "where am I making mistakes"."""
    out = df.groupby("lesson").agg(trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum"))
    saving = {k: df.loc[df["lesson"] == k, f"fix_{k}"].sum() for k in out.index if k != "fine"}
    out["saving"] = pd.Series(saving)
    out["meaning"] = out.index.map(lambda k: QUESTIONS.get(k, "No fix worth 0.1% of notional"))
    return out.sort_values("saving", ascending=False)


def exit_timing(df):
    """Do your exits come early? Average move after the exit, in your direction, with a t-stat.

    Positive means price kept going your way after you left. A t-stat
    below about 2 means the average could be luck.
    """
    rows = []
    for h in (1, 4, 24):
        x = df[f"after_{h}h_close_pct"].dropna()
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else np.nan
        rows.append({"after": f"{h}h", "trades": len(x), "mean_pct": x.mean(), "median_pct": x.median(),
                     "share_in_your_favour": (x > 0).mean(), "t_stat": t})
    return pd.DataFrame(rows).set_index("after")


# ---------------------------------------------------------------- rule sets

def rules_for(stop, take):
    """A rule set scaled to the wallet's own stop and target sizes, plus time and sizing rules."""
    pct = lambda x: f"{100 * x:.2g}%"
    return [
        Rule(f"stop {pct(stop / 2)}", stop=stop / 2),
        Rule(f"stop {pct(stop)}", stop=stop),
        Rule(f"stop {pct(2 * stop)}", stop=2 * stop),
        Rule(f"take {pct(take)}", take=take),
        Rule(f"take {pct(2 * take)}", take=2 * take),
        Rule(f"stop {pct(stop)} / take {pct(take)}", stop=stop, take=take),
        Rule(f"stop {pct(stop)} / take {pct(2 * take)}", stop=stop, take=2 * take),
        Rule(f"trail {pct(stop)}", trail=stop),
        Rule("max 1h", max_hours=1),
        Rule("max 4h", max_hours=4),
        Rule("no adds", no_adds=True),
        Rule(f"no adds + stop {pct(stop)}", no_adds=True, stop=stop),
        Rule(f"stop {pct(stop)}, re-enter on {pct(stop / 2)} bounce", stop=stop, reenter=stop / 2),
    ]


def test_rules(trades, prices, rules, split=0.5):
    """Replay every rule on every trade; score the earlier and later trades separately.

    A rule picked because it looks best on the trades you already reviewed is
    fitted to them. Pick on `first_half`, then read `second_half`: if the
    winner still helps on trades it was not chosen on, it is worth trying.
    """
    rate = taker_rate(trades)
    cut = trades[int(len(trades) * split)].open_time if trades else 0
    early = np.array([t.open_time < cut for t in trades])
    rows = []
    for rule in [ACTUAL] + list(rules):
        pnl = np.array([simulate(t, prices, rule, rate) for t in trades])
        rows.append({
            "rule": rule.name,
            "net_pnl": pnl.sum(),
            "first_half": pnl[early].sum(),
            "second_half": pnl[~early].sum(),
            "win_rate": (pnl > 0).mean(),
            "worst_trade": pnl.min(),
        })
    out = pd.DataFrame(rows).set_index("rule")
    out["vs_actual"] = out["net_pnl"] - out.loc["actual", "net_pnl"]
    return out
