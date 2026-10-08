"""Compile the actual package, without launching UI or reading a save.

Removing the explicit host deployment target must fail this regression on a
compiler whose default target is newer than the current Mac.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def version_tuple(value):
    parts = [int(part) for part in value.split('.')]
    return tuple((parts + [0, 0, 0])[:3])


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'), 'macOS + Swift required')
class CurrentMacBundleTests(unittest.TestCase):
    def test_real_bundle_timer_core_runs_without_compiler_or_writing_inside_app(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-packaged-core-') as temporary:
            folder = Path(temporary)
            app = folder / 'Tianmu.app'
            built = subprocess.run([sys.executable, str(ROOT / 'tools/build_native.py'),
                                    '--output', str(app)], capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            backend = app / 'Contents/Resources/backend'
            self.assertEqual(len(list((backend / 'build').glob('catime-core-*.dylib'))), 1,
                             'Ship the real Catime core; opening a timer must not require a developer compiler')
            def files():
                return {str(path.relative_to(app)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in app.rglob('*') if path.is_file()}
            before = files()
            path = folder / 'disposable-save/state.json'
            requests = [{'id': 1, 'action': 'timer_start', 'mode': 'countdown', 'duration': '1m30s'},
                        {'id': 2, 'action': 'timer_pause'}, {'id': 3, 'action': 'timer_resume'},
                        {'id': 4, 'action': 'timer_end'},
                        {'id': 5, 'action': 'timer_start', 'mode': 'stopwatch'},
                        {'id': 6, 'action': 'timer_pause'}, {'id': 7, 'action': 'timer_resume'},
                        {'id': 8, 'action': 'timer_end'},
                        {'id': 9, 'action': 'timer_start', 'mode': 'pomodoro', 'work': '25', 'rest': '5'},
                        {'id': 10, 'action': 'quit'}]
            run = subprocess.run([sys.executable, '-m', 'tianmu_mvp.worker', '--save-file', str(path)],
                                 input=''.join(json.dumps(row) + '\n' for row in requests),
                                 cwd=backend, env={**os.environ, 'PATH': str(folder / 'no-compiler'),
                                                   'PYTHONDONTWRITEBYTECODE': '1'},
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            replies = [json.loads(row) for row in run.stdout.splitlines()]
            self.assertTrue(all(row.get('ok') is True for row in replies), replies)
            self.assertEqual([row['id'] for row in replies if row.get('id') is not None], list(range(1, 11)))
            self.assertEqual(replies[1]['state']['timer']['countdown_seconds'], 90)
            native_env = {**os.environ, 'PATH': str(folder / 'no-compiler')}
            native_env.pop('PYTHONDONTWRITEBYTECODE', None)
            native = subprocess.run([str(app / 'Contents/MacOS/Tianmu'), '--check-backend', '--save-file', str(path)],
                                    env=native_env, capture_output=True, text=True, timeout=20)
            self.assertEqual(native.returncode, 0, native.stdout + native.stderr)
            self.assertTrue(json.loads(native.stdout)['ok'])
            self.assertEqual(before, files(), 'A packaged timer must not compile or write inside its app')
            self.assertTrue(path.is_file())
            print('PASS packaged Catime core: real temporary worker; compiler unavailable; application bytes unchanged; NO_UI_NO_REAL_SAVE')

    def test_real_bundle_deployment_floor_does_not_exceed_this_mac(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-current-mac-bundle-') as temporary:
            app = Path(temporary) / 'Tianmu.app'
            built = subprocess.run([sys.executable, str(ROOT / 'tools/build_native.py'),
                                    '--output', str(app)], capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            inspected = subprocess.run(['/usr/bin/otool', '-l', str(app / 'Contents/MacOS/Tianmu')],
                                       capture_output=True, text=True, timeout=15)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            minimum = re.search(r'LC_BUILD_VERSION\s+cmdsize\s+\d+\s+platform\s+\d+\s+minos\s+([\d.]+)', inspected.stdout)
            self.assertIsNotNone(minimum, 'Actual Mach-O must declare its deployment floor')
            actual = minimum.group(1)
            current = platform.mac_ver()[0]
            self.assertLessEqual(version_tuple(actual), version_tuple(current),
                                 f'LaunchServices rejects minos {actual} on current macOS {current}')
            info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
            self.assertEqual(version_tuple(info['LSMinimumSystemVersion']), version_tuple(actual))
            print(f'PASS actual bundle: minos={actual}, current={current}; NO_LAUNCH_NO_SAVE_NO_WORKER')


if __name__ == '__main__':
    unittest.main()
