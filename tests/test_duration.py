import unittest


class DurationParsingTests(unittest.TestCase):
    def test_mature_parser_accepts_units_and_minutes(self):
        from tianmu_mvp.duration import parse_duration
        for text, expected in (("25", 1500), ("1h30m", 5400), ("90s", 90), ("1 30", 90), ("1 30 15", 5415)):
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), expected)

    def test_invalid_zero_negative_overflow_and_embedded_nul_are_rejected(self):
        from tianmu_mvp.duration import parse_duration
        for text in ("", "0", "-5", "bad", "99999999999999999999h", "1 70", "25\x00junk"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)
