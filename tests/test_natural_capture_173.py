"""173 natural selection uses the default passive presentation, with no shown UI."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
var now: TimeInterval = 10
let screen = DesktopInsectScreen(id:"left",frame:NSRect(x:-1000,y:-100,width:1000,height:800))
let primaryTop = NSScreen.screens.first!.frame.maxY
let iconLevel = Int(CGWindowLevelForKey(.desktopIconWindow))
let dockLevel = Int(CGWindowLevelForKey(.dockWindow))
let origin = NSPoint(x:-600,y:200), finish = NSPoint(x:-400,y:400)
func row(_ number:Int,_ owner:Int,_ level:Int,_ frame:NSRect) -> [String:Any] {
    [kCGWindowNumber as String:number,kCGWindowOwnerPID as String:owner,kCGWindowLayer as String:level,
     kCGWindowAlpha as String:1,kCGWindowBounds as String:["X":frame.minX,"Y":primaryTop-frame.maxY,
     "Width":frame.width,"Height":frame.height]]
}
var rows = [row(2,401,iconLevel,screen.frame),row(25,402,dockLevel,screen.frame)]
var count = 7
func metadata() -> DesktopNaturalCaptureContext {
    DesktopNaturalCaptureContext.fromWindowInfo(rows,screenID:"left",visibleFrame:screen.frame,
        primaryTop:primaryTop,excludingWindowNumbers:[],dragPasteboardChangeCount:count,
        applicationIdentifier:{$0 == 401 ? "com.apple.finder" : $0 == 402 ? "com.apple.dock" : nil})
}
var presented:[NSWindow] = []
let layer = DesktopInsects(motionModuleURL: URL(fileURLWithPath:CommandLine.arguments[2]),
    screens:[screen], renderTime:{now},naturalEventTime:{now},
    windowPresenter:{presented.append($0)},naturalContextProvider:{_,_ in metadata()})
var caught:[[String]] = []
layer.onCapture = {caught.append($0)}
layer.update(rows:(1...4).map{["id":"fly-\($0)","x":0.5,"y":0.5,"color":"普通褐色","sex":"female"]})
layer.show()
for _ in 0..<65 { now += 0.05; layer.refresh() }
let visible = Set(layer.positions.filter{$0.opacity > 0.05}.map{$0.id})
assert(visible == ["fly-1","fly-2","fly-3"],"Real default presentation must expose three of the four real insects")
presented=[]
func input(_ type:CGEventType,_ point:NSPoint = origin,_ target:Int64 = 401,_ handler:Int64 = 2) {
    let cg = CGEvent(mouseEventSource:nil,mouseType:type,
        mouseCursorPosition:CGPoint(x:point.x,y:primaryTop-point.y),mouseButton:.left)!
    cg.timestamp=UInt64(now*1_000_000_000)
    cg.setIntegerValueField(.eventTargetUnixProcessID,value:target)
    cg.setIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent,value:handler)
    let event=NSEvent(cgEvent:cg)!
    assert(layer.observeNaturalEvent(event) === event)
    assert((layer.windows + layer.spriteWindows).allSatisfy{$0.ignoresMouseEvents && !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow})
}
func release(_ dragged:Bool = true) {
    input(.leftMouseDown); if dragged {input(.leftMouseDragged,finish)}; input(.leftMouseUp,finish)
    assert(layer.isWeaving && layer.captureIsNatural && !layer.isCapturing)
}
func finishNet() {now += 5; layer.refresh(); now += 1; layer.refresh()}
// NSEvent(cgEvent:) does not populate the associated NSWindow number used by
// real global callbacks. Keep this OS input-boundary double separate from the
// real metadata parser, adapter, state machine, drawing and capture callbacks.
final class ObservedGlobalMouseEvent: NSEvent {
    let backing: CGEvent
    let kind: NSEvent.EventType
    let associatedWindow: Int
    let recordedTimestamp: TimeInterval
    init(_ backing: CGEvent, kind: NSEvent.EventType, window: Int, time: TimeInterval) {
        self.backing=backing; self.kind=kind; associatedWindow=window; recordedTimestamp=time
        super.init()
    }
    required init?(coder: NSCoder) { nil }
    override var cgEvent: CGEvent? { backing }
    override var type: NSEvent.EventType { kind }
    override var windowNumber: Int { associatedWindow }
    override var timestamp: TimeInterval { recordedTimestamp }
    override var modifierFlags: NSEvent.ModifierFlags { [] }
    override var clickCount: Int { 1 }
}
func observerCopy(_ type:CGEventType,_ point:NSPoint = origin,_ handler:Int64 = 2,_ target:Int64? = nil) {
    let cg = CGEvent(mouseEventSource:nil,mouseType:type,
        mouseCursorPosition:CGPoint(x:point.x,y:primaryTop-point.y),mouseButton:.left)!
    cg.timestamp=UInt64(now*1_000_000_000)
    cg.setIntegerValueField(.eventTargetUnixProcessID,value:target ?? Int64(ProcessInfo.processInfo.processIdentifier))
    cg.setIntegerValueField(.mouseEventWindowUnderMousePointer,value:handler)
    cg.setIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent,value:handler)
    let kind: NSEvent.EventType = type == .leftMouseDown ? .leftMouseDown : type == .leftMouseUp ? .leftMouseUp : .leftMouseDragged
    let event=ObservedGlobalMouseEvent(cg,kind:kind,window:Int(handler),time:now)
    assert(layer.observeNaturalEvent(event) === event)
    assert((layer.windows + layer.spriteWindows).allSatisfy{$0.ignoresMouseEvents && !$0.isVisible})
}
func pixels(_ label:String) -> Int {
    let view = layer.windows[0].contentView!
    let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    var opaque = 0
    for y in 0..<bitmap.pixelsHigh { for x in 0..<bitmap.pixelsWide {
        if let color = bitmap.colorAt(x:x,y:y), color.alphaComponent > 0.05 { opaque += 1 }
    } }
    if CommandLine.arguments.count > 3 {
        let folder = URL(fileURLWithPath:CommandLine.arguments[3])
        try! FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        try! bitmap.representation(using:.png,properties:[:])!.write(to:folder.appendingPathComponent(label + ".png"))
    }
    return opaque
}
switch CommandLine.arguments[1] {
case "native_selection_only":
    input(.leftMouseDown); input(.leftMouseDragged,finish)
    assert(layer.hasNaturalGesture && layer.isCapturing,"Finder selection must be observed without arming a tool")
    assert(!layer.captureOverlayPresented && presented.isEmpty,
        "A natural drag must leave Finder's own selection visible without drawing a second red frame or opening the net canvas")
    input(.leftMouseUp,finish)
    assert(layer.isWeaving && layer.captureOverlayPresented && presented.count == 1,
        "The passive net canvas must first appear at the proven mouse-up")
    finishNet()
    assert(caught.count == 1 && Set(caught[0]) == visible && !layer.captureOverlayPresented)
case "pinned_insects_passive_net":
    layer.setLevel(aboveApplications:true); release()
    assert(layer.spriteWindows.allSatisfy{$0.level == .floating},"The insect display option remains effective")
    assert(layer.windows.allSatisfy{$0.level.rawValue < NSWindow.Level.normal.rawValue},
        "A natural net must remain behind ordinary applications even when the user pins insects on top")
    finishNet(); assert(caught.count == 1 && Set(caught[0]) == visible)
case "fast_visibility_and_reset":
    release(false); finishNet()
    assert(caught.count == 1 && Set(caught[0]) == visible,
        "A fast down/up must catch exactly the IDs that the default presentation really exposed")
    assert(!layer.captureOverlayPresented && layer.windows.count == 1)
    release(); layer.cancelCapture(); finishNet()
    assert(caught.count == 1 && !layer.captureOverlayPresented,"Cancel must clear the released net and prevent a submission")
    release(); finishNet(); assert(caught.count == 2,"The deferred canvas must work again after teardown and cancellation")
case "source_and_obstruction":
    input(.leftMouseDown); input(.leftMouseUp,finish,401,99); finishNet()
    assert(caught.isEmpty && !layer.isWeaving)
    rows.append(row(99,401,0,NSRect(x:-550,y:250,width:30,height:30)))
    input(.leftMouseDown); input(.leftMouseUp,finish); finishNet()
    assert(caught.isEmpty && !layer.isWeaving,"A Finder window crossing the selection remains a blocker")
    rows.removeLast(); input(.leftMouseDown); count += 1; input(.leftMouseUp,finish); finishNet()
    assert(caught.isEmpty && !layer.isWeaving,"A file drag must not become a natural net")
case "diagnostic_reasons":
    var observations:[String] = []
    layer.onNaturalCaptureObservation = { observations.append($0.rawValue) }
    input(.leftMouseDown,origin,0,0)
    assert(observations == ["eventReceived","eventProofMissing"],"A delivered event with missing proof differs from no events")
    observations=[]; input(.leftMouseDown,origin,401,99)
    assert(observations == ["eventReceived","eventTargetNotDesktop"],"A Finder file window is not a Finder desktop proof")
    observations=[]; rows.append(row(99,401,0,NSRect(x:-620,y:180,width:50,height:50)))
    input(.leftMouseDown)
    assert(observations == ["eventReceived","desktopNotExposed"],"Window obstruction must have a separate reason")
    rows.removeLast(); observations=[]; input(.leftMouseDown); count += 1; input(.leftMouseUp,finish)
    assert(observations.contains("fileDrag") && !observations.contains("weavingBegan"))
    observations=[]; release(false); finishNet()
    assert(observations.filter{$0 == "eventReceived"}.count == 2)
    assert(observations.filter{$0 == "gestureBegan"}.count == 1)
    assert(observations.filter{$0 == "weavingBegan"}.count == 1)
    assert(observations.filter{$0 == "captureSubmitted"}.count == 1,
        "Observation must distinguish submission from backend acceptance")
case "weave_pixels":
    input(.leftMouseDown); input(.leftMouseDragged,finish)
    assert(pixels("01-held-selection") == 0,"The default net surface must draw nothing over the held Finder selection")
    input(.leftMouseUp,finish)
    let released = pixels("02-released")
    now += 0.6; layer.refresh()
    let half = pixels("03-weaving")
    now += 0.4; layer.refresh()
    let later = pixels("04-woven")
    assert(released > 0 && half > released && later > half,
        "Actual production drawing must grow the released net across successive refreshes")
    finishNet()
    assert(pixels("05-cleared") == 0 && !layer.captureOverlayPresented && caught.count == 1,
        "After completion/retraction, the deferred surface must have no remaining painted pixels")
case "observer_copy":
    observerCopy(.leftMouseDown)
    assert(layer.hasNaturalGesture,
        "A real global-copy target PID equal to this observer must use its exact Finder desktop window identity")
    observerCopy(.leftMouseDragged,finish); observerCopy(.leftMouseUp,finish)
    assert(layer.isWeaving && layer.captureIsNatural)
    finishNet()
    assert(caught.count == 1 && Set(caught[0]) == visible,
        "The normalized Finder owner proof must survive released-net identity revalidation")
case "observer_copy_rejections":
    rows.append(row(99,401,0,NSRect(x:-950,y:-50,width:50,height:50)))
    for (handler,target):(Int64,Int64?) in [(99,nil),(25,nil),(999,nil),(2,0),(2,402)] {
        observerCopy(.leftMouseDown,origin,handler,target)
        observerCopy(.leftMouseDragged,finish); observerCopy(.leftMouseUp,finish); finishNet()
        assert(caught.isEmpty && !layer.hasNaturalGesture && !layer.isWeaving,
            "Finder file windows, Dock, unknown windows and mismatched non-observer PIDs cannot seed a desktop gesture")
    }
    rows.removeLast()
    observerCopy(.leftMouseDragged,finish); observerCopy(.leftMouseUp,finish); finishNet()
    assert(caught.isEmpty,"An application drag reaching the desktop cannot start without a verified desktop down")
    observerCopy(.leftMouseDown); count += 1; observerCopy(.leftMouseUp,finish); finishNet()
    assert(caught.isEmpty,"PID normalization must not authorize a Finder file drag")
case "observer_window_disagreement":
    let cg = CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,
        mouseCursorPosition:CGPoint(x:origin.x,y:primaryTop-origin.y),mouseButton:.left)!
    cg.setIntegerValueField(.eventTargetUnixProcessID,value:Int64(ProcessInfo.processInfo.processIdentifier))
    cg.setIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent,value:2)
    let event=ObservedGlobalMouseEvent(cg,kind:.leftMouseDown,window:99,time:now)
    assert(layer.observeNaturalEvent(event) === event)
    observerCopy(.leftMouseDragged,finish); observerCopy(.leftMouseUp,finish); finishNet()
    assert(caught.isEmpty && !layer.hasNaturalGesture,
        "A desktop handler field cannot override the event's different associated application window")
default: fatalError("unknown scenario")
}
layer.close()
print("PASS \(CommandLine.arguments[1]): default quiet presentation; exact Finder event proof; no shown window, event posting, worker or save")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class NaturalCapture173Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="tianmu-173-natural-")
        cls.addClassCleanup(cls.tmp.cleanup)
        folder = Path(cls.tmp.name)
        main = folder / "main.swift"
        main.write_text(HARNESS)
        cls.binary = folder / "check"
        cls.build = subprocess.run(["swiftc", "-framework", "AppKit", *(str(ROOT / "native/v1" / x) for x in
            ["WindowPlacement.swift", "InsectArtwork.swift", "DesktopInsects.swift"]), str(main), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=90)

    def scenario(self, name):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        result = subprocess.run([str(self.binary), name, str(ROOT / "third_party/fly-paradise/desktop-motion.js")],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS {name}:", result.stdout)
        print(result.stdout.strip())

    def test_finder_owns_selection_until_release_then_net_appears(self): self.scenario("native_selection_only")
    def test_pinning_insects_never_raises_natural_net_over_work_windows(self): self.scenario("pinned_insects_passive_net")
    def test_fast_release_submits_only_visible_ids_and_canvas_reopens_after_cancel(self): self.scenario("fast_visibility_and_reset")
    def test_event_origin_finder_windows_and_file_drags_remain_vetoes(self): self.scenario("source_and_obstruction")
    def test_optional_diagnostics_distinguish_delivery_proof_obstruction_and_weaving(self): self.scenario("diagnostic_reasons")
    def test_real_net_drawing_grows_only_after_release_and_clears_after_retraction(self): self.scenario("weave_pixels")
    def test_global_copy_observer_pid_uses_exact_finder_window_and_revalidates_release(self): self.scenario("observer_copy")
    def test_observer_pid_never_authorizes_other_windows_or_application_drags(self): self.scenario("observer_copy_rejections")
    def test_conflicting_event_window_number_cannot_be_replaced_by_desktop_handler(self): self.scenario("observer_window_disagreement")


if __name__ == "__main__": unittest.main()
