"""Actual native setting binding and save-before-display order, no worker or visible UI."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let store=Store()
store.availableInsectStyles = Set(InsectStyle.allCases)
let control=InsectStyleControl(store:store)
var writes:[InsectStyle]=[]
var commands=0
store.commandSink={ _,_,_ in commands += 1 }
store.state=["desktop":[["id":"fly-9","color":"白色","x":0.4,"y":0.6]],"coins":76,"bottle":[],"sold_ids":[]]
let before=NSDictionary(dictionary:store.state)
store.onInsectStyleChange={ style in
 assert(store.insectStyle == .cute,"The selected setting must not change before persistence succeeds")
 writes.append(style)
}
switch CommandLine.arguments[1] {
case "binding":
 control.value.wrappedValue = .realistic
 assert(writes == [.realistic] && store.insectStyle == .realistic && store.insectStyleError.isEmpty)
 control.value.wrappedValue = .realistic
 assert(writes.count == 1,"Selecting the same style does not write again")
case "failed_write":
 store.onInsectStyleChange={ _ in throw NSError(domain:"test",code:1) }
 control.value.wrappedValue = .realistic
 assert(store.insectStyle == .cute && !store.insectStyleError.isEmpty)
case "unavailable":
 store.availableInsectStyles=[.cute]
 control.value.wrappedValue = .realistic
 assert(store.insectStyle == .cute && writes.isEmpty && !store.insectStyleError.isEmpty)
case "unconfigured":
 store.onInsectStyleChange=nil
 control.value.wrappedValue = .realistic
 assert(store.insectStyle == .cute && writes.isEmpty && !store.insectStyleError.isEmpty)
default: fatalError("Unknown case")
}
assert(commands==0 && before.isEqual(to:store.state) && store.process==nil)
print("PASS: \(CommandLine.arguments[1]); NO_WINDOWS_NO_WORKER_NO_SAVE")
'''
class InsectStyleControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='tianmu-insect-setting-')
        cls.addClassCleanup(cls.temp.cleanup)
        folder=Path(cls.temp.name)
        source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        (folder/'main.swift').write_text(source+HARNESS)
        (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        cls.binary=folder/'check'
        paths=['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']
        if (ROOT/'native/v1/InsectArtwork.swift').exists(): paths.append('InsectArtwork.swift')
        build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*(str(ROOT/'native/v1'/p) for p in paths),str(folder/'main.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
        if build.returncode: raise AssertionError(build.stderr)

def install_case(name):
    def test(self):
        result=subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout.strip())
    setattr(InsectStyleControlTests,'test_'+name,test)
for name in ['binding','failed_write','unavailable','unconfigured']: install_case(name)
