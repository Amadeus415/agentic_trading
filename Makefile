.PHONY: install dev api ui test lint security build demo health validate

install:
	uv sync --extra dev

api:
	uv run uvicorn edgecraft.api:app --reload --host 127.0.0.1 --port 8000

dev:
	uv run uvicorn edgecraft.api:app --reload --host 127.0.0.1 --port 8000

test:
	uv run pytest

lint:
	uv run ruff check src tests scripts/guard_robinhood_tool.py
	uv run ruff format --check src tests scripts/guard_robinhood_tool.py
	node --check frontend/app.js

security:
	uv export --frozen --no-dev --no-emit-project --format requirements-txt | uvx --python 3.13 --from pip-audit==2.10.1 pip-audit -r /dev/stdin --disable-pip
	# B608 misclassifies the JSON-formatted execution prompt as a SQL query.
	uvx --python 3.13 --from bandit==1.9.4 bandit -q -r src scripts -ll --skip B608

build:
	@echo "Frontend is dependency-free and served directly by FastAPI"

demo:
	uv run python scripts/demo.py

health:
	uv run edgecraft health

validate: test lint
	uv run edgecraft mandate-validate --config examples/mandate.index-dca.json
	uv run edgecraft mandate-validate --config examples/mandate.index-dca-live.example.json
	uv run edgecraft backtest --config examples/research.json --data-source synthetic --output artifacts/smoke-backtest.json
	uv run edgecraft walk-forward --config examples/research.json --data-source synthetic --train-sessions 504 --test-sessions 126 --output artifacts/smoke-walk-forward.json
