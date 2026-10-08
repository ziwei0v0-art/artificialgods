"""Launcher checks use disposable bundles and recording boundaries only."""
import importlib
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class NativeLauncherTests(unittest.TestCase):
    def setUp(self):
        try:
            self.launcher = importlib.import_module('tools.launch_native')
        except ModuleNotFoundError:
            self.launcher = None
        self.assertIsNotNone(self.launcher, 'Native candidate launcher is not implemented')
        self.temp = tempfile.TemporaryDirectory(prefix='tianmu-launch-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / '项目').resolve()
        self.app = self.root / '候选' / '天姥.app'
        self.binary = self.app / 'Contents' / 'MacOS' / 'Tianmu'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'fixture, never executed')
        self.binary.chmod(0o755)
        self.python = Path(self.temp.name) / 'python3.12'
        self.python.write_bytes(b'fixture, never executed')
        self.python.chmod(0o755)
        self.plist = self.app / 'Contents' / 'Info.plist'
        self.info = {
            'CFBundleExecutable': 'Tianmu',
            'CFBundleIdentifier': 'local.tianmu.garden',
            'CFBundleShortVersionString': '0.9.7',
            'TianmuPythonExecutable': str(self.python),
        }
        self.plist.write_bytes(plistlib.dumps(self.info))
        self.manifest = self.root / '当前原生候选.json'
        self.record = {'app': '候选/天姥.app', 'version': '0.9.7', 'status': 'candidate'}
        self.write_manifest(self.record)

    def write_manifest(self, value):
        self.manifest.write_text(json.dumps(value, ensure_ascii=False))

    def test_default_uses_candidate_experience_save_without_creating_it(self):
        plan = self.launcher.resolve_launch(self.root)
        self.assertEqual(plan.binary, self.binary)
        self.assertEqual(plan.version, '0.9.7')
        self.assertEqual(plan.save_file, self.root / '候选/体验存档/state.json')
        self.assertTrue(plan.isolated)
        self.assertFalse(plan.save_file.parent.exists())

    def test_released_bundle_uses_contained_runtime_after_relocation(self):
        embedded = self.app / 'Contents/Resources/Runtime/bin/python3'
        embedded.parent.mkdir(parents=True)
        embedded.write_bytes(b'fixture, never executed')
        embedded.chmod(0o755)
        self.plist.write_bytes(plistlib.dumps({**self.info, 'TianmuPythonExecutable':'Runtime/bin/python3', 'TianmuEmbeddedPython':True}))
        self.write_manifest({**self.record, 'status':'release'})
        plan = self.launcher.resolve_launch(self.root)
        self.assertEqual(plan.python, embedded)
        embedded.unlink()
        embedded.symlink_to(self.python)
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)

    def test_explicit_save_is_preserved_without_reading_its_contents(self):
        save = Path(self.temp.name) / '已选存档.json'
        save.write_bytes(b'not JSON; launcher must not parse it')
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == save:
                raise AssertionError('Launcher must not read the selected save')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded_open):
            plan = self.launcher.resolve_launch(self.root, save)
        self.assertEqual(plan.save_file, save)
        self.assertFalse(plan.isolated)
        self.assertEqual(save.read_bytes(), b'not JSON; launcher must not parse it')

    def test_invalid_or_missing_manifest_fails_closed(self):
        bad_records = [[], {}, {**self.record, 'status': 'ready'},
                       {**self.record, 'version': ''}, {**self.record, 'app': str(self.app)},
                       {**self.record, 'app': '../outside.app'},
                       {**self.record, 'app': '候选/天姥'},
                       {**self.record, 'app': '候选/missing.app'}]
        for record in bad_records:
            with self.subTest(record=record):
                self.write_manifest(record)
                with self.assertRaises(self.launcher.LaunchError):
                    self.launcher.resolve_launch(self.root)
        self.manifest.write_text('{')
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)
        self.manifest.unlink()
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)

    def test_app_symlink_cannot_escape_project(self):
        outside = Path(self.temp.name) / 'outside.app'
        self.app.rename(outside)
        self.app.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)

    def test_bundle_identity_and_runtime_must_match(self):
        changes = [('CFBundleExecutable', 'other'), ('CFBundleIdentifier', 'other.app'),
                   ('CFBundleShortVersionString', '0.9.6'),
                   ('TianmuPythonExecutable', str(self.python.parent / 'missing')),
                   ('TianmuPythonExecutable', 'relative/python3.12')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.plist.write_bytes(plistlib.dumps({**self.info, key: value}))
                with self.assertRaises(self.launcher.LaunchError):
                    self.launcher.resolve_launch(self.root)
        self.plist.write_bytes(b'not a plist')
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)

    def test_binary_and_python_must_be_executable_files(self):
        for path in [self.binary, self.python]:
            with self.subTest(path=path):
                path.chmod(0o644)
                with self.assertRaises(self.launcher.LaunchError):
                    self.launcher.resolve_launch(self.root)
                path.chmod(0o755)
        self.binary.unlink()
        self.binary.mkdir()
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)

    def test_binary_symlink_cannot_substitute_an_external_program(self):
        self.binary.unlink()
        self.binary.symlink_to(self.python)
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.resolve_launch(self.root)

    def test_check_only_never_checks_processes_executes_or_creates_save(self):
        plan = self.launcher.resolve_launch(self.root)
        output = []
        def forbidden(*args, **kwargs):
            self.fail('Check-only crossed a process boundary')
        self.launcher.execute_launch(plan, check_only=True, process_runner=forbidden,
                                     exec_fn=forbidden, printer=output.append)
        self.assertIn('0.9.7', '\n'.join(output))
        self.assertIn('灶神原生候选', '\n'.join(output))
        self.assertIn('隔离', '\n'.join(output))
        self.assertIn(str(plan.save_file), '\n'.join(output))
        self.assertFalse(plan.save_file.parent.exists())

    def test_renamed_product_bundle_still_uses_the_same_runtime_and_save_contract(self):
        renamed = self.app.with_name('灶神.app')
        self.app.rename(renamed)
        self.write_manifest({**self.record, 'app': '候选/灶神.app'})
        plan = self.launcher.resolve_launch(self.root)
        self.assertEqual(plan.binary, renamed / 'Contents/MacOS/Tianmu')
        self.assertEqual(plan.save_file, self.root / '候选/体验存档/state.json')
        self.assertFalse(plan.save_file.parent.exists())

    def test_launch_checks_exact_process_then_executes_binary_with_explicit_save(self):
        save = Path(self.temp.name) / '任意 保存路径.json'
        plan = self.launcher.resolve_launch(self.root, save)
        events = []
        def runner(args, **kwargs):
            events.append(('check', args))
            return subprocess.CompletedProcess(args, 1, '', '')
        def execute(path, args):
            events.append(('exec', path, args))
        output = []
        self.launcher.execute_launch(plan, process_runner=runner, exec_fn=execute, printer=output.append)
        self.assertEqual(events, [
            ('check', ['/usr/bin/pgrep', '-x', 'Tianmu']),
            ('exec', str(self.binary), [str(self.binary), '--save-file', str(save)]),
        ])
        self.assertIn('显式', '\n'.join(output))
        self.assertFalse(save.exists())

    def test_existing_game_or_failed_process_check_prevents_execution(self):
        plan = self.launcher.resolve_launch(self.root)
        for code in [0, 2]:
            with self.subTest(code=code):
                executed = []
                def runner(args, **kwargs):
                    return subprocess.CompletedProcess(args, code, '123\n', 'fixture')
                with self.assertRaises(self.launcher.LaunchError):
                    self.launcher.execute_launch(plan, process_runner=runner,
                                                 exec_fn=lambda *args: executed.append(args), printer=lambda _: None)
                self.assertEqual(executed, [])
        self.assertFalse(plan.save_file.parent.exists())

    def test_process_check_unavailable_prevents_execution(self):
        plan = self.launcher.resolve_launch(self.root)
        def unavailable(*args, **kwargs):
            raise OSError('missing pgrep fixture')
        with self.assertRaises(self.launcher.LaunchError):
            self.launcher.execute_launch(plan, process_runner=unavailable,
                                         exec_fn=lambda *args: self.fail('must not execute'), printer=lambda _: None)


if __name__ == '__main__':
    unittest.main()
