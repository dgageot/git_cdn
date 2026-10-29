# Standard Library
import os
import stat
import time

# Third Party Libraries
import pytest

from git_cdn.repo_cache import RepoCache
from git_cdn.tests.test_upload_pack import FakeStreamWriter
from git_cdn.upload_pack import UploadPackHandler
from git_cdn.upload_pack_input_parser import UploadPackInputParser

# pylint: disable=unused-argument,protected-access,redefined-outer-name

FAKE_UPLOAD_PACK = """#!/bin/sh
# flood stderr beyond the pipe buffer, then answer like git
head -c 2000000 /dev/zero | tr '\\0' 'w' >&2
cat >/dev/null
printf '0008NAK\\n0000'
"""


FAILING_UPLOAD_PACK = """#!/bin/sh
echo "fatal: boom" >&2
exit 128
"""


@pytest.fixture
def fake_git(tmpworkdir, monkeypatch):
    def install(content):
        bindir = tmpworkdir / "bin"
        bindir.mkdir()
        script = bindir / "git-upload-pack"
        script.write(content)
        os.chmod(str(script), stat.S_IRWXU)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")

    return install


def handler():
    writer = FakeStreamWriter()
    proc = UploadPackHandler("project.git", writer, "u:p", "http://upstream/", 1)
    proc.rcache = RepoCache("project.git", "u:p", "http://upstream/")
    return proc, writer


INPUT = UploadPackInputParser(
    b"0032want 4284b1521b200ba4934ee710a4a538549f1f0f97\n00000009done\n"
)


@pytest.mark.asyncio
async def test_stderr_flood_does_not_block(fake_git, cdn_event_loop):
    fake_git(FAKE_UPLOAD_PACK)
    proc, writer = handler()
    start = time.time()
    await proc._do_upload_pack(INPUT)
    assert time.time() - start < 1
    assert writer.output == b"0008NAK\n0000"


@pytest.mark.asyncio
async def test_stderr_is_forwarded_on_failure(fake_git, cdn_event_loop):
    fake_git(FAILING_UPLOAD_PACK)
    proc, writer = handler()
    await proc._do_upload_pack(INPUT)
    assert writer.output == b"0014ERR fatal: boom\n"
