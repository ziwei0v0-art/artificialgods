"""Optional paid artwork, pure preview selection and 159 integration; no windows or saves."""
import copy
import json
from pathlib import Path
import unittest

from tests import test_shrine_art as shrine
from tests import test_fixed_daily_actions as daily
from tests.test_attendant_art import png as attendant_png

ROOT = Path(__file__).resolve().parents[1]
COLORS = {'g1': (150,80,20,255), 'g2': (220,180,30,255), 'painted': (60,100,220,255),
          'clay': (180,80,40,255), 'bell-rest': (170,120,60,255),
          'plate-fresh': (20,220,100,255), 'plate-soft': (50,180,80,255), 'plate-ripe': (60,140,70,255),
          'base-fresh': (240,70,90,255), 'base-soft': (200,50,70,255), 'base-ripe': (160,30,50,255)}


def config():
    m = shrine.manifest()
    m['fruitVariants'] = {stage: {'file': f'base-{stage}.png'} for stage in ['fresh','soft','ripe']}
    m['appearances'] = {
        'shrine_g1': {'layers': [{'id':'shrine','file':'g1.png','bounds':[65,135,160,160]}]},
        'shrine_g2': {'layers': [{'id':'shrine','file':'g2.png','bounds':[65,135,160,160]},
                               {'id':'idol','file':'painted.png','bounds':[115,175,80,80]}]},
        'offering_plate': {'layers': [{'id':'fruit','file':'plate-fresh.png','bounds':[180,280,30,20]}],
                          'fruitVariants': {s: {'file': f'plate-{s}.png'} for s in ['fresh','soft','ripe']}},
        'incense_burner': {'layers': [{'id':'incense','file':'clay.png','bounds':[95,270,24,30]}],
                           'incenseAnchor':[0.25,0.2]},
        'bell': {'layers': [{'id':'bell','file':'bell-rest.png','bounds':[240,280,12,18]}]},
    }
    return m


def assets(scene):
    for name, color in COLORS.items():
        # The hollow corner and center also exercise transparent selection input.
        shrine.png(scene/(name+'.png'),4,4,{(x,y): color for y in range(4) for x in range(4)
                                         if (x,y) not in [(0,0),(2,2)]})


def daily_assets(scene):
    art=scene.parent/'A01'
    pixels={(x,y):(160,160,160,255) for y in range(16,44) for x in range(24)}
    pixels.update({(x,y):(255,0,255,255) for y in range(16) for x in range(4,20)})
    pixels.update({(x,y):(0,255,255,255) for y in range(44,48) for x in range(3,9)})
    pixels.update({(x,y):(0,255,0,255) for y in range(44,48) for x in range(15,21)})
    attendant_png(art/'stand.png',width=24,height=48,pixels=pixels)
    attendant_png(art/'underlay.png',width=12,height=18,
                  pixels={(x,y):(160,160,160,255) for y in range(18) for x in range(12)})
    attendant_png(art/'net.png',width=8,height=24,pixels={(3,y):(255,255,0,255) for y in range(24)})
    for name,color in daily.COLORS.items():
        w,h=(3,24) if name=='incense' else (8,16)
        attendant_png(art/(name+'.png'),width=w,height=h,
                      pixels={(x,y):color for y in range(h) for x in range(w) if name!='incense' or x==1})
    (art/'manifest.json').write_text(json.dumps({'version':1,'sampling':'nearest','stand':{'file':'stand.png'},
        'fixedWalk':{'sourceSize':[24,48],'bodyCutY':44,'legStartY':42,'legSplitX':12,'maxRootStep':3,'footLift':2},
        'fixedActions':daily.RIG}))


