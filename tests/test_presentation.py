import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class PresentationTests(unittest.TestCase):
    def test_sidebar_replaces_content_dismisses_and_clamps_to_screen(self):
        source = ROOT / 'native/v1/Presentation.swift'
        self.assertTrue(source.exists(), 'Missing shared presentation controller')
        harness = '''
import AppKit
let state = PresentationState()
assert(state.route == nil)
state.open("虫瓶")
assert(state.route == "虫瓶")
state.open("计时")
assert(state.route == "计时")
state.dismiss()
assert(state.route == nil)
state.open("unknown")
assert(state.route == nil)
let screen = NSRect(x: -1280, y: 30, width: 1280, height: 720)
for origin in [NSPoint(x: -1280, y: 30), NSPoint(x: -200, y: 600)] {
 let frame = sidebarFrame(near: NSRect(origin: origin, size: NSSize(width: 420, height: 300)), screen: screen)
 assert(screen.contains(frame))
}
assert(PresentationState.ritualDuration == 5)
state.beginRitual(now: 100)
assert(state.ritualStage(now: 100.2) == "迎候")
assert(state.ritualStage(now: 100.9) == "上香")
assert(state.ritualStage(now: 101.8) == "入炉")
assert(state.ritualStage(now: 102.6) == "摇签")
assert(state.ritualStage(now: 103.5) == "呈签")
assert(state.ritualStage(now: 104.6) == "余烟")
assert(state.ritualStage(now: 105) == nil)
assert(state.ritualElapsed(now: 99) == 0)
state.dismiss()
assert(state.ritualStage(now: 100.9) == "上香", "Closing panel need not stop desktop ceremony")
state.open("求签")
assert(state.ritualStage(now: 100.9) == nil, "Returning shows the already saved sign directly")
state.beginRitual(now: 100); state.skipRitual()
assert(state.ritualStage(now: 100.9) == nil)
state.open("神前"); assert(state.route == "求签")
state.open("虫谱"); assert(state.route == "装扮")
assert(!menuRoutes.contains("拉网"))
let compact = sidebarFrame(near: .zero, screen: NSRect(x:0,y:0,width:1440,height:900), route:"求签")
assert(compact.size == NSSize(width:360,height:440))
print("presentation ok")
'''
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.swift'; main.write_text(harness)
            binary = Path(directory) / 'check'
            build = subprocess.run(['swiftc', str(source), str(main), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('presentation ok', run.stdout)

    def test_scene_clicks_route_only_visible_subjects(self):
        source = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        harness = '''
let app = NSApplication.shared
let view = TianmuView(frame: NSRect(x: 0, y: 0, width: 370, height: 190))
assert(view.subject(at: NSPoint(x: 105, y: 90)) == "shrine")
assert(view.subject(at: NSPoint(x: 300, y: 135)) == "attendant")
assert(view.subject(at: NSPoint(x: 215, y: 100)) == nil)
assert(view.subject(at: NSPoint(x: 10, y: 10)) == nil)
var clicked = ""
view.onSubjectClick = { clicked = $0 }
let event = NSEvent.mouseEvent(with: .leftMouseDown, location: NSPoint(x:105,y:90), modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil, eventNumber: 1, clickCount: 1, pressure: 1)!
view.mouseDown(with: event)
assert(clicked.isEmpty, "A press must not open before click/drag is resolved")
let release = NSEvent.mouseEvent(with: .leftMouseUp, location: NSPoint(x:105,y:90), modifierFlags: [], timestamp: 0.1, windowNumber: 0, context: nil, eventNumber: 2, clickCount: 1, pressure: 0)!
view.mouseUp(with: release)
assert(clicked == "shrine")
print("hit ok")
'''
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.swift'; main.write_text(source + harness)
            binary = Path(directory) / 'check'
            build = subprocess.run(['swiftc', str(main), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_placement_roundtrip_and_removed_monitor_recovery(self):
        source = ROOT / 'native/v1/WindowPlacement.swift'
        self.assertTrue(source.exists(), 'Window placement is not restored by the new host')
        harness = '''
import AppKit
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let preferences = WindowPlacementStore(url: url)
let primary = NSRect(x: 0,y: 40,width:1440,height:860)
let secondary = NSRect(x:-1280,y:0,width:1280,height:800)
let desired = NSRect(x:-900,y:200,width:370,height:190)
try preferences.save(desired)
let reopened = WindowPlacementStore(url: url)
assert(reopened.restore(screens:[primary,secondary]) == desired)
let recovered = reopened.restore(screens:[primary])
assert(primary.contains(recovered))
assert(recovered.size == desired.size)
let huge = NSRect(x:0,y:0,width:6000,height:4000)
assert(primary.contains(fitOverlayFrame(huge, screens:[primary])))
let broken = NSRect(x:CGFloat.nan,y:CGFloat.infinity,width:-1,height:0)
assert(primary.contains(fitOverlayFrame(broken,screens:[primary])))
try "broken".write(to:url,atomically:true,encoding:.utf8)
assert(primary.contains(reopened.restore(screens:[primary])))
print("placement ok")
'''
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.swift'; main.write_text(harness)
            binary = Path(directory) / 'check'
            build = subprocess.run(['swiftc', str(source), str(main), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(Path(directory) / 'placement.json')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('placement ok', run.stdout)

    def test_scene_exposes_accessible_subject_actions(self):
        source = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        harness = '''
let app = NSApplication.shared
let view = TianmuView(frame:NSRect(x:0,y:0,width:370,height:190))
var received = ""
view.onSubjectClick = { received = $0 }
let children = view.accessibilityChildren() ?? []
assert(children.count >= 2, "Scene subjects are missing from accessibility")
let shrine = children[0] as! NSAccessibilityElement
assert(shrine.accessibilityLabel() == "神龛")
assert(shrine.isAccessibilityEnabled(), "Shrine action is disabled")
assert(shrine.accessibilityPerformPress())
assert(received == "shrine")
'''
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.swift'; main.write_text(source + harness)
            binary = Path(directory) / 'check'
            build = subprocess.run(['swiftc', str(main), '-o', str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run = subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
