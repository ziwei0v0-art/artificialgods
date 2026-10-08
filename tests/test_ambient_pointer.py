"""Animation-only desktop visibility: no event proof, posted input or shown windows."""
import unittest

from tests import test_pointer_access


CONTEXT_FIXTURE = r'''
let primaryTop=NSScreen.screens.first!.frame.maxY
let screenA=DesktopInsectScreen(id:"left",frame:NSRect(x:0,y:0,width:800,height:600))
let screenB=DesktopInsectScreen(id:"right",frame:NSRect(x:800,y:0,width:800,height:600))
let iconLevel=Int(CGWindowLevelForKey(.desktopIconWindow))
let dockLevel=Int(CGWindowLevelForKey(.dockWindow))
let freePoint=NSPoint(x:100,y:100), otherPoint=NSPoint(x:900,y:100)
let coveredFrame=NSRect(x:80,y:80,width:40,height:40)
func windowRow(_ number:Int,_ owner:Int,_ level:Int,_ frame:NSRect) -> [String:Any] {
    [kCGWindowNumber as String:number,kCGWindowOwnerPID as String:owner,
     kCGWindowLayer as String:level,kCGWindowAlpha as String:1,
     kCGWindowBounds as String:["X":frame.minX,"Y":primaryTop-frame.maxY,
         "Width":frame.width,"Height":frame.height]]
}
func context(_ screen:DesktopInsectScreen,_ extra:[[String:Any]] = []) -> DesktopNaturalCaptureContext {
    DesktopNaturalCaptureContext.fromWindowInfo([
        windowRow(2,401,iconLevel,screen.frame),windowRow(25,402,dockLevel,screen.frame)
    ]+extra,screenID:screen.id,visibleFrame:screen.frame,primaryTop:primaryTop,
        excludingWindowNumbers:[],dragPasteboardChangeCount:7,
        applicationIdentifier:{$0 == 401 ? "com.apple.finder" : $0 == 402 ? "com.apple.dock" : nil})
}
'''


