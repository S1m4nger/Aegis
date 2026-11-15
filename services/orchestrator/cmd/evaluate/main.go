// Command evaluate runs the frozen Go rule and decision policy over offline
// JSONL rows. Python only prepares model scores and computes reporting metrics.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"

	"aegis/orchestrator/internal/config"
	"aegis/orchestrator/internal/domain"
	"aegis/orchestrator/internal/policy"
	"aegis/orchestrator/internal/rules"
)

type inputRow struct {
	Step    int     `json:"step"`
	Type    string  `json:"type"`
	Amount  float64 `json:"amount"`
	Fraud   bool    `json:"fraud"`
	MLScore float64 `json:"ml_score"`
}

type scoredRow struct {
	Input inputRow
	Rule  float64
}

type selectionBundle struct {
	SchemaVersion  string                              `json:"schema_version"`
	RuleDocument   rules.Document                      `json:"rule_document"`
	SelectedRules  map[string]float64                  `json:"selected_rule_thresholds"`
	Classification map[string]policy.Config            `json:"classification_policies"`
	CostPolicies   map[string]map[string]policy.Config `json:"cost_policies"`
	Selection      map[string]selectionMetric          `json:"selection_metrics"`
	Primary        policy.Config                       `json:"primary_policy"`
	ScenarioIDs    []string                            `json:"scenario_ids"`
}

type selectionMetric struct {
	F1        float64 `json:"f1"`
	Precision float64 `json:"precision"`
	Recall    float64 `json:"recall"`
	Threshold float64 `json:"classification_threshold"`
	FalsePos  int     `json:"false_positives"`
}

type prediction struct {
	Step             int                `json:"step"`
	Type             string             `json:"type"`
	Amount           float64            `json:"amount"`
	Fraud            bool               `json:"fraud"`
	MLScore          float64            `json:"ml_score"`
	RuleScore        float64            `json:"rule_score"`
	Conflict         string             `json:"conflict"`
	Score            float64            `json:"score"`
	Predicted        bool               `json:"predicted_fraud"`
	Actions          map[string]string  `json:"actions"`
	UnboundedActions map[string]string  `json:"unbounded_actions"`
	Losses           map[string]float64 `json:"simulated_losses"`
	DefaultActions   map[string]string  `json:"default_actions_without_cost_optimizer"`
	DefaultLosses    map[string]float64 `json:"default_simulated_losses"`
	TopKSelected     map[string]bool    `json:"top_k_selected"`
}

func readRows(path string) ([]inputRow, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 64*1024), 2*1024*1024)
	rows := make([]inputRow, 0, 200_000)
	for scanner.Scan() {
		var fields map[string]json.RawMessage
		dec := json.NewDecoder(bytes.NewReader(scanner.Bytes()))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&fields); err != nil {
			return nil, fmt.Errorf("decode row %d: %w", len(rows)+1, err)
		}
		if len(fields) != 5 {
			return nil, fmt.Errorf("row %d must contain exactly step/type/amount/fraud/ml_score", len(rows)+1)
		}
		for _, name := range []string{"step", "type", "amount", "fraud", "ml_score"} {
			if raw, ok := fields[name]; !ok || bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
				return nil, fmt.Errorf("row %d missing required field %q", len(rows)+1, name)
			}
		}
		var row inputRow
		if err := json.Unmarshal(scanner.Bytes(), &row); err != nil {
			return nil, fmt.Errorf("decode row %d: %w", len(rows)+1, err)
		}
		var extra any
		if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("row %d has trailing data", len(rows)+1)
		}
		if row.Step < 1 || !validType(row.Type) || math.IsNaN(row.Amount) || math.IsInf(row.Amount, 0) || row.Amount < 0 || row.Amount > 1e12 || math.IsNaN(row.MLScore) || math.IsInf(row.MLScore, 0) || row.MLScore < 0 || row.MLScore > 1 {
			return nil, fmt.Errorf("invalid transaction or ML score at row %d", len(rows)+1)
		}
		rows = append(rows, row)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, errors.New("input contains no rows")
	}
	return rows, nil
}

func validType(s string) bool {
	switch s {
	case "CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER":
		return true
	}
	return false
}

