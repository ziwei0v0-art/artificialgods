"""169 released natural nets: real production boundary, in-memory input only."""
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
var now:TimeInterval = 10
let screen = DesktopInsectScreen(id:"test",frame:NSRect(x:-1000,y:-100,width:1000,height:800))
let primaryTop = NSScreen.screens.first!.frame.maxY
let origin = NSPoint(x:-600,y:200), finish = NSPoint(x:-400,y:400)
let iconLevel = Int(CGWindowLevelForKey(.desktopIconWindow))
let dockLevel = Int(CGWindowLevelForKey(.dockWindow))
func row(_ number:Int,_ owner:Int,_ level:Int,_ frame:NSRect,_ alpha:Double = 1) -> [String:Any] {
    [kCGWindowNumber as String:number,kCGWindowOwnerPID as String:owner,kCGWindowLayer as String:level,
     kCGWindowAlpha as String:alpha,kCGWindowBounds as String:["X":frame.minX,"Y":primaryTop-frame.maxY,
     "Width":frame.width,"Height":frame.height]]
}
let icons = row(2,401,iconLevel,screen.frame), dock = row(25,402,dockLevel,screen.frame)
var rows = [icons,dock]
var reliable = true
var captured:[[String]] = []
func metadata() -> DesktopNaturalCaptureContext {
    if !reliable { return DesktopNaturalCaptureContext(screenID:"test",visibleFrame:screen.frame,
        desktopFrames:[],blockedFrames:[],isReliable:false,dragPasteboardChangeCount:7) }
    return DesktopNaturalCaptureContext.fromWindowInfo(rows,screenID:"test",visibleFrame:screen.frame,
        primaryTop:primaryTop,excludingWindowNumbers:[],dragPasteboardChangeCount:7,
        applicationIdentifier:{$0 == 401 ? "com.apple.finder" : $0 == 402 ? "com.apple.dock" : nil})
}
let layer = DesktopInsects(screens:[screen],renderTime:{now},naturalEventTime:{now},
    windowPresenter:{_ in},naturalContextProvider:{_,_ in metadata()})
func passive() {
    assert(layer.windows.allSatisfy{$0.ignoresMouseEvents && !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow},
        "Released net must remain hidden, non-focusing and mouse-pass-through in this harness")
}
func insect(_ id:String,_ x:Double = 0.5,_ y:Double = 0.5) -> [String:Any] {
    ["id":id,"x":x,"y":y,"color":"普通褐色","sex":"female"]
}
layer.update(rows:[insect("original")]); layer.onCapture = {captured.append($0)}; layer.show()
func input(_ type:CGEventType,_ point:NSPoint = origin,_ local:Bool = false,_ target:Int64 = 401,_ handler:Int64 = 2) {
    let cg = CGEvent(mouseEventSource:nil,mouseType:type,
        mouseCursorPosition:CGPoint(x:point.x,y:primaryTop-point.y),mouseButton:.left)!
    cg.timestamp=UInt64(now*1_000_000_000)
    cg.setIntegerValueField(.eventTargetUnixProcessID,value:target)
    cg.setIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent,value:handler)
    let event=NSEvent(cgEvent:cg)!
    assert(layer.observeNaturalEvent(event,isLocal:local) === event,"Every event must be returned unchanged")
    passive()
}
func release(_ start:NSPoint = origin,_ end:NSPoint = finish) {
    input(.leftMouseDown,start); input(.leftMouseDragged,end); input(.leftMouseUp,end)
    assert(layer.isWeaving && layer.captureIsNatural,"Full Finder desktop proof must release a natural net")
}
func complete() {now += 5; layer.refresh(); now += 1; layer.refresh(); passive()}
switch CommandLine.arguments[1] {
case "ordinary_clicks":
    for type in [CGEventType.leftMouseDown,.otherMouseDown] {
        for local in [false,true] {
            release(); input(type,finish,local,0,0)
            assert(layer.isWeaving,"A later ordinary click belongs to its app and must not cancel the validated released net")
            input(.leftMouseDragged,finish,local,0,0); input(.leftMouseUp,finish,local,0,0)
            complete()
        }
    }
    assert(captured == [["original"],["original"],["original"],["original"]],
        "Each locked net must finish exactly once while subsequent app input remains unrelated")
case "later_application_cover":
    for pinned in [false,true] {
        rows=[icons,dock]; layer.setLevel(aboveApplications:pinned); release()
        rows.append(row(30,999,0,NSRect(x:-650,y:150,width:300,height:300)))
        input(.leftMouseDown,finish,false,999,30); complete()
    }
    assert(captured == [["original"],["original"]],
        "A later application covering the released rectangle cannot convert a valid past gesture into an invalid new one")
case "freeze_release_ids":
    release()
    layer.update(rows:[insect("original"),insect("newly-entered")]); complete()
    assert(captured == [["original"]],"The released net must exclude every ID not inside its valid rectangle at release")
case "removed_original":
    release()
    layer.update(rows:[insect("replacement")]); complete()
    assert(captured == [[]],"A removed release-time insect cannot be replaced by a later ID at the same location")
case "original_leaves":
    let center=layer.positions[0].point
    let start=NSPoint(x:center.x-5,y:center.y-5), end=NSPoint(x:center.x+5,y:center.y+5)
    release(start,end)
    for step in 1...30 {now = 10+Double(step)*0.03; layer.refresh()}
    let current=layer.positions[0].point
    assert(current.x < start.x || current.x > end.x || current.y < start.y || current.y > end.y,
        "Fixture must independently establish that the original fly left the selected rectangle before completion")
    complete()
    assert(captured == [[]],"Locking release IDs cannot catch an original insect that has left the locked rectangle")
case "explicit_cancellation":
    for kind in 0..<8 {
        layer.setNaturalCaptureEnabled(true); layer.show(); release()
        switch kind {
        case 0: input(.rightMouseDown)
        case 1: input(.rightMouseDown,origin,true)
        case 2:
            let escape = NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:now,
                windowNumber:0,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",
                isARepeat:false,keyCode:53)!
            assert(layer.observeNaturalEvent(escape,isLocal:true) === escape)
        case 3: layer.setNaturalCaptureEnabled(false)
        case 4: layer.hide()
        case 5: layer.updateScreens([screen])
        case 6: layer.cancelForWorkspaceChange()
        default: layer.cancelCapture()
        }
        complete()
        assert(captured.isEmpty && !layer.isWeaving,"Explicit cancellation must still discard the locked net")
    }
