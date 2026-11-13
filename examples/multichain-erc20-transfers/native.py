"""Native-coin transfers (top-level and internal) for one address.

Logs do not record native ETH moves, so Ethereum, Base and Arbitrum need traces.
On Polygon, the POL system contract emits a LogTransfer event for each value transfer
in a call or contract creation. A SELFDESTRUCT pays its beneficiary without one, so
only --traces sees that case.

    python native.py ethereum 0xADDRESS --blocks 7200     # trace_filter, one request per window
    python native.py arbitrum 0xADDRESS --blocks 20       # debug_traceBlockByNumber, one request per block
    python native.py polygon 0xADDRESS --blocks 50000     # LogTransfer logs, like the ERC-20 scan
"""
import argparse
import time

from rpc import Chain, RpcError
from windows import Window, scan_logs

TRACE_WINDOW = 100  # trace_filter range cap measured on Dwellir Ethereum and Base, 13 Nov 2026


def _move(trace):
    """(from, to, value) when a trace_filter trace can move native coin, else None."""
    action, kind = trace["action"], trace["type"]
    if kind == "call" and action.get("callType") == "call":
        # delegatecall and staticcall repeat the caller's value without moving coins
        return action["from"], action["to"], int(action.get("value", "0x0"), 16)
    if kind == "create":
        # value sent with a contract deployment; the new address is in the result
        return action["from"], (trace.get("result") or {}).get("address", ""), int(action["value"], 16)
    if kind in ("suicide", "selfdestruct"):
        # SELFDESTRUCT sends the contract's whole balance to the beneficiary
        return action["address"], action["refundAddress"], int(action["balance"], 16)
    return None


def via_trace_filter(chain, address, from_block, to_block):
    found = {}
    windows = [(lo, min(lo + TRACE_WINDOW - 1, to_block))
               for lo in range(from_block, to_block + 1, TRACE_WINDOW)]
    for field in ("fromAddress", "toAddress"):
        traces = []
        for lo, hi in windows:
            traces += chain.call("trace_filter", [{"fromBlock": hex(lo), "toBlock": hex(hi), field: [address]}])
        for trace in traces:
            move = None if trace.get("error") else _move(trace)
            if move and move[2]:
                key = (trace["transactionHash"], tuple(trace["traceAddress"]))
                found[key] = (trace["blockNumber"], trace["transactionHash"],
                              "top-level" if not trace["traceAddress"] else "internal", *move)
    # trace_filter marks an error only on the frame that reverted, not on the frames beneath it,
    # and a failed transaction carries its error on the top frame. For an internal transfer,
    # read the whole transaction once and drop the transfer if any frame above it reverted.
    reverted = {}
    for tx_hash, path in found:
        if path and tx_hash not in reverted:
            reverted[tx_hash] = {tuple(t["traceAddress"])
                                 for t in chain.call("trace_transaction", [tx_hash]) if t.get("error")}
    return sorted(row for (tx_hash, path), row in found.items()
                  if not any(path[:depth] in reverted.get(tx_hash, ()) for depth in range(len(path))))


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
    # SELFDESTRUCT pays the contract's balance to the beneficiary in "to"
    moves = frame.get("type") in ("CALL", "CREATE", "CREATE2", "SELFDESTRUCT")
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
