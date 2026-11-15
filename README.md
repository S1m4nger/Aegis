# Aegis AI — Hybrid Fraud Intelligence

> A contest-window, solo participant research prototype to compare fraud rules, machine learning and conflict-aware policy on **synthetic PaySim transactions**.

**Status: trained and evaluated locally. Submission has not been completed.**

## Problem / audience
An imagined analyst for a small payment service needs to balance missed suspicious transactions against burdensome reviews. Aegis AI prototypes an explainable policy, not a real payment processing service.

## Architecture
Go (Uber Fx, Zap, chi) API & orchestration -> Python FastAPI ML scoring -> Go JSON AST rules + conflict fusion + cost-aware actions -> Streamlit visualization. See `docs/architecture.md`.

## Data
Source: [PaySim on Kaggle](https://www.kaggle.com/datasets/ealaxi/paysim1), synthetic 6,362,620 rows / 8,213 fraud labels. `sample_submission` zip in original upload belongs to another competition and is excluded. We exclude balance columns and simulator flag to avoid leakage; see `docs/data-contract.md`.

## Reproducible setup
See [running instructions](docs/running.md), [documentation](docs/INDEX.md). Work from the repository root. The verified local environment uses Python 3.12.15 and Go `1.27.3-X:nodwarf5`; Go module minimum is 1.24. CSV/ZIP and trained artifacts are not committed.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r services/ml/requirements.lock.txt
.venv/bin/python scripts/prepare_data.py --zip '/path/to/archive(1).zip'
.venv/bin/python -m services.ml.train --data data/raw/paysim.csv
cd services/orchestrator
go mod download
go run ./cmd/aegis
```

Run the private scorer separately with `.venv/bin/uvicorn services.ml.app:app --host 127.0.0.1 --port 8091` from the root. Training fits the model and calibrator only; it does **not** evaluate final-test performance. See `docs/training.md` for provenance and restrictions.

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

## What was tested
Whether independent rule/ML disagreement-aware handling + cost-aware policy improves decision outcomes compared with standard strategies on held-out time periods. The measured outcome above does not establish an advantage over simple fusion.

## Limitations
Synthetic simulator, large temporal prevalence drift, simplistic interpretable input fields, no real cost labels, no privacy/demographic fairness data, not suitable for live blocking. Score is not guaranteed to be probability.

## Credits
PaySim authors/provider, Go/Python OSS and AI assistants (including ChatGPT and OpenAI Codex) detailed in `docs/credits.md`. This is a SOLO participant entry; no fictitious teammates.

**This project is a prototype and is not financial advice.**
