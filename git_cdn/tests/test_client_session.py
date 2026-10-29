# Standard Library
import asyncio

# Third Party Libraries
import pytest
from aiohttp import ClientSession
from aiohttp import TCPConnector
from aiohttp import web

from git_cdn.client_session import ClientSessionWithRetry

# pylint: disable=redefined-outer-name


@pytest.fixture
def flaky_upstream(aiohttp_server):
    """First call fails with 500, then succeeds. Records received bodies."""
    bodies = []

    async def handler(request):
        bodies.append(await request.read())
        return web.Response(status=500 if len(bodies) == 1 else 200)

    async def start():
        app = web.Application()
        app.router.add_route("*", "/", handler)
        return await aiohttp_server(app), bodies

    return start


async def request(session, server, **kwargs):
    retry = ClientSessionWithRetry(
        lambda: session, range(500, 600), "post", server.make_url("/"), **kwargs
    )
    retry.REQUEST_MAX_RETRIES = 3
    async with retry as response:
        return response.status


@pytest.mark.asyncio
async def test_bytes_body_is_retried(flaky_upstream, mocker):
    mocker.patch("asyncio.sleep")
    server, bodies = await flaky_upstream()
    async with ClientSession() as session:
        assert await request(session, server, data=b"PUSH") == 200
    assert bodies == [b"PUSH", b"PUSH"]


@pytest.mark.asyncio
async def test_streamed_body_is_not_retried(flaky_upstream, mocker):
    mocker.patch("asyncio.sleep")
    server, bodies = await flaky_upstream()

    async def stream():
        yield b"PUSH"

    async with ClientSession() as session:
        assert await request(session, server, data=stream()) == 500
    assert bodies == [b"PUSH"]


@pytest.mark.asyncio
async def test_connection_released_while_waiting(aiohttp_server, mocker):
    calls = 0
    hang = asyncio.Event()

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls > 1:
            return web.Response(status=200)
        # a 500 whose body never completes: the connection stays busy
        response = web.StreamResponse(status=500)
        await response.prepare(request)
        await response.write(b"error")
        await hang.wait()
        return response

    app = web.Application()
    app.router.add_route("*", "/", handler)
    server = await aiohttp_server(app)

    sleeping = asyncio.Event()
    real_sleep = asyncio.sleep

    async def sleep(_):
        sleeping.set()
        await real_sleep(0.01)

    mocker.patch("git_cdn.client_session.asyncio.sleep", sleep)
    async with ClientSession(connector=TCPConnector(limit=1)) as session:
        task = asyncio.create_task(request(session, server, data=b"PUSH"))
        await sleeping.wait()
        assert not session.connector._acquired
        assert await asyncio.wait_for(task, 2) == 200
    hang.set()
