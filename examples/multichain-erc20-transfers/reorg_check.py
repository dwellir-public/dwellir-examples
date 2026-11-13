"""Re-check rows that were not final when written. Exit code 1 means a reorg replaced a block.

    python reorg_check.py out/base.csv out/arbitrum.csv
"""
import csv
import sys

from rpc import Chain


def check(path):
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    pending = [row for row in rows if row["finalized"] == "False"]
    if not pending:
        print(f"{path}: all {len(rows)} rows were final when written")
        return 0
    chain = Chain(pending[0]["chain"])
    finalized = int(chain.block("finalized")["number"], 16)
    stored = {int(row["block_number"]): row["block_hash"] for row in pending}
    replaced = []
    for number in sorted(stored):
        canonical = chain.block(number)
        if canonical is None or canonical["hash"] != stored[number]:
            replaced.append(number)
    now_final = sum(1 for number in stored if number <= finalized)
    print(
        f"{path}: {len(pending)} rows in {len(stored)} blocks were not final, "
        f"{now_final} of those blocks are final now, {len(replaced)} replaced"
    )
    if replaced:
        print(f"  rescan from block {replaced[0]}: {replaced}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(max(check(path) for path in sys.argv[1:]))
