import shlex
import exectools
import logutil
import constants

logger = logutil.getLogger(__name__)


class DockerContainer(object):
    """This is an abstraction for launching containers from images and
then running a subset of operations in the new container."""

    def __init__(self, image, autostart=False):
        self.image = image
        self.name_tag = image.split('/')[-1]
        self.logger = logutil.EntityLoggingAdapter(logger, {'entity': '{}'.format(self.name_tag)})
        self.cid = None
        if autostart:
            self.start()

    def _cmd(self, cmd):
        """Run a docker related command"""
        return exectools.cmd_gather(shlex.split(cmd))

    def start(self):
        """Start the container"""
        run_str = 'docker run --network=host -d -ti -u 0 --entrypoint /bin/bash {img}'.format(img=self.image)
        self.logger.info("[Verify] image: {img}".format(img=self.name_tag))
        # TODO: Check if this failed
        rc, stdout, stderr = self._cmd(run_str)
        self.cid = stdout.rstrip()

    def stop(self):
        """Stop the container"""
        return self._cmd('docker stop {cid}'.format(cid=self.cid))

    def rm(self):
        """Erase the used container"""
        return self._cmd('docker rm {cid}'.format(cid=self.cid))

    def execute(self, cmd):
        """Execute a command in the container

        :param string cmd: The command to run the the container. This
        will be automatically split into a shell acceptable format
        using the shlex library. Fancy/tedious escaping of quote
        characters is not necessary.

        """
        return self._cmd('docker exec {cid} {cmd}'.format(cid=self.cid, cmd=cmd))

    def copy_into(self, source, dest):
        """Copy a file into the container

        :param string source: The fully qualified path to the file to
        copy into the container

        :param string dest: The destination directory to copy the
        `source` file into in the container

        """
        return self._cmd('docker cp {source} {cid}:{dest}'.format(source=source, cid=self.cid, dest=dest))
