# Hyperliquid wallet data in Go

Four Go programs that get data for a list of your own Hyperliquid wallets through Dwellir:

| Program | What it does | Dwellir API |
|---------|--------------|-------------|
| [`wallet-events`](./cmd/wallet-events) | Streams funding payments and ledger updates (deposits, withdrawals, transfers, vault and staking moves), live or replayed | gRPC `StreamMiscEvents` |
| [`fills-history`](./cmd/fills-history) | Downloads every fill for a time range and prints a per-coin summary | Index `userFillsByTime` |
| [`hip3-markets`](./cmd/hip3-markets) | Lists HIP-3 DEXes and markets, reads positions and orders on one DEX (default `xyz`, TradeXYZ), streams its prices and your fills | Info + gRPC `StreamBbo`, `StreamAllFills` |
| [`builder-staking`](./cmd/builder-staking) | Reads builder-fee approvals and staked HYPE per validator | Info `maxBuilderFee`, `delegatorSummary`, `delegations` |

- Chain: Hyperliquid mainnet
- Language: Go 1.23 or newer
- Difficulty: Intermediate
- Dependencies: `google.golang.org/grpc`, `google.golang.org/protobuf`. The generated gRPC code is included, so you do not need `protoc`.

## Quick start

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/hyperliquid-wallet-data-go

cp .env.example .env
# Set DWELLIR_API_KEY and WALLETS in .env

go run ./cmd/wallet-events -since 2h
go run ./cmd/fills-history -from 72h -out fills.jsonl
go run ./cmd/hip3-markets -dex xyz -stream 30s
go run ./cmd/builder-staking -builders 0xYourBuilderAddress
```

Each program reads `DWELLIR_API_KEY` and `WALLETS` from `.env` or from the environment. Use `-wallets 0xabc...,0xdef...` to use other wallets for one run. Run a program with `-h` to see all its flags.

The sample output in this README comes from real runs. The wallet addresses in it are replaced with placeholders.

## 1. Funding and ledger stream: `wallet-events`

`StreamMiscEvents` carries the non-trade events of each block. The program asks the server for events that touch your wallets only (filter field `users`) and prints one line per event:

```text
2026-10-30T04:00:00.041094828  Funding        user=0xcccc...0004 coin=HYPE amount=25.862038 size=-2461.22 rate=0.0001135857
2026-10-30T04:00:00.041094828  Funding        user=0xaaaa...0001 coin=xyz:CL amount=-0.037895 size=187.685 rate=0.0000019563
2026-10-30T06:01:41.705940565  LedgerUpdate   spotTransfer         users=0xbbbb...0003,0xaaaa...0001 {"amount":"474.0","destination":"0xaaaa...0001",...} tx=0x...
```

These are the event kinds:

| Kind | Content |
|------|---------|
| `Funding` | Hourly funding, one delta per position, default DEX and HIP-3 DEXes |
| `LedgerUpdate` | `deposit`, `withdraw`, `send`, `spotTransfer`, `internalTransfer`, `subAccountTransfer`, `accountClassTransfer`, `vaultDeposit`, `vaultWithdraw`, `vaultLeaderCommission`, `cStakingTransfer`, `rewardsClaim`, `borrowLend` and others |
| `Delegation`, `CDeposit`, `CWithdrawal` | Staking delegations and staking-balance moves |
| `CreateSubAccount` | New sub-accounts |

Things to know:

- **One Funding event lists every open position on Hyperliquid.** The `users` filter selects the event, but it does not remove other users' deltas from it. One event is tens of MB with about 300,000 deltas. The program filters the deltas to your wallets on the client, and it sets the gRPC receive limit to 256 MB. With the 4 MB default, the stream fails on the first funding hour.
- **Read and parse on different goroutines.** If you parse large records inside the receive loop, the client can fall behind and the server ends the stream. The program receives on one goroutine and parses on another.
- **Resume from the last cursor.** After `UNAVAILABLE`, `DATA_LOSS`, `DEADLINE_EXCEEDED` or `RESOURCE_EXHAUSTED`, the program connects again from the last block it handled. Start positions are inclusive, so it skips that block when it comes again. It also asks for progress frames. These move the cursor forward while your wallets are quiet, so a reconnect does not scan the same blocks again.
- **Replay window.** `-since` replays history first. On 2026-10-30 replay reached back about 2 days. A start of 60 hours back returned `NOT_FOUND: Data for provided timestamp is pruned`. For older funding and ledger history, keep your own copy of this stream.

## 2. Fill history: `fills-history`

The Dwellir Index serves `userFillsByTime` for a wallet over any time range since 2025-07-27. It returns at most 2,000 fills per request, oldest first. The program pages forward from the time of the last fill. Fills in that same millisecond come back on the next page, so it removes repeats by `(tid, oid)`.

```text
0xaaaa...0002  46423 fills from 2026-10-30T03:16:04Z to 2026-10-30T06:16:04Z
  coin                fills         notional     closed_pnl         fees
  xyz:SKHX             6985      10898258.00      -12391.90     266.8916
  xyz:SP500            1635       7844667.43         -91.29     132.0915
  ...
