"""Offscreen production sale layout; QA-only geometry probes, no clicks or worker."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SaleScrollTests(unittest.TestCase):
    def test_confirmation_is_visible_or_scroll_reachable_at_both_sizes(self):
        source = (ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        # Add layout-neutral measurement only to the two actual production buttons.
        for label in ['确认出售', '取消']:
            if label == '确认出售':
                needle = 'Button("确认出售") { controls.confirmSale() }'
            else:
                needle = 'Button("取消") { controls.cancelSale() }'
            self.assertEqual(source.count(needle), 1)
            source = source.replace(needle, needle + '.background(GeometryReader { g in Color.clear.onAppear { qaFrames["'+label+'"] = g.frame(in: .named("qaRoot")) }.onChange(of: g.frame(in: .named("qaRoot"))) { f in qaFrames["'+label+'"] = f } })')
        harness = r'''
var qaFrames: [String:CGRect] = [:]
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let fixture = try! JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [String:Any]
func scrolls(_ view:NSView)->[NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap { scrolls($0) }
}
for (width,height) in [(460,520),(480,580)] {
    qaFrames = [:]
    let store=Store(); store.state=fixture; store.message="隔离样例 · 不读写存档"
    store.commandSink = { _,_,_ in fatalError("A layout probe must not submit a transaction") }
    store.sale=["token":"fixture-only","count":1,"amount":1]
    let presentation=PresentationState();presentation.open("虫瓶")
    let view=NSHostingView(rootView:PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{}).coordinateSpace(name:"qaRoot"))
    let window=NSWindow(contentRect:NSRect(x:0,y:0,width:width,height:height),styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false;window.contentView=view
    view.frame=NSRect(x:0,y:0,width:width,height:height)
    func layout() {
        view.layoutSubtreeIfNeeded()
        let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
        view.cacheDisplay(in:view.bounds,to:bitmap)
        RunLoop.current.run(until:Date().addingTimeInterval(0.08))
        view.layoutSubtreeIfNeeded()
    }
    layout()
    let candidates=scrolls(view)
    assert(candidates.count==1,"Expected exactly one production scroll container")
    let scroll=candidates[0], clip=scroll.contentView, doc=scroll.documentView!
    assert(doc.isFlipped,"Probe expects production flipped document")
    let before=clip.bounds
    let maxY=max(0,doc.bounds.height-before.height)
    assert(doc.bounds.width <= clip.bounds.width+0.5,"Sale content must not overflow horizontally")
    assert(qaFrames.count==2,"Actual button measurements missing; cannot claim reachability")
    let viewport=view.convert(clip.bounds,from:clip)
    let initial=qaFrames
    print("PROBE viewport=\(viewport) initial=\(initial) clip=\(clip.bounds) doc=\(doc.bounds)"); fflush(stdout)
    print("SIZE \(width)x\(height) document=\(doc.bounds) viewport=\(viewport) initialButtons=\(initial)")
    clip.scroll(to:NSPoint(x:0,y:maxY));scroll.reflectScrolledClipView(clip)
    layout()
    assert(abs(clip.bounds.minY-maxY)<1,"Did not reach document bottom")
    let visible=view.convert(clip.bounds,from:clip)
    for label in ["确认出售","取消"] {
        let frame=qaFrames[label]!
        assert(frame.width>0 && frame.height>0)
        assert(visible.insetBy(dx:-0.5,dy:-0.5).contains(frame),"Button not fully visible after scroll: \(label) \(frame), viewport \(visible)")
        assert(abs((initial[label]!.minY-frame.minY)-maxY)<1,"Target did not move with production scroll document")
        print("REACHABLE \(label) initiallyVisible=\(viewport.contains(initial[label]!)) frame=\(frame)")
    }
    assert(!window.isVisible,"Fixture must never show a desktop window")
    assert(store.sale?["token"] as? String == "fixture-only","No sale action may occur")
    assert(store.process == nil && store.input == nil && store.output == nil,"Layout probe must not start a worker")
    print("PASS \(width)x\(height) bottomOffset=\(clip.bounds.minY); CLICK_UNTESTED; no worker/save/window display")
}
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-sale-scroll-') as folder:
            folder=Path(folder)
            (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            (folder/'main.swift').write_text(source+harness)
            binary=folder/'check'
            build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),str(ROOT/'native/v1/Presentation.swift'),str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT/'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),str(folder/'main.swift'),'-o',str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary),str(ROOT/'tests/fixtures/ui_populated.json')],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertEqual(run.stdout.count('PASS '),2,run.stdout)
            print(run.stdout.strip())