EXTRA=r'''
func state(_ action:String,_ serial:Int,_ elapsed:Double,_ duration:Double,_ fruit:String="fresh")->[String:Any] {
 ["action":action,"action_serial":serial,"action_elapsed":elapsed,"action_duration":duration,
  "progress":duration>0 ? elapsed/duration:0,"fruit_stage":fruit]
}
func countColor(_ rgb:[CGFloat],minimumX:CGFloat=55,maximumX:CGFloat=425)->Int {
 let rep=render(); var n=0
 for y in 130..<320 {for x in Int(minimumX)..<Int(maximumX) {
  let c=colorAt(rep,CGFloat(x)+0.5,CGFloat(y)+0.5)
  if c.alphaComponent>0.5 && abs(c.redComponent-rgb[0]/255)<0.02 && abs(c.greenComponent-rgb[1]/255)<0.02
    && abs(c.blueComponent-rgb[2]/255)<0.02 { n += 1 }
 }}; return n
}
func pressHead() {
 let rep=render()
 for y in 140..<230 {for x in 300..<400 {
  let c=colorAt(rep,CGFloat(x)+0.5,CGFloat(y)+0.5)
  if c.alphaComponent>0.9 && c.redComponent>0.95 && c.greenComponent<0.05 && c.blueComponent>0.95 {
   let event=NSEvent.mouseEvent(with:.leftMouseDown,location:point(CGFloat(x)+0.5,CGFloat(y)+0.5),modifierFlags:[],timestamp:0,windowNumber:0,context:nil,eventNumber:0,clickCount:1,pressure:1)!
   view.mouseDown(with:event); return
  }
 }}; check(false,"Visible original head needed for press")
}
'''


