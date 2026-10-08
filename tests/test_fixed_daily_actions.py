"""Daily original-art gestures and ritual layers in a windowless TianmuView."""
import copy
import json
from pathlib import Path
import unittest

from tests import test_fixed_art_actions as catch_tests
from tests.test_attendant_art import png

DAILY = {
    'farSleeve': {'mask': [[16,24],[24,24],[24,40],[18,40]], 'pivot': [17,31]},
    'head': {'mask': [[0,0],[24,0],[24,23],[0,23]], 'pivot': [14,23]},
    'handCover': [7,37,3,3],
    'props': {
        'book': {'file':'book.png','height':5,'grip':[0.5,0.9]},
        'broom': {'file':'broom.png','grip':[0.5,0.30],'groundY':47.8},
        'fruit': {'file':'fruit.png','height':6.4,'grip':[0.5,0.9]},
        'bell': {'file':'bell.png','height':8.3,'grip':[0.5,0.13]},
        'incense': {'file':'incense.png','height':12,'grip':[0.5,0.92],
                    'rotation':15,'minCoreWidth':1.5},
        'paper': {'file':'paper.png','height':8.1,'grip':[0.5,0.9]},
    },
}
RIG=copy.deepcopy(catch_tests.RIG)
RIG['daily']=DAILY
COLORS={'book':(255,32,32,255),'broom':(255,128,0,255),
        'fruit':(255,64,128,255),'bell':(50,80,255,255),
        'incense':(255,255,200,255),'paper':(230,230,255,255)}

EXTRA=r'''
func propPixels(_ image:NSBitmapImageRep,_ name:String)->Set<Pixel> {
    let colors:[String:[CGFloat]]=["book":[255,32,32],"broom":[255,128,0],
        "fruit":[255,64,128],"bell":[50,80,255],"incense":[255,255,200],"paper":[230,230,255]]
    let expected=colors[name]!
    var result:Set<Pixel>=[]
    for y in 0..<image.pixelsHigh { for x in 0..<image.pixelsWide {
        let c=image.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
        if c.alphaComponent > 0.6 && abs(c.redComponent-expected[0]/255)<0.04
            && abs(c.greenComponent-expected[1]/255)<0.04 && abs(c.blueComponent-expected[2]/255)<0.04 {
            result.insert(Pixel(x:x,y:y))
        }
    }}
    return result
}
'''


class FixedDailyActionsTests(unittest.TestCase):
    def run_swift(self,body,*,rigs=None,facing='right',mutate=None):
        def assets(art,index):
            for name,color in COLORS.items():
                width,height=(12,5) if name=='book' else ((3,24) if name=='incense' else (8,16))
                pixels={(x,y):color for y in range(height) for x in range(width)
                        if name!='incense' or x==1}
                png(art/(name+'.png'),width=width,height=height,pixels=pixels)
            if mutate: mutate(art,index)
        catch_tests.FixedArtActionsTests.run_swift(self,EXTRA+body,
            rigs=rigs if rigs is not None else [RIG],facing=facing,mutate=assets)

    def test_read_draws_original_parts_with_book_then_returns_exact_stand(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,18,"read")), "Read snapshot is accepted")
check(bytes(render())==bytes(referenceStand), "Read starts as exact original stand")
view.updateAnimation(elapsed:0.8)
let reading=render()
check(propPixels(reading,"book").count>12, "Read must actually draw the supplied book")
check(view.unavailableRoutineAction==nil, "An available book fulfills read presentation")
check(view.applyRoutine(snapshot(1,18,18,"read")), "Read endpoint is accepted")
check(bytes(render())==bytes(referenceStand), "Finished read is exact original stand")
view.updateAnimation(elapsed:8)
check(bytes(render())==bytes(referenceStand), "Finished read does not loop")
''')

    def test_adding_daily_keeps_the_verified_catch_pixels_and_input(self):
        self.run_swift(r'''
