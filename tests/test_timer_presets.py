"""Persisted Catime-parsed quick durations share the current timer session."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tianmu_mvp.service import ApplicationService


class TimerPresetTests(unittest.TestCase):
    def test_custom_durations_roundtrip_without_replacing_the_running_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            self.assertTrue(service.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '10'}, now=100)['ok'])
            before = service.game.timer_session.to_dict()
            result = service.handle({'action': 'timer_preferences', 'preset_durations': ['90s', '12', '1h30m', '24h']}, now=101)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['state']['timer'].get('preset_seconds'), [90, 720, 5400, 86400])
            timer = service.game.timer_session.to_dict()
            for key, value in before.items():
                if key != 'preset_seconds':
                    self.assertEqual(timer[key], value)
            restored = ApplicationService(path).snapshot(102)['timer']
            self.assertEqual(restored['preset_seconds'], [90, 720, 5400, 86400])
            self.assertEqual(restored['deadline'], before['deadline'])

    def test_invalid_preset_update_never_writes_or_changes_other_preferences(self):
        invalid = [None, '5,15,25,45', ['5'], ['5'] * 4,
                   ['5', '15', '25', '1500s'], ['5', '15', '25', '0s'],
                   ['5', '15', '25', '24h1s'], ['5', '15', '25', True],
                   ['5', '15', '25', 'not-a-duration']]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.handle({'action': 'timer_preferences'}, now=100)
            before_bytes, before = path.read_bytes(), copy.deepcopy(service.game.timer_session.to_dict())
            for values in invalid:
                with self.subTest(values=values):
                    reply = service.handle({'action': 'timer_preferences', 'preset_durations': values, 'sound_enabled': False}, now=101)
                    self.assertFalse(reply['ok'])
                    self.assertEqual(service.game.timer_session.to_dict(), before)
                    self.assertEqual(path.read_bytes(), before_bytes)

    def test_failed_save_keeps_previous_presets_and_current_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            service = ApplicationService(path)
            service.handle({'action': 'timer_start', 'mode': 'stopwatch'}, now=100)
            before_bytes, before = path.read_bytes(), copy.deepcopy(service.game.timer_session.to_dict())
            with patch('tianmu_mvp.service.save_state', side_effect=OSError('test disk full')):
                result = service.handle({'action': 'timer_preferences', 'preset_durations': ['2', '3', '4', '5']}, now=101)
            self.assertFalse(result['ok'])
            self.assertEqual(service.game.timer_session.to_dict(), before)
            self.assertEqual(path.read_bytes(), before_bytes)


if __name__ == '__main__':
    unittest.main()
