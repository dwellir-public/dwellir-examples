"""Token decimals and symbol with eth_call, cached per chain and token.

Reads at `latest`, so every row shows the token's current decimals and symbol.
"""
import time

from rpc import RpcError
from windows import TRANSIENT

DECIMALS = "0x313ce567"  # decimals()
SYMBOL = "0x95d89b41"  # symbol()


def _eth_call(chain, token, selector, retries=3):
    for attempt in range(retries + 1):
        try:
            return chain.call("eth_call", [{"to": token, "data": selector}, "latest"])
        except RpcError as error:
            if error.code is not None and not TRANSIENT.search(error.message):
                return None  # reverted, or no such function
            if attempt == retries:
                raise  # a timeout or rate limit says nothing about the token: do not cache it
            time.sleep(2 ** (attempt + 1))


def decode_symbol(result):
    raw = bytes.fromhex((result or "0x")[2:])
    if len(raw) == 32:
        # Old tokens such as MKR return bytes32, not a string.
        text = raw.rstrip(b"\0")
    elif len(raw) >= 64:
        offset = int.from_bytes(raw[:32], "big")
        length = int.from_bytes(raw[offset : offset + 32], "big") if offset + 32 <= len(raw) else 0
        text = raw[offset + 32 : offset + 32 + length]
    else:
        return ""
    clean = "".join(c for c in text.decode("utf-8", "replace") if c.isprintable())
    return clean[:32]


class TokenCache:
    def __init__(self, chain):
        self.chain = chain
        self._cache = {}

    def get(self, token):
        if token not in self._cache:
            decimals = None
            result = _eth_call(self.chain, token, DECIMALS)
            if result and len(result) >= 66:
                value = int(result[:66], 16)
                decimals = value if value <= 36 else None
            symbol = decode_symbol(_eth_call(self.chain, token, SYMBOL))
            self._cache[token] = (symbol, decimals)
        return self._cache[token]
