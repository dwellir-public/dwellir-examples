// fills-history downloads the full fill history of a list of wallets for a
// time range from the Dwellir Hyperliquid Index (userFillsByTime), then
// prints a per-coin summary. Use -out to also save every fill as JSON lines.
//
// The Index answers with at most 2,000 fills per request, oldest first.
// The program pages forward by time until the range is complete.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"sort"
	"strconv"
	"time"

	"github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/dwellir"
)

const pageSize = 2000 // the most fills the Index returns per request

type fill struct {
	Coin      string `json:"coin"`
	Px        string `json:"px"`
	Sz        string `json:"sz"`
	Side      string `json:"side"`
	Time      int64  `json:"time"`
	Dir       string `json:"dir"`
	ClosedPnl string `json:"closedPnl"`
	Fee       string `json:"fee"`
	Tid       int64  `json:"tid"`
	Oid       int64  `json:"oid"`

	raw json.RawMessage
}

func (f *fill) UnmarshalJSON(b []byte) error {
	type plain fill
	if err := json.Unmarshal(b, (*plain)(f)); err != nil {
		return err
	}
	f.raw = append(json.RawMessage(nil), b...)
	return nil
}

func main() {
	walletsFlag := flag.String("wallets", "", "comma-separated wallet addresses (default: WALLETS from .env)")
	fromFlag := flag.String("from", "24h", "start: a duration back from now (72h) or a date (2026-10-01 or RFC3339)")
	toFlag := flag.String("to", "", "end: same formats as -from; empty = now")
	outFlag := flag.String("out", "", "also write every fill to this JSON-lines file")
	flag.Parse()

	cfg, err := dwellir.LoadConfig(*walletsFlag)
	if err != nil {
		log.Fatal(err)
	}
	now := time.Now()
	from, err := parseTime(*fromFlag, now)
	if err != nil {
		log.Fatalf("-from: %v", err)
	}
	to := now
	if *toFlag != "" {
		if to, err = parseTime(*toFlag, now); err != nil {
			log.Fatalf("-to: %v", err)
		}
	}

	var out *bufio.Writer
	if *outFlag != "" {
		f, err := os.Create(*outFlag)
		if err != nil {
			log.Fatal(err)
		}
		defer f.Close()
		out = bufio.NewWriter(f)
		defer out.Flush()
	}

	ctx := context.Background()
	for _, wallet := range cfg.Wallets {
		fills, err := fetchFills(ctx, cfg, wallet, from.UnixMilli(), to.UnixMilli())
		if err != nil {
			log.Fatalf("%s: %v", wallet, err)
		}
		fmt.Printf("\n%s  %d fills from %s to %s\n", wallet, len(fills),
			from.UTC().Format(time.RFC3339), to.UTC().Format(time.RFC3339))
		summarize(fills)

		for _, f := range fills {
			if out == nil {
				break
			}
			// Add the wallet so lines from several wallets stay apart.
			line := fmt.Sprintf(`{"wallet":%q,"fill":%s}`, wallet, f.raw)
			out.WriteString(line + "\n")
		}
	}
}

// fetchFills pages through userFillsByTime from startMs to endMs (inclusive).
func fetchFills(ctx context.Context, cfg dwellir.Config, wallet string, startMs, endMs int64) ([]fill, error) {
	var all []fill
	seen := map[[2]int64]bool{} // (tid, oid) pairs at the page boundary, to drop repeats

	for start := startMs; start <= endMs; {
		var page []fill
		req := map[string]any{
			"type":      "userFillsByTime",
			"user":      wallet,
			"startTime": start,
			"endTime":   endMs,
		}
		if err := dwellir.PostInfo(ctx, cfg, cfg.IndexURL, req, &page); err != nil {
			return nil, err
		}
		for _, f := range page {
			if !seen[[2]int64{f.Tid, f.Oid}] {
				all = append(all, f)
			}
		}
		log.Printf("%s: page from %d -> %d fills (total %d)", wallet, start, len(page), len(all))
		if len(page) < pageSize {
			break
		}

		// Next page starts at the time of the last fill. Fills that share
		// that millisecond come back again, so remember them. A trade ID is shared by both sides of a match, so key on (tid, oid).
		last := page[len(page)-1].Time
		seen = map[[2]int64]bool{}
		for _, f := range page {
			if f.Time == last {
				seen[[2]int64{f.Tid, f.Oid}] = true
			}
		}
		if last == start {
			// A full page inside one millisecond: step past it so the loop ends.
			log.Printf("warning: %d+ fills at %d ms; some fills in that millisecond may be missing", pageSize, last)
			last++
		}
		start = last
	}
	return all, nil
}

type coinStats struct {
	fills               int
	notional, pnl, fees float64
}

func summarize(fills []fill) {
	stats := map[string]*coinStats{}
	for _, f := range fills {
		s := stats[f.Coin]
		if s == nil {
			s = &coinStats{}
			stats[f.Coin] = s
		}
		s.fills++
		s.notional += num(f.Px) * num(f.Sz)
		s.pnl += num(f.ClosedPnl)
		s.fees += num(f.Fee)
	}
	coins := make([]string, 0, len(stats))
	for c := range stats {
		coins = append(coins, c)
	}
	sort.Slice(coins, func(i, j int) bool { return stats[coins[i]].notional > stats[coins[j]].notional })

	fmt.Printf("  %-16s %8s %16s %14s %12s\n", "coin", "fills", "notional", "closed_pnl", "fees")
	for _, c := range coins {
		s := stats[c]
		fmt.Printf("  %-16s %8d %16.2f %14.2f %12.4f\n", c, s.fills, s.notional, s.pnl, s.fees)
	}
}

func num(s string) float64 {
	v, _ := strconv.ParseFloat(s, 64)
	return v
}

func parseTime(s string, now time.Time) (time.Time, error) {
	if d, err := time.ParseDuration(s); err == nil {
		return now.Add(-d), nil
	}
	for _, layout := range []string{time.RFC3339, "2006-01-02T15:04", "2006-01-02"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("cannot parse %q", s)
}
