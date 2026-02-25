"""
rate_limit.py — Per-tenant fixed-window rate limiting.

Tracks how many job submissions each tenant has made within the current
time window. Tenants that exceed the limit receive HTTP 429 with a
Retry-After signal telling them exactly when their window resets.

Why fixed window (not sliding)?
  Simpler to implement and reason about. The known trade-off is that a
  tenant can burst 2x the limit across a window boundary (end of window N
  + start of window N+1). Acceptable for v1 internal use.

Why not a middleware or decorator?
  Rate limiting is a per-tenant policy decision, not a blanket API concern.
  Keeping it as an explicit call in the submission path makes the order of
  checks visible and easy to reason about.
"""

import math
import os
import time
import logging
from threading import Lock

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Configurable via environment variables.
RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW_S: int = int(os.getenv("RATE_LIMIT_WINDOW_S", "60"))


class RateLimiter:
    """
    Thread-safe fixed-window rate limiter.

    Internal structure:
        { tenant_id -> (request_count, window_start_time) }

    The window resets lazily — no background thread or cleanup loop needed.
    When a request arrives and the current window has expired, the counter
    resets in place. Stale entries for inactive tenants stay in memory but
    are harmless for v1 scale.
    """

    def __init__(self) -> None:
        # Maps tenant_id → (count_in_current_window, window_start_monotonic)
        self._windows: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    def check_and_increment(self, tenant_id: str) -> None:
        """
        Verify the tenant is within their rate limit, then record the request.

        Raises HTTPException(400) if tenant_id is missing or blank.
        Raises HTTPException(429) if the limit is exceeded, with Retry-After.
        Returns None if the request is allowed.
        """
        # Guard: reject blank tenant_id explicitly (whitespace slips past Pydantic min_length).
        # This is a 400, not a 429 — the request is malformed, not rate-limited.
        if not tenant_id or not tenant_id.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_TENANT_ID",
                    "message": "tenant_id must not be missing or blank",
                },
            )

        now = time.monotonic()

        with self._lock:
            count, window_start = self._windows.get(tenant_id, (0, now))
            window_end = window_start + RATE_LIMIT_WINDOW_S

            # If the window has expired, reset the counter for a fresh window.
            if now >= window_end:
                count = 0
                window_start = now
                window_end = now + RATE_LIMIT_WINDOW_S

            if count >= RATE_LIMIT_REQUESTS:
                # Tell the caller exactly how long to wait before retrying.
                retry_after = max(1, math.ceil(window_end - now))

                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "tenant_id": tenant_id,
                        "count": count,
                        "limit": RATE_LIMIT_REQUESTS,
                        "window_s": RATE_LIMIT_WINDOW_S,
                        "retry_after_s": retry_after,
                    },
                )
                raise HTTPException(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    detail={
                        "code": "RATE_LIMITED",
                        "message": (
                            f"Rate limit exceeded for tenant '{tenant_id}': "
                            f"{RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_S}s"
                        ),
                        "retry_after_s": retry_after,
                    },
                )

            # Request is allowed — record it.
            self._windows[tenant_id] = (count + 1, window_start)

            logger.debug(
                "Rate limit check passed",
                extra={
                    "tenant_id": tenant_id,
                    "count": count + 1,
                    "limit": RATE_LIMIT_REQUESTS,
                },
            )
