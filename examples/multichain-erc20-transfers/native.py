"""Native-coin transfers (top-level and internal) for one address.

Logs do not record native ETH moves, so Ethereum, Base and Arbitrum need traces.
Polygon is the exception: its POL system contract emits a LogTransfer event per move.

    python native.py ethereum 0xADDRESS --blocks 7200     # trace_filter, one request per window
    python native.py arbitrum 0xADDRESS --blocks 20       # debug_traceBlockByNumber, one request per block
    python native.py polygon 0xADDRESS --blocks 50000     # LogTransfer logs, like the ERC-20 scan
"""
import argparse
import time

from rpc import Chain, RpcError
from windows import Window, scan_logs

TRACE_WINDOW = 100  # trace_filter range cap measured on Dwellir Ethereum and Base, 13 Nov 2026


def via_trace_filter(chain, address, from_block, to_block):
    found = {}
    windows = [(lo, min(lo + TRACE_WINDOW - 1, to_block))
               for lo in range(from_block, to_block + 1, TRACE_WINDOW)]
    for field in ("fromAddress", "toAddress"):
        traces = []
        for lo, hi in windows:
            traces += chain.call("trace_filter", [{"fromBlock": hex(lo), "toBlock": hex(hi), field: [address]}])
        for trace in traces:
            action = trace["action"]
            # delegatecall and staticcall repeat the caller's value without moving coins
            if trace["type"] != "call" or action.get("callType") != "call" or trace.get("error"):
                continue
            value = int(action.get("value", "0x0"), 16)
            if value:
                key = (trace["transactionHash"], tuple(trace["traceAddress"]))
                found[key] = (trace["blockNumber"], trace["transactionHash"],
                              "top-level" if not trace["traceAddress"] else "internal",
                              action["from"], action["to"], value)
    # trace_filter marks an error on the frame that reverted, not on its children.
    # Drop every row from a failed transaction. A child of a caught inner revert can still slip through.
    # One eth_getBlockReceipts per block, not one receipt per transaction.
    ok = set()
    for block in {row[0] for row in found.values()}:
        for receipt in chain.call("eth_getBlockReceipts", [hex(block)]):
            if receipt["status"] == "0x1":
                ok.add(receipt["transactionHash"])
    return sorted(row for row in found.values() if row[1] in ok)


POL_CONTRACT = "0x0000000000000000000000000000000000001010"
# LogTransfer(address indexed token, address indexed from, address indexed to, uint256 amount, ...)
LOG_TRANSFER = "0xe6497e3ee548a3372136af2fcb0696db31fc6cf20260707645068bd3fe97f3c4"


def via_pol_logs(chain, address, from_block, to_block):
    me = "0x" + address[2:].rjust(64, "0")
    window = Window(10000)
    found = {}
    for topics in ([LOG_TRANSFER, None, me], [LOG_TRANSFER, None, None, me]):
        for logs in scan_logs(chain, from_block, to_block, topics, window, address=POL_CONTRACT):
            for log in logs:
                found[(log["transactionHash"], log["logIndex"])] = (
                    int(log["blockNumber"], 16), log["transactionHash"], "LogTransfer",
                    "0x" + log["topics"][2][-40:], "0x" + log["topics"][3][-40:],
                    int(log["data"][2:66], 16))
    return sorted(found.values())


def _walk(frame, address, block, tx_hash, depth=0):
    if "error" in frame:
        return  # a reverted frame undoes every transfer beneath it
    value = int(frame.get("value", "0x0"), 16)
    moves = frame.get("type") in ("CALL", "CREATE", "CREATE2")
    if value and moves and address in (frame["from"].lower(), frame.get("to", "").lower()):
        yield (block, tx_hash, "top-level" if depth == 0 else "internal",
               frame["from"], frame.get("to", ""), value)
    for child in frame.get("calls", []):
        yield from _walk(child, address, block, tx_hash, depth + 1)


def via_block_traces(chain, address, from_block, to_block):
    found = []
    for number in range(from_block, to_block + 1):
        traces = chain.call(
            "debug_traceBlockByNumber", [hex(number), {"tracer": "callTracer"}]
        )
        for item in traces:
            if "result" in item:
                found += _walk(item["result"], address, number, item.get("txHash", ""))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain")
    parser.add_argument("address")
    parser.add_argument("--blocks", type=int, default=100)
    parser.add_argument("--traces", action="store_true", help="on Polygon, trace instead of reading LogTransfer")
    args = parser.parse_args()

    chain = Chain(args.chain)
    address = args.address.lower()
    head = int(chain.call("eth_blockNumber", []), 16)
    first = head - args.blocks + 1
    started = time.monotonic()
    if args.chain == "polygon" and not args.traces:
        rows, route = via_pol_logs(chain, address, first, head), "LogTransfer logs"
    else:
        try:
            rows, route = via_trace_filter(chain, address, first, head), "trace_filter"
        except RpcError as error:
            if error.code != -32601:  # -32601: method not available on this chain
                raise
            rows, route = via_block_traces(chain, address, first, head), "debug_traceBlockByNumber"
    for row in rows:
        print(*row[:5], f"{row[5] / 1e18:.6f}")
    print(f"{args.chain}: {route}, blocks {first}-{head}, {len(rows)} native transfers, "
          f"{chain.requests} requests, {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
