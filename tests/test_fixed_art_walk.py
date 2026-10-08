"""Fixed-source gait behavior through the real view; temporary art, no window/worker/save."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_attendant_art import png

ROOT = Path(__file__).resolve().parents[1]
RIG = {'sourceSize': [24, 48], 'bodyCutY': 38, 'legStartY': 34,
       'legSplitX': 12, 'maxRootStep': 3, 'footLift': 2}

PRELUDE = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let artwork = AttendantArtwork.load(from: URL(fileURLWithPath: CommandLine.arguments[1]))!
let view = TianmuView(frame: NSRect(origin: .zero, size: TianmuView.sceneCanvas.size))
view.attendantArtwork = artwork
view.persistLegacyFrame = false
func snapshot(_ serial: Int, _ elapsed: Double = 0, _ duration: Double = 5,
              _ action: String = "walk") -> [String: Any] {
    ["action": action, "action_serial": serial, "action_elapsed": elapsed,
     "action_duration": duration, "progress": duration > 0 ? elapsed / duration : 0,
     "fruit_stage": "fresh"]
}
func render(_ target: TianmuView = view) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(target.bounds.width),
        pixelsHigh: Int(target.bounds.height), bitsPerSample: 8, samplesPerPixel: 4,
        hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    target.draw(target.bounds); NSGraphicsContext.restoreGraphicsState(); return rep
}
struct Pixel: Hashable { let x: Int; let y: Int }
func pixels(_ image: NSBitmapImageRep, _ kind: String) -> Set<Pixel> {
    var found: Set<Pixel> = []
    for y in 0..<image.pixelsHigh { for x in 0..<image.pixelsWide {
        let c = image.colorAt(x: x, y: y)!.usingColorSpace(.deviceRGB)!
        guard c.alphaComponent > 0.99 else { continue }
        let r = c.redComponent, g = c.greenComponent, b = c.blueComponent
        let matches = kind == "head" ? (r > 0.95 && b > 0.95 && g < 0.05)
            : kind == "cyan" ? (g > 0.95 && b > 0.95 && r < 0.05)
            : (g > 0.95 && r < 0.05 && b < 0.05)
        if matches { found.insert(Pixel(x: x, y: y)) }
    }}
    return found
}
func box(_ pixels: Set<Pixel>) -> NSRect {
    precondition(!pixels.isEmpty, "Missing colored fixture pixels")
    let xs = pixels.map(\.x), ys = pixels.map(\.y)
    return NSRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()! + 1, height: ys.max()! - ys.min()! + 1)
}
func bbox(_ image: NSBitmapImageRep, _ kind: String) -> NSRect { box(pixels(image, kind)) }
func localFoot(_ image: NSBitmapImageRep, _ kind: String) -> NSRect {
    let head = bbox(image, "head")
    return bbox(image, kind).offsetBy(dx: -head.minX, dy: -head.minY)
}
func changed(_ a: NSRect, _ b: NSRect, _ tolerance: CGFloat = 1.1) -> Bool {
    abs(a.minX-b.minX) > tolerance || abs(a.minY-b.minY) > tolerance
        || abs(a.width-b.width) > tolerance || abs(a.height-b.height) > tolerance
}
func bytes(_ image: NSBitmapImageRep) -> Data {
    Data(bytes: image.bitmapData!, count: image.bytesPerRow * image.pixelsHigh)
}
func mouse(_ type: NSEvent.EventType, _ point: NSPoint, _ time: Double) -> NSEvent {
    NSEvent.mouseEvent(with: type, location: point, modifierFlags: [], timestamp: time,
                      windowNumber: 0, context: nil, eventNumber: 1, clickCount: 1, pressure: 1)!
}
func headPoint(_ image: NSBitmapImageRep, _ target: TianmuView = view) -> NSPoint {
    let b = bbox(image, "head")
    return NSPoint(x: b.midX, y: target.bounds.height-b.midY)
}
func fixtureKind(_ c: NSColor) -> Int {
    guard c.alphaComponent > 0.99 else { return 0 }
    let r = c.redComponent, g = c.greenComponent, b = c.blueComponent
    if r > 0.95 && b > 0.95 && g < 0.05 { return 1 }
    if g > 0.95 && b > 0.95 && r < 0.05 { return 2 }
    if g > 0.95 && r < 0.05 && b < 0.05 { return 3 }
    if abs(r-160.0/255) < 0.01 && abs(g-r) < 0.01 && abs(b-r) < 0.01 { return 4 }
    return 0
}
struct ColoredPixel: Hashable { let x: Int; let y: Int; let kind: Int }
func normalizedFixture(_ image: NSBitmapImageRep) -> Set<ColoredPixel> {
    let head = bbox(image, "head")
    var result: Set<ColoredPixel> = []
    for y in 0..<image.pixelsHigh { for x in 0..<image.pixelsWide {
        let kind = fixtureKind(image.colorAt(x: x, y: y)!.usingColorSpace(.deviceRGB)!)
        if kind > 0 { result.insert(ColoredPixel(x: x-Int(head.minX), y: y-Int(head.minY), kind: kind)) }
    }}
    return result
}
func assertHitsMatchPixels(_ target: TianmuView) {
    let image = render(target), w = image.pixelsWide, h = image.pixelsHigh
    var drawn = 0, matched = 0, invisibleInteriorHits = 0
    for y in stride(from: 1, to: h-1, by: 2) { for x in stride(from: 1, to: w-1, by: 2) {
        let point = NSPoint(x: CGFloat(x)+0.5, y: CGFloat(h-y)-0.5)
        let hit = target.subject(at: point) == "attendant"
        let color = image.colorAt(x: x, y: y)!.usingColorSpace(.deviceRGB)!
        if fixtureKind(color) > 0 { drawn += 1; if hit { matched += 1 } }
        if hit && color.alphaComponent < 0.01 {
            let nearbyOpaque = [(-1,0),(1,0),(0,-1),(0,1)].contains { dx, dy in
                image.colorAt(x: x+dx, y: y+dy)!.alphaComponent > 0.01
            }
            if !nearbyOpaque { invisibleInteriorHits += 1 }
        }
    }}
    assert(drawn > 30 && Double(matched)/Double(drawn) >= 0.97,
           "Opaque fixed-art pixels must be clickable in the actual rendered pose")
    assert(invisibleInteriorHits == 0, "A moving shoe must release its old transparent area; no invisible hit rectangles")
}
let referenceView = TianmuView(frame: view.frame)
referenceView.attendantArtwork = artwork
referenceView.persistLegacyFrame = false
assert(referenceView.applyRoutine(snapshot(0, 0, 0, "idle")))
let referenceStand = render(referenceView)
func assertStandFeet(_ image: NSBitmapImageRep) {
    for kind in ["cyan", "green"] {
        assert(!changed(localFoot(image, kind), localFoot(referenceStand, kind)),
               "Settled feet must return to the complete original stand")
    }
}
'''


class FixedArtWalkTests(unittest.TestCase):
    def run_swift(self, body, *, rigs=None, facing='right'):
        with tempfile.TemporaryDirectory(prefix='tianmu-fixed-walk-test-') as directory:
            work = Path(directory)
            art_paths = []
            for index, rig in enumerate(rigs if rigs is not None else [RIG]):
                art = work / ('A01-' + str(index))
                art.mkdir()
                # Full source extent is occupied; the head and two shoes are
                # separately identifiable in actual rendered output.
                fixture = {(x, y): (160, 160, 160, 255) for y in range(16, 38) for x in range(24)}
                fixture.update({(x, y): (255, 0, 255, 255) for y in range(16) for x in range(4, 20)})
                fixture.update({(x, y): (0, 255, 255, 255) for y in range(38, 48) for x in range(3, 9)})
                fixture.update({(x, y): (0, 255, 0, 255) for y in range(38, 48) for x in range(15, 21)})
                png(art / 'stand.png', width=24, height=48, pixels=fixture)
                manifest = {'version': 1, 'sampling': 'nearest',
                            'stand': {'file': 'stand.png', 'facing': facing}}
                if rig is not None:
                    manifest['fixedWalk'] = copy.deepcopy(rig)
                (art / 'manifest.json').write_text(json.dumps(manifest))
                art_paths.append(art)
            source = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
            (work / 'Scene.swift').write_text(source)
            (work / 'main.swift').write_text(PRELUDE + body)
            build = subprocess.run(['swiftc', '-framework', 'AppKit', str(work / 'Scene.swift'),
                                    str(work / 'main.swift'), '-o', str(work / 'check')],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(work / 'check'), *map(str, art_paths)],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

    def test_fixed_source_walk_moves_and_changes_feet_without_warping_head(self):
        self.run_swift(r'''
assert(!artwork.hasWalkFrames, "The fixture deliberately has no walk frame table")
assert(view.applyRoutine(snapshot(1)))
let initial = render(), startHead = bbox(initial, "head")
view.updateAnimation(elapsed: 0.65)
let moving = render(), movingHead = bbox(moving, "head")
assert(movingHead.midX < startHead.midX - 1,
       "fixedWalk without frame tables must really travel after a service walk snapshot")
assert(changed(localFoot(initial, "cyan"), localFoot(moving, "cyan"))
       || changed(localFoot(initial, "green"), localFoot(moving, "green")),
       "Feet must change relative to the fixed head; sliding the whole stand is not walking")
assert(abs(movingHead.width-startHead.width) <= 1 && abs(movingHead.height-startHead.height) <= 1,
       "The original head must retain its shape rather than being stretched")
assert(view.unavailableRoutineAction == nil, "A usable fixed-source rig fulfills service walk")
print("PASS: real service travel, feet move relative to an undeformed head, no frame table; NO_WINDOWS_NO_WORKER_NO_SAVE")
''')

    def test_planted_shoe_and_current_hit_mask_follow_real_rendering(self):
        self.run_swift(r'''
assert(artwork.hasWalkMotion && !artwork.hasWalkFrames)
assert(view.applyRoutine(snapshot(1)))
let ground = render()
view.updateAnimation(elapsed: 0.35)
let first = render()
view.updateAnimation(elapsed: 0.75)
let second = render()
assert(bbox(second, "head").midX < bbox(first, "head").midX - 1)
var stableShoes = 0, swingingShoes = 0
for kind in ["cyan", "green"] {
    let a = bbox(first, kind), b = bbox(second, kind), resting = bbox(ground, kind)
    if !changed(a, b, 1) {
        stableShoes += 1
        assert(abs(b.maxY-resting.maxY) <= 1, "The supporting shoe must stay at ground level")
    } else if b.maxY < resting.maxY - 1 || a.maxY < resting.maxY - 1 { swingingShoes += 1 }
}
assert(stableShoes == 1 && swingingShoes == 1,
       "One shoe must remain fixed in world space while the other actually lifts and travels")
for factor: CGFloat in [0.5, 1, 1.5] {
    let target = TianmuView(frame: NSRect(x: 0, y: 0, width: 370*factor, height: 190*factor))
    target.attendantArtwork = artwork; target.persistLegacyFrame = false
    assert(target.applyRoutine(snapshot(1)))
    target.updateAnimation(elapsed: 0.65)
    assertHitsMatchPixels(target)
    // Completing the left leg through a service receipt starts a genuinely right-facing trip.
    assert(target.applyRoutine(snapshot(1, 5)))
    assert(target.applyRoutine(snapshot(2)))
    let start = bbox(render(target), "head").midX
    target.updateAnimation(elapsed: 1.3)
    assert(bbox(render(target), "head").midX > start)
    assertHitsMatchPixels(target)
}
print("PASS: planted world-space shoe, independent lift, rendered alpha and subject input agree in both directions at 50/100/150 percent; NO_WINDOWS_NO_WORKER_NO_SAVE")
''')

    def test_duplicate_and_stale_service_receipts_preserve_motion_and_final_stand(self):
        self.run_swift(r'''
assert(view.applyRoutine(snapshot(7)))
view.updateAnimation(elapsed: 0.65)
let moving = bytes(render())
assert(view.applyRoutine(snapshot(7)))
assert(bytes(render()) == moving, "Duplicate serial/elapsed cannot reset the feet or body")
view.updateAnimation(elapsed: 1)
assert(view.applyRoutine(snapshot(7, 1)))
view.updateAnimation(elapsed: 2)
let frozen = bytes(render())
view.updateAnimation(elapsed: 9)
assert(bytes(render()) == frozen, "A missing service heartbeat must freeze both travel and gait after one second")
assert(view.applyRoutine(snapshot(7, 5)))
let arrived = render(), arrivedHead = bbox(arrived, "head")
assert(normalizedFixture(arrived) == normalizedFixture(referenceStand),
       "At the natural endpoint the entire image must already be the exact original stand")
assert(view.applyRoutine(snapshot(8, 0, 0, "idle")))
assert(bytes(render()) == bytes(arrived), "Finishing a walk must not apply another positional reset")
view.updateAnimation(elapsed: 9.2)
assert(bytes(render()) == bytes(arrived) && bbox(render(), "head") == arrivedHead,
       "Natural arrival needs no extra foot transition or location change")
print("PASS: duplicate receipt idempotence, bounded stale-feed freeze, complete original stand at arrival without a reset; NO_WINDOWS_NO_WORKER_NO_SAVE")
''')

    def test_left_facing_source_keeps_supporting_shoe_fixed_in_world_space(self):
        self.run_swift(r'''
assert(artwork.hasWalkMotion && !artwork.hasWalkFrames)
assert(view.applyRoutine(snapshot(1)))
let ground = render()
view.updateAnimation(elapsed: 0.35)
let first = render()
view.updateAnimation(elapsed: 0.75)
let second = render()
assert(bbox(second, "head").midX < bbox(first, "head").midX - 1,
       "The left-facing source must really travel left")
var planted = 0, swinging = 0
for kind in ["cyan", "green"] {
    let a = bbox(first, kind), b = bbox(second, kind), resting = bbox(ground, kind)
    if !changed(a, b, 1) {
        planted += 1
        assert(abs(b.maxY-resting.maxY) <= 1, "A planted shoe must remain grounded")
    } else if a.maxY < resting.maxY - 1 || b.maxY < resting.maxY - 1 { swinging += 1 }
}
assert(planted == 1 && swinging == 1,
       "Left-facing source: one supporting shoe must remain fixed in world space instead of sliding backward")
print("PASS: left-facing source preserves a grounded world-space supporting shoe while the other foot swings; NO_WINDOWS_NO_WORKER_NO_SAVE")
''', facing='left')

    def test_action_changes_press_and_response_release_settle_only_feet(self):
        self.run_swift(r'''
assert(view.applyRoutine(snapshot(1)))
view.updateAnimation(elapsed: 0.65)
let walking = render(), walkingHead = bbox(walking, "head")
assert(view.applyRoutine(snapshot(2, 0, 0, "idle")))
assert(bytes(render()) == bytes(walking), "A mid-step action change must preserve the first displayed foot pose")
view.updateAnimation(elapsed: 0.85)
let stopped = render()
assert(bbox(stopped, "head") == walkingHead, "Settling feet cannot slide the body")
assertStandFeet(stopped)

assert(view.applyRoutine(snapshot(3)))
view.updateAnimation(elapsed: 1.5)
let beforePress = render(), pressPoint = headPoint(beforePress)
view.mouseDown(with: mouse(.leftMouseDown, pressPoint, 10))
let held = render(), heldHead = bbox(held, "head")
view.updateAnimation(elapsed: 4)
assert(view.applyRoutine(snapshot(3, 5)))
assert(bytes(render()) == bytes(held), "A press must hold the exact foot pixels even when its service walk expires")
view.cancelInteraction()
assert(bytes(render()) == bytes(held), "Releasing a long hold cannot teleport feet back to stand")
view.updateAnimation(elapsed: 4.2)
let released = render()
assert(bbox(released, "head") == heldHead, "Long-hold release must retain its displayed location")
assertStandFeet(released)

assert(view.applyRoutine(snapshot(4)))
let responseAt = 4.85
view.updateAnimation(elapsed: responseAt)
view.respond()
let responseHeld = render(), responseHead = bbox(responseHeld, "head")
view.updateAnimation(elapsed: responseAt + 0.5)
assert(view.applyRoutine(snapshot(5, 0, 0, "idle")))
assert(bytes(render()) == bytes(responseHeld), "A response holds the exact current pose while the new business state arrives")
view.updateAnimation(elapsed: responseAt + 1.1)
assert(bytes(render()) == bytes(responseHeld), "At response release the displayed feet remain continuous")
view.updateAnimation(elapsed: responseAt + 1.3)
let responseDone = render()
assert(bbox(responseDone, "head") == responseHead)
assertStandFeet(responseDone)
print("PASS: action switch, expired press hold and response release preserve initial foot pixels then settle only feet within 0.2 seconds; NO_WINDOWS_NO_WORKER_NO_SAVE")
''')

    def test_invalid_fixed_walk_disables_motion_without_discarding_stand(self):
        invalid = [
            [], {}, 'unsupported',
            {**RIG, 'sourceSize': [25, 48]}, {**RIG, 'sourceSize': [24]},
            {**RIG, 'bodyCutY': 49}, {**RIG, 'bodyCutY': 0},
            {**RIG, 'legStartY': 39}, {**RIG, 'legStartY': -1},
            {**RIG, 'legSplitX': 0}, {**RIG, 'legSplitX': 24},
            {**RIG, 'maxRootStep': 0}, {**RIG, 'maxRootStep': 1000},
            {**RIG, 'footLift': -1}, {**RIG, 'footLift': True},
        ]
        self.run_swift(r'''
for path in CommandLine.arguments.dropFirst(2) {
    guard let candidate = AttendantArtwork.load(from: URL(fileURLWithPath: path)) else {
        fatalError("A bad optional fixedWalk must not discard the otherwise valid stand: \(path)")
    }
    assert(!candidate.hasWalkMotion && !candidate.hasWalkFrames, "Invalid optional rig must be disabled")
    let target = TianmuView(frame: view.frame)
    target.attendantArtwork = candidate; target.persistLegacyFrame = false
    assert(target.applyRoutine(snapshot(0, 0, 0, "idle")))
    let stand = render(target)
    assert(normalizedFixture(stand) == normalizedFixture(referenceStand))
    assert(target.applyRoutine(snapshot(1)))
    target.updateAnimation(elapsed: 0.75)
    assert(bytes(render(target)) == bytes(stand), "A rejected rig must keep the accepted source standing still")
    assert(target.unavailableRoutineAction == "walk")
}
print("PASS: absent/malformed/out-of-range optional rigs preserve valid stand and disable movement; NO_WINDOWS_NO_WORKER_NO_SAVE")
''', rigs=[RIG, None, *invalid])


if __name__ == '__main__':
    unittest.main()
