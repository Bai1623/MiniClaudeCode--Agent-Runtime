PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PY := $(BIN)/python

.PHONY: install test coverage lint format typecheck build check clean

install:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m unittest discover

coverage:
	$(PY) -m coverage run -m unittest discover
	$(PY) -m coverage report

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff check . --fix
	$(PY) -m ruff format .

typecheck:
	$(PY) -m mypy

build:
	$(PY) -m build

check: lint typecheck coverage build

clean:
	rm -rf build dist .coverage .mypy_cache .ruff_cache
