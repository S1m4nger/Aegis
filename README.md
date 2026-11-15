# Aegis AI — Hybrid Fraud Intelligence

> A contest-window, solo participant research prototype to compare fraud rules, machine learning and conflict-aware policy on **synthetic PaySim transactions**.

**Status: trained, evaluated and verified locally in Docker Compose. Submission has not been completed.**

**Main finding:** on 196,601 held-out transactions, Simple Hybrid detected **502 of 2,148 frauds** and missed **1,646 (76.6%)**. Conflict-Aware improved Average Precision but did not improve F1 or simulated cost over Simple Hybrid. This is a measured trade-off, not a deployment-ready fraud prevention claim.

## Problem / audience
An imagined analyst for a small payment service needs to balance missed suspicious transactions against burdensome reviews. Aegis AI prototypes an explainable policy, not a real payment processing service.

## Architecture
The application runs as three Docker containers: a Streamlit dashboard, a Go API (Uber Fx, Zap, chi), and a Python FastAPI scorer. Go owns transaction validation, JSON AST rules, conflict fusion and cost-aware recommendations; Python serves the frozen trained model. Only the dashboard is published, at `127.0.0.1:8501`; API and ML communicate over internal Compose networks. See [architecture](docs/architecture.md).

## Build and run with Docker

Requirements: Git, Docker Engine and Docker Compose v2.20+, with access to the
Docker daemon. The first build needs internet access. No local Python/Go setup,
Kaggle account, PaySim download or retraining is needed to run the application.

```bash
git clone https://github.com/S1m4nger/Aegis.git
cd Aegis
docker compose up --build --wait --detach
```

Open **http://127.0.0.1:8501**. Compose builds all three images, downloads and
verifies the pinned model, then waits for ML, API and dashboard readiness. The
analyzer shows the model score, fired rules, disagreement group and recommendation.
The evidence tab shows frozen test results; Cost Lab re-costs saved actions under
hypothetical assumptions without retraining or changing the experiment.

```bash
docker compose ps                       # all three services should be healthy
docker compose logs --tail=100          # inspect startup or readiness failures
docker compose down                    # stop and remove the application containers
```

**Verified build on the development machine:** outbound HTTPS through Docker
bridge failed, while host HTTPS worked. If dependency downloads time out for this
reason, use the build-only host-network alternative:

```bash
docker buildx bake -f compose.yaml --set '*.network=host' --allow network.host --load
docker compose up --no-build --wait --wait-timeout 120 --detach
```

Host networking applies only to the build. Running containers retain the original
Compose networks, non-root users and read-only root filesystems. Only the dashboard
port is published. This build and the live analyzer, 15 scenario comparisons,
dashboard, ML outage/recovery and shutdown passed; see [verification evidence](docs/deployment-verification.md).
The default bridge-network build did not pass on this host.

For standalone Python/Go execution, training reproduction and configuration, see
[running instructions](docs/running.md). Details of model delivery, networking and
operating limits are in the [deployment guide](docs/deployment.md).

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

The Docker build installs pinned runtime dependencies and verifies the frozen model before startup. Container checks exercised actual Go-to-Python inference, input validation, all 15 strategy/scenario cost comparisons and the dashboard analyzer/Cost Lab. With ML stopped, Go returned 503 without an invented score; service recovery and shutdown were also checked. Container packaging does not change the model, frozen policy or reported results.

## Next steps
Validate on a separate public data source to test generalization, and investigate richer features that are demonstrably available before a transaction decision. Any new experiment needs a new validation/test design; the current final test must not be reused to tune parameters.

## Limitations
Synthetic simulator, large temporal prevalence drift, simplistic interpretable input fields, no real cost labels, no privacy/demographic fairness data, not suitable for live blocking. Score is not guaranteed to be probability.

## Licence
The project code is under the [MIT licence](LICENSE), copyright S1m4nger. Permitting reuse of the code does not make downstream users coauthors of this contest entry. PaySim is third-party data, obtained from its original provider and subject to its own licence; it is not distributed in the deployment images or relicensed under MIT. Attribution is recorded in [credits](docs/credits.md).

## Credits
PaySim authors/provider, Go/Python OSS and AI assistants (including ChatGPT and OpenAI Codex) detailed in `docs/credits.md`. This is a SOLO participant entry; no fictitious teammates.

**This project is a prototype and is not financial advice.**
