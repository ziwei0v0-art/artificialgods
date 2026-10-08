"""Real Store/host/settings paths with hidden windows and recorded transport only."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.desktop_motion_fixture import with_desktop_motion_fixture

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
final class LogicalPanel: NSWindow {
    var presented = false
    override var isVisible: Bool { presented }
    override func orderOut(_ sender: Any?) { presented = false; super.orderOut(sender) }
}
let host = ApplicationHost()
host.overlay = OverlayWindow(contentRect:NSRect(x:-140,y:12,width:80,height:50),styleMask:[.borderless],backing:.buffered,defer:false)
host.scene = TianmuView(frame:NSRect(x:0,y:0,width:80,height:50)); host.overlay.contentView = host.scene
let panel = LogicalPanel(contentRect:NSRect(x:0,y:0,width:480,height:580),styleMask:[.titled],backing:.buffered,defer:false)
panel.isReleasedWhenClosed = false; host.panel = panel
host.availableScreens = { [NSRect(x:-1200,y:0,width:1200,height:800)] }
host.panelPresenter = { _ in panel.presented = true }
host.overlayPresenter = { _ in }
host.fortunePresenter = { _ in }
host.fortuneReduceMotion = { false }
host.captureFocus = { _,_ in }
host.desktopInsects = DesktopInsects(screens:[DesktopInsectScreen(id:"left",frame:NSRect(x:-1200,y:0,width:1200,height:800))],windowPresenter:{_ in})
host.onboardingGuide = OnboardingGuide(present:{_ in})
host.configureOnboarding(); host.configureSceneState()
var requests:[[String:Any]] = []
host.store.requestSink = { requests.append($0) }
var signSaved = false
func state(_ step:String) -> [String:Any] {
    var value:[String:Any] = ["onboarding":step,"game_timezone":"Pacific/Auckland","timer":["status":"running","mode":"countdown","clock_timezone":"Asia/Shanghai"],"coins":7]
    if signSaved {
        let date = currentSignDate(state:value)
        value["daily_sign_date"] = date
        value["signs"] = [["date":date,"verse":"檐前新叶动，窗下有微风。","meaning":"先做一件小事。"]]
    }
    return value
}
func incoming(_ step:String) {
    host.store.receive(try! JSONSerialization.data(withJSONObject:["ok":true,"state":state(step)])+Data([10]))
}
func answer(_ ok:Bool, _ step:String) {
    host.store.receive(try! JSONSerialization.data(withJSONObject:["id":requests.last(where: { $0["action"] as? String != "sale_cancel" })!["id"]!,"ok":ok,"state":state(step),"error":ok ? "" : "样例保存失败"])+Data([10]))
}
func relevant() -> [[String:Any]] { requests.filter { ($0["action"] as? String)?.hasPrefix("onboarding_") == true } }
switch CommandLine.arguments[1] {
case "navigation":
    incoming("shrine")
    assert(host.onboardingGuide.step == "shrine" && relevant().isEmpty)
    let preview = PanelView(store:host.store,presentation:host.presentation,adjust:{_ in},hide:{},dismiss:{})
    preview.selectPage("神前")
    assert(relevant().isEmpty, "View construction/fixture navigation is not a visit")
    let real = PanelView(store:host.store,presentation:host.presentation,adjust:{_ in},hide:{},dismiss:{},changeRoute:{host.openRoute($0)})
    real.selectPage("神前"); real.selectPage("神前")
    assert(requests.filter{$0["action"] as? String == "sign"}.count == 1)
    assert(relevant().isEmpty && !panel.isVisible && host.fortuneWindow == nil,
           "Desktop fortune must wait for the saved sign receipt, without opening the old panel")
    signSaved = true; answer(true,"shrine")
    assert(relevant().count == 1 && relevant()[0]["page"] as? String == "神前",
           "A saved desktop sign counts the visit even while the shared panel stays closed")
    assert(!panel.isVisible && !host.onboardingGuide.actionButton.isEnabled)
    answer(false,"shrine")
    assert(host.onboardingGuide.isPresented && host.onboardingGuide.actionButton.isEnabled && host.scene.ceremonyElapsed == 0)
    host.onboardingGuide.actionButton.performClick(nil)
    assert(relevant().count == 2, "Retrying failed onboarding during the ceremony must save the visit again")
    assert(host.scene.ceremonyElapsed == nil && host.fortuneWindow != nil,
           "The first retry finishes the ceremony and shows its already saved sign")
    answer(false,"shrine")
    assert(host.onboardingGuide.isPresented && host.onboardingGuide.actionButton.isEnabled)
    host.onboardingGuide.actionButton.performClick(nil)
    assert(relevant().count == 3, "Retrying failed onboarding after the ceremony must save the same-day visit again")
    assert(host.scene.ceremonyElapsed == nil && host.fortuneWindow != nil && !panel.isVisible)
    assert(requests.filter{$0["action"] as? String == "sign"}.count == 1,
           "Retrying onboarding cannot draw another sign")
    answer(true,"capture")
    host.openRoute("虫瓶")
    assert(relevant().count == 3, "Out-of-order visits cannot complete capture")
    incoming("bottle")
    host.dismissPanel(); host.panelPresenter = { _ in }; real.selectPage("虫瓶")
    assert(relevant().count == 3, "An unshown bottle panel must not count as a visit")
    host.panelPresenter = { _ in panel.presented = true }; real.selectPage("虫瓶")
    assert(relevant().count == 4 && relevant().last!["page"] as? String == "虫瓶")
    answer(true,"done")
    assert(!host.onboardingGuide.isPresented)
case "skip":
    incoming("shrine")
    host.onboardingGuide.skipButton.performClick(nil); host.onboardingGuide.skipButton.performClick(nil)
    assert(relevant().count == 1 && host.onboardingGuide.isPresented)
    assert(!host.onboardingGuide.actionButton.isEnabled)
    incoming("shrine")
    assert(!host.onboardingGuide.skipButton.isEnabled, "Ticks must not unlock a pending save")
    answer(false,"shrine")
    assert(host.onboardingGuide.isPresented && host.onboardingGuide.skipButton.isEnabled)
    host.onboardingGuide.skipButton.performClick(nil); answer(true,"skipped")
    assert(!host.onboardingGuide.isPresented)
    incoming("skipped"); assert(!host.onboardingGuide.isPresented)
case "visibility":
    incoming("capture")
    host.onboardingGuide.actionButton.performClick(nil)
    assert(!host.desktopInsects!.isCapturing && !host.onboardingGuide.isPresented && relevant().isEmpty, "Acknowledging a passive hint must not arm capture or advance progress")
    incoming("capture"); assert(!host.onboardingGuide.isPresented)
    host.onboardingCaptureHintDismissed = false; host.refreshOnboarding()
    assert(host.onboardingGuide.isPresented)
    host.sleepNow(); incoming("capture"); assert(!host.onboardingGuide.isPresented)
    host.desktopInsects!.update(rows:[["id":"sleep-insect","x":0.5,"y":0.5,"color":"普通褐色"]])
    host.updateInsectPointer(host.desktopInsects!.positions[0].point,buttonsPressed:0)
    assert(!host.desktopInsects!.isNaturalHandleVisible, "Sleep must suppress pointer polling as well as the guide")
    host.wakeNow(); incoming("capture"); assert(host.onboardingGuide.isPresented)
    host.hidePet(); incoming("capture"); assert(!host.onboardingGuide.isPresented)
    host.showPet(); assert(host.onboardingGuide.isPresented)
    incoming("legacy"); assert(!host.onboardingGuide.isPresented)
    host.store.state = [:]; host.refreshOnboarding(); assert(!host.onboardingGuide.isPresented)
case "timezone":
    incoming("legacy")
    let controls = host.store.gameSettings
    assert(controls.savedTimezone == "Pacific/Auckland" && controls.timezones.contains("Pacific/Auckland"))
    assert(Set(controls.timezones).count == controls.timezones.count && controls.timezones.contains("UTC"))
    controls.draftTimezone = "UTC"; incoming("legacy")
    assert(controls.draftTimezone == "UTC" && requests.isEmpty, "Choosing a draft or receiving a tick must not save/reset it")
    let timer = NSDictionary(dictionary:host.store.timer)
    controls.applyTimezone(); controls.applyTimezone()
    assert(requests.count == 1 && requests[0]["action"] as? String == "game_timezone_set" && requests[0]["timezone"] as? String == "UTC")
    assert(controls.isSubmitting && controls.savedTimezone == "Pacific/Auckland")
    answer(false,"legacy")
    assert(!controls.isSubmitting && controls.savedTimezone == "Pacific/Auckland" && !controls.feedback.isEmpty)
    controls.applyTimezone()
    var next = state("legacy"); next["game_timezone"] = "UTC"
    host.store.receive(try! JSONSerialization.data(withJSONObject:["id":requests.last!["id"]!,"ok":true,"state":next])+Data([10]))
    assert(controls.savedTimezone == "UTC" && !controls.isSubmitting && !controls.canApply)
    assert(timer.isEqual(to:host.store.timer), "Game zone must not edit clock or running timer")
    let count = requests.count; controls.applyTimezone(); assert(requests.count == count)
default: fatalError("Unknown scenario")
}
host.dismissFortune(cancelPending:true); host.onboardingGuide.dismiss(); host.desktopInsects?.close(); panel.orderOut(nil)
assert(!host.overlay.isVisible && host.store.process == nil && host.onboardingGuide.window?.isVisible != true)
print("PASS: \(CommandLine.arguments[1]); no worker, real save, visible window or permissions")
'''
class OnboardingHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='tianmu-onboarding-host-')
        cls.addClassCleanup(cls.temp.cleanup)
        folder=Path(cls.temp.name)
        (folder/'main.swift').write_text(with_desktop_motion_fixture((ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]+HARNESS))
        (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        cls.binary=folder/'check'
        build=subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),
            *(str(ROOT/'native/v1'/name) for name in ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift', 'InsectArtwork.swift','TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']),
            str(folder/'main.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
        if build.returncode: raise AssertionError(build.stderr)
def install_case(name):
    def test(self):
        run=subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr); self.assertIn('PASS:',run.stdout)
        print(run.stdout.strip())
    setattr(OnboardingHostTests,'test_'+name,test)
for name in ['navigation','skip','visibility','timezone']: install_case(name)
