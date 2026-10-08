"""Execute the pinned upstream adult motion and compare the actual Swift port.

JavaScriptCore only executes the extracted pure functions. No browser, app,
upstream game loop, network, input hooks, worker, or save is created.
"""
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "dcfe5153feff4b5bfd47ad5fdde63cf5da337cbf286bb41ba0cb0562c7f2ac95"
JAVASCRIPT = r'''
var JAR_W=180, JAR_H=320, JAR_DIE_MS=Infinity, jar=[], randomState=0n;
function pruneJarSel() {}
function rand(lo,hi) {
 randomState=BigInt.asUintN(64,randomState*6364136223846793005n+1442695040888963407n);
 return lo+(hi-lo)*Number(randomState>>11n)/9007199254740992;
}
function begin(id) {
 var hash=14695981039346656037n;
 for(var i=0;i<id.length;i++) hash=BigInt.asUintN(64,(hash^BigInt(id.charCodeAt(i)))*1099511628211n);
 randomState=hash;
 jar=[{id:id,kind:'fly',seed:Number(hash%1000n),x:rand(24,156),y:rand(28,292),heading:rand(0,2*Math.PI)}];
}
'''
HARNESS = r'''
import JavaScriptCore
func check(_ condition:@autoclosure ()->Bool,_ message:String) {
 if !condition() { print("FAIL: \(message)"); exit(1) }
}
let javascript=try String(contentsOfFile:CommandLine.arguments[1],encoding:.utf8)
var maximumError=0.0, compared=0
for id in ["real-1","real-2","white-male"] {
 let js=JSContext()!
 js.exceptionHandler = { _,error in print("JavaScript error: \(error?.toString() ?? "unknown")"); exit(1) }
 js.evaluateScript(javascript)
 js.objectForKeyedSubscript("begin")!.call(withArguments:[id])
 let native=BottleMotionEngine(); var now=0.0
 native.update(ids:[id],now:now)
 for _ in 0..<3600 {
  let previous=now; now += 1.0/30
  native.update(ids:[id],now:now)
  let frame=native.frames[id]!
  js.objectForKeyedSubscript("stepJar")!.call(withArguments:[min(0.05,now-previous),frame.animationTime*1000])
  let original=js.evaluateScript("jar[0]")!
  for (key,value) in [("x",frame.x),("y",frame.y),("heading",frame.heading)] {
   let error=abs(original.forProperty(key)!.toDouble()-value)
   maximumError=max(maximumError,error)
   check(error < 0.0000001,"Port diverged from original \(id) \(key), error \(error)")
  }
  compared += 1
 }
}
print("PASS: \(compared) upstream/native frames; max_error=\(maximumError); JAVASCRIPTCORE_NO_UI_NO_WORKER_NO_SAVE")
'''


class BottleUpstreamMotionTests(unittest.TestCase):
    def test_original_adult_step_and_wall_response_match_port(self):
        original = (ROOT / "third_party/fly-paradise/upstream/renderer/overlay.js").read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), EXPECTED)
        source = original.decode()
        closure = source[source.index("function bounceJar(u) {"):source.index("function publishJar() {")]
        motion = (ROOT / "native/v1/InsectArtwork.swift").read_text().split(
            "// MARK: - Bottle motion adapted from fly-paradise",1)[1]
        with tempfile.TemporaryDirectory(prefix="tianmu-original-bottle-") as tmp:
            folder = Path(tmp)
            (folder / "reference.js").write_text(JAVASCRIPT + closure)
            (folder / "main.swift").write_text("import Foundation\n" + motion + HARNESS)
            binary = folder / "check"
            build = subprocess.run(["swiftc","-framework","JavaScriptCore",str(folder/"main.swift"),"-o",str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stderr)
            run = subprocess.run([str(binary),str(folder/"reference.js")],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn("JAVASCRIPTCORE_NO_UI_NO_WORKER_NO_SAVE",run.stdout)
            print(run.stdout.strip())


if __name__ == "__main__": unittest.main()
