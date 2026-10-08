"""167 display identity boundaries, with synthetic bugs and no save access."""
from pathlib import Path
import random
import tempfile
import unittest

from tianmu_mvp.model import COLORS, GameState, Insect
from tianmu_mvp.service import ApplicationService


class ReferenceSnapshotTests(unittest.TestCase):
    def test_desktop_snapshot_preserves_real_sex_for_both_rendered_shapes(self):
        state = GameState.new(random.Random(167))
        for sex in ('F', 'M'):
            bug = Insect('desktop-' + sex, sex, ('A', 'B'), COLORS[0], .2, .3)
            state.desktop[bug.id] = bug
        with tempfile.TemporaryDirectory() as directory:
            service = ApplicationService(Path(directory) / 'unused.json', state)
            rows = service.snapshot(100)['desktop']
            self.assertEqual({row['id']: row.get('sex') for row in rows},
                             {'desktop-F': 'F', 'desktop-M': 'M'})
            self.assertFalse(service.save_path.exists())

    def test_bottle_preview_has_stable_real_ids_rare_colors_and_no_mutation(self):
        state = GameState.new(random.Random(167))
        for index in range(60):
            bug = Insect('brown-%03d' % index, 'M' if index % 2 else 'F',
                         ('A', 'B'), COLORS[0], .2, .3)
            state.bottle[bug.id] = bug
        for index, color in enumerate(COLORS[1:]):
            bug = Insect('rare-%d' % index, 'M', ('A', 'B'), color, .2, .3)
            state.bottle[bug.id] = bug
        original = dict(state.bottle)
        with tempfile.TemporaryDirectory() as directory:
            service = ApplicationService(Path(directory) / 'unused.json', state)
            preview = service.snapshot(100).get('bottle_individuals', [])
            self.assertEqual(len(preview), 12)
            self.assertEqual(len({row['id'] for row in preview}), 12)
            self.assertEqual({row['color'] for row in preview}, set(COLORS))
            for row in preview:
                bug = original[row['id']]
                self.assertEqual(row, {'id': bug.id, 'color': bug.color, 'sex': bug.sex})
            state.bottle = dict(reversed(list(state.bottle.items())))
            self.assertEqual(service.snapshot(100)['bottle_individuals'], preview)
            self.assertEqual(state.bottle, original)
            removed = preview[0]['id']
            state.bottle.pop(removed)
            after = service.snapshot(100)['bottle_individuals']
            self.assertNotIn(removed, {row['id'] for row in after})
            self.assertEqual(len(after), 12)
            self.assertFalse(service.save_path.exists())

    def test_empty_bottle_is_an_empty_display_without_invented_individuals(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ApplicationService(Path(directory) / 'unused.json', GameState.new(random.Random(167)))
            self.assertEqual(service.snapshot(100).get('bottle_individuals'), [])


if __name__ == '__main__':
    unittest.main()
