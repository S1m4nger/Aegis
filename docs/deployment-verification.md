# Deployment verification

Current container qualification **passed** on 2026-11-15 UTC. All three images
built, then the original Compose runtime passed readiness, analyzer/Cost Lab,
15 scenario comparisons, 400 validation responses, ML outage/recovery and shutdown.
The final experiment and model were unchanged. Default bridge outbound networking
failed; the successful build used host networking for build steps only. A fresh
non-container dependency installation and anonymous final published links remain
unverified. Earlier failures below are historical and were resolved as stated.

## Current container evidence

- `docker buildx bake -f compose.yaml --set '*.network=host' --allow network.host --load --metadata-file reports/generated/docker-build-metadata.json`: exit 0 after the ownership repair. Runtime Python dependencies were installed in fresh image layers; pinned model downloaded and verified.
- `docker compose up --no-build --wait --wait-timeout 120 --detach`: exit 0, all three services healthy.
- `.venv/bin/python /tmp/aegis-docker-probe.py`: exit 0. Temporary executable removed in finally. Inside web: real API, invalid input/label rejection 400, 15 frozen scenario comparisons, live AppTest analyzer and Cost Lab passed. Host `/` and `/_stcore/health` returned 200.
- Runtime inspection: UID/GID10001:10001, read-only root filesystem, dropped capabilities, no-new-privileges and no bind mounts for all services. Only `127.0.0.1:8501` published; API/ML ports internal.
- ML stopped: Go liveness 200, readiness/analyze 503, no fabricated score. Dashboard showed the exact unavailable message and retained no stale result. ML restarted and services recovered; the full probe then passed.
- `docker compose stop`: exit 0; API/web exit 0, ML exit143 after logged complete application shutdown (SIGTERM, no SIGKILL/OOM). API Fx lifecycle stop hooks completed. Application was restarted after the stop check.
- All original reports remained byte-identical during qualification. No retraining, final-test scoring, policy change, commit, push or submission was performed.

Initial API startup failed because generated configs copied as root-owned0600.
Dockerfiles now explicitly assign config/report ownership to runtime10001:10001;
web build also reads every packaged report as that user. The attempted chmod-only
repair failed the new read-check and was replaced by the verified ownership fix.
The first container UI test incorrectly treated the normal red FLAG recommendation
as an error; corrected assertions allow only that exact expected recommendation.
An outage UI test initially expected detailed HTTP503 text; the corrected test
requires the actual generic unavailable message. Failures and corrections are
recorded truthfully in the local verification journal.

Detailed local artifacts: `reports/generated/docker-check.json` and
`reports/generated/docker-build-metadata.json`. Reproducible launch commands and
build-network workaround: [deployment.md](deployment.md).

## Recorded readiness audit — 2026-11-15 UTC

The following results were recorded in the local development verification journal
during the readiness audit; this document summarizes those runs rather than claiming
they were rerun when this file was created.

| Command from repository root | Actual result | Scope |
|---|---|---|
| `docker compose config --quiet` | Exit 0 | Compose configuration parses; does not contact the Engine or build/start images. |
| `make verify-artifacts` | Exit 0 | Existing frozen model bundle `paysim-lr-6035ac438abfb769` passes the manifest checks; not a fresh download test. |
| `make verify` | Exit 0 | Go tests, Go vet and 21 Python/UI checks; generated temporary sources removed by the verifier. |
| `make check` | Exit 0 before and after the regression suite | Static submission files/disclaimer/temporary-source checks only. |

## Earlier checks before container qualification — 2026-11-15 UTC

These failures predate the successful container qualification above. Engine access
was subsequently restored; these are historical results, not current blockers.

- `docker info`: exit 1 both inside and outside the sandbox; Docker socket permission denied. No image build or container startup is claimed.
- `.venv/bin/python scripts/fetch_model.py --output /tmp/aegis-submission-artifacts-20261116`: initial sandbox run exit 1 (DNS denied); authorized outside-sandbox retry exit 0, all three pinned files verified.
- `.venv/bin/python scripts/demo_check.py`: first updated run exit 1 due to the dashboard package import; corrected script-local import, then exit 0. Current analyzer/Cost Lab, nine batch/API probes, 15 scenario comparisons, missing scorer 503, missing field 400 and graceful Go stop 0 passed. Final report bytes were unchanged.
- `make verify`: exit 0 after adding delivery regressions; Go tests/vet passed and **56 Python tests passed**. Generated source files removed in finally.

The demo now supplies the server-owned API origin through a temporary environment
setting instead of a removed visitor widget. Go demo builds disable VCS stamping
so source archives without Git metadata can be tested. Downloader regression tests
cover empty and README-only artifact directories as found in a clean clone,
checksum/provenance failures, and refusal to overwrite partial or corrupt bundles.
The API tests cover origin validation, bounded responses, redirects and redacted errors.

An initial isolated source-copy build failed on VCS stamping; fixed in the demo.
The following sandbox attempt could not bind its loopback port (exit 1), an
environment permission failure. The successful authorized isolated qualification is recorded below. Existing dependencies are reused, so it is not a fresh-machine
installation test. No final-test inference is performed by these probes.

## Acceptance checklist (including checks completed after the audit)

- [x] Download the pinned artifact bundle into an empty isolated directory and verify it.
- [x] Run the current standalone application from an isolated publishable source copy (existing dependency environment reused).
- [x] Build all three images using the declared root build context (build-only host network).
- [x] Start Compose and confirm ML/API/web readiness, analyzer and scenario lab behavior.
- [x] Verify published-port boundaries and graceful shutdown with Compose.
- [ ] Inspect final publishable files and anonymous repository/document access.

Append actual commands, exit codes, timestamps and limitations as checks complete.
A parsed Compose file or passing standalone demo is not evidence of a passing
container startup. See [running.md](running.md) for operator commands and
[verification-summary.md](verification-summary.md) for the research checks.

## Isolated publishable source qualification — 2026-11-15 UTC

`/home/souslacroix/Aegis/.venv/bin/python /tmp/aegis-delivery-qualification.py`
exited **0** outside the sandbox. The temporary qualification source was removed
by its exact path after execution. It copied only publishable tracked/untracked
files into a temporary directory, with no `.git`, raw data or local model binaries.
Within that copy, `scripts/fetch_model.py` downloaded into the default README-only
artifact directory (exit 0), then `scripts/demo_check.py` passed the full live flow
(exit 0). Temporary services stopped and the source copy was removed.

The existing virtual environment was reused; no fresh dependency installation or
container startup is claimed. All original non-demo report hashes were unchanged.
Detailed local evidence: `reports/generated/delivery-check.json`; exact commands,
failures and cleanup are recorded in `docs/verification-log.md`.
