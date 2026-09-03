.PHONY: lint test run validate

lint:
	ruff check .

test:
	pytest -q

run:
	python -m poller run

validate:
	python -m poller validate
