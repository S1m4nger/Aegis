package transport

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"aegis/orchestrator/internal/policy"
)

// Only aggregate frozen decisions are re-costed; no scores or thresholds change.
type frozenCohort struct {
	Strategy          string `json:"strategy"`
	Rows              *int   `json:"rows"`
	Frauds            *int   `json:"frauds"`
	Reviews           *int   `json:"review"`
	FraudApproved     *int   `json:"fraud_approved_misses"`
	FraudReviewed     *int   `json:"fraud_sent_to_review"`
	FraudFlagged      *int   `json:"fraud_flagged"`
	LegitimateFlagged *int   `json:"legitimate_flagged"`
}
type scenarioInput struct {
	ID       string   `json:"id"`
	Miss     *float64 `json:"missed_fraud_cost"`
	Block    *float64 `json:"false_block_cost"`
	Review   *float64 `json:"review_cost"`
	Success  *float64 `json:"review_success_rate"`
	Capacity *int     `json:"capacity_per_1000"`
}
type scenarioResult struct {
	Strategy string  `json:"strategy"`
	Rows     int     `json:"rows"`
	Total    float64 `json:"total_simulated_cost"`
	Per1000  float64 `json:"cost_per_1000"`
}

func simulateFrozen(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 64*1024)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	var input struct {
		Scenario scenarioInput  `json:"scenario"`
		Cohorts  []frozenCohort `json:"cohorts"`
	}
	if err := dec.Decode(&input); err != nil {
		jsonError(w, 400, "invalid scenario JSON")
		return
	}
	var extra any
	if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
		jsonError(w, 400, "only one JSON object allowed")
		return
	}
	raw := input.Scenario
	if raw.Miss == nil || raw.Block == nil || raw.Review == nil || raw.Success == nil || raw.Capacity == nil {
		jsonError(w, 400, "all scenario costs, success rate and capacity are required")
		return
	}
	scenario := policy.Scenario{ID: raw.ID, MissedFraudCost: *raw.Miss, FalseBlockCost: *raw.Block, ReviewCost: *raw.Review, ReviewSuccessRate: *raw.Success, CapacityPer1000: *raw.Capacity}
	if scenario.Validate() != nil || len(scenario.ID) > 64 || strings.TrimSpace(scenario.ID) == "" || *raw.Miss > 1e9 || *raw.Block > 1e9 || *raw.Review > 1e9 || len(input.Cohorts) < 1 || len(input.Cohorts) > 20 {
		jsonError(w, 400, "invalid scenario or cohort count")
		return
	}
	results := make([]scenarioResult, 0, len(input.Cohorts))
	seen := map[string]bool{}
	for _, c := range input.Cohorts {
		if c.Strategy == "" || len(c.Strategy) > 64 || seen[c.Strategy] {
			jsonError(w, 400, "invalid or duplicate strategy")
			return
		}
		seen[c.Strategy] = true
		values := []*int{c.Rows, c.Frauds, c.Reviews, c.FraudApproved, c.FraudReviewed, c.FraudFlagged, c.LegitimateFlagged}
		for _, v := range values {
			if v == nil || *v < 0 || *v > 1_000_000_000 {
				jsonError(w, 400, "all cohort counts must be integers in [0, 1000000000]")
				return
			}
		}
		rows, frauds, reviews := *c.Rows, *c.Frauds, *c.Reviews
		if rows == 0 || frauds > rows || reviews > rows || *c.FraudReviewed > reviews || *c.FraudApproved+*c.FraudReviewed+*c.FraudFlagged != frauds || *c.LegitimateFlagged+reviews-*c.FraudReviewed > rows-frauds {
			jsonError(w, 400, "inconsistent frozen cohort counts")
			return
		}
		total := float64(*c.FraudApproved)*scenario.Loss(true, "APPROVE") +
			float64(*c.FraudReviewed)*scenario.Loss(true, "REVIEW") +
			float64(reviews-*c.FraudReviewed)*scenario.Loss(false, "REVIEW") +
			float64(*c.FraudFlagged)*scenario.Loss(true, "FLAG") +
			float64(*c.LegitimateFlagged)*scenario.Loss(false, "FLAG")
		results = append(results, scenarioResult{Strategy: c.Strategy, Rows: rows, Total: total, Per1000: total * 1000 / float64(rows)})
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(struct {
		ScenarioOnly bool             `json:"scenario_only"`
		Cohorts      []scenarioResult `json:"cohorts"`
		Note         string           `json:"note"`
	}{true, results, "Hypothetical re-costing of supplied frozen action counts; no policies, rankings, capacity decisions or held-out findings changed."})
}
