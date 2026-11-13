"""Re-check a scan that was not final when written, and rescan if a reorg replaced a block.

Exit code 1 means a block was replaced and the CSV was rescanned.

    python reorg_check.py out/base.csv out/arbitrum.csv
"""
import csv
import json
import sys
from pathlib import Path

from rpc import Chain
from transfers import scan_to_csv


def check(path):
    path = Path(path)
    scan = json.loads(path.with_suffix(".scan.json").read_text())
    if scan["finalized"] >= scan["head"]:
        print(f"{path}: every scanned block was final when written")
        return 0
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    kept = [row for row in rows if int(row["block_number"]) <= scan["finalized"]]
    pending = [row for row in rows if int(row["block_number"]) > scan["finalized"]]
    # The head hash covers blocks with no rows: a fork can add a transfer where there was none.
    # Row hashes catch a row read from a short-lived fork, even if the head is back on the old one.
    stored = [(scan["head"], scan["head_hash"])]
    stored += sorted({(int(row["block_number"]), row["block_hash"]) for row in pending})
    chain = Chain(scan["chain"])
    finalized = int(chain.block("finalized")["number"], 16)
    replaced, canonical = None, {}
    for number, block_hash in stored:
        if number not in canonical:
            block = chain.block(number)
            canonical[number] = block and block["hash"]
        if canonical[number] != block_hash:
            replaced = number
            break
    first = max(scan["first"], scan["finalized"] + 1)
    if replaced is None:
        state = "all final now" if scan["head"] <= finalized else f"final up to block {finalized}"
        print(f"{path}: blocks {first}-{scan['head']} ({len(pending)} rows) unchanged, {state}")
        return 0
    # Rows at or below the old finalized block stand. The rest of the scan is read again.
    head_block = chain.block("latest")
    rows, _ = scan_to_csv(chain, scan["address"], first, head_block, finalized, path, kept)
    print(f"{path}: block {replaced} replaced, rescanned {first}-{int(head_block['number'], 16)}: "
          f"{len(pending)} rows above block {scan['finalized']} are now {len(rows) - len(kept)}")
    return 1


if __name__ == "__main__":
    sys.exit(max(check(path) for path in sys.argv[1:]))
