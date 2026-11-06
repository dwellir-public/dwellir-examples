"""Rank Hyperliquid vaults, inspect one, or list the vaults an address leads.

    python vaults.py top --by tvl --n 20
    python vaults.py top --by apr --min-tvl 250000
    python vaults.py show 0xdfc24b077bc1425ad1dea75bcb6f8158e10df303
    python vaults.py leader 0x677d831aef5328190852e24f13c46cac05f984e7
"""

import argparse
from datetime import datetime, timezone

from hl_api import feed, info, pct, usd, windows


def last(series: list) -> float:
    """Last value of a cumulative PnL series, or 0 when the window has no points yet."""
    return float(series[-1]) if series else 0.0


def load_vaults(open_only: bool = True, min_tvl: float = 0.0) -> list[dict]:
    """Flatten the /Mainnet/vaults feed into one dict per vault."""
    rows = []
    for entry in feed("vaults"):
        summary = entry["summary"]
        if open_only and summary["isClosed"]:
            continue
        tvl = float(summary["tvl"])
        if tvl < min_tvl:
            continue
        pnls = windows(entry["pnls"])
        rows.append({
            "name": summary["name"],
            "address": summary["vaultAddress"],
            "leader": summary["leader"],
            "tvl": tvl,
            "apr": float(entry["apr"]),
            # Each window is a short series of cumulative PnL points. The last
            # point is the PnL over that window; a brand-new vault has none yet.
            "pnl_day": last(pnls["day"]),
            "pnl_week": last(pnls["week"]),
            "pnl_month": last(pnls["month"]),
            "pnl_all": last(pnls["allTime"]),
            "created": datetime.fromtimestamp(summary["createTimeMillis"] / 1000, timezone.utc),
            "kind": summary["relationship"]["type"],
        })
    return rows


SORT_KEYS = {"tvl": "tvl", "apr": "apr", "day": "pnl_day", "week": "pnl_week",
             "month": "pnl_month", "all": "pnl_all"}


def print_top(rows: list[dict], by: str, n: int) -> None:
    rows = sorted(rows, key=lambda r: r[SORT_KEYS[by]], reverse=True)[:n]
    print(f"{'#':>3}  {'Vault':<34} {'TVL':>14} {'APR':>9} {'30d PnL':>13}  Address")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}  {r['name'][:34]:<34} {usd(r['tvl']):>14} {pct(r['apr']):>9} "
              f"{usd(r['pnl_month']):>13}  {r['address']}")


def show_vault(address: str) -> None:
    """Everything the vault page shows, from vaultDetails plus live positions."""
    details = info({"type": "vaultDetails", "vaultAddress": address})
    portfolio = windows(details["portfolio"])
    print(f"{details['name']}  ({address})")
    print(f"  leader        {details['leader']}")
    print(f"  APR           {pct(details['apr'])}")
    print(f"  leader share  {pct(details['leaderFraction'], signed=False)} of equity, "
          f"{pct(details['leaderCommission'], signed=False)} commission")
    print(f"  deposits      {'open' if details['allowDeposits'] else 'closed'}"
          f"{', vault closed' if details['isClosed'] else ''}")
    print(f"  followers     {len(details['followers'])} listed, "
          f"max distributable {usd(details['maxDistributable'])}")

    print("  returns")
    for window in ("day", "week", "month", "allTime"):
        history = portfolio[window]["accountValueHistory"]
        if not history:
            print(f"    {window:<8} no history yet")
            continue
        pnl = portfolio[window]["pnlHistory"][-1][1]
        start, end = float(history[0][1]), float(history[-1][1])
        print(f"    {window:<8} equity {usd(start):>14} -> {usd(end):>14}   "
              f"pnl {usd(pnl):>13}   volume {usd(portfolio[window]['vlm'])}")

    print("  largest followers")
    followers = sorted(details["followers"], key=lambda f: float(f["vaultEquity"]), reverse=True)
    for f in followers[:5]:
        print(f"    {f['user']}  equity {usd(f['vaultEquity']):>12}  "
              f"all-time pnl {usd(f['allTimePnl']):>12}  {f['daysFollowing']} days")

    # HLP is a parent vault: its capital sits in child vaults, which show up in
    # the vaults feed with the parent as their leader.
    children = [v for v in load_vaults(open_only=False) if v["leader"].lower() == address.lower()]
    if children:
        print(f"  child vaults ({len(children)})")
        for c in sorted(children, key=lambda c: c["tvl"], reverse=True):
            print(f"    {c['name']:<24} TVL {usd(c['tvl']):>13}  APR {pct(c['apr']):>7}  {c['address']}")

    # A vault is an address, so its open positions come from clearinghouseState
    # like any other wallet. This call runs through Dwellir.
    state = info({"type": "clearinghouseState", "user": address})
    positions = [p["position"] for p in state["assetPositions"] if float(p["position"]["szi"]) != 0]
    print(f"  open positions ({len(positions)})  account value {usd(state['marginSummary']['accountValue'])}")
    for p in sorted(positions, key=lambda p: abs(float(p["positionValue"])), reverse=True)[:10]:
        side = "LONG " if float(p["szi"]) > 0 else "SHORT"
        print(f"    {side} {p['coin']:<8} {usd(p['positionValue']):>13}  "
              f"{p['leverage']['value']}x {p['leverage']['type']}  "
              f"upnl {usd(p['unrealizedPnl'])}")


def show_leader(address: str) -> None:
    """Vaults this address leads. leadingVaults needs a user; without one it returns 422."""
    vaults = info({"type": "leadingVaults", "user": address})
    if not vaults:
        print(f"{address} leads no vaults")
        return
    for v in vaults:
        print(f"{v['name']}  {v['address']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    top = sub.add_parser("top", help="rank vaults")
    top.add_argument("--by", choices=SORT_KEYS, default="tvl")
    top.add_argument("--n", type=int, default=20)
    top.add_argument("--min-tvl", type=float, default=0.0)
    top.add_argument("--include-closed", action="store_true")

    sub.add_parser("show", help="inspect one vault").add_argument("address")
    sub.add_parser("leader", help="vaults an address leads").add_argument("address")

    args = parser.parse_args()
    if args.command == "top":
        rows = load_vaults(open_only=not args.include_closed, min_tvl=args.min_tvl)
        print(f"{len(rows)} vaults after filters")
        print_top(rows, args.by, args.n)
    elif args.command == "show":
        show_vault(args.address)
    else:
        show_leader(args.address)


if __name__ == "__main__":
    main()
