# Standard Library
import os

# Third Party Libraries
import pytest

from git_cdn import repo_cache
from git_cdn.repo_cache import KnownMissing
from git_cdn.repo_cache import RepoCache

# pylint: disable=unused-argument,redefined-outer-name

SHA1 = b"a" * 40
OTHER = b"b" * 40


@pytest.fixture
def rcache(tmpworkdir, mocker):
    mocker.patch.object(repo_cache, "known_missing", KnownMissing(60))
    rcache = RepoCache("project.git", "u:p", "http://upstream/")
    os.makedirs(rcache.directory)
    mocker.patch.object(rcache, "update")
    mocker.patch.object(rcache, "cat_file", return_value=SHA1 + b" missing\n")
    return rcache


@pytest.mark.asyncio
async def test_missing_want_fetches_once(rcache):
    await rcache.ensure_input_wants({SHA1})
    await rcache.ensure_input_wants({SHA1})
    assert rcache.update.call_count == 1


@pytest.mark.asyncio
async def test_other_missing_want_fetches_again(rcache):
    await rcache.ensure_input_wants({SHA1})
    rcache.cat_file.return_value = OTHER + b" missing\n"
    await rcache.ensure_input_wants({SHA1, OTHER})
    assert rcache.update.call_count == 2


@pytest.mark.asyncio
async def test_want_found_by_fetch_is_not_remembered(rcache):
    rcache.cat_file.side_effect = [SHA1 + b" missing\n", SHA1 + b" commit 123\n"]
    await rcache.ensure_input_wants({SHA1})
    rcache.cat_file.side_effect = None
    await rcache.ensure_input_wants({SHA1})
    assert rcache.update.call_count == 2


@pytest.mark.asyncio
async def test_present_want_does_not_fetch(rcache):
    rcache.cat_file.return_value = SHA1 + b" commit 123\n"
    await rcache.ensure_input_wants({SHA1})
    rcache.update.assert_not_called()


@pytest.mark.asyncio
async def test_ttl_zero_disables(rcache):
    repo_cache.known_missing.ttl = 0
    await rcache.ensure_input_wants({SHA1})
    await rcache.ensure_input_wants({SHA1})
    assert rcache.update.call_count == 2
