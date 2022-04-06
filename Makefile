.PHONY: venv tox lint test

venv:
	python3 -m venv venv
	./venv/bin/pip install -r requirements-dev.txt
	# source venv/bin/activate

lint:
	./venv/bin/python -m flake8

test: lint
	./venv/bin/python -m pytest --verbose --color=yes --disable-pytest-warnings tests/

test-functional: lint
	./venv/bin/python -m pytest --verbose --color=yes --disable-pytest-warnings functional_tests/

# run by CI
tox:
	tox --recreate
