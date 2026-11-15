# Evaluation runner — task 05

Status: implementation and synthetic regression checks ready for parent review/real selection. No real selection, final scoring or model fitting was run by this worker. Parent owns those acceptance gates.

## Entry points and immutable evidence

- `.venv/bin/python -m services.ml.evaluate --select-only` reads steps471–550, scores the trained model, and invokes Go select/score. It writes selected rules/policy, selection bundle/metrics/predictions and a fingerprint manifest. Python and Go both refuse overwriting existing selection/final locks.
- `.venv/bin/python -m services.ml.evaluate --final --confirm-final` checks all frozen fingerprints, creates the exclusive durable final lock before reading test-window labels, then scores551–743 once. Existing lock/report prevents repeat scoring. Never remove the lock to tune on test.
- `_summarize` and report writers can regenerate analytical evidence from retained prediction JSONL without model inference. Preserve the final lock/raw predictions if a reporting repair is needed; do not rescore or change frozen decisions.

The current CSV hash is checked against training provenance; model/calibrator are loaded from the exact verified bytes. Offline input requires all5 explicit fields (step/type/amount/fraud/ml_score). All5 classification and scenario cost configs must exist and validate; cost policies cannot change scoring/classification parameters. Go validates the selected/final step window separately.

## Policy and report semantics

Go owns rules, fusion, classification, actions, capacity and hypothetical loss. Python supplies ML scores and computes evidence metrics only. API parity compares `unbounded_actions`; online recommendations have no global queue state. Offline capacity is per simulator step: floor(step_rows*capacity_per_1000/1000). Scores select REVIEW rows with original-index tie-break; labels do not select rows; excess reviews become APPROVE and FLAG is preserved.

Go adds3 fields per strategy/scenario:
- `default_actions_without_cost_optimizer` and `default_simulated_losses`: ablation using fixed default action cutoffs REVIEW.35/FLAG.8 from the frozen classification policy, the same scores/scenario/capacity. These cutoffs are distinct from the F1 classification threshold.
- `top_k_selected`: a separate diagnostic ranking every row by frozen score within the simulator step using the same budget. Baseline scores are constant, so its ranking is source-order ties, not learned signal.

Python cost summaries include optimized/default counts and costs; delta_per1000 is optimized minus default (negative favors optimizer); approved fraud misses, fraud reviewed/flagged, legitimate flags; review and top-K precision/recall; exact selected and default action thresholds. Classification alerts and policy actions remain distinct. CSV includes classification, review and flag thresholds, cost-ablation and top-K evidence.

`model_metrics.json` includes source/model/frozen fingerprints, seed, dependency versions, partition counts and feature names, plus all5 strategies and3scenarios. False alarms and alerts per1000 use all source rows. AP is sklearn.average_precision_score, not trapezoidal PR-AUC; constant-score baseline AP equals prevalence. Only ML gets Brier/reliability diagnostics. Drift/type/conflict tables and sampled PR curves are separate artifacts. Error examples retain up to5FP and5FN per strategy including amount/type/step, never account identifiers.

Summary aggregation streams prediction JSONL and retains compact numeric arrays for ranking metrics, not all nested row dictionaries. This avoids several GB of Python dictionary memory.

## Actual worker verification

Local Graphify query `graphify query 'scoreRows _summarize OptimizeCosts ApplyCapacity' --budget 1800` exit0, returned78 of116 nodes including shared Go optimizer/capacity and Python summary/final paths; source confirmed relevant relationships. No exposed Graphify MCP. Context7 `/scikit-learn/scikit-learn/1.9.1` consulted for installed1.9.1 AP/PR APIs; focused response mostly returned versioned release/glossary material, and metrics were verified by local fixtures. No new dependency.

`GOMODCACHE=/tmp/aegis-go-mod GOCACHE=/tmp/aegis-go-build go vet ./cmd/evaluate` from services/orchestrator exited0. Go build to /tmp/aegis-evaluate-check exited0. Initial `go test ./cmd/evaluate` issued at repository root failed because Go module is nested; corrected module-directory call passed.

`go test -v ./cmd/evaluate` — exit 0
```text
=== RUN   TestOfflineInputRejectsMissingNullAndUnknown
--- PASS: TestOfflineInputRejectsMissingNullAndUnknown (0.01s)
=== RUN   TestFrozenBatchActionsAblationRankingAndGuard
--- PASS: TestFrozenBatchActionsAblationRankingAndGuard (0.00s)
PASS
ok  	aegis/orchestrator/cmd/evaluate	0.015s
```

`/home/souslacroix/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12 -m pytest -q -p no:cacheprovider services/ml/test_evaluator_ephemeral.py` — exit 1
```text
/home/souslacroix/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12: No module named pytest
```

`/home/souslacroix/Aegis/.venv/bin/python -m pytest -q -p no:cacheprovider services/ml/test_evaluator_ephemeral.py` — exit 0
```text
....                                                                     [100%]
4 passed in 1.80s
```

The first Python invocation resolved the venv symlink and invoked the base interpreter lacking pytest. Rerun with the actual .venv/bin/python path passed4/4. This was a test-runner invocation error, not a skipped check.

Temporary source manifest: services/orchestrator/cmd/evaluate/zz_evaluator_ephemeral_test.go and services/ml/test_evaluator_ephemeral.py. Both removed in finally even on failure; bytecode/cache generation disabled. Temporary /tmp staging text files containing source were also removed by exact path. No dataset, artifact, report or user-authored tests deleted.

Parent must record these actual commands/results in docs/verification-log.md, review frozen selection and live API/batch parity, then run final once. Draft/source tests alone do not establish final experiment acceptance.

## Completed run
Selection used138615 rows and792 fraud labels; final test used196601 rows and2148 fraud labels. Both CLI runs exited0. API/batch parity passed on nine synthetic selection-window inputs before final scoring. Final hashes and all confusion/action denominators were verified. The detailed local development journal is intentionally excluded from Git; reproducible methods and measured evidence are retained here, in evaluation-protocol.md and reports/.
