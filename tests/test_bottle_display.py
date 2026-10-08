"""Read-only bottle illustration inventory, compiled from the production model.

Foundation only: no application, windows, worker, or save files are opened.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
func row(_ color: String, _ female: Int, _ male: Int) -> [String: Any] {
    ["color": color, "female": female, "male": male, "price": 1]
}
let colors = ["普通褐色", "中褐色", "深褐色", "白色"]
switch CommandLine.arguments[1] {
case "empty":
    for rows in [[], colors.map { row($0, 0, 0) }] {
        let display = BottleDisplayInventory(rows: rows)
        assert(display.total == 0 && display.visibleColors.isEmpty && display.visibleSexes.isEmpty,
               "Empty inventory must not fabricate decorative insects")
    }
case "exact":
    let rows = [row(colors[0], 2, 1), row(colors[1], 0, 1),
                row(colors[2], 1, 0), row(colors[3], 0, 2)]
    let before = NSDictionary(dictionary: ["bottle": rows])
    let display = BottleDisplayInventory(rows: rows)
    assert(display.total == 7 && display.visibleColors.count == 7)
    assert(display.visibleSexes == ["F", "M", "F", "M", "F", "M", "M"],
           "Each displayed sex must come from its actual colour inventory")
    for original in rows {
        let count = (original["female"] as! Int) + (original["male"] as! Int)
        assert(display.visibleColors.filter { $0 == original.colorKey }.count == count,
               "Below the cap, show exactly the inventory's colour counts")
    }
    assert(before.isEqual(to: ["bottle": rows]), "Illustration changed its source rows")
case "capped":
    let rows = [row(colors[0], 9000, 1000), row(colors[1], 1, 1),
                row(colors[2], 0, 1), row(colors[3], 1, 0)]
    let state: [String: Any] = ["bottle": rows, "coins": 17, "capture_seconds": 123,
                               "timer": ["status": "running", "remaining": 30],
                               "desktop": [["id": "bug-00001", "color": colors[0]]]]
    let frozen = try! JSONSerialization.data(withJSONObject: state, options: [.sortedKeys])
    for _ in 0..<50 {
        let display = BottleDisplayInventory(rows: state["bottle"] as! [[String: Any]])
        assert(display.total == 10004, "Display cap must never replace the actual inventory total")
        assert(display.visibleColors.count == 12 && display.visibleSexes.count == 12, "Illustration must remain bounded")
        for original in rows {
            let matching = zip(display.visibleColors, display.visibleSexes).filter { $0.0 == original.colorKey }
            assert(matching.filter { $0.1 == "F" }.count <= original["female"] as! Int)
            assert(matching.filter { $0.1 == "M" }.count <= original["male"] as! Int)
        }
        assert(Set(display.visibleColors) == Set(colors),
               "An abundant common colour must not displace a rare owned colour")
        for original in rows {
            let count = (original["female"] as! Int) + (original["male"] as! Int)
            assert(display.visibleColors.filter { $0 == original.colorKey }.count <= count)
        }
    }
    let after = try! JSONSerialization.data(withJSONObject: state, options: [.sortedKeys])
    assert(after == frozen, "Animation inventory must not simulate or alter accepted state")
case "single":
    for color in colors {
        let display = BottleDisplayInventory(rows: colors.map { row($0, $0 == color ? 13 : 0, 0) })
        assert(display.total == 13 && display.visibleColors == Array(repeating: color, count: 12))
        assert(display.visibleSexes == Array(repeating: "F", count: 12))
        let mixed = BottleDisplayInventory(rows: [row(color, 2, 13)])
        assert(mixed.total == 15 && mixed.visibleSexes == ["F", "F"] + Array(repeating: "M", count: 10))
        let allMale = BottleDisplayInventory(rows: [row(color, 0, 13)])
        assert(allMale.visibleSexes == Array(repeating: "M", count: 12))
    }
default: fatalError("Unknown case")
}
print("PASS: \(CommandLine.arguments[1]); FOUNDATION_ONLY_NO_WINDOWS_NO_WORKER_NO_SAVE")
'''


class BottleDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tianmu-bottle-display-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        source = (ROOT / "native/v1/main.swift").read_text()
        dictionary = "extension Dictionary where Key == String, Value == Any {"
        extension = dictionary + source.split(dictionary, 1)[1].split("\n}", 1)[0] + "\n}\n"
        inventory = "struct BottleDisplayInventory {" + source.split(
            "struct BottleDisplayInventory {", 1)[1].split("\nfinal class BottleInventoryView:", 1)[0]
        (folder / "main.swift").write_text("import Foundation\n" + extension + inventory + HARNESS)
        cls.binary = folder / "check"
        build = subprocess.run(["swiftc", str(folder / "main.swift"), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=30)
        if build.returncode:
            raise AssertionError(build.stderr)

    def _case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FOUNDATION_ONLY_NO_WINDOWS_NO_WORKER_NO_SAVE", result.stdout)
        print(result.stdout.strip())

    def test_empty_bottle_has_no_invented_insects(self):
        self._case("empty")

    def test_under_cap_keeps_exact_counts(self):
        self._case("exact")

    def test_cap_preserves_rare_colours_total_and_snapshot(self):
        self._case("capped")

    def test_single_colour_never_invents_other_colours(self):
        self._case("single")


if __name__ == "__main__":
    unittest.main()
