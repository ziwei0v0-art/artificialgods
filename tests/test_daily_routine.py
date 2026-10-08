"""Calendar-driven daily work; all saves are temporary, no UI or worker."""
import copy
import datetime
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from tianmu_mvp.model import GameState
from tianmu_mvp.service import ApplicationService
from tianmu_mvp.storage import load_state, save_state


def instant(value):
    return datetime.datetime.fromisoformat(value).timestamp()


class DailyRoutineTests(unittest.TestCase):
    def game(self):
        game = GameState.new(rng=random.Random(19))
        game.game_timezone = 'UTC'
        self.assertIsNotNone(getattr(game, 'routine', None), 'Daily work must be model state, not a repeating visual loop')
        return game

    def view(self, game):
        return game.routine.snapshot(game.elapsed_seconds)

    def test_first_fruit_ripens_after_fifteen_active_seconds(self):
        game = self.game()
        start = instant('2026-09-30T12:00:00+00:00')
        self.assertEqual(self.view(game)['action'], 'offer')
        self.assertEqual(self.view(game)['fruit_stage'], 'fresh')
        game.advance(14, now=start + 14)
        self.assertEqual(self.view(game)['fruit_stage'], 'soft')
        self.assertEqual(len(game.desktop), 0)
        game.advance(1, now=start + 15)
        self.assertEqual(self.view(game)['fruit_stage'], 'ripe')
        self.assertEqual(len(game.desktop), 6)
        self.assertEqual(sum(b.sex == 'F' for b in game.desktop.values()), 3)
        self.assertTrue(all(b.genotype == ('Aa', 'Bb') for b in game.desktop.values()))

    def test_daily_offer_once_and_next_day_matures_after_sixty_active_seconds(self):
        game = self.game()
        start = instant('2026-09-30T12:00:00+00:00')
        game.advance(80, now=start + 80)
        count = game.routine.offering_count
        game.advance(1, now=start + 1000)
        self.assertEqual(game.routine.offering_count, count)
        # Several missed calendar days trigger only today's offering.
        wake = instant('2026-10-04T12:00:00+00:00')
        game.advance(1, now=wake)
        self.assertEqual(game.routine.offering_count, count + 1)
        self.assertEqual(self.view(game)['game_date'], '2026-10-04')
        self.assertEqual(self.view(game)['fruit_stage'], 'fresh')
        game.advance(58, now=wake + 58)
        self.assertEqual(self.view(game)['fruit_stage'], 'soft')
        game.advance(1, now=wake + 59)
        self.assertEqual(self.view(game)['fruit_stage'], 'ripe')
        self.assertEqual(game.routine.offering_count, count + 1)

    def test_evening_practice_defers_one_real_capture_and_manual_capture_still_works(self):
        game = self.game()
        start = instant('2026-09-30T16:59:40+00:00')
        game.advance(64, now=start + 64)
        self.assertEqual(self.view(game)['action'], 'practice')
        self.assertEqual(self.view(game)['practice_period'], 'evening')
        self.assertEqual(len(game.bottle), 0)
        self.assertTrue(self.view(game)['pending_capture'])
        bug = next(iter(game.desktop.values()))
        self.assertEqual(game.catch([bug.id]), [bug.id])
        game.advance(1, now=start + 65)
        self.assertEqual(len(game.bottle), 2)
        self.assertEqual(game.bottle[bug.id], bug)
        self.assertEqual(self.view(game)['action'], 'catch')
        self.assertFalse(self.view(game)['pending_capture'])
        game.advance(1, now=start + 66)
        self.assertEqual(len(game.bottle), 2, 'Deferred work must not repeat on each tick')

    def test_practice_window_is_once_and_missed_window_is_not_replayed(self):
        game = self.game()
        start = instant('2026-09-30T05:00:00+00:00')
        game.advance(10, now=start + 10)
        self.assertEqual(self.view(game)['action'], 'practice')
        serial = self.view(game)['action_serial']
        game.advance(44, now=start + 54)
        self.assertNotEqual(self.view(game)['action'], 'practice')
        game.advance(1, now=start + 1000)
        self.assertNotEqual(self.view(game)['action'], 'practice')
        self.assertGreater(self.view(game)['action_serial'], serial)
        # Reopening after a window never replays the old morning or evening.
        game.advance(1, now=instant('2026-10-03T08:00:00+00:00'))
        game.advance(10, now=instant('2026-10-03T08:00:10+00:00'))
        self.assertNotEqual(self.view(game)['action'], 'practice')
        self.assertEqual(game.routine.practiced_periods, [])

    def test_calendar_uses_game_timezone_and_night_does_not_stop_auto_capture(self):
        utc = self.game()
        new_york = self.game()
        new_york.game_timezone = 'America/New_York'
        start = instant('2026-09-30T21:00:00+00:00')
        utc.advance(10, now=start + 10)
        new_york.advance(10, now=start + 10)
        self.assertEqual(self.view(utc)['action'], 'rest')
        self.assertEqual(self.view(new_york)['action'], 'practice')
        utc.advance(50, now=start + 60)
        self.assertEqual(len(utc.bottle), 1)
        utc.advance(4, now=start + 64)
        self.assertEqual(self.view(utc)['action'], 'rest')

    def test_started_practice_finishes_forty_five_active_seconds_across_window_edge(self):
        game = self.game()
        start = instant('2026-09-30T06:59:40+00:00')
        game.advance(52, now=start + 52)
        self.assertEqual(self.view(game)['action'], 'practice')
        self.assertAlmostEqual(self.view(game)['progress'], 44 / 45)
        game.advance(1, now=start + 53)
        self.assertNotEqual(self.view(game)['action'], 'practice')

    def test_sleeping_past_practice_window_does_not_replay_remaining_ritual(self):
        game = self.game()
        start = instant('2026-09-30T06:00:00+00:00')
        game.advance(10, now=start + 10)
        self.assertEqual(self.view(game)['action'], 'practice')
        game.advance(1, now=instant('2026-09-30T12:00:00+00:00'))
        self.assertNotEqual(self.view(game)['action'], 'practice')

    def test_daytime_actions_match_batched_and_single_second_advances(self):
        game = self.game()
        start = instant('2026-09-30T12:00:00+00:00')
        actions = set()
        for second in range(1, 151):
            game.advance(1, now=start + second)
            state = self.view(game)
            actions.add(state['action'])
            self.assertGreaterEqual(state['progress'], 0)
            self.assertLessEqual(state['progress'], 1)
        self.assertTrue({'walk', 'sweep', 'read', 'idle', 'catch'}.issubset(actions), actions)
        other = self.game()
        other.advance(150, now=start + 150)
        self.assertEqual(game.desktop, other.desktop)
        self.assertEqual(game.bottle, other.bottle)
        self.assertEqual(game.rng.getstate(), other.rng.getstate())
        self.assertEqual(self.view(game), self.view(other))

    def test_fruit_maturity_gates_refill_without_blocking_existing_breeders(self):
        game = self.game()
        start = instant('2026-09-30T23:58:50+00:00')
        game.advance(15, now=start + 15)
        game.catch(list(game.desktop))
        # Refill would be due at active t=75; daily new fruit at t=70 is not ripe yet.
        game.advance(114, now=start + 129)
        self.assertEqual(len(game.desktop), 0)
        self.assertEqual(self.view(game)['fruit_stage'], 'soft')
        game.advance(1, now=start + 130)
        self.assertEqual(len(game.desktop), 2)
        self.assertEqual(self.view(game)['fruit_stage'], 'ripe')

    def test_bell_requires_placement_and_first_trial_is_not_repeated(self):
        game = self.game()
        start = instant('2026-09-30T12:00:00+00:00')
        game.advance(20, now=start + 20)
        game.coins = 60
        self.assertTrue(game.buy('bell'))
        game.advance(1, now=start + 21)
        self.assertNotEqual(self.view(game)['action'], 'bell')
        self.assertTrue(game.place('bell'))
        game.advance(1, now=start + 22)
        self.assertEqual(self.view(game)['action'], 'bell')
        serial = self.view(game)['action_serial']
        game.advance(5, now=start + 27)
        self.assertTrue(game.place('bell'))
        self.assertTrue(game.place('bell'))
        game.advance(1, now=start + 28)
        self.assertNotEqual(self.view(game)['action'], 'bell')
        self.assertTrue(game.routine.bell_trial_played)
        self.assertGreater(self.view(game)['action_serial'], serial)

    def test_timer_expiry_is_immediate_while_bell_waits_for_practice(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-routine-') as directory:
            app = ApplicationService(Path(directory) / 'state.json')
            self.assertIn('routine', app.snapshot(0), 'Production snapshot must expose rule-driven action')
            app.game.game_timezone = 'UTC'
            start = instant('2026-09-30T16:59:40+00:00')
            app.game.advance(15, now=start + 15)
            app.game.coins = 60
            app.handle({'action': 'buy', 'item': 'bell'}, now=start + 15)
            app.handle({'action': 'place', 'item': 'bell'}, now=start + 15)
            app.game.advance(45, now=start + 60)
            self.assertEqual(self.view(app.game)['action'], 'practice')
            self.assertTrue(app.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '1s'}, now=start + 60)['ok'])
            reply = app.tick(now=start + 61, active_seconds=1)
            self.assertEqual(reply['events'], ['timer_expired'])
            self.assertEqual(reply['state']['routine']['action'], 'practice')
            self.assertTrue(reply['state']['routine']['pending_bell'])
            self.assertEqual(app.tick(now=start + 62, active_seconds=1)['events'], [])
            actions = []
            for second in range(63, 74):
                actions.append(app.tick(now=start + second, active_seconds=1)['state']['routine']['action'])
            self.assertIn('bell', actions)

    def test_save_restore_preserves_pending_work_and_no_offline_maturation(self):
        game = self.game()
        start = instant('2026-09-30T16:59:40+00:00')
        game.advance(61, now=start + 61)
        before = self.view(game)
        with tempfile.TemporaryDirectory(prefix='tianmu-routine-') as directory:
            path = Path(directory) / 'state.json'
            save_state(path, game)
            app = ApplicationService(path)
            self.assertEqual(self.view(app.game), before)
            later = instant('2026-10-04T12:00:00+00:00')
            reply = app.tick(now=later, active_seconds=0)
            self.assertEqual(reply['state']['routine'], before)
            self.assertEqual(app.game.elapsed_seconds, 61)
            app.tick(now=later + 1, active_seconds=1)
            self.assertEqual(self.view(app.game)['fruit_stage'], 'fresh')
            self.assertEqual(self.view(app.game)['game_date'], '2026-10-04')
            self.assertEqual(app.game.elapsed_seconds, 62)
            self.assertEqual(len(app.game.bottle), 0)

    def test_legacy_save_adds_routine_without_mutating_existing_individuals(self):
        game = self.game()
        game.advance(15)
        original = copy.deepcopy(game.desktop)
        with tempfile.TemporaryDirectory(prefix='tianmu-routine-') as directory:
            path = Path(directory) / 'state.json'
            save_state(path, game)
            raw = json.loads(path.read_text())
            raw.pop('routine')
            path.write_text(json.dumps(raw))
            restored = load_state(path)
            self.assertEqual(restored.desktop, original)
            self.assertEqual(restored.elapsed_seconds, 15)
            self.assertEqual(self.view(restored)['fruit_stage'], 'ripe')
            restored.advance(1, now=instant('2026-09-30T12:00:00+00:00'))
            self.assertEqual(restored.desktop, original)
            self.assertEqual(self.view(restored)['fruit_stage'], 'ripe')

    def test_failed_persistence_rolls_back_routine_and_rejects_corrupt_routine(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-routine-') as directory:
            path = Path(directory) / 'state.json'
            app = ApplicationService(path)
            self.assertIn('routine', app.snapshot(0))
            before = copy.deepcopy(app.game.routine.to_dict())
            with patch('tianmu_mvp.service.save_state', side_effect=OSError('disk full')):
                result = app.tick(now=instant('2026-09-30T12:00:00+00:00'), active_seconds=1)
            self.assertFalse(result['ok'])
            self.assertEqual(app.game.routine.to_dict(), before)
            self.assertFalse(path.exists())
            save_state(path, app.game)
            raw = json.loads(path.read_text())
            raw['routine']['action'] = 'invented_magic'
            path.write_text(json.dumps(raw))
            unchanged = path.read_bytes()
            with self.assertRaises(ValueError):
                load_state(path)
            self.assertEqual(path.read_bytes(), unchanged)

    def test_first_mature_fruit_is_visible_before_next_day_offering(self):
        game = self.game()
        start = instant('2026-09-30T23:59:55+00:00')
        game.advance(15, now=start + 15)
        self.assertEqual(len(game.desktop), 6)
        self.assertEqual(self.view(game)['fruit_stage'], 'ripe')
        self.assertEqual(game.routine.offering_count, 1)
        game.advance(1, now=start + 16)
        self.assertEqual(self.view(game)['fruit_stage'], 'fresh')
        self.assertEqual(game.routine.offering_count, 2)
        game.advance(60, now=start + 76)
        self.assertEqual(self.view(game)['fruit_stage'], 'ripe')

    def test_next_day_does_not_resume_previous_days_offering_animation(self):
        game = self.game()
        start = instant('2026-09-30T12:00:00+00:00')
        game.advance(20, now=start + 20)
        tomorrow = instant('2026-10-01T12:00:00+00:00')
        game.advance(1, now=tomorrow)
        old_serial = self.view(game)['action_serial']
        self.assertEqual(game.routine.offering_count, 2)
        game.advance(1, now=instant('2026-10-04T12:00:00+00:00'))
        self.assertEqual(self.view(game)['action'], 'offer')
        self.assertEqual(game.routine.offering_count, 3)
        self.assertGreater(self.view(game)['action_serial'], old_serial)
        self.assertEqual(game.routine.last_offered_date, '2026-10-04')

    def test_legacy_already_placed_bell_gets_one_trial_after_migration(self):
        game = self.game()
        game.advance(20)
        game.coins = 60
        game.buy('bell')
        game.place('bell')
        with tempfile.TemporaryDirectory(prefix='tianmu-routine-') as directory:
            path = Path(directory) / 'state.json'
            save_state(path, game)
            raw = json.loads(path.read_text())
            raw.pop('routine')
            path.write_text(json.dumps(raw))
            restored = load_state(path)
            restored.advance(1, now=instant('2026-09-30T12:00:00+00:00'))
            self.assertEqual(self.view(restored)['action'], 'bell')
            self.assertTrue(restored.routine.bell_trial_played)
            restored.advance(10, now=instant('2026-09-30T12:00:10+00:00'))
            save_state(path, restored)
            twice = load_state(path)
            twice.advance(1, now=instant('2026-09-30T12:00:11+00:00'))
            self.assertNotEqual(self.view(twice)['action'], 'bell')


if __name__ == '__main__':
    unittest.main()
