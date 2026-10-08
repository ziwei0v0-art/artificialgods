"""Pure bottle display contracts: Foundation only, no application, worker or save."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "// MARK: - Bottle motion adapted from fly-paradise"
HARNESS = r'''
func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { print("FAIL: \(message)"); exit(1) }
}
let colors = ["普通褐色", "中褐色", "深褐色", "白色"]
func countRow(_ color: String, _ female: Int, _ male: Int) -> [String:Any] {
    ["color":color,"female":female,"male":male]
}
func bug(_ id:String,_ color:String = "普通褐色",_ sex:String = "F") -> [String:Any] {
    ["id":id,"color":color,"sex":sex]
}
switch CommandLine.arguments[1] {
case "identity":
    let rows = [countRow(colors[0],2,1),countRow(colors[3],0,1)]
    let real = [bug("a"),bug("white",colors[3],"M"),bug("b"),bug("c",colors[0],"M")]
    let inventory = BottleDisplayInventory(rows:rows,individuals:real)
    check(inventory.visibleIDs == ["a","white","b","c"],"Actual IDs must reach the bottle display")
    check(inventory.visibleSexes == ["F","M","F","M"],"Actual sex must stay paired with ID")
    check(inventory.total == 4 && inventory.hasAuthoritativeIDs,"Counts remain authoritative")
    let fallback = BottleDisplayInventory(rows:rows)
    check(!fallback.hasAuthoritativeIDs,"Aggregate-only fixtures must never claim actual IDs")
    let bad = BottleDisplayInventory(rows:rows,individuals:[bug("a"),bug("a"),bug("bad",colors[2]),bug("",colors[0]),bug("badsex",colors[0],"?")])
    check(bad.visibleIDs == ["a"],"Reject duplicate, empty, unknown and inventory-inconsistent samples")
    check(BottleDisplayInventory(rows:rows,individuals:[]).visibleIDs.isEmpty,"Explicit empty samples do not invent insects")
case "continuity":
    let engine = BottleMotionEngine(), peer = BottleMotionEngine()
    var now = 10.0
    engine.update(ids:["a","b"],now:now); peer.update(ids:["a"],now:now)
    for i in 1...600 {
        now += 1.0/30
        engine.update(ids:i%2 == 0 ? ["a","b"]:["b","a"],now:now)
        peer.update(ids:["a"],now:now)
        check(engine.frames["a"] == peer.frames["a"],"Neighbours or row order changed an individual's path")
    }
    let before = engine.frames["a"]!
    engine.update(ids:["a"],now:now)
    check(engine.frames["a"] == before && engine.frames["b"] == nil,"Removing a released ID must preserve the other individual")
    engine.update(ids:[],now:now)
    check(engine.frames.isEmpty,"Empty bottle discards departed motion state")
case "bounds":
    let engine = BottleMotionEngine(); var now = 0.0
    let ids = (0..<12).map { "real-\($0)" }
    engine.update(ids:ids,now:now); let initial = engine.frames
    var moved = Set<String>(), hitX = false, hitY = false
    for _ in 1...10800 {
        now += 1.0/30; let prior = engine.frames; engine.update(ids:ids,now:now)
        for id in ids {
            let frame = engine.frames[id]!, previous = prior[id]!
            check(frame.x >= 18 && frame.x <= 162 && frame.y >= 22 && frame.y <= 298,"Fly crossed the original jar bounds")
            check(hypot(frame.x-previous.x,frame.y-previous.y) <= 1.50001,"A rendered step exceeded upstream maximum burst speed")
            check(frame.heading.isFinite && frame.animationTime.isFinite,"Nonfinite presentation escaped")
            if abs(frame.x-initial[id]!.x)+abs(frame.y-initial[id]!.y)>20 { moved.insert(id) }
            hitX = hitX || frame.x == 18 || frame.x == 162
            hitY = hitY || frame.y == 22 || frame.y == 298
        }
    }
    check(moved.count == 12 && hitX && hitY,"Individuals must move and actually encounter both jar wall axes")
    check(Set(engine.frames.values.map { String(format:"%.5f,%.5f",$0.x,$0.y) }).count == 12,"Independent IDs collapsed into one trajectory")
case "clock":
    let engine = BottleMotionEngine(); engine.update(ids:["a"],now:10); engine.update(ids:["a"],now:10.05)
    let before = engine.frames["a"]!
    for time in [10.05,9,900,Double.nan,901] {
        engine.update(ids:["a"],now:time)
        check(engine.frames["a"] == before,"Repeated, backward, suspended or invalid time moved the insect")
    }
    engine.update(ids:["a"],now:901.033)
    let after = engine.frames["a"]!
    check(after.animationTime > before.animationTime,"A valid next frame did not resume")
    check(hypot(after.x-before.x,after.y-before.y) <= 1.50001,"Resume caught up offline travel")
default: fatalError("Unknown case")
}
print("PASS: \(CommandLine.arguments[1]); FOUNDATION_ONLY_NO_WINDOWS_NO_WORKER_NO_SAVE")
'''


class BottleMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tianmu-bottle-motion-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        main = (ROOT / "native/v1/main.swift").read_text()
        dictionary = "extension Dictionary where Key == String, Value == Any {"
        extension = dictionary + main.split(dictionary, 1)[1].split("\n}", 1)[0] + "\n}\n"
        inventory = "struct BottleDisplayInventory {" + main.split("struct BottleDisplayInventory {", 1)[1].split("\nfinal class BottleInventoryView:", 1)[0]
        art = (ROOT / "native/v1/InsectArtwork.swift").read_text()
        motion = art.split(MARKER, 1)[1] if MARKER in art else ""
        (folder / "main.swift").write_text("import Foundation\n" + extension + inventory + motion + HARNESS)
        cls.binary = folder / "check"
        built = subprocess.run(["swiftc",str(folder/"main.swift"),"-o",str(cls.binary)],capture_output=True,text=True,timeout=30)
        if built.returncode: raise AssertionError(built.stderr)

    def run_case(self,name):
        ran = subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=15)
        self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
        print(ran.stdout.strip())

    def test_actual_identity_and_aggregate_compatibility(self): self.run_case("identity")
    def test_identity_continuity_reordering_and_departure(self): self.run_case("continuity")
    def test_independent_motion_and_original_wall_bounds(self): self.run_case("bounds")
    def test_clock_gaps_do_not_rewind_or_catch_up(self): self.run_case("clock")


if __name__ == "__main__": unittest.main()
