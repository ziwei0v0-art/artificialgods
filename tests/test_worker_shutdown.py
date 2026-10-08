"""Headless Store shutdown against owned temporary workers; never a user save/UI."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
STUBS = r'''
final class WeatherAtmosphereStore {}
protocol TimerNotificationClient {}
final class SystemTimerNotificationClient: TimerNotificationClient {}
final class TimerNotifications {
    init(client: TimerNotificationClient) {}
    func timerCompleted(enabled: Bool) {}
}
enum SceneExitAction { case hideShrine, hideCompanions, quitApplication }
enum InsectStyle { case cute }
func normalizedSceneScale(_ value: Double) -> Double { value }
final class SceneTransparencyStore { static func normalized(_ value: Double) -> Double { value } }
final class FixtureControls {
    init(store: Store) {}
    func refresh() {}
}
typealias RecoveryControls = FixtureControls
typealias TimerControls = FixtureControls
typealias BottleControls = FixtureControls
typealias ShopControls = FixtureControls
typealias GameSettingsControls = FixtureControls
extension Dictionary where Key == String, Value == Any {
    var colorKey: String { self["color"] as? String ?? "" }
}
'''
FAKE_WORKER = r'''
import fcntl, json, os, signal, subprocess, sys, time
from pathlib import Path
if os.getpgrp() != os.getpid():
    os.setpgid(0, 0)
mode, path = sys.argv[1], Path(sys.argv[2]).resolve()
if mode in ('normal', 'recovery', 'save_failed', 'before_replace', 'after_replace'):
    sys.path.insert(0, sys.argv[3])
    from tianmu_mvp import worker
    if mode == 'save_failed':
        from tianmu_mvp import service
        def fail_save(*args):
            raise OSError('isolated disk failure')
        service.save_state = fail_save
    if mode in ('before_replace', 'after_replace'):
        from tianmu_mvp import service, storage
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        replace, save = storage.os.replace, service.save_state
        def blocked_replace(source, destination):
            is_primary = str(destination) == str(path)
            if is_primary and mode == 'before_replace':
                while True: time.sleep(.1)
            replace(source, destination)
            if is_primary and mode == 'after_replace':
                while True: time.sleep(.1)
        def changed_save(filename, state):
            state.coins = 23
            save(filename, state)
        storage.os.replace, service.save_state = blocked_replace, changed_save
    sys.argv = ['worker', '--save-file', str(path)]
    raise SystemExit(worker.main())
lock = open(str(path) + '.lock', 'a+')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
if mode in ('blocked', 'ignore_term', 'failed', 'starting', 'force'):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode in ('descendant', 'retry_first'):
    child = subprocess.Popen([sys.executable, '-c',
        'import pathlib,signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(sys.argv[1]).touch(); time.sleep(60)',
        str(path) + '.child.ready'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(str(path) + '.child.pid').write_text(str(child.pid))
    while not Path(str(path) + '.child.ready').exists():
        time.sleep(.01)
if mode == 'zombie':
    keeper_code = """import os,pathlib,sys,time
group, path = int(sys.argv[1]), pathlib.Path(sys.argv[2])
os.setpgid(0, 0)
child = os.fork()
if child == 0:
    os.setpgid(0, group)
    os._exit(0)
