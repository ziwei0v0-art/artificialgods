"""Native menu dispatch and whole-application teardown with hidden test windows."""
import subprocess
import unittest
from tests import test_capture_host_sequence as fixture

HARNESS = fixture.BASE_HARNESS + r'''
func quitKey(_ flags:NSEvent.ModifierFlags, type:NSEvent.EventType = .keyDown, characters:String = "q")->NSEvent {
    NSEvent.keyEvent(with:type,location:.zero,modifierFlags:flags,timestamp:now,
        windowNumber:host.panel.windowNumber,context:nil,characters:characters,
        charactersIgnoringModifiers:characters,isARepeat:false,keyCode:12)!
}
switch CommandLine.arguments[1] {
case "local_quit_key":
    var requests=0
    host.terminateApplication={requests += 1}
    for choice:SceneExitAction in [.hideShrine,.hideCompanions,.quitApplication] {
        host.store.exitAction=choice
        for flags:NSEvent.ModifierFlags in [[.command],[.command,.capsLock]] {
            let input=quitKey(flags,characters:flags.contains(.capsLock) ? "Q":"q")
            let previous=requests
            require(host.handleLocalEvent(input) == nil,"Local Command-Q is consumed without an open status menu")
            require(requests == previous+1,"Command-Q always requests full termination, including scene hiding preferences")
        }
    }
    require(!host.petHidden && !host.desktopInsectsHidden,"Quit shortcut never follows scene hiding preferences")
case "other_keys_passthrough":
    var requests=0
    host.terminateApplication={requests += 1}
    for flags:NSEvent.ModifierFlags in [[],[.capsLock],[.command,.control],[.command,.option],
                                      [.command,.shift],[.command,.control,.option,.shift]] {
        let input=quitKey(flags)
        require(host.handleLocalEvent(input) === input,"Other Q key combinations retain their original event")
    }
    for input in [quitKey(.command,type:.keyUp),quitKey(.command,characters:"x")] {
        require(host.handleLocalEvent(input) === input,"Key-up and other command keys retain their original event")
    }
    require(requests == 0,"Only local Command-Q key-down may request termination")
case "global_quit_key_passthrough":
    var requests=0
    host.terminateApplication={requests += 1}
    let input=quitKey(.command)
    require(host.handleGlobalEvent(input,context:context()) === input,"The global event boundary leaves Command-Q untouched")
    require(requests == 0,"Another application's Command-Q must never terminate this app")
case "quit_ignores_scene_preference":
    let menu=host.makeStatusMenu()
    let item=menu.items.first{$0.title == "退出"}!
    var requests=0
    host.terminateApplication={requests += 1}
    for choice:SceneExitAction in [.hideShrine,.hideCompanions,.quitApplication] {
        host.store.exitAction=choice
        require(app.sendAction(item.action!,to:item.target,from:item),"Native menu quit action dispatches")
    }
    require(requests == 3,"Menu-bar quit always requests application termination, independent of scene hiding preference")
    require(item.title == "退出","Quit label remains concise")
case "native_menu":
    host.statusItem=NSStatusBar.system.statusItem(withLength:0)
    host.statusItem.isVisible=false
    host.configureStatusMenu()
    let menu=host.statusItem.menu!
    require(menu.delegate === host,"Status item owns the native NSMenu")
    let mask=NSEvent.EventTypeMask(rawValue:UInt64(host.statusItem.button!.sendAction(on:[.leftMouseUp,.rightMouseUp])))
    require(mask.contains(.rightMouseUp) && mask.contains(.leftMouseUp),"Both mouse buttons are routed to AppKit's menu")
    require(host.sceneMenuWindow == nil,"Status menu never allocates a wheel")
    let item=menu.items.first{$0.title == "退出"}!
    require(item.keyEquivalent == "q" && item.keyEquivalentModifierMask == .command,"Standard quit shortcut is available")
    let route=menu.items.first{$0.title == "虫瓶"}!
    require(app.sendAction(route.action!,to:route.target,from:route),"Native route remains actionable")
    require(host.presentation.route == "虫瓶","Route opens the existing product page")
    host.dismissPanel()
    NSStatusBar.system.removeStatusItem(host.statusItem); host.statusItem=nil
case "whole_application_cleanup":
    host.timerTools.present={presented.append($0)}
    host.timerTools.showDetached(near:host.overlay.frame)
    host.pointerTimer=Timer.scheduledTimer(withTimeInterval:10,repeats:true){_ in fatalError("Stale timer")}
    let oldTimer=host.pointerTimer!
    var replies:[Bool]=[]
    host.replyToTermination={replies.append($0)}
    require(host.applicationShouldTerminate(app) == .terminateLater,"Shutdown uses one bounded async completion")
    require(host.applicationShouldTerminate(app) == .terminateLater,"Repeated quit joins the same shutdown")
    require(!oldTimer.isValid && host.pointerTimer == nil,"Animation and pointer polling stop immediately")
    require(!host.timerTools.detachedPresented && host.petHidden && host.desktopInsectsHidden,"All companions and timer windows close")
    let presentations=presented.count
    host.openRoute("设置"); host.showPet(); host.showTimer(); host.showReminder(); host.requestFortune(); host.detachTimer()
    require(presented.count == presentations && host.reminderWindow == nil,"Late UI callbacks cannot reopen the application while quitting")
    let deadline=Date().addingTimeInterval(2)
    while replies.isEmpty && Date() < deadline { RunLoop.current.run(until:Date().addingTimeInterval(0.01)) }
    require(replies == [true],"The application approves termination once, even without a worker")
    require(host.applicationShouldTerminate(app) == .terminateNow,"Completed shutdown cannot become stuck waiting again")
    host.applicationWillTerminate(Notification(name:NSApplication.willTerminateNotification,object:app))
default: fatalError("Unknown case")
}
finishedAudit()
'''


class StatusMenuExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.prepare_harness(cls, 'zaoshen-status-menu-exit-', HARNESS)

    def check(self, case):
        run = subprocess.run([str(self.binary), case, str(self.folder / 'appearance.json'),
                              '--save-file', str(self.folder / 'unused-state.json')],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('NO_VISIBLE_WINDOWS_NO_WORKER_NO_REAL_SAVE', run.stdout)

    def test_status_quit_bypasses_every_scene_hiding_choice(self):
        self.check('quit_ignores_scene_preference')

    def test_local_command_q_consumes_event_and_bypasses_scene_hiding_preferences(self):
        self.check('local_quit_key')

    def test_other_keys_and_key_up_do_not_request_termination(self):
        self.check('other_keys_passthrough')

    def test_global_command_q_does_not_request_termination(self):
        self.check('global_quit_key_passthrough')

    def test_status_bar_owns_native_menu_for_both_mouse_buttons(self):
        self.check('native_menu')

    def test_whole_application_cleanup_is_immediate_and_idempotent(self):
        self.check('whole_application_cleanup')


if __name__ == '__main__':
    unittest.main()
