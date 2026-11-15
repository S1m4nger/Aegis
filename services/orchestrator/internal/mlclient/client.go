package mlclient

import (
	"aegis/orchestrator/internal/config"
	"aegis/orchestrator/internal/domain"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"strings"
)

type Client struct {
	url  string
	http *http.Client
}

func decodeResponse(body io.Reader, target any) error {
	const limit = 16 * 1024
	data, err := io.ReadAll(io.LimitReader(body, limit+1))
	if err != nil || len(data) > limit {
		return errors.New("scorer response too large or unreadable")
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	if err := dec.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("trailing scorer response data")
	}
	return nil
}

func New(cfg config.Config) *Client {
	return &Client{url: strings.TrimSuffix(cfg.MLURL, "/"), http: &http.Client{Timeout: cfg.MLTimeout}}
}
func (c *Client) Ready(ctx context.Context) bool {
	req, err := http.NewRequestWithContext(ctx, "GET", c.url+"/health/ready", nil)
	if err != nil {
		return false
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var status struct {
		Ready        bool   `json:"ready"`
		ModelVersion string `json:"model_version"`
	}
	return decodeResponse(resp.Body, &status) == nil && status.Ready && status.ModelVersion != ""
}
func (c *Client) Score(ctx context.Context, t domain.Transaction) (domain.MLSignal, error) {
	b, err := json.Marshal(t)
	if err != nil {
		return domain.MLSignal{}, err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", c.url+"/internal/v1/score", bytes.NewReader(b))
	if err != nil {
		return domain.MLSignal{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return domain.MLSignal{}, fmt.Errorf("scorer unavailable: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return domain.MLSignal{}, errors.New("scorer returned non-200 status")
	}
	var wire struct {
		Score        *float64 `json:"score"`
		ModelVersion string   `json:"model_version"`
		Semantics    string   `json:"score_semantics"`
	}
	if err := decodeResponse(resp.Body, &wire); err != nil {
		return domain.MLSignal{}, err
	}
	if wire.Score == nil {
		return domain.MLSignal{}, errors.New("invalid scorer response")
	}
	signal := domain.MLSignal{Score: *wire.Score, ModelVersion: wire.ModelVersion, Semantics: wire.Semantics}
	if math.IsNaN(signal.Score) || math.IsInf(signal.Score, 0) || signal.Score < 0 || signal.Score > 1 || signal.ModelVersion == "" || signal.Semantics == "" {
		return signal, errors.New("invalid scorer response")
	}
	return signal, nil
}
