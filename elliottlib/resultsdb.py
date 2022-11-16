import asyncio
import itertools
from typing import Iterable, Optional
from urllib.parse import urlparse

from aiohttp import ClientSession

from elliottlib import constants


class ResultsDBAPI:
    def __init__(self, url: Optional[str] = None, session: Optional[ClientSession] = None):
        self._url = url or constants.RESULTSDB_API_URL
        parsed_url = urlparse(self._url)
        self._session = session or ClientSession(f"{parsed_url.scheme}://{parsed_url.netloc}")

    async def close(self):
        await self._session.close()

    async def get_latest_results(self, test_cases: Iterable[str], items: Iterable[str], batch_size: int = 50):
        """ Get latest test results from ResultsDB
        It takes filter parameters, and returns the most recent result for all the relevant Testcases. Only Testcases with at least one Result that meet the filter are present
        https://resultsdb20.docs.apiary.io/#reference/0/results/get-a-list-of-latest-results-for-a-specified-filter

        # an example CVP test result for ose-insights-operator-container-v4.5.0-202007240519.p0:
        # https://resultsdb-api.engineering.redhat.com/api/v2.0/results/latest?testcases=cvp.rhproduct.default.sanity&item=ose-insights-operator-container-v4.5.0-202007240519.p0
        """
        params = {
            "ci_name": "Container Verification Pipeline",
            "_distinct_on": "item",
        }
        if test_cases:
            params["testcases"] = ",".join(test_cases)
        it = iter(items)
        url = "/api/v2.0/results/latest"
        results = []
        while True:
            chunk = list(itertools.islice(it, batch_size))
            if not chunk:
                return results
            params["item"] = ",".join(map(str, chunk))
            async with self._session.get(url, params=params) as response:
                response.raise_for_status()
                batch_results = await response.json()
                results.extend(batch_results.get("data", []))
