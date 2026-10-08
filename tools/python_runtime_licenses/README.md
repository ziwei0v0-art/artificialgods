# Bundled CPython runtime license notices

These unmodified notices are extracted from the official python-build-standalone
20260814 release, CPython 3.12.14, aarch64-apple-darwin, pgo+lto full archive.
The downloaded archive SHA-256 matched the digest published by the GitHub
release API. `provenance.json` records its exact URL, digest, preserved notice
hashes, and extension/dependency associations. `PYTHON.json` is the original
115,979-byte build metadata, retained unchanged.

The local uv installation has the matching 20260814 BUILD marker. Its
`bin/python3.12` is byte-identical to the official install_only_stripped archive.
The local libpython dylib differs in Mach-O load-command bytes and code-signature
bytes: its LC_ID_DYLIB is a local absolute path instead of upstream @rpath. All
bytes from the end of the longer load-command area to the code signature match
the official dylib (17,898,544 bytes). Exact hashes and offsets are recorded in
`provenance.json`; the local dylib is not described as byte-identical overall.

## Contents and scope

The copied files include the CPython license and every license text referenced
by this build metadata that exists in the official archive. This covers static
bzip2, libffi, mpdecimal, expat, OpenSSL, liblzma, SQLite and libuuid dependencies.
System-library notices (libedit, ncurses, Tcl/Tk and zlib) are retained as well;
including a notice does not mean that library is copied into the application.
The original metadata lists both OpenSSL 1.1 and 3 license paths, so both are
preserved without interpreting those paths as two bundled OpenSSL versions.

The metadata also mentions `licenses/LICENSE.zlib-ng.txt`, but that file is
absent from this exact full archive. The zlib link is marked `system: true`;
`LICENSE.zlib.txt` is present and preserved. No missing license text is invented,
and the discrepancy remains explicit in `provenance.json`.

This collection does not include the separate notices shipped with pip and its
vendored packages. A minimal runtime that omits pip/site-packages does not copy
those packages; any packaging that includes them must retain their own notices.
The PSF-only `lib/python3.12/LICENSE.txt` is not sufficient by itself for this
standalone runtime's static dependencies.

## Official references

- Release: https://github.com/astral-sh/python-build-standalone/releases/tag/20260814
- Licensing: https://github.com/astral-sh/python-build-standalone/blob/38d35dcf0e212ca02eed8ebc11d0c92906387d56/docs/running.rst#licensing
- Distribution metadata: https://github.com/astral-sh/python-build-standalone/blob/38d35dcf0e212ca02eed8ebc11d0c92906387d56/docs/distributions.rst

This directory is a notice/provenance companion for the locally packaged
runtime. It is not a claim of application distribution, signing, notarization,
or publication, and it does not replace the application's BongoCat/Catime/fly
source and license records.
