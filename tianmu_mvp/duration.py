"""Catime's Apache-2.0 parser and timer core, with no Windows UI dependency."""

import ctypes
from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess
import os
import tempfile

from .traditional_time import (DEFAULT_INCENSE_SECONDS, DEFAULT_TEA_SECONDS,
                               duration_label, parse_traditional_duration,
                               traditional_elapsed, validate_unit_seconds)


def _native_inputs(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    vendor = root / "third_party" / "catime"
    sources = [vendor / "upstream" / "src" / "utils" / name for name in
               ("time_parser.c", "time_parser_advanced.c", "time_format.c")]
    sources.append(vendor / "portable" / "timer_core.c")
    headers = [vendor / "include" / "utils" / "time_parser.h",
               vendor / "portable" / "timer_core.h"]
    return root, vendor, sources, headers


def native_library_path(root=None):
    """Content-addressed path; safe to inspect without creating/writing files."""
    root, _, sources, headers = _native_inputs(root)
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sources + headers)).hexdigest()[:16]
    return root / "build" / ("catime-core-" + digest + ".dylib")


def ensure_native_library(root=None):
    """Development/build helper. A packaged existing library requires no clang."""
    root, vendor, sources, _ = _native_inputs(root)
    destination = native_library_path(root)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Atomic publication also permits independent headless tests to compile
        # concurrently without another process loading a half-written library.
        descriptor, name = tempfile.mkstemp(prefix='catime-', suffix='.dylib', dir=destination.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            subprocess.run(["clang", "-dynamiclib", "-O2", "-std=c11", "-I", str(vendor / "include"),
                            *map(str, sources), "-o", str(temporary)],
                           check=True, capture_output=True, timeout=30)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


@lru_cache(maxsize=1)
def _library():
    return ctypes.CDLL(str(ensure_native_library()))


@lru_cache(maxsize=1)
def _parser():
    library = _library()
    parser = library.TimeParser_ParseAdvanced
    parser.argtypes = (ctypes.c_char_p, ctypes.POINTER(ctypes.c_int))
    parser.restype = ctypes.c_int
    return parser


def parse_duration(text, *, tea_seconds=DEFAULT_TEA_SECONDS,
                   incense_seconds=DEFAULT_INCENSE_SECONDS):
    validate_unit_seconds(tea_seconds, incense_seconds)
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("请输入有效时长，例如 25 分钟对应 25，或 1h30m。")
    try:
        encoded = text.strip().encode("ascii")
    except UnicodeEncodeError:
        return parse_traditional_duration(text, tea_seconds=tea_seconds,
                                          incense_seconds=incense_seconds)
    seconds = ctypes.c_int()
    if not _parser()(encoded, ctypes.byref(seconds)):
        raise ValueError("请输入大于零的有效时长，例如 25 或 1h30m。")
    return seconds.value
