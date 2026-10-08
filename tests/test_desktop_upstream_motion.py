"""Pinned upstream adult movement, executed with JavaScriptCore and no visible UI."""
from pathlib import Path
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "third_party/fly-paradise/upstream/renderer/overlay.js"
MODULE = ROOT / "third_party/fly-paradise/desktop-motion.js"
FUNCTION = re.compile(r"^function (\w+)\([^\n]*\) \{(?:[^\n]*\}|.*?^\})", re.M | re.S)

REFERENCE = r'''
let clock = 0;
const performance = {now:() => clock};
let W=1200,H=800,fast=false,breed=false,swatterOn=false,netOn=false;
let mouse={x:-1e9,y:-1e9,vx:0,vy:0,spd:0};
let flies=[],foods=[],icons=[],screens=[],corpses=[],eggs=[],larvae=[],pupae=[],shells=[],nextId=1;
let randomState=0n, animationTime=0;
Math.random=()=>{
  randomState=BigInt.asUintN(64,randomState*6364136223846793005n+1442695040888963407n);
  return Number(randomState>>11n)/9007199254740992;
};
function referenceBegin(id,seed,x,y,ss,ii) {
  randomState=BigInt(seed); screens=ss; icons=ii;
  const f=spawnFly(x,y,{force:true,sex:'f'}); f.id=id; f.retired=true;
}
function referenceStep(dt,pointer,suppressThreat) {
  clock+=dt*1000;
  mouse=pointer.enabled ? {...pointer,spd:Math.hypot(pointer.vx,pointer.vy)} : {x:-1e9,y:-1e9,vx:0,vy:0,spd:0};
  netOn=suppressThreat;
  const f=flies[0];
  f.retired=true; f.ripe=false; f.mateSeek=0; f.liveMs=0; f.kidDieAt=0; f.dieAt=0;
  f.hunger=Math.min(f.hunger,0.4);
  stepFly(f,dt,clock);
  if(f.state==='fly'||f.state==='flee') animationTime+=dt;
  return {x:f.x,y:f.y,vx:f.vx,vy:f.vy,heading:f.visHead,animationTime,
    activity:f.state==='fly'||f.state==='flee'?'flying':f.crawling?'crawling':'resting',state:f.state};
}
'''

HARNESS = r'''
import AppKit
import JavaScriptCore
let app=NSApplication.shared
app.setActivationPolicy(.prohibited)
func check(_ condition:@autoclosure ()->Bool,_ message:String) {
  if !condition() { print("FAIL: \(message)"); exit(1) }
}
let original=try String(contentsOfFile:CommandLine.arguments[1],encoding:.utf8)
let module=URL(fileURLWithPath:CommandLine.arguments[2])
var compared=0,maximumError=0.0,states=Set<String>(),sawWrap=false
for rate in [20.0,30.0,60.0] {
 for id in ["real-adult-1","real-adult-2","白色雌蝇"] {
  var now=10.0
  let screen=DesktopInsectScreen(id:"screen",frame:NSRect(x:-1200,y:-100,width:1200,height:800))
  let surfaces=[DesktopInsectLandingSurface(id:"fruit",frame:NSRect(x:-616,y:284,width:32,height:32)),
    DesktopInsectLandingSurface(id:"shrine",frame:NSRect(x:-150,y:600,width:32,height:32)),
    DesktopInsectLandingSurface(id:"edge",frame:NSRect(x:-1190,y:-90,width:32,height:32))]
  let native=DesktopInsects(motionModuleURL:module,quietPresentation:false,screens:[screen],renderTime:{now},windowPresenter:{_ in})
  native.updateBehaviorLandingSurfaces(surfaces)
  native.update(rows:[["id":id,"x":0.5,"y":0.5,"color":"白色","sex":"F"]])
  check(native.motionUnavailableReason == nil,"Module initialization failed")
  let js=JSContext()!
  js.exceptionHandler={_,error in print("JS ERROR: \(error?.toString() ?? "unknown")");exit(1)}
  js.evaluateScript(original)
  let seed=id.utf8.reduce(UInt64(14695981039346656037)){($0 ^ UInt64($1)) &* 1099511628211}
  let ss:[[String:Any]]=[["id":"screen","x":-1200.0,"y":-700.0,"w":1200.0,"h":800.0]]
  let ii:[[String:Any]]=surfaces.map{["id":$0.id,"name":$0.id,"x":$0.frame.minX,"y":(-$0.frame.maxY),"w":32.0,"h":32.0]}
  js.objectForKeyedSubscript("referenceBegin")!.call(withArguments:[id,String(seed),-600.0,-300.0,ss,ii])
  var previousPointer:NSPoint?,last=native.positions[0].point
  let duration = rate == 30 && id == "real-adult-1" ? 300.0 : 80.0
  for frame in 0..<Int(rate*duration) {
    let previous=now;now+=1/rate;let dt=min(0.05,now-previous)
    // Rest/landing first; later approach the current fly, then leave it alone.
    // Pressed-button samples also cover net/tool threat suppression.
    let enabled=(frame>Int(rate*8) && frame<Int(rate*9)) || (frame>Int(rate*30) && frame<Int(rate*31))
    let pressed=frame<Int(rate*10)
    let point=NSPoint(x:last.x-25,y:last.y+10)
    var pointer:[String:Any] = ["enabled":false]
    if enabled {
      let vx=previousPointer.map{(point.x-$0.x)/dt} ?? 0
      let vy=previousPointer.map{-(point.y-$0.y)/dt} ?? 0
      pointer=["enabled":true,"x":point.x,"y":(-point.y),"vx":vx,"vy":vy]
      previousPointer=point
    } else {previousPointer=nil}
    native.updateBehaviorPointer(point,buttonsPressed:pressed ? 1:0,enabled:enabled)
    native.refresh()
    check(native.motionUnavailableReason == nil,"Module execution failed")
    check(native.positions.count == 1,"An authoritative live ID disappeared")
    let result=js.objectForKeyedSubscript("referenceStep")!.call(withArguments:[dt,pointer,pressed])!
    let actual=native.positions[0]
    let values:[(String,Double)] = [("x",Double(actual.point.x)),("y",-Double(actual.point.y)),("vx",Double(actual.velocity.x)),("vy",-Double(actual.velocity.y)),("heading",-actual.heading),("animationTime",actual.animationTime)]
    for (key,value) in values {
      let error=abs(result.forProperty(key)!.toDouble()-value)
      maximumError=max(maximumError,error)
      check(error<1e-7,"Upstream/native diverged at \(rate) Hz \(id) frame \(frame), \(key) error \(error)")
    }
    check(actual.activity.rawValue == result.forProperty("activity")!.toString(),"Activity differs from the original state")
    check(actual.sex == "F" && actual.color == "白色","Motion altered backend-owned sex or color")
    states.insert(result.forProperty("state")!.toString())
    states.insert(actual.activity.rawValue)
    sawWrap = sawWrap || hypot(actual.point.x-last.x,actual.point.y-last.y)>600
    last=actual.point;compared+=1
  }
  check(native.windows.allSatisfy{!$0.isVisible && !$0.isKeyWindow},"Differential test exposed a window")
  native.close()
 }
}
check(states.contains("flee") && states.contains("perch") && states.contains("crawling"),"Reference fixture did not exercise scare, land and small hops")
check(sawWrap,"Reference fixture did not exercise original screen wrapping")
print("PASS: \(compared) original/native frames at 20/30/60 Hz; max_error=\(maximumError); states=\(states.sorted()); NO_VISIBLE_UI_NO_WORKER_NO_SAVE")
'''


