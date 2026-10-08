"""Natural capture contracts using unshown AppKit windows and synthetic events.

No worker, persisted state, visible window, activation or system permission.
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
let left = DesktopInsectScreen(id: "left", frame: NSRect(x:-1200,y:-100,width:1200,height:800))
let main = DesktopInsectScreen(id: "main", frame: NSRect(x:0,y:0,width:1600,height:1000))
var now: TimeInterval = 37
var presented: [NSWindow] = []
var focusRequests = 0
var caught: [[String]] = []
let layer = DesktopInsects(screens:[left,main], renderTime:{ now }, windowPresenter:{ presented.append($0) })
layer.setNaturalCaptureEnabled(false) // Exercise the retained explicit small-handle path.
layer.onNaturalCaptureBegin = { focusRequests += 1 }
layer.onCapture = { caught.append($0) }
func rows(_ id: String = "fly") -> [[String:Any]] {
    [["id":id,"x":0.5,"y":0.5,"color":"普通褐色"]]
}
layer.update(rows: rows())
layer.show()
func ready() -> NSWindow {
    layer.updatePointer(layer.positions[0].point, buttonsPressed:0, enabled:true)
    assert(layer.isNaturalHandleVisible)
    return layer.captureHandleWindow!
}
func point(_ window: NSWindow) -> NSPoint { NSPoint(x:window.frame.midX,y:window.frame.midY) }
func mouse(_ type:NSEvent.EventType, _ window:NSWindow, _ position:NSPoint) -> NSEvent {
    NSEvent.mouseEvent(with:type, location:window.convertPoint(fromScreen:position), modifierFlags:[], timestamp:now,
        windowNumber:window.windowNumber, context:nil, eventNumber:1, clickCount:1, pressure:1)!
}
func down(_ window:NSWindow) { window.contentView!.mouseDown(with:mouse(.leftMouseDown,window,point(window))) }
func drag(_ window:NSWindow, to position:NSPoint) { window.contentView!.mouseDragged(with:mouse(.leftMouseDragged,window,position)) }
func up(_ window:NSWindow, at position:NSPoint) { window.contentView!.mouseUp(with:mouse(.leftMouseUp,window,position)) }
func passive() {
    assert(layer.windows.allSatisfy{$0.ignoresMouseEvents})
    assert(!layer.isCapturing)
}
func cleared() {
    passive()
    assert(!layer.isNaturalHandleVisible)
    assert(layer.captureHandleWindow?.ignoresMouseEvents != false)
}

switch CommandLine.arguments[1] {
case "hover":
    let window = ready()
    passive()
    assert(window.frame.width == 40 && window.frame.height == 28)
    assert(!window.canBecomeKey && !window.canBecomeMain)
    assert(window is NSPanel, "Nonactivation requires an actual panel, not a window with a panel flag")
    assert(window.styleMask.contains(.nonactivatingPanel), "Pressing a grab point must not activate the app")
    assert(window.level.rawValue < NSWindow.Level.normal.rawValue)
    assert(window.level == layer.windows[0].level)
    assert(!window.ignoresMouseEvents && focusRequests == 0)
    let fixed = window.frame
    now += 0.4; layer.refresh()
    layer.updatePointer(point(window), buttonsPressed:0)
    assert(window.frame == fixed, "Handle must not chase the fly or pointer")
    assert(layer.captureHandleWindow === window)
    layer.setLevel(aboveApplications:true)
    assert(window.level == .floating)
    layer.setLevel(aboveApplications:false)
    assert(window.level.rawValue < 0)
    layer.updatePointer(NSPoint(x:3000,y:3000), buttonsPressed:0)
    cleared()
case "external_drag":
    let insect = layer.positions[0].point
    layer.updatePointer(insect, buttonsPressed:1)
    cleared()
    let window = ready()
    layer.updatePointer(point(window), buttonsPressed:1)
    cleared()
    assert(focusRequests == 0 && caught.isEmpty)
    _ = ready()
    layer.updatePointer(point(window), buttonsPressed:0, enabled:false)
    cleared()
    layer.updatePointer(NSPoint(x:Double.nan,y:0), buttonsPressed:0)
    cleared()
case "threshold":
    let window = ready(), origin = point(layer.captureHandleWindow!)
    down(window)
    passive()
    assert(focusRequests == 0 && layer.isNaturalHandleVisible)
    layer.updatePointer(origin, buttonsPressed:1)
    assert(layer.isNaturalHandleVisible, "A press that began on the handle must survive polling")
    drag(window,to:NSPoint(x:origin.x+3,y:origin.y))
    passive()
    up(window,at:NSPoint(x:origin.x+3,y:origin.y))
    assert(layer.isCapturing && layer.captureState == .armed && !layer.isNaturalHandleVisible)
    assert(focusRequests == 1 && caught.isEmpty && !layer.isWeaving)
    layer.cancelCapture()
    cleared()
    let same = ready()
    same.contentView!.rightMouseDown(with:mouse(.rightMouseDown,same,point(same)))
    passive()
    assert(focusRequests == 1)
    down(same)
    drag(same,to:NSPoint(x:point(same).x+5,y:point(same).y))
    assert(layer.isCapturing && focusRequests == 2)
    assert(layer.windows.allSatisfy{$0.ignoresMouseEvents && $0.level == .floating})
    assert(layer.captureHandleWindow === same && !same.ignoresMouseEvents)
    layer.cancelCapture()
    cleared()
case "continuous":
    let window = ready(), origin = point(layer.captureHandleWindow!)
    down(window)
    let finish = NSPoint(x:origin.x+80,y:origin.y-80)
    drag(window,to:finish)
    assert(layer.isCapturing && focusRequests == 1)
    up(window,at:finish)
    cleared()
    assert(layer.isWeaving && caught.isEmpty, "Same gesture releases input and then weaves")
    layer.updatePointer(layer.positions[0].point, buttonsPressed:0)
    cleared()
    up(window,at:finish)
    now += 2; layer.refresh()
    assert(caught == [["fly"]])
    now += 1; layer.refresh(); layer.refresh()
    assert(!layer.isWeaving && caught.count == 1)
case "cancellation":
    for index in 0..<7 {
        layer.updateScreens([left,main]); layer.update(rows:rows()); layer.show()
        let window = ready(), origin = point(layer.captureHandleWindow!)
        down(window)
        // A removed anchor only cancels before the drag threshold. 163 covers
        // removal after the threshold, when the selection belongs to the player.
        if index % 2 == 0 && index != 6 { drag(window,to:NSPoint(x:origin.x+80,y:origin.y-80)) }
        switch index {
        case 0: layer.cancelCapture()
        case 1: layer.hide()
        case 2: layer.updateScreens([left])
        case 3: layer.update(rows:[])
        case 4: NotificationCenter.default.post(name:NSApplication.didResignActiveNotification,object:app)
        case 5: layer.updatePointer(origin,buttonsPressed:1,enabled:false)
        default: layer.update(rows:rows("replacement"))
        }
        cleared()
        drag(window,to:NSPoint(x:origin.x+100,y:origin.y-100)); up(window,at:origin)
        now += 6; layer.refresh()
        assert(caught.isEmpty && !layer.isWeaving, "Cancelled old handle events cannot resurrect capture")
    }
case "reentrant_cancel":
    let window = ready(), origin = point(layer.captureHandleWindow!)
    layer.onNaturalCaptureBegin = { focusRequests += 1; layer.cancelCapture() }
    down(window); drag(window,to:NSPoint(x:origin.x+60,y:origin.y-60))
    cleared()
    up(window,at:NSPoint(x:origin.x+60,y:origin.y-60))
    now += 6; layer.refresh()
    assert(focusRequests == 1 && caught.isEmpty && !layer.isWeaving)
case "edges":
    layer.updateScreens([left])
    for x in [0.0,1.0] { for y in [0.0,1.0] {
        layer.cancelCapture()
        layer.update(rows:[["id":"fly","x":x,"y":y,"color":"普通褐色"]])
        let window = ready()
        assert(left.frame.contains(window.frame), "Negative-screen edge handle must be wholly in the screen")
    } }
    layer.hide()
    layer.updatePointer(layer.positions[0].point,buttonsPressed:0)
    cleared()
case "current_ids":
    let window = ready(), origin = point(layer.captureHandleWindow!)
    down(window); drag(window,to:NSPoint(x:origin.x+80,y:origin.y-80))
    up(window,at:NSPoint(x:origin.x+80,y:origin.y-80))
    layer.update(rows:[])
    now += 2; layer.refresh()
    assert(caught == [[]], "A fly caught automatically during weaving must not be sent again")
    now += 1; layer.refresh()
    layer.update(rows:rows())
    layer.beginCapture()
    assert(layer.isCapturing && !layer.isNaturalHandleVisible, "Legacy explicit capture remains available")
    layer.cancelCapture()
default: fatalError("Unknown scenario")
}
assert(presented.allSatisfy{!$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow})
layer.close()
assert(layer.captureHandleWindow == nil && !layer.isNaturalHandleVisible)
print("PASS \(CommandLine.arguments[1]): unshown native windows, no worker/save/activation/permission")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class NaturalCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tianmu-natural-capture-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.binary = folder / "check"
        harness = folder / "main.swift"
        harness.write_text(with_desktop_motion_fixture(HARNESS))
        cls.build = subprocess.run(["swiftc", "-framework", "AppKit", str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(SOURCE), str(harness), "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)

    def scenario(self, name):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        run = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"PASS {name}:", run.stdout)
        print(run.stdout.strip())

    def test_hover_uses_one_stationary_small_desktop_handle_and_keeps_fullscreen_passive(self):
        self.scenario("hover")

    def test_external_drag_disabled_state_and_invalid_pointer_never_take_input(self):
        self.scenario("external_drag")

    def test_short_release_arms_right_click_stays_passive_and_drag_starts_at_threshold(self):
        self.scenario("threshold")

    def test_one_continuous_handle_gesture_weaves_and_commits_only_once_after_release(self):
        self.scenario("continuous")

    def test_cancel_hide_focus_screen_change_and_removed_anchor_leave_no_input_or_capture(self):
        self.scenario("cancellation")

    def test_cancellation_inside_focus_callback_does_not_resurrect_the_gesture(self):
        self.scenario("reentrant_cancel")

    def test_handles_fit_negative_screen_edges_and_cannot_reappear_while_hidden(self):
        self.scenario("edges")

    def test_weaving_uses_current_ids_and_legacy_explicit_capture_still_works(self):
        self.scenario("current_ids")


if __name__ == "__main__":
    unittest.main()
