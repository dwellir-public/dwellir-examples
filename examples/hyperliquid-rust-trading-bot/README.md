# Hyperliquid EVM Rust trading bot

A 54-line Rust bot that reads the live HYPE price on Hyperliquid EVM through a Dwellir RPC endpoint and paper-trades a moving-average crossover.

- Chain: Hyperliquid EVM mainnet (chain ID 999)
- Language: Rust (1.80 or newer)
- Difficulty: Beginner
- Dependencies: `ureq`, `serde_json`
- Video walkthrough (3 min): see [TRANSCRIPT.md](./TRANSCRIPT.md) for the full timestamped script

> Paper trading only. The bot reads data with `eth_call` and never signs or sends a transaction. Example code, not financial advice.

## Quick start

1. Get a Hyperliquid EVM endpoint: log in at https://dashboard.dwellir.com, open **Chains**, search **Hyperliquid**, click **Endpoints**, and copy the HTTPS URL.
   On the Hyperliquid page, use the **Hyperliquid EVM** box (not the Index, gRPC, Info or Orderbook endpoints).
2. Clone and run:

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/hyperliquid-rust-trading-bot
export DWELLIR_URL="https://api-hyperliquid-mainnet-evm.n.dwellir.com/YOUR_API_KEY"
cargo run --release
```

Windows PowerShell: `$env:DWELLIR_URL="https://api-hyperliquid-mainnet-evm.n.dwellir.com/YOUR_API_KEY"`

## Build it from scratch

```bash
cargo new hyper-bot
cd hyper-bot
```

Add to `Cargo.toml`:

```toml
[dependencies]
ureq = { version = "2", features = ["json"] }
serde_json = "1"
```

Replace `src/main.rs` with [the code in this folder](./src/main.rs), set `DWELLIR_URL`, and run `cargo run --release`.

## Example output

Real run against Hyperliquid EVM mainnet on 2026-10-14:

```text
Connected. Chain ID 999
block 48525347 | HYPE $80.464 | paper value $1000.20
block 48525349 | HYPE $80.464 | paper value $1000.20
BUY  12.4305 HYPE @ $80.464
...
SELL @ $80.387  balance $999.25
```

## How it works

| Part | Code | What it does |
|------|------|--------------|
| Connect | `rpc()` | Sends one JSON-RPC request to your Dwellir endpoint and returns `result` |
| Price | `price()` | Calls `slot0()` (`0x3850c7bd`) on the WHYPE/USDC 0.05% pool `0x6c9a33e3b592c0d65b3ba59355d5be0d38259285`. Squares `sqrtPriceX96 / 2^96` and multiplies by `1e12` (the token has 18 decimals, USDC has 6). |
| Loop | `main()` | Every 2 seconds: `eth_blockNumber`, read the price, keep the last 20 prices |
| Strategy | `main()` | Average of the last 5 prices above the average of all 20 = BUY, below = SELL. Starts with $1,000 of paper money |

## Next steps

- Paper trade for a few days and check the results before you use real funds.
- To trade for real, add a wallet key and a swap router call. Test with small amounts.
- Use the WSS endpoint and `eth_subscribe` (`newHeads`) to react to every block instead of polling.
- Swap `POOL` for another Uniswap-v3-style pool to track a different pair.
