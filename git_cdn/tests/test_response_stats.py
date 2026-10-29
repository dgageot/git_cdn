# Standard Library
import asyncio

# Third Party Libraries
import pytest
from aiohttp import web

from git_cdn import app as git_cdn_app

# pylint: disable=unused-argument

HEADERS = {"Authorization": "Basic dTpw", "User-Agent": "git/2.0"}


@pytest.mark.asyncio
async def test_resp_time_is_per_request(
    tmpworkdir, aiohttp_server, aiohttp_client, mocker
):
    async def upstream(request):
        if request.path.startswith("/slow"):
            await asyncio.sleep(0.5)
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", upstream)
    server = await aiohttp_server(app)
    client = await aiohttp_client(git_cdn_app.make_app(str(server.make_url("/"))))
    log = mocker.patch("git_cdn.git_cdn.log")

    async def fast():
        await asyncio.sleep(0.1)
        await client.get("/fast.git/info/refs", headers=HEADERS)

    await asyncio.gather(client.get("/slow.git/info/refs", headers=HEADERS), fast())

    resp_times = [
        call.kwargs["resp_time"]
        for call in log.info.call_args_list
        if call.args == ("Response stats",)
    ]
    assert len(resp_times) == 2
    assert min(resp_times) < 0.4
    assert max(resp_times) >= 0.5
