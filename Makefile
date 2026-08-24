.PHONY: test safety-test lint typecheck security-check migrate-check api-test frontend-install frontend-build frontend-test ci

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

test:
	PYTHONPATH=src:. $(PYTHON) -m unittest discover -s tests -v

safety-test:
	PYTHONPATH=src $(PYTHON) -m tradeforge.safety_suite

lint:
	PYTHONPATH=src $(PYTHON) -m tradeforge.quality lint

typecheck:
	PYTHONPATH=src $(PYTHON) -m tradeforge.quality typecheck

security-check:
	PYTHONPATH=src $(PYTHON) -m tradeforge.quality security

migrate-check:
	PYTHONPATH=src $(PYTHON) -m tradeforge.quality migrations

api-test:
	PYTHONPATH=src:. $(PYTHON) -m unittest tests.test_api -v

frontend-install:
	npm --prefix web install

frontend-build:
	npm --prefix web run build

frontend-test:
	npm --prefix web run test -- --run

ci: lint typecheck security-check migrate-check test safety-test api-test frontend-test frontend-build
