"""Real collection snapshots, production artwork and hidden compact card geometry."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let output = URL(fileURLWithPath:CommandLine.arguments[1])
func require(_ value:@autoclosure()->Bool,_ message:String) {
    if !value() { fputs("FAIL: \(message)\n",stderr); exit(1) }
}
let store = Store()
let shop:[[String:Any]] = [
 ["id":"offering_plate","name":"供果盘","slot":"plate","price":12,"owned":false,"placed":false,"can_buy":true],
 ["id":"incense_burner","name":"陶香炉","slot":"incense","price":24,"owned":true,"placed":true,"can_buy":false],
 ["id":"bell","name":"小铜铃","slot":"bell","price":60,"owned":true,"placed":false,"can_buy":false],
 ["id":"shrine_g1","name":"木龛","slot":"shrine","price":120,"owned":false,"placed":false,"can_buy":true],
 ["id":"shrine_g2","name":"彩塑神龛","slot":"shrine","price":360,"owned":false,"placed":false,"can_buy":false,"unavailable_reason":"需先拥有木龛"]]
let discoveries:[[String:Any]] = [
 ["color":"普通褐色","found":true,"date":"2026-10-04","description":"快照中的普通褐色说明"],
 ["color":"中褐色","found":true,"date":NSNull(),"description":"快照中的中褐色说明"],
 ["color":"深褐色","found":false,"date":"不应展示的日期","description":"尚未解锁的说明"],
 ["color":"白色","found":false,"date":NSNull(),"description":"尚未解锁的说明"]]
store.state = ["coins":500,"shop":shop,"placed_items":["incense":"incense_burner"],"discoveries":discoveries]
let frozen = NSDictionary(dictionary:store.state)
var commands:[(String,[String:Any])] = []
var completion:((Bool)->Void)?
store.commandSink = { action,values,done in commands.append((action,values)); completion=done }

let entries = CollectionInsectEntry.entries(snapshot:store.state)
require(entries.count == 4,"Cards must come from the backend's four discovery rows")
require(entries[0].found && entries[0].discoveryText.contains("2026-10-04"),"Found date must come from the snapshot")
require(entries[0].explanation == "快照中的普通褐色说明","Description must come from the snapshot")
require(entries[1].discoveryText.contains("未记录"),"A legacy missing date must not be invented")
require(!entries[2].found && entries[2].discoveryText == "尚未发现","A date cannot turn an unknown insect into a discovery")
require(!entries[2].explanation.contains("尚未解锁的说明"),"Unknown cards must keep the discovery detail locked")
require(CollectionInsectEntry.entries(snapshot:[:]).isEmpty,"An empty snapshot must not fabricate a catalog")
require(CollectionInsectEntry.entries(snapshot:["discoveries":[["color":"新种","found":true]]]).isEmpty,
        "An unsupported color must not silently render as an ordinary brown fly")

let artwork = CollectionArtwork.shared
let expectedLayers:[String:[String]] = ["offering_plate":["fruit"],"incense_burner":["incense"],"bell":["bell"],
    "shrine_g1":["shrine","idol"],"shrine_g2":["shrine","idol"]]
func bitmap(_ image:NSImage)->NSBitmapImageRep { NSBitmapImageRep(data:image.tiffRepresentation!)! }
func pixelHash(_ image:NSImage)->String {
    let rep=bitmap(image), data=Data(bytes:rep.bitmapData!,count:rep.bytesPerRow*rep.pixelsHigh)
    return String(data.reduce(UInt64(14695981039346656037)) { ($0 ^ UInt64($1)) &* 1099511628211 },radix:16)
}
var itemHashes=Set<String>()
for id in ["offering_plate","incense_burner","bell","shrine_g1","shrine_g2"] {
    require(artwork.layers(for:id).map(\.id) == expectedLayers[id]!,"Each card must display its own production layers: \(id)")
    require(artwork.image(for:id) != nil,"Missing production item thumbnail: \(id)")
    let image=artwork.image(for:id)!, rep=bitmap(image)
    var visible=0
    for y in 0..<rep.pixelsHigh { for x in 0..<rep.pixelsWide {
        if rep.colorAt(x:x,y:y)!.alphaComponent > 0.1 { visible += 1 }
    }}
    require(visible > 1000,"A real equipment card cannot render an empty or tiny placeholder")
    itemHashes.insert(pixelHash(image))
    try! rep.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(id+".png"))
}
require(itemHashes.count == 5,"Different equipment must not collapse to one generic symbol")
require(artwork.layers(for:"offering_plate").first!.frame.width == 825,"Plate must use the authored production crop")
require(artwork.layers(for:"bell").first!.frame.width == 459,"Bell must use the authored production crop")
require(artwork.image(for:"missing") == nil,"Missing artwork must not be replaced with another item")
let missing=CollectionArtwork(shrineArtwork:nil)
require(missing.image(for:"bell") == nil,"Missing resources must remain unavailable")
require(missing.currentImage(for:"神龛",snapshot:store.state) == nil,"A missing current shrine cannot use another artwork")
require(artwork.currentImage(for:"unknown",snapshot:store.state) == nil,"Unsupported category must not borrow known artwork")
require(artwork.layers(for:"shrine_g0").map(\.id) == ["shrine","idol"],"The initial shrine uses the original actual base layers")
let baseShrine=artwork.image(for:"shrine_g0")!
require(pixelHash(artwork.currentImage(for:"神龛",snapshot:store.state)!) == pixelHash(baseShrine),
        "A newly equipped base shrine must not show a paid appearance")
var changed=store.state, ownedRows=shop
ownedRows[3]["owned"]=true;ownedRows[4]["owned"]=true;ownedRows[4]["placed"]=true
changed["shop"]=ownedRows;changed["placed_items"]=["shrine":"shrine_g1"]
require(pixelHash(artwork.currentImage(for:"神龛",snapshot:changed)!) == pixelHash(artwork.image(for:"shrine_g1")!),
        "The current root thumbnail must follow actual G1 even with owned/stale-placed G2")
changed["placed_items"]=["shrine":"shrine_g2"]
require(pixelHash(artwork.currentImage(for:"神龛",snapshot:changed)!) == pixelHash(artwork.image(for:"shrine_g2")!),
        "An actual G2 receipt must update the current root thumbnail")
changed["placed_items"]=[String:String]()
require(pixelHash(artwork.currentImage(for:"神龛",snapshot:changed)!) == pixelHash(baseShrine),
        "An explicit empty equipment receipt must restore the G0 root thumbnail")
let utensilsWithoutBell=pixelHash(artwork.currentImage(for:"供具",snapshot:changed)!)
changed["placed_items"]=["bell":"bell"]
require(pixelHash(artwork.currentImage(for:"供具",snapshot:changed)!) != utensilsWithoutBell,
        "Equipping the bell must change the actual supply-category composition")
let shrineArtwork=ShrineArtwork.shared!
let equipped=SceneAppearance(snapshot:["placed_items":["plate":"offering_plate","incense":"incense_burner","bell":"bell"]])
let selected=shrineArtwork.resolve(appearance:equipped,fruitStage:"fresh")
let bell=selected.layers.first{$0.id=="bell"}!,plate=selected.layers.first{$0.id=="fruit"}!,censer=selected.layers.first{$0.id=="incense"}!
require(!bell.bounds.intersects(plate.bounds) && !bell.bounds.intersects(censer.bounds),"The tabletop bell must not overlap the plate or censer")
require(TianmuView.sceneCanvas.contains(bell.bounds),"The bell must remain inside the scene canvas")
require(!shrineArtwork.resolve(appearance:equipped,fruitStage:"fresh",heldBellVisible:true).layers.contains{$0.id=="bell"},
        "A held bell must hide its table copy")
require(!shrineArtwork.resolve(appearance:equipped.resetting(slot:"bell"),fruitStage:"fresh").layers.contains{$0.id=="bell"},
        "Removing the bell must remove its actual scene layer")

var insectHashes=Set<String>()
for entry in entries {
    let image=CollectionArtwork.insectImage(color:entry.id)!
    insectHashes.insert(pixelHash(image))
    try! bitmap(image).representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(entry.id+".png"))
}
require(insectHashes.count == 4,"Four backend colors must retain distinct dorsal fly renderings")
require(CollectionArtwork.insectImage(color:"新种") == nil,"Unknown art must not pretend to be an existing body color")

// The page uses these exact controls. Preview, cancellation and failed receipts
// must preserve the authoritative snapshot even with the compact presentation.
store.shopControls.choose("offering_plate")
require(commands.isEmpty && frozen.isEqual(to:store.state),"Opening a detail must not buy or place")
store.shopControls.dismissPreview()
require(commands.isEmpty && frozen.isEqual(to:store.state),"Closing a detail must not change state")
store.shopControls.choose("offering_plate"); store.shopControls.buySelected(); store.shopControls.buySelected()
require(commands.count == 1 && commands[0].0 == "buy" && commands[0].1["item"] as? String == "offering_plate",
        "The compact page must retain the existing one-in-flight purchase and exact backend ID")
completion?(false)
require(!store.shopControls.selectedOwned && frozen.isEqual(to:store.state),"A failed receipt must not create ownership")
store.shopControls.dismissPreview()

func scrolls(_ view:NSView)->[NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(scrolls)
}
let insectKeys=Set(entries.map { "insect-"+$0.id })
let categoryCases:[(String?,Set<String>)]=[
 (nil,Set(["group-神龛","group-供具"])),
 ("神龛",Set(["item-shrine_g1","item-shrine_g2"])),
 ("供具",Set(["item-offering_plate","item-incense_burner","item-bell"]))]
for (width,height,padding) in [(380,450,18),(400,450,18),(420,450,18),(420,540,16)] {
 for (category,equipmentKeys) in categoryCases {
    if let category {store.shopControls.openCategory(category)} else {store.shopControls.showCollectionRoot()}
    qaCollectionFrames=[:]
    let view=NSHostingView(rootView:ScrollView { CollectionPage(store:store) }
        .padding(CGFloat(padding)).background(paper).foregroundStyle(ink).coordinateSpace(name:"collection-root"))
    let window=NSWindow(contentRect:NSRect(x:0,y:0,width:width,height:height),styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false; window.contentView=view
    view.frame=window.contentLayoutRect
    view.layoutSubtreeIfNeeded(); RunLoop.current.run(until:Date().addingTimeInterval(0.12)); view.layoutSubtreeIfNeeded()
    let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:rep)
    try! rep.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("page-\(category ?? "root")-\(width)-\(height).png"))
    let expected=equipmentKeys.union(insectKeys)
    require(Set(qaCollectionFrames.keys) == expected,
            "Root must show only 2 categories; shrine 2 and utensils 3 exact items, with 4 insects. Actual: \(qaCollectionFrames.keys.sorted())")
    for (key,rect) in qaCollectionFrames {
        require(view.bounds.contains(rect),"Compact page clips a card at width \(width): \(key) \(rect)")
        require(rect.width >= 60 && rect.height >= 60,"Visual cards need usable pointer targets")
    }
    require(scrolls(view).count == 1,"Combined page must share the panel's single scroll container")
    require(!window.isVisible && !window.isKeyWindow && !window.isMainWindow,"The collection verification must stay offscreen")
    require(frozen.isEqual(to:store.state),"Opening any category must not change ownership or placement")
    window.contentView=nil; window.close()
 }
}
for (id,actionKey) in [("offering_plate","buy"),("incense_burner","place"),("bell","place"),("shrine_g2","buy")] {
    qaCollectionFrames=[:]
    store.shopControls.choose(id)
    let view=NSHostingView(rootView:ScrollView { CollectionPage(store:store) }
        .padding(16).background(paper).foregroundStyle(ink).coordinateSpace(name:"collection-root"))
    // Match the production 420x540 panel after its compact header and footer.
    let window=NSWindow(contentRect:NSRect(x:0,y:0,width:420,height:430),styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false; window.contentView=view; view.frame=window.contentLayoutRect
    func layout() {
        view.layoutSubtreeIfNeeded(); RunLoop.current.run(until:Date().addingTimeInterval(0.1)); view.layoutSubtreeIfNeeded()
    }
    layout()
    let scroll=scrolls(view)[0], clip=scroll.contentView, document=scroll.documentView!
    clip.scroll(to:NSPoint(x:0,y:max(0,document.bounds.height-clip.bounds.height)))
    scroll.reflectScrolledClipView(clip); layout()
    let viewport=view.convert(clip.bounds,from:clip)
    require(qaCollectionFrames[actionKey] != nil,"Expanded detail is missing its backend action")
    require(viewport.contains(qaCollectionFrames[actionKey]!),"Expanded detail action must be reachable by scrolling")
    let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:rep)
    try! rep.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("detail-\(id).png"))
    require(!window.isVisible && frozen.isEqual(to:store.state),"Opening and scrolling detail cannot alter the game")
    window.contentView=nil; window.close(); store.shopControls.dismissPreview()
}
require(store.process == nil && store.input == nil && store.output == nil,"No worker or real save may be touched")
print("PASS: production root 2 categories, shrine 2 / utensils 3 exact items across 4 viewports, 4 reachable detail actions, current G0/G1/G2 and supply thumbnail receipts, bell separation, 5 production thumbnails, 4 dorsal colors, preview/failure isolation; NO_VISIBLE_WINDOWS_NO_WORKER_NO_SAVE")
'''

PROBE = r'''
var qaCollectionFrames:[String:CGRect] = [:]
struct QACollectionProbe:View {
    let key:String
    var body:some View {
        GeometryReader { geometry in
            Color.clear.onAppear { qaCollectionFrames[key]=geometry.frame(in:.named("collection-root")) }
                .onChange(of:geometry.frame(in:.named("collection-root"))) { qaCollectionFrames[key]=$0 }
        }
    }
}
'''


class CollectionCardTests(unittest.TestCase):
    def test_real_resources_snapshot_states_and_compact_geometry(self):
        output = ROOT/'evidence/1.0/171-collection/production-cards'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='tianmu-collection-') as directory:
            folder = Path(directory)
            production = {name:(ROOT/name).read_text() for name in ['native/v1/main.swift','native/OverlayHost.swift']}
            host = production['native/v1/main.swift'].split('let application = NSApplication.shared')[0]
            scene = production['native/OverlayHost.swift'].split('final class Host:')[0]
            (folder/'main.swift').write_text(host+PROBE+HARNESS)
            (folder/'Scene.swift').write_text(scene)
            names = ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift',
                     'TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
            for name in names:
                source = (ROOT/'native/v1'/name).read_text()
                production['native/v1/'+name] = source
                if name == 'LeisureViews.swift':
                    for needle, key in [
                        ('.accessibilityIdentifier("collection-group-\\(group)")','"group-" + group'),
                        ('.accessibilityIdentifier("collection-item-\\(item.itemKey)")','"item-" + item.itemKey'),
                        ('.accessibilityIdentifier("collection-insect-\\(entry.id)")','"insect-" + entry.id'),
                        ('.accessibilityIdentifier("collection-buy")','"buy"'),
                        ('.accessibilityIdentifier("collection-place")','"place"')]:
                        self.assertEqual(source.count(needle), 1, 'Production probe location must remain unique: '+needle)
                        source = source.replace(needle, needle+'.background(QACollectionProbe(key:'+key+'))')
                (folder/name).write_text(source)
            shutil.copytree(ROOT/'assets/production/scene',folder/'art/scene')
            production['assets/production/scene/manifest.json'] = (folder/'art/scene/manifest.json').read_text()
            (output/'source-hashes.json').write_text(json.dumps({name:hashlib.sha256(value.encode()).hexdigest()
                for name,value in production.items()},indent=2)+'\n')
            build = subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),
                *(str(folder/name) for name in names),str(folder/'main.swift'),'-o',str(folder/'check')],
                capture_output=True,text=True,timeout=120)
            (output/'compile.txt').write_text(build.stdout+build.stderr)
            self.assertEqual(build.returncode,0,build.stderr)
            result = subprocess.run([str(folder/'check'),str(output)],capture_output=True,text=True,timeout=40)
            (output/'run.txt').write_text(result.stdout+result.stderr)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())
