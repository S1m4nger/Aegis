package orchestrator

import (
	"aegis/orchestrator/internal/domain"
	"aegis/orchestrator/internal/policy"
	"aegis/orchestrator/internal/rules"
	"context"
)

const Disclaimer = "This project is a prototype and is not financial advice."

type Scorer interface {
	Score(context.Context, domain.Transaction) (domain.MLSignal, error)
	Ready(context.Context) bool
}

type Service struct {
	ml     Scorer
	rules  *rules.Engine
	policy policy.Config
}

func New(ml Scorer, rules *rules.Engine, policy policy.Config) *Service {
	return &Service{ml: ml, rules: rules, policy: policy}
}
func (s *Service) Ready(ctx context.Context) bool { return s.ml.Ready(ctx) }
func (s *Service) Analyze(ctx context.Context, tx domain.Transaction) (domain.Analysis, error) {
	if err := tx.Validate(); err != nil {
		return domain.Analysis{}, err
	}
	ml, err := s.ml.Score(ctx, tx)
	if err != nil {
		return domain.Analysis{}, err
	}
	rule := s.rules.Evaluate(tx)
	fused, conflict := s.policy.Combine(ml.Score, rule.Score)
	reasons := make([]string, 0, len(rule.Fired)+1)
	for _, r := range rule.Fired {
		reasons = append(reasons, r.ID)
	}
	if len(reasons) == 0 {
		reasons = append(reasons, "no_rule_triggered")
	}
	return domain.Analysis{
		SchemaVersion: "1.0", ModelVersion: ml.ModelVersion, MLScore: ml.Score, RuleScore: rule.Score,
		FusionScore: fused, ConflictType: conflict, RecommendedAction: s.policy.Action(fused),
		Reasons: reasons, MLScoreSemantics: ml.Semantics, PolicyVersion: s.policy.Version, Disclaimer: Disclaimer, FiredRules: rule.Fired, Strategy: s.policy.Strategy, FusionScoreSemantics: "heuristic_risk_score",
	}, nil
}
