# BongoCat dial source attribution

Upstream project: BongoCat — https://github.com/vladelaina/BongoCat

License: GNU Affero General Public License, version 3 only (`AGPL-3.0-only`, as stated in the preserved README). The complete upstream license is in `upstream/LICENSE`. All upstream attribution and license text is retained unchanged.

This directory preserves the radial/flower menu from the historical official base commit `f455f7c3b903ee98d2b9c0c5119c5d508c623f95` and the PR #44 head `05b7a92cb4b17a4603e939033a5cae2a6a697bdb`: https://github.com/vladelaina/BongoCat/pull/44 . PR #44 is closed and was not merged. These files are not represented as the repository's current main implementation.

`upstream/src/ui/dial/` contains all eleven dial C/header files from the pinned PR head, byte-for-byte. `base/` preserves the two C files changed by that PR and its README/LICENSE. Other dial files are identical between base and head. `manifest.json` records each preserved file's commit and SHA-256.

Tianmu adaptation: `native/v1/BrandArtwork.swift`, `SceneDialGeometry`, translates the original polar geometry, vertex sampling, hit testing, and timing functions to Swift/AppKit-compatible values. The translation keeps C Float intermediate calculations and downward-positive y coordinates. The original GPL-family provenance remains applicable to the adapted code. The surrounding Tianmu UI supplies its own artwork, menu contents, business actions, native window and event lifecycle. No BongoCat image or model assets are copied by this package.

`extract_oracle.py` builds a test-only C oracle from the preserved original function bodies. It removes only the SDL-dependent include and provides minimal data structures for fields actually read by the extracted functions. Geometry and hit functions are retained verbatim; `dial_child_count`, `dial_child_step`, `dial_child_angle`, `pointer`, `reveal`, and `animate` are extracted without rewriting their bodies. The root angle expression is extracted from `dial_paint.c`. This oracle is compiled without SDL, OpenGL or Nuklear, and is compared against the compiled production Swift enum by `tests/test_scene_dial_geometry.py`. Test harnesses and type adapters are Tianmu additions, not upstream source.

Intentional API adaptations:

- Swift accepts Double/NSPoint at the boundary, converts to Float for original calculations and returns Double/NSPoint. UI input coordinates must already be relative to center and divided by layout scale and opening scale.
- `hit` mirrors the original raw `dial_hit`. `pointerHit` additionally returns the child-focus state and applies the original pointer's inner-circle escape and strict click behavior.
- Optional `compactChildren` overrides BongoCat's index-specific compact-spacing rule, so Tianmu can use semantic groups with a different order. Omission preserves the original rule (root indices 4 and 5, or over 11 children).
- Invalid/nonfinite geometry or nonexistent roots safely yields no path/hit; these guardrails are Tianmu additions outside the original valid-input domain.
- `hoverLift` uses seconds instead of integer timestamp differences. The original time-step cap and response curve are unchanged for valid nonnegative time intervals.
- The upstream implementation has no closing transition; any closing animation in Tianmu's host is a host addition.

No publication or distribution action is performed by this local adaptation.
