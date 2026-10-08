"""Default low-activity behavior, using real pinned movement and deterministic IDs."""
import importlib.util
from pathlib import Path
import unittest
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

HARNESS=r'''
import AppKit
let app=NSApplication.shared
app.setActivationPolicy(.prohibited)
func check(_ ok:@autoclosure ()->Bool,_ text:String) {if !ok() {print("FAIL: "+text);exit(1)}}
let screen=DesktopInsectScreen(id:"left",frame:NSRect(x:-1920,y:-120,width:1920,height:1080))
var now=10.0
var presentations=[NSWindow]()
let layer=DesktopInsects(motionModuleURL:URL(fileURLWithPath:CommandLine.arguments[2]),
    screens:[screen],renderTime:{now},weaving:DesktopWeavingConfiguration(minimumDuration:0.2,maximumDuration:0.2),windowPresenter:{presentations.append($0)})
var rows=[[String:Any]]()
for index in 0..<12 {
    let id="adult-\(index)",x=Double(index+1)/13.0,y=Double(index%3+1)/4.0
    let color=["普通褐色","中褐色","深褐色","白色"][index%4]
    let sex=index%2==0 ? "F":"M"
    rows.append(["id":id,"x":x,"y":y,"color":color,"sex":sex])
}
layer.update(rows:rows)
func step(_ n:Int) {for _ in 0..<n {now+=1/30;layer.refresh()}}
func positions()->[String:NSPoint] {Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.point)})}
func shownIDs()->Set<String> {Set(layer.positions.filter{$0.opacity>0.05}.map{$0.id})}
func mouse(_ type:NSEvent.EventType,_ point:NSPoint)->NSEvent {
 let window=layer.windows[0]
 return NSEvent.mouseEvent(with:type,location:window.convertPoint(fromScreen:point),modifierFlags:[],timestamp:now,
  windowNumber:window.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
switch CommandLine.arguments[1] {
case "quiet_idle_uses_only_small_windows":
 layer.show();step(150)
 check(presentations.count==3 && layer.spriteWindows.count==3,"Visible insects must request exactly three reusable small display windows")
 check(presentations.allSatisfy{$0.frame.width<=40 && $0.frame.height<=40},"Passive quiet insects must never present a full-desktop backing surface")
 check(presentations.allSatisfy{$0.ignoresMouseEvents && !$0.canBecomeKey && !$0.canBecomeMain},"Every passive sprite must remain nonfocusing and mouse-through")
 check(!layer.captureOverlayPresented,"An idle quiet layer never orders the full-screen net")
 check(layer.spriteWindows.allSatisfy{screen.frame.contains($0.frame)},"Small windows follow real monitor geometry, including negative origins")
 check(layer.contextExcludedWindowNumbers.isSuperset(of:Set(layer.spriteWindows.map{$0.windowNumber}.filter{$0>0})),"Desktop safety must exclude every owned passive sprite")
 func visiblePixels(_ view:NSView)->Int {
  let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(view.bounds.width),pixelsHigh:Int(view.bounds.height),bitsPerSample:8,
   samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
  NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap);view.draw(view.bounds);NSGraphicsContext.restoreGraphicsState()
  var count=0
  for y in 0..<bitmap.pixelsHigh {for x in 0..<bitmap.pixelsWide {if bitmap.colorAt(x:x,y:y)!.alphaComponent>0 {count+=1}}}
  return count
 }
 check(layer.spriteWindows.allSatisfy{visiblePixels($0.contentView!)>0},"Actual small views draw the original insects")
 check(visiblePixels(layer.windows[0].contentView!)==0,"Idle full-screen views never duplicate the sprite artwork")
case "quiet_window_capture_lifecycle":
 layer.show();step(150)
 let original=layer.windows[0],sprites=layer.spriteWindows.map{ObjectIdentifier($0)}
 layer.beginCapture();check(!layer.captureOverlayPresented,"Arming a passive gesture does not allocate a blank full-screen surface")
 let view=layer.windows[0].contentView!
 view.mouseDown(with:mouse(.leftMouseDown,NSPoint(x:screen.frame.minX+1,y:screen.frame.minY+1)))
 view.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)))
 check(layer.captureOverlayPresented && presentations.contains{$0===original},"A real selection presents its full-screen net surface")
 view.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)))
 check(layer.captureOverlayPresented && layer.isWeaving,"Release keeps only passive weaving, without hiding the net early")
 step(20)
 check(!layer.captureOverlayPresented && !layer.isWeaving,"The full-screen surface retires after net retraction")
 check(layer.windows[0] !== original,"Completed full-screen backing is closed and replaced with an unshown deferred window")
 check(layer.spriteWindows.map{ObjectIdentifier($0)}==sprites,"Net completion must retain independent sprite windows")
 let count=presentations.count
 layer.hide();step(30);check(presentations.count==count,"Hidden mode cannot re-present a sprite or net")
 layer.show();check(presentations.count>count && !layer.captureOverlayPresented,"Show restores sprites without a blank full-screen layer")
 let retained=layer.windows+layer.spriteWindows
 layer.close()
 check(layer.windows.isEmpty && layer.spriteWindows.isEmpty && layer.contextExcludedWindowNumbers.isEmpty,"Close releases both window families and exclusion metadata")
 check(retained.allSatisfy{!$0.isVisible && $0.ignoresMouseEvents},"Every retired surface remains unshown and passive")
case "quiet_unchanged_frame_does_not_redraw":
 layer.show();step(150)
 let moves=layer.spriteWindowMoveCount,redraws=layer.spriteRedrawRequestCount
 check(moves>0 && redraws>0,"Counters must have observed the actual initial positioning and rendered frames")
 for _ in 0..<100 {layer.refresh()}
 print("UNCHANGED_COUNTERS moves=\(layer.spriteWindowMoveCount-moves) redraws=\(layer.spriteRedrawRequestCount-redraws)")
 // Unshown AppKit views can retain their initial needsDisplay flag without a
 // display transaction. Measure new side-effect requests, not that stale flag.
 let repeatedRedraws=layer.spriteRedrawRequestCount-redraws
 check(layer.spriteWindowMoveCount==moves && repeatedRedraws==0,"A repeated identical frame performs no setFrameOrigin or redraw request")
 check(layer.positions.filter{$0.opacity>0}.allSatisfy{$0.activity == .resting},"Fixture must be resting")
 step(15)
 check(layer.spriteWindowMoveCount==moves,"Fractional stationary positions must not keep requesting AppKit window movement while grooming")
 print("STATIC_COUNTERS moves=\(layer.spriteWindowMoveCount-moves), repeated_redraws=\(repeatedRedraws)")
case "quiet_natural_capture_excludes_sprites":
 var excluded=Set<Int>(),caught=[[String]](),shown=[NSWindow]()
 let context=DesktopNaturalCaptureContext(screenID:screen.id,visibleFrame:screen.frame,desktopFrames:[screen.frame],blockedFrames:[],isReliable:true,dragPasteboardChangeCount:7)
 let peer=DesktopInsects(motionModuleURL:URL(fileURLWithPath:CommandLine.arguments[2]),screens:[screen],renderTime:{now},
   weaving:DesktopWeavingConfiguration(minimumDuration:0.2,maximumDuration:0.2),windowPresenter:{shown.append($0)},
   naturalContextProvider:{_,numbers in excluded=numbers;return context})
 peer.onCapture={caught.append($0)};peer.update(rows:rows);peer.show()
 for _ in 0..<150 {now+=1/30;peer.refresh()}
 let expected=Set(peer.positions.filter{$0.opacity>0.05}.map{$0.id})
 let origin=NSPoint(x:screen.frame.minX+1,y:screen.frame.minY+1),end=NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)
 peer.observeNaturalMouse(.leftMouseDown,at:origin,context:context)
 check(!peer.captureOverlayPresented,"A desktop press alone must not expose an overlay")
 peer.observeNaturalMouse(.leftMouseDragged,at:end,context:context)
 check(!peer.captureOverlayPresented && peer.captureIsNatural,"Validated desktop dragging leaves the selection to Finder")
 peer.observeNaturalMouse(.leftMouseUp,at:end,context:context)
 check(peer.captureOverlayPresented && peer.isWeaving,"Only the validated release presents the passive natural net")
 let passiveNumbers=Set(peer.spriteWindows.map{$0.windowNumber}.filter{$0>0})
 for _ in 0..<20 {now+=1/30;peer.refresh()}
 check(caught.count==1 && Set(caught[0])==expected,"Natural completion captures only the same visible real IDs")
 check(excluded.isSuperset(of:passiveNumbers),"Released natural validation must exclude small owned windows")
 check(!peer.captureOverlayPresented,"Natural completion also releases its large backing surface")
 check((peer.windows+peer.spriteWindows).allSatisfy{!$0.isVisible && $0.ignoresMouseEvents},"Synthetic natural capture never shows or intercepts a physical window")
 peer.close()
case "default_identity_and_input_cache":
 check(layer.positions.count==12 && shownIDs().isEmpty,"All real IDs exist before the first gentle admission")
 let builds=layer.motionInputBuildCount
 var seen=Set<String>()
 for _ in 0..<1800 {
  step(1)
  check(layer.positions.count==12,"Quiet presentation cannot delete real IDs")
  check(layer.positions.filter{$0.opacity>0}.count<=3,"Native layer must preserve the three-visible cap")
  check(layer.positions.filter{$0.opacity>0 && $0.activity == .flying}.count<=1,"Native layer must enforce one flying body per screen")
  for insect in layer.positions {
   let row=rows.first{$0["id"] as? String == insect.id}!
   check(insect.color == row["color"] as! String && insect.sex == row["sex"] as! String,"Display scheduling cannot alter source sex or phenotype")
   check(insect.scale>=0.95 && insect.scale<=1.2,"Use upstream individual's original scale")
   check(screen.frame.contains(insect.point),"All IDs remain on the real screen")
   if insect.opacity>0 {seen.insert(insect.id)}
  }
 }
 check(seen.count>=6,"Waiting IDs eventually get a display slot")
 check(layer.motionInputBuildCount==builds,"Unchanged rows/screens/surfaces must not be mapped every animation frame")
case "quiet_capture_only_visible_real_ids":
 step(150);let expected=shownIDs()
 check(expected.count==3,"Fixture requires three visible real IDs")
 var submitted=[[String]]();layer.onCapture={submitted.append($0)}
 layer.beginCapture()
 let view=layer.windows[0].contentView!
 view.mouseDown(with:mouse(.leftMouseDown,NSPoint(x:screen.frame.minX+1,y:screen.frame.minY+1)))
 view.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)))
 view.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)))
 check(layer.windows.allSatisfy{$0.ignoresMouseEvents},"Weaving releases input immediately")
 step(10)
 check(submitted.count==1 && Set(submitted[0])==expected,"Only drawn real IDs are captured, never hidden placeholders")
 check(layer.positions.count==12,"Capture callback alone is not backend acknowledgement and cannot delete IDs")
case "quiet_snapshot_and_clock_continuity":
 step(260)
 let old=positions(),alphas=Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.opacity)})
 layer.update(rows:Array(rows.reversed()))
 check(positions()==old,"Snapshot reordering at the same clock cannot move any ID")
 check(Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.opacity)})==alphas,"Reordering cannot restart admission or alpha")
 now+=90;layer.refresh();check(positions()==old,"Long gaps cannot advance quiet flight")
 now-=100;layer.refresh();check(positions()==old,"Backward clock cannot advance quiet flight")
 now=Double.nan;layer.refresh();check(positions()==old,"Invalid clock freezes quiet motion")
 now=500;layer.refresh();check(positions()==old,"Clock recovery only establishes an anchor")
case "quiet_pointer_keeps_original_threat_boundary":
 step(120)
 let resting=layer.positions.first{$0.opacity>0.9 && $0.activity == .resting}!
 let pointer=NSPoint(x:resting.point.x-20,y:resting.point.y)
 now+=1/30;layer.updateBehaviorPointer(pointer,buttonsPressed:1);layer.refresh()
 check(layer.positions.first{$0.id==resting.id}!.activity == .resting,"Pressed pointer cannot start a new fright")
 now+=1/30;layer.updateBehaviorPointer(pointer,buttonsPressed:0);layer.refresh()
 let escaped=layer.positions.first{$0.id==resting.id}!
 check(escaped.activity == .flying && escaped.velocity.x>0,"A free nearby pointer still invokes original escape away from the pointer")
 check(hypot(escaped.velocity.x,escaped.velocity.y)<=180.001,"Quiet fright has a bounded desktop speed")
case "quiet_shared_fright_has_one_flying_limit":
 layer.update(rows:[])
 layer.update(rows:(0..<3).map {i -> [String:Any] in ["id":"fright-\(i)","x":0.5,"y":0.5,"color":"普通褐色"]})
 step(120)
 let resting=layer.positions.first{$0.opacity>0.9}!
 now+=1/30;layer.updateBehaviorPointer(NSPoint(x:resting.point.x-20,y:resting.point.y),buttonsPressed:0);layer.refresh()
 check(layer.positions.filter{$0.opacity>0 && $0.activity == .flying}.count==1,"Even simultaneous nearby threats may animate only one flying individual per screen")
case "quiet_multiscreen_and_disconnect":
 let right=DesktopInsectScreen(id:"right",frame:NSRect(x:500,y:-700,width:800,height:600))
 layer.updateScreens([screen,right])
 check(layer.spriteWindows.count==6,"Two real screens have at most three reusable sprite windows each")
 for _ in 0..<900 {
  step(1)
  check(layer.positions.count==12,"Disconnected monitors preserve all real IDs")
  for display in [screen,right] {
   check(layer.positions.filter{$0.screenID==display.id && $0.opacity>0}.count<=3,"Each actual screen owns at most three visible bodies")
  }
  for insect in layer.positions {check([screen,right].contains{$0.id==insect.screenID && $0.frame.contains(insect.point)},"No gap coordinates")}
 }
 layer.updateScreens([right]);step(30)
 check(layer.spriteWindows.count==3,"Removed screen sprite windows are closed rather than left resident")
 check(layer.positions.count==12 && layer.positions.allSatisfy{$0.screenID==right.id && right.frame.contains($0.point)},"Rehome every ID onto retained screen")
 check(layer.positions.filter{$0.opacity>0}.count<=3,"Screen removal cannot merge two visible flocks")
case "quiet_capture_tracks_backend_removal":
 step(150);let visible=shownIDs(),removed=visible.sorted().first!
 layer.beginCapture()
 var submitted=[[String]]();layer.onCapture={submitted.append($0)}
 let view=layer.windows[0].contentView!
 view.mouseDown(with:mouse(.leftMouseDown,NSPoint(x:screen.frame.minX+1,y:screen.frame.minY+1)))
 view.mouseDragged(with:mouse(.leftMouseDragged,NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)))
 view.mouseUp(with:mouse(.leftMouseUp,NSPoint(x:screen.frame.maxX-1,y:screen.frame.maxY-1)))
 layer.update(rows:rows.filter{$0["id"] as? String != removed} + [["id":"new-born","x":0.5,"y":0.5,"color":"白色","sex":"F"]])
 step(10)
 check(submitted.count==1 && Set(submitted[0])==visible.subtracting([removed]),"Removed IDs stay removed and unseen replacements cannot enter the submitted net")
case "quiet_population_shrink_and_late_arrival":
 step(150)
 let survivor=shownIDs().sorted().last!
 layer.update(rows:rows.filter{$0["id"] as? String==survivor})
 step(30)
 check(layer.positions.count==1 && shownIDs()==Set([survivor]),"A remaining ID in any slot stays visible after population shrink")
 step(900)
 let one=rows.filter{$0["id"] as? String==survivor}
 layer.update(rows:one + [["id":"late-one","x":0.5,"y":0.5,"color":"白色"],
   ["id":"late-two","x":0.4,"y":0.4,"color":"白色"],["id":"late-three","x":0.6,"y":0.6,"color":"白色"]])
 var last=Dictionary(uniqueKeysWithValues:layer.positions.map{($0.id,$0.opacity)})
 for _ in 0..<180 {
  step(1)
  for insect in layer.positions {
   if let alpha=last[insect.id] {check(abs(alpha-insect.opacity)<0.08,"A late new ID cannot abruptly retire a long-visible individual")}
   last[insect.id]=insect.opacity
  }
 }
default:exit(2)
}
check((layer.windows+layer.spriteWindows).allSatisfy{!$0.isVisible && !$0.isKeyWindow && !$0.isMainWindow},"Tests must never expose a window")
layer.close();print("PASS: \(CommandLine.arguments[1]); DEFAULT_QUIET_NO_VISIBLE_UI_NO_WORKER_NO_SAVE")
'''

class QuietInsectPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='tianmu-quiet171-');cls.addClassCleanup(cls.temp.cleanup)
        folder=Path(cls.temp.name);(folder/'main.swift').write_text(HARNESS)
        cls.binary=folder/'check'
        cls.build=subprocess.run(['swiftc','-O','-framework','AppKit',*(str(ROOT/'native/v1'/name) for name in ['WindowPlacement.swift','InsectArtwork.swift','DesktopInsects.swift']),str(folder/'main.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=60)

    def scenario(self,name):
        self.assertEqual(self.build.returncode,0,self.build.stderr)
        result=subprocess.run([str(self.binary),name,str(ROOT/'third_party/fly-paradise/desktop-motion.js')],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('DEFAULT_QUIET_NO_VISIBLE_UI_NO_WORKER_NO_SAVE',result.stdout);print(result.stdout.strip())

    def test_native_default_retains_population_and_caches_static_mapping(self):
        self.scenario('default_identity_and_input_cache')

    def test_default_capture_submits_visible_real_ids_only(self):
        self.scenario('quiet_capture_only_visible_real_ids')

    def test_default_clock_gaps_and_snapshot_order_preserve_continuity(self):
        self.scenario('quiet_snapshot_and_clock_continuity')

    def test_quiet_rest_retains_original_free_pointer_fright_and_pressed_suppression(self):
        self.scenario('quiet_pointer_keeps_original_threat_boundary')

    def test_shared_threat_cannot_exceed_one_flying_individual(self):
        self.scenario('quiet_shared_fright_has_one_flying_limit')

    def test_default_real_screen_limits_and_disconnect(self):
        self.scenario('quiet_multiscreen_and_disconnect')

    def test_default_capture_uses_latest_backend_ids(self):
        self.scenario('quiet_capture_tracks_backend_removal')

    def test_idle_presentation_never_orders_a_fullscreen_backing_surface(self):
        self.scenario('quiet_idle_uses_only_small_windows')

    def test_small_window_capture_retraction_hide_show_and_close(self):
        self.scenario('quiet_window_capture_lifecycle')

    def test_repeated_unchanged_sprite_frame_does_not_request_redraw(self):
        self.scenario('quiet_unchanged_frame_does_not_redraw')

    def test_natural_capture_context_excludes_owned_small_windows(self):
        self.scenario('quiet_natural_capture_excludes_sprites')

    def test_population_shrink_and_late_arrival_do_not_flash_or_hide_survivor(self):
        self.scenario('quiet_population_shrink_and_late_arrival')

    def test_default_sixty_seconds_limits_activity_and_has_long_real_stays(self):
        spec=importlib.util.spec_from_file_location('insect171',ROOT/'tools/benchmark_desktop_insects.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.measure(ROOT/'third_party/fly-paradise/desktop-motion.js',repeats=1)
        self.assertTrue(result['countPreserved'],'All real IDs must remain represented')
        self.assertLessEqual(result['maxVisible'],3,'Desktop must show at most three real insects per screen')
        self.assertLessEqual(result['maxFlying'],1,'At most one visible fly may fly at once')
        self.assertLess(result['p95FlyingSpeed'],120,'Ambient flight must be markedly slower than upstream 280-570')
        self.assertGreater(result['longestContinuousRestSeconds'],6,'Rest must stay continuous for seconds')
        self.assertGreater(result['restTimeRatio'],.45,'Visible insects must spend substantial time resting')
        self.assertEqual(result['timeline'][0]['visible'],0,'Startup begins without a sudden full flock')
        self.assertLess(result['maxAlphaJump'],.08,'Admission and retirement must fade, not flash')
        self.assertGreaterEqual(result['seenIDs'],6,'Hidden IDs must take turns without being discarded')

if __name__=='__main__':unittest.main()
