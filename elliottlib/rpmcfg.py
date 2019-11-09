from __future__ import absolute_import
from __future__ import unicode_literals
import glob
import os
from .pushd import Dir
from .metadata import Metadata
from .model import Missing


class RPMMetadata(Metadata):

    def __init__(self, runtime, data_obj, clone_source=True):
        super(RPMMetadata, self).__init__('rpm', runtime, data_obj)

        self.source = self.config.content.source
        if self.source is Missing:
            raise ValueError('RPM config must contain source entry.')

        self.rpm_name = self.config.name
        self.version = None
        self.release = None
        self.tag = None
        self.commit_sha = None
        self.build_status = False

        if clone_source:
            self.source_path = self.runtime.resolve_source(self.source.alias)
            self.source_head = self.runtime.resolve_source_head(self.source.alias)
            if self.source.specfile:
                self.specfile = os.path.join(self.source_path, self.source.specfile)
                if not os.path.isfile(self.specfile):
                    config_filename = '???'  # F821 undefined name 'config_filename'
                    raise ValueError('{} config specified a spec file that does not exist: {}'.format(
                        config_filename, self.specfile
                    ))
            else:
                with Dir(self.source_path):
                    specs = []
                    for spec in glob.glob('*.spec'):
                        specs.append(spec)
                    if len(specs) > 1:
                        raise ValueError('More than one spec file found. Specify correct file in config yaml')
                    elif len(specs) == 0:
                        raise ValueError('Unable to find any spec files in {}'.format(self.source_path))
                    else:
                        self.specfile = os.path.join(self.source_path, specs[0])
