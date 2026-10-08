"""Strict save boundaries and write preflight; temporary files, no UI/worker."""
import copy
import datetime
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from tianmu_mvp.model import COLORS, GameState
from tianmu_mvp.service import ApplicationService
from tianmu_mvp import storage
from tianmu_mvp.timer import TimerSession


MAX_INT = (1 << 63) - 1


class StorageIntegrityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='tianmu-integrity-')
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'state.json'
        self.backup = Path(str(self.path) + '.bak')
        self.game = GameState.new(rng=random.Random(19))
        self.game.game_timezone = 'UTC'
        self.raw = storage._state_dict(self.game)

    def rejected(self, raw, code='save_corrupt'):
        encoded = json.dumps(raw, ensure_ascii=False).encode()
        self.path.write_bytes(encoded)
        backup = json.dumps(self.raw, ensure_ascii=False).encode()
        self.backup.write_bytes(backup)
        with self.assertRaises(ValueError) as raised:
            storage.load_state(self.path)
        self.assertEqual(getattr(raised.exception, 'code', None), code, str(raised.exception))
        self.assertEqual(getattr(raised.exception, 'message', None), str(raised.exception))
        self.assertEqual(self.path.read_bytes(), encoded)
        self.assertEqual(self.backup.read_bytes(), backup)

    def populated(self):
        game = copy.deepcopy(self.game)
        game.advance(20)
        return storage._state_dict(game)

    def test_public_decoder_roundtrips_without_save_io_and_errors_remain_value_errors(self):
        decoder = getattr(storage, 'decode_state_bytes', None)
        self.assertTrue(callable(decoder), 'Recovery needs a decoder independent of save paths')
        restored = decoder(json.dumps(self.raw).encode())
        self.assertEqual(storage._state_dict(restored), self.raw)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.backup.exists())
        error_type = getattr(storage, 'SaveLoadError', None)
        self.assertTrue(isinstance(error_type, type) and issubclass(error_type, ValueError))
        with self.assertRaises(error_type) as raised:
            decoder(b'{broken')
        self.assertEqual(raised.exception.code, 'save_corrupt')
        self.assertEqual(raised.exception.message, str(raised.exception))

    def test_version_type_corruption_is_distinct_from_unsupported_integer_version(self):
        for value in (True, 1.0, '1', None):
            with self.subTest(value=value):
                self.rejected({**self.raw, 'schema_version': value})
        self.rejected({**self.raw, 'schema_version': 2}, 'save_incompatible')

    def test_decoder_classifies_broken_rng_deep_json_and_duplicate_fields_as_corrupt(self):
        raw = {**self.raw, 'rng_state': []}
        ordinary = json.dumps(self.raw)
        duplicate = ordinary[:-1] + ', "coins": 9}'
        for label, payload in [('rng', json.dumps(raw).encode()), ('duplicate', duplicate.encode()),
                               ('deep', ('[' * 2000 + '0' + ']' * 2000).encode()),
                               ('encoding', b'\xff\xfe\xfa')]:
            with self.subTest(label=label):
                with self.assertRaises(ValueError) as raised:
                    storage.decode_state_bytes(payload)
                self.assertEqual(getattr(raised.exception, 'code', None), 'save_corrupt')
                self.assertFalse(self.path.exists())
                self.assertFalse(self.backup.exists())

    def test_unreadable_and_missing_main_with_backup_are_distinct_and_do_not_create_new_game(self):
        self.path.write_text('{}')
        with patch('pathlib.Path.open', side_effect=PermissionError('isolated permission failure')):
            with self.assertRaises(ValueError) as raised:
                storage.load_state(self.path)
        self.assertEqual(getattr(raised.exception, 'code', None), 'save_unreadable')
        self.path.unlink()
        self.backup.write_bytes(b'not necessarily a valid backup')
        with self.assertRaises(ValueError) as raised:
            storage.load_state(self.path)
        self.assertEqual(getattr(raised.exception, 'code', None), 'save_missing')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.backup.read_bytes(), b'not necessarily a valid backup')
        self.backup.unlink()
        self.assertEqual(storage.load_state(self.path).onboarding, 'shrine')
        self.assertFalse(self.path.exists())

    def test_integer_fields_reject_coercion_negative_and_native_overflow(self):
        for name in ('coins', 'elapsed_seconds', 'active_capture_seconds', 'next_insect_number', 'timer_remaining'):
            for value in (-1, 1.9, '12', True, MAX_INT + 1):
                with self.subTest(field=name, value=value):
                    self.rejected({**self.raw, name: value})
        self.rejected({**self.raw, 'next_insect_number': 0})
        self.rejected({**self.raw, 'active_capture_seconds': 86401})
        old = {**self.raw, 'elapsed_seconds': -1}
        old.pop('routine')
        self.rejected(old)

    def test_collection_containers_and_individual_ids_are_not_silently_coerced(self):
        for name in ('desktop', 'bottle', 'sold_ids', 'owned_items', 'discovered_colors'):
            with self.subTest(field=name):
                self.rejected({**self.raw, name: 'bell'})
        for value in ('', True, 7, None):
            with self.subTest(id=value):
                raw = self.populated()
                raw['desktop'][0]['id'] = value
                self.rejected(raw)
                self.rejected({**self.raw, 'sold_ids': [value]})
        self.rejected({**self.raw, 'owned_items': ['bell', 'bell']})
        self.rejected({**self.raw, 'discovered_colors': ['白色', '白色']})

    def test_global_duplicates_and_reused_standard_number_are_rejected(self):
        for location in ('desktop', 'bottle', 'sold_ids'):
            with self.subTest(location=location):
                raw = self.populated()
                bug = copy.deepcopy(raw['desktop'][0])
                raw[location].append(bug['id'] if location == 'sold_ids' else bug)
                self.rejected(raw)
        raw = self.populated()
        raw['next_insect_number'] = 1
        self.rejected(raw)
        self.rejected({**self.raw, 'sold_ids': ['bug-00009'], 'next_insect_number': 9})

    def test_coordinates_are_finite_numeric_normalized_values(self):
        for name in ('x', 'y'):
            for value in (float('nan'), float('inf'), -0.1, 1.1, '0.5', True):
                with self.subTest(field=name, value=value):
                    raw = self.populated()
                    raw['desktop'][0][name] = value
                    self.rejected(raw)

    def test_schedules_accept_only_none_or_bounded_nonnegative_integers(self):
        for name in ('first_spawn_at', 'next_breed_at', 'next_auto_capture_at', 'next_empty_refill_at'):
            for value in (-1, 1.5, '4', True, float('nan'), MAX_INT + 1):
                with self.subTest(field=name, value=value):
                    self.rejected({**self.raw, name: value})

    def test_prices_require_complete_four_colors_and_nonnegative_integer_amounts(self):
        for value in (-1, 1.5, '8', True, MAX_INT + 1):
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw['prices']['白色'] = value
                self.rejected(raw)
        raw = copy.deepcopy(self.raw)
        raw['prices'].pop('白色')
        self.rejected(raw)
        raw = copy.deepcopy(self.raw)
        raw['prices']['unknown'] = 1
        self.rejected(raw)

    def test_item_ownership_slot_and_legacy_plate_mirror_must_agree(self):
        changes = [
            {'owned_items': ['unknown']}, {'placed_items': {'unknown': 'bell'}},
            {'owned_items': ['bell'], 'placed_items': {'plate': 'bell'}},
            {'placed_items': {'bell': 'bell'}}, {'placed_item': 'unknown'},
            {'owned_items': ['bell'], 'placed_item': 'bell'},
            {'owned_items': ['offering_plate'], 'placed_item': 'offering_plate', 'placed_items': {'plate': 'unknown'}},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.rejected({**self.raw, **change})

    def test_signs_discoveries_and_dates_are_valid_without_inventing_missing_old_dates(self):
        changes = [
            {'sign_history': {'not-a-date': '1'}}, {'sign_history': {'2032-04-05': '12'}},
            {'sign_history': {'2032-04-05': True}}, {'daily_sign_date': '2032-04-05', 'daily_sign': 'bad'},
            {'daily_sign_date': None, 'daily_sign': '1'},
            {'daily_sign_date': '2032-04-05', 'daily_sign': '1', 'sign_history': {'2032-04-05': '2'}},
            {'discovered_colors': ['blue']}, {'discovery_dates': {'blue': '2032-04-05'}},
            {'discovered_colors': ['白色'], 'discovery_dates': {'白色': '2032-02-30'}},
            {'discovery_dates': {'白色': '2032-04-05'}},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.rejected({**self.raw, **change})

    def test_present_invalid_timer_never_falls_back_to_legacy_fields(self):
        for value in (None, {}, [], False, 0, '', {'junk': 1}, {'notification_enabled': False}):
            with self.subTest(value=value):
                self.rejected({**self.raw, 'timer_session': value})

    def test_timer_core_fields_are_required_but_missing_old_preferences_keep_defaults(self):
        for name in ('mode', 'status', 'deadline', 'remaining_seconds', 'started_at', 'elapsed_seconds'):
            with self.subTest(missing=name):
                raw = copy.deepcopy(self.raw)
                raw['timer_session'].pop(name)
                self.rejected(raw)
        for mode, name in (('countdown', 'countdown_seconds'), ('pomodoro', 'phase'),
                           ('pomodoro', 'work_seconds'), ('pomodoro', 'break_seconds')):
            with self.subTest(mode=mode, missing=name):
                raw = copy.deepcopy(self.raw)
                raw['timer_session']['mode'] = mode
                raw['timer_session'].pop(name)
                self.rejected(raw)
        raw = copy.deepcopy(self.raw)
        for name in ('clock_timezone', 'show_traditional', 'sound_enabled', 'widget_enabled', 'notification_enabled'):
            raw['timer_session'].pop(name)
        self.path.write_text(json.dumps(raw))
        restored = storage.load_state(self.path)
        self.assertEqual(restored.timer_session.status, 'idle')
        self.assertEqual(restored.timer_session.clock_timezone, 'local')
        self.assertTrue(restored.timer_session.notification_enabled)

    def test_timer_integer_durations_and_boolean_preferences_are_strict(self):
        for name in ('remaining_seconds', 'elapsed_seconds', 'countdown_seconds', 'work_seconds', 'break_seconds'):
            for value in (-1, 0.5, '5', True, MAX_INT + 1):
                with self.subTest(field=name, value=value):
                    raw = copy.deepcopy(self.raw)
                    raw['timer_session'][name] = value
                    self.rejected(raw)
        for name in ('show_traditional', 'sound_enabled', 'widget_enabled', 'notification_enabled'):
            for value in ('false', 0, 1, None):
                with self.subTest(field=name, value=value):
                    raw = copy.deepcopy(self.raw)
                    raw['timer_session'][name] = value
                    self.rejected(raw)

    def test_legacy_timer_values_are_validated_before_migration(self):
        for name, values in [('timer_deadline', ('200', True, float('nan'), float('inf'))),
                             ('timer_remaining', (-1, 1.5, '5', True)),
                             ('timer_completed', ('false', 0, None))]:
            for value in values:
                with self.subTest(field=name, value=value):
                    raw = {**self.raw, name: value}
                    raw.pop('timer_session')
                    self.rejected(raw)

    def test_timer_anchors_match_state_but_expired_running_timer_is_valid(self):
        for change in ({'mode': 'countdown', 'status': 'paused', 'deadline': 100.0},
                       {'mode': 'countdown', 'status': 'finished', 'deadline': 100.0},
                       {'mode': 'stopwatch', 'status': 'idle', 'started_at': 100.0},
                       {'mode': 'stopwatch', 'status': 'running', 'started_at': 100.0, 'deadline': 150.0},
                       {'mode': 'countdown', 'status': 'running', 'deadline': True}):
            with self.subTest(change=change):
                raw = copy.deepcopy(self.raw)
                raw['timer_session'].update(change)
                self.rejected(raw)

    def test_save_validation_precedes_mkdir_backup_and_replacement(self):
        storage.save_state(self.path, self.game)
        self.game.coins = 4
        storage.save_state(self.path, self.game)
        original, backup = self.path.read_bytes(), self.backup.read_bytes()
        names = set(self.path.parent.iterdir())
        for value in (-1, 1.5, True, MAX_INT + 1):
            with self.subTest(value=value):
                invalid = copy.deepcopy(self.game)
                invalid.coins = value
                with patch('tianmu_mvp.storage.tempfile.mkstemp') as create_temp:
                    with self.assertRaises(ValueError):
                        storage.save_state(self.path, invalid)
                    create_temp.assert_not_called()
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.backup.read_bytes(), backup)
                self.assertEqual(set(self.path.parent.iterdir()), names)
        invalid = copy.deepcopy(self.game)
        invalid.coins = -1
        new_path = self.path.parent / 'not-created' / 'state.json'
        with self.assertRaises(ValueError):
            storage.save_state(new_path, invalid)
        self.assertFalse(new_path.parent.exists())

    def test_overflowing_sale_rolls_back_inventory_money_and_files(self):
        app = ApplicationService(self.path)
        app.game.game_timezone = 'UTC'
        app.game.advance(15)
        bug = next(iter(app.game.desktop.values()))
        self.assertTrue(app.handle({'action': 'catch', 'ids': [bug.id]}, now=100)['ok'])
        app.game.coins = MAX_INT
        self.assertTrue(app.handle({'action': 'checkpoint'}, now=100)['ok'])
        before = copy.deepcopy(storage._state_dict(app.game))
        original, backup = self.path.read_bytes(), self.backup.read_bytes()
        preview = app.handle({'action': 'sale_preview', 'color': bug.color, 'count': 1}, now=100)
        reply = app.handle({'action': 'sale_confirm', 'token': preview['sale']['token']}, now=100)
        self.assertFalse(reply['ok'])
        self.assertEqual(storage._state_dict(app.game), before)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.backup.read_bytes(), backup)

    def test_compatible_legacy_defaults_and_custom_prices_are_preserved(self):
        raw = copy.deepcopy(self.raw)
        for name in ('routine', 'timer_session', 'timer_completed', 'onboarding', 'game_timezone', 'placed_items'):
            raw.pop(name)
        raw.update(owned_items=['offering_plate'], placed_item='offering_plate',
                   elapsed_seconds=15, active_capture_seconds=456, discovered_colors=['白色'])
        raw['prices']['白色'] = 0
        self.path.write_text(json.dumps(raw))
        original = self.path.read_bytes()
        with patch('tianmu_mvp.model.local_timezone', return_value='Pacific/Honolulu'):
            restored = storage.load_state(self.path)
        self.assertEqual(restored.onboarding, 'legacy')
        self.assertEqual(restored.placed_items, {'plate': 'offering_plate'})
        self.assertEqual(restored.active_capture_seconds, 456)
        self.assertEqual(restored.discovery_dates, {})
        self.assertEqual(restored.prices['白色'], 0)
        self.assertFalse(restored.timer_completed)
        self.assertEqual(self.path.read_bytes(), original)

    def test_normal_overdue_refill_and_capture_schedules_are_not_rejected_or_rewritten(self):
        start = datetime.datetime.fromisoformat('2032-04-05T23:58:50+00:00').timestamp()
        game = copy.deepcopy(self.game)
        game.advance(15, now=start + 15)
        game.catch(list(game.desktop), now=start + 15)
        game.advance(114, now=start + 129)
        self.assertEqual(game._next_empty_refill_at, 75)
        storage.save_state(self.path, game)
        restored = storage.load_state(self.path)
        self.assertEqual(restored._next_empty_refill_at, 75)
        restored.advance(1, now=start + 130)
        self.assertEqual(len(restored.desktop), 2)
        raw = storage._state_dict(restored)
        raw['next_auto_capture_at'] = 10
        self.path.write_text(json.dumps(raw))
        self.assertEqual(storage.load_state(self.path)._next_auto_capture_at, 10)

    def test_release_above_soft_limit_and_legacy_g2_only_ownership_still_roundtrip(self):
        game = copy.deepcopy(self.game)
        game.advance(600)
        for color in COLORS:
            game.release(color, None, 999)
        self.assertGreater(len(game.desktop), 24)
        # Existing G2-only ownership remains valid; new purchases now need G1.
        game.coins = 0
        game.owned_items.add('shrine_g2')
        storage.save_state(self.path, game)
        restored = storage.load_state(self.path)
        self.assertEqual(restored.desktop, game.desktop)
        self.assertEqual(restored.owned_items, {'shrine_g2'})

    def test_timer_presets_idle_next_phase_and_overdue_running_survive(self):
        timer = TimerSession(work_seconds=60, break_seconds=30)
        timer.start('pomodoro', now=100)
        timer.work_seconds = 12
        self.assertEqual(TimerSession.from_dict(timer.to_dict()).deadline, 160)
        timer.tick(now=161)
        timer.next_phase()
        restored = TimerSession.from_dict(timer.to_dict())
        self.assertEqual((restored.status, restored.remaining_seconds), ('idle', 30))
        old = copy.deepcopy(self.raw)
        old.pop('timer_session')
        old.update(timer_deadline=10.0, timer_remaining=60, timer_completed=False)
        self.path.write_text(json.dumps(old))
        restored = storage.load_state(self.path)
        self.assertEqual(restored.timer_session.status, 'running')
        self.assertEqual(restored.timer_session.deadline, 10.0)


if __name__ == '__main__':
    unittest.main()
