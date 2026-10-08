"""Real JSON recovery roundtrip, temporary saves and hidden native controls only.

The Swift fixture never calls Store.start; Python owns WorkerSession in-process.
No worker process, game window, production save or process-discovery workflow runs.
"""
import importlib
import json
from pathlib import Path
import random
import selectors
import subprocess
import tempfile
import unittest

from tianmu_mvp.model import GameState, Insect
from tianmu_mvp.storage import _state_dict, load_state


ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000
HARNESS = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let store = Store()
var requests: [[String: Any]] = []
func emitJSON(_ object: [String: Any]) {
    FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: object) + Data([10]))
}
func readReply() -> Data {
    guard let line = readLine() else { fatalError("Missing Python response") }
    return Data(line.utf8) + Data([10])
}
store.requestSink = { request in requests.append(request); emitJSON(request) }
let initial = readReply()
store.receive(initial.prefix(11))
assert(store.runtimePhase == "starting", "Partial JSON must not produce a startup result")
store.receive(initial.dropFirst(11))
assert(store.runtimePhase == "recovery" && store.state.isEmpty)
let summary = store.recoveryInfo?["backup_summary"] as! [String: Any]
assert(summary["coins"] as? Int == 37)
assert(summary["desktop_count"] as? Int == 2 && summary["bottle_count"] as? Int == 1)
let originalToken = store.recoveryInfo?["token"] as! String
let controls = store.recoveryControls
let panel = RecoveryControlView(controls: controls)
let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 440),
                      styleMask: [.borderless], backing: .buffered, defer: false)
window.isReleasedWhenClosed = false
window.contentView = panel
assert(!window.isVisible && store.process == nil)
assert(panel.restoreButton.isEnabled && panel.backupLabel.stringValue.contains("37"))
panel.restoreButton.performClick(nil)
assert(requests.isEmpty && controls.confirmingToken == originalToken)
panel.cancelButton.performClick(nil)
assert(requests.isEmpty && controls.confirmingToken == nil)
panel.restoreButton.performClick(nil)
panel.confirmButton.performClick(nil)
panel.confirmButton.performClick(nil)
assert(requests.count == 1 && controls.isSubmitting && !panel.confirmButton.isEnabled)
assert(requests[0]["token"] as? String == originalToken && requests[0]["confirmed"] as? Bool == true)
store.receive(readReply())
let stale = CommandLine.arguments[1] == "stale"
if stale {
    assert(store.runtimePhase == "recovery" && store.startupIssue?["code"] as? String == "recovery_stale")
    assert(!controls.isSubmitting && controls.confirmingToken == nil && !controls.feedback.isEmpty)
    assert(!controls.canRestore && panel.inspectButton.isEnabled)
    panel.confirmButton.performClick(nil)
    assert(requests.count == 1, "Expired confirmation must not submit again")
    panel.inspectButton.performClick(nil)
    assert(requests.count == 2 && requests[1]["action"] as? String == "recovery_inspect")
    store.receive(readReply())
    let refreshedToken = controls.token!
    assert(refreshedToken != originalToken && panel.backupLabel.stringValue.contains("43"))
    assert(controls.confirmingToken == nil && !controls.isSubmitting)
    panel.restoreButton.performClick(nil)
    panel.confirmButton.performClick(nil)
    assert(requests.count == 3 && requests[2]["token"] as? String == refreshedToken)
    store.receive(readReply())
}
let expectedCoins = stale ? 43 : 37
assert(store.runtimePhase == "ready" && store.startupIssue == nil && store.recoveryInfo == nil)
assert(!controls.isSubmitting && controls.confirmingToken == nil)
assert(store.completions.isEmpty, "The real response id must settle the pending native request")
assert(store.coins == expectedCoins)
let desktopIDs = store.rows("desktop").compactMap { $0["id"] as? String }.sorted()
assert(desktopIDs == ["bug-00001", "bug-00002"])
let bottleCount = store.rows("bottle").reduce(0) { $0 + ($1["female"] as? Int ?? 0) + ($1["male"] as? Int ?? 0) }
assert(bottleCount == 1)
let white = store.rows("bottle").first { $0["color"] as? String == "白色" }!
assert(white["female"] as? Int == 1 && white["male"] as? Int == 0)
assert(store.process == nil && !window.isVisible)
emitJSON(["phase": store.runtimePhase, "coins": store.coins,
          "desktop_ids": desktopIDs, "bottle_count": bottleCount,
          "request_count": requests.count, "visible": window.isVisible])
