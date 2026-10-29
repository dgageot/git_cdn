# Standard Library
import os
import subprocess

# Third Party Libraries
import pytest
import pytest_asyncio

import git_cdn.util

# pylint: disable=unused-argument,redefined-outer-name

AUTH = {"Authorization": "Basic dTpw"}
REPO = "group/project.git"


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def local_repo(tmpworkdir):
    src = tmpworkdir / "src"
    src.mkdir()
    git("init", "-q", cwd=src)
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "-m",
        "init",
        "--allow-empty",
        cwd=src,
    )
    bare = os.path.join(git_cdn.util.get_subdir("git"), REPO)
    git("clone", "-q", "--bare", str(src), bare, cwd=src)
    git(
        "--git-dir",
        bare,
        "update-ref",
        "refs/remotes/origin/heads/main",
        "HEAD",
        cwd=src,
    )
    return bare


@pytest_asyncio.fixture
async def api_client(make_client, cdn_event_loop, app, mocker):
    client = await make_client(app)
    mocker.patch.object(app.gitcdn, "auth_request", return_value=None)
    return client


@pytest.mark.asyncio
async def test_last_active_branches(api_client, local_repo):
    resp = await api_client.get(
        "/__api__/last_active_branches", params={"repo": REPO}, headers=AUTH
    )
    assert resp.status == 200
    assert b"refs/remotes/origin/heads/main" in await resp.read()


@pytest.mark.asyncio
async def test_last_active_branches_no_shell(api_client, tmpworkdir):
    marker = tmpworkdir / "pwned"
    repo = f"x'$(touch {marker})"
    resp = await api_client.get(
        "/__api__/last_active_branches", params={"repo": repo}, headers=AUTH
    )
    assert not marker.exists()
    assert resp.status == 500
