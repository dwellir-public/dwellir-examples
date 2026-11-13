# Multichain ERC-20 transfers

Pull one address's ERC-20 transfer history on Ethereum, Base, Arbitrum and Polygon with plain JSON-RPC, and write one CSV per chain.

- Chains: Ethereum, Base, Arbitrum One, Polygon PoS (mainnets)
- Language: Python 3.10 or newer
- Difficulty: Intermediate
- Dependencies: `httpx`
- Needs: a Dwellir API key on a plan that includes `eth_getLogs` (Developer or above)

Companion guide: [Get ERC-20 token transfers for an address across EVM chains](https://www.dwellir.com/guides/multichain-erc20-transfers).

## What is in here

| File | What it does |
|------|--------------|
| `rpc.py` | JSON-RPC client per chain. Builds each Dwellir endpoint from `DWELLIR_API_KEY`, or reads `RPC_<CHAIN>`. Spaces requests by `MIN_INTERVAL` seconds (default 0.5) |
| `windows.py` | Self-sizing `eth_getLogs` windows, condensed from the [eth_getLogs limits guide](https://www.dwellir.com/guides/eth-getlogs-limits). Reads the plan cap and the suggested range from rejections, and halves on a timeout |
| `transfers.py` | Scans `Transfer` logs with the address in `topics[1]` (sent) and `topics[2]` (received), keeps 3-topic logs (ERC-20, not ERC-721), merges both directions on `(tx_hash, log_index)`, resolves token metadata, marks rows above the finalized block, writes CSV |
| `tokens.py` | `decimals()` and `symbol()` with `eth_call`, cached, including `bytes32` symbols |
| `reorg_check.py` | Re-reads the block hash of every row that was not final when written, and exits 1 if a block was replaced |
| `native.py` | Native-coin transfers, top-level and internal: `trace_filter` on Ethereum and Base, `debug_traceBlockByNumber` with `callTracer` on Arbitrum, and `LogTransfer` logs from the POL system contract on Polygon (`--traces` to trace instead) |

## Quick start

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/multichain-erc20-transfers
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DWELLIR_API_KEY=your-api-key
python transfers.py 0xYourAddress --days 7
python reorg_check.py out/*.csv
```

Pick chains, or point a chain at another endpoint:

```bash
python transfers.py 0xYourAddress --days 30 --chains base,polygon
RPC_POLYGON=https://your-other-endpoint python transfers.py 0xYourAddress --chains polygon
```

Native transfers for the same address:

```bash
python native.py ethereum 0xYourAddress --blocks 7200
python native.py arbitrum 0xYourAddress --blocks 20
python native.py polygon 0xYourAddress --blocks 50000
```

## CSV columns

`chain, block_number, block_time_utc, tx_hash, log_index, direction, counterparty, token, symbol, decimals, amount, amount_raw, finalized, block_hash`

- `direction` is `in`, `out` or `self`.
- `amount` is exact: integer arithmetic, no float. It is empty when the token has no usable `decimals()`.
- `finalized` is `False` for rows above the chain's `finalized` block when written. `reorg_check.py` re-checks those.

## Limits measured on 13 November 2026

One request at a time, on a key whose plan allows 10,000 blocks per `eth_getLogs`.

| | Ethereum | Base | Arbitrum | Polygon |
|---|---|---|---|---|
| `eth_getLogs` block range | 10,000 | 10,000 | 10,000 | 10,000 |
| `eth_getLogs` result cap | 20,000 logs | 10,000 logs | none at 84,116 logs | none at 130,333 logs; 2,000 blocks of all transfers timed out |
| `finalized` behind head | 91 blocks | 5,854 to 12,111 blocks | 4,760 blocks | 1 to 2 blocks |
| `trace_filter` | yes, 100 blocks per call | yes, 100 blocks per call | not available | not available |
| Native POL in logs | | | | `LogTransfer` from `0x...1010` |
| `debug_traceBlockByNumber` | yes | yes | yes | yes |

Requests scale with blocks scanned, not with transfers found. A 7-day run for one address took 1,197 requests and found 34 transfers, none on Arbitrum (430 requests).

## Not covered

- Native and internal transfers in `transfers.py`. Use `native.py`.
- Children of a caught inner revert in `trace_filter` output. `native.py` drops failed transactions, not reverted subcalls inside successful ones.
- Balance changes that emit no `Transfer` event, such as rebasing tokens. Reconcile with `balanceOf` at the end block.
- Incremental runs. Each run rescans its window. Checkpoint the last block per chain and direction for production.
