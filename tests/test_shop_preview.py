"""Real native shop intents and receipts without a worker or visible window."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let store = Store()
let allIDs:Set<String> = ["offering_plate","incense_burner","bell","shrine_g1","shrine_g2"]
let controls = ShopControls(store:store, availableArtwork:allIDs)
func row(_ id:String,_ slot:String,_ price:Int,_ owned:Bool = false,_ placed:Bool = false,_ buy:Bool = true)->[String:Any] {
 ["id":id,"name":id,"slot":slot,"price":price,"owned":owned,"placed":placed,"can_buy":buy]
}
func initial()->[String:Any] {
 ["coins":500,"placed_items":["incense":"incense_burner"],"shop":[
 row("offering_plate","plate",12),row("incense_burner","incense",24,true,true,false),
 row("bell","bell",60,true),row("shrine_g1","shrine",120),row("shrine_g2","shrine",360,false,false,false)]]
}
store.state = initial()
var commands:[(String,[String:Any])] = []
var done:((Bool)->Void)?
store.commandSink = { action, values, completion in commands.append((action,values)); done=completion }
let before = NSDictionary(dictionary:store.state)
func cornerAlpha(_ view:TianmuView)->CGFloat {
 let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:370,pixelsHigh:190,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
 view.draw(view.bounds);NSGraphicsContext.restoreGraphicsState()
 return bitmap.colorAt(x:2,y:2)!.alphaComponent
}
switch CommandLine.arguments[1] {

case "hierarchy":
 assert(ShopControls.categories == ["神龛","供具"])
 assert(!controls.showingCategory && controls.selectedID == nil)
 controls.openCategory("神龛")
 assert(controls.showingCategory && controls.category == "神龛")
 assert(controls.items.map(\.itemKey) == ["shrine_g1","shrine_g2"])
 controls.openCategory("供具")
 assert(controls.items.map(\.itemKey) == ["offering_plate","incense_burner","bell"])
 controls.choose("shrine_g2")
 assert(controls.showingCategory && controls.category == "神龛" && controls.selectedID == "shrine_g2")
 controls.showCollectionRoot()
 assert(!controls.showingCategory && controls.selectedID == nil)
 controls.openCategory("unknown")
 assert(!controls.showingCategory && controls.selectedID == nil)
 controls.chooseCategory("神前")
 assert(controls.category == "神龛" && controls.showingCategory && controls.selectedID == nil)
 controls.openCategory("供具");controls.choose("offering_plate");controls.buySelected()
 controls.openCategory("神龛");controls.showCollectionRoot();controls.choose("bell")
 assert(controls.showingCategory && controls.category == "供具" && controls.selectedID == "offering_plate",
        "An in-flight purchase must not retarget the category or selected item")
 done?(false)
 controls.showCollectionRoot()
 assert(!controls.showingCategory && !controls.selectedOwned && before.isEqual(to:store.state))
case "current_style":
 assert(controls.currentShrineID == nil && controls.currentShrineName == "初始神龛")
 var latest=initial(), shop=initial()["shop"] as! [[String:Any]]
 shop[3]["owned"]=true;shop[4]["owned"]=true;shop[4]["placed"]=true
 latest["shop"]=shop;latest["placed_items"]=["shrine":"shrine_g1","bell":"bell"]
 store.state=latest
 assert(controls.currentShrineID == "shrine_g1" && controls.currentShrineName == "shrine_g1",
        "Root category must reflect equipped G1, not the owned or stale-row-placed G2")
 assert(controls.currentUtensilsName == "bell")
 controls.choose("shrine_g2")
 assert(controls.previewAppearance.itemID(in:"shrine") == "shrine_g2" && controls.currentShrineID == "shrine_g1",
        "Previewing another shrine must not change the root card's actual equipment")
 latest["placed_items"]=[String:String]();store.state=latest
 assert(controls.currentShrineID == nil && controls.currentShrineName == "初始神龛",
        "Explicit empty placement must win over stale shop flags")
 assert(controls.currentUtensilsName == "初始供盘与香炉")
 shop.append(row("future_outfit","outfit",10,true,true));latest["shop"]=shop;store.state=latest
 controls.openCategory("供具")
 assert(controls.items.map(\.itemKey) == ["offering_plate","incense_burner","bell"])
 assert(commands.isEmpty)
case "utensil_toggle":
 store.commandSink=nil
 var requests:[[String:Any]]=[];store.requestSink={requests.append($0)}
 for (item,slot) in [("offering_plate","plate"),("incense_burner","incense"),("bell","bell")] {
  var equipped=initial(),shop=initial()["shop"] as! [[String:Any]]
  for index in 0..<3 {shop[index]["owned"]=true;shop[index]["can_buy"]=false}
  equipped["shop"]=shop;equipped["placed_items"]=["plate":"offering_plate","incense":"incense_burner","bell":"bell"]
  store.state=equipped;controls.choose(item)
  assert(controls.selectedOwned && controls.selectedPlaced)
  assert(controls.placementActionTitle == (item == "bell" ? "收起":"恢复初始"))
  let start=requests.count;controls.placeSelected();controls.placeSelected()
  assert(requests.count == start+1 && requests.last!["action"] as? String == "place" && requests.last!["item"] as? String == item)
  assert(controls.selectedPlaced && store.coins == 500,"Sending must not optimistically remove equipment")
  let failedID=requests.last!["id"] as! Int
  store.receive(try! JSONSerialization.data(withJSONObject:["id":failedID,"ok":false,"state":equipped])+Data([10]))
  assert(controls.selectedPlaced && !controls.isSubmitting,"A failed removal preserves placement")
  controls.placeSelected()
  let id=requests.last!["id"] as! Int
  var removed=equipped,placed=equipped["placed_items"] as! [String:String];placed.removeValue(forKey:slot);removed["placed_items"]=placed
  store.receive(try! JSONSerialization.data(withJSONObject:["id":id,"ok":true,"state":removed])+Data([10]))
  assert(controls.selectedOwned && !controls.selectedPlaced && controls.placementActionTitle == "摆上" && store.coins == 500)
  for (otherSlot,otherItem) in placed {assert(SceneAppearance(snapshot:store.state).itemID(in:otherSlot) == otherItem)}
 }
case "preview":
 store.state["coins"] = 0
 let frozen = NSDictionary(dictionary:store.state)
 controls.choose("offering_plate")
 assert(controls.selectedID == "offering_plate")
 assert(controls.previewAppearance.itemID(in:"plate") == "offering_plate")
 assert(controls.previewAppearance.itemID(in:"incense") == "incense_burner")
 assert(SceneAppearance(snapshot:store.state).itemID(in:"plate") == nil)
 controls.previewInitial()
 assert(controls.previewAppearance.itemID(in:"plate") == nil)
 assert(controls.previewAppearance.itemID(in:"incense") == "incense_burner")
 assert(commands.isEmpty && frozen.isEqual(to:store.state))
 controls.dismissPreview()
 assert(controls.selectedID == nil && controls.previewAppearance == SceneAppearance(snapshot:store.state))
case "snapshot":
 controls.choose("offering_plate")
 var latest=store.state; latest["placed_items"]=["bell":"bell","shrine":"shrine_g1"]
 store.receive(try! JSONSerialization.data(withJSONObject:["state":latest])+Data([10]))
 controls.refresh()
 assert(controls.previewAppearance.itemID(in:"plate") == "offering_plate")
 assert(controls.previewAppearance.itemID(in:"incense") == nil)
 assert(controls.previewAppearance.itemID(in:"bell") == "bell")
 assert(SceneAppearance(snapshot:store.state).itemID(in:"plate") == nil && commands.isEmpty)
 controls.chooseCategory("神前")
 assert(controls.selectedID == nil && controls.previewAppearance == SceneAppearance(snapshot:latest))
case "purchase":
 controls.choose("offering_plate"); controls.buySelected(); controls.buySelected(); controls.placeSelected()
 assert(commands.count == 1 && commands[0].0 == "buy" && commands[0].1["item"] as? String == "offering_plate")
 assert(controls.isSubmitting && before.isEqual(to:store.state))
 done?(false)
 assert(!controls.isSubmitting && !controls.selectedOwned && controls.selectedID == "offering_plate")
 controls.buySelected(); done?(true)
 assert(commands.count == 2 && !controls.selectedOwned, "A completion alone must not fabricate ownership")
case "receipt":
 store.commandSink = nil
 var requests:[[String:Any]]=[]; store.requestSink={requests.append($0)}
 controls.choose("offering_plate"); controls.buySelected()
 let id=requests.last!["id"] as! Int
 var purchased=store.state; purchased["coins"]=488
 var shop=purchased["shop"] as! [[String:Any]];shop[0]["owned"]=true;shop[0]["can_buy"]=false;purchased["shop"]=shop
 store.receive(try! JSONSerialization.data(withJSONObject:["id":id,"ok":true,"state":purchased])+Data([10]))
 assert(controls.selectedOwned && !controls.selectedPlaced && !controls.isSubmitting)
 assert(SceneAppearance(snapshot:store.state).itemID(in:"plate") == nil && requests.count == 1)
 controls.placeSelected();controls.placeSelected()
 assert(requests.count == 2 && requests.last!["action"] as? String == "place")
 let placeID=requests.last!["id"] as! Int
 var placed=purchased; placed["placed_items"]=["plate":"offering_plate","incense":"incense_burner"]
 store.receive(try! JSONSerialization.data(withJSONObject:["id":placeID,"ok":true,"state":placed])+Data([10]))
 assert(controls.selectedPlaced && store.coins == 488)
 controls.placeSelected()
 assert(requests.count == 3 && requests.last!["action"] as? String == "place")
case "g2":
 controls.choose("shrine_g2"); assert(!controls.canBuySelected); controls.buySelected();assert(commands.isEmpty)
 var old=store.state;var shop=old["shop"] as! [[String:Any]];shop[4]["owned"]=true;old["shop"]=shop
 store.state=old;controls.refresh()
 assert(controls.selectedOwned && !controls.selectedPlaced)
 controls.placeSelected();assert(commands.count == 1 && commands[0].0 == "place")
case "unavailable":
 let missing = ShopControls(store:store, availableArtwork:[])
 missing.choose("offering_plate");assert(!missing.selectedArtworkAvailable && !missing.canBuySelected)
 missing.buySelected();assert(commands.isEmpty)
 missing.choose("bell");missing.placeSelected();assert(commands.isEmpty)
 missing.choose("incense_burner");missing.placeSelected()
 assert(commands.count == 1 && commands[0].0 == "place", "Missing art must not prevent removing a currently equipped item")
case "mapping":
 let actual=TianmuView(frame:NSRect(origin:.zero,size:TianmuView.sceneCanvas.size))
 let preview=TianmuView(frame:actual.frame)
 controls.choose("shrine_g2")
 applySceneState(store.state,to:actual)
 ScenePreview(store:store,appearanceOverride:controls.previewAppearance).apply(to:preview)
 assert(actual.sceneAppearance == SceneAppearance(snapshot:store.state))
 assert(preview.sceneAppearance == controls.previewAppearance && actual.sceneAppearance != preview.sceneAppearance)
 assert(commands.isEmpty && before.isEqual(to:store.state))
case "static_preview":
 let actual=TianmuView(frame:NSRect(origin:.zero,size:TianmuView.sceneCanvas.size))
 let preview=TianmuView(frame:actual.frame)
 controls.choose("offering_plate")
 for (index,fruit) in ["fresh","soft","ripe"].enumerated() {
  store.state["routine"]=["action":"offer","action_serial":10,"action_duration":8,
      "action_elapsed":Double(index+1),"progress":Double(index+1)/8,"fruit_stage":fruit]
  applySceneState(store.state,to:actual)
  ScenePreview(store:store,appearanceOverride:controls.previewAppearance,staticAppearancePreview:true).apply(to:preview)
  assert(actual.routinePresentation.snapshot?.action == "offer")
  assert(preview.routinePresentation.snapshot?.action == "idle" && preview.routinePresentation.snapshot?.fruitStage == fruit)
  assert(preview.sceneAppearance.itemID(in:"plate") == "offering_plate")
  assert(actual.sceneAppearance.itemID(in:"plate") == nil)
 }
 assert(commands.isEmpty)
 assert(cornerAlpha(preview)==1 && cornerAlpha(actual)==0, "Shop paints opaque paper without changing the transparent desktop")
default: fatalError("Unknown case")
}
assert(store.process == nil && store.input == nil && store.output == nil)
print("PASS: \(CommandLine.arguments[1]); NO_WINDOWS_NO_WORKER_NO_SAVE")
'''

class ShopPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='tianmu-shop-preview-')
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        output = ROOT/'evidence/1.0/171-collection/production-shop'
        output.mkdir(parents=True, exist_ok=True)
        sources = {name: (ROOT/name).read_text() for name in [
            'native/v1/main.swift', 'native/OverlayHost.swift',
            *('native/v1/'+name for name in ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift',
                'InsectArtwork.swift','TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift'])]}
        source = sources['native/v1/main.swift'].split('let application = NSApplication.shared')[0]
        (folder/'main.swift').write_text(source+HARNESS)
        (folder/'Scene.swift').write_text(sources['native/OverlayHost.swift'].split('final class Host:')[0])
        names = ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift',
                 'TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
        for name in names:
            (folder/name).write_text(sources['native/v1/'+name])
        (output/'source-hashes.json').write_text(json.dumps({name:hashlib.sha256(value.encode()).hexdigest()
            for name,value in sources.items()},indent=2)+'\n')
        cls.binary = folder/'check'
        build = subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),
            *(str(folder/name) for name in names), str(folder/'main.swift'),'-o',str(cls.binary)],
            capture_output=True,text=True,timeout=120)
        (output/'compile.txt').write_text(build.stdout+build.stderr)
        if build.returncode: raise AssertionError(build.stderr)

def install_case(name):
    def test(self):
        result=subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout.strip())
    setattr(ShopPreviewTests,'test_'+name,test)

for name in ['preview','snapshot','purchase','receipt','g2','unavailable','mapping','static_preview','hierarchy','current_style','utensil_toggle']:
    install_case(name)
