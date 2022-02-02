import datetime, re, click
from collections import deque
from itertools import chain
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from sys import getsizeof, stderr
from typing import Dict, Iterable, List, Optional, Tuple, Sequence, Any

from elliottlib import brew
from elliottlib.exceptions import BrewBuildException

from errata_tool import Erratum
from spnego.exceptions import GSSError

# -----------------------------------------------------------------------------
# Constants and defaults
# -----------------------------------------------------------------------------
default_release_date = datetime.datetime(1970, 1, 1, 0, 0)
now = datetime.datetime.now()
YMD = '%Y-%b-%d'


def red_prefix(msg, file=None):
    """Print out a message prefix in bold red letters, like for "Error: "
messages"""
    click.secho(msg, nl=False, bold=True, fg='red', file=file)


def green_prefix(msg, file=None):
    """Print out a message prefix in bold green letters, like for "Success: "
messages"""
    click.secho(msg, nl=False, bold=True, fg='green', file=file)


def yellow_prefix(msg, file=None):
    """Print out a message prefix in bold yellow letters, like for "Warning: "
or Notice: messages"""
    click.secho(msg, nl=False, bold=True, fg='yellow', file=file)


def red_print(msg, file=None):
    """Print out a message in red text"
messages"""
    click.secho(msg, nl=True, bold=False, fg='red', file=file)


def green_print(msg, file=None):
    """Print out a message in green text"""
    click.secho(msg, nl=True, bold=False, fg='green', file=file)


def yellow_print(msg, file=None):
    """Print out a message in yellow text"""
    click.secho(msg, nl=True, bold=False, fg='yellow', file=file)


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


def progress_func(func, char='*', file=None):
    """Use to wrap functions called in parallel. Prints a character for
each function call.

    :param lambda-function func: A 'lambda wrapped' function to call
    after printing a progress character
    :param str char: The character (or multi-char string, if you
    really wanted to) to print before calling `func`
    :param file: the file to print the progress. None means stdout.

    Usage examples:
      * See find-builds command
    """
    click.secho(char, fg='green', nl=False, file=file)
    return func()


def parallel_results_with_progress(inputs, func, file=None):
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
    click.secho('[', nl=False, file=file)
    pool = ThreadPool(cpu_count())
    results = pool.map(
        lambda it: progress_func(lambda: func(it), file=file),
        inputs)

    # Wait for results
    pool.close()
    pool.join()
    click.echo(']', file=file)

    return results


def get_target_release(bugs):
    """
    Pass in a list of bugs attached to an advisory and get
    the target release version back
    """
    invalid_bugs = []
    target_releases = set()
    for bug in bugs:
        # make sure it's a list with a valid str value
        valid_target_rel = isinstance(bug.target_release, list) and len(bug.target_release) > 0 and \
            re.match(r'(\d+.\d+.[0|z])', bug.target_release[0])
        if not valid_target_rel:
            invalid_bugs.append(bug)
        else:
            target_releases.add(bug.target_release[0])

    if invalid_bugs:
        err = 'bug.target_release should be a list with a string matching regex (digit+.digit+.[0|z])'
        for b in invalid_bugs:
            err += f'\n bug.id: {b.id}, bug.target_release: {b.target_release} '
        return '', err

    if len(target_releases) != 1:
        err = f'Found different target_release values for tracker bugs: {target_releases}. ' \
              'There should be only 1 target release for all bugs. Fix the offending bug(s) and try again.'
        return '', err

    return target_releases.pop(), ''


def get_release_version(pv):
    """ there are two kind of format of product_version: OSE-4.1-RHEL-8 RHEL-7-OSE-4.1 RHEL-7-OSE-4.1-FOR-POWER-LE """
    return re.search(r'OSE-(\d+\.\d+)', pv).groups()[0]


def convert_remote_git_to_https(source):
    """
    Accepts a source git URL in ssh or https format and return it in a normalized
    https format:
        - https protocol
        - no trailing /
    :param source: Git remote
    :return: Normalized https git URL
    """
    url = re.sub(
        pattern=r'[^@]+@([^:/]+)[:/]([^\.]+)',
        repl='https://\\1/\\2',
        string=source.strip(),
    )
    return re.sub(string=url, pattern=r'\.git$', repl='').rstrip('/')


def minor_version_tuple(bz_target):
    """
    Turns '4.5' or '4.5.z' into numeric (4, 5)
    Assume the target version begins with numbers 'x.y' - explode otherwise

    :param bz_target: A string like "4.5.0"
    :return: A tuple like (4, 5)
    """
    if bz_target == '---':
        return (0, 0)
    major, minor, _ = f"{bz_target}.z".split('.', 2)
    return (int(major), int(minor))


