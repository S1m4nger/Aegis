# PaySim training and calibration

Run from the repository root after preparing `data/raw/paysim.csv` and installing `services/ml/requirements.txt` into `.venv`:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m services.ml.train --data data/raw/paysim.csv
```

The pipeline first validates the exact 11-column PaySim header and scans the source in 250,000-row chunks. It checks that each row has an allowed transaction type, finite amount in `[0, 1e12]`, integer step in `[1, 743]`, and binary `isFraud` label. It writes per-window row, label, and transaction-type counts to `reports/data_audit.json`.

Chronological windows are fixed: train `1–400`, calibration `401–470`, strategy selection `471–550`, and final test `551–743`. All train frauds are retained. Legitimate train rows are sampled deterministically with a hard cap of 200,000, allocated proportionally across CSV chunks. The fitted model sees only the train sample. A separate logistic mapping is fitted on model logits from the calibration window.

Selection and final-test records are not materialized as partition dataframes by training. The pipeline does not score either window or choose a strategy/threshold. It only records their audit counts; task 05 must perform strategy selection and final evaluation using frozen artifacts. Model artifacts are written under `services/ml/artifacts/`; `metadata.json` records full SHA-256 hashes for the source, model, and calibrator, feature schema, version, and score semantics. `reports/training.json` records the run provenance, fit-sample quantiles for proposed TRANSFER/CASH_OUT rule cutoffs, and confirms that final-test predictions were not computed.

The logistic baseline uses the existing feature schema `type`, `amount_log`, `hour`. Amount and step live-input bounds align with the API schema (`1e12` and `1,000,000` respectively); the source audit applies the narrower observed PaySim step domain `1–743`. Calibration scores can drift as prevalence changes over simulator time. No result in these audit/training files is evidence of final-test model quality.

## Verified run

On 2026-11-15, the pipeline processed 6,362,620 source rows. The audit found 5,787,030 train rows / 4,477 frauds, 240,374 calibration rows / 796 frauds, 138,615 selection rows / 792 frauds, and 196,601 final-test rows / 2,148 frauds. Fit used all 4,477 train frauds and exactly 200,000 of 5,782,553 legitimate train rows (seed 42). Selection and final test were not scored. Model version: `paysim-lr-6035ac438abfb769`. Python 3.12.15, scikit-learn 1.9.1, pandas 2.3.3, NumPy 2.5.4, joblib 1.6.0. Full source/model/calibrator hashes are recorded in `services/ml/artifacts/metadata.json` and `reports/training.json`.
