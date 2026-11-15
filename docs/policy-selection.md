# Selection-only policy tuning

`internal/policy/selection.go` provides offline helpers for the strategy-selection window. Callers must pass only rows from steps 471–550. Do not use these optimizers on final-test labels.

`Observation` contains a score, a fraud label, and the PaySim simulation step. The score is the frozen strategy's ranking signal and may be a heuristic; the optimizer does not assume it is a probability. The classification optimizer searches distinct positive observed scores plus `1`, maximizes F1, and breaks exact ties by fewer false positives and then the higher threshold.

Cost tuning searches review and flag thresholds from the configured fixed grid (`0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.999, 1`) plus linear score quantiles (`0.50, 0.75, 0.90, 0.95, 0.99`) calculated from selection rows. Only pairs with `review < flag` are evaluated. Each pair first generates actions, then applies the scenario's per-step review capacity, then sums the existing hypothetical payoff table. `ClassificationThreshold` is copied unchanged. The first minimum-cost pair in sorted grid order wins ties, making the result deterministic.

Capacity is calculated independently per simulation step as `floor(rows_in_step * capacity_per_1000 / 1000)`. It ranks only REVIEW actions by descending frozen score; original row order breaks score ties. Overflow reviews become APPROVE. FLAG actions stay unchanged and do not consume review capacity. Labels are not consulted when ranking.

Inputs must be nonempty, contain both classes, have positive steps and finite scores in `[0,1]`. Cost tuning also validates the base policy and scenario. These are offline experiment helpers; the resulting thresholds must be frozen before final-test evaluation. Cost values are hypothetical scenario assumptions, not real bank costs.
