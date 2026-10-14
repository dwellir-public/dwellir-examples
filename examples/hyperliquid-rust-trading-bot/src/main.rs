// Hyperliquid EVM trading bot: HYPE/USDC moving-average crossover.
// Paper trades by default. Read-only: it never signs or sends a transaction.
use serde_json::{json, Value};
use std::{env, thread, time::Duration};

const POOL: &str = "0x6c9a33e3b592c0d65b3ba59355d5be0d38259285"; // WHYPE/USDC 0.05%

fn rpc(url: &str, method: &str, params: Value) -> Value {
    let body = json!({"jsonrpc": "2.0", "id": 1, "method": method, "params": params});
    let res: Value = ureq::post(url).send_json(body).unwrap().into_json().unwrap();
    res["result"].clone()
}

fn price(url: &str) -> f64 {
    // slot0() returns sqrtPriceX96 as the first 32-byte word
    let hex = rpc(url, "eth_call", json!([{"to": POOL, "data": "0x3850c7bd"}, "latest"]));
    let word = &hex.as_str().unwrap()[2..66];
    let sqrt = u128::from_str_radix(&word[32..], 16).unwrap() as f64 / 2f64.powi(96);
    sqrt * sqrt * 1e12 // WHYPE has 18 decimals, USDC has 6
}

fn num(v: Value) -> u64 {
    u64::from_str_radix(&v.as_str().unwrap()[2..], 16).unwrap()
}

fn avg(v: &[f64]) -> f64 {
    v.iter().sum::<f64>() / v.len() as f64
}

fn main() {
    let url = env::var("DWELLIR_URL").expect("set DWELLIR_URL");
    let (mut prices, mut usd, mut coins) = (Vec::new(), 1000.0, 0.0);
    println!("Connected. Chain ID {}", num(rpc(&url, "eth_chainId", json!([]))));

    loop {
        let block = num(rpc(&url, "eth_blockNumber", json!([])));
        let price = price(&url);
        prices.push(price);
        if prices.len() > 20 { prices.remove(0); }

        if prices.len() == 20 {
            let (fast, slow) = (avg(&prices[15..]), avg(&prices));
            if fast > slow && usd > 0.0 {
                coins = usd / price; usd = 0.0;
                println!("BUY  {coins:.4} HYPE @ ${price:.3}");
            } else if fast < slow && coins > 0.0 {
                usd = coins * price; coins = 0.0;
                println!("SELL @ ${price:.3}  balance ${usd:.2}");
            }
        }
        println!("block {block} | HYPE ${price:.3} | paper value ${:.2}", usd + coins * price);
        thread::sleep(Duration::from_secs(2));
    }
}
