# Third Party Libraries
import pytest

from git_cdn import app as git_cdn_app
from git_cdn.conftest import GITSERVER_UPSTREAM

# pylint: disable=unused-argument

HEADERS = {"Authorization": "Basic dTpw", "User-Agent": "git/2.0"}


@pytest.mark.asyncio
async def test_upload_pack_input_too_large(tmpworkdir, monkeypatch, aiohttp_client):
    monkeypatch.setattr(git_cdn_app, "MAX_UPLOAD_PACK_INPUT", 1024)
    client = await aiohttp_client(git_cdn_app.make_app(GITSERVER_UPSTREAM))
    resp = await client.post(
        "/a.git/git-upload-pack", data=b"x" * 2048, headers=HEADERS
    )
    assert resp.status == 413
