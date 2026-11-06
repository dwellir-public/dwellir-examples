"""Show a wallet's vault deposits with names, lockups and vault performance.

    python my_vaults.py 0x677d831aef5328190852e24f13c46cac05f984e7
"""

import sys
from datetime import datetime, timezone

from hl_api import info, pct, usd
from vaults import load_vaults


def main(address: str) -> None:
    # userVaultEquities runs through Dwellir. It returns address, equity and
    # lockup only, so we join the vaults feed for names and APR.
    equities = info({"type": "userVaultEquities", "user": address})
    if not equities:
        print(f"{address} has no vault deposits")
        return
    vaults = {v["address"]: v for v in load_vaults(open_only=False)}
    now = datetime.now(timezone.utc)

    total = 0.0
    print(f"{'Vault':<34} {'Equity':>12} {'APR':>9} {'TVL':>14}  Lockup")
    for e in equities:
        v = vaults.get(e["vaultAddress"])
        name = v["name"] if v else e["vaultAddress"]
        apr = pct(v["apr"]) if v else "n/a"
        tvl = usd(v["tvl"]) if v else "n/a"
        unlock = datetime.fromtimestamp(e["lockedUntilTimestamp"] / 1000, timezone.utc)
        lock = "unlocked" if unlock <= now else f"locked until {unlock:%Y-%m-%d %H:%M} UTC"
        total += float(e["equity"])
        print(f"{name[:34]:<34} {usd(e['equity']):>12} {apr:>9} {tvl:>14}  {lock}")
    print(f"{'total':<34} {usd(total):>12}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
