"""HTTP client: single shared client with UA, timeout, retry, and rate limit.

Plan §18-20. Retries: 429/5xx/timeout/connection errors with exponential
backoff; 404/403 are not retried. Concurrency is intentionally low.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from shikoku_nature_trail.config import (
    BACKOFF_SECONDS,
    DEFAULT_CONCURRENCY,
    DEFAULT_DELAY,
    DEFAULT_TIMEOUT,
    MAX_ATTEMPTS,
    RETRYABLE_STATUS,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class HttpError(Exception):
    def __init__(self, url, status):
        super().__init__("GET %s -> HTTP %s" % (url, status))
        self.url = url
        self.status = status


class RateLimiter:
    """Throttle requests to at least `delay` seconds apart (global lock)."""

    def __init__(self, delay):
        self.delay = delay
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        if self.delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._last + self.delay - now
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def __enter__(self):
        self.wait()
        return self

    def __exit__(self, *exc):
        return False


class HttpClient:
    def __init__(self, timeout=DEFAULT_TIMEOUT, concurrency=DEFAULT_CONCURRENCY,
                 delay=DEFAULT_DELAY):
        self.timeout = timeout
        self.rate = RateLimiter(delay)
        self._sem = threading.BoundedSemaphore(concurrency)

    def _open(self, url):
        # Percent-encode the path/query so non-ASCII (e.g. Japanese) URLs can
        # be sent over the wire; urllib refuses to encode them itself.
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
        req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
        return urllib.request.urlopen(req, timeout=self.timeout)

    def _attempt(self, url):
        """One raw GET. Returns (status, headers, body) for any HTTP response."""
        try:
            with self._sem, self.rate:
                resp = self._open(url)
                try:
                    status = resp.getcode()
                    headers = dict(resp.headers.items())
                    body = resp.read()
                    return status, headers, body
                finally:
                    resp.close()
        except urllib.error.HTTPError as e:
            headers = dict(e.headers.items()) if e.headers else {}
            body = e.read() if hasattr(e, "read") else b""
            return e.code, headers, body
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            logger.debug("network error for %s: %s", url, e)
            return None, {}, b""

    def get_bytes(self, url, retry=True):
        """GET url with retry policy. Returns (status, headers, bytes).

        Never retries 403/404. Retries 429/5xx/network with backoff.
        """
        attempts = MAX_ATTEMPTS if retry else 1
        for i in range(attempts):
            status, headers, body = self._attempt(url)
            if status is None:
                logger.warning("network error %s (attempt %d/%d)", url, i + 1, attempts)
            elif status in (403, 404):
                return status, headers, body
            elif status == 200:
                return status, headers, body
            elif status in RETRYABLE_STATUS and i + 1 < attempts:
                logger.warning(
                    "HTTP %s %s (attempt %d/%d), backing off",
                    status, url, i + 1, attempts,
                )
            else:
                return status, headers, body
            if i + 1 < attempts:
                time.sleep(BACKOFF_SECONDS[min(i, len(BACKOFF_SECONDS) - 1)])
        # exhausted network-retry attempts without a definitive answer
        return None, {}, b""