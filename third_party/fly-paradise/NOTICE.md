# Upstream attribution and license declaration

Project: 果蝇乐园 / desktop-fly-pet
Repository: https://github.com/pyd021226/fly-paradise
Pinned commit: 9c6130681c1a112c3c7faaafbad6d335cc0a1c36 (v0.3.6)
Package author field: desktop-fly-pet
Package license field: MIT

The files under upstream/ are byte-identical copies from that commit. Their
source URLs, SHA-256 values and Git blob identities are recorded in
source-manifest.json. No upstream source file has been edited.

The pinned upstream tree contains no separate LICENSE, COPYING or NOTICE file.
The copied renderer and README contain no separate copyright attribution.
This notice preserves the published package license declaration and project
attribution; it does not invent a copyright year, legal owner, or an upstream
license document that was not present.

The standard MIT permission and warranty terms below are reproduced from the
SPDX MIT license reference (https://spdx.org/licenses/MIT.html). This local
notice is not represented as a verbatim upstream LICENSE file. Preserve this
notice, upstream/package.json and the source provenance with any substantial
reuse of the renderer. No unrelated music, image, font or binary assets have
been copied or licensed by this notice.

The native drawing adaptation is `FlyParadiseArtwork` in
`native/v1/InsectArtwork.swift`. The 2026-10-04 adult bottle movement adaptation
is `BottleMotionEngine` in the same file; its function mapping and intentional
changes are documented in `BOTTLE-MOTION-ADAPTATION.md`.

The 2026-10-04 desktop adult movement extraction is `desktop-motion.js`, run by
JavaScriptCore from `native/v1/DesktopInsects.swift`. Its 62 original function
bodies, host-only adapter boundaries, and differential verification are
documented in `DESKTOP-MOTION-ADAPTATION.md`.

## MIT permission and warranty terms

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
