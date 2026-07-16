"""Security helpers for the AccessAudit dashboard (pre-deployment checklist).

AccessAudit is a single-operator tool: one security/IT owner reviews findings
for their own org. There is one tenant, so authorization is a shared operator
token rather than per-row ownership. Provides:
  * Bearer-token auth for state-changing endpoints (checklist #1).
  * A per-client sliding-window rate limiter (checklist #5).
  * An upload-size guard (checklist #3).
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

def max_upload_bytes() -> int:
    """Cap for in-memory upload reads (memory-DoS guard). Read at call time so
    it can be tuned via ACCESSAUDIT_MAX_UPLOAD without a restart. Default 5 MB."""
    try:
        return int(os.environ.get("ACCESSAUDIT_MAX_UPLOAD", str(5 * 1024 * 1024)))
    except ValueError:
        return 5 * 1024 * 1024


def token_configured() -> bool:
    return bool(os.environ.get("ACCESSAUDIT_TOKEN"))


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Enforce the operator token when ACCESSAUDIT_TOKEN is set.
    Send:  Authorization: Bearer <token>. Unset -> trusted local mode.
    """
    expected = os.environ.get("ACCESSAUDIT_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    supplied = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid token")


# ---- rate limiting ---------------------------------------------------------
_WINDOW = 60.0
_STRICT_PATHS = ("/api/upload", "/api/use-sample-data", "/api/clear")
_hits_default: dict[str, deque] = defaultdict(deque)
_hits_strict: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _limit(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _allow(store: dict[str, deque], key: str, limit: int) -> bool:
    now = time.monotonic()
    with _lock:
        q = store[key]
        while q and q[0] <= now - _WINDOW:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_check(request: Request) -> bool:
    key = client_key(request)
    strict = any(request.url.path.startswith(p) for p in _STRICT_PATHS)
    if strict:
        return _allow(_hits_strict, key, _limit("ACCESSAUDIT_RATE_STRICT", 15))
    return _allow(_hits_default, key, _limit("ACCESSAUDIT_RATE", 120))


def reset_rate_limits() -> None:
    with _lock:
        _hits_default.clear()
        _hits_strict.clear()
