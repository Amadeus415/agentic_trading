.PHONY: install test lint security demo health fund-init fund-context fund-status fund-performance scheduled-cycle validate dashboard

FUND_CONFIG := examples/fund.mandate.json
FUND_LEDGER := state/edgecraft-fund.db

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

fund-init:
	uv run edgecraft fund-init --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

fund-context:
	uv run edgecraft fund-context --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

fund-status:
	uv run edgecraft fund-status --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

fund-performance:
	uv run edgecraft fund-performance --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

# Read-only Next.js dashboard over the paper ledger (Node/npm required).
dashboard:
	cd dashboard && npm run dev

# Codex writes today's researched input; this applies fake-money accounting only.
scheduled-cycle:
	./scripts/run_scheduled_cycle.sh

validate: test lint
	uv run edgecraft fund-validate --config $(FUND_CONFIG)
	uv run edgecraft backtest --config examples/research.json --data-source synthetic --output artifacts/smoke-backtest.json
	uv run edgecraft walk-forward --config examples/research.json --data-source synthetic --train-sessions 504 --test-sessions 126 --output artifacts/smoke-walk-forward.json
