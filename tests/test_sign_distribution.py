"""Real macOS signing checks on disposable, compiled fixtures; never starts the game."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/sign_distribution.py'


def tree_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS codesign and clang')
class SignDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory(prefix='sign-fixture-')
        cls.fixture = Path(cls.fixture_dir.name) / 'Fixture.app'
        contents = cls.fixture / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Resources/Runtime/bin').mkdir(parents=True)
        (contents / 'Resources/Runtime/lib/python3.12/lib-dynload').mkdir(parents=True)
        (contents / 'Resources/message.txt').write_text('original resource\n')
        with (contents / 'Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'test.artificialgods.signing',
                          'CFBundleName': 'Fixture', 'CFBundleExecutable': 'Fixture',
                          'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1'}, stream)
        # Executable, dylib and extension use real, intentionally unsigned Mach-O.
        for relative, source, flags in [
            ('MacOS/Fixture', 'int main(void) { return 0; }', []),
            ('Resources/Runtime/bin/python3', 'int main(void) { return 0; }', []),
            ('Resources/Runtime/lib/libfixture.dylib', 'int fixture(void) { return 7; }',
             ['-dynamiclib']),
            ('Resources/Runtime/lib/python3.12/lib-dynload/_fixture.so',
             'int extension(void) { return 3; }', ['-bundle']),
        ]:
            subprocess.run(['/usr/bin/xcrun', 'clang', '-x', 'c', '-', *flags,
                            '-Wl,-no_adhoc_codesign', '-o', str(contents / relative)],
                           input=source, text=True, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='sign-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'input.app'
        shutil.copytree(self.fixture, self.source)
        self.output = self.root / 'signed.app'

    def run_tool(self, *options):
        return subprocess.run([sys.executable, '-B', str(TOOL), '--app', str(self.source),
                               '--output', str(self.output), *options],
                              text=True, capture_output=True, timeout=60)

    def test_signs_nested_macho_and_seals_resources_without_changing_input(self):
        before = tree_hashes(self.source)
        result = self.run_tool('--ad-hoc')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['mode'], 'ad-hoc')
        self.assertEqual(report['notarization'], 'not-performed')
        self.assertEqual(report['gatekeeper'], 'not-assessed')
        self.assertEqual(len(report['machO']), 4)
        self.assertEqual(tree_hashes(self.source), before)
        for relative in ['Contents/MacOS/Fixture', 'Contents/Resources/Runtime/bin/python3',
                         'Contents/Resources/Runtime/lib/libfixture.dylib',
                         'Contents/Resources/Runtime/lib/python3.12/lib-dynload/_fixture.so']:
            target = self.output / relative
            checked = subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(target)],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
        sealed = self.output / 'Contents/_CodeSignature/CodeResources'
        self.assertTrue(sealed.is_file(), 'outer bundle must have a resource seal')
        checked = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                                  str(self.output)], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        (self.output / 'Contents/Resources/message.txt').write_text('tampered\n')
        tampered = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                                   str(self.output)], capture_output=True, text=True)
        self.assertNotEqual(tampered.returncode, 0, 'changed resource must invalidate the seal')

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('keep this existing package')
        before = tree_hashes(self.output)
        result = self.run_tool('--ad-hoc')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertEqual(tree_hashes(self.output), before)

    def test_output_inside_input_is_rejected_before_any_write(self):
        self.output = self.source / 'Contents/Resources/child.app'
        before = tree_hashes(self.source)
        result = self.run_tool('--ad-hoc')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inside', result.stderr)
        self.assertEqual(tree_hashes(self.source), before)

    def test_external_symlink_is_rejected_without_touching_its_target(self):
        external = self.root / 'external.txt'
        external.write_text('outside input')
        (self.source / 'Contents/Resources/escape').symlink_to('../../../external.txt')
        result = self.run_tool('--ad-hoc')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink', result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(external.read_text(), 'outside input')

    def test_info_plist_symlink_is_rejected_before_reading_external_content(self):
        external = self.root / 'not-a-plist.txt'
        external.write_text('outside input')
        plist = self.source / 'Contents/Info.plist'
        plist.unlink()
        plist.symlink_to(external)
        result = self.run_tool('--ad-hoc')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink', result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_developer_id_fails_without_ad_hoc_fallback(self):
        before = tree_hashes(self.source)
        result = self.run_tool('--identity',
                               'Developer ID Application: Missing Signing Test (0000000000)')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Developer ID Application identity', result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(tree_hashes(self.source), before)

    def test_ad_hoc_must_be_explicit_not_disguised_as_developer_identity(self):
        result = self.run_tool('--identity', '-')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Developer ID Application identity', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
