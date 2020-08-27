from elliottlib import constants
import requests
from itertools import islice


class ResultsDBAPI:
    def __init__(self):
        self.url = constants.RESULTSDB_API_URL
        self.session = requests.Session()

    def get_latest_results(self, test_cases, items):
        """ Get latest test results from ResultsDB
        It takes filter parameters, and returns the most recent result for all the relevant Testcases. Only Testcases with at least one Result that meet the filter are present
        https://resultsdb20.docs.apiary.io/#reference/0/results/get-a-list-of-latest-results-for-a-specified-filter
        """
        params = {}
        if test_cases:
            params["testcases"] = ",".join(test_cases)

        results = []
        if items:
            params["item"] = ",".join(map(str, items))
        r = self.session.get(f"{self.url}/results/latest", params=params)
        # an example CVP test result for ose-insights-operator-container-v4.5.0-202007240519.p0:
        # https://resultsdb-api.engineering.redhat.com/api/v2.0/results/latest?testcases=rhproduct.default.sanity&item=ose-insights-operator-container-v4.5.0-202007240519.p0
        r.raise_for_status()
        results = r.json()
        return results

    async def async_get_latest_results(self, test_cases, items, session):
        params = {}
        if test_cases:
            params["testcases"] = ",".join(test_cases)
        if items:
            params["item"] = ",".join(map(str, items))
        url = self.url + "/results/latest"
        async with session.get(url, params=params) as response:
            results = await response.json()
            return results
