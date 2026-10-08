"""Native startup and recovery controls; recorded transport, no process or windows."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let store=Store()
var requests:[[String:Any]]=[]
store.requestSink={requests.append($0)}
var retries=0; store.retryStartup={retries += 1}
func envelope(_ token:String="version-one", _ phase:String="recovery") -> [String:Any] {
    ["ok":false,"phase":phase,"issue":["code":"save_corrupt","message":"存档内容损坏，原文件已保留。"],
     "recovery":["save_path":"/tmp/fixture-only/state.json","backup_available":true,"token":token,
      "backup_summary":["coins":9,"desktop_count":6,"bottle_count":3,"modified_at":1700000000]]]
}
func receive(_ reply:[String:Any]) { store.receive(try! JSONSerialization.data(withJSONObject:reply)+Data([10])) }
receive(envelope())
let controls=store.recoveryControls
let panel=RecoveryControlView(controls:controls)
let window=NSWindow(contentRect:NSRect(x:0,y:0,width:420,height:440),styleMask:[.borderless],backing:.buffered,defer:false)
window.isReleasedWhenClosed=false;window.contentView=panel;panel.frame=NSRect(x:0,y:0,width:420,height:440)
switch CommandLine.arguments[1] {
case "confirmation":
    assert(store.runtimePhase=="recovery" && store.startupIssue?["code"] as? String=="save_corrupt")
    panel.restoreButton.performClick(nil)
    assert(requests.isEmpty && controls.confirmingToken=="version-one")
    panel.cancelButton.performClick(nil)
    assert(requests.isEmpty && controls.confirmingToken==nil)
    panel.restoreButton.performClick(nil);panel.confirmButton.performClick(nil);panel.confirmButton.performClick(nil)
    assert(requests.count==1 && requests[0]["action"] as? String=="recovery_restore")
    assert(requests[0]["token"] as? String=="version-one" && requests[0]["confirmed"] as? Bool==true)
    assert(controls.isSubmitting)
    var failed=envelope();failed["id"]=requests.last!["id"]!
    receive(failed)
    assert(!controls.isSubmitting && store.startupIssue != nil && !controls.feedback.isEmpty)
    panel.confirmButton.performClick(nil)
    let reply:[String:Any] = ["id":requests.last!["id"]!,"ok":true,"phase":"ready","state":["coins":9,"onboarding":"legacy","game_timezone":"UTC"]]
    receive(reply)
    assert(store.runtimePhase=="ready" && store.startupIssue==nil && store.recoveryInfo==nil && !controls.isSubmitting)
case "stale":
    panel.restoreButton.performClick(nil);receive(envelope("version-two"))
    assert(controls.confirmingToken==nil, "A changed backup must require a fresh confirmation")
    panel.confirmButton.performClick(nil);assert(requests.isEmpty)
    var missing=envelope();missing["recovery"]=["backup_available":false,"save_path":"/tmp/fixture-only/state.json"]
    receive(missing);panel.restoreButton.performClick(nil)
    assert(controls.confirmingToken==nil && requests.isEmpty)
    panel.inspectButton.performClick(nil)
    assert(requests.count==1 && requests[0]["action"] as? String=="recovery_inspect")
case "disconnect":
    panel.restoreButton.performClick(nil);panel.confirmButton.performClick(nil)
    assert(controls.isSubmitting)
    store.transportStopped(status:2)
    assert(!controls.isSubmitting && store.runtimePhase=="failed")
    assert(store.startupIssue?["code"] as? String=="save_corrupt", "Specific startup error must survive process exit")
    let count=requests.count;panel.confirmButton.performClick(nil);assert(requests.count==count)
    panel.retryButton.performClick(nil);assert(retries==1)
case "blocked_commands":
    var completion:Bool?
    store.send("buy",["item":"bell"]) { completion=$0 }
    assert(completion==false && requests.isEmpty)
    let timer=NSDictionary(dictionary:store.timer)
    store.send("timer_start",["mode":"stopwatch"])
    assert(requests.isEmpty && timer.isEqual(to:store.timer))
case "host":
    let host=ApplicationHost()
    host.overlay=OverlayWindow(contentRect:NSRect(x:0,y:0,width:150,height:90),styleMask:[.borderless],backing:.buffered,defer:false)
    host.scene=TianmuView(frame:NSRect(x:0,y:0,width:150,height:90));host.overlay.contentView=host.scene
    host.panel=NSWindow(contentRect:NSRect(x:0,y:0,width:480,height:580),styleMask:[.titled],backing:.buffered,defer:false)
    host.panel.isReleasedWhenClosed=false
    host.availableScreens={ [NSRect(x:0,y:0,width:1000,height:800)] }
    var shown=0;host.panelPresenter={_ in shown += 1};host.overlayPresenter={_ in}
    host.store.requestSink={_ in}
    host.configureRuntime()
    host.store.receive(try! JSONSerialization.data(withJSONObject:envelope())+Data([10]))
    assert(host.presentation.route=="设置" && shown==1 && !host.overlay.isVisible)
    host.capture();host.showTimer();host.openRoute("虫瓶")
    assert(host.presentation.route=="设置" && !host.overlay.isVisible && !host.timerTools.quickPresented)
    host.store.receive(try! JSONSerialization.data(withJSONObject:["ok":true,"phase":"ready","state":["onboarding":"legacy"]])+Data([10]))
    assert(host.store.startupIssue==nil && !host.petHidden && host.presentation.route==nil)
    assert(!host.overlay.isVisible && !host.panel.isVisible && host.store.process==nil)
case "check_protocol":
    var buffer=Data()
    buffer.append(try! JSONSerialization.data(withJSONObject:["ok":true,"phase":"ready","state":["coins":0]])+Data([10]))
    assert(try! checkedBackendReply(&buffer)==nil, "A startup greeting is not the requested snapshot")
    let wire=try! JSONSerialization.data(withJSONObject:["id":1,"ok":true,"state":["timer":["mode":"clock"]]])+Data([10])
    buffer.append(wire.prefix(10));assert(try! checkedBackendReply(&buffer)==nil)
    buffer.append(wire.dropFirst(10));assert(try! checkedBackendReply(&buffer)?["id"] as? Int==1)
    buffer.append(try! JSONSerialization.data(withJSONObject:envelope())+Data([10]))
    assert(try! checkedBackendReply(&buffer)?["phase"] as? String=="recovery")
case "late_ready":
    var phases:[String]=[];store.onRuntimeChange={phases.append($0)}
    store.transportStopped(status:3)
    receive(["ok":true,"phase":"ready","state":["coins":42,"onboarding":"legacy"]])
    assert(store.runtimePhase=="failed" && store.startupIssue != nil && !phases.contains("ready"), "Late greeting must not revive a closed connection")
    var precise=envelope();precise["issue"]=["code":"save_incompatible","message":"此存档来自其它版本。"]
    receive(precise)
    assert(store.startupIssue?["code"] as? String=="save_incompatible" && store.runtimePhase=="failed")
case "saved_quit":
    receive(["ok":true,"phase":"ready","state":["coins":9]])
    var acknowledged=false
    store.send("quit") { acknowledged=$0 }
    receive(["id":requests.last!["id"]!,"ok":true,"phase":"ready"])
    store.transportStopped(status:0)
    assert(acknowledged && store.startupIssue==nil && store.runtimePhase=="ready", "An acknowledged saved quit is not a startup failure")
case "render":
    panel.restoreButton.performClick(nil);panel.layoutSubtreeIfNeeded()
    let bitmap=panel.bitmapImageRepForCachingDisplay(in:panel.bounds)!
    panel.cacheDisplay(in:panel.bounds,to:bitmap)
    if CommandLine.arguments.count>2 { try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[2])) }
    assert(panel.bounds.contains(panel.confirmButton.frame) && panel.bounds.contains(panel.cancelButton.frame))
default:fatalError("Unknown scenario")
}
assert(store.process==nil && !window.isVisible)
print("PASS \(CommandLine.arguments[1]); no worker, save, visible window or permission")
window.close()
'''
class RecoveryHostTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory(prefix='tianmu-recovery-native-');cls.addClassCleanup(cls.temp.cleanup)
  folder=Path(cls.temp.name)
  (folder/'main.swift').write_text((ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]+HARNESS)
  (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
  cls.binary=folder/'check'
  result=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*(str(ROOT/'native/v1'/name) for name in ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift', 'InsectArtwork.swift','TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']),str(folder/'main.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
  if result.returncode:raise AssertionError(result.stderr)
def install(name):
 def test(self):
  run=subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=20)
  self.assertEqual(run.returncode,0,run.stdout+run.stderr);self.assertIn('PASS ',run.stdout);print(run.stdout.strip())
 setattr(RecoveryHostTests,'test_'+name,test)
for name in ['confirmation','stale','disconnect','blocked_commands','host','check_protocol','late_ready','saved_quit','render']:install(name)
