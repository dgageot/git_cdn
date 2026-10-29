# Standard Library
import os
import time

# Third Party Libraries
import pytest

from git_cdn.auth_cache import AuthCache

# pylint: disable=unused-argument,redefined-outer-name

AUTH = "Basic dTpw"
REPO = "group/project.git"


@pytest.fixture
def cache(tmpworkdir, monkeypatch):
    monkeypatch.setenv("AUTH_CACHE_TTL", "60")
    return AuthCache()


def test_disabled_by_default(tmpworkdir, monkeypatch):
    monkeypatch.delenv("AUTH_CACHE_TTL", raising=False)
    cache = AuthCache()
    cache.store_auth_ok(AUTH, REPO)
    assert not cache.auth_ok(AUTH, REPO)
    assert not os.listdir(tmpworkdir)


def test_miss_then_hit(cache):
    assert not cache.auth_ok(AUTH, REPO)
    cache.store_auth_ok(AUTH, REPO)
    assert cache.auth_ok(AUTH, REPO)
    assert not cache.auth_ok(AUTH, "other.git")
    assert not cache.auth_ok("Basic b3RoZXI=", REPO)


def test_expired_entry_is_removed(cache):
    cache.store_auth_ok(AUTH, REPO)
    filename = cache.cache_file(AUTH, REPO)
    old = time.time() - 120
    os.utime(filename, (old, old))
    assert not cache.auth_ok(AUTH, REPO)
    assert not os.path.exists(filename)


def test_stored_in_workdir(cache, tmpworkdir):
    cache.store_auth_ok(AUTH, REPO)
    assert os.listdir(tmpworkdir / "gitCDN" / "auth_cache")
