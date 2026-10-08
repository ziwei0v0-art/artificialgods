"""Exercise AppKit's delegate notification path without starting a game worker."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QA = Path('/tmp/tianmu-qa-0929-focus')


class NativeFocusTests(unittest.TestCase):
    def test_appkit_resign_notification_dismisses_only_own_panel(self):
        QA.mkdir(parents=True, exist_ok=True)
        host = (ROOT / 'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        scene = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        harness = r'''
final class ObservedPanel: NSWindow {
    var dismissals = 0
    override func orderOut(_ sender: Any?) {
        dismissals += 1
        super.orderOut(sender)
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let host = ApplicationHost()
let panel = ObservedPanel(contentRect:NSRect(x:0,y:0,width:480,height:580),styleMask:[.titled],backing:.buffered,defer:false)
panel.isReleasedWhenClosed = false
host.panel = panel
// Same delegate assignment as applicationDidFinishLaunching; never start the worker.
panel.delegate = host
assert(panel.delegate === host)
var notices = 0
let observer = NotificationCenter.default.addObserver(forName:NSWindow.didResignKeyNotification,object:panel,queue:nil) { _ in notices += 1 }
host.store.state = ["timer": ["mode":"countdown", "status":"running", "deadline":12345]]
let timerBefore = NSDictionary(dictionary:host.store.timer)
host.presentation.beginRitual(now:100)
for route in ["虫瓶", "计时"] {
    host.presentation.open(route)
    host.store.sale = ["token":"test-only"]
    let before = panel.dismissals
    let countBefore = notices
    // AppKit emits the notification. Do not directly invoke host.windowDidResignKey.
    panel.resignKey()
    assert(notices == countBefore + 1, "AppKit did not emit didResignKey")
    assert(panel.dismissals > before, "Delegate did not reach dismissPanel/orderOut")
    assert(host.presentation.route == nil, "Sidebar route survived resign-key notification")
    assert(host.store.sale == nil, "Pending local sale preview was not cleared")
    assert(timerBefore.isEqual(to:host.store.timer), "Closing sidebar changed timer")
    assert(host.presentation.ritualStage(now:100.2) == "迎候", "Closing sidebar stopped ritual")
}
host.presentation.open("神前")
let other = NSWindow(contentRect:.zero,styleMask:[.titled],backing:.buffered,defer:false)
other.isReleasedWhenClosed = false
NotificationCenter.default.post(name:NSWindow.didResignKeyNotification,object:other)
assert(host.presentation.route == "求签", "Unrelated window dismissed sidebar")
NotificationCenter.default.removeObserver(observer)
panel.delegate = nil
print("PASS: AppKit resignKey -> notification -> delegate -> dismissPanel, 2 routes; foreign window ignored; timer/ritual preserved; no worker/save/window shown")
'''
        with tempfile.TemporaryDirectory(dir=QA, prefix='host-focus-') as folder:
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
            self.assertIn('PASS: AppKit resignKey', run.stdout)
            print(run.stdout.strip())
