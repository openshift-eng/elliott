.PHONY: venv tox lint test

venv:
	python3 -m venv venv
	./venv/bin/pip install -r requirements-dev.txt
	# source venv/bin/activate

lint:
	flake8
	mypy .

test: lint
	py.test --verbose --color=yes tests/

# run by CI
tox:
	tox --recreate
