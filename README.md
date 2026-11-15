# Aegis AI — Hybrid Fraud Intelligence

> A contest-window, solo participant research prototype to compare fraud rules, machine learning and conflict-aware policy on **synthetic PaySim transactions**.

**Status: trained and evaluated locally. Submission has not been completed.**

**Main finding:** on 196,601 held-out transactions, Simple Hybrid detected **502 of 2,148 frauds** and missed **1,646 (76.6%)**. Conflict-Aware improved Average Precision but did not improve F1 or simulated cost over Simple Hybrid. This is a measured trade-off, not a deployment-ready fraud prevention claim.

## Problem / audience
An imagined analyst for a small payment service needs to balance missed suspicious transactions against burdensome reviews. Aegis AI prototypes an explainable policy, not a real payment processing service.

## Architecture
Go (Uber Fx, Zap, chi) API & orchestration -> Python FastAPI ML scoring -> Go JSON AST rules + conflict fusion + cost-aware actions -> Streamlit visualization. See `docs/architecture.md`.

## Run the application

For standalone local execution with Python3.12 and Go1.24+:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r services/ml/requirements.lock.txt
make artifacts
(cd services/orchestrator && go mod download)
```

Then run `make ml-api`, `make go-api` and `make dashboard` in three terminals. Open **http://127.0.0.1:8501**. `AEGIS_API_URL` is a validated server-side setting, defaulting to `http://127.0.0.1:8080`; dashboard visitors cannot change the upstream destination. See [running instructions](docs/running.md).

The live analyzer and scenario lab passed from an isolated publishable source copy after downloading the pinned model, without the raw dataset. That check reused installed dependencies; a fresh-machine dependency installation is not claimed. See [verification evidence](docs/deployment-verification.md).

### Optional Docker Compose packaging

Use Docker Engine with Docker Compose v2.20+ from the repository root:

```bash
docker compose up --build --wait
```

Open **http://127.0.0.1:8501**. Only the web interface is published by default. The web container calls `http://api:8080`; Go calls the internal scorer at `http://ml:8091`. No source-code bind mounts, development reloaders, database or broker are required. Stop the application with `docker compose down`.

Container builds and live Compose checks passed: analyzer, 15 scenario comparisons, dashboard, ML outage/recovery and shutdown. On this Omarchy host, outbound HTTPS through Docker bridge failed, so dependency downloads used **host networking during build only**; runtime networks and isolation follow the original Compose file. For the verified build command and evidence, see the [deployment guide](docs/deployment.md) and [verification record](docs/deployment-verification.md). Packaging does not change the prototype's research limitations.

## Frozen model delivery

