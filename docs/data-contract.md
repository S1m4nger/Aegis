# Dataset contract — VERIFIED by direct inspection

Source input: uploaded `archive(1)(1).zip`, member `PS_20174392719_1491204439457_log.csv` (PaySim). `sample_submission.csv(1)(1).zip` is NOT this dataset: that file has `TransactionID,isFraud`, implying a different competition and cannot be joined. Preserve source provenance.

Official PaySim dataset: https://www.kaggle.com/datasets/ealaxi/paysim1 — synthetic/mobile money simulation derived from aggregated real-data patterns. No assertions of real banking effectiveness. Main data rows: **6,362,620**. Fraud labels 8,213 (0.1291%), legitimate 6,354,407. `step` observed 1..743. Nulls: zero in all 11 columns on uploaded CSV. Counts: PAYMENT 2,151,495; CASH_OUT 2,237,500; CASH_IN 1,399,284; TRANSFER 532,909; DEBIT 41,432. `isFlaggedFraud=1` in only 16 rows.

## Original CSV columns
`step`, `type`, `amount`, `nameOrig`, `oldbalanceOrg`, `newbalanceOrig`, `nameDest`, `oldbalanceDest`, `newbalanceDest`, `isFraud`, `isFlaggedFraud`.

## STRICT feature allowlist for primary modeling and rule engine
- `type` categorical: `CASH_IN`, `CASH_OUT`, `DEBIT`, `PAYMENT`, `TRANSFER`.
- `amount` numeric >=0 (be careful not to infer currency; simulated monetary unit).
- `step` integer observed 1..743; represents simulator hours. Use `step % 24` only if justified, and don't pretend real calendar date/time.
- Derivatives of those **known-at-decision-time** features: log amount, transaction type × log amount, hour-of-simulation, thresholds fit on TRAIN ONLY.

## STRICT excluded columns
- `isFraud`: target only, never a feature.
- `isFlaggedFraud`: simulator's flag / leakage or trivial proxy; exclude from model and rules (can be described in EDA only).
- `oldbalanceOrg`, `newbalanceOrig`, `oldbalanceDest`, `newbalanceDest`: PaySim official description warns these balance columns should not be used for fraud detection due to canceled flagged transactions (possible target leakage). Exclude all four from **primary** model and demo rules.
- `nameOrig`, `nameDest`: high-cardinality account identifiers, potential identity leakage; exclude from primary model. Only separate causal-history research with strong proof could use precomputed history; not required this weekend.

## Chronological partition — STRICT
- Train: steps 1..400 | **5,787,030 rows, 4,477 fraud**.
- Calibration: steps 401..470 | derive exact count from data at run time; fit score mapping/calibrator (not final test).
- Strategy selection: steps 471..550 | derive exact count; tune rule thresholds, fusion weights, review policy, costs.
- Final untouched test: steps 551..743 | **196,601 rows, 2,148 fraud**.

Calibrator and strategy selection MAY NOT see final test labels. Use source rows as-is for evaluation. Downsample negatives only while FITTING training, never in calibration/strategy/test. `step` itself not part of the base model if it risks learning the simulator timeline instead of transaction patterns; time index remains for split and drift reporting.

## Confirmed drift
- Steps 1..400: fraud prevalence 0.0774%.
- Steps 401..550 combined: 0.4190%.
- Steps 551..743: 1.0926%.
This is a major distribution shift; do not claim calibration at a given period generalizes unchanged. Show rate and precision/recall per segment.

## Evaluation proof
- Always-report fraud prevalence, class counts, confusion matrix, Precision, Recall, F1, Average Precision (`average_precision_score`), FPR, alerts per 1k transactions, simulated cost per 1k, and one false positive + one false negative if found.
- Report cohort metrics by transaction type and chronological interval when enough positives.
- Do not compare models on differently filtered or differently sampled test subsets.
- No true fairness conclusions: PaySim lacks real demographic attributes.

## Current workspace provenance
Actual supplied archive in this machine: `/home/souslacroix/Downloads/archive(1).zip`; exact member/header validated at bootstrap. The duplicated `(1)` spelling above is the original starter provenance, not a different dataset. Current CSV SHA256: `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b`. Fresh allowlisted-column audit and all partition counts are in `reports/data_audit.json`. Calibration:240374/796frauds; selection:138615/792frauds; final:196601/2148frauds. Claims about all11columns/flagcounts in the original starter are inherited inspection notes; the new audit validates only the reader's approved fields and target, not all excluded columns.

The feature `hour=(step-1)%24` is a predefined simulator-hour proxy to capture possible cyclic patterns without using absolute future step; it is not a real calendar variable. Its inclusion and the full feature schema were fixed before final evaluation; no temporal test tuning.
