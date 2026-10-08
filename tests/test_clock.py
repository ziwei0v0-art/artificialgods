import unittest

from tianmu_mvp.clock import consume_active_delta


class ActiveClockTests(unittest.TestCase):
    def test_fractional_heartbeats_accumulate_without_losing_time(self):
        seconds, fraction = consume_active_delta(0.6, True)
        self.assertEqual(seconds, 0)
        seconds, fraction = consume_active_delta(0.6, True, fraction)
        self.assertEqual(seconds, 1)
        self.assertAlmostEqual(fraction, 0.2)

    def test_hidden_window_and_long_suspend_discard_elapsed_game_time(self):
        self.assertEqual(consume_active_delta(1.5, False, 0.4), (0, 0.0))
        self.assertEqual(consume_active_delta(900, True, 0.4), (0, 0.0))

    def test_small_scheduler_jitter_keeps_fractional_carry(self):
        self.assertEqual(consume_active_delta(1.2, True, 0.3), (1, 0.5))


if __name__ == "__main__":
    unittest.main()
