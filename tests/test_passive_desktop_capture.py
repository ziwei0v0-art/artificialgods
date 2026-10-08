"""166 passive desktop input. Synthetic metadata/events; unshown windows only."""
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
let screen = DesktopInsectScreen(id:"test",frame:NSRect(x:-1000,y:-100,width:1000,height:800))
var now:TimeInterval = 10
var caught:[[String]] = []
var focuses = 0
var completionBlocked:[NSRect] = []
var completionReliable = true
let layer = DesktopInsects(screens:[screen],renderTime:{now},naturalEventTime:{now},windowPresenter:{_ in},
    naturalContextProvider:{_,_ in context(blocked:completionBlocked,reliable:completionReliable)})
layer.onCapture = { caught.append($0) }
layer.onNaturalCaptureBegin = { focuses += 1 }
layer.update(rows:[["id":"fly","x":0.5,"y":0.5,"color":"普通褐色"]]); layer.show()
let origin = NSPoint(x:-600,y:200), finish = NSPoint(x:-400,y:400)
func context(_ count:Int = 7, blocked:[NSRect] = [], reliable:Bool = true, local:Bool = false,
             desktop:Bool = true, id:String = "test") -> DesktopNaturalCaptureContext {
    DesktopNaturalCaptureContext(screenID:id,visibleFrame:screen.frame,
        desktopFrames:desktop ? [screen.frame] : [], blockedFrames:blocked,
        isReliable:reliable, dragPasteboardChangeCount:count, sourceIsLocal:local)
}
func feed(_ type:NSEvent.EventType,_ point:NSPoint,_ c:DesktopNaturalCaptureContext? = nil) {
    layer.observeNaturalMouse(type,at:point,context:c ?? context())
    assert(layer.windows.allSatisfy{$0.ignoresMouseEvents && !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow},
           "A native mouse event must never enable a screen-sized input shield or focus")
}
func release(_ c:DesktopNaturalCaptureContext? = nil) {
    feed(.leftMouseDown,origin,c); feed(.leftMouseDragged,finish,c); feed(.leftMouseUp,finish,c)
}
func complete() { now += 5; layer.refresh(); now += 1; layer.refresh() }
let stages:[(NSEvent.EventType,NSPoint)] = [(.leftMouseDown,origin),(.leftMouseDragged,finish),(.leftMouseUp,finish)]
func event(_ type:NSEvent.EventType,_ point:NSPoint,_ timestamp:TimeInterval? = nil) {
    let input = NSEvent.mouseEvent(with:type,location:point,modifierFlags:[],timestamp:timestamp ?? now,
        windowNumber:0,context:nil,eventNumber:1,clickCount:1,pressure:1)!
    assert(layer.observeNaturalEvent(input,context:context(8)) === input,
           "Even rejected input must return the original event, without replay or replacement")
    assert(layer.windows.allSatisfy{$0.ignoresMouseEvents && !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow})
}
switch CommandLine.arguments[1] {
case "delayed_batch":
    // The global monitor is asynchronous. Finder has already changed the drag
    // pasteboard before this app gets the entire queued mouse event sequence.
    for (index, pair) in [(NSEvent.EventType.leftMouseDown,origin),(.leftMouseDragged,finish),(.leftMouseUp,finish)].enumerated() {
        let event = NSEvent.mouseEvent(with:pair.0,location:pair.1,modifierFlags:[],timestamp:now-1+Double(index)*0.1,
            windowNumber:0,context:nil,eventNumber:index+1,clickCount:1,pressure:1)!
        assert(layer.observeNaturalEvent(event,context:context(8)) === event)
    }
    complete()
    assert(caught.isEmpty && !layer.isCapturing && !layer.isWeaving,
           "A delayed event batch with a post-drag pasteboard baseline must never capture")
case "stale_each_stage", "future_each_stage":
    let offset:TimeInterval = CommandLine.arguments[1] == "stale_each_stage" ? -0.101 : 0.001
    for rejectedStage in 0..<stages.count {
        for (index,pair) in stages.enumerated() {
            event(pair.0,pair.1,now + (index == rejectedStage ? offset : 0))
        }
        event(.leftMouseUp,finish)
        complete()
        assert(caught.isEmpty && !layer.isCapturing && !layer.isWeaving,
               "A stale/future down, drag or up must cancel; a late up cannot resurrect it")
    }
    for pair in stages { event(pair.0,pair.1) }
    complete()
    assert(caught == [["fly"]],"The next fresh gesture must work after a rejected sequence")
case "nonfinite_clock":
    for invalid in [Double.nan,Double.infinity,-Double.infinity] {
        for rejectedStage in 0..<stages.count {
            for (index,pair) in stages.enumerated() {
                let timestamp = now
                if index == rejectedStage { now = invalid }
                event(pair.0,pair.1,timestamp)
                now = timestamp
            }
            complete()
            assert(caught.isEmpty && !layer.isCapturing && !layer.isWeaving,
                   "An invalid clock cannot validate any stage of the gesture")
        }
    }
case "fresh_event_age":
    for age:TimeInterval in [0,0.05,0.099] {
        for pair in stages {
            // Delivery age matters; the player may hold a selection for seconds.
            now += 2
            event(pair.0,pair.1,now-age)
        }
        complete()
    }
    assert(caught == [["fly"],["fly"],["fly"]],
           "Fresh events, including a long held gesture, must complete exactly once")
case "stale_after_release":
    for pair in stages { event(pair.0,pair.1) }
    assert(layer.isWeaving)
    for pair in stages { event(pair.0,pair.1,now-1) }
    complete()
    assert(caught == [["fly"]] && !layer.isWeaving,
           "Later stale app input cannot replace or cancel the already validated released gesture")
case "explicit_stale":
    layer.setNaturalCaptureEnabled(false)
    for rejectedStage in 0..<stages.count {
        layer.beginCapture()
        for (index,pair) in stages.enumerated() {
            event(pair.0,pair.1,now - (index == rejectedStage ? 1 : 0))
        }
        event(.leftMouseUp,finish)
        complete()
        assert(caught.isEmpty && !layer.isWeaving && !layer.hasNaturalGesture
               && (!layer.isCapturing || layer.captureState == .armed),
               "Explicit arming cannot authorize a stale desktop event sequence")
    }
    layer.beginCapture()
    for pair in stages { event(pair.0,pair.1) }
    complete()
    assert(caught == [["fly"]] && !layer.captureIsNatural)
case "continuous":
    assert(layer.naturalCaptureEnabled)
    layer.updatePointer(layer.positions[0].point,buttonsPressed:0)
    assert(!layer.isNaturalHandleVisible && layer.captureHandleWindow == nil,
           "Natural default cannot create a clickable text button")
    feed(.leftMouseDown,origin)
    assert(!layer.isCapturing && !layer.isWeaving,"A click alone has no game effect")
    feed(.leftMouseDragged,finish)
    assert(layer.isCapturing && layer.captureIsNatural && layer.captureState == .dragging)
    assert(layer.windows.allSatisfy{$0.level.rawValue < NSWindow.Level.normal.rawValue})
    feed(.leftMouseUp,finish)
    assert(layer.isWeaving && caught.isEmpty && !layer.isCapturing)
    feed(.leftMouseUp,finish); complete()
    assert(caught == [["fly"]] && !layer.isWeaving && focuses == 0)
    release(); complete()
    assert(caught == [["fly"],["fly"]],"Two successive normal desktop selections must each work without rearming")
case "file_drag":
    feed(.leftMouseDown,origin); feed(.leftMouseDragged,finish,context(8))
    feed(.leftMouseUp,finish,context(8)); complete()
    assert(caught.isEmpty && !layer.isWeaving && !layer.isCapturing,
           "A changed drag pasteboard counter denotes a system drag, never a net")
    feed(.leftMouseDown,origin); feed(.leftMouseDragged,finish)
    feed(.leftMouseUp,finish,context(9)); complete()
    assert(caught.isEmpty,"A drag recognized only at mouse-up must also cancel")
case "completion_visibility":
    release()
    completionBlocked = [NSRect(x:-600,y:200,width:200,height:200)]
    complete()
    assert(caught == [["fly"]],"A later app window cannot rewrite the validated release-time selection")
    completionBlocked = []; release(); completionReliable = false; complete()
    assert(caught == [["fly"]],"Unknown completion geometry must cancel without committing")
    completionReliable = true; release(); complete()
    assert(caught == [["fly"],["fly"]],"The next valid release still completes after geometry recovers")
case "applications":
    let textWindow = NSRect(x:-650,y:150,width:300,height:300)
    release(context(blocked:[textWindow])); complete()
    assert(caught.isEmpty && !layer.isWeaving,"Text selection inside an application must be excluded")
    feed(.leftMouseDown,origin); feed(.leftMouseDragged,finish,context(blocked:[NSRect(x:-420,y:380,width:90,height:90)]))
    feed(.leftMouseUp,finish); complete()
    assert(caught.isEmpty,"A path entering a window must not recover on mouse-up")
    feed(.leftMouseDown,origin); feed(.leftMouseDragged,finish,context(blocked:[NSRect(x:-510,y:290,width:20,height:20)]))
    feed(.leftMouseUp,finish); complete()
    assert(caught.isEmpty,"A net rectangle crossing a window must fail even if both endpoints are desktop")
    release(context(local:true)); complete()
    assert(caught.isEmpty,"Our own application UI must never create a passive desktop net")
case "unknown":
    for c in [context(reliable:false),context(desktop:false)] { release(c); complete() }
    feed(.leftMouseDown,origin); feed(.leftMouseUp,finish,context(id:"another")); complete()
    assert(caught.isEmpty,"Missing metadata, missing desktop or changed display must fail closed")
    feed(.leftMouseDown,NSPoint(x:Double.nan,y:200)); feed(.leftMouseUp,finish); complete()
    assert(caught.isEmpty)
case "cancel":
    for choice in 0..<5 {
        layer.setNaturalCaptureEnabled(true); layer.show()
        feed(.leftMouseDown,origin); feed(.leftMouseDragged,finish)
        switch choice {
        case 0: feed(.rightMouseDown,finish)
        case 1: layer.setNaturalCaptureEnabled(false)
        case 2: layer.hide()
        case 3: layer.updateScreens([screen])
        default: layer.cancelCapture()
        }
        feed(.leftMouseUp,finish); complete()
        assert(caught.isEmpty && !layer.isWeaving,"Cancelled gestures cannot be resurrected by a late up")
    }
    layer.setNaturalCaptureEnabled(false); release(); complete()
    assert(caught.isEmpty)
case "fast_and_zero":
    feed(.leftMouseDown,origin); feed(.leftMouseUp,finish); complete()
    assert(caught == [["fly"]],"Coalesced/quick movement with only a displaced up still completes once")
    feed(.leftMouseDown,origin); feed(.leftMouseUp,origin); complete()
    feed(.leftMouseDown,origin); feed(.leftMouseUp,NSPoint(x:-400,y:200)); complete()
    assert(caught.count == 1,"Clicks and zero area selections must not capture")
case "explicit_observation":
    layer.setNaturalCaptureEnabled(false); layer.beginCapture()
    assert(layer.windows.allSatisfy{$0.ignoresMouseEvents})
    NotificationCenter.default.post(name:NSApplication.didResignActiveNotification,object:app)
    assert(layer.captureState == .armed,"Clicking the desktop must not disarm the passive explicit fallback")
    release(); complete()
    assert(caught == [["fly"]] && !layer.captureIsNatural)
case "event_identity":
    for type:NSEvent.EventType in [.leftMouseDown,.leftMouseDragged,.leftMouseUp,.rightMouseDown] {
        let event = NSEvent.mouseEvent(with:type,location:origin,modifierFlags:[],timestamp:now,
            windowNumber:0,context:nil,eventNumber:1,clickCount:1,pressure:1)!
        let returned = layer.observeNaturalEvent(event,context:context(local:true))
        assert(returned === event,"Local monitor adapter must return the original NSEvent object")
    }
    let escape = NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:now,
        windowNumber:0,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!
    feed(.leftMouseDown,origin); feed(.leftMouseDragged,finish)
    assert(layer.observeNaturalEvent(escape,context:context(local:true)) === escape)
    feed(.leftMouseUp,finish); complete()
    assert(caught.isEmpty,"Escape may cancel observation without consuming the user's key")
case "dock_background_regression", "dock_event_chain", "dock_unsafe_targets", "dock_other_windows",
     "dock_completion_fingerprint", "dock_completion_occlusion", "dock_new_input", "dock_workspace", "dock_pinned_completion":
    let finderPID:pid_t = 401, dockPID:pid_t = 402
    let primaryTop = NSScreen.screens.first!.frame.maxY
    let iconLevel = Int(CGWindowLevelForKey(.desktopIconWindow)), dockLevel = Int(CGWindowLevelForKey(.dockWindow))
    func windowRow(_ id:Int,_ owner:pid_t,_ level:Int,_ frame:NSRect,_ alpha:Double = 1) -> [String:Any] {
        [kCGWindowNumber as String:id,kCGWindowOwnerPID as String:owner,kCGWindowLayer as String:level,
         kCGWindowAlpha as String:alpha,kCGWindowBounds as String:["X":frame.minX,"Y":primaryTop-frame.maxY,"Width":frame.width,"Height":frame.height]]
    }
    let icons = windowRow(2,finderPID,iconLevel,screen.frame)
    let backdrop = windowRow(25,dockPID,dockLevel,screen.frame)
    let baseRows = [icons,backdrop]
    var currentRows = baseRows
    func metadata() -> DesktopNaturalCaptureContext {
        DesktopNaturalCaptureContext.fromWindowInfo(currentRows,screenID:"test",visibleFrame:screen.frame,
            primaryTop:primaryTop,excludingWindowNumbers:[],dragPasteboardChangeCount:7,
            applicationIdentifier:{ $0 == 401 ? "com.apple.finder" : $0 == 402 ? "com.apple.dock" : nil })
    }
    assert(!metadata().permits(NSRect(origin:origin,size:.zero)),"Metadata alone must still reject the whole-screen Dock")
    let check = DesktopInsects(screens:[screen],renderTime:{now},naturalEventTime:{now},windowPresenter:{_ in},
        naturalContextProvider:{_,_ in metadata()})
    check.update(rows:[["id":"fly","x":0.5,"y":0.5,"color":"普通褐色"]]); check.show()
    var results:[[String]] = []
    check.onCapture = { results.append($0) }
    func input(_ type:CGEventType,_ point:NSPoint,_ target:Int64 = 401,_ handler:Int64 = 2,_ local:Bool = false) {
        let cg = CGEvent(mouseEventSource:nil,mouseType:type,
            mouseCursorPosition:CGPoint(x:point.x,y:primaryTop-point.y),mouseButton:.left)!
        cg.timestamp = UInt64(now*1_000_000_000)
        cg.setIntegerValueField(.eventTargetUnixProcessID,value:target)
        cg.setIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent,value:handler)
        let event = NSEvent(cgEvent:cg)!
        assert(check.observeNaturalEvent(event,isLocal:local) === event,"All observed input must return unchanged")
        assert(check.windows.allSatisfy{$0.ignoresMouseEvents && !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow})
    }
    func releaseProven() {
        input(.leftMouseDown,origin); input(.leftMouseDragged,finish); input(.leftMouseUp,finish)
        assert(check.isWeaving,"A proven full gesture must enter weaving")
    }
    func finishProven() { now += 5; check.refresh(); now += 1; check.refresh() }
    switch CommandLine.arguments[1] {
    case "dock_background_regression":
        input(.leftMouseDown,origin)
        assert(check.hasNaturalGesture,"A fresh event proven to hit the Finder desktop must begin despite the non-receiving full-screen Dock backdrop")
    case "dock_event_chain":
        releaseProven(); finishProven()
        assert(results == [["fly"]],"The exact release-time Dock fingerprint must remain usable for completion")
        input(.leftMouseDown,origin,0,0); input(.leftMouseUp,finish,0,0); finishProven()
        assert(results == [["fly"]],"A completed net cannot lend its proof to a new unknown gesture")
        currentRows = [backdrop,icons] // WindowServer ordering alone is not a fingerprint change.
        releaseProven(); finishProven()
        assert(results == [["fly"],["fly"]])
    case "dock_unsafe_targets":
        assert(DesktopNaturalEventProof.from(nil) == nil)
        for (target,handler):(Int64,Int64) in [(0,2),(401,0),(402,2),(401,999),(-1,2),(Int64(Int32.max)+1,2)] {
            for badStage in 0..<3 {
                for (stage,pair) in [(CGEventType.leftMouseDown,origin),(.leftMouseDragged,finish),(.leftMouseUp,finish)].enumerated() {
                    input(pair.0,pair.1,stage == badStage ? target : 401,stage == badStage ? handler : 2)
                }
                input(.leftMouseUp,finish); finishProven()
                assert(results.isEmpty && !check.hasNaturalGesture && !check.isWeaving,
                       "Missing or mismatched event PID/window at any stage must fail closed")
            }
        }
    case "dock_other_windows":
        let rectangle = NSRect(x:-650,y:150,width:300,height:300)
        for row in [windowRow(60,finderPID,0,rectangle), windowRow(61,dockPID,dockLevel,rectangle),
                    windowRow(62,999,dockLevel,screen.frame)] {
            currentRows = baseRows+[row]
            input(.leftMouseDown,origin); input(.leftMouseDragged,finish); input(.leftMouseUp,finish); finishProven()
            assert(results.isEmpty && !check.hasNaturalGesture && !check.isWeaving,
                   "Finder file windows, smaller Dock windows and unrelated owners must remain blockers")
        }
        currentRows = baseRows+[windowRow(60,finderPID,0,rectangle)]
        input(.leftMouseDown,origin,401,60); input(.leftMouseUp,finish,401,60); finishProven()
        assert(results.isEmpty,"A Finder file-window handler is not the Finder desktop")
    case "dock_completion_fingerprint":
        let changed = [windowRow(26,dockPID,dockLevel,screen.frame),windowRow(25,999,dockLevel,screen.frame),
            windowRow(25,dockPID,dockLevel+1,screen.frame),windowRow(25,dockPID,dockLevel,screen.frame,0.5),
            windowRow(25,dockPID,dockLevel,screen.frame.offsetBy(dx:1,dy:0))]
        for row in changed {
            currentRows = baseRows; releaseProven(); currentRows = [icons,row]; finishProven()
            assert(results.isEmpty && !check.isWeaving,"Any release-time Dock fingerprint change must withdraw completion")
        }
        currentRows = baseRows; releaseProven(); currentRows = [icons]; finishProven()
        assert(results.isEmpty,"Disappearance of the proven Dock window also invalidates its bounded proof")
    case "dock_completion_occlusion":
        currentRows = baseRows; releaseProven()
        currentRows = baseRows+[windowRow(60,999,0,NSRect(x:-610,y:190,width:30,height:30))]; finishProven()
        assert(results == [["fly"]],"A later app window does not change the locked release intent")
        currentRows = baseRows; releaseProven()
        currentRows = baseRows+[windowRow(26,dockPID,dockLevel,screen.frame)]; finishProven()
        assert(results == [["fly"]] && !check.isWeaving,"New fullscreen Dock evidence must still cancel the released net")
        currentRows = baseRows; releaseProven()
        currentRows = baseRows+[windowRow(60,999,0,NSRect(x:-990,y:-90,width:20,height:20))]
        finishProven()
        assert(results == [["fly"],["fly"]],"Unrelated geometry outside the rectangle also preserves the locked net")
    case "dock_pinned_completion":
        check.setLevel(aboveApplications:true)
        releaseProven(); currentRows = [icons,windowRow(26,dockPID,dockLevel,screen.frame)]; finishProven()
        assert(results.isEmpty && !check.isWeaving,"Pinned presentation must not bypass released Dock fingerprint validation")
        currentRows = baseRows; releaseProven()
        currentRows = baseRows+[windowRow(60,999,0,NSRect(x:-610,y:190,width:30,height:30))]
        finishProven()
        assert(results == [["fly"]],"Pinned presentation uses the same release-time intent as the lower desktop layer")
    case "dock_new_input":
        for type in [CGEventType.leftMouseDown,.rightMouseDown,.otherMouseDown] {
            for local in [false,true] {
                let prior = results.count
                releaseProven(); input(type,origin,401,2,local); finishProven()
                let expected = type == .rightMouseDown ? prior : prior+1
                assert(results.count == expected && !check.isWeaving,
                       "Right-click explicitly cancels; later ordinary left/middle clicks preserve the locked released net")
            }
        }
    default:
        input(.leftMouseDown,origin); check.cancelForWorkspaceChange(); input(.leftMouseUp,finish); finishProven()
        assert(results.isEmpty && !check.hasNaturalGesture)
        releaseProven(); check.cancelForWorkspaceChange(); finishProven()
        assert(results.isEmpty && !check.isWeaving,"Workspace changes cannot preserve a released desktop proof")
    }
    check.close()
