.PHONY: help install index dev api web build test eval analyze clean

help:
	@echo "make install  — установить зависимости (Python + Node)"
	@echo "make index    — собрать поисковый индекс"
	@echo "make api      — запустить API с автоперезагрузкой (:8000)"
	@echo "make web      — запустить фронтенд с hot reload (:5173)"
	@echo "make build    — собрать фронтенд в frontend/dist"
	@echo "make test     — прогнать тесты"
	@echo "make eval     — метрики качества поиска"
	@echo "make analyze  — пересобрать docs/DATA_ANALYSIS.md"

install:
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r backend/requirements.txt
	cd frontend && npm install --no-audit --no-fund

index:
	cd backend && ../.venv/bin/python -m app.ingest.build_index

api:
	cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	cd backend && ../.venv/bin/python -m pytest tests/ -q

eval:
	cd backend && ../.venv/bin/python -m tests.eval_search

analyze:
	.venv/bin/python scripts/analyze_data.py

clean:
	rm -rf data/index frontend/dist backend/**/__pycache__ .pytest_cache
