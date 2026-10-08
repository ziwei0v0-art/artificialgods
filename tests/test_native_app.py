import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class NativeApplicationBuildTests(unittest.TestCase):
    def test_native_host_builds_and_roundtrips_the_backend_without_showing_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '天姥.app'
            build = subprocess.run([sys.executable, str(PROJECT / 'tools' / 'build_native.py'), '--output', str(target)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(target / 'Contents' / 'MacOS' / 'Tianmu'), '--check-backend',
                                  '--save-file', str(Path(directory) / 'test-state.json')],
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertTrue(result['ok'])
            self.assertEqual(result['pages'], ['求签', '虫瓶', '装扮'])
            self.assertEqual(result['mode'], 'clock')
