# Build a Rust trading bot on Robinhood Chain: transcript


## 0:00 Intro: Rust trading bot on Robinhood Chain

[0:00] In three minutes, you'll build a Rust trading bot on Robinhood Chain, using a Dwellir endpoint.

## 0:08 What you need (Rust 1.80+, Dwellir account, editor)

[0:08] You need three things. Rust, version 1.80 or newer. A free Dwellir account. And a code editor.

## 0:17 Get a Robinhood Chain RPC endpoint from the Dwellir dashboard

[0:17] Log in to the Dwellir dashboard and open Chains. Click search, and type Robinhood.
[0:25] On the Robinhood card, click Endpoints.
[0:29] Here are your Robinhood endpoints. Your API key is built into the URL.
[0:34] Click the copy icon next to the HTTPS URL.
[0:39] That's copied. Keep this key secret, because every request on it counts against your account.

## 0:50 Create the Rust project (cargo new)

[0:50] Open a terminal, and run cargo new hood-bot.
[0:55] Change into the folder,
[0:57] and open it in your editor.

## 1:01 Add dependencies: ureq and serde_json

[1:01] Open Cargo.toml. Under dependencies, add ureq, for HTTP calls, and serde_json, for JSON.

## 1:11 Paste the bot code into main.rs

[1:11] Open main.rs, select all, and paste in the bot. The code is in the description.

## 1:18 Code part 1: JSON-RPC call to Dwellir

[1:18] Part one connects to Dwellir. POOL is the WETH/USDG pool, and the rpc function sends one JSON-RPC call to your endpoint.

## 1:30 Code part 2: read WETH/USDG price from the pool (slot0)

[1:30] The price function reads the pool directly, with one call to slot0. The price is stored as a square root, so we square it and adjust for decimals.

## 1:42 Code part 3: poll new blocks every 2 seconds

[1:42] In main, the bot reads your endpoint from DWELLIR_URL. Every two seconds, it gets the latest block and price, and keeps the last twenty.

## 1:53 Code part 4: moving-average crossover strategy

[1:53] Then the strategy. When the average of the last five prices goes above the average of all twenty, it buys. When it drops below, it sells. It starts with one thousand dollars of paper money, so nothing real is at risk.

## 2:08 Set DWELLIR_URL with your endpoint

[2:08] Type export DWELLIR_URL, equals, quote.
[2:11] Paste your endpoint, and close the quote.
[2:14] This keeps your key out of the code, so you can share the code safely.

## 2:20 Run the bot: real output

[2:20] Now run it, with cargo run --release.
[2:25] It's connected to Robinhood Chain mainnet. Each line is a new block, and the live WETH price.
[2:32] This is real output, sped up seven times. When the two averages cross, the bot prints a buy, or a sell.
[2:44] There's a buy.
[2:47] And a sell, a few cents down.

## 2:50 Next steps: paper trade, then go live

[2:50] Your bot is live on Robinhood Chain. Paper trade first, then add a wallet to go live. Get your endpoint at dashboard.dwellir.com.