let catchOnly=AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[2]))!
for t:Double in [0,0.3,0.8,1.3,2.2,2.7,3] {
    let old=TianmuView(frame:view.frame); old.attendantArtwork=catchOnly; old.persistLegacyFrame=false
    let expanded=TianmuView(frame:view.frame); expanded.attendantArtwork=artwork; expanded.persistLegacyFrame=false
    check(old.applyRoutine(catchSnapshot(1,t)) && expanded.applyRoutine(catchSnapshot(1,t)), "Catch receipts")
    check(bytes(render(old))==bytes(render(expanded)), "Adding daily must preserve the previously verified catch pixels")
    if t==0.8 {
        check(pixels(render(expanded),"head")==pixels(referenceStand,"head"), "Catch keeps original unmoved head")
        let net=netPixels(render(expanded))
        check(!net.isEmpty, "Catch keeps its supplied net")
        check(net.allSatisfy { expanded.subject(at:NSPoint(x:CGFloat($0.x)+0.5,y:expanded.bounds.height-CGFloat($0.y)-0.5))=="attendant" }, "Catch net alpha remains clickable with daily loaded")
    }
}
''',rigs=[RIG,catch_tests.RIG])

    def test_all_service_gestures_have_visible_middle_and_exact_endpoints(self):
        self.run_swift(r'''
