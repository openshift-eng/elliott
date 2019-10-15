import unittest
import io
from elliottlib import distgit
import mock


class TestDistGit(unittest.TestCase):
    def parse_lookaside_sources(self):
        sources_file = io.BytesIO(b"2ba370dd5e06259ec4fa3b22c50ad2f9  openshift-clients-git-1.c8c7aaa.tar.gz")
        sources = distgit.parse_lookaside_sources(sources_file)
        self.assertEqual(sources.entries[0].hash, "2ba370dd5e06259ec4fa3b22c50ad2f9")
        self.assertEqual(sources.entries[0].file, "openshift-clients-git-1.c8c7aaa.tar.gz")


class TestDistGitRepo(unittest.TestCase):
    def setUp(self):
        pass

    def test_get_lookaside_cache(self):
        lookaside = distgit.DistGitRepo("git://unknown.example.com/rpms/openshift-clients").get_lookaside_cache()
        self.assertEqual(lookaside, None)
        lookaside = distgit.DistGitRepo("git://pkgs.devel.redhat.com/rpms/openshift-clients").get_lookaside_cache()
        self.assertNotEqual(lookaside, None)

    def test_download_lookaside_source(self):
        repo = distgit.DistGitRepo("git://pkgs.devel.redhat.com/rpms/openshift-clients")
        source_hash = "2ba370dd5e06259ec4fa3b22c50ad2f9"
        source_content = b"abcdefg"
        mock_response = mock.MagicMock()
        mock_response.iter_content.return_value = [source_content]
        mock_session = mock.MagicMock()
        mock_session.get.return_value = mock_response
        downloaded_file = io.BytesIO()
        downloaded_bytes = repo.download_lookaside_source("example.txt", source_hash, downloaded_file, session=mock_session)
        downloaded_file.seek(0)
        self.assertEqual(downloaded_file.read(), source_content)
        self.assertEqual(downloaded_bytes, len(source_content))
