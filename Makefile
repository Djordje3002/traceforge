PYTHON ?= python3
export PYTHONPATH := src

.PHONY: test demo serve showcase
test:
	$(PYTHON) -m unittest discover -s tests -v
demo:
	$(PYTHON) -m traceforge demo
serve:
	$(PYTHON) -m traceforge serve
showcase:
	$(PYTHON) -m traceforge showcase --output docs/demo.html
