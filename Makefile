.PHONY: install test lint security demo health scheduled-cycle validate

# Paper-only schedule entrypoint (fail-closed health → readiness → cycle).
LEDGER ?= state/edgecraft-paper.db

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check src tests scripts/guard_robinhood_tool.py
	uv run ruff format --check src tests scripts/guard_robinhood_tool.py

security:
	uv export --frozen --no-dev --no-emit-project --format requirements-txt | uvx --python 3.13 --from pip-audit==2.10.1 pip-audit -r /dev/stdin --disable-pip
	# B608 misclassifies the JSON-formatted execution prompt as a SQL query.
	uvx --python 3.13 --from bandit==1.9.4 bandit -q -r src scripts -ll --skip B608

demo:
	uv run edgecraft backtest --config examples/research.json --data-source synthetic

health:
	uv run edgecraft health

# Single paper-only wake path for Codex scheduled tasks.
scheduled-cycle:
	LEDGER=$(LEDGER) ./scripts/run_scheduled_cycle.sh

validate: test lint
	uv run edgecraft mandate-validate --config examples/mandate.index-dca.json
	uv run edgecraft mandate-validate --config examples/mandate.index-dca-live.example.json
	uv run edgecraft backtest --config examples/research.json --data-source synthetic --output artifacts/smoke-backtest.json
	uv run edgecraft walk-forward --config examples/research.json --data-source synthetic --train-sessions 504 --test-sessions 126 --output artifacts/smoke-walk-forward.json
