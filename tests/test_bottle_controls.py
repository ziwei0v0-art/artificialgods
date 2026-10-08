"""Bottle intent and discovery replies through the real Store, without a worker."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
final class QuietNotifications: TimerNotificationClient {
    var onOpen:(()->Void)?
    var submitted = 0
    func settings(_ done:@escaping(NotificationAccess)->Void) { done(.authorized) }
    func requestPermission(_ done:@escaping(String?)->Void) { fatalError("No permission requests") }
    func submit(_ done:@escaping(String?)->Void) { submitted += 1; done(nil) }
}
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let notification = QuietNotifications(), store = Store(notificationClient:QuietNotifications())
var commands:[(String,[String:Any])] = []
var completion:((Bool)->Void)?
store.commandSink = { action, values, done in commands.append((action,values)); completion = done }
store.state = ["coins":17,"capture_seconds":86000,"bottle":[
    ["color":"普通褐色","female":2,"male":3,"price":1],
    ["color":"中褐色","female":0,"male":0,"price":3]],
    "discoveries":[],"timer":["status":"running","mode":"countdown"]]
let controls = store.bottleControls
let before = NSDictionary(dictionary:store.state)
switch CommandLine.arguments[1] {
case "selection":
    assert(controls.totalInventory == 5 && !controls.releaseExpanded)
    controls.beginRelease()
    controls.releaseSex = "雌"; controls.releaseCount = 2
    assert(controls.releaseAvailable == 2)
    controls.dismissRelease()
    controls.count = 5
    controls.previewSale()
    assert(commands.count == 1 && commands[0].0 == "sale_preview")
    assert(commands[0].1["count"] as? Int == 5 && commands[0].1["sex"] == nil)
    assert(before.isEqual(to:store.state), "UI intent must not edit inventory or capture time")
case "release":
    controls.beginRelease(); controls.releaseSex = "雄"; controls.releaseCount = 2
    assert(commands.isEmpty)
    controls.release(); controls.release()
    assert(commands.count == 1 && commands[0].0 == "release")
    assert(commands[0].1["sex"] as? String == "M" && commands[0].1["count"] as? Int == 2)
    completion?(false)
    assert(controls.releaseExpanded && !controls.isSubmitting)
    controls.release(); completion?(true)
    assert(!controls.releaseExpanded)
    assert(before.isEqual(to:store.state))
case "sale":
    controls.count = 3; controls.previewSale(); completion?(true)
    store.sale = ["token":"fixed-selection","count":3,"amount":3]
    controls.beginRelease(); assert(!controls.releaseExpanded)
    controls.previewSale(); assert(commands.count == 1)
    controls.confirmSale(); controls.confirmSale()
    assert(commands.count == 2 && commands.last!.1["token"] as? String == "fixed-selection")
    completion?(false)
    assert(store.sale != nil && !controls.isSubmitting)
    controls.confirmSale(); completion?(true)
    assert(store.sale == nil)
case "cancel_pending":
    store.commandSink = nil
    var requests:[[String:Any]] = []
    store.requestSink = { requests.append($0) }
    controls.previewSale()
    let first = requests.last!["id"] as! Int
    store.cancelSale()
    let oldReply:[String:Any] = ["id":first,"ok":true,"sale":["token":"late-preview","count":1,"amount":1],"state":store.state]
    store.receive(try! JSONSerialization.data(withJSONObject:oldReply)+Data([10]))
    assert(store.sale == nil && !controls.isSubmitting, "A late preview must be ignored and unlock its completion")
    controls.previewSale()
    let second = requests.last!["id"] as! Int
    let accepted:[String:Any] = ["id":second,"ok":true,"sale":["token":"new-preview","count":1,"amount":1],"state":store.state]
    store.receive(try! JSONSerialization.data(withJSONObject:accepted)+Data([10]))
    assert(store.sale?["token"] as? String == "new-preview")
    controls.confirmSale()
    var afterSale = store.state
    afterSale["coins"] = 18
    afterSale["bottle"] = [["color":"普通褐色","female":1,"male":3,"price":1]]
    store.receive(try! JSONSerialization.data(withJSONObject:["id":requests.last!["id"]!,"ok":true,"state":afterSale])+Data([10]))
    assert(store.sale == nil)
    store.receive(try! JSONSerialization.data(withJSONObject:accepted)+Data([10]))
    assert(store.sale == nil, "A consumed preview cannot reappear after successful sale")
    assert(NSDictionary(dictionary:store.state).isEqual(to:afterSale), "A replayed preview must not roll back inventory or coins")
case "snapshot":
    controls.count = 5
    store.state["bottle"] = [["color":"普通褐色","female":1,"male":1,"price":1]]
    assert(controls.saleCount == 2)
    store.state["bottle"] = [["color":"普通褐色","female":4,"male":4,"price":1]]
    assert(controls.saleCount == 2, "New inventory must not enlarge an existing selection")
    controls.previewSale()
    assert(commands.last!.1["count"] as? Int == 2)
    completion?(true)
    store.sale = ["token":"locked","count":2,"amount":2]
    store.state["bottle"] = [["color":"普通褐色","female":9,"male":9,"price":1]]
    assert(store.sale?["count"] as? Int == 2 && store.sale?["amount"] as? Int == 2)
case "host_notice":
    let host = ApplicationHost()
    host.overlay = OverlayWindow(contentRect:NSRect(x:-100,y:10,width:60,height:40),styleMask:[.borderless],backing:.buffered,defer:false)
    host.scene = TianmuView(frame:NSRect(x:0,y:0,width:60,height:40)); host.overlay.contentView = host.scene
    host.panel = NSWindow(contentRect:.zero,styleMask:[.titled],backing:.buffered,defer:false)
    host.panel.isReleasedWhenClosed = false
    host.store.commandSink = { _,_,done in done?(true) }
    host.availableScreens = { [NSRect(x:-1200,y:0,width:1200,height:800)] }
    var dismissals:[()->Void] = []
    host.discoveryNotice = DiscoveryNotice(present:{_ in}, schedule:{_,done in dismissals.append(done)})
    host.configureDiscovery()
    func found(_ names:[String], _ fresh:[String]) {
        host.store.receive(try! JSONSerialization.data(withJSONObject:["ok":true,"new_discoveries":fresh,
            "state":["discoveries":names.map { ["color":$0,"found":true] as [String:Any] }]])+Data([10]))
    }
    found(["普通褐色"],["普通褐色"])
    assert(host.discoveryNotice.isPresented && host.presentation.route == nil)
    assert(host.discoveryNotice.window?.isVisible == false && !host.overlay.isVisible && !host.panel.isVisible)
    host.hidePet(); assert(!host.discoveryNotice.isPresented)
    found(["普通褐色","白色"],["白色"])
    assert(!host.discoveryNotice.isPresented && dismissals.count == 1)
    host.petHidden = false
    found(["普通褐色","白色"],["白色"])
    assert(!host.discoveryNotice.isPresented, "Hidden discoveries must not replay later")
    found(["普通褐色","白色","深褐色"],["深褐色"])
    assert(host.discoveryNotice.isPresented)
    host.sleepNow(); assert(!host.discoveryNotice.isPresented)
    assert(host.store.process == nil)
case "empty":
    controls.chooseColor("中褐色")
    assert(controls.totalInventory == 5 && controls.available == 0)
    let n = commands.count
    controls.previewSale(); controls.beginRelease(); controls.release()
    assert(commands.count == n && !controls.releaseExpanded)
    store.state["bottle"] = []
    assert(controls.totalInventory == 0)
case "discovery":
    var notices:[[String]] = []
    store.onDiscovery = { notices.append($0) }
    func reply(_ found:[String], _ fresh:[String], ok:Bool = true) -> Data {
        let rows = ["普通褐色","中褐色","深褐色","白色"].map { ["color":$0,"found":found.contains($0)] as [String:Any] }
        return try! JSONSerialization.data(withJSONObject:["ok":ok,"state":["discoveries":rows],"new_discoveries":fresh])+Data([10])
    }
    store.receive(reply(["普通褐色"],[]))
    assert(notices.isEmpty, "Historic discoveries do not replay on initial snapshot")
    let data = reply(["普通褐色","中褐色","白色"],["中褐色","白色","白色"])
    store.receive(data.prefix(9)); assert(notices.isEmpty)
    store.receive(data.dropFirst(9)); assert(notices == [["中褐色","白色"]])
    store.receive(data); assert(notices.count == 1)
    store.receive(reply(["普通褐色","中褐色","白色"],["深褐色"],ok:false))
    assert(notices.count == 1)
    store.receive(reply(["普通褐色","中褐色","白色","深褐色"],["深褐色"]))
    assert(notices == [["中褐色","白色"],["深褐色"]])
case "simultaneous":
    var notices = 0, reminders = 0, sounds = 0
    store.onDiscovery = { _ in notices += 1 }; store.onReminder = { reminders += 1 }; store.playSound = { sounds += 1 }
    store.receive(try! JSONSerialization.data(withJSONObject:["ok":true,"new_discoveries":["普通褐色"],
        "events":["timer_expired"],"state":["discoveries":[["color":"普通褐色","found":true]],
        "timer":["sound_enabled":false,"widget_enabled":true,"notification_enabled":false]]])+Data([10]))
    assert(notices == 1 && reminders == 1 && sounds == 0)
default: fatalError("Unknown case")
}
assert(store.process == nil)
print("PASS: \(CommandLine.arguments[1]); no worker, save, visible window or permissions")
'''

class BottleControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='tianmu-bottle-controls-')
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        source = (ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        (folder/'main.swift').write_text(source+HARNESS)
        (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
        cls.binary = folder/'check'
        build = subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),
            *(str(ROOT/'native/v1'/name) for name in ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift', 'InsectArtwork.swift','TimerControls.swift', 'BrandArtwork.swift', 'WeatherAtmosphere.swift', 'LeisureViews.swift']),
            str(folder/'main.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
        if build.returncode: raise AssertionError(build.stderr)

def install_case(name):
    def test(self):
        run = subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertIn('PASS:',run.stdout)
        print(run.stdout.strip())
    setattr(BottleControlsTests,'test_'+name,test)
for name in ['selection','release','sale','cancel_pending','snapshot','host_notice','empty','discovery','simultaneous']: install_case(name)
