"""Turn a wallet's fills into round-trip trades.

A trade starts when a perp position leaves zero and ends when it returns to
zero. Fills in between are entries (they grow the position) or exits (they
shrink it). A fill that flips the position, such as "Long > Short", closes
the old trade and opens a new one at the same price.

Every Hyperliquid fill carries `startPosition`, the signed position before
the fill. That lets us skip trades that were already open when the window
started, and check that our running position matches the exchange's.
"""

from dataclasses import dataclass, field

import pandas as pd

EPS = 1e-9


@dataclass
class Trade:
    coin: str
    side: int                                     # +1 long, -1 short
    entries: list = field(default_factory=list)   # (time_ms, px, sz, fee)
    exits: list = field(default_factory=list)     # (time_ms, px, sz, fee, closedPnl)
    liquidated: bool = False

    @property
    def open_time(self):
        return self.entries[0][0]

    @property
    def close_time(self):
        return self.exits[-1][0]

    @property
    def size(self):
        """Total size entered, in coins."""
        return sum(e[2] for e in self.entries)

    @property
    def avg_entry(self):
        return sum(e[1] * e[2] for e in self.entries) / self.size

    @property
    def avg_exit(self):
        return sum(x[1] * x[2] for x in self.exits) / sum(x[2] for x in self.exits)

    @property
    def gross_pnl(self):
        """Realized PnL as Hyperliquid reports it (sum of closedPnl), before fees and funding."""
        return sum(x[4] for x in self.exits)

    @property
    def fees(self):
        return sum(e[3] for e in self.entries) + sum(x[3] for x in self.exits)

    @property
    def net_pnl(self):
        return self.gross_pnl - self.fees

    @property
    def notional(self):
        return self.avg_entry * self.size

    @property
    def adds(self):
        """Entries placed more than a minute after the first one."""
        return [e for e in self.entries if e[0] - self.open_time > 60_000]


def build_trades(fills):
    """Group fills into completed perp round trips, oldest first.

    Spot (`@123`) and HIP-4 outcome (`#123`) markets are skipped: spot has no
    short side and outcomes settle rather than close. HIP-3 markets such as
    `xyz:TSLA` are perps and are kept.
    """
    trades = []
    perps = fills[~fills["coin"].str.match(r"^[@#]")]
    for coin, rows in perps.groupby("coin", sort=False):
        pos = None      # unknown until we see a fill that starts flat
        trade = None
        for f in rows.itertuples(index=False):
            start = f.startPosition
            if pos is None or abs(pos - start) > EPS * max(1.0, abs(start)):
                # First fill for this coin, or our running position drifted
                # (for example a liquidation fill we cannot see). Resync on the
                # exchange's number and drop the trade we cannot account for.
                pos, trade = start, None
            qty = f.sz if f.side == "B" else -f.sz
            liq = isinstance(getattr(f, "liquidation", None), dict)   # set only on liquidation fills, when present

            if abs(pos) < EPS:
                trade = Trade(coin, 1 if qty > 0 else -1)
                trade.entries.append((f.time, f.px, abs(qty), f.fee))
            elif (pos > 0) == (qty > 0):
                if trade:
                    trade.entries.append((f.time, f.px, abs(qty), f.fee))
            else:
                closing = min(abs(qty), abs(pos))
                share = closing / abs(qty)
                if trade:
                    trade.exits.append((f.time, f.px, closing, f.fee * share, f.closedPnl))
                    trade.liquidated |= liq
                if abs(qty) > abs(pos) + EPS:          # flip: the rest opens a new trade
                    if trade:
                        trades.append(trade)
                    trade = Trade(coin, 1 if qty > 0 else -1)
                    trade.entries.append((f.time, f.px, abs(qty) - closing, f.fee * (1 - share)))
                elif abs(pos + qty) < EPS * max(1.0, abs(pos)):
                    if trade:
                        trades.append(trade)
                    trade = None
            pos += qty
    trades.sort(key=lambda t: t.open_time)
    return trades


def trades_frame(trades):
    """One row per trade with the numbers the rest of the analysis reads."""
    return pd.DataFrame([{
        "coin": t.coin,
        "side": "long" if t.side > 0 else "short",
        "open": pd.Timestamp(t.open_time, unit="ms", tz="UTC"),
        "close": pd.Timestamp(t.close_time, unit="ms", tz="UTC"),
        "hours": (t.close_time - t.open_time) / 3.6e6,
        "size": t.size,
        "notional": t.notional,
        "avg_entry": t.avg_entry,
        "avg_exit": t.avg_exit,
        "entries": len(t.entries),
        "adds": len(t.adds),
        "exits": len(t.exits),
        "gross_pnl": t.gross_pnl,
        "fees": t.fees,
        "net_pnl": t.net_pnl,
        "liquidated": t.liquidated,
    } for t in trades])
