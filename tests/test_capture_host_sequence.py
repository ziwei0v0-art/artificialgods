"""166 real host/passive-monitor sequences with synthetic events and hidden windows.

No WindowServer event delivery, application activation, production worker, real
save or physical mouse claim is made. Injected metadata describes one desktop.
"""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]
BASE_HARNESS = r'''
let app=NSApplication.shared; app.setActivationPolicy(.prohibited)
let host=ApplicationHost()
let screen=DesktopInsectScreen(id:"audit",frame:NSRect(x:-1200,y:-100,width:1200,height:800))
let work=NSRect(x:-1200,y:-70,width:1200,height:740)
let origin=NSPoint(x:-1050,y:70), finish=NSPoint(x:-150,y:630)
var now:TimeInterval=37
var presented:[NSWindow]=[], focuses=0, captured:[[String]]=[], commands:[String]=[]
var states:[DesktopCaptureState]=[]
var completionBlocked:[NSRect]=[], completionReliable=true
func context(_ count:Int=7, blocked:[NSRect]=[], reliable:Bool=true, local:Bool=false,
             desktop:Bool=true, id:String="audit")->DesktopNaturalCaptureContext {
    DesktopNaturalCaptureContext(screenID:id,visibleFrame:work,
        desktopFrames:desktop ? [screen.frame] : [],blockedFrames:blocked,
        isReliable:reliable,dragPasteboardChangeCount:count,sourceIsLocal:local)
}
let layer=DesktopInsects(screens:[screen],renderTime:{now},naturalEventTime:{now},windowPresenter:{presented.append($0)},
    naturalContextProvider:{_,_ in context(blocked:completionBlocked,reliable:completionReliable)})
host.desktopInsects=layer
host.overlay=OverlayWindow(contentRect:NSRect(x:-1200,y:-100,width:200,height:130),styleMask:[.borderless],backing:.buffered,defer:false)
host.overlay.isReleasedWhenClosed=false
host.scene=TianmuView(frame:host.overlay.contentView!.bounds)
host.scene.attendantArtwork=nil; host.scene.shrineArtwork=nil; host.scene.persistLegacyFrame=false
host.overlay.contentView=host.scene; host.scene.attach(window:host.overlay)
host.panel=NSWindow(contentRect:NSRect(x:-1000,y:100,width:480,height:580),styleMask:[.titled],backing:.buffered,defer:false)
host.panel.isReleasedWhenClosed=false
host.overlayPresenter={presented.append($0)}; host.panelPresenter={presented.append($0)}
host.availableScreens={ [work] }
host.captureFeedback=CaptureFeedback(present:{presented.append($0)})
host.captureFocus={_,_ in focuses += 1}
host.configureInsects(SceneTransparencyStore(url:URL(fileURLWithPath:CommandLine.arguments[2])))
let hostStateChange=layer.onCaptureStateChange
layer.onCaptureStateChange={state in states.append(state); hostStateChange?(state)}
host.store.commandSink={action,values,done in
    commands.append(action)
    if action == "catch" { captured.append(values["ids"] as? [String] ?? []) }
    done?(true)
}
func require(_ condition:@autoclosure()->Bool,_ message:String) {
    if !condition() { fputs("FAIL: \(message)\n",stderr); exit(1) }
}
func passive(natural:Bool=true) {
    require(layer.windows.allSatisfy{$0.ignoresMouseEvents && !$0.isVisible && !$0.isKeyWindow},
        "A passive net must never turn the screen layer into an input shield or activate it")
    require(!layer.isNaturalHandleVisible && layer.captureHandleWindow == nil,
        "Default passive input must never create the old hover trigger")
    if natural { require(!host.captureFeedback.isPresented,"Natural desktop selection must not show a game HUD") }
    require(focuses == 0,"Passive desktop input must never request application focus")
}
func fresh(_ id:String="one") {
    layer.update(rows:[["id":id,"x":0.5,"y":0.5,"color":"普通褐色"]]); layer.show()
}
func event(_ type:NSEvent.EventType,_ point:NSPoint,_ timestamp:TimeInterval?=nil,
           modifiers:NSEvent.ModifierFlags=[],clicks:Int=1,windowNumber:Int=0)->NSEvent {
    NSEvent.mouseEvent(with:type,location:point,modifierFlags:modifiers,timestamp:timestamp ?? now,
        windowNumber:windowNumber,context:nil,eventNumber:1,clickCount:clicks,pressure:1)!
}
func global(_ type:NSEvent.EventType,_ point:NSPoint,_ c:DesktopNaturalCaptureContext?=nil,
            timestamp:TimeInterval?=nil,modifiers:NSEvent.ModifierFlags=[],clicks:Int=1) {
    let input=event(type,point,timestamp,modifiers:modifiers,clicks:clicks)
    require(host.handleGlobalEvent(input,context:c ?? context()) === input,
        "The production global monitor boundary must return the identical NSEvent")
}
func begin() {
    global(.leftMouseDown,origin)
    require(layer.hasNaturalGesture && !layer.isCapturing && !layer.isWeaving,
        "A down may remember a desktop origin but must not arm or weave")
    passive()
}
func drag() { begin(); global(.leftMouseDragged,finish); passive() }
func release() { drag(); global(.leftMouseUp,finish); passive() }
func complete() { now += 6; layer.refresh(); now += 1; layer.refresh(); layer.refresh() }
func loseFocus() {
    host.windowDidResignKey(Notification(name:NSWindow.didResignKeyNotification,object:host.overlay))
    host.applicationDidResignActive(Notification(name:NSApplication.didResignActiveNotification,object:app))
    NotificationCenter.default.post(name:NSApplication.didResignActiveNotification,object:app)
}
func escape(local:Bool=true) {
    let input=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:now,
        windowNumber:host.overlay.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!
    let returned=local ? host.handleLocalEvent(input) : host.handleGlobalEvent(input,context:context())
    require(returned === input,"Esc cancels observation without consuming the user's original key")
}
func finishedAudit() {
    require(!host.overlay.isVisible && !host.panel.isVisible && presented.allSatisfy{!$0.isVisible},
        "All presenters must remain stubbed; no window may be displayed")
    require(!app.isActive && host.store.process == nil && focuses == 0,
        "The harness must not activate itself, launch a worker or request focus")
    layer.close()
    print("PASS \(CommandLine.arguments[1]): real passive host boundary; NO_VISIBLE_WINDOWS_NO_WORKER_NO_REAL_SAVE")
}
fresh()
'''

