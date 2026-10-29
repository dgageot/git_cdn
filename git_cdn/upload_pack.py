# Standard Library
import asyncio
import os
import tempfile
from concurrent.futures import CancelledError
from functools import partial
from time import time

# Third Party Libraries
from aiohttp.abc import AbstractStreamWriter
from structlog import getLogger
from structlog.contextvars import bind_contextvars
from structlog.contextvars import get_contextvars

from git_cdn.log import bind_context_from_exp
from git_cdn.pack_cache import PackCache
from git_cdn.pack_cache import PackCacheCleaner
from git_cdn.packet_line import to_packet
from git_cdn.repo_cache import RepoCache
from git_cdn.util import GIT_PROCESS_WAIT_TIMEOUT
from git_cdn.util import ensure_proc_terminated
from git_cdn.util import get_subdir
from git_cdn.util import read_chunk

log = getLogger()

cache_cleaner = PackCacheCleaner()
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 32 * 1024))


async def write_input(proc, input_data):
    try:
        proc.stdin.write(input_data)
        await proc.stdin.drain()
    except RuntimeError:
        log.exception("exception while writing to upload-pack stdin")
        raise
    except BrokenPipeError:
        # This occur with large input, and upload pack return an early error
        # like "not our ref"
        log.warning("Ignoring BrokenPipeError, while writing to stdin", pid=proc.pid)
    finally:
        proc.stdin.close()


async def spool_output(spool, stdout):
    while chunk := await stdout.read(CHUNK_SIZE):
        spool.write(chunk)


def input_to_ctx(dict_input):
    if "wants" in dict_input:
        del dict_input["wants"]
    if "haves" in dict_input:
        del dict_input["haves"]
    if "caps" in dict_input:
        del dict_input["caps"]
    bind_contextvars(input_details=dict_input)


class UploadPackHandler:
    """Unit testable upload-pack handler
    which automatically call git fetch to update the local copy"""

    def __init__(
        self,
        path,
        writer: AbstractStreamWriter,
        auth,
        upstream,
        protocol_version,
        sema=None,
    ):
        self.upstream = upstream
        self.auth = auth
        self.path = path
        self.sema = sema
        self.writer = writer
        self.rcache = None
        self.pcache = None
        self.protocol_version = protocol_version

    async def _do_upload_pack(self, data, sink):
        """Run git-upload-pack, feeding its stdout to sink(stdout).
        Returns git's stderr if it failed, None otherwise."""
        proc = await asyncio.create_subprocess_exec(
            "git-upload-pack",
            "--stateless-rpc",
            self.rcache.directory,
            env=dict(os.environ, GIT_PROTOCOL=f"version={self.protocol_version}"),
            stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # drain stderr while git runs: a full pipe would block it forever
        stderr = asyncio.create_task(proc.stderr.read())
        try:
            await asyncio.gather(write_input(proc, data.input), sink(proc.stdout))
        except (asyncio.CancelledError, CancelledError, ConnectionResetError) as e:
            bind_context_from_exp(e)
            log.warning("Client disconnected during upload-pack")
            raise
        except Exception:
            log.exception("upload pack failure")
            raise
        finally:
            # Wait 10 min, for the shielded upload pack to terminate
            # or 2s if not caching, as the process is useless now
            timeout = 10 * 60 if self.pcache else GIT_PROCESS_WAIT_TIMEOUT
            await ensure_proc_terminated(proc, "git upload-pack", timeout)
            log.debug("Upload pack done", pid=proc.pid)
        if proc.returncode == 0:
            return None
        error_message = await stderr
        bind_contextvars(
            upload_pack_status="error",
            upload_pack_returncode=proc.returncode,
            reason=error_message,
        )
        return error_message

    def _to_cache(self, stdout):
        return asyncio.shield(self.pcache.cache_pack(stdout.readexactly, self.writer))

    async def _limited(self, coro):
        """Run coro in one of the MAX_GIT_UPLOAD_PACK slots"""
        if not self.sema:
            return await coro
        start_wait = time()
        async with self.sema:
            start = time()
            bind_contextvars(sema_wait=start - start_wait)
            try:
                return await coro
            finally:
                bind_contextvars(upload_pack_duration=time() - start)

    async def _write_pack_error(self, error: str):
        log.error("Upload pack, sending error to client", pack_error=error)
        pkt = to_packet(("ERR " + error).encode())
        await self.writer.write(pkt)

    async def _flush_to_writer(self, read_func):
        while True:
            chunk = await read_func(CHUNK_SIZE)
            if not chunk:
                break
            await self.writer.write(chunk)

    async def _run_with_cache(self, parsed_input):
        self.pcache = PackCache(parsed_input.hash)
        async with self.pcache.read_lock():
            if self.pcache.exists():
                await self.pcache.send_pack(self.writer)
                return

        async with self.pcache.write_lock():
            # In case 2 threads race for write lock, check again if it has been added in the cache
            if not self.pcache.exists():
                await self._execute(parsed_input)

        async with self.pcache.read_lock():
            if self.pcache.exists():
                await self.pcache.send_pack(self.writer)
                # ensure cache size doesn't grow in a background task
                cache_cleaner.clean()
                return
        # if we are here because of upload_pack failure,
        # the client see the error via the git protocol (mainly "not our ref" error)
        # and "Response stats" report the error via context upload_pack_status="error"
        if get_contextvars()["upload_pack_status"] != "error":
            # Should not happen
            # This case may be due to pack cache deletion before serving it:
            # look logs with with the corresponding hash
            raise RuntimeError("Run with cache failed")

    async def _upload_pack(self, parsed_input):
        # git's output is spooled (to the pack cache, or to a temporary file) so
        # that the slot and the repo lock are held while the pack is computed,
        # not while a possibly slow client downloads it
        with tempfile.TemporaryFile(dir=get_subdir("tmp")) as spool:
            async with self.rcache.read_lock():
                if not self.rcache.exists():
                    return
                sink = self._to_cache if self.pcache else partial(spool_output, spool)
                error = await self._limited(self._do_upload_pack(parsed_input, sink))
            spool.seek(0)
            await self._flush_to_writer(partial(read_chunk, spool))
            if error is not None:
                await self._write_pack_error(error.decode())

    async def _ensure_input_wants_in_rcache(self, wants):
        """Checks if all 'wants' are in rcache
        and updates rcache if that is not the case
        """
        await self.rcache.ensure_input_wants(wants)

    async def _execute(self, parsed_input):
        """Runs git upload-pack
        after being insure that all 'wants' are in cache
        """
        self.rcache = RepoCache(self.path, self.auth, self.upstream)

        await self._ensure_input_wants_in_rcache(parsed_input.wants)
        await self._upload_pack(parsed_input)

    async def run(self, parsed_input):
        """Run the whole process of upload pack, including sending the result to the writer"""
        dict_input = parsed_input.as_dict.copy()
        log.debug("parsed input", input_details=dict_input)
        input_to_ctx(dict_input)
        if parsed_input.parse_error:
            await self._write_pack_error(
                f"Wrong upload pack input: {parsed_input.input[:128]}"
            )
            return
        if not parsed_input.wants:
            log.warning("Request without wants")
            return
        if parsed_input.can_be_cached():
            await self._run_with_cache(parsed_input)
        else:
            await self._execute(parsed_input)
