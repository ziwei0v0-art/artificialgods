"""Native reminder fixture: no worker, no game save, no game scene shown."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QA = Path('/tmp/tianmu-qa-0929-focus')


class NativeReminderTests(unittest.TestCase):
    def test_reminder_window_visibility_and_available_accessible_route(self):
        QA.mkdir(parents=True, exist_ok=True)
        host = (ROOT / 'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        scene = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        harness = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let host = ApplicationHost()
host.statusItem = NSStatusBar.system.statusItem(withLength:NSStatusItem.variableLength)
host.panel = NSWindow(contentRect:NSRect(x:0,y:0,width:480,height:580),styleMask:[.titled],backing:.buffered,defer:false)
host.panel.isReleasedWhenClosed = false
host.overlay = OverlayWindow(contentRect:NSRect(x:120,y:80,width:540,height:380),styleMask:[.borderless],backing:.buffered,defer:false)
host.overlay.isReleasedWhenClosed = false
host.scene = TianmuView(frame:host.overlay.contentView!.bounds)
host.store.state = ["timer":["mode":"countdown","status":"finished"]]
let timerBefore = NSDictionary(dictionary:host.store.timer)
host.showReminder()
let reminder = host.reminderWindow!
assert(reminder.isVisible, "Reminder was not ordered visible")
assert(reminder.styleMask.contains(.nonactivatingPanel), "Reminder must not activate the app")
assert(!reminder.isKeyWindow, "Reminder stole key focus")
assert(!host.panel.isVisible && host.presentation.route == nil, "Reminder opened management panel without a click")
reminder.contentView!.layoutSubtreeIfNeeded()
func pressButton(_ object: Any) -> Bool {
    guard let node = object as? NSAccessibilityProtocol else { return false }
    if node.accessibilityRole() == .button {
        return node.accessibilityPerformPress()
    }
    for child in node.accessibilityChildren() ?? [] {
        if pressButton(child) { return true }
    }
    return false
}
let didPress = pressButton(reminder.contentView!)
if didPress {
RunLoop.current.run(until:Date().addingTimeInterval(0.1))
assert(!reminder.isVisible, "Click did not hide reminder")
assert(host.presentation.route == "计时", "Click did not route to timer")
assert(host.panel.isVisible, "Click did not show sidebar")
assert(timerBefore.isEqual(to:host.store.timer), "Reminder click changed timer state")
print("CLICK_VERIFIED: accessible press hid reminder and opened timer sidebar")
} else {
print("CLICK_UNVERIFIED: standalone SwiftUI fixture exposes no accessible button; requires app-host UI validation")
}
host.panel.orderOut(nil); reminder.orderOut(nil); host.overlay.orderOut(nil)
NSStatusBar.system.removeStatusItem(host.statusItem)
print("PASS: reminder visible/nonactivating; no unsolicited sidebar; no worker/save; click status above")
'''
        with tempfile.TemporaryDirectory(dir=QA, prefix='reminder-') as folder:
            folder = Path(folder)
            (folder / 'Scene.swift').write_text(scene)
            (folder / 'main.swift').write_text(host + harness)
            binary = folder / 'check'
            build = subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
                str(folder / 'Scene.swift'), str(ROOT / 'native/v1/Presentation.swift'),
                str(ROOT / 'native/v1/WindowPlacement.swift'), str(ROOT / 'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT / 'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'), str(folder / 'main.swift'), '-o', str(binary)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('PASS: reminder', run.stdout)
            print(run.stdout.strip())
