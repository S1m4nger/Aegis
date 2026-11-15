# Leak-safe experiment protocol and reproducibility gates

## Hypothesis
Does a conflict-aware hybrid system (trained ML signal + independent rule signal + adaptive decision policy) reduce **simulated** decision cost, false alerts or missed fraud compared with plain ML and plain rules, when evaluated chronologically on untouched PaySim transactions?

## Stages
1. Train window 1..400: fit feature transform, categorical encoder, LR (and optional tree model); rule thresholds derived from TRAIN data only. For manageable RAM, retain all fraud + deterministically subsample legitimate training cases; log sampling fraction and seed.
2. Calibration window 401..470: fit post-hoc score mapping only and assess Brier/ reliability diagram. If samples few/drift severe, call scores risk scores and report limitations. Don't assume perfect calibration.
3. Strategy-selection window 471..550: fix any rule parameters, choose between ML, rules, equal/weighted fusion and conflict-aware policies, cost weights; choose thresholds and Top-K budget **once** from here. Use a separate tab in results: `selection`.
4. Final test window 551..743: apply all frozen strategies and thresholds. No retraining, threshold adjustment, or change of rules after looking at test labels. Report all final metrics including failure cases; comparisons use same rows.

## Must-have comparisons
- Always-negative (demonstrates misleading accuracy)
- Rules-only (deterministic JSON AST rules + aggregate heuristic)
- ML-only (LR; optional trees)
- Simple fusion (fixed weight tuned on strategy window)
- Conflict-aware hybrid (explicit disagreement indicator / policy tuned on strategy window)
- Cost-aware policy from the above frozen scores

## Genuine novelty, not claims
- DSL engine AND/OR nesting, traceability and predictable short-circuit behavior.
- Disagreement-specific evaluation table: ML-only-high, Rules-only-high, both-high, both-low. Report counts, fraud prevalence and errors on test without interpreting labels at inference time.
- **Cost under capacity**: assume review budget K per 1000 transactions and choose top-K based on frozen score; distinguish offline batch rank from online decisions.
- Ablation: removing rules, removing conflict policy, removing cost optimizer; measure deltas on same test.
- Temporal robustness: segment test periods without peeking during tuning, show data drift.

## Cost model
A simple transparent scenario:
`cost = FN * missed_fraud_cost + FP * false_alert_cost + REVIEW * review_cost`.
If REVIEW and FP overlap, state that the costs are **incremental** and avoid double-counting; model should more properly use a payoff table per true state × decision:
- APPROVE + legitimate: 0; APPROVE + fraud: L_miss
- REVIEW + legitimate/fraud: C_review + residual fraud if review fails (specify assumed catch rate q)
- FLAG + legitimate: L_false_block; FLAG + fraud: 0 (assume stop success for this scenario)
No claim that a $ threshold is a real bank's cost. Run sensitivity analysis over 3 sets of assumption values.

## Metrics
Classification: precision, recall, F1, average precision, confusion matrix; report accuracy only as context. Rankings: recall@K, precision@K, alert rate. Probability: Brier score / reliability only if calibrated. Policy: simulated costs & cost per 1000, number of reviews, missed fraud.
Confidence: optionally bootstrap by **time blocks** (not IID transaction rows); single synthetic dataset cannot support sweeping external generalization claims.

## Data and experiment artifact contract
- `reports/model_metrics.json`: actual numeric metrics with source partitions, time, seed, model version, exact denominator.
- `reports/decision_experiments.csv`: strategy + scenario + threshold + confusion and cost.
- `reports/error_cases.csv`: redacted feature-only samples, no identifiable account IDs.
- `reports/limitations.md`: observed failure cases and simulator limitations.
- `docs/verification-log.md`: actual tests and commands. No invented test pass or figures.
