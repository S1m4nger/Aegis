# Dependency verification

Environment resolved on 2026-11-14 UTC. Exact Python versions: `services/ml/requirements.lock.txt`; Go versions/checksums: `services/orchestrator/go.mod` and `go.sum`.

Context7 documentation consulted before integration changes:
- `/uber-go/fx`: v1.24.0 not separately indexed, current official docs used and checked by compiling against v1.24.0. Constructor interface binding via `fx.Annotate(constructor, fx.As(new(Interface)))`; lifecycle `OnStart`/`OnStop`. https://github.com/uber-go/fx/blob/master/docs/src/annotate.md
- `/go-chi/docs`: current docs (no version-specific index); RequestID middleware and GetReqID match installed chi/v5 v5.5.0. https://github.com/go-chi/docs/blob/master/quickstart.md
- `/websites/fastapi_tiangolo`: current docs used for installed FastAPI 0.163.0; lifespan context manager replaces deprecated startup event. https://fastapi.tiangolo.com/advanced/events/
- `/pydantic/pydantic/v2.14.1`: nearest indexed patch to installed 2.14.3; strict fields and extra-forbid. https://github.com/pydantic/pydantic/blob/v2.14.1/docs/concepts/strict_mode.md

Local Pydantic compatibility probe confirmed strict float accepts JSON-style integer amount and rejects strings, booleans and nulls. Contract checks cover these cases. No external example copied verbatim.
- `/scikit-learn/scikit-learn/1.9.1`: training/calibration API and separate calibration windows verified through Context7; pandas 2.x chunked CSV reading and deterministic sampling also checked by the training worker. Exact installed sklearn 1.9.1 and pandas 2.3.3.
- `/streamlit/docs`: current official AppTest/form/table/Plotly APIs consulted for installed Streamlit 1.67.0 (no exact indexed version). https://docs.streamlit.io/develop/api-reference/app-testing
- `/plotly/plotly.py`: current official Scatter/Bar/update_layout APIs for installed Plotly 6.9.0 (no exact indexed version). https://github.com/plotly/plotly.py/blob/main/doc/python/ml-roc-pr.md
