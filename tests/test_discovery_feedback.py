"""Committed discovery feedback and capture dates; temporary saves, no worker/UI."""
import copy
import datetime
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from tianmu_mvp.model import COLORS, GameState
from tianmu_mvp.service import ApplicationService


def instant(value):
    return datetime.datetime.fromisoformat(value).timestamp()


class DiscoveryFeedbackTests(unittest.TestCase):
    def service(self, zone='UTC'):
        folder = tempfile.TemporaryDirectory(prefix='tianmu-discovery-')
        self.addCleanup(folder.cleanup)
        app = ApplicationService(Path(folder.name) / 'state.json')
        app.game = GameState.new(rng=random.Random(19))
        app.game.game_timezone = zone
        return app

    def add_bug(self, app, genotype=('Aa', 'Bb'), sex='F'):
        bug = app.game._new_insect(sex=sex, genotype=genotype)
        app.game.desktop[bug.id] = bug
        return bug

    def feedback(self, reply, colors=(), ok=True):
        self.assertEqual(reply['ok'], ok, reply)
        self.assertEqual(reply.get('new_discoveries'), list(colors), reply)

    def test_snapshot_has_descriptions_for_all_four_entries_without_discovering_them(self):
        app = self.service()
        before = copy.deepcopy(app.game)
        reply = app.handle({'action': 'snapshot'}, now=instant('2032-01-01T12:00:00+00:00'))
        rows = reply['state']['discoveries']
        self.assertEqual([row['color'] for row in rows], list(COLORS))
        self.assertTrue(all(isinstance(row.get('description'), str) and row['description'].strip()
                            for row in rows), rows)
        self.assertTrue(all(not row['found'] and row['date'] is None for row in rows))
        self.assertEqual(app.game.discovered_colors, before.discovered_colors)
        self.assertEqual(app.game.discovery_dates, before.discovery_dates)
        self.assertFalse(app.save_path.exists(), 'Looking at the codex must not create a save')
        self.feedback(reply)

    def test_manual_multicolor_capture_reports_each_new_color_once_in_codex_order(self):
        app = self.service()
        bugs = [self.add_bug(app, genes) for genes in
                [('Aa', 'Bb'), ('Aa', 'bb'), ('aa', 'Bb'), ('aa', 'bb')]]
        now = instant('2032-04-05T12:00:00+00:00')
        ids = [bug.id for bug in reversed(bugs)] + [bugs[-1].id, 'missing-bug']
        reply = app.handle({'action': 'catch', 'ids': ids}, now=now)
        self.feedback(reply, ['普通褐色', '中褐色', '深褐色', '白色'])
        self.assertEqual(app.game.bottle, {bug.id: bug for bug in bugs})
        self.assertEqual(app.game.coins, 0)
        self.assertEqual(app.game.discovery_dates, {color: '2032-04-05' for color in COLORS})
        restored = ApplicationService(app.save_path)
        self.assertEqual(restored.game.discovery_dates, app.game.discovery_dates)
        self.assertEqual(restored.game.bottle, app.game.bottle)

    def test_repeat_release_sale_and_restart_never_report_saved_discovery_again(self):
        app = self.service()
        bug = self.add_bug(app)
        now = instant('2032-04-05T12:00:00+00:00')
        self.feedback(app.handle({'action': 'catch', 'ids': [bug.id]}, now=now), ['普通褐色'])
        first_date = dict(app.game.discovery_dates)
        self.feedback(app.handle({'action': 'catch', 'ids': [bug.id, bug.id]}, now=now))
        self.feedback(app.handle({'action': 'release', 'color': bug.color, 'count': 1}, now=now))
        self.assertEqual(app.game.desktop[bug.id], bug)
        self.feedback(app.handle({'action': 'catch', 'ids': [bug.id]}, now=now + 86400))
        preview = app.handle({'action': 'sale_preview', 'color': bug.color, 'count': 1}, now=now)
        self.feedback(preview)
        self.feedback(app.handle({'action': 'sale_cancel'}, now=now))
        preview = app.handle({'action': 'sale_preview', 'color': bug.color, 'count': 1}, now=now)
        self.feedback(app.handle({'action': 'sale_confirm', 'token': preview['sale']['token']}, now=now))
        self.assertFalse(app.game.bottle)
        restored = ApplicationService(app.save_path)
        self.assertEqual(restored.game.discovered_colors, {'普通褐色'})
        self.assertEqual(restored.game.discovery_dates, first_date)
        self.feedback(restored.handle({'action': 'snapshot'}, now=now))
        self.feedback(restored.tick(now=now, active_seconds=0))
        other = self.add_bug(restored)
        self.feedback(restored.handle({'action': 'catch', 'ids': [other.id]}, now=now + 86400))
        self.assertEqual(restored.game.discovery_dates, first_date)

    def test_failed_manual_save_rolls_back_discovery_and_retry_reports_it(self):
        app = self.service()
        bug = self.add_bug(app, ('aa', 'bb'))
        before = copy.deepcopy(app.game)
        now = instant('2032-04-05T12:00:00+00:00')
        with patch('tianmu_mvp.service.save_state', side_effect=OSError('isolated disk failure')):
            reply = app.handle({'action': 'catch', 'ids': [bug.id]}, now=now)
        self.feedback(reply, ok=False)
        self.assertEqual(app.game.desktop, before.desktop)
        self.assertEqual(app.game.bottle, before.bottle)
        self.assertEqual(app.game.discovered_colors, before.discovered_colors)
        self.assertEqual(app.game.discovery_dates, before.discovery_dates)
        self.assertFalse(app.save_path.exists())
        self.feedback(app.handle({'action': 'catch', 'ids': [bug.id]}, now=now), ['白色'])
        self.assertEqual(app.game.bottle[bug.id], bug)
        self.assertEqual(app.game.discovery_dates['白色'], '2032-04-05')

    def test_automatic_capture_uses_its_second_before_midnight_and_preserves_timer_event(self):
        app = self.service('Asia/Shanghai')
        start = instant('2032-04-05T23:58:59+08:00')
        app.game.advance(59, now=start + 59)
        self.assertFalse(app.game.bottle)
        self.feedback(app.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '1s'},
                                 now=start + 59))
        # Capture at t=60 (23:59:59), tick response at t=61 (next day).
        reply = app.tick(now=start + 61, active_seconds=2)
        self.feedback(reply, ['普通褐色'])
        self.assertEqual(reply['events'], ['timer_expired'])
        self.assertEqual(len(app.game.bottle), 1)
        self.assertEqual(app.game.discovery_dates['普通褐色'], '2032-04-05')
        self.assertEqual(reply['state']['routine']['game_date'], '2032-04-06')
        next_reply = app.tick(now=start + 62, active_seconds=1)
        self.feedback(next_reply)
        self.assertEqual(next_reply['events'], [])

    def test_failed_automatic_save_restores_capture_clock_rng_and_discovery_for_retry(self):
        app = self.service('Asia/Shanghai')
        start = instant('2032-04-05T23:58:59+08:00')
        app.game.advance(59, now=start + 59)
        app.handle({'action': 'checkpoint'}, now=start + 59)
        before = copy.deepcopy(app.game)
        saved = app.save_path.read_bytes()
        with patch('tianmu_mvp.service.save_state', side_effect=OSError('isolated tick failure')):
            reply = app.tick(now=start + 61, active_seconds=2)
        self.feedback(reply, ok=False)
        self.assertEqual(reply['events'], [])
        for name in ('desktop', 'bottle', 'discovered_colors', 'discovery_dates',
                     'elapsed_seconds', 'active_capture_seconds', 'routine'):
            self.assertEqual(getattr(app.game, name), getattr(before, name), name)
        self.assertEqual(app.game.rng.getstate(), before.rng.getstate())
        self.assertEqual(app.save_path.read_bytes(), saved)
        self.feedback(app.tick(now=start + 61, active_seconds=2), ['普通褐色'])
        self.assertEqual(len(app.game.bottle), 1)
        self.assertEqual(app.game.discovery_dates['普通褐色'], '2032-04-05')

    def test_manual_capture_date_uses_service_clock_and_game_timezone_across_midnight(self):
        for zone, expected in [('Asia/Shanghai', ('2032-04-05', '2032-04-06')),
                               ('Pacific/Honolulu', ('2032-04-05', '2032-04-05'))]:
            with self.subTest(zone=zone):
                app = self.service(zone)
                first = self.add_bug(app)
                second = self.add_bug(app, ('aa', 'bb'))
                edge = instant('2032-04-05T16:00:00+00:00')
                app.handle({'action': 'catch', 'ids': [first.id]}, now=edge - 1)
                app.handle({'action': 'catch', 'ids': [second.id]}, now=edge)
                self.assertEqual(app.game.discovery_dates,
                                 {'普通褐色': expected[0], '白色': expected[1]})

    def test_old_discovery_without_date_stays_unknown_after_recapture(self):
        app = self.service()
        bug = self.add_bug(app)
        app.game.discovered_colors.add(bug.color)
        # Older records may have a discovered color without its first date.
        app.handle({'action': 'checkpoint'}, now=0)
        app = ApplicationService(app.save_path)
        reply = app.handle({'action': 'catch', 'ids': [bug.id]},
                           now=instant('2032-04-05T12:00:00+00:00'))
        self.assertNotIn(bug.color, app.game.discovery_dates,
                         'Recapture must not invent a first date for an old discovery')
        self.feedback(reply)
        row = next(row for row in reply['state']['discoveries'] if row['color'] == bug.color)
        self.assertTrue(row['found'])
        self.assertIsNone(row['date'])

    def test_legacy_catch_without_clock_keeps_working(self):
        app = self.service()
        bug = self.add_bug(app)
        before = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        self.assertEqual(app.game.catch([bug.id]), [bug.id])
        after = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        self.assertIn(app.game.discovery_dates[bug.color], (before, after))
        self.assertEqual(app.game.bottle[bug.id], bug)
