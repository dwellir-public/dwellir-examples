# Build a Rust trading bot on BSC: transcript


## 0:00 Intro: Rust trading bot on BSC

In three minutes, you'll build a Rust trading bot on BSC, using a Dwellir endpoint.

## 0:08 What you need (Rust 1.80+, Dwellir account, editor)

You need three things. Rust, version 1.80 or newer. A free Dwellir account. And a code editor.

## 0:17 Get a BSC RPC endpoint from the Dwellir dashboard

Log in to the Dwellir dashboard and open Chains. Click search, and type Binance. On the Binance Smart Chain card, click Endpoints. Here are your Binance Smart Chain endpoints. Your API key is built into the URL. Click the copy icon next to the HTTPS URL. That's copied. Keep this key secret, because every request on it counts against your account.

## 0:50 Create the Rust project (cargo new)

Open a terminal, and run cargo new bsc-bot. Change into the folder, and open it in your editor.

## 1:01 Add dependencies: ureq and serde_json

Open Cargo.toml. Under dependencies, add ureq, for HTTP calls, and serde_json, for JSON.

## 1:11 Paste the bot code into main.rs

Open main.rs, select all, and paste in the bot. The code is in the description.

## 1:18 Code part 1: JSON-RPC call to Dwellir

Part one connects to Dwellir. POOL is the BNB/USDT pool, and the rpc function sends one JSON-RPC call to your endpoint.

## 1:30 Code part 2: read the USDT/WBNB price from the pool (slot0)

The price function reads the pool directly, with one call to slot0. The price is stored as a square root, so we square it, then flip it to get dollars per BNB.

## 1:42 Code part 3: poll new blocks every 2 seconds

In main, the bot reads your endpoint from DWELLIR_URL. Every two seconds, it gets the latest block and price, and keeps the last twenty.

## 1:53 Code part 4: moving-average crossover strategy

Then the strategy. When the average of the last five prices goes above the average of all twenty, it buys. When it drops below, it sells. It starts with one thousand dollars of paper money, so nothing real is at risk.

## 2:08 Set DWELLIR_URL with your endpoint

Type export DWELLIR_URL, equals, quote. Paste your endpoint, and close the quote. This keeps your key out of the code, so you can share the code safely.

## 2:20 Run the bot: real output

Now run it, with cargo run --release. It's connected to BSC mainnet. Each line is a new block, and the live BNB price. This is real output, sped up. When the two averages cross, the bot prints a buy, or a sell. There's a buy. And a sell, 52 cents down.

## 2:50 Next steps: paper trade, then go live

Your bot is live on BSC. Paper trade first, then add a wallet to go live. Get your endpoint at dashboard.dwellir.com.
