import contextlib
import hashlib
import os
import pathlib
import time

from structlog import getLogger

from git_cdn.util import get_subdir

log = getLogger()


class AuthCache:
    """Remember for AUTH_CACHE_TTL seconds that upstream accepted creds for a repo.
    Disabled when the TTL is 0. Entries are files shared by all workers."""

    def __init__(self):
        self.ttl = int(os.getenv("AUTH_CACHE_TTL", "0"))

    def auth_ok(self, auth_header, path):
        if self.ttl <= 0 or not auth_header:
            return False
        filename = self.cache_file(auth_header, path)
        try:
            age = time.time() - os.stat(filename).st_mtime
        except FileNotFoundError:
            return False
        if age > self.ttl:
            log.info("Auth cache expired", filename=filename)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(filename)
            return False
        log.info("Auth cache ok", filename=filename)
        return True

    def store_auth_ok(self, auth_header, path):
        if self.ttl <= 0 or not auth_header:
            return
        filename = self.cache_file(auth_header, path)
        pathlib.Path(filename).touch()
        log.info("Auth cache created", filename=filename)

    @staticmethod
    def cache_file(auth_header, path):
        key = hashlib.sha256(f"{auth_header} {path}".encode()).hexdigest()
        return os.path.join(get_subdir("auth_cache"), key)