def get_golang_version_from_build_log(log):
    # TODO add a test for this
    # Based on below greps:
    # $ grep -m1 -o -E '(go-toolset-1[^ ]*|golang-(bin-|))[0-9]+.[0-9]+.[0-9]+[^ ]*' ./3.11/*.log | sed 's/:.*\([0-9]\+\.[0-9]\+\.[0-9]\+.*\)/: \1/'
    # $ grep -m1 -o -E '(go-toolset-1[^ ]*|golang.*module[^ ]*).*[0-9]+.[0-9]+.[0-9]+[^ ]*' ./4.5/*.log | sed 's/\:.*\([^a-z][0-9]\+\.[0-9]\+\.[0-9]\+[^ ]*\)/:\ \1/'
    m = re.search(r'(go-toolset-1\S+-golang\S+|golang-bin).*[0-9]+.[0-9]+.[0-9]+[^\s]*', log)
    s = m.group(0).split()
    return s


def split_el_suffix_in_release(release: str) -> Tuple[str, Optional[str]]:
    """
    Given a release field, this will method will split out any
    .el### suffix and return (prefix, el_suffix) where el_suffix
    is None if there .el### is not detected.
    """

    el_suffix_match = re.match(r'(.*)\.(el\d+)(?:\.+|$)', release)
    if el_suffix_match:
        prefix = el_suffix_match.group(1)
        el_suffix = el_suffix_match.group(2)
        return prefix, el_suffix
    else:
        return release, None


def isolate_assembly_in_release(release: str) -> str:
    """
    Given a release field, determines whether is contains
    an assembly name. If it does, it returns the assembly
    name. If it is not found, None is returned.
    """
    # Because RPM release fields will have .el? as their suffix, we cannot
    # assume that endswith(.assembly.<name>). Strip off .el?
    prefix, _ = split_el_suffix_in_release(release)
    asm_pos = prefix.rfind('.assembly.')
    if asm_pos == -1:
        return None

    return prefix[asm_pos + len('.assembly.'):]


def isolate_el_version_in_release(release: str) -> Optional[int]:
    """
    Given a release field, determines whether is contains
    a RHEL version. If it does, it returns the version value as an int.
    If it is not found, None is returned.
    """
    _, el_suffix = split_el_suffix_in_release(release)
    if el_suffix:
        return int(el_suffix[2:])
    return None


def isolate_el_version_in_brew_tag(tag: str) -> Optional[int]:
    """
    Given a brew tag (target) name, determines whether is contains
    a RHEL version. If it does, it returns the version value.
    If it is not found, None is returned.
    """
    el_version_match = re.search(r"rhel-(\d+)", tag)
    return int(el_version_match[1]) if el_version_match else None


def find_latest_build(builds: List[Dict], assembly: Optional[str]) -> Optional[Dict]:
    """ Find the latest build specific to the assembly in a list of builds belonging to the same component and brew tag
    :param brew_builds: a list of build dicts sorted by tagging event in descending order
    :param assembly: the name of assembly; None if assemblies support is disabled
    :return: a brew build dict or None
    """
    chosen_build = None
    if not assembly:  # if assembly is not enabled, choose the true latest tagged
        chosen_build = builds[0] if builds else None
    else:  # assembly is enabled
        # find the newest build containing ".assembly.<assembly-name>" in its RELEASE field
        chosen_build = next((build for build in builds if isolate_assembly_in_release(build["release"]) == assembly), None)
        if not chosen_build and assembly != "stream":
            # If no such build, fall back to the newest build containing ".assembly.stream"
            chosen_build = next((build for build in builds if isolate_assembly_in_release(build["release"]) == "stream"), None)
        if not chosen_build:
            # If none of the builds have .assembly.stream in the RELEASE field, fall back to the latest build without .assembly in the RELEASE field
            chosen_build = next((build for build in builds if isolate_assembly_in_release(build["release"]) is None), None)
    return chosen_build


def find_latest_builds(brew_builds: Iterable[Dict], assembly: Optional[str]) -> Iterable[Dict]:
    """ Find latest builds specific to the assembly in a list of brew builds.
    :param brew_builds: a list of build dicts sorted by tagging event in descending order
    :param assembly: the name of assembly; None if assemblies support is disabled
    :return: an iterator of latest brew build dicts
    """
    # group builds by component name
    grouped_builds = {}  # key is component_name, value is a list of Brew build dicts
    for build in brew_builds:
        grouped_builds.setdefault(build["name"], []).append(build)

    for builds in grouped_builds.values():  # builds are ordered from newest tagged to oldest tagged
        chosen_build = find_latest_build(builds, assembly)
        if chosen_build:
            yield chosen_build


