PYTHON ?= python3
PYTHONPATH := src

.PHONY: install test lint demo docs clean

install:
	@echo "No third-party dependencies. Pure standard library."
	@$(PYTHON) --version

test:
	@PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -t . -q

lint:
	@ruff check .

demo:
	@PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m dpa_review.cli --input data/sample_dpa.json --out examples

docs:
	@$(PYTHON) scripts/generate.py

clean:
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
