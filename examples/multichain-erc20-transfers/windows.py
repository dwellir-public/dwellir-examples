"""Self-sizing eth_getLogs windows.

A condensed version of the scanner in
https://www.dwellir.com/guides/eth-getlogs-limits. That guide explains each rule.
"""
import re
import time

from rpc import RpcError

# The answer was too big or too slow. Checked first: these messages can name a range.
TOO_MUCH_DATA = re.compile(
    r"exceeds max results|more than \d+ results|response size|timed out|timeout|too many", re.I
)
# The span itself is over the plan cap.
RANGE_CAP = re.compile(r"range of \d+ blocks|-block limit|block range|maximum allowed is \d+ blocks", re.I)
TRANSIENT = re.compile(r"rate limit|overloaded|try again|temporarily unavailable|HTTP 429", re.I)
SUGGESTED_RANGE = re.compile(r"retry with the range (\d+)-(\d+)", re.I)
STATED_CAP = re.compile(r"at most (\d+) blocks|(\d+)-block limit|maximum allowed is (\d+) blocks", re.I)

TARGET_LOGS = 5000
MAX_RETRIES = 5


class Window:
    """Window width for one chain. A range-cap rejection lowers the ceiling for good."""

    def __init__(self, ceiling):
        self.ceiling = ceiling
        self.size = ceiling

    def narrow(self, message, cursor, end):
        if TOO_MUCH_DATA.search(message):
            match = SUGGESTED_RANGE.search(message)
            if match and cursor <= int(match.group(2)) < end:
                return int(match.group(2)) - cursor + 1
            return max(1, (end - cursor + 1) // 2)
        if RANGE_CAP.search(message):
            match = STATED_CAP.search(message)
            cap = int(next(g for g in match.groups() if g)) if match else (end - cursor + 1) // 2
            self.ceiling = max(1, cap)
            return self.ceiling
        return None

    def resize(self, blocks, logs):
        ideal = blocks * 2 if logs == 0 else blocks * TARGET_LOGS / logs
        self.size = int(max(1, min(self.ceiling, blocks * 2, ideal)))


def scan_logs(chain, from_block, to_block, topics, window, address=None):
    """Yield the logs for [from_block, to_block] one accepted window at a time."""
    cursor = from_block
    retries = 0
    while cursor <= to_block:
        end = min(cursor + window.size - 1, to_block)
        try:
            log_filter = {"fromBlock": hex(cursor), "toBlock": hex(end), "topics": topics}
            if address:
                log_filter["address"] = address
            logs = chain.call("eth_getLogs", [log_filter])
        except RpcError as error:
            if TRANSIENT.search(error.message) and retries < MAX_RETRIES:
                retries += 1
                time.sleep(2**retries)
                continue
            size = window.narrow(error.message, cursor, end)
            if size is None or end == cursor:
                raise  # unknown error, or one block alone is too much for eth_getLogs
            window.size = size
            continue
        retries = 0
        yield logs
        window.resize(end - cursor + 1, len(logs))
        cursor = end + 1
