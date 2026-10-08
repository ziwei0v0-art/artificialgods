"""Actual native controls: unit intent, honest failed saves, transparent window."""
from test_timer_controls import HARNESS, ROOT
import subprocess
import tempfile
import unittest

EXTRA = r'''
case "traditional":
    var value = store.timer
    value["unit_presets"] = [["label":"一盏茶","input":"一盏茶","seconds":600],
        ["label":"一刻","input":"一刻","seconds":900],
        ["label":"一炷香","input":"一炷香","seconds":1800],
        ["label":"一时辰","input":"一时辰","seconds":7200]]
    value["traditional_readout"] = "五分"
    value["duration_equivalent"] = "半盏茶"
    store.state = ["timer":value]
    let tea = quick.subviews.compactMap { $0 as? NSButton }.first { $0.title == "一盏茶" }
    assert(tea != nil && !tea!.isHidden, "The quick tool must expose traditional units without opening the sidebar")
    tea!.performClick(nil)
    assert(commands.last?.0 == "timer_start" && commands.last?.1["duration"] as? String == "一盏茶")
    assert(quick.detail.stringValue.contains("五分"), "Modern seconds and traditional conversion must come from the same snapshot")
    assert(tea!.toolTip?.contains("10") == true, "A conventional tea unit must reveal its configured modern duration")
    let tool = TimerToolWindows(controls:controls,screens:{[NSRect(x:0,y:0,width:1440,height:900)]},present:{_ in})
    tool.showDetached(near:NSRect(x:40,y:50,width:100,height:100))
    let window = tool.detachedWindow!
    assert(!window.styleMask.contains(.titled) && !window.isOpaque, "Resident timer is a borderless transparent panel")
    assert(window.isMovableByWindowBackground, "Removing the title bar must retain dragging")
    assert(window.frame.width <= 280 && window.frame.height <= 132, "Resting panel is light and compact")
    let panel = window.contentView!
    assert(panel.subviews.contains { $0 is NSVisualEffectView }, "A real backdrop material is required, not an opaque color imitation")
    assert(!window.isVisible && store.process == nil)
case "keyboard":
    let window = TimerToolPanel(contentRect:NSRect(x:100,y:100,width:312,height:260),styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed = false;window.contentView = quick
    quick.durationInput.stringValue = "半炷香"
    assert(window.makeFirstResponder(quick.durationInput))
    guard let editor=window.firstResponder as? NSTextView else { fatalError("Duration input must use the real AppKit field editor") }
    assert(editor.isEditable && editor.isFieldEditor && !window.isVisible)
    editor.setSelectedRange(NSRange(location:(editor.string as NSString).length,length:0))
    func shortcut(_ key:String,_ flags:NSEvent.ModifierFlags = [.command]) -> NSEvent {
        NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:flags,timestamp:1,windowNumber:window.windowNumber,
            context:nil,characters:key,charactersIgnoringModifiers:key,isARepeat:false,keyCode:0)!
    }
    assert(window.performKeyEquivalent(with:shortcut("a")),"An editable field receives Command+A even without a main menu")
    assert(editor.selectedRange() == NSRange(location:0,length:3),"Command+A actually selects the Chinese duration")
    assert(editor.allowsUndo,"The real duration field editor enables native undo without test configuration")
    let undo=editor.undoManager!
    undo.removeAllActions();undo.groupsByEvent = false;undo.beginUndoGrouping()
    editor.insertText("90s",replacementRange:editor.selectedRange())
    undo.endUndoGrouping()
    assert(editor.string == "90s","Typing after Select All replaces, rather than appends to, the old duration")
    assert(undo.canUndo,"The real text edit registers native undo")
    assert(window.performKeyEquivalent(with:shortcut("z")))
    assert(editor.string == "半炷香","Command+Z undoes the edit in the active field")
    assert(window.performKeyEquivalent(with:shortcut("z",[.command,.shift])))
    assert(editor.string == "90s","Command+Shift+Z redoes the same edit")
    editor.setSelectedRange(NSRange(location:1,length:0))
    assert(!window.performKeyEquivalent(with:shortcut("a",[.command,.option])))
    assert(editor.selectedRange() == NSRange(location:1,length:0),"Additional modifiers must not be stolen")
    assert(!window.performKeyEquivalent(with:shortcut("a",[.command,.shift])))
    assert(window.makeFirstResponder(quick.primaryButton))
    assert(!window.performKeyEquivalent(with:shortcut("a")),"Other controls keep their own shortcuts")
    let readonly=NSTextView(frame:.zero);readonly.isEditable = false;readonly.isSelectable = true
    readonly.string = "read only";window.contentView!.addSubview(readonly)
    assert(window.makeFirstResponder(readonly))
    readonly.setSelectedRange(NSRange(location:1,length:0))
    _ = window.performKeyEquivalent(with:shortcut("a"))
    assert(readonly.selectedRange() == NSRange(location:1,length:0),"The timer override only forwards editable text")
    assert(!window.isVisible && commands.isEmpty && store.process == nil)
case "label_drag":
    final class DragRecordingWindow: NSWindow {
        var drags = 0
        override func performDrag(with event:NSEvent) { assert(event.type == .leftMouseDown);drags += 1 }
    }
    let window=DragRecordingWindow(contentRect:quick.bounds,styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed = false;window.isMovable = true;window.contentView = quick
    let down=NSEvent.mouseEvent(with:.leftMouseDown,location:NSPoint(x:100,y:50),modifierFlags:[],timestamp:1,
        windowNumber:window.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
    for label in [quick.readout,quick.detail,quick.heading] {
        assert(!label.isEditable && !label.isSelectable && label.mouseDownCanMoveWindow,
            "Read-only timer labels expose background window dragging")
        let before=window.drags;label.mouseDown(with:down)
        assert(window.drags == before+1,"Dragging a visible label forwards the actual event to its window")
    }
    assert(quick.durationInput.isEditable && quick.durationInput.isSelectable && !quick.durationInput.mouseDownCanMoveWindow,
        "The duration field remains a standard selectable editor")
    assert(!window.isVisible && commands.isEmpty && store.process == nil)

'''


class TraditionalNativeTimerTests(unittest.TestCase):
    def check(self, case):
        # Reuse the production harness, not an alternative test implementation.
        harness = HARNESS.replace('default: fatalError("Unknown case")', EXTRA + '\ndefault: fatalError("Unknown case")')
        with tempfile.TemporaryDirectory(prefix='tianmu-traditional-ui-') as temporary:
            from pathlib import Path
            folder = Path(temporary)
            source = (ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
            (folder/'main.swift').write_text(source+harness)
            (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            names = ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift','TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
            for name in names: (folder/name).write_text((ROOT/'native/v1'/name).read_text())
            build = subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*[str(folder/n) for n in names],str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr)
            run = subprocess.run([str(folder/'check'),case],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout.strip())

    def test_traditional_shortcut_and_shared_snapshot_in_glass_panel(self):
        self.check('traditional')

    def test_borderless_window_routes_native_text_shortcuts(self):
        self.check('keyboard')

    def test_read_only_labels_drag_without_taking_text_selection(self):
        self.check('label_drag')
