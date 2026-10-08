"""Exit choices keep live tools independent, with hidden hosts and temporary prefs."""
import subprocess
import unittest
from tests import test_capture_host_sequence as fixture

HARNESS = fixture.BASE_HARNESS + r'''
switch CommandLine.arguments[1] {
case "choices":
    let url=URL(fileURLWithPath:CommandLine.arguments[2])
    let settings=SceneTransparencyStore(url:url)
    host.configureTransparency(settings)
    host.store.setExitAction(.hideCompanions); host.quit()
    require(host.petHidden && host.desktopInsectsHidden,"Second choice hides all game companions")
    global(.leftMouseDown,origin); global(.leftMouseDragged,finish); global(.leftMouseUp,finish); complete()
    require(captured.isEmpty && !layer.hasNaturalGesture,"Hidden flies cannot seed a new net")
    require(settings.restoreExitAction() == .hideCompanions,"Exit choice is persisted beside selected save")
    host.showPet(); host.store.setExitAction(.hideShrine); host.quit()
    require(host.petHidden && !host.desktopInsectsHidden,"First choice retains the insect layer")
    release(); complete(); require(captured == [["one"]],"First choice retains natural selection")
    var shutdowns=0
    host.terminateApplication={shutdowns += 1}
    host.store.setExitAction(.quitApplication); host.quit()
    require(shutdowns == 1,"Only the third configured choice requests application termination")
    require(settings.restoreExitAction() == .quitApplication,"Explicit whole-program choice survives restart")
    require(!commands.contains("sleep") && !commands.contains("quit"),"Hiding companions never shuts down or sleeps the worker")
case "keep_timer":
    host.store.state["timer"]=["mode":"countdown","status":"running","readout":"04:59","remaining_seconds":299,"countdown_seconds":300]
    let original=NSDictionary(dictionary:host.store.timer)
    host.timerTools.present={presented.append($0)}
    host.timerTools.showDetached(near:host.overlay.frame)
    require(host.timerTools.detachedPresented,"Detached timer fixture is presented through a suppressed presenter")
    for choice:SceneExitAction in [.hideShrine,.hideCompanions] {
        host.store.exitAction=choice; host.quit()
        require(host.timerTools.detachedPresented,"Both hide choices retain the detached timer display")
        require(original.isEqual(to:host.store.timer),"Hide choices do not change the running timer session")
        require(!commands.contains(where:{$0.hasPrefix("timer_")}),"Hiding art must not reset or pause a timer")
        host.showPet()
    }
    host.timerTools.dismissAll()
case "failed_preference":
    let url=URL(fileURLWithPath:CommandLine.arguments[2])
    try! Data("{\"transparency\":42,\"exitAction\":\"futureValue\"}".utf8).write(to:url)
    let settings=SceneTransparencyStore(url:url)
    require(settings.restoreExitAction() == .hideShrine && settings.restore() == 42,"Unknown exit value falls back safely without discarding other valid preferences")
    let blocked=url.deletingLastPathComponent().appendingPathComponent("blocked")
    try! "file".write(to:blocked,atomically:true,encoding:.utf8)
    host.configureTransparency(SceneTransparencyStore(url:blocked.appendingPathComponent("appearance.json")))
    host.store.setExitAction(.quitApplication)
    require(host.store.exitAction == .hideShrine && host.store.exitActionError.contains("未保存"),"A failed save cannot silently change exit behavior")
case "default_exit":
    host.quit()
    require(host.petHidden,"Default exit action hides the shrine instead of terminating the program")
    release(); complete()
    require(captured == [["one"]],"Default exit retains flies and the live service")
case "preserve_exit_preference":
    let url=URL(fileURLWithPath:CommandLine.arguments[2])
    try! Data("{\"transparency\":80,\"exitAction\":\"hideCompanions\"}".utf8).write(to:url)
    let appearance=SceneTransparencyStore(url:url)
    try! appearance.saveNaturalCapture(true)
    let saved=try! JSONSerialization.jsonObject(with:Data(contentsOf:url)) as! [String:Any]
    require(saved["exitAction"] as? String == "hideCompanions","Changing capture or opacity must preserve the independently chosen exit behavior")
case "hide_shrine":
    host.hidePet()
    require(host.petHidden && !host.overlay.isVisible,"Hide only the shrine and attendant")
    release(); complete(); passive()
    require(captured == [["one"]],"With the shrine hidden, flies and natural desktop capture continue")
    require(!commands.contains("quit") && !commands.contains("sleep"),"Hiding artwork must not stop the running service")
    host.showPet(); fresh("two"); release(); complete()
    require(captured == [["one"],["two"]],"Restoring the shrine does not duplicate or disable the next net")
default: fatalError("Unknown case")
}
finishedAudit()
'''


class ExitBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.prepare_harness(cls, 'tianmu-exit-behavior-', HARNESS)

    def check(self, case):
        run = subprocess.run([str(self.binary), case, str(self.folder / 'appearance.json')],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('NO_VISIBLE_WINDOWS_NO_WORKER_NO_REAL_SAVE', run.stdout)

    def test_hiding_shrine_retains_flies_and_natural_capture(self):
        self.check('hide_shrine')

    def test_default_exit_hides_shrine_without_stopping_service(self):
        self.check('default_exit')

    def test_other_preferences_preserve_saved_exit_choice(self):
        self.check('preserve_exit_preference')

    def test_three_choices_persist_and_dispatch_independently(self):
        self.check('choices')

    def test_both_hiding_choices_keep_visible_timer_and_session(self):
        self.check('keep_timer')

    def test_unknown_choice_and_failed_preference_save_are_safe(self):
        self.check('failed_preference')


if __name__ == '__main__':
    unittest.main()