func loadScenarios(path string) ([]policy.Scenario, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var doc struct {
		Scenarios []policy.Scenario `json:"scenarios"`
	}
	if err := json.Unmarshal(b, &doc); err != nil {
		return nil, err
	}
	if len(doc.Scenarios) == 0 {
		return nil, errors.New("no cost scenarios")
	}
	seen := map[string]bool{}
	for _, scenario := range doc.Scenarios {
		if seen[scenario.ID] {
			return nil, fmt.Errorf("duplicate scenario %s", scenario.ID)
		}
		seen[scenario.ID] = true
		if err := scenario.Validate(); err != nil {
			return nil, fmt.Errorf("scenario %s: %w", scenario.ID, err)
		}
	}
	return doc.Scenarios, nil
}

func loadTrainingCandidates(path string) (map[string][]float64, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var report struct {
		RuleCandidates struct {
			AmountThresholds map[string]map[string]float64 `json:"amount_thresholds"`
		} `json:"rule_candidates"`
	}
	if err := json.Unmarshal(b, &report); err != nil {
		return nil, err
	}
	out := map[string][]float64{}
	for kind, values := range report.RuleCandidates.AmountThresholds {
		for _, q := range []string{"0.75", "0.9", "0.99"} {
			value, ok := values[q]
			if !ok || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
				return nil, fmt.Errorf("missing valid train candidate %s/%s", kind, q)
			}
			out[kind] = append(out[kind], value)
		}
	}
	if len(out["TRANSFER"]) != 3 || len(out["CASH_OUT"]) != 3 {
		return nil, errors.New("training report lacks rule candidate thresholds")
	}
	return out, nil
}

func setAmountThreshold(c *rules.Condition, threshold float64) {
	if c.Field == "amount" {
		b, _ := json.Marshal(threshold)
		c.Value = b
	}
	for i := range c.Children {
		setAmountThreshold(&c.Children[i], threshold)
	}
}

func engineFor(doc rules.Document) (*rules.Engine, func(), error) {
	b, err := json.Marshal(doc)
	if err != nil {
		return nil, nil, err
	}
	f, err := os.CreateTemp("", "aegis-rules-*.json")
	if err != nil {
		return nil, nil, err
	}
	path := f.Name()
	if _, err := f.Write(b); err != nil {
		f.Close()
		os.Remove(path)
		return nil, nil, err
	}
	if err := f.Close(); err != nil {
		os.Remove(path)
		return nil, nil, err
	}
	e, err := rules.New(config.Config{RulesPath: path})
	if err != nil {
		os.Remove(path)
		return nil, nil, err
	}
	return e, func() { _ = os.Remove(path) }, nil
}

func ruleDocument(base rules.Document, transfer, cashout float64) rules.Document {
	doc := base
	doc.Rules = append([]rules.Rule(nil), base.Rules...)
	for i := range doc.Rules {
		doc.Rules[i].When = cloneCondition(base.Rules[i].When)
		if doc.Rules[i].ID == "large_transfer_example" {
			setAmountThreshold(&doc.Rules[i].When, transfer)
		}
		if doc.Rules[i].ID == "large_cashout_example" {
			setAmountThreshold(&doc.Rules[i].When, cashout)
		}
	}
	return doc
}

func cloneCondition(c rules.Condition) rules.Condition {
	out := c
	out.Value = append(json.RawMessage(nil), c.Value...)
	out.Children = make([]rules.Condition, len(c.Children))
	for i := range c.Children {
		out.Children[i] = cloneCondition(c.Children[i])
	}
	return out
}

func calcMetric(obs []policy.Observation, threshold float64) selectionMetric {
	tp, fp, fn := 0, 0, 0
	for _, item := range obs {
		pred := item.Score >= threshold
		switch {
		case pred && item.Fraud:
			tp++
		case pred:
			fp++
		case item.Fraud:
			fn++
		}
	}
	precision, recall, f1 := 0.0, 0.0, 0.0
	if tp+fp > 0 {
		precision = float64(tp) / float64(tp+fp)
	}
	if tp+fn > 0 {
		recall = float64(tp) / float64(tp+fn)
	}
	if precision+recall > 0 {
		f1 = 2 * precision * recall / (precision + recall)
	}
	return selectionMetric{F1: f1, Precision: precision, Recall: recall, Threshold: threshold, FalsePos: fp}
}

