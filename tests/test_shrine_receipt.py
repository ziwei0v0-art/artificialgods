"""Sign persistence + production Swift receipt/action replay, no visible windows."""
import copy
import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.datetime(2026, 9, 30, 12, tzinfo=datetime.timezone.utc).timestamp()

class ShrineReceiptTests(unittest.TestCase):
    def test_saved_before_success_same_day_restart_and_write_failure(self):
        from tianmu_mvp.service import ApplicationService
        from tianmu_mvp.storage import load_state
        with tempfile.TemporaryDirectory(prefix='tianmu-sign-service-') as directory:
            path = Path(directory)/'state.json'
            app = ApplicationService(path)
            app.game.timer_session.start('countdown', now=NOW, minutes=1.5)
            timer = copy.deepcopy(app.game.timer_session)
            coins = app.game.coins
            reply = app.handle({'action':'sign'}, now=NOW)
            self.assertTrue(reply['ok'])
            self.assertEqual(reply['state']['daily_sign_date'], app.game.daily_sign_date)
            self.assertIn(reply['state']['daily_sign_date'], app.game.sign_history)
            self.assertTrue(path.is_file(), 'Success must not precede persisted result')
            history = dict(app.game.sign_history)
            self.assertEqual(load_state(path).sign_history, history)
            self.assertEqual(app.game.coins, coins)
            self.assertEqual(app.game.timer_session.deadline, timer.deadline)
            self.assertEqual(app.game.timer_session.status, timer.status)
            self.assertTrue(app.handle({'action':'sign'}, now=NOW+10)['ok'])
            self.assertEqual(app.game.sign_history, history)
            reopened = ApplicationService(path)
            self.assertEqual(reopened.game.sign_history, history)
            original = path.read_bytes()
            before = copy.deepcopy(reopened.game.sign_history)
            with patch('tianmu_mvp.service.save_state', side_effect=OSError('isolated disk failure')):
                failed = reopened.handle({'action':'sign'}, now=NOW+86400)
            self.assertFalse(failed['ok'])
            self.assertIn('isolated disk failure', failed['error'])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(reopened.game.sign_history, before)

    def test_native_receipt_close_return_skip_failure_and_restored_result(self):
        from tianmu_mvp.service import ApplicationService
        source = (ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        # Execute the actual current requestSign method body. Its enclosing View's
        # State storage is replaced only by local intent variables, not a copied action.
        start = source.index('func requestSign() {') + len('func requestSign() {')
        depth, end = 1, start
        while depth:
            if source[end] == '{': depth += 1
            elif source[end] == '}': depth -= 1
            end += 1
        action = source[start:end - 1]
        with tempfile.TemporaryDirectory(prefix='tianmu-sign-native-') as directory:
            folder = Path(directory)
            service = ApplicationService(folder/'state.json')
            empty = service.snapshot(NOW)
            success = service.handle({'action':'sign'}, now=NOW)
            self.assertTrue(success['ok'])
            saved = (folder/'state.json').read_bytes()
            success['id'] = 1
            with patch('tianmu_mvp.service.save_state', side_effect=OSError('isolated disk failure')):
                failure = ApplicationService(folder/'failure.json').handle({'action':'sign'}, now=NOW)
            failure['id'] = 1
            restored = ApplicationService(folder/'state.json').snapshot(NOW)
            (folder/'fixtures.json').write_text(json.dumps({'empty':empty,'success':success,'failure':failure,'restored':restored}))
            harness = r'''
let fixture = try! JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [String:Any]
func runCase(success:Bool, stay:Bool, reduceMotion:Bool=false) {
    let store=Store(), presentation=PresentationState()
    store.state=fixture["empty"] as! [String:Any]
    var sent:[[String:Any]]=[]
    store.requestSink={sent.append($0)}
    var historyDate="历史", requesting=false
    let date=(fixture["success"] as! [String:Any])["state"] as! [String:Any]
    let today=(date["signs"] as! [[String:Any]])[0]["date"] as! String
    var hasToday:Bool { store.rows("signs").contains { $0["date"] as? String == today } }
    func request() {
        let signs=store.rows("signs")
ACTION
    }
    presentation.open("神前");request()
    assert(requesting && store.number==1 && presentation.ritualStarted==nil,"Must wait for reply before ritual")
    assert(sent.count==1 && sent[0]["action"] as? String == "sign","Seeking a sign must never dispatch an insect capture")
    assert(historyDate=="今日")
    request()
    assert(sent.count==1 && store.number==1,"Pending request must not submit twice")
    assert(store.process==nil,"Native replay must not start a worker")
    // Close and navigate away before the delayed reply. No window methods needed.
    if !stay { presentation.dismiss();presentation.open("虫瓶") }
    let reply=fixture[success ? "success":"failure"] as! [String:Any]
    let data=try! JSONSerialization.data(withJSONObject:reply)
    let split=data.count/2
    store.receive(Data(data.prefix(split)))
    assert(requesting && presentation.ritualStarted==nil,"Partial JSON must not trigger ritual")
    store.receive(Data(data.dropFirst(split))+Data([10]))
    assert(!requesting && store.completions.isEmpty)
    assert(presentation.route==(stay ? "求签":"虫瓶"),"Delayed response must not reopen shrine")
    if success {
        assert(!store.rows("signs").isEmpty)
        if stay && !reduceMotion {
            let start=presentation.ritualStarted!
            assert(presentation.ritualStage(now:start+1) != nil)
            assert(presentation.ritualStage(now:start+2.5) != nil)
            assert(presentation.ritualStage(now:start+4.99) != nil)
            assert(presentation.ritualStage(now:start+5)==nil)
        } else {
            assert(presentation.ritualStarted==nil,"Away or reduced-motion receipt should save without starting a ritual")
        }
        presentation.dismiss();presentation.open("神前")
        assert(presentation.ritualStarted==nil,"Return must show saved sign directly")
        let count=store.number, coins=store.coins
        let retainedSigns=NSArray(array:store.rows("signs"))
        request()
        assert(store.number==count && presentation.ritualStarted==nil,"Same-day view reuses saved result without animation or request")
        assert(store.coins==coins && retainedSigns.isEqual(to:store.rows("signs")),"View must not charge or replace the sign")
        presentation.beginRitual(now:100);presentation.skipRitual()
        assert(presentation.ritualStage(now:101)==nil && !store.rows("signs").isEmpty)
        let fresh=PresentationState(), restoredStore=Store()
        restoredStore.state=fixture["restored"] as! [String:Any]
        fresh.open("神前")
        assert(fresh.ritualStarted==nil && !restoredStore.rows("signs").isEmpty,"Restart must retain saved sign without unfinished ceremony")
        print("PASS receipt: delayed/fragmented success -> no forced navigation; one-click/5s/skip/direct-same-day/restart")
    } else {
        assert(presentation.ritualStarted==nil && store.rows("signs").isEmpty)
        assert(store.message.contains("isolated disk failure"))
        print("PASS failure: no ritual or sign; pending released; error retained")
    }
}
runCase(success:true,stay:true);runCase(success:true,stay:false);runCase(success:true,stay:true,reduceMotion:true);runCase(success:false,stay:true)
'''.replace('ACTION', action)
            (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            (folder/'main.swift').write_text(source+harness)
            binary=folder/'check'
            built=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),str(ROOT/'native/v1/Presentation.swift'),str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT/'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),str(folder/'main.swift'),'-o',str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary),str(folder/'fixtures.json')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.count('PASS '),4)
            self.assertEqual((folder/'state.json').read_bytes(),saved,'Native replay must not write save')
            self.assertFalse((folder/'failure.json').exists())
            print(result.stdout.strip())

    def test_compact_sign_page_renders_without_another_desktop_scene(self):
        """A duplicated shrine/attendant scene breaks the single-vessel page."""
        source = (ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        harness = r'''
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let root = URL(fileURLWithPath:CommandLine.arguments[1])
let output = URL(fileURLWithPath:CommandLine.arguments[2])
UIArtifactLibrary.shared = UIArtifactLibrary(resourceRoot:root.appendingPathComponent("assets/production/ui"))
assert(UIArtifactLibrary.shared.image("divination-vessel") != nil)
ShrineCeremonyView.paperImage = AttendantArtwork.load(from:root.appendingPathComponent("assets/production/A01"))?.propFrame("paper")?.image
assert(ShrineCeremonyView.paperImage != nil)
func desktopSceneCount(_ view:NSView) -> Int {
    (view is TianmuView ? 1 : 0) + view.subviews.reduce(0) { $0 + desktopSceneCount($1) }
}
func render<V:View>(_ content:V,name:String,width:CGFloat,height:CGFloat) -> NSHostingView<V> {
    let view=NSHostingView(rootView:content)
    view.sizingOptions=[]
    let window=NSWindow(contentRect:NSRect(x:0,y:0,width:width,height:height),styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false; window.contentView=view
    view.frame=NSRect(x:0,y:0,width:width,height:height)
    view.layoutSubtreeIfNeeded()
    assert(abs(view.bounds.width-width)<0.5 && abs(view.bounds.height-height)<0.5,
           "The hidden harness must preserve its requested viewport")
    RunLoop.current.run(until:Date().addingTimeInterval(0.1))
    view.layoutSubtreeIfNeeded()
    let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    try! bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name+".png"))
    assert(!window.isVisible,"Layout verification must not open a visible window")
    assert(desktopSceneCount(view)==0,"The sign page must not duplicate the desktop shrine and attendant")
    return view
}
let store=Store(), presentation=PresentationState()
store.commandSink={ _,_,_ in fatalError("Rendering must not send a command") }
store.state=["game_timezone":"UTC", "signs":[]]
let vessel=render(ShrineCeremonyView(store:store,presentation:presentation,request:{fatalError("Rendering must not draw a sign")},requesting:false),
    name:"vessel",width:320,height:204)
assert(vessel.fittingSize.height <= 204,"The isolated sign vessel must fit a compact 204pt stage")
_ = render(ShrinePage(store:store,presentation:presentation).padding(16),name:"empty",width:352,height:400)
let today=Date().formatted(Date.ISO8601FormatStyle(timeZone:.gmt).year().month().day().dateSeparator(.dash))
store.state=["game_timezone":"UTC", "signs":[["date":today,"verse":"一线牵来千里意，\n满庭春色待君归。", "meaning":"将眼前的小事做好，也给远处的消息留些余地。今日所得不必急于解释，安静看清自己的心意。"]]]
_ = render(ShrinePage(store:store,presentation:presentation).padding(16),name:"saved",width:352,height:420)
presentation.open("求签")
store.message=""
let panel=render(PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{},capture:{fatalError("Seeking a sign must not capture insects")}),
    name:"panel-saved",width:360,height:440)
func scrolls(_ view:NSView)->[NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(scrolls)
}
let scroll=scrolls(panel).first!
let document=scroll.documentView!, clip=scroll.contentView
assert(document.bounds.width <= clip.bounds.width+0.5,"Sign result must not overflow horizontally")
let end=max(0,document.bounds.height-clip.bounds.height)
clip.scroll(to:NSPoint(x:0,y:end)); scroll.reflectScrolledClipView(clip)
assert(abs(clip.bounds.minY-end)<1,"The complete sign must remain scroll reachable")
panel.layoutSubtreeIfNeeded()
let bottom=panel.bitmapImageRepForCachingDisplay(in:panel.bounds)!
panel.cacheDisplay(in:panel.bounds,to:bottom)
try! bottom.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("panel-saved-bottom.png"))
print("LAYOUT sign panel 360x440 document=\(document.bounds) viewport=\(clip.bounds)")
presentation.beginRitual(now:ProcessInfo.processInfo.systemUptime-10.5)
_ = render(ShrinePage(store:store,presentation:presentation).padding(16),name:"drawing",width:352,height:400)
presentation.skipRitual()
_ = render(ShrineCeremonyView(store:store,presentation:presentation,request:{fatalError("Rendering must not draw a sign")},requesting:true),
    name:"requesting",width:320,height:204)
assert(store.process == nil,"Visual checks must not start a backend")
print("PASS compact shrine: standalone vessel; empty/saved/drawing/requesting hidden renders; no duplicate scene")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-sign-layout-') as directory:
            folder=Path(directory)
            (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            (folder/'main.swift').write_text(source+harness)
            sources=['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift','InsectArtwork.swift','TimerControls.swift','BrandArtwork.swift','WeatherAtmosphere.swift','LeisureViews.swift']
            binary=folder/'check'
            built=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*[str(ROOT/'native/v1'/name) for name in sources],str(folder/'main.swift'),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            output=ROOT/'evidence/1.0/170-shrine'
            output.mkdir(exist_ok=True)
            result=subprocess.run([str(binary),str(ROOT),str(output)],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())
