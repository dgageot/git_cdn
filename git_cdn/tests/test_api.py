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
ZERO = "0" * 40


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(src, message, content):
    (src / "file.txt").write(content)
    git("add", "file.txt", cwd=src)
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "-m",
        message,
        cwd=src,
    )
    return git("rev-parse", "HEAD", cwd=src)


@pytest.fixture
def local_repo(tmpworkdir):
    """A cached bare repo with two commits on refs/remotes/origin/heads/main"""
    src = tmpworkdir / "src"
    src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    base = commit(src, "base", "hello\n")
    head = commit(src, "head", "hello world\n")
    bare = os.path.join(git_cdn.util.get_subdir("git"), REPO)
    git("clone", "-q", "--bare", str(src), bare, cwd=src)
    git(
        "--git-dir", bare, "update-ref", "refs/remotes/origin/heads/main", head, cwd=src
    )
    return {"base": base, "head": head}


@pytest_asyncio.fixture
async def api_client(make_client, cdn_event_loop, app, mocker):
    client = await make_client(app)
    mocker.patch.object(app.gitcdn, "auth_request", return_value=None)
    return client


async def api(client, command, **params):
    return await client.get(f"/__api__/{command}", params=params, headers=AUTH)


@pytest.mark.asyncio
async def test_last_active_branches(api_client, local_repo):
    resp = await api(api_client, "last_active_branches", repo=REPO)
    assert resp.status == 200
    assert b"refs/remotes/origin/heads/main" in await resp.read()


@pytest.mark.asyncio
async def test_merge_base(api_client, local_repo):
    resp = await api(
        api_client,
        "merge_base",
        repo=REPO,
        base="main",
        current_sha1=local_repo["base"],
    )
    assert resp.status == 200
    assert (await resp.text()).strip() == local_repo["base"]


@pytest.mark.asyncio
async def test_diff(api_client, local_repo):
    resp = await api(
        api_client,
        "diff",
        repo=REPO,
        base_sha1=local_repo["base"],
        current_sha1=local_repo["head"],
    )
    assert resp.status == 200
    assert "+hello world" in await resp.text()


@pytest.mark.asyncio
async def test_diff_no_renames(api_client, local_repo):
    resp = await api(
        api_client,
        "diff_no_renames",
        repo=REPO,
        base_sha1=local_repo["base"],
        current_sha1=local_repo["head"],
    )
    assert resp.status == 200
    assert "+hello world" in await resp.text()


@pytest.mark.asyncio
async def test_git_error_is_reported(api_client, local_repo):
    resp = await api(api_client, "last_active_branches", repo="group/missing.git")
    assert resp.status == 500
    assert "not a git repository" in await resp.text()


@pytest.mark.asyncio
async def test_unknown_command(api_client):
    resp = await api(api_client, "rev-parse", repo=REPO)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_requires_auth(api_client):
    resp = await api_client.get("/__api__/last_active_branches", params={"repo": REPO})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_last_active_branches_no_shell(api_client, tmpworkdir):
    marker = tmpworkdir / "pwned"
    resp = await api(api_client, "last_active_branches", repo=f"x'$(touch {marker})")
    assert not marker.exists()
    assert resp.status == 400


@pytest.mark.parametrize(
    "repo",
    [
        "",
        "project",
        "/etc/project.git",
        "group/../other.git",
        "group/./project.git",
        "project.git/info/refs?service=git-upload-pack&x=/../../other.git",
        "project.git#frag",
        "group/pro ject.git",
    ],
)
@pytest.mark.asyncio
async def test_bad_repo(api_client, repo):
    resp = await api(api_client, "last_active_branches", repo=repo)
    assert resp.status == 400


@pytest.mark.parametrize(
    "params",
    [
        {"base_sha1": ZERO},
        {"base_sha1": ZERO, "current_sha1": "HEAD"},
        {"base_sha1": "--output=/tmp/owned", "current_sha1": ZERO},
        {"base_sha1": ZERO, "current_sha1": "A" * 40},
    ],
)
@pytest.mark.asyncio
async def test_bad_sha1(api_client, params):
    resp = await api(api_client, "diff", repo=REPO, **params)
    assert resp.status == 400


@pytest.mark.asyncio
async def test_params_validated_before_auth(make_client, cdn_event_loop, app, mocker):
    client = await make_client(app)
    auth = mocker.patch.object(app.gitcdn, "auth_request", return_value=None)
    resp = await api(client, "diff", repo=REPO, base_sha1="x", current_sha1=ZERO)
    assert resp.status == 400
    auth.assert_not_called()