HARNESS = BASE_HARNESS + r'''
switch CommandLine.arguments[1] {
case "repeat_natural":
    for index in 0..<3 {
        fresh("fly-\(index)"); states=[]
        host.updateInsectPointer(layer.positions[0].point,buttonsPressed:0); passive()
        release()
        require(layer.isWeaving && !layer.isCapturing && captured.count == index,
            "Release starts background weaving without submitting early")
        loseFocus(); complete(); passive()
        require(captured.count == index+1 && captured.last == ["fly-\(index)"],
            "Each repeated native desktop selection must submit current IDs exactly once")
        require(states == [.dragging,.weaving,.completed],"Natural capture must not flicker through explicit armed/idle states")
        global(.leftMouseUp,finish); layer.refresh()
        require(captured.count == index+1,"Repeated release cannot replay completion")
    }
case "repeat_explicit":
    host.store.setNaturalCaptureEnabled(false)
    for index in 0..<3 {
        fresh("explicit-\(index)"); host.capture()
        require(layer.captureState == .armed && host.captureFeedback.isPresented,
            "Explicit menu entry keeps its instruction while remaining passive")
        passive(natural:false); loseFocus()
        require(layer.captureState == .armed,"Returning to desktop must not disarm the explicit fallback")
        global(.leftMouseDown,origin); global(.leftMouseDragged,finish); global(.leftMouseUp,finish)
        require(!layer.captureIsNatural && layer.isWeaving,"Explicit fallback still uses the original observed desktop stream")
        passive(natural:false); complete()
        require(captured.count == index+1 && captured.last == ["explicit-\(index)"],"Explicit fallback must remain repeatable")
    }
case "focus_preserves_candidate":
    begin(); loseFocus()
    require(layer.hasNaturalGesture && !layer.isCapturing,"Normal focus transfer must preserve a pending desktop origin")
    global(.leftMouseDragged,finish); loseFocus()
    require(layer.hasNaturalGesture && layer.captureState == .dragging,"Normal focus transfer must preserve a held passive drag")
    global(.leftMouseUp,finish); loseFocus()
    require(layer.isWeaving,"Released background weaving must survive ordinary key and app focus changes")
    complete(); passive(); require(captured == [["one"]],"Focus transfers cannot lose the valid selection")
case "poll_before_async_up":
    drag(); host.updateInsectPointer(finish,buttonsPressed:0)
    require(layer.hasNaturalGesture && layer.isCapturing,
        "Physical-button poll may precede queued up; it must not steal a valid release")
    now += 0.05; global(.leftMouseUp,finish,timestamp:now-0.05)
    complete(); passive(); require(captured == [["one"]],"Fresh queued mouse-up must finish exactly once")
case "host_route_and_manual_gate":
    drag(); host.openRoute("虫瓶")
    global(.leftMouseUp,finish); complete(); passive()
    require(captured.isEmpty,"Opening an explicit own route must cancel an uncommitted natural selection")
    host.dismissPanel(); host.manualInteraction=true
    global(.leftMouseDown,origin); global(.leftMouseDragged,finish); global(.leftMouseUp,finish); complete()
    require(captured.isEmpty && !layer.hasNaturalGesture,"Scene movement must exclude natural capture origin acquisition")
    host.manualInteraction=false; release(); complete()
    require(captured == [["one"]],"Closing the scene adjustment gate must permit the next fresh selection")
case "fast_release_and_clicks":
    for _ in 0..<3 {
        global(.leftMouseDown,origin); global(.leftMouseUp,NSPoint(x:origin.x+2,y:origin.y+1)); complete(); passive()
        require(captured.isEmpty && layer.captureState == .idle,"Desktop short clicks must never arm an explicit net")
    }
    begin(); global(.leftMouseUp,finish); complete(); passive()
    require(captured == [["one"]],"Displaced release must preserve a fast/coalesced desktop selection")
case "host_cancellation":
    for released in [false,true] {
        for reason in 0..<5 {
            host.showPet(); host.wakeNow(); fresh(); drag()
            if released { global(.leftMouseUp,finish) }
            switch reason {
            case 0: host.hideDesktopCompanions()
            case 1: host.sleepNow()
            case 2: global(.rightMouseDown,finish)
            case 3: escape()
            default: escape(local:false)
            }
            global(.leftMouseUp,finish); complete()
            require(captured.isEmpty && !layer.hasNaturalGesture && !layer.isCapturing && !layer.isWeaving,
                "Host hide/sleep/right-click/local or global Esc must cancel without stale completion")
            passive()
        }
    }
    host.showPet(); host.wakeNow(); release(); complete()
    require(captured == [["one"]],"Every cancellation path must leave a later valid selection usable")
case "hidden_and_sleep_gate":
    for asleep in [false,true] {
        if asleep { host.showPet(); host.sleepNow() } else { host.hideDesktopCompanions() }
        global(.leftMouseDown,origin); global(.leftMouseDragged,finish); global(.leftMouseUp,finish); complete()
        require(captured.isEmpty && !layer.hasNaturalGesture && !layer.isWeaving,"Hidden/sleeping host must reject new desktop candidates")
        host.wakeNow(); host.showPet()
    }
    release(); complete(); require(captured == [["one"]],"Wake/show must restore fresh passive capture")
case "state_reentrant":
    layer.onCaptureStateChange={state in hostStateChange?(state); if state == .dragging { layer.cancelCapture() } }
    release(); complete(); require(captured.isEmpty && layer.captureState == .idle,"A cancelled state callback must not resurrect a drag on up")
    layer.onCaptureStateChange=hostStateChange
    let hostCapture=layer.onCapture
    layer.onCapture={ids in hostCapture?(ids); host.capture()}
    release(); now += 6; layer.refresh()
    require(captured == [["one"]] && layer.captureState == .armed && !layer.isWeaving && layer.lastCaptureCount == nil,
        "A replacement net started by the real capture callback must not be overwritten by old completion")
    passive(natural:false)
case "natural_opt_out":
    host.store.setNaturalCaptureEnabled(false)
    global(.leftMouseDown,origin); global(.leftMouseDragged,finish); global(.leftMouseUp,finish); complete()
    host.updateInsectPointer(layer.positions[0].point,buttonsPressed:0)
    passive(); require(captured.isEmpty && !layer.hasNaturalGesture,"Opt-out must remove natural capture without reintroducing a hover trigger")
    host.store.setNaturalCaptureEnabled(true); release(); complete()
    require(captured == [["one"]],"Changing the saved preference back must restore natural capture")
default: fatalError("Unknown scenario")
}
finishedAudit()
'''


