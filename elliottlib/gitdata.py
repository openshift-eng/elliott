# This file is part of gitdata project <https://github.com/adammhaile/gitdata>
# and released under LGPL v3 <https://www.gnu.org/licenses/lgpl-3.0.en.html>
from __future__ import absolute_import, print_function, unicode_literals
from future.utils import as_native_str
from future.standard_library import install_aliases
install_aliases()
from urllib.parse import urlparse

import yaml
import ruamel.yaml
import ruamel.yaml.util
import logging
import os
import shutil
from . import exectools
from .pushd import Dir


SCHEMES = ['ssh', 'ssh+git', "http", "https"]


class GitDataException(Exception):
    """A broad exception for errors during GitData operations"""
    pass


class GitDataBranchException(GitDataException):
    pass


class GitDataPathException(GitDataException):
    pass


class DataObj(object):
    def __init__(self, key, path, data):
        self.key = key
        self.path = path
        self.base_dir = os.path.dirname(self.path)
        self.filename = self.path.replace(self.base_dir, '').strip('/')
        self.data = data
        self.indent = 2
        self.block_seq_indent = None

    @as_native_str()
    def __repr__(self):
        result = {
            'key': self.key,
            'path': self.path,
            'data': self.data
        }
        return str(result)

    def reload(self):
        with open(self.path, 'r') as f:
            # Reload with ruamel.yaml and guess the indent.
            self.data, self.indent, self.block_seq_indent = ruamel.yaml.util.load_yaml_guess_indent(f, preserve_quotes=True)

    def save(self):
        with open(self.path, 'w') as f:
            # pyyaml doesn't preserve the order of keys or comments when loading and saving yamls. Save with ruamel.yaml instead to keep the format as much as possible.
            ruamel.yaml.round_trip_dump(self.data, f, indent=self.indent, block_seq_indent=self.block_seq_indent)


