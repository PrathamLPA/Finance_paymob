"""Slow down password guessing on the staff login.

After a few wrong passwords for one account (or many wrong tries from one address) the
login answers 429 for a while, even if the next password is right. Kept in memory: it
resets on restart and is per server, which is enough to make guessing impractical.
"""

from __future__ import annotations

import threading
import time

MAX_FAILS_PER_ACCOUNT = 5
MAX_FAILS_PER_ADDRESS = 20
WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_fails: dict[str, list[float]] = {}


def _recent(key: str, now: float) -> list[float]:
    stamps = [t for t in _fails.get(key, []) if now - t < WINDOW_SECONDS]
    if stamps:
        _fails[key] = stamps
    else:
        _fails.pop(key, None)
    return stamps


def seconds_locked(account: str, address: str) -> int:
    """0 when the attempt may go ahead, otherwise seconds until it may."""
    now = time.time()
    with _lock:
        waits = []
        for key, limit in ((f"acct:{account}", MAX_FAILS_PER_ACCOUNT), (f"ip:{address}", MAX_FAILS_PER_ADDRESS)):
            stamps = _recent(key, now)
            if len(stamps) >= limit:
                waits.append(int(WINDOW_SECONDS - (now - stamps[0])) + 1)
        return max(waits, default=0)


def record_failure(account: str, address: str) -> None:
    now = time.time()
    with _lock:
        for key in (f"acct:{account}", f"ip:{address}"):
            _recent(key, now)
            _fails.setdefault(key, []).append(now)


def record_success(account: str) -> None:
    with _lock:
        _fails.pop(f"acct:{account}", None)


def reset() -> None:
    with _lock:
        _fails.clear()
