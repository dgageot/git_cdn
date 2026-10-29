# Third Party Libraries
import pytest
from multidict import CIMultiDict

from git_cdn.git_cdn import get_protocol_version
from git_cdn.git_cdn import hide_auth_on_headers

SECRET = "Basic c2VjcmV0OnBhc3N3b3Jk"


@pytest.mark.parametrize("name", ["Authorization", "authorization", "AUTHORIZATION"])
def test_hide_auth_on_headers(name):
    headers = CIMultiDict({name: SECRET})
    hide_auth_on_headers(headers)
    assert SECRET not in headers.values()
    assert "XXX" in headers["Authorization"]


def test_hide_auth_without_auth():
    headers = CIMultiDict({"Host": "x"})
    hide_auth_on_headers(headers)
    assert dict(headers) == {"Host": "x"}


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({}, 1),
        ({"Git-Protocol": "version=2"}, 2),
        ({"git-protocol": "version=2"}, 2),
        ({"Git-Protocol": "garbage"}, 1),
    ],
)
def test_get_protocol_version(headers, expected):
    assert get_protocol_version(CIMultiDict(headers)) == expected