class GitData(object):
    def __init__(self, data_path=None, clone_dir='./', branch='main',
                 sub_dir=None, exts=['yaml', 'yml', 'json'], logger=None):
        """
        Load structured data from a git source.
        :param str data_path: Git url (git/http/https) or local directory path
        :param str clone_dir: Location to clone data into
        :param str branch: Repo branch (tag or sha also allowed) to checkout
        :param str sub_dir: Sub dir in data to treat as root
        :param list exts: List of valid extensions to search for in data, with out period
        :param logger: Python logging object to use
        :raises GitDataException:
        """
        self.logger = logger
        if logger is None:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger()

        self.clone_dir = clone_dir
        self.branch = branch

        self.remote_path = None
        self.sub_dir = sub_dir
        self.exts = ['.' + e.lower() for e in exts]
        if data_path:
            self.clone_data(data_path)

    def clone_data(self, data_path):
        """
        Clones data for given data_path:
        :param str data_path: Git url (git/http/https) or local directory path
        """
        self.data_path = data_path

        data_url = urlparse(self.data_path)
        if data_url.scheme in SCHEMES or (data_url.scheme == '' and ':' in data_url.path):
            data_name = os.path.splitext(os.path.basename(data_url.path))[0]
            data_destination = os.path.join(self.clone_dir, data_name)
            clone_data = True
            if os.path.isdir(data_destination):
                self.logger.info('Data clone directory already exists, checking commit sha')
                with Dir(data_destination):
                    # check the current status of what's local
                    rc, out, err = exectools.cmd_gather("git status -sb")
                    if rc:
                        raise GitDataException('Error getting data repo status: {}'.format(err))

                    lines = out.strip().split('\n')
                    synced = ('ahead' not in lines[0] and 'behind' not in lines[0] and len(lines) == 1)

                    # check if there are unpushed
                    # verify local branch
                    rc, out, err = exectools.cmd_gather("git rev-parse --abbrev-ref HEAD")
                    if rc:
                        raise GitDataException('Error checking local branch name: {}'.format(err))
                    branch = out.strip()
                    if branch != self.branch:
                        if not synced:
                            msg = ('Local branch is `{}`, but requested `{}` and you have uncommitted/pushed changes\n'
                                   'You must either clear your local data or manually checkout the correct branch.'
                                   ).format(branch, self.branch)
                            raise GitDataBranchException(msg)
                    else:
                        # Check if local is synced with remote
                        rc, out, err = exectools.cmd_gather(["git", "ls-remote", self.data_path, self.branch])
                        if rc:
                            raise GitDataException('Unable to check remote sha: {}'.format(err))
                        remote = out.strip().split('\t')[0]
                        try:
                            exectools.cmd_assert('git branch --contains {}'.format(remote))
                            self.logger.info('{} is already cloned and latest'.format(self.data_path))
                            clone_data = False
                        except:
                            if not synced:
                                msg = ('Local data is out of sync with remote and you have unpushed commits: {}\n'
                                       'You must either clear your local data\n'
                                       'or manually rebase from latest remote to continue'
                                       ).format(data_destination)
                                raise GitDataException(msg)

            if clone_data:
                if os.path.isdir(data_destination):  # delete if already there
                    shutil.rmtree(data_destination)
                self.logger.info('Cloning config data from {}'.format(self.data_path))
                if not os.path.isdir(data_destination):
                    cmd = "git clone -b {} --depth 1 {} {}".format(self.branch, self.data_path, data_destination)
                    rc, out, err = exectools.cmd_gather(cmd)
                    if rc:
                        raise GitDataException('Error while cloning data: {}'.format(err))

            self.remote_path = self.data_path
            self.data_path = data_destination
        elif data_url.scheme in ['', 'file']:
            self.remote_path = None
            self.data_path = os.path.abspath(self.data_path)  # just in case relative path was given
        else:
            raise ValueError(
                'Invalid data_path: {} - invalid scheme: {}'
                .format(self.data_path, data_url.scheme)
            )

        if self.sub_dir:
            self.data_dir = os.path.join(self.data_path, self.sub_dir)
        else:
            self.data_dir = self.data_path
        if not os.path.isdir(self.data_dir):
            raise GitDataPathException('{} is not a valid sub-directory in the data'.format(self.sub_dir))

    def bz(self):
        return self.load_data(key='bugzilla')

    def bz_server_url(self):
        return self.bz().data['server']

    def bz_target_release(self):
        return self.bz().data['target_release']

    def load_data(self, path='', key=None, keys=None, exclude=None, filter_funcs=None, replace_vars={}):
        full_path = os.path.join(self.data_dir, path.replace('\\', '/'))
        if path and not os.path.isdir(full_path):
            raise GitDataPathException('Cannot find "{}" under "{}"'.format(path, self.data_dir))

        if filter_funcs is not None and not isinstance(filter_funcs, list):
            filter_funcs = [filter_funcs]

        if exclude is not None and not isinstance(exclude, list):
            exclude = [exclude]

        if key and keys:
            raise GitDataException('Must use key or keys, but not both!')

        if key:
            keys = [key]

        if keys:
            if not isinstance(keys, list):
                keys = [keys]
            files = []
            for k in keys:
                for ext in self.exts:
                    path = k + ext
                    if os.path.isfile(os.path.join(full_path, k + ext)):
                        files.append(path)
                        break  # found for this key, move on
        else:
            files = os.listdir(full_path)

        result = {}

        for name in files:
            base_name, ext = os.path.splitext(name)
            if ext.lower() in self.exts:
                data_file = os.path.join(full_path, name)
                if os.path.isfile(data_file):
                    with open(data_file, 'r') as f:
                        raw_text = f.read()
                        if replace_vars:
                            try:
                                raw_text = raw_text.format(**replace_vars)
                            except KeyError as e:
                                self.logger.warning('{} contains template key `{}` but no value was provided'.format(data_file, e.args[0]))
                        data = yaml.full_load(raw_text)
                        use = True
                        if exclude and base_name in exclude:
                            use = False

                        if use and filter_funcs:
                            for func in filter_funcs:
                                use &= func(base_name, data)
                                if not use:
                                    break

                        if use:
                            result[base_name] = DataObj(base_name, data_file, data)

        if key and key in result:
            result = result[key]

        return result

    def commit(self, msg):
        """
        Commit outstanding data changes
        """
        self.logger.info('Commit config: {}'.format(msg))
        with Dir(self.data_path):
            exectools.cmd_assert('git add .')
            exectools.cmd_assert('git commit --allow-empty -m "{}"'.format(msg))

    def push(self):
        """
        Push changes back to data repo.
        Will of course fail if user does not have write access.
        """
        self.logger.info('Pushing config...')
        with Dir(self.data_path):
            exectools.cmd_assert('git push')
