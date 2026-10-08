"""Placement with synthetic display geometry, no app launch or saved game data."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScenePlacementEnvelopeTests(unittest.TestCase):
    def test_art_edges_dock_space_menu_bar_and_recovery(self):
        harness = r'''
import AppKit
func require(_ value:@autoclosure()->Bool,_ message:String) {
    if !value() { fputs("FAIL: \(message)\n",stderr); exit(1) }
}
let full=NSRect(x:0,y:0,width:1440,height:900)
let work=NSRect(x:0,y:90,width:1440,height:786)
let screen=scenePlacementScreen(frame:full,visibleFrame:work)
require(screen == NSRect(x:0,y:0,width:1440,height:876),"Dock space must be available but the top menu bar reserved")
let side=scenePlacementScreen(frame:full,visibleFrame:NSRect(x:80,y:0,width:1360,height:876))
require(side == screen,"Side Dock must not reserve a full-height strip")
let art=NSRect(x:40.0/370,y:10.0/190,width:280.0/370,height:170.0/190)
let bottom=fitOverlayFrame(NSRect(x:300,y:-90,width:370,height:190),screens:[screen],contentBounds:art)
require(bottom == NSRect(x:300,y:-10,width:370,height:190),"Transparent bottom margin must leave screen so visible feet can reach y=0")
let left=fitOverlayFrame(NSRect(x:-800,y:120,width:370,height:190),screens:[screen],contentBounds:art)
require(left.minX == -40,"Transparent left margin must not hold visible art away from screen edge")
let upperRight=fitOverlayFrame(NSRect(x:1400,y:850,width:370,height:190),screens:[screen],contentBounds:art)
require(upperRight == NSRect(x:1120,y:696,width:370,height:190),"Visible art must remain completely below menu bar and inside screen right edge")
let small=scaledOverlayFrame(bottom,percent:25,screens:[screen],contentBounds:art)
require(abs(sceneScalePercent(small)-25)<0.001,"Art bounds must not change requested continuous scale")
let store=WindowPlacementStore(url:URL(fileURLWithPath:CommandLine.arguments[1]))
try! store.save(bottom)
require(store.restore(screens:[screen],contentBounds:art) == bottom,"Restore must retain the intentional transparent margin outside the screen")
let negative=NSRect(x:-1200,y:-250,width:1200,height:760)
let recovered=store.restore(screens:[negative],contentBounds:art)
let body=NSRect(x:recovered.minX+40,y:recovered.minY+10,width:280,height:170)
require(negative.contains(body),"Disconnected-screen recovery must keep the complete visible art findable")
let invalid=fitOverlayFrame(bottom,screens:[screen],contentBounds:NSRect(x:Double.nan,y:0,width:1,height:1))
require(screen.contains(invalid),"Invalid artwork metadata must conservatively recover full canvas")
print("PASS: Dock/bottom/side freedom, art-only edge constraints, menu bar protection, scale, isolated restore and disconnected monitor")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-art-placement-') as directory:
            folder=Path(directory)
            (folder/'main.swift').write_text(harness)
            build=subprocess.run(['swiftc',str(ROOT/'native/v1/WindowPlacement.swift'),str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(folder/'check'),str(folder/'placement.json')],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout.strip())

    def test_production_art_envelope_is_stable_across_motion(self):
        scene=(ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        harness=r'''
let app=NSApplication.shared; app.setActivationPolicy(.prohibited)
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let view=TianmuView(frame:NSRect(x:0,y:0,width:370,height:190))
view.attendantArtwork=AttendantArtwork.load(from:root.appendingPathComponent("assets/production/A01"))
view.shrineArtwork=ShrineArtwork.load(from:root.appendingPathComponent("assets/production/scene"))
assert(view.attendantArtwork != nil && view.shrineArtwork != nil,"Production read-only art must load")
let envelope=view.placementUnitBounds
assert(envelope.minX > 0.08 && envelope.minY >= 0 && envelope.maxX <= 1 && envelope.maxY <= 1,
    "Stable bounds must remove the authored empty left margin without extending beyond rendered canvas")
for (index,action) in ["walk","sweep","read","rest","practice","offer","catch","bell","idle"].enumerated() {
    let time=Double(index+1)*5
    view.updateAnimation(elapsed:time)
    assert(view.applyRoutine(["action":action,"action_serial":index+1,"action_elapsed":0.0,
        "action_duration":4.0,"progress":0.0,"fruit_stage":"fresh"]))
    for offset in [0.0,0.25,0.5,0.75,1.0] {
        view.updateAnimation(elapsed:time+offset)
        assert(view.placementUnitBounds == envelope,"Placement must never change with animation or current walking pose")
    }
}
view.setFrameSize(NSSize(width:74,height:38))
assert(view.placementUnitBounds == envelope,"Normalized placement must stay stable at minimum size")
view.setFrameSize(NSSize(width:555,height:285))
assert(view.placementUnitBounds == envelope,"Normalized placement must stay stable at maximum size")
print("PASS: read-only production artwork, stable envelope across nine actions and 20/150 percent size; unit=\(envelope); NO_VISIBLE_WINDOWS_NO_WORKER")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-art-envelope-') as directory:
            folder=Path(directory); (folder/'main.swift').write_text(scene+harness)
            build=subprocess.run(['swiftc',str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True,timeout=45)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(folder/'check'),str(ROOT)],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout.strip())