def prepare_harness(cls, prefix, harness):
    cls.temporary=tempfile.TemporaryDirectory(prefix=prefix)
    cls.addClassCleanup(cls.temporary.cleanup)
    cls.folder=Path(cls.temporary.name); cls.binary=cls.folder/'check'
    source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
    (cls.folder/'main.swift').write_text(with_desktop_motion_fixture(source+harness))
    (cls.folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
    files=['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift',
           'TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
    for name in files: (cls.folder/name).write_text((ROOT/'native/v1'/name).read_text())
    build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(cls.folder/'Scene.swift'),
        *[str(cls.folder/name) for name in files],str(cls.folder/'main.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
    if build.returncode: raise AssertionError(build.stderr)


def run_scenario(test, name):
    run=subprocess.run([str(test.binary),name,str(test.folder/(name+'.appearance.json')),
        '--save-file',str(test.folder/'unused-state.json')],capture_output=True,text=True,timeout=20)
    test.assertEqual(run.returncode,0,run.stdout+run.stderr)
    test.assertIn('NO_VISIBLE_WINDOWS_NO_WORKER_NO_REAL_SAVE',run.stdout)
    print(run.stdout.strip())


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'),'macOS + Swift required')
class CaptureHostSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): prepare_harness(cls,'tianmu-passive-host-sequence-',HARNESS)
    def test_three_natural_selections_through_actual_global_host(self): run_scenario(self,'repeat_natural')
    def test_explicit_fallback_remains_passive_repeatable_and_focus_safe(self): run_scenario(self,'repeat_explicit')
    def test_ordinary_focus_changes_preserve_pending_held_and_released_input(self): run_scenario(self,'focus_preserves_candidate')
    def test_physical_button_poll_cannot_steal_a_queued_mouse_up(self): run_scenario(self,'poll_before_async_up')
    def test_explicit_route_cancels_and_manual_scene_gate_rearms(self): run_scenario(self,'host_route_and_manual_gate')
    def test_short_clicks_have_no_effect_and_displaced_release_captures(self): run_scenario(self,'fast_release_and_clicks')
    def test_hide_sleep_right_click_and_escape_cancel_held_and_released_nets(self): run_scenario(self,'host_cancellation')
    def test_hidden_sleeping_host_rejects_new_candidates_until_show_wake(self): run_scenario(self,'hidden_and_sleep_gate')
    def test_reentrant_host_callbacks_do_not_resurrect_replaced_work(self): run_scenario(self,'state_reentrant')
    def test_saved_natural_opt_out_does_not_restore_hover_interception(self): run_scenario(self,'natural_opt_out')


if __name__ == '__main__': unittest.main()
