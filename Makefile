.PHONY: venv tox lint test

install:
	./venv/bin/pip install .[tests]

venv:
	python3.8 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install .[tests]
	# source venv/bin/activate

lint:
	./venv/bin/python -m flake8

pylint:
	./venv/bin/python -m pylint elliottlib/

test: lint
	./venv/bin/python -m pytest --verbose --color=yes --disable-pytest-warnings tests/

test-functional: lint
	./venv/bin/python -m pytest --verbose --color=yes --disable-pytest-warnings functional_tests/

# run by CI
tox:
	tox --recreate
