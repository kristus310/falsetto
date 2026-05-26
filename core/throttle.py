import time
import threading
from collections import defaultdict, deque
from functools import wraps

from django.http import HttpResponse
from django.shortcuts import render
from django.conf import settings

_lock = threading.Lock()
_request_log: dict[tuple, deque] = defaultdict(deque)
_prune_counter = 0
_PRUNE_EVERY = 500

def _get_client_ip(request) -> str:
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "unknown")

def _maybe_prune(window_seconds: int):
    global _prune_counter
    _prune_counter += 1

    if _prune_counter < _PRUNE_EVERY:
        return

    _prune_counter = 0
    cutoff = time.time() - window_seconds
    stale_keys = [k for k, v in _request_log.items() if not v or v[-1] < cutoff]
    for k in stale_keys:
        del _request_log[k]

def _is_rate_limited(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - window_seconds

    with _lock:
        bucket = _request_log[key]

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        _maybe_prune(window_seconds)

        if len(bucket) >= max_requests:
            retry_after = int(bucket[0] - cutoff) + 1
            return True, retry_after

        bucket.append(now)
        return False, 0

def _build_429(request, retry_after: int) -> HttpResponse:
    try:
        response = render(request, "429.html", {"retry_after": retry_after}, status=429)
    except Exception:
        response = HttpResponse(
            "Too many requests. Please slow down.",
            status=429,
            content_type="text/plain",
        )
    response["Retry-After"] = str(retry_after)
    response["X-RateLimit-Limit"] = str(retry_after)
    response["X-RateLimit-Remaining"] = "0"
    return response

def rate_limit(max_requests: int = 20, window_seconds: int = 60, key_prefix: str = ""):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if getattr(settings, "TESTING", False):
                return view_func(request, *args, **kwargs)

            ip = _get_client_ip(request)
            prefix = key_prefix or view_func.__name__
            bucket_key = f"{prefix}:{ip}"

            limited, retry_after = _is_rate_limited(bucket_key, max_requests, window_seconds)
            if limited:
                return _build_429(request, retry_after)

            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator

class RateLimitMixin:
    rate_limit_max: int = 20
    rate_limit_window: int = 60
    rate_limit_methods: list = ["POST"]

    def dispatch(self, request, *args, **kwargs):
        if getattr(settings, "TESTING", False):
            return super().dispatch(request, *args, **kwargs)

        if request.method.upper() in [m.upper() for m in self.rate_limit_methods]:
            ip = _get_client_ip(request)
            bucket_key = f"{self.__class__.__name__}:{ip}"

            limited, retry_after = _is_rate_limited(
                bucket_key, self.rate_limit_max, self.rate_limit_window
            )
            if limited:
                return _build_429(request, retry_after)

        return super().dispatch(request, *args, **kwargs)