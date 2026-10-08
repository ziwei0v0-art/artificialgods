import json
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"),
                     "macOS + Swift required for the desktop overlay")
class NativeOverlayTests(unittest.TestCase):
    def test_escape_clears_drag_and_requests_redraw_without_catching(self):
        source = (PROJECT / "native" / "OverlayHost.swift").read_text().split("final class Host:")[0]
        harness = r"""
let app = NSApplication.shared
let window = OverlayWindow(contentRect: NSRect(x:0,y:0,width:540,height:380),styleMask:[.borderless],backing:.buffered,defer:false)
let view = TianmuView(frame:window.contentView!.bounds)
window.contentView = view; view.attach(window:window)
var captured = 0
view.emit = { if $0["type"] as? String == "capture" { captured += 1 } }
view.windowMode = "capture"; view.captureMode = true; window.ignoresMouseEvents = false
func mouse(_ type: NSEvent.EventType, _ x: CGFloat) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:NSPoint(x:x,y:100),modifierFlags:[],timestamp:0,windowNumber:window.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
view.mouseDown(with:mouse(.leftMouseDown,50))
view.mouseDragged(with:mouse(.leftMouseDragged,200))
view.needsDisplay = false
let escape = NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:0,windowNumber:window.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!
view.keyDown(with:escape)
assert(window.ignoresMouseEvents && !view.captureMode && view.windowMode == "passthrough")
assert(view.needsDisplay, "Escape must redraw to erase the visible net")
// Re-arming without a new drag must not reuse the cancelled rectangle.
view.windowMode = "capture"; view.captureMode = true
view.mouseUp(with:mouse(.leftMouseUp,200))
assert(captured == 0, "Cancelled drag must never submit a capture")
print("escape cleanup ok")
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.swift"
            path.write_text(source + harness)
            binary = Path(directory) / "check"
            subprocess.run(["swiftc", str(path), "-o", str(binary)], check=True, capture_output=True, timeout=45)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("escape cleanup ok", run.stdout)

    def test_native_focus_loss_releases_mouse_and_cancels_drag(self):
        source = (PROJECT / "native" / "OverlayHost.swift").read_text()
        declarations = source.rsplit("let app = NSApplication.shared", 1)[0]
        harness = r"""
let app = NSApplication.shared
let window = OverlayWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 380), styleMask: [.borderless], backing: .buffered, defer: false)
let view = TianmuView(frame: window.contentView!.bounds)
window.contentView = view
view.attach(window: window)
var events: [[String: Any]] = []
view.emit = { events.append($0) }
view.windowMode = "capture"
view.captureMode = true
window.ignoresMouseEvents = false
NotificationCenter.default.post(name: NSWindow.didResignKeyNotification, object: window)
let result: [String: Any] = ["passthrough": window.ignoresMouseEvents, "capturing": view.captureMode, "mode": view.windowMode, "eventCount": events.count]
let data = try! JSONSerialization.data(withJSONObject: result)
print(String(data: data, encoding: .utf8)!)
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.swift"
            path.write_text(declarations + harness)
            binary = Path(directory) / "check"
            subprocess.run(["swiftc", "-framework", "AppKit", str(path), "-o", str(binary)],
                           check=True, capture_output=True, timeout=45)
            run = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
        state = json.loads(run.stdout.strip())
        self.assertTrue(state["passthrough"])
        self.assertFalse(state["capturing"])
        self.assertEqual(state["mode"], "passthrough")
        self.assertEqual(state["eventCount"], 1)

    def test_native_host_builds_and_announces_transparent_desktop_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "TianmuOverlayHost"
            subprocess.run(
                ["swiftc", "-framework", "AppKit", str(PROJECT / "native" / "OverlayHost.swift"), "-o", str(binary)],
                check=True, capture_output=True, text=True, timeout=45,
            )
            run = subprocess.run(
                [str(binary), "--smoke-test"], check=True, capture_output=True, text=True, timeout=10,
            )
        messages = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        ready = next(message for message in messages if message.get("type") == "ready")
        self.assertEqual(ready["frame"]["width"], 540)
        self.assertEqual(ready["frame"]["height"], 380)

    def test_native_host_accepts_mode_commands_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "TianmuOverlayHost"
            subprocess.run(
                ["swiftc", "-framework", "AppKit", str(PROJECT / "native" / "OverlayHost.swift"), "-o", str(binary)],
                check=True, capture_output=True, text=True, timeout=45,
            )
            run = subprocess.run(
                [str(binary)], input='{"type":"mode","mode":"capture"}\n'
                                   '{"type":"mode","mode":"passthrough"}\n'
                                   '{"type":"hide"}\n'
                                   '{"type":"show"}\n'
                                   '{"type":"timer_expired"}\n'
                                   '{"type":"timer_dismissed"}\n'
                                   '{"type":"quit"}\n',
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(run.returncode, 0)
        messages = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        self.assertEqual([message["type"] for message in messages[:5]],
                         ["ready", "mode", "mode", "overlay_visibility", "overlay_visibility"])
        self.assertEqual(messages[1]["mode"], "capture")
        self.assertEqual(messages[2]["mode"], "passthrough")
        self.assertFalse(messages[3]["visible"])
        self.assertTrue(messages[4]["visible"])


if __name__ == "__main__":
    unittest.main()
