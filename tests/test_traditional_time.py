import datetime
import unittest

from tianmu_mvp.duration import parse_duration


class TraditionalDurationTests(unittest.TestCase):
    def test_chinese_units_parse_to_the_same_seconds_as_modern_units(self):
        cases = {
            '一刻': 900, '三刻': 2700, '3刻': 2700, '半刻': 450,
            '半个时辰': 3600, '一时辰': 7200, '2个时辰': 14400,
            '一盏茶': 600, '半盏茶': 300, '半炷香': 900,
            '一炷香': 1800, '两炷香': 3600, '二炷香': 3600,
            '一时辰三刻': 9900, '一刻又五分钟': 1200,
            ' 2 刻 5 分钟 3 秒 ': 2103, '25分钟': 1500,
            '一小时三十分钟': 5400, '半小时': 1800, '十五秒': 15,
            '九十九刻': 89100,
        }
        for value, seconds in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value), seconds)

    def test_tea_and_incense_are_injected_product_durations(self):
        for value, seconds in (('一盏茶', 420), ('半盏茶', 210),
                               ('一炷香', 2400), ('半炷香', 1200),
                               ('两炷香', 4800)):
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value, tea_seconds=420,
                                                incense_seconds=2400), seconds)

    def test_clock_expressions_cannot_start_a_duration(self):
        for value in ('辰时三刻', '辰初三刻', '子正', '午时'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, '时刻'):
                    parse_duration(value)

    def test_malformed_or_ambiguous_chinese_quantities_are_rejected(self):
        for value in ('', '零刻', '0刻', '-一刻', '一二刻', '十十刻',
                      '一两刻', '半半刻', '1.5刻', '1 2刻', '一茶',
                      '一刻余', '一刻又', '又一刻', '一刻又又一秒',
                      '一刻一刻', '一小时一时辰', '一炷香\x00junk',
                      '2147483648秒', '99999999999999999999时辰'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_duration(value)

    def test_unit_config_rejects_non_integer_zero_overflow_and_half_seconds(self):
        for field in ('tea_seconds', 'incense_seconds'):
            for value in (0, -1, True, 3.5, '600', None, float('nan'), 2147483648):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        parse_duration('一刻', **{field: value})
        with self.assertRaises(ValueError):
            parse_duration('半盏茶', tea_seconds=601)
        self.assertEqual(parse_duration('一盏茶', tea_seconds=601), 601)

    def test_existing_catime_inputs_and_int32_limit_are_preserved(self):
        for value, seconds in (('25', 1500), ('1h30m', 5400), ('90s', 90),
                               ('1 30', 90), ('1 30 15', 5415),
                               ('2147483647秒', 2147483647)):
            with self.subTest(value=value):
                self.assertEqual(parse_duration(value), seconds)


class TraditionalReadoutTests(unittest.TestCase):
    def test_elapsed_format_retains_each_remainder_without_rounding(self):
        from tianmu_mvp.traditional_time import traditional_elapsed
        cases = {0: '0秒', 1: '1秒', 59: '59秒', 60: '1分',
                 899: '14分59秒', 900: '一刻', 901: '一刻1秒',
                 1500: '一刻10分', 3900: '四刻5分', 7199: '七刻14分59秒',
                 7200: '一时辰', 7201: '一时辰1秒',
                 8100: '一时辰一刻', 86401: '十二时辰1秒'}
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(traditional_elapsed(seconds), expected)

    def test_duration_labels_show_configured_units_only_when_exact(self):
        from tianmu_mvp.traditional_time import duration_label
        cases = {0: '0秒', 300: '半盏茶', 600: '一盏茶', 900: '一刻',
                 1200: '两盏茶', 1500: '一刻10分', 1800: '一炷香',
                 2700: '三刻', 3600: '半个时辰', 7200: '一时辰'}
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(duration_label(seconds), expected)
        self.assertEqual(duration_label(420, tea_seconds=420), '一盏茶')
        self.assertEqual(duration_label(2400, incense_seconds=2400), '一炷香')
        self.assertEqual(duration_label(600, tea_seconds=420), '10分')

    def test_labels_reject_bad_seconds_instead_of_silently_rounding(self):
        from tianmu_mvp.traditional_time import duration_label, traditional_elapsed
        for formatter in (duration_label, traditional_elapsed):
            for value in (-1, True, 1.5, None, float('inf'), '900'):
                with self.subTest(formatter=formatter.__name__, value=value):
                    with self.assertRaises(ValueError):
                        formatter(value)

    def test_legacy_large_elapsed_values_keep_compact_numeric_counts(self):
        from tianmu_mvp.traditional_time import duration_label, traditional_elapsed
        self.assertEqual(traditional_elapsed(720000000000001), '100000000000时辰1秒')
        self.assertEqual(duration_label(720000000000000), '100000000000时辰')

    def test_clock_rollover_and_quarter_boundaries_use_initial_and_zheng(self):
        from tianmu_mvp.traditional_time import traditional_clock_label
        cases = ((23, 0, '子初'), (23, 59, '子初三刻'), (0, 0, '子正'),
                 (0, 59, '子正三刻'), (1, 0, '丑初'), (7, 0, '辰初'),
                 (7, 14, '辰初'), (7, 15, '辰初一刻'), (7, 45, '辰初三刻'),
                 (8, 0, '辰正'), (8, 30, '辰正二刻'), (9, 0, '巳初'))
        for hour, minute, expected in cases:
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(traditional_clock_label(datetime.time(hour, minute)), expected)

    def test_clock_parser_keeps_wall_clock_addresses_separate_from_durations(self):
        from tianmu_mvp.traditional_time import parse_traditional_clock
        cases = {'辰时三刻': (7, 45), '辰时3刻': (7, 45), '辰初三刻': (7, 45),
                 '辰时初三刻': (7, 45), '辰正二刻': (8, 30), '辰时七刻': (8, 45),
                 '辰时': (7, 0), '辰初初刻': (7, 0), '子正': (0, 0),
                 '子时四刻': (0, 0), '子时七刻': (0, 45), '亥正三刻': (22, 45)}
        for value, (hour, minute) in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_traditional_clock(value), datetime.time(hour, minute))
        for value in ('辰', '辰时八刻', '辰正四刻', '辰初五刻', '一炷香',
                      '辰时三刻后', '辰时三刻\x00', '辰时-1刻', '辰时一二刻'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_traditional_clock(value)

    def test_every_quarter_of_a_day_round_trips_as_a_clock_address(self):
        from tianmu_mvp.traditional_time import parse_traditional_clock, traditional_clock_label
        for minute in range(0, 1440, 15):
            moment = datetime.time(minute // 60, minute % 60)
            with self.subTest(moment=moment):
                self.assertEqual(parse_traditional_clock(traditional_clock_label(moment)), moment)

    def test_clock_readout_uses_requested_timezone_and_keeps_modern_time(self):
        from tianmu_mvp.clock import clock_readout
        timestamp = datetime.datetime(2026, 10, 8, 23, 45,
                                      tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(clock_readout(timestamp, timezone='Asia/Shanghai'),
                         '07:45:00\n辰初三刻')
        self.assertEqual(clock_readout(timestamp, timezone='UTC', show_traditional=False),
                         '23:45:00')
        for value in (True, None, '0', float('nan'), float('inf'), 10 ** 1000):
            with self.subTest(value=repr(value)[:25]):
                with self.assertRaises(ValueError):
                    clock_readout(value)
        with self.assertRaises(ValueError):
            clock_readout(timestamp, timezone='No/Such/Timezone')


if __name__ == '__main__':
    unittest.main()
