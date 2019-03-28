import metadata
import yaml
from pykwalify.core import Core
import os
import shutil
from pushd import Dir
import exectools
import sys


VALID_UPDATES = {
    'mode': metadata.CONFIG_MODES,
}


# Used in oit.py to print out valid update options
# in --help output
def valid_updates():
    res = '\n\tKey\tValid Options\n\n'
    for k, v in VALID_UPDATES.iteritems():
        opts = ""
        if v:
            v = [str(i) for i in v]
            opts = ':\t{}'.format(','.join(v))
        res += '\t{}{}\n\n'.format(k, opts)
    return res


class MetaDataConfig(object):
    """
    Holds common functions for managing the MetaData configs
    Mostly is a class to hold runtime
    """
    def __init__(self, runtime):
        self.runtime = runtime
        if self.runtime.remove_tmp_working_dir:
            print('config:* options require a non-temporary working space. Must run with --working-dir')
            sys.exit(1)

    def _load_config_log(self):
        """
        <working_dir>/.config file holds details of the current
        config management session
        Load that file into a dict
        """
        config_path = os.path.join(self.runtime.working_dir, '.config')
        if not os.path.isfile(config_path):
            return {}
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
        return data

    def _save_config_log(self, data):
        """
        <working_dir>/.config file holds details of the current
        config management session
        Save that file
        """
        config_path = os.path.join(self.runtime.working_dir, '.config')
        with open(config_path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    def _do_update(self, meta, k, v):
        """
        Convenience function for setting meta keys
        """
        self.runtime.logger.info('{}: [{}] -> {}'.format(meta.in_group_config_path, k, v))
        meta.config[k] = v
        meta.save()

    def update(self, key, val):
        """
        Update [key] to [val] in all given image/rpm metas
        VALID_UPDATES is used to lock out what can be updated
        Right now only [mode] is valid, but that may change
        """
        if key not in VALID_UPDATES:
            raise ValueError('{} is not a valid update key. See --help'.format(key))

        if VALID_UPDATES[key]:
            if val not in VALID_UPDATES[key]:
                msg = '{} is not a valid value for {}. Use one of: {}'.format(val, key, ','.join(VALID_UPDATES[key]))
                raise ValueError(msg)

        for img in self.runtime.image_metas():
            self._do_update(img, key, val)

        for rpm in self.runtime.rpm_metas():
            self._do_update(rpm, key, val)

    def config_print(self, key=None, name_only=False):
        """
        Print name, sub-key, or entire config
        """
        def _do_print(meta, k):
            if name_only:
                print(meta.in_group_config_path)
            else:
                if k:
                    val = meta.config.get(k, None)
                else:
                    val = meta.config.primitive()

                val = yaml.safe_dump(val, default_flow_style=False)

                print("*****" + meta.in_group_config_path + "*****")
                print(val)
                print('')

        image_metas = self.runtime.image_metas()
        rpm_metas = self.runtime.rpm_metas()

        if image_metas:
            print('')
            print('********* Images *********')
            for img in image_metas:
                _do_print(img, key)

        if rpm_metas:
            print('')
            print('*********  RPMs  *********')
            for rpm in rpm_metas:
                _do_print(rpm, key)

    def commit(self, msg):
        """
        Commit outstanding metadata config changes
        """
        self.runtime.logger.info('Commit config: {}'.format(msg))
        with Dir(self.runtime.metadata_dir):
            exectools.cmd_assert(["git", "add", "."])
            exectools.cmd_assert(["git", "commit", "--allow-empty", "-m", msg])

    def push(self):
        """
        Push changes back to config repo.
        Will of course fail if user does not have write access.
        """
        self.runtime.logger.info('Pushing config...')
        with Dir(self.runtime.metadata_dir):
            exectools.cmd_assert(["git", "push"])

    def new(self, new_type, name):
        """
        Given type and name, copy template config into correct place
        and report that new config file path for editing.
        """
        valid_types = ['image', 'rpm']
        new_type = new_type.lower()
        if new_type not in valid_types:
            raise ValueError('Type must be one of {}'.format(','.join(valid_types)))

        new_type = new_type + 's'
        template = os.path.join(self.runtime.metadata_dir, 'example', new_type, 'template.yml')
        new_config = os.path.join(self.runtime.group_dir, new_type, '{}.yml'.format(name))

        if os.path.exists(new_config):
            raise ValueError('{} already exists!'.format(new_config))

        shutil.copyfile(template, new_config)

        config_log = self._load_config_log()
        config_log.setdefault('new', []).append(new_config)

        self._save_config_log(config_log)

        self.runtime.logger.info("New config template created: \n{}".format(new_config))

    def sanitize_new_config(self):
        """
        Configs created with new() will be filled with template comments.
        We do not want those cluttering the final configs, so remove them
        by parsing and rewriting the file.
        """
        config_log = self._load_config_log()
        if 'new' in config_log:
            for cfg in config_log['new']:
                with open(cfg, 'r+') as f:
                    data = yaml.safe_load(f)
                    f.seek(0)
                    yaml.safe_dump(data, f, default_flow_style=False)
                    f.truncate()
            del config_log['new']

        self._save_config_log(config_log)

