package dwellir

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ErrNotServed is returned when the endpoint answers 403 "type not allowed":
// the request type exists on Hyperliquid but this endpoint does not serve it.
var ErrNotServed = errors.New("request type not served by this endpoint")

var httpClient = &http.Client{Timeout: 60 * time.Second}

// PostInfo sends one Info-style request (for example {"type":"meta"}) to url
// and decodes the JSON answer into out.
func PostInfo(ctx context.Context, cfg Config, url string, req any, out any) error {
	body, err := json.Marshal(req)
	if err != nil {
		return err
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("X-Api-Key", cfg.APIKey)

	resp, err := httpClient.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	switch {
	case resp.StatusCode == http.StatusForbidden && strings.Contains(string(data), "type not allowed"):
		return fmt.Errorf("%w: %s", ErrNotServed, strings.TrimSpace(string(data)))
	case resp.StatusCode != http.StatusOK:
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
	}
	return json.Unmarshal(data, out)
}