case "window_metadata":
    let desktop = Int(CGWindowLevelForKey(.desktopWindow))
    let icons = Int(CGWindowLevelForKey(.desktopIconWindow))
    // Quartz y increases down from primary top; the fixture screen has a negative origin.
    func row(_ id:Int,_ frame:NSRect,_ layer:Int,_ alpha:Double = 1) -> [String:Any] {
        [kCGWindowNumber as String:id,kCGWindowLayer as String:layer,
         kCGWindowAlpha as String:alpha,kCGWindowBounds as String:["X":frame.minX,"Y":frame.minY,"Width":frame.width,"Height":frame.height]]
    }
    let wallpaper = row(1,NSRect(x:-1000,y:300,width:1000,height:800),desktop)
    let finderIcons = row(2,NSRect(x:-1000,y:300,width:1000,height:800),icons)
    let appWindow = row(3,NSRect(x:-600,y:600,width:200,height:200),0)
    let ownLayer = row(4,NSRect(x:-1000,y:300,width:1000,height:800),icons+1)
    let c = DesktopNaturalCaptureContext.fromWindowInfo([wallpaper,finderIcons,appWindow,ownLayer],
        screenID:"test",visibleFrame:screen.frame,primaryTop:1000,excludingWindowNumbers:[4],dragPasteboardChangeCount:7)
    assert(c.isReliable && c.desktopFrames.count == 2 && c.blockedFrames == [NSRect(x:-600,y:200,width:200,height:200)])
    assert(!c.permits(NSRect(x:-590,y:210,width:20,height:20)))
    assert(c.permits(NSRect(x:-900,y:500,width:30,height:30)))
    let malformed = DesktopNaturalCaptureContext.fromWindowInfo([wallpaper,[kCGWindowNumber as String:99]],
        screenID:"test",visibleFrame:screen.frame,primaryTop:1000,excludingWindowNumbers:[],dragPasteboardChangeCount:7)
    assert(!malformed.isReliable && !malformed.permits(NSRect(x:-900,y:500,width:10,height:10)))
