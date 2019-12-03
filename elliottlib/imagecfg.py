from __future__ import absolute_import, print_function, unicode_literals
from . import assertion
from . import exectools
from . import logutil
from . import exceptions
import json
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

    def get_latest_build_info(self, product_version_dict, tag_set, latest_builds, brew_session):
        """
        Queries brew to determine the most recently built release of the component
        associated with this image. This method does not rely on the "release"
        label needing to be present in the Dockerfile.

        :return: A tuple: (component name, version, release, product_version); e.g. ("registry-console-docker", "v3.6.173.0.75", "1", "OSE-4.1-RHEL-8")
        """
        component_name = self.get_component_name()
        tag = "{}-candidate".format(self.branch())
        if tag not in tag_set:
            tags = brew_session.getLatestBuilds(tag)
            for t in tags:
                latest_builds[t['name']] = t['nvr']
            tag_set.add(tag)

        nvr = latest_builds.get(component_name, "")
        if nvr != "":
            name, version, release = nvr.rsplit("-", 2)
            return name, version, release, product_version_dict[self.name]

        # If no builds found
        raise exceptions.BrewBuildException("No builds detected for %s using tag: %s" % (component_name, tag))