```

`-out fills.jsonl` writes each fill as `{"wallet": ..., "fill": {...}}` in the same format as the Hyperliquid Info API.

Things to know:

- **The Index bills per fill returned.** A market-making wallet can have tens of thousands of fills per hour. Start with a short `-from`.
- **The Index is complete.** On a 10-minute window for a busy wallet, the Index and the gRPC `StreamFills` feed returned the same 3,022 fills.
- For new fills as they happen, use gRPC `StreamUserFills` or `StreamAllFills` with `users` (see `hip3-markets`).

## 3. HIP-3 markets: `hip3-markets`

HIP-3 coins have the DEX name as a prefix, for example `xyz:SILVER`. The program does these steps:

1. `perpDexs` lists the HIP-3 DEXes.
2. `meta` with `"dex": "xyz"` lists the markets on that DEX.
3. `clearinghouseState` and `openOrders` with `"dex": "xyz"` give each wallet's account value, positions and open orders on that DEX.
4. gRPC `StreamBbo` streams best bid and offer for the coins the wallets hold (1 to 20 coins).
5. gRPC `StreamAllFills` with `users` and `dexes: ["xyz"]` streams the wallets' fills on that DEX only. `StreamUserFills` also accepts `dexes`.

```text
xyz: 141 markets, 120 live, e.g. xyz:XYZ100, xyz:TSLA, xyz:NVDA, xyz:GOLD, ...
0xaaaa...0002 on xyz: account value 67859036.15, withdrawable 44014873.29, 22 positions, 63 open orders
  xyz:GOLD         size -6329.2547   entry 4128.54    value 25253726.25 uPnL 876869.48
bbo   06:18:04.379 xyz:SILVER       bid 51.004     ask 51.005
fill  06:18:05.654 0xaaaa...0002 xyz:SILVER       A 196.06 @ 51.004 Open Short pnl 0.0 fee 0.287995
```

The `Funding` events in `wallet-events` include HIP-3 positions too.

## 4. Builder fees and staking: `builder-staking`

- `maxBuilderFee` gives the highest fee a wallet has approved for a builder. The unit is tenths of a basis point: `100` is 10 bp, or 0.1%. `0` means no approval.
- `delegatorSummary` and `delegations` give staked HYPE in total and per validator.
- The program also tries `delegatorRewards` and `delegatorHistory`. If the endpoint does not serve a request type, the program prints `not served by this endpoint (403)` and continues.

## What the Dwellir endpoints do not serve

Checked on 2026-10-30. These requests return an error on the Dwellir Info endpoint. The table gives the alternative where one exists.

| Request | Result | Alternative |
|---------|--------|-------------|
| `userFills`, `userFillsByTime` | 403 | Index `userFillsByTime` (example 2) |
| `userFunding`, `userNonFundingLedgerUpdates` | 403 | gRPC `StreamMiscEvents` (example 1), about 2 days of replay |
| `metaAndAssetCtxs` with a HIP-3 `dex` | 400, default DEX only | `StreamBbo` for prices. No HIP-3 mark, oracle or funding-rate snapshot. |
| `l2Book`, `allMids`, `perpDexLimits`, `perpDexStatus` | 403 | gRPC `StreamL2Book`, `StreamBbo` |
| `delegatorRewards`, `delegatorHistory`, `approvedBuilders`, `referral` | 403 | `rewardsClaim`, `cStakingTransfer` and `Delegation` events in example 1 |

gRPC `StreamActiveAssetCtx` serves default-DEX coins only.

## Regenerate the gRPC code

The generated code in `internal/hlpb` comes from [`proto/v3.proto`](./proto/v3.proto), a copy of <https://www.dwellir.com/docs/hyperliquid/grpc/v3.proto>. To regenerate it, install `protoc`, `protoc-gen-go` and `protoc-gen-go-grpc`, then run:

```bash
make proto
```

## Layout

```text
cmd/wallet-events     funding + ledger stream (gRPC)
cmd/fills-history     fill history (Index)
cmd/hip3-markets      HIP-3 DEX data (Info + gRPC)
cmd/builder-staking   builder fees + staking (Info)
internal/dwellir      config, gRPC connection, Info/Index client
internal/hlpb         generated gRPC code
proto/v3.proto        Dwellir Hyperliquid gRPC API definition
```
