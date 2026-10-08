"""Production menu behavior in unshown AppKit hosts, with memory-only snapshots.

The upstream C/Swift oracle remains in test_scene_dial_geometry.py. These tests
exercise Tianmu's arrangement, actual hit paths, callbacks and redraw lifecycle.
No worker, application startup, real preferences, system input or save is used.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
func require(_ condition:@autoclosure ()->Bool,_ message:String) {
    if !condition() { fputs("FAIL: \(message)\n",stderr); exit(1) }
}
func snapshot() -> [String:Any] {
    ["coins":500,"placed_items":["shrine":"shrine_g1","incense":"incense_burner"],"shop":[
        ["id":"offering_plate","name":"供果盘","slot":"plate","price":12,"owned":false,"placed":false,"can_buy":true],
        ["id":"incense_burner","name":"陶香炉","slot":"incense","price":24,"owned":true,"placed":true,"can_buy":false],
        ["id":"bell","name":"小铜铃","slot":"bell","price":60,"owned":true,"placed":false,"can_buy":false],
        ["id":"shrine_g1","name":"木龛","slot":"shrine","price":120,"owned":true,"placed":true,"can_buy":false],
        ["id":"shrine_g2","name":"彩塑神龛","slot":"shrine","price":360,"owned":false,"placed":false,"can_buy":false]]]
}
func fixtureStore() -> Store {
    let store = Store(); store.state = snapshot()
    store.commandSink = { action,_,_ in require(action == "sale_cancel","Unexpected service command: \(action)") }
    return store
}
func key(_ code:UInt16) -> NSEvent {
    NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:10,windowNumber:0,
        context:nil,characters:"",charactersIgnoringModifiers:"",isARepeat:false,keyCode:code)!
}
func center(_ surface:SceneDialSurface,_ index:Int,_ count:Int) -> NSPoint {
    let a = SceneSemicircleLayout.angle(index:index,count:count)
    return surface.point(at:NSPoint(x:94*cos(a),y:94*sin(a)))
}
func makeSurface(_ direction:SceneMenuDirection = .up,hidden:Bool = false) -> SceneDialSurface {
    let surface = SceneDialSurface(store:fixtureStore(),hidden:hidden,direction:direction)
    surface.stopAnimation(); surface.render(at:ProcessInfo.processInfo.systemUptime+2)
    return surface
}
func fixtureHost() -> ApplicationHost {
    let host = ApplicationHost()
    host.store.state = snapshot()
    host.store.commandSink = { action,_,_ in require(action == "sale_cancel","Unexpected host command: \(action)") }
    host.overlay = OverlayWindow(contentRect:NSRect(x:200,y:100,width:370,height:190),
        styleMask:[.borderless],backing:.buffered,defer:false)
    host.overlay.isReleasedWhenClosed = false
    host.scene = TianmuView(frame:host.overlay.contentView!.bounds)
    host.scene.persistLegacyFrame = false
    host.overlay.contentView = host.scene; host.scene.attach(window:host.overlay)
    applySceneState(host.store.state,to:host.scene)
    host.panel = NSWindow(contentRect:NSRect(x:600,y:100,width:480,height:580),
        styleMask:[.titled,.closable],backing:.buffered,defer:false)
    host.panel.isReleasedWhenClosed = false
    host.availableScreens = { [NSRect(x:0,y:0,width:1440,height:900)] }
    host.panelPresenter = { window in require(!window.isVisible,"Panel must remain unshown") }
    host.overlayPresenter = { window in require(!window.isVisible,"Scene must remain unshown") }
    host.scenePopupPresenter = { window in require(!window.isVisible,"Popup must remain unshown") }
    host.captureFocus = { _,_ in require(false,"No capture activation in geometry checks") }
    host.contextMenu = host.makeSceneMenu()
    return host
}
let operation = CommandLine.arguments[1]
switch operation {
case "hit_regions":
    for direction in SceneMenuDirection.allCases {
        let surface = makeSurface(direction)
        require(surface.bounds.size == SceneSemicircleLayout.size(for:direction),"Compact surface size")
        require(surface.bounds.width*surface.bounds.height < 320*320/2,"Remove surplus transparent canvas")
        require(surface.roots.map(\.title) == ["虫瓶","装扮","计时","设置","退出"],"Primary actions")
        for (index,button) in surface.roots.enumerated() {
            require(surface.bounds.contains(button.frame),"Unclipped root")
            require(button.image != nil,"Production artwork/symbol is available for \(button.title)")
            let p = center(surface,index,surface.roots.count)
            require(surface.hitTest(p) === button,"Actual sector center")
            let painted = button.convert(button.iconCenter,to:surface)
            require(hypot(painted.x-p.x,painted.y-p.y) < 0.01,"Icon stays centered without caption compensation")
            require(button.imagePosition == .imageOnly && button.toolTip == button.title
                && button.accessibilityLabel() == button.title,"Icon keeps hover and accessible labels")
            for i in 0..<24 {
                let angle = Double(i)*Double.pi/12
                require(surface.hitTest(NSPoint(x:p.x+22*cos(angle),y:p.y+22*sin(angle))) === button,
                    "Each sector retains a 44 pt circular click target")
            }
            let boundary = -.pi+Double(index)*Double.pi/Double(surface.roots.count)
            let gap = surface.point(at:NSPoint(x:94*cos(boundary),y:94*sin(boundary)))
            require(surface.hitTest(gap) === surface,"Separator cannot dispatch a neighbor")
        }
        let hub = surface.subviews.compactMap{$0 as? SceneWheelButton}.first{$0.title == "求签"}!
        require(hub.emphasized && hub.frame.size == NSSize(width:60,height:60),"Fortune is the primary center")
        require(hub.image === UIArtifactLibrary.shared.image("divination-vessel"),"Use formal fortune vessel")
        require(surface.hitTest(SceneSemicircleLayout.anchor(for:direction)) === hub,"Fortune hub hit")
        require(hub.iconCenter == NSPoint(x:30,y:30),"Hub icon has no caption offset")
        require(surface.roots.first{$0.title == "计时"}!.image!.isTemplate,"Timer uses a recognizable system symbol")
        require(surface.window == nil,"No visible surface")
    }
case "groups_and_routes":
    let store = fixtureStore(), frozen = NSDictionary(dictionary:snapshot())
    let surface = SceneDialSurface(store:store,hidden:false)
    surface.stopAnimation(); surface.render(at:ProcessInfo.processInfo.systemUptime+2)
    var route = "", group = "", visibility = 0, quit = 0
    surface.onRoute = { route = $0 }; surface.onCollectionGroup = { group = $0 }
    surface.onVisibility = { visibility += 1 }; surface.onQuit = { quit += 1 }
    surface.keyDown(with:key(36)); require(route == "求签","Default action is fortune")
    for button in surface.roots where !["装扮","退出"].contains(button.title) {
        button.performClick(nil); require(route == button.title,"Direct primary callback")
    }
    let clothes = surface.roots.firstIndex{$0.title == "装扮"}!
    surface.select(at:center(surface,clothes,surface.roots.count))
    require(!surface.childFocus && surface.children.isEmpty,"Hover never enters or buys an item")
    surface.roots[clothes].performClick(nil); surface.render(at:ProcessInfo.processInfo.systemUptime+2)
    require(surface.children.map(\.title) == ["神龛","供具"],"Exactly two collection categories")
    require(surface.roots.allSatisfy(\.isHidden),"Second level replaces, rather than enlarges, menu")
    for (index,button) in surface.children.enumerated() {
        require(button.image === CollectionArtwork.shared.currentImage(for:button.title,snapshot:store.state),"Category uses equipped artwork")
        require(button.image != nil && surface.bounds.contains(button.frame),"Visible unclipped category")
        require(surface.hitTest(center(surface,index,surface.children.count)) === button,"Child real hit")
        button.performClick(nil); require(group == button.title,"Category callback")
    }
    require(surface.back(),"Back from collection")
    let quitButton = surface.roots.first{$0.title == "退出"}
    require(quitButton != nil,"Quit is a direct primary action")
    quitButton?.performClick(nil)
    require(quit == 1 && visibility == 0 && !surface.childFocus,"Quit calls its dedicated callback without opening a submenu")
    let hidden = makeSurface(hidden:true)
    hidden.onVisibility = { visibility += 1 }; hidden.onQuit = { quit += 1 }
    hidden.onRoute = { _ in require(false,"Hidden center must restore the scene, not request a fortune") }
    let restore = hidden.subviews.compactMap{$0 as? SceneWheelButton}.first{$0.title == "显示"}
    require(restore != nil,"Hidden subject exposes restoration at the center")
    require(hidden.hitTest(SceneSemicircleLayout.anchor(for:.up)) === restore,"Restore action occupies the hub")
    hidden.keyDown(with:key(36)); require(visibility == 1,"Keyboard activates central scene restoration")
    hidden.roots.first{$0.title == "装扮"}!.performClick(nil)
    hidden.keyDown(with:key(36)); require(!hidden.childFocus,"Hidden collection returns through the hub")
    require(hidden.subviews.compactMap{$0 as? SceneWheelButton}.contains{$0.title == "显示"},"Back restores the hidden-state hub")
    hidden.roots.first{$0.title == "退出"}!.performClick(nil)
    require(quit == 2 && visibility == 1,"Hidden scene preserves direct quit independently of restore")
    require(frozen.isEqual(to:store.state) && store.process == nil,"Navigation does not mutate saved state")
    surface.stopAnimation(); hidden.stopAnimation()
case "keyboard":
    let surface = makeSurface()
    var dismissed = 0, route = ""
    surface.onDismiss = { dismissed += 1 }; surface.onRoute = { route = $0 }
    surface.keyDown(with:key(123)); require(surface.active == 4,"Reverse from hub starts final action")
    surface.keyDown(with:key(124)); require(surface.active == -1,"Forward includes hub")
    surface.keyDown(with:key(49)); require(route == "求签","Space activates default fortune")
    surface.roots.first{$0.title == "装扮"}!.performClick(nil)
    surface.keyDown(with:key(123)); require(surface.child == 1,"Reverse begins final category")
    surface.keyDown(with:key(124)); require(surface.child == -1,"Forward includes back")
    surface.keyDown(with:key(36)); require(!surface.childFocus,"Return on back returns to main")
    surface.roots.first{$0.title == "装扮"}!.performClick(nil)
    surface.keyDown(with:key(53)); require(!surface.childFocus && dismissed == 0,"First Esc returns")
    surface.keyDown(with:key(53)); require(dismissed == 1,"Next Esc closes")
    surface.stopAnimation()
case "placement":
    for screen in [NSRect(x:0,y:0,width:1440,height:900),NSRect(x:-1920,y:120,width:1920,height:1080),NSRect(x:0,y:0,width:390,height:844)] {
        for x in [screen.minX+4,screen.midX-50,screen.maxX-104] {
            for y in [screen.minY+4,screen.midY-60,screen.maxY-124] {
                let subject = NSRect(x:x,y:y,width:100,height:120)
                let p = SceneSemicircleLayout.placement(near:subject,in:screen)
                require(screen.contains(p.frame) && !p.frame.intersects(subject),"Keep all menu art visible beside shrine")
                let nearest = NSPoint(x:max(subject.minX,min(p.anchor.x,subject.maxX)),y:max(subject.minY,min(p.anchor.y,subject.maxY)))
                let gap = hypot(p.anchor.x-nearest.x,p.anchor.y-nearest.y)-SceneSemicircleLayout.hubRadius
                require(gap >= 4 && gap <= 15,"Actual hub stays close to shrine: \(gap)")
            }
        }
        let status = NSRect(x:screen.midX-10,y:screen.maxY,width:20,height:22)
        let p = SceneSemicircleLayout.placement(near:status,in:screen,preferred:.down)
        require(p.direction == .down && screen.contains(p.frame),"Status-menu popup fits below menu bar")
    }
case "host_placement":
    let host = fixtureHost(), screen = NSRect(x:0,y:0,width:1440,height:900)
    for origin in [NSPoint(x:0,y:0),NSPoint(x:1271,y:0),NSPoint(x:0,y:813),NSPoint(x:1271,y:813)] {
        host.overlay.setFrame(NSRect(origin:origin,size:NSSize(width:169,height:87)),display:false)
        let shrine = host.overlay.convertToScreen(host.scene.convert(host.scene.shrineBounds,to:nil))
        let expected = SceneSemicircleLayout.placement(near:shrine,in:screen)
        host.openSceneMenu()
        let window = host.sceneMenuWindow!, surface = window.contentView as! SceneDialSurface
        // AppKit rounds NSWindow origins to backing pixels. Do not mistake
        // that subpoint alignment for an anchor change.
        require(abs(window.frame.minX-expected.frame.minX) <= 1 && abs(window.frame.minY-expected.frame.minY) <= 1
                && surface.direction == expected.direction,"Host anchors actual shrine rather than transparent overlay")
        require(window.frame.size == surface.bounds.size && screen.contains(window.frame),"Host passes compact oriented size")
        require(!window.isVisible && host.menuTracking,"Presenter keeps test invisible while menu state is active")
        host.dismissTransientControls(); require(!host.menuTracking,"Dismiss releases menu mode")
    }
    host.openStatusMenu() // Missing status item takes the same safe scene route.
    require(host.sceneMenuWindow != nil && !host.sceneMenuWindow!.isVisible,"Status fallback remains unshown")
    host.dismissSceneMenu()
    require(host.store.process == nil && !host.overlay.isVisible && !host.panel.isVisible,"No worker or visible windows")
case "host_categories":
    let host = fixtureHost(), frozen = NSDictionary(dictionary:snapshot())
    for group in ["神龛","供具"] {
        host.openSceneMenu()
        let surface = host.sceneMenuWindow!.contentView as! SceneDialSurface
        surface.roots.first{$0.title == "装扮"}!.performClick(nil)
        surface.children.first{$0.title == group}!.performClick(nil)
        require(!host.menuTracking && host.presentation.route == "装扮","Category opens collection and closes menu")
        require(host.store.shopControls.showingCategory && host.store.shopControls.category == group,"Host selects requested category")
        require(host.store.shopControls.selectedID == nil,"Category has no stale item preview")
        host.dismissPanel()
    }
    host.openSceneMenu()
    (host.sceneMenuWindow!.contentView as! SceneDialSurface).roots.first{$0.title == "虫瓶"}!.performClick(nil)
    require(host.presentation.route == "虫瓶" && !host.menuTracking,"Bottle route remains direct")
    host.dismissPanel()
    require(frozen.isEqual(to:host.store.state) && host.store.process == nil,"Category navigation is memory-only")
case "icon_only_render":
    func raster(_ button:SceneWheelButton) -> Data {
        let width = Int(ceil(button.bounds.width))*2, height = Int(ceil(button.bounds.height))*2
        let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:width,pixelsHigh:height,
            bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        let context = NSGraphicsContext(bitmapImageRep:bitmap)!
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = context
        context.cgContext.clear(CGRect(x:0,y:0,width:width,height:height)); context.cgContext.scaleBy(x:2,y:2)
        button.draw(button.bounds); NSGraphicsContext.restoreGraphicsState()
        return Data(bytes:bitmap.bitmapData!,count:bitmap.bytesPerRow*bitmap.pixelsHigh)
    }
    func checkIconOnly(_ surface:SceneDialSurface) {
        for button in surface.subviews.compactMap({$0 as? SceneWheelButton}) where !button.isHidden {
            let unlabeled = SceneWheelButton(frame:button.frame)
            unlabeled.image = button.image; unlabeled.imagePosition = .imageOnly
            unlabeled.shape = button.shape.copy() as! NSBezierPath
            unlabeled.iconCenter = button.iconCenter; unlabeled.iconSide = button.iconSide
            unlabeled.selected = button.selected; unlabeled.checked = button.checked
            unlabeled.emphasized = button.emphasized; unlabeled.opacity = button.opacity
            require(raster(button) == raster(unlabeled),"No permanent caption is painted for \(button.title)")
            require(button.toolTip == button.title && button.accessibilityLabel() == button.title,
                "Every icon still has an accessible and hover label")
        }
    }
    for hidden in [false,true] {
        let surface = makeSurface(hidden:hidden); checkIconOnly(surface)
        surface.roots.first{$0.title == "装扮"}!.performClick(nil)
        surface.stopAnimation(); surface.render(at:ProcessInfo.processInfo.systemUptime+2)
        checkIconOnly(surface); surface.stopAnimation()
    }
case "glass_and_local_motion":
    let surface = makeSurface()
    let glass = surface.subviews.compactMap { $0 as? NSVisualEffectView }
    require(glass.count == 8,"Every root, category and hub has a masked native glass surface")
    for effect in glass where !effect.isHidden {
        require(effect.blendingMode == .behindWindow && effect.state == .active,"Desktop backdrop is the native blur source")
        require(effect.maskImage != nil && effect.alphaValue < 0.85,"Glass is shaped and light")
        let bitmap=NSBitmapImageRep(data:effect.maskImage!.tiffRepresentation!)!
        require(bitmap.colorAt(x:0,y:0)!.alphaComponent < 0.01,"Mask leaves frame corners transparent")
        require(bitmap.colorAt(x:bitmap.pixelsWide/2,y:bitmap.pixelsHigh/2)!.alphaComponent > 0.9,"Mask preserves the visible petal center")
        require(effect.hitTest(effect.frame.origin) == nil,"Blur surface never steals hit testing")
    }
    let emerging=SceneDialSurface(store:fixtureStore(),hidden:false)
    emerging.stopAnimation()
    let opened=Mirror(reflecting:emerging).children.first{$0.label == "openedAt"}!.value as! Double
    emerging.render(at:opened+0.12)
    let early=emerging.roots[4].frame, earlyIcon=emerging.roots[4].iconSide
    emerging.render(at:opened+1)
    require(emerging.roots[4].frame.width > early.width*1.2 && emerging.roots[4].iconSide > earlyIcon*1.2,
            "Staggered reveal changes local geometry and icon size, not only alpha")
    emerging.stopAnimation()
    let button = surface.roots[2], oldFrame = button.frame, oldIcon = button.iconSide
    let c = center(surface,2,surface.roots.count)
    surface.select(at:c)
    let now = ProcessInfo.processInfo.systemUptime+4
    for i in 0..<30 { surface.render(at:now+Double(i)/60) }
    require(button.frame.width > oldFrame.width*1.035 && button.iconSide > oldIcon*1.1,"Hover lifts both local petal scale and icon scale")
    require(surface.bounds.contains(button.frame),"Lifted petal stays inside compact canvas")
    let painted = button.convert(button.iconCenter,to:surface)
    require(hypot(painted.x-c.x,painted.y-c.y) > 3,"Hover moves locally outward")
    surface.roots[1].performClick(nil);surface.render(at:now+3)
    let visibleGlass=glass.filter { !$0.isHidden }
    require(visibleGlass.count == 3,"Only two child petals and hub retain backdrop")
    for child in surface.children {
        require(child.frame.width*child.frame.height < 6200,"Collection is two petals, not opaque quarter panels")
    }
    surface.stopAnimation()
case "idle_redraw":
    let surface = SceneDialSurface(store:fixtureStore(),hidden:false)
    func timerRunning() -> Bool {
        let timer = Mirror(reflecting:surface).children.first{$0.label == "ticker"}?.value as? Timer
        return timer?.isValid == true
    }
    func settle() {
        let start = ProcessInfo.processInfo.systemUptime
        for frame in 1...90 { surface.render(at:start+Double(frame)/60) }
    }
    func quiet(_ message:String) {
        require(!timerRunning(),message)
    }
    require(timerRunning(),"Opening has an active animation timer")
    settle(); quiet("Settled opening must stop 60 Hz redraws")
    let p = center(surface,0,surface.roots.count)
    surface.select(at:p)
    require(surface.roots[0].selected,"Hover resumes immediate visual feedback")
    require(timerRunning(),"Hover restarts animation timer")
    settle(); quiet("Settled hover must stop redraws")
    let shapes = surface.roots.map { ObjectIdentifier($0.shape) }
    surface.select(at:p)
    require(surface.roots.map{ObjectIdentifier($0.shape)} == shapes && !timerRunning(),"Same hover target must not recreate or invalidate unchanged art")
    surface.keyDown(with:key(124)); require(surface.active == 1,"Keyboard wakes selection")
    require(timerRunning(),"Keyboard restarts animation timer")
    settle(); quiet("Settled keyboard selection must stop redraws")
    surface.keyDown(with:key(36)); require(surface.childFocus,"Keyboard opens collection")
    settle(); quiet("Settled secondary menu must stop redraws")
    surface.back(); settle(); quiet("Returning to main settles again")
    surface.stopAnimation(); require(surface.window == nil,"No visible window used for performance assertion")
default: fatalError("Unknown case")
}
print("PASS: \(operation); NO_VISIBLE_WINDOWS_NO_WORKER_NO_SAVE_ACCESS")
'''


class SemicircleMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-semicircle-menu-')
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        source = (ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        (folder/'main.swift').write_text(source+HARNESS)
        (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        names = ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift',
                 'TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
        for name in names:
            shutil.copy2(ROOT/'native/v1'/name,folder/name)
        for art in ['scene','A01','ui','bottle']:
            shutil.copytree(ROOT/'assets/production'/art,folder/'art'/art)
        cls.binary = folder/'check'
        build = subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),
                                *(str(folder/name) for name in names),str(folder/'main.swift'),'-o',str(cls.binary)],
                               capture_output=True,text=True,timeout=150)
        if build.returncode:
            raise AssertionError('Production menu host failed compilation:\n'+build.stderr)

    def check(self,case):
        run = subprocess.run([str(self.binary),case],capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,case+':\n'+run.stdout+run.stderr)
        self.assertIn('NO_VISIBLE_WINDOWS_NO_WORKER_NO_SAVE_ACCESS',run.stdout)

    def test_glass_masks_and_local_hover_motion(self): self.check('glass_and_local_motion')

    def test_actual_semicircle_hit_regions_and_formal_art(self): self.check('hit_regions')
    def test_collection_direct_quit_and_hidden_restore_preserve_state(self): self.check('groups_and_routes')
    def test_keyboard_cycles_include_fortune_and_back(self): self.check('keyboard')
    def test_edges_negative_monitor_and_status_menu_placement(self): self.check('placement')
    def test_production_host_uses_shrine_anchor_and_oriented_size(self): self.check('host_placement')
    def test_production_host_opens_requested_collection_category(self): self.check('host_categories')
    def test_all_menu_levels_paint_icons_only_with_accessible_labels(self): self.check('icon_only_render')
    def test_idle_animation_stops_and_input_restarts_it(self): self.check('idle_redraw')


if __name__ == '__main__': unittest.main()
