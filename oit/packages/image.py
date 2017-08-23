import yaml
import string

from common import *
from model import *


class ImageMetadata(object):

    def __init__(self, runtime, dir, name):
        self.runtime = runtime
        self.dir = os.path.abspath(dir)
        self.config_path = os.path.join(self.dir, "config.yml")
        self.name = name

        runtime.verbose("Loading image metadata for %s from %s" % (name, self.config_path))

        assert_file(self.config_path, "Unable to find image configuration file")

        # Create an array of lines to eliminate the possibility of linefeed differences
        config_yml_lines = list(runtime.global_yaml_lines)
        with open(self.config_path, "r") as f:
            for line in f.readlines():
                config_yml_lines.append(line.rstrip())

        config_yml_content = "\n".join(config_yml_lines)
        runtime.verbose(config_yml_content)
        self.config = Model(yaml.load(config_yml_content))

        self.type = "rpms" # default type is rpms
        if self.config.repo.type is not Missing:
            self.type = self.config.repo.type

        self.qualified_name = "%s/%s" % (self.type, name)

        self.distgit_dir = None

    def clone_distgit(self):
        with Dir(self.runtime.distgits_dir):
            cmd_list = ["rhpkg"]

            if self.runtime.user is not None:
                cmd_list.append("--user=%s" % self.runtime.user)

            cmd_list.extend(["clone", self.qualified_name])

            self.distgit_dir = os.path.join(os.getcwd(), self.name)

            self.runtime.info("Cloning distgit repository: %s" % self.qualified_name, self.distgit_dir)

            # Clone the distgit repository
            assert_exec(self.runtime, cmd_list)


            with Dir(self.distgit_dir):
                # Switch to the target branch
                assert_exec(self.runtime, ["rhpkg", "switch-branch", self.runtime.distgit_branch])




