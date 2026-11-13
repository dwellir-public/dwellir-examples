"""ERC-20 transfer history for one address on several EVM chains, written as CSV.

    python transfers.py 0xADDRESS --days 1
    python transfers.py 0xADDRESS --days 7 --chains base,polygon
"""
import argparse
import csv
import datetime as dt
import json
import os
import time
from pathlib import Path

from rpc import ENDPOINTS, Chain
from tokens import TokenCache
from windows import Window, scan_logs

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
START_WINDOW = int(os.environ.get("START_WINDOW", "10000"))
FIELDS = [
    "chain", "block_number", "block_time_utc", "tx_hash", "log_index", "direction",
    "counterparty", "token", "symbol", "decimals", "amount", "amount_raw",
    "finalized", "block_hash",
]


def topic_for(address):
    return "0x" + address[2:].lower().rjust(64, "0")


def address_from(topic):
    return "0x" + topic[-40:]


def start_block(chain, head_block, days):
    """Estimate the block `days` ago from the average block time of the last 1,000 blocks."""
    head = int(head_block["number"], 16)
    older = chain.block(head - 1000)
    seconds_per_block = (int(head_block["timestamp"], 16) - int(older["timestamp"], 16)) / 1000
    return max(0, head - int(days * 86400 / seconds_per_block))


def fetch_transfers(chain, address, from_block, to_block):
    """Both directions, merged on (tx_hash, log_index) so a self-transfer appears once."""
    me = topic_for(address)
    window = Window(START_WINDOW)
    merged = {}
    for direction, topics in (("out", [TRANSFER, me]), ("in", [TRANSFER, None, me])):
        for logs in scan_logs(chain, from_block, to_block, topics, window):
            for log in logs:
                if len(log["topics"]) != 3:
                    continue  # ERC-721 uses the same event with a 4th indexed topic
                key = (log["transactionHash"], int(log["logIndex"], 16))
                if key in merged:
                    merged[key]["direction"] = "self"
                    continue
                merged[key] = {"log": log, "direction": direction}
    return [merged[key] for key in sorted(merged, key=lambda k: (
        int(merged[k]["log"]["blockNumber"], 16), k[1]))]


def scale(raw, decimals):
    """Exact decimal string. float and the default Decimal context both round large amounts."""
    if decimals == 0:
        return str(raw)
    whole, fraction = divmod(raw, 10**decimals)
    return f"{whole}.{fraction:0{decimals}d}"


def block_time(chain, log, cache):
    stamp = log.get("blockTimestamp")
    if stamp is None:
        number = log["blockNumber"]
        if number not in cache:
            cache[number] = chain.block(number)["timestamp"]
        stamp = cache[number]
    return dt.datetime.fromtimestamp(int(stamp, 16), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def to_row(chain, item, tokens, finalized, time_cache):
    log, direction = item["log"], item["direction"]
    sender, recipient = address_from(log["topics"][1]), address_from(log["topics"][2])
    symbol, decimals = tokens.get(log["address"])
    raw = int(log["data"], 16) if log["data"] not in ("0x", "") else 0
    number = int(log["blockNumber"], 16)
    return {
        "chain": chain.name,
        "block_number": number,
        "block_time_utc": block_time(chain, log, time_cache),
        "tx_hash": log["transactionHash"],
        "log_index": int(log["logIndex"], 16),
        "direction": direction,
        "counterparty": sender if direction == "in" else recipient,
        "token": log["address"],
        "symbol": symbol,
        "decimals": "" if decimals is None else decimals,
        "amount": "" if decimals is None else scale(raw, decimals),
        "amount_raw": raw,
        "finalized": number <= finalized,
        "block_hash": log["blockHash"],
    }


def cell(value):
    """Spreadsheets run a cell that starts with = + - or @ as a formula. Anyone can name a token that way."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def scan_to_csv(chain, address, first, head_block, finalized, path, kept=()):
    """Scan [first, head], write the CSV after the `kept` rows, and record the scan for reorg_check.py."""
    head = int(head_block["number"], 16)
    items = fetch_transfers(chain, address, first, head)
    tokens, time_cache = TokenCache(chain), {}
    rows = list(kept) + [to_row(chain, item, tokens, finalized, time_cache) for item in items]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({key: cell(value) for key, value in row.items()} for row in rows)
    # A block hash commits to its parent, so the head hash vouches for every block below it,
    # including blocks that held no transfer.
    record = {"chain": chain.name, "address": address, "first": first, "head": head,
              "head_hash": head_block["hash"], "finalized": finalized}
    path.with_suffix(".scan.json").write_text(json.dumps(record, indent=2) + "\n")
    return rows, tokens


def run_chain(name, address, days, out_dir):
    started = time.monotonic()
    chain = Chain(name)
    head_block = chain.block("latest")
    finalized = int(chain.block("finalized")["number"], 16)
    first = start_block(chain, head_block, days)
    head = int(head_block["number"], 16)
    path = out_dir / f"{name}.csv"
    rows, tokens = scan_to_csv(chain, address, first, head_block, finalized, path)
    pending = sum(1 for row in rows if not row["finalized"])
    print(
        f"{name:9s} blocks {first}-{head} ({head - first + 1:,}), "
        f"{len(rows)} transfers ({pending} not final), {len(tokens._cache)} tokens, "
        f"{chain.requests} requests, {time.monotonic() - started:.1f}s -> {path}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--days", type=float, default=1.0)
    parser.add_argument("--chains", default=",".join(ENDPOINTS))
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    for name in args.chains.split(","):
        run_chain(name.strip(), args.address, args.days, out_dir)


if __name__ == "__main__":
    main()
