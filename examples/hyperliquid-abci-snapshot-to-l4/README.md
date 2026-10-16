# Hyperliquid ABCI snapshot to L4 order book

Rebuild the full L4 order book (every resting order on every perp, spot and outcome market) from a Hyperliquid `periodic_abci_states` snapshot with plain Python. You do not need `hl-node`.

- Chain: Hyperliquid mainnet
- Language: Python 3.9 or newer
- Difficulty: Intermediate
- Dependencies: `msgpack`, `lz4`
- Input: one `periodic_abci_states/<date>/<height>.rmp` or `.rmp.lz4` file

## Why use this

`hl-node compute-l4-snapshots` reads only snapshots written in its own state format. Hyperliquid changes that format at some network upgrades, and it publishes only the latest `hl-node` binary. A current `hl-node` therefore stops on older snapshots with an error like this:

```text
rmp_from_slice: <file>.rmp: missing field ktm
```

The snapshot file is MessagePack with named fields. Any MessagePack library can read it, whichever `hl-node` version wrote it. This script reads the order books from the file directly and writes them in the same JSON shape as `hl-node`.

## Quick start

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/hyperliquid-abci-snapshot-to-l4
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python abci_to_l4.py 1131000000.rmp.lz4 l4-1131000000.json
```

Add `--users` to include the address that placed each order. The `hl-node` export does not include this field.

You need about 20 GB of free RAM. The script loads the whole state into memory. A 1.6 GB snapshot takes about 2 minutes.

## Example output

```text
height 1131000000 at 2026-09-01T00:09:38.186546526: 1226 books, 516930 orders -> l4-1131000000.json
```

The JSON file is a list of `[coin, [bids, asks]]`. Each side starts at the best price. Inside a price level, orders are in time priority.

```json
["BTC", [[
  {"coin": "BTC", "side": "B", "limitPx": "78711.0", "sz": "0.0123", "oid": 532430470001,
   "timestamp": 1788221378120, "triggerCondition": "N/A", "isTrigger": false, "triggerPx": "0.0",
   "children": [
     {"coin": "BTC", "side": "A", "limitPx": "71000.0", "sz": "0.0123", "oid": 532430470002,
      "timestamp": 1788221378120, "triggerCondition": "Price below 77000", "isTrigger": true,
      "triggerPx": "77000.0", "children": [], "isPositionTpsl": false, "reduceOnly": true,
      "orderType": "Stop Market", "origSz": "0.0123", "tif": null, "cloid": null}
   ],
   "isPositionTpsl": false, "reduceOnly": false, "orderType": "Limit", "origSz": "0.0123",
   "tif": "Gtc", "cloid": null},
  ...
], [ ... asks ... ]]]
```

(The orders above show the format. They are not real orders.)

`children` holds the TP/SL orders that were placed with the resting order and that wait for it to fill. They are not on the book.

## How it works

| Step | Snapshot path | What it gives |
|------|---------------|---------------|
| Perp markets | `exchange.locus.cls[i].meta.universe[j]` | Coin name and `szDecimals` for book `exchange.perp_dexs[i].books[j]` |
| Spot markets | `exchange.locus.scl.meta.spot_infos` and `token_infos` | Base token and `szDecimals` for each book in `exchange.spot_books` |
| Outcome markets | `exchange.locus.scl.meta.outr.tto` and `ots` | Outcome id and side, used for names like `#28390` |
| Price levels | `book.halfs[0]` (bids), `book.halfs[1]` (asks) | Levels, best price first. Bid prices are stored as negative numbers |
| Orders | `book.bod.e[k].o` | One resting order. Slots shaped `{"v": ...}` are empty |
| Time priority | level `f`, then order `n` | Start at the level's first slot `f` and follow each order's `n` |
| TP/SL children | `book.user_states[k][1].u` | Waiting trigger orders as `[oid, order]`, found by the ids in the parent's `c.R.c` |

Order fields:

| Raw key | L4 field | Notes |
|---------|----------|-------|
| `o` | `oid` | |
| `c.s` | `side` | `B` or `A` |
| `c.l` | `limitPx` | Integer. Divide by 10^(6 − szDecimals) for perps, 10^(8 − szDecimals) for spot |
| `r` | `sz` | Remaining size. Divide by 10^szDecimals |
| `O` | `origSz` | Original size. Missing means 0 |
| `c.t` | `timestamp` | Milliseconds since the Unix epoch |
| `t` | `tif` | For example `Gtc` or `Alo` |
| `c.r` | `reduceOnly` | |
| `c.c` | `cloid` | Client order id |
| `c.d` | `orderType` | Missing: `Limit`. `S`: `Stop Market`, `s`: `Stop Limit`, `T`: `Take Profit Market`, `t`: `Take Profit Limit` |
| `c.d` | `triggerCondition` | `N/A` without `c.d`. `Triggered` with it, because a trigger order on the book has already fired |
| `i` | `isPositionTpsl` | |
| | `isTrigger`, `triggerPx` | Always `false` and `"0.0"` for orders on the book |
| `c.R.c` | `children` | Child TP/SL order ids, see below |
| `u` | `user` | Only with `--users` |
| `c.b` | | Builder address and fee. Not included in the output |

Child order fields (from `user_states`):

| Raw key | L4 field | Notes |
|---------|----------|-------|
| `c.S` | `sz`, `origSz` | Missing means the TP/SL closes the whole position: size `0.0` and `isPositionTpsl` true |
| `c.l` | `limitPx` | Scaled as for book orders |
| `t.p` | `triggerPx` | Scaled like `limitPx` |
| `t.t` | `triggerCondition` | `sl` or `tp`. A sell stop loss or a buy take profit gives `Price below <px>`. The other two give `Price above <px>` |
| `c.d` | `orderType` | Same codes as above |
| | `isTrigger`, `tif`, `children` | Always `true`, `null` and `[]` |

Spot book 0 is `PURR/USDC`. Other spot books are `@<index>`, or `#<outcome * 10 + side>` for outcome tokens.

## Verified against hl-node

We ran this script and `hl-node compute-l4-snapshots` on the same mainnet snapshot (block 1145900000, 13 September 2026), then compared the two files with [`compare_l4.py`](./compare_l4.py):

```text
coins: 1282 vs 1282, only in one file: 0
orders: 492491, sides with a different sequence: 0, field differences: 0
```

Every coin name, every order, its place in the book, and every field match. This includes the 7,554 child TP/SL orders of 5,620 parents.

For snapshots that the current `hl-node` cannot read, there is no reference export to compare against. For those, the script's output can be checked against the totals that the snapshot stores for each price level (order count and total size). On the 1 September 2026 snapshot (block 1131000000), all 339,922 levels match their stored totals.

To check your own snapshot against `hl-node`:

```bash
hl-node --chain Mainnet compute-l4-snapshots <height>.rmp reference.json
python abci_to_l4.py <height>.rmp ours.json
python compare_l4.py ours.json reference.json
```

## Limits

- The raw key names are internal to Hyperliquid and are not documented. A future upgrade can rename them. If the script fails on a new snapshot, print the keys of one book and update the paths.
- Untriggered stop and take-profit orders are not on the book. The output includes them only as `children` of a resting parent order, which is what `hl-node` does too.

## Get the data

Dwellir keeps a historical archive of Hyperliquid node data, including `periodic_abci_states`, order statuses, raw book diffs and fills. See [dwellir.com](https://www.dwellir.com) for access.
