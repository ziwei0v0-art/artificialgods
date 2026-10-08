"""Passive host safety gates and async event timing; injected desktop metadata only."""
import platform
import shutil
import unittest
import test_capture_host_sequence as fixture

HARNESS=fixture.BASE_HARNESS+r'''
switch CommandLine.arguments[1] {
case "local_identity":
    require(host.localObservedEvents.contains(.otherMouseDown),"The installed local monitor must subscribe to middle/extra mouse buttons")
    for type:NSEvent.EventType in [.leftMouseDown,.leftMouseDragged,.leftMouseUp,.rightMouseDown,.otherMouseDown] {
        let input=event(type,NSPoint(x:30,y:30),windowNumber:host.overlay.windowNumber)
        require(host.handleLocalEvent(input) === input,"Local own-UI mouse events must remain the same original object")
    }
    complete(); passive()
    require(captured.isEmpty && !layer.hasNaturalGesture,"Own buttons and scene mouse events must never seed a desktop net")
    drag()
    let localDown=event(.leftMouseDown,NSPoint(x:30,y:30),windowNumber:host.panel.windowNumber)
    require(host.handleLocalEvent(localDown) === localDown,"Own UI interaction must cancel observation without swallowing input")
    global(.leftMouseUp,finish); complete(); passive()
    require(captured.isEmpty && !layer.hasNaturalGesture,"A local click cancels the pending desktop gesture rather than carrying it into our UI")
    drag(); escape(); global(.leftMouseUp,finish); complete()
    require(captured.isEmpty,"Local Esc must reach cancellation and leave its late up inert")
    release()
    let middleDown=event(.otherMouseDown,NSPoint(x:30,y:30),windowNumber:host.panel.windowNumber)
    require(host.handleLocalEvent(middleDown) === middleDown,"A local middle click must remain the original event")
    complete(); passive()
    require(captured == [["one"]] && !layer.isWeaving,"A middle click on our own panel preserves the locked released net")
    release()
    let rightDown=event(.rightMouseDown,NSPoint(x:30,y:30),windowNumber:host.panel.windowNumber)
    require(host.handleLocalEvent(rightDown) === rightDown,"Explicit right-click cancellation also returns the original event")
    complete(); passive()
    require(captured == [["one"]] && !layer.isWeaving,"A local right click must still cancel the released net")
case "application_and_file_drag":
    let appFrame=NSRect(x:-700,y:200,width:200,height:160)
    for c in [context(blocked:[appFrame]),context(reliable:false),context(desktop:false),context(local:true)] {
        global(.leftMouseDown,origin,c); global(.leftMouseDragged,finish,c); global(.leftMouseUp,finish,c); complete()
        passive(); require(captured.isEmpty && !layer.hasNaturalGesture,"Application overlap/unknown/local geometry cannot authorize a desktop net")
    }
    for changeAtRelease in [false,true] {
        begin(); global(.leftMouseDragged,finish,context(changeAtRelease ? 7:8))
        global(.leftMouseUp,finish,context(8)); complete()
        passive(); require(captured.isEmpty && !layer.isWeaving,"Finder drag pasteboard changes, including release-only detection, must veto the whole net")
    }
    begin(); global(.leftMouseDragged,finish,context(id:"other-display")); global(.leftMouseUp,finish); complete()
    require(captured.isEmpty,"A changed display must reject the gesture instead of guessing a cross-screen region")
    release(); complete(); require(captured == [["one"]],"Rejected application/file gestures must not disable a later ordinary desktop selection")
case "delayed_event_queue":
    let stages:[(NSEvent.EventType,NSPoint)]=[(.leftMouseDown,origin),(.leftMouseDragged,finish),(.leftMouseUp,finish)]
    for offset:TimeInterval in [-0.101,0.001] {
        for rejected in 0..<3 {
            for (index,pair) in stages.enumerated() {
                global(pair.0,pair.1,timestamp:now+(index == rejected ? offset:0))
            }
            global(.leftMouseUp,finish); complete(); passive()
            require(captured.isEmpty && !layer.hasNaturalGesture && !layer.isWeaving,
                "Delayed/future down, drag or up through the host must fail closed; late up cannot resurrect it")
        }
    }
    // A stalled global monitor may deliver the entire sequence after Finder's
    // pasteboard baseline changed. Fresh metadata cannot validate old input.
    for (index,pair) in stages.enumerated() { global(pair.0,pair.1,context(8),timestamp:now-1+Double(index)*0.1) }
    complete(); require(captured.isEmpty,"A queued old batch must never become a capture using a post-drag context")
    release(); complete(); require(captured == [["one"]],"A new fresh selection remains usable after rejected event batches")
case "long_hold_fresh_delivery":
    global(.leftMouseDown,origin,timestamp:now-0.05)
    now += 4; host.updateInsectPointer(origin,buttonsPressed:1); loseFocus()
    global(.leftMouseDragged,finish,timestamp:now-0.05)
    now += 4; host.updateInsectPointer(finish,buttonsPressed:1)
    require(layer.hasNaturalGesture && layer.isCapturing,"Holding a valid desktop rectangle for several seconds is not a stale event")
    host.updateInsectPointer(finish,buttonsPressed:0)
    require(layer.hasNaturalGesture,"A zero-button poll cannot run ahead of the asynchronous mouse-up")
    global(.leftMouseUp,finish,timestamp:now-0.099); complete(); passive()
    require(captured == [["one"]],"Only delivery age, not total human gesture duration, may reject an event")
case "missing_release":
    drag(); now += 60; layer.refresh(); host.updateInsectPointer(finish,buttonsPressed:0)
    require(captured.isEmpty && !layer.isWeaving,"An observed down/drag without up must never autonomously submit a net")
    escape(local:false); complete(); passive()
    require(!layer.hasNaturalGesture && captured.isEmpty,"Explicit Esc must clear an unfinished observed selection")
    drag(); global(.leftMouseDown,origin); global(.leftMouseUp,finish); complete(); passive()
    require(captured == [["one"]],"A next valid mouse-down replaces abandoned observation; only its release captures")
    global(.leftMouseUp,finish); layer.refresh(); require(captured.count == 1,"A trailing old up cannot replay the replacement selection")
case "current_visible_ids":
    release()
    layer.update(rows:[["id":"replacement","x":0.5,"y":0.5,"color":"普通褐色"]])
    complete(); passive()
    require(captured == [[]],"A removed release-time ID cannot be replaced by a later ID at the same location")
    release(); completionBlocked=[work]; complete()
    require(captured == [[],["replacement"]],"An application covering a locked selection later must not rewrite release intent")
    completionBlocked=[]; release(); completionReliable=false; complete()
    require(captured == [[],["replacement"]],"Unknown completion geometry cancels without a capture submission")
    completionReliable=true; release(); complete(); passive()
    require(captured == [[],["replacement"],["replacement"]],"A new valid release still submits once after context recovers")
case "workspace_notifications":
    begin(); host.desktopApplicationActivated()
    require(layer.hasNaturalGesture,"Initial Finder activation must preserve an unreleased desktop press")
    global(.leftMouseDragged,finish); global(.leftMouseUp,finish)
    require(layer.isWeaving,"Fresh release must start natural weaving")
    host.desktopApplicationActivated(); complete(); passive()
    require(captured == [["one"]] && !layer.isWeaving,"A later application activation preserves the locked released net")
    begin(); host.desktopSpaceChanged()
    global(.leftMouseDragged,finish); global(.leftMouseUp,finish); complete()
    require(captured == [["one"]] && !layer.hasNaturalGesture,"A space change clears a pending gesture before its late release")
    release(); host.desktopSpaceChanged(); complete(); passive()
    require(captured == [["one"]],"A space change also cancels a released natural net")
    release(); complete()
    require(captured == [["one"],["one"]],"Workspace cancellation must leave the next ordinary desktop selection usable")
default: fatalError("Unknown passive safety scenario")
}
finishedAudit()
'''


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'),'macOS + Swift required')
class NaturalCaptureHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixture.prepare_harness(cls,'tianmu-natural-host-passive-',HARNESS)
    def test_local_mouse_and_escape_are_returned_without_seeding_capture(self): fixture.run_scenario(self,'local_identity')
    def test_application_geometry_and_file_drag_vetoes_reach_actual_host(self): fixture.run_scenario(self,'application_and_file_drag')
    def test_async_stale_and_future_events_cannot_capture_or_resurrect(self): fixture.run_scenario(self,'delayed_event_queue')
    def test_human_hold_duration_and_async_release_order_do_not_cancel_fresh_events(self): fixture.run_scenario(self,'long_hold_fresh_delivery')
    def test_missing_up_never_commits_and_explicit_cancel_or_next_down_recovers(self): fixture.run_scenario(self,'missing_release')
    def test_completed_net_submits_release_ids_still_inside_locked_rectangle(self): fixture.run_scenario(self,'current_visible_ids')
    def test_app_activation_preserves_release_but_space_changes_cancel(self): fixture.run_scenario(self,'workspace_notifications')


if __name__ == '__main__': unittest.main()
