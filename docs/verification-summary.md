# Public verification summary

Completed local runs on **2026-11-15** are summarized here. This document does not claim the commands were rerun when the documentation was edited. The detailed development journal is local and gitignored.

## Commands and recorded results

From the root, after installing the locked dependencies, use `make verify`, `make check` and `.venv/bin/python scripts/demo_check.py`.

| Exact recorded command | Result | Coverage |
|---|---|---|
| `bash scripts/verify-and-clean.sh` | Exit 0 | Generated Go regression suite and `go vet ./...` passed; combined Python inference/UI contracts: **21 passed** |
| `go test -v ./cmd/evaluate` from `services/orchestrator`, with temporary tests present | Exit 0; **2 passed** | Strict offline inputs, batch policy/action parity, label-independent top-K, selection windows and malformed bundles |
| `.venv/bin/python -m pytest -q -p no:cacheprovider services/ml/test_evaluator_ephemeral.py` | Exit 0; **4 passed** | Exclusive final lock, source tampering, window isolation and known metrics/cost/top-K fixtures |
| `.venv/bin/python -m pytest -q -p no:cacheprovider app/test_dashboard_ephemeral.py` | Exit 0; **8 passed** | Measured rendering, missing/corrupt reports, API errors, analyzer responses and scenario/report preservation |
| `.venv/bin/python scripts/demo_check.py` | Exit 0 | Real Go→Python→Go inference, nine API/batch probes, all 15 strategy/scenario costs, live UI analyzer/Cost Lab, missing scorer 503, missing field 400 and graceful stop 0 |
| `make check` | Exit 0 | Required public documents/disclaimer and absence of temporary test sources; static packaging check only |

`make verify` creates explicit temporary test paths and removes them in `finally`, even after failure. The separate evaluator/dashboard commands above used temporary sources that are now removed; direct `go test` after cleanup does not execute them. Suite counts overlap and must not be added into one total. Initial wrong-directory/interpreter calls and regression failures were corrected before the passing runs; see [evaluation-run.md](evaluation-run.md) and [dashboard.md](dashboard.md).

## Experiment evidence

Selection used **138,615 rows / 792 frauds**; the one-shot final test used **196,601 rows / 2,148 frauds**. Both real evaluation commands exited 0. Source/model/configuration fingerprints and raw final-prediction SHA-256 matched the completed [final lock](../reports/final-evaluation.lock). Confusion/action denominators, 15 strategy/scenario rows and 45 redacted error examples were checked.

[demo.json](../reports/demo.json) records the live checks and unchanged report bytes during re-costing. Simple Hybrid detected **502 / 2,148** frauds and missed **1,646 (76.6%)**. Conflict-Aware has higher AP, but lower F1 and higher hypothetical cost than Simple Hybrid.

## Limits

- These are local synthetic-data results, not production banking effectiveness or observed savings.
- A complete fresh-machine installation is not established by the recorded runs. AppTest is not browser-pixel or public-hosting verification.
- Offline review capacity differs from unbounded single-transaction recommendations. Cost Lab changes assumptions for saved actions; it does not retune or rerank.
- No public hosted application, recorded video or official submission confirmation is asserted.
- The bundled trained artifacts support live analysis without raw data. PaySim retains its own dataset licence, separately from MIT-licensed code.

Preserve the completed final lock. Do not rescore or tune on the held-out data to obtain a better result.

## Delivery repair verification — 2026-11-15 UTC

`make verify` passed after the packaging repairs: Go tests/vet and **56 Python tests**.
This includes API-origin/HTTP contracts and model-download integrity/no-overwrite
cases, plus the original inference/UI checks. Temporary test sources were removed.
The current `.venv/bin/python scripts/demo_check.py` exited 0 after correcting
script-local imports and configuring its API origin through the environment.
The demo checks nine API/batch probes, 15 scenario comparisons, analyzer/Cost Lab,
400/503 failures and graceful shutdown. Its first attempt exposed the import defect
and exited 1; this was corrected and rerun, not skipped.

Fresh artifact download passed outside the sandbox. At that earlier checkpoint,
Docker Engine access failed; access was later restored and container qualification
passed as recorded in the next section. See [deployment verification](deployment-verification.md) for the isolated
source qualification and remaining container checks. The final test was not rerun.

## Container qualification — 2026-11-15 UTC

All three images built using fresh runtime dependency layers and a pinned model
download. On this host default Docker bridge outbound HTTPS failed; the successful
build used `docker buildx bake -f compose.yaml --set '*.network=host' --allow network.host --load --metadata-file reports/generated/docker-build-metadata.json` (exit0).
The original Compose runtime was started with
`docker compose up --no-build --wait --wait-timeout 120 --detach` (exit0).

Actual container checks passed: three healthy non-root/read-only services, only
loopback8501 published, real inference, input/label rejection400, 15 scenario
comparisons, live dashboard analyzer/CostLab, ML outage503 with no fabricated score,
recovery and shutdown. `docker compose stop` exited0; API/web exited0, ML exited143
following logged complete application shutdown on SIGTERM. No OOM or forced kill.
Original report bytes were unchanged. Temporary executable source was removed.
See [deployment verification](deployment-verification.md) for corrected initial
permission failures, test-assertion failures and exact qualifications.
