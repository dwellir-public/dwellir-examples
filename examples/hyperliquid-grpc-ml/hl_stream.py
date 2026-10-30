"""Stream Hyperliquid fills from Dwellir's gRPC gateway and roll them into bars.

StreamFills on the HyperliquidL1Gateway service replays from a block or a
timestamp, then keeps streaming live on the same call. That lets one loop
build a training set from the last few days and carry on into live data.
"""

import json
import math
import os
import queue
import threading
import time
from collections import defaultdict

import grpc

try:
    import v3_pb2 as pb
    import v3_pb2_grpc as rpc
except ImportError:  # BarBuilder works without the gRPC stubs (Index path)
    pb = rpc = None

ENDPOINT = os.environ.get("DWELLIR_GRPC_ENDPOINT", "api-hyperliquid-mainnet-grpc.n.dwellir.com:443")
RETRY_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.DATA_LOSS,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
}


def connect():
    channel = grpc.secure_channel(
        ENDPOINT,
        grpc.ssl_channel_credentials(),
        options=[("grpc.max_receive_message_length", 64 << 20)],
    )
    metadata = [("x-api-key", os.environ["DWELLIR_API_KEY"])]
    return channel, metadata


def stream_fills(coins, start_ms):
    """Yield (block_number, block_time_ms, user, fill) from start_ms onward.

    The server filters to `coins`. A background thread reads the stream as
    fast as the server sends it and queues the raw records; this generator
    parses them. A reader that falls behind makes the gateway slow the stream
    down, so keep parsing off the receive loop.
    """
    records = queue.Queue()
    threading.Thread(target=_read_fills, args=(coins, start_ms, records), daemon=True).start()
    while True:
        item = records.get()
        if isinstance(item, Exception):
            raise item
        block_number, block_ms, data = item
        for user, fill in json.loads(data)["events"]:
            yield block_number, block_ms, user, fill


def _read_fills(coins, start_ms, records):
    """Read StreamFills into `records`, resuming from the last block on retryable errors.

    Positions are inclusive, so the last block is skipped the second time.
    """
    channel, metadata = connect()
    gateway = rpc.HyperliquidL1GatewayStub(channel)
    flt = pb.Filter(fields=[pb.FieldFilter(field="coins", values=coins)])
    position = pb.Position(timestamp=start_ms)
    last_block = None
    backoff = 1
    while True:
        try:
            request = pb.StreamRequest(position=position, filter=flt)
            for record in gateway.StreamFills(request, metadata=metadata):
                if not record.HasField("block_number"):
                    continue
                if last_block is not None and record.block_number <= last_block:
                    continue
                last_block = record.block_number
                backoff = 1
                records.put((record.block_number, record.timestamp, record.data))
        except grpc.RpcError as err:
            if err.code() not in RETRY_CODES:
                records.put(err)
                return
            if last_block is not None:
                position = pb.Position(block_number=last_block)
            print(f"stream {err.code().name}: {err.details()}; resuming in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


def _empty_bar():
    return {
        "open": math.nan, "high": -math.inf, "low": math.inf, "close": math.nan,
        "notional": 0.0, "base": 0.0, "buy_ntl": 0.0, "sell_ntl": 0.0,
        "open_buy_ntl": 0.0, "open_sell_ntl": 0.0,
        "liq_long_ntl": 0.0, "liq_short_ntl": 0.0, "trades": 0,
    }


class BarBuilder:
    """Turn taker fills into fixed-width bars per coin.

    Every match produces one fill per side. Counting only the taker side
    (crossed=True) counts each trade once and tells you who was aggressive.
    A bar is final once a block arrives at or after its close time.
    """

    def __init__(self, bar_ms=60_000):
        self.bar_ms = bar_ms
        self.bars = defaultdict(_empty_bar)  # (bar_start, coin) -> bar
        self.closed_through = None

    def add(self, block_ms, fill):
        """Add one fill. Returns the list of bars that closed, oldest first."""
        closed = self._close_up_to(block_ms - block_ms % self.bar_ms)
        if not fill.get("crossed"):
            return closed
        px, sz = float(fill["px"]), float(fill["sz"])
        ntl = px * sz
        bar = self.bars[(fill["time"] - fill["time"] % self.bar_ms, fill["coin"])]
        if math.isnan(bar["open"]):
            bar["open"] = px
        bar["high"] = max(bar["high"], px)
        bar["low"] = min(bar["low"], px)
        bar["close"] = px
        bar["notional"] += ntl
        bar["base"] += sz
        bar["trades"] += 1
        buy = fill["side"] == "B"
        bar["buy_ntl" if buy else "sell_ntl"] += ntl
        if fill["dir"].startswith("Open"):
            bar["open_buy_ntl" if buy else "open_sell_ntl"] += ntl
        if fill.get("liquidation"):
            # A forced sell closes a long, a forced buy closes a short.
            bar["liq_short_ntl" if buy else "liq_long_ntl"] += ntl
        return closed

    def flush(self):
        """Close every open bar. Use at the end of a bounded download."""
        return self._close_up_to(math.inf)

    def _close_up_to(self, bar_start):
        if self.closed_through is not None and bar_start <= self.closed_through:
            return []
        done = sorted(k for k in self.bars if k[0] < bar_start)
        self.closed_through = bar_start - self.bar_ms
        out = []
        for key in done:
            bar = self.bars.pop(key)
            bar["vwap"] = bar["notional"] / bar["base"]
            del bar["base"]
            out.append({"time": key[0], "coin": key[1], **bar})
        return out
