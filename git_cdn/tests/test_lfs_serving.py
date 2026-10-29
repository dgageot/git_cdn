# Standard Library
import gzip
import os
from types import SimpleNamespace

# Third Party Libraries
import pytest
import pytest_asyncio

from git_cdn.lfs_cache_manager import LFSCacheFile

# pylint: disable=unused-argument,redefined-outer-name

OID = "a" * 64
PATH = f"/group/project.git/gitlab-lfs/objects/{OID}"
HEADERS = {"Authorization": "Basic dTpw", "User-Agent": "git-lfs/3.0"}


@pytest_asyncio.fixture
async def client(make_client, cdn_event_loop, app):
    client = await make_client(app)
    cache_file = LFSCacheFile(f"http://x{PATH}", {})
    os.makedirs(os.path.dirname(cache_file.filename))
    with open(cache_file.filename, "wb") as f:
        f.write(b"CACHED")
    return client


@pytest.mark.asyncio
async def test_cached_object_requires_upstream_auth(client, mocker):
    auth = mocker.patch.object(
        client.app.gitcdn,
        "auth_request",
        return_value=SimpleNamespace(status=403, reason="Forbidden"),
    )
    resp = await client.get(PATH, headers=HEADERS)
    assert resp.status == 403
    assert await resp.read() != b"CACHED"
    auth.assert_called_once_with(mocker.ANY, "group/project.git")


@pytest.mark.asyncio
async def test_cached_object_served_once_authenticated(client, mocker):
    mocker.patch.object(client.app.gitcdn, "auth_request", return_value=None)
    resp = await client.get(PATH, headers=HEADERS)
    assert resp.status == 200
    assert await resp.read() == b"CACHED"


@pytest.mark.asyncio
async def test_cached_gzip_object_served(client, mocker):
    mocker.patch.object(client.app.gitcdn, "auth_request", return_value=None)
    cache_file = LFSCacheFile(f"http://x{PATH}", {})
    with open(cache_file.gzip, "wb") as f:
        f.write(gzip.compress(b"CACHED-GZIP"))
    resp = await client.get(PATH, headers={**HEADERS, "Accept-Encoding": "gzip"})
    assert resp.status == 200
    assert resp.headers["Content-Encoding"] == "gzip"
    assert await resp.read() == b"CACHED-GZIP"