def split_nvr_epoch(nvre):
    """Split nvre to N-V-R and E.

    @param nvre: E:N-V-R or N-V-R:E string
    @type nvre: str
    @return: (N-V-R, E)
    @rtype: (str, str)
    """

    if ":" in nvre:
        if nvre.count(":") != 1:
            raise ValueError("Invalid NVRE: %s" % nvre)

        nvr, epoch = nvre.rsplit(":", 1)
        if "-" in epoch:
            if "-" not in nvr:
                # switch nvr with epoch
                nvr, epoch = epoch, nvr
            else:
                # it's probably N-E:V-R format, handle it after the split
                nvr, epoch = nvre, ""
    else:
        nvr, epoch = nvre, ""

    return (nvr, epoch)


def parse_nvr(nvre):
    """Split N-V-R into a dictionary.

    @param nvre: N-V-R:E, E:N-V-R or N-E:V-R string
    @type nvre: str
    @return: {name, version, release, epoch}
    @rtype: dict
    """

    if "/" in nvre:
        nvre = nvre.split("/")[-1]

    nvr, epoch = split_nvr_epoch(nvre)

    nvr_parts = nvr.rsplit("-", 2)
    if len(nvr_parts) != 3:
        raise ValueError("Invalid NVR: %s" % nvr)

    # parse E:V
    if epoch == "" and ":" in nvr_parts[1]:
        epoch, nvr_parts[1] = nvr_parts[1].split(":", 1)

    # check if epoch is empty or numeric
    if epoch != "":
        try:
            int(epoch)
        except ValueError:
            raise ValueError("Invalid epoch '%s' in '%s'" % (epoch, nvr))

    result = dict(zip(["name", "version", "release"], nvr_parts))
    result["epoch"] = epoch
    return result


def to_nvre(build_record: Dict):
    """
    From a build record object (such as an entry returned by listTagged),
    returns the full nvre in the form n-v-r:E.
    """
    nvr = build_record['nvr']
    if 'epoch' in build_record and build_record["epoch"] and build_record["epoch"] != 'None':
        return f'{nvr}:{build_record["epoch"]}'
    return nvr


def strip_epoch(nvr: str):
    """
    If an NVR string is N-V-R:E, returns only the NVR portion. Otherwise
    returns NVR exactly as-is.
    """
    return nvr.split(':')[0]


# https://code.activestate.com/recipes/577504/
def total_size(o, handlers={}, verbose=False):
    """ Returns the approximate memory footprint an object and all of its contents.

    Automatically finds the contents of the following builtin containers and
    their subclasses:  tuple, list, deque, dict, set and frozenset.
    To search other containers, add handlers to iterate over their contents:

        handlers = {SomeContainerClass: iter,
                    OtherContainerClass: OtherContainerClass.get_elements}

    """
    dict_handler = lambda d: chain.from_iterable(d.items())
    all_handlers = {
        tuple: iter,
        list: iter,
        deque: iter,
        dict: dict_handler,
        set: iter,
        frozenset: iter,
    }
    all_handlers.update(handlers)  # user handlers take precedence
    seen = set()  # track which object id's have already been seen
    default_size = getsizeof(0)  # estimate sizeof object without __sizeof__

    def sizeof(o):
        if id(o) in seen:  # do not double count the same object
            return 0
        seen.add(id(o))
        s = getsizeof(o, default_size)

        if verbose:
            print(s, type(o), repr(o), file=stderr)

        for typ, handler in all_handlers.items():
            if isinstance(o, typ):
                s += sum(map(sizeof, handler(o)))
                break
        return s

    return sizeof(o)


def isolate_timestamp_in_release(release: str) -> Optional[str]:
    """
    Given a release field, determines whether is contains
    a timestamp. If it does, it returns the timestamp.
    If it is not found, None is returned.
    """
    match = re.search(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})", release)  # yyyyMMddHHmm
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        hour = int(match.group(4))
        minute = int(match.group(5))
        if year >= 2000 and month >= 1 and month <= 12 and day >= 1 and day <= 31 and hour <= 23 and minute <= 59:
            return match.group(0)
    return None


