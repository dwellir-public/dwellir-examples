"""Minimal JSON-RPC client for Dwellir EVM endpoints, one client per chain."""
import os
import time

import httpx

# Endpoint per chain. Set RPC_<CHAIN> to override, for example RPC_POLYGON.
ENDPOINTS = {
    "ethereum": "https://api-ethereum-mainnet.n.dwellir.com/{key}",
    "base": "https://api-base-mainnet-archive.n.dwellir.com/{key}",
    "arbitrum": "https://api-arbitrum-mainnet-archive.n.dwellir.com/{key}",
    "polygon": "https://api-polygon-mainnet-full.n.dwellir.com/{key}",
}

# Seconds between requests. 0.5 keeps one process at 2 requests per second.
MIN_INTERVAL = float(os.environ.get("MIN_INTERVAL", "0.5"))


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class Chain:
    def __init__(self, name):
        override = os.environ.get(f"RPC_{name.upper()}")
        if override:
            url = override
        else:
            key = os.environ.get("DWELLIR_API_KEY")
            if not key:
                raise SystemExit("set DWELLIR_API_KEY, or RPC_<CHAIN> for each chain")
            url = ENDPOINTS[name].format(key=key)
        self.name = name
        self._url = url
        self._client = httpx.Client(timeout=60.0)
        self._last = 0.0
        self.requests = 0

    def call(self, method, params):
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self.requests += 1
        try:
            response = self._client.post(
                self._url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
        except httpx.TimeoutException:
            raise RpcError(None, "client timeout") from None
        finally:
            self._last = time.monotonic()
        if response.status_code == 429 or response.status_code >= 500:
            raise RpcError(response.status_code, f"HTTP {response.status_code} temporarily unavailable")
        payload = response.json()
        if "error" in payload:
            error = payload["error"]
            raise RpcError(error.get("code"), error.get("message", ""))
        return payload["result"]

    def block(self, tag):
        number = tag if isinstance(tag, str) else hex(tag)
        return self.call("eth_getBlockByNumber", [number, False])
