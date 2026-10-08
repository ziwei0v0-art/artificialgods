"""Pointer access policy and wiring with unshown windows and temporary preferences.

No production launch, game worker, system pointer input, or real save is used.
Presenter callbacks are stubs; the harness never activates an application.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest


from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let fixtureDirectory = URL(fileURLWithPath: CommandLine.arguments[1])
func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { fputs("FAIL: \(message)\n", stderr); exit(1) }
}
func hostAt(_ name: String) -> ApplicationHost {
    let host = ApplicationHost()
    host.overlay = OverlayWindow(contentRect: NSRect(x:200,y:100,width:370,height:190),
        styleMask:[.borderless], backing:.buffered, defer:false)
    host.overlay.isReleasedWhenClosed = false
    host.scene = TianmuView(frame: host.overlay.contentView!.bounds)
    host.scene.attendantArtwork = nil; host.scene.shrineArtwork = nil
    host.scene.persistLegacyFrame = false
    host.overlay.contentView = host.scene; host.scene.attach(window:host.overlay)
    host.panel = NSWindow(contentRect:NSRect(x:600,y:100,width:480,height:580),
        styleMask:[.titled,.closable], backing:.buffered, defer:false)
    host.panel.isReleasedWhenClosed = false; host.panel.delegate = host
    host.availableScreens = { [NSRect(x:0,y:0,width:1440,height:900)] }
    host.panelPresenter = { _ in }
    host.overlayPresenter = { _ in }
    host.captureFocus = { _,_ in require(false,"Unexpected capture activation") }
    host.configureSceneActions()
    host.configureTransparency(SceneTransparencyStore(
        url:fixtureDirectory.appendingPathComponent(name + ".appearance.json")))
    return host
}
let near = NSPoint(x:305,y:190)
let away = NSPoint(x:20,y:20)
'''


class PointerAccessTests(unittest.TestCase):
    def _run_harness(self, name, harness):
        host = (ROOT / 'native/v1/main.swift').read_text().split(
            'let application = NSApplication.shared')[0]
        scene = (ROOT / 'native/OverlayHost.swift').read_text().split(
            'final class Host:')[0]
        with tempfile.TemporaryDirectory(prefix='tianmu-pointer-access-') as directory:
            folder = Path(directory)
            (folder / 'Scene.swift').write_text(scene)
            (folder / 'main.swift').write_text(with_desktop_motion_fixture(host + FIXTURE + harness))
            binary = folder / 'check'
            build = subprocess.run([
                'swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
                str(folder / 'Scene.swift'),
                str(ROOT / 'native/v1/Presentation.swift'),
                str(ROOT / 'native/v1/WindowPlacement.swift'),
                str(ROOT / 'native/v1/DesktopInsects.swift'),
                str(ROOT / 'native/v1/InsectArtwork.swift'),
                str(ROOT / 'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),
                str(folder / 'main.swift'), '-o', str(binary),
            ], capture_output=True, text=True, timeout=90)
            self.assertEqual(build.returncode, 0, name + ':\n' + build.stderr)
            run = subprocess.run([str(binary), str(folder)], capture_output=True,
                                 text=True, timeout=20)
            self.assertEqual(run.returncode, 0, name + ':\n' + run.stdout + run.stderr)
            self.assertIn('NO_VISIBLE_WINDOWS_NO_WORKER', run.stdout)
            print(run.stdout.strip())

    def test_adjustment_handle_moves_only_its_own_press_and_cancels(self):
        self._run_harness('handle drag ownership', r'''
let handle=SceneAdjustmentHandle(present:{ _ in })
let screen=NSRect(x:0,y:0,width:1440,height:900)
let initial=NSRect(x:200,y:100,width:370,height:190)
var frame=initial, starts=0, activations=0, commits=0, cancels=0, moved=false
handle.onActivate={ activations += 1 }
handle.onPress={ starts += 1; moved=false }
handle.onMove={ delta in frame=initial.offsetBy(dx:delta.x,dy:delta.y); moved=true }
handle.onMoveEnd={ cancelled in
    if cancelled { frame=initial; cancels += 1 }
    else if moved { commits += 1 }
}
func show() {
    handle.update(pointer:near,sceneFrame:initial,screens:[screen],enabled:true,buttonsPressed:0)
    require(handle.isPresented,"Handle must be available before pressing")
}
func mouse(_ type:NSEvent.EventType,_ delta:NSPoint = .zero) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:NSPoint(x:16+delta.x,y:16+delta.y),modifierFlags:[],
        timestamp:10,windowNumber:handle.window!.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
show()
let button=handle.window!.contentView as! NSButton
button.mouseDown(with:mouse(.leftMouseDown))
require(handle.isInteracting && starts == 1 && activations == 0,"Press must latch without opening settings")
handle.update(pointer:NSPoint(x:900,y:500),sceneFrame:frame,screens:[screen],enabled:false,buttonsPressed:1)
require(handle.isPresented && handle.isInteracting,"Owned press must survive host movement bypass and outside pointer")
button.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:3,y:2)))
require(frame == initial,"Below-threshold jitter must not move scene")
button.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:80,y:-40)))
require(frame == NSRect(x:280,y:60,width:370,height:190),"Drag must deliver total screen displacement")
button.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:2,y:1)))
button.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:2,y:1)))
require(frame == NSRect(x:202,y:101,width:370,height:190) && commits == 1 && activations == 0 && !handle.isInteracting,
    "Returning inside handle after a drag must commit movement and never open settings")
show(); button.mouseDown(with:mouse(.leftMouseDown))
button.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:100,y:-30)))
let escape=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:11,
    windowNumber:handle.window!.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!
button.keyDown(with:escape)
button.mouseUp(with:mouse(.leftMouseUp))
require(frame == initial && cancels == 1 && commits == 1 && activations == 0 && !handle.isInteracting,
    "Esc must restore movement and discard later mouse-up")
show(); button.mouseDown(with:mouse(.leftMouseDown))
button.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:40,y:20)))
NotificationCenter.default.post(name:NSWindow.didResignKeyNotification,object:handle.window!)
require(frame == initial && cancels == 2 && !handle.isInteracting && !handle.isPresented,
    "Nonactivating handle key loss must independently cancel its owned gesture")
show(); button.mouseDown(with:mouse(.leftMouseDown)); handle.dismiss()
button.mouseUp(with:mouse(.leftMouseUp))
require(cancels == 3 && activations == 0 && !handle.isPresented,"Hide must cancel a pending click")
for held in [1,2,4] {
    show()
    handle.update(pointer:near,sceneFrame:initial,screens:[screen],enabled:true,buttonsPressed:held)
    require(!handle.isPresented && !handle.isInteracting,"A Finder/system press must never acquire a gesture")
}
show(); button.mouseDown(with:mouse(.leftMouseDown)); button.mouseUp(with:mouse(.leftMouseUp))
require(activations == 1 && !handle.isPresented,"Short click opens adjustment once, on release")
require(!handle.window!.isVisible,"Harness must never show its handle")
print("PASS: click on release, own-press latch, cumulative drag/jitter, Esc, focus loss, hide, office drags; NO_VISIBLE_WINDOWS_NO_WORKER")
''')

    def test_scene_menu_fits_above_desktop_corner(self):
        self._run_harness('complete scene menu placement', r'''
let host=hostAt("menu-placement")
host.contextMenu=host.makeSceneMenu()
let screen=NSRect(x:0,y:0,width:1440,height:900)
var visits=0
host.sceneMenuPresenter = { menu, local, scene in
    let top=scene.window!.convertPoint(toScreen:scene.convert(local,to:nil))
    let size=menu.size
    let frame=NSRect(x:top.x,y:top.y-size.height,width:size.width,height:size.height)
    require(screen.contains(frame),"Menu extends offscreen and collapses into a scrolling sliver")
    require(!frame.intersects(scene.window!.frame),"Scene menu covers its own subject despite available adjacent space")
    visits += 1
}
for origin in [NSPoint(x:0,y:0),NSPoint(x:1271,y:0),NSPoint(x:0,y:813),NSPoint(x:1271,y:813)] {
    host.overlay.setFrame(NSRect(origin:origin,size:NSSize(width:169,height:87)),display:false)
    host.openSceneMenu()
}
require(visits == 4,"All desktop corners must exercise the production menu presenter")
require(!host.overlay.isVisible && host.store.process == nil,"No visible app or worker permitted")
print("PASS: whole scene menu fits all four corners without covering the scene; NO_VISIBLE_WINDOWS_NO_WORKER")
''')

    def test_capture_feedback_repeat_cancel_and_focus_lifecycle(self):
        self._run_harness('capture feedback lifecycle', r'''
let host=hostAt("capture-feedback")
var shown=0, focuses=0
host.captureFeedback=CaptureFeedback(present:{ _ in shown += 1 })
host.captureFocus={ _,_ in focuses += 1 }
let screen=DesktopInsectScreen(id:"fixture",frame:NSRect(x:0,y:0,width:1440,height:900))
var now:TimeInterval=10
let layer=DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{_ in})
host.desktopInsects=layer
host.configureInsects(SceneTransparencyStore(url:fixtureDirectory.appendingPathComponent("hud.json")))
host.store.commandSink={ _,_,done in done?(true) }
host.capture()
require(layer.captureState == .armed && host.captureFeedback.isPresented && shown == 1,
    "Choosing capture must keep a visible, explicit next-action prompt")
require(host.captureFeedback.title.contains("红色网框"),"Armed prompt must explain the drag")
func button(_ title:String,in view:NSView) -> NSButton? {
    if let found=view as? NSButton,found.title == title { return found }
    return view.subviews.compactMap { button(title,in:$0) }.first
}
for _ in 0..<3 {
    let panel=layer.windows[0], view=panel.contentView!
    func mouse(_ type:NSEvent.EventType,_ point:NSPoint) -> NSEvent {
        NSEvent.mouseEvent(with:type,location:panel.convertPoint(fromScreen:point),modifierFlags:[],
            timestamp:now,windowNumber:panel.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
    }
    view.mouseDown(with:mouse(.leftMouseDown,NSPoint(x:600,y:300)))
    require(host.captureFeedback.title.contains("松手"),"Dragging must explain release")
    view.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:800,y:440)))
    require(layer.captureState == .weaving && host.captureFeedback.title.contains("织网中"),"Weaving status missing")
    host.applicationDidResignActive(Notification(name:NSApplication.didResignActiveNotification))
    require(host.captureFeedback.isPresented && layer.isWeaving,"Returning to work must not lose the released weave")
    now += 6; layer.refresh(); host.refreshCaptureFeedback()
    require(layer.captureState == .completed && host.captureFeedback.title == "织网完成","Completion status missing")
    let again=button("再拉一网",in:host.captureFeedback.window!.contentView!)!
    require(!again.isHidden,"Completion must expose a repeat action")
    again.performClick(nil)
    require(layer.captureState == .armed && host.captureFeedback.isPresented,"Repeat action lost capture access")
}
require(focuses == 0,"Explicit capture must preserve the current working application focus")
button("取消",in:host.captureFeedback.window!.contentView!)!.performClick(nil)
require(layer.captureState == .idle && !host.captureFeedback.isPresented,"Cancel left the prompt or interception active")
require(layer.windows.allSatisfy{$0.ignoresMouseEvents && !$0.isVisible},"Cancel must release all desktop input")
require(!host.captureFeedback.window!.isVisible && host.store.process == nil,"No actual windows/worker permitted")
print("PASS: start, drag, passive weave, three repeat actions and cancel retain correct HUD/input state; NO_VISIBLE_WINDOWS_NO_WORKER")
''')

    def test_scene_popup_actual_panel_actions_and_dismissal(self):
        self._run_harness('scene popup panel', r'''
let host=hostAt("scene-popup")
host.contextMenu=host.makeSceneMenu()
host.store.state=["coins":500,"shop":[
 ["id":"offering_plate","name":"供果盘","slot":"plate","price":12,"owned":false,"placed":false,"can_buy":true],
 ["id":"incense_burner","name":"陶香炉","slot":"incense","price":24,"owned":true,"placed":true,"can_buy":false],
 ["id":"bell","name":"小铜铃","slot":"bell","price":60,"owned":true,"placed":false,"can_buy":false],
 ["id":"shrine_g1","name":"木龛","slot":"shrine","price":120,"owned":false,"placed":false,"can_buy":true],
 ["id":"shrine_g2","name":"彩塑神龛","slot":"shrine","price":360,"owned":false,"placed":false,"can_buy":false]]]
let frozen=NSDictionary(dictionary:host.store.state)
var commands=0
host.store.commandSink={ action,_,_ in if action != "sale_cancel" { commands += 1 } }
var presented=0
host.scenePopupPresenter={ window in
    presented += 1
    require(NSRect(x:0,y:0,width:1440,height:900).contains(window.frame),"Popup must fit whole screen")
    let shrine=host.overlay.convertToScreen(host.scene.convert(host.scene.shrineBounds,to:nil))
    require(!window.frame.intersects(shrine),"Popup must not cover the displayed shrine")
    require(!window.isVisible,"Test presenter must never show a popup")
}
func button(_ title:String) -> NSButton {
    host.sceneMenuWindow!.contentView!.subviews.compactMap{$0 as? NSButton}.first{$0.title == title}!
}
for origin in [NSPoint(x:0,y:0),NSPoint(x:1271,y:0),NSPoint(x:0,y:813),NSPoint(x:1271,y:813)] {
    host.overlay.setFrame(NSRect(origin:origin,size:NSSize(width:169,height:87)),display:false)
    host.openSceneMenu()
    require(host.menuTracking,"Opening must enter popup tracking")
    let surface=host.sceneMenuWindow!.contentView! as! SceneDialSurface
    surface.stopAnimation(); surface.render(at:ProcessInfo.processInfo.systemUptime+1)
    require(host.sceneMenuWindow!.frame.size == SceneSemicircleLayout.size(for:surface.direction),"Host must use compact oriented half-circle size")
    let buttons=surface.subviews.compactMap{$0 as? SceneWheelButton}.filter{!$0.isHidden}
    require(Set(buttons.map{$0.title}) == Set(["求签","虫瓶","装扮","计时","设置","退出"]),"Main semicircle has redundant or missing actions")
    require(surface.children.isEmpty && !surface.childFocus,"Secondary categories must begin collapsed")
    for title in ["求签","虫瓶","装扮","计时","设置","退出"] {
        require(host.sceneMenuWindow!.contentView!.bounds.contains(button(title).frame),"Menu button is clipped")
        require(button(title).toolTip == title && button(title).accessibilityLabel() == title,"Icon-only actions retain accessible names and hover help")
    }
    let fortune=button("求签"), anchor=SceneSemicircleLayout.anchor(for:surface.direction)
    require(fortune.frame.size == NSSize(width:60,height:60) && fortune.frame.midX == anchor.x && fortune.frame.midY == anchor.y,"Fortune must be the large subject-facing target")
    for (index,item) in surface.roots.enumerated() {
        let angle=SceneSemicircleLayout.angle(index:index,count:5)
        for radius in [76.0,94.0,110.0] {
            let p=surface.point(at:NSPoint(x:radius*cos(angle),y:radius*sin(angle)))
            require(surface.hitTest(p) === item,"A root must be a full radial petal, not a circular button")
        }
        let gap=surface.point(at:NSPoint(x:94*cos(angle+Double.pi/10),y:94*sin(angle+Double.pi/10)))
        require(surface.hitTest(gap) === surface,"Gaps between petals must not dispatch a neighboring action")
    }
    host.updatePointer(host.overlay.frame.center)
    require(!host.pointerAvoiding,"Open menu must hold source visibility")
    host.dismissTransientControls()
    require(!host.menuTracking,"Collapse must exit menu mode")
}
host.openSceneMenu()
let dial=host.sceneMenuWindow!.contentView! as! SceneDialSurface
dial.stopAnimation(); dial.render(at:ProcessInfo.processInfo.systemUptime+1)
let clothesAngle=SceneSemicircleLayout.angle(index:1,count:5)
dial.select(at:dial.point(at:NSPoint(x:94*cos(clothesAngle),y:94*sin(clothesAngle))))
dial.render(at:ProcessInfo.processInfo.systemUptime+1)
require(dial.active == 1 && dial.child == -1 && !dial.childFocus && dial.children.isEmpty,"Hover highlights decoration without replacing the main menu")
require(commands == 0 && frozen.isEqual(to:host.store.state) && host.presentation.route == nil,"Hover must not buy, place, or open a page")
dial.roots[1].performClick(nil)
dial.render(at:ProcessInfo.processInfo.systemUptime+1)
require(dial.children.map{ $0.title } == ["神龛","供具"],"Decoration must show two categories")
for (index,item) in dial.children.enumerated() {
    let a=SceneSemicircleLayout.angle(index:index,count:2)
    let p=dial.point(at:NSPoint(x:94*cos(a),y:94*sin(a)))
    dial.select(at:p); dial.render(at:ProcessInfo.processInfo.systemUptime+1)
    require(dial.active == 1 && dial.child == index && dial.hitTest(p) === item,"Pointer must hit each displayed category")
    require(dial.bounds.contains(item.frame),"Expanded item must remain inside its transparent window")
}
dial.roots[1].performClick(nil)
require(dial.childFocus && dial.child == -1,"Clicking a parent must focus children without preselecting or executing one")
let left=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:3,
    windowNumber:host.sceneMenuWindow!.windowNumber,context:nil,characters:"",charactersIgnoringModifiers:"",isARepeat:false,keyCode:123)!
dial.keyDown(with:left)
require(dial.child == 1,"First reverse navigation must select the final category")
let right=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:4,
    windowNumber:host.sceneMenuWindow!.windowNumber,context:nil,characters:"",charactersIgnoringModifiers:"",isARepeat:false,keyCode:124)!
dial.keyDown(with:right)
require(dial.child == -1,"Forward navigation must wrap through the back button")
require(dial.back() && dial.active == -1 && !dial.childFocus,"Esc from children returns to the parent wheel")
dial.roots[1].performClick(nil); dial.children[1].performClick(nil)
require(!host.menuTracking && host.presentation.route == "装扮" && host.store.shopControls.category == "供具" && host.store.shopControls.selectedID == nil,"Category click must open utensils without selecting an item")
require(commands == 0 && frozen.isEqual(to:host.store.state),"Preview must never imply a purchase or placement")
host.dismissPanel(); host.openSceneMenu()
let allDial=host.sceneMenuWindow!.contentView! as! SceneDialSurface
allDial.roots[1].performClick(nil); allDial.children[0].performClick(nil)
require(host.presentation.route == "装扮" && host.store.shopControls.category == "神龛" && host.store.shopControls.selectedID == nil,"Shrine category must open without stale preview")
host.dismissPanel()
host.openSceneMenu()
let menu=host.sceneMenuWindow!
let press=NSEvent.mouseEvent(with:.leftMouseDown,location:NSPoint(x:40,y:30),modifierFlags:[],timestamp:1,
    windowNumber:menu.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
_ = host.handleLocalEvent(press)
require(host.menuTracking,"Local monitor dismissed a menu button before dispatch")
button("设置").performClick(nil)
require(!host.menuTracking && host.sceneAdjustmentActive && host.presentation.route == "设置","Adjustment button must enter settings")
host.dismissPanel(); host.openSceneMenu(); button("虫瓶").performClick(nil)
require(!host.menuTracking && host.presentation.route == "虫瓶","Route button did not open bottle")
host.dismissPanel(); host.openSceneMenu(); host.dismissTransientControls()
require(!host.menuTracking,"Outside press must close popup")
host.openSceneMenu(); host.applicationDidResignActive(Notification(name:NSApplication.didResignActiveNotification))
require(!host.menuTracking,"Application focus loss must close popup")
host.openSceneMenu(); host.windowDidResignKey(Notification(name:NSWindow.didResignKeyNotification,object:menu))
require(!host.menuTracking,"Popup key loss must close popup")
let native=NSMenu()
host.menuWillOpen(native)
let nativeWindow=NSWindow(contentRect:NSRect(x:900,y:200,width:220,height:386),styleMask:[.borderless],backing:.buffered,defer:false)
nativeWindow.isReleasedWhenClosed=false
let sliderPress=NSEvent.mouseEvent(with:.leftMouseDown,location:NSPoint(x:40,y:40),modifierFlags:[],timestamp:2,
    windowNumber:nativeWindow.windowNumber,context:nil,eventNumber:2,clickCount:1,pressure:1)!
_ = host.handleLocalEvent(sliderPress)
require(host.menuTracking,"Dismissing the scene popup must not clear the active menu-bar slider's tracking")
host.menuDidClose(native)
require(!host.menuTracking,"Native menu close must release its own tracking")
require(!menu.isVisible && !host.panel.isVisible && host.store.process == nil,"No visible windows or worker allowed")
print("PASS: actual semicircle petals, four shrine corners, primary fortune, two category click/focus, no mutation on hover, routes and dismissal; NO_VISIBLE_WINDOWS_NO_WORKER")
'''.replace('host.overlay.frame.center','NSPoint(x:host.overlay.frame.midX,y:host.overlay.frame.midY)'))

    def test_settings_route_keeps_pointer_access_until_dismissal(self):
        # Deliberately uses only pre-fix APIs: its first red is a behavior failure,
        # not merely a missing SceneAdjustmentHandle declaration.
        self._run_harness('settings access lifecycle', r'''
let host = hostAt("settings-existing-api")
require(host.scene.subject(at:NSPoint(x:105,y:90)) != nil,"Fixture must hit a real subject")
require(host.store.pointerAvoidance && host.store.sceneTransparency == 100,"Expected fresh saved defaults")
host.updatePointer(near)
require(host.pointerAvoiding && host.scene.alphaValue == 0 && host.overlay.ignoresMouseEvents,
    "Office avoidance baseline must remain enabled")
host.openRoute("设置")
require(host.presentation.route == "设置","Settings route was not opened")
host.updatePointer(near)
require(!host.pointerAvoiding && host.scene.alphaValue == 1 && !host.overlay.ignoresMouseEvents,
    "SETTINGS_ACCESS_TRAP: settings opened but subject still disappears and rejects the first click")
host.scene.cancelInteraction()
host.windowDidResignKey(Notification(name:NSWindow.didResignKeyNotification,object:host.overlay))
host.menuDidClose(NSMenu())
host.updatePointer(near)
require(!host.pointerAvoiding && host.scene.alphaValue == 1 && !host.overlay.ignoresMouseEvents,
    "Cancelling a scene gesture or losing overlay key must not end settings adjustment")
host.dismissPanel(); host.updatePointer(near)
require(host.pointerAvoiding && host.scene.alphaValue == 0 && host.overlay.ignoresMouseEvents,
    "Dismissal must restore saved office avoidance without waiting for pointer movement")
require(host.store.pointerAvoidance && host.store.sceneTransparency == 100,
    "Temporary adjustment must not rewrite saved preference values")
require(!host.overlay.isVisible && !host.panel.isVisible && host.store.process == nil,
    "Harness must leave windows unshown and never start a worker")
print("PASS: settings access survives scene/menu/overlay callbacks and ends on dismissal; NO_VISIBLE_WINDOWS_NO_WORKER")
''')

    def test_adjustment_handle_hot_path_geometry_and_host_exits(self):
        self._run_harness('adjustment handle and exits', r'''
var presented = 0, activated = 0
let wasActive = app.isActive
let handle = SceneAdjustmentHandle(present: { window in
    presented += 1
    require(!window.isVisible && !window.isKeyWindow,"Presenter must receive an unshown non-key panel")
})
handle.onActivate = { activated += 1 }
let frame = NSRect(x:200,y:100,width:370,height:190)
let screen = NSRect(x:0,y:0,width:1440,height:900)
handle.update(pointer:away,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
require(!handle.isPresented && presented == 0,"An unrelated desktop point must not summon the handle")
handle.update(pointer:near,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
require(handle.isPresented && handle.window != nil,"Avoiding scene needs an independent adjustment entry")
let target = handle.window!.frame
require(screen.contains(target) && !target.intersects(frame),"Handle must fit the visible screen outside the subject frame")
require(handle.window!.styleMask.contains(.nonactivatingPanel),"Hover entry must not activate another app")
require(handle.window!.alphaValue == 1 && !handle.window!.ignoresMouseEvents,
    "Entry must remain opaque and interactive independently of scene opacity")
func findButton(_ view:NSView?) -> NSButton? {
    guard let view else { return nil }
    if let button = view as? NSButton, button.title == "设置" { return button }
    for child in view.subviews { if let found = findButton(child) { return found } }
    return nil
}
let button = findButton(handle.window!.contentView)
require(button != nil,"Independent panel needs an actual labelled adjustment button")
button!.performClick(nil)
require(activated == 1,"Adjustment button did not invoke its action")
require(app.isActive == wasActive && !handle.window!.isKeyWindow,"Hover and stubbed action must not activate the harness")
handle.update(pointer:near,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
func buttonEvent(_ kind:NSEvent.EventType,_ panel:NSWindow) -> NSEvent {
    NSEvent.mouseEvent(with:kind,location:NSPoint(x:26,y:14),modifierFlags:[],timestamp:10,
        windowNumber:panel.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
button!.mouseDown(with:buttonEvent(.leftMouseDown,handle.window!))
require(activated == 1,"ADJUSTMENT_PRESS_OPENS_TOO_EARLY: mouse-down must leave room for a drag")
handle.update(pointer:near,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:1)
require(handle.isPresented,"Held own adjustment press must survive pointer polling")
button!.mouseUp(with:buttonEvent(.leftMouseUp,handle.window!))
require(activated == 2,"Short release must activate exactly once")

// Every sampled point is on the continuous route from scene to its fixed handle.
let end = NSPoint(x:target.midX,y:target.midY)
for step in 0...40 {
    let t = CGFloat(step)/40
    let point = NSPoint(x:near.x+(end.x-near.x)*t,y:near.y+(end.y-near.y)*t)
    handle.update(pointer:point,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
    require(handle.isPresented && handle.window!.frame == target,
        "Handle disappeared in its bridge region or chased the pointer")
}
handle.update(pointer:away,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
require(!handle.isPresented,"Leaving scene, bridge and handle must dismiss the entry")
handle.update(pointer:end,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
require(!handle.isPresented,"An already dismissed handle must not reactivate from its stale target area")
for pressed in [1,2,4] {
    handle.update(pointer:near,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:0)
    require(handle.isPresented,"Fixture re-entry failed")
    handle.update(pointer:near,sceneFrame:frame,screens:[screen],enabled:true,buttonsPressed:pressed)
    require(!handle.isPresented,"Pressed Finder/system mouse must not meet an adjustment interceptor")
}
handle.update(pointer:near,sceneFrame:frame,screens:[screen],enabled:false,buttonsPressed:0)
require(!handle.isPresented,"Disabled entry must remain dismissed")

let screens = [NSRect(x:-1600,y:-100,width:1600,height:900),screen]
for current in screens {
    for scale in [CGFloat(0.2),CGFloat(0.75),CGFloat(1.5)] {
        let size=NSSize(width:370*scale,height:190*scale)
        for origin in [NSPoint(x:current.minX,y:current.minY),
                       NSPoint(x:current.maxX-size.width,y:current.minY),
                       NSPoint(x:current.minX,y:current.maxY-size.height),
                       NSPoint(x:current.maxX-size.width,y:current.maxY-size.height)] {
            let placed=NSRect(origin:origin,size:size)
            handle.dismiss()
            handle.update(pointer:NSPoint(x:placed.midX,y:placed.midY),sceneFrame:placed,
                          screens:screens,enabled:true,buttonsPressed:0)
            require(handle.isPresented && current.contains(handle.window!.frame),
                "Screen edge/negative-origin layout left the entry off its scene screen")
            require(!handle.window!.frame.intersects(placed),"Screen edge fallback covered the original scene")
        }
    }
}
handle.dismiss()

let host=hostAt("host-new-api")
host.adjustmentHandle=SceneAdjustmentHandle(present:{ _ in })
host.updatePointer(near,buttonsPressed:0)
require(host.adjustmentHandle.isPresented,"Host did not route avoided hover to independent handle")
host.store.setSceneTransparency(0)
host.updatePointer(near,buttonsPressed:0)
require(host.scene.alphaValue == 1 && host.overlay.ignoresMouseEvents && host.adjustmentHandle.isPresented,
    "Zero transparency still passes clicks through and must retain a findable adjustment entry")
host.updatePointer(near,buttonsPressed:1)
require(!host.adjustmentHandle.isPresented,"Host must forward system button state for Finder drags")
host.updatePointer(near,buttonsPressed:0)
let hostButton=findButton(host.adjustmentHandle.window!.contentView)!
let initialPress=buttonEvent(.leftMouseDown,host.adjustmentHandle.window!)
_ = host.handleLocalEvent(initialPress)
require(host.adjustmentHandle.isPresented,
    "Local event monitor dismissed the adjustment button before its view could receive the press")
hostButton.mouseDown(with:initialPress)
host.updatePointer(near,buttonsPressed:1)
hostButton.mouseUp(with:buttonEvent(.leftMouseUp,host.adjustmentHandle.window!))
host.updatePointer(near,buttonsPressed:0)
require(host.sceneAdjustmentActive && !host.pointerAvoiding && !host.overlay.ignoresMouseEvents,
    "Explicit adjustment did not hold subject access")
require(!host.adjustmentHandle.isPresented,"Settings adjustment must hide the redundant hover entry")
host.scene.cancelInteraction()
host.windowDidResignKey(Notification(name:NSWindow.didResignKeyNotification,object:host.overlay))
host.updatePointer(near)
require(host.sceneAdjustmentActive && !host.pointerAvoiding,"Scene gesture cleanup cleared the configuration session")
host.store.setPointerAvoidance(false); host.dismissPanel(); host.updatePointer(near)
require(!host.sceneAdjustmentActive && !host.store.pointerAvoidance && !host.pointerAvoiding,
    "Dismissing adjustment restored a stale preference over the user's new opt-out")
host.store.setPointerAvoidance(true); host.store.setSceneTransparency(100)

func requireRestored(_ name:String) {
    host.updatePointer(near)
    require(!host.sceneAdjustmentActive && host.pointerAvoiding && host.overlay.ignoresMouseEvents
        && host.scene.alphaValue == 0,"\(name) did not restore saved avoidance")
}
host.openRoute("设置"); host.dismissTransientControls(); requireRestored("Outside-click cleanup")
host.openRoute("设置")
host.windowDidResignKey(Notification(name:NSWindow.didResignKeyNotification,object:host.panel))
requireRestored("Settings resign-key")
host.openRoute("设置")
host.applicationDidResignActive(Notification(name:NSApplication.didResignActiveNotification,object:app))
requireRestored("Application resign-active")
host.openRoute("设置")
let escape=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:1,
    windowNumber:host.panel.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",
    isARepeat:false,keyCode:53)!
_ = host.handleLocalEvent(escape); requireRestored("Escape")
host.openRoute("设置"); host.hidePet()
host.updatePointer(near,buttonsPressed:0)
require(!host.sceneAdjustmentActive && !host.adjustmentHandle.isPresented,
    "Hidden pet left an orphaned adjustment entry/session")
require(!host.overlay.isVisible && !host.panel.isVisible && host.store.process == nil,
    "Harness must leave windows unshown and never start a worker")
require(app.isActive == wasActive,"Harness unexpectedly activated the application")
print("PASS: stationary accessible handle, continuous bridge, edges/negative screens, office drags, zero transparency and host exits; NO_VISIBLE_WINDOWS_NO_WORKER")
''')


if __name__ == '__main__':
    unittest.main()
