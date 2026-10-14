# Arbitrum Rust trading bot

A 54-line Rust bot that reads the live WETH price on Arbitrum through a Dwellir RPC endpoint and paper-trades a moving-average crossover.

- Chain: Arbitrum mainnet (chain ID 42161)
- Language: Rust (1.80 or newer)
- Difficulty: Beginner
- Dependencies: `ureq`, `serde_json`
- Video walkthrough (3 min): see [TRANSCRIPT.md](./TRANSCRIPT.md) for the full timestamped script

> Paper trading only. The bot reads data with `eth_call` and never signs or sends a transaction. Example code, not financial advice.

## Quick start

1. Get a Arbitrum endpoint: log in at https://dashboard.dwellir.com, open **Chains**, search **Arbitrum**, click **Endpoints**, and copy the HTTPS URL.
   Use the **Arbitrum (Full Node)** box. The archive endpoint also works.
2. Clone and run:

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/arbitrum-rust-trading-bot
export DWELLIR_URL="https://api-arbitrum-mainnet-full.n.dwellir.com/YOUR_API_KEY"
cargo run --release
```

Windows PowerShell: `$env:DWELLIR_URL="https://api-arbitrum-mainnet-full.n.dwellir.com/YOUR_API_KEY"`

## Build it from scratch

```bash
cargo new arbitrum-bot
cd arbitrum-bot
```

Add to `Cargo.toml`:

```toml
[dependencies]
ureq = { version = "2", features = ["json"] }
serde_json = "1"
```

Replace `src/main.rs` with [the code in this folder](./src/main.rs), set `DWELLIR_URL`, and run `cargo run --release`.

## Example output

Real run against Arbitrum mainnet on 2026-10-14:

```text
Connected. Chain ID 42161
block 514760959 | WETH $2453.10 | paper value $1000.00
block 514760967 | WETH $2453.10 | paper value $1000.00
BUY  0.4077 WETH @ $2452.63
...
SELL @ $2451.64  balance $999.60
```

## How it works

| Part | Code | What it does |
|------|------|--------------|
| Connect | `rpc()` | Sends one JSON-RPC request to your Dwellir endpoint and returns `result` |
| Price | `price()` | Calls `slot0()` (`0x3850c7bd`) on the WETH/USDC 0.05% pool `0xc6962004f452be9203591991d15f6b388e09e8d0`. Squares `sqrtPriceX96 / 2^96` and multiplies by `1e12` (the token has 18 decimals, USDC has 6). |
| Loop | `main()` | Every 2 seconds: `eth_blockNumber`, read the price, keep the last 20 prices |
| Strategy | `main()` | Average of the last 5 prices above the average of all 20 = BUY, below = SELL. Starts with $1,000 of paper money |

## Next steps

- Paper trade for a few days and check the results before you use real funds.
- To trade for real, add a wallet key and a swap router call. Test with small amounts.
- Use the WSS endpoint and `eth_subscribe` (`newHeads`) to react to every block instead of polling.
- Swap `POOL` for another Uniswap-v3-style pool to track a different pair.
