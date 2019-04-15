"""
Utility functions and object abstractions for general interactions
with oc cli
"""

# stdlib
from subprocess import call, check_output, CalledProcessError

# ours
from elliottlib.exceptions import ElliottFatalError


def get_bug_list(working_dir, old, new):
    bug_list = []
    try:
        bug_list = check_output(['oc', 'adm', 'release', 'info',
                                '-o', 'name', # only output BZ IDs
                                '--bugs={}/origin'.format(working_dir), # clone origin to working dir
                                '--changes-from={}'.format(old), 
                                new], # payloads to compare
        ).splitlines()
    except CalledProcessError as e:
        raise ElliottFatalError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))

    return bug_list