"""171 desktop-only fortune routing with injected receipt, clock and presenters."""
import unittest
from tests.test_capture_host_sequence import prepare_harness, run_scenario

HARNESS = r'''
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let host=ApplicationHost()
host.overlay=OverlayWindow(contentRect:NSRect(x:100,y:100,width:370,height:190),styleMask:[.borderless],backing:.buffered,defer:false)
host.overlay.isReleasedWhenClosed=false
host.scene=TianmuView(frame:host.overlay.contentView!.bounds);host.scene.persistLegacyFrame=false
host.scene.attendantArtwork=nil;host.scene.shrineArtwork=nil
host.overlay.contentView=host.scene;host.scene.attach(window:host.overlay)
host.panel=NSWindow(contentRect:.zero,styleMask:[.titled],backing:.buffered,defer:false)
host.panel.isReleasedWhenClosed=false
var now:TimeInterval=100,requested:[String]=[],receipts:[(Bool)->Void]=[],shown:[NSWindow]=[]
host.fortuneClock={now};host.fortuneReduceMotion={false}
host.availableScreens={ [NSRect(x:0,y:0,width:1440,height:900)] }
host.panelPresenter={shown.append($0)};host.fortunePresenter={shown.append($0)}
host.overlayPresenter={shown.append($0)};host.timerTools.present={shown.append($0)}
host.store.state=["game_timezone":"UTC","signs":[],"onboarding":"skipped"]
host.store.commandSink={action,_,done in
    if action == "sign" || action == "onboarding_visit" { requested.append(action);if let done { receipts.append(done) } }
}
func require(_ value:@autoclosure()->Bool,_ why:String) { if !value() { fputs("FAIL: \(why)\n",stderr);exit(1) } }
func saved() { host.store.state["signs"]=[["date":currentSignDate(state:host.store.state),"verse":"竹影移墙上，茶烟散案头。","meaning":"留一刻，理清眼前事。"]] }
func begin() {
    host.openRoute("求签")
    require(requested==["sign"] && host.fortuneRequesting,"One initial request only")
    require(host.presentation.route==nil && host.fortuneWindow==nil && shown.isEmpty,"No panel or result before saved receipt")
    require(host.presentation.ritualElapsed(now:now)==nil,"No ceremony before receipt")
}
switch CommandLine.arguments[1] {
case "saved_then_five_seconds":
    begin();host.requestFortune();require(requested.count==1,"Pending click cannot duplicate sign")
    saved();receipts[0](true)
    require(host.presentation.ritualElapsed(now:now)==0,"Saved receipt starts desktop gesture")
    now=104.99;host.refreshFortune();require(shown.isEmpty,"No premature result")
    now=105;host.refreshFortune()
    require(shown.count==1 && host.fortuneWindow===shown[0],"At five seconds reveal standalone sign")
    require(host.presentation.route==nil && host.scene.ceremonyElapsed==nil,"Shared panel stays closed and gesture ends")
    host.refreshFortune();require(shown.count==1,"No repeated reveal")
case "failed_save":
    begin();host.store.message="保存失败";receipts[0](false)
    require(host.presentation.ritualElapsed(now:now)==nil && host.fortuneWindow != nil,"Failure never plays successful gesture")
    require(host.store.rows("signs").isEmpty,"Failure does not invent a sign")
case "same_day":
    saved();host.openRoute("神前")
    require(requested.isEmpty && shown.count==1,"Same-day legacy route directly shows saved sign")
    require(host.presentation.ritualElapsed(now:now)==nil,"No repeated wait")
case "late_receipt":
    begin();host.openRoute("设置");saved();receipts[0](true)
    require(host.fortuneWindow==nil && host.presentation.ritualElapsed(now:now)==nil,"Explicit route change discards late animation and card")
    require(host.presentation.route=="设置","Late reply cannot replace current task")
case "sleep_pending":
    begin();host.sleepNow();saved();receipts[0](true);now=120;host.refreshFortune()
    require(host.fortuneWindow==nil && host.presentation.ritualElapsed(now:now)==nil,"Sleep invalidates late receipt and reveal")
case "timer_pending":
    begin();host.showTimer();saved();receipts[0](true);now=120;host.refreshFortune()
    require(host.fortuneWindow==nil && host.presentation.ritualElapsed(now:now)==nil,"Quick timer invalidates late receipt and reveal")
case "hidden_request":
    host.hidePet();host.requestFortune();require(!host.petHidden && requested==["sign"],"Explicit sign restores hidden scene")
    saved();receipts[0](true);now=105;host.refreshFortune()
    require(host.fortuneWindow != nil,"Restored scene reveals the saved sign")
case "reduce_motion":
    host.fortuneReduceMotion={true};begin();saved();receipts[0](true)
    require(shown.count==1 && host.presentation.ritualElapsed(now:now)==nil,"Reduced motion reveals immediately after saved receipt")
case "skip_and_hide":
    begin();saved();receipts[0](true);now=101;host.requestFortune()
    require(shown.count==1 && requested.count==1 && host.presentation.ritualElapsed(now:now)==nil,"Second click directly reveals saved sign")
    host.hidePet();now=120;host.refreshFortune();require(host.fortuneWindow==nil && shown.count==1,"Hide cannot reveal a late card")
case "midnight":
    begin()
    host.store.state["daily_sign_date"]="2032-04-05"
    host.store.state["signs"]=[["date":"2032-04-05","verse":"旧日已保存的签","meaning":"已落盘"]]
    receipts[0](true);now=105;host.refreshFortune()
    let card=(host.fortuneWindow!.contentView as! NSHostingView<DesktopFortuneCard>).rootView
    require(card.sign?.dateKey=="2032-04-05","Reveal must retain receipt date even when system date has advanced")
case "midnight_skip":
    begin()
    host.store.state["daily_sign_date"]="2032-04-05"
    host.store.state["signs"]=[["date":"2032-04-05","verse":"旧日已保存的签","meaning":"已落盘"]]
    receipts[0](true);now=101;host.requestFortune()
    let card=(host.fortuneWindow!.contentView as! NSHostingView<DesktopFortuneCard>).rootView
    require(requested==["sign"] && card.sign?.dateKey=="2032-04-05","Skipping after midnight must reveal saved result without a second sign request")
case "onboarding":
    host.store.state["onboarding"]="shrine";begin();saved();receipts[0](true)
    require(requested==["sign","onboarding_visit"],"Desktop-only entry still advances first visit")
    require(!host.panel.isVisible,"Onboarding never needs a panel")
default:fatalError("unknown")
}
require(!host.panel.isVisible && !host.overlay.isVisible && shown.allSatisfy{!$0.isVisible},"No real window displayed")
require(host.store.process==nil,"No backend worker")
host.dismissFortune(cancelPending:true)
print("PASS \(CommandLine.arguments[1]): NO_VISIBLE_WINDOWS_NO_WORKER_NO_REAL_SAVE")
'''

class DesktopFortuneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): prepare_harness(cls, 'tianmu-desktop-fortune-', HARNESS)
    def test_saved_receipt_then_five_second_desktop_reveal(self): run_scenario(self,'saved_then_five_seconds')
    def test_failed_save_has_no_success_animation(self): run_scenario(self,'failed_save')
    def test_same_day_and_legacy_route_skip_wait(self): run_scenario(self,'same_day')
    def test_navigation_discards_late_reply(self): run_scenario(self,'late_receipt')
    def test_reduced_motion_reveals_after_save(self): run_scenario(self,'reduce_motion')
    def test_skip_and_hide_do_not_duplicate(self): run_scenario(self,'skip_and_hide')
    def test_sleep_cancels_late_receipt(self): run_scenario(self,'sleep_pending')
    def test_quick_timer_cancels_late_receipt(self): run_scenario(self,'timer_pending')
    def test_explicit_sign_restores_hidden_scene(self): run_scenario(self,'hidden_request')
    def test_desktop_entry_preserves_onboarding(self): run_scenario(self,'onboarding')

    def test_midnight_retains_saved_receipt_date(self): run_scenario(self,"midnight")
    def test_midnight_skip_keeps_original_result(self): run_scenario(self,"midnight_skip")
