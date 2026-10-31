// hip3-markets shows how to work with a HIP-3 builder-deployed perp DEX,
// such as TradeXYZ ("xyz"), through Dwellir:
//
//  1. List the HIP-3 DEXes (Info perpDexs).
//  2. Read the markets on one DEX (Info meta with "dex").
//  3. Read each wallet's positions and open orders on that DEX
//     (Info clearinghouseState and openOrders with "dex").
//  4. Stream best bid/offer for those markets (gRPC StreamBbo).
//  5. Stream the wallets' fills on that DEX only (gRPC StreamAllFills
//     with "users" and "dexes").
//
// HIP-3 coin names carry the DEX as a prefix, for example "xyz:SILVER".
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"sync"
	"time"

	"github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/dwellir"
	pb "github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/hlpb"
)

type perpDex struct {
	Name     string `json:"name"`
	FullName string `json:"fullName"`
	Deployer string `json:"deployer"`
}

type meta struct {
	Universe []struct {
		Name        string `json:"name"`
		SzDecimals  int    `json:"szDecimals"`
		MaxLeverage int    `json:"maxLeverage"`
		IsDelisted  bool   `json:"isDelisted"`
	} `json:"universe"`
}

type clearinghouseState struct {
	MarginSummary struct {
		AccountValue string `json:"accountValue"`
	} `json:"marginSummary"`
	Withdrawable   string `json:"withdrawable"`
	AssetPositions []struct {
		Position struct {
			Coin          string `json:"coin"`
			Szi           string `json:"szi"`
			EntryPx       string `json:"entryPx"`
			PositionValue string `json:"positionValue"`
			UnrealizedPnl string `json:"unrealizedPnl"`
		} `json:"position"`
	} `json:"assetPositions"`
}

type openOrder struct {
	Coin    string `json:"coin"`
	Side    string `json:"side"`
	LimitPx string `json:"limitPx"`
	Sz      string `json:"sz"`
	Oid     int64  `json:"oid"`
}

func main() {
	walletsFlag := flag.String("wallets", "", "comma-separated wallet addresses (default: WALLETS from .env)")
	dexFlag := flag.String("dex", "xyz", "HIP-3 DEX name, as listed by perpDexs")
	streamFor := flag.Duration("stream", 30*time.Second, "how long to stream BBO and fills; 0 = skip streaming")
	flag.Parse()

	cfg, err := dwellir.LoadConfig(*walletsFlag)
	if err != nil {
		log.Fatal(err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	dex := *dexFlag

	// 1. HIP-3 DEXes. The first entry is null: it stands for the default DEX.
	var dexes []*perpDex
	must(dwellir.PostInfo(ctx, cfg, cfg.InfoURL, map[string]any{"type": "perpDexs"}, &dexes))
	fmt.Println("HIP-3 perp DEXes:")
	found := false
	for _, d := range dexes {
		if d == nil {
			continue
		}
		fmt.Printf("  %-8s %-24s deployer %s\n", d.Name, d.FullName, d.Deployer)
		found = found || d.Name == dex
	}
	if !found {
		log.Fatalf("DEX %q not found", dex)
	}

	// 2. Markets on the DEX.
	var m meta
	must(dwellir.PostInfo(ctx, cfg, cfg.InfoURL, map[string]any{"type": "meta", "dex": dex}, &m))
	var live []string
	for _, a := range m.Universe {
		if !a.IsDelisted {
			live = append(live, a.Name)
		}
	}
	fmt.Printf("\n%s: %d markets, %d live, e.g. %s\n", dex, len(m.Universe), len(live), strings.Join(live[:min(8, len(live))], ", "))

	// 3. Positions and open orders per wallet on the DEX.
	watch := map[string]bool{}
	for _, w := range cfg.Wallets {
		var st clearinghouseState
		must(dwellir.PostInfo(ctx, cfg, cfg.InfoURL,
			map[string]any{"type": "clearinghouseState", "user": w, "dex": dex}, &st))
		var orders []openOrder
		must(dwellir.PostInfo(ctx, cfg, cfg.InfoURL,
			map[string]any{"type": "openOrders", "user": w, "dex": dex}, &orders))

		fmt.Printf("\n%s on %s: account value %s, withdrawable %s, %d positions, %d open orders\n",
			w, dex, st.MarginSummary.AccountValue, st.Withdrawable, len(st.AssetPositions), len(orders))
		for _, ap := range st.AssetPositions {
			p := ap.Position
			fmt.Printf("  %-16s size %-12s entry %-10s value %-12s uPnL %s\n",
				p.Coin, p.Szi, p.EntryPx, p.PositionValue, p.UnrealizedPnl)
			watch[p.Coin] = true
		}
		for _, o := range orders[:min(5, len(orders))] {
			fmt.Printf("  order %-16s %s %s @ %s (oid %d)\n", o.Coin, o.Side, o.Sz, o.LimitPx, o.Oid)
		}
	}

	if *streamFor == 0 {
		return
	}

	// StreamBbo takes 1-20 coins. Use the wallets' positions, or the first
	// live markets when the wallets hold nothing on this DEX.
	var coins []string
	for c := range watch {
		coins = append(coins, c)
	}
	if len(coins) == 0 {
		coins = live[:min(3, len(live))]
	}
	coins = coins[:min(20, len(coins))]

	conn, err := dwellir.DialGRPC(cfg)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()
	market := pb.NewMarketStreamingClient(conn)

	sctx, cancel := context.WithTimeout(dwellir.WithAPIKey(ctx, cfg), *streamFor)
	defer cancel()
	fmt.Printf("\nstreaming BBO for %s and %s fills for %d wallet(s) for %v\n",
		strings.Join(coins, ", "), dex, len(cfg.Wallets), *streamFor)

	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); streamBbo(sctx, market, coins) }()
	go func() { defer wg.Done(); streamFills(sctx, market, cfg.Wallets, dex) }()
	wg.Wait()
}

