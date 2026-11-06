# Hyperliquid vaults and leaderboard

Three small Python programs that read Hyperliquid vault and leaderboard data through the API, so you can rank vaults, inspect one before you deposit, rank traders, and see what the top traders hold right now.

| Program | What it does | Data source |
|---------|--------------|-------------|
| `vaults.py top` | Ranks every open vault by TVL, APR or window PnL | `stats-data` vaults feed |
| `vaults.py show` | One vault: leader, fees, returns, largest followers, child vaults, open positions | Public `vaultDetails`, Dwellir `clearinghouseState` |
| `vaults.py leader` | The vaults an address leads | Dwellir `leadingVaults` |
| `leaderboard.py top` | Ranks traders by PnL, ROI or volume over a day, week, month or all time, optionally only vault leaders, optionally with live positions | `stats-data` leaderboard feed, Dwellir `batchClearinghouseStates` |
| `leaderboard.py addresses` | Writes every ranked address to a file | `stats-data` leaderboard feed |
| `my_vaults.py` | A wallet's vault deposits with names, APR and lockups | Dwellir `userVaultEquities` |

- Chain: Hyperliquid mainnet (HyperCore)
- Language: Python 3.10 or newer
- Difficulty: Beginner
- Dependencies: `httpx`
- Needs: a Dwellir API key for the Info queries (`vaults.py show`, `--profile`, `my_vaults.py`). The feed-only commands run without one. No gRPC add-on.

Companion guide: [Hyperliquid vaults and leaderboard data via API](https://www.dwellir.com/guides/hyperliquid-vaults-leaderboard).

## Quick start

```bash
git clone https://github.com/dwellir-public/dwellir-examples
cd dwellir-examples/examples/hyperliquid-vaults-leaderboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DWELLIR_API_KEY=your-api-key

python vaults.py top --by apr --min-tvl 250000
python vaults.py show 0x07fd993f0fa3a185f7207adccd29f7a87404689d
python leaderboard.py top --window week --by pnl --n 10 --profile
python leaderboard.py top --window month --by pnl --vault-leaders --min-volume 1000000
python my_vaults.py 0xYourWallet
```

## Where the data comes from

Hyperliquid's Info endpoint has no "list all vaults" or "leaderboard" query that returns data. Checked on 5 November 2026:

- `vaultSummaries` returns `[]` on both the public endpoint and Dwellir.
- `leadingVaults` needs a `user` and returns the vaults that address leads. Without `user` it returns HTTP 422.
- `vaultDetails` and `portfolio` are not on the Dwellir proxy (HTTP 403 `type not allowed`), so `hl_api.py` sends those two to `https://api.hyperliquid.xyz/info`.

The list of all vaults and the trader leaderboard come from the two JSON feeds the Hyperliquid app itself loads:

- `https://stats-data.hyperliquid.xyz/Mainnet/vaults`: every vault ever created (9,478 on 5 November 2026, 3,062 open), about 14 MB, with name, leader, TVL, APR and short cumulative PnL series per window.
- `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`: every ranked trader (48,192 rows), about 40 MB, with account value and PnL, ROI and volume for `day`, `week`, `month` and `allTime`.

Both feeds are undocumented, unauthenticated and large, so `hl_api.feed()` caches them in `.cache/` for ten minutes. Everything per wallet (`clearinghouseState`, `batchClearinghouseStates`, `userVaultEquities`, `leadingVaults`) goes through the Dwellir Info proxy with your API key.

## Notes

- `batchClearinghouseStates` is a Dwellir-only Info type. It is billed per wallet in the batch, so profiling the top 20 traders costs 20 responses in one round trip.
- ROI in the leaderboard is PnL over starting equity for the window. Accounts that were nearly empty at the start of the window show enormous ROI on small PnL. Use `--min-value` and `--min-volume` when you rank by ROI.
- HLP is a parent vault. Its capital sits in child vaults (`HLP Strategy A`, `HLP Strategy X`, `HLP Liquidator 2`, ...), which `vaults.py show` lists, and the parent's own `clearinghouseState` holds almost no positions.
- `leadingVaults` returns vaults the address leads, not a ranked list of top vaults, whatever the name suggests.
