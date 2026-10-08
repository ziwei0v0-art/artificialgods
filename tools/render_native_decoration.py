"""Review real decoration layers and linked actions through offscreen TianmuView."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / 'assets/incoming/decoration_20261001'
OUT = ROOT / 'evidence/1.0/160-native-decoration'
SHARED = ROOT / 'tools/render_native_fixed_actions.py'
# Common crops retain two source pixels around the union of alpha > 16 cores.
# Images remain original byte copies; the loader crops only in memory.
CROPS = {
    'plate-fresh-v01-original.png': [371, 190, 825, 640],
    'plate-soft-v01-original.png': [371, 190, 825, 640],
    'plate-ripe-v01-original.png': [371, 190, 825, 640],
    'clay-incense-v01-original.png': [133, 256, 1109, 701],
    'shrine-g1-v01-original.png': [56, 106, 1143, 1103],
    'shrine-g2-v01-original.png': [56, 106, 1143, 1103],
    'idol-g2-v01-original.png': [82, 163, 1052, 1046],
    'bell-v01-original.png': [362, 287, 459, 756],
}


def appearance_config(base):
    layers = {item['id']: item for item in base['layers']}
    def layer(kind, filename, bounds=None):
        return {'id': kind, 'file': filename, 'sourceRect': CROPS[filename],
                'bounds': bounds if bounds is not None else layers[kind]['bounds']}
    plate = {'layers': [layer('fruit', 'plate-fresh-v01-original.png')],
             'fruitVariants': {stage: {'file': f'plate-{stage}-v01-original.png',
                                      'sourceRect': CROPS[f'plate-{stage}-v01-original.png']}
                               for stage in ('fresh', 'soft', 'ripe')}}
    return {'incenseAnchor': [0.5, 0.24], 'appearances': {
        'offering_plate': plate,
        'incense_burner': {'layers': [layer('incense', 'clay-incense-v01-original.png')],
                           'incenseAnchor': [0.5, 0.24]},
        'bell': {'layers': [layer('bell', 'bell-v01-original.png', [191.5, 268, 16*459/756, 16])]},
        'shrine_g1': {'layers': [layer('shrine', 'shrine-g1-v01-original.png')]},
        'shrine_g2': {'layers': [layer('shrine', 'shrine-g2-v01-original.png'),
                                layer('idol', 'idol-g2-v01-original.png')]},
    }}


def referenced_files(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'file' and isinstance(item, str):
                yield item
            else:
                yield from referenced_files(item)
    elif isinstance(value, list):
        for item in value:
            yield from referenced_files(item)


def extract_swift(path):
    tree = ast.parse(path.read_text())
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'SWIFT' for target in node.targets))


READ_ONLY_REVIEW = r'''
extension TianmuView {
    func decorationReviewSelection()->ShrineArtwork.Selection { selectedScene()! }
    func decorationReviewRect(_ design:NSRect)->NSRect { rect(design.minX,design.minY,design.width,design.height) }
    func decorationReviewDrawLayer(_ id:String) {
        if id=="runtime-incense" {sceneIncenseSprite()?.draw(designToView:designToViewTransform);return}
        if id=="runtime-smoke" {drawRitualSmoke();return}
        if let layer=selectedScene()?.layers.first(where:{$0.id==id}) {
            layer.frame.draw(in:decorationReviewRect(layer.bounds),mirrored:false)
        }
    }
    func decorationReviewState()->[String:Any] {
        let selected=selectedScene()!,display=resolvedDisplayPose(),gesture=display.gesture
        let fresh=selected.freshOfferingFrame
        let actualFruit=attendantSprites()?.filter{$0.frame.image === fresh.image} ?? []
        var value:[String:Any]=["layer_ids":selected.layers.map(\.id),"unavailable_ids":selected.unavailableIDs.sorted(),
            "display_prop":gesture.prop ?? "","prop_amount":Double(gesture.propAmount),
            "held_bell_visible":gesture.prop=="bell" && gesture.propAmount>0.000001,
            "static_bell_visible":selected.layers.contains{$0.id=="bell"},
            "held_fruit_uses_selected_fresh":actualFruit.count==1,
            "incense_anchor_design":[Double(selected.incenseAnchor.x),Double(selected.incenseAnchor.y)],
            "scene_incense_amount":Double(display.scene.incense),"scene_smoke_amount":Double(display.scene.smoke)]
        if let sprite=sceneIncenseSprite(),let core=attendantArtwork?.propCoreBounds("incense") {
            let bottom=NSPoint(x:core.midX,y:core.maxY).applying(sprite.pixelToDesign)
            value["incense_anchor_error"]=Double(hypot(bottom.x-selected.incenseAnchor.x,bottom.y-selected.incenseAnchor.y))
        }
        return value
    }
}
'''

SWIFT = extract_swift(SHARED).split('struct ReviewRow {')[0] + r'''
struct Outfit {
    let stage:Int,plate:Bool,fruit:String,censer:Bool,bell:Bool
    var key:String {"g\(stage)-p\(plate ? 1:0)-\(fruit)-c\(censer ? 1:0)-b\(bell ? 1:0)"}
    var appearance:SceneAppearance {
        var placed=[String:String]()
        if stage>0 {placed["shrine"]="shrine_g\(stage)"}
        if plate {placed["plate"]="offering_plate"};if censer {placed["incense"]="incense_burner"};if bell {placed["bell"]="bell"}
        return SceneAppearance(snapshot:["placed_items":placed,"shrine_stage":stage])
    }
}
let itemIDs=Set(["offering_plate","incense_burner","bell","shrine_g1","shrine_g2"])
precondition(shrine.availableAppearanceIDs==itemIDs,"All five appearances must resolve to supplied original PNGs")
var states=[[String:Any]](),hits=[[String:Any]](),actionChecks=[[String:Any]](),pixelChecks=[[String:Any]](),boundaries=[[String:Any]]()
var allEvents=[[String:Any]]()
func json(_ data:Any,_ name:String) {try! JSONSerialization.data(withJSONObject:data,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent(name))}
func outfitView(_ outfit:Outfit,_ scale:CGFloat,_ direction:String="right")->(TianmuView,Double,Int) {
    let(v,start,serial)=prepared(128,direction)
    v.setFrameSize(NSSize(width:TianmuView.sceneCanvas.width*scale,height:TianmuView.sceneCanvas.height*scale))
    v.sceneAppearance=outfit.appearance
    var state=snapshot("idle",serial,0,0);state["fruit_stage"]=outfit.fruit
    precondition(v.applyRoutine(state));v.updateAnimation(elapsed:start+0.2)
    v.emit={allEvents.append($0)}
    return(v,start+0.2,serial+1)
}
func receipt(_ v:TianmuView,_ action:String,_ serial:Int,_ elapsed:Double,_ duration:Double,_ clock:Double,_ fruit:String) {
    v.updateAnimation(elapsed:clock);var state=snapshot(action,serial,elapsed,duration);state["fruit_stage"]=fruit
    precondition(v.applyRoutine(state))
}
func layerRaw(_ v:TianmuView,_ id:String)->NSBitmapImageRep {
    bitmap(Int(ceil(v.bounds.width)),Int(ceil(v.bounds.height))){v.decorationReviewDrawLayer(id)}
}
func layerPixels(_ v:TianmuView,_ id:String,_ label:String)->[String:Any] {
    let b=layerRaw(v,id),d=b.bitmapData!,edges=alphaEdges(b)
    var strong=0,core=0,maxAlpha=0
    for y in 0..<b.pixelsHigh {for x in 0..<b.pixelsWide {let a=Int(d[y*b.bytesPerRow+x*4+3]);maxAlpha=max(maxAlpha,a);if a>128{strong+=1};if a>16{core+=1}}}
    let row:[String:Any]=["case":label,"layer":id,"alpha_max":maxAlpha,"alpha_gt128":strong,"alpha_gt16":core,"bbox":edges.any]
    pixelChecks.append(row);return row
}
func captureState(_ v:TianmuView,_ label:String,_ scale:CGFloat,_ elapsed:Double=0) {
    var row=v.decorationReviewState();row["case"]=label;row["scale"]=Double(scale);row["elapsed"]=elapsed
    states.append(row)
    precondition((row["unavailable_ids"] as! [String]).isEmpty)
    if (row["held_bell_visible"] as! Bool) {precondition(!(row["static_bell_visible"] as! Bool),"The visible held bell must hide the tabletop bell")}
    if let error=row["incense_anchor_error"] as? Double {precondition(error<0.000001,"Incense bottom missed selected censer anchor")}
    let pad=4,w=Int(ceil(v.bounds.width)),h=Int(ceil(v.bounds.height))
    let extended=bitmap(w+pad*2,h+pad*2){
        NSGraphicsContext.current!.cgContext.translateBy(x:CGFloat(pad),y:CGFloat(pad))
        v.draw(v.bounds)
    },d=extended.bitmapData!
    var outside=0,maxAlpha=0
    for y in 0..<extended.pixelsHigh {for x in 0..<extended.pixelsWide where x<pad || x>=w+pad || y<pad || y>=h+pad {
        let a=Int(d[y*extended.bytesPerRow+x*4+3]);maxAlpha=max(maxAlpha,a);if a>16{outside+=1}
    }}
    boundaries.append(["case":label,"scale":Double(scale),"elapsed":elapsed,
        "outside_canvas_alpha_gt16_pixels":outside,"outside_canvas_alpha_max":maxAlpha,
        "actual_canvas_size":[w,h],"inspection_padding_px":pad])
}
func auditHit(_ v:TianmuView,_ outfit:Outfit,_ scale:CGFloat) {
    let selected=v.decorationReviewSelection(),children=v.accessibilityChildren()!
    let accessible=(children[0] as! NSAccessibilityElement).accessibilityFrame()
    precondition(accessible==v.shrineBounds && (children[2] as! NSAccessibilityElement).accessibilityFrame()==v.shrineBounds,
                 "Accessibility and menu frame must use selected shrine bounds")
    precondition(v.shrineBounds==v.decorationReviewRect(selected.bounds),"Static shrine bounds must match selected layers")
    for layer in selected.layers {
        let b=layerRaw(v,layer.id),d=b.bitmapData!
        var candidates=[NSPoint]()
        for y in 0..<b.pixelsHigh {for x in 0..<b.pixelsWide where d[y*b.bytesPerRow+x*4+3]>220 {
            candidates.append(NSPoint(x:CGFloat(x)+0.5,y:CGFloat(b.pixelsHigh-y)-0.5))
        }}
        let step=max(1,candidates.count/80),sampled=Array(candidates.enumerated().filter{$0.offset%step==0}.prefix(80).map(\.element))
        let count=sampled.filter{v.subject(at:$0) != nil}.count
        let ratio=sampled.isEmpty ? 0:Double(count)/Double(sampled.count)
        hits.append(["case":outfit.key,"scale":Double(scale),"layer":layer.id,"sampled_solid_pixels":sampled.count,
                     "reachable_solid_pixels":count,"reachability":ratio,"accessibility_matches":true])
        precondition(!sampled.isEmpty,"Selected layer has no solid pixels at product scale: \(layer.id)")
        // The smallest product view is 74x38; subpixel boundaries can differ by
        // one raster pixel, so log all ratios and require a usable visible target.
        precondition(count>0,"A visible selected layer cannot be reached through alpha input: \(layer.id)")
    }
    let full=rawRender(v),d=full.bitmapData!;var empty=0,blocked=0,safeEmpty=0,safeBlocked=0,edgeSamples=[[String:Any]]()
    for y in stride(from:0,to:full.pixelsHigh,by:5) {for x in stride(from:0,to:full.pixelsWide,by:5) {
        if d[y*full.bytesPerRow+x*4+3]==0 {
            empty+=1
            let target=v.subject(at:NSPoint(x:CGFloat(x)+0.5,y:CGFloat(full.pixelsHigh-y)-0.5))
            let safe=(max(0,y-1)...min(full.pixelsHigh-1,y+1)).allSatisfy{yy in
                (max(0,x-1)...min(full.pixelsWide-1,x+1)).allSatisfy{xx in d[yy*full.bytesPerRow+xx*4+3]==0}
            }
            if safe {safeEmpty+=1;if target != nil {safeBlocked+=1}}
            if let target {blocked+=1;edgeSamples.append(["pixel":[x,y],"subject":target,"transparent_3x3":safe])}
        }
    }}
    hits.append(["case":outfit.key,"scale":Double(scale),"layer":"transparent-scene-grid","empty_samples":empty,
        "unexpected_hits":blocked,"edge_samples":edgeSamples,"clear_3x3_samples":safeEmpty,"clear_3x3_hits":safeBlocked])
    precondition(safeBlocked==0,"A transparent area away from raster edges must pass input through")
}
func flatSave(_ raw:NSBitmapImageRep,_ stem:String) {
    for(theme,bg,_)in backgrounds {png(composite(NSBitmapImageRep(cgImage:raw.cgImage!),bg),"\(stem)-\(theme).png")}
}
func board(_ rows:[(String,CGImage)],_ columns:Int,_ name:String) {
    let cw=rows.map{$0.1.width}.max()!+14,ch=rows.map{$0.1.height}.max()!+32
    let height=((rows.count+columns-1)/columns)*ch+30,width=columns*cw+12
    for(theme,bg,ink)in backgrounds {
        let b=bitmap(width,height){
            bg.setFill();NSRect(x:0,y:0,width:width,height:height).fill()
            ("实际 TianmuView · \(name)" as NSString).draw(at:NSPoint(x:10,y:height-20),withAttributes:[.font:NSFont.systemFont(ofSize:11),.foregroundColor:ink])
            for(i,row)in rows.enumerated(){let x=CGFloat(8+(i%columns)*cw),y=CGFloat(8+((rows.count-1)/columns-i/columns)*ch)
                NSImage(cgImage:row.1,size:NSSize(width:row.1.width,height:row.1.height)).draw(in:NSRect(x:x,y:y+18,width:CGFloat(row.1.width),height:CGFloat(row.1.height)))
                (row.0 as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:9),.foregroundColor:ink])
            }
        };png(b,"\(name)-\(theme).png")
    }
}
var outfits=[Outfit]()
for stage in 0...2 {for plate in [false,true] {for fruit in ["fresh","soft","ripe"] {for censer in [false,true] {for bell in [false,true] {
    outfits.append(Outfit(stage:stage,plate:plate,fruit:fruit,censer:censer,bell:bell))
}}}}}
precondition(outfits.count==72)
var overview=[(String,CGImage)](),stills=[String:CGImage]()
for outfit in outfits {
    for scale:CGFloat in [0.2,0.75,1.5] {
        let(v,_,_)=outfitView(outfit,scale),raw=rawRender(v),selected=v.decorationReviewSelection()
        precondition(selected.layers.filter{$0.id=="fruit"}.count==1,"A plate variant replaces, never stacks onto, the fruit layer")
        precondition(selected.layers.contains{$0.id=="bell"}==outfit.bell)
        precondition(v.routinePresentation.snapshot?.fruitStage==outfit.fruit,"Appearance cannot reset fruit age")
        if outfit.stage<2 {precondition(selected.layers.first{$0.id=="idol"}!.frame.image === shrine.layer(id:"idol")!.frame.image,"G0/G1 preserve the exact original static idol")}
        captureState(v,outfit.key,scale);auditHit(v,outfit,scale)
        let key="\(outfit.key)-\(Int(scale*100))pct";stills[key]=raw.cgImage!;flatSave(raw,"static-\(key)")
        if scale==0.75 {overview.append((outfit.key,raw.cgImage!))}
    }
    // Preview is a pure copy and changes only its selected slot.
    for item in itemIDs {
        let current=outfit.appearance,preview=current.previewing(itemID:item)
        let slot=item=="offering_plate" ? "plate":item=="incense_burner" ? "incense":item=="bell" ? "bell":"shrine"
        for other in SceneAppearance.slots where other != slot {precondition(current.itemID(in:other)==preview.itemID(in:other))}
        precondition(outfit.appearance==current && preview.itemID(in:slot)==item)
    }
}
board(overview,6,"overview-72")
for pct in [20,75,150] {
    let stageRows=(0...2).map{stage in ("G\(stage) · original plate",stills["g\(stage)-p0-fresh-c0-b0-\(pct)pct"]!)}
    board(stageRows,3,"growth-\(pct)pct")
    let plates=[false,true].flatMap{plate in ["fresh","soft","ripe"].map{fruit in ("\(plate ? "青瓷":"白盘") / \(fruit)",stills["g2-p\(plate ? 1:0)-\(fruit)-c1-b1-\(pct)pct"]!)}}
    board(plates,3,"plates-six-\(pct)pct")
    let props=[false,true].flatMap{censer in [false,true].map{bell in ("\(censer ? "暖陶":"灰炉") / bell \(bell)",stills["g2-p1-soft-c\(censer ? 1:0)-b\(bell ? 1:0)-\(pct)pct"]!)}}
    board(props,2,"tableware-\(pct)pct")
}

func movie(_ v:TianmuView,_ name:String,_ times:[Int],_ at:(Int)->Void) {
    var destinations=[CGImageDestination](),contacts=[(String,CGImage)]()
    for(theme,_,_)in backgrounds {
        let d=CGImageDestinationCreateWithURL(output.appendingPathComponent("\(name)-\(theme).gif") as CFURL,"com.compuserve.gif" as CFString,times.count,nil)!
        CGImageDestinationSetProperties(d,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary);destinations.append(d)
    }
    for(index,ms)in times.enumerated(){at(ms);let raw=rawRender(v)
        captureState(v,name,CGFloat(v.bounds.width/TianmuView.sceneCanvas.width),Double(ms)/1000)
        let delay=index+1<times.count ? Double(times[index+1]-ms)/1000:0.4
        for(i,entry)in backgrounds.enumerated(){let flat=composite(NSBitmapImageRep(cgImage:raw.cgImage!),entry.1)
            CGImageDestinationAddImage(destinations[i],flat.cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:max(0.02,delay),kCGImagePropertyGIFUnclampedDelayTime:max(0.02,delay)]] as CFDictionary)
        }
        if [0,800,2000,2800,4000,4800,5000,5500,5580,5720,6220,8220].contains(ms) {contacts.append(("\(Double(ms)/1000)s",raw.cgImage!))}
    }
    destinations.forEach{precondition(CGImageDestinationFinalize($0))};board(contacts,4,"contact-\(name)")
}
for plate in [false,true] {for fruit in ["fresh","soft","ripe"] {for direction in ["left","right"] {
    let outfit=Outfit(stage:2,plate:plate,fruit:fruit,censer:true,bell:true)
    let(v,start,serial)=outfitView(outfit,0.75,direction),name="offer-p\(plate ? 1:0)-\(fruit)-\(direction)"
    receipt(v,"offer",serial,0,8,start,fruit)
    let times=Array(Set([0,80,160,350,800,1000,2000,2800,3000,4000,4800,5000,6000,7000,7800,8000,8080,8160,8220])).sorted()
    movie(v,name,times){ms in
        if ms>0 && ms%1000==0 && ms<8000 {receipt(v,"offer",serial,Double(ms)/1000,8,start+Double(ms)/1000,fruit)}
        if ms==8000 {receipt(v,"offer",serial,8,8,start+8,fruit);receipt(v,"idle",serial+1,0,0,start+8,fruit)}
        v.updateAnimation(elapsed:start+Double(ms)/1000)
        if ms==800 {precondition(v.decorationReviewState()["held_fruit_uses_selected_fresh"] as! Bool,"Offer must hold current plate's fresh image");flatSave(rawRender(v),"\(name)-middle")}
        precondition(v.routinePresentation.snapshot?.fruitStage==fruit)
    }
    actionChecks.append(["case":name,"result":"PASS","fresh_offering_matches":true,"table_fruit_stage":fruit])
}}}
for censer in [false,true] {for scale:CGFloat in [0.2,0.75,1.5] {for direction in ["left","right"] {
    let outfit=Outfit(stage:2,plate:true,fruit:"soft",censer:censer,bell:true)
    let(v,start,_)=outfitView(outfit,scale,direction),name="ritual-c\(censer ? 1:0)-\(Int(scale*100))pct-\(direction)"
    v.ritualStage="取香行礼"
    let times=[0,80,160,350,800,1200,1800,2000,2080,2200,2800,3500,4000,4080,4200,4800,5500,6000,6080,6160,6220]
    movie(v,name,times){ms in
        v.updateAnimation(elapsed:start+Double(ms)/1000)
        if ms==2000 {v.ritualStage="炉烟升起"};if ms==4000 {v.ritualStage="呈出签纸"};if ms==6000 {v.ritualStage=nil}
        if ms==2800 {
            precondition((layerPixels(v,"runtime-incense",name)["alpha_gt128"] as! Int)>0)
            precondition((layerPixels(v,"runtime-smoke",name)["alpha_gt16"] as! Int)>0)
            flatSave(rawRender(v),"\(name)-smoke-middle")
        }
    }
    actionChecks.append(["case":name,"result":"PASS","censer_anchor_follows_selection":true])
}}}
for scale:CGFloat in [0.2,0.75,1.5] {for direction in ["left","right"] {
    let outfit=Outfit(stage:2,plate:true,fruit:"ripe",censer:true,bell:true)
    let(v,start,serial)=outfitView(outfit,scale,direction),baseline=bytes(rawRender(v)),head=v.attendantBounds
    let name="bell-hold-\(Int(scale*100))pct-\(direction)";receipt(v,"bell",serial,0,4,start,"ripe")
    let times=[0,80,160,350,800,1000,2000,3000,4000,4800,5000,5500,5580,5660,5720]
    var held:Data?
    movie(v,name,times){ms in
        v.updateAnimation(elapsed:start+Double(ms)/1000)
        if ms==800 {v.mouseDown(with:mouse(headPoint(v,head),start+0.8));held=bytes(rawRender(v))}
        if [1000,2000,3000,4000].contains(ms) {receipt(v,"bell",serial,Double(ms)/1000,4,start+Double(ms)/1000,"ripe")}
        if ms==4000 {receipt(v,"idle",serial+1,0,0,start+4,"ripe")}
        if ms==5500 {v.cancelInteraction();precondition(bytes(rawRender(v))==held!,"Release must preserve held first frame")}
        if let held,ms>=800 && ms<5500 {precondition(bytes(rawRender(v))==held,"Press must freeze actual bell and selected tabletop")}
        if ms==5720 {precondition(bytes(rawRender(v))==baseline,"Expired bell must settle to original dressed stand")}
    }
    actionChecks.append(["case":name,"result":"PASS","single_visible_bell":true,"pressed_expiry_no_replay":true])
}}
let business=allEvents.filter{($0["type"] as? String) != "mode"};precondition(business.isEmpty,"Offscreen decoration cannot transact or save")
json(states,"states.json");json(hits,"alpha-accessibility.json");json(actionChecks,"action-checks.json");json(pixelChecks,"incense-pixel-checks.json")
json(boundaries,"frame-bounds.json")
let violations=boundaries.filter{($0["outside_canvas_alpha_gt16_pixels"] as! Int)>0}
json(violations,"boundary-violations.json")
precondition(violations.isEmpty,"Visible scene pixels exceed actual canvas; inspect boundary-violations.json")
json(["static_outfits":72,"static_product_views":216,"preview_value_checks":360,"action_sequences":actionChecks.count,
      "state_frames":states.count,"business_events":business.count,"ui_mode_events":allEvents.count-business.count],"checks.json")
print("NATIVE_DECORATION_PASS: 72 outfits / 216 product views / 360 pure previews / \(actionChecks.count) linked action sequences / \(states.count) states; actual selected layer pixels, alpha input and accessibility; no window, worker or save")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-art', action='store_true', help='Read an already enabled production scene manifest directly.')
    parser.add_argument('--compile-only', action='store_true', help='Compile the isolated view helper without running it.')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare persistent byte-copy scene fixtures without compiling or running.')
    args = parser.parse_args()
    output = ROOT/'evidence/1.0'/('160-native-decoration-production' if args.production_art else '160-native-decoration')
    output.mkdir(parents=True, exist_ok=True)
    scene, character = ROOT/'assets/production/scene', ROOT/'assets/production/A01'
    manifest_path = scene/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    sources = {filename: scene/filename for filename in referenced_files(manifest)}
    if not args.production_art:
        appearances = appearance_config(manifest);manifest.update(appearances)
        for filename in CROPS:
            sources[filename] = character/filename if filename=='bell-v01-original.png' else INCOMING/filename
        (output/'appearance-candidate.json').write_text(json.dumps(appearances,ensure_ascii=False,indent=2)+'\n')
    assert set(manifest['appearances'])=={'offering_plate','incense_burner','bell','shrine_g1','shrine_g2'}
    character_manifest = character/'manifest.json'
    character_data=json.loads(character_manifest.read_text())
    watched={manifest_path,character_manifest,*sources.values(),*(character/f for f in referenced_files(character_data))}
    digests={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(watched)}
    if args.production_art: assets=scene
    else:
        assets=output/'fixture-scene';assets.mkdir(exist_ok=True)
        for filename in set(referenced_files(manifest)):
            assert Path(filename).name==filename
            shutil.copy2(sources[filename],assets/filename)
        (assets/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    if args.prepare_only:
        print(f'FIXTURE_PREPARED: {assets}');return
    native=(ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0]
    with tempfile.TemporaryDirectory(prefix='tianmu-native-decoration-') as folder:
        work=Path(folder)
        (work/'Scene.swift').write_text(native+READ_ONLY_REVIEW);(work/'main.swift').write_text(SWIFT)
        subprocess.run(['swiftc','-framework','AppKit','-framework','ImageIO',str(work/'Scene.swift'),str(work/'main.swift'),'-o',str(work/'render')],check=True)
        if args.compile_only:
            print('COMPILE_ONLY_PASS; executable not run');return
        subprocess.run([str(work/'render'),str(character),str(assets),str(output)],check=True)
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in digests.items())
    (output/'fixture-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (output/'fixture.json').write_text(json.dumps({'art_mode':'production' if args.production_art else 'original byte copies and temporary appearance manifest',
        'source_manifest':str(manifest_path),'source_sha256':digests,'native_prefix_sha256':hashlib.sha256(native.encode()).hexdigest(),
        'shared_helper_sha256':hashlib.sha256(SHARED.read_bytes()).hexdigest(),'scene_canvas_unchanged':True,'renderer':'actual TianmuView and selected formal PNG layers',
        'source_images_modified':False,'no_window':True,'no_worker':True,'no_save_access':True,'business_transport_connected':False},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
