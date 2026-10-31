package dwellir

import (
	"context"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
)

// MaxRecvMsgSize is the largest gRPC message the client accepts.
// One hourly Funding event holds a delta for every open position on
// Hyperliquid and is tens of MB, far above gRPC's 4 MB default.
const MaxRecvMsgSize = 256 << 20

// DialGRPC opens a TLS connection to the Dwellir Hyperliquid gRPC gateway.
func DialGRPC(cfg Config) (*grpc.ClientConn, error) {
	return grpc.NewClient(cfg.GRPCEndpoint,
		grpc.WithTransportCredentials(credentials.NewTLS(nil)),
		grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(MaxRecvMsgSize)),
	)
}

// WithAPIKey adds the x-api-key header to every call made with the context.
func WithAPIKey(ctx context.Context, cfg Config) context.Context {
	return metadata.AppendToOutgoingContext(ctx, "x-api-key", cfg.APIKey)
}
