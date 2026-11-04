"""Charts for the notebook."""

import matplotlib.pyplot as plt
import pandas as pd

from analysis import QUESTIONS

COLORS = {"skip": "#c0392b", "stop": "#e67e22", "take": "#2980b9", "hold": "#8e44ad",
          "reenter": "#16a085", "no_adds": "#7f8c8d", "fine": "#27ae60"}


def trade_chart(trade, prices, row=None, stop=None, take=None, ax=None):
    """Price from first entry to an hour after the exit, with entries, exits and rule levels."""
    ax = ax or plt.subplots(figsize=(11, 4))[1]
    bars = prices.path(trade, until=trade.close_time + 3_600_000)
    t = pd.to_datetime(bars.index, unit="ms", utc=True)
    ax.fill_between(t, bars["l"], bars["h"], color="#bbb", alpha=0.6, linewidth=0, label="candle range")
    ax.plot(t, bars["c"], color="#555", linewidth=0.8)
    ent = pd.DataFrame(trade.entries, columns=["t", "px", "sz", "fee"])
    ext = pd.DataFrame(trade.exits, columns=["t", "px", "sz", "fee", "pnl"])
    up, down = ("^", "v") if trade.side > 0 else ("v", "^")
    ax.scatter(pd.to_datetime(ent.t, unit="ms", utc=True), ent.px, marker=up, s=20 + 200 * ent.sz / ent.sz.max(), color="#2980b9", label="entries", zorder=3)
    ax.scatter(pd.to_datetime(ext.t, unit="ms", utc=True), ext.px, marker=down, s=20 + 200 * ext.sz / ext.sz.max(), color="#c0392b", label="exits", zorder=3)
    ax.axvline(pd.to_datetime(trade.close_time, unit="ms", utc=True), color="#c0392b", linestyle=":", linewidth=1)
    # Stops and targets follow the running average entry, as in analysis.simulate()
    held = bars.index <= trade.close_time
    cost = ent.px * ent.sz
    avg = pd.Series((cost.cumsum() / ent.sz.cumsum()).values, index=ent.t.values)
    avg = avg.groupby(level=0).last()            # several fills can share a timestamp
    run_avg = avg.reindex(avg.index.union(bars.index[held])).ffill().loc[bars.index[held]]
    th = pd.to_datetime(run_avg.index, unit="ms", utc=True)
    ax.step(th, run_avg, where="post", color="#2980b9", linewidth=0.8, alpha=0.7, label="average entry")
    if stop:
        ax.step(th, run_avg * (1 - trade.side * stop), where="post", color="#e67e22", linestyle="--", linewidth=1, label=f"stop {100 * stop:.2g}%")
    if take:
        ax.step(th, run_avg * (1 + trade.side * take), where="post", color="#27ae60", linestyle="--", linewidth=1, label=f"take {100 * take:.2g}%")
    side = "long" if trade.side > 0 else "short"
    title = f"{trade.coin} {side}, net ${trade.net_pnl:,.0f}"
    if row is not None:
        title += f", MFE {row['mfe_pct']:.2f}%, MAE {row['mae_pct']:.2f}%, lesson: {QUESTIONS.get(row['lesson'], 'fine')}"
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8, loc="best")
    return ax


def excursion_scatter(df, ax=None):
    """Best move for you against worst move against you, per trade. Winners and losers separate cleanly here."""
    ax = ax or plt.subplots(figsize=(7, 5))[1]
    for lesson, g in df.groupby("lesson"):
        ax.scatter(-g["mae_pct"], g["mfe_pct"], s=12 + g["notional"] / df["notional"].max() * 150,
                   color=COLORS.get(lesson, "#333"), alpha=0.75, label=QUESTIONS.get(lesson, "Fine"))
    ax.set_xlabel("Worst move against you while open, %  (MAE)")
    ax.set_ylabel("Best move in your favour while open, %  (MFE)")
    ax.axline((0, 0), slope=1, color="#999", linewidth=0.7, linestyle=":")
    ax.legend(fontsize=8)
    return ax


def lessons_bar(lessons, ax=None):
    ax = ax or plt.subplots(figsize=(7, 3))[1]
    d = lessons.drop("fine", errors="ignore")
    ax.barh(d["meaning"], d["saving"], color=[COLORS.get(k, "#333") for k in d.index])
    for i, (k, row) in enumerate(d.iterrows()):
        ax.text(row["saving"], i, f"  {row['trades']} trades", va="center", fontsize=8)
    ax.set_xlabel("What the fix would have added, $")
    ax.invert_yaxis()
    return ax


def rules_bar(rules, ax=None):
    """Each rule's change against what you actually did, on the earlier and the later half of trades."""
    ax = ax or plt.subplots(figsize=(9, 5))[1]
    d = rules.drop("actual")
    base = rules.loc["actual"]
    early = d["first_half"] - base["first_half"]
    late = d["second_half"] - base["second_half"]
    y = range(len(d))
    ax.barh([i - 0.2 for i in y], early, height=0.4, color="#95a5a6", label="earlier half")
    ax.barh([i + 0.2 for i in y], late, height=0.4, color="#2c3e50", label="later half")
    ax.set_yticks(list(y), d.index, fontsize=8)
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_xlabel("Change vs what you actually did, $")
    ax.invert_yaxis()
    ax.legend(fontsize=8)
    return ax
