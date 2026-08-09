"""Shared login/recovery/roster-lookup throttle helpers (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md
batch 5). Backed by whatever CACHES["default"] points at — config/settings.py uses Django's
DatabaseCache (PostgreSQL), so counts are shared across every Gunicorn worker and survive a
worker restart, unlike the previous per-process LocMemCache default.

Every call site combines two keys: an IP+identifier key (catches repeated guesses against
one account from one source) and an identifier-only key with a higher limit (catches a
slow, distributed attack against one account spread across many IPs). Keeping the
IP+identifier key separate — rather than only using the identifier-only key — is what
keeps two different accounts behind the same NAT/shared IP from locking each other out;
each account has its own IP+identifier counter.

Only ever stores integer counts under these keys — never a password, security-question
answer, or any other secret.
"""

from django.core.cache import cache

THROTTLE_TIMEOUT_SECONDS = 900  # 15 minutes, matches every throttle message in the UI


def is_throttled(key, limit):
    return cache.get(key, 0) >= limit


def any_throttled(keys_with_limits):
    return any(is_throttled(key, limit) for key, limit in keys_with_limits)


def register_failure(key, timeout=THROTTLE_TIMEOUT_SECONDS):
    cache.set(key, cache.get(key, 0) + 1, timeout)


def register_failures(keys, timeout=THROTTLE_TIMEOUT_SECONDS):
    for key in keys:
        register_failure(key, timeout=timeout)


def clear_throttles(keys):
    for key in keys:
        cache.delete(key)
