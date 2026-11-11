"""A minimal in-process sliding-window limiter. It resets if the server restarts and doesn't share state across multiple instances -
fine for a single small Render web service; the first upgrade if this ever needs to scale out is a shared store (Redis) instead."""
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_hits = defaultdict(deque)


def allow(key, max_per_window, window_s):
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= max_per_window:
            return False
        q.append(now)
        return True
