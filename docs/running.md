# Running Aegis locally

Use repository root, Python3.12 (verified3.12.15), Go1.24+ (verified local toolchain go1.27.3-X:nodwarf5). No database or cloud service is needed. Model/dataset files and virtual environment are intentionally excluded from Git.

## Existing local workspace
The model and data already exist. Start three terminals from the repository root:

```bash
make ml-api
```
```bash
make go-api
```
```bash
make dashboard
```

Private ML:127.0.0.1:8091. GoAPI:127.0.0.1:8080. Streamlit:127.0.0.1:8501. Each command stays running; Ctrl+C stops its process. `.env.example` documents optional Go environment overrides; it is not automatically loaded. Config paths are relative to the Go process directory (`services/orchestrator` for `make go-api`).

## Fresh checkout

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r services/ml/requirements.lock.txt
.venv/bin/python scripts/prepare_data.py --zip '/path/to/PaySim.zip'
.venv/bin/python -m services.ml.train --data data/raw/paysim.csv
cd services/orchestrator
go mod download
```

Download only the PaySim archive from the source credited in README; the script requires the exact original CSV name and header. Never use the unrelated sample submission. Train recreates the source-audited, seeded LR model and calibration, without selection/final predictions. Return to the root before starting the commands above. Existing frozen JSON reports are inspectable without the raw dataset or model.

## Verification

```bash
make verify
make check
.venv/bin/python scripts/demo_check.py
```

The verifier generates explicit temporary test source paths, executes the suites, records results in a local gitignored journal and deletes those sources even on failure. It does not delete data, reports or unrelated tests. Live demo binds temporary loopback services on18080/18091, verifies real inference, batch/API parity using nine synthetic examples, scorer failure503 and graceful shutdown; then stops its services. It never evaluates the held-out dataset. Loopback access may require sandbox permission.

## Frozen final experiment

Final evaluation is complete and protected by `reports/final-evaluation.lock`. Do not delete it or rerun final scoring to choose better thresholds. See `docs/evaluation-run.md` for actual commands, gates and analytical definitions. `make select` is for a new experiment before any selection/final artifacts exist; it deliberately refuses to overwrite the current freeze. To audit these reported results, inspect the manifest, CSV tables and retained local prediction JSONL files; do not retune on the held-out labels. Raw prediction JSONL files remain local and are ignored because they are large.
