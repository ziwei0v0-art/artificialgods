"""160 declared appearance packaging; temporary PNGs only, no app build/game."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib


ROOT = Path(__file__).resolve().parents[1]


def png(path, *, width=2, height=2, alpha=True, visible=None, color=(200, 110, 70), opacity=255):
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload)))
    rows = []
    for y in range(height):
        row = bytearray(b'\0')
        for x in range(width):
            pixel = (*color, opacity if visible is None or (x, y) in visible else 0)
            row.extend(pixel if alpha else pixel[:3])
        rows.append(row)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6 if alpha else 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


def manifest():
    def layer(name, file, bounds):
        return {'id': name, 'file': file, 'bounds': bounds}
    shrine = [55, 130, 200, 190]
    idol = [105, 150, 100, 110]
    incense = [130, 270, 30, 40]
    fruit = [170, 290, 30, 20]
    return {'version': 1, 'sampling': 'nearest', 'incenseAnchor': [0.5, 0.24],
            'layers': [layer('shrine', 'shrine.png', shrine), layer('idol', 'idol.png', idol),
                       layer('incense', 'incense.png', incense), layer('fruit', 'fruit.png', fruit)],
            'appearances': {
                'shrine_g1': {'layers': [layer('shrine', 'shrine-g1.png', shrine)]},
                'shrine_g2': {'layers': [layer('shrine', 'shrine-g2.png', shrine),
                                         layer('idol', 'idol-g2.png', idol)]},
                'offering_plate': {'layers': [layer('fruit', 'plate-fresh.png', fruit)],
                                   'fruitVariants': {'fresh': {'file': 'plate-fresh.png'},
                                                     'soft': {'file': 'plate-atlas.png', 'sourceRect': [0, 0, 2, 2]},
                                                     'ripe': {'file': 'plate-atlas.png', 'sourceRect': [2, 0, 2, 2]}}},
                'incense_burner': {'layers': [layer('incense', 'warm-incense.png', incense)],
                                   'incenseAnchor': [0.5, 0.2]},
                'bell': {'layers': [layer('bell', 'bell.png', [210, 275, 16, 30])]},
            }}


class DecorationPackagingTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('decoration_packaging_build', ROOT / 'tools/build_native.py')
        self.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.build)
        folder = tempfile.TemporaryDirectory(prefix='tianmu-decoration-package-')
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.source = self.folder / 'source'
        self.source.mkdir()
        self.resources = self.folder / 'temporary-resources'
        self.target = self.resources / 'art/scene'
        self.names = {'shrine.png', 'idol.png', 'incense.png', 'fruit.png', 'shrine-g1.png',
                      'shrine-g2.png', 'idol-g2.png', 'plate-fresh.png', 'plate-atlas.png',
                      'warm-incense.png', 'bell.png'}
        for name in self.names:
            png(self.source / name, width=4 if name == 'plate-atlas.png' else 2)
        self.save(manifest())

    def save(self, value):
        (self.source / 'manifest.json').write_text(json.dumps(value))

    def package(self):
        return self.build.copy_scene_art(self.source, self.resources)

    def target_bytes(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob('*') if path.is_file()}

    def rejected_preserving_target(self, value):
        before = self.target_bytes()
        self.save(value)
        with self.assertRaises(ValueError):
            self.package()
        self.assertEqual(self.target_bytes(), before)
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ['scene'])

    def test_copies_every_declared_appearance_and_shared_atlas_once(self):
        (self.source / 'private-reference.png').write_bytes(b'not production art')
        self.target.mkdir(parents=True)
        (self.target / 'withdrawn.png').write_bytes(b'old output')
        original = {path.name: path.read_bytes() for path in self.source.iterdir()}
        self.assertTrue(self.package())
        self.assertEqual(set(self.target_bytes()), self.names | {'manifest.json'})
        for name in self.names | {'manifest.json'}:
            self.assertEqual((self.target / name).read_bytes(), original[name])
        self.assertEqual({path.name: path.read_bytes() for path in self.source.iterdir()}, original)

    def test_base_without_appearances_and_valid_edge_anchors_remain_compatible(self):
        for optional in (None, {}):
            for anchor in (None, [0, 0], [1, 1], [0.5, 0.24]):
                with self.subTest(appearances=optional, anchor=anchor):
                    value = manifest()
                    if optional is None:
                        value.pop('appearances')
                    else:
                        value['appearances'] = optional
                    if anchor is None:
                        value.pop('incenseAnchor')
                    else:
                        value['incenseAnchor'] = anchor
                    self.save(value)
                    self.assertTrue(self.package())
                    self.assertEqual(set(self.target_bytes()),
                                     {'manifest.json', 'shrine.png', 'idol.png', 'incense.png', 'fruit.png'})

    def test_appearance_whitelist_structure_and_exact_layer_sets_are_required(self):
        self.package()
        invalid = [None, [], 'decorations', {'unknown': manifest()['appearances']['bell']}]
        for entry in (None, [], {}, {'layers': []}, {'layers': 'shrine'}):
            invalid.append({'shrine_g1': entry})
        for item, entry in manifest()['appearances'].items():
            for change in ('wrong', 'duplicate', 'missing', 'not-object'):
                value = copy.deepcopy(entry)
                if change == 'wrong':
                    value['layers'][0]['id'] = 'cloud'
                elif change == 'duplicate':
                    value['layers'].append(copy.deepcopy(value['layers'][0]))
                elif change == 'missing':
                    value['layers'].pop()
                else:
                    value['layers'][0] = None
                invalid.append({item: value})
        for appearances in invalid:
            with self.subTest(appearances=appearances):
                value = manifest(); value['appearances'] = appearances
                self.rejected_preserving_target(value)

    def test_plate_requires_all_three_valid_fruit_states(self):
        self.package()
        invalid = (None, {}, [], {'fresh': {'file': 'plate-fresh.png'}},
                   {'fresh': {'file': 'plate-fresh.png'}, 'soft': {'file': 'plate-fresh.png'},
                    'ripe': {'file': 'missing.png'}},
                   {'fresh': {'file': 'plate-fresh.png'}, 'soft': {'file': 'plate-fresh.png'},
                    'ripe': {'file': 'plate-fresh.png'}, 'old': {'file': 'plate-fresh.png'}})
        for variants in invalid:
            with self.subTest(variants=variants):
                value = manifest(); value['appearances']['offering_plate']['fruitVariants'] = variants
                self.rejected_preserving_target(value)
        value = manifest(); value['appearances']['offering_plate'].pop('fruitVariants')
        self.rejected_preserving_target(value)

    def test_invalid_base_or_paid_anchor_is_rejected_and_paid_anchor_is_required(self):
        self.package()
        for anchor in (None, [], [0.5], [0, 0, 0], [-0.01, 0], [0, 1.01],
                       [True, 0], ['0.5', 0], [float('inf'), 0], [0, float('nan')]):
            for paid in (False, True):
                with self.subTest(anchor=anchor, paid=paid):
                    value = manifest()
                    target = value['appearances']['incense_burner'] if paid else value
                    target['incenseAnchor'] = anchor
                    self.rejected_preserving_target(value)
        value = manifest(); value['appearances']['incense_burner'].pop('incenseAnchor')
        self.rejected_preserving_target(value)

    def test_paid_paths_stay_in_scene_and_geometry_is_validated_before_copy(self):
        self.package()
        outside = self.folder / 'outside.png'; png(outside)
        (self.source / 'escape.png').symlink_to(outside)
        (self.source / 'renamed.jpg').write_bytes((self.source / 'bell.png').read_bytes())
        invalid = [('file', name) for name in (None, '', 'missing.png', '../outside.png',
                                              '../A01/bell.png', str(outside), 'escape.png',
                                              './bell.png', 'nested/bell.png', 'renamed.jpg')]
        invalid += [('bounds', box) for box in (None, [55, 130, 0, 2], [54, 130, 2, 2],
                                               [424, 319, 2, 2], [55, 130, float('inf'), 2],
                                               [55, 130, True, 2])]
        invalid += [('sourceRect', box) for box in (None, [-1, 0, 1, 1], [0, 0, 0, 1],
                                                   [0, 0, 3, 2], [2, 0, 1, 1],
                                                   [0, 0, 1.5, 1], [0, 0, True, 1])]
        for field, content in invalid:
            with self.subTest(field=field, content=content):
                value = manifest(); value['appearances']['bell']['layers'][0][field] = content
                self.rejected_preserving_target(value)

    def test_actual_png_alpha_and_nonempty_crop_are_required_for_base_and_paid_images(self):
        self.package()
        (self.source / 'invalid.png').write_bytes(b'not a PNG')
        (self.source / 'truncated.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        png(self.source / 'noalpha.png', alpha=False)
        png(self.source / 'empty.png', visible=set())
        png(self.source / 'partial.png', width=4, visible={(0, 0)})
        for name, crop in (('invalid.png', None), ('truncated.png', None), ('noalpha.png', None),
                           ('empty.png', None), ('partial.png', [2, 0, 2, 2])):
            for paid in (False, True):
                with self.subTest(name=name, crop=crop, paid=paid):
                    value = manifest()
                    layer = value['appearances']['bell']['layers'][0] if paid else value['layers'][0]
                    layer['file'] = name
                    if crop is not None:
                        layer['sourceRect'] = crop
                    self.rejected_preserving_target(value)

    def test_nonzero_black_alpha_is_visible_even_below_hit_threshold(self):
        # A zero RGB value cannot be mistaken for alpha, and alpha 1 is visible
        # for resource loading even though it is below pointer-hit alpha 16.
        png(self.source / 'faint.png', width=4, color=(0, 0, 0), opacity=1, visible={(2, 1)})
        value = manifest()
        value['appearances']['bell']['layers'][0].update(file='faint.png', sourceRect=[2, 1, 1, 1])
        self.save(value)
        self.assertTrue(self.package())
        self.assertEqual((self.target / 'faint.png').read_bytes(), (self.source / 'faint.png').read_bytes())

    def test_copy_failure_on_paid_resource_keeps_existing_target(self):
        self.package()
        before = self.target_bytes()
        original_copy = self.build.shutil.copy2

        def fail_on_bell(source, destination):
            if Path(source).name == 'bell.png':
                raise OSError('isolated paid-image copy failure')
            return original_copy(source, destination)

        with patch.object(self.build.shutil, 'copy2', side_effect=fail_on_bell):
            with self.assertRaises(OSError):
                self.package()
        self.assertEqual(self.target_bytes(), before)
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ['scene'])

    def test_invalid_optional_entry_does_not_create_fresh_output(self):
        value = manifest(); value['appearances']['shrine_g2']['layers'][1]['file'] = 'missing.png'
        self.save(value)
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.resources.exists())


if __name__ == '__main__':
    unittest.main()
