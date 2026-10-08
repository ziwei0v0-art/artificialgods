"""Unshown native onboarding card and real button presses; no host or storage."""
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
var actions = 0, skips = 0
let guide = OnboardingGuide(present: { presented.append($0) })
guide.onAction = { actions += 1 }
guide.onSkip = { skips += 1 }
let left = NSRect(x:-1280,y:-100,width:1280,height:800)
let main = NSRect(x:0,y:0,width:1600,height:1000)
let anchor = NSRect(x:-800,y:220,width:240,height:150)
func show(_ step: String) { guide.show(step:step,near:anchor,screens:[main,left]) }
func labels(_ view: NSView) -> [NSTextField] {
    (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap { labels($0) }
}
func absent() {
    assert(!guide.isPresented && guide.window == nil && guide.step == nil)
}
func label(_ text: String) -> NSTextField? {
    guide.window?.contentView.flatMap { labels($0).first { $0.stringValue == text } }
}

switch CommandLine.arguments[1] {
case "terminal":
    absent()
    for step in ["done", "skipped", "legacy", "unknown", ""] { show(step); absent() }
    assert(presented.isEmpty && actions == 0 && skips == 0)
    show("shrine")
    let staleAction = guide.actionButton, staleSkip = guide.skipButton
    show("done")
    absent()
    staleAction.performClick(nil); staleSkip.performClick(nil)
    assert(actions == 0 && skips == 0, "A hidden card must not dispatch stale button actions")
case "steps_and_buttons":
    for (step,title) in [("shrine","打开签筒"),("capture","知道了"),("bottle","查看虫瓶")] {
        show(step)
        let panel = guide.window!
        assert(guide.step == step && guide.isPresented && guide.actionButton.title == title)
        assert(guide.skipButton.title == "跳过")
        assert(panel.styleMask.contains(.nonactivatingPanel) && !panel.canBecomeKey && !panel.canBecomeMain)
        assert(!panel.ignoresMouseEvents, "Only the compact card accepts its own button clicks")
        assert(panel.frame.width <= 340 && panel.frame.height <= 200 && left.contains(panel.frame))
        assert(guide.actionButton.window === panel && guide.skipButton.window === panel)
        let beforeActions = actions, beforeSkips = skips
        guide.actionButton.performClick(nil)
        assert(actions == beforeActions+1 && skips == beforeSkips)
        guide.skipButton.performClick(nil)
        assert(skips == beforeSkips+1 && actions == beforeActions+1)
        assert(guide.isPresented && guide.step == step, "The host owns saved progress and navigation")
    }
case "busy":
    show("shrine")
    guide.setBusy(true)
    assert(!guide.actionButton.isEnabled && !guide.skipButton.isEnabled)
    guide.actionButton.performClick(nil); guide.skipButton.performClick(nil)
    assert(actions == 0 && skips == 0)
    guide.setBusy(false)
    assert(guide.actionButton.isEnabled && guide.skipButton.isEnabled)
    guide.actionButton.performClick(nil)
    assert(actions == 1 && skips == 0)
    guide.dismiss()
    guide.setBusy(false)
    guide.actionButton.performClick(nil); guide.skipButton.performClick(nil)
    assert(actions == 1 && skips == 0)
case "repeat_and_error":
    show("shrine")
    let original = guide.window!, firstPresentations = presented.count
    guide.setBusy(true)
    guide.showError("保存失败，请重试。")
    for _ in 0..<4 { show("shrine") }
    assert(guide.window === original && presented.count == firstPresentations,
           "Snapshot refreshes must not reorder the card")
    assert(!guide.actionButton.isEnabled && !guide.skipButton.isEnabled,
           "Repeated show must not unlock an in-flight action")
    let error = label("保存失败，请重试。")!
    assert(!error.isHidden && error.frame.width > 0 && error.frame.height > 0)
    assert(original.contentView!.bounds.contains(error.frame), "The actual error text must be in the card")
    assert(error.font!.pointSize < 13, "Error is secondary, compact text")
    show("capture")
    assert(guide.step == "capture" && guide.actionButton.title == "知道了")
    assert(guide.actionButton.isEnabled && guide.skipButton.isEnabled)
    assert(label("保存失败，请重试。") == nil, "A new step must clear the preceding error")
    guide.showError("临时错误")
    guide.showError("")
    assert(label("临时错误") == nil)
case "dismiss":
    show("bottle")
    let original = guide.window!
    guide.dismiss(); guide.dismiss()
    absent()
    assert(actions == 0 && skips == 0, "Hiding the card is not a saved skip")
    assert(!original.isVisible)
    show("bottle")
    assert(guide.isPresented && guide.step == "bottle" && guide.actionButton.isEnabled)
case "placement":
    for screen in [left,main] {
        for origin in [NSPoint(x:screen.minX,y:screen.minY), NSPoint(x:screen.maxX-60,y:screen.maxY-50)] {
            let pet = NSRect(origin:origin,size:NSSize(width:60,height:50))
            guide.show(step:"capture",near:pet,screens:[main,left])
            assert(screen.contains(guide.window!.frame), "Negative screen edges must contain the complete card")
            assert(abs(guide.window!.frame.midX-pet.midX) <= guide.window!.frame.width/2)
            guide.showError("保存失败，请重试。")
            assert(screen.contains(guide.window!.frame), "Error expansion must stay on screen")
            guide.dismiss()
        }
    }
    guide.show(step:"shrine",near:NSRect(x:-1900,y:0,width:100,height:100),screens:[main,left])
    assert(left.contains(guide.window!.frame), "An offscreen anchor uses the nearest available display")
    guide.show(step:"shrine",near:anchor,screens:[])
    absent()
case "render":
    show("capture")
    let view = guide.window!.contentView!
    view.layoutSubtreeIfNeeded()
    let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    let data = bitmap.representation(using:.png,properties:[:])!
    assert(data.count > 1000)
    if CommandLine.arguments.count > 2 {
        try! data.write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
    }
default: fatalError("Unknown scenario")
}
assert(presented.allSatisfy { !$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow })
guide.dismiss()
absent()
print("PASS \(CommandLine.arguments[1]): unshown native card and real buttons; no host/worker/save/sound/permissions")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class OnboardingGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tianmu-onboarding-guide-")
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
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"PASS {name}:", run.stdout)
        print(run.stdout.strip())

    def test_terminal_and_unknown_steps_never_show_or_dispatch_stale_buttons(self):
        self.scenario("terminal")

    def test_three_steps_are_compact_nonactivating_and_real_buttons_dispatch_once(self):
        self.scenario("steps_and_buttons")

    def test_busy_disables_both_buttons_until_explicitly_reenabled(self):
        self.scenario("busy")

    def test_repeat_show_keeps_busy_error_and_order_until_step_changes(self):
        self.scenario("repeat_and_error")

    def test_dismiss_is_local_and_allows_the_same_unfinished_step_to_return(self):
        self.scenario("dismiss")

    def test_card_and_error_expansion_fit_negative_screen_edges(self):
        self.scenario("placement")

    def test_actual_native_card_renders_offscreen(self):
        self.scenario("render")


if __name__ == "__main__":
    unittest.main()
