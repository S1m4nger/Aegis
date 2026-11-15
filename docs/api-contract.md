# Contracts v1: Go API and Python scorer

## Public Go
`POST /v1/analyze`
Request:
```json
{"step": 400, "type": "TRANSFER", "amount": 191234.25}
```
Success (field structure; numbers illustrative ONLY):
```json
{
  "schema_version": "1.0",
  "model_version": "trained-artifact-version",
  "ml_score": 0.27,
  "rule_score": 0.61,
  "fusion_score": 0.44,
  "conflict_type": "RULES_ONLY_HIGH",
  "recommended_action": "REVIEW",
  "reasons": ["large_transfer"],
  "disclaimer": "This project is a prototype and is not financial advice."
}
```
Do not present an uncalibrated ML/rule/fusion score as objective fraud probability. Responses are explanations for a research prototype and no real card/account is affected.

`GET /health/live` → `200` process alive. `GET /health/ready` → `200` only if scorer artifact loaded/readiness valid; `503` otherwise. `/v1/experiment-summary` can serve frozen results once created, not manufactured numbers. `/v1/simulate` may be a stateless **explicitly scenario-only** endpoint if implemented.

Validation: `type ∈ {CASH_IN,CASH_OUT,DEBIT,PAYMENT,TRANSFER}`, `amount` finite >=0 and <= documented maximum, `step` positive integer. Max request body 64KB. Unknown JSON keys are rejected. 400 for invalid user input; 503 for scorer unavailable; 500 for unexpected internal error without exposed traces. Return `application/json`; configure timeouts, bounded body and HTTP retries only for safe idempotent operations.

## Private Python
`POST /internal/v1/score`, identical input fields, returns:
```json
{"score":0.27,"model_version":"v1","score_semantics":"calibrated_probability_estimate"}
```
Score values in this schema illustrate shape, not real results. `GET /health/ready` returns 503 if artifact absent; Go must respect that. Keep loopback binding by default. Model and calibrator are loaded only from trusted locally created artifacts; no arbitrary client-supplied paths.

## Idempotency / logging
No writes or transactions. Do not log source account IDs, personal information or whole payloads. Log request id, latency, error code, model/decision versions and conflict type; no invented user identity.

## Verified transport changes
All three fields `step`, `type`, `amount` are required and non-null, including zero-valued amount. JSON strings/booleans cannot substitute numeric fields. The Go service depends on a scoring interface injected by Fx. ML responses must contain a finite score, nonempty model version and score semantics; missing/null scores and trailing JSON fail. Readiness requires the scorer's JSON ready flag and model version, not HTTP 200 alone.

Live verification on loopback used the actual trained model: healthy endpoints 200, absent amount 400, stopped Python scorer caused readiness and analysis 503, Go terminated gracefully with exit 0. The resulting synthetic demonstration response is saved in `reports/demo.json`; it is not experimental performance evidence.

## Stateless frozen-action scenario endpoint
`POST /v1/simulate` accepts `scenario` (id, missed_fraud_cost, false_block_cost, review_cost, review_success_rate, capacity_per_1000) and up to 20 `cohorts` with strategy, rows, frauds, review, fraud_approved_misses, fraud_sent_to_review, fraud_flagged and legitimate_flagged. All counts are required nonnegative integers; rows >0, max 1e9. Counts must form a consistent true-state/action table. Costs finite in [0,1e9], success rate [0,1], capacity [0,1000]. Unknown/null/missing fields are rejected; body limit64KiB.

Go reuses the scenario payoff table to re-cost supplied aggregate actions. Response: scenario_only=true, cohorts[{strategy,rows,total_simulated_cost,cost_per_1000}], explanatory note. It performs no inference, threshold selection, ranking or writes. Capacity is validated metadata; supplied actions remain fixed. Changing costs does not recompute capacity or recommendations. The dashboard chooses one original frozen action scenario as its base and varies only payoff assumptions. The endpoint stays available when the ML scorer is unavailable, because it needs only supplied counts.
