"""QA relaunch isolation: never show UI or inspect a real saved game.

The Foundation-only preflight executes the production save resolver and stops
before any worker exists. Even the expected red run cannot open a default save.
"""
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'), 'macOS + Swift required')
class QABundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-qa-bundle-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name).resolve()
        source = (ROOT / 'native/v1/main.swift').read_text()
        resolver = source[source.index('func argument('):source.index('func startWorker(')]
        cls.resolver_source = resolver
        swift = cls.folder / 'main.swift'
        swift.write_text('import Foundation\n' + resolver + r'''
// This executable never starts NSApplication, a worker, or any file operation.
// In particular, do not print or inspect an unexpectedly selected real path.
let expected = URL(fileURLWithPath:CommandLine.arguments[1]).standardizedFileURL
let selected = saveFileURL().standardizedFileURL
guard selected == expected else {
    print("QA_SAVE_ROUTE_ESCAPED_FIXTURE")
    exit(42)
}
print("RESOLVED_FIXTURE_SAVE")
''')
        cls.resolver_binary = cls.folder / 'resolver'
        build = subprocess.run(['swiftc', '-target',
                                f'{platform.machine()}-apple-macosx{platform.mac_ver()[0]}',
                                str(swift), '-o', str(cls.resolver_binary)],
                               capture_output=True, text=True, timeout=30)
        if build.returncode:
            raise AssertionError(build.stderr)

    def _probe(self, name, qa_path=None, explicit_path=None, expected=None):
        bundle = self.folder / (name + '.app') / 'Contents'
        binary = bundle / 'MacOS' / 'Probe'
        binary.parent.mkdir(parents=True)
        shutil.copy2(self.resolver_binary, binary)
        info = {'CFBundleIdentifier': 'local.tianmu.resolver-probe.' + name,
                'CFBundleExecutable': 'Probe', 'CFBundlePackageType': 'APPL'}
        if qa_path is not None:
            info['TianmuQASaveFile'] = str(qa_path)
        (bundle / 'Info.plist').write_bytes(plistlib.dumps(info))
        command = [str(binary), str(expected)]
        if explicit_path is not None:
            command += ['--save-file', str(explicit_path)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0,
                         'Resolver must select only the expected disposable path: ' + run.stdout + run.stderr)
        self.assertIn('RESOLVED_FIXTURE_SAVE', run.stdout)
        self.assertFalse(expected.exists(), 'A resolver must not create or read saved state')

    def test_qa_info_selects_isolated_save_without_launch_arguments(self):
        path = self.folder / 'qa-default' / 'state.json'
        self._probe('qa-no-arguments', qa_path=path, expected=path)

    def test_explicit_save_argument_precedes_qa_bundle_default(self):
        qa = self.folder / 'unused-qa' / 'state.json'
        explicit = self.folder / 'explicit' / 'state.json'
        self._probe('qa-explicit', qa_path=qa, explicit_path=explicit, expected=explicit)
        self.assertFalse(qa.exists())

    def test_builder_records_qa_identity_and_absolute_path_only_for_qa(self):
        spec = importlib.util.spec_from_file_location('qa_builder_under_test', ROOT / 'tools/build_native.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertTrue(callable(getattr(builder, 'bundle_info', None)),
                        'The builder must use the shared production Info generator')
        normal = builder.bundle_info(platform.mac_ver()[0])
        self.assertEqual(normal['CFBundleIdentifier'], 'local.tianmu.garden')
        self.assertNotIn('TianmuQASaveFile', normal, 'Normal packages must not inherit a QA save')
        current_directory = Path.cwd()
        try:
            os.chdir(self.folder)
            qa = builder.bundle_info(platform.mac_ver()[0], Path('configured-qa/state.json'))
        finally:
            os.chdir(current_directory)
        expected = self.folder / 'configured-qa/state.json'
        self.assertEqual(qa['CFBundleIdentifier'], 'local.tianmu.garden.qa')
        self.assertEqual(Path(qa['TianmuQASaveFile']), expected)
        self.assertTrue(Path(qa['TianmuQASaveFile']).is_absolute())
        self.assertNotEqual(qa['CFBundleName'], normal['CFBundleName'])
        self.assertNotEqual(qa['CFBundleDisplayName'], normal['CFBundleDisplayName'])
        self.assertFalse(expected.parent.exists(), 'Generating package metadata must not create state')

    def test_real_qa_bundle_without_save_arguments_writes_only_disposable_state(self):
        qa = self.folder / 'integration-save' / 'state.json'
        # Gate the real worker behind the already verified production resolver.
        # A regression fails here without executing the complete app or backend.
        self._probe('integration-preflight', qa_path=qa, expected=qa)
        source = (ROOT / 'native/v1/main.swift').read_text()
        self.assertEqual(source[source.index('func argument('):source.index('func startWorker(')],
                         self.resolver_source, 'Save resolver changed after the safe preflight; rerun the test')
        app = self.folder / 'DisposableQA.app'
        built = subprocess.run([sys.executable, str(ROOT / 'tools/build_native.py'),
                                '--output', str(app), '--qa-save-file', str(qa)],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleIdentifier'], 'local.tianmu.garden.qa')
        self.assertEqual(info['TianmuQASaveFile'], str(qa))
        self.assertFalse(qa.exists(), 'A package build must not start or initialize saved state')
        binary = app / 'Contents/MacOS' / info['CFBundleExecutable']
        run = subprocess.run([str(binary), '--check-backend'],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(json.loads(run.stdout)['ok'])
        self.assertTrue(qa.is_file(), 'No-argument QA startup must persist its disposable state')
        self.assertTrue(json.loads(qa.read_text()), 'Only the disposable QA state is inspected')
        # Check explicit precedence again at the complete native/worker boundary.
        previous = qa.read_bytes()
        explicit = self.folder / 'integration-explicit' / 'state.json'
        run = subprocess.run([str(binary), '--check-backend', '--save-file', str(explicit)],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(json.loads(run.stdout)['ok'])
        self.assertTrue(explicit.is_file())
        self.assertEqual(qa.read_bytes(), previous, 'Explicit save must leave the embedded QA state unchanged')
        print('PASS: real QA bundle, no-argument QA default and explicit override; '
              'NO_UI_NO_REAL_SAVE_ACCESS_DISPOSABLE_WORKER_ONLY')


if __name__ == '__main__':
    unittest.main()