class AmbientPointerTests(unittest.TestCase):
    _run_harness = test_pointer_access.PointerAccessTests._run_harness

    def test_only_classified_fullscreen_dock_is_omitted_without_mutating_capture_proof(self):
        self._run_harness('ambient visibility boundary', CONTEXT_FIXTURE + r'''
let raw=context(screenA)
let blocked=raw.blockedFrames, docks=raw.dockBackgrounds, targets=raw.desktopEventTargets
let sample=NSRect(x:99.9,y:99.9,width:0.2,height:0.2)
require(raw.dockBackgrounds.count == 1 && !raw.permits(sample),"Fixture must retain full-screen Dock as a raw capture blocker")
require(ApplicationHost.ambientDesktopVisible(freePoint,context:raw),"Animation may omit the classified full-screen Dock background")
for extra in [windowRow(30,999,0,coveredFrame),
              windowRow(31,999,iconLevel+2,coveredFrame),
              windowRow(32,402,dockLevel,coveredFrame),
              windowRow(33,999,dockLevel,screenA.frame)] {
    let obstructed=context(screenA,[extra])
    require(!ApplicationHost.ambientDesktopVisible(freePoint,context:obstructed),
        "Ordinary apps, widgets, small Dock windows and unclassified full-screen owners remain blockers")
}
require(!ApplicationHost.ambientDesktopVisible(NSPoint(x:800,y:100),context:raw),"A point spanning the screen edge is not exposed desktop")
require(!ApplicationHost.ambientDesktopVisible(otherPoint,context:raw),"Visibility cannot escape its source screen")
var local=raw; local.sourceIsLocal=true
require(!ApplicationHost.ambientDesktopVisible(freePoint,context:local),"Local capture metadata cannot authorize ambient desktop visibility")
let unknown=DesktopNaturalCaptureContext(screenID:"left",visibleFrame:screenA.frame,
    desktopFrames:[screenA.frame],blockedFrames:[],isReliable:false,dragPasteboardChangeCount:7)
require(!ApplicationHost.ambientDesktopVisible(freePoint,context:unknown),"Unreliable geometry fails closed")
let noDesktop=DesktopNaturalCaptureContext(screenID:"left",visibleFrame:screenA.frame,
    desktopFrames:[],blockedFrames:[],isReliable:true,dragPasteboardChangeCount:7)
require(!ApplicationHost.ambientDesktopVisible(freePoint,context:noDesktop),"Visible-screen bounds alone do not establish desktop coverage")
require(raw.blockedFrames == blocked && raw.dockBackgrounds == docks && raw.desktopEventTargets == targets,
    "Animation visibility must not modify raw capture geometry or target metadata")
require(raw.eventProof == nil && raw.approvedDockWindows.isEmpty && raw.validatingDesktopEvent(nil) == nil && !raw.permits(sample),
    "Animation visibility must never synthesize Finder input proof or approve a capture")
print("PASS: full-screen Dock classification, apps/widgets/small Dock/unknown owner veto, screen/local/reliability bounds, capture proof unchanged; NO_VISIBLE_WINDOWS_NO_WORKER")
''')

    def test_cache_refresh_failure_cross_screen_clock_and_activation_boundaries(self):
        self._run_harness('ambient cache boundary', CONTEXT_FIXTURE + r'''
let host=hostAt("ambient-cache")
let layer=DesktopInsects(screens:[screenA,screenB],renderTime:{10},windowPresenter:{_ in})
host.desktopInsects=layer
var now=10.0, reads=0
var offered:DesktopNaturalCaptureContext?=context(screenA)
host.ambientClock={now}
host.ambientContextProvider={ point,excluded in
    reads += 1
    require(excluded == Set(layer.windows.map{$0.windowNumber}),"Only known insect windows may be excluded from geometry")
    require(point.x.isFinite && point.y.isFinite,"Invalid points must not reach the metadata reader")
    return offered
}
require(host.ambientDesktopVisible(at:freePoint) && reads == 1,"First sample must read fresh context")
offered=context(screenA,[windowRow(30,999,0,coveredFrame)])
now=10.199
require(host.ambientDesktopVisible(at:freePoint) && reads == 1,"Same-screen context can be cached for less than 0.2 seconds")
now=10.201
require(!host.ambientDesktopVisible(at:freePoint) && reads == 2,"Application coverage must be refreshed after the 0.2-second bound")
offered=context(screenB); now=10.202
require(host.ambientDesktopVisible(at:otherPoint) && reads == 3,"Cross-screen movement must immediately read that screen")
now=10.1
require(host.ambientDesktopVisible(at:otherPoint) && reads == 4,"Clock rollback must invalidate the old cache and read fresh metadata")
now=Double.nan
require(!host.ambientDesktopVisible(at:otherPoint) && reads == 4,"Invalid clock values disable animation without a metadata read")
now=10.11
require(host.ambientDesktopVisible(at:otherPoint) && reads == 5,"A valid sample after clock failure cannot reuse invalidated cache")
require(!host.ambientDesktopVisible(at:NSPoint(x:CGFloat.nan,y:100)) && reads == 5,"Invalid coordinates fail closed before metadata")
require(host.ambientDesktopVisible(at:otherPoint) && reads == 6,"Coordinate failure clears the former cache")
offered=nil; now=10.4
require(!host.ambientDesktopVisible(at:otherPoint) && reads == 7,"Read failure cannot retain stale exposed-desktop state")
offered=context(screenB)
require(host.ambientDesktopVisible(at:otherPoint) && reads == 8,"Read failure is not cached and may recover on the next sample")
offered=DesktopNaturalCaptureContext(screenID:"right",visibleFrame:screenB.frame,
    desktopFrames:[screenB.frame],blockedFrames:[],isReliable:false,dragPasteboardChangeCount:7)
now=10.7
require(!host.ambientDesktopVisible(at:otherPoint) && reads == 9,"Unreliable reads invalidate exposed-desktop state")
offered=context(screenB)
require(host.ambientDesktopVisible(at:otherPoint) && reads == 10,"Unreliable metadata cannot poison later recovery")
offered=context(screenB,[windowRow(34,999,0,coveredFrame.offsetBy(dx:800,dy:0))])
host.desktopApplicationActivated()
require(!host.ambientDesktopVisible(at:otherPoint) && reads == 11,"Application activation must invalidate cached animation visibility immediately")
require(!host.overlay.isVisible && host.store.process == nil && layer.windows.allSatisfy{!$0.isVisible && $0.ignoresMouseEvents},
    "Animation visibility remains passive without a production worker")
layer.close()
print("PASS: 0.2-second cache, own-window exclusions, cross-screen refresh, clock rollback/nonfinite, read/reliability recovery, activation invalidation; NO_VISIBLE_WINDOWS_NO_WORKER")
''')


if __name__ == '__main__':
    unittest.main()
