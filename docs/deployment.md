# Container deployment

The deployment packages the final frozen LR application without changing its
ML inference, Go rules/fusion/cost decisions or measured reports. HGB experiments
and their runtime were removed from the final application tree. Original final
reports/lock and frozen ML artifacts remain unchanged.

**Verification status:** all three images built and live Compose checks passed:
ML/API/web readiness, actual inference, 15 scenario comparisons, dashboard analyzer
and Cost Lab, ML outage/recovery, port boundaries and shutdown. Default Docker
bridge outbound HTTPS failed on this host, so dependency downloads used a build-only
host network override. Runtime services retain the original networks and controls.
See [deployment-verification.md](deployment-verification.md) for exact evidence.

## Start and stop

From a clean checkout with Docker Engine/Compose v2.20+:

```bash
docker compose up --build --wait
```

Open **http://127.0.0.1:8501**. Inspect with `docker compose ps` and
`docker compose logs --tail=100`; stop with `docker compose down`.
The first build needs internet access for pinned base images, dependency
artifacts and the frozen model. No Kaggle account, raw data or training is needed.

If Docker bridge outbound HTTPS is unavailable but host HTTPS works (as observed
on this Omarchy host), the verified alternative is:

```bash
docker buildx bake -f compose.yaml --set '*.network=host' --allow network.host --load
docker compose up --no-build --wait --wait-timeout 120 --detach
```

The explicit entitlement grants host networking to build steps only. This does
not publish Go/ML ports or change the application's runtime network mode. The
network issue is not hidden by disabling checks or changing dependency versions.


## Three service boundaries

| Service | Runtime | Responsibility | Connections |
|---|---|---|---|
| web | Python3.12 / Streamlit | Transaction form, saved evidence and scenario presentation | `http://api:8080` |
| api | Static Go binary, Fx/Zap/chi | Validation, rules, fusion, actions and scenario costs | `http://ml:8091` |
| ml | Python3.12 / FastAPI | Frozen LR feature transform, calibration and inference | Internal scorer only |

Only web has a host port. The default binding is loopback8501; change it with
operator-owned `AEGIS_WEB_BIND`/`AEGIS_WEB_PORT` when intentionally needed. API and
ML are not published to the host. The internal backend network contains API/ML;
the frontend network contains web/API. Compose waits for ML readiness before
API, and API readiness before web. An unhealthy dependency is not an automatic
replacement model or a promise of automatic health-based restarts.

`AEGIS_API_URL` is validated server configuration, never visitor input. Its local
standalone default is `http://127.0.0.1:8080`; Compose sets `http://api:8080`.
Only known dashboard routes are called and redirects are rejected. Go binds
`0.0.0.0:8080`, uses the service-discovery ML URL and explicit
`/app/configs/rules.json` and `/app/configs/policy.json` paths. The default policy
remains `CONFLICT_AWARE_HYBRID`; the underlying trained model remains LR.

## Reproducible images

The three Dockerfiles build independently from an allowlisted root context.
Official Go1.27.3-bookworm and Python3.12.15-slim-bookworm bases are pinned by
immutable digests in the Dockerfiles. Go uses a multi-stage build with a static
binary and static readiness probe, copied into a non-root scratch runtime.
Python dependencies are installed from runtime subsets constrained by the
unchanged existing `services/ml/requirements.lock.txt`. ML omits dashboard/test
packages, and web omits ML/test packages.

All runtimes use non-root users. Compose enables init/signal forwarding, graceful
stop periods, restart policies, read-only root filesystems, bounded tmpfs writes,
resource limits, dropped capabilities and no-new-privileges. There are no source
bind mounts or development reloaders. These are deployment controls for a local
research prototype, not evidence of load-tested banking deployment.

Packaged Go configuration and dashboard evidence files explicitly belong to
runtime UID/GID `10001:10001`. Generated reports/configuration can be `0600` on
the development machine; preserving that mode with root ownership prevents the
runtime user from reading them. Compose's read-only root filesystem prevents
modification of the packaged files.

## Frozen model source

Version **`paysim-lr-6035ac438abfb769`** is distributed from a controlled public
[artifact commit](https://github.com/S1m4nger/Aegis/tree/dfd7a087202702c87f1b899b293a0d88f8cb6483/models/paysim-lr-6035ac438abfb769).
It lives on a separate artifact-only branch. The manifest pins commit
`dfd7a087202702c87f1b899b293a0d88f8cb6483`, filenames, sizes and SHA-256 values;
consumers do not follow a mutable branch or `latest` tag. This is the supported
controlled-source alternative to Release assets, not a GitHub Release.

During the ML build, the standard-library downloader fetches only `model.joblib`,
`calibrator.joblib` and `metadata.json`, rejects redirects and mismatched bytes,
then checks metadata provenance before installation. No artifact is deserialized
by the downloader. The unchanged inference service checks model/calibrator hashes
again before loading. Existing matching local files are verified, while different
or incomplete existing bundles are refused rather than overwritten.

No secrets, PaySim source CSV/ZIP, local model files, virtual environment,
experimental output or private AI instructions enter the default build context.
Frozen display reports are copied separately into web; they are not recalculated
by deployment or mixed into inference. Neither model code nor frozen policy is
changed by packaging. For local artifact preparation use `make artifacts`.

## Operation and limits

Readiness endpoints are internal: API `/health/ready`, ML `/health/ready`, web
`/_stcore/health`. Missing/corrupt model artifacts keep scoring unavailable;
there is no invented fallback score. Use logs to diagnose build or readiness
failure, and do not delete the original final lock to make startup pass.

The default binding is local, with no added authentication or TLS terminator.
Public exposure needs its own controlled ingress/authentication/TLS plan and
capacity verification; it is not supplied by this packaging task. Raw PaySim is
needed only for a separately isolated training reproduction, described in
[running.md](running.md). Do not rerun the completed final evaluation.

Graphify source discovery and Context7 Docker/Compose documentation informed the
configuration. Mandatory AI disclosure and sole authorship remain; no collaborators
or Co-authored-by attribution were added. Publication of the model bundle does
not imply that local application changes have been committed or pushed to `main`.
