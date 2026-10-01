.PHONY: install dev-api dev-ui build demo test lint seed calibrate fit fit-replay fit-monthly fit-station \
        replay-archive basemap static parity clean

VENV := .venv
PY   := $(VENV)/bin/python

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r backend/requirements.txt pytest httpx
	npm --prefix frontend install

dev-api:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

dev-ui:
	npm --prefix frontend run dev

build:
	npm --prefix frontend run build

# Build the UI, then serve API and UI together from a single process.
demo: build
	cd backend && ../$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

test:
	cd backend && ../$(PY) -m pytest tests/ -q

lint:
	npm --prefix frontend run typecheck

seed:
	cd backend && ../$(PY) -m app.db.seed --days 7

calibrate:
	cd backend && ../$(PY) -m scripts.calibrate

# Rebuild the bundled India map from the DataMeet boundary shapefile.
basemap:
	cd backend && ../$(PY) -m scripts.build_basemap

# Train and compare logistic, random forest and XGBoost; keep the best.
fit:
	cd backend && ../$(PY) -m scripts.train_models

# Fit the historical-replay model on origin-only predictors. Separate from
# `fit`, and deliberately so: that model is trained on ensemble-derived
# features, which are anchored to the outcome they are later verified against.
fit-replay:
	cd backend && ../$(PY) -m scripts.train_replay_model

# Fit the 7-day station forecast and bust models on NOAA GHCN-Daily.
# Trains on 1995-2009; every day of 2010-2017 is held out.
fit-station:
	cd backend && ../$(PY) -m scripts.train_station_model

# Fit the monthly model on the 1901-2017 sub-division record. Trains to 2009
# and holds out 2010-2017 as a block.
fit-monthly:
	cd backend && ../$(PY) -m scripts.train_monthly_model

# Show what the daily observational archive covers, and where more of it comes
# from. Pass FILE=<path> to import a published daily file.
replay-archive:
	cd backend && ../$(PY) -m scripts.import_imd_daily_rainfall $(if $(FILE),--file $(FILE),--describe)

# Single self-contained HTML file: the whole dashboard with the API responses
# baked in, for a read-only deployment with no backend.
static: build
	cd backend && ../$(PY) -m scripts.export_station_sidecar
	cd backend && ../$(PY) -m scripts.export_snapshot
	npm --prefix frontend run package-static

# Prove the static build's station replays equal the live API, field by field.
parity:
	cd backend && ../$(PY) -m scripts.check_sidecar_parity

clean:
	rm -rf frontend/dist frontend/node_modules $(VENV) atmosguard.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
