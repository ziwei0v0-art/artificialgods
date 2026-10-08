"""Render current game-timezone settings with sample data, never show a window."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
let app=NSApplication.shared; app.setActivationPolicy(.prohibited)
let output=URL(fileURLWithPath:CommandLine.arguments[1])
func scrolls(_ view:NSView)->[NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap { scrolls($0) }
}
func invalidate(_ view:NSView) { view.needsDisplay=true; view.subviews.forEach { invalidate($0) } }
for (width,height) in [(460,520),(480,580)] {
for failed in [false,true] {
    let store=Store()
    store.state=["onboarding":"legacy","game_timezone":"Pacific/Auckland","timer":["clock_timezone":"Asia/Shanghai","notification_enabled":false]]
    store.message="隔离设置样例 · 不读写存档"
    store.commandSink = { action,_,done in
        assert(failed && action=="game_timezone_set"); done?(false)
    }
    store.gameSettings.draftTimezone="UTC"
    if failed { store.gameSettings.applyTimezone() }
    let presentation=PresentationState(); presentation.open("设置")
    let view=NSHostingView(rootView:PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{}))
    let frame=NSRect(x:0,y:0,width:width,height:height)
    let window=NSWindow(contentRect:frame,styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false; window.contentView=view; view.frame=frame
    func settle() {
        for _ in 0..<3 {
            view.layoutSubtreeIfNeeded()
            let warmup=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
            view.cacheDisplay(in:view.bounds,to:warmup)
            RunLoop.current.run(until:Date().addingTimeInterval(0.08))
        }
    }
    settle()
    let candidates=scrolls(view); assert(candidates.count==1)
    let scroll=candidates[0], clip=scroll.contentView, document=scroll.documentView!
    assert(document.bounds.width <= clip.bounds.width+0.5)
    // Settings are intentionally scrollable; capture the actual lower section.
    clip.scroll(to:NSPoint(x:0,y:max(0,document.bounds.height-clip.bounds.height)))
    scroll.reflectScrolledClipView(clip); settle(); invalidate(view)
    let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    let name="settings-\(failed ? "error" : "draft")-\(width)x\(height).png"
    try! bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name))
    assert(!window.isVisible && store.process==nil && store.gameSettings.savedTimezone=="Pacific/Auckland")
    print("PASS \(name) document=\(document.bounds) viewport=\(clip.bounds); sample only, no visible window/save/worker")
    window.close()
}
}
'''
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
    print('main.swift SHA256',hashlib.sha256((ROOT/'native/v1/main.swift').read_bytes()).hexdigest(),flush=True)
    with tempfile.TemporaryDirectory(prefix='tianmu-settings-render-') as folder:
        folder=Path(folder)
        (folder/'main.swift').write_text(source+HARNESS)
        (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),
            *(str(ROOT/'native/v1'/name) for name in ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift', 'InsectArtwork.swift','TimerControls.swift']),
            str(folder/'main.swift'),'-o',str(folder/'render')],check=True,timeout=90)
        subprocess.run([str(folder/'render'),str(output)],check=True,timeout=30)
if __name__=='__main__':main()
