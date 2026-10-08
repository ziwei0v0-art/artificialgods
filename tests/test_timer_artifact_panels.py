"""Actual compact numeric timer views rendered offscreen with synthetic snapshots."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
let app=NSApplication.shared; app.setActivationPolicy(.prohibited)
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let out=URL(fileURLWithPath:CommandLine.arguments[2])
UIArtifactLibrary.shared=UIArtifactLibrary(resourceRoot:root.appendingPathComponent("assets/production/ui"))
let store=Store()
store.commandSink={ _,_,done in done?(true) }
func snapshot(_ status:String,_ readout:String,mode:String="countdown") {
    let state:[String:Any] = ["ok":true,"state":["timer":["mode":mode,"status":status,"readout":readout,
        "clock_readout":"13:20:30\n午正一刻","countdown_seconds":300,"remaining_seconds":150,
        "elapsed_seconds":150,"work_seconds":1500,"break_seconds":300]]]
    store.receive(try! JSONSerialization.data(withJSONObject:state)+Data([10]))
}
func require(_ condition:@autoclosure()->Bool,_ message:String) {
    if !condition() { fputs("FAIL: \(message)\n",stderr); exit(1) }
}
func imageViews(_ view:NSView)->[NSImageView] {
    (view as? NSImageView).map { [$0] } ?? view.subviews.flatMap(imageViews)
}
func verify(_ view:TimerControlPanelView) {
    view.layoutSubtreeIfNeeded()
    require(view.readout.frame.width >= 240 && (view.readout.font?.pointSize ?? 0) >= 33,"Time must be readable without a decorative artifact shrinking the digits")
    let buttons=view.subviews.compactMap { $0 as? NSButton }.filter { !$0.isHidden }
    for (index,button) in buttons.enumerated() {
        require(view.bounds.contains(button.frame),"Timer action lies outside its visible panel")
        require(button.frame.width >= 28 && button.frame.height >= 28,"Timer action needs a reliable hit target")
        for other in buttons.dropFirst(index+1) { require(!button.frame.intersects(other.frame),"Timer controls must not cover each other") }
        require(!button.frame.intersects(view.readout.frame),"Timer controls must never cover current time")
    }
    for control in [view.primaryButton!,view.endButton!,view.expandButton!,view.closeButton!] {
        require(control.image != nil && control.imagePosition != .noImage,"Core controls must retain understandable icons with accessible short labels")
        require(!(control.toolTip ?? "").isEmpty && !(control.accessibilityLabel() ?? "").isEmpty,"Icons must retain hover and accessibility meanings")
    }
}
func render(_ view:TimerControlPanelView,_ name:String) {
    let window=NSWindow(contentRect:view.bounds,styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false; window.contentView=view
    view.layoutSubtreeIfNeeded()
    let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    try! bitmap.representation(using:.png,properties:[:])!.write(to:out.appendingPathComponent(name+".png"))
    require(!window.isVisible,"Offscreen rendering must never show a window")
}
snapshot("running","02:30")
let quick=TimerControlPanelView(controls:store.timerControls,surface:.quick)
let detached=TimerControlPanelView(controls:store.timerControls,surface:.detached)
verify(quick); verify(detached); render(quick,"quick-running"); render(detached,"detached-running")
detached.editDurationButton!.performClick(nil)
verify(detached); render(detached,"detached-input")
detached.editDurationButton!.performClick(nil)
snapshot("paused","02:30")
verify(quick); verify(detached)
require(quick.primaryButton.toolTip == "继续" && detached.primaryButton.accessibilityLabel() == "继续","Paused icon must describe its actual resume action")
render(quick,"quick-paused")
snapshot("idle","13:20:30",mode:"clock")
verify(quick); verify(detached); render(quick,"quick-clock"); render(detached,"detached-clock")
snapshot("finished","00:00",mode:"pomodoro")
verify(quick); verify(detached); render(quick,"quick-pomodoro-finished"); render(detached,"detached-pomodoro-finished")
snapshot("running","23:59:59")
verify(quick); verify(detached); render(quick,"quick-long-duration"); render(detached,"detached-long-duration")
snapshot("running","02:30")
quick.presetButtons[1].performClick(nil)
verify(quick); render(quick,"quick-replacement")
require(!quick.confirmButton.isHidden && !quick.cancelButton.isHidden,"Existing replacement gate must remain present")
store.timerControls.cancelReplacement(from:.quick)
store.timerControls.start(TimerStartRequest(mode:"stopwatch"),from:.detached)
verify(detached); render(detached,"detached-replacement")
require(!detached.confirmButton.isHidden && !detached.cancelButton.isHidden,"Detached replacement gate must remain intact")
require(store.process == nil,"No worker or real save may be touched")
print("PASS: readable numbers, icon/accessibility semantics, collision-free controls/readout, both replacement gates, twelve offscreen renders; NO_VISIBLE_WINDOWS_NO_WORKER")
'''

class TimerArtifactPanelsTests(unittest.TestCase):
    def test_actual_art_native_controls_and_confirmation_geometry(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-timer-art-') as directory:
            folder=Path(directory)
            host=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
            scene=(ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0]
            (folder/'main.swift').write_text(host+HARNESS); (folder/'Scene.swift').write_text(scene)
            sources=['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift','TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
            for name in sources: (folder/name).write_text((ROOT/'native/v1'/name).read_text())
            build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*[str(folder/s) for s in sources],str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True,timeout=90)
            self.assertEqual(build.returncode,0,build.stderr)
            output=ROOT/'evidence/1.0/174-timer/previews'
            output.mkdir(parents=True,exist_ok=True)
            run=subprocess.run([str(folder/'check'),str(ROOT),str(output)],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout.strip())
