"""Pure appearance-sidecar fixtures; no app, host, window, worker or game save."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRELUDE = r'''
import AppKit
import Foundation
func check(_ condition:@autoclosure () throws -> Bool,_ message:String) {
    do { if try condition() { return } }
    catch { fputs("ERROR: \(error)\n",stderr) }
    fputs("FAIL: \(message)\n",stderr);exit(1)
}
let url=URL(fileURLWithPath:CommandLine.arguments[1])
let settings=SceneTransparencyStore(url:url)
func put(_ object:[String:Any]) throws {
    try JSONSerialization.data(withJSONObject:object,options:[.sortedKeys]).write(to:url)
}
func raw()->[String:Any] {
    try! JSONSerialization.jsonObject(with:Data(contentsOf:url)) as! [String:Any]
}
'''


class InsectStylePreferencesTests(unittest.TestCase):
    def run_swift(self, body):
        with tempfile.TemporaryDirectory(prefix='tianmu-insect-preferences-') as directory:
            folder = Path(directory)
            (folder/'main.swift').write_text(PRELUDE+body)
            binary = folder/'check'
            build = subprocess.run(['swiftc', str(ROOT/'native/v1/WindowPlacement.swift'),
                                    str(folder/'main.swift'), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(folder/'appearance.json')],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            print(run.stdout.strip())

    def test_existing_setting_writers_preserve_a_saved_realistic_style(self):
        # This uses only the pre-161 API, so the first red is a real lost field,
        # not a compile failure caused by the new enum/interface being absent.
        self.run_swift(r'''
try put(["transparency":63.5,"avoidPointer":false,"insectsOnTop":true,"insectStyle":"realistic"])
try settings.save(42.25)
check(raw()["insectStyle"] as? String == "realistic","save(transparency) discarded the saved insect style")
check(settings.restore()==42.25 && !settings.restoreAvoidance() && settings.restoreInsectsOnTop(),"Transparency write changed another old preference")
try settings.saveAvoidance(true)
check(raw()["insectStyle"] as? String == "realistic","saveAvoidance discarded the saved insect style")
check(settings.restore()==42.25 && settings.restoreAvoidance() && settings.restoreInsectsOnTop(),"Avoidance write changed another preference")
try settings.saveInsectsOnTop(false)
check(raw()["insectStyle"] as? String == "realistic","saveInsectsOnTop discarded the saved insect style")
check(settings.restore()==42.25 && settings.restoreAvoidance() && !settings.restoreInsectsOnTop(),"Layer write changed another preference")
print("PASS existing three setting writers preserve realistic style and independent values; TEMP_FILE_ONLY")
''')

    def test_whitelist_raw_values_titles_and_direct_codable_are_strict(self):
        self.run_swift(r'''
check(InsectStyle.allCases.map(\.rawValue)==["cute","realistic"],"Style whitelist changed")
check(InsectStyle.allCases.map(\.title)==["可爱","写实"],"Style titles must be explicit Chinese labels")
for style in InsectStyle.allCases {
    let encoded=try JSONEncoder().encode(style)
    check(try JSONDecoder().decode(InsectStyle.self,from:encoded)==style,"Style Codable roundtrip failed")
}
for value in [#""unknown""#,#""CUTE""#,#"" realistic ""#,"3","true","null","{}","[]"] {
    let parsed=try? JSONDecoder().decode(InsectStyle.self,from:Data(value.utf8))
    check(parsed==nil,"Direct enum decoding must not invent a style for \(value)")
}
check(!FileManager.default.fileExists(atPath:url.path),"Enum validation created a sidecar")
print("PASS strict two-value Codable/CaseIterable enum and Chinese titles; NO_FILE_WRITE")
''')

    def test_missing_and_legacy_fields_restore_cute_without_writing_or_resetting(self):
        self.run_swift(r'''
check(settings.restoreInsectStyle() == .cute,"Missing sidecar must default to cute")
check(settings.restore()==100 && settings.restoreAvoidance() && !settings.restoreInsectsOnTop(),"Missing sidecar old defaults changed")
check(!FileManager.default.fileExists(atPath:url.path),"Restore created a missing sidecar")
for old:[String:Any] in [["transparency":36.5],
                         ["transparency":27.25,"avoidPointer":false,"insectsOnTop":true]] {
    try put(old);let before=try Data(contentsOf:url)
    let restored=SceneTransparencyStore(url:url)
    check(restored.restoreInsectStyle() == .cute,"Legacy record must default to cute")
    check(restored.restore()==old["transparency"] as! Double,"Legacy transparency changed")
    check(restored.restoreAvoidance()==(old["avoidPointer"] as? Bool ?? true),"Legacy avoidance changed")
    check(restored.restoreInsectsOnTop()==(old["insectsOnTop"] as? Bool ?? false),"Legacy insect layer changed")
    check(try Data(contentsOf:url)==before,"Read migrated the sidecar on disk")
}
print("PASS missing/legacy records use cute without changing old preferences or writing; TEMP_FILE_ONLY")
''')

    def test_bad_style_is_isolated_from_all_three_valid_old_preferences(self):
        self.run_swift(r'''
let invalid:[Any]=[NSNull(),true,false,0,1,1.5,[],[:],"","unknown","CUTE"," realistic "]
for value in invalid {
    try put(["transparency":63.5,"avoidPointer":false,"insectsOnTop":true,"insectStyle":value])
    let before=try Data(contentsOf:url),restored=SceneTransparencyStore(url:url)
    check(restored.restoreInsectStyle() == .cute,"Bad style did not independently fall back")
    check(restored.restore()==63.5 && !restored.restoreAvoidance() && restored.restoreInsectsOnTop(),"Bad style reset an unrelated preference")
    check(try Data(contentsOf:url)==before,"Tolerant restore must not rewrite the input")
    try restored.saveInsectsOnTop(false)
    check(raw()["insectStyle"] as? String == "cute","A later explicit save did not preserve the resolved default")
    check(restored.restore()==63.5 && !restored.restoreAvoidance() && !restored.restoreInsectsOnTop(),"Later write reset an unrelated preference")
}
print("PASS missing/null/type/unknown-style fallback isolated from old values; later writes retain the resolved style; TEMP_FILE_ONLY")
''')

    def test_style_saves_reopen_and_preserve_other_settings_in_both_directions(self):
        self.run_swift(r'''
try put(["transparency":31.75,"avoidPointer":false,"insectsOnTop":true])
for style:InsectStyle in [.realistic,.cute,.realistic] {
    try settings.saveInsectStyle(style)
    let reopened=SceneTransparencyStore(url:url)
    check(reopened.restoreInsectStyle()==style,"Style did not survive a fresh store")
    check(raw()["insectStyle"] as? String == style.rawValue,"Stored style is not its canonical raw value")
    check(reopened.restore()==31.75 && !reopened.restoreAvoidance() && reopened.restoreInsectsOnTop(),"Style write reset an old setting")
}
try settings.save(112)
try settings.saveAvoidance(true)
try settings.saveInsectsOnTop(false)
let reopened=SceneTransparencyStore(url:url)
check(reopened.restoreInsectStyle() == .realistic,"Old settings lost style across reopening")
check(reopened.restore()==100 && reopened.restoreAvoidance() && !reopened.restoreInsectsOnTop(),"Old normalizing/default behavior changed")
print("PASS style changes persist/reopen and preserve transparency, avoidance and insect layer; TEMP_FILE_ONLY")
''')

    def test_style_write_failure_throws_and_preserves_existing_sidecar_bytes(self):
        self.run_swift(r'''
try put(["transparency":49.5,"avoidPointer":false,"insectsOnTop":true,"insectStyle":"cute"])
let before=try Data(contentsOf:url)
// An ordinary file cannot be the new sidecar's parent directory. This fails
// deterministically even on machines where permission bits are bypassed.
let blocked=SceneTransparencyStore(url:url.appendingPathComponent("blocked.json"))
var failed=false
do {try blocked.saveInsectStyle(.realistic)} catch {failed=true}
check(failed,"Style write failure was silently accepted")
check(try Data(contentsOf:url)==before,"Failed write altered the existing appearance file")
let reopened=SceneTransparencyStore(url:url)
check(reopened.restoreInsectStyle() == .cute,"Failure replaced the saved style")
check(reopened.restore()==49.5 && !reopened.restoreAvoidance() && reopened.restoreInsectsOnTop(),"Failure reset old settings")
try reopened.saveInsectStyle(.realistic)
check(SceneTransparencyStore(url:url).restoreInsectStyle() == .realistic,"Successful later write failed")
print("PASS failed style write throws and preserves existing bytes; valid later write succeeds; TEMP_FILE_ONLY")
''')


if __name__ == '__main__':
    unittest.main()