class DecorationArtTests(unittest.TestCase):
    def run_swift(self,body,*,scene_manifest=None,custom=None,with_daily=False):
        def setup(scene,directory):
            assets(scene)
            if with_daily: daily_assets(scene)
            if custom: custom(scene,directory)
        shrine.ShrineArtTests.run_swift(self,EXTRA+body,scene_manifest=scene_manifest or config(),custom=setup)

    def test_scene_appearance_is_a_pure_four_slot_preview_value(self):
        self.run_swift(r'''
let raw:[String:Any] = ["placed_items":["plate":"offering_plate","incense":"incense_burner","bell":"bell","shrine":"shrine_g1"],"shrine_stage":2]
let current=SceneAppearance(snapshot:raw)
let preview=current.previewing(itemID:"shrine_g2")
check(current.itemID(in:"shrine")=="shrine_g1","Preview must leave current placement unchanged")
check(preview.itemID(in:"shrine")=="shrine_g2","Preview selects the requested shrine")
for slot in ["plate","incense","bell"] { check(preview.itemID(in:slot)==current.itemID(in:slot),"Preview keeps other placed slots") }
check(preview.resetting(slot:"plate").itemID(in:"plate")==nil)
check(preview.resetting(slot:"plate").itemID(in:"shrine")=="shrine_g2")
check(current.previewing(itemID:"unknown")==current && current.resetting(slot:"unknown")==current)
check(SceneAppearance(snapshot:["placed_items":[:],"shrine_stage":2]).itemID(in:"shrine")==nil,"Explicit reset wins over legacy stage")
let legacy=SceneAppearance(snapshot:["shop":[["id":"bell","placed":true]],"shrine_stage":2])
check(legacy.itemID(in:"bell")=="bell" && legacy.itemID(in:"shrine")=="shrine_g2","Old G2-only appearance remains selectable")
for invalid:Any in ["shrine_g2",3,["shrine":true],["shrine":"bell"],["plate":"../../bad"]] {
 let parsed=SceneAppearance(snapshot:["placed_items":invalid,"shrine_stage":2])
 check(parsed==SceneAppearance(),"Malformed explicit placements must safely select base")
}
var emitted=0; view.emit={_ in emitted += 1}; view.sceneAppearance=preview
_ = render(); _ = view.shrineBounds; _ = view.accessibilityChildren()
check(emitted==0,"Preview rendering cannot transact, place, or persist")
''')

    def test_selected_layers_drive_pixels_alpha_hits_bounds_and_fruit_age(self):
        self.run_swift(r'''
let art=view.shrineArtwork!
check(view.appearanceAvailability==Set(["shrine_g1","shrine_g2","offering_plate","incense_burner","bell"]))
let base=art.resolve(appearance:SceneAppearance(),fruitStage:"fresh")
let originalIdol=base.layers.first{$0.id=="idol"}!.frame.image
view.sceneAppearance=SceneAppearance().previewing(itemID:"shrine_g1")
let g1=art.resolve(appearance:view.sceneAppearance,fruitStage:"fresh")
check(g1.layers.first{$0.id=="idol"}!.frame.image===originalIdol,"G1 must keep original static idol")
check(colorAt(render(),125,145).redComponent>0.5,"G1 must actually replace visible shrine pixels")
view.sceneAppearance=view.sceneAppearance.previewing(itemID:"shrine_g2").previewing(itemID:"offering_plate").previewing(itemID:"incense_burner").previewing(itemID:"bell")
let chosen=art.resolve(appearance:view.sceneAppearance,fruitStage:"ripe")
check(chosen.layers.count==5 && chosen.layers.filter{$0.id=="fruit"}.count==1,"One plate replaces one fruit layer")
check(chosen.layers.first{$0.id=="idol"}!.frame.image !== originalIdol,"G2 uses its original-identity painted statue layer")
check(chosen.incenseAnchor==NSPoint(x:101,y:276),"Authored censer anchor follows chosen bounds")
check(chosen.bounds==NSRect(x:65,y:135,width:187,height:165),"Accessibility union includes actual selected bell")
for (stage,rgb) in [("fresh",[20,220,100]),("soft",[50,180,80]),("ripe",[60,140,70])] {
 check(view.applyRoutine(state("idle",1,0,0,stage)),"Fruit stage receipt")
 let c=colorAt(render(),191,282)
 check(abs(c.greenComponent-CGFloat(rgb[1])/255)<0.01,"Current fruit age chooses matching plate variant")
}
for scale:CGFloat in [0.5,1,1.5] {
 view.setFrameSize(NSSize(width:370*scale,height:190*scale))
 check(view.subject(at:point(245,282))=="shrine","New visible bell participates in input")
 check(view.subject(at:point(241,281))==nil,"Transparent bell corner does not acquire rectangle input")
 let bounds=(view.accessibilityChildren()![0] as! NSAccessibilityElement).accessibilityFrame()
 check(bounds==NSRect(x:10*scale,y:20*scale,width:187*scale,height:165*scale),"Selected layer union drives scaled accessibility")
}
''')

    def test_invalid_optional_entries_fall_back_only_their_own_slot(self):
        def cases(scene,directory):
            paths=[]
            def add(name,change):
                folder=directory/name; shrine.scene_pngs(folder); assets(folder)
                m=config(); change(m,folder); (folder/'manifest.json').write_text(json.dumps(m)); paths.append(name)
            add('bad-json',lambda m,p:m['appearances'].__setitem__('shrine_g2','bad'))
            add('missing-idol',lambda m,p:m['appearances']['shrine_g2']['layers'].pop())
            add('duplicate-id',lambda m,p:m['appearances']['shrine_g2']['layers'][1].update(id='shrine'))
            add('escape',lambda m,p:m['appearances']['shrine_g2']['layers'][0].update(file='../g2.png'))
            add('bounds',lambda m,p:m['appearances']['shrine_g2']['layers'][0].update(bounds=[54,135,160,160]))
            add('crop',lambda m,p:m['appearances']['shrine_g2']['layers'][0].update(sourceRect=[0,0,500,500]))
            add('plate-stage',lambda m,p:m['appearances']['offering_plate']['fruitVariants'].pop('soft'))
            add('anchor',lambda m,p:m['appearances']['incense_burner'].update(incenseAnchor=[1.1,0.2]))
            add('extra-anchor',lambda m,p:m['appearances']['shrine_g2'].update(incenseAnchor=[-1,0.2]))
            add('extra-variants',lambda m,p:m['appearances']['shrine_g2'].update(fruitVariants={'fresh':{'file':'base-fresh.png'}}))
            add('empty',lambda m,p:shrine.png(p/'g2.png',4,4,{}))
            add('symlink',lambda m,p:((p/'g2.png').unlink(),(p/'g2.png').symlink_to(scene/'g2.png')))
            add('rgb',lambda m,p:shrine.png(p/'g2.png',4,4,{(1,1):(255,0,0,255)},alpha=False))
            add('unknown',lambda m,p:m['appearances'].__setitem__('extra_paid_item',m['appearances']['bell']))
            add('bad-container',lambda m,p:m.update(appearances='bad'))
            add('bad-base-anchor',lambda m,p:m.update(incenseAnchor=['bad']))
            (directory/'cases.json').write_text(json.dumps(paths))
        self.run_swift(r'''
let names=try! JSONDecoder().decode([String].self,from:Data(contentsOf:caseRoot.appendingPathComponent("cases.json")))
for name in names {
 let loaded=ShrineArtwork.load(from:caseRoot.appendingPathComponent(name))
 check(loaded != nil,"Bad optional data must never invalidate accepted base layers: "+name)
 let art=loaded!,selection=art.resolve(appearance:SceneAppearance().previewing(itemID:"shrine_g2").previewing(itemID:"offering_plate").previewing(itemID:"incense_burner").previewing(itemID:"bell"),fruitStage:"soft")
 if name=="unknown" {check(art.availableAppearanceIDs.count==5,"Unknown catalog ID cannot become available");continue}
 if name=="bad-base-anchor" {check(art.availableAppearanceIDs.count==5);continue}
 if name=="bad-container" {check(art.availableAppearanceIDs.isEmpty);continue}
 let broken=name=="plate-stage" ? "offering_plate":(name=="anchor" ? "incense_burner":"shrine_g2")
 check(!art.availableAppearanceIDs.contains(broken) && art.availableAppearanceIDs.count==4,"Only malformed appearance unavailable: "+name)
 check(selection.unavailableIDs==Set([broken]),"Fallback reports exactly unavailable selected item")
 let id=broken=="offering_plate" ? "fruit":(broken=="incense_burner" ? "incense":"shrine")
 let fallback=selection.layers.first{$0.id==id}!,base=art.resolve(appearance:SceneAppearance(),fruitStage:"soft").layers.first{$0.id==id}!
 check(fallback.frame.image===base.frame.image,"Bad selected appearance returns that base layer")
}
''',custom=cases)

    def test_old_g0_manifest_preserves_exact_base_and_has_no_paid_availability(self):
        self.run_swift(r'''
check(view.appearanceAvailability.isEmpty,"Old v1 four-layer manifest remains valid without optional art")
let baseline=bytes(render())
view.sceneAppearance=SceneAppearance().previewing(itemID:"shrine_g2").previewing(itemID:"offering_plate").previewing(itemID:"incense_burner").previewing(itemID:"bell")
check(bytes(render())==baseline,"Missing paid resources restore exact accepted G0")
let selection=view.shrineArtwork!.resolve(appearance:view.sceneAppearance,fruitStage:nil)
check(selection.unavailableIDs.count==4 && selection.layers.count==4)
''',scene_manifest=shrine.manifest())

    def test_offering_uses_selected_fresh_plate_and_press_freezes_held_asset(self):
        self.run_swift(r'''
view.sceneAppearance=SceneAppearance().previewing(itemID:"offering_plate")
check(view.applyRoutine(state("offer",1,0.8,8,"ripe")))
check(countColor([20,220,100],minimumX:260)>5,"Held offering uses selected fresh plate")
check(countColor([60,140,70],maximumX:260)>5,"Table keeps actual ripe plate fruit")
check(countColor([255,64,128],minimumX:260)==0,"The old fixed fruit prop is replaced")
pressHead();let held=render()
view.sceneAppearance=view.sceneAppearance.resetting(slot:"plate")
check(countColor([20,220,100],minimumX:260)>5,"Changing scene placement while pressed cannot replace the held asset")
view.cancelInteraction();view.updateAnimation(elapsed:0.2)
check(countColor([20,220,100],minimumX:260)==0 && countColor([240,70,90],minimumX:260)>5,"Release uses current base fresh plate")
check(countColor([160,30,50],maximumX:260)>5,"Restoring base never resets fruit age")
''',with_daily=True)

    def test_identical_appearance_receipts_do_not_restart_static_prop_return(self):
        self.run_swift(r'''
view.sceneAppearance=SceneAppearance().previewing(itemID:"offering_plate")
check(view.applyRoutine(state("offer",1,0.8,8,"soft")))
view.sceneAppearance=SceneAppearance()
for t:Double in [0.04,0.08,0.12] {
 view.updateAnimation(elapsed:t)
 view.sceneAppearance=SceneAppearance(snapshot:["placed_items":[:]])
}
view.updateAnimation(elapsed:0.17)
check(countColor([240,70,90],minimumX:260)>5,"Identical scene receipts must not restart the 0.16-second return")
check(countColor([20,220,100],minimumX:260)==0,"Previous plate must finish returning on original deadline")
''',with_daily=True)

    def test_selected_held_plate_shares_alpha_input_at_both_facings_and_scales(self):
        for facing in ['right','left']:
            def orientation(scene,_):
                path=scene.parent/'A01/manifest.json'
                value=json.loads(path.read_text()); value['stand']['facing']=facing
                path.write_text(json.dumps(value))
            with self.subTest(facing=facing):
                self.run_swift(r'''
view.sceneAppearance=SceneAppearance().previewing(itemID:"offering_plate")
check(view.applyRoutine(state("offer",1,0.8,8,"soft")))
for factor:CGFloat in [0.5,1,1.5] {
 view.setFrameSize(NSSize(width:370*factor,height:190*factor))
 let rep=render();var n=0,matched=0
 for y in 0..<rep.pixelsHigh {for x in 0..<rep.pixelsWide where 55+(CGFloat(x)+0.5)/factor>260 {
  let c=rep.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
  if c.alphaComponent>0.6 && abs(c.redComponent-20.0/255)<0.02 && abs(c.greenComponent-220.0/255)<0.02 && abs(c.blueComponent-100.0/255)<0.02 {
   n += 1
   let p=NSPoint(x:CGFloat(x)+0.5,y:view.bounds.height-CGFloat(y)-0.5)
   if view.subject(at:p)=="attendant" {matched += 1}
   check(view.attendantBounds.insetBy(dx:-1,dy:-1).contains(p),"Selected held plate is within actual accessible sprite union")
  }
 }}
 check(n>4 && Double(matched)/Double(n)>0.97,"Selected fresh plate uses the same facing, scale and inverse-alpha input as its pixels")
}
view.setFrameSize(NSSize(width:370,height:190))
let displayed=bytes(render())
view.sceneAppearance=view.sceneAppearance.resetting(slot:"plate")
// Compare the child region because the table changes to current placement immediately.
check(countColor([20,220,100],minimumX:260)>5,"A plate change starts at the old displayed prop")
for t:Double in [0.04,0.08,0.12,0.17] {
 view.updateAnimation(elapsed:t)
 check(countColor([20,220,100],minimumX:260)==0 || countColor([240,70,90],minimumX:260)==0,"Different plate assets never overlap during static return")
}
check(countColor([240,70,90],minimumX:260)>5,"Latest plate appears after the short return")
''',with_daily=True,custom=orientation)

    def test_bell_static_visibility_tracks_actual_pose_and_selected_censer_anchor(self):
        self.run_swift(r'''
view.sceneAppearance=SceneAppearance().previewing(itemID:"bell").previewing(itemID:"incense_burner")
check(view.applyRoutine(state("idle",1,0,0)))
check(countColor([170,120,60],maximumX:260)>5,"Equipped bell rests on table")
check(view.applyRoutine(state("bell",2,0.8,4)))
check(countColor([170,120,60],maximumX:260)==0,"Held visible bell temporarily hides static bell")
pressHead();check(view.applyRoutine(state("idle",3,0,0)))
check(countColor([170,120,60],maximumX:260)==0,"Press uses actual displayed bell despite new idle")
view.cancelInteraction()
check(countColor([170,120,60],maximumX:260)==0,"Static return still holds bell at release instant")
view.updateAnimation(elapsed:0.2)
check(countColor([170,120,60],maximumX:260)>5,"Bell returns to table after final visible prop disappears")
view.ritualStage="炉烟升起";view.updateAnimation(elapsed:0.8)
check(view.subject(at:point(101,263))=="shrine","Inserted incense input follows paid censer ash anchor")
check(view.subject(at:point(105,268)) != "shrine","Old censer anchor cannot retain displaced stick input")
''',with_daily=True)
