# syntax=docker/dockerfile:1.7
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY services/ml/requirements.lock.txt /build/services/ml/requirements.lock.txt
COPY app/requirements.runtime.txt /build/app/requirements.runtime.txt
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install --only-binary=:all: -r app/requirements.runtime.txt

FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOME=/tmp XDG_CACHE_HOME=/tmp/.cache \
    AEGIS_API_URL=http://127.0.0.1:8080 AEGIS_REPORTS_DIR=/app/reports
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app/dashboard.py app/api_config.py /app/app/
COPY .streamlit/config.toml /app/.streamlit/config.toml
COPY --chown=10001:10001 reports/model_metrics.json reports/pr_curve.json reports/drift_metrics.json reports/decision_experiments.csv reports/error_cases.csv /app/reports/
USER 10001:10001
RUN python -c "import json, pandas, plotly, streamlit; from pathlib import Path; [p.read_bytes() for p in Path('/app/reports').iterdir()]; json.loads(Path('/app/reports/model_metrics.json').read_text())"
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).close()"]
CMD ["python", "-m", "streamlit", "run", "app/dashboard.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--server.fileWatcherType=none", "--browser.gatherUsageStats=false"]