path.write_text(str(child))
time.sleep(60)
"""
    keeper = subprocess.Popen([sys.executable, '-c', keeper_code, str(os.getpgrp()), str(path) + '.zombie.pid'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(str(path) + '.keeper.pid').write_text(str(keeper.pid))
    while not Path(str(path) + '.zombie.pid').exists():
        time.sleep(.01)
    zombie = Path(str(path) + '.zombie.pid').read_text()
    while not subprocess.check_output(['ps', '-o', 'stat=', '-p', zombie], text=True).strip().startswith('Z'):
        time.sleep(.01)
if mode != 'starting':
    print(json.dumps({'phase':'ready', 'ok':True, 'state':{'coins':7}}), flush=True)
if mode == 'retry_first':
    raise SystemExit(2)
requests = []
while True:
    if mode in ('blocked', 'ignore_term', 'starting', 'force'):
        time.sleep(.1)
    else:
        line = sys.stdin.readline()
        if not line:
            time.sleep(.1)
            continue
        request = json.loads(line)
        requests.append(request)
        Path(str(path) + '.requests').write_text(json.dumps(requests))
        if mode in ('late', 'ordered', 'descendant', 'zombie'):
            result = {'id':request['id'], 'ok':True, 'phase':'ready'}
            if mode == 'late' and request['action'] == 'quit':
                result.update(state={'coins':999}, events=['timer_expired'])
            print(json.dumps(result), flush=True)
            if request['action'] == 'quit':
                raise SystemExit(0)
'''
HARNESS = r'''
func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { fputs("FAIL: \(message)\n", stderr); exit(1) }
}
func pump(until condition: () -> Bool, seconds: Double) {
    let deadline = Date().addingTimeInterval(seconds)
    while !condition() && Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.01))
    }
}
var launches = 0
func fixtureWorker() throws -> (Process, Pipe, Pipe) {
    let retry = CommandLine.arguments[1] == "retry"
    if retry && launches > 0 {
        let child = Int32(try! String(contentsOfFile: CommandLine.arguments[4] + ".child.pid", encoding: .utf8))!
        require(Darwin.kill(child, 0) != 0, "Retry must remove the old worker group before replacing ownership")
    }
    launches += 1
    let process = Process(), input = Pipe(), output = Pipe()
    process.executableURL = URL(fileURLWithPath: CommandLine.arguments[2])
    let fixtureMode = retry ? (launches == 1 ? "retry_first" : "silent") : CommandLine.arguments[1]
    process.arguments = [CommandLine.arguments[3], fixtureMode, CommandLine.arguments[4], CommandLine.arguments[5]]
    process.standardInput = input; process.standardOutput = output
    process.standardError = FileHandle.standardError
    try process.run()
    try String(process.processIdentifier).write(toFile: CommandLine.arguments[4] + ".pid", atomically: true, encoding: .utf8)
    return (process, input, output)
}
let store = Store()
store.workerLauncher = fixtureWorker
let mode = CommandLine.arguments[1]
if mode == "ownership" {
    let (unowned, input, output) = try! fixtureWorker()
    store.process = unowned; store.input = input; store.output = output
    var done = 0
    store.shutdown { done += 1 }
    store.forceStop()
    store.shutdown { done += 1 }
    pump(until: { done == 2 }, seconds: 0.2)
    require(done == 2 && unowned.isRunning, "A Process merely assigned to Store must never be signalled")
    // This fixture created the sentinel itself; cleanup is not a Store action.
    _ = Darwin.kill(unowned.processIdentifier, SIGKILL)
    pump(until: { !unowned.isRunning }, seconds: 0.5)
    require(!unowned.isRunning, "The fixture must reap its own sentinel")
    print("PASS ownership; NO_WINDOWS_TEMPORARY_WORKER_ONLY")
    exit(0)
}
store.start()
if mode == "retry" {
    pump(until: { store.runtimePhase == "failed" && store.process?.isRunning == false }, seconds: 3)
    require(store.runtimePhase == "failed", "First temporary worker must fail after creating its child")
    let orphan = Int32(try! String(contentsOfFile: CommandLine.arguments[4] + ".child.pid", encoding: .utf8))!
    pump(until: { Darwin.kill(orphan, 0) != 0 }, seconds: 0.5)
    require(Darwin.kill(orphan, 0) != 0, "An idle failed Store must retire its old group without waiting for retry or quit")
    store.retryOpening()
}
if mode != "starting" {
    let expected = mode == "recovery" ? "recovery" : "ready"
    pump(until: { store.runtimePhase == expected }, seconds: 3)
    require(store.runtimePhase == expected, "Temporary worker must reach \(expected)")
}
let worker = store.process!
let pid = worker.processIdentifier
if mode == "normal" {
    var saved = false
    store.send("timer_start", ["mode":"countdown", "duration":"90s"]) { saved = $0 }
    pump(until: { saved }, seconds: 3)
    require(saved, "Normal command must be saved before its reply")
}
if mode == "failed" { store.transportStopped(status: nil) }
var updates = 0, reminders = 0, sounds = 0
store.onState = { _ in updates += 1 }
store.onReminder = { reminders += 1 }
store.playSound = { sounds += 1 }
let start = Date()
if mode == "blocked" || mode == "force" {
    for _ in 0..<8 { store.send("snapshot", ["padding": String(repeating: "x", count: 131072)]) }
}
if mode == "ordered" {
    for _ in 0..<25 { store.send("snapshot") }
}
var completed = 0
func finished() {
    require(Thread.isMainThread, "Shutdown completion must run on the main thread")
    require(!worker.isRunning && Darwin.kill(pid, 0) != 0, "Completion must follow actual worker exit")
    completed += 1
}
if mode == "force" { store.forceStop() }
store.shutdown(completion: finished)
store.shutdown(completion: finished)
var rejected: Bool?
store.send("buy", ["item":"bell"]) { rejected = !$0 }
require(rejected == true, "Shutdown must reject new game commands")
pump(until: { completed == 2 }, seconds: 1.8)
require(!worker.isRunning, "An unresponsive owned worker must be gone within the shutdown deadline")
require(completed == 2, "Every shutdown caller must complete exactly once after process cleanup")
RunLoop.current.run(until: Date().addingTimeInterval(0.05))
require(completed == 2 && updates == 0 && reminders == 0 && sounds == 0,
        "Late replies cannot change state, notify, or repeat shutdown completion")
require(Date().timeIntervalSince(start) < 2, "Pipe writes and shutdown must not block the main thread")
if mode == "force" { require(Date().timeIntervalSince(start) < 0.5, "Force stop must bypass the normal grace window") }
print("PASS \(mode) \(Date().timeIntervalSince(start)); NO_WINDOWS_TEMPORARY_WORKER_ONLY")
'''


class WorkerShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-shutdown-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.fake = cls.folder / 'worker.py'
        cls.fake.write_text(FAKE_WORKER)
        source = (ROOT / 'native/v1/main.swift').read_text().split('struct SmallHeading:')[0]
        main = cls.folder / 'main.swift'
        main.write_text(source + STUBS + HARNESS)
        cls.binary = cls.folder / 'check'
        result = subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
                                 str(main), '-o', str(cls.binary)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, mode):
        with tempfile.TemporaryDirectory(prefix='tianmu-owned-worker-') as directory:
            path = Path(directory) / 'state.json'
            original, backup = b'{isolated broken save', b'isolated original backup'
            if mode in ('recovery', 'save_failed', 'before_replace', 'after_replace'):
                if mode != 'recovery':
                    from tianmu_mvp.model import GameState
                    from tianmu_mvp.storage import _state_dict
                    game = GameState.new(); game.coins = 13
                    original = json.dumps(_state_dict(game)).encode()
                path.write_bytes(original)
                Path(str(path) + '.bak').write_bytes(backup)
            def clean_owned_worker():
                pidfile = Path(str(path) + '.pid')
                if pidfile.exists():
                    pid = int(pidfile.read_text())
                    try:
                        if os.getpgid(pid) == pid:
                            os.killpg(pid, signal.SIGKILL)
                        else:
                            os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for suffix in ('.child.pid', '.keeper.pid'):
                    childfile = Path(str(path) + suffix)
                    if childfile.exists():
                        try:
                            os.kill(int(childfile.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            run = subprocess.Popen([str(self.binary), mode, sys.executable, str(self.fake), str(path), str(ROOT)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                try:
                    stdout, stderr = run.communicate(timeout=6)
                except subprocess.TimeoutExpired:
                    run.kill()
                    clean_owned_worker()
                    stdout, stderr = run.communicate(timeout=2)
                    self.fail('Main thread blocked on worker pipe or shutdown: ' + stdout + stderr)
                self.assertEqual(run.returncode, 0, stdout + stderr)
                self.assertIn('NO_WINDOWS_TEMPORARY_WORKER_ONLY', stdout)
                print(stdout.strip())
                pid = int(Path(str(path) + '.pid').read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                with open(str(path) + '.lock', 'a+') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if mode == 'normal':
                    state = json.loads(path.read_bytes())
                    self.assertEqual(state['timer_session']['countdown_seconds'], 90)
                    self.assertEqual(state['timer_session']['status'], 'running')
                if mode in ('recovery', 'save_failed'):
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(Path(str(path) + '.bak').read_bytes(), backup)
                if mode in ('before_replace', 'after_replace'):
                    from tianmu_mvp.storage import decode_state_bytes
                    saved = decode_state_bytes(path.read_bytes())
                    self.assertEqual(saved.coins, 13 if mode == 'before_replace' else 23)
                    self.assertEqual(Path(str(path) + '.bak').read_bytes(), original)
                    if mode == 'before_replace':
                        self.assertEqual(path.read_bytes(), original)
                if mode == 'ordered':
                    requests = json.loads(Path(str(path) + '.requests').read_text())
                    self.assertEqual([item['id'] for item in requests], list(range(1, 27)))
                    self.assertEqual([item['action'] for item in requests], ['snapshot'] * 25 + ['quit'])
                if mode in ('descendant', 'retry'):
                    child = int(Path(str(path) + '.child.pid').read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child, 0)
            finally:
                if run.poll() is None:
                    run.kill(); run.wait(timeout=2)
                clean_owned_worker()

    def test_unresponsive_worker_is_terminated(self):
        self.run_case('silent')

    def test_full_stdin_pipe_does_not_block_main_thread(self):
        self.run_case('blocked')

    def test_term_ignoring_worker_is_killed(self):
        self.run_case('ignore_term')

    def test_failed_runtime_still_cleans_up_worker(self):
        self.run_case('failed')

    def test_starting_worker_has_same_shutdown_deadline(self):
        self.run_case('starting')

    def test_force_stop_bypasses_blocked_pipe_and_grace_period(self):
        self.run_case('force')

    def test_normal_quit_saves_timer_and_releases_lock(self):
        self.run_case('normal')

    def test_recovery_quit_preserves_original_and_backup(self):
        self.run_case('recovery')

    def test_save_failure_cannot_veto_exit_or_replace_files(self):
        self.run_case('save_failed')

    def test_late_replies_cannot_update_or_notify(self):
        self.run_case('late')

    def test_serial_requests_finish_in_order_before_quit(self):
        self.run_case('ordered')

    def test_owned_descendant_is_gone_before_completion(self):
        self.run_case('descendant')

    def test_process_not_launched_by_store_is_never_signalled(self):
        self.run_case('ownership')

    def test_forced_exit_before_atomic_replace_keeps_original(self):
        self.run_case('before_replace')

    def test_forced_exit_after_atomic_replace_keeps_complete_new_save_and_backup(self):
        self.run_case('after_replace')

    def test_retry_reaps_previous_worker_group_before_replacing_ownership(self):
        self.run_case('retry')

    def test_only_zombies_in_owned_group_cannot_hold_exit_open(self):
        self.run_case('zombie')


if __name__ == '__main__':
    unittest.main()
