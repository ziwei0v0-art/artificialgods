"""Traditional units share Catime state and the normal save transaction."""
from pathlib import Path
import copy
import datetime
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tianmu_mvp.service import ApplicationService
from tianmu_mvp.timer import TimerSession


class TraditionalTimerServiceTests(unittest.TestCase):
    def test_named_countdown_uses_same_pause_restart_and_saved_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            reply = service.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '一炷香'}, now=100)
            self.assertTrue(reply['ok'], reply)
            self.assertEqual(reply['state']['timer']['countdown_seconds'], 1800)
            self.assertEqual(reply['state']['timer']['deadline'], 1900)
            service.handle({'action': 'timer_pause'}, now=400)
            restored = ApplicationService(path)
            self.assertEqual(restored.game.timer_session.seconds(900), 1500)
            result = restored.handle({'action': 'timer_resume'}, now=900)
            self.assertEqual(result['state']['timer']['deadline'], 2400)
            self.assertTrue(result['state']['timer']['traditional_readout'])

    def test_unit_preferences_persist_without_changing_current_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '25'}, now=100)
            before = service.game.timer_session.to_dict()
            result = service.handle({'action': 'timer_preferences', 'tea_duration': '5', 'incense_duration': '45'}, now=101)
            self.assertTrue(result['ok'], result)
            timer = result['state']['timer']
            self.assertEqual((timer.get('tea_seconds'), timer.get('incense_seconds')), (300, 2700))
            for key, value in before.items():
                if key not in ('tea_seconds', 'incense_seconds'):
                    self.assertEqual(service.game.timer_session.to_dict()[key], value)
            restored = ApplicationService(path)
            reply = restored.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '两盏茶', 'replace': True}, now=200)
            self.assertTrue(reply['ok'], reply)
            self.assertEqual(reply['state']['timer']['countdown_seconds'], 600)

    def test_invalid_unit_or_failed_save_does_not_change_disk_or_active_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.handle({'action': 'timer_start', 'mode': 'stopwatch'}, now=100)
            before = copy.deepcopy(service.game.timer_session.to_dict())
            saved = path.read_bytes()
            for request in ({'tea_duration': '0s'}, {'incense_duration': '24h1s'},
                            {'tea_duration': True}, {'tea_duration': '辰时三刻'},
                            {'tea_duration': '5', 'incense_duration': '0s'},
                            {'tea_duration': '5', 'timezone': 'invalid'},
                            {'tea_duration': '5', 'show_traditional': 'false'}):
                result = service.handle({'action': 'timer_preferences', **request}, now=101)
                self.assertFalse(result['ok'], request)
                self.assertEqual(service.game.timer_session.to_dict(), before)
                self.assertEqual(path.read_bytes(), saved)
            with patch('tianmu_mvp.service.save_state', side_effect=OSError('synthetic disk full')):
                result = service.handle({'action': 'timer_preferences', 'tea_duration': '5'}, now=102)
            self.assertFalse(result['ok'])
            self.assertEqual(service.game.timer_session.to_dict(), before)
            self.assertEqual(path.read_bytes(), saved)

    def test_idle_pomodoro_traditional_preview_matches_modern_phase_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ApplicationService(Path(directory) / 'state.json')
            started = service.handle({'action': 'timer_start', 'mode': 'pomodoro',
                                      'work': '25', 'rest': '5'}, now=100)
            self.assertTrue(started['ok'], started)
            paused = service.handle({'action': 'timer_pause'}, now=400)['state']['timer']
            self.assertEqual((paused['readout'], paused['traditional_readout']),
                             ('20:00', '一刻5分'))
            idle = service.handle({'action': 'timer_end'}, now=401)['state']['timer']
            self.assertEqual(idle['status'], 'idle')
            self.assertEqual((idle['readout'], idle['traditional_readout']),
                             ('25:00', '一刻10分'))

    def test_simultaneous_unit_definitions_are_resolved_against_previous_units(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            reply = service.handle({'action': 'timer_preferences',
                                    'tea_duration': '一炷香',
                                    'incense_duration': '一盏茶',
                                    'preset_durations': ['一盏茶', '一炷香', '一刻', '一时辰']}, now=100)
            self.assertTrue(reply['ok'], reply)
            timer = ApplicationService(path).game.timer_session
            self.assertEqual((timer.tea_seconds, timer.incense_seconds), (1800, 600))
            self.assertEqual(timer.preset_seconds, [1800, 600, 900, 7200])

    def test_clock_expression_replacement_rejection_restores_exact_paused_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.handle({'action': 'timer_start', 'mode': 'countdown',
                            'duration': '一炷香'}, now=100)
            service.handle({'action': 'timer_pause'}, now=200.125)
            before, saved = service.game.timer_session.to_dict(), path.read_bytes()
            requests = ({'mode': 'countdown', 'duration': '辰时三刻'},
                        {'mode': 'pomodoro', 'work': '一盏茶', 'rest': '辰正二刻'})
            for request in requests:
                with self.subTest(request=request):
                    reply = service.handle({'action': 'timer_start', 'replace': True,
                                            **request}, now=300)
                    self.assertFalse(reply['ok'])
                    self.assertIn('时刻', reply['error'])
                    self.assertEqual(service.game.timer_session.to_dict(), before)
                    self.assertEqual(path.read_bytes(), saved)

    def test_late_disk_replacement_failure_preserves_named_timer_and_precision(self):
        from tianmu_mvp import storage
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.handle({'action': 'timer_start', 'mode': 'countdown',
                            'duration': '一盏茶'}, now=100)
            service.handle({'action': 'timer_pause'}, now=200.25)
            before, saved = service.game.timer_session.to_dict(), path.read_bytes()
            real_replace = storage.os.replace

            def fail_only_main_replacement(source, destination):
                if Path(destination) == path:
                    raise OSError('synthetic late atomic replacement failure')
                return real_replace(source, destination)

            with patch('tianmu_mvp.storage.os.replace', side_effect=fail_only_main_replacement):
                reply = service.handle({'action': 'timer_start', 'mode': 'countdown',
                                        'duration': '一炷香', 'replace': True}, now=300)
            self.assertFalse(reply['ok'])
            self.assertEqual(service.game.timer_session.to_dict(), before)
            self.assertEqual(ApplicationService(path).game.timer_session.to_dict(), before)
            self.assertEqual(path.read_bytes(), saved)
            self.assertEqual(service.game.timer_session.remaining_milliseconds, 499750)
            self.assertEqual(reply['state']['timer']['traditional_readout'], '8分20秒')
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_old_saves_default_units_and_reject_malformed_new_values(self):
        raw = TimerSession().to_dict()
        raw.pop('tea_seconds', None); raw.pop('incense_seconds', None)
        restored = TimerSession.from_dict(raw)
        self.assertEqual((getattr(restored, 'tea_seconds', None), getattr(restored, 'incense_seconds', None)), (600, 1800))
        for value in (0, -1, True, '600', 86401):
            with self.assertRaises(ValueError):
                TimerSession.from_dict({**raw, 'tea_seconds': value})

    def test_clock_and_duration_snapshots_are_explicit_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.game.timer_session.clock_timezone = 'Asia/Shanghai'
            now = datetime.datetime(2026, 10, 8, 7, 45, 23, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
            before = service.game.timer_session.to_dict()
            timer = service.snapshot(now)['timer']
            self.assertEqual(timer.get('traditional_readout'), '辰初三刻')
            self.assertEqual([p['seconds'] for p in timer.get('unit_presets', [])], [600, 900, 1800, 7200])
            self.assertEqual(service.game.timer_session.to_dict(), before)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
