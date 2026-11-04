"""Rate-limited stdlib HTTP client with finite retries."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

USER_AGENT = "ohenro-map-data/min88-archiver"


class HttpClient:
    def __init__(self, timeout: float = 30, delay: float = 0.3, attempts: int = 3,
                 request=None, sleep=time.sleep, clock=time.monotonic):
        self.timeout = timeout
        self.delay = delay
        self.attempts = attempts
        self._request = request or self._stdlib_request
        self._sleep = sleep
        self._clock = clock
        self._last_request = None

    def _stdlib_request(self, url: str, timeout: float):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.getcode(), dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers.items()) if error.headers else {}, error.read()

    def _wait(self):
        if self._last_request is not None:
            remaining = self.delay - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def get_bytes(self, url: str):
        for attempt in range(self.attempts):
            self._wait()
            try:
                status, headers, body = self._request(url, self.timeout)
            except (OSError, TimeoutError, urllib.error.URLError):
                status, headers, body = None, {}, b""
            retryable = status is None or status == 429 or (status is not None and status >= 500)
            if not retryable or attempt + 1 == self.attempts:
                return status, headers, body
            self._sleep(2 ** attempt)
        return None, {}, b""
