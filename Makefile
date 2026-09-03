VENV ?= .venv
PYTHON ?= python3

ifeq ($(OS),Windows_NT)
BIN := $(VENV)/Scripts
PY := $(BIN)/python.exe
else
BIN := $(VENV)/bin
PY := $(BIN)/python
endif

.PHONY: install test e2e coverage lint format typecheck build check clean

install:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m unittest discover

e2e:
	$(PY) -m unittest tests.test_e2e_agent_task

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
	$(PY) -c "from pathlib import Path; import shutil; [shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True) for p in map(Path, ['build', 'dist', '.coverage', '.mypy_cache', '.ruff_cache'])]"
