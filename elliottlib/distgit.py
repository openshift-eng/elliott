from __future__ import division, unicode_literals
import requests
from elliottlib import constants
from pyrpkg.lookaside import CGILookasideCache
from pyrpkg.sources import SourcesFile
from urlparse import urljoin, urlparse
from elliottlib.logutil import getLogger

LOGGER = getLogger()


class DistGitRepo(object):
    """ Represents a dist-git repository.
    Currently only lookaside cache related methods are implemented.
    """

    def __init__(self, repo_url):
        """ Initialize DistGitRepo with a repository URL
        """
        url = urlparse(repo_url)
        self.url = url
        self.scheme = url.scheme
        self.host = url.netloc
        self.component = url.path.strip("/")

    def get_lookaside_cache(self):
        """ Get the lookaside cache from configuration for this repository
        :returns: None if not found.
        """
        config = constants.DIST_GIT_CONFIG.get(self.url.netloc)
        if not config:  # This is not a dist-git repo
            return None
        cache_config = config.get("lookaside_cache")
        if not cache_config:
            return None
        return CGILookasideCache(cache_config["hash_type"], cache_config["download_url"], cache_config["upload_url"])

    def download_lookaside_source(self, filename, hash, fileobj, session=None):
        """ Download source from lookaside cache
        :param filename: filename of the source
        :param hash: hexstring of source hash
        :param fileobj: file object to save the downloaded source
        :param session: optional requests.Session object
        :returns: number of bytes written to fileobj
        """
        lookaside = self.get_lookaside_cache()
        download_url = lookaside.get_download_url(self.component, filename, hash)
        LOGGER.info("Downloading dist-git lookaside source {} from {}...".format(filename, download_url))
        if not session:
            session = requests.session()
        response = session.get(download_url, stream=True)
        response.raise_for_status()
        content_length = int(response.headers.get("Content-length", "-1"))
        downloaded = 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:  # filter out keep-alive new chunks
                fileobj.write(chunk)
                downloaded += len(chunk)
                if content_length < 0:  # unknown content length
                    LOGGER.debug("Downloading {}: {}".format(filename, downloaded))
                else:
                    LOGGER.debug("Downloading {} ({:.2%}): {}/{}".format(filename, downloaded / content_length, downloaded, content_length))
        fileobj.flush()
        return downloaded


def parse_lookaside_sources(file_obj):
    """ Parse dist-git `sources` file.
    :file_obj: File object for the sources file.
    """
    sources = SourcesFile(None, "old", True)
    for line in file_obj:
        entry = sources.parse_line(line)
        sources.entries.append(entry)
    return sources