case "completion_identity":
    for kind in 0..<4 {
        reliable=true; rows=[icons,dock]; release()
        switch kind {
        case 0: reliable=false
        case 1: rows=[dock]
        case 2: rows=[icons,row(26,402,dockLevel,screen.frame)]
        default: rows=[icons,dock,row(26,402,dockLevel,screen.frame)]
        }
        complete()
        assert(captured.isEmpty && !layer.isWeaving,
            "Unknown geometry, lost desktop identity or changed/new fullscreen Dock evidence must still fail closed")
    }
case "unreleased_rejection":
    for kind in 0..<3 {
        rows=[icons,dock]; input(.leftMouseDown)
        if kind == 0 {rows.append(row(30,999,0,NSRect(x:-650,y:150,width:300,height:300)))}
        input(.leftMouseDragged,finish,false,kind == 1 ? 0:401,kind == 1 ? 0:2)
        input(.leftMouseUp,finish,false,kind == 2 ? 0:401,kind == 2 ? 0:2)
        complete()
        assert(captured.isEmpty && !layer.isWeaving,"Release locking cannot rescue an invalid original desktop chain")
    }
default: fatalError("Unknown scenario")
}
layer.close()
print("PASS \(CommandLine.arguments[1]): real adapter; synthetic event objects; no posting, visible windows or saves")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class ReleasedDesktopCapture169Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="tianmu-169-released-")
        cls.addClassCleanup(cls.tmp.cleanup)
        folder = Path(cls.tmp.name)
        main = folder / "main.swift"
        main.write_text(with_desktop_motion_fixture(HARNESS))
        cls.binary = folder / "check"
        cls.build = subprocess.run(["swiftc", "-framework", "AppKit", *(str(ROOT / "native/v1" / x) for x in
            ["WindowPlacement.swift", "InsectArtwork.swift", "DesktopInsects.swift"]), str(main), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=60)

    def scenario(self, name):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS {name}:", result.stdout)
        print(result.stdout.strip())

    def test_later_left_and_middle_clicks_preserve_locked_net_without_intercepting_input(self): self.scenario("ordinary_clicks")
    def test_later_application_cover_preserves_verified_release_in_both_window_levels(self): self.scenario("later_application_cover")
    def test_release_time_id_snapshot_excludes_later_entrants(self): self.scenario("freeze_release_ids")
    def test_removed_release_id_cannot_be_replaced_at_same_location(self): self.scenario("removed_original")
    def test_original_insect_that_leaves_locked_rectangle_is_not_captured(self): self.scenario("original_leaves")
    def test_right_click_escape_disable_hide_screen_and_workspace_cancellation_remain(self): self.scenario("explicit_cancellation")
    def test_missing_or_changed_desktop_identity_still_cancels_at_completion(self): self.scenario("completion_identity")
    def test_release_policy_cannot_rescue_unverified_or_occluded_original_gesture(self): self.scenario("unreleased_rejection")


if __name__ == "__main__": unittest.main()