class DesktopUpstreamSourceTests(unittest.TestCase):
    def test_original_step_chain_is_copied_without_rewriting(self):
        original = UPSTREAM.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), "dcfe5153feff4b5bfd47ad5fdde63cf5da337cbf286bb41ba0cb0562c7f2ac95")
        module = MODULE.read_text()
        functions = {m[1]: m[0] for m in FUNCTION.finditer(original.decode())}
        todo, needed = ["stepFly", "spawnFly"], set()
        while todo:
            name = todo.pop()
            if name in needed:
                continue
            needed.add(name)
            todo.extend(other for other in functions if other not in needed and re.search(r"\b" + other + r"\s*\(", functions[name]))
        for name in needed:
            self.assertIn(functions[name], module, f"Original {name} body changed")
        self.assertGreater(len(needed), 60)
        self.assertNotIn("addEventListener(", module)
        self.assertNotIn("window.api", module)


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class DesktopUpstreamDifferentialTests(unittest.TestCase):
    def test_native_trajectories_match_original_at_three_frame_rates(self):
        source = UPSTREAM.read_text()
        functions = {m[1]: m[0] for m in FUNCTION.finditer(source)}
        needed, todo = set(), ["stepFly", "spawnFly"]
        while todo:
            name = todo.pop()
            if name in needed:
                continue
            needed.add(name)
            todo.extend(other for other in functions if other not in needed and re.search(r"\b" + other + r"\s*\(", functions[name]))
        constants = source[source.index("const FLY_HIT"):source.index("\nfunction mateMs")]
        reference = constants + "\n" + "\n\n".join(functions[name] for name in functions if name in needed) + "\n" + REFERENCE
        with tempfile.TemporaryDirectory(prefix="tianmu-original-adult-") as tmp:
            folder = Path(tmp)
            (folder / "reference.js").write_text(reference)
            (folder / "main.swift").write_text(HARNESS)
            binary = folder / "check"
            build = subprocess.run(["swiftc", "-framework", "AppKit", "-framework", "JavaScriptCore", *(str(ROOT / "native/v1" / name) for name in ["WindowPlacement.swift", "InsectArtwork.swift", "DesktopInsects.swift"]), str(folder / "main.swift"), "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(folder / "reference.js"), str(MODULE)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("NO_VISIBLE_UI_NO_WORKER_NO_SAVE", run.stdout)
            print(run.stdout.strip())


if __name__ == "__main__":
    unittest.main()
