"""Display-only flight/rest/crawl contracts; no visible windows, worker or saves."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
from tests.desktop_motion_fixture import with_desktop_motion_fixture


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let screen = DesktopInsectScreen(id:"left",frame:NSRect(x:-1200,y:-100,width:1200,height:800))
var now:TimeInterval = 37
let layer = DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{ _ in })
func require(_ value:@autoclosure ()->Bool,_ message:String) {
    if !value() { print("FAIL: \(message)"); exit(1) }
}
func row(_ id:String = "one",_ x:Double = 0.5,_ y:Double = 0.5) -> [String:Any] {
    ["id":id,"x":x,"y":y,"color":"普通褐色"]
}
func point(_ id:String = "one",in subject:DesktopInsects = layer) -> NSPoint {
    subject.positions.first{$0.id == id}!.point
}
func distance(_ a:NSPoint,_ b:NSPoint) -> Double { hypot(a.x-b.x,a.y-b.y) }
func step(_ count:Int = 1) { for _ in 0..<count { now += 1.0/30; layer.refresh() } }
layer.update(rows:[row()])

switch CommandLine.arguments[1] {
case "trips_and_stays":
    let initial = point()
    var last = initial, farthest = 0.0, stillFrames = 0, longestStay = 0
    for _ in 0..<900 {
        step(); let current = point()
        farthest = max(farthest,distance(initial,current))
        if current == last { stillFrames += 1; longestStay = max(longestStay,stillFrames) }
        else { stillFrames = 0 }
        require(screen.frame.contains(current),"Original wrapping must keep each position on the actual screen")
        require(hypot(layer.positions[0].velocity.x,layer.positions[0].velocity.y) <= 570.001,"Unthreatened original flight must stay within its cruise and burst band")
        last = current
    }
    require(farthest > 35,"Flight must cross several body lengths, not orbit inside a 10-point patch")
    require(longestStay >= 8,"A fly must genuinely stop for at least the original 0.3-second minimum")
    require(longestStay <= 181,"A normal stay must end within the original 6-second still interval")
case "snapshot_continuity":
    step(12)
    let existing = point()
    var changed = row("one",1,0); changed["color"] = "白色"
    layer.update(rows:[changed])
    require(point() == existing,"Existing ID must keep local position even if a later backend snapshot carries other coordinates")
    require(layer.positions[0].color == "白色","Display color still reflects authoritative snapshot")
    layer.update(rows:[row("new",0,1),changed])
    require(point() == existing,"A new ID must not reset another fly's movement")
    require(point("new") == NSPoint(x:-1188,y:-88),"Only new IDs initialize from normalized backend coordinates")
    let both = Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.point)})
    layer.update(rows:[changed,row("new",1,0)])
    require(Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.point)}) == both,"Reordering and duplicate snapshots must not teleport insects")
case "clock_gap":
    step(3); let previous = point()
    now += 90; layer.refresh()
    require(point() == previous,"A long paused interval resets the time anchor rather than teleporting or chasing elapsed time")
    now -= 100; layer.refresh()
    require(point() == previous,"A backward clock must not rewind the rendered flight")
    now += 0.1; layer.refresh()
    require(distance(previous,point()) <= 28.501,"One delayed update must be capped at .05 seconds")
    let after = point()
    now = Double.nan; layer.refresh()
    require(point() == after,"Invalid time must not move a fly to a synthetic epoch")
    now = 500; layer.refresh()
    require(point() == after,"Recovering a valid time must establish an anchor without catching up")
case "independent_ids":
    let peer = DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{ _ in })
    peer.update(rows:[row()])
    layer.update(rows:[row("other",0.8,0.8),row()])
    for index in 0..<600 {
        now += 1.0/30; layer.refresh(); peer.refresh()
        if index % 30 == 0 { layer.update(rows:[row(),row("other",0.2,0.2)]) }
        require(point() == point(in:peer),"An ID's deterministic motion must not depend on neighbours or snapshot ordering")
    }
    let old = point()
    layer.update(rows:[]); layer.update(rows:[row("one",0,1)])
    require(point() != old && point() == NSPoint(x:-1188,y:-88),"Removing an ID discards its display state before later reintroduction")
    peer.close()
case "activity_and_direction":
    layer.update(rows:[])
    layer.updateBehaviorLandingSurfaces([
        DesktopInsectLandingSurface(id:"fruit",frame:NSRect(x:-616,y:284,width:32,height:32)),
        DesktopInsectLandingSurface(id:"shrine",frame:NSRect(x:-150,y:600,width:32,height:32)),
        DesktopInsectLandingSurface(id:"edge",frame:NSRect(x:-1190,y:-90,width:32,height:32))])
    var adult = row("real-adult-1"); adult["sex"] = "F"
    layer.update(rows:[adult])
    var sawCrawl = false, sawRest = false, sawFlight = false
    var previous = layer.positions[0]
    for _ in 0..<3600 {
        step(); let current = layer.positions[0]
        let turn = atan2(sin(current.heading-previous.heading),cos(current.heading-previous.heading))
        require(abs(turn) <= Double.pi/3+0.001,"Original displayed heading must take the shortest arc with dt*10 smoothing")
        require(current.facingLeft == (cos(current.heading) < 0),"Facing must follow the original displayed heading")
        if current.activity == previous.activity {
            switch current.activity {
            case .resting:
                sawRest = true
                require(current.point == previous.point && current.animationTime == previous.animationTime,"Resting must freeze position and flight wing phase")
            case .crawling:
                sawCrawl = true
                require(current.animationTime == previous.animationTime,"Original perch hops must keep flight wings folded")
            case .flying:
                sawFlight = true
                require(current.animationTime > previous.animationTime,"Flying must advance wing animation")
            }
        }
        previous = current
    }
    require(sawCrawl && sawRest && sawFlight,"Original state machine must include flight, perching and short perch hops")
case "pointer_and_pressed_suppression":
    layer.updateBehaviorLandingSurfaces([])
    let peer = DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{_ in})
    peer.updateBehaviorLandingSurfaces([]); peer.update(rows:[row()])
    let input = NSPoint(x:point().x-20,y:point().y)
    now += 1.0/30
    layer.updateBehaviorPointer(input,buttonsPressed:1)
    layer.refresh(); peer.refresh()
    require(point() == point(in:peer),"A pressed-button sample must not trigger a new ambient fright")
    now += 1.0/30
    layer.updateBehaviorPointer(NSPoint(x:point().x-20,y:point().y),buttonsPressed:0)
    layer.refresh(); peer.refresh()
    require(hypot(layer.positions[0].velocity.x,layer.positions[0].velocity.y)>1000,"Nearby free pointer must invoke original boosted flee speed")
    require(layer.positions[0].velocity.x>0,"Original flee must move away from the nearby pointer")
    require(point() != point(in:peer),"Ambient pointer must affect the actual rendered insect")
    layer.updateBehaviorPointer(.zero,buttonsPressed:0,enabled:false)
    peer.close()
case "disconnected_screen_gap":
    let right = DesktopInsectScreen(id:"right",frame:NSRect(x:500,y:-700,width:800,height:600))
    layer.updateScreens([screen,right])
    layer.update(rows:(0..<12).map{row("gap-\($0)")})
    for _ in 0..<1800 {
        step()
        require(layer.positions.count == 12,"Topology gaps must not hide authoritative IDs")
        for insect in layer.positions {
            let actual = [screen,right].first{$0.id == insect.screenID}!
            require(actual.frame.contains(insect.point),"No insect may occupy the empty bounding rectangle between monitors")
        }
    }
case "missing_module":
    let missing = DesktopInsects(motionModuleURL:URL(fileURLWithPath:"/nonexistent-tianmu-motion.js"),screens:[screen],windowPresenter:{_ in})
    missing.update(rows:[row()])
    require(missing.motionUnavailableReason != nil && missing.positions.isEmpty,"A missing module must fail explicitly without a hidden fallback movement engine")
    missing.close()
case "screen_and_style":
    let art = InsectArtwork(directory:URL(fileURLWithPath:CommandLine.arguments[2]))
    require(art.availableStyles == Set([.cute,.realistic]),"Fixture needs both accepted display styles")
    let subject = DesktopInsects(screens:[screen],renderTime:{now},windowPresenter:{ _ in },artwork:art)
    subject.update(rows:[row("one",0.9,0.1)])
    for _ in 0..<30 { now += 1.0/30; subject.refresh() }
    let before = subject.positions[0]
    require(subject.setStyle(.realistic),"Second style must be available")
    let after = subject.positions[0]
    require(before.point == after.point && before.activity == after.activity && before.animationTime == after.animationTime && before.heading == after.heading,"Changing artwork must not reset movement or animation phase")
    let other = DesktopInsectScreen(id:"right",frame:NSRect(x:80,y:-800,width:600,height:450))
    subject.updateScreens([other])
    for _ in 0..<180 {
        now += 1.0/30; subject.refresh()
        require(subject.positions[0].screenID == "right" && other.frame.contains(subject.positions[0].point),"Removed monitors must safely rehome motion into a real screen")
    }
    let beforeDisconnect = subject.positions[0].point
    subject.updateScreens([]); require(subject.positions.isEmpty,"No screen means no off-screen rendered insects")
    for _ in 0..<120 { now += 1.0/30; subject.refresh() }
    subject.updateScreens([other])
    require(subject.positions[0].point == beforeDisconnect,"Temporarily missing screens must preserve each existing ID and its position")
    subject.updateScreens([screen])
    require(screen.frame.contains(subject.positions[0].point),"Restored screen must clamp retained state")
    require(subject.windows.allSatisfy{!$0.isVisible},"Screen rebuild must remain unshown in tests")
    subject.close()
case "rendered_rest":
    let art = InsectArtwork(directory:URL(fileURLWithPath:CommandLine.arguments[2]))
    let small = DesktopInsectScreen(id:"render",frame:NSRect(x:-320,y:-50,width:320,height:240))
    let subject = DesktopInsects(screens:[small],renderTime:{now},windowPresenter:{ _ in },artwork:art)
    subject.update(rows:[row()])
    var found = false
    for _ in 0..<90 {
        now += 1.0/30; subject.refresh()
        if subject.positions[0].activity == .resting { found = true; break }
    }
    require(found,"Fixture must reach a real rest")
    func bitmap() -> NSBitmapImageRep {
        let view = subject.windows[0].contentView!
        let image = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:320,pixelsHigh:240,bitsPerSample:8,
            samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:image)
        view.draw(view.bounds); NSGraphicsContext.restoreGraphicsState()
        return image
    }
    let resting = subject.positions[0]
    let anchor = NSPoint(x:resting.point.x-small.frame.minX,y:240-(resting.point.y-small.frame.minY))
    let forward = NSPoint(x:cos(resting.heading),y:-sin(resting.heading))
    let first = bitmap()
    var visible = 0, changingHeadPixels = 0
    for _ in 0..<15 {
        now += 1.0/30; subject.refresh()
        require(subject.positions[0].activity == .resting && subject.positions[0].point == resting.point
            && subject.positions[0].heading == resting.heading,"Rest keeps position and heading fixed while original front legs may groom")
        let current = bitmap()
        for y in 0..<240 { for x in 0..<320 {
            let pixel = current.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
            let before = first.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
            let dx = Double(x)+0.5-anchor.x, dy = Double(y)+0.5-anchor.y
            let along = dx*forward.x+dy*forward.y, across = -dx*forward.y+dy*forward.x
            if pixel.alphaComponent > 0.05 {
                visible += 1
                require(abs(across) < 4.75,"Resting fly must use folded wings, without extended flight-wing pixels")
            }
            if pixel != before {
                require(along > -0.75 && along < 5 && abs(across)<3.5,"Resting changes must stay at the original grooming forelegs, without moving body or flapping wings")
                changingHeadPixels += 1
            }
        } }
    }
    require(visible>0,"Rest rendering must contain the actual fly")
    require(changingHeadPixels>0,"Original resting front-leg grooming must remain animated")
    subject.close()
case "rendered_facing":
    let art = InsectArtwork(directory:URL(fileURLWithPath:CommandLine.arguments[2]))
    let small = DesktopInsectScreen(id:"render",frame:NSRect(x:-320,y:-50,width:320,height:240))
    let subject = DesktopInsects(screens:[small],renderTime:{now},windowPresenter:{ _ in },artwork:art)
    subject.update(rows:[row()])
    func bitmap() -> NSBitmapImageRep {
        let view = subject.windows[0].contentView!
        let image = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:320,pixelsHigh:240,bitsPerSample:8,
            samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:image)
        view.draw(view.bounds); NSGraphicsContext.restoreGraphicsState()
        return image
    }
    for target in [0.0,Double.pi/2,Double.pi,-Double.pi/2] {
        var found = false
        for _ in 0..<3600 {
            now += 1.0/30; subject.refresh()
            let insect = subject.positions[0]
            let difference = atan2(sin(insect.heading-target),cos(insect.heading-target))
            if insect.activity == .flying && abs(difference)<0.25 { found = true; break }
        }
        require(found,"Fixture needs each quadrant of actual full-heading flight")
        let image = bitmap(), insect = subject.positions[0]
        var sumX = 0.0, sumY = 0.0, count = 0.0
        for y in 0..<240 { for x in 0..<320 {
            let color = image.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
            if color.alphaComponent > 0.35 && color.redComponent > 0.35
                && color.redComponent > color.greenComponent*1.8 && color.redComponent > color.blueComponent*1.4 {
                sumX += Double(x)+0.5; sumY += Double(y)+0.5; count += 1
            }
        } }
        require(count>0,"Original rendered red eye pixels must remain readable")
        let dx = sumX/count-(insect.point.x-small.frame.minX)
        let dy = sumY/count-(240-(insect.point.y-small.frame.minY))
        let along = dx*cos(insect.heading)-dy*sin(insect.heading)
        let across = dx*sin(insect.heading)+dy*cos(insect.heading)
        require(along>1 && abs(across)<1.5,"Original head must face actual full heading, including north/south rather than side mirroring")
        let original = Data(bytes:image.bitmapData!,count:image.bytesPerRow*image.pixelsHigh)
        for style:InsectStyle in [.cute,.realistic] {
            require(subject.setStyle(style),"Legacy style value remains readable for existing preferences")
            let other = bitmap()
            require(Data(bytes:other.bitmapData!,count:other.bytesPerRow*other.pixelsHigh)==original,
                "Both legacy preferences must render the same requested upstream artwork at the same state")
        }
    }
    require(subject.windows.allSatisfy{!$0.isVisible},"Facing test must stay off screen")
    subject.close()
default: fatalError("Unknown scenario")
}
require(layer.windows.allSatisfy{!$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow},"All test windows must remain unshown")
layer.close()
print("PASS: \(CommandLine.arguments[1]); deterministic display-only movement, no worker/save/visible window")
'''


@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swiftc"), "macOS + Swift required")
class InsectMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tianmu-insect-motion-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.binary = folder / "check"
        source = folder / "main.swift"
        source.write_text(with_desktop_motion_fixture(HARNESS))
        cls.build = subprocess.run(["swiftc", "-framework", "AppKit", *(str(ROOT / "native/v1" / name) for name in ["WindowPlacement.swift", "InsectArtwork.swift", "DesktopInsects.swift"]), str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)

    def scenario(self,name):
        self.assertEqual(self.build.returncode,0,self.build.stderr)
        result = subprocess.run([str(self.binary),name,str(ROOT / "assets/production/insects")],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn(f"PASS: {name};",result.stdout)
        print(result.stdout.strip())

    def test_original_flight_crosses_body_lengths_and_includes_finite_perches(self):
        self.scenario("trips_and_stays")

    def test_repeated_snapshots_update_color_without_reinitializing_motion(self):
        self.scenario("snapshot_continuity")

    def test_long_pause_backward_or_invalid_time_cannot_teleport_insects(self):
        self.scenario("clock_gap")

    def test_each_id_has_independent_motion_and_removed_ids_are_forgotten(self):
        self.scenario("independent_ids")

    def test_original_heading_and_wing_phase_follow_actual_activity(self):
        self.scenario("activity_and_direction")

    def test_free_pointer_scares_but_pressed_pointer_does_not(self):
        self.scenario("pointer_and_pressed_suppression")

    def test_disconnected_monitor_gaps_never_hide_authoritative_ids(self):
        self.scenario("disconnected_screen_gap")

    def test_missing_module_is_explicit_and_has_no_fallback(self):
        self.scenario("missing_module")

    def test_style_changes_preserve_motion_and_removed_screens_safely_clamp_it(self):
        self.scenario("screen_and_style")

    def test_real_rest_folds_wings_and_only_front_legs_keep_grooming(self):
        self.scenario("rendered_rest")

    def test_original_eye_pixels_follow_full_heading_and_legacy_styles_agree(self):
        self.scenario("rendered_facing")


if __name__ == "__main__":
    unittest.main()