func better(a, b selectionMetric) bool {
	if a.F1 != b.F1 {
		return a.F1 > b.F1
	}
	if a.FalsePos != b.FalsePos {
		return a.FalsePos < b.FalsePos
	}
	return a.Threshold > b.Threshold
}

func selectPolicies(rows []inputRow, trainingPath, rulesPath, scenariosPath, bundlePath, primaryPath string) error {
	for _, path := range []string{bundlePath, filepath.Join(filepath.Dir(bundlePath), "final-evaluation.lock")} {
		if _, err := os.Stat(path); err == nil {
			return errors.New("selection or final lock already exists; refusing to overwrite")
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	baseBytes, err := os.ReadFile(rulesPath)
	if err != nil {
		return err
	}
	var baseDoc rules.Document
	if err := json.Unmarshal(baseBytes, &baseDoc); err != nil {
		return err
	}
	candidates, err := loadTrainingCandidates(trainingPath)
	if err != nil {
		return err
	}
	scenarios, err := loadScenarios(scenariosPath)
	if err != nil {
		return err
	}
	baseObs := make([]policy.Observation, len(rows))
	mlObs := make([]policy.Observation, len(rows))
	for i, row := range rows {
		if row.Step < 471 || row.Step > 550 {
			return fmt.Errorf("selection input contains out-of-window step %d", row.Step)
		}
		baseObs[i] = policy.Observation{Score: row.MLScore, Fraud: row.Fraud, Step: row.Step}
		mlObs[i] = baseObs[i]
	}
	mlThreshold, err := policy.OptimizeClassification(mlObs)
	if err != nil {
		return err
	}
	bestRuleF1 := selectionMetric{F1: -1}
	var chosenDoc rules.Document
	var chosenScores []float64
	var chosenRuleThresholds map[string]float64
	chosenRuleCutoff := 0.5
	for _, transfer := range candidates["TRANSFER"] {
		for _, cashout := range candidates["CASH_OUT"] {
			doc := ruleDocument(baseDoc, transfer, cashout)
			engine, cleanup, err := engineFor(doc)
			if err != nil {
				return err
			}
			ruleScores := make([]float64, len(rows))
			for i, row := range rows {
				ruleScores[i] = engine.Evaluate(domain.Transaction{Step: row.Step, Type: row.Type, Amount: row.Amount}).Score
			}
			cleanup()
			obs := make([]policy.Observation, len(rows))
			ruleObs := make([]policy.Observation, len(rows))
			for i, row := range rows {
				ruleObs[i] = policy.Observation{Score: ruleScores[i], Fraud: row.Fraud, Step: row.Step}
			}
			ruleThreshold, err := policy.OptimizeClassification(ruleObs)
			if err != nil {
				return err
			}
			candidate := policy.Config{Version: "selection-v1", Strategy: policy.ConflictAware, MLWeight: .7, DisagreementWeight: .5, MLConflictCutoff: mlThreshold, RuleConflictCutoff: ruleThreshold, ReviewThreshold: .35, FlagThreshold: .8, ClassificationThreshold: 1}
			for i, row := range rows {
				score, _ := candidate.Combine(row.MLScore, ruleScores[i])
				obs[i] = policy.Observation{Score: score, Fraud: row.Fraud, Step: row.Step}
			}
			threshold, err := policy.OptimizeClassification(obs)
			if err != nil {
				return err
			}
			metric := calcMetric(obs, threshold)
			if metric.F1 > bestRuleF1.F1 || (metric.F1 == bestRuleF1.F1 && (metric.FalsePos < bestRuleF1.FalsePos || (metric.FalsePos == bestRuleF1.FalsePos && (chosenRuleThresholds == nil || transfer < chosenRuleThresholds["TRANSFER"] || (transfer == chosenRuleThresholds["TRANSFER"] && cashout < chosenRuleThresholds["CASH_OUT"]))))) {
				bestRuleF1 = metric
				chosenDoc = doc
				chosenScores = ruleScores
				chosenRuleThresholds = map[string]float64{"TRANSFER": transfer, "CASH_OUT": cashout}
				chosenRuleCutoff = ruleThreshold
			}
		}
	}
	if len(chosenScores) != len(rows) {
		return errors.New("rule selection produced no candidate")
	}
	strategies := []string{policy.AlwaysLegitimate, policy.MLOnly, policy.RulesOnly, policy.SimpleHybrid, policy.ConflictAware}
	classification := make(map[string]policy.Config, len(strategies))
	selectionMetrics := make(map[string]selectionMetric, len(strategies))
	for _, strategy := range strategies {
		weights := []float64{.7}
		disagreements := []float64{.5}
		if strategy == policy.SimpleHybrid || strategy == policy.ConflictAware {
			weights = []float64{.5, .7, .9}
		}
		if strategy == policy.ConflictAware {
			disagreements = []float64{.25, .5, 1}
		}
		best := selectionMetric{F1: -1}
		var bestConfig policy.Config
		for _, weight := range weights {
			for _, disagreement := range disagreements {
				cfg := policy.Config{Version: "selection-v1", Strategy: strategy, MLWeight: weight, DisagreementWeight: disagreement, MLConflictCutoff: mlThreshold, RuleConflictCutoff: chosenRuleCutoff, ReviewThreshold: .35, FlagThreshold: .8, ClassificationThreshold: 1}
				obs := make([]policy.Observation, len(rows))
				for i, row := range rows {
					score, _ := cfg.Combine(row.MLScore, chosenScores[i])
					if strategy == policy.AlwaysLegitimate {
						score = 0
					}
					obs[i] = policy.Observation{Score: score, Fraud: row.Fraud, Step: row.Step}
				}
				threshold := 1.0
				var err error
				if strategy != policy.AlwaysLegitimate {
					threshold, err = policy.OptimizeClassification(obs)
					if err != nil {
						return err
					}
				}
				metric := calcMetric(obs, threshold)
				if better(metric, best) {
					best = metric
					cfg.ClassificationThreshold = threshold
					bestConfig = cfg
				}
			}
		}
		classification[strategy] = bestConfig
		selectionMetrics[strategy] = best
	}
	costs := map[string]map[string]policy.Config{}
	for _, strategy := range strategies {
		costs[strategy] = map[string]policy.Config{}
		base := classification[strategy]
		obs := make([]policy.Observation, len(rows))
		for i, row := range rows {
			score, _ := base.Combine(row.MLScore, chosenScores[i])
			obs[i] = policy.Observation{Score: score, Fraud: row.Fraud, Step: row.Step}
		}
		for _, scenario := range scenarios {
			optimized, err := policy.OptimizeCosts(obs, base, scenario)
			if err != nil {
				return err
			}
			costs[strategy][scenario.ID] = optimized
		}
	}
	primary := costs[policy.ConflictAware][scenarios[0].ID]
	primary.Note = "Frozen on steps 471-550; cost scenario " + scenarios[0].ID + "; synthetic PaySim only."
	bundle := selectionBundle{SchemaVersion: "1.0", RuleDocument: chosenDoc, SelectedRules: chosenRuleThresholds, Classification: classification, CostPolicies: costs, Selection: selectionMetrics, Primary: primary}
	for _, scenario := range scenarios {
		bundle.ScenarioIDs = append(bundle.ScenarioIDs, scenario.ID)
	}
	if err := writeJSONAtomic(bundlePath, bundle); err != nil {
		return err
	}
	if err := writeJSONAtomic(rulesPath, chosenDoc); err != nil {
		return err
	}
	if err := writeJSONAtomic(primaryPath, primary); err != nil {
		return err
	}
	return nil
}

func scoreRows(rows []inputRow, bundlePath, rulesPath, scenariosPath, outputPath string) error {
	b, err := os.ReadFile(bundlePath)
	if err != nil {
		return err
	}
	var bundle selectionBundle
	if err := json.Unmarshal(b, &bundle); err != nil {
		return err
	}
	if bundle.SchemaVersion != "1.0" {
		return errors.New("unsupported frozen policy bundle")
	}
	scenarios, err := loadScenarios(scenariosPath)
	if err != nil {
		return err
	}
	ruleBytes, err := json.Marshal(bundle.RuleDocument)
	if err != nil {
		return err
	}
	var doc rules.Document
	if err := json.Unmarshal(ruleBytes, &doc); err != nil {
		return err
	}
	engine, cleanup, err := engineFor(doc)
	if err != nil {
		return err
	}
	defer cleanup()
	strategies := []string{policy.AlwaysLegitimate, policy.MLOnly, policy.RulesOnly, policy.SimpleHybrid, policy.ConflictAware}
	for _, strategy := range strategies {
		cfg, ok := bundle.Classification[strategy]
		if !ok || cfg.Strategy != strategy {
			return fmt.Errorf("missing classification policy for %s", strategy)
		}
		if err := cfg.Validate(); err != nil {
			return fmt.Errorf("invalid classification policy %s: %w", strategy, err)
		}
		for _, scenario := range scenarios {
			costCfg, ok := bundle.CostPolicies[strategy][scenario.ID]
			if !ok || costCfg.Strategy != strategy {
				return fmt.Errorf("missing cost policy for %s/%s", strategy, scenario.ID)
			}
			if err := costCfg.Validate(); err != nil {
				return fmt.Errorf("invalid cost policy %s/%s: %w", strategy, scenario.ID, err)
			}
			if costCfg.MLWeight != cfg.MLWeight || costCfg.DisagreementWeight != cfg.DisagreementWeight || costCfg.MLConflictCutoff != cfg.MLConflictCutoff || costCfg.RuleConflictCutoff != cfg.RuleConflictCutoff || costCfg.ClassificationThreshold != cfg.ClassificationThreshold {
				return fmt.Errorf("cost policy changes frozen scoring/classification for %s/%s", strategy, scenario.ID)
			}
		}
	}
	observations := make(map[string][]policy.Observation, len(strategies))
	actions := make(map[string]map[string][]string, len(strategies))
	for _, strategy := range strategies {
		observations[strategy] = make([]policy.Observation, len(rows))
		actions[strategy] = map[string][]string{}
		for _, scenario := range scenarios {
			actions[strategy][scenario.ID] = make([]string, len(rows))
		}
	}
	scores := make(map[string][]float64, len(strategies))
	conflicts := make([]string, len(rows))
	ruleScores := make([]float64, len(rows))
	for _, strategy := range strategies {
		scores[strategy] = make([]float64, len(rows))
	}
	for i, row := range rows {
		ruleScores[i] = engine.Evaluate(domain.Transaction{Step: row.Step, Type: row.Type, Amount: row.Amount}).Score
		conflicts[i] = ""
		for _, strategy := range strategies {
			cfg := bundle.Classification[strategy]
			score, conflict := cfg.Combine(row.MLScore, ruleScores[i])
			if strategy == policy.AlwaysLegitimate {
				score = 0
			}
			scores[strategy][i] = score
			if strategy == policy.ConflictAware {
				conflicts[i] = conflict
			}
			observations[strategy][i] = policy.Observation{Score: score, Fraud: row.Fraud, Step: row.Step}
		}
	}
	for _, strategy := range strategies {
		for _, scenario := range scenarios {
			cfg, ok := bundle.CostPolicies[strategy][scenario.ID]
			if !ok {
				return fmt.Errorf("missing frozen policy for %s/%s", strategy, scenario.ID)
			}
			a := make([]string, len(rows))
			for i, score := range scores[strategy] {
				a[i] = cfg.Action(score)
			}
			actions[strategy]["unbounded/"+scenario.ID] = append([]string(nil), a...)
			a = policy.ApplyCapacity(observations[strategy], a, scenario.CapacityPer1000)
			actions[strategy][scenario.ID] = a
			defaults := make([]string, len(rows))
			allReviews := make([]string, len(rows))
			for i, score := range scores[strategy] {
				defaults[i] = bundle.Classification[strategy].Action(score)
				allReviews[i] = "REVIEW"
			}
			actions[strategy]["default/"+scenario.ID] = policy.ApplyCapacity(observations[strategy], defaults, scenario.CapacityPer1000)
			// A separate ranking diagnostic uses every row as a candidate.
			// ApplyCapacity consumes scores and step sizes, never labels.
			actions[strategy]["topk/"+scenario.ID] = policy.ApplyCapacity(observations[strategy], allReviews, scenario.CapacityPer1000)
		}
	}
	out, err := os.Create(outputPath)
	if err != nil {
		return err
	}
	defer out.Close()
	w := bufio.NewWriterSize(out, 256*1024)
	enc := json.NewEncoder(w)
	for i, row := range rows {
		per := make(map[string]prediction, len(strategies))
		for _, strategy := range strategies {
			cfg := bundle.Classification[strategy]
			p := prediction{Step: row.Step, Type: row.Type, Amount: row.Amount, Fraud: row.Fraud, MLScore: row.MLScore, RuleScore: ruleScores[i], Conflict: conflicts[i], Score: scores[strategy][i], Predicted: scores[strategy][i] >= cfg.ClassificationThreshold, Actions: map[string]string{}, UnboundedActions: map[string]string{}, Losses: map[string]float64{}, DefaultActions: map[string]string{}, DefaultLosses: map[string]float64{}, TopKSelected: map[string]bool{}}
			for _, scenario := range scenarios {
				action := actions[strategy][scenario.ID][i]
				p.Actions[scenario.ID] = action
				p.UnboundedActions[scenario.ID] = actions[strategy]["unbounded/"+scenario.ID][i]
				p.Losses[scenario.ID] = scenario.Loss(row.Fraud, action)
				p.DefaultActions[scenario.ID] = actions[strategy]["default/"+scenario.ID][i]
				p.DefaultLosses[scenario.ID] = scenario.Loss(row.Fraud, p.DefaultActions[scenario.ID])
				p.TopKSelected[scenario.ID] = actions[strategy]["topk/"+scenario.ID][i] == "REVIEW"
			}
			per[strategy] = p
		}
		if err := enc.Encode(per); err != nil {
			return err
		}
	}
	return w.Flush()
}

func writeJSONAtomic(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	b = append(b, '\n')
	tmp, err := os.CreateTemp(filepath.Dir(path), ".selection-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	if _, err := tmp.Write(b); err != nil {
		tmp.Close()
		os.Remove(name)
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(name)
		return err
	}
	if err := os.Rename(name, path); err != nil {
		os.Remove(name)
		return err
	}
	return nil
}

func run(args []string) error {
	if len(args) == 0 {
		return errors.New("expected select or score subcommand")
	}
	switch args[0] {
	case "select":
		fs := flag.NewFlagSet("select", flag.ContinueOnError)
		in := fs.String("input", "", "selection JSONL")
		training := fs.String("training", "../../reports/training.json", "training report")
		rulePath := fs.String("rules", "../../configs/rules.json", "rules JSON")
		scenarioPath := fs.String("scenarios", "../../configs/scenarios.json", "scenarios JSON")
		bundle := fs.String("bundle", "../../reports/selection_bundle.json", "selection bundle output")
		primary := fs.String("primary", "../../configs/policy.json", "deploy policy output")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if *in == "" {
			return errors.New("--input is required")
		}
		rows, err := readRows(*in)
		if err != nil {
			return err
		}
		return selectPolicies(rows, *training, *rulePath, *scenarioPath, *bundle, *primary)
	case "score":
		fs := flag.NewFlagSet("score", flag.ContinueOnError)
		in := fs.String("input", "", "final JSONL")
		bundle := fs.String("bundle", "../../reports/selection_bundle.json", "frozen bundle")
		rulePath := fs.String("rules", "../../configs/rules.json", "frozen rules")
		scenarioPath := fs.String("scenarios", "../../configs/scenarios.json", "frozen scenarios")
		out := fs.String("output", "", "output JSONL")
		window := fs.String("window", "final", "selection or final")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if *in == "" || *out == "" {
			return errors.New("--input and --output are required")
		}
		rows, err := readRows(*in)
		if err != nil {
			return err
		}
		for _, row := range rows {
			if (*window == "selection" && (row.Step < 471 || row.Step > 550)) || (*window == "final" && (row.Step < 551 || row.Step > 743)) || (*window != "selection" && *window != "final") {
				return fmt.Errorf("input row step %d does not match evaluation window %q", row.Step, *window)
			}
		}
		return scoreRows(rows, *bundle, *rulePath, *scenarioPath, *out)
	default:
		return fmt.Errorf("unknown subcommand %q", args[0])
	}
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "evaluate:", err)
		os.Exit(1)
	}
}