The ML image downloads version **`paysim-lr-6035ac438abfb769`** during its build. [The artifact manifest](configs/model-artifacts.json) pins an immutable [GitHub artifact commit](https://github.com/S1m4nger/Aegis/tree/dfd7a087202702c87f1b899b293a0d88f8cb6483/models/paysim-lr-6035ac438abfb769), exact byte sizes and SHA-256 values for the model, calibrator and metadata. Downloads and metadata are checked before installation; the scorer checks model/calibrator hashes again before loading. No floating `latest` model is used.

This controlled public artifact source is a separate artifact-only branch, not a GitHub Release. The files are the unchanged frozen LR outputs. Model binaries and raw PaySim data are not committed to the application source or copied from local files into images. A clean checkout needs internet access for base images, dependencies and this pinned bundle, but no PaySim download or retraining.

## Data

Training/evaluation used the original [PaySim dataset](https://www.kaggle.com/datasets/ealaxi/paysim1): **6,362,620 synthetic rows / 8,213 fraud labels**. Raw data is needed only for a separate training reproduction, not application startup. It is excluded from Git and Docker images. The unrelated `sample_submission` file is excluded. Balance columns and simulator flags are excluded from model features; see [the data contract](docs/data-contract.md).

## Model and experiment
The base model is scikit-learn **Logistic Regression**, followed by a logistic score calibrator fitted on a separate later window. It is a compact, reproducible baseline for imbalanced tabular data. The shared training/inference transform uses only transaction `type`, `amount_log = log(1 + amount)` and `hour = (step - 1) % 24`; type is one-hot encoded and numeric inputs are scaled. Account identifiers, balances, target and simulator flags are excluded from features.

Training uses steps 1–400, calibration 401–470, policy selection 471–550 and final test 551–743. The raw PaySim archive is only needed to audit data preparation or reproduce training. The downloaded frozen model and saved evidence can be used without the raw dataset. Full method: [evaluation protocol](docs/evaluation-protocol.md).

## Results
Final chronological test: **196,601 transactions, 2,148 fraud labels**, steps 551–743. All policies were frozen on selection before one final scoring run. Source: `reports/model_metrics.json` and `reports/final-evaluation.lock`.

| Strategy | Precision | Recall | F1 | Average precision | False alarms / 1,000 |
|---|---:|---:|---:|---:|---:|
| ALWAYS_LEGITIMATE | 0.0000 | 0.0000 | 0.0000 | 0.0109 | 0.0000 |
| ML_ONLY | 0.3108 | 0.1155 | 0.1684 | 0.1437 | 2.7975 |
| RULES_ONLY | 0.9099 | 0.1834 | 0.3053 | 0.1677 | 0.1984 |
| SIMPLE_HYBRID | 0.7893 | 0.2337 | 0.3606 | 0.3068 | 0.6816 |
| CONFLICT_AWARE_HYBRID | 0.7880 | 0.2318 | 0.3583 | 0.3274 | 0.6816 |

The conflict-aware hybrid did **not** outperform the simple hybrid on F1 or simulated cost in any of the three cost scenarios. It had higher ranking Average Precision. Recall remained low: the simple hybrid missed 1,646 frauds; conflict-aware missed 1,650. These are research results on synthetic data, not banking performance claims. Constant-baseline AP equals prevalence; AP is not trapezoidal PR-AUC. See `reports/error_cases.csv`, `reports/drift_metrics.json`, and `reports/decision_experiments.csv` for failures, drift and policy costs.

## Costs and failure cases
Costs are arbitrary scenario units per 1,000 test transactions; actions and capacities were selected on earlier data.

| Scenario | Always legitimate | Simple hybrid | Conflict-aware hybrid |
|---|---:|---:|---:|
| review_low_cost | 10,925.68 | 7,315.41 | 7,339.33 |
| review_expensive | 10,925.68 | 8,456.01 | 8,465.98 |
| missed_fraud_expensive | 54,628.41 | 17,011.87 | 17,056.60 |

For the simple hybrid, a legitimate TRANSFER at step 555 with amount 2,375,178.33 was a false alert; a fraudulent TRANSFER at step 551 with amount 879,321.88 was missed. These amounts are simulated units. Within the held-out period fraud prevalence varied from 0.589% (steps 551–600) to 4.290% (701–743), while recall stayed near 22–25%. No real demographic fairness claim is possible.

## What we added and tested
Beyond a plain fraud classifier, Aegis adds a safe Go JSON rule tree with explanations, explicit rule/ML disagreement groups, a cost-aware review policy under a fixed offline capacity, and the same Go decision functions in the live API and batch experiment. We tested whether these additions improved results over simple rules, ML and weighted fusion. The measured outcome does not establish an advantage for conflict handling over simple fusion.

## Next steps
Validate on a separate public data source to test generalization, and investigate richer features that are demonstrably available before a transaction decision. Any new experiment needs a new validation/test design; the current final test must not be reused to tune parameters.

## Limitations
Synthetic simulator, large temporal prevalence drift, simplistic interpretable input fields, no real cost labels, no privacy/demographic fairness data, not suitable for live blocking. Score is not guaranteed to be probability.

## Licence
The project code is under the [MIT licence](LICENSE), copyright S1m4nger. Permitting reuse of the code does not make downstream users coauthors of this contest entry. PaySim is third-party data, obtained from its original provider and subject to its own licence; it is not distributed in the deployment images or relicensed under MIT. Attribution is recorded in [credits](docs/credits.md).

## Credits
PaySim authors/provider, Go/Python OSS and AI assistants (including ChatGPT and OpenAI Codex) detailed in `docs/credits.md`. This is a SOLO participant entry; no fictitious teammates.

**This project is a prototype and is not financial advice.**
