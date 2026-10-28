.PHONY: setup test lint fmt ci reports

setup:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

ci: lint test

# Regenerate the committed verification reports under studies/. foam-verify exits 1 for a study
# that is not a clean pass (pitzDaily); only 2, bad input, stops the loop.
reports:
	for s in duct cavity pitzDaily; do \
		uv run foam-verify report studies/$$s --output studies/$$s || test $$? -eq 1 || exit 1; \
	done
