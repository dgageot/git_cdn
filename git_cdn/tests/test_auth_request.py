# Standard Library
import asyncio

# Third Party Libraries
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from git_cdn.app import make_app

# pylint: disable=unused-argument

AUTH = "Basic dTpw"


@pytest.mark.asyncio
async def test_auth_request_does_not_read_body(tmpworkdir, aiohttp_server):
    """A huge or never-ending ref advertisement must not delay the auth check"""

    async def endless_refs(request):
        resp = web.StreamResponse()
        await resp.prepare(request)
        while True:
            await resp.write(b"x" * 1024)
            await asyncio.sleep(0.01)

    upstream = web.Application()
    upstream.router.add_get("/group/project.git/info/refs", endless_refs)
    server = await aiohttp_server(upstream)

    app = make_app(str(server.make_url("/")))
    gitcdn = app.gitcdn
    request = make_mocked_request("GET", "/", headers={"Authorization": AUTH})
    try:
        result = await asyncio.wait_for(
            gitcdn.auth_request(request, "group/project.git"), timeout=2
        )
        assert result is None
    finally:
        await gitcdn.get_session().close()


@pytest.mark.asyncio
async def test_auth_request_forwards_failure(tmpworkdir, aiohttp_server):
    async def forbidden(request):
        raise web.HTTPForbidden()

    upstream = web.Application()
    upstream.router.add_get("/group/project.git/info/refs", forbidden)
    server = await aiohttp_server(upstream)

    app = make_app(str(server.make_url("/")))
    gitcdn = app.gitcdn
    request = make_mocked_request("GET", "/", headers={"Authorization": AUTH})
    try:
        result = await gitcdn.auth_request(request, "group/project.git")
        assert result.status == 403
    finally:
        await gitcdn.get_session().close()
