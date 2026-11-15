# syntax=docker/dockerfile:1.7
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY services/ml/requirements.lock.txt services/ml/requirements.runtime.txt /build/
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install --only-binary=:all: -r requirements.runtime.txt
COPY configs/model-artifacts.json /build/configs/model-artifacts.json
COPY scripts/fetch_model.py /build/scripts/fetch_model.py
RUN python scripts/fetch_model.py --manifest configs/model-artifacts.json --output /artifacts

FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    HOME=/tmp
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY services/__init__.py /app/services/__init__.py
COPY services/ml/__init__.py services/ml/app.py services/ml/features.py services/ml/inference.py /app/services/ml/
COPY --from=builder /artifacts /app/services/ml/artifacts
USER 10001:10001
# Verify compiled-wheel shared-library imports in the exact minimal runtime base.
RUN python -c "import fastapi, joblib, numpy, pandas, sklearn.tree._tree"
EXPOSE 8091
HEALTHCHECK --interval=15s --timeout=4s --start-period=30s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/health/ready', timeout=3).close()"]
CMD ["python", "-m", "uvicorn", "services.ml.app:app", "--host", "0.0.0.0", "--port", "8091"]
