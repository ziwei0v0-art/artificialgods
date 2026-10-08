"""Timer precision and compatible restore, using isolated in-memory sessions."""

import json
from unittest.mock import patch
import unittest

from tianmu_mvp.duration import ensure_native_library, native_library_path
from tianmu_mvp.timer import TimerSession, validate_presets


class TimerPrecisionTests(unittest.TestCase):
    def test_exact_millisecond_start_does_not_expire_a_millisecond_early(self):
        timer = TimerSession(countdown_seconds=1)
        timer.start('countdown', now=1.001)
        self.assertEqual(timer.tick(now=2.0), 'running')
        self.assertEqual(timer.tick(now=2.001), 'expired')

    def test_short_stopwatch_pauses_retain_all_elapsed_time(self):
        timer = TimerSession()
        timer.start('stopwatch', now=100)
        for index in range(10):
            timer.pause(now=100 + index * 10 + .6)
            timer.resume(now=110 + index * 10)
        timer.finish_stopwatch(now=200)
        self.assertEqual(timer.readout(now=999), '00:06')

    def test_short_countdown_pauses_do_not_add_seconds(self):
        timer = TimerSession(countdown_seconds=60)
        timer.start('countdown', now=100)
        for index in range(10):
            timer.pause(now=100 + index * 10 + .6)
            timer.resume(now=110 + index * 10)
        self.assertEqual(timer.readout(now=200), '00:54')
        self.assertEqual(timer.tick(now=254), 'expired')
        self.assertEqual(timer.tick(now=255), 'unchanged')

    def test_fractional_stopwatch_survives_json_restore_while_paused(self):
        timer = TimerSession()
        timer.start('stopwatch', now=100.125)
        timer.pause(now=100.875)
        restored = TimerSession.from_dict(json.loads(json.dumps(timer.to_dict())))
        restored.resume(now=1000)
        restored.finish_stopwatch(now=1000.25)
        self.assertEqual(restored.seconds(now=2000), 1)

    def test_fractional_countdown_survives_json_restore_while_paused(self):
        timer = TimerSession(countdown_seconds=1)
        timer.start('countdown', now=100.125)
        timer.pause(now=100.875)
        restored = TimerSession.from_dict(json.loads(json.dumps(timer.to_dict())))
        restored.resume(now=1000)
        self.assertEqual(restored.tick(now=1000.249), 'running')
        self.assertEqual(restored.tick(now=1000.25), 'expired')

    def test_pomodoro_fraction_survives_pause_without_automatic_advance(self):
        timer = TimerSession(work_seconds=1, break_seconds=2)
        timer.start('pomodoro', now=100)
        timer.pause(now=100.6)
        timer.resume(now=200)
        self.assertEqual(timer.tick(now=200.4), 'expired')
        self.assertEqual((timer.phase, timer.status), ('work', 'finished'))
        self.assertEqual(timer.tick(now=99999), 'unchanged')
        self.assertTrue(timer.next_phase())
        self.assertEqual((timer.phase, timer.status), ('break', 'idle'))

    def test_legacy_integer_saves_restore_all_four_modes_without_new_fields(self):
        for mode in ('clock', 'countdown', 'stopwatch', 'pomodoro'):
            for paused in (False, True):
                with self.subTest(mode=mode, paused=paused):
                    timer = TimerSession(countdown_seconds=60, work_seconds=60)
                    if mode != 'clock':
                        timer.start(mode, now=100)
                        if paused:
                            timer.pause(now=110)
                    raw = timer.to_dict()
                    for key in ('remaining_milliseconds', 'elapsed_milliseconds', 'pause_started_at', 'preset_seconds'):
                        raw.pop(key)
                    restored = TimerSession.from_dict(json.loads(json.dumps(raw)))
                    self.assertEqual(restored.readout(now=120), timer.readout(now=120))
                    self.assertEqual(restored.preset_seconds, [300, 900, 1500, 2700])
                    if paused and mode != 'clock':
                        restored.resume(now=200)
                        timer.resume(now=200)
                        self.assertEqual(restored.readout(now=210), timer.readout(now=210))

    def test_invalid_or_contradictory_precision_fields_are_rejected(self):
        timer = TimerSession(countdown_seconds=60)
        timer.start('countdown', now=100)
        timer.pause(now=100.25)
        raw = timer.to_dict()
        changes = [
            {'remaining_milliseconds': -1}, {'remaining_milliseconds': True},
            {'remaining_milliseconds': 1.5}, {'remaining_milliseconds': '59750'},
            {'remaining_milliseconds': 1 << 63}, {'remaining_milliseconds': 1000},
            {'elapsed_milliseconds': -1}, {'elapsed_milliseconds': True},
            {'elapsed_milliseconds': 1000}, {'pause_started_at': float('nan')},
            {'pause_started_at': float('inf')}, {'pause_started_at': True},
            {'deadline': 1e100}, {'deadline': 10 ** 400}, {'remaining_seconds': 1 << 63},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                TimerSession.from_dict({**raw, **change})
        timer.stop()
        with self.assertRaises(ValueError):
            TimerSession.from_dict({**timer.to_dict(), 'pause_started_at': 100})

    def test_preset_defaults_are_independent_and_custom_presets_round_trip(self):
        first, second = TimerSession(), TimerSession()
        first.preset_seconds[0] = 60
        self.assertEqual(second.preset_seconds, [300, 900, 1500, 2700])
        first.preset_seconds = [1, 90, 3600, 86400]
        self.assertEqual(TimerSession.from_dict(first.to_dict()).preset_seconds, first.preset_seconds)
        valid = [60, 300, 900, 1800]
        validated = validate_presets(valid)
        validated[0] = 120
        self.assertEqual(valid[0], 60)

    def test_invalid_presets_are_rejected_in_old_or_new_saves(self):
        invalid = [[], [1, 2, 3], [1, 2, 3, 4, 5], [1, 2, 3, 3],
                   [True, 2, 3, 4], [1.0, 2, 3, 4], [0, 2, 3, 4],
                   [-1, 2, 3, 4], [86401, 2, 3, 4], '1,2,3,4', None]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                TimerSession.from_dict({**TimerSession().to_dict(), 'preset_seconds': values})

    def test_independent_sessions_do_not_share_native_global_state(self):
        a = TimerSession(countdown_seconds=60)
        b = TimerSession()
        a.start('countdown', now=100)
        b.start('stopwatch', now=10)
        a.pause(now=100.75)
        b.pause(now=12.25)
        a.resume(now=200)
        b.resume(now=300)
        self.assertEqual(a.tick(now=259.25), 'expired')
        b.finish_stopwatch(now=300.75)
        self.assertEqual(b.readout(now=999), '00:03')
        self.assertEqual(a.readout(now=999), '已结束')

    def test_precompiled_library_is_loaded_without_invoking_a_compiler(self):
        path = ensure_native_library()
        self.assertEqual(path, native_library_path())
        self.assertTrue(path.is_file())
        with patch('tianmu_mvp.duration.subprocess.run', side_effect=AssertionError('Compiler invoked')):
            self.assertEqual(ensure_native_library(), path)


if __name__ == '__main__':
    unittest.main()
