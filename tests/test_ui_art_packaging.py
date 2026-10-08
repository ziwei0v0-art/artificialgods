"""Production UI assets and icon packaging, without an app build or launch.

Only disposable Resources directories are written. Native probes never create
NSApplication, windows, a worker, or any saved game.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/production/ui'
SPEC = importlib.util.spec_from_file_location('tianmu_ui_packaging_builder', ROOT / 'tools/build_native.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def snapshot(root):
    if not root.exists():
        return None
    return {str(path.relative_to(root)): ('directory' if path.is_dir() else
            hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(root.rglob('*'))}


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'), 'macOS + Swift required')
class UIArtPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-ui-art-packaging-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.originals = snapshot(SOURCE)
        cls.addClassCleanup(lambda: cls.assert_production_unchanged())
        main = cls.folder / 'main.swift'
        main.write_text(r'''import AppKit
let root = URL(fileURLWithPath:CommandLine.arguments[2])
if CommandLine.arguments[1] == "ui" {
    let document = try! JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("manifest.json"))) as! [String:Any]
    let rows = document["assets"] as! [String:[String:Any]]
    let library = UIArtifactLibrary(resourceRoot:root)
    assert(Set(rows.keys) == Set(["divination-vessel","timer-dial"]))
    for (name,row) in rows {
        let crop = row["sourceRect"] as! [Double]
        guard let image=library.image(name), let cg=image.cgImage(forProposedRect:nil,context:nil,hints:nil) else {
            fatalError("Packaged production UI image must load")
        }
        assert(image.size == NSSize(width:crop[2],height:crop[3]))
        assert(cg.width == Int(crop[2]) && cg.height == Int(crop[3]))
    }
} else {
    guard let image=NSImage(contentsOf:root), let cg=image.cgImage(forProposedRect:nil,context:nil,hints:nil) else {
        fatalError("The declared application icon must decode")
    }
    assert(cg.width > 0 && cg.height > 0)
}
assert(NSApp == nil,"Resource probes must never create an application or windows")
print("PASS: native resource decoding; no application, windows, worker or saved game")
''')
        cls.probe = cls.folder / 'probe'
        result = subprocess.run(['swiftc', '-framework', 'AppKit',
                                 str(ROOT / 'native/v1/BrandArtwork.swift'), str(main), '-o', str(cls.probe)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def assert_production_unchanged(cls):
        if snapshot(SOURCE) != cls.originals:
            raise AssertionError('Production source assets changed during packaging tests')

    def run_probe(self, kind, path):
        result = subprocess.run([str(self.probe), kind, str(path)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS:', result.stdout)

    def fixture(self, folder):
        source = folder / 'source'
        shutil.copytree(SOURCE, source)
        return source, json.loads((source / 'manifest.json').read_text())

    def test_production_pair_is_copied_byte_for_byte_and_loads_with_native_crop(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            resources = Path(directory) / 'Resources'
            BUILDER.copy_ui_art(SOURCE, resources)
            target = resources / 'art/ui'
            manifest = json.loads((SOURCE / 'manifest.json').read_text())
            names = {'manifest.json', *(row['file'] for row in manifest['assets'].values())}
            self.assertEqual(len(names), 3)
            self.assertEqual({p.name for p in target.iterdir()}, names)
            for name in names:
                self.assertTrue((target / name).read_bytes() == (SOURCE / name).read_bytes(), name)
            for row in manifest['assets'].values():
                self.assertEqual(hashlib.sha256((target / row['file']).read_bytes()).hexdigest(), row['sha256'])
            self.run_probe('ui', target)

    def test_bad_hash_and_crop_never_create_or_partially_replace_a_package(self):
        invalid = {
            'hash': ('sha256', '0' * 64),
            'missing-hash': ('sha256', None),
            'outside-crop': ('sourceRect', [0, 0, 4097, 4097]),
            'zero-width': ('sourceRect', [0, 0, 0, 1]),
            'negative-origin': ('sourceRect', [-1, 0, 1, 1]),
            'float-coordinate': ('sourceRect', [0.5, 0, 1, 1]),
            'boolean-coordinate': ('sourceRect', [False, 0, 1, 1]),
            'nan-coordinate': ('sourceRect', [float('nan'), 0, 1, 1]),
            'infinite-size': ('sourceRect', [0, 0, float('inf'), 1]),
            'short-rectangle': ('sourceRect', [0, 0, 1]),
        }
        for label, (field, value) in invalid.items():
            for existing in (False, True):
                with self.subTest(case=label, existing=existing), tempfile.TemporaryDirectory(dir=self.folder) as directory:
                    folder = Path(directory)
                    source, manifest = self.fixture(folder)
                    # Fail on the second asset: validating the first must not
                    # copy it before the complete manifest is accepted.
                    manifest['assets']['timer-dial'][field] = value
                    (source / 'manifest.json').write_text(json.dumps(manifest))
                    resources = folder / 'Resources'
                    if existing:
                        target = resources / 'art/ui'
                        target.mkdir(parents=True)
                        (target / 'manifest.json').write_bytes(b'previous manifest')
                        (target / 'previous.png').write_bytes(b'previous image')
                    before = snapshot(resources)
                    with self.assertRaises(ValueError):
                        BUILDER.copy_ui_art(source, resources)
                    self.assertEqual(snapshot(resources), before)

    def test_interrupted_copy_preserves_the_complete_previous_package(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            resources = Path(directory) / 'Resources'
            target = resources / 'art/ui'
            target.mkdir(parents=True)
            (target / 'manifest.json').write_bytes(b'previous manifest')
            (target / 'previous.png').write_bytes(b'previous image')
            before = snapshot(resources)
            original_copy = shutil.copy2

            def interrupted_copy(source, destination, *args, **kwargs):
                if Path(source).name == 'timer-dial-v01.png':
                    # A copy can write some bytes before an I/O error occurs.
                    Path(destination).write_bytes(b'partial image')
                    raise OSError('synthetic interrupted second PNG copy')
                return original_copy(source, destination, *args, **kwargs)

            with patch.object(BUILDER.shutil, 'copy2', side_effect=interrupted_copy):
                with self.assertRaisesRegex(OSError, 'interrupted second PNG'):
                    BUILDER.copy_ui_art(SOURCE, resources)
            self.assertEqual(snapshot(resources), before,
                             'A failed copy must leave the entire previous package and no staging debris')

    def test_failed_install_restores_the_previous_package_and_removes_staging(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            resources = Path(directory) / 'Resources'
            target = resources / 'art/ui'
            target.mkdir(parents=True)
            (target / 'manifest.json').write_bytes(b'previous manifest')
            (target / 'previous.png').write_bytes(b'previous image')
            before = snapshot(resources)
            original_rename = Path.rename

            def failed_install(path, destination):
                if path.name == 'ui' and path.parent.name.startswith('ui-'):
                    raise OSError('synthetic final directory rename failure')
                return original_rename(path, destination)

            with patch.object(Path, 'rename', autospec=True, side_effect=failed_install):
                with self.assertRaisesRegex(OSError, 'final directory rename'):
                    BUILDER.copy_ui_art(SOURCE, resources)
            self.assertEqual(snapshot(resources), before)

    def test_successful_replacement_removes_files_outside_the_current_manifest(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            resources = Path(directory) / 'Resources'
            target = resources / 'art/ui'
            target.mkdir(parents=True)
            (target / 'retired.png').write_bytes(b'old image')
            (resources / 'unrelated.dat').write_bytes(b'keep')
            BUILDER.copy_ui_art(SOURCE, resources)
            self.assertEqual(snapshot(target), self.originals)
            self.assertEqual((resources / 'unrelated.dat').read_bytes(), b'keep')
            self.assertEqual({p.name for p in target.parent.iterdir()}, {'ui'})

    def test_interrupted_first_install_leaves_no_partial_ui_package(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            resources = Path(directory) / 'Resources'
            original_copy = shutil.copy2

            def interrupted_copy(source, destination, *args, **kwargs):
                if Path(source).name == 'timer-dial-v01.png':
                    Path(destination).write_bytes(b'partial image')
                    raise OSError('synthetic first install interruption')
                return original_copy(source, destination, *args, **kwargs)

            with patch.object(BUILDER.shutil, 'copy2', side_effect=interrupted_copy):
                with self.assertRaisesRegex(OSError, 'first install interruption'):
                    BUILDER.copy_ui_art(SOURCE, resources)
            self.assertFalse((resources / 'art/ui').exists())
            self.assertFalse(any(path.is_file() for path in resources.rglob('*')))
            self.assertFalse(any(path.name.startswith('ui-') for path in resources.rglob('*')))

    def test_version_info_names_a_real_generated_decodable_icon(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            resources = Path(directory) / 'Resources'
            resources.mkdir()
            info = plistlib.loads(plistlib.dumps(BUILDER.bundle_info('15.0')))
            self.assertEqual(info['CFBundleShortVersionString'], '1.0.7')
            self.assertEqual(info['CFBundleVersion'], '27')
            self.assertEqual(info['CFBundleIconFile'], 'Tianmu.icns')
            BUILDER.build_brand_icon(resources)
            icon = resources / info['CFBundleIconFile']
            data = icon.read_bytes()
            self.assertEqual(data[:4], b'icns')
            self.assertEqual(int.from_bytes(data[4:8], 'big'), len(data))
            self.assertGreater(len(data), 8)
            self.run_probe('icon', icon)


if __name__ == '__main__':
    unittest.main()
