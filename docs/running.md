# Running Aegis

The final application uses the frozen Logistic Regression model, unchanged Go
rules/fusion/cost policy and Streamlit dashboard. No raw PaySim data, training or
new final evaluation is needed to start it.

## Standalone local execution

Use Python3.12 (verified local3.12.15) and Go1.24+. From the root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r services/ml/requirements.lock.txt
make artifacts
(cd services/orchestrator && go mod download)
```

`make artifacts` downloads and checks the immutable bundle described in
`configs/model-artifacts.json`. A matching existing bundle is verified and reused;
different/incomplete existing files are not overwritten. Check without networking:

```bash
.venv/bin/python scripts/fetch_model.py --check
```

Run each command in its own terminal:

```bash
make ml-api
```

```bash
make go-api
```

```bash
make dashboard
```

ML listens on127.0.0.1:8091, Go on127.0.0.1:8080 and Streamlit on127.0.0.1:8501.
Ctrl+C stops each standalone service. `AEGIS_API_URL` defaults to
`http://127.0.0.1:8080`; environment variables for standalone commands must be
exported explicitly because `.env.example` is documentation, not an automatic
shell loader. Go config paths remain relative to its process directory for
`make go-api`; Compose supplies explicit absolute paths instead.

## Docker Compose

Install Docker Engine and Docker Compose v2.20+ with access to the local Engine.
From the repository root:

```bash
docker compose up --build --wait
```

Open **http://127.0.0.1:8501**. Only web is published. Go and ML are internal
services; container communication uses `api:8080` and `ml:8091`, not localhost.
Check state and stop with:

```bash
docker compose ps
docker compose logs --tail=100
docker compose down
```

Compose reads `AEGIS_WEB_BIND` and `AEGIS_WEB_PORT` from the shell or project
`.env`; defaults are `127.0.0.1` and `8501`. `.env.example` contains no secrets.
The Docker deployment sets the dashboard's server-owned `AEGIS_API_URL` to
`http://api:8080`; there is no public API-address input. See [deployment.md](deployment.md)
for the network, image, artifact and readiness contracts.

Container builds and live Compose behavior passed. On this Omarchy host the default
Docker bridge could not reach dependency registries, while the host could. The
verified build-only workaround is:

```bash
docker buildx bake -f compose.yaml --set '*.network=host' --allow network.host --load
docker compose up --no-build --wait --wait-timeout 120 --detach
```

This changes build networking only. Runtime services retain the original Compose
networks, non-root users and read-only root filesystems. Default bridge-network
builds have not passed on this host. See [deployment-verification.md](deployment-verification.md)
for actual successes, initial failures and remaining limits.

## Optional training reproduction

Download the original [PaySim archive](https://www.kaggle.com/datasets/ealaxi/paysim1)
separately and use the existing strict preparation script:

```bash
make prepare DATA_ZIP='/path/to/archive(1).zip'
```

Keep the provider's licence/attribution and exclude the unrelated sample
submission. To reproduce training without overwriting frozen artifacts/reports:

```bash
.venv/bin/python -m services.ml.train --data data/raw/paysim.csv \
  --artifact-dir data/cache/reproduction/artifacts --report-dir data/cache/reproduction/reports
```

This fits only the declared training/calibration windows. It does not authorize
another final evaluation or tuning on held-out labels. Do not use the default
training output paths to replace the published frozen model.

## Existing research verification

`make verify` generates temporary test sources, runs them, records actual results
and removes those exact sources even after failure. `make check` checks submission
files. The public historical record is [verification-summary.md](verification-summary.md).
The live demo checker uses temporary loopback services and may require sandbox
socket permission; it writes a demo report, so it is not part of immutable
deployment evidence. Neither training nor the demo reruns the final test.

Final evaluation remains protected by `reports/final-evaluation.lock`. Do not
delete it, rerun final scoring or choose thresholds using its labels. `make select`
deliberately refuses to overwrite the current selection freeze. Inspect the saved
reports/manifests rather than mutating completed evidence; see [evaluation-run.md](evaluation-run.md).
