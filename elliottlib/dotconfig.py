# This file is part of dotconfig project <https://github.com/adammhaile/dotconfig>
# and released under LGPL v3 <https://www.gnu.org/licenses/lgpl-3.0.en.html>

from __future__ import absolute_import, print_function, unicode_literals
from future.utils import string_types
import yaml
import os
import shutil


VALID_EXT = [
    'yaml',
    'yml',
    'json'
]


class Config(object):
    def __init__(self, app=None, name=None, base_dir='~/.config/',
                 template_file=None, template=None, envvars={},
                 defaults={}, cli_args={}, path_override=None,
                 file_override=None):
        """
        Automatically load an app config with environment variable and
        default overrides.
        Config file path will be {base_dir}/{app}/{name}.[yaml|yml|json]

        :param str app: Application name
        :param str name: Name of app sub-config
        :param str base_dir: Base config dir. Defaults to '~/.config/`
        :param str template_file: Template file to copy to given location if none exists
        :param str/dict template: YAML/JSON string or dict to write use as template
        if no config exists.
        :param dict envvars: Map of environment variables to map to keys. { key: APP_ENV_VAR }
        These override anything in the config file
        :param dict defaults: Default values for config keys
        :param dict cli_args: Config key overrides likely from the app CLI.
        These override any config file or env var values.
        :param str path_override: Specify direct path instead of default base dir
        :param str file_override: Direct path to config file to read

        :raises exceptions.IOError: when permissions denied
        """

        self.filename = None
        self.full_path = None

        if file_override is not None:
            self.full_path = file_override
            if not os.path.isfile(self.full_path):
                raise Exception('Unable to find specified file {}'.format(self.full_path))
        else:
            if path_override:
                self.base_dir = os.path.expanduser(path_override)
            else:
                self.base_dir = os.path.expanduser(os.path.join(base_dir, app))

            if not os.path.isdir(self.base_dir):
                os.makedirs(self.base_dir)

            for ext in VALID_EXT:
                for _ext in [ext, ext.upper()]:
                    filename = '{}.{}'.format(name, _ext)
                    cfg = os.path.join(self.base_dir, filename)
                    if os.path.isfile(cfg):
                        self.full_path = cfg
                        self.filename = filename
                        break

            if self.filename is None:
                self.filename = name + '.' + VALID_EXT[0]
                self.full_path = os.path.join(self.base_dir, self.filename)
                if template_file:
                    shutil.copyfile(template_file, self.full_path)
                else:
                    with open(self.full_path, 'w') as f:
                        if template:
                            if isinstance(template, string_types):
                                f.write(template)
                            elif isinstance(template, dict):
                                yaml.dump(template, f, default_flow_style=False)
                        else:
                            yaml.dump({}, f, default_flow_style=False)

        self._data = defaults
        with open(self.full_path, 'r') as f:
            data = yaml.full_load(f)
            self._data.update(data)
            # load envvars if given and override
            for k, v in envvars.items():
                if v in os.environ:
                    self._data[k] = os.environ[v]

            # finally, override with given cli args
            for k, v in cli_args.items():
                if k not in self._data or v is not None:
                    self._data[k] = v

    def __getitem__(self, item):
        return self._data[item]

    def items(self):
        return self._data.items()

    def to_dict(self):
        return dict(self._data)