// 4. Best bid and offer. Prints a line only when the price changes.
func streamBbo(ctx context.Context, c pb.MarketStreamingClient, coins []string) {
	s, err := c.StreamBbo(ctx, &pb.BboRequest{Coins: coins})
	if err != nil {
		log.Printf("bbo: %v", err)
		return
	}
	last := map[string]string{}
	for {
		u, err := s.Recv()
		if err != nil {
			if ctx.Err() == nil {
				log.Printf("bbo: %v", err)
			}
			return
		}
		quote := fmt.Sprintf("%s / %s", u.GetBid().GetPx(), u.GetAsk().GetPx())
		if last[u.Coin] == quote {
			continue
		}
		last[u.Coin] = quote
		fmt.Printf("bbo   %s %-16s bid %-10s ask %s\n", ts(u.Time), u.Coin, u.GetBid().GetPx(), u.GetAsk().GetPx())
	}
}

// 5. The wallets' fills on one DEX only.
func streamFills(ctx context.Context, c pb.MarketStreamingClient, wallets []string, dex string) {
	s, err := c.StreamAllFills(ctx, &pb.AllFillsRequest{Users: wallets, Dexes: []string{dex}})
	if err != nil {
		log.Printf("fills: %v", err)
		return
	}
	var next uint64 = 1
	for {
		u, err := s.Recv()
		if err != nil {
			if ctx.Err() == nil {
				log.Printf("fills: %v", err)
			}
			return
		}
		// The sequence has no gaps; a gap means lost frames, so resubscribe.
		if u.Sequence != next {
			log.Printf("fills: sequence gap (%d, expected %d)", u.Sequence, next)
		}
		next = u.Sequence + 1
		for _, f := range u.Fills {
			fmt.Printf("fill  %s %s %-16s %s %s @ %s %s pnl %s fee %s\n",
				ts(f.Time), f.User, f.Coin, f.Side, f.Sz, f.Px, f.Dir, f.ClosedPnl, f.Fee)
		}
	}
}

func ts(ms int64) string { return time.UnixMilli(ms).UTC().Format("15:04:05.000") }

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
