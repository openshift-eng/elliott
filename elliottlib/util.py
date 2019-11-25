from __future__ import unicode_literals
import click
import datetime
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
import re

from errata_tool import Erratum
from kerberos import GSSError

# -----------------------------------------------------------------------------
# Constants and defaults
# -----------------------------------------------------------------------------
default_release_date = datetime.datetime(1970, 1, 1, 0, 0)
now = datetime.datetime.now()
YMD = '%Y-%b-%d'


def red_prefix(msg):
    """Print out a message prefix in bold red letters, like for "Error: "
messages"""
    click.secho(msg, nl=False, bold=True, fg='red')


def green_prefix(msg):
    """Print out a message prefix in bold green letters, like for "Success: "
messages"""
    click.secho(msg, nl=False, bold=True, fg='green')


def yellow_prefix(msg):
    """Print out a message prefix in bold yellow letters, like for "Warning: "
or Notice: messages"""
    click.secho(msg, nl=False, bold=True, fg='yellow')


def red_print(msg):
    """Print out a message in red text"
messages"""
    click.secho(msg, nl=True, bold=False, fg='red')


def green_print(msg):
    """Print out a message in green text"""
    click.secho(msg, nl=True, bold=False, fg='green')


def yellow_print(msg):
    """Print out a message in yellow text"""
    click.secho(msg, nl=True, bold=False, fg='yellow')


def cprint(msg):
    """Wrapper for click.echo"""
    click.echo(msg)


def exit_unauthenticated():
    """Standard response when an API call returns 'unauthenticated' (401)"""
    red_prefix("Error Unauthenticated: ")
    click.echo("401 - user is not authenticated, are you sure you have a kerberos ticket?")
    exit(1)


def exit_unauthorized():
    """Standard response when an API call returns 'unauthorized' (403)"""
    red_prefix("Error Unauthorized: ")
    click.echo("403 - user is authenticated, but unauthorized to perform this action")
    exit(1)


def ensure_erratatool_auth():
    """Test (cheaply) that we at least have authentication to erratatool"""
    try:
        Erratum(errata_id=1)
    except GSSError:
        exit_unauthenticated()


def validate_release_date(ctx, param, value):
    """Ensures dates are provided in the correct format"""
    try:
        release_date = datetime.datetime.strptime(value, YMD)
        if release_date == default_release_date:
            # Default date, nothing special to note
            pass
        else:
            # User provided date passed validation, they deserve a
            # hearty thumbs-up!
            green_prefix("User provided release date: ")
            click.echo("{} - Validated".format(release_date.strftime(YMD)))
        return value
    except ValueError:
        raise click.BadParameter('Release date (--date) must be in YYYY-Mon-DD format')


def validate_email_address(ctx, param, value):
    """Ensure that email addresses provided are valid email strings"""
    # Really just check to match /^[^@]+@[^@]+\.[^@]+$/
    email_re = re.compile(r'^[^@ ]+@[^@ ]+\.[^@ ]+$')
    if not email_re.match(value):
        raise click.BadParameter(
            "Invalid email address for {}: {}".format(param, value))

    return value


def release_from_branch(ver):
    """Parse the release version from the provided 'branch'.

For example, if --group=openshift-3.9 then runtime.group_config.branch
will have the value rhaos-3.9-rhel-7. When passed to this function the
return value would be the number 3.9, where in considering '3.9' then
'3.9' is the RELEASE version.

This behavior is HIGHLY dependent on the format of the input
argument. Hence, why this function indicates the results are based on
the 'branch' variable. Arbitrary input will fail. Use of this implies
you read the docs.
    """
    return ver.split('-')[1]


def major_from_branch(ver):
    """Parse the major version from the provided version (or 'branch').

For example, if --group=openshift-3.9 then runtime.group_config.branch
will have the value rhaos-3.9-rhel-7. When passed to this function the
return value would be the number 3, where in considering '3.9' then
'3' is the MAJOR version.

I.e., this gives you the X component if 3.9 => X.Y.

This behavior is HIGHLY dependent on the format of the input
argument. Hence, why this function indicates the results are based on
the 'branch' variable. Arbitrary input will fail. Use of this implies
you read the docs.
    """
    return ver.split('-')[1].split('.')[0]


def minor_from_branch(ver):
    """Parse the minor version from the provided version (or 'branch').

For example, if --group=openshift-3.9 then runtime.group_config.branch
will have the value rhaos-3.9-rhel-7. When passed to this function the
return value would be the number 9, where in considering '3.9' then
'9' is the MINOR version.

I.e., this gives you the Y component if 3.9 => X.Y.

This behavior is HIGHLY dependent on the format of the input
argument. Hence, why this function indicates the results are based on
the 'branch' variable. Arbitrary input will fail. Use of this implies
you read the docs.
    """
    return ver.split('-')[1].split('.')[1]


def pbar_header(msg_prefix='', msg='', seq=[], char='*'):
    """Generate a progress bar header for a given iterable or
sequence. The given sequence must have a countable length. A bar of
`char` characters is printed between square brackets.

    :param string msg_prefix: Header text to print in heavy green text
    :param string msg: Header text to print in the default char face
    :param sequence seq: A sequence (iterable) to size the progress
    bar against
    :param str char: The character to use when drawing the progress
    bar

For example:

    pbar_header("Foo: ", "bar", seq=[None, None, None], char='-')

would produce:

    Foo: bar
    [---]

where 'Foo: ' is printed using green_prefix() and 'bar' is in the
default console fg color and weight.

TODO: This would make a nice context wrapper.

    """
    green_prefix(msg_prefix)
    click.echo(msg)
    click.echo("[" + (char * len(seq)) + "]")


def progress_func(func, char='*'):
    """Use to wrap functions called in parallel. Prints a character for
each function call.

    :param lambda-function func: A 'lambda wrapped' function to call
    after printing a progress character
    :param str char: The character (or multi-char string, if you
    really wanted to) to print before calling `func`

    Usage examples:
      * See find-builds command
    """
    click.secho(char, fg='green', nl=False)
    return func()


def parallel_results_with_progress(inputs, func):
    """Run a function against a list of inputs with a progress bar

    :param sequence inputs : A sequence of items to iterate over in parallel
    :param lambda-function func: A lambda function to call with one arg to process

    Usage examples:
      * See find-builds command

        candidate_build_infos = parallel_results_with_progress(
            candidate_builds,
            lambda build: build.get_latest_build_info()
        )

    Example output:
    [****************]

    """
    click.secho('[', nl=False)
    pool = ThreadPool(cpu_count())
    results = pool.map(
        lambda it: progress_func(lambda: func(it)),
        inputs)

    # Wait for results
    pool.close()
    pool.join()
    click.echo(']')

    return results


def override_product_version(pv, branch):
    """ if user specify -b branch will override product_version of erratatool.yml"""
    rp = pv.split("-")
    rb = branch.split("-")
    if rp[1] != rb[3] or rp[3] != rb[1]:
        if rb[3] == '8':
            # hardcoded differently for RHEL8 since the product version name changed
            # TODO: it should look up the right product version that can accept content from the brew tag.
            return 'OSE-{}-RHEL-{}'.format(rb[1], rb[3])
        return 'RHEL-{}-OSE-{}'.format(rb[3], rb[1])
    return pv


def get_release_version(pv):
    """ there are two kind of format of product_version: OSE-4.1-RHEL-8 RHEL-7-OSE-4.1 """
    return re.search(r'OSE-(\d+\.\d+)', pv).groups()[0]
