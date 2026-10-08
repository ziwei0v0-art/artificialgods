import unittest

from tianmu_mvp.timer import TimerSession


class TimerSessionTests(unittest.TestCase):
    def test_clock_uses_its_own_timezone_and_fifteen_minute_quarters(self):
        import datetime
        timer = TimerSession(mode="clock")
        timer.clock_timezone = "Asia/Shanghai"
        timer.show_traditional = True
        timestamp = datetime.datetime(2026, 9, 25, 0, 30, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(timer.readout(timestamp), "08:30:00\n辰正二刻")
        restored = TimerSession.from_dict(timer.to_dict())
        self.assertEqual(restored.clock_timezone, "Asia/Shanghai")
        self.assertEqual(restored.readout(timestamp), "08:30:00\n辰正二刻")

    def test_finished_stopwatch_keeps_elapsed_readout_after_restore(self):
        timer = TimerSession()
        timer.start("stopwatch", now=100)
        timer.finish_stopwatch(now=165)
        restored = TimerSession.from_dict(timer.to_dict())
        self.assertEqual(restored.status, "finished")
        self.assertEqual(restored.readout(now=999), "01:05")

    def test_pause_at_deadline_leaves_expiry_for_single_notification(self):
        for mode in ("countdown", "pomodoro"):
            with self.subTest(mode=mode):
                timer = TimerSession(work_seconds=60)
                timer.start(mode, now=100, minutes=1)
                self.assertFalse(timer.pause(now=161))
                self.assertEqual(timer.tick(now=162), "expired")
                self.assertEqual(timer.tick(now=163), "unchanged")
                self.assertEqual(timer.status, "finished")

    def test_countdown_pauses_resumes_and_expires_once(self):
        timer = TimerSession()
        timer.start("countdown", now=100, minutes=2)
        self.assertEqual(timer.readout(now=130), "01:30")
        timer.pause(now=130)
        self.assertEqual(timer.readout(now=500), "01:30")
        timer.resume(now=500)
        self.assertEqual(timer.tick(now=590), "expired")
        self.assertEqual(timer.tick(now=600), "unchanged")
        self.assertEqual(timer.readout(now=600), "已结束")

    def test_stopwatch_continues_across_pause_and_restore(self):
        timer = TimerSession()
        timer.start("stopwatch", now=10)
        self.assertEqual(timer.readout(now=73), "01:03")
        timer.pause(now=73)
        restored = TimerSession.from_dict(timer.to_dict())
        self.assertEqual(restored.readout(now=100), "01:03")
        restored.resume(now=100)
        self.assertEqual(restored.readout(now=157), "02:00")

    def test_pomodoro_waits_for_confirmation_before_next_phase(self):
        timer = TimerSession(work_seconds=60, break_seconds=30)
        timer.start("pomodoro", now=0)
        self.assertEqual(timer.tick(now=60), "expired")
        self.assertEqual(timer.phase, "work")
        self.assertEqual(timer.status, "finished")
        self.assertTrue(timer.next_phase())
        self.assertEqual(timer.phase, "break")
        self.assertEqual(timer.status, "idle")
        timer.start("pomodoro", now=90)
        self.assertEqual(timer.readout(now=100), "00:20")

    def test_running_countdown_deadline_survives_restore_and_stop_resets(self):
        timer = TimerSession()
        timer.start("countdown", now=100, minutes=1)
        restored = TimerSession.from_dict(timer.to_dict())
        self.assertEqual(restored.readout(now=130), "00:30")
        restored.stop()
        self.assertEqual(restored.status, "idle")
        self.assertEqual(restored.readout(now=300), "尚未开始")

    def test_countdown_keeps_the_last_custom_duration_for_next_start(self):
        timer = TimerSession()
        timer.start("countdown", now=0, minutes=17)
        timer.stop()
        timer.start(now=100)
        self.assertEqual(timer.remaining_seconds, 17 * 60)


if __name__ == "__main__":
    unittest.main()
