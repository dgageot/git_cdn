import asyncio
import os

import pytest

from git_cdn.repo_cache import RepoCache

# pylint: disable=no-member,unused-argument


def run_git_fake(*args, **kwargs):
    return asyncio.create_subprocess_exec(
        "sleep",
        "0.5",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


@pytest.mark.asyncio
async def test_run(mocker):
    mocker.patch("git_cdn.repo_cache.exec_git", run_git_fake)
    spycom = mocker.spy(asyncio.subprocess.Process, "communicate")
    rcache = RepoCache("/tmp", "fake", "fake")
    task = asyncio.create_task(rcache.run_git("fake"))
    await task
    assert task.done()
    assert not task.cancelled()
    assert spycom.call_count == 1


@pytest.mark.asyncio
async def test_cancel_run(mocker):
    mocker.patch("git_cdn.repo_cache.exec_git", run_git_fake)
    spycom = mocker.spy(asyncio.subprocess.Process, "communicate")
    rcache = RepoCache("/tmp", "fake", "fake")
    task = asyncio.create_task(rcache.run_git("fake"))
    await asyncio.sleep(0.2)
    task.cancel()
    assert not task.done()
    assert not task.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done()
    assert task.cancelled()
    assert spycom.call_count == 2


@pytest.fixture
def repo_dir(tmpworkdir):
    rcache = RepoCache("project.git", "u:p", "http://upstream/")
    os.makedirs(rcache.directory)
    os.utime(rcache.directory, (0, 0))
    return rcache


@pytest.mark.asyncio
async def test_fetch_success_updates_mtime(repo_dir, mocker):
    mocker.patch.object(repo_dir, "run_git", return_value=(b"", b"", 0))
    await repo_dir.fetch()
    assert repo_dir.mtime() > 0
    repo_dir.run_git.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_failure_keeps_mtime(repo_dir, mocker):
    mocker.patch.object(repo_dir, "run_git", return_value=(b"", b"error", 128))
    mocker.patch("git_cdn.repo_cache.asyncio.sleep")
    await repo_dir.fetch()
    assert repo_dir.mtime() == 0
    assert repo_dir.run_git.call_count == 5


@pytest.mark.asyncio
async def test_run_git_spawn_failure(mocker):
    mocker.patch("git_cdn.repo_cache.exec_git", side_effect=FileNotFoundError("git"))
    rcache = RepoCache("/tmp", "fake", "fake")
    with pytest.raises(FileNotFoundError):
        await rcache.run_git("fake")
