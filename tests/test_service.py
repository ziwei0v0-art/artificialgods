import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ApplicationServiceTests(unittest.TestCase):
    def test_navigation_cancel_is_silent_but_real_cancel_confirms(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as directory:
            app = ApplicationService(Path(directory) / 'state.json')
            self.assertNotIn('message', app.handle({'action': 'sale_cancel'}))
            app.game.advance(15)
            first = next(iter(app.game.desktop.values()))
            app.handle({'action': 'catch', 'ids': [first.id]})
            app.handle({'action': 'sale_preview', 'color': first.color, 'count': 1})
            result = app.handle({'action': 'sale_cancel'})
            self.assertIn('已取消', result['message'])
            self.assertIn(first.id, app.game.bottle)
            self.assertIsNone(app.pending_sale)
            self.assertNotIn('message', app.handle({'action': 'sale_cancel'}))

    def test_rules_can_run_without_loading_tk_and_survive_restart(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            app = ApplicationService(path)
            app.game.advance(15)
            first = next(iter(app.game.desktop.values()))
            self.assertTrue(app.handle({'action': 'catch', 'ids': [first.id]})['ok'])
            preview = app.handle({'action': 'sale_preview', 'color': first.color, 'count': 1})
            self.assertEqual(preview['sale']['amount'], 1)
            result = app.handle({'action': 'sale_confirm', 'token': preview['sale']['token']})
            self.assertTrue(result['ok'])
            self.assertEqual(result['state']['coins'], 1)
            restored = ApplicationService(path)
            self.assertIn(first.id, restored.game.sold_ids)
            self.assertEqual(restored.game.coins, 1)
            self.assertFalse(app.handle({'action': 'sale_confirm', 'token': preview['sale']['token']})['ok'])

    def test_service_rolls_back_failed_disk_write(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as directory:
            app = ApplicationService(Path(directory) / 'state.json')
            app.game.advance(15)
            first = next(iter(app.game.desktop.values()))
            with patch('tianmu_mvp.service.save_state', side_effect=OSError('disk full')):
                result = app.handle({'action': 'catch', 'ids': [first.id]})
            self.assertFalse(result['ok'])
            self.assertIn(first.id, app.game.desktop)
            self.assertNotIn(first.id, app.game.bottle)

    def test_timer_uses_vendored_parser_and_never_silently_replaces_task(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as directory:
            app = ApplicationService(Path(directory) / 'state.json')
            result = app.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '1m30s'}, now=100)
            self.assertTrue(result['ok'])
            self.assertEqual(app.game.timer_session.deadline, 190)
            self.assertFalse(app.handle({'action': 'timer_start', 'mode': 'stopwatch'}, now=110)['ok'])
            self.assertEqual(app.game.timer_session.deadline, 190)
            expired = app.tick(now=191, active_seconds=0)
            self.assertEqual(expired['events'], ['timer_expired'])
            self.assertEqual(app.tick(now=192, active_seconds=0)['events'], [])

    def test_unknown_command_does_not_create_a_save_or_mutate_state(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            app = ApplicationService(path)
            result = app.handle({'action': 'delete_everything'})
            self.assertFalse(result['ok'])
            self.assertFalse(path.exists())

    def test_clock_readout_does_not_replace_running_countdown(self):
        from tianmu_mvp.service import ApplicationService
        with tempfile.TemporaryDirectory() as directory:
            app = ApplicationService(Path(directory) / 'state.json')
            app.handle({'action': 'timer_start', 'mode': 'countdown', 'duration': '90s'}, now=1000)
            state = app.snapshot(1010)
            self.assertIn('clock_readout', state['timer'])
            self.assertEqual(state['timer']['deadline'], 1090)
            self.assertEqual(app.game.timer_session.mode, 'countdown')
