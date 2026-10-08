"""Measure production controls offscreen; no clicks, worker, saves or visible window."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContentScrollTests(unittest.TestCase):
    def test_pages_release_and_empty_bottle_are_visible_or_scroll_reachable(self):
        source = (ROOT / "native/v1/main.swift").read_text().split("let application = NSApplication.shared")[0]
        # Test-only backgrounds observe actual geometry and inherited enabled
        # state, without replacing a production label, action, or container.
        # Only bottle states run in this harness. Grouped collection cards and
        # their detail actions are measured in test_collection_cards.py; stale
        # probes for the unused legacy ShopPage must not prevent bottle layout.
        probes = [
            ('Text("虫瓶 · \\(status.inventoryText)").font(.system(size: 20, weight: .medium, design: .serif))', '"bottle-total"'),
            ('Text(status.captureText).font(.caption).foregroundStyle(.secondary)\n                    .fixedSize(horizontal: false, vertical: true)', '"bottle-capture"'),
            ('Text(store.state["auto_paused"] as? Bool == true ? "自动捕捉已暂停：出售或放回至少一只即可继续；手动捕虫仍可用。" : "瓶里暂停繁殖，长期保存，无需清洁。")\n                .font(.callout).foregroundStyle(.secondary).padding(.top, 4)', '"bottle-footer"'),
            ('Button("放回…") { controls.beginRelease() }', '"release-open"'),
            ('Button("出售 \\(controls.saleCount) 只 · \\(controls.saleAmount) 铜钱") { controls.previewSale() }\n                        .buttonStyle(.borderedProminent)', '"sale"'),
            ('Button("收起") { controls.dismissRelease() }', '"release-collapse"'),
            ('Text("雌 \\(controls.female) · 雄 \\(controls.male)").font(.caption).foregroundStyle(.secondary)', '"release-sex-count"'),
            ('Picker("性别", selection: $controls.releaseSex) {\n                                ForEach(["全部", "雌", "雄"], id: \\.self) { Text($0) }\n                            }.frame(width: 160)', '"release-sex-picker"'),
            ('Button("放回桌面") { controls.release() }.disabled(controls.releaseAvailable == 0)', '"release-confirm"'),
            ('Text("在桌面空白处框选，松手后等蜘蛛织网。").font(.caption).foregroundStyle(.secondary)', '"empty-hint"'),
            ('.frame(width: 252, height: 252).allowsHitTesting(false)', '"bottle-art"'),
            ('.accessibilityIdentifier("bottle-color-\\(name)")', '"bottle-color-" + name'),
            ('Button("确认出售") { controls.confirmSale() }', '"sale-confirm"'),
            ('Button("取消") { controls.cancelSale() }', '"sale-cancel"'),
        ]
        for needle, expression in probes:
            self.assertEqual(source.count(needle), 1, needle)
            source = source.replace(needle, needle + ".background(QALayoutProbe(key: " + expression + "))")
        harness = r'''
var qaFrames: [String:CGRect] = [:]
var qaEnabled: [String:Bool] = [:]
struct QALayoutProbe: View {
    let key: String
    @Environment(\.isEnabled) private var enabled
    private func record(_ frame: CGRect) { qaFrames[key] = frame; qaEnabled[key] = enabled }
    var body: some View {
        GeometryReader { g in
            Color.clear.onAppear { record(g.frame(in: .named("qaRoot"))) }
                .onChange(of: g.frame(in: .named("qaRoot"))) { record($0) }
                .onChange(of: enabled) { _ in record(g.frame(in: .named("qaRoot"))) }
        }
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let fixture = try! JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [String:Any]
func scrolls(_ view:NSView)->[NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap { scrolls($0) }
}
for (scenario,route) in [("bottle","虫瓶"),("release","虫瓶"),("empty","虫瓶")] {
for (width,height) in [(420,540),(480,580)] {
    qaFrames = [:]; qaEnabled = [:]
    var state = fixture
    if scenario == "empty" {
        state["bottle"] = (fixture["bottle"] as! [[String:Any]]).map { original -> [String:Any] in
            var row = original; row["female"] = 0; row["male"] = 0; return row
        }
    }
    let store=Store(); store.state=state; store.message="隔离样例 · 不读写存档"
    store.commandSink = { _,_,_ in fatalError("A layout probe must not submit a command") }
    var captures = 0
    if scenario == "release" { store.bottleControls.beginRelease() }
    let presentation=PresentationState(); presentation.open(route)
    let view=NSHostingView(rootView:PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{},capture:{ captures += 1 }).coordinateSpace(name:"qaRoot"))
    let window=NSWindow(contentRect:NSRect(x:0,y:0,width:width,height:height),styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false; window.contentView=view
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
    let maxY=max(0,doc.bounds.height-clip.bounds.height)
    let bottomKeys: [String]
    switch scenario {
    case "release": bottomKeys = ["bottle-footer", "release-collapse", "release-sex-count", "release-sex-picker", "release-confirm"]
    case "empty": bottomKeys = ["bottle-footer", "empty-hint"]
    default: bottomKeys = ["bottle-footer", "release-open", "sale"]
    }
    assert(bottomKeys.allSatisfy { qaFrames[$0] != nil }, "Missing actual target measurements")
    let viewport=view.convert(clip.bounds,from:clip)
    let initial=qaFrames
    if route == "虫瓶" {
        let art = initial["bottle-art"]!
        assert(art.height >= 246 && abs(art.midX-viewport.midX)<1,
               "Bottle must be a large centred page subject, not a left-side thumbnail")
        assert(viewport.insetBy(dx:-0.5,dy:-0.5).contains(art),
               "Bottle artwork must be fully visible at the initial document top")
        for key in ["bottle-total", "bottle-capture"] {
            assert(initial[key] != nil, "Bottle status missing from production view")
            assert(viewport.contains(initial[key]!), "Bottle status not fully visible at top")
            print("STATUS_VISIBLE \(key) frame=\(initial[key]!)")
        }
        let colorKeys = ["普通褐色", "中褐色", "深褐色", "白色"].map { "bottle-color-" + $0 }
        let chips = colorKeys.map { initial[$0]! }
        assert(chips.allSatisfy { viewport.contains($0) }, "All four colour counters must fit beside the complete bottle at first view")
        assert(chips.allSatisfy { abs($0.midY-chips[0].midY)<0.5 && $0.height>=40 }, "Colour counters must form one readable row")
        assert(chips[0].minY >= art.maxY, "Colour chips must follow the centred bottle")

        if scenario == "release" {
            assert(qaEnabled["release-confirm"] == true && store.bottleControls.releaseExpanded)
        } else {
            assert(initial["release-sex-count"] == nil && initial["release-sex-picker"] == nil,
                   "Sex controls must be absent until release is expanded")
        }
        if scenario == "empty" {
            assert(initial["empty-hint"] != nil,"An empty bottle should explain passive desktop capture")
            assert(initial["sale"] == nil && initial["release-open"] == nil,"Empty inventory cannot offer a transaction")
        }
    }
    assert(abs(clip.bounds.minY)<0.5,"Initial document top not reachable")
    assert(doc.bounds.width <= clip.bounds.width+0.5,"Content must not overflow horizontally")
    print("BEFORE \(scenario) \(width)x\(height) document=\(doc.bounds) viewport=\(viewport)")
    for key in bottomKeys { print("TARGET \(key) frame=\(initial[key]!) initialVisible=\(viewport.contains(initial[key]!))") }
    fflush(stdout)
    clip.scroll(to:NSPoint(x:0,y:maxY)); scroll.reflectScrolledClipView(clip)
    layout()
    assert(abs(clip.bounds.minY-maxY)<1,"Did not reach document bottom")
    let visible=view.convert(clip.bounds,from:clip)
    for label in bottomKeys {
        let frame=qaFrames[label]!
        assert(frame.width>0 && frame.height>0)
        assert(visible.insetBy(dx:-0.5,dy:-0.5).contains(frame),"Target not fully visible after scroll: \(label) \(frame), viewport \(visible)")
        assert(abs((initial[label]!.minY-frame.minY)-maxY)<1,"Target did not move with production scroll document")
        print("REACHABLE \(label) initiallyVisible=\(viewport.contains(initial[label]!)) frame=\(frame)")
    }
    if scenario == "bottle" {
        clip.scroll(to:.zero); scroll.reflectScrolledClipView(clip); layout()
        store.bottleControls.beginRelease()
        for _ in 0..<3 { layout() }
        assert(store.bottleControls.releaseExpanded)
        for key in ["release-collapse", "release-sex-picker", "release-confirm"] {
            assert(view.convert(clip.bounds,from:clip).insetBy(dx:-0.5,dy:-0.5).contains(qaFrames[key]!),
                   "Expanded release controls must become visible automatically: \(key), \(qaFrames[key]!)")
        }
        store.bottleControls.dismissRelease(); layout()
        clip.scroll(to:.zero); scroll.reflectScrolledClipView(clip); layout()
        store.sale = ["token":"layout-only", "count":1, "amount":2]
        for _ in 0..<3 { layout() }
        for key in ["sale-confirm", "sale-cancel"] {
            assert(view.convert(clip.bounds,from:clip).insetBy(dx:-0.5,dy:-0.5).contains(qaFrames[key]!),
                   "Sale confirmation must become visible automatically: \(key), \(qaFrames[key]!)")
        }
        store.sale = nil; layout()
        print("AUTOSCROLL_PASS \(width)x\(height): release and sale confirmation remain in the sole production scroll view")
    }
    assert(!window.isVisible,"Fixture must never show a desktop window")
    assert(store.sale == nil && captures == 0,"No capture or sale action may occur")
    assert(store.process == nil && store.input == nil && store.output == nil,"Layout probe must not start a worker")
    assert(NSDictionary(dictionary:store.state).isEqual(to:state),"Fixture data changed")
    print("PASS \(scenario) \(width)x\(height) bottomOffset=\(clip.bounds.minY); CLICK_UNTESTED; no worker/save/window display")
    window.close()
}
}
'''
        with tempfile.TemporaryDirectory(prefix="tianmu-content-scroll-") as folder:
            folder = Path(folder)
            (folder / "Scene.swift").write_text((ROOT / "native/OverlayHost.swift").read_text().split("final class Host:")[0])
            (folder / "main.swift").write_text(source + harness)
            binary = folder / "check"
            build = subprocess.run(["swiftc", "-framework", "AppKit", "-framework", "SwiftUI", str(folder / "Scene.swift"),
                                    str(ROOT / "native/v1/Presentation.swift"), str(ROOT / "native/v1/WindowPlacement.swift"),
                                    str(ROOT / "native/v1/DesktopInsects.swift"), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT / "native/v1/TimerControls.swift"), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),
                                    str(folder / "main.swift"), "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(ROOT / "tests/fixtures/ui_populated.json")],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(sum(line.startswith("PASS ") for line in run.stdout.splitlines()), 6, run.stdout)
            self.assertEqual(run.stdout.count("AUTOSCROLL_PASS "), 2, run.stdout)
            print(run.stdout.strip())
