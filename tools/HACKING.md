# How to Hack

Wrote some code and want to test it now? Source the hacking
environment file and a virtualenv will be setup for you.

    $ . ./hack/env_setup.sh
    New python executable in /home/you/.../enterprise-images/tools/venv/bin/python2
    Also creating executable in /home/you/.../enterprise-images/tools/venv/bin/python
    Installing setuptools, pip, wheel...done.
    Obtaining file:///home/you/.../enterprise-images/tools
    Collecting pyyaml (from ocp-cd-tools==0.1)
    Collecting click (from ocp-cd-tools==0.1)
    Using cached click-6.7-py2.py3-none-any.whl
    Collecting dockerfile-parse (from ocp-cd-tools==0.1)
    Using cached dockerfile_parse-0.0.7-py2-none-any.whl
    Installing collected packages: pyyaml, click, dockerfile-parse, ocp-cd-tools
    Running setup.py develop for ocp-cd-tools
    Successfully installed click-6.7 dockerfile-parse-0.0.7 ocp-cd-tools pyyaml-3.12

Now that the virtualenv is setup, your prompt should have an
indicator, something like `(venv)` will be added.

Run the scripts like normal

    $ . ./hack/env_setup.sh
    ... output as above ...

	(venv) $ which oit elliott
	~/.../enterprise-images/tools/venv/bin/oit
	~/.../enterprise-images/tools/venv/bin/elliott

    (venv) $ elliott --help
    Usage: elliott [OPTIONS] COMMAND [ARGS]...

    Options:
    -h, --help  Show this message and exit.

    Commands:
    advisory:add-bugs       Add new MODIFED bugs to the advisory
    ...
