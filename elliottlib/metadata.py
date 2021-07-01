import re
import time
from builtins import object
from typing import Optional, Tuple

import yaml
from koji import ClientSession

from elliottlib import logutil
from elliottlib.assembly import assembly_basis_event, assembly_metadata_config
from elliottlib.brew import BuildStates
from elliottlib.model import Missing, Model

CONFIG_MODES = [
    'enable',  # business as usual
    'disable',  # manually disabled from automatically building
    'wip',  # Work in Progress, do not build
]

CONFIG_MODE_DEFAULT = CONFIG_MODES[0]


class Metadata(object):
    def __init__(self, meta_type, runtime, data_obj):
        """
        :param: meta_type - a string. Index to the sub-class <'rpm'|'image'>.
        :param: runtime - a Runtime object.
        :param: name - a filename to load as metadata
        """
        self.meta_type = meta_type
        self.runtime = runtime
        self.data_obj = data_obj
        self.base_dir = data_obj.base_dir
        self.config_filename = data_obj.filename
        self.full_config_path = data_obj.path

        # Some config filenames have suffixes to avoid name collisions; strip off the suffix to find the real
        # distgit repo name (which must be combined with the distgit namespace).
        # e.g. openshift-enterprise-mediawiki.apb.yml
        #      distgit_key=openshift-enterprise-mediawiki.apb
        #      name (repo name)=openshift-enterprise-mediawiki

        self.distgit_key = data_obj.key
        self.name = self.distgit_key.split('.')[0]   # Split off any '.apb' style differentiator (if present)

        self.runtime.logger.debug("Loading metadata from {}".format(self.full_config_path))

        self.raw_config = Model(data_obj.data)  # Config straight from ocp-build-data
        assert (self.raw_config.name is not Missing)

        self.config = assembly_metadata_config(runtime.get_releases_config(), runtime.assembly, meta_type, self.distgit_key, self.raw_config)
        self.namespace, self._component_name = Metadata.extract_component_info(meta_type, self.name, self.config)

        self.mode = self.config.get('mode', CONFIG_MODE_DEFAULT).lower()
        if self.mode not in CONFIG_MODES:
            raise ValueError('Invalid mode for {}'.format(self.config_filename))

        self.enabled = (self.mode == CONFIG_MODE_DEFAULT)

        self.qualified_name = "%s/%s" % (self.namespace, self.name)
        self.qualified_key = "%s/%s" % (self.namespace, self.distgit_key)

        # Includes information to identify the metadata being used with each log message
        self.logger = logutil.EntityLoggingAdapter(logger=self.runtime.logger, extra={'entity': self.qualified_key})

        self._distgit_repo = None

    def save(self):
        with open(self.full_config_path, "w") as f:
            yaml.safe_dump(self.config.primitive(), f, default_flow_style=False)

    def distgit_repo(self):
        if self._distgit_repo is None:
            DISTGIT_TYPES = {}  # F821 undefined name 'DISTGIT_TYPES'
            self._distgit_repo = DISTGIT_TYPES[self.meta_type](self)
        return self._distgit_repo

    def branch(self):
        if self.config.distgit.branch is not Missing:
            return self.config.distgit.branch
        return self.runtime.branch

    @classmethod
    def extract_component_info(cls, meta_type: str, meta_name: str, config_model: Model) -> Tuple[str, str]:
        """
        Determine the component information for either RPM or Image metadata
        configs.
        :param meta_type: 'rpm' or 'image'
        :param meta_name: The name of the component's distgit
        :param config_model: The configuration for the metadata.
        :return: Return (namespace, component_name)
        """

        # Choose default namespace for config data
        if meta_type == "image":
            namespace = "containers"
        else:
            namespace = "rpms"

        # Allow config data to override namespace
        if config_model.distgit.namespace is not Missing:
            namespace = config_model.distgit.namespace

        if namespace == "rpms":
            # For RPMS, component names must match package name and be in metadata config
            return namespace, config_model.name

        # For RPMs, by default, the component is the name of the distgit,
        # but this can be overridden in the config yaml.
        component_name = meta_name

        # For apbs, component name seems to have -apb appended.
        # ex. http://dist-git.host.prod.eng.bos.redhat.com/cgit/apbs/openshift-enterprise-mediawiki/tree/Dockerfile?h=rhaos-3.7-rhel-7
        if namespace == "apbs":
            component_name = "%s-apb" % component_name

        if namespace == "containers":
            component_name = "%s-container" % component_name

        if config_model.distgit.component is not Missing:
            component_name = config_model.distgit.component

        return namespace, component_name

    def get_component_name(self) -> str:
        """
        :return: Returns the component name of the metadata. This is the name in the nvr
        that brew assigns to component build. Component name is synonymous with package name.
        For RPMs, spec files declare the package name. For images, it is usually based on
        the distgit repo name + '-container'.
        """
        return self._component_name

    def branch_major_minor(self) -> str:
        """
        :return: Extracts and returns '{major}.{minor}' from the distgit branch.
        """
        split = self.branch().split('-')  # e.g. ['rhaos', '4.8', 'rhel', '8']
        return split[1]

    def get_latest_build(self, koji_api: ClientSession, event: Optional[int] = None, default=-1, assembly=None, extra_pattern='*', build_state: BuildStates = BuildStates.COMPLETE, el_target=None, honor_is=True):
        """
        :param koji_api: An instance of koji.ClientSession
        :param event: Brew event ID
        :param default: A value to return if no latest is found (if not specified, an exception will be thrown)
        :param assembly: A non-default assembly name to search relative to. If not specified, runtime.assembly
                         will be used. If runtime.assembly is also None, the search will return true latest.
                         If the assembly parameter is set to '', this search will also return true latest.
        :param extra_pattern: An extra glob pattern that must be matched in the middle of the
                         build's release field. Pattern must match release timestamp and components
                         like p? and git commit (up to, but not including ".assembly.<name>" release
                         component). e.g. "*.git.<commit>.*   or '*.p1.*'
        :param build_state: 0=BUILDING, 1=COMPLETE, 2=DELETED, 3=FAILED, 4=CANCELED
        :param el_target: In the case of an RPM, which can build for multiple targets, you can specify
                            '7' for el7, '8' for el8, etc. You can also pass in a brew target that
                            contains '....-rhel-?..' and the number will be extraced. If you want the true
                            latest, leave as None.
        :param honor_is: If True, and an assembly component specifies 'is', that nvr will be returned.
        :return: Returns the most recent build object from koji for this package & assembly.
                 Example https://gist.github.com/jupierce/57e99b80572336e8652df3c6be7bf664
        """
        component_name = self.get_component_name()
        builds = []

        package_info = koji_api.getPackage(component_name)  # e.g. {'id': 66873, 'name': 'atomic-openshift-descheduler-container'}
        if not package_info:
            raise IOError(f'No brew package is defined for {component_name}')
        package_id = package_info['id']  # we could just constrain package name using pattern glob, but providing package ID # should be a much more efficient DB query.
        # listBuilds returns all builds for the package; We need to limit the query to the builds
        # relevant for our major/minor.

        rpm_suffix = ''  # By default, find the latest RPM build - regardless of el7, el8, ...

        if self.meta_type == 'image':
            ver_prefix = 'v'  # openshift-enterprise-console-container-v4.7.0-202106032231.p0.git.d9f4379
        else:
            # RPMs do not have a 'v' in front of their version; images do.
            ver_prefix = ''  # openshift-clients-4.7.0-202106032231.p0.git.e29b355.el8
            if el_target:
                el_target = f'-rhel-{el_target}'  # Whether the incoming value is an int, decimal str, or a target, normalize for regex
                target_match = re.match(r'.*-rhel-(\d+)(?:-|$)', str(el_target))  # tolerate incoming int with str()
                if target_match:
                    rpm_suffix = f'.el{target_match.group(1)}'
                else:
                    raise IOError(f'Unable to determine rhel version from specified el_target: {el_target}')

        pattern_prefix = f'{component_name}-{ver_prefix}{self.branch_major_minor()}.'

        if assembly is None:
            assembly = self.runtime.assembly

        def default_return():
            msg = f"No builds detected for using prefix: '{pattern_prefix}', extra_pattern: '{extra_pattern}', assembly: '{assembly}', build_state: '{build_state.name}', el_target: '{el_target}'"
            if default != -1:
                self.logger.info(msg)
                return default
            raise IOError(msg)

        def latest_build_list(pattern_suffix):
            # Include * after pattern_suffix to tolerate:
            # 1. Matching an unspecified RPM suffix (e.g. .el7).
            # 2. Other release components that might be introduced later.
            builds = koji_api.listBuilds(packageID=package_id,
                                         state=None if build_state is None else build_state.value,
                                         pattern=f'{pattern_prefix}{extra_pattern}{pattern_suffix}*{rpm_suffix}',
                                         queryOpts={'limit': 1, 'order': '-creation_event_id'})

            # Ensure the suffix ends the string OR at least terminated by a '.' .
            # This latter check ensures that 'assembly.how' doesn't not match a build from
            # "assembly.howdy'.
            refined = [b for b in builds if b['nvr'].endswith(pattern_suffix) or f'{pattern_suffix}.' in b['nvr']]

            if refined and build_state == BuildStates.COMPLETE:
                # A final sanity check to see if the build is tagged with something we
                # respect. There is a chance that a human may untag a build. There
                # is no standard practice at present in which they should (they should just trigger
                # a rebuild). If we find the latest build is not tagged appropriately, blow up
                # and let a human figure out what happened.
                check_nvr = refined[0]['nvr']
                for i in range(2):
                    tags = {tag['name'] for tag in koji_api.listTags(build=check_nvr)}
                    if tags:
                        refined[0]['_tags'] = tags  # save tag names to dict for future use
                        break
                    # Observed that a complete build needs some time before it gets tagged. Give it some
                    # time if not immediately available.
                    time.sleep(60)

                # RPMS have multiple targets, so our self.branch() isn't perfect.
                # We should permit rhel-8/rhel-7/etc.
                tag_prefix = self.branch().rsplit('-', 1)[0] + '-'   # String off the rhel version.
                accepted_tags = [name for name in tags if name.startswith(tag_prefix)]
                if not accepted_tags:
                    raise IOError(f'Expected to find at least one tag starting with {self.branch()} on latest build {check_nvr} but found [{tags}]; something has changed tags in an unexpected way')

            return refined

        if honor_is and self.config['is']:
            if build_state != BuildStates.COMPLETE:
                # If this component is defined by 'is', history failures, etc, do not matter.
                return default_return()

            # under 'is' for RPMs, we expect 'el7' and/or 'el8', etc. For images, just 'nvr'.
            isd = self.config['is']
            if self.meta_type == 'rpm':
                if el_target is None:
                    raise ValueError(f'Expected el_target to be set when querying a pinned RPM component {self.distgit_key}')
                is_nvr = isd[f'el{el_target}']
                if not is_nvr:
                    return default_return()
            else:
                # The image metadata (or, more likely, the currently assembly) has the image
                # pinned. Return only the pinned NVR. When a child image is being rebased,
                # it uses get_latest_build to find the parent NVR to use (if it is not
                # included in the "-i" doozer argument). We need it to find the pinned NVR
                # to place in its Dockerfile.
                # Pinning also informs gen-payload when attempting to assemble a release.
                is_nvr = isd.nvr
                if not is_nvr:
                    raise ValueError(f'Did not find nvr field in pinned Image component {self.distgit_key}')

            # strict means raise an exception if not found.
            found_build = koji_api.getBuild(is_nvr, strict=True)
            # Different brew apis return different keys here; normalize to make the rest of doozer not need to change.
            found_build['id'] = found_build['build_id']
            return found_build

        if not assembly:
            # if assembly is '' (by parameter) or still None after runtime.assembly,
            # we are returning true latest.
            builds = latest_build_list('')
        else:
            basis_event = assembly_basis_event(self.runtime.get_releases_config(), assembly=assembly)
            if basis_event:
                self.logger.warning(f'Constraining image search to stream assembly due to assembly basis event {basis_event}')
                # If an assembly has a basis event, its latest images can only be sourced from
                # "is:" or the stream assembly. We've already checked for "is" above.
                assembly = 'stream'

            # Assemblies without a basis will return assembly qualified builds for their
            # latest images. This includes "stream" and "test", but could also include
            # an assembly that is customer specific  with its own branch.
            builds = latest_build_list(f'.assembly.{assembly}')
            if not builds:
                if assembly != 'stream':
                    builds = latest_build_list('.assembly.stream')
                if not builds:
                    # Fall back to true latest
                    builds = latest_build_list('')
                    if builds and '.assembly.' in builds[0]['release']:
                        # True latest belongs to another assembly. In this case, just return
                        # that they are no builds for this assembly.
                        builds = []

        if not builds:
            return default_return()

        found_build = builds[0]
        # Different brew apis return different keys here; normalize to make the rest of doozer not need to change.
        found_build['id'] = found_build['build_id']
        return found_build
