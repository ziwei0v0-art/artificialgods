# Bottle motion adaptation

Source: `pyd021226/fly-paradise`, pinned commit
`9c6130681c1a112c3c7faaafbad6d335cc0a1c36` (v0.3.6).
The package declares MIT and its author field is `desktop-fly-pet`. Preserve
`NOTICE.md`, `source-manifest.json`, and the unmodified upstream files.

On 2026-10-04 the adult bottle movement was adapted to Swift in
`native/v1/InsectArtwork.swift`, `BottleMotionEngine`. This extends the existing
`FlyParadiseArtwork` drawing adaptation; it does not replace upstream sources.

| Upstream `renderer/overlay.js` | Native counterpart | Retained behavior |
| --- | --- | --- |
| `jarRandPos`, lines 1772–1774 | `Individual.init` | 180×320 logical jar; initial x 24–156, y 28–292. |
| `stepJar`, adult branch lines 1860–1879 | `Individual.advance` | Turn interval 300–1000 ms, course offset ±2.6 rad, 1.2–1.5× brief burst for 200–300 ms, shortest-angle steering `min(1,dt×7)`, small sine perturbation, 30 logical units/s baseline. |
| `bounceJar`, lines 1843–1850 | End of `Individual.advance` | Clamp and reflect at x 18/162, y 22/298; reflected heading jitter ±0.6 rad. |
| `drawBottle` adult `drawFly` call | `BottleInventoryView.draw` | Same live renderer as desktop; actual colour and sex remain paired with the original ID. |

Intentional platform/product adaptations:

- Seconds replace milliseconds; the time factors and durations are converted.
- Each actual insect ID gets its own deterministic random stream and state.
  Snapshot order, removal of neighbours, or redraws cannot reset another fly.
- The presentation clock advances only on rendered updates. Repeated, backward,
  invalid or >250 ms gaps do not move the fly; ordinary dt is capped at 50 ms.
  This prevents off-screen or sleep time from producing catch-up movement.
- Logical coordinates map to the bottle interior, with the artwork's 12 pt
  radius reserved. Heading is mapped through its actual displayed aspect ratio.
- The real-ID sample contains at most 12 flies. Full inventory totals continue
  to come from the backend's colour/sex summary. Older aggregate-only fixtures
  have explicitly synthetic IDs and never claim individual identity.
- The upstream `inMs`, `JAR_DIE_MS`, death, larva/pupa branches and selection
  mutation are excluded. This is display-only motion: no lifecycle, breeding,
  genetics, currency, sale/release or persistent state is changed.

No music, font, image, Electron runtime or unrelated assets are copied by this
adaptation. The existing package process includes this file and `NOTICE.md`.
