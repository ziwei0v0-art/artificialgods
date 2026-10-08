"""Scene packaging checks using isolated temporary files, never a game/worker."""
import copy
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib


ROOT = Path(__file__).resolve().parents[1]


def write_png(path, *, second_alpha=0):
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload)))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress((b'\0\xff\0\0\xff\0\0\0' + bytes([second_alpha])) * 2))
                     + chunk(b'IEND', b''))


def manifest():
    return {'version': 1, 'sampling': 'nearest', 'attendantHeight': 100,
            'layers': [
                {'id': 'shrine', 'file': 'shrine.png', 'bounds': [55, 130, 200, 190]},
                {'id': 'idol', 'file': 'idol.png', 'bounds': [105, 150, 100, 110]},
                {'id': 'incense', 'file': 'incense.png', 'bounds': [130, 270, 30, 40]},
                {'id': 'fruit', 'file': 'fruit.png', 'sourceRect': [0, 0, 2, 2],
                 'bounds': [170, 290, 30, 20]}]}


class ShrineArtPackagingTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('scene_packaging_build', ROOT / 'tools/build_native.py')
        self.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.build)
        self.temporary = tempfile.TemporaryDirectory(prefix='tianmu-scene-package-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.source = self.folder / 'source'
        self.source.mkdir()
        self.resources = self.folder / 'Check.app/Contents/Resources'
        self.target = self.resources / 'art/scene'
        self.original = manifest()
        for name in ('shrine.png', 'idol.png', 'incense.png', 'fruit.png'):
            write_png(self.source / name)
        self.save(self.original)

    def save(self, value):
        (self.source / 'manifest.json').write_text(json.dumps(value))

    def package(self):
        operation = getattr(self.build, 'copy_scene_art', None)
        self.assertTrue(callable(operation), 'Native build must package manifest-owned scene art')
        return operation(self.source, self.resources)

    def target_bytes(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob('*') if path.is_file()}

    def assert_rejected_before_write(self, value):
        self.save(value)
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.resources.exists(), 'Rejected input must not create output directories')

    def test_copies_only_owned_files_and_replaces_stale_scene(self):
        (self.source / 'private-reference.png').write_bytes(b'not a production asset')
        (self.source / 'notes.txt').write_text('not bundled')
        self.target.mkdir(parents=True)
        (self.target / 'withdrawn.png').write_bytes(b'old output')
        self.assertTrue(self.package())
        expected_names = {'manifest.json', 'shrine.png', 'idol.png', 'incense.png', 'fruit.png'}
        self.assertEqual(set(self.target_bytes()), expected_names)
        for name in expected_names:
            self.assertEqual((self.target / name).read_bytes(), (self.source / name).read_bytes())

    def test_copies_every_fruit_variant_and_shared_atlas_once(self):
        # Both referenced columns must contain visible alpha for the native loader.
        write_png(self.source / 'fruit-stages.png', second_alpha=255)
        value = manifest()
        value['fruitVariants'] = {
            'fresh': {'file': 'fruit.png'},
            'soft': {'file': 'fruit-stages.png', 'sourceRect': [0, 0, 1, 2]},
            'ripe': {'file': 'fruit-stages.png', 'sourceRect': [1, 0, 1, 2]}}
        self.save(value)
        self.assertTrue(self.package())
        self.assertEqual(set(self.target_bytes()),
                         {'manifest.json', 'shrine.png', 'idol.png', 'incense.png', 'fruit.png', 'fruit-stages.png'})
        self.assertEqual(json.loads((self.target / 'manifest.json').read_text()), value)

    def test_rejects_bad_manifest_version_sampling_and_layer_membership(self):
        invalid = [None, [], 'scene', {}, {'version': 1}]
        for field, values in [('version', [0, 2, True, '1']),
                              ('sampling', [None, 'smooth', '', 1]),
                              ('layers', [None, {}, [], manifest()['layers'][:3]])]:
            for value in values:
                item = manifest(); item[field] = value; invalid.append(item)
        for index, replacement in [(1, 'shrine'), (2, 'unknown'), (3, None)]:
            item = manifest(); item['layers'][index]['id'] = replacement; invalid.append(item)
        item = manifest(); item['layers'].append(copy.deepcopy(item['layers'][0])); invalid.append(item)
        item = manifest(); item['layers'][0] = 'shrine'; invalid.append(item)
        for value in invalid:
            with self.subTest(value=value):
                self.assert_rejected_before_write(value)

    def test_rejects_missing_unsafe_and_non_png_references(self):
        outside = self.folder / 'outside.png'; write_png(outside)
        (self.source / 'escape.png').symlink_to(outside)
        (self.source / 'not-png.txt').write_text('not PNG')
        nested = self.source / 'nested'; nested.mkdir(); write_png(nested / 'nested.png')
        for name in [None, '', 4, '../outside.png', str(outside), 'escape.png',
                     'missing.png', 'not-png.txt', 'nested/nested.png', './fruit.png', 'fruit.png/']:
            with self.subTest(name=name):
                value = manifest(); value['layers'][-1]['file'] = name
                self.assert_rejected_before_write(value)

    def test_manifest_symlink_escape_is_rejected(self):
        (self.source / 'manifest.json').unlink()
        external = self.folder / 'external-manifest.json'; external.write_text(json.dumps(manifest()))
        (self.source / 'manifest.json').symlink_to(external)
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.resources.exists())

    def test_invalid_manifest_preserves_existing_output(self):
        self.package(); before = self.target_bytes()
        value = manifest(); value['layers'][2]['file'] = 'missing.png'; self.save(value)
        with self.assertRaises(ValueError):
            self.package()
        self.assertEqual(self.target_bytes(), before)

    def test_copy_failure_preserves_existing_output(self):
        self.package(); before = self.target_bytes()
        with patch.object(self.build.shutil, 'copy2', side_effect=OSError('isolated copy failure')):
            with self.assertRaises(OSError):
                self.package()
        self.assertEqual(self.target_bytes(), before)
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ['scene'])

    def test_missing_source_only_allows_a_clean_development_fallback(self):
        self.source = self.folder / 'missing'
        self.assertFalse(self.package())
        self.assertFalse(self.resources.exists())
        self.target.mkdir(parents=True)
        (self.target / 'stale.png').write_bytes(b'preserve old bytes')
        before = self.target_bytes()
        with self.assertRaises(ValueError):
            self.package()
        self.assertEqual(self.target_bytes(), before)

    def test_accepts_empty_or_partial_fruit_variants_for_runtime_fallback(self):
        for variants in [{}, {'fresh': {'file': 'fruit.png'}}, {'soft': {'file': 'fruit.png'}},
                         {'ripe': {'file': 'fruit.png'}},
                         {'fresh': {'file': 'fruit.png'}, 'ripe': {'file': 'fruit.png'}}]:
            with self.subTest(variants=variants):
                value = manifest(); value['fruitVariants'] = variants; self.save(value)
                self.assertTrue(self.package())
                self.assertEqual(json.loads((self.target / 'manifest.json').read_text()), value)

    def test_rejects_invalid_fruit_variants(self):
        for variants in [None, [],
                         {'fresh': {}, 'soft': {'file': 'fruit.png'}, 'ripe': {'file': 'fruit.png'}},
                         {'fresh': {'file': 'fruit.png'}, 'soft': {'file': 'fruit.png'}, 'ripe': {'file': 'missing.png'}},
                         {'fresh': {'file': 'fruit.png'}, 'soft': {'file': 'fruit.png'}, 'old': {'file': 'fruit.png'}}]:
            with self.subTest(variants=variants):
                value = manifest(); value['fruitVariants'] = variants
                self.assert_rejected_before_write(value)

    def test_rejects_malformed_geometry_before_copy(self):
        for field, values in [('bounds', [None, [1, 2, 3], [55, 130, 0, 1], [55, 130, -1, 1],
                                           [55, 130, float('inf'), 1], [54, 130, 1, 1],
                                           [424, 319, 2, 2], [55, 130, True, 1]]),
                              ('sourceRect', [None, [0, 0, 2], [0, 0, 0, 1], [-1, 0, 1, 1],
                                              [0, 0, 1.5, 1], [0, 0, True, 1]])]:
            for geometry in values:
                with self.subTest(field=field, geometry=geometry):
                    value = manifest(); value['layers'][0][field] = geometry
                    self.assert_rejected_before_write(value)
        for height in [None, 0, -1, 181, float('nan'), '100', True]:
            with self.subTest(attendantHeight=height):
                value = manifest(); value['attendantHeight'] = height
                self.assert_rejected_before_write(value)

    def test_accepts_attendant_height_at_180_and_omitted_default(self):
        for height in [180, None]:
            with self.subTest(attendantHeight=height):
                value = manifest()
                if height is None:
                    del value['attendantHeight']
                else:
                    value['attendantHeight'] = height
                self.save(value)
                self.assertTrue(self.package())
                self.assertEqual(json.loads((self.target / 'manifest.json').read_text()), value)

    def test_withdrawn_098_output_is_not_modified(self):
        output = self.folder / 'Withdrawn.app'
        info = output / 'Contents/Info.plist'; info.parent.mkdir(parents=True)
        original = plistlib.dumps({'CFBundleShortVersionString': '0.9.8', 'CFBundleVersion': '9'})
        info.write_bytes(original)
        # Confine even a missing early guard to empty temporary inputs; no compiler or game may run.
        with patch.object(self.build.sys, 'argv', ['build_native.py', '--output', str(output)]), \
                patch.object(self.build, 'ROOT', self.folder / 'isolated-empty-project'), \
                patch.object(self.build.subprocess, 'run', side_effect=AssertionError('No process is permitted')):
            try:
                self.build.main()
            except BaseException as error:
                self.assertIsInstance(error, SystemExit, 'Withdrawn output must be rejected before build inputs are touched')
            else:
                self.fail('Withdrawn output must be rejected')
        self.assertEqual(info.read_bytes(), original)
        self.assertEqual([path.name for path in info.parent.iterdir()], ['Info.plist'])


if __name__ == '__main__':
    unittest.main()
