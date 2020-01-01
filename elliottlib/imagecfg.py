from __future__ import absolute_import, print_function, unicode_literals
from . import assertion
from . import exectools
from . import logutil
from .metadata import Metadata

logger = logutil.getLogger(__name__)


class ImageMetadata(Metadata):

    def __init__(self, runtime, data_obj):
        super(ImageMetadata, self).__init__('image', runtime, data_obj)
        self.image_name = self.config.name
        self.image_name_short = self.image_name.split('/')[-1]

    @property
    def base_only(self):
        """
        Some images are marked base-only.  Return the flag from the config file
        if present.
        """
        return self.config.base_only

    def get_latest_build_info(self, product_version):
        """
        Queries brew to determine the most recently built release of the component
        associated with this image. This method does not rely on the "release"
        label needing to be present in the Dockerfile.

        :return: A tuple: (component name, version, release); e.g. ("registry-console-docker", "v3.6.173.0.75", "1")
        """

        component_name = self.get_component_name()

        tag = "{}-candidate".format(self.branch())

        rc, stdout, stderr = exectools.cmd_gather(["brew", "latest-build", tag, component_name])

        assertion.success(rc, "Unable to search brew builds: %s" % stderr)

        latest = stdout.strip().splitlines()[-1].split(' ')[0]

        if not latest.startswith(component_name):
            # If no builds found, `brew latest-build` output will appear as:
            # Build                                     Tag                   Built by
            # ----------------------------------------  --------------------  ----------------
            raise IOError("No builds detected for %s using tag: %s" % (self.qualified_name, tag))

        # latest example: "registry-console-docker-v3.6.173.0.75-1""
        name, version, release = latest.rsplit("-", 2)  # [ "registry-console-docker", "v3.6.173.0.75", "1"]

        return name, version, release, product_version[self.name]
