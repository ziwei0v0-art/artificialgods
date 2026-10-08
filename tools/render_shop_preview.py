"""Render the real shop panel with isolated data and byte-copied formal artwork.

Windows are created only as unshown layout hosts. The helper never starts a
worker or loads/saves game progress. Hidden SwiftUI accessibility is attempted
once; unavailable AX is recorded without making a window visible.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SWIFT = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let fixtureURL = URL(fileURLWithPath:CommandLine.arguments[1])
let output = URL(fileURLWithPath:CommandLine.arguments[2])
let fixtures = try! JSONSerialization.jsonObject(with:Data(contentsOf:fixtureURL)) as! [String:Any]
let cases = fixtures["cases"] as! [[String:Any]]
let expectedArt:Set<String> = ["shrine_g1","shrine_g2","offering_plate","incense_burner","bell"]
precondition(app.windows.allSatisfy{!$0.isVisible})

func scrolls(_ view:NSView) -> [NSScrollView] {
    (view as? NSScrollView).map{[$0]} ?? view.subviews.flatMap{scrolls($0)}
}
func sceneViews(_ view:NSView) -> [TianmuView] {
    (view as? TianmuView).map{[$0]} ?? view.subviews.flatMap{sceneViews($0)}
}
func invalidate(_ view:NSView) {
    view.needsDisplay = true
    view.subviews.forEach{invalidate($0)}
}
func settle(_ view:NSView) {
    for _ in 0..<3 {
        view.layoutSubtreeIfNeeded()
        let warm = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
        view.cacheDisplay(in:view.bounds,to:warm)
        RunLoop.current.run(until:Date().addingTimeInterval(0.06))
    }
    view.layoutSubtreeIfNeeded()
}
func receive(_ store:Store, _ reply:[String:Any]) {
    store.receive(try! JSONSerialization.data(withJSONObject:reply)+Data([10]))
}
func panel(_ store:Store,_ width:Int,_ height:Int) -> (NSWindow,NSHostingView<PanelView>) {
    let presentation = PresentationState(); presentation.open("装扮")
    let view = NSHostingView(rootView:PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{}))
    let frame = NSRect(x:0,y:0,width:width,height:height)
    let window = NSWindow(contentRect:frame,styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed = false
    window.ignoresMouseEvents = true
    window.contentView = view; view.frame = frame
    settle(view)
    return (window,view)
}
func guardIsolation(_ store:Store,_ window:NSWindow) {
    precondition(!window.isVisible && !window.isKeyWindow && !window.isMainWindow)
    precondition(app.windows.allSatisfy{!$0.isVisible})
    precondition(store.process == nil && store.input == nil && store.output == nil)
}
@discardableResult
func capture(_ view:NSView,_ name:String) -> [String:Any] {
    invalidate(view)
    let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    let data = bitmap.representation(using:.png,properties:[:])!
    precondition(data.count > 4096, "The actual panel cannot be empty")
    try! data.write(to:output.appendingPathComponent(name+".png"))
    return ["file":name+".png","pixels":[bitmap.pixelsWide,bitmap.pixelsHigh],"bytes":data.count]
}
var checks:[[String:Any]] = []
// Keep one real hosting tree alive so reviewing additional sizes does not
// repeatedly decode the same original PNGs or recreate the SwiftUI scene.
let renderingStore = Store()
renderingStore.commandSink = {action,_,_ in fatalError("Rendering must not transact: \(action)")}
renderingStore.requestSink = {_ in fatalError("Rendering must not request a worker")}
receive(renderingStore,["phase":"ready","ok":true,"state":cases[0]["state"]!])
renderingStore.shopControls.choose(cases[0]["selected"] as! String)
let (renderingWindow,renderingView) = panel(renderingStore,460,520)
let loadedScenes = sceneViews(renderingView)
precondition(loadedScenes.count == 1 && loadedScenes[0].appearanceAvailability == expectedArt)
precondition(loadedScenes[0].attendantArtwork != nil, "The accepted production attendant must load")
for sample in cases {
    let name = sample["name"] as! String
    let state = sample["state"] as! [String:Any]
    let selected = sample["selected"] as! String
    receive(renderingStore,["ok":true,"state":state])
    renderingStore.message = "离屏样例 · 不代表真实铜钱 · 不读写存档"
    renderingStore.shopControls.choose(selected)
    precondition(renderingStore.shopControls.selectedID == selected)
    precondition(renderingStore.shopControls.selectedArtworkAvailable)
    for (width,height) in [(460,520),(480,580),(480,1000)] {
        autoreleasepool {
            let store = renderingStore,window = renderingWindow,view = renderingView
            window.setContentSize(NSSize(width:width,height:height))
            view.frame = NSRect(x:0,y:0,width:width,height:height)
            settle(view)
            let containers = scrolls(view)
            precondition(containers.count == 1)
            let scroll = containers[0],clip = scroll.contentView,document = scroll.documentView!
            precondition(document.isFlipped)
            precondition(document.bounds.width <= clip.bounds.width+0.5, "Shop content overflows horizontally")
            precondition(view.bounds.width == CGFloat(width) && view.bounds.height == CGFloat(height))
            let positions:[(String,CGFloat)] = height == 1000 ? [("full",0)] : [("top",0),("actions",max(0,document.bounds.height-clip.bounds.height))]
            if height == 1000 {precondition(document.bounds.height <= clip.bounds.height+0.5,"Full-height panel must contain the complete shop")}
            for (position,y) in positions {
                clip.scroll(to:NSPoint(x:0,y:y));scroll.reflectScrolledClipView(clip);settle(view)
                var check = capture(view,"\(name)-\(width)x\(height)-\(position)")
                check["case"] = name;check["position"] = position;check["size_points"] = [width,height]
                check["document_width"] = document.bounds.width;check["viewport_width"] = clip.bounds.width
                check["document_height"] = document.bounds.height;check["viewport_height"] = clip.bounds.height
                check["scroll_y"] = clip.bounds.minY;check["horizontal_overflow"] = false
                check["selected_item"] = selected;check["can_buy"] = store.shopControls.canBuySelected
                check["owned"] = store.shopControls.selectedOwned;check["placed"] = store.shopControls.selectedPlaced
                check["unavailable_reason"] = store.shopControls.unavailableReason ?? ""
                checks.append(check)
                guardIsolation(store,window)
                precondition(NSDictionary(dictionary:store.state).isEqual(to:state),"Rendering changed sample business state")
                print("RENDER \(check["file"]!) doc=\(document.bounds.size) viewport=\(clip.bounds.size) scrollY=\(clip.bounds.minY)")
            }
        }
    }
}
renderingWindow.contentView = nil;renderingWindow.close()

// This is a local accessibility tree belonging only to an unshown fixture.
// It does not use system AX permissions or inspect any other application.
func nodes(_ root:Any) -> [NSAccessibilityProtocol] {
    var seen = Set<ObjectIdentifier>(),result:[NSAccessibilityProtocol] = []
    func walk(_ object:Any) {
        guard let node = object as? NSAccessibilityProtocol else {return}
        let key = ObjectIdentifier(node as AnyObject)
        guard seen.insert(key).inserted,seen.count<5000 else {return}
        result.append(node)
        for child in node.accessibilityChildren() ?? [] {walk(child)}
    }
    walk(root);return result
}
func find(_ root:Any,_ id:String) -> NSAccessibilityProtocol? {
    nodes(root).first{$0.accessibilityIdentifier() == id}
}
var ax:[String:Any] = ["window_shown":false,"system_accessibility_used":false,"commands":[]]
let store = Store()
let initial = fixtures["interaction_initial"] as! [String:Any]
receive(store,["phase":"ready","ok":true,"state":initial])
store.message = "按钮回执离屏样例 · 无真钱交易 · 无存档"
var requests:[[String:Any]] = []
store.requestSink = {requests.append($0)}
let (window,view) = panel(store,480,1000)
let exposed = nodes(view)
ax["node_count"] = exposed.count
ax["identifiers"] = exposed.compactMap{$0.accessibilityIdentifier()}
if let row = find(view,"shop-preview-shrine_g1") {
    let didPress = row.accessibilityPerformPress();settle(view)
    if didPress && store.shopControls.selectedID == "shrine_g1" {
        precondition(requests.isEmpty && NSDictionary(dictionary:store.state).isEqual(to:initial))
        guard let buy = find(view,"shop-buy") else {fatalError("AX selected the row but did not expose its purchase button")}
        precondition(buy.accessibilityPerformPress());settle(view)
        precondition(requests.count == 1 && requests[0]["action"] as? String == "buy" && requests[0]["item"] as? String == "shrine_g1")
        precondition(store.shopControls.isSubmitting && !store.shopControls.selectedOwned)
        let purchased = fixtures["interaction_purchased"] as! [String:Any]
        receive(store,["id":requests[0]["id"]!,"ok":true,"state":purchased]);settle(view)
        precondition(store.shopControls.selectedOwned && !store.shopControls.selectedPlaced && !store.shopControls.isSubmitting)
        capture(view,"ax-after-purchase-480x1000")
        guard let place = find(view,"shop-place") else {fatalError("AX did not expose the place button after a real Store receipt")}
        precondition(place.accessibilityPerformPress());settle(view)
        precondition(requests.count == 2 && requests[1]["action"] as? String == "place" && requests[1]["item"] as? String == "shrine_g1")
        let placed = fixtures["interaction_placed"] as! [String:Any]
        receive(store,["id":requests[1]["id"]!,"ok":true,"state":placed]);settle(view)
        precondition(store.shopControls.selectedPlaced && !store.shopControls.isSubmitting)
        precondition(store.coins == initial["coins"] as! Int - 120)
        capture(view,"ax-after-placement-480x1000")
        ax["status"] = "verified"
        ax["commands"] = requests
        ax["row_purchase_placement_receipts"] = true
        print("AX_VERIFIED: actual hidden SwiftUI row, buy and place presses reached fake requestSink, then real Store.receive applied ownership and placement separately")
    } else {
        precondition(requests.isEmpty)
        ax["status"] = "unavailable"
        ax["reason"] = "The hidden SwiftUI row was found, but accessibilityPerformPress did not select it. No visible-window fallback was attempted."
        ax["row_press_returned"] = didPress
        print("AX_UNAVAILABLE: hidden row action did not execute; no visible-window fallback")
    }
} else {
    ax["status"] = "unavailable"
    ax["reason"] = "The unshown NSHostingView accessibility tree did not expose shop-preview-shrine_g1. No visible-window fallback was attempted."
    precondition(requests.isEmpty)
    print("AX_UNAVAILABLE: unshown NSHostingView exposed \(exposed.count) nodes but no shop-preview-shrine_g1; existing intent tests remain separate evidence")
}
guardIsolation(store,window)
window.contentView = nil;window.close()
precondition(checks.count == 30)
try! JSONSerialization.data(withJSONObject:checks,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("layout-checks.json"))
try! JSONSerialization.data(withJSONObject:ax,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("accessibility-check.json"))
print("SHOP_VISUAL_PASS: 30 actual PanelView/ShopPage images, no horizontal overflow, formal PNGs, synthetic state, no displayed window/worker/save")
'''


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


def sample_states(save_sentinel):
    sys.path.insert(0, str(ROOT))
    import random
    from tianmu_mvp.model import GameState
    from tianmu_mvp.service import ApplicationService

    def state(coins, owned=(), placed=None, age=20):
        game = GameState.new(rng=random.Random(160))
        game.game_timezone = 'UTC';game.onboarding = 'legacy'
        game.advance(age, now=1964779220)
        game.coins = coins;game.owned_items.update(owned)
        game.placed_items = dict(placed or {})
        game.placed_item = game.placed_items.get('plate')
        result = ApplicationService(save_sentinel, initial_state=game).snapshot(1964779220)
        assert not save_sentinel.exists()
        return result

    all_items = ('offering_plate', 'incense_burner', 'bell', 'shrine_g1', 'shrine_g2')
    all_slots = {'plate': 'offering_plate', 'incense': 'incense_burner', 'bell': 'bell', 'shrine': 'shrine_g2'}
    return {'_note': 'Constructed sample states; no real inventory, currency, worker or save access.',
            'cases': [
                {'name': 'g1-unowned', 'selected': 'shrine_g1', 'state': state(240, age=0)},
                {'name': 'g2-locked', 'selected': 'shrine_g2', 'state': state(1000)},
                {'name': 'plate-insufficient', 'selected': 'offering_plate',
                 'state': state(5, ('shrine_g1', 'incense_burner'), {'shrine': 'shrine_g1', 'incense': 'incense_burner'}, 8)},
                {'name': 'incense-owned', 'selected': 'incense_burner',
                 'state': state(16, ('offering_plate', 'incense_burner', 'shrine_g1'), {'plate': 'offering_plate', 'shrine': 'shrine_g1'})},
                {'name': 'bell-owned', 'selected': 'bell',
                 'state': state(12, all_items, {key: value for key, value in all_slots.items() if key != 'bell'})},
                {'name': 'g2-equipped', 'selected': 'shrine_g2', 'state': state(424, all_items, all_slots)},
            ],
            'interaction_initial': state(240),
            'interaction_purchased': state(120, ('shrine_g1',)),
            'interaction_placed': state(120, ('shrine_g1',), {'shrine': 'shrine_g1'})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve();output.mkdir(parents=True, exist_ok=True)
    scene = args.scene_dir.resolve();attendant = ROOT/'assets/production/A01'
    dependencies = ['Presentation.swift', 'WindowPlacement.swift', 'DesktopInsects.swift', 'InsectArtwork.swift', 'TimerControls.swift']
    paths = [Path(__file__).resolve(), ROOT/'native/OverlayHost.swift', ROOT/'native/v1/main.swift',
             *(ROOT/'native/v1'/name for name in dependencies),
             *(ROOT/'tianmu_mvp'/name for name in ['model.py', 'service.py', 'tuning.py'])]
    manifests = {}
    for folder in (scene, attendant):
        manifest_path = folder/'manifest.json'
        config = json.loads(manifest_path.read_text())
        manifests[folder] = config
        paths.append(manifest_path)
        for name in set(referenced_files(config)):
            assert Path(name).name == name and '\\' not in name
            paths.append(folder/name)
    originals = {path: path.read_bytes() for path in paths}
    hashes = {str(path): hashlib.sha256(data).hexdigest() for path, data in originals.items()}
    main_source = originals[ROOT/'native/v1/main.swift'].decode()
    scene_source = originals[ROOT/'native/OverlayHost.swift'].decode()
    assert main_source.count('let application = NSApplication.shared') == 1
    assert scene_source.count('final class Host:') == 1
    with tempfile.TemporaryDirectory(prefix='tianmu-shop-visual-') as directory:
        work = Path(directory)
        bundle = work/'ShopReview.app/Contents';macos = bundle/'MacOS';macos.mkdir(parents=True)
        for source, name in ((scene, 'scene'), (attendant, 'A01')):
            destination = bundle/'Resources/art'/name;destination.mkdir(parents=True)
            for filename in set(referenced_files(manifests[source])) | {'manifest.json'}:
                (destination/filename).write_bytes(originals[source/filename])
        (bundle/'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'local.tianmu.shop-review', 'CFBundleExecutable': 'review',
            'CFBundlePackageType': 'APPL', 'LSUIElement': True, 'NSHighResolutionCapable': True}))
        (work/'Scene.swift').write_text(scene_source.split('final class Host:')[0])
        (work/'main.swift').write_text(main_source.split('let application = NSApplication.shared')[0]+SWIFT)
        for name in dependencies:
            (work/name).write_bytes(originals[ROOT/'native/v1'/name])
        sentinel = work/'never-created-game-state.json'
        fixture = sample_states(sentinel)
        fixture_path = work/'sample-states.json';fixture_path.write_text(json.dumps(fixture, ensure_ascii=False))
        binary = macos/'review'
        subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI', str(work/'Scene.swift'),
                        *(str(work/name) for name in dependencies), str(work/'main.swift'), '-o', str(binary)],
                       check=True, timeout=90)
        try:
            run = subprocess.run([str(binary), str(fixture_path), str(output), '--save-file', str(sentinel)],
                                 capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b'', error.stderr or b''
            if isinstance(stdout, bytes): stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes): stderr = stderr.decode(errors='replace')
            (output/'render.log').write_text(stdout+stderr+'\nFAILED: isolated render exceeded its 120-second runtime limit.\n')
            raise
        (output/'render.log').write_text(run.stdout+run.stderr)
        print(run.stdout, end='', flush=True)
        if run.returncode:
            raise RuntimeError('Isolated shop render failed: '+run.stderr)
        assert not sentinel.exists() and not Path(str(sentinel)+'.bak').exists()
        (output/'sample-states.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2)+'\n')
    changed = [str(path) for path, data in originals.items() if path.read_bytes() != data]
    if changed:
        raise RuntimeError('Source or artwork changed during rendering; regenerate before acceptance: '+', '.join(changed))
    (output/'fixture.json').write_text(json.dumps({
        'renderer': 'actual PanelView + ShopPage + static ScenePreview using the current native source',
        'scene_source': str(scene), 'attendant_source': str(attendant),
        'source_sha256': hashes, 'source_and_original_images_preserved': True,
        'rendered_scenarios': 6, 'rendered_images': 30, 'sizes_points': [[460, 520], [480, 580], [480, 1000]],
        'window_hosts_unshown': True, 'no_visible_window': True, 'no_worker': True, 'no_save_access': True,
        'business_state': 'synthetic backend snapshots; fake requestSink and real Store.receive for optional hidden AX proof',
    }, ensure_ascii=False, indent=2)+'\n')
    print('SOURCE_AND_ORIGINAL_IMAGE_GUARD_PASS; actual source snapshots and all copied PNGs remain byte-identical.', flush=True)


if __name__ == '__main__':
    main()
