"""Insect packaging in temporary resources, with the real windowless Swift loader."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib


ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location('insect_packaging_build', ROOT / 'tools/build_native.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PALETTE = {
    '普通褐色': [[96, 64, 39], [168, 117, 66], [214, 166, 106]],
    '中褐色': [[66, 45, 34], [123, 80, 51], [175, 128, 83]],
    '深褐色': [[41, 34, 31], [76, 55, 44], [118, 81, 59]],
    '白色': [[130, 126, 116], [198, 193, 175], [239, 234, 215]],
}
SOURCE_PALETTE = [[50, 60, 57], [89, 86, 82], [132, 126, 135]]


def png(path, width, height, pixels, *, alpha=True):
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload)))
    rows = []
    for y in range(height):
        row = bytearray(b'\0')
        for x in range(width):
            pixel = pixels.get((x, y), (0, 0, 0, 0))
            row.extend(pixel if alpha else pixel[:3])
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6 if alpha else 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


def manifest():
    common = {'canvasSize': [24, 24], 'sampleScale': 2, 'fps': 12,
              'sequence': [0, 1, 2, 1], 'palette': copy.deepcopy(PALETTE)}
    cute = dict(copy.deepcopy(common), kind='atlas', file='atlas.png', displayScale=2,
                frames=[{'sourceRect': [4 * frame, 0, 4, 4], 'anchor': [2, 2],
                         'bodyRows': [[2, 1, 2]], 'sourcePalette': copy.deepcopy(SOURCE_PALETTE)}
                        for frame in range(3)])
    realistic = dict(copy.deepcopy(common), kind='wingLayers',
                     body={'file': 'body.png', 'sourceRect': [0, 0, 4, 4], 'bounds': [-2, -2, 4, 4]},
                     upperWing={'file': 'wings.png', 'sourceRect': [0, 0, 4, 4],
                                'bounds': [-4, -7, 8, 6], 'pivot': [0, -1]},
                     lowerWing={'file': 'wings.png', 'sourceRect': [4, 0, 4, 4],
                                'bounds': [-4, 1, 8, 6], 'pivot': [0, 1]},
                     frames=[{'upperYScale': scale, 'lowerYScale': scale} for scale in (1, .55, .18)],
                     bodyPolygon=[[0, 1], [4, 1], [4, 4], [0, 4]],
                     warmGate={'minRed': 20, 'minGreenOverRed': .5, 'minGreenMinusBlue': 20},
                     lumaRange=[30, 220])
    return {'version': 1, 'sampling': 'nearest', 'styles': {'cute': cute, 'realistic': realistic}}


class InsectPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator_directory = tempfile.TemporaryDirectory(prefix='tianmu-insect-loader-check-')
        cls.addClassCleanup(cls.validator_directory.cleanup)
        cls.validator_binary = None

    def setUp(self):
        self.build = load_builder()
        directory = tempfile.TemporaryDirectory(prefix='tianmu-insect-package-')
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.source = self.folder / 'source'
        self.source.mkdir()
        self.resources = self.folder / 'resources'
        self.target = self.resources / 'art/insects'
        atlas = {}
        for frame in range(3):
            atlas[(4 * frame + frame, 0)] = (205, 220, 225, 180)
            for x in (1, 2):
                atlas[(4 * frame + x, 2)] = (*SOURCE_PALETTE[x - 1], 255)
        png(self.source / 'atlas.png', 12, 4, atlas)
        body = {(x, y): (180, 140, 70, 255) for y in (1, 2, 3) for x in (1, 2)}
        body[(2, 0)] = (230, 25, 25, 255)
        png(self.source / 'body.png', 4, 4, body)
        wings = {(x, y): (190, 210, 225, 150) for x in range(4) for y in range(4) if x + y > 0}
        wings.update({(x + 4, y): (150, 180, 200, 180) for x in range(4) for y in range(4) if x >= y})
        png(self.source / 'wings.png', 8, 4, wings)
        self.save(manifest())

    def save(self, value):
        (self.source / 'manifest.json').write_text(json.dumps(value, ensure_ascii=False))

    def real_validator(self):
        cls = type(self)
        if cls.validator_binary is None:
            cls.validator_binary = self.build._compile_insect_validator(Path(cls.validator_directory.name))
        return cls.validator_binary

    def package(self):
        function = self.build.copy_insect_art  # Missing API is a red before any compiler may run.
        binary = self.real_validator()
        with patch.object(self.build, '_compile_insect_validator', return_value=binary):
            return function(self.source, self.resources)

    def target_bytes(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob('*') if path.is_file()}

    def rejected(self, value, *, runtime=False):
        before = self.target_bytes()
        self.save(value)
        with self.assertRaisesRegex(ValueError, 'runtime' if runtime else 'Insect'):
            self.package()
        self.assertEqual(self.target_bytes(), before)
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ['insects'])

    def test_build_rejects_missing_insects_before_touching_a_fresh_output(self):
        build = load_builder()
        with tempfile.TemporaryDirectory(prefix='tianmu-insect-build-guard-') as directory:
            folder = Path(directory)
            output = folder / 'Untouched.app'
            with patch.object(build, 'ROOT', folder / 'empty-project'), \
                    patch.object(build.sys, 'argv', ['build_native.py', '--output', str(output)]), \
                    patch.object(build.subprocess, 'run', side_effect=AssertionError('No compiler or app may run')):
                failure = None
                try:
                    build.main()
                except Exception as error:
                    failure = error
            self.assertFalse(output.exists(), 'Missing required insect art must not create a partial candidate')
            self.assertIsInstance(failure, ValueError)
            self.assertIn('Insect', str(failure))

    def test_two_real_styles_are_validated_then_original_bytes_are_copied(self):
        (self.source / 'private-reference.png').write_bytes(b'not a production resource')
        self.target.mkdir(parents=True)
        (self.target / 'stale.png').write_bytes(b'old output')
        original = {path.name: path.read_bytes() for path in self.source.iterdir()}
        self.assertTrue(self.package())
        expected = {'manifest.json', 'atlas.png', 'body.png', 'wings.png'}
        self.assertEqual(set(self.target_bytes()), expected)
        self.assertEqual(self.target_bytes(), {name: original[name] for name in expected})
        self.assertEqual({path.name: path.read_bytes() for path in self.source.iterdir()}, original)

    def test_missing_source_and_missing_style_never_use_geometry_or_stale_art(self):
        function = self.build.copy_insect_art
        with self.assertRaisesRegex(ValueError, 'Insect'):
            function(self.folder / 'missing', self.resources)
        self.assertFalse(self.resources.exists())
        value = manifest(); value['styles'].pop('realistic'); self.save(value)
        with self.assertRaisesRegex(ValueError, 'Insect'):
            self.package()
        self.assertFalse(self.resources.exists())
        self.save(manifest()); self.package(); before = self.target_bytes()
        with self.assertRaisesRegex(ValueError, 'Insect'):
            function(self.folder / 'missing', self.resources)
        self.assertEqual(self.target_bytes(), before)

    def test_manifest_requires_exact_style_kinds_version_and_three_frames(self):
        self.package()
        invalid = [None, [], {}, {'version': 1, 'sampling': 'nearest', 'styles': {}}]
        for field, values in [('version', [True, 1.0, 2, '1']), ('sampling', [None, 'linear', True])]:
            for replacement in values:
                value = manifest(); value[field] = replacement; invalid.append(value)
        for replacement in [None, [], {'cute': manifest()['styles']['cute']},
                            dict(manifest()['styles'], extra={})]:
            value = manifest(); value['styles'] = replacement; invalid.append(value)
        for style in ('cute', 'realistic'):
            for kind in [None, 'wrong', 'wingLayers' if style == 'cute' else 'atlas']:
                value = manifest(); value['styles'][style]['kind'] = kind; invalid.append(value)
            for frames in [None, [], 'three', manifest()['styles'][style]['frames'][:2],
                           manifest()['styles'][style]['frames'] * 2]:
                value = manifest(); value['styles'][style]['frames'] = frames; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value):
                self.rejected(value)

    def test_common_geometry_sequence_and_four_integer_palettes_are_required(self):
        self.package()
        invalid = [('canvasSize', [0, 24]), ('canvasSize', [24.25, 24]), ('canvasSize', [24, True]),
                   ('canvasSize', [float('inf'), 24]), ('canvasSize', [23.25, 24]),
                   ('sampleScale', True), ('sampleScale', 1), ('sampleScale', 2.0),
                   ('fps', 0), ('fps', 30.01), ('fps', float('nan')), ('fps', '12'),
                   ('sequence', []), ('sequence', [0, 1, 2, 3]), ('sequence', [0, 1, True]),
                   ('sequence', [0, 0, 1]), ('sequence', [0, 1, 2] * 6),
                   ('palette', None), ('palette', {key: value for key, value in PALETTE.items() if key != '白色'}),
                   ('palette', dict(PALETTE, unknown=SOURCE_PALETTE))]
        for channel in [-1, 256, True, 22.5, '22']:
            palette = copy.deepcopy(PALETTE); palette['白色'][0][0] = channel
            invalid.append(('palette', palette))
        for style in ('cute', 'realistic'):
            for field, replacement in invalid:
                with self.subTest(style=style, field=field, replacement=replacement):
                    value = manifest(); value['styles'][style][field] = replacement
                    self.rejected(value)

    def test_paths_are_confined_and_internal_nested_resources_remain_byte_copies(self):
        self.package()
        outside = self.folder / 'outside.png'; outside.write_bytes((self.source / 'atlas.png').read_bytes())
        (self.source / 'escape.png').symlink_to(outside)
        for name in [None, '', 7, '../outside.png', str(outside), 'escape.png', 'missing.png', 'body.txt']:
            with self.subTest(name=name):
                value = manifest(); value['styles']['cute']['file'] = name
                self.rejected(value)
        nested = self.source / 'nested'; nested.mkdir()
        (nested / 'atlas.png').write_bytes((self.source / 'atlas.png').read_bytes())
        (self.source / 'atlas-alias.png').symlink_to(nested / 'atlas.png')
        for name in ['nested/atlas.png', 'atlas-alias.png']:
            value = manifest(); value['styles']['cute']['file'] = name; self.save(value)
            self.assertTrue(self.package())
            copied = self.target / name
            self.assertFalse(copied.is_symlink())
            self.assertEqual(copied.read_bytes(), (nested / 'atlas.png').read_bytes())
        before = self.target_bytes()
        (self.source / 'manifest.json').unlink()
        external = self.folder / 'external.json'; external.write_text(json.dumps(manifest()))
        (self.source / 'manifest.json').symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'Insect'):
            self.package()
        self.assertEqual(self.target_bytes(), before)

    def test_png_signature_alpha_visible_crop_and_source_bounds_are_required(self):
        self.package()
        (self.source / 'invalid.png').write_bytes(b'not PNG')
        (self.source / 'truncated.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        png(self.source / 'noalpha.png', 12, 4, {(1, 2): (50, 60, 57, 255)}, alpha=False)
        png(self.source / 'transparent.png', 12, 4, {})
        for name in ('invalid.png', 'truncated.png', 'noalpha.png', 'transparent.png'):
            with self.subTest(name=name):
                value = manifest(); value['styles']['cute']['file'] = name
                self.rejected(value)
        for rect in [None, [-1, 0, 4, 4], [0, 0, 0, 4], [0, 0, True, 4],
                     [0, 0, 4.5, 4], [0, 0, 13, 4], [12, 0, 1, 1], [0, 0, 10 ** 200, 4]]:
            with self.subTest(rect=rect):
                value = manifest(); value['styles']['cute']['frames'][0]['sourceRect'] = rect
                self.rejected(value)

    def test_atlas_anchors_mask_intervals_and_source_palette_are_checked(self):
        self.package()
        for field, replacement in [('anchor', None), ('anchor', [True, 2]), ('anchor', [-1, 2]),
                                   ('anchor', [5, 2]), ('bodyRows', None), ('bodyRows', []),
                                   ('bodyRows', [[2, 1, 4]]), ('bodyRows', [[4, 0, 1]]),
                                   ('bodyRows', [[2, 2, 1]]), ('bodyRows', [[2, 1, True]]),
                                   ('bodyRows', [[2, 1, 2], [2, 2, 3]]),
                                   ('sourcePalette', []), ('sourcePalette', [[50, 60, 57]] * 3)]:
            with self.subTest(field=field, replacement=replacement):
                value = manifest(); value['styles']['cute']['frames'][0][field] = replacement
                self.rejected(value)
        for scale in (0, -1, True, 4.1, 10 ** 200):
            value = manifest(); value['styles']['cute']['displayScale'] = scale
            self.rejected(value)
        value = manifest(); value['styles']['cute']['frames'][0]['anchor'] = [0, 0]
        value['styles']['cute']['displayScale'] = 4
        self.rejected(value)  # 16 pt rect exceeds this canvas's positive 12 pt edge.

    def test_rig_bounds_pivots_scales_polygon_and_color_gate_are_checked(self):
        self.package()
        invalid = []
        for part in ('body', 'upperWing', 'lowerWing'):
            for bounds in [[-13, -2, 4, 4], [10, 0, 4, 4], [0, 0, 0, 1], [0, 0, True, 1]]:
                value = manifest(); value['styles']['realistic'][part]['bounds'] = bounds; invalid.append(value)
        for pivot in [None, [10, 10], [False, 0], [0, float('nan')]]:
            value = manifest(); value['styles']['realistic']['upperWing']['pivot'] = pivot; invalid.append(value)
        for scale in [None, True, -1.001, 1.001, float('inf')]:
            value = manifest(); value['styles']['realistic']['frames'][0]['upperYScale'] = scale; invalid.append(value)
        for polygon in [None, [], [[0, 0], [1, 1], [2, 2]], [[0, 0], [4, 0], [5, 4]],
                        [[0, 0], [4, 4], [0, 4], [4, 0]]]:
            value = manifest(); value['styles']['realistic']['bodyPolygon'] = polygon; invalid.append(value)
        for field, replacement in [('minRed', True), ('minRed', -1), ('minRed', 256),
                                   ('minGreenOverRed', -0.1), ('minGreenOverRed', 1.1),
                                   ('minGreenMinusBlue', 1.5), ('minGreenMinusBlue', -1)]:
            value = manifest(); value['styles']['realistic']['warmGate'][field] = replacement; invalid.append(value)
        for span in [None, [0, 0], [100, 99], [-1, 200], [0, 256], [0, True]]:
            value = manifest(); value['styles']['realistic']['lumaRange'] = span; invalid.append(value)
        value = manifest(); value['styles']['realistic']['body']['rotation'] = 10; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value):
                self.rejected(value)

    def test_real_loader_rejects_static_frames_and_masks_that_select_no_color(self):
        self.package()
        invalid = []
        value = manifest(); value['styles']['cute']['frames'] = [copy.deepcopy(value['styles']['cute']['frames'][0])] * 3
        invalid.append(value)
        value = manifest(); value['styles']['realistic']['frames'] = [{'upperYScale': 1, 'lowerYScale': 1}] * 3
        invalid.append(value)
        value = manifest(); value['styles']['cute']['frames'][0]['sourcePalette'] = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        invalid.append(value)
        value = manifest(); value['styles']['realistic']['warmGate']['minRed'] = 255
        invalid.append(value)
        value = manifest(); value['styles']['realistic']['bodyPolygon'] = [[0, 0], [1, 0], [1, 1], [0, 1]]
        invalid.append(value)
        for value in invalid:
            with self.subTest(value=value):
                self.rejected(value, runtime=True)

    def test_zero_wing_scale_and_omitted_sequence_are_valid_if_three_sprites_differ(self):
        value = manifest()
        value['styles']['realistic']['frames'][1] = {'upperYScale': 0, 'lowerYScale': 0}
        value['styles']['cute'].pop('sequence')
        value['styles']['realistic'].pop('sequence')
        self.save(value)
        self.assertTrue(self.package())
        self.assertEqual(json.loads((self.target / 'manifest.json').read_text()), value)

    def test_copy_failure_preserves_existing_output_and_no_staging_survives(self):
        self.package(); before = self.target_bytes()
        original = self.build.shutil.copy2

        def fail_last(source, destination):
            if Path(source).name == 'wings.png':
                raise OSError('isolated final image copy failure')
            return original(source, destination)

        with patch.object(self.build.shutil, 'copy2', side_effect=fail_last):
            with self.assertRaises(OSError):
                self.package()
        self.assertEqual(self.target_bytes(), before)
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ['insects'])

    def test_output_symlink_cannot_redirect_packaging(self):
        external = self.folder / 'external-output'; external.mkdir()
        sentinel = external / 'sentinel'; sentinel.write_bytes(b'unchanged')
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Insect'):
            self.package()
        self.assertEqual(sentinel.read_bytes(), b'unchanged')
        self.assertEqual([path.name for path in external.iterdir()], ['sentinel'])


if __name__ == '__main__':
    unittest.main()
