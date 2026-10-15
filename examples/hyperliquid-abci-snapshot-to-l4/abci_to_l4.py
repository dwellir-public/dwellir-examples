#!/usr/bin/env python3
"""Extract L4 order books from a Hyperliquid periodic ABCI state snapshot.

Reads a `periodic_abci_states/<date>/<height>.rmp` file (or `.rmp.lz4`) with
plain msgpack, so it works on snapshots written by any hl-node version, and
writes the books in the same shape as `hl-node compute-l4-snapshots`:

    [[coin, [bids, asks]], ...]

Each side is best price first, then time priority within a price level.
"""

import argparse
import json
import sys
from decimal import Decimal

import msgpack

PERP_MAX_DECIMALS = 6
SPOT_MAX_DECIMALS = 8


def load_state(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".lz4"):
        import lz4.frame

        data = lz4.frame.decompress(data)
    return msgpack.unpackb(data, raw=False, strict_map_key=False)


def fmt(raw, decimals):
    """Scale a fixed-point integer and print it like hl-node does ("193.0")."""
    s = format(Decimal(raw).scaleb(-decimals), "f")
    if "." not in s:
        return s + ".0"
    s = s.rstrip("0")
    return s + "0" if s.endswith(".") else s


def outcome_names(spot_meta):
    """Map outcome-token id -> "#<outcome*10 + side>" (prediction markets)."""
    outr = spot_meta.get("outr")
    if not outr:
        return {}
    side_index = {}
    for outcome, spec in outr.get("ots", []):
        for i, side in enumerate(spec["s"]):
            side_index[side["t"]] = i
    return {
        token: f"#{outcome * 10 + side_index[token]}"
        for token, outcome in outr.get("tto", [])
        if token in side_index
    }


def markets(exchange):
    """Yield (coin, book, sz_decimals, px_decimals) for every perp and spot book."""
    locus = exchange["locus"]
    for dex, clearinghouse in zip(exchange["perp_dexs"], locus["cls"]):
        universe = clearinghouse["meta"]["universe"]
        for book, asset in zip(dex["books"], universe):
            szd = asset["szDecimals"]
            yield asset["name"], book, szd, PERP_MAX_DECIMALS - szd

    spot_meta = locus["scl"]["meta"]
    tokens = spot_meta["token_infos"]
    outcomes = outcome_names(spot_meta)
    for book in exchange["spot_books"]:
        idx = book["asset"]
        base = spot_meta["spot_infos"][idx]["tokens"][0]
        szd = tokens[base]["spec"]["szDecimals"]
        if idx == 0:
            coin = "PURR/USDC"
        elif base in outcomes:
            coin = outcomes[base]
        else:
            coin = f"@{idx}"
        yield coin, book, szd, SPOT_MAX_DECIMALS - szd


def side_orders(coin, half, slots, szd, pxd, with_users):
    """Walk each price level's linked list (f -> n -> n ...) in book order."""
    out = []
    for _, level in half["levels"]:
        i = level["f"]
        while i is not None:
            o = slots[i]["o"]
            c = o["c"]
            order = {
                "coin": coin,
                "side": c["s"],
                "limitPx": fmt(c["l"], pxd),
                "sz": fmt(o["r"], szd),
                "oid": o["o"],
                "timestamp": c["t"],
                "origSz": fmt(o.get("O", 0), szd),
                "tif": o.get("t"),
                "reduceOnly": bool(c.get("r", False)),
                "cloid": c.get("c"),
            }
            if with_users:
                order["user"] = o["u"]
            out.append(order)
            i = o.get("n")
    return out


def extract(state, with_users=False):
    books = []
    for coin, book, szd, pxd in markets(state["exchange"]):
        slots = book["bod"]["e"]
        bids, asks = (side_orders(coin, h, slots, szd, pxd, with_users) for h in book["halfs"])
        books.append([coin, [bids, asks]])
    books.sort(key=lambda b: b[0])
    return books


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("snapshot", help="path to <height>.rmp or <height>.rmp.lz4")
    p.add_argument("output", help="where to write the L4 JSON")
    p.add_argument("--users", action="store_true", help="include each order's user address")
    args = p.parse_args()

    state = load_state(args.snapshot)
    ctx = state["exchange"]["locus"]["ctx"]
    books = extract(state, args.users)
    with open(args.output, "w") as f:
        json.dump(books, f)
    n = sum(len(b) + len(a) for _, (b, a) in books)
    print(f"height {ctx['height']} at {ctx['time']}: {len(books)} books, {n} orders -> {args.output}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