window.close()
'''


class RecoveryRoundtripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix='tianmu-roundtrip-native-')
        cls.addClassCleanup(cls.build.cleanup)
        folder = Path(cls.build.name)
        (folder / 'main.swift').write_text(
            (ROOT / 'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
            + HARNESS)
        (folder / 'Scene.swift').write_text(
            (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        cls.binary = folder / 'roundtrip-native-check'
        result = subprocess.run([
            'swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
            str(folder / 'Scene.swift'),
            *(str(ROOT / 'native/v1' / name) for name in
              ['Presentation.swift', 'WindowPlacement.swift', 'DesktopInsects.swift', 'InsectArtwork.swift', 'TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']),
            str(folder / 'main.swift'), '-o', str(cls.binary),
        ], capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stderr)

    def setUp(self):
        try:
            self.recovery = importlib.import_module('tianmu_mvp.recovery')
            self.worker = importlib.import_module('tianmu_mvp.worker')
        except ImportError as error:
            self.fail('Recovery protocol is not available: ' + str(error))
        self.assertTrue(hasattr(self.worker, 'WorkerDriver'),
                        'Production WorkerDriver response envelope is not implemented')
        self.temporary = tempfile.TemporaryDirectory(prefix='tianmu-roundtrip-save-')
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'state.json'
        self.backup = self.path.with_name('state.json.bak')
        self.original = b'{broken original for roundtrip\xff'
        self.path.write_bytes(self.original)
        self.game = GameState.new(rng=random.Random(7))
        self.game.coins = 37
        self.game.desktop = {
            'bug-00001': Insect('bug-00001', 'F', ('Aa', 'Bb'), '普通褐色', 0.3, 0.4),
            'bug-00002': Insect('bug-00002', 'M', ('aa', 'Bb'), '深褐色', 0.7, 0.4),
        }
        self.game.bottle = {
            'bug-00003': Insect('bug-00003', 'F', ('aa', 'bb'), '白色', 0.5, 0.5),
        }
        self.game.discovered_colors = {'白色'}
        self.game.next_insect_number = 4
        self.game.game_timezone = 'UTC'
        self.game.onboarding = 'legacy'
        self.good = self.backup_bytes()
        self.backup.write_bytes(self.good)
        self.driver, self.startup = self.worker.bootstrap(self.path, NOW, NOW)
        self.assertIsNotNone(self.driver, self.startup)
        self.session = self.driver.session
        self.addCleanup(self.session.close)

    def backup_bytes(self):
        return json.dumps(_state_dict(self.game), ensure_ascii=False, indent=2).encode('utf-8')

    @staticmethod
    def wire(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n'

    def read_native_request(self, process, action='recovery_restore'):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=20), 'Native recovery control did not produce a request')
        line = process.stdout.readline()
        if not line:
            self.fail('Native control failed before its request: ' + process.stderr.read())
        request = json.loads(line)
        self.assertEqual(request['action'], action)
        if action == 'recovery_restore':
            self.assertIs(request['confirmed'], True)
        self.assertIs(type(request['id']), int)
        return request

    def run_roundtrip(self, stale=False):
        startup = self.startup
        self.assertIsNone(startup['id'])
        self.assertEqual(startup['phase'], 'recovery')
        self.assertEqual(startup['recovery']['backup_summary']['coins'], 37)
        self.assertEqual(self.path.read_bytes(), self.original)
        with subprocess.Popen([str(self.binary), 'stale' if stale else 'success'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) as native:
            native.stdin.write(self.wire(startup)); native.stdin.flush()
            first = self.read_native_request(native)
            self.assertEqual(first['id'], 1)
            self.assertEqual(first['token'], startup['recovery']['token'])
            if stale:
                self.game.coins = 43
                self.good = self.backup_bytes()
                self.backup.write_bytes(self.good)
            # Production driver invokes this session in-process and owns the id envelope.
            response = self.driver.handle(first, NOW, NOW)
            self.assertEqual(response['id'], first['id'])
            if stale:
                self.assertFalse(response['ok'])
                self.assertEqual(response['issue']['code'], 'recovery_stale')
                self.assertEqual(self.path.read_bytes(), self.original)
                native.stdin.write(self.wire(response)); native.stdin.flush()
                inspection = self.read_native_request(native, 'recovery_inspect')
                self.assertEqual(inspection['id'], 2)
                response = self.driver.handle(inspection, NOW, NOW)
                self.assertEqual(response['id'], inspection['id'])
                self.assertTrue(response['ok'])
                self.assertEqual(response['phase'], 'recovery')
                native.stdin.write(self.wire(response)); native.stdin.flush()
                renewed = self.read_native_request(native)
                self.assertEqual(renewed['id'], 3)
                self.assertNotEqual(renewed['token'], first['token'])
                self.assertEqual(renewed['token'], response['recovery']['token'])
                response = self.driver.handle(renewed, NOW, NOW)
                self.assertEqual(response['id'], renewed['id'])
            self.assertTrue(response['ok'])
            self.assertEqual(response['phase'], 'ready')
            stdout, stderr = native.communicate(self.wire(response), timeout=20)
            self.assertEqual(native.returncode, 0, stdout + stderr)
            final = json.loads(stdout)
        self.assertEqual(final, {'phase': 'ready', 'coins': 43 if stale else 37,
                                 'desktop_ids': ['bug-00001', 'bug-00002'], 'bottle_count': 1,
                                 'request_count': 3 if stale else 1, 'visible': False})
        self.assertEqual(self.path.read_bytes(), self.good)
        self.assertEqual(self.backup.read_bytes(), self.good)
        restored = load_state(self.path)
        self.assertEqual(restored.coins, final['coins'])
        self.assertEqual(set(restored.desktop), {'bug-00001', 'bug-00002'})
        self.assertEqual(set(restored.bottle), {'bug-00003'})
        self.assertEqual(restored.elapsed_seconds, 0)
        print('PASS real recovery JSON roundtrip:', 'stale then reconfirm' if stale else 'restore',
              '; no worker process or visible window')

    def test_real_backup_recovers_through_native_confirmation_and_request_id(self):
        self.run_roundtrip()

    def test_changed_backup_invalidates_native_confirmation_before_new_restore(self):
        self.run_roundtrip(stale=True)


if __name__ == '__main__':
    unittest.main()
