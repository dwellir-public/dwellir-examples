# Robinhood Chain Rust trading bot

A 54-line Rust bot that reads the live WETH/USDG price on Robinhood Chain through a Dwellir RPC endpoint and paper-trades a moving-average crossover.

- Chain: Robinhood Chain mainnet (chain ID 4663)
- Language: Rust (1.80 or newer)
- Difficulty: Beginner
- Dependencies: `ureq`, `serde_json`
- Video walkthrough (3 min): see [TRANSCRIPT.md](./TRANSCRIPT.md) for the full timestamped script

> Paper trading only. The bot reads data with `eth_call` and never signs or sends a transaction. Example code, not financial advice.

## Quick start

1. Get a Robinhood Chain endpoint: log in at https://dashboard.dwellir.com, open **Chains**, search **Robinhood**, click **Endpoints**, and copy the HTTPS URL.
2. Clone and run:

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/robinhood-rust-trading-bot
export DWELLIR_URL="https://api-robinhood-mainnet-archive.n.dwellir.com/YOUR_API_KEY"
cargo run --release
```

Windows PowerShell: `$env:DWELLIR_URL="https://api-robinhood-mainnet-archive.n.dwellir.com/YOUR_API_KEY"`

## Build it from scratch

```bash
cargo new hood-bot
cd hood-bot
```

Add to `Cargo.toml`:

```toml
[dependencies]
ureq = { version = "2", features = ["json"] }
serde_json = "1"
```

Replace `src/main.rs` with [the code in this folder](./src/main.rs), set `DWELLIR_URL`, and run `cargo run --release`.

## Example output

```text
Connected. Chain ID 4663
block 88331094 | WETH $2499.20 | paper value $1000.00
block 88331115 | WETH $2499.20 | paper value $1000.00
BUY  0.4001 WETH @ $2499.21
block 88331135 | WETH $2499.21 | paper value $1000.00
...
SELL @ $2498.88  balance $999.87
```

## How it works

| Part | Code | What it does |
|------|------|--------------|
| Connect | `rpc()` | Sends one JSON-RPC request to your Dwellir endpoint and returns `result` |
| Price | `weth_price()` | Calls `slot0()` (`0x3850c7bd`) on the WETH/USDG 0.01% pool `0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca`, squares `sqrtPriceX96 / 2^96`, and multiplies by `1e12` (WETH has 18 decimals, USDG has 6) |
| Loop | `main()` | Every 2 seconds: `eth_blockNumber`, read the price, keep the last 20 prices |
| Strategy | `main()` | Average of the last 5 prices above the average of all 20 = BUY, below = SELL. Starts with $1,000 of paper money |

## Next steps

- Paper trade for a few days and check the results before you use real funds.
- To trade for real, add a wallet key and a swap router call. Test with small amounts.
- Use the WSS endpoint and `eth_subscribe` (`newHeads`) to react to every block instead of polling.
