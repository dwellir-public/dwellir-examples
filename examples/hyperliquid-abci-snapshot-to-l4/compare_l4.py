#!/usr/bin/env python3
"""Compare two L4 JSON files, for example abci_to_l4.py output against hl-node's.

Checks that both files have the same coins, the same orders in the same
sequence on every side, and the same value for each shared field.
"""

import json
import sys
from decimal import Decimal

FIELDS = [
    "coin", "side", "limitPx", "sz", "oid", "timestamp", "triggerCondition", "isTrigger", "triggerPx",
    "isPositionTpsl", "reduceOnly", "orderType", "origSz", "tif", "cloid",
]
NUMERIC = {"limitPx", "sz", "origSz", "triggerPx"}


def same(field, a, b):
    if field in NUMERIC:
        # hl-node prints some values as floats, e.g. "2398088.6000000001".
        a, b = Decimal(a), Decimal(b)
        return abs(a - b) <= Decimal("1e-9") * max(1, abs(b))
    return a == b


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: compare_l4.py ours.json reference.json")
    ours, ref = (dict(json.load(open(p))) for p in sys.argv[1:])

    missing = set(ours) ^ set(ref)
    orders = sequence_errors = field_errors = 0
    examples = []
    for coin in sorted(set(ours) & set(ref)):
        for side in (0, 1):
            a, b = ours[coin][side], ref[coin][side]
            orders += len(b)
            if [o["oid"] for o in a] != [o["oid"] for o in b]:
                sequence_errors += 1
                examples.append(f"{coin} side {side}: order sequence differs")
                continue
            for x, y in zip(a, b):
                # Check each order, then its TP/SL children in the same way.
                pairs = [(x, y)]
                if [c["oid"] for c in x["children"]] != [c["oid"] for c in y["children"]]:
                    field_errors += 1
                    examples.append(f"{coin} oid {y['oid']} children differ")
                else:
                    pairs += zip(x["children"], y["children"])
                for p, q in pairs:
                    for f in FIELDS:
                        if not same(f, p[f], q[f]):
                            field_errors += 1
                            examples.append(f"{coin} oid {q['oid']} {f}: {p[f]!r} != {q[f]!r}")

    print(f"coins: {len(ours)} vs {len(ref)}, only in one file: {len(missing)}")
    print(f"orders: {orders}, sides with a different sequence: {sequence_errors}, field differences: {field_errors}")
    for line in examples[:10]:
        print("  " + line)
    sys.exit(1 if missing or sequence_errors or field_errors else 0)


if __name__ == "__main__":
    main()
