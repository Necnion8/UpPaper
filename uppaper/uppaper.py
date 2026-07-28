from logging import getLogger

import aiohttp

from . import GIT_URL
from .model import *
from .util import *

USER_AGENT = f"UpPaper v1, {GIT_URL}"
API_URL = "https://fill.papermc.io/"
log = getLogger(__name__)


class UpPaper(object):
    def __init__(self, *, user_agent: str | None = None, cache_expire_minutes=5):
        headers = {"User-Agent": user_agent or USER_AGENT, }
        self.session = aiohttp.ClientSession(base_url=API_URL, headers=headers)
        self._cache = TimedCache(cache_expire_minutes * 60)

    async def close(self):
        await self.session.close()

    async def _fetch(self, url):
        try:
            dat = self._cache.lookup(url)
        except KeyError:
            pass
        else:
            log.debug("Cached: %s", url)
            if isinstance(dat, Exception):
                raise dat from Exception("cached raise")
            return dat

        try:
            log.debug("Fetching %s", url)
            async with self.session.get(url) as resp:
                if not resp.ok:
                    try:
                        msg = await resp.text()
                    except Exception as e:
                        log.warning("Exception in read error response: %s", e)
                        msg = None
                    log.warning("Failed to fetch %s (%s): %s", url, resp.status, msg)
                resp.raise_for_status()
                return self._cache.set(url, await resp.json())

        except Exception as e:
            self._cache.set(url, e)
            raise e

    # api

    async def project(self, project: str) -> Project:
        url = f"/v3/projects/{project}"
        return from_dict(Project, await self._fetch(url))

    async def version(self, project: str, version: str) -> Version:
        url = f"/v3/projects/{project}/versions/{version}"
        return from_dict(Version, await self._fetch(url))

    async def builds(self, project: str, version: str) -> list[Build]:
        url = f"/v3/projects/{project}/versions/{version}/builds"
        return [from_dict(Build, j) for j in await self._fetch(url)]
