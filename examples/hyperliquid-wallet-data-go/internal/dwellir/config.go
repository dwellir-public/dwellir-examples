// Package dwellir holds the small amount of shared setup the examples need:
// configuration from the environment, a gRPC connection, and an HTTP client
// for the Info and Index endpoints.
package dwellir

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// Default endpoints. Override any of them with the matching environment variable.
const (
	DefaultGRPCEndpoint = "api-hyperliquid-mainnet-grpc.n.dwellir.com:443"
	DefaultInfoURL      = "https://api-hyperliquid-mainnet-info.n.dwellir.com/info"
	DefaultIndexURL     = "https://api-hyperliquid-index.n.dwellir.com/info"
)

// Config is read from environment variables, after loading ./.env if it exists.
type Config struct {
	APIKey       string   // DWELLIR_API_KEY
	Wallets      []string // WALLETS, comma separated, lower-cased
	GRPCEndpoint string   // HL_GRPC_ENDPOINT
	InfoURL      string   // HL_INFO_URL
	IndexURL     string   // HL_INDEX_URL
}

// LoadConfig reads the configuration. walletsFlag, when not empty, overrides WALLETS.
func LoadConfig(walletsFlag string) (Config, error) {
	loadDotEnv(".env")

	cfg := Config{
		APIKey:       os.Getenv("DWELLIR_API_KEY"),
		GRPCEndpoint: envOr("HL_GRPC_ENDPOINT", DefaultGRPCEndpoint),
		InfoURL:      envOr("HL_INFO_URL", DefaultInfoURL),
		IndexURL:     envOr("HL_INDEX_URL", DefaultIndexURL),
	}
	if cfg.APIKey == "" {
		return cfg, fmt.Errorf("DWELLIR_API_KEY is not set (copy .env.example to .env and add your key)")
	}

	raw := walletsFlag
	if raw == "" {
		raw = os.Getenv("WALLETS")
	}
	cfg.Wallets = ParseWallets(raw)
	if len(cfg.Wallets) == 0 {
		return cfg, fmt.Errorf("no wallets: set WALLETS in .env or pass -wallets 0xabc...,0xdef...")
	}
	return cfg, nil
}

// ParseWallets splits a comma-separated list and lower-cases each address.
// Hyperliquid returns addresses in lower case, so compare in lower case.
func ParseWallets(raw string) []string {
	var out []string
	for _, w := range strings.Split(raw, ",") {
		w = strings.ToLower(strings.TrimSpace(w))
		if w == "" {
			continue
		}
		out = append(out, w)
	}
	return out
}

// WalletSet returns the wallets as a set for fast lookups.
func (c Config) WalletSet() map[string]bool {
	set := make(map[string]bool, len(c.Wallets))
	for _, w := range c.Wallets {
		set[w] = true
	}
	return set
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// loadDotEnv sets KEY=VALUE lines from path. Variables already set in the
// environment win. A missing file is not an error.
func loadDotEnv(path string) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		k = strings.TrimSpace(strings.TrimPrefix(k, "export "))
		v = strings.Trim(strings.TrimSpace(v), `"'`)
		if _, set := os.LookupEnv(k); !set {
			os.Setenv(k, v)
		}
	}
}
