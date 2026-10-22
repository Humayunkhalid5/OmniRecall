"""Process-wide native library settings."""

from __future__ import annotations

import platform
import sys

from omnirecall.native import limit_malloc_arenas


def test_malloc_arenas_are_capped_only_on_glibc():
    on_glibc = sys.platform.startswith("linux") and platform.libc_ver()[0] == "glibc"
    assert limit_malloc_arenas() is on_glibc
