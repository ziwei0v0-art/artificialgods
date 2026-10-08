"""163 gesture-continuity regressions; unshown native windows, no worker/save/input tap."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let screen = DesktopInsectScreen(id:"test",frame:NSRect(x:-1200,y:-100,width:1200,height:800))
var now: TimeInterval = 37
var presented: [NSWindow] = []
var focusRequests = 0
var captured: [[String]] = []
let layer = DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{presented.append($0)})
layer.setNaturalCaptureEnabled(false) // Exercise the retained explicit small-handle path.
layer.onNaturalCaptureBegin = { focusRequests += 1 }
layer.onCapture = { captured.append($0) }
func require(_ value: @autoclosure () -> Bool, _ message:String) {
    if !value() { print("FAIL: \(message)"); exit(1) }
}
func rows(_ id:String) -> [[String:Any]] { [["id":id,"x":0.5,"y":0.5,"color":"普通褐色"]] }
layer.update(rows:rows("anchor")); layer.show()
func pointerEvent(_ type:NSEvent.EventType,_ window:NSWindow,_ point:NSPoint) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:window.convertPoint(fromScreen:point),modifierFlags:[],timestamp:now,
        windowNumber:window.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
func event(_ type:NSEvent.EventType,_ window:NSWindow,_ point:NSPoint) {
    let value = pointerEvent(type,window,point)
    switch type {
    case .leftMouseDown: window.contentView!.mouseDown(with:value)
    case .leftMouseDragged: window.contentView!.mouseDragged(with:value)
    default: window.contentView!.mouseUp(with:value)
    }
}
func press() -> (NSWindow,NSPoint,NSPoint) {
    layer.updatePointer(layer.positions[0].point,buttonsPressed:0)
    require(layer.isNaturalHandleVisible,"Fixture needs the real natural grab point")
    let window = layer.captureHandleWindow!
    let start = NSPoint(x:window.frame.midX,y:window.frame.midY)
    let end = NSPoint(x:start.x+100,y:start.y-100)
    event(.leftMouseDown,window,start)
    return (window,start,end)
}
func passive() {
    require(!layer.isCapturing && layer.windows.allSatisfy{$0.ignoresMouseEvents},"All screen input must already be released")
}
func resign() { NotificationCenter.default.post(name:NSApplication.didResignActiveNotification,object:app) }
func complete() { now += 6; layer.refresh(); now += 1; layer.refresh(); layer.refresh() }

switch CommandLine.arguments[1] {
case "fast_release":
    let (window,_,end) = press()
    event(.leftMouseUp,window,end)
    require(layer.isWeaving,"A displaced mouse-up must finish the drag even without an intermediate dragged event")
    passive()
    require(focusRequests == 0,"An already released fast gesture must not take application focus")
    event(.leftMouseUp,window,end)
    complete()
    require(captured == [["anchor"]],"The fast gesture must capture once, not zero or twice")
case "anchor_removed":
    let (window,_,end) = press()
    event(.leftMouseDragged,window,end)
    require(layer.isCapturing,"Fixture must exceed the drag threshold")
    layer.update(rows:rows("survivor"))
    require(layer.isCapturing,"Removing the starting fly must not cancel the user's active selection")
    event(.leftMouseDragged,window,end); event(.leftMouseUp,window,end)
    require(layer.isWeaving,"Active selection must still weave after its starting fly disappears")
    // Even the surviving fly can be caught automatically while weaving.
    layer.update(rows:rows("current"))
    complete()
    require(captured == [["current"]],"Completion must use current IDs, never freeze/restore starting insects")
case "passive_weaving":
    let (window,_,end) = press()
    event(.leftMouseDragged,window,end); event(.leftMouseUp,window,end)
    require(layer.isWeaving,"Fixture must reach passive weaving")
    passive(); resign()
    require(layer.isWeaving,"Switching to another application after release must preserve passive weaving")
    layer.update(rows:rows("current"))
    complete(); resign(); layer.refresh()
    require(captured == [["current"]],"Passive weaving must submit current IDs once despite repeated loss of focus")
    passive()
case "active_focus_loss":
    let (window,_,end) = press()
    event(.leftMouseDragged,window,end); resign()
    passive()
    require(!layer.isNaturalHandleVisible && !layer.isWeaving,"Focus loss during a held drag must cancel")
    event(.leftMouseDragged,window,end); event(.leftMouseUp,window,end); complete()
    require(captured.isEmpty,"Late events from a cancelled press must never resurrect a net")
case "pending_focus_loss":
    let (window,_,end) = press()
    resign()
    event(.leftMouseUp,window,end); complete()
    require(captured.isEmpty && !layer.isWeaving && !layer.isNaturalHandleVisible,"Focus loss before threshold must reject a later displaced up")
    passive()
case "negative_releases":
    // 164 gives a short click a useful armed mode; zero-area displaced drags
    // still cancel and can never submit a capture.
    for delta in [NSPoint(x:30,y:0),NSPoint(x:0,y:-30)] {
        let (window,start,_) = press()
        event(.leftMouseUp,window,NSPoint(x:start.x+delta.x,y:start.y+delta.y))
        require(!layer.isWeaving,"Zero-area selections must not weave")
        passive()
    }
    require(focusRequests == 0 && captured.isEmpty,"Negative releases must neither focus nor capture")
case "prethreshold_anchor":
    let (window,_,end) = press()
    layer.update(rows:rows("replacement"))
    require(!layer.isNaturalHandleVisible,"Before a drag starts the missing starting fly must remove its handle")
    event(.leftMouseUp,window,end); complete()
    require(captured.isEmpty && !layer.isWeaving,"A stale prethreshold press cannot become a quick-release capture")
case "explicit_focus":
    layer.beginCapture()
    let window = layer.windows[0], center = layer.positions[0].point
    let start = NSPoint(x:center.x-60,y:center.y+60), end = NSPoint(x:center.x+60,y:center.y-60)
    event(.leftMouseDown,window,start); event(.leftMouseDragged,window,end); event(.leftMouseUp,window,end)
    resign()
    require(layer.isWeaving,"The legacy menu entry also releases into passive weaving")
    complete(); require(captured == [["anchor"]],"Legacy weaving must complete once after losing focus")
    layer.beginCapture(); event(.leftMouseDown,window,start); event(.leftMouseDragged,window,end); resign()
    event(.leftMouseUp,window,end); complete()
    require(captured.count == 1 && !layer.isWeaving,"A held legacy drag must still cancel on focus loss")
case "explicit_cancel":
    for choice in 0..<4 {
        layer.show(); layer.update(rows:rows("anchor"))
        let (window,_,end) = press()
        event(.leftMouseDragged,window,end); event(.leftMouseUp,window,end)
        require(layer.isWeaving,"Fixture must start weaving")
        switch choice {
        case 0: layer.cancelCapture() // Esc and sleep use this explicit contract.
        case 1: layer.hide()
        case 2: layer.updateScreens([screen])
        default: layer.beginCapture(); layer.cancelCapture() // A newly requested net cancels the old one.
        }
        complete()
        require(captured.isEmpty && !layer.isWeaving,"Explicit cancellation must still clear the whole net")
    }
default: fatalError("Unknown scenario")
}
require(presented.allSatisfy{!$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow},"Test must never show or focus a window")
layer.close()
print("PASS: \(CommandLine.arguments[1]); native unshown events; no worker/save/activation/global input")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class CaptureFrictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tianmu-capture-friction-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.binary = folder / "check"
        source = folder / "main.swift"
        source.write_text(with_desktop_motion_fixture(HARNESS))
        cls.build = subprocess.run(["swiftc", "-framework", "AppKit", *(str(ROOT / "native/v1" / name) for name in ["WindowPlacement.swift", "InsectArtwork.swift", "DesktopInsects.swift"]), str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)

    def scenario(self, name):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS: {name};", result.stdout)
        print(result.stdout.strip())

    def test_displaced_mouse_up_finishes_without_requiring_an_intermediate_drag_event(self):
        self.scenario("fast_release")

    def test_active_selection_survives_starting_fly_removal_and_uses_current_ids(self):
        self.scenario("anchor_removed")

    def test_released_net_keeps_weaving_after_focus_loss_without_holding_input(self):
        self.scenario("passive_weaving")

    def test_focus_loss_still_cancels_held_drag_and_rejects_old_events(self):
        self.scenario("active_focus_loss")

    def test_focus_loss_before_threshold_rejects_late_displaced_up(self):
        self.scenario("pending_focus_loss")

    def test_displaced_zero_area_release_never_captures_or_focuses(self):
        self.scenario("negative_releases")

    def test_missing_starting_fly_before_threshold_still_removes_handle(self):
        self.scenario("prethreshold_anchor")

    def test_menu_capture_distinguishes_active_drag_from_released_weaving_on_focus_loss(self):
        self.scenario("explicit_focus")

    def test_escape_hide_screen_change_and_new_net_still_cancel_passive_weaving(self):
        self.scenario("explicit_cancel")


if __name__ == "__main__":
    unittest.main()
