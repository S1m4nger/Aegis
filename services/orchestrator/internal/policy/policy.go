// Package policy owns deterministic fusion, decisions and hypothetical cost loss.
package policy

import (
	"aegis/orchestrator/internal/config"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
)

const (
	MLOnly           = "ML_ONLY"
	RulesOnly        = "RULES_ONLY"
	SimpleHybrid     = "SIMPLE_HYBRID"
	ConflictAware    = "CONFLICT_AWARE_HYBRID"
	AlwaysLegitimate = "ALWAYS_LEGITIMATE"
)

type Config struct {
	Version                 string  `json:"version"`
	Strategy                string  `json:"strategy"`
	MLWeight                float64 `json:"ml_weight"`
	DisagreementWeight      float64 `json:"disagreement_weight"`
	MLConflictCutoff        float64 `json:"ml_conflict_cutoff"`
	RuleConflictCutoff      float64 `json:"rule_conflict_cutoff"`
	ReviewThreshold         float64 `json:"review_threshold"`
	FlagThreshold           float64 `json:"flag_threshold"`
	ClassificationThreshold float64 `json:"classification_threshold"`
	Note                    string  `json:"note"`
}

func (p Config) Validate() error {
	switch p.Strategy {
	case MLOnly, RulesOnly, SimpleHybrid, ConflictAware, AlwaysLegitimate:
	default:
		return errors.New("unknown strategy")
	}
	vals := []float64{p.MLWeight, p.DisagreementWeight, p.MLConflictCutoff, p.RuleConflictCutoff, p.ReviewThreshold, p.FlagThreshold, p.ClassificationThreshold}
	for _, n := range vals {
		if math.IsNaN(n) || math.IsInf(n, 0) || n < 0 || n > 1 {
			return errors.New("policy value outside [0,1]")
		}
	}
	if p.ReviewThreshold >= p.FlagThreshold || p.Version == "" {
		return errors.New("invalid policy thresholds/version")
	}
	if p.MLConflictCutoff <= 0 || p.RuleConflictCutoff <= 0 || p.ClassificationThreshold <= 0 {
		return errors.New("cutoffs must be positive")
	}
	return nil
}

func Load(cfg config.Config) (Config, error) {
	b, err := os.ReadFile(cfg.PolicyPath)
	if err != nil {
		return Config{}, fmt.Errorf("read policy: %w", err)
	}
	var p Config
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	if err = dec.Decode(&p); err != nil {
		return p, err
	}
	var extra any
	if err = dec.Decode(&extra); !errors.Is(err, io.EOF) {
		return p, errors.New("trailing policy JSON")
	}
	return p, p.Validate()
}

// Combine keeps agreement observable independently of the selected strategy.
// Disagreements move the weighted signal toward the higher independent signal.
// This is a heuristic risk score, not a probability estimate.
func (p Config) Combine(ml, rule float64) (float64, string) {
	mh, rh := ml >= p.MLConflictCutoff, rule >= p.RuleConflictCutoff
	conflict := "BOTH_LOW"
	switch {
	case mh && rh:
		conflict = "BOTH_HIGH"
	case mh:
		conflict = "ML_ONLY_HIGH"
	case rh:
		conflict = "RULES_ONLY_HIGH"
	}
	score := p.MLWeight*ml + (1-p.MLWeight)*rule
	switch p.Strategy {
	case AlwaysLegitimate:
		score = 0
	case MLOnly:
		score = ml
	case RulesOnly:
		score = rule
	case ConflictAware:
		if mh != rh {
			score += p.DisagreementWeight * (math.Max(ml, rule) - score)
		}
	}
	return score, conflict
}
func (p Config) Action(score float64) string {
	if p.Strategy == AlwaysLegitimate {
		return "APPROVE"
	}
	if score >= p.FlagThreshold {
		return "FLAG"
	}
	if score >= p.ReviewThreshold {
		return "REVIEW"
	}
	return "APPROVE"
}

type Scenario struct {
	ID                string  `json:"id"`
	MissedFraudCost   float64 `json:"missed_fraud_cost"`
	FalseBlockCost    float64 `json:"false_block_cost"`
	ReviewCost        float64 `json:"review_cost"`
	ReviewSuccessRate float64 `json:"review_success_rate"`
	CapacityPer1000   int     `json:"capacity_per_1000"`
}

func (s Scenario) Validate() error {
	if s.ID == "" || s.CapacityPer1000 < 0 || s.CapacityPer1000 > 1000 || s.ReviewSuccessRate < 0 || s.ReviewSuccessRate > 1 {
		return errors.New("invalid cost scenario")
	}
	for _, v := range []float64{s.MissedFraudCost, s.FalseBlockCost, s.ReviewCost, s.ReviewSuccessRate} {
		if math.IsNaN(v) || math.IsInf(v, 0) || v < 0 {
			return errors.New("invalid scenario cost")
		}
	}
	return nil
}

// Loss is a hypothetical payoff table, with incremental review cost and residual misses.
func (s Scenario) Loss(fraud bool, action string) float64 {
	switch action {
	case "REVIEW":
		if fraud {
			return s.ReviewCost + (1-s.ReviewSuccessRate)*s.MissedFraudCost
		}
		return s.ReviewCost
	case "FLAG":
		if !fraud {
			return s.FalseBlockCost
		}
		return 0
	default:
		if fraud {
			return s.MissedFraudCost
		}
		return 0
	}
}
