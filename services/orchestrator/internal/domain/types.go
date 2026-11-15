package domain

import (
	"errors"
	"math"
)

type Transaction struct {
	Step   int     `json:"step"`
	Type   string  `json:"type"`
	Amount float64 `json:"amount"`
}

func (t Transaction) Validate() error {
	if t.Step < 1 || t.Step > 1_000_000 {
		return errors.New("invalid step")
	}
	if math.IsNaN(t.Amount) || math.IsInf(t.Amount, 0) || t.Amount < 0 || t.Amount > 1e12 {
		return errors.New("invalid amount")
	}
	switch t.Type {
	case "CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER":
	default:
		return errors.New("invalid transaction type")
	}
	return nil
}

type MLSignal struct {
	Score        float64 `json:"score"`
	ModelVersion string  `json:"model_version"`
	Semantics    string  `json:"score_semantics"`
}

type FiredRule struct {
	ID          string  `json:"id"`
	Priority    int     `json:"priority"`
	Weight      float64 `json:"weight"`
	Explanation string  `json:"explanation"`
}

type RuleSignal struct {
	Score float64     `json:"score"`
	Fired []FiredRule `json:"fired"`
}

type Analysis struct {
	FiredRules           []FiredRule `json:"fired_rules"`
	Strategy             string      `json:"strategy"`
	FusionScoreSemantics string      `json:"fusion_score_semantics"`
	SchemaVersion        string      `json:"schema_version"`
	ModelVersion         string      `json:"model_version"`
	MLScore              float64     `json:"ml_score"`
	RuleScore            float64     `json:"rule_score"`
	FusionScore          float64     `json:"fusion_score"`
	ConflictType         string      `json:"conflict_type"`
	RecommendedAction    string      `json:"recommended_action"`
	Reasons              []string    `json:"reasons"`
	MLScoreSemantics     string      `json:"ml_score_semantics"`
	Disclaimer           string      `json:"disclaimer"`
	PolicyVersion        string      `json:"policy_version"`
}
