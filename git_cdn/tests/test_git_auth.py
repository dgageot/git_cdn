# Standard Library
import base64
import subprocess

# Third Party Libraries
import pytest
from aiohttp import web

from git_cdn.repo_cache import RepoCache
from git_cdn.util import get_creds_from_auth

# pylint: disable=unused-argument

CREDS = "m@example.com:s3cret+pass"


def basic(creds):
    return "Basic " + base64.b64encode(creds.encode()).decode()


def test_get_creds_from_auth():
    assert get_creds_from_auth(basic("me:pass")) == "me:pass"
    assert get_creds_from_auth(basic(CREDS)) == CREDS


@pytest.mark.asyncio
async def test_git_gets_creds_from_header_not_url(tmpworkdir, aiohttp_server, mocker):
    seen = []

    async def upstream(request):
        seen.append((str(request.url), request.headers.get("Authorization")))
        raise web.HTTPForbidden()

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", upstream)
    server = await aiohttp_server(app)
    mocker.patch("git_cdn.repo_cache.asyncio.sleep")
    repo_log = mocker.patch("git_cdn.repo_cache.log")
    util_log = mocker.patch("git_cdn.util.log")

    rcache = RepoCache("group/project.git", CREDS, str(server.make_url("/")))
    subprocess.run(["git", "init", "-q", "--bare", rcache.directory], check=True)
    await rcache.fetch()

    assert seen
    for url, auth in seen:
        assert url == str(
            server.make_url("/group/project.git/info/refs?service=git-upload-pack")
        )
        assert auth == basic(CREDS)
    assert "s3cret" not in str(repo_log.mock_calls) + str(util_log.mock_calls)
