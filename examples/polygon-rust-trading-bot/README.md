# Polygon Rust trading bot

A 54-line Rust bot that reads the live POL price on Polygon through a Dwellir RPC endpoint and paper-trades a moving-average crossover.

- Chain: Polygon mainnet (chain ID 137)
- Language: Rust (1.80 or newer)
- Difficulty: Beginner
- Dependencies: `ureq`, `serde_json`
- Video walkthrough (3 min): see [TRANSCRIPT.md](./TRANSCRIPT.md) for the full timestamped script

> Paper trading only. The bot reads data with `eth_call` and never signs or sends a transaction. Example code, not financial advice.

## Quick start

1. Get a Polygon endpoint: log in at https://dashboard.dwellir.com, open **Chains**, search **Polygon**, click **Endpoints**, and copy the HTTPS URL.
   Use the **Full** box. The archive endpoint also works.
2. Clone and run:

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/polygon-rust-trading-bot
export DWELLIR_URL="https://api-polygon-mainnet-full.n.dwellir.com/YOUR_API_KEY"
cargo run --release
```

Windows PowerShell: `$env:DWELLIR_URL="https://api-polygon-mainnet-full.n.dwellir.com/YOUR_API_KEY"`

## Build it from scratch

```bash
cargo new polygon-bot
cd polygon-bot
```

Add to `Cargo.toml`:

```toml
[dependencies]
ureq = { version = "2", features = ["json"] }
serde_json = "1"
```

Replace `src/main.rs` with [the code in this folder](./src/main.rs), set `DWELLIR_URL`, and run `cargo run --release`.

## Example output

Real run against Polygon mainnet on 2026-10-14:

```text
Connected. Chain ID 137
block 95520966 | POL $0.09706 | paper value $1001.26
block 95520967 | POL $0.09706 | paper value $1001.26
BUY  10315.5949 POL @ $0.09706
...
SELL @ $0.09705  balance $1001.09
```

## How it works

| Part | Code | What it does |
|------|------|--------------|
| Connect | `rpc()` | Sends one JSON-RPC request to your Dwellir endpoint and returns `result` |
| Price | `price()` | Calls `slot0()` (`0x3850c7bd`) on the WPOL/USDC 0.05% pool `0xb6e57ed85c4c9dbfef2a68711e9d6f36c56e0fcb`. Squares `sqrtPriceX96 / 2^96` and multiplies by `1e12` (the token has 18 decimals, USDC has 6). |
| Loop | `main()` | Every 2 seconds: `eth_blockNumber`, read the price, keep the last 20 prices |
| Strategy | `main()` | Average of the last 5 prices above the average of all 20 = BUY, below = SELL. Starts with $1,000 of paper money |

## Next steps

- Paper trade for a few days and check the results before you use real funds.
- To trade for real, add a wallet key and a swap router call. Test with small amounts.
- Use the WSS endpoint and `eth_subscribe` (`newHeads`) to react to every block instead of polling.
- Swap `POOL` for another Uniswap-v3-style pool to track a different pair.
