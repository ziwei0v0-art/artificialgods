"""Desktop insect contract checks. All AppKit windows remain unshown.

No application host, worker, persisted data, or system permission is used.
"""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native/v1/DesktopInsects.swift"

HARNESS = r'''
import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let left = DesktopInsectScreen(id: "left", frame: NSRect(x: -1200, y: -100, width: 1200, height: 800))
let main = DesktopInsectScreen(id: "main", frame: NSRect(x: 0, y: 0, width: 1600, height: 1000))
var now: TimeInterval = 37
// CLI harnesses have no app Bundle resources: inject the same production art explicitly.
let artwork = InsectArtwork(directory: URL(fileURLWithPath: CommandLine.arguments[2]))
assert(artwork.availableStyles == Set([.cute, .realistic]))
let layer = DesktopInsects(screens: [left, main], renderTime: { now }, artwork: artwork)
func rows(_ count: Int = 24) -> [[String: Any]] {
    (0..<count).map { index -> [String: Any] in
        let x = Double(index % 5) / 4
        let y = Double(index % 7) / 6
        let color = ["普通褐色", "中褐色", "深褐色", "白色"][index % 4]
        return ["id": "fly-\(index)", "x": x, "y": y, "color": color]
    }
}
func assertUnshown() {
    assert(layer.windows.allSatisfy { !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow }, "Test must never show or focus a window")
}
func mouse(_ type: NSEvent.EventType, _ window: NSWindow, _ global: NSPoint) -> NSEvent {
    NSEvent.mouseEvent(with: type, location: window.convertPoint(fromScreen: global), modifierFlags: [],
                      timestamp: now, windowNumber: window.windowNumber, context: nil,
                      eventNumber: 1, clickCount: 1, pressure: 1)!
}
func drag(_ window: NSWindow, _ a: NSPoint, _ b: NSPoint, release: Bool = true) {
    let view = window.contentView!
    view.mouseDown(with: mouse(.leftMouseDown, window, a))
    view.mouseDragged(with: mouse(.leftMouseDragged, window, b))
    if release { view.mouseUp(with: mouse(.leftMouseUp, window, b)) }
}

switch CommandLine.arguments[1] {
case "windows":
    assert(layer.windows.count == 2)
    assert(Set(layer.windows.map { $0.frame }) == Set([left.frame, main.frame]), "Use complete screen frames, including negative origins")
    for window in layer.windows {
        assert(!window.canBecomeKey && !window.canBecomeMain)
        assert(window.ignoresMouseEvents && !window.isOpaque && !window.hasShadow)
        assert(window.backgroundColor?.alphaComponent == 0)
        assert(window.level.rawValue == Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        assert(window.level.rawValue < NSWindow.Level.normal.rawValue)
        assert(window.collectionBehavior.contains(.canJoinAllSpaces))
        assert(window.collectionBehavior.contains(.stationary))
        assert(!window.collectionBehavior.contains(.fullScreenAuxiliary))
    }
    layer.setLevel(aboveApplications: true)
    assert(layer.windows.allSatisfy { $0.level == .floating && $0.ignoresMouseEvents })
    layer.setLevel(aboveApplications: false)
    assert(layer.windows.allSatisfy { $0.level.rawValue < NSWindow.Level.normal.rawValue && $0.ignoresMouseEvents })
case "identity":
    layer.update(rows: rows() + [rows()[0]])
    assert(layer.positions.count == 24 && Set(layer.positions.map { $0.id }).count == 24, "Duplicate rows must not duplicate insects")
    assert(Set(layer.positions.map { $0.screenID }) == Set(["left", "main"]))
    let original = Dictionary(uniqueKeysWithValues: layer.positions.map { ($0.id, $0.screenID) })
    for position in layer.positions {
        let frame = position.screenID == "left" ? left.frame : main.frame
        assert(frame.insetBy(dx: 7, dy: 7).contains(position.point), "No insect may live in a gap or beyond its display")
    }
    assert(layer.positions.contains { $0.point.x < -800 })
    assert(layer.positions.contains { $0.point.x > 900 }, "Activity must cover the desktop, not a 540-point pet canvas")
    let before = Dictionary(uniqueKeysWithValues: layer.positions.map { ($0.id, $0.point) })
    layer.update(rows: Array(rows().reversed()))
    assert(Dictionary(uniqueKeysWithValues: layer.positions.map { ($0.id, $0.point) }) == before, "Reordered backend rows must not teleport insects")
    layer.updateScreens([main, left])
    assert(Dictionary(uniqueKeysWithValues: layer.positions.map { ($0.id, $0.screenID) }) == original)
    layer.updateScreens([main])
    assert(layer.windows.count == 1 && layer.positions.count == 24)
    assert(layer.positions.allSatisfy { $0.screenID == "main" && main.frame.contains($0.point) })
    layer.updateScreens([])
    assert(layer.windows.isEmpty && layer.positions.isEmpty)
    layer.updateScreens([left])
    assert(layer.positions.count == 24 && layer.positions.allSatisfy { left.frame.contains($0.point) })
case "render_capture":
    layer.updateScreens([left])
    layer.update(rows: [["id":"moving", "x":0.75, "y":0.3, "color":"深褐色"]])
    let earlier = layer.positions[0].point
    // A continuous sequence advances flight; a long suspended interval must
    // no longer fast-forward it (163 display-only movement contract).
    for _ in 0..<9 { now += 1.0/30; layer.refresh() }
    let center = layer.positions[0].point
    assert(center.x < 0, "Exercise an actual negative-origin screen")
    assert(hypot(center.x - earlier.x, center.y - earlier.y) > 1, "Insects must keep moving between backend snapshots")
    let window = layer.windows[0], view = window.contentView!
    let local = window.convertPoint(fromScreen: center)
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1200, pixelsHigh: 800,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    view.draw(view.bounds)
    NSGraphicsContext.restoreGraphicsState()
    // Bitmap rows are top-down, AppKit screen/view points are bottom-up.
    let centerColor = bitmap.colorAt(x: Int(local.x), y: 799 - Int(local.y))!
    assert(centerColor.alphaComponent > 0.5, "Drawn body must occupy the very center used by capture")
    assert(bitmap.colorAt(x: 30, y: 30)!.alphaComponent == 0, "Layer must stay transparent away from insects")
    var captures: [[String]] = []
    layer.onCapture = { captures.append($0) }
    layer.beginCapture()
    assert(layer.isCapturing && window.ignoresMouseEvents, "Even explicit capture must never install a full-screen mouse shield")
    // A tight box excludes the old position; drawing/catching cannot use separate coordinates.
    drag(window, NSPoint(x:center.x-0.3,y:center.y-0.3), NSPoint(x:center.x+0.3,y:center.y+0.3))
    assert(captures.isEmpty, "Mouse-up starts weaving; it must not submit capture")
    assert(!layer.isCapturing && window.ignoresMouseEvents && window.level.rawValue < NSWindow.Level.normal.rawValue)
    window.contentView!.mouseUp(with: mouse(.leftMouseUp, window, center))
    assert(captures.isEmpty, "A repeated mouse-up must not submit capture")
    for _ in 0..<150 { now += 1.0/30; layer.refresh() }
    let moved = layer.positions[0].point
    assert(abs(moved.x-center.x) > 0.3 || abs(moved.y-center.y) > 0.3)
    assert(captures == [[]], "A bug that leaves the tight net during weaving must escape")
    assert(layer.positions.count == 1, "Only backend acknowledgement removes captured insects")
case "cross_screen_capture":
    layer.update(rows: rows())
    let expected = Set(rows().map { $0["id"] as! String })
    var captures: [[String]] = []
    layer.onCapture = { captures.append($0) }
    layer.beginCapture()
    // AppKit keeps delivering a drag to the original view beyond its own screen.
    let window = layer.windows.first { $0.frame.minX < 0 }!
    drag(window, NSPoint(x:-1200,y:-100), NSPoint(x:1600,y:1000))
    assert(captures.isEmpty, "Cross-screen release must not bypass weaving")
    now += 5
    layer.refresh()
    assert(captures.count == 1 && Set(captures[0]) == expected && captures[0].count == 24)
    assert(layer.windows.allSatisfy { $0.ignoresMouseEvents })
case "cancellation":
    layer.update(rows: rows())
    var captured = 0
    layer.onCapture = { _ in captured += 1 }
    for cancel in [0, 1, 2, 3] {
        layer.beginCapture()
        let window = layer.windows[0]
        drag(window, NSPoint(x:-1100,y:0), NSPoint(x:400,y:400), release:false)
        switch cancel {
        case 0: layer.cancelCapture()
        case 1: NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: app)
        case 2: layer.hide()
        default: layer.updateScreens([main, left])
        }
        assert(!layer.isCapturing && layer.windows.allSatisfy { $0.ignoresMouseEvents })
        layer.beginCapture()
        window.contentView?.mouseUp(with: mouse(.leftMouseUp, window, NSPoint(x:400,y:400)))
        assert(captured == 0, "Cancelled drag rectangle must not survive rearming")
        layer.cancelCapture()
    }
    // Released weaving survives focus loss (163-capture: passive_weaving and
    // explicit_focus); held-gesture focus cancellation remains asserted above.
    for cancel in [0, 2, 3] {
        layer.beginCapture()
        let window = layer.windows[0]
        drag(window, NSPoint(x:-1100,y:0), NSPoint(x:400,y:400))
        assert(layer.isWeaving && !layer.isCapturing && window.ignoresMouseEvents)
        switch cancel {
        case 0: layer.cancelCapture()
        case 2: layer.hide()
        default: layer.updateScreens([main, left])
        }
        now += 10
        layer.refresh()
        assert(!layer.isWeaving && captured == 0, "Cancelled weaving must never submit later")
    }
    layer.setLevel(aboveApplications: true)
    layer.beginCapture(); layer.cancelCapture()
    assert(layer.windows.allSatisfy { $0.level == .floating && $0.ignoresMouseEvents })
    let oldWindows = layer.windows
    layer.close()
    assert(layer.windows.isEmpty && layer.positions.isEmpty && !layer.isCapturing)
    assert(oldWindows.allSatisfy { !$0.isVisible && $0.ignoresMouseEvents })
case "weaving_clock":
    layer.updateScreens([main])
    layer.update(rows: [["id":"inside", "x":0.5,"y":0.5,"color":"普通褐色"]])
    let window = layer.windows[0]
    var captures: [[String]] = []
    layer.onCapture = { captures.append($0) }
    layer.beginCapture()
    drag(window, NSPoint(x:750,y:450), NSPoint(x:850,y:550))
    assert(layer.isWeaving && layer.weaveProgress == 0 && captures.isEmpty)
    assert(!layer.isCapturing && layer.windows.allSatisfy { $0.ignoresMouseEvents })
    now += 0.12
    layer.refresh()
    let early = layer.weaveProgress!
    assert(early > 0 && early < 0.2 && captures.isEmpty, "First phase lays radial skeleton")
    now += 0.4
    layer.refresh()
    assert(layer.weaveProgress! > early && layer.weaveProgress! < 1 && captures.isEmpty)
    now += 1.5
    layer.refresh()
    assert(captures == [["inside"]] && layer.isWeaving && layer.weaveProgress == 1)
    now += 0.3
    layer.refresh()
    assert(!layer.isWeaving && layer.weaveProgress == nil && captures.count == 1, "Completed web retracts and does not capture twice")
    layer.beginCapture()
    drag(window, NSPoint(x:200,y:100), NSPoint(x:1400,y:900))
    now += 2
    layer.refresh()
    assert(layer.isWeaving && layer.weaveProgress! < 1 && captures.count == 1, "A large net must take longer than a small one")
    // Automatic capture removes the old insect; a newly released current individual can enter.
    layer.update(rows: [["id":"newcomer", "x":0.5,"y":0.5,"color":"白色"]])
    now += 2.1
    layer.refresh()
    assert(captures == [["inside"], ["newcomer"]], "Completion evaluates current IDs and current positions")
    now += 1
    layer.refresh(); layer.refresh()
    assert(captures.count == 2 && !layer.isWeaving)
case "weaving_frames":
    let screen = DesktopInsectScreen(id:"visual", frame:NSRect(x:-320,y:-40,width:320,height:240))
    let timing = DesktopWeavingConfiguration(minimumDuration:2, maximumDuration:2, fullDurationArea:800_000, retractionDuration:0.25)
    let visual = DesktopInsects(screens:[screen], renderTime:{now}, weaving:timing)
    let window = visual.windows[0]
    func frame(_ name: String) -> NSBitmapImageRep {
        let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil, pixelsWide:320, pixelsHigh:240,
            bitsPerSample:8, samplesPerPixel:4, hasAlpha:true, isPlanar:false,
            colorSpaceName:.deviceRGB, bytesPerRow:0, bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
        window.contentView!.draw(window.contentView!.bounds)
        NSGraphicsContext.restoreGraphicsState()
        if CommandLine.arguments.count > 3 {
            let output = URL(fileURLWithPath:CommandLine.arguments[3]).appendingPathComponent(name + ".png")
            try! bitmap.representation(using:.png, properties:[:])!.write(to:output)
        }
        return bitmap
    }
    func visiblePixels(_ bitmap: NSBitmapImageRep) -> Int {
        var count = 0
        for y in 0..<240 { for x in 0..<320 {
            if bitmap.bitmapData![y * bitmap.bytesPerRow + x * 4 + 3] > 10 { count += 1 }
        } }
        return count
    }
    visual.beginCapture()
    drag(window, NSPoint(x:-280,y:-10), NSPoint(x:-40,y:170))
    assert(!visual.isCapturing && window.ignoresMouseEvents)
    _ = frame("138-insects-weave-0-start")
    now += 0.2; visual.refresh()
    let early = frame("138-insects-weave-1-skeleton")
    now += 1; visual.refresh()
    let middle = frame("138-insects-weave-2-spiral")
    // At 60% of a two-second weave, thread growth is 50%: three turns, spider halfway right.
    let spider = middle.colorAt(x:220,y:119)!.usingColorSpace(.deviceRGB)!
    // Calibrated 0.20 gray becomes about 0.26 in device RGB; distinguish it from the pale thread.
    assert(spider.alphaComponent > 0.9 && spider.redComponent < 0.35, "Spider must follow the thread away from the center")
    now += 0.7; visual.refresh()
    let late = frame("138-insects-weave-3-outer")
    assert(visiblePixels(early) > 100)
    assert(visiblePixels(middle) > visiblePixels(early) * 2, "The drawing must add rings beyond the initial spokes")
    assert(visiblePixels(late) > visiblePixels(middle), "Later rings extend outwards")
    now += 0.1; visual.refresh()
    _ = frame("138-insects-weave-4-complete")
    now += 0.12; visual.refresh()
    _ = frame("138-insects-weave-5-retract")
    now += 0.2; visual.refresh()
    assert(visiblePixels(frame("138-insects-weave-6-cleared")) == 0, "Retraction must remove every net/spider pixel")
    assert(visual.windows.allSatisfy { !$0.isVisible && $0.ignoresMouseEvents })
    visual.close()
case "latest_rows":
    layer.updateScreens([main])
    layer.update(rows: [["id":"gone", "x":0.5,"y":0.5,"color":"白色"]])
    let window = layer.windows[0]
    var result: [[String]] = []
    layer.onCapture = { result.append($0) }
    layer.beginCapture()
    drag(window, .zero, NSPoint(x:1600,y:1000), release:false)
    layer.update(rows: [])
    window.contentView!.mouseUp(with: mouse(.leftMouseUp, window, NSPoint(x:1600,y:1000)))
    assert(result.isEmpty)
    now += 5
    layer.refresh()
    assert(result == [[]], "An insect removed by automatic capture must not be sent again")
    layer.update(rows: [["id":"valid", "x":-2,"y":3,"color":"白色"],
                        ["id":"bad-x", "x":Double.nan,"y":0.5,"color":"白色"],
                        ["id":"missing-y", "x":0.5,"color":"白色"],
                        ["id":"", "x":0.5,"y":0.5,"color":"白色"]])
    assert(layer.positions.count == 1 && layer.positions[0].id == "valid")
    assert(main.frame.insetBy(dx:7,dy:7).contains(layer.positions[0].point))
default: fatalError("Unknown scenario")
}
assertUnshown()
layer.close()
print("PASS \(CommandLine.arguments[1]): real unshown AppKit windows; no worker, save, permissions, or visible window")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class DesktopInsectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tianmu-desktop-insects-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.binary = folder / "check"
        if SOURCE.exists():
            harness = folder / "main.swift"
            harness.write_text(with_desktop_motion_fixture(HARNESS))
            cls.build = subprocess.run(["swiftc", "-framework", "AppKit", str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(SOURCE), str(harness), "-o", str(cls.binary)],
                                       capture_output=True, text=True, timeout=60)

    def check_scenario(self, scenario):
        self.assertTrue(SOURCE.exists(), "Independent desktop insect layer is not implemented")
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        run = subprocess.run([str(self.binary), scenario, str(ROOT / 'assets/production/insects')], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"PASS {scenario}:", run.stdout)
        print(run.stdout.strip())

    def test_full_screen_nonfocusing_windows_default_below_applications(self):
        self.check_scenario("windows")

    def test_ids_are_unique_stable_and_rehomed_after_display_removal(self):
        self.check_scenario("identity")

    def test_draw_and_single_capture_use_the_same_moving_screen_position(self):
        self.check_scenario("render_capture")

    def test_cancellation_hiding_focus_loss_and_screen_changes_release_input(self):
        self.check_scenario("cancellation")

    def test_drag_can_capture_across_screen_boundary_without_duplicate_ids(self):
        self.check_scenario("cross_screen_capture")

    def test_capture_uses_current_rows_and_rejects_invalid_coordinates(self):
        self.check_scenario("latest_rows")

    def test_weaving_clock_progress_duration_completion_and_current_ids(self):
        self.check_scenario("weaving_clock")

    def test_offscreen_weaving_draws_spokes_then_rings_and_spider_then_retracts(self):
        self.check_scenario("weaving_frames")


if __name__ == "__main__":
    unittest.main()
