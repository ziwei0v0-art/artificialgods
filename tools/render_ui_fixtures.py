"""Render six production-view states at three sizes without app entry/worker/save.

Release and sale captures show the bottom of the production scroll view so their
expanded controls can be inspected. Other states retain the initial position.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let fixture = try! JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [String:Any]
let output = URL(fileURLWithPath:CommandLine.arguments[2])
func scrolls(_ view: NSView) -> [NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap { scrolls($0) }
}
func invalidate(_ view: NSView) {
    view.needsDisplay = true
    for child in view.subviews { invalidate(child) }
}
var rendered = 0
for (name,route) in [("bottle","虫瓶"),("release","虫瓶"),("empty","虫瓶"),
                     ("sale","虫瓶"),("codex","虫谱"),("shop","装扮")] {
    for (width,height) in [(460,520),(480,580),(480,1000)] {
        autoreleasepool {
        var state = fixture
        if name == "empty" {
            state["bottle"] = (fixture["bottle"] as! [[String:Any]]).map { original in
                var row = original; row["female"] = 0; row["male"] = 0; return row
            }
        }
        let store = Store()
        store.commandSink = { action, _, _ in fatalError("Rendering must not send a command: \(action)") }
        store.requestSink = { _ in fatalError("Rendering must not send a worker request") }
        store.state = state
        store.message = "隔离样例 · 数量和日期非实况 · 不读写存档"
        if name == "release" { store.bottleControls.beginRelease() }
        if name == "sale" { store.sale = ["token":"fixture-only", "count":1, "amount":1] }
        let presentation = PresentationState(); presentation.open(route)
        let view = NSHostingView(rootView:PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{}))
        let frame = NSRect(x:0,y:0,width:width,height:height)
        let window = NSWindow(contentRect:frame, styleMask:[.borderless], backing:.buffered, defer:false)
        window.isReleasedWhenClosed = false; window.ignoresMouseEvents = true
        window.contentView = view; view.frame = frame
        func settle() {
            for _ in 0..<3 {
                view.layoutSubtreeIfNeeded()
                let warmup = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
                view.cacheDisplay(in:view.bounds,to:warmup)
                RunLoop.current.run(until:Date().addingTimeInterval(0.08))
            }
            view.layoutSubtreeIfNeeded()
        }
        settle()
        let containers = scrolls(view)
        assert(containers.count == 1, "Expected one production scroll view")
        let scroll = containers[0], clip = scroll.contentView, document = scroll.documentView!
        if name == "release" || name == "sale" {
            assert(document.isFlipped)
            clip.scroll(to:NSPoint(x:0,y:max(0,document.bounds.height-clip.bounds.height)))
            scroll.reflectScrolledClipView(clip)
            settle()
        }
        invalidate(view)
        let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
        view.cacheDisplay(in:view.bounds,to:bitmap)
        let target = output.appendingPathComponent("\(name)-\(width)x\(height).png")
        let png = bitmap.representation(using:.png,properties:[:])!
        assert(png.count > 4096, "Rendered panel is unexpectedly empty")
        assert(view.bounds.size == frame.size, "Requested panel dimensions changed")
        assert(!window.isVisible && !window.isKeyWindow && !window.isMainWindow)
        assert(store.process == nil && store.input == nil && store.output == nil)
        assert(NSDictionary(dictionary:store.state).isEqual(to:state), "Rendering changed sample inventory")
        assert(store.bottleControls.releaseExpanded == (name == "release"))
        if name == "empty" {
            assert(store.rows("bottle").count == 4 && store.bottleControls.totalInventory == 0)
        }
        if name == "sale" { assert(store.sale?["token"] as? String == "fixture-only") }
        else { assert(store.sale == nil) }
        try! png.write(to:target)
        print("RENDER \(target.lastPathComponent) pixels=\(bitmap.pixelsWide)x\(bitmap.pixelsHigh) bytes=\(png.count) scrollY=\(clip.bounds.minY) documentHeight=\(document.bounds.height)")
        window.contentView = nil; window.close()
        rendered += 1
        }
    }
}
assert(rendered == 18)
print("PASS: 18 production-view images; isolated sample data; no displayed windows, commands, worker or save access")
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source_paths = [ROOT/'native/OverlayHost.swift', *(ROOT/'native/v1'/name for name in [
        'Presentation.swift', 'WindowPlacement.swift', 'DesktopInsects.swift', 'InsectArtwork.swift',
        'TimerControls.swift', 'main.swift']), ROOT/'tests/fixtures/ui_populated.json']
    sources = {path: path.read_bytes() for path in source_paths}
    for path, data in sources.items():
        print(f'SOURCE {path.relative_to(ROOT)} sha256={hashlib.sha256(data).hexdigest()}', flush=True)
    print('FIXTURE: constructed inventory, coins and dates; not current game state.', flush=True)
    with tempfile.TemporaryDirectory(prefix='tianmu-ui-fixtures-') as directory:
        directory = Path(directory)
        scene_source = sources[ROOT/'native/OverlayHost.swift'].decode()
        main_source = sources[ROOT/'native/v1/main.swift'].decode()
        assert scene_source.count('final class Host:') == 1
        assert main_source.count('let application = NSApplication.shared') == 1
        (directory/'Scene.swift').write_text(scene_source.split('final class Host:')[0])
        (directory/'main.swift').write_text(main_source.split('let application = NSApplication.shared')[0]+HARNESS)
        dependencies = ['Presentation.swift', 'WindowPlacement.swift', 'DesktopInsects.swift', 'InsectArtwork.swift', 'TimerControls.swift']
        for name in dependencies:
            (directory/name).write_bytes(sources[ROOT/'native/v1'/name])
        fixture = directory/'ui_populated.json'
        fixture.write_bytes(sources[ROOT/'tests/fixtures/ui_populated.json'])
        binary = directory/'render'
        subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(directory/'Scene.swift'),
                        *(str(directory/name) for name in dependencies),str(directory/'main.swift'),'-o',str(binary)],
                       check=True,timeout=90)
        subprocess.run([str(binary),str(fixture),str(args.output.resolve())],check=True,timeout=45)
    changed = [str(path.relative_to(ROOT)) for path, data in sources.items() if path.read_bytes() != data]
    if changed:
        raise RuntimeError('Sources changed during rendering; regenerate before acceptance: ' + ', '.join(changed))
    print('SOURCE_STABILITY: PASS; rendered source snapshots still match current files.', flush=True)

if __name__ == '__main__':
    main()
