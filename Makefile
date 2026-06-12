.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help install test test-one clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create/sync the uv-managed environment
	$(UV) sync

test: ## Run the full unittest suite
	$(UV) run python -m unittest discover -s tests

test-one: ## Run a single test: make test-one T=tests.test_tools.Class.method
	$(UV) run python -m unittest $(T)

clean: ## Remove Python caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .coverage htmlcov *.egg-info
