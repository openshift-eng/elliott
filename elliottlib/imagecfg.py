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

    @property
    def is_release(self):
        return self.config.get('for_release', True)

    @property
    def is_payload(self):
        return self.config.get('for_payload', False)
