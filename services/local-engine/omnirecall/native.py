"""Process-wide settings for the native libraries the engine loads."""

from __future__ import annotations

import ctypes
import platform
import sys

# glibc mallopt parameter: the most malloc arenas the process may create.
_M_ARENA_MAX = -8
MALLOC_ARENAS = 4


def limit_malloc_arenas(arenas: int = MALLOC_ARENAS) -> bool:
    """Cap glibc's malloc arenas. True if the cap was applied.

    LanceDB's search threads each get an arena by default (up to 8 per CPU), and
    the freed memory stays in them: at 40,000 chunks a hundred vector searches
    held about 700 MB, 250 MB with four arenas (measurements.md). Only Linux with
    glibc has these arenas; elsewhere this does nothing. Arenas that already
    exist are kept, so call it before the native libraries start their threads.
    """
    if not sys.platform.startswith("linux") or platform.libc_ver()[0] != "glibc":
        return False
    try:
        return bool(ctypes.CDLL(None).mallopt(_M_ARENA_MAX, arenas))
    except (OSError, AttributeError):
        return False
