"""Post-mortem of a Hyperliquid wallet's closed perp trades.

    export DWELLIR_API_KEY=your-api-key
    python postmortem.py 0xYourWallet --days 30
    python postmortem.py 0xYourWallet --start 2026-10-01 --end 2026-11-01 --csv trades.csv

Prints where the wallet lost money, which of six alternatives would have
helped each trade, whether exits come early, and how a set of stop, target,
trailing, time and sizing rules would have done on the same trades.
"""

import argparse
import time

import pandas as pd

import analysis
import hl_index
import trades as tr

DAY = 86_400_000


def run(user, start_ms, end_ms, after_hours=24, stop=None, take=None):
    """Fetch, rebuild and score. Returns a dict the CLI and the notebook both read."""
    fills = hl_index.user_fills(user, start_ms, end_ms)
    if fills.empty:
        raise SystemExit(f"No fills for {user} in that window")
    trades = tr.build_trades(fills)
    if not trades:
        raise SystemExit("No completed perp round trips in that window")
    prices = analysis.Prices(trades, after_hours=after_hours)
    df = analysis.analyse(trades, prices, stop=stop, take=take)
    rules = analysis.rules_for(df.attrs["stop"], df.attrs["take"])
    return {
        "fills": fills,
        "trades": trades,
        "prices": prices,
        "df": df,
        "lessons": analysis.lessons(df),
        "exit_timing": analysis.exit_timing(df),
        "rules": analysis.test_rules(trades, prices, rules),
    }


def pick_and_check(rules):
    """Choose the rule that did best on the earlier trades, and show how it did on the later ones."""
    gain_early = rules["first_half"] - rules.loc["actual", "first_half"]
    best = gain_early.drop("actual").idxmax()
    return {
        "rule": best,
        "first_half_gain": gain_early[best],
        "second_half_gain": rules.loc[best, "second_half"] - rules.loc["actual", "second_half"],
    }


def _usd(x):
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def report(r):
    df, attrs = r["df"], r["df"].attrs
    win = df["net_pnl"] > 0
    print(f"\n{len(df)} closed trades from {len(r['fills'])} fills, "
          f"{df['open'].min():%Y-%m-%d} to {df['close'].max():%Y-%m-%d}")
    print(f"Net {_usd(df['net_pnl'].sum())} = gross {_usd(df['gross_pnl'].sum())} - fees {_usd(df['fees'].sum())} (funding not included)")
    print(f"Won {win.sum()} of {len(df)} ({win.mean():.0%}); average win {_usd(df.loc[win, 'net_pnl'].mean())}, "
          f"average loss {_usd(df.loc[~win, 'net_pnl'].mean())}")
    print(f"Best move in your favour, median: winners {df.loc[win, 'mfe_pct'].median():.2f}%, "
          f"losers {df.loc[~win, 'mfe_pct'].median():.2f}%")
    print(f"Stop and target sized from your trades: stop {100 * attrs['stop']:.2f}%, take {100 * attrs['take']:.2f}%")

    print("\nWhere the money went (one lesson per trade, saving = what that fix would have added):")
    print(r["lessons"].assign(net_pnl=lambda d: d["net_pnl"].map(_usd), saving=lambda d: d["saving"].map(lambda x: "" if pd.isna(x) else _usd(x))).to_string())

    print("\nDo you exit early? Price move after your exit, in your direction:")
    print(r["exit_timing"].round(3).to_string())

    print("\nRules replayed on the same trades:")
    show = r["rules"].copy()
    for c in ["net_pnl", "first_half", "second_half", "worst_trade", "vs_actual"]:
        show[c] = show[c].map(_usd)
    show["win_rate"] = r["rules"]["win_rate"].map("{:.0%}".format)
    print(show.to_string())
    pc = pick_and_check(r["rules"])
    verdict = "still helped" if pc["second_half_gain"] > 0 else "did not help"
    print(f"\nBest rule on the earlier half: {pc['rule']} ({_usd(pc['first_half_gain'])}). "
          f"On the later half it {verdict} ({_usd(pc['second_half_gain'])}).")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("user", help="0x wallet address")
    p.add_argument("--days", type=float, default=30, help="look back this many days (default 30)")
    p.add_argument("--start", help="UTC start date, e.g. 2026-10-01 (overrides --days)")
    p.add_argument("--end", help="UTC end date, exclusive (default now)")
    p.add_argument("--stop", type=float, help="stop size as a fraction, e.g. 0.01 (default: sized from your trades)")
    p.add_argument("--take", type=float, help="target size as a fraction (default: sized from your trades)")
    p.add_argument("--csv", help="write the per-trade table here")
    a = p.parse_args()
    end = int(pd.Timestamp(a.end, tz="UTC").timestamp() * 1000) if a.end else int(time.time() * 1000)
    start = int(pd.Timestamp(a.start, tz="UTC").timestamp() * 1000) if a.start else end - int(a.days * DAY)
    r = run(a.user, start, end, stop=a.stop, take=a.take)
    report(r)
    if a.csv:
        r["df"].to_csv(a.csv, index=False)
        print(f"\nPer-trade table written to {a.csv}")


if __name__ == "__main__":
    main()