default:fatalError("unknown test")
}
assert(focuses == 0)
layer.close()
print("PASS \(CommandLine.arguments[1]): synthetic metadata/events, unshown windows, no saves or input injection")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class PassiveDesktopCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="tianmu-166-passive-")
        cls.addClassCleanup(cls.tmp.cleanup)
        folder = Path(cls.tmp.name)
        harness = folder / "main.swift"
        harness.write_text(with_desktop_motion_fixture(HARNESS))
        cls.binary = folder / "check"
        cls.build = subprocess.run(["swiftc", "-framework", "AppKit", *(str(ROOT / "native/v1" / x) for x in ["WindowPlacement.swift", "InsectArtwork.swift", "DesktopInsects.swift"]), str(harness), "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)

    def scenario(self, name):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS {name}:", result.stdout)
        print(result.stdout.strip())

    def test_proven_finder_desktop_event_passes_nonreceiving_fullscreen_dock(self): self.scenario("dock_background_regression")

    def test_desktop_event_proof_survives_only_its_own_released_net(self): self.scenario("dock_event_chain")
    def test_missing_or_mismatched_pid_and_handler_fail_each_gesture_stage(self): self.scenario("dock_unsafe_targets")
    def test_finder_files_other_dock_windows_and_other_owners_remain_blockers(self): self.scenario("dock_other_windows")
    def test_release_time_dock_fingerprint_change_or_disappearance_cancels(self): self.scenario("dock_completion_fingerprint")
    def test_later_application_geometry_preserves_release_but_new_dock_evidence_cancels(self): self.scenario("dock_completion_occlusion")
    def test_later_ordinary_clicks_preserve_release_while_right_click_cancels(self): self.scenario("dock_new_input")
    def test_pinned_presentation_cannot_bypass_released_desktop_proof(self): self.scenario("dock_pinned_completion")
    def test_workspace_change_cancels_pending_and_released_desktop_proof(self): self.scenario("dock_workspace")

    def test_two_natural_selections_preserve_passthrough_and_do_not_focus(self): self.scenario("continuous")
    def test_system_file_drag_cancels_before_weaving_or_capture(self): self.scenario("file_drag")
    def test_completion_preserves_released_selection_under_apps_but_unknown_geometry_cancels(self): self.scenario("completion_visibility")
    def test_app_selections_window_paths_and_local_events_do_not_weave(self): self.scenario("applications")
    def test_unreliable_metadata_and_display_changes_fail_closed(self): self.scenario("unknown")
    def test_cancel_disable_hide_screen_change_and_late_mouseup(self): self.scenario("cancel")
    def test_fast_release_click_and_zero_area(self): self.scenario("fast_and_zero")
    def test_explicit_fallback_observes_desktop_without_installing_input_shield(self): self.scenario("explicit_observation")
    def test_event_adapter_returns_same_event_even_when_cancelling(self): self.scenario("event_identity")
    def test_window_bounds_use_correct_coordinates_and_only_known_own_layers_are_excluded(self): self.scenario("window_metadata")
    def test_delayed_global_event_batch_cannot_reuse_post_drag_pasteboard_count(self): self.scenario("delayed_batch")
    def test_stale_down_drag_and_up_cancel_without_late_up_resurrection(self): self.scenario("stale_each_stage")
    def test_future_down_drag_and_up_fail_closed(self): self.scenario("future_each_stage")
    def test_nonfinite_clock_at_each_stage_fails_closed(self): self.scenario("nonfinite_clock")
    def test_fresh_delivery_allows_normal_and_long_held_gestures(self): self.scenario("fresh_event_age")
    def test_later_delayed_input_cannot_cancel_or_replace_locked_release(self): self.scenario("stale_after_release")
    def test_explicit_arming_does_not_bypass_event_freshness(self): self.scenario("explicit_stale")

if __name__ == "__main__": unittest.main()
