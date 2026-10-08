"""First-run progress and explicit game calendar changes; temp saves, no UI/worker."""
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
from tianmu_mvp.storage import _state_dict, load_state, save_state


def instant(value):
    return datetime.datetime.fromisoformat(value).timestamp()


class OnboardingTimezoneTests(unittest.TestCase):
    def service(self, zone='UTC'):
        folder = tempfile.TemporaryDirectory(prefix='tianmu-onboarding-zone-')
        self.addCleanup(folder.cleanup)
        app = ApplicationService(Path(folder.name) / 'state.json')
        app.game = GameState.new(rng=random.Random(19))
        app.game.game_timezone = zone
        return app

    def add_bug(self, app, genotype=('Aa', 'Bb')):
        bug = app.game._new_insect(sex='F', genotype=genotype)
        app.game.desktop[bug.id] = bug
        return bug

    def send(self, app, action, now=None, **fields):
        reply = app.handle({'action': action, **fields},
                           now=instant('2032-04-05T12:00:00+00:00') if now is None else now)
        self.assertTrue(reply['ok'], reply)
        return reply

    def stage(self, app, expected):
        self.assertEqual(getattr(app.game, 'onboarding', None), expected)
        self.assertEqual(app.snapshot(0).get('onboarding'), expected)

    def test_new_progress_resumes_each_step_and_finishes_only_after_bottle_visit(self):
        app = self.service()
        self.stage(app, 'shrine')
        self.send(app, 'onboarding_visit', page='神前')
        self.stage(app, 'capture')
        app = ApplicationService(app.save_path)
        self.stage(app, 'capture')
        bug = self.add_bug(app)
        self.send(app, 'catch', ids=[bug.id])
        self.stage(app, 'bottle')
        app = ApplicationService(app.save_path)
        self.stage(app, 'bottle')
        self.assertIn(bug.id, app.game.bottle)
        self.send(app, 'onboarding_visit', page='虫瓶')
        self.stage(app, 'done')
        self.stage(ApplicationService(app.save_path), 'done')

    def test_wrong_order_repeated_visits_empty_net_and_duplicate_ids_do_not_skip_steps(self):
        app = self.service()
        bug = self.add_bug(app)
        self.send(app, 'onboarding_visit', page='虫瓶')
        self.send(app, 'catch', ids=[bug.id])
        self.stage(app, 'shrine')
        self.send(app, 'onboarding_visit', page='神前')
        for action, fields in [('onboarding_visit', {'page': '神前'}),
                               ('onboarding_visit', {'page': '虫瓶'}),
                               ('catch', {'ids': []}),
                               ('catch', {'ids': [bug.id, bug.id, 'missing']})]:
            self.send(app, action, **fields)
            self.stage(app, 'capture')
        second = self.add_bug(app)
        self.send(app, 'catch', ids=[second.id, second.id])
        self.stage(app, 'bottle')
        self.send(app, 'onboarding_visit', page='神前')
        self.stage(app, 'bottle')
        self.send(app, 'onboarding_visit', page='虫瓶')
        self.send(app, 'onboarding_visit', page='神前')
        self.send(app, 'onboarding_visit', page='虫瓶')
        self.stage(app, 'done')

    def test_skip_persists_at_each_unfinished_step_and_never_changes_terminal_states(self):
        for stage in ('shrine', 'capture', 'bottle', 'done', 'skipped', 'legacy'):
            with self.subTest(stage=stage):
                app = self.service()
                app.game.onboarding = stage
                expected = 'skipped' if stage in ('shrine', 'capture', 'bottle') else stage
                self.send(app, 'onboarding_skip')
                self.stage(app, expected)
                self.stage(ApplicationService(app.save_path), expected)
                self.send(app, 'onboarding_visit', page='神前')
                self.send(app, 'onboarding_visit', page='虫瓶')
                self.send(app, 'catch', ids=[self.add_bug(app).id])
                self.stage(app, expected)

    def test_legacy_missing_progress_is_exempt_without_claiming_completion_or_rewriting_on_load(self):
        app = self.service()
        save_state(app.save_path, app.game)
        raw = json.loads(app.save_path.read_text())
        raw.pop('onboarding', None)
        app.save_path.write_text(json.dumps(raw))
        saved = app.save_path.read_bytes()
        app = ApplicationService(app.save_path)
        self.stage(app, 'legacy')
        self.assertEqual(app.save_path.read_bytes(), saved)
        self.send(app, 'checkpoint')
        self.assertEqual(json.loads(app.save_path.read_text())['onboarding'], 'legacy')

    def test_invalid_persisted_progress_is_rejected_without_rewriting_source(self):
        app = self.service()
        for value in ('unknown', '', None, 1, [], {}):
            with self.subTest(value=value):
                raw = _state_dict(app.game)
                raw['onboarding'] = value
                app.save_path.write_text(json.dumps(raw))
                saved = app.save_path.read_bytes()
                with self.assertRaises(ValueError):
                    load_state(app.save_path)
                self.assertEqual(app.save_path.read_bytes(), saved)

    def test_automatic_capture_does_not_complete_manual_capture_step(self):
        app = self.service()
        self.send(app, 'onboarding_visit', page='神前')
        start = instant('2032-04-05T12:00:00+00:00')
        app.game.advance(59, now=start + 59)
        reply = app.tick(now=start + 60, active_seconds=1)
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(len(app.game.bottle), 1)
        self.stage(app, 'capture')
        self.stage(ApplicationService(app.save_path), 'capture')

    def test_failed_progress_saves_restore_capture_inventory_and_stage_together(self):
        for stage, action, fields in [('shrine', 'onboarding_visit', {'page': '神前'}),
                                     ('capture', 'catch', {}),
                                     ('bottle', 'onboarding_visit', {'page': '虫瓶'}),
                                     ('capture', 'onboarding_skip', {})]:
            with self.subTest(stage=stage, action=action):
                app = self.service()
                app.game.onboarding = stage
                bug = self.add_bug(app)
                request = {'action': action, **fields}
                if action == 'catch':
                    request['ids'] = [bug.id]
                save_state(app.save_path, app.game)
                before, saved = copy.deepcopy(_state_dict(app.game)), app.save_path.read_bytes()
                with patch('tianmu_mvp.service.save_state', side_effect=OSError('isolated write failure')):
                    reply = app.handle(request, now=0)
                self.assertFalse(reply['ok'])
                self.stage(app, stage)
                self.assertEqual(_state_dict(app.game), before)
                self.assertEqual(app.save_path.read_bytes(), saved)

    def test_unrelated_tools_remain_available_without_progress_or_automatic_sign(self):
        app = self.service()
        self.send(app, 'timer_start', mode='countdown', duration='25m')
        self.stage(app, 'shrine')
        self.assertEqual(app.game.timer_session.status, 'running')
        self.assertEqual(app.game.sign_history, {})
        self.assertEqual(app.game.coins, 0)

    def calendar_service(self, now, zone='UTC'):
        app = self.service(zone)
        app.game.advance(20, now=now)
        # Real timer and history exercise independence from game-calendar writes.
        self.send(app, 'timer_start', now=now, mode='countdown', duration='25m')
        self.send(app, 'timer_preferences', now=now, timezone='Asia/Shanghai')
        self.send(app, 'sign', now=now)
        self.send(app, 'catch', now=now, ids=[next(iter(app.game.desktop))])
        return app

    def test_invalid_game_zones_return_failure_and_preserve_state_and_file(self):
        app = self.calendar_service(instant('2032-04-05T12:00:00+00:00'))
        before, saved = copy.deepcopy(_state_dict(app.game)), app.save_path.read_bytes()
        for zone in ('Not/A_Zone', 'local', '', '/etc/localtime', None, 7, [], {}):
            with self.subTest(zone=zone):
                reply = app.handle({'action': 'game_timezone_set', 'timezone': zone}, now=0)
                self.assertFalse(reply['ok'])
                self.assertIn('时区', reply['error'])
                self.assertEqual(_state_dict(app.game), before)
                self.assertEqual(app.save_path.read_bytes(), saved)

    def test_same_zone_is_idempotent_even_if_wall_date_has_changed(self):
        now = instant('2032-04-05T12:00:00+00:00')
        app = self.calendar_service(now)
        before = copy.deepcopy(_state_dict(app.game))
        self.send(app, 'game_timezone_set', now=now + 86400 * 3, timezone='UTC')
        self.assertEqual(_state_dict(app.game), before)
        self.assertEqual(_state_dict(ApplicationService(app.save_path).game), before)

    def test_switch_preserves_noncalendar_state_and_survives_restart(self):
        for source, target, clock, expected_date in [
                ('UTC', 'Europe/London', '2032-04-05T12:00:00+00:00', '2032-04-05'),
                ('UTC', 'Asia/Shanghai', '2032-04-05T16:30:00+00:00', '2032-04-06'),
                ('Asia/Shanghai', 'Pacific/Honolulu', '2032-04-05T16:30:00+00:00', '2032-04-05')]:
            with self.subTest(source=source, target=target):
                now = instant(clock)
                app = self.calendar_service(now, source)
                before = copy.deepcopy(_state_dict(app.game))
                reply = self.send(app, 'game_timezone_set', now=now, timezone=target)
                self.assertEqual(reply['state']['game_timezone'], target)
                self.assertEqual(app.game.routine.game_date, expected_date)
                self.assertEqual(app.game.routine.last_offered_date, expected_date)
                self.assertEqual(app.game.routine.last_observed_wall, now)
                after = _state_dict(app.game)
                for key in before.keys() - {'game_timezone', 'routine'}:
                    self.assertEqual(after[key], before[key], key)
                calendar_fields = {'game_date', 'last_observed_wall', 'calendar_rebased_wall', 'last_offered_date',
                                   'practiced_periods', 'current_period', 'night'}
                for key in before['routine'].keys() - calendar_fields:
                    self.assertEqual(after['routine'][key], before['routine'][key], key)
                self.assertEqual(_state_dict(ApplicationService(app.save_path).game), after)

    def test_switch_back_reuses_old_sign_and_new_discoveries_use_selected_zone(self):
        now = instant('2032-04-05T23:30:00+00:00')
        app = self.calendar_service(now)
        old_history, old_dates = dict(app.game.sign_history), dict(app.game.discovery_dates)
        self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
        self.assertEqual(app.game.sign_history, old_history)
        self.assertEqual(app.game.discovery_dates, old_dates)
        self.send(app, 'sign', now=now)
        self.assertEqual(set(app.game.sign_history), {'2032-04-05', '2032-04-06'})
        self.send(app, 'catch', now=now, ids=[self.add_bug(app, ('aa', 'bb')).id])
        self.assertEqual(app.game.discovery_dates['白色'], '2032-04-06')
        self.send(app, 'game_timezone_set', now=now, timezone='UTC')
        self.send(app, 'sign', now=now)
        self.assertEqual(app.game.daily_sign_date, '2032-04-05')
        self.assertEqual(app.game.daily_sign, old_history['2032-04-05'])
        self.assertEqual(app.game.discovery_dates['普通褐色'], old_dates['普通褐色'])

    def test_clock_preferences_do_not_change_game_zone_or_calendar(self):
        now = instant('2032-04-05T12:00:00+00:00')
        app = self.calendar_service(now)
        self.send(app, 'game_timezone_set', now=now, timezone='Pacific/Honolulu')
        before = copy.deepcopy(app.game.routine)
        self.send(app, 'timer_preferences', now=now, timezone='local')
        self.assertEqual(app.game.game_timezone, 'Pacific/Honolulu')
        self.assertEqual(app.game.routine, before)

    def test_zone_snapshot_uses_current_clock_while_zero_second_tick_preserves_calendar(self):
        now = instant('2032-04-05T12:00:00+00:00')
        app = self.calendar_service(now)
        timer = copy.deepcopy(app.game.timer_session.to_dict())
        mirrors = (app.game.timer_deadline, app.game.timer_remaining, app.game.timer_completed)
        reply = self.send(app, 'game_timezone_set', now=now + 5, timezone='Pacific/Honolulu')
        self.assertEqual(app.game.timer_session.to_dict(), timer)
        self.assertEqual((app.game.timer_deadline, app.game.timer_remaining, app.game.timer_completed), mirrors)
        self.assertEqual(reply['state']['timer']['readout'], '24:55')
        self.assertTrue(reply['state']['timer']['clock_readout'].startswith('20:00:05'))
        routine = copy.deepcopy(app.game.routine)
        elapsed = app.game.elapsed_seconds
        reply = app.tick(now=now + 6, active_seconds=0)
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(app.game.elapsed_seconds, elapsed)
        self.assertEqual(app.game.routine, routine)
        self.assertEqual(reply['state']['timer']['readout'], '24:54')

    def test_failed_zone_save_restores_full_state_calendar_and_pending_sale(self):
        now = instant('2032-04-05T16:30:00+00:00')
        app = self.calendar_service(now)
        self.send(app, 'sale_preview', now=now, color='普通褐色', count=1)
        before, pending = copy.deepcopy(_state_dict(app.game)), copy.deepcopy(app.pending_sale)
        saved = app.save_path.read_bytes()
        with patch('tianmu_mvp.service.save_state', side_effect=OSError('isolated write failure')):
            reply = app.handle({'action': 'game_timezone_set', 'timezone': 'Asia/Shanghai'}, now=now)
        self.assertFalse(reply['ok'])
        self.assertEqual(_state_dict(app.game), before)
        self.assertEqual(app.pending_sale, pending)
        self.assertEqual(app.save_path.read_bytes(), saved)
        self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
        self.assertEqual(app.game.routine.game_date, '2032-04-06')

    def test_switch_skips_started_and_ended_windows_without_new_offer(self):
        for clock, expected in [('2032-04-05T22:00:00+00:00', ['morning']),
                                ('2032-04-05T04:00:00+00:00', ['morning']),
                                ('2032-04-05T10:00:00+00:00', ['morning', 'evening']),
                                ('2032-04-05T12:00:00+00:00', ['morning', 'evening'])]:
            with self.subTest(clock=clock):
                now = instant(clock)
                app = self.calendar_service(now)
                # Ensure the assertion observes new scheduling, not an already running ritual.
                app.game.routine.action = 'idle'
                app.game.routine.action_duration = 0
                count = app.game.routine.offering_count
                fruit = app.game.routine.fruit_started_active
                self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
                self.assertEqual(app.game.routine.practiced_periods, expected)
                reply = app.tick(now=now + 1, active_seconds=1)
                self.assertTrue(reply['ok'], reply)
                self.assertNotIn(app.game.routine.action, ('practice', 'offer'))
                self.assertEqual(app.game.routine.offering_count, count)
                self.assertEqual(app.game.routine.fruit_started_active, fruit)

    def test_same_date_preserves_done_periods_when_switch_moves_clock_backward(self):
        now = instant('2032-04-05T18:00:00+00:00')
        app = self.calendar_service(now)
        app.game.routine.practiced_periods = ['morning', 'evening']
        self.send(app, 'game_timezone_set', now=now, timezone='Pacific/Honolulu')
        self.assertEqual(app.game.routine.game_date, '2032-04-05')
        self.assertEqual(app.game.routine.practiced_periods, ['morning', 'evening'])
        app.game.routine.action_duration = 0
        reply = app.tick(now=instant('2032-04-05T17:00:00-10:00'), active_seconds=1)
        self.assertTrue(reply['ok'], reply)
        self.assertNotEqual(app.game.routine.action, 'practice')

    def test_future_window_and_next_natural_midnight_continue_without_offline_accrual(self):
        now = instant('2032-04-05T08:00:00+00:00')
        app = self.calendar_service(now)
        self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
        before_elapsed, count = app.game.elapsed_seconds, app.game.routine.offering_count
        app.tick(now=instant('2032-04-05T17:00:01+08:00'), active_seconds=1)
        self.assertEqual(app.game.elapsed_seconds, before_elapsed + 1)
        self.assertEqual(app.game.routine.action, 'practice')
        self.assertEqual(app.game.routine.practice_period, 'evening')
        app.tick(now=instant('2032-04-06T00:00:01+08:00'), active_seconds=1)
        self.assertEqual(app.game.elapsed_seconds, before_elapsed + 2)
        self.assertEqual(app.game.routine.offering_count, count + 1)
        self.assertEqual(app.game.routine.action, 'offer')
        self.assertEqual(app.game.routine.practiced_periods, [])
        self.assertEqual(app.game.routine.game_date, '2032-04-06')

    def test_in_progress_short_work_can_finish_after_cross_date_zone_switch(self):
        for action in ('practice', 'offer', 'catch', 'bell'):
            with self.subTest(action=action):
                now = instant('2032-04-05T23:30:00+00:00')
                app = self.calendar_service(now)
                app.game.routine._start(action, app.game.elapsed_seconds, 3,
                                        'evening' if action == 'practice' else None)
                if action == 'bell':
                    app.game.owned_items.add('bell')
                    app.game.placed_items['bell'] = 'bell'
                before = copy.deepcopy(app.game.routine)
                self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
                for name in ('action', 'action_duration', 'action_started_active',
                             'action_serial', 'practice_period'):
                    self.assertEqual(getattr(app.game.routine, name), getattr(before, name))
                app.tick(now=now + 1, active_seconds=1)
                self.assertEqual(app.game.routine.action, action)
                app.tick(now=now + 3, active_seconds=2)
                self.assertNotEqual(app.game.routine.action, action)
                self.assertEqual(app.game.routine.offering_count, before.offering_count)
                self.assertIsNone(app.game.routine.calendar_rebased_wall)

    def test_first_batched_tick_overlapping_zone_change_never_rewinds_calendar_or_interrupts_work(self):
        for clock in ('2032-04-06T00:00:00+08:00', '2032-04-06T05:00:00+08:00',
                      '2032-04-06T17:00:00+08:00'):
            with self.subTest(clock=clock):
                now = instant(clock)
                app = self.calendar_service(now)
                prior_period = 'morning' if 'T17:' in clock else 'evening'
                app.game.routine._start('practice', app.game.elapsed_seconds, 5, prior_period)
                self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
                count = app.game.routine.offering_count
                periods = list(app.game.routine.practiced_periods)
                fruit = app.game.routine.fruit_started_active
                elapsed = app.game.elapsed_seconds
                # Reload also preserves the protection against an overlapping heartbeat.
                app = ApplicationService(app.save_path)
                reply = app.tick(now=now + 1, active_seconds=2)
                self.assertTrue(reply['ok'], reply)
                self.assertEqual(app.game.elapsed_seconds, elapsed + 2)
                self.assertEqual(app.game.routine.game_date, '2032-04-06')
                self.assertEqual(app.game.routine.action, 'practice')
                self.assertEqual(app.game.routine.action_duration, 5)
                self.assertEqual(app.game.routine.practiced_periods, periods)
                self.assertEqual(app.game.routine.offering_count, count)
                self.assertEqual(app.game.routine.fruit_started_active, fruit)

    def test_intervening_place_does_not_remove_overlap_protection_before_next_heartbeat(self):
        now = instant('2032-04-06T00:00:00+08:00')
        app = self.calendar_service(now)
        app.game.owned_items.add('offering_plate')
        app.game.routine._start('practice', app.game.elapsed_seconds, 5, 'morning')
        self.send(app, 'game_timezone_set', now=now, timezone='Asia/Shanghai')
        count = app.game.routine.offering_count
        fruit = app.game.routine.fruit_started_active
        self.send(app, 'place', now=now + 0.1, item='offering_plate')
        reply = app.tick(now=now + 1, active_seconds=2)
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(app.game.routine.game_date, '2032-04-06')
        self.assertEqual(app.game.routine.offering_count, count)
        self.assertEqual(app.game.routine.fruit_started_active, fruit)
        self.assertEqual(app.game.routine.action, 'practice')
        self.assertEqual(app.game.routine.action_duration, 5)


if __name__ == '__main__':
    unittest.main()
