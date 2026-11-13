# Ethereum nonce allocator

Read account nonces through Dwellir and reconcile them with saved reservations. The helper never signs or submits a transaction.

Use Node.js 22 or later. No packages are required.

```bash
cd examples/ethereum-nonce-allocator
node test-mock.mjs
node test-live.mjs
node handover.mjs
```

`test-mock.mjs` checks invalid RPC replies, pool gaps, and receipt checkpoints offline.
`test-live.mjs` replays recorded Dwellir counts against synthetic reservations. Its default run makes no network requests.
`handover.mjs` shows the first reconciliation after a completed custody handover at nonce 42.

## Read Dwellir counts

Get a key from the [Dwellir dashboard](https://dashboard.dwellir.com/). Set it in your shell without committing it.

```bash
export DWELLIR_API_KEY='your-dwellir-api-key'
export SENDER='0x7d0ebbe6f5308b9ef4e6108247cf793bab98ffcd'
node read-nonces.mjs
```

The runner checks `eth_chainId` for Ethereum mainnet, then reads `latest` and `pending`.
It uses `https://api-ethereum-mainnet.n.dwellir.com/${DWELLIR_API_KEY}`.
Errors omit authenticated URLs.

To check both Dwellir mainnet hosts, run:

```bash
node test-live.mjs --live
```

This sends six sequential, read-only calls across the default and Erigon hosts.
Calls have timeouts and an 800 ms pause before each request. No transaction is sent.
Live counts can change. Recorded counts in `dwellir-counts.json` are observations from 13 November 2026, not current pool guarantees.
The replay uses synthetic reservations and a hypothetical consecutive-pool assumption. It does not verify either host's pool rules.

## Integrate the helper

`readNonces(url, sender)` validates JSON-RPC envelopes, hexadecimal quantities, and count ordering.
The two reads are separate. Retry an inconsistent pair, and investigate count decreases before allocating.

`reconcile(records, view, baseline, poolSemantics, settledNext)` returns an action:

| Action | Required response |
| --- | --- |
| `ok` | Reserve `next` under the allocator lock. Persist the reservation before signing. |
| `repair` | Rebroadcast saved bytes or replace the lowest `notCounted` nonce. Reconcile again before allocating. |
| `stop` | Resolve missing settlement evidence, unexplained counts, or missing records before allocating. |

Keep consecutive reservations under one lock for each sender and chain, starting at `baseline`.
Store nonces as `BigInt`. Retain consumed reservations and every signed hash.
Persist signed bytes and their hash before submission.

Use the default `unknown` pool mode for hosted endpoints.
It permits one outstanding reservation per sender and requires a durable `settledNext` checkpoint.
The checkpoint is the next nonce after consecutive settled records. Never copy a live count into it.

Before initialization, take exclusive custody of the key, including EIP-7702 authorization signing.
For a new, unused key, set `baseline` and `settledNext` to `0n`.
For an existing key, stop previous signers and inventory every signed transaction and authorization.
Wait for that activity to settle before setting both values to the finalized account nonce.
Use a new key when the inventory is incomplete. Do not sign new authorizations during allocator custody.

Advance the checkpoint only through consecutive records with canonical finalized receipts.
Match each receipt's block hash to the canonical block at its height.
Require that block to be at or below the finalized head. A reverted transaction still consumes its nonce.
A null receipt never clears a reservation. Reopen a record if a reorganization removes its transaction.

Resume only when no reservation remains open and `latest`, `pending`, and `settledNext` agree.
Unknown mode cannot pipeline withdrawals. Each sender waits for settlement before starting another transaction.
Equal counts alone do not prove an empty pool. Exclusive custody and complete records establish what you signed.

Use `verified-consecutive` only with audited implementation and routing evidence for every backend, including failover.
The cited Geth revision in the [article](https://www.dwellir.com/blog/eth-gettransactioncount-production) provides one implementation reference.
A public probe or `web3_clientVersion` string cannot verify that condition.

The helper does not implement storage, locks, signing, submission, custody checks, or receipt polling.
Your application must implement those procedures. The fixtures model their inputs and reconciliation outcomes.
