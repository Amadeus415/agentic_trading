.PHONY: install dev api ui test lint build demo

install:
	uv sync --extra dev

api:
	uv run uvicorn edgecraft.api:app --reload --host 127.0.0.1 --port 8000

dev:
	uv run uvicorn edgecraft.api:app --reload --host 127.0.0.1 --port 8000

test:
	uv run pytest

lint:
	uv run ruff check src tests
	node --check frontend/app.js

build:
	@echo "Frontend is dependency-free and served directly by FastAPI"

demo:
	uv run python scripts/demo.py
