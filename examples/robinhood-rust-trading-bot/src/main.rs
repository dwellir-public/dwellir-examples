// Robinhood Chain trading bot: WETH/USDG moving-average crossover.
// Paper trades by default. Read-only: it never signs or sends a transaction.
use serde_json::{json, Value};
use std::{env, thread, time::Duration};

const POOL: &str = "0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca"; // WETH/USDG 0.01%

fn rpc(url: &str, method: &str, params: Value) -> Value {
    let body = json!({"jsonrpc": "2.0", "id": 1, "method": method, "params": params});
    let res: Value = ureq::post(url).send_json(body).unwrap().into_json().unwrap();
    res["result"].clone()
}

fn weth_price(url: &str) -> f64 {
    // slot0() returns sqrtPriceX96 as the first 32-byte word
    let hex = rpc(url, "eth_call", json!([{"to": POOL, "data": "0x3850c7bd"}, "latest"]));
    let word = &hex.as_str().unwrap()[2..66];
    let sqrt = u128::from_str_radix(&word[32..], 16).unwrap() as f64 / 2f64.powi(96);
    sqrt * sqrt * 1e12 // WETH has 18 decimals, USDG has 6
}

fn num(v: Value) -> u64 {
    u64::from_str_radix(&v.as_str().unwrap()[2..], 16).unwrap()
}

fn avg(v: &[f64]) -> f64 {
    v.iter().sum::<f64>() / v.len() as f64
}

fn main() {
    let url = env::var("DWELLIR_URL").expect("set DWELLIR_URL");
    let (mut prices, mut usd, mut eth) = (Vec::new(), 1000.0, 0.0);
    println!("Connected. Chain ID {}", num(rpc(&url, "eth_chainId", json!([]))));

    loop {
        let block = num(rpc(&url, "eth_blockNumber", json!([])));
        let price = weth_price(&url);
        prices.push(price);
        if prices.len() > 20 { prices.remove(0); }

        if prices.len() == 20 {
            let (fast, slow) = (avg(&prices[15..]), avg(&prices));
            if fast > slow && usd > 0.0 {
                eth = usd / price; usd = 0.0;
                println!("BUY  {eth:.4} WETH @ ${price:.2}");
            } else if fast < slow && eth > 0.0 {
                usd = eth * price; eth = 0.0;
                println!("SELL @ ${price:.2}  balance ${usd:.2}");
            }
        }
        println!("block {block} | WETH ${price:.2} | paper value ${:.2}", usd + eth * price);
        thread::sleep(Duration::from_secs(2));
    }
}
