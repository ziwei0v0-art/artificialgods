"""Native timer controls with a recording command transport; no worker or visible windows."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
final class TimerTestNotifications: TimerNotificationClient {
    var onOpen: (() -> Void)?
    var submitted = 0
    func settings(_ done: @escaping (NotificationAccess) -> Void) { done(.authorized) }
    func requestPermission(_ done: @escaping (String?) -> Void) { fatalError("No permissions in tests") }
    func submit(_ done: @escaping (String?) -> Void) { submitted += 1; done(nil) }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let notifications = TimerTestNotifications()
let store = Store(notificationClient: notifications)
var commands: [(String, [String: Any])] = []
store.commandSink = { action, values, done in commands.append((action, values)); done?(true) }
func snapshot(_ status: String, _ readout: String, mode: String = "countdown", events: [String] = []) {
    let reply: [String: Any] = ["ok": true, "state": ["timer": ["mode": mode, "status": status,
        "readout": readout, "clock_readout": "13:20:30\n午正一刻", "countdown_seconds": 300,
        "work_seconds": 1500, "break_seconds": 300, "sound_enabled": true,
        "widget_enabled": true, "notification_enabled": true]], "events": events]
    store.receive(try! JSONSerialization.data(withJSONObject: reply) + Data([10]))
}
snapshot("idle", "05:00")
let controls = store.timerControls
let quick = TimerControlPanelView(controls: controls, surface: .quick)
let detached = TimerControlPanelView(controls: controls, surface: .detached)
let test = CommandLine.arguments[1]
switch test {
case "daily_flow":
    let inputs = quick.subviews.compactMap { $0 as? NSTextField }.filter { $0.isEditable }
    assert(inputs.count == 1, "A custom duration must be editable in the quick tool without opening settings")
    let input = inputs[0]
    let begin = quick.subviews.compactMap { $0 as? NSButton }.first { $0.title == "开始" }!
    var acknowledgement: ((Bool) -> Void)?
    store.commandSink = { action, values, done in commands.append((action, values)); acknowledgement = done }
    input.stringValue = "  90s  "
    let editor = NSTextView()
    editor.string = "  90s  "
    assert(quick.control(input,textView:editor,doCommandBy:#selector(NSResponder.insertNewline(_:))))
    assert(commands.count == 1 && commands[0].0 == "timer_start")
    assert(commands[0].1["duration"] as? String == "90s")
    assert(controls.isSubmitting && quick.readout.stringValue == "05:00", "Pending save must not pretend the timer started")
    begin.performClick(nil)
    assert(commands.count == 1, "Return and a quick extra click must not start twice")
    acknowledgement?(false)
    assert(input.stringValue == "  90s  " && !controls.feedback.isEmpty && !controls.isSubmitting)
    snapshot("running", "04:57")
    input.sendAction(input.action!, to: input.target)
    assert(commands.count == 1 && controls.pending?.surface == .quick)
    quick.cancelButton.performClick(nil)
    assert(controls.pending == nil && commands.count == 1)
    input.stringValue = "   "
    input.sendAction(input.action!, to: input.target)
    assert(commands.count == 1 && controls.pending == nil && !controls.feedback.isEmpty)
    assert(detached.subviews.compactMap { $0 as? NSTextField }.contains { $0.isEditable }, "Detached tool must also accept a duration in place")
case "restart":
    let restart = quick.subviews.compactMap { $0 as? NSButton }.first { $0.title == "重来" }
    assert(restart != nil, "Timer controls need a direct start-over action")
    snapshot("paused", "01:23")
    restart!.performClick(nil)
    assert(commands.isEmpty && controls.pending?.request.duration == "300s", "Restart uses original duration, never the remaining readout")
    quick.confirmButton.performClick(nil)
    assert(commands.count == 1 && commands[0].1["replace"] as? Bool == true)
    snapshot("finished", "00:00")
    restart!.performClick(nil)
    assert(commands.count == 2 && commands[1].1["replace"] as? Bool == false)
    snapshot("finished", "00:00", mode: "pomodoro")
    assert(quick.primaryButton.title == "下一段")
    restart!.performClick(nil)
    assert(commands.last?.1["mode"] as? String == "pomodoro" && commands.last?.1["work"] as? String == "1500s" && commands.last?.1["rest"] as? String == "300s")
    assert(!commands.contains { $0.0 == "timer_next" }, "Restart and manual next phase must remain distinct")
    snapshot("idle", "13:20:30", mode: "clock")
    assert(!restart!.isEnabled)
case "preset_save":
    controls.beginPresetEditing()
    assert(controls.editingPresets && controls.presetDrafts == ["5","15","25","45"])
    controls.presetDrafts = ["90s","12","1h30m","24h"]
    var acknowledgement: ((Bool) -> Void)?
    store.commandSink = { action, values, done in commands.append((action, values)); acknowledgement = done }
    controls.savePresetEdits(); controls.savePresetEdits()
    assert(commands.count == 1 && commands.last?.0 == "timer_preferences" && controls.isSubmitting)
    assert(commands.last?.1["preset_durations"] as? [String] == controls.presetDrafts)
    assert(quick.presetButtons[0].title == "5分", "Editing a draft must not optimistically replace a saved shortcut")
    controls.cancelPresetEditing()
    assert(controls.editingPresets, "Save in progress cannot silently close its draft")
    acknowledgement?(false)
    assert(controls.editingPresets && !controls.presetFeedback.isEmpty && !controls.isSubmitting)
    assert(quick.presetButtons[0].title == "5分")
    controls.savePresetEdits()
    assert(commands.count == 2 && commands.allSatisfy { $0.0 == "timer_preferences" })
    var custom = store.timer; custom["preset_seconds"] = [90,720,5400,86400]
    store.state = ["timer": custom]; acknowledgement?(true)
    assert(!controls.editingPresets && !controls.isSubmitting && controls.presetFeedback.isEmpty)
    assert(quick.presetButtons[0].title == "90秒")
    controls.beginPresetEditing(); controls.presetDrafts[0] = "3"
    controls.cancelPresetEditing()
    assert(commands.count == 2 && controls.presetSeconds[0] == 90)
case "presets":
    var custom = store.timer
    custom["preset_seconds"] = [90,720,5400,86400]
    store.state = ["timer": custom]
    quick.presetButtons[0].performClick(nil)
    assert(commands.last?.1["duration"] as? String == "90s", "Configured 90-second preset must not silently run the old five minutes")
    assert(quick.presetButtons.map(\.title) == ["90秒","12分","90分","24时"])
    assert(quick.presetButtons[0].toolTip == "90秒")
    quick.presetButtons[1].performClick(nil)
    assert(commands.last?.1["duration"] as? String == "12")
    custom["preset_seconds"] = [300,900,1500,2700]
    store.state = ["timer": custom]
    quick.presetButtons[2].performClick(nil)
    assert(commands.last?.1["duration"] as? String == "25")
case "shared":
    assert(quick.controls === detached.controls && controls === store.timerControls)
    snapshot("running", "04:57")
    assert(quick.readout.stringValue == "04:57" && detached.readout.stringValue == "04:57")
    quick.primaryButton.performClick(nil)
    assert(commands.last?.0 == "timer_pause")
    snapshot("paused", "04:55")
    assert(quick.primaryButton.title == "继续" && detached.primaryButton.title == "继续")
    detached.primaryButton.performClick(nil)
    assert(commands.last?.0 == "timer_resume")
    snapshot("running", "04:55")
    detached.endButton.performClick(nil)
    assert(commands.last?.0 == "timer_end")
    controls.prepareEditor()
    controls.draftMode = "stopwatch"
    let detailed = TimerView(store: store)
    let before = commands.count
    detailed.begin()
    assert(commands.count == before && controls.pending?.surface == .sidebar)
    controls.confirmReplacement(from: .sidebar)
    assert(commands.last?.0 == "timer_start" && commands.last?.1["mode"] as? String == "stopwatch")
    snapshot("finished", "00:00", mode: "pomodoro")
    detached.primaryButton.performClick(nil)
    assert(commands.last?.0 == "timer_next")
    snapshot("idle", "13:20:30\n午正一刻", mode: "clock")
    assert(detached.readout.stringValue == "13:20:30" && detached.detail.stringValue.contains("午正一刻"))
case "replace":
    snapshot("running", "11:00")
    quick.presetButtons[0].performClick(nil)
    assert(commands.isEmpty && controls.pending != nil)
    controls.cancelReplacement(from: .quick)
    assert(commands.isEmpty && controls.pending == nil)
    quick.presetButtons[2].performClick(nil)
    assert(controls.pending?.request.duration == "25")
    controls.confirmReplacement(from: .detached)
    assert(commands.isEmpty, "Other view must not confirm an unseen request")
    var acknowledgement: ((Bool) -> Void)?
    store.commandSink = { action, values, done in commands.append((action, values)); acknowledgement = done }
    controls.confirmReplacement(from: .quick)
    controls.confirmReplacement(from: .quick)
    quick.presetButtons[1].performClick(nil)
    assert(commands.count == 1 && commands[0].1["replace"] as? Bool == true)
    assert(commands[0].1["duration"] as? String == "25" && controls.isSubmitting)
    snapshot("running", "25:00")
    acknowledgement?(true)
    assert(!controls.isSubmitting)
    controls.start(TimerStartRequest(mode: "stopwatch"), from: .sidebar)
    controls.confirmReplacement(from: .sidebar)
    acknowledgement?(false)
    assert(!controls.isSubmitting && !controls.feedback.isEmpty)
case "compact":
    assert(detached.bounds.height <= 160 && detached.durationInput.isHidden, "A resident timer must default to compact readout and actions")
    let edit = detached.subviews.compactMap { $0 as? NSButton }.first { $0.title == "设时长" }!
    edit.performClick(nil)
    assert(detached.bounds.height > 132 && detached.bounds.height <= 194 && !detached.durationInput.isHidden)
    detached.durationInput.stringValue = "8m"
    edit.performClick(nil)
    assert(detached.bounds.height <= 160 && detached.durationInput.isHidden && detached.durationInput.stringValue == "8m")
    snapshot("running","02:00")
    detached.restartButton.performClick(nil)
    assert(detached.bounds.height > 132 && detached.bounds.height <= 194 && !detached.confirmButton.isHidden && detached.durationInput.isHidden)
    detached.cancelButton.performClick(nil)
    assert(detached.bounds.height <= 160 && controls.pending == nil && commands.isEmpty)
case "position":
    let folder = URL(fileURLWithPath:NSTemporaryDirectory()).appendingPathComponent("tianmu-timer-position-" + UUID().uuidString)
    let url = folder.appendingPathComponent("position.json")
    defer { try? FileManager.default.removeItem(at:folder) }
    let screen = NSRect(x:0,y:0,width:1440,height:850)
    let anchor = NSRect(x:20,y:20,width:180,height:120)
    let first = TimerToolWindows(controls:controls,screens:{[screen]},placementURL:url,present:{_ in})
    first.showDetached(near:anchor)
    let moved = first.detachedWindow!
    moved.setFrameOrigin(NSPoint(x:700,y:390))
    first.windowDidMove(Notification(name:NSWindow.didMoveNotification,object:moved))
    let expandedView = moved.contentView as! TimerControlPanelView
    let edit = expandedView.subviews.compactMap { $0 as? NSButton }.first { $0.title == "设时长" }!
    let anchoredTop = moved.frame.maxY
    edit.performClick(nil)
    assert(moved.frame.maxY == anchoredTop, "Expanding input must keep the title bar in place")
    first.dismiss(.detached)
    assert(FileManager.default.fileExists(atPath:url.path))
    let reopened = TimerToolWindows(controls:controls,screens:{[screen]},placementURL:url,present:{_ in})
    assert(!reopened.detachedPresented && reopened.detachedWindow == nil, "Restoring placement must not reopen a hidden timer by itself")
    reopened.showDetached(near:anchor)
    assert(reopened.detachedWindow!.frame.origin == NSPoint(x:700,y:390))
    let smallerScreen = NSRect(x:0,y:0,width:800,height:500)
    let rehomed = TimerToolWindows(controls:controls,screens:{[smallerScreen]},placementURL:url,present:{_ in})
    rehomed.showDetached(near:anchor)
    assert(smallerScreen.contains(rehomed.detachedWindow!.frame), "Old monitor placement must restore visibly")
    try! Data("{broken".utf8).write(to:url)
    let invalid = TimerToolWindows(controls:controls,screens:{[screen]},placementURL:url,present:{_ in})
    invalid.showDetached(near:anchor)
    assert(screen.contains(invalid.detachedWindow!.frame) && commands.isEmpty)
    for tool in [first,reopened,rehomed,invalid] {
        assert(!tool.detachedWindow!.isVisible)
        tool.dismissAll()
    }
case "expanded_position":
    let folder=URL(fileURLWithPath:NSTemporaryDirectory()).appendingPathComponent("tianmu-timer-expanded-position-"+UUID().uuidString)
    let url=folder.appendingPathComponent("position.json")
    defer { try? FileManager.default.removeItem(at:folder) }
    try! FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
    try! JSONSerialization.data(withJSONObject:["x":700,"y":390]).write(to:url)
    let screen=NSRect(x:0,y:0,width:1440,height:850), anchor=NSRect(x:20,y:20,width:180,height:120)
    func savedOrigin() -> NSPoint {
        let json=try! JSONSerialization.jsonObject(with:Data(contentsOf:url)) as! [String:Double]
        return NSPoint(x:json["x"]!,y:json["y"]!)
    }
    controls.reportPositionFailure()
    let expanded=TimerToolWindows(controls:controls,screens:{[screen]},placementURL:url,present:{_ in})
    expanded.showDetached(near:anchor)
    let window=expanded.detachedWindow!
    assert(window.contentView!.bounds.height == 178,"The initial saved-position recovery includes the error row")
    assert(window.frame.minX == 700 && window.frame.maxY == 522,
        "A saved compact origin restores the same top edge when initial feedback expands the window")
    let expandedFrame=window.frame
    expanded.dismiss(.detached)
    assert(savedOrigin() == NSPoint(x:700,y:390),"Closing initially expanded content must not add its extra height to the saved origin")
    expanded.showDetached(near:anchor)
    assert(window.frame == expandedFrame,"Same-process current frame is not converted from compact coordinates a second time")
    expanded.dismiss(.detached)
    assert(savedOrigin() == NSPoint(x:700,y:390))
    let reopened=TimerToolWindows(controls:controls,screens:{[screen]},placementURL:url,present:{_ in})
    reopened.showDetached(near:anchor)
    assert(reopened.detachedWindow!.frame.maxY == 522,"A new tool restores the same expanded top again")
    reopened.dismiss(.detached)
    snapshot("running","04:59")
    controls.startCustom("一盏茶",from:.detached)
    assert(controls.pending?.surface == .detached && commands.isEmpty)
    let confirming=TimerToolWindows(controls:controls,screens:{[screen]},placementURL:url,present:{_ in})
    confirming.showDetached(near:anchor)
    assert(confirming.detachedWindow!.contentView!.bounds.height == 194)
    assert(confirming.detachedWindow!.frame.maxY == 522,"Initial replacement confirmation uses the same compact-origin conversion")
    confirming.dismiss(.detached)
    assert(savedOrigin() == NSPoint(x:700,y:390),"Cancel-on-close preserves the compact saved coordinate")
    for tool in [expanded,reopened,confirming] { assert(!tool.detachedWindow!.isVisible) }
    assert(commands.isEmpty && store.process == nil)
case "windows":
    snapshot("running", "02:00")
    let timerBefore = NSDictionary(dictionary: store.timer)
    let screen = NSRect(x: -1440, y: -120, width: 1440, height: 870)
    var presented = 0
    let tools = TimerToolWindows(controls: controls, screens: { [screen] }, present: { _ in presented += 1 })
    let anchor = NSRect(x: -80, y: -110, width: 74, height: 38)
    tools.showQuick(near: anchor)
    assert(screen.contains(tools.quickWindow!.frame) && tools.quickPresented)
    assert(!tools.quickWindow!.isVisible)
    let windowQuickView = tools.quickWindow!.contentView as! TimerControlPanelView
    assert(tools.quickWindow!.initialFirstResponder === windowQuickView.durationInput)
    windowQuickView.presetButtons[0].performClick(nil)
    assert(controls.pending != nil)
    tools.quickWindow!.onEscape()
    assert(controls.pending == nil && tools.quickPresented && commands.isEmpty, "Escape should cancel an open replacement without hiding the tool")
    tools.showDetached(near: anchor)
    assert(!tools.quickPresented && tools.detachedPresented && presented == 2)
    assert(screen.contains(tools.detachedWindow!.frame) && !tools.detachedWindow!.isVisible)
    let window = tools.detachedWindow!
    assert(!window.styleMask.contains(.titled) && window.isMovableByWindowBackground, "Borderless timer retains background dragging")
    window.setFrameOrigin(NSPoint(x: -1050, y: 300))
    tools.windowDidMove(Notification(name: NSWindow.didMoveNotification, object: window))
    assert(tools.windowShouldClose(window) == false && !tools.detachedPresented)
    tools.showDetached(near: anchor)
    assert(tools.detachedWindow === window && window.frame.origin == NSPoint(x: -1050, y: 300))
    tools.dismissAll()
    assert(commands.isEmpty && timerBefore.isEqual(to: store.timer))
    assert(!window.isVisible && !tools.quickWindow!.isVisible)
case "layout":
    let screens = [NSRect(x: 0,y: 0,width: 1440,height: 850), NSRect(x: -1280,y: -150,width: 1280,height: 850)]
    for anchor in [NSRect(x: -40,y: -145,width: 36,height: 20), NSRect(x: -1275,y: 670,width: 30,height: 20), NSRect(x: 1410,y: 830,width: 20,height: 15)] {
        let fitted = timerToolFrame(near: anchor, size: NSSize(width: 360,height: 302), screens: screens)
        assert(screens.contains(where: { $0.contains(fitted) }))
        if anchor.midX < 0 { assert(fitted.maxX <= 0) }
    }
    let restored = fitTimerToolFrame(NSRect(x: -900,y: 400,width: 320,height: 210), screens: [screens[0]])
    assert(screens[0].contains(restored))
case "expiry":
    var sounds = 0, reminders = 0
    store.playSound = { sounds += 1 }; store.onReminder = { reminders += 1 }
    snapshot("finished", "00:00", events: ["timer_expired"])
    assert(sounds == 1 && reminders == 1 && notifications.submitted == 1)
    for _ in 0..<3 {
        let recreated = TimerControlPanelView(controls: controls, surface: .detached)
        assert(recreated.readout.stringValue == "00:00")
        controls.refresh()
        snapshot("finished", "00:00")
    }
    assert(sounds == 1 && reminders == 1 && notifications.submitted == 1, "Views must not replay completion effects")
case "routing":
    let host = ApplicationHost()
    var presented = 0, sidebarPresented = 0
    host.availableScreens = { [NSRect(x: 0,y: 0,width: 1440,height: 850)] }
    host.timerTools.present = { _ in presented += 1 }
    host.panelPresenter = { _ in sidebarPresented += 1 }
    host.overlay = OverlayWindow(contentRect: NSRect(x: 30,y: 50,width: 200,height: 130), styleMask: [.borderless], backing: .buffered, defer: false)
    host.scene = TianmuView(frame: NSRect(x: 0,y: 0,width: 200,height: 130))
    host.overlay.contentView = host.scene
    host.panel = NSWindow(contentRect: NSRect(x: 0,y: 0,width: 480,height: 580), styleMask: [.titled], backing: .buffered, defer: false)
    host.panel.isReleasedWhenClosed = false
    host.selectRoute(NSMenuItem(title: "计时", action: nil, keyEquivalent: ""))
    assert(presented == 1 && host.timerTools.quickPresented && !host.panel.isVisible)
    let actualQuick = host.timerTools.quickWindow!.contentView as! TimerControlPanelView
    actualQuick.durationInput.stringValue = "90s"
    actualQuick.customButton.performClick(nil)
    assert(sidebarPresented == 0 && host.timerTools.quickPresented, "Inline custom entry must stay in the small window")
    actualQuick.expandButton.performClick(nil)
    assert(sidebarPresented == 1 && host.presentation.route == "计时" && !host.timerTools.quickPresented)
    host.showTimer()
    actualQuick.detachButton.performClick(nil)
    assert(host.timerTools.detachedPresented && !host.timerTools.quickPresented)
    let actualDetached = host.timerTools.detachedWindow!.contentView as! TimerControlPanelView
    actualDetached.expandButton.performClick(nil)
    assert(sidebarPresented == 2 && host.presentation.route == "计时")
    actualDetached.closeButton.performClick(nil)
    assert(!host.timerTools.detachedPresented)
    host.dismissTransientControls()
    assert(!host.timerTools.quickPresented && host.store.process == nil)
    assert(!host.overlay.isVisible && !host.panel.isVisible)
default: fatalError("Unknown case")
}
print("PASS " + test + ": NO_WORKER_NO_VISIBLE_WINDOWS_NO_REAL_SAVE")
'''


class TimerControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-timer-controls-')
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        source = (ROOT / 'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        (folder / 'main.swift').write_text(source + HARNESS)
        (folder / 'Scene.swift').write_text((ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        cls.binary = folder / 'check'
        sources = ['Presentation.swift', 'WindowPlacement.swift', 'DesktopInsects.swift', 'InsectArtwork.swift', 'TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']
        for file in sources: (folder / file).write_text((ROOT / 'native/v1' / file).read_text())
        result = subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
            str(folder / 'Scene.swift'), *(str(folder / file) for file in sources),
            str(folder / 'main.swift'), '-o', str(cls.binary)], capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ' + name, result.stdout)
        print(result.stdout.strip())

    def test_inline_duration_return_retains_failed_draft_and_replacement_gate(self): self.run_case('daily_flow')
    def test_start_over_uses_original_parameters_and_manual_pomodoro_next(self): self.run_case('restart')
    def test_native_views_and_sidebar_share_commands_and_snapshot(self): self.run_case('shared')
    def test_live_custom_presets_drive_the_existing_quick_buttons(self): self.run_case('presets')
    def test_editing_presets_waits_for_saved_snapshot_and_retains_failed_draft(self): self.run_case('preset_save')
    def test_replacement_confirmation_and_inflight_guard(self): self.run_case('replace')
    def test_resident_timer_collapses_input_and_temporarily_expands_confirmation(self): self.run_case('compact')
    def test_detached_position_persists_only_to_injected_url_and_refits(self): self.run_case('position')
    def test_initial_feedback_or_confirmation_restores_compact_origin_without_drift(self): self.run_case('expanded_position')
    def test_close_reopen_and_dragged_placement_keep_session(self): self.run_case('windows')
    def test_negative_screen_edges_and_removed_monitor_refitting(self): self.run_case('layout')
    def test_reopening_controls_does_not_repeat_expiry_effects(self): self.run_case('expiry')
    def test_actual_menu_routes_to_quick_controls(self): self.run_case('routing')
