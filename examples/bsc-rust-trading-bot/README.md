# BSC Rust trading bot

A 54-line Rust bot that reads the live BNB price on BSC through a Dwellir RPC endpoint and paper-trades a moving-average crossover.

- Chain: BSC mainnet (chain ID 56)
- Language: Rust (1.80 or newer)
- Difficulty: Beginner
- Dependencies: `ureq`, `serde_json`
- Video walkthrough (3 min): see [TRANSCRIPT.md](./TRANSCRIPT.md) for the full timestamped script

> Paper trading only. The bot reads data with `eth_call` and never signs or sends a transaction. Example code, not financial advice.

## Quick start

1. Get a BSC endpoint: log in at https://dashboard.dwellir.com, open **Chains**, search **Binance**, click **Endpoints**, and copy the HTTPS URL.
2. Clone and run:

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/bsc-rust-trading-bot
export DWELLIR_URL="https://api-bsc-mainnet-full.n.dwellir.com/YOUR_API_KEY"
cargo run --release
```

Windows PowerShell: `$env:DWELLIR_URL="https://api-bsc-mainnet-full.n.dwellir.com/YOUR_API_KEY"`

## Build it from scratch

```bash
cargo new bsc-bot
cd bsc-bot
```

Add to `Cargo.toml`:

```toml
[dependencies]
ureq = { version = "2", features = ["json"] }
serde_json = "1"
```

Replace `src/main.rs` with [the code in this folder](./src/main.rs), set `DWELLIR_URL`, and run `cargo run --release`.

## Example output

Real run against BSC mainnet on 2026-10-14:

```text
Connected. Chain ID 56
block 127606932 | BNB $736.43 | paper value $1000.00
block 127606936 | BNB $736.51 | paper value $1000.00
BUY  1.3579 BNB @ $736.44
...
SELL @ $736.05  balance $999.48
```

## How it works

| Part | Code | What it does |
|------|------|--------------|
| Connect | `rpc()` | Sends one JSON-RPC request to your Dwellir endpoint and returns `result` |
| Price | `price()` | Calls `slot0()` (`0x3850c7bd`) on the USDT/WBNB 0.01% pool `0x172fcd41e0913e95784454622d1c3724f546f849`. The pool's token0 is USDT and token1 is WBNB, so the raw price is WBNB per USDT; the bot flips it (`1.0 / (sqrt * sqrt)`). |
| Loop | `main()` | Every 2 seconds: `eth_blockNumber`, read the price, keep the last 20 prices |
| Strategy | `main()` | Average of the last 5 prices above the average of all 20 = BUY, below = SELL. Starts with $1,000 of paper money |

## Next steps

- Paper trade for a few days and check the results before you use real funds.
- To trade for real, add a wallet key and a swap router call. Test with small amounts.
- Use the WSS endpoint and `eth_subscribe` (`newHeads`) to react to every block instead of polling.
- Swap `POOL` for another Uniswap-v3-style pool to track a different pair.
