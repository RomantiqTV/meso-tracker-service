"""Dotted-version comparison ("1.2.10" > "1.2.9", unlike plain string comparison). Mirrored in the client's
meso_overlay/license/versioning.py - kept deliberately tiny and dependency-free so both copies stay easy to keep in sync."""
import re

_PART = re.compile(r"\d+")


def _parts(v):
    return tuple(int(x) for x in _PART.findall(v or ""))


def compare_versions(a, b):
    """-> -1 if a<b, 0 if a==b, 1 if a>b. Missing trailing parts count as 0 ("1.2" == "1.2.0")."""
    pa, pb = _parts(a), _parts(b)
    n = max(len(pa), len(pb))
    pa += (0,) * (n - len(pa))
    pb += (0,) * (n - len(pb))
    return (pa > pb) - (pa < pb)


def is_older(a, b):
    """Is version a strictly older than b? False (never blocks) if either is empty/unset."""
    if not a or not b:
        return False
    return compare_versions(a, b) < 0
