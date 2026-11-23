"""HTTP client shared by all extractors: auth, timeouts, retries and request counts.

Retry policy:
* 429  -> wait for the server's Retry-After (seconds or HTTP date), then retry.
* 5xx, timeouts, dropped connections -> exponential backoff with jitter
  (0.5 s, 1 s, 2 s ... capped at 30 s).
* 404  -> not an error here; returned as ``None`` so the caller can decide
  (e.g. an issue that has no completion details yet).
* any other 4xx (401 bad credentials, 400 bad request) -> raise at once,
  because retrying cannot fix it.
"""

from __future__ import annotations

import base64
import logging
import os
import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.url = url


@dataclass
class RequestStats:
    """Counts kept per table, reported in the run manifest."""

    requests: int = 0
    retries: int = 0
    rate_limited: int = 0
    not_found: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **counts: int) -> None:
        with self._lock:
            for name, n in counts.items():
                setattr(self, name, getattr(self, name) + n)

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "rate_limited": self.rate_limited,
            "not_found": self.not_found,
        }


def retry_after_seconds(header: str | None, default: float) -> float:
    if not header:
        return default
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(header)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return default


class ApiClient:
    """Thread-safe JSON GET client for one source system."""

    def __init__(
        self,
        base_url: str,
        headers: Mapping[str, str],
        *,
        timeout: float = 30.0,
        max_attempts: int = 6,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
        pool_size: int = 32,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._sleep = sleep
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10.0),
            limits=httpx.Limits(max_connections=pool_size, max_keepalive_connections=pool_size),
        )
        self._headers = {"Accept": "application/json", **headers}

    def url(self, path_or_url: str) -> str:
        """Absolute URL. Paging links from the API are already absolute and used as is."""
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return f"{self.base_url}{path_or_url}"

    def get(
        self,
        path_or_url: str,
        params: Mapping[str, Any] | None = None,
        stats: RequestStats | None = None,
    ) -> Any | None:
        """GET and parse JSON. Returns None on 404."""
        url = self.url(path_or_url)
        stats = stats or RequestStats()
        for attempt in range(1, self.max_attempts + 1):
            stats.add(requests=1)
            try:
                resp = self._http.get(url, params=params, headers=self._headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self.max_attempts:
                    raise
                wait = self._backoff(attempt)
                log.warning("%s on %s, retry %d in %.1fs", type(exc).__name__, url, attempt, wait)
                stats.add(retries=1)
                self._sleep(wait)
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                stats.add(not_found=1)
                return None
            if resp.status_code in RETRY_STATUSES and attempt < self.max_attempts:
                if resp.status_code == 429:
                    stats.add(rate_limited=1)
                    wait = retry_after_seconds(
                        resp.headers.get("Retry-After"), self._backoff(attempt)
                    )
                else:
                    wait = self._backoff(attempt)
                log.debug("HTTP %d on %s, retry %d in %.1fs", resp.status_code, url, attempt, wait)
                stats.add(retries=1)
                self._sleep(wait)
                continue
            raise ApiError(resp.status_code, str(resp.request.url), resp.text)
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int) -> float:
        wait = min(self.backoff_cap, self.backoff_base * 2 ** (attempt - 1))
        return wait * random.uniform(0.8, 1.2)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()


def auth_headers(system: Mapping[str, Any], env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the Authorization header for a system from environment variables."""
    env = env if env is not None else os.environ

    def need(name: str) -> str:
        value = env.get(name)
        if not value:
            raise RuntimeError(f"{name} is not set (see .env.example)")
        return value

    if system["auth"] == "mri_basic":
        user = "/".join(
            need(n)
            for n in ("MRI_CLIENT_ID", "MRI_DATABASE", "MRI_WEB_SERVICES_USER", "MRI_PARTNER_KEY")
        )
        token = base64.b64encode(f"{user}:{need('MRI_PASSWORD')}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    if system["auth"] == "bearer":
        return {"Authorization": f"Bearer {need(system['token_env'])}"}
    raise ValueError(f"unknown auth type {system['auth']!r}")
