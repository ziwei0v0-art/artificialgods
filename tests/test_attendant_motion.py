"""Replay real animation/hit paths offscreen: no worker, window, or game save."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let view = TianmuView(frame:NSRect(origin:.zero,size:TianmuView.sceneCanvas.size))
func point(_ x:CGFloat, _ y:CGFloat) -> NSPoint {
    let canvas = TianmuView.sceneCanvas
    let s = min(view.bounds.width/canvas.width,view.bounds.height/canvas.height)
    return NSPoint(x:(view.bounds.width-canvas.width*s)/2+(x-canvas.minX)*s,
                   y:view.bounds.height-(view.bounds.height-canvas.height*s)/2-(y-canvas.minY)*s)
}
func render(_ target:TianmuView = view) -> NSBitmapImageRep {
    let w = Int(target.bounds.width), h = Int(target.bounds.height)
    let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:w,pixelsHigh:h,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    rep.size = target.bounds.size
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
    target.draw(target.bounds)
    NSGraphicsContext.restoreGraphicsState()
    return rep
}
func pixelBytes(_ rep:NSBitmapImageRep,_ box:NSRect) -> [UInt8] {
    var result:[UInt8] = []
    for y in Int(box.minY)..<Int(box.maxY) { for x in Int(box.minX)..<Int(box.maxX) {
        let p = rep.bitmapData!.advanced(by:y*rep.bytesPerRow+x*4)
        result += [p[0],p[1],p[2],p[3]]
    } }
    return result
}
func allBytes(_ rep:NSBitmapImageRep) -> [UInt8] {
    pixelBytes(rep,NSRect(x:0,y:0,width:rep.pixelsWide,height:rep.pixelsHigh))
}
func save(_ rep:NSBitmapImageRep,_ name:String) {
    let output = URL(fileURLWithPath:CommandLine.arguments[1])
    try! rep.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("138-animation-\(name).png"))
}
func mouse(_ type:NSEvent.EventType,_ p:NSPoint,_ time:Double) -> NSEvent {
    NSEvent.mouseEvent(with:type,location:p,modifierFlags:[],timestamp:time,windowNumber:0,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
'''


class AttendantMotionTests(unittest.TestCase):
    def run_swift(self, harness):
        source = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        with tempfile.TemporaryDirectory(prefix='tianmu-animation-test-') as directory:
            folder = Path(directory)
            (folder / 'main.swift').write_text(source + PRELUDE + harness)
            build = subprocess.run(['swiftc', '-framework', 'AppKit', str(folder/'main.swift'), '-o', str(folder/'check')], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            output = Path(os.environ.get('TIANMU_ANIMATION_EVIDENCE', directory))
            run = subprocess.run([str(folder/'check'), str(output)], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

    def test_idle_blinks_walk_steps_daily_actions_and_static_idol(self):
        self.run_swift(r'''
let first = render(); save(first,"idle")
view.updateAnimation(elapsed:0.75)
let breath = render(); save(breath,"breathe")
assert(allBytes(first) != allBytes(breath), "Idle needs visible breathing")
view.updateAnimation(elapsed:2.25)
let blink = render(); save(blink,"blink")
assert(allBytes(blink) != allBytes(first), "Eyes must blink")
view.updateAnimation(elapsed:4)
let leftA = render(); let frameA = view.attendantBounds; save(leftA,"walk-left-a")
view.updateAnimation(elapsed:4.18)
let leftB = render(); save(leftB,"walk-left-b")
assert(frameA.midX > view.attendantBounds.midX, "Left walk must travel")
// Compare local feet and upper body after compensating root translation. A
// standing sprite shifted across the scene cannot pass this part-motion check.
let delta = Int((frameA.midX-view.attendantBounds.midX).rounded())
let localA = NSRect(x:frameA.midX-25,y:160,width:50,height:25)
let localB = localA.offsetBy(dx:-CGFloat(delta),dy:0)
assert(pixelBytes(leftA,localA) != pixelBytes(leftB,localB), "Walking needs alternating feet, not whole-image translation")
view.updateAnimation(elapsed:7.5)
let leftEnd = view.attendantBounds.midX
view.updateAnimation(elapsed:9)
let sweep = render(); save(sweep,"sweep")
view.updateAnimation(elapsed:13)
let right = render(); save(right,"walk-right")
assert(view.attendantBounds.midX > leftEnd, "Return walk must move right")
view.updateAnimation(elapsed:19)
let rest = render(); save(rest,"rest")
assert(allBytes(rest) != allBytes(first), "Rest must have its own same-character pose")
// The shrine and static idol are invariant until the child crosses their edge;
// this central crop never intersects the moving child or its broom.
let innerShrine = NSRect(x:30,y:18,width:135,height:132)
for frame in [breath,blink,leftA,leftB,sweep,right,rest] {
    assert(pixelBytes(frame,innerShrine) == pixelBytes(first,innerShrine), "Static idol cannot breathe")
}
let frozen = allBytes(rest)
view.updateAnimation(elapsed:.nan); view.updateAnimation(elapsed:-1)
assert(allBytes(render()) == frozen, "Invalid and backwards clocks must be ignored")
let direct = TianmuView(frame:view.frame); direct.updateAnimation(elapsed:19)
assert(allBytes(render(direct)) == frozen, "Pose must depend on elapsed time, not render rate")
print("PASS: idle/breath/blink, two-way travel, independent foot gait, sweeping/rest, static idol, deterministic clock; OFFSCREEN_NO_WORKER")
''')

    def test_crop_connected_ears_and_visible_hit_silhouette_at_scales(self):
        self.run_swift(r'''
assert(TianmuView.sceneCanvas.size == NSSize(width:370,height:190))
let initial = render(); save(initial,"crop")
var minX = 370, minY = 190, maxX = 0, maxY = 0
for y in 0..<190 { for x in 0..<370 {
    if (initial.colorAt(x:x,y:y)?.alphaComponent ?? 0) > 0.1 {
        minX = min(minX,x); minY = min(minY,y); maxX = max(maxX,x); maxY = max(maxY,y)
    }
} }
assert(minX <= 10 && minY <= 10 && 369-maxX <= 20 && 189-maxY <= 10, "Visible subjects should closely fill the compact canvas")
// Full ear-root bands attach to the head, including the old detached gap.
for x in stride(from:CGFloat(323),through:CGFloat(331),by:2) {
    assert(view.subject(at:point(x,190)) == "attendant", "Left ear must connect")
    assert(view.subject(at:point(710-x,190)) == "attendant", "Right ear must connect")
}
for scale:CGFloat in [0.6,1,1.5] {
    view.setFrameSize(NSSize(width:370*scale,height:190*scale))
    view.updateAnimation(elapsed:0.75)
    assert(view.subject(at:point(355,187)) == "attendant")
    assert(view.subject(at:point(325,190)) == "attendant")
    assert(view.subject(at:point(290,170)) == nil)
    let rep = render()
    var matched = 0, opaque = 0
    // Check opaque interior pixels of the moving character against the actual
    // input mask, at default/minimum/maximum size. Edge antialiasing is excluded.
    for y in 0..<rep.pixelsHigh { for x in 0..<rep.pixelsWide {
        let local = NSPoint(x:CGFloat(x)+0.5,y:CGFloat(rep.pixelsHigh-y)-0.5)
        if view.attendantBounds.contains(local), (rep.colorAt(x:x,y:y)?.alphaComponent ?? 0) > 0.99 {
            opaque += 1
            if view.subject(at:local) != nil { matched += 1 }
        }
    } }
    assert(matched > Int(1500*scale*scale) && Double(matched)/Double(opaque) > 0.97, "Opaque character pixels must match the current input silhouette")
}
print("PASS: compact 370x190 crop, connected outward ear roots, same drawn/input shapes at 60/100/150 percent; OFFSCREEN_NO_WORKER")
''')

    def test_moving_hit_mask_accessibility_bow_and_press_lock(self):
        self.run_swift(r'''
let oldTip = point(403,174)
assert(view.subject(at:oldTip) == "attendant")
view.updateAnimation(elapsed:7)
assert(view.subject(at:oldTip) == nil, "The old silhouette must release the desktop")
let moved = render()
for y in 15..<180 { for x in 160..<330 {
    let local = NSPoint(x:CGFloat(x)+0.5,y:190-CGFloat(y)-0.5)
    if view.subject(at:local) == "attendant" {
        assert((moved.colorAt(x:x,y:y)?.alphaComponent ?? 0) > 0, "Moving input mask cannot claim transparent pixels at \(x),\(y)")
    }
} }
let frame = view.attendantBounds
let children = view.accessibilityChildren()!
let child = children[1] as! NSAccessibilityElement
assert(child.accessibilityFrame() == frame, "Accessibility must follow the visible pose")
let start = point(297,187)
assert(view.subject(at:start) == "attendant")
var clicks = 0
view.onSubjectClick = { if $0 == "attendant" { clicks += 1; view.respond() } }
view.mouseDown(with:mouse(.leftMouseDown,start,10))
let held = allBytes(render())
view.updateAnimation(elapsed:15)
assert(allBytes(render()) == held, "A pending press must freeze character geometry")
assert(view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)), "Press ownership must outlive its moving hit region")
view.mouseUp(with:mouse(.leftMouseUp,start,10.1))
assert(clicks == 1 && !view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)))
view.updateAnimation(elapsed:15.55)
let bow = render(); save(bow,"bow")
assert(allBytes(bow) != held, "Click response must articulate a bow")
assert((view.accessibilityChildren()![1] as! NSAccessibilityElement).accessibilityFrame() == view.attendantBounds)
view.updateAnimation(elapsed:16.1)
assert(abs(view.attendantBounds.midX-frame.midX) < 0.1, "Respond must not teleport the routine")
view.mouseDown(with:mouse(.leftMouseDown,start,20))
view.cancelInteraction()
view.mouseUp(with:mouse(.leftMouseUp,start,20.1))
assert(clicks == 1 && !view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)))
print("PASS: moving mask clears old pixels, dynamic accessibility, frozen press/locked pointer, release-only response, bow and cancel; NO_WINDOWS_NO_WORKER")
''')

    def test_legacy_insect_payload_is_not_drawn_in_scene(self):
        self.run_swift(r'''
let clean = allBytes(render())
view.insects = [["id":"visible-bug","x":CGFloat(0.6),"y":CGFloat(0.5),"color":"白色"]]
assert(allBytes(render()) == clean, "Desktop insects must have one dedicated rendering owner")
print("PASS: scene ignores legacy insect drawing payload; OFFSCREEN_NO_WORKER")
''')

    def test_reused_backing_clears_the_previous_attendant_position(self):
        self.run_swift(r'''
let reused = render()
// Old right sleeve/robe interior; far from the shrine and the later left pose.
assert((reused.colorAt(x:315,y:130)?.alphaComponent ?? 0) > 0.95)
view.updateAnimation(elapsed:7)
assert(view.subject(at:point(370,260)) == nil, "Fixture must leave this old pixel fully outside every subject")
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:reused)
view.draw(view.bounds)
NSGraphicsContext.restoreGraphicsState()
assert((reused.colorAt(x:315,y:130)?.alphaComponent ?? 1) == 0, "Reused backing must clear the previous attendant silhouette")
assert(allBytes(reused) == allBytes(render()), "Repainting a reused backing must equal a fresh transparent frame")
print("PASS: same backing reused across moving poses releases old pixels and exactly matches a fresh frame; OFFSCREEN_NO_WORKER")
''')
