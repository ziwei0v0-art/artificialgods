"""Pinned fly-paradise appearance on the passive layer; windows are never shown.

The old cute/realistic preference values remain readable, but both intentionally
display the same upstream renderer after the user's 164 direction change.
These are integration checks against the production pose cache. Source-shape
agreement is separately checked by the independent pinned-JS 171 render review.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_insect_artwork import fixture

from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { print("FAIL: " + message); exit(1) }
}
func render(_ view: NSView) -> NSBitmapImageRep {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil, pixelsWide:Int(view.bounds.width),
        pixelsHigh:Int(view.bounds.height), bitsPerSample:8, samplesPerPixel:4,
        hasAlpha:true, isPlanar:false, colorSpaceName:.deviceRGB, bytesPerRow:0, bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
    view.draw(view.bounds)
    NSGraphicsContext.restoreGraphicsState()
    return bitmap
}
func upstreamReference(_ view: NSView, _ insects: [DesktopInsectPosition],
                       _ screenFrame: NSRect, _ now: TimeInterval) -> NSBitmapImageRep {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil, pixelsWide:Int(view.bounds.width),
        pixelsHigh:Int(view.bounds.height), bitsPerSample:8, samplesPerPixel:4,
        hasAlpha:true, isPlanar:false, colorSpaceName:.deviceRGB, bytesPerRow:0, bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
    NSColor.clear.setFill(); view.bounds.fill(using:.copy)
    for insect in insects {
        // Independently invoke the accepted renderer at the actual logical
        // position, body heading, activity, sex and stable identity phase.
        let activity:FlyParadiseArtwork.Motion = insect.activity == .flying ? .flying
            : insect.activity == .resting ? .resting : .crawling
        FlyParadiseArtwork.shared.drawCached(
            at:NSPoint(x:insect.point.x-screenFrame.minX,y:insect.point.y-screenFrame.minY),
            color:insect.color, sex:insect.sex, heading:insect.heading,
            motion:activity, now:now, seed:insect.artworkSeed,scale:insect.scale,opacity:insect.opacity)
    }
    NSGraphicsContext.restoreGraphicsState()
    return bitmap
}
func visibleCount(_ bitmap: NSBitmapImageRep) -> Int {
    var count = 0
    for y in 0..<bitmap.pixelsHigh { for x in 0..<bitmap.pixelsWide {
        if bitmap.colorAt(x:x,y:y)!.alphaComponent > 0 { count += 1 }
    } }
    return count
}
func bytes(_ bitmap: NSBitmapImageRep) -> Data {
    Data(bytes:bitmap.bitmapData!,count:bitmap.bytesPerRow * bitmap.pixelsHigh)
}
func mouse(_ type:NSEvent.EventType,_ window:NSWindow,_ point:NSPoint,_ time:TimeInterval) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:window.convertPoint(fromScreen:point),modifierFlags:[],timestamp:time,
        windowNumber:window.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
'''


class InsectStyleLayerTests(unittest.TestCase):
    def run_swift(self, body, setup=None):
        with tempfile.TemporaryDirectory(prefix="tianmu-insect-style-") as temporary:
            folder = Path(temporary)
            if setup:
                setup(folder)
            main = folder / "main.swift"
            main.write_text(with_desktop_motion_fixture(PRELUDE + body))
            sources = [ROOT / "native/v1/WindowPlacement.swift", ROOT / "native/v1/DesktopInsects.swift"]
            artwork = ROOT / "native/v1/InsectArtwork.swift"
            if artwork.exists():
                sources.insert(1, artwork)
            binary = folder / "check"
            built = subprocess.run(["swiftc", "-framework", "AppKit", *map(str, sources), str(main),
                                    "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary), str(folder)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS:", result.stdout)
            print(result.stdout.strip())

    def test_missing_legacy_pngs_still_draw_upstream_pose_cache_pixels(self):
        self.run_swift(r'''
let screen = DesktopInsectScreen(id:"fixture", frame:NSRect(x:0,y:0,width:80,height:80))
let layer = DesktopInsects(screens:[screen], renderTime:{ 37 }, windowPresenter:{ _ in
    check(false,"A passive fixture must never ask to show a window")
})
layer.update(rows:[["id":"same-real-id","x":0.5,"y":0.5,"color":"普通褐色","sex":"M"]])
check(layer.availableStyles.isEmpty,"Fixture must genuinely omit the old PNG resources")
check(layer.positions.count == 1 && layer.positions[0].id == "same-real-id" && layer.positions[0].sex == "M",
      "Missing old images must preserve the real ID and sex")
check(layer.windows.allSatisfy { !$0.isVisible && $0.ignoresMouseEvents },"Missing images cannot take input")
let view = layer.windows[0].contentView!, image = render(view)
let expected = upstreamReference(view,layer.positions,screen.frame,37)
check(visibleCount(expected)>0 && bytes(image) == bytes(expected),
      "Missing obsolete PNGs must still draw the accepted fly-paradise pose cache, not a placeholder")
layer.close()
print("PASS: missing legacy PNGs retain upstream pose-cache pixels and actual ID/sex; no shown windows/worker/save")
''')

    def test_legacy_style_values_keep_identical_cached_pixels_without_refreshing(self):
        self.run_swift(r'''
let artwork=InsectArtwork(directory:URL(fileURLWithPath:CommandLine.arguments[1]).appendingPathComponent("assets"))
var now:TimeInterval=37.19, reads=0, presentations=0
let screen=DesktopInsectScreen(id:"negative",frame:NSRect(x:-320,y:-40,width:320,height:240))
let layer=DesktopInsects(screens:[screen],renderTime:{reads += 1; return now},windowPresenter:{_ in presentations += 1},artwork:artwork)
layer.update(rows:[["id":"visible","x":0.5,"y":0.5,"color":"普通褐色","sex":"F"]])
check(layer.availableStyles == Set([.cute,.realistic]) && layer.style == .cute,"Layer must expose actual loaded choices")
let window=layer.windows[0], view=window.contentView!, position=layer.positions[0].point
let cute=render(view), before=bytes(cute), clockReads=reads
let reference=upstreamReference(view,layer.positions,screen.frame,now)
check(visibleCount(reference)>0 && before == bytes(reference),
      "The old cute preference must draw accepted upstream pose-cache pixels")
now += 100
check(layer.setStyle(.realistic),"Available realistic style must be accepted")
let realistic=render(view)
check(bytes(realistic) == bytes(reference),
      "Both old preference values intentionally keep the same exact upstream renderer")
check(layer.positions[0].point == position && reads == clockReads,"Style selection/draw cannot take a fresh clock sample or move insects")
check(layer.setStyle(.cute),"Can return to cute")
check(bytes(render(view)) == before,"Returning to cute at the same displayed time must restore byte-identical pixels")
check(layer.setStyle(.cute) && bytes(render(view)) == before,"Duplicate style updates cannot restart phases")
check(layer.windows[0] === window && window.contentView === view,"Style changes must preserve actual window/view objects")
check(presentations == 0 && !window.isVisible && window.ignoresMouseEvents,"Pure style changes never present or capture input")
let second:[String:Any] = ["id":"other","x":0.2,"y":0.3,"color":"白色"]
now=37.19
let first:[String:Any] = ["id":"visible","x":0.5,"y":0.5,"color":"普通褐色"]
layer.update(rows:[first,second])
let originalPoints=Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.point)})
let originalScreens=Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.screenID)})
let ordered=bytes(render(view))
layer.update(rows:[second,first])
check(Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.point)}) == originalPoints,"Reordering cannot teleport insects")
check(Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.screenID)}) == originalScreens,"Reordering cannot reassign screens")
check(bytes(render(view)) == ordered,"Reordered same-time rows must retain the same actual ID animation phases")
layer.close()
print("PASS: legacy preferences retain identical upstream pixels and stable ID/time; no refresh/input/window changes")
''', setup=lambda folder: fixture(folder / "assets"))

    def test_switch_during_drag_or_overdue_weave_keeps_the_same_capture_id_set(self):
        self.run_swift(r'''
let artwork=InsectArtwork(directory:URL(fileURLWithPath:CommandLine.arguments[1]).appendingPathComponent("assets"))
let screens=[DesktopInsectScreen(id:"left",frame:NSRect(x:-320,y:-40,width:320,height:240)),
             DesktopInsectScreen(id:"right",frame:NSRect(x:0,y:0,width:320,height:240))]
var now:TimeInterval=10, clockReads=0, presentations=0
let baseline=DesktopInsects(screens:screens,renderTime:{clockReads += 1;return now},windowPresenter:{_ in presentations += 1},artwork:artwork)
let changed=DesktopInsects(screens:screens,renderTime:{clockReads += 1;return now},windowPresenter:{_ in presentations += 1},artwork:artwork)
let rows:[[String:Any]]=(0..<12).map { index -> [String:Any] in
    let x=Double(index % 4)/3.0, y=Double(index % 3)/2.0
    return ["id":"fly-\(index)","x":x,"y":y,"color":"普通褐色"]
}
var caughtA:[[String]]=[],caughtB:[[String]]=[]
baseline.onCapture={caughtA.append($0)}; changed.onCapture={caughtB.append($0)}
baseline.update(rows:rows);changed.update(rows:rows)
let start=NSPoint(x:-320,y:-40),end=NSPoint(x:320,y:240)
for layer in [baseline,changed] {
    layer.beginCapture();let window=layer.windows[0]
    window.contentView!.mouseDown(with:mouse(.leftMouseDown,window,start,now))
    window.contentView!.mouseDragged(with:mouse(.leftMouseDragged,window,end,now))
}
let oldWindows=changed.windows, readsBefore=clockReads
check(changed.setStyle(.realistic),"Can switch during the existing gesture")
check(changed.isCapturing && changed.windows.allSatisfy{$0.ignoresMouseEvents},"Style changes preserve the selection without enabling a full-screen mouse shield")
check(zip(oldWindows,changed.windows).allSatisfy{$0 === $1} && clockReads == readsBefore,"Style cannot rebuild screens or advance time")
for layer in [baseline,changed] {
    let window=layer.windows[0]
    window.contentView!.mouseUp(with:mouse(.leftMouseUp,window,end,now))
}
check(baseline.isWeaving && changed.isWeaving && caughtA.isEmpty && caughtB.isEmpty,"Release starts existing weaving only")
let current=Array(rows.dropFirst()) + [["id":"newcomer","x":0.5,"y":0.5,"color":"白色"]]
baseline.update(rows:current);changed.update(rows:current)
now += 6
let dueReads=clockReads
check(changed.setStyle(.cute) && changed.setStyle(.realistic),"Style remains selectable during weaving")
check(caughtA.isEmpty && caughtB.isEmpty && clockReads == dueReads,"An overdue weave must not complete just because a style was selected")
baseline.refresh();changed.refresh()
let expected=Set(current.map{$0["id"] as! String})
check(caughtA.count == 1 && caughtB.count == 1 && Set(caughtA[0]) == expected && Set(caughtB[0]) == expected,"Style switching must preserve the current cross-screen capture ID set")
check(caughtB[0].count == expected.count && !caughtB[0].contains("fly-0"),"No duplicate IDs or automatically removed old individual")
now += 1;baseline.refresh();changed.refresh();changed.refresh()
check(caughtA.count == 1 && caughtB.count == 1 && !changed.isWeaving,"Normal completion remains exactly once")
check(presentations == 0 && changed.windows.allSatisfy{!$0.isVisible && $0.ignoresMouseEvents},"The comparison never displays or retains input")
baseline.close();changed.close()
print("PASS: same real IDs captured after style changes through drag/overdue weaving; no premature callbacks")
''', setup=lambda folder: fixture(folder / "assets"))

    def test_style_changes_do_not_add_input_or_restart_the_existing_natural_handle_gesture(self):
        self.run_swift(r'''
let artwork=InsectArtwork(directory:URL(fileURLWithPath:CommandLine.arguments[1]).appendingPathComponent("assets"))
let screen=DesktopInsectScreen(id:"main",frame:NSRect(x:0,y:0,width:320,height:240))
var now:TimeInterval=37,presentations=0,focus=0
let layer=DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{_ in presentations += 1},artwork:artwork)
layer.setNaturalCaptureEnabled(false) // Exercise the retained explicit handle.
layer.onNaturalCaptureBegin={focus += 1}
layer.update(rows:[["id":"fly","x":0.5,"y":0.5,"color":"普通褐色"]]);layer.show()
func switchPreserving() {
    let windows=layer.windows, handle=layer.captureHandleWindow
    let frames=windows.map{$0.frame}, levels=windows.map{$0.level}, inputs=windows.map{$0.ignoresMouseEvents}
    let handleFrame=handle?.frame, handleInput=handle?.ignoresMouseEvents, handleLevel=handle?.level
    let capturing=layer.isCapturing,weaving=layer.isWeaving,visible=layer.isNaturalHandleVisible
    let shownCount=presentations,focusCount=focus,allWindowCount=app.windows.count
    let target:InsectStyle=layer.style == .cute ? .realistic:.cute
    check(layer.setStyle(target),"Both styles exist")
    check(zip(windows,layer.windows).allSatisfy{$0 === $1},"Existing insect windows cannot be replaced")
    check(layer.captureHandleWindow === handle,"Existing handle must retain the current press owner")
    check(layer.windows.map{$0.frame} == frames && layer.windows.map{$0.level} == levels && layer.windows.map{$0.ignoresMouseEvents} == inputs,"Style cannot modify fullscreen input or level")
    check(handle?.frame == handleFrame && handle?.ignoresMouseEvents == handleInput && handle?.level == handleLevel,"Style cannot move or activate the handle")
    check(layer.isCapturing == capturing && layer.isWeaving == weaving && layer.isNaturalHandleVisible == visible,"Style cannot restart or cancel the gesture")
    check(presentations == shownCount && focus == focusCount && app.windows.count == allWindowCount,"Style cannot request new presentation/focus/windows")
}
switchPreserving() // Passive.
layer.updatePointer(layer.positions[0].point,buttonsPressed:0)
check(layer.isNaturalHandleVisible,"Existing hover creates the existing handle")
switchPreserving() // Hover.
let handle=layer.captureHandleWindow!, origin=NSPoint(x:handle.frame.midX,y:handle.frame.midY)
handle.contentView!.mouseDown(with:mouse(.leftMouseDown,handle,origin,now))
switchPreserving() // Press below the drag threshold.
check(focus == 0,"A style change after pressing cannot trigger capture focus")
let end=NSPoint(x:origin.x+80,y:origin.y-80)
handle.contentView!.mouseDragged(with:mouse(.leftMouseDragged,handle,end,now))
check(layer.isCapturing && focus == 1,"The same press must continue into natural capture")
switchPreserving() // Active drag.
handle.contentView!.mouseUp(with:mouse(.leftMouseUp,handle,end,now))
check(layer.isWeaving && !layer.isCapturing,"Same release starts weaving and releases input")
switchPreserving() // Weaving.
check(layer.windows.allSatisfy{!$0.isVisible && $0.ignoresMouseEvents},"All real test windows remain hidden and passive")
layer.cancelCapture();layer.close()
print("PASS: style switching preserves passive/hover/press/drag/weave windows and input ownership")
''', setup=lambda folder: fixture(folder / "assets"))

    def test_unavailable_style_rejects_switch_and_constructor_fallback_is_explicit(self):
        def setup(folder):
            fixture(folder / "cute-only", lambda m, p: m["styles"].pop("realistic"))
            fixture(folder / "realistic-only", lambda m, p: m["styles"].pop("cute"))
            fixture(folder / "none", lambda m, p: m.update(styles={}))
        self.run_swift(r'''
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let cute=DesktopInsects(screens:[],artwork:InsectArtwork(directory:root.appendingPathComponent("cute-only")),style:.realistic)
check(cute.style == .cute && cute.availableStyles == Set([.cute]),"Missing preference may use the actual available cute style")
check(!cute.setStyle(.realistic) && cute.style == .cute,"A missing requested style cannot be reported as selected")
let realistic=DesktopInsects(screens:[],artwork:InsectArtwork(directory:root.appendingPathComponent("realistic-only")))
check(realistic.style == .realistic && realistic.availableStyles == Set([.realistic]),"Default missing cute uses genuine realistic when available")
check(!realistic.setStyle(.cute) && realistic.style == .realistic,"Reject missing cute without overwriting the active genuine style")
let missing=DesktopInsects(screens:[],artwork:InsectArtwork(directory:root.appendingPathComponent("none")))
check(missing.style == .cute && missing.availableStyles.isEmpty,"An empty cache remains explicitly unavailable")
check(!missing.setStyle(.cute) && !missing.setStyle(.realistic),"No geometric or other-style fallback may report success")
cute.close();realistic.close();missing.close()
print("PASS: constructor chooses available style; missing style never pretends success; no saved preference writes")
''', setup=setup)


if __name__ == "__main__":
    unittest.main()
