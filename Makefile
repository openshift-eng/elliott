venv/bin/activate: requirements-dev.txt
	python3 -m venv venv
	./venv/bin/pip install -r requirements-dev.txt

lint:
	flake8

test:
	py.test --verbose --color=yes tests/

tox:
	tox --recreate
