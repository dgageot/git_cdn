import asyncio
import os
import time

import aiohttp
from structlog import getLogger

from git_cdn.util import backoff

log = getLogger()


class ClientSessionWithRetry:
    """Retry an upstream request on connection errors and on retry_on statuses.
    Statuses are only retried when the body can be sent again: a streamed body
    is consumed by the first attempt."""

    REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", "10"))
    # exponential backoff, but capped: 10 retries must not mean a minute of waiting
    MAX_BACKOFF = 2.0

    def __init__(self, get_session, retry_on, method, url, *args, **kwargs):
        self.status_retry_on = retry_on
        self.get_session = get_session
        self.session = None
        self.cm_request = None
        self.method = method
        self.url = url
        self.args = args
        self.kwargs = kwargs
        self.replayable = isinstance(kwargs.get("data"), (bytes, str, type(None)))

    async def __aenter__(self):
        start_time = time.time()
        self.session = self.get_session()
        self.cm_request = None
        for retries, timeout in enumerate(backoff(0.1, self.REQUEST_MAX_RETRIES), 1):
            last_try = retries >= self.REQUEST_MAX_RETRIES
            try:
                self.cm_request = await self.session.request(
                    self.method, self.url, *self.args, **self.kwargs
                )
                if (
                    self.cm_request.status not in self.status_retry_on
                    or not self.replayable
                    or last_try
                ):
                    return self.cm_request
                log.debug(
                    "upstream wrong return, retry",
                    request_url=self.url,
                    request_method=self.method,
                    resp_status=self.cm_request.status,
                    retries=retries,
                    resp_time=time.time() - start_time,
                )
                # don't hold a pooled connection while waiting
                self.cm_request.release()
            except aiohttp.ClientConnectionError:
                if last_try:
                    log.exception(
                        "Max of request retries reached",
                        resp_time=time.time() - start_time,
                        timeout=timeout,
                        request_max_retries=self.REQUEST_MAX_RETRIES,
                        request_url=self.url,
                        request_method=self.method,
                    )
                    raise
                log.exception(
                    "Client connection error",
                    resp_time=time.time() - start_time,
                    timeout=timeout,
                    request_max_retries=self.REQUEST_MAX_RETRIES,
                    retries=retries,
                    request_url=self.url,
                    request_method=self.method,
                )
            await asyncio.sleep(min(timeout, self.MAX_BACKOFF))
        return self.cm_request

    async def __aexit__(self, *args, **kwargs):
        if self.cm_request is not None:
            self.cm_request.close()
