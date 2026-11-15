.PHONY: artifacts verify-artifacts prepare train ml-api go-api dashboard verify check select up down logs
AEGIS_PYTHON ?= .venv/bin/python
DATA_ZIP ?= $(HOME)/Downloads/archive(1).zip
artifacts:
	$(AEGIS_PYTHON) scripts/fetch_model.py
verify-artifacts:
	$(AEGIS_PYTHON) scripts/fetch_model.py --check
prepare:
	$(AEGIS_PYTHON) scripts/prepare_data.py --zip '$(DATA_ZIP)'
train:
	$(AEGIS_PYTHON) -m services.ml.train --data data/raw/paysim.csv
ml-api:
	$(AEGIS_PYTHON) -m uvicorn services.ml.app:app --host 127.0.0.1 --port 8091
go-api:
	cd services/orchestrator && go run ./cmd/aegis
dashboard:
	$(AEGIS_PYTHON) -m streamlit run app/dashboard.py --server.address 127.0.0.1
verify:
	$(AEGIS_PYTHON) scripts/verify.py
check:
	$(AEGIS_PYTHON) scripts/check_submission.py
select:
	$(AEGIS_PYTHON) -m services.ml.evaluate --select-only
up:
	docker compose up --build --wait --detach
down:
	docker compose down
logs:
	docker compose logs --follow --tail=100
# Deliberately no final recipe: preserve the completed final lock. Read docs/evaluation-run.md.
