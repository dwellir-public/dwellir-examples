# RPC provider audit

Test Ethereum RPC endpoints from the machine that sends your application's requests. Compare required reads before comparing latency or cost.

The tool uses Node.js 22.15 or newer, with no dependencies. It sends read-only requests and subscribes to `newHeads`. It never signs or sends transactions.

## Start in five minutes

1. Clone the repository and copy the configuration.

   ```bash
   git clone https://github.com/dwellir-public/dwellir-examples.git
   cd dwellir-examples/examples/rpc-provider-audit
   cp config.example.json config.json
   ```

2. Set credentials in your shell. These prompts keep values out of shell history.

   ```bash
   read -rsp 'Dwellir API key: ' DWELLIR_API_KEY
   export DWELLIR_API_KEY
   read -rsp 'Alchemy API key: ' ALCHEMY_API_KEY
   export ALCHEMY_API_KEY
   ```

   Use the actual plans you are evaluating. Get a Dwellir key at [the dashboard](https://dashboard.dwellir.com/).
   Replace either endpoint in `config.json` with another provider's URL template.
   `${ENV_NAME}` placeholders read environment variables. The tool never saves expanded URLs or keys.
   Remove `ws` when you have no WebSocket endpoint. That check becomes `not tested`.
   Change or remove `priceId` when you change providers or plans.

3. Set `monthlyCalls` to your expected monthly HTTP calls, by method.

   ```json
   "monthlyCalls": {
     "eth_blockNumber": 2000000,
     "eth_call": 8000000
   }
   ```

   Count each batch member. Include billable retry attempts and the extra queries needed when backfills split large log ranges.
   For Dwellir, exclude unbilled HTTP 429 responses from this cost input.
   Streaming messages need separate pricing. Do not add them to the HTTP call mix.

4. Run from your application server region, CI runner or development machine.

   ```bash
   node audit.mjs
   ```

   Read `report.md` and retain `report.json` for comparison. Both omit endpoint URLs and keys.
   The default two-endpoint configuration takes a few minutes, including a 60-second observation window.
   No package installation is needed.

5. Run the offline tests.

   ```bash
   npm test
   ```

   Tests start local HTTP and WebSocket fixtures. They need no provider account or internet access.

Optional paths and offline cost calculation:

```bash
node audit.mjs config.json prices.json region-a
node audit.mjs --cost-only config.json prices.json costs
```

The cost command makes no network calls. It reads the monthly mix without requiring endpoint credentials.

## Choose the reads that matter

The supplied preset targets Ethereum mainnet. Do not reuse its contract or pinned block on another chain.

| Configuration | What to change | Decision it supports |
| --- | --- | --- |
| `probe.chainId`, `block`, `blockHash` | A trusted block hash and its exact height | Reject a wrong chain or mismatched historical block |
| `archiveBlocks` | Your oldest required block and useful intermediate blocks | Check historical bodies, balances, contract state, receipts and logs separately |
| `account` | An account your application reads | Test old account state |
| `contract`, `callData` | A read-only call returning one 32-byte value | Test contract state and compare responses |
| `logEnd`, `logFilters` | Explicit block ranges, addresses and event topics | Find tested range or result boundaries |
| `settings` | Sampling window, rounds and response bounds | Repeat the same configuration from each deployment region |

The pinned hash comes from [Ethereum block 15,537,394](https://etherscan.io/block/15537394).
The contract preset reads USDC's `totalSupply()` with selector `0x18160ddd`.
Check your pinned reference before treating a mismatch as an endpoint defect.

Two filters exercise different constraints. The sparse factory filter increases block width without many events.
The dense USDC transfer filter increases result volume. The defaults stop at 501 and 500 blocks respectively.
Choose wider ranges only when your plan permits them. The maximum configurable range is 100,000 blocks.

Each filter stops an endpoint after its first error, invalid payload, disagreement or unverified comparison.
A stop is a tested boundary, not an exact permanent provider limit.
An empty log array can be valid. Use ranges with known events to detect missing history.

## Read the report

- `ok` means the response passed the stated shape or pinned-value check.
- `match` means a strict majority of valid responses agrees, with at least two matching responses.
- `no quorum` means valid responses disagree without a strict majority.
- `disagrees` identifies a response outside that majority.
- `unverified` means only one usable response remains.
- `null`, `invalid result`, HTTP errors and RPC errors stay separate.

Agreement does not prove correctness or provider independence. A provider can route multiple hostnames to the same backend.
The archive contract call has an agreement check. Balance, receipt and body checks validate shape and identity, without claiming independent value verification.

Log fingerprints cover block and transaction identities, address, topics, data and removal status.
The validator rejects duplicates, out-of-range results and logs outside the configured filter.
Fingerprint comparisons ignore result ordering. They can expose disagreement, including silent truncation, without identifying the correct endpoint.

Freshness checks fetch the body at each reported head height. The body must match the requested height and have a valid hash.
The report records unavailable bodies, backward heads and conflicting hashes at the same height.
Lag is relative to the highest validated endpoint in each polling round. It does not identify the true chain tip or delay in seconds.
Polling order rotates. Requests remain sequential, so a block arriving during a round can create a height difference.

Latency rows separate new connections from keep-alive requests. The `reused` count records actual socket reuse.
Percentiles include validated successes only. Compare failure counts and the same method before comparing percentiles.
The default five warm samples are a smoke check. Increase `latencyRounds` for a latency evaluation, up to 100.
Pinned reads repeat the same parameters, so caches can affect results. These rows do not measure maximum throughput.

WebSocket checks compare stream heights with the same endpoint's HTTP heads.
The range includes the last HTTP height after a grace period. Missing configuration or a failed subscription never produces zero gaps.
A stream range starts at its first notification. With no notifications, it starts at the first HTTP sample after subscription acknowledgement.
Leading heights before the first notification are outside that range. The JSON report records the range.
Repeated hashes, changed hashes at the same height, disconnects and HTTP hash conflicts have separate counts.
A changed hash can reflect a reorganization. Investigate it before calling it bad data.
The audit records disconnects without reconnecting. Your application still needs reconnection and HTTP backfill.

## Price your workload

`prices.json` separates commercial data from the probes. Every plan has a primary source URL and a `checkedAt` date.
Select the actual plan with each endpoint's `priceId` in `config.json`.
The default compares Dwellir Developer with Alchemy Pay as You Go.
Numeric entries also cover Dwellir Growth and Scale, QuickNode Build, Accelerate and Scale, and Chainstack Growth, Pro and Business.
Rates and method weights were checked on 13 November 2026.

For the sample 2 million `eth_blockNumber` calls and 8 million latest-block `eth_call` requests:

| Price ID | Monthly units | Subscription | Overage | Monthly estimate |
| --- | --- | --- | --- | --- |
| `dwellir-developer` | 10M responses | $49.00 | $0.00 | $49.00 |
| `alchemy-payg` | 228M CU | $0.00 | $118.56 | $118.56 |
| `quicknode-build` | 200M API credits | $49.00 | $74.40 | $123.40 |
| `chainstack-growth-full` | 10M RU | $49.00 | $0.00 | $49.00 |

CU means compute units. RU means request units.
These estimates include the full monthly subscription, without allocating it across the allowance.
Dwellir includes 25M responses, with $5/M overage on Developer.
Alchemy charges $0.52/M CU for all PAYG usage, without the separate Free plan's allowance.
Its method weights are 10 CU for `eth_blockNumber` and 26 CU for `eth_call`.
QuickNode Build includes 80M credits, then charges $0.62/M. Both methods cost 20 credits each on Ethereum.
Chainstack Growth includes 20M RU, then charges $15/M. Regional and Global full-node requests cost 1 RU each.

Choose a Chainstack `-archive` entry for a workload billed entirely as archive requests, at 2 RU each.
For mixed full and archive calls, calculate their combined RU before applying one plan allowance and subscription.
Do not add separate full and archive estimates, which would count the subscription twice.
Every entry states its service scope. Match that scope to your actual requests.
Price sources and conflicting official rates remain in `prices.json`; the provider's pricing page takes precedence.

For a response plan:

```text
units = sum(monthlyCalls)
overage = max(0, units - includedUnits) / 1,000,000 * overageUsdPerMillion
estimate = monthlyUsd + roundToCents(overage)
```

At 30 million responses, Developer costs $49 + 5 × $5 = $74.00.

To add a compute-unit plan, set `model` to `compute-units` and provide all of these fields:

- `sourceUrl` and `checkedAt` for the price.
- `monthlyUsd`, `includedUnits` and `overageUsdPerMillion` in that provider's billing units.
- `weights` mapping each method in your monthly mix to its published unit weight.
- `weightsSourceUrl` for those weights.
- `scope` stating the plan, chain, products and excluded charges.

The calculator multiplies each method's call count by its weight, then applies the included allowance and overage rate.
It never substitutes an average method weight. Missing rates or weights return `unpriced`.
Plans with tiered pricing need a different model; do not flatten their tiers into a guessed rate.

Prices older than 30 days carry a refresh warning. Future price dates do not produce a quote.
The calculation excludes taxes, premium support, extra throughput capacity and unlisted products.
Check rate limits, archive access and log ranges on the actual plan. A low calculated cost does not establish suitability.

Dwellir does not bill HTTP 429 responses. Other providers' rejected-request charges need a documented answer.
The tool does not trigger rate limits or infer billing from error responses.

## Bounds and troubleshooting

Requests start at least 500 ms apart per endpoint. There are no automatic HTTP retries.
Each request has a total deadline and a response-size cap. Oversized responses fail without retaining their contents.
A single log call can consume substantial server work despite the request spacing.

A missing variable, invalid URL, invalid configuration or write failure exits with code 1.
A completed audit exits with code 0 even when endpoints fail checks. Read the report's verdicts before using it in automation.
Endpoints that fail chain or pinned-block checks receive no later capability probes.
HTTPS and WSS are required, except loopback HTTP and WS for local fixtures.
Valid JSON-RPC error codes and messages remain beside non-2xx HTTP failure verdicts.
HTTP failures never supply successful values or agreement fingerprints.
Provider error messages are redacted and shortened. Raw response bodies and expanded URLs never enter output files.
Report timestamps use UTC, with no fixed city or timezone.

Keep `config.json`, reports and credentials out of source control. The folder's ignore rules cover local configuration and default reports.
Use a new output prefix for each region or evaluation. Report paths must have an existing parent directory.
