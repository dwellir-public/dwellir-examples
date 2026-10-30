// wallet-events streams funding payments and ledger updates (deposits,
// withdrawals, transfers, vault moves, staking transfers, ...) for a list of
// wallets from the Dwellir gRPC StreamMiscEvents feed.
//
// The server filters the feed to events that touch your wallets. One hourly
// Funding event lists every open position on Hyperliquid, so the program
// also filters the funding deltas to your wallets on the client side.
//
// On a disconnect it resumes from the last cursor it saw, so no events are
// lost or repeated.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/dwellir"
	pb "github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/hlpb"
)

// block is the JSON envelope inside Record.data.
type block struct {
	BlockNumber int64   `json:"block_number"`
	BlockTime   string  `json:"block_time"`
	Events      []event `json:"events"`
}

// event has exactly one key in Inner, the event kind, for example "Funding".
type event struct {
	Time  string                     `json:"time"`
	Hash  string                     `json:"hash"`
	Inner map[string]json.RawMessage `json:"inner"`
}

type funding struct {
	Deltas []struct {
		User          string `json:"user"`
		Coin          string `json:"coin"`
		FundingAmount string `json:"funding_amount"`
		Szi           string `json:"szi"`
		FundingRate   string `json:"funding_rate"`
	} `json:"deltas"`
}

type ledgerUpdate struct {
	Users []string       `json:"users"`
	Delta map[string]any `json:"delta"`
}

func main() {
	walletsFlag := flag.String("wallets", "", "comma-separated wallet addresses (default: WALLETS from .env)")
	since := flag.Duration("since", 0, "replay history first, e.g. 2h; 0 = live only")
	flag.Parse()

	cfg, err := dwellir.LoadConfig(*walletsFlag)
	if err != nil {
		log.Fatal(err)
	}
	conn, err := dwellir.DialGRPC(cfg)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()
	client := pb.NewHyperliquidL1GatewayClient(conn)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	ctx = dwellir.WithAPIKey(ctx, cfg)

	var start *pb.Position
	if *since > 0 {
		ts := time.Now().Add(-*since).UnixMilli()
		start = &pb.Position{Position: &pb.Position_Timestamp{Timestamp: ts}}
	}
	log.Printf("streaming misc events for %d wallet(s), since=%v", len(cfg.Wallets), *since)

	if err := run(ctx, client, cfg, start); err != nil && ctx.Err() == nil {
		log.Fatal(err)
	}
}

// run keeps a stream open and reconnects after retryable errors.
func run(ctx context.Context, client pb.HyperliquidL1GatewayClient, cfg dwellir.Config, start *pb.Position) error {
	wallets := cfg.WalletSet()
	var lastBlock int64 = -1 // newest block fully handled; resume after it
	backoff := time.Second

	for ctx.Err() == nil {
		pos := start
		if lastBlock >= 0 {
			// Positions are inclusive. The handler skips lastBlock if it comes again.
			pos = &pb.Position{Position: &pb.Position_BlockNumber{BlockNumber: lastBlock}}
		}
		err := stream(ctx, client, cfg, wallets, pos, &lastBlock)
		if ctx.Err() != nil {
			return nil
		}
		switch status.Code(err) {
		case codes.Unavailable, codes.DataLoss, codes.DeadlineExceeded, codes.ResourceExhausted:
			log.Printf("stream ended (%v), resuming from block %d in %v", err, lastBlock, backoff)
			select {
			case <-time.After(backoff):
			case <-ctx.Done():
				return nil
			}
			backoff = min(backoff*2, 30*time.Second)
		default:
			// NOT_FOUND means the start point is older than the replay window.
			return err
		}
	}
	return nil
}

func stream(ctx context.Context, client pb.HyperliquidL1GatewayClient, cfg dwellir.Config,
	wallets map[string]bool, pos *pb.Position, lastBlock *int64) error {

	req := &pb.StreamRequest{
		Position: pos,
		Filter: &pb.Filter{Fields: []*pb.FieldFilter{
			{Field: "users", Values: cfg.Wallets},
		}},
		// Progress frames tell us how far the server has scanned while our
		// wallets are quiet, so a reconnect does not rescan old blocks.
		Progress: &pb.Progress{IntervalMs: 0},
	}
	sctx, cancel := context.WithCancel(ctx)
	defer cancel()
	s, err := client.StreamMiscEvents(sctx, req)
	if err != nil {
		return err
	}

	// Read on one goroutine and parse on another. Parsing a large Funding
	// record inside the receive loop can make the client fall behind, and
	// the server then ends the stream.
	records := make(chan *pb.Record, 64)
	recvErr := make(chan error, 1)
	go func() {
		defer close(records)
		for {
			rec, err := s.Recv()
			if err != nil {
				recvErr <- err
				return
			}
			select {
			case records <- rec:
			case <-sctx.Done():
				recvErr <- sctx.Err()
				return
			}
		}
	}()

	for rec := range records {
		if p := rec.GetProgress(); p != nil {
			if bn, ok := p.GetScannedThrough().GetPosition().(*pb.Position_BlockNumber); ok && bn.BlockNumber > *lastBlock {
				*lastBlock = bn.BlockNumber
			}
			continue
		}
		if rec.BlockNumber == nil || rec.GetBlockNumber() <= *lastBlock {
			continue
		}
		if err := handle(rec, wallets); err != nil {
			return err
		}
		*lastBlock = rec.GetBlockNumber()
	}
	err = <-recvErr
	if errors.Is(err, context.Canceled) {
		return nil
	}
	return err
}

func handle(rec *pb.Record, wallets map[string]bool) error {
	var b block
	if err := json.Unmarshal(rec.Data, &b); err != nil {
		return fmt.Errorf("block %d: %w", rec.GetBlockNumber(), err)
	}
	for _, ev := range b.Events {
		for kind, raw := range ev.Inner {
			switch kind {
			case "Funding":
				printFunding(ev, raw, wallets)
			case "LedgerUpdate":
				printLedger(ev, raw)
			default:
				// Delegation, CDeposit, CWithdrawal, CreateSubAccount, and any
				// kind Hyperliquid adds later.
				fmt.Printf("%s  %-14s %s\n", ev.Time, kind, raw)
			}
		}
	}
	return nil
}

func printFunding(ev event, raw json.RawMessage, wallets map[string]bool) {
	var f funding
	if err := json.Unmarshal(raw, &f); err != nil {
		log.Printf("funding: %v", err)
		return
	}
	for _, d := range f.Deltas {
		if !wallets[strings.ToLower(d.User)] {
			continue
		}
		fmt.Printf("%s  %-14s user=%s coin=%s amount=%s size=%s rate=%s\n",
			ev.Time, "Funding", d.User, d.Coin, d.FundingAmount, d.Szi, d.FundingRate)
	}
}

func printLedger(ev event, raw json.RawMessage) {
	var l ledgerUpdate
	if err := json.Unmarshal(raw, &l); err != nil {
		log.Printf("ledger: %v", err)
		return
	}
	typ, _ := l.Delta["type"].(string)
	delete(l.Delta, "type")
	rest, _ := json.Marshal(l.Delta)
	fmt.Printf("%s  %-14s %-20s users=%s %s tx=%s\n",
		ev.Time, "LedgerUpdate", typ, strings.Join(l.Users, ","), rest, ev.Hash)
}
