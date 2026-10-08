"""Backend routine-to-native bridge, only offscreen views and temporary art."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.test_attendant_art import png

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let view = TianmuView(frame:NSRect(origin:.zero,size:TianmuView.sceneCanvas.size))
view.attendantArtwork = AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[1]))
func snapshot(_ action:String,_ serial:Int,_ elapsed:Double = 0,_ duration:Double = 5,_ fruit:String = "fresh") -> [String:Any] {
 ["action":action,"action_serial":serial,"action_elapsed":elapsed,"action_duration":duration,"progress":duration > 0 ? elapsed/duration : 0,"fruit_stage":fruit,"game_date":"2026-09-30","practice_period":NSNull(),"pending_bell":false,"pending_capture":false]
}
func render(_ target:TianmuView = view)->NSBitmapImageRep {
 let result=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(target.bounds.width),pixelsHigh:Int(target.bounds.height),bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:result)
 target.draw(target.bounds);NSGraphicsContext.restoreGraphicsState();return result
}
func bytes(_ rep:NSBitmapImageRep,_ box:NSRect? = nil)->[UInt8] {
 let box=box ?? NSRect(x:0,y:0,width:rep.pixelsWide,height:rep.pixelsHigh)
 var output:[UInt8]=[]
 for y in Int(box.minY)..<Int(box.maxY) {for x in Int(box.minX)..<Int(box.maxX) {
  let p=rep.bitmapData!.advanced(by:y*rep.bytesPerRow+x*4);output += [p[0],p[1],p[2],p[3]]
 }};return output
}
func mouse(_ type:NSEvent.EventType,_ p:NSPoint,_ time:Double)->NSEvent {
 NSEvent.mouseEvent(with:type,location:p,modifierFlags:[],timestamp:time,windowNumber:0,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
func visiblePoint()->NSPoint {
 for y in 0..<190 {for x in 205..<370 {let p=NSPoint(x:CGFloat(x)+0.5,y:CGFloat(y)+0.5);if view.subject(at:p) == "attendant" {return p}}}
 fatalError("Missing fixture sprite")
}
'''


class RoutinePresentationTests(unittest.TestCase):
    def run_swift(self, body, *, walk=True):
        with tempfile.TemporaryDirectory(prefix='tianmu-routine-presentation-') as directory:
            d = Path(directory); art = d/'A01'; art.mkdir()
            png(art/'stand.png')
            manifest = {'version':1,'stand':{'file':'stand.png'}}
            if walk:
                manifest['walk'] = {'fps':6,'frames':[]}
                for index in range(4):
                    name=f'walk-{index}.png'; png(art/name, pixels={(1,1):(255,0,0,255),(6,10):(0,0,255,255),(3,5):(0,255 if index % 2 else 0,255,255)})
                    manifest['walk']['frames'].append({'file':name})
            (art/'manifest.json').write_text(json.dumps(manifest))
            (d/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
            (d/'main.swift').write_text(source+PRELUDE+body)
            build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(d/'Scene.swift'),str(ROOT/'native/v1/Presentation.swift'),str(ROOT/'native/v1/WindowPlacement.swift'),str(ROOT/'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT/'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),str(d/'main.swift'),'-o',str(d/'check')],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(d/'check'),str(art)],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);print(run.stdout.strip())

    def test_service_stand_never_runs_old_loop_or_slides_without_walk_art(self):
        self.run_swift(r'''
assert(view.applyRoutine(snapshot("walk",1)))
let initial=bytes(render()), bounds=view.attendantBounds
for time:Double in [0.5,4,8,15,26,99] {
 view.updateAnimation(elapsed:time)
 assert(view.attendantBounds == bounds && bytes(render()) == initial, "Stand-only production art must never slide through the old 26-second loop")
}
assert(view.unavailableRoutineAction == "walk")
for (index,action) in ["read","sweep","offer","practice","catch","bell","rest"].enumerated() {
 assert(view.applyRoutine(snapshot(action,index+2)))
 assert(view.unavailableRoutineAction == action)
 assert(view.attendantBounds == bounds && bytes(render()) == initial, "Missing formal actions must retain stand instead of inventing geometry")
}
print("PASS: service mode stops fixed loop; no stand sliding or invented formal action; NO_WINDOWS_NO_WORKER")
''',walk=False)

    def test_snapshots_interpolate_without_restarts_or_transition_teleports(self):
        self.run_swift(r'''
assert(view.applyRoutine(snapshot("walk",10)))
let start=view.attendantBounds.midX
view.updateAnimation(elapsed:0.5)
let half=view.attendantBounds.midX
assert(half < start)
assert(view.applyRoutine(snapshot("walk",10)))
assert(view.attendantBounds.midX == half, "Duplicate serial and elapsed must not restart a walk")
view.updateAnimation(elapsed:1)
assert(view.applyRoutine(snapshot("walk",10,1)))
let progressed=view.attendantBounds.midX
assert(progressed < half)
view.updateAnimation(elapsed:1.25)
assert(view.attendantBounds.midX < progressed)
let beforeStop=view.attendantBounds
assert(view.applyRoutine(snapshot("read",11,0,12)))
assert(view.attendantBounds.midX == beforeStop.midX, "Action transition must retain the exact displayed position")
view.updateAnimation(elapsed:12)
assert(view.attendantBounds.midX == beforeStop.midX)
assert(view.applyRoutine(snapshot("walk",12,2)))
assert(view.attendantBounds.midX == beforeStop.midX, "Joining a partially complete service action must not teleport")
view.updateAnimation(elapsed:12.25)
assert(view.attendantBounds.midX != beforeStop.midX)
view.updateAnimation(elapsed:13)
let stale=view.attendantBounds
view.updateAnimation(elapsed:99)
assert(view.attendantBounds == stale, "A stale backend must stop after bounded interpolation, never free-run a private routine")
assert(view.routinePresentation.snapshot?.serial == 12)
print("PASS: backend progress interpolation, duplicate serial idempotence, continuous transitions and bounded stale feed; NO_WINDOWS_NO_WORKER")
''')

    def test_invalid_and_out_of_order_data_cannot_reset_live_state(self):
        self.run_swift(r'''
assert(!view.applyRoutine(nil))
let safe=view.attendantBounds
view.updateAnimation(elapsed:10)
assert(view.attendantBounds == safe, "Missing initial service data must remain safely still")
assert(view.applyRoutine(snapshot("walk",5,1)))
let stable=view.attendantBounds
var bad:[String:Any]
for key in ["progress","action_duration","action_elapsed","action_serial"] {
 bad=snapshot("walk",6);bad[key]=Double.nan
 assert(!view.applyRoutine(bad), "NaN must be rejected")
 bad=snapshot("walk",6);bad[key]=true
 assert(!view.applyRoutine(bad), "Boolean is not numeric routine timing")
}
bad=snapshot("dance",6);assert(!view.applyRoutine(bad))
bad=snapshot("walk",6);bad["fruit_stage"]="rotten";assert(!view.applyRoutine(bad))
bad=snapshot("walk",6);bad["progress"]=0.9;assert(!view.applyRoutine(bad), "Inconsistent elapsed/progress must not be consumed")
assert(!view.applyRoutine(snapshot("walk",4)))
assert(!view.applyRoutine(snapshot("read",5,1)))
assert(!view.applyRoutine(snapshot("walk",5,0)))
assert(!view.applyRoutine(nil))
assert(view.routinePresentation.snapshot?.serial == 5 && view.attendantBounds == stable)
print("PASS: invalid/missing/out-of-order/conflicting service snapshots preserve live pose; NO_WINDOWS_NO_WORKER")
''')

    def test_press_and_ritual_hold_pose_then_resume_latest_service_state(self):
        self.run_swift(r'''
assert(view.applyRoutine(snapshot("walk",1)))
view.updateAnimation(elapsed:0.5)
let p=visiblePoint()
view.mouseDown(with:mouse(.leftMouseDown,p,10))
let held=view.attendantBounds, heldPixels=bytes(render())
view.updateAnimation(elapsed:2)
assert(view.applyRoutine(snapshot("walk",1,2)))
assert(view.attendantBounds == held && bytes(render()) == heldPixels)
assert(view.shouldCapturePointer(at:NSPoint(x:-999,y:-999)))
view.cancelInteraction()
assert(view.attendantBounds == held, "Cancel resumes from the held position, not invisible service displacement")
view.updateAnimation(elapsed:2.2)
assert(view.attendantBounds.midX < held.midX)
view.ritualStage="取香行礼"
let ritual=view.attendantBounds
let spriteRegion=NSRect(x:205,y:0,width:165,height:190)
let ritualPixels=bytes(render(),spriteRegion)
assert(view.applyRoutine(snapshot("read",2,0,12)))
view.updateAnimation(elapsed:6)
assert(view.attendantBounds == ritual && bytes(render(),spriteRegion) == ritualPixels)
assert(view.routinePresentation.snapshot?.action == "read", "A ritual must keep receiving current service work")
view.ritualStage=nil
assert(view.attendantBounds.midX == ritual.midX)
view.updateAnimation(elapsed:8)
assert(view.attendantBounds.midX == ritual.midX && view.unavailableRoutineAction == "read")
assert(view.applyRoutine(snapshot("walk",3)))
view.ritualStage="取香行礼"
let secondHold=view.attendantBounds
assert(view.applyRoutine(snapshot("walk",3,2)))
view.ritualStage=nil
assert(view.attendantBounds.midX == secondHold.midX)
view.updateAnimation(elapsed:8.25)
assert(view.attendantBounds.midX != secondHold.midX)
// Every claimed sprite point still refers to the currently rendered frame.
let image=render()
for y in 0..<190 {for x in 205..<370 {
 let p=NSPoint(x:CGFloat(x)+0.5,y:CGFloat(y)+0.5)
 if view.subject(at:p) == "attendant" {assert((image.colorAt(x:x,y:189-y)?.alphaComponent ?? 0) > 0)}
}}
let crossing=TianmuView(frame:view.frame);crossing.attendantArtwork=view.attendantArtwork
assert(crossing.applyRoutine(snapshot("walk",1)))
assert(crossing.applyRoutine(snapshot("walk",1,3)))
crossing.ritualStage="取香行礼"
let crossed=crossing.attendantBounds.midX
assert(crossing.applyRoutine(snapshot("walk",1,4)))
crossing.ritualStage=nil
crossing.updateAnimation(elapsed:0.1)
assert(crossing.attendantBounds.midX < crossed, "Resuming the same walk after its midpoint must preserve its destination and direction")
print("PASS: pointer/ritual priority, latest service receipt while held, no resume jump, matching frame alpha; NO_WINDOWS_NO_WORKER")
''')

    def test_fruit_changes_only_existing_plate_and_idol_stays_static(self):
        self.run_swift(r'''
assert(view.applyRoutine(snapshot("idle",1,0,0,"fresh")))
let fresh=render()
assert(view.applyRoutine(snapshot("idle",1,0,0,"soft")))
let soft=render()
assert(view.applyRoutine(snapshot("idle",1,0,0,"ripe")))
let ripe=render()
let fruit=NSRect(x:90,y:139,width:35,height:9)
assert(bytes(fresh,fruit) != bytes(soft,fruit) && bytes(soft,fruit) != bytes(ripe,fruit))
let idol=NSRect(x:55,y:70,width:100,height:66)
assert(bytes(fresh,idol) == bytes(soft,idol) && bytes(soft,idol) == bytes(ripe,idol))
assert(view.routinePresentation.snapshot?.serial == 1)
print("PASS: fresh/soft/ripe on existing fruit, same-serial metadata updates, static idol unchanged; NO_WINDOWS_NO_WORKER")
''',walk=False)

    def test_host_and_scene_preview_consume_same_backend_snapshot_offscreen(self):
        self.run_swift(r'''
let host=ApplicationHost()
host.scene=TianmuView(frame:view.frame);host.scene.attendantArtwork=view.attendantArtwork
host.configureSceneState()
let preview=TianmuView(frame:view.frame);preview.attendantArtwork=view.attendantArtwork
let state:[String:Any]=["routine":snapshot("practice",4,10,45,"soft"),"shop":[["id":"offering_plate","placed":true]]]
let wire=try! JSONSerialization.data(withJSONObject:["state":state]) + Data([10])
host.store.receive(wire)
ScenePreview(store:host.store).apply(to:preview)
assert(host.scene.routinePresentation.snapshot?.action == "practice" && preview.routinePresentation.snapshot?.action == "practice")
assert(host.scene.routinePresentation.snapshot?.fruitStage == "soft" && preview.offeringPlate && host.scene.offeringPlate)
assert(bytes(render(host.scene)) == bytes(render(preview)))
host.scene.updateAnimation(elapsed:15);preview.updateAnimation(elapsed:15)
assert(bytes(render(host.scene)) == bytes(render(preview)))
assert(host.store.process == nil && host.overlay == nil && host.panel == nil)
print("PASS: actual Store receipt -> production scene callback and ScenePreview shared mapping; NO_WINDOWS_NO_WORKER")
''',walk=False)
