import asyncio
from typing import Optional
from urllib.parse import quote, urlparse

import aiohttp
import kerberos

from elliottlib import Runtime, constants


class ErrataAsyncClient:
    @staticmethod
    def from_runtime(runtime: Runtime):
        errata_url = constants.errata_url
        if runtime.initialized:
            et_data = runtime.gitdata.load_data(key='erratatool', replace_vars=runtime.group_config.vars.primitive() if runtime.group_config.vars else {})
            errata_url = et_data.get("server") or constants.errata_url
        return ErrataAsyncClient(errata_url)

    def __init__(self, errata_url) -> None:
        self._errata_url = errata_url
        self._headers = {}
        self._krb_context = None
        self._session = aiohttp.ClientSession()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    def gssapi_login(self):
        # authenticate to the Errata Tool server using Kerberos/GSSAPI
        # See http://python-notes.curiousefficiency.org/en/latest/python_kerberos.html
        __, krb_context = kerberos.authGSSClientInit("HTTP@" + urlparse(self._errata_url).hostname)
        self._krb_context = krb_context
        kerberos.authGSSClientStep(krb_context, "")
        client_token = kerberos.authGSSClientResponse(krb_context)
        self._headers["Authorization"] = "Negotiate " + client_token

    async def close(self):
        if self._krb_context:
            kerberos.authGSSClientClean(self._krb_context)
            self._krb_context = None
        await self._session.close()

    async def _get_json(self, path):
        r = await self._session.get(self._errata_url + path, headers=self._headers)
        r.raise_for_status()
        return await r.json()

    async def get_advisory_builds(self, advisory_id: int, flatten_result=True):
        """5.2.2.6. GET /api/v1/erratum/{id}/builds
        Fetch the Brew builds associated with an advisory."""
        result = await self._get_json(f"/api/v1/erratum/{int(advisory_id)}/builds")
        if not flatten_result:
            return result
        builds = [b for product_version in result.values() for build in product_version.get("builds", []) for b in build.values()]
        return builds

    async def get_advisory(self, advisory_id: int):
        """5.2.1.3. GET /api/v1/erratum/{id}
        Retrieve the advisory data. """
        return await self._get_json(f"/api/v1/erratum/{int(advisory_id)}")

    async def get_released_builds(self, product_version: str, package_name: Optional[str] = None):
        """⁠5.2.3.12. GET /api/v1/product_versions/{product_version_id}/released_builds
        Get the list of released builds for a product version

        5.2.3.16. GET /api/v1/product_versions/{product_version_id}/released_builds/{package_name}
        Get the released build for a product version and a given package
        """
        path = f"/api/v1/product_versions/{quote(product_version)}/released_builds"
        if package_name:
            path += f"/{quote(package_name)}"
        return await self._get_json(path)

    async def get_released_modules(self, product_version: str, package_name: Optional[str] = None):
        path = f"/api/v1/product_versions/{quote(product_version)}/released_modules"
        if package_name:
            path += f"/{quote(package_name)}"
        return await self._get_json(path)