def get_golang_container_nvrs(nvrs, logger):
    all_build_objs = brew.get_build_objects([
        '{}-{}-{}'.format(*n) for n in nvrs
    ])
    go_container_nvrs = {}
    for build in all_build_objs:
        go_version = 'N/A'
        nvr = (build['name'], build['version'], build['release'])
        name = nvr[0]
        if 'golang-builder' in name or 'go-toolset' in name:
            go_version = golang_builder_version(nvr, logger)
            go_container_nvrs[name] = {
                'nvr': nvr,
                'go': go_version
            }
            continue

        try:
            parents = build['extra']['image']['parent_image_builds']
        except KeyError:
            logger.debug(f'Could not find parent build image for {nvr}')
            continue

        for p, pinfo in parents.items():
            if 'builder' in p or 'go-toolset' in p:
                go_version = pinfo.get('nvr')

        go_container_nvrs[name] = {
            'nvr': nvr,
            'go': go_version
        }
        if not go_version or go_version == 'N/A':
            logger.debug(f'Could not find parent Go builder image for {nvr}')

    return go_container_nvrs


def golang_builder_version(nvr, logger):
    go_version = 'N/A'
    try:
        build_log = brew.get_nvr_arch_log(*nvr)
    except BrewBuildException:
        logger.debug(f'Could not brew log for {nvr}')
    else:
        try:
            go_version = get_golang_version_from_build_log(build_log)
        except AttributeError:
            logger.debug(f'Could not find Go version in build log for {nvr}')
    return go_version


def get_golang_rpm_nvrs(nvrs, logger):
    go_rpm_nvrs = {}
    for nvr in nvrs:
        go_version = 'N/A'
        # what we build in brew as openshift
        # is called openshift-hyperkube in rhcos
        if nvr[0] == 'openshift-hyperkube':
            n = 'openshift'
            nvr = (n, nvr[1], nvr[2])

        try:
            root_log = brew.get_nvr_root_log(*nvr)
        except BrewBuildException:
            logger.debug(f'Could not find brew log for {nvr}')
        else:
            try:
                go_version = get_golang_version_from_build_log(root_log)[2]
            except AttributeError:
                logger.debug(f'Could not find go version in root log for {nvr}')

        go_rpm_nvrs[nvr[0]] = {
            'nvr': nvr,
            'go': go_version
        }
    return go_rpm_nvrs


def pretty_print_nvrs_go(nvrs, group=False, ignore_na=False):
    go_groups = {}
    for component in nvrs.keys():
        go_version = nvrs[component]['go']
        nvr = nvrs[component]['nvr']
        if go_version not in go_groups:
            go_groups[go_version] = []
        go_groups[go_version].append(nvr)

    if not group:
        green_print('NVR | Go Version')
    for go_version in sorted(go_groups.keys()):
        nvrs = go_groups[go_version]
        if go_version == 'N/A' and ignore_na:
            continue
        if group:
            green_print(f'Following nvrs are built with {go_version}:')
        for nvr in sorted(nvrs):
            pretty_nvr = '-'.join(nvr)
            if group:
                print(pretty_nvr)
            else:
                print(f'{pretty_nvr} | {go_version}')


# some of our systems refer to golang's architecture nomenclature; translate between that and brew arches
brew_arches = ["x86_64", "s390x", "ppc64le", "aarch64"]
brew_arch_suffixes = ["", "-s390x", "-ppc64le", "-aarch64"]
go_arches = ["amd64", "s390x", "ppc64le", "arm64"]
go_arch_suffixes = ["", "-s390x", "-ppc64le", "-arm64"]


def go_arch_for_brew_arch(brew_arch: str) -> str:
    if brew_arch in go_arches:
        return brew_arch   # allow to already be a go arch, just keep same
    if brew_arch in brew_arches:
        return go_arches[brew_arches.index(brew_arch)]
    raise Exception(f"no such brew arch '{brew_arch}' - cannot translate to golang arch")


def brew_arch_for_go_arch(go_arch: str) -> str:
    if go_arch in brew_arches:
        return go_arch  # allow to already be a brew arch, just keep same
    if go_arch in go_arches:
        return brew_arches[go_arches.index(go_arch)]
    raise Exception(f"no such golang arch '{go_arch}' - cannot translate to brew arch")


# imagestreams and such often began without consideration for multi-arch and then
# added a suffix everywhere to accommodate arches (but kept the legacy location for x86).
def go_suffix_for_arch(arch: str) -> str:
    arch = go_arch_for_brew_arch(arch)  # translate either incoming arch style
    return go_arch_suffixes[go_arches.index(arch)]


def brew_suffix_for_arch(arch: str) -> str:
    arch = brew_arch_for_go_arch(arch)  # translate either incoming arch style
    return brew_arch_suffixes[brew_arches.index(arch)]


def chunk(a_sequence: Sequence[Any], chunk_size: int) -> List[Any]:
    for i in range(0, len(a_sequence), chunk_size):
        yield a_sequence[i:i + chunk_size]
