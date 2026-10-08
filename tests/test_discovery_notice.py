"""Discovery notices use unshown AppKit windows and an injected expiry clock.

No host, worker, save data, sound, permission request, or visible window is used.
"""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native/v1/Presentation.swift"
HARNESS = r'''
import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
var presented: [NSWindow] = []
var scheduled: [(TimeInterval, () -> Void)] = []
let notice = DiscoveryNotice(present: { presented.append($0) }, schedule: { scheduled.append(($0, $1)) })
let left = NSRect(x:-1280,y:-100,width:1280,height:800)
let main = NSRect(x:0,y:0,width:1600,height:1000)
let anchor = NSRect(x:-800,y:220,width:240,height:150)
func show(_ colors: [String]) { notice.show(colors:colors, near:anchor, screens:[main,left]) }
func absent() {
    assert(!notice.isPresented && notice.window == nil && notice.text.isEmpty)
}

switch CommandLine.arguments[1] {
case "empty":
    absent()
    show([])
    show(["", "unknown"])
    absent()
    assert(presented.isEmpty && scheduled.isEmpty)
case "passive":
    show(["白色"])
    let window = notice.window!
    assert(notice.isPresented && notice.text == "新发现：白色")
    assert(window.styleMask.contains(.nonactivatingPanel))
    assert(!window.canBecomeKey && !window.canBecomeMain && window.ignoresMouseEvents)
    assert(!window.isOpaque && window.backgroundColor?.alphaComponent == 0)
    assert(window.collectionBehavior.contains(.canJoinAllSpaces))
    assert(!window.hidesOnDeactivate)
    assert(left.contains(window.frame))
    assert(scheduled.count == 1 && scheduled[0].0 == 4)
    scheduled[0].1()
    absent()
    assert(!window.isVisible && window.ignoresMouseEvents)
case "merge":
    show(["白色", "普通褐色", "白色"])
    let original = notice.window!
    assert(notice.text == "新发现：普通褐色、白色")
    show(["深褐色", "中褐色"])
    assert(notice.window === original, "A batch updates one notice instead of stacking windows")
    assert(notice.text == "新发现：普通褐色、中褐色、深褐色、白色")
    assert(scheduled.count == 2)
    show(["白色"]); show([])
    assert(scheduled.count == 2, "Duplicates and empty deltas must not keep a notice alive indefinitely")
    scheduled[0].1()
    assert(notice.isPresented, "An older deadline must not hide merged discoveries")
    scheduled[1].1()
    absent()
case "generation":
    show(["白色"])
    let old = notice.window!
    notice.dismiss(); notice.dismiss()
    absent()
    show(["深褐色"])
    assert(notice.text == "新发现：深褐色" && notice.window !== old)
    scheduled[0].1()
    assert(notice.isPresented && notice.text == "新发现：深褐色")
    scheduled[1].1()
    absent()
case "placement":
    for screen in [left, main] {
        for origin in [NSPoint(x:screen.minX,y:screen.minY), NSPoint(x:screen.maxX-60,y:screen.maxY-50)] {
            notice.dismiss()
            let pet = NSRect(origin:origin, size:NSSize(width:60,height:50))
            notice.show(colors:["白色"],near:pet,screens:[main,left])
            let frame = notice.window!.frame
            assert(screen.contains(frame), "Notice must remain on the pet's screen, including negative origins")
            assert(abs(frame.midX-pet.midX) <= frame.width / 2)
        }
    }
    notice.dismiss()
    notice.show(colors:["白色"],near:NSRect(x:-1900,y:0,width:100,height:100),screens:[main,left])
    assert(left.contains(notice.window!.frame), "An offscreen pet uses the nearest screen")
    notice.dismiss()
    let tiny = NSRect(x:-30,y:-20,width:90,height:50)
    notice.show(colors:["白色"],near:tiny,screens:[tiny])
    assert(tiny.contains(notice.window!.frame))
    notice.show(colors:["深褐色"],near:anchor,screens:[])
    absent()
case "render":
    show(["普通褐色", "中褐色", "深褐色", "白色"])
    let view = notice.window!.contentView!
    view.layoutSubtreeIfNeeded()
    let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    assert(bitmap.pixelsWide > 0 && bitmap.pixelsHigh > 0)
    let data = bitmap.representation(using:.png,properties:[:])!
    assert(data.count > 1000, "The actual native notice should render its background and text")
    if CommandLine.arguments.count > 2 {
        try! data.write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
    }
default: fatalError("Unknown scenario")
}
assert(presented.allSatisfy { !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow && $0.ignoresMouseEvents })
notice.dismiss()
absent()
print("PASS \(CommandLine.arguments[1]): unshown native notice; no host/worker/save/sound/permissions")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class DiscoveryNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tianmu-discovery-notice-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.binary = folder / "check"
        harness = folder / "main.swift"
        harness.write_text(HARNESS)
        cls.build = subprocess.run(["swiftc", str(SOURCE), str(harness), "-o", str(cls.binary)],
                                   capture_output=True, text=True, timeout=60)

    def scenario(self, name):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        run = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"PASS {name}:", run.stdout)
        print(run.stdout.strip())

    def test_empty_or_unknown_colors_never_present_or_schedule(self):
        self.scenario("empty")

    def test_notice_is_nonactivating_passive_and_expires_after_four_seconds(self):
        self.scenario("passive")

    def test_visible_discoveries_merge_once_and_old_deadline_cannot_hide_them(self):
        self.scenario("merge")

    def test_dismiss_clears_and_expiry_cannot_hide_a_later_notice(self):
        self.scenario("generation")

    def test_notice_fits_pet_screen_negative_coordinates_edges_and_small_screens(self):
        self.scenario("placement")

    def test_actual_native_notice_renders_offscreen(self):
        self.scenario("render")


if __name__ == "__main__":
    unittest.main()
