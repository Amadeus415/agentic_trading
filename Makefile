.PHONY: install check session tick publish site

install:
	uv sync --extra dev

check:
	uv run pytest
	uv run ruff check src tests
	uv run ruff format --check src tests

# One session for every live agent run, in parallel.
session:
	uv run nightshift session

# Settle, mark, resolve forecasts, trade baselines; then rebuild the site.
tick:
	uv run nightshift tick
	uv run nightshift publish

publish:
	uv run nightshift publish

site: publish
	open -a Helium $${NIGHTSHIFT_HOME:-$$HOME/.nightshift}/site/index.html
