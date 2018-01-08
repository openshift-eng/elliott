import os
import glob
import traceback
import yaml
from common import (
    BREW_IMAGE_HOST, CGIT_URL, RetryException,
    assert_rc0, assert_file, assert_exec, assert_dir,
    exec_cmd, gather_exec, retry, Dir, recursive_overwrite, watch_task,
)
from model import Model, Missing
from distgit import DistGitRepo
from metadata import Metadata
import time


RELEASERS_CONF = """
[aos]
releaser = tito.release.DistGitReleaser
branches = {branch}
srpm_disttag = .el7aos
builder.test = 1
remote_git_name = {name}
"""

TITO_PROPS = """

[aos]
remote_git_name = {name}
"""


class RPMMetadata(Metadata):

    def __init__(self, runtime, dir, name):
        super(RPMMetadata, self).__init__('rpm', runtime, dir, name)

        self.info = self.runtime.info

        self.source = self.config.content.source
        if self.source is Missing:
            raise ValueError('RPM config must contain source entry.')
        self.source_path = self.runtime.resolve_source(self.source.alias)
        if self.source.specfile:
            self.specfile = os.path.join(self.source_path, self.source.specfile)
            if not os.path.isfile(self.specfile):
                raise ValueError('{} config specified a spec file that does not exist: {}'.format(
                    name, self.specfile
                ))
        else:
            with Dir(self.source_path):
                specs = []
                for spec in glob.glob('*.spec'):
                    specs.append(spec)
                if len(specs) > 1:
                    raise ValueError('More than one spec file found. Specify correct file in config.yml')
                elif len(specs) == 0:
                    raise ValueError('Unable to find any spec files in {}'.format(self.source_path))
                else:
                    self.specfile = os.path.join(self.source_path, specs[0])

        self.rpm_name = self.config.name
        self.version = None
        self.release = None
        self.tag = None
        self.build_status = False

    def set_nvr(self, version, release):
        self.version = version
        self.release = release
        self.tag = '{}-{}-{}'.format(self.config.name, self.version, self.release)

    def create_tag(self):
        if not self.tag:
            raise ValueError('Must run set_nvr() before calling!')

        with Dir(self.source_path):
            assert_exec(self.runtime, 'git tag {}'.format(self.tag))

    def push_tag(self):
        if not self.tag:
            raise ValueError('Must run set_nvr() before calling!')

        with Dir(self.source_path):
            assert_exec(self.runtime, 'git push origin {}'.format(self.tag))

    def commit_changes(self):
        with Dir(self.source_path):
            assert_exec(self.runtime, "git add .")
            assert_exec(self.runtime, ['git', 'commit', '-m', "Local commit for dist-git build"])

    def tito_setup(self):
        tito_dir = os.path.join(self.source_path, '.tito')
        with Dir(self.source_path):
            if not os.path.isdir(tito_dir):
                assert_exec(self.runtime, 'tito init')

            with open(os.path.join(tito_dir, 'releasers.conf'), 'w') as r:
                r.write(RELEASERS_CONF.format(branch=self.runtime.branch,
                                              name=self.name))
                r.flush()

            # fix for tito 0.6.10 which looks like remote_git_name in wrong place
            with open(os.path.join(tito_dir, 'tito.props'), 'a') as props:
                props.write(TITO_PROPS.format(name=self.name))
                props.flush()

    def _run_modifications(self):
        """
        Interprets and applies content.source.modify steps in the image metadata.
        """
        with open(self.specfile, 'r') as df:
            specfile_data = df.read()

        self.runtime.log_verbose("\nAbout to start modifying spec file [%s]:\n%s\n" %
                                 (self.name, specfile_data))

        for modification in self.config.content.source.modifications:
            if modification.action == "replace":
                match = modification.match
                assert (match is not Missing)
                replacement = modification.replacement
                assert (replacement is not Missing)
                pre = specfile_data
                specfile_data = pre.replace(match, replacement)
                if specfile_data == pre:
                    raise IOError("Replace (%s->%s) modification did not make a change to the Dockerfile content" % (
                        match, replacement))
                self.runtime.log_verbose("\nPerformed string replace '%s' -> '%s':\n%s\n" %
                                         (match, replacement, specfile_data))
            else:
                raise IOError("Don't know how to perform modification action: %s" % modification.action)

        with open(self.specfile, 'w') as df:
            df.write(specfile_data)

    def update_spec(self):
        replace = {
            'Name:': 'Name:           {}\n'.format(self.config.name),
            'Version:': 'Version:        {}\n'.format(self.version),
            'Release:': 'Release:        {}%{{?dist}}\n'.format(self.release),
        }

        replace_keys = replace.keys()

        with Dir(self.source_path):
            # run generic modifications first
            if self.config.content.source.modifications is not Missing:
                self._run_modifications()

            # second, update with NVR
            lines = []
            with open(self.specfile, 'r+') as sf:
                lines = sf.readlines()
                for i in range(len(lines)):
                    if len(replace_keys):
                        for k in replace_keys:
                            v = replace[k]
                            if lines[i].startswith(k):
                                lines[i] = v
                                replace_keys.remove(k)
                    else:
                        break  # no more replacements, drop out
                # truncate the original file
                sf.seek(0)
                sf.truncate()
                # write back new lines
                sf.writelines(lines)

    def _build_rpm(self, scratch, record):
        """
        The part of `build_container` which actually starts the build,
        separated for clarity.
        """
        with Dir(self.source_path):
            self.info("Building rpm: %s" % self.rpm_name)

            cmd_list = ['tito', 'release', '--debug', '--yes', '--test']
            if scratch:
                cmd_list.append('--scratch')
            cmd_list.append('aos')

            # Run the build with --nowait so that we can immediately get information about the brew task
            rc, out, err = gather_exec(self.runtime, cmd_list)

            if rc != 0:
                # Probably no point in continuing.. can't contact brew?
                self.info("Unable to create brew task: out={}  ; err={}".format(out, err))
                return False

            # Otherwise, we should have a brew task we can monitor listed in the stdout.
            out_lines = out.splitlines()

            # Look for a line like: "Created task: 13949050" . Extract the identifier.
            task_id = next((created_line.split(":")[1]).strip() for created_line in out_lines if
                           created_line.startswith("Created task:"))

            record["task_id"] = task_id

            # Look for a line like: "Task info: https://brewweb.engineering.redhat.com/brew/taskinfo?taskID=13948942"
            task_url = next((info_line.split(":", 1)[1]).strip() for info_line in out_lines if
                            info_line.startswith("Task info:"))

            self.info("Build running: {} - {}".format(self.rpm_name, task_url))

            record["task_url"] = task_url

            # Now that we have the basics about the task, wait for it to complete
            rc, out, err = watch_task(self.info, task_id)

            # Gather brew-logs
            logs_dir = "%s/%s" % (self.runtime.brew_logs_dir, self.name)
            logs_rc, logs_out, logs_err = gather_exec(self.runtime, ["brew", "download-logs", "-d", logs_dir, task_id])

            if logs_rc != 0:
                self.info("Error downloading build logs from brew for task %s: %s" % (task_id, logs_err))

            if rc != 0:
                # An error occurred during watch-task. We don't have a viable build.
                self.info("Error building rpm: {}\nout={}  ; err={}".format(task_url, out, err))
                return False

            self.info("Successfully built rpm: {} ; {}".format(self.rpm_name, task_url))
        return True

    def build_rpm(self, version, release, scratch=False, retries=3):
        self.set_nvr(version, release)
        self.create_tag()
        self.tito_setup()
        self.update_spec()
        self.commit_changes()
        action = "build_rpm"
        record = {
            "specfile": "{}/{}".format(self.source_path, self.specfile),
            "rpm": self.rpm_name,
            "version": self.version,
            "release": self.release,
            "message": "Unknown failure",
            "status": -1,
            # Status defaults to failure until explicitly set by succcess. This handles raised exceptions.
        }

        try:
            def wait(n):
                self.info("Async error in rpm build thread [attempt #{}]: {}".format(n + 1, self.qualified_name))
                # Brew does not handle an immediate retry correctly.
                time.sleep(5 * 60)  # wait 5 minutes
            try:
                retry(
                    n=3, wait_f=wait,
                    f=lambda: self._build_rpm(scratch, record))
            except RetryException as err:
                self.info(str(err))
                return False

            record["message"] = "Success"
            record["status"] = 0
            self.build_status = True

        except Exception:
            tb = traceback.format_exc()
            record["message"] = "Exception occurred:\n{}".format(tb)
            self.info("Exception occurred during build:\n{}".format(tb))
            # This is designed to fall through to finally. Since this method is designed to be
            # threaded, we should not throw an exception; instead return False.
        finally:
            self.runtime.add_record(action, **record)

        if self.build_status:
            try:
                self.push_tag()
            except:
                raise RuntimeError('Build succeeded but failure pushing RPM tag.')

        return self.build_status
