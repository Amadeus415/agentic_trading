.PHONY: install test lint security demo fund-init fund-context fund-cycle-key fund-show fund-verify fund-visualize scheduled-cycle validate validate-lab dashboard

FUND_CONFIG ?= examples/fund.mandate.aggressive.json
FUND_LEDGER ?= state/edgecraft-aggressive.db

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check src tests scripts/deny_broker_tools.py
	uv run ruff format --check src tests scripts/deny_broker_tools.py

security:
	uv export --frozen --no-dev --no-emit-project --format requirements-txt | uvx --python 3.13 --from pip-audit==2.10.1 pip-audit -r /dev/stdin --disable-pip
	uvx --python 3.13 --from bandit==1.9.4 bandit -q -r src scripts -ll --skip B608

demo:
	uv run edgecraft backtest --config examples/research.json --data-source synthetic

fund-init:
	uv run edgecraft fund-init --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

fund-context:
	uv run edgecraft fund-context --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

fund-cycle-key:
	uv run edgecraft fund-cycle-key

fund-show:
	uv run edgecraft fund-show --config $(FUND_CONFIG) --ledger $(FUND_LEDGER) --history

fund-verify:
	uv run edgecraft fund-verify --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

fund-visualize:
	uv run edgecraft fund-visualize --config $(FUND_CONFIG) --ledger $(FUND_LEDGER)

# Read-only Next.js dashboard over the paper ledger (Node/npm required).
dashboard:
	cd dashboard && npm run dev

# Codex writes this UTC session's researched input; this applies fake-money accounting only.
scheduled-cycle:
	./scripts/run_scheduled_cycle.sh

validate: test lint
	uv run edgecraft fund-validate --config $(FUND_CONFIG)

validate-lab:
	uv run edgecraft backtest --config examples/research.json --data-source synthetic --output artifacts/smoke-backtest.json
	uv run edgecraft walk-forward \
		--config examples/research.json \
		--data-source synthetic \
		--train-sessions 504 \
		--test-sessions 126 \
		--output artifacts/smoke-walk-forward.json
