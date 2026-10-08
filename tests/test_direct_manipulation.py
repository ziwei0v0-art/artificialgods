"""Replay production AppKit input on an unshown window; no worker or game save."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]


class DirectManipulationTests(unittest.TestCase):
    def run_swift(self, harness):
        with tempfile.TemporaryDirectory(prefix='tianmu-input-') as directory:
            folder = Path(directory)
            source = (ROOT / 'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
            (folder / 'main.swift').write_text(with_desktop_motion_fixture(source + harness))
            (folder / 'Scene.swift').write_text((ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            build = subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
                str(folder / 'Scene.swift'), str(ROOT / 'native/v1/Presentation.swift'),
                str(ROOT / 'native/v1/WindowPlacement.swift'), str(ROOT / 'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT / 'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'), str(folder / 'main.swift'),
                '-o', str(folder / 'check')], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(folder / 'check'), str(folder)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_click_fires_on_release_not_press_or_long_hold(self):
        self.run_swift(r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let view = TianmuView(frame:NSRect(x:0,y:0,width:370,height:190))
var clicks:[String] = []
view.onSubjectClick = { clicks.append($0) }
func event(_ type:NSEvent.EventType, _ p:NSPoint, _ time:Double) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:p,modifierFlags:[],timestamp:time,windowNumber:0,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
let shrine = NSPoint(x:105,y:90), child = NSPoint(x:300,y:135)
view.mouseDown(with:event(.leftMouseDown,shrine,10))
assert(clicks.isEmpty, "Press must wait for release before opening an entry")
view.mouseUp(with:event(.leftMouseUp,NSPoint(x:107,y:92),10.2))
assert(clicks == ["shrine"], "Small pointer jitter should still be a click")
view.mouseUp(with:event(.leftMouseUp,shrine,10.3))
assert(clicks.count == 1, "Duplicate release must not reopen")
view.mouseDown(with:event(.leftMouseDown,child,20))
view.mouseUp(with:event(.leftMouseUp,child,20.1))
assert(clicks == ["shrine","attendant"])
view.mouseDown(with:event(.leftMouseDown,shrine,30))
view.mouseUp(with:event(.leftMouseUp,shrine,31.2))
assert(clicks.count == 2, "Long stationary press is not a short click")
view.mouseDown(with:event(.leftMouseDown,NSPoint(x:10,y:10),40))
view.mouseUp(with:event(.leftMouseUp,shrine,40.1))
assert(clicks.count == 2, "An outside press cannot become a subject click")
view.mouseDown(with:event(.leftMouseDown,shrine,50))
view.cancelInteraction()
view.mouseUp(with:event(.leftMouseUp,shrine,50.1))
assert(clicks.count == 2, "Cancelling a pending press must discard its eventual release")
print("PASS: release-only shrine/attendant clicks, jitter, long hold, duplicate up, outside press; NO_WINDOWS_NO_WORKER")
''')

    def test_drag_latches_uses_screen_coordinates_and_cancels(self):
        self.run_swift(r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let window = OverlayWindow(contentRect:NSRect(x:200,y:100,width:370,height:190),styleMask:[.borderless],backing:.buffered,defer:false)
window.isReleasedWhenClosed = false
let view = TianmuView(frame:NSRect(x:0,y:0,width:370,height:190))
window.contentView = view; view.attach(window:window); view.persistLegacyFrame = false
let original = window.frame
var clicks = 0, commits = 0
view.onSubjectClick = { _ in clicks += 1 }
view.emit = { if $0["type"] as? String == "window_frame" { commits += 1 } }
func mouse(_ type:NSEvent.EventType, _ screen:NSPoint, _ time:Double) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:window.convertPoint(fromScreen:screen),modifierFlags:[],timestamp:time,windowNumber:window.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
func start(_ local:NSPoint, _ time:Double) -> NSPoint {
    let screen = window.convertPoint(toScreen:local)
    view.mouseDown(with:mouse(.leftMouseDown,screen,time))
    assert(view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)), "Pending press must survive pointer leaving the hit region")
    return screen
}
for local in [NSPoint(x:105,y:90), NSPoint(x:300,y:135)] {
    window.setFrame(original,display:false)
    let p = start(local,10)
    let q = NSPoint(x:p.x+100,y:p.y+40)
    view.mouseDragged(with:mouse(.leftMouseDragged,q,10.1))
    assert(window.frame.origin == NSPoint(x:300,y:140), "Drag should move the scene by screen delta")
    view.mouseDragged(with:mouse(.leftMouseDragged,q,10.2))
    assert(window.frame.origin == NSPoint(x:300,y:140), "Repeated event must not accumulate movement")
    view.mouseUp(with:mouse(.leftMouseUp,q,10.3))
    assert(!view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)))
}
assert(commits == 2 && clicks == 0)
window.setFrame(original,display:false)
let p = start(NSPoint(x:105,y:90),20)
view.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:p.x+40,y:p.y),20.1))
view.mouseDragged(with:mouse(.leftMouseDragged,p,20.2))
view.mouseUp(with:mouse(.leftMouseUp,p,20.3))
assert(clicks == 0 && commits == 3, "Dragging back to the start must not become a click")
let hold = start(NSPoint(x:300,y:135),30)
view.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:hold.x+60,y:hold.y),32))
view.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:hold.x+60,y:hold.y),32.1))
assert(window.frame.minX == 260 && commits == 4 && clicks == 0, "Long hold may still turn into drag")
for cancel in ["escape", "focus", "application"] {
    window.setFrame(original,display:false)
    let p = start(NSPoint(x:105,y:90),40)
    view.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:p.x+40,y:p.y),40.1))
    if cancel == "escape" {
        view.keyDown(with:NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:40.2,windowNumber:window.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!)
    } else {
        NotificationCenter.default.post(name:cancel == "focus" ? NSWindow.didResignKeyNotification : NSApplication.didResignActiveNotification,object:cancel == "focus" ? window : app)
    }
    assert(window.frame == original, "Cancelled drag must restore its original placement")
    view.mouseUp(with:mouse(.leftMouseUp,p,40.3))
    assert(clicks == 0 && commits == 4 && !view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)))
}
assert(!window.isVisible)
print("PASS: shrine/child drag, no cumulative jitter, leave-hit-region lock, drag-back latch, long-hold drag, Esc/window/app focus cancellation; HIDDEN_WINDOW_NO_WORKER")
''')

    def test_menu_scale_binding_limits_restore_and_save_failure(self):
        self.run_swift(r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let folder = URL(fileURLWithPath:CommandLine.arguments[1])
let url = folder.appendingPathComponent("experience-state.json.window.json")
let host = ApplicationHost()
host.overlay = OverlayWindow(contentRect:NSRect(x:200,y:100,width:370,height:190),styleMask:[.borderless],backing:.buffered,defer:false)
host.overlay.isReleasedWhenClosed = false
host.scene = TianmuView(frame:host.overlay.contentView!.bounds)
host.overlay.contentView = host.scene; host.scene.attach(window:host.overlay); host.scene.persistLegacyFrame = false
host.availableScreens = { [NSRect(x:0,y:0,width:1440,height:900)] }
host.configureGeometry(WindowPlacementStore(url:url))
host.desktopScreens = { [DesktopInsectScreen(id:"main",frame:NSRect(x:0,y:0,width:1440,height:900))] }
host.desktopInsects = DesktopInsects(screens:host.desktopScreens(),renderTime:{ 10 })
host.desktopInsects!.update(rows:[["id":"fly","x":0.99,"y":0.99,"color":"白色"]])
let insectPoint = host.desktopInsects!.positions.first!.point
host.contextMenu = host.makeSceneMenu()
var openings = 0
host.sceneMenuPresenter = { menu, _, _ in
    openings += 1
    assert(menu.items.contains { $0.title == "计时" })
    assert(menu.items.contains { $0.view is SceneSizeMenuView }, "Continuous size slider must be in the left-click entry")
}
host.configureSceneActions()
host.scene.onSubjectClick?("shrine"); host.scene.onSubjectClick?("attendant")
assert(openings == 2 && !FileManager.default.fileExists(atPath:url.path), "Opening must not save placement")
let control = SceneSizeControl(store:host.store)
let beforeScaleArt=host.scene.placementScreenFrame
control.value.wrappedValue = 120
assert(host.overlay.frame.size == NSSize(width:444,height:228), "Scale must preserve the exact scene aspect ratio")
let afterScaleArt=host.scene.placementScreenFrame
assert(abs(beforeScaleArt.midX-afterScaleArt.midX) <= 1 && abs(beforeScaleArt.midY-afterScaleArt.midY) <= 1,
    "Visible artwork center must survive scale within AppKit window pixel rounding")
assert(host.store.sceneScale == 120)
func restoredWindowFrame() -> NSRect {
    let restored=NSWindow(contentRect:.zero,styleMask:[.borderless],backing:.buffered,defer:false)
    restored.isReleasedWhenClosed=false
    restored.setFrame(WindowPlacementStore(url:url).restore(screens:host.availableScreens(),
        contentBounds:host.scene.placementUnitBounds),display:false)
    assert(!restored.isVisible,"Restore verification must not show a window")
    return restored.frame
}
assert(restoredWindowFrame() == host.overlay.frame,"Reopening the saved fractional frame must reproduce the actual AppKit window")
control.value.wrappedValue = 999
assert(host.overlay.frame.width == 555 && host.overlay.frame.height == 285 && host.store.sceneScale == 150)
control.value.wrappedValue = 1
assert(host.overlay.frame.width == 74 && host.overlay.frame.height == 38 && host.store.sceneScale == 20)
let sizeControl = host.contextMenu.items.compactMap { $0.view as? SceneSizeMenuView }.first!
sizeControl.slider.doubleValue = 100
sizeControl.changed()
assert(host.store.sceneScale == 100 && host.overlay.frame.width == 370)
func drag(_ offset:NSPoint, _ time:Double) {
    let start = host.overlay.convertPoint(toScreen:NSPoint(x:105,y:90))
    func event(_ type:NSEvent.EventType, _ p:NSPoint, _ t:Double) -> NSEvent {
        NSEvent.mouseEvent(with:type,location:host.overlay.convertPoint(fromScreen:p),modifierFlags:[],timestamp:t,windowNumber:host.overlay.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
    }
    let finish = NSPoint(x:start.x+offset.x,y:start.y+offset.y)
    host.scene.mouseDown(with:event(.leftMouseDown,start,time))
    host.scene.mouseDragged(with:event(.leftMouseDragged,finish,time+0.1))
    host.scene.mouseUp(with:event(.leftMouseUp,finish,time+0.2))
}
let origin = host.overlay.frame.origin
drag(NSPoint(x:70,y:30),10)
assert(host.overlay.frame.origin == NSPoint(x:origin.x+70,y:origin.y+30))
assert(openings == 2, "Moving a subject cannot open a menu")
assert(restoredWindowFrame() == host.overlay.frame, "Host must connect completed drag to the selected sidecar")
let saved = try! Data(contentsOf:url), before = host.overlay.frame
let blocked = folder.appendingPathComponent("not-a-directory")
try! "file".write(to:blocked,atomically:true,encoding:.utf8)
host.configureGeometry(WindowPlacementStore(url:blocked.appendingPathComponent("position.json")))
control.value.wrappedValue = 125
assert(host.overlay.frame == before && host.store.sceneScale == 100)
assert(!host.store.sceneSizeError.isEmpty && (try! Data(contentsOf:url)) == saved)
drag(NSPoint(x:40,y:20),20)
assert(host.overlay.frame == before && (try! Data(contentsOf:url)) == saved, "Failed drag save must restore previous placement")
assert(!host.scene.shouldCapturePointer(at:NSPoint(x:-999,y:-999)), "Save failure cannot retain the mouse")
// The next left-click entry must expose a failed-save notice, even with sidebar closed.
host.openSceneMenu()
assert(host.contextMenu.items.contains { $0.title.contains("未保存") })
let second = NSRect(x:-1440,y:0,width:1440,height:900)
let resized = scaledOverlayFrame(NSRect(x:-900,y:100,width:370,height:190),percent:125,screens:[second])
assert(resized == NSRect(x:-946.25,y:76.25,width:462.5,height:237.5))
assert(second.contains(fitOverlayFrame(NSRect(x:-100,y:-100,width:9000,height:9000),screens:[second])))
let stretched = fitOverlayFrame(NSRect(x:0,y:0,width:9000,height:225),screens:host.availableScreens())
assert(abs(stretched.width / stretched.height - 370.0 / 190) < 0.001, "Stretched dimensions must normalize to the compact scene")
// Monitor reconfiguration must end an uncommitted drag before saving a safe frame.
host.configureGeometry(WindowPlacementStore(url:url))
host.panel = NSWindow(contentRect:.zero,styleMask:[.borderless],backing:.buffered,defer:false)
host.panel.isReleasedWhenClosed = false
let beforeReconfigure = host.overlay.frame
let start = host.overlay.convertPoint(toScreen:NSPoint(x:105,y:90))
func monitorEvent(_ type:NSEvent.EventType, _ p:NSPoint, _ time:Double) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:host.overlay.convertPoint(fromScreen:p),modifierFlags:[],timestamp:time,windowNumber:host.overlay.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
host.scene.mouseDown(with:monitorEvent(.leftMouseDown,start,50))
host.scene.mouseDragged(with:monitorEvent(.leftMouseDragged,NSPoint(x:start.x+80,y:start.y),50.1))
assert(host.overlay.frame != beforeReconfigure, "Fixture must have an in-flight moved frame")
host.screensChanged()
assert(host.overlay.frame == beforeReconfigure, "Screen change must not commit the in-flight frame")
assert(!host.scene.shouldCapturePointer(at:NSPoint(x:-999,y:-999)), "Screen change must release the gesture before any trailing mouseUp")
host.scene.mouseUp(with:monitorEvent(.leftMouseUp,start,50.2))
assert(host.overlay.frame == beforeReconfigure, "Screen reconfiguration must cancel the in-flight drag")
assert(restoredWindowFrame() == beforeReconfigure)
assert(!host.scene.shouldCapturePointer(at:NSPoint(x:-999,y:-999)))
host.desktopInsects!.refresh()
assert(host.desktopInsects!.positions.first!.point == insectPoint,"Shrine scaling/dragging must never transform desktop insect positions")
host.desktopInsects?.close()
assert(!host.overlay.isVisible && host.store.process == nil)
print("PASS: real scene callbacks/menu, production slider binding, 20...150 continuous limits, center anchor, negative monitor, sidecar restore, failed save retains frame/file and exposes notice; HIDDEN_WINDOW_NO_WORKER")
''')
