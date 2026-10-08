"""Exercise relocation with a disposable backend; never launch app UI or real saves."""
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('embedded_builder_under_test', ROOT / 'tools/build_native.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'), 'macOS + Swift required')
class EmbeddedPythonTests(unittest.TestCase):
    def test_relocated_runtime_runs_worker_without_installed_python_or_compiler(self):
        self.assertTrue(callable(getattr(builder, 'copy_embedded_python', None)),
                        'Release packaging must embed a relocatable Python runtime')
        with tempfile.TemporaryDirectory(prefix='tianmu-runtime-relocation-') as temporary:
            folder = Path(temporary).resolve()
            resources = folder / 'original.app/Contents/Resources'
            resources.mkdir(parents=True)
            metadata = builder.copy_embedded_python(resources)
            info = builder.bundle_info(platform.mac_ver()[0], embed_python=True)
            self.assertEqual(info['TianmuPythonExecutable'], 'Runtime/bin/python3')
            self.assertTrue(info['TianmuEmbeddedPython'])
            self.assertTrue(metadata['selfContained'])
            self.assertFalse((resources / 'Runtime/lib/python3.12/site-packages').exists())
            self.assertTrue((resources / 'Runtime/LICENSE.txt').is_file())
            for name in ['LICENSE.cpython.txt', 'LICENSE.bzip2.txt', 'LICENSE.libffi.txt',
                         'LICENSE.mpdecimal.txt', 'LICENSE.expat.txt', 'LICENSE.openssl-3.txt',
                         'LICENSE.liblzma.txt', 'LICENSE.sqlite.txt', 'LICENSE.libuuid.txt',
                         'PYTHON.json', 'provenance.json']:
                self.assertTrue((resources / 'Runtime/licenses' / name).is_file(), name)
            backend = resources / 'backend'
            shutil.copytree(ROOT / 'tianmu_mvp', backend / 'tianmu_mvp',
                            ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'third_party', backend / 'third_party')
            builder.build_timer_core(backend)
            moved = folder / '搬移后的目录/天姥.app'
            moved.parent.mkdir()
            (folder / 'original.app').rename(moved)
            resources = moved / 'Contents/Resources'
            runtime = resources / 'Runtime'
            def hashes():
                return {str(path.relative_to(moved)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in moved.rglob('*') if path.is_file()}
            before = hashes()
            save = folder / 'isolated-save/state.json'
            env = {'PATH': str(folder / 'no-python-or-compiler'), 'HOME': str(folder / 'isolated-home'),
                   'PYTHONDONTWRITEBYTECODE': '1', 'LC_CTYPE': 'UTF-8'}
            probe = subprocess.run([str(runtime / 'bin/python3'), '-I', '-B', '-c',
                                    'import json,sys,ssl,sqlite3,ctypes,lzma,zoneinfo; '
                                    'print(json.dumps({"prefix":sys.prefix,"paths":sys.path}))'],
                                   env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            actual = json.loads(probe.stdout)
            self.assertEqual(Path(actual['prefix']), runtime)
            self.assertTrue(all(Path(path).is_relative_to(runtime) for path in actual['paths']), actual)
            requests = [{'id': 1, 'action': 'timer_start', 'mode': 'countdown', 'duration': '1m30s'},
                        {'id': 2, 'action': 'timer_pause'}, {'id': 3, 'action': 'timer_resume'},
                        {'id': 4, 'action': 'timer_end'}, {'id': 5, 'action': 'quit'}]
            worker = subprocess.run([str(runtime / 'bin/python3'), '-E', '-s', '-B', '-m',
                                     'tianmu_mvp.worker', '--save-file', str(save)],
                                    cwd=resources / 'backend', env=env,
                                    input=''.join(json.dumps(row) + '\n' for row in requests),
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(worker.returncode, 0, worker.stdout + worker.stderr)
            replies = [json.loads(line) for line in worker.stdout.splitlines()]
            self.assertTrue(all(reply['ok'] for reply in replies), replies)
            self.assertEqual([reply['id'] for reply in replies if reply['id'] is not None], [1,2,3,4,5])
            self.assertEqual(replies[1]['state']['timer']['countdown_seconds'], 90)
            self.assertTrue(save.is_file())
            self.assertEqual(before, hashes(), 'Relocated runtime must not write inside the app')
            print('PASS runtime relocation: unicode path; PATH has no Python/compiler; temporary worker; app unchanged')
            outside = folder / 'outside.txt'
            outside.write_text('must never enter a bundle')
            (runtime / 'lib/python3.12/unsafe_fixture.py').symlink_to(outside)
            destination = folder / 'rejected-output'
            code = (
                'import importlib.util,sys; from pathlib import Path; '
                'spec=importlib.util.spec_from_file_location("builder",sys.argv[1]); '
                'builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)\n'
                'try: builder.copy_embedded_python(Path(sys.argv[2]))\n'
                'except ValueError as error: print(str(error))\n'
                'else: raise SystemExit(42)\n'
            )
            rejected = subprocess.run([str(runtime / 'bin/python3'), '-I', '-B', '-c', code,
                                       str(ROOT / 'tools/build_native.py'), str(destination)],
                                      env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
            self.assertIn('unsafe symbolic link', rejected.stdout)
            self.assertFalse((destination / 'Runtime').exists())

    def test_corrupt_or_missing_dependency_notice_stops_before_staging_runtime(self):
        self.assertTrue(callable(getattr(builder, '_validated_python_licenses', None)))
        with tempfile.TemporaryDirectory(prefix='tianmu-python-license-') as temporary:
            folder = Path(temporary)
            source = folder / 'licenses'
            shutil.copytree(ROOT / 'tools/python_runtime_licenses', source)
            for damage in ('missing', 'changed'):
                with self.subTest(damage=damage):
                    path = source / 'LICENSE.libffi.txt'
                    if damage == 'missing':
                        path.unlink()
                    else:
                        path.write_text('not the original notice')
                    with self.assertRaisesRegex(ValueError, 'license'):
                        builder._validated_python_licenses(source, '3.12.14', '20260814', 'arm64')


if __name__ == '__main__':
    unittest.main()
