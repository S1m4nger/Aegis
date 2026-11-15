# Dashboard — task 06

The Streamlit dashboard is a presentation layer. It does not load model artifacts, evaluate rules, fuse scores, optimize thresholds or calculate scenario cost formulas. It reads actual finalized reports and calls the Go API for transaction recommendations and scenario recosting. The immutable final experiment/config/evaluator source files were not modified for this work.

## Run

From the repository root, with Go on loopback8080 and the trained private scorer running:

```bash
.venv/bin/streamlit run app/dashboard.py
```

`.streamlit/config.toml` selects the dark navy theme, orange accent, loopback binding and disabled usage telemetry. The sidebar Go API address can be changed; requests occur only after explicit form submission. No readiness/network requests are made during initial rendering.

## Views

1. **Transaction analyzer** accepts synthetic type/amount/simulation step. It calls `POST /v1/analyze` and displays returned ML/rule/fusion scores, Go action, conflict, fired-rule trace and model/policy versions. Zero/invalid score substitution is never used; missing or malformed API data shows an unavailable state. Last successful input is labeled explicitly.
2. **Measured evidence** reads `model_metrics.json`, `pr_curve.json`, `drift_metrics.json`, `decision_experiments.csv` and `error_cases.csv`. It shows all five strategies on the same held-out denominator, sampled PR curves, confusion counts, temporal/type/conflict cohorts, cost-optimizer ablation, review capacity/top-K diagnostics and actual FP/FN examples. It states the observed trade-off: simple hybrid has higher F1 than conflict-aware while conflict-aware has higher AP; recall remains low and no universal hybrid superiority is claimed. Classification alerts and cost-policy actions are labeled separately.
3. **Conflict & cost lab** selects one saved final-action cohort. Sliders change only hypothetical missed-fraud/false-block/review costs and review catch assumptions. Capacity remains read-only at the saved scenario's value. The form sends `scenario` plus five saved aggregate `cohorts` to Go `/v1/simulate`. The response must declare `scenario_only: true`. No model scoring, reranking, threshold change, inference formula or report write occurs in the dashboard.

API scenario request fields: `scenario:{id,missed_fraud_cost,false_block_cost,review_cost,review_success_rate,capacity_per_1000}`, `cohorts:[{strategy,rows,frauds,review,fraud_approved_misses,fraud_sent_to_review,fraud_flagged,legitimate_flagged}]`. Expected Go response: `{scenario_only:true,cohorts:[{strategy,rows,total_simulated_cost,cost_per_1000}],note}`.

## Failure handling and fixture boundary

Missing/corrupt reports show clear empty/error states; no charts are fabricated. `AEGIS_REPORTS_DIR` can redirect report reads for isolated UI tests. Tests used temporary fixtures or read existing finalized files without overwriting them. API transport uses bounded JSON reads, finite score validation and timeout/error handling. Account IDs, balances and labels cannot be entered for live analysis.

## Actual verification

Initial `AppTest.from_file('app/dashboard.py',default_timeout=20).run()` on real reports had no exceptions, rendered three main tabs (plus four evidence subtabs) and both submit forms. No long-running server was started.

`/home/souslacroix/Aegis/.venv/bin/python -m pytest -q -p no:cacheprovider app/test_dashboard_ephemeral.py` — exit 0
```text
........                                                                 [100%]
8 passed in 3.90s
```

Eight ephemeral AppTests passed: actual measured initial render with network forbidden, absent reports, three corrupt-report shapes, unavailable API with no fallback, returned Go analyzer data/action, and scenario request/five cohort invariants/report-byte preservation. `app/test_dashboard_ephemeral.py` and the temporary source staging file were removed in finally; bytecode/cache writes disabled. Mock API numbers existed only as test fixtures and were never saved as experiment evidence.

Context7 `/streamlit/docs` consulted for installed Streamlit1.67.0 forms, tables and AppTest interactions (current official docs; no exact1.67 index). Plotly6.9.0 uses previously verified graph_objects APIs. Local Graphify `graphify query 'dashboard plotly scoreRows' --budget 900` exited0 and exposed dashboard/evaluator relationships; output truncated37/69nodes, then source/report contracts were inspected directly. Parent refreshes the graph after integration.

Integration completed: live Go `/v1/simulate` matched all15 frozen strategy/scenario costs; AppTest analyzer and lab called the real Go/Python services. Independent review found two nested-malformed-data paths; dict guards/strategy uniqueness added and four regression cases passed in the final21-test combined suite. AppTest verifies rendering and contracts; it is not a visual screenshot review or proof of public deployment.
