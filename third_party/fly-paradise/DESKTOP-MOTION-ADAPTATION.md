# Desktop adult movement extraction

Source: `pyd021226/fly-paradise`, pinned commit
`9c6130681c1a112c3c7faaafbad6d335cc0a1c36` (`v0.3.6`).
The package declares MIT; its author field is `desktop-fly-pet`. Preserve
`NOTICE.md`, `source-manifest.json`, and the unchanged upstream files. No
copyright owner, year, or separate upstream license document is inferred.

`desktop-motion.js` copies the 62-function transitive call closure of
`spawnFly` and `stepFly` byte-for-byte from the original `renderer/overlay.js`.
The source SHA-256 is
`dcfe5153feff4b5bfd47ad5fdde63cf5da337cbf286bb41ba0cb0562c7f2ac95`.
The copied function section has explicit begin/end markers; original constants
are copied separately. The source file itself remains unchanged.

`DesktopInsects.swift` loads this module in one isolated JavaScriptCore context
from `Bundle.main/Resources/backend/third_party/fly-paradise/desktop-motion.js`.
Unbundled tests inject an explicit file URL. There is no working-directory
fallback or alternate handwritten movement engine. Load/JavaScript errors are
available through `motionUnavailableReason` and suppress unverified positions.

The module retains the original adult behavior chain: mouse speed-dependent
sense radius, immediate fright, direct escape then wandering, proximity boost
stages, three-second safe interval, cruise/landing choice, target selection,
quiet landing eligibility, 1.8-second post-landing grace, 0.3–6-second still
intervals, short eased perch hops, timed departures, 400-ms takeoff, cruise and
burst movement, full-heading smoothing, and screen wrapping. As of 2026-10-07
(171), that exact timing is exercised by the explicit `quietPresentation:false`
reference fixture. Production defaults to quiet desktop presentation, described
below. Motion still uses the same real IDs used to draw and capture insects.

Intentional host adaptations are confined to the adapter after the copied
function section and the Swift input/output bridge:

- Actual backend IDs, sex, and four established color values remain
  authoritative. Normalized backend coordinates initialize only new IDs.
  Reordered/repeated snapshots and changes to other individuals do not reset
  an existing insect. Removed IDs discard only their own presentation state.
- Each ID receives its own seeded 64-bit random stream. The same original
  JavaScript random calls therefore produce independent random sequences.
  Quiet admission intentionally also depends on per-screen display occupancy.
- AppKit global points map to source coordinates as `(x, -y)`; velocity and
  displayed heading map back with the same Y-axis reversal. In quiet production
  mode the host passes `dt * 0.18` to the unchanged original step, maps velocity
  to that same 0.18 scale, and caps a frightened flight at 180 points/second.
  The source constants and 62 copied function bodies remain unchanged. The
  reference fixture still runs the original timing and velocities exactly.
- Quiet presentation retains every backend ID, sex, phenotype, and initial
  coordinate in its state map, but admits at most three visible individuals per
  real monitor. Admission starts after 0.6/1.7/2.8 seconds, fades over 1.2 seconds,
  and waiting individuals rotate into slots after approximately 22 seconds.
  An eighteen-second schedule staggers six-second flight opportunities with
  uninterrupted stays; hidden IDs stay still. A stay holds exact coordinates
  and heading while the original folded-wing grooming pose is drawn. These
  host-owned temporary landing rectangles are display geometry, not Finder
  data or new backend entities. Original per-individual scale (0.95–1.2) and
  wing seed now reach the native renderer instead of being discarded.
- New admissions/retirements pause during active capture, weaving or pressed
  buttons. Capture uses only actual IDs above 0.05 opacity at their current
  global coordinates; hidden waiting individuals are never proxy capture
  targets. A natural release still locks its original real-ID set. No inventory,
  genetic or lifecycle row is removed by the visual limit.
  A free nearby pointer still invokes the original threat and escape chain,
  including from a scheduled stay, within the one-flying-individual hard limit.
- The host supplies exposed-desktop pointer position at its existing polling
  rate. Consecutive valid samples determine pointer speed. Disabled samples
  clear the pointer velocity anchor. Net/capture/weaving gestures and pressed
  buttons use the original `netOn` suppression for new threat reactions.
  This bridge installs no event monitor, global key, input hook, or permission.
- `updateBehaviorLandingSurfaces` accepts small host-owned rectangles. Without
  explicit surfaces, each actual screen contributes eight 32-point edge/corner
  sites (limited by screen size). These are synthetic landing geometry, not
  discovered Finder icons. An explicit empty list means no landing sites.
  No Finder titles, screenshots, accessibility data, or private icon layout is
  read. Windows are not misrepresented as their central 32-point icon glyph.
- The host backend owns lifecycle, breeding, food production, and persistence.
  The adapter marks adults retired from upstream breeding and clears original
  death clocks. It caps upstream hunger at the original newborn band's 0.4
  maximum, because no upstream food-care loop runs; otherwise an empty food
  array would eventually force endless foraging and eliminate normal rests.
  The copied lifecycle functions stay intact but are unreachable under these
  explicit inputs. No eggs, larva, pupa, corpse, genetics, or currency state is
  produced by this presentation engine. This is not the whole upstream game
  loop, which is neither imported nor started.
- A presentation clock advances only on valid rendered intervals. Repeated,
  backward, invalid, or over-250-ms gaps do not advance it; ordinary intervals
  are capped at 50 ms as in the source frame loop. Missing screens preserve
  existing individual state and freeze time until screens return.
- Original wrapping uses the screens' outer bounds. On disconnected displays,
  a final host topology guard moves positions from a non-screen gap to the
  nearest real display and invalidates obsolete landing state. Removed screens
  similarly rehome retained individuals. This guard does not change the
  single-screen trajectories tested against the original source. Quiet flights
  wrap within the actual monitor owning their display slot, so they cannot enter
  another monitor's three visible slots or occupy a disconnected-screen gap.

Verification in `tests/test_desktop_upstream_motion.py` separately extracts and
executes the pinned original functions, rather than importing the production
adapter. It compares actual Swift layer positions, velocity, heading, activity,
and animation clock at 20, 30, and 60 Hz, including a five-minute continuous
run, pointer approach, pressed-button suppression, landing, hops, and screen
wrap. The original-timing fixture compares 33,000 frames with maximum difference zero.
The original function body and source-hash checks protect provenance.

`tests/test_insect_motion.py` covers independent IDs, changing snapshots, clock
gaps, module failure, true pointer-triggered escape, multi-screen gaps/removal,
style continuity, and actual off-screen-rendered folded-wing rest/grooming and
full-heading eye orientation. All native windows remain unshown. These tests
do not launch the product, touch a save, or constitute human desktop acceptance.

`tests/test_insect_quiet_presentation.py` separately verifies the production
default: 60-second activity/visibility limits, same real-ID capture, backend
removal, unchanged snapshots, clock gaps, monitor changes, gradual new arrivals,
and small-window/temporary-net lifecycle. Same-seed before/after metrics and
the separate native cost measurement are recorded in `evidence/1.0/171-insects.md`;
they are not claimed to match upstream timing.
