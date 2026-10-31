// builder-staking reads builder-fee approvals and staking state for a list
// of wallets from the Dwellir Info endpoint:
//
//   - maxBuilderFee: the highest fee each wallet has approved for a builder.
//   - delegatorSummary and delegations: staked HYPE per wallet and validator.
//   - delegatorRewards and delegatorHistory: tried too. If the endpoint does
//     not serve them, the program says so and continues.
//
// Staking transfers and reward claims also arrive as ledger events in the
// wallet-events example (cStakingTransfer, rewardsClaim, Delegation).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/dwellir"
)

type delegatorSummary struct {
	Delegated              string `json:"delegated"`
	Undelegated            string `json:"undelegated"`
	TotalPendingWithdrawal string `json:"totalPendingWithdrawal"`
	NPendingWithdrawals    int    `json:"nPendingWithdrawals"`
}

type delegation struct {
	Validator            string `json:"validator"`
	Amount               string `json:"amount"`
	LockedUntilTimestamp int64  `json:"lockedUntilTimestamp"`
}

func main() {
	walletsFlag := flag.String("wallets", "", "comma-separated wallet addresses (default: WALLETS from .env)")
	buildersFlag := flag.String("builders", "", "comma-separated builder addresses to check approvals for (default: BUILDERS from .env)")
	flag.Parse()

	cfg, err := dwellir.LoadConfig(*walletsFlag)
	if err != nil {
		log.Fatal(err)
	}
	builders := dwellir.ParseWallets(*buildersFlag)
	if len(builders) == 0 {
		builders = dwellir.ParseWallets(os.Getenv("BUILDERS"))
	}
	ctx := context.Background()
	info := func(req map[string]any, out any) error {
		return dwellir.PostInfo(ctx, cfg, cfg.InfoURL, req, out)
	}

	for _, w := range cfg.Wallets {
		fmt.Printf("\n== %s\n", w)

		// Builder-fee approvals. The answer is in tenths of a basis point:
		// 10 = 1 bp = 0.01%. 0 means no approval.
		if len(builders) == 0 {
			fmt.Println("builder fees: no builders given (-builders or BUILDERS)")
		}
		for _, b := range builders {
			var fee int
			if err := info(map[string]any{"type": "maxBuilderFee", "user": w, "builder": b}, &fee); err != nil {
				report("maxBuilderFee", err)
				continue
			}
			fmt.Printf("builder fee: %s approved up to %d (%.3f%%)\n", b, fee, float64(fee)/1000)
		}

		var sum delegatorSummary
		if err := info(map[string]any{"type": "delegatorSummary", "user": w}, &sum); err != nil {
			report("delegatorSummary", err)
		} else {
			fmt.Printf("staking: delegated %s HYPE, undelegated %s, pending withdrawal %s (%d)\n",
				sum.Delegated, sum.Undelegated, sum.TotalPendingWithdrawal, sum.NPendingWithdrawals)
		}

		var dels []delegation
		if err := info(map[string]any{"type": "delegations", "user": w}, &dels); err != nil {
			report("delegations", err)
		}
		for _, d := range dels {
			fmt.Printf("  validator %s: %s HYPE\n", d.Validator, d.Amount)
		}

		// Reward and history requests. Print the raw answer if served.
		for _, typ := range []string{"delegatorRewards", "delegatorHistory"} {
			var raw json.RawMessage
			if err := info(map[string]any{"type": typ, "user": w}, &raw); err != nil {
				report(typ, err)
				continue
			}
			fmt.Printf("%s: %.300s\n", typ, raw)
		}
	}
}

func report(typ string, err error) {
	if errors.Is(err, dwellir.ErrNotServed) {
		fmt.Printf("%s: not served by this endpoint (403)\n", typ)
		return
	}
	fmt.Printf("%s: error: %v\n", typ, err)
}
