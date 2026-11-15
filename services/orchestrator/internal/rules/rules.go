package rules

import (
	"aegis/orchestrator/internal/config"
	"aegis/orchestrator/internal/domain"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"sort"
)

type Condition struct {
	Op       string          `json:"op"`
	Field    string          `json:"field,omitempty"`
	Value    json.RawMessage `json:"value,omitempty"`
	Children []Condition     `json:"children,omitempty"`
}
type Rule struct {
	ID          string    `json:"id"`
	Enabled     bool      `json:"enabled"`
	Priority    int       `json:"priority"`
	RiskWeight  float64   `json:"risk_weight"`
	When        Condition `json:"when"`
	Explanation string    `json:"explanation"`
}
type Document struct {
	Version string `json:"version"`
	Rules   []Rule `json:"rules"`
}
type Engine struct{ rules []Rule }

func strictDecode(data []byte, dst any) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return err
	}
	var extra any
	if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("unexpected data after JSON")
	}
	return nil
}

func validate(c Condition, depth int, nodes *int) error {
	(*nodes)++
	if depth > 8 || *nodes > 64 {
		return errors.New("rule AST depth/node limit exceeded")
	}
	if c.Op == "and" || c.Op == "or" {
		if c.Field != "" || len(c.Value) > 0 || len(c.Children) < 2 {
			return errors.New("invalid logical node")
		}
		for _, child := range c.Children {
			if err := validate(child, depth+1, nodes); err != nil {
				return err
			}
		}
		return nil
	}
	if len(c.Children) > 0 || len(c.Value) == 0 {
		return errors.New("invalid leaf node")
	}
	switch c.Field {
	case "type":
		if c.Op != "eq" && c.Op != "neq" && c.Op != "in" {
			return errors.New("type only allows eq/neq/in")
		}
		if c.Op == "in" {
			var s []string
			if err := json.Unmarshal(c.Value, &s); err != nil || len(s) == 0 || len(s) > 20 {
				return errors.New("invalid type in list")
			}
			for _, v := range s {
				if !validType(v) {
					return errors.New("invalid type in list")
				}
			}
		} else {
			var s string
			if err := json.Unmarshal(c.Value, &s); err != nil || !validType(s) {
				return errors.New("invalid type constant")
			}
		}
	case "amount", "step":
		switch c.Op {
		case "eq", "neq", "gt", "gte", "lt", "lte":
		default:
			return errors.New("numeric comparison unsupported")
		}
		var n float64
		if bytes.Equal(bytes.TrimSpace(c.Value), []byte("null")) {
			return errors.New("null numeric constant")
		}
		if err := json.Unmarshal(c.Value, &n); err != nil || math.IsNaN(n) || math.IsInf(n, 0) || n < 0 || n > 1e12 {
			return errors.New("invalid numeric constant")
		}
		if c.Field == "step" && (n < 1 || n > 1_000_000 || n != math.Trunc(n)) {
			return errors.New("invalid step constant")
		}
	default:
		return fmt.Errorf("unapproved field in rule: %s", c.Field)
	}
	return nil
}

func validType(v string) bool {
	switch v {
	case "CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER":
		return true
	}
	return false
}

func New(cfg config.Config) (*Engine, error) {
	b, err := os.ReadFile(cfg.RulesPath)
	if err != nil {
		return nil, fmt.Errorf("read rules: %w", err)
	}
	var doc Document
	if err := strictDecode(b, &doc); err != nil {
		return nil, err
	}
	if doc.Version != "1.0" || len(doc.Rules) > 200 {
		return nil, errors.New("invalid rules document version or size")
	}
	seen := map[string]bool{}
	for _, r := range doc.Rules {
		if r.ID == "" || seen[r.ID] || r.Priority < 0 || math.IsNaN(r.RiskWeight) || r.RiskWeight < 0 || r.RiskWeight > 1 {
			return nil, errors.New("invalid rule metadata")
		}
		seen[r.ID] = true
		nodes := 0
		if err := validate(r.When, 1, &nodes); err != nil {
			return nil, fmt.Errorf("rule %s: %w", r.ID, err)
		}
	}
	sort.SliceStable(doc.Rules, func(i, j int) bool {
		if doc.Rules[i].Priority == doc.Rules[j].Priority {
			return doc.Rules[i].ID < doc.Rules[j].ID
		}
		return doc.Rules[i].Priority < doc.Rules[j].Priority
	})
	return &Engine{rules: doc.Rules}, nil
}

func eval(c Condition, t domain.Transaction) bool {
	switch c.Op {
	case "and":
		for _, n := range c.Children {
			if !eval(n, t) {
				return false
			}
		}
		return true
	case "or":
		for _, n := range c.Children {
			if eval(n, t) {
				return true
			}
		}
		return false
	}
	if c.Field == "type" {
		if c.Op == "in" {
			var ss []string
			_ = json.Unmarshal(c.Value, &ss)
			for _, s := range ss {
				if s == t.Type {
					return true
				}
			}
			return false
		}
		var s string
		_ = json.Unmarshal(c.Value, &s)
		if c.Op == "eq" {
			return t.Type == s
		}
		return t.Type != s
	}
	var n float64
	_ = json.Unmarshal(c.Value, &n)
	v := t.Amount
	if c.Field == "step" {
		v = float64(t.Step)
	}
	switch c.Op {
	case "eq":
		return v == n
	case "neq":
		return v != n
	case "gt":
		return v > n
	case "gte":
		return v >= n
	case "lt":
		return v < n
	case "lte":
		return v <= n
	}
	return false
}

func (e *Engine) Evaluate(t domain.Transaction) domain.RuleSignal {
	fired := make([]domain.FiredRule, 0)
	product := 1.0
	for _, r := range e.rules {
		if !r.Enabled || !eval(r.When, t) {
			continue
		}
		product *= 1 - r.RiskWeight
		fired = append(fired, domain.FiredRule{ID: r.ID, Priority: r.Priority, Weight: r.RiskWeight, Explanation: r.Explanation})
	}
	return domain.RuleSignal{Score: 1 - product, Fired: fired}
}
