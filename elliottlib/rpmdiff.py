from __future__ import absolute_import, print_function, unicode_literals

from builtins import object
import requests
from requests_kerberos import HTTPKerberosAuth


class RPMDiffClient(object):
    def __init__(self, hub_url, session=None):
        self.hub_url = hub_url
        self.session = session if session else requests.Session()  # type: requests.Session

    def get_token(self, auth):
        endpoint = self.hub_url + "/api/v1/token/obtain/"
        resp = self.session.get(endpoint, auth=auth)
        resp.raise_for_status()
        return resp.json()["token"]

    def authenticate(self):
        token = self.get_token(HTTPKerberosAuth())
        self.session.headers["Authorization"] = "Token " + token

    def get_run(self, run_id):
        endpoint = self.hub_url + "/api/v1/runs/{}/".format(int(run_id))
        resp = self.session.get(endpoint)
        resp.raise_for_status()
        return resp.json()

    def get_test_results(self, run_id):
        endpoint = self.hub_url + "/api/v1/runs/{}/results/".format(int(run_id))
        resp = self.session.get(endpoint)
        resp.raise_for_status()
        return resp.json()["results"]

    def list_waivers(self, package_name, test, offset=0, limit=10):
        """ List waivers.

        https://rpmdiff-hub.host.prod.eng.bos.redhat.com/api/v1/waivers/
        """
        endpoint = self.hub_url + "/api/v1/waivers/"
        params = {
            "package": package_name,
            "test": int(test),
            "offset": int(offset),
            "limit": int(limit),
        }
        resp = self.session.get(endpoint, params=params)
        resp.raise_for_status()
        return resp.json()["results"]
