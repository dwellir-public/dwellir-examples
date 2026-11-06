"""Rank Hyperliquid traders from the leaderboard feed and profile the top ones live.

    python leaderboard.py top --window week --by pnl --n 20
    python leaderboard.py top --window month --by roi --min-value 100000 --profile
    python leaderboard.py top --vault-leaders --n 10
    python leaderboard.py addresses --out addresses.txt
"""

import argparse

from hl_api import feed, info, pct, usd, windows
from vaults import load_vaults

WINDOWS = ("day", "week", "month", "allTime")
METRICS = ("pnl", "roi", "vlm")


def load_leaderboard(min_value: float = 0.0, min_volume: float = 0.0, window: str = "month") -> list[dict]:
    """Flatten /Mainnet/leaderboard into one dict per trader.

    min_value drops small accounts. min_volume drops accounts that did not trade
    in the window: deposits and transfers can show up as PnL on a tiny starting
    balance, which makes their ROI meaningless.
    """
    rows = []
    for row in feed("leaderboard")["leaderboardRows"]:
        value = float(row["accountValue"])
        if value < min_value:
            continue
        perf = windows(row["windowPerformances"])
        if float(perf[window]["vlm"]) < min_volume:
            continue
        rows.append({
            "address": row["ethAddress"],
            "name": row.get("displayName") or "",
            "value": value,
            # perf[window] is {"pnl": ..., "roi": ..., "vlm": ...} as strings. Flattened
            # to pnl_day, roi_day, vlm_day, pnl_week, ... pnl_allTime, roi_allTime, vlm_allTime.
            **{f"{m}_{w}": float(perf[w][m]) for w in WINDOWS for m in METRICS},
        })
    return rows


def print_top(rows: list[dict], window: str, by: str, n: int, live: bool) -> None:
    key = f"{by}_{window}"
    rows = sorted(rows, key=lambda r: r[key], reverse=True)[:n]
    states = profile([r["address"] for r in rows]) if live else {}
    print(f"{'#':>3}  {'Trader':<42} {'Account':>13} {'PnL':>13} {'ROI':>8} {'Volume':>16}")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}  {r['address']:<42} {usd(r['value']):>13} {usd(r[f'pnl_{window}']):>13} "
              f"{pct(r[f'roi_{window}']):>8} {usd(r[f'vlm_{window}']):>16}")
        notes = [r["name"]] if r["name"] else []
        if r["address"] in states:
            notes.append(describe(states[r["address"]]))
        if notes:
            print(f"     {' | '.join(notes)}")


def profile(addresses: list[str]) -> dict[str, dict]:
    """Live account state for many wallets in one Dwellir request.

    batchClearinghouseStates is a Dwellir-only Info type. It is billed per wallet,
    so 20 addresses cost 20 responses, the same as 20 single calls, in one round trip.
    """
    result = info({"type": "batchClearinghouseStates", "users": addresses}, timeout=60.0)
    return {address: state for address, state in result["successful_states"]}


def describe(state: dict) -> str:
    """One line: biggest position, leverage, margin use."""
    summary = state["marginSummary"]
    value = float(summary["accountValue"])
    used = float(summary["totalMarginUsed"])
    positions = [p["position"] for p in state["assetPositions"] if float(p["position"]["szi"]) != 0]
    if not positions:
        return f"flat, margin used {used / value * 100 if value else 0:.0f}%"
    big = max(positions, key=lambda p: abs(float(p["positionValue"])))
    side = "long" if float(big["szi"]) > 0 else "short"
    return (f"{len(positions)} positions, largest {side} {big['coin']} "
            f"{usd(big['positionValue'])} at {big['leverage']['value']}x, "
            f"margin used {used / value * 100 if value else 0:.0f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    top = sub.add_parser("top", help="rank traders")
    top.add_argument("--window", choices=WINDOWS, default="week")
    top.add_argument("--by", choices=METRICS, default="pnl")
    top.add_argument("--n", type=int, default=20)
    top.add_argument("--min-value", type=float, default=0.0,
                     help="ignore accounts below this value in USD")
    top.add_argument("--min-volume", type=float, default=0.0,
                     help="ignore accounts that traded less than this in the window (ROI on untraded deposits is noise)")
    top.add_argument("--vault-leaders", action="store_true",
                     help="only traders who lead at least one open vault")
    top.add_argument("--profile", action="store_true",
                     help="add live positions from Dwellir batchClearinghouseStates")

    dump = sub.add_parser("addresses", help="write every leaderboard address to a file")
    dump.add_argument("--out", default="addresses.txt")

    args = parser.parse_args()
    if args.command == "addresses":
        rows = load_leaderboard()
        with open(args.out, "w") as fh:
            fh.write("\n".join(r["address"] for r in rows) + "\n")
        print(f"wrote {len(rows)} addresses to {args.out}")
        return

    rows = load_leaderboard(min_value=args.min_value, min_volume=args.min_volume, window=args.window)
    print(f"{len(rows)} traders after filters")
    if args.vault_leaders:
        # A leader can run several vaults (HLP's leader runs eight). Name the
        # largest and count the rest.
        vaults_by_leader: dict[str, list[dict]] = {}
        for v in sorted(load_vaults(open_only=True), key=lambda v: v["tvl"], reverse=True):
            vaults_by_leader.setdefault(v["leader"], []).append(v)
        rows = [dict(r, name=f"leads {vs[0]['name']} ({usd(vs[0]['tvl'])} TVL"
                             + (f", and {len(vs) - 1} more)" if len(vs) > 1 else ")"))
                for r in rows if (vs := vaults_by_leader.get(r["address"]))]
        print(f"{len(rows)} of them lead an open vault")
    print_top(rows, args.window, args.by, args.n, live=args.profile)


if __name__ == "__main__":
    main()
