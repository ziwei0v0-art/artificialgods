"""Actual handle -> host geometry -> isolated placement persistence, all windows hidden."""
import unittest
import test_pointer_access as pointer_fixture


class SceneAdjustmentHostDragTests(unittest.TestCase):
    def test_handle_commits_own_drag_and_rolls_back_cancel_or_failed_write(self):
        pointer_fixture.PointerAccessTests._run_harness(self,'host adjustment drag',r'''
let host=hostAt("host-handle-drag")
host.adjustmentHandle=SceneAdjustmentHandle(present:{ _ in })
let full=NSRect(x:0,y:0,width:1440,height:900)
let work=NSRect(x:0,y:90,width:1440,height:786)
host.availableScreens={ [work] }
host.placementScreens={ [scenePlacementScreen(frame:full,visibleFrame:work)] }
let url=fixtureDirectory.appendingPathComponent("handle-window.json")
let settings=WindowPlacementStore(url:url)
host.configureGeometry(settings)
func show()->NSButton {
    let art=host.scene.placementScreenFrame
    host.updatePointer(NSPoint(x:art.midX,y:art.midY),buttonsPressed:0)
    require(host.adjustmentHandle.isPresented,"Host must present an independently reachable handle")
    return host.adjustmentHandle.window!.contentView as! NSButton
}
func mouse(_ type:NSEvent.EventType,_ delta:NSPoint = .zero)->NSEvent {
    NSEvent.mouseEvent(with:type,location:NSPoint(x:16+delta.x,y:16+delta.y),modifierFlags:[],timestamp:10,
        windowNumber:host.adjustmentHandle.window!.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
let first=show()
let down=mouse(.leftMouseDown)
_ = host.handleLocalEvent(down); first.mouseDown(with:down)
require(host.manualInteraction && host.adjustmentHandle.isInteracting && !host.pointerAvoiding
    && host.overlay.ignoresMouseEvents,"Owned handle press must show the body without intercepting desktop clicks")
require(host.presentation.route == nil && !FileManager.default.fileExists(atPath:url.path),"Mouse-down must not open settings or write a placement")
first.mouseUp(with:mouse(.leftMouseUp))
require(host.presentation.route == "设置" && !host.manualInteraction && !host.adjustmentHandle.isInteracting,
    "Short click must finish the press and open settings on release")
require(!FileManager.default.fileExists(atPath:url.path),"Short click with no movement must not create a placement file")
host.dismissPanel()
let moving=show(); moving.mouseDown(with:mouse(.leftMouseDown))
moving.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:160,y:-500)))
let unit=host.scene.placementUnitBounds
let bottom=host.overlay.frame
require(abs(bottom.minX-360)<0.001 && abs(bottom.minY+unit.minY*bottom.height)<0.001,
    "Visible art must reach physical screen bottom instead of stopping above the Dock")
require(!FileManager.default.fileExists(atPath:url.path),"Drag preview must not save before mouse-up")
host.updatePointer(NSPoint(x:900,y:20),buttonsPressed:1)
require(host.adjustmentHandle.isPresented && host.adjustmentHandle.isInteracting && host.overlay.ignoresMouseEvents,
    "Host poll must not cancel its own acquired drag or make the canvas intercept office input")
moving.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:160,y:-500)))
require(host.presentation.route == nil && !host.manualInteraction && !host.adjustmentHandle.isInteracting,
    "Committed drag must exit movement without opening settings")
let committed=host.overlay.frame
let saved=try! Data(contentsOf:url)
let record=try! JSONSerialization.jsonObject(with:saved) as! [String:Any]
require(abs((record["x"] as! Double)-360)<0.001 && abs((record["y"] as! Double)-committed.minY)<0.001,
    "Committed movement must persist the actual constrained frame in its isolated file")
require(host.committedPlacement == committed,"Host committed frame must agree with stored placement")
let cancel=show(); cancel.mouseDown(with:mouse(.leftMouseDown))
cancel.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:80,y:220)))
require(host.overlay.frame != committed,"Cancellation fixture must actually move")
let escape=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:11,
    windowNumber:host.adjustmentHandle.window!.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!
_ = host.handleLocalEvent(escape)
cancel.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:80,y:220)))
require(host.overlay.frame == committed && (try! Data(contentsOf:url)) == saved && !host.manualInteraction,
    "Host Esc must restore the starting position and leave persistence unchanged")
let losing=show(); losing.mouseDown(with:mouse(.leftMouseDown))
losing.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:-70,y:180)))
NotificationCenter.default.post(name:NSWindow.didResignKeyNotification,object:host.adjustmentHandle.window!)
require(host.overlay.frame == committed && (try! Data(contentsOf:url)) == saved && !host.manualInteraction,
    "Handle focus loss must roll back its actual host movement")
let blocked=fixtureDirectory.appendingPathComponent("blocked-placement")
try! "file".write(to:blocked,atomically:true,encoding:.utf8)
host.configureGeometry(WindowPlacementStore(url:blocked.appendingPathComponent("window.json")))
let failing=show(); failing.mouseDown(with:mouse(.leftMouseDown))
failing.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:50,y:100)))
failing.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:50,y:100)))
require(host.overlay.frame == committed && host.store.sceneSizeError.contains("未保存"),
    "Failed placement write must restore committed geometry and report failure")
require(!host.overlay.isVisible && !host.panel.isVisible && !host.adjustmentHandle.window!.isVisible
    && host.store.process == nil,"Harness must not show a window, run a worker or use a real save")
print("PASS: real host click without write, bottom drag commit, held-pointer passthrough, Esc/focus rollback and failed-write recovery; NO_VISIBLE_WINDOWS_NO_WORKER")
''')
