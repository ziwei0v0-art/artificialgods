"""Fake notification transport only; no system permissions, delivery or windows."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class SystemNotificationTests(unittest.TestCase):
    def test_preference_is_independent_and_persisted(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'; app=ApplicationService(path)
            result=app.handle({'action':'timer_preferences','notification_enabled':False})
            self.assertIs(result['state']['timer'].get('notification_enabled'),False)
            self.assertTrue(result['state']['timer']['sound_enabled'])
            self.assertTrue(result['state']['timer']['widget_enabled'])
            self.assertIs(ApplicationService(path).snapshot(0)['timer']['notification_enabled'],False)
            self.assertFalse(app.handle({'action':'timer_preferences','notification_enabled':'yes'})['ok'])
    def test_expiry_routes_without_permission_or_losing_fallback(self):
        source=(ROOT/'native/v1/main.swift').read_text().split('let application = NSApplication.shared')[0]
        harness=r'''
final class FakeNotifications: TimerNotificationClient {
 var access: NotificationAccess = .notDetermined
 var requests=0, sent=0, fail=false
 var onOpen: (() -> Void)?
 func settings(_ done:@escaping (NotificationAccess)->Void) { done(access) }
 func requestPermission(_ done:@escaping (String?)->Void) { requests += 1; done(nil) }
 func submit(_ done:@escaping (String?)->Void) { sent += 1; done(fail ? "fixture transport error" : nil) }
}
let fake=FakeNotifications()
let store=Store(notificationClient:fake)
var sounds=0, widgets=0
store.playSound={sounds += 1}; store.onReminder={widgets += 1}
assert(fake.requests == 0 && fake.sent == 0)
func event(_ enabled:Bool=true) {
 let reply:[String:Any] = ["state":["timer":["sound_enabled":true,"widget_enabled":true,"notification_enabled":enabled]],"events":["timer_expired"]]
 store.receive(try! JSONSerialization.data(withJSONObject:reply)+Data([10]))
}
for access in [NotificationAccess.notDetermined,.denied,.unavailable] {
 fake.access=access; event()
 assert(fake.sent == 0 && fake.requests == 0)
 assert(store.notifications.access == access)
}
assert(sounds == 3 && widgets == 3)
fake.access = .authorized; event()
assert(fake.sent == 1 && sounds == 4 && widgets == 4)
assert(store.notifications.deliveryText.contains("已提交"))
event(false); assert(fake.sent == 1 && sounds == 5 && widgets == 5)
fake.fail=true; event()
assert(fake.sent == 2 && sounds == 6 && widgets == 6)
assert(store.notifications.deliveryText.contains("失败"))
fake.fail=false; fake.access = .quiet; event()
assert(fake.sent == 3 && store.notifications.statusText.contains("横幅"))
let quiet:[String:Any] = ["state":["timer":["sound_enabled":false,"widget_enabled":false,"notification_enabled":true]],"events":["timer_expired"]]
store.receive(try! JSONSerialization.data(withJSONObject:quiet)+Data([10]))
assert(fake.sent == 4 && sounds == 7 && widgets == 7, "Independent switches changed fallback")
store.receive(try! JSONSerialization.data(withJSONObject:["ok":true])+Data([10]))
assert(fake.sent == 4, "Non-expiry reply must not notify")
store.notifications.refresh()
assert(fake.requests == 0, "Refresh/expiry must never request permission")
var opened=false; store.notifications.onOpenTimer={opened=true}; fake.onOpen?()
assert(opened)
print("PASS: authorized/denied/undetermined/unavailable/quiet, switch, failure fallback, click route; REAL_PERMISSION_REQUESTS=0 REAL_NOTIFICATIONS=0")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-notification-test-') as d:
            d=Path(d);(d/'main.swift').write_text(source+harness)
            (d/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            cmd=['swiftc','-framework','AppKit','-framework','SwiftUI',str(d/'Scene.swift'),str(ROOT/'native/v1/Presentation.swift'),str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'), str(ROOT/'native/v1/TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'),str(d/'main.swift'),'-o',str(d/'check')]
            build=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(d/'check')],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);print(run.stdout)

    def test_explicit_click_is_the_only_permission_request_path(self):
        # A missing state guard must fail; no live client is instantiated.
        source=(ROOT/'native/v1/Presentation.swift').read_text()
        harness=r'''
import Foundation
final class PermissionFake: TimerNotificationClient {
 var onOpen:(()->Void)?
 var access:NotificationAccess = .notDetermined
 var requests=0
 var pending:((String?)->Void)?
 func settings(_ done:@escaping(NotificationAccess)->Void) { done(access) }
 func requestPermission(_ done:@escaping(String?)->Void) { requests += 1; pending=done }
 func submit(_ done:@escaping(String?)->Void) { done(nil) }
}
for state in [NotificationAccess.denied,.authorized] {
 let fake=PermissionFake();fake.access=state
 let controller=TimerNotifications(client:fake)
 controller.refresh();controller.timerCompleted(enabled:true)
 assert(fake.requests == 0, "Background operations requested permission")
 controller.requestFromUserClick()
 assert(fake.requests == 0, "Forbidden access state requested permission")
}
let fake=PermissionFake()
let controller=TimerNotifications(client:fake)
assert(fake.requests == 0)
controller.refresh();controller.timerCompleted(enabled:true)
assert(fake.requests == 0)
controller.requestFromUserClick()
assert(fake.requests == 1 && controller.requesting)
controller.requestFromUserClick()
controller.refresh();controller.timerCompleted(enabled:true)
assert(fake.requests == 1, "Repeated click or background event duplicated in-flight request")
fake.access = .authorized
fake.pending?(nil)
assert(!controller.requesting && controller.access == .authorized)
controller.requestFromUserClick();controller.refresh();controller.timerCompleted(enabled:true)
assert(fake.requests == 1)
print("PASS explicit click: notDetermined=1, denied=0, authorized=0, duplicate click suppressed; refresh/expiry=0 additional; REAL_AUTHORIZATION_REQUESTS=0")
'''
        guard='guard access == .notDetermined, !requesting else { return }'
        self.assertEqual(source.count(guard),1)
        variants=[('negative-control',source.replace(guard,'guard !requesting else { return }')),('production',source)]
        with tempfile.TemporaryDirectory(prefix='tianmu-permission-click-') as folder:
            folder=Path(folder);(folder/'main.swift').write_text(harness)
            for name,body in variants:
                (folder/'Presentation.swift').write_text(body)
                build=subprocess.run(['swiftc',str(folder/'Presentation.swift'),str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True,timeout=60)
                self.assertEqual(build.returncode,0,build.stderr)
                run=subprocess.run([str(folder/'check')],capture_output=True,text=True,timeout=10)
                if name=='negative-control':
                    self.assertNotEqual(run.returncode,0)
                    self.assertIn('Forbidden access state requested permission',run.stderr)
                    print('EXPECTED_RED: temporary guard-removal exits',run.returncode,'with Forbidden access state requested permission')
                else:
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                    print(run.stdout.strip())
