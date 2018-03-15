# How to Hack

Wrote some code and want to test it now? Source the hacking
environment file and a virtualenv will be setup for you.

    <enterprise-images/tools> $ . ./hack/env_setup.sh
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

# HAVING PROBLEMS WITH CERTIFICATE VERIFICATION?

Then you do not have the CA chain for Red Hat internal certs installed
in your system PKI. You would see something like this:

    requests.exceptions.SSLError:
    HTTPSConnectionPool(host='errata.devel.redhat.com', port=443): Max
    retries exceeded with url: /filter/1965.json (Caused by
    SSLError(SSLError("bad handshake:
    Error([('SSL routines', 'tls_process_server_certificate', 'certificate verify failed')],)",),))


You need to either install the CA chain yourself, or use this other
little hack to tell python-requests where the CA chain is (a copy of
the chain is in the `hack/` directory)

Run the env setup script like normal

    <enterprise-images/tools> $ . ./hack/env_setup.sh
    ... output as above ...

Then export `REQUESTS_CA_BUNDLE` while in the `tools/` directory:

	<enterprise-images/tools> (venv) $ export REQUESTS_CA_BUNDLE=`pwd`/hack/cert-chain.crt

Switch back to the root directory of the repo and then you should be ready to go!

    <enterprise-images/tools> (venv) $ cd ..

	<enterprise-images> (venv) $ elliott advisory:list
	2018-03-02T15:19:08 NEW_FILES TEST OpenShift Container Platform 3.5 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32916
	2018-01-25T19:19:15 NEW_FILES OpenShift Container Platform 3.3 and 3.4 images update https://errata.devel.redhat.com/advisory/32352
	2018-01-25T19:15:25 NEW_FILES OpenShift Container Platform 3.3 and 3.4 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32351
	2018-01-24T15:01:59 NEW_FILES OpenShift Container Platform 3.7, 3.6, 3.5 images update https://errata.devel.redhat.com/advisory/32337
	2018-01-24T14:56:43 NEW_FILES OpenShift Container Platform 3.7, 3.6, and 3.5 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32336

Ensure you `unset REQUESTS_CA_BUNDLE` afterwards or other cli tools
using python-requests will fail to verify *other* sites because it'll
try to use the manually provided CA chain.
