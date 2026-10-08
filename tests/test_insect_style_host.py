"""Real host/style/sidecar wiring with production art; unshown windows and temporary preferences."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let directory=URL(fileURLWithPath:CommandLine.arguments[1]),tmp=URL(fileURLWithPath:CommandLine.arguments[2])
let art=InsectArtwork(directory:directory)
assert(art.complete,"This check must load both real production styles")
var clockReads=0,now:TimeInterval=37
func hostAt(_ url:URL,_ artwork:InsectArtwork=art)->ApplicationHost {
 let host=ApplicationHost()
 host.overlay=OverlayWindow(contentRect:NSRect(x:200,y:100,width:370,height:190),styleMask:[.borderless],backing:.buffered,defer:false)
 host.overlay.isReleasedWhenClosed=false
 host.scene=TianmuView(frame:host.overlay.contentView!.bounds);host.overlay.contentView=host.scene
 host.scene.attach(window:host.overlay);host.scene.persistLegacyFrame=false
 host.desktopInsects=DesktopInsects(screens:[DesktopInsectScreen(id:"fixture",frame:NSRect(x:0,y:0,width:800,height:600))],renderTime:{clockReads += 1;return now},windowPresenter:{_ in},artwork:artwork)
 host.configureInsects(SceneTransparencyStore(url:url))
 host.desktopInsects!.update(rows:[["id":"fly-9","x":0.5,"y":0.5,"color":"白色"]])
 return host
}
let url=tmp.appendingPathComponent("appearance.json")
let host=hostAt(url)
let control=InsectStyleControl(store:host.store)
var commands=0
host.store.commandSink={ _,_,_ in commands += 1 }
host.store.state=["coins":76,"desktop":[["id":"fly-9","color":"白色","x":0.5,"y":0.5]],"bottle":[]]
let state=NSDictionary(dictionary:host.store.state)
let windows=host.desktopInsects!.windows.map{ObjectIdentifier($0)}
let point=host.desktopInsects!.positions[0].point
let reads=clockReads
assert(host.store.insectStyle == .cute && !FileManager.default.fileExists(atPath:url.path))
control.value.wrappedValue = .realistic
assert(host.store.insectStyle == .realistic && host.desktopInsects!.style == .realistic)
assert(SceneTransparencyStore(url:url).restoreInsectStyle() == .realistic)
assert(clockReads==reads && host.desktopInsects!.positions[0].point==point,"Style save must not advance positions/clock")
assert(host.desktopInsects!.windows.map{ObjectIdentifier($0)} == windows,"Style save must reuse all desktop windows")
assert(commands==0 && state.isEqual(to:host.store.state) && host.store.process==nil)
let fresh=hostAt(url)
assert(fresh.store.insectStyle == .realistic && fresh.desktopInsects!.style == .realistic)
let blocked=tmp.appendingPathComponent("blocked")
try! "file".write(to:blocked,atomically:true,encoding:.utf8)
let failed=hostAt(blocked.appendingPathComponent("appearance.json"))
failed.store.setInsectStyle(.realistic)
assert(failed.store.insectStyle == .cute && failed.desktopInsects!.style == .cute && !failed.store.insectStyleError.isEmpty)
// Missing artwork can alter this run's display, never the user's saved choice.
let savedBefore=try! Data(contentsOf:url)
let missing=hostAt(url,InsectArtwork(directory:tmp.appendingPathComponent("missing")))
assert(missing.store.availableInsectStyles.isEmpty && !missing.store.insectStyleError.isEmpty)
assert(try! Data(contentsOf:url)==savedBefore)
for h in [host,fresh,failed,missing] {
 assert(!h.overlay.isVisible && h.desktopInsects!.windows.allSatisfy{ !$0.isVisible && $0.ignoresMouseEvents })
 assert(h.store.process==nil)
 h.desktopInsects?.close();h.overlay.close()
}
print("PASS native binding→host→atomic sidecar→same layer, reopen, failed write, missing-art saved-choice preservation; NO_VISIBLE_WINDOWS_NO_WORKER_TEMP_PREFERENCES")
'''
class InsectStyleHostTests(unittest.TestCase):
    def test_real_art_save_restore_and_layer_identity(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-insect-host-') as directory:
            folder=Path(directory)
            source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
            (folder/'main.swift').write_text(with_desktop_motion_fixture(source+HARNESS))
            (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            binary=folder/'check'
            names=['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift','TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']
            build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*(str(ROOT/'native/v1'/name) for name in names),str(folder/'main.swift'),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(build.returncode,0,build.stderr)
            result=subprocess.run([str(binary),str(ROOT/'assets/production/insects'),str(folder)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())