let durations:[String:Double]=["read":18,"sweep":12,"practice":45,"offer":8,"bell":4,"rest":60]
let names=["read":"book","sweep":"broom","offer":"fruit","bell":"bell"]
for action in ["read","sweep","practice","offer","bell","rest"] {
    let target=TianmuView(frame:view.frame); target.attendantArtwork=artwork; target.persistLegacyFrame=false
    var emitted=0; target.emit={ _ in emitted += 1 }
    let duration=durations[action]!
    check(target.applyRoutine(snapshot(1,0,duration,action)), "Daily snapshot accepted")
    check(bytes(render(target))==bytes(referenceStand), "Each daily action begins at the complete original stand")
    check(target.applyRoutine(snapshot(1,0.8,duration,action)), "Daily middle accepted")
    let active=render(target)
    check(bytes(active) != bytes(referenceStand), "Each available daily gesture has visible motion")
    if let name=names[action] { check(propPixels(active,name).count>3, "Daily action displays its corresponding prop") }
    check(target.unavailableRoutineAction==nil, "Available action is not reported missing")
    let originalHead=pixels(referenceStand,"head").count,currentHead=pixels(active,"head").count
    check(abs(Double(currentHead-originalHead))/Double(originalHead)<0.12, "Head remains a rigid original part with similar area")
    for shoe in ["cyan","green"] {
        let visible=pixels(active,shoe),original=pixels(referenceStand,shoe)
        if action=="sweep" {
            // The foreground grass bundle can cover part of the near shoe.
            check(visible.isSubset(of:original) && visible.count>original.count/2, "Broom may occlude a planted shoe but cannot move or replace it")
        } else {
            check(visible==original, "Daily head tilt cannot move the original planted shoes: " + action + "/" + shoe)
        }
    }
    check(target.applyRoutine(snapshot(1,duration,duration,action)), "Daily end accepted")
    check(bytes(render(target))==bytes(referenceStand), "Each service endpoint is the complete original stand")
    check(emitted==0, "Sampling and drawing gestures cannot emit business actions")
}
''')

    def test_midjoin_duplicates_stale_feed_and_prop_changes_do_not_replay(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,7.2,18,"read")), "Join read in middle")
let reading=bytes(render())
check(!propPixels(render(),"book").isEmpty, "Midjoin does not restart the take-book entry")
check(view.applyRoutine(snapshot(1,7.2,18,"read")), "Duplicate read")
check(bytes(render())==reading, "Duplicate does not restart gesture")
check(!view.applyRoutine(snapshot(0,8,18,"read")), "Old serial rejected")
check(view.applyRoutine(snapshot(2,1,4,"bell")), "Switch prop")
check(bytes(render())==reading, "Switch starts from the actual displayed old pose")
for t:Double in [0.04,0.08,0.12,0.17] {
    view.updateAnimation(elapsed:t)
    let image=render()
    check(propPixels(image,"book").isEmpty || propPixels(image,"bell").isEmpty, "Different held props never overlap")
}
check(propPixels(render(),"book").isEmpty && !propPixels(render(),"bell").isEmpty, "Only newest prop remains after static return")
view.updateAnimation(elapsed:1)
let stopped=bytes(render())
view.updateAnimation(elapsed:8)
check(bytes(render())==stopped, "Stale daily feed advances at most one second")
check(view.applyRoutine(catchSnapshot(3,0.8)), "Switch to catch")
view.updateAnimation(elapsed:8.2)
check(!netPixels(render()).isEmpty && propPixels(render(),"bell").isEmpty, "Net replaces bell without residual prop")
let caught=bytes(render())
check(view.applyRoutine(snapshot(4,7.2,18,"read")), "Return to current read")
check(bytes(render())==caught, "Catch to daily transition starts at exact displayed catch")
view.updateAnimation(elapsed:8.4)
check(netPixels(render()).isEmpty && !propPixels(render(),"book").isEmpty, "Current read appears without replaying its entry")
''')

    def test_bad_independent_props_disable_only_their_dependent_action(self):
        rigs=[]
        for name in ['book','broom','fruit','bell','incense','paper']:
            rig=copy.deepcopy(RIG); rig['daily']['props'][name]['file']='missing.png'; rigs.append(rig)
        malformed=copy.deepcopy(RIG); malformed['daily']['props']['book']='bad'; rigs.append(malformed)
        bad_net=copy.deepcopy(RIG); bad_net['catch']['net']['height']='bad'; rigs.append(bad_net)
        bad_daily=copy.deepcopy(RIG); bad_daily['daily']='bad'; rigs.append(bad_daily)
        for ground in [-1,1e12]:
            grounded_book=copy.deepcopy(RIG); grounded_book['daily']['props']['book']['groundY']=ground; rigs.append(grounded_book)
        self.run_swift(r'''
let names=["book","broom","fruit","bell","incense","paper","book","net","daily","book","book"]
let actions=["book":"read","broom":"sweep","fruit":"offer","bell":"bell","incense":"incense","paper":"paper"]
for (index,path) in CommandLine.arguments.dropFirst().enumerated() {
    let loaded=AttendantArtwork.load(from:URL(fileURLWithPath:path))!
    check(loaded.hasWalkMotion, "Bad optional daily data cannot discard fixed walk")
    let broken=names[index]
    if broken=="daily" {
        check(!loaded.hasDailyMotion && loaded.hasCatchMotion, "Malformed daily preserves catch")
    } else if broken=="net" {
        check(!loaded.hasCatchMotion && loaded.canPresent("read"), "Bad net cannot poison shared source rig or daily props")
    } else {
        check(loaded.hasCatchMotion && loaded.hasDailyMotion, "Bad independent prop leaves other art intact")
        for (name,action) in actions {
            check(loaded.canPresent(action)==(name != broken), "Only action depending on broken prop becomes unavailable")
        }
        check(loaded.canPresent("practice") && loaded.canPresent("rest") && loaded.canPresent("response"), "Prop-free daily poses survive")
    }
}
''',rigs=rigs)

    def test_all_props_share_rotated_alpha_input_both_facings_and_scales(self):
        for facing in ['right','left']:
            with self.subTest(facing=facing):
                self.run_swift(r'''
for factor:CGFloat in [0.5,1,1.5] {
    for (action,name,duration) in [("read","book",18.0),("sweep","broom",12.0),("offer","fruit",8.0),("bell","bell",4.0),("incense","incense",2.0),("paper","paper",2.0)] {
        let target=TianmuView(frame:NSRect(x:0,y:0,width:370*factor,height:190*factor))
        target.attendantArtwork=artwork; target.persistLegacyFrame=false
        if action=="incense" || action=="paper" {
            check(target.applyRoutine(snapshot(1,0,0,"idle")), "Idle before ritual")
            target.ritualStage=action=="incense" ? "取香行礼":"呈出签纸"
            target.updateAnimation(elapsed:0.8)
        } else { check(target.applyRoutine(snapshot(1,0.8,duration,action)), "Daily middle") }
        let image=render(target),prop=propPixels(image,name)
        check(!prop.isEmpty, "Every prop is visible in real view at each scale")
        let matched=prop.filter { target.subject(at:NSPoint(x:CGFloat($0.x)+0.5,y:target.bounds.height-CGFloat($0.y)-0.5))=="attendant" }.count
        check(Double(matched)/Double(prop.count)>=0.97, "Prop alpha follows rotation and facing in the actual input surface")
        for pixel in prop {
            check(target.attendantBounds.insetBy(dx:-1,dy:-1).contains(NSPoint(x:CGFloat(pixel.x)+0.5,y:target.bounds.height-CGFloat(pixel.y)-0.5)), "Accessibility bounds contain visible props")
        }
        assertHitsMatchPixels(target)
    }
    let frame=artwork.propFrame("incense")!,core=artwork.propCoreBounds("incense")!
    let unit=CGFloat(170)/48*factor,width=artwork.propWidth("incense",height:12,unitToView:unit)!
    check(core.width/CGFloat(frame.width)*width*unit>=1.5-0.000001, "Incense core stays at least 1.5 final view points wide")
}
''',facing=facing)

    def test_invalid_daily_geometry_preserves_verified_catch_and_walk(self):
        rigs=[]
        for path,value in [(['farSleeve','pivot'],[-1,31]),(['head','pivot'],[14,49]),
                           (['head','mask'],[[0,0],[24,0],[24,50],[0,50]]),
                           (['farSleeve','mask'],[[0,0],[1,1],[2,2]]),
                           (['handCover'],[7,37,-3,3]),(['handCover'],[23,47,3,3]),
                           (['props'],'bad')]:
            rig=copy.deepcopy(RIG); target=rig['daily']
            for key in path[:-1]: target=target[key]
            target[path[-1]]=value; rigs.append(rig)
        self.run_swift(r'''
for path in CommandLine.arguments.dropFirst() {
    let loaded=AttendantArtwork.load(from:URL(fileURLWithPath:path))!
    check(!loaded.hasDailyMotion && loaded.hasCatchMotion && loaded.hasWalkMotion, "Invalid daily geometry is isolated from existing art")
    let target=TianmuView(frame:view.frame); target.attendantArtwork=loaded; target.persistLegacyFrame=false
    check(target.applyRoutine(snapshot(1,0.8,18,"read")), "Unsupported daily snapshot retained")
    check(bytes(render(target))==bytes(referenceStand) && target.unavailableRoutineAction=="read", "Invalid daily preserves exact stand fallback")
    check(target.applyRoutine(catchSnapshot(2,0.8)), "Existing catch remains available")
    check(!netPixels(render(target)).isEmpty, "Invalid daily cannot hide the existing net")
}
''',rigs=rigs)

    def test_thin_incense_remains_visible_at_fractional_pixel_position(self):
        def thin_source(art,index):
            # Reproduce the formal asset's high-alpha core and very weak border.
            # A 3-pixel toy image hides the fractional-position downsampling bug.
            pixels={(x,y):(255,255,200,254 if 2<=x<34 and 2<=y<1098 else 3)
                    for y in range(1100) for x in range(36)}
            png(art/'incense.png',width=36,height=1100,pixels=pixels)
        scene=json.dumps(str(catch_tests.ROOT/'assets/production/scene'),ensure_ascii=False)
        body=r'''
let target=TianmuView(frame:NSRect(x:0,y:0,width:555,height:285))
target.attendantArtwork=artwork; target.persistLegacyFrame=false
target.shrineArtwork=ShrineArtwork.load(from:URL(fileURLWithPath:SCENE_PATH))!
check(target.applyRoutine(snapshot(1,0,0,"idle")), "Idle before smoke")
target.ritualStage="炉烟升起"; target.updateAnimation(elapsed:0.8)
let image=render(target)
let censer=target.shrineArtwork!.layer(id:"incense")!.bounds
let factor:CGFloat=1.5,anchorX=(censer.midX-TianmuView.sceneCanvas.minX)*factor
let anchorY=(censer.minY+censer.height*0.24-TianmuView.sceneCanvas.minY)*factor
let top=Int(anchorY-18*factor)+1,bottom=Int((censer.minY-TianmuView.sceneCanvas.minY)*factor)-1
var visibleRows=0
for y in top...bottom {
    var visible=false
    for x in Int(anchorX-2)...Int(anchorX+2) {
        let c=image.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
        if c.redComponent>0.8 && c.greenComponent>0.8 && c.blueComponent>0.55 { visible=true }
    }
    if visible { visibleRows += 1 }
}
check(visibleRows>=Int(Double(bottom-top+1)*0.8), "Thin incense must be visibly continuous, not merely have a 1.5pt mathematical box")
'''.replace('SCENE_PATH',scene)
        self.run_swift(body,mutate=thin_source)
