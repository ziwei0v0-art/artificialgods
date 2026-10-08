"""Real setting binding and scene view, temporary config, no windows or worker."""
from pathlib import Path
import subprocess,tempfile,unittest
from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT=Path(__file__).resolve().parents[1]
class SceneTransparencyTests(unittest.TestCase):
    def test_control_boundaries_restore_and_scene_only(self):
        source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        harness=r'''
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let url=URL(fileURLWithPath:CommandLine.arguments[1])
func hostAt(_ url:URL)->ApplicationHost {
 let host=ApplicationHost()
 host.overlay=OverlayWindow(contentRect:NSRect(x:200,y:100,width:370,height:190),styleMask:[.borderless],backing:.buffered,defer:false)
 host.overlay.isReleasedWhenClosed=false
 host.scene=TianmuView(frame:host.overlay.contentView!.bounds)
 host.overlay.contentView=host.scene;host.scene.attach(window:host.overlay);host.scene.persistLegacyFrame=false
 host.configureSceneActions()
 host.configureTransparency(SceneTransparencyStore(url:url))
 return host
}
let host=hostAt(url)
let actual=SceneTransparencyControl(store:host.store)
assert(host.store.sceneTransparency == 100 && host.scene.alphaValue == 1)
assert(!FileManager.default.fileExists(atPath:url.path))
let hovered=NSPoint(x:305,y:190), away=NSPoint(x:100,y:100)
host.updatePointer(hovered)
assert(host.pointerAvoiding && host.scene.alphaValue == 0 && host.overlay.ignoresMouseEvents,"Invisible subject must pass clicks through")
for (input,want) in [(25.7,25.7),(-5,0),(99,99),(101,100),(Double.nan,100),(Double.infinity,100)] {
 actual.value.wrappedValue=input
 assert(host.store.sceneTransparency == want)
 assert(abs(Double(host.scene.alphaValue)-(1-want/100))<0.001)
 assert(host.overlay.ignoresMouseEvents,"Even partially faded avoidance must not intercept office clicks")
 assert(SceneTransparencyStore(url:url).restore() == want)
}
host.updatePointer(away)
assert(!host.pointerAvoiding && host.scene.alphaValue == 1)
host.store.setPointerAvoidance(false);host.updatePointer(hovered)
assert(host.scene.alphaValue == 1 && !host.overlay.ignoresMouseEvents,"Turning off avoidance restores direct subject interaction")
assert(!SceneTransparencyStore(url:url).restoreAvoidance())
host.store.setPointerAvoidance(true);actual.value.wrappedValue=70
let fresh=hostAt(url)
assert(fresh.store.sceneTransparency == 70 && fresh.store.pointerAvoidance && fresh.scene.alphaValue == 1)
fresh.updatePointer(hovered)
assert(abs(fresh.scene.alphaValue-0.3)<0.001)
// Moving is an explicit exception; a latched drag must not disappear under its pointer.
fresh.manualInteraction=true;fresh.updatePointer(hovered)
assert(!fresh.pointerAvoiding && fresh.scene.alphaValue == 1 && !fresh.overlay.ignoresMouseEvents)
func mouse(_ type:NSEvent.EventType,_ p:NSPoint,_ t:Double)->NSEvent {
 NSEvent.mouseEvent(with:type,location:p,modifierFlags:[],timestamp:t,windowNumber:fresh.overlay.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
fresh.scene.mouseDown(with:mouse(.leftMouseDown,NSPoint(x:105,y:90),10))
fresh.manualInteraction=false;fresh.updatePointer(hovered)
assert(!fresh.pointerAvoiding,"An in-flight gesture must own its mouse until released/cancelled")
fresh.scene.cancelInteraction();fresh.updatePointer(hovered)
assert(fresh.pointerAvoiding && fresh.overlay.ignoresMouseEvents)
let panel=NSHostingView(rootView:actual)
assert(panel.alphaValue == 1)
let blocked=url.deletingLastPathComponent().appendingPathComponent("blocked")
try! "file".write(to:blocked,atomically:true,encoding:.utf8)
host.configureTransparency(SceneTransparencyStore(url:blocked.appendingPathComponent("appearance.json")))
actual.value.wrappedValue=50
assert(host.store.sceneTransparency == 100 && host.store.transparencyError.contains("未保存"))
host.store.setPointerAvoidance(false)
assert(host.store.pointerAvoidance && host.store.transparencyError.contains("未保存"))
// A selected move mode must not survive leaving the application before a press.
app.delegate = fresh
fresh.manualInteraction = true
NotificationCenter.default.post(name:NSApplication.didResignActiveNotification,object:app)
assert(!fresh.manualInteraction, "Leaving before the first drag must re-enable avoidance")
fresh.updatePointer(hovered)
assert(fresh.pointerAvoiding && fresh.overlay.ignoresMouseEvents)
app.delegate = nil
fresh.desktopInsects=DesktopInsects(screens:[DesktopInsectScreen(id:"main",frame:NSRect(x:0,y:0,width:1440,height:900))])
fresh.configureInsects(SceneTransparencyStore(url:url))
assert(fresh.desktopInsects!.windows.allSatisfy { $0.level.rawValue < NSWindow.Level.normal.rawValue })
fresh.store.setInsectsOnTop(true)
assert(fresh.desktopInsects!.windows.allSatisfy { $0.level == .floating && $0.ignoresMouseEvents })
fresh.store.setSceneTransparency(42.3); fresh.store.setPointerAvoidance(false)
let savedAppearance=SceneTransparencyStore(url:url)
assert(savedAppearance.restoreInsectsOnTop() && !savedAppearance.restoreAvoidance() && savedAppearance.restore() == 42.3,"Independent appearance settings must not overwrite each other")
fresh.desktopInsects?.beginCapture()
NotificationCenter.default.post(name:NSApplication.didResignActiveNotification,object:app)
assert(fresh.desktopInsects!.windows.allSatisfy { $0.ignoresMouseEvents })
fresh.desktopInsects?.close()
assert(!host.overlay.isVisible && !fresh.overlay.isVisible && host.store.process == nil)
print("PASS: continuous 0...100 hover opacity, full passthrough, leave restore, opt-out, move override, press lock, isolated persistence and failed write rollback; NO_VISIBLE_WINDOWS_NO_WORKER")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-opacity-test-') as d:
            d=Path(d); (d/'main.swift').write_text(with_desktop_motion_fixture(source+harness))
            (d/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(d/'Scene.swift'),str(ROOT/'native/v1/Presentation.swift'),str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT/'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),str(d/'main.swift'),'-o',str(d/'check')],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(d/'check'),str(d/'state.json.appearance.json')],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);print(run.stdout)
