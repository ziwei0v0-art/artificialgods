"""Decoration purchase/placement rules; temporary saves, no UI or worker."""
import copy
import datetime
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from tianmu_mvp.model import GameState
from tianmu_mvp.service import ApplicationService
from tianmu_mvp.storage import _state_dict, load_state, save_state


NOW = datetime.datetime.fromisoformat('2032-04-05T12:00:20+00:00').timestamp()
ITEMS = ('offering_plate', 'incense_burner', 'bell', 'shrine_g1', 'shrine_g2')


class DecorationGrowthTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='tianmu-decoration-')
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'state.json'
        self.backup = Path(str(self.path) + '.bak')

    def game(self, coins=1000, age=20):
        game = GameState.new(rng=random.Random(160))
        game.game_timezone = 'UTC'
        game.advance(age, now=NOW)
        game.sync_routine(NOW)
        game.coins = coins
        return game

    def app(self, game=None):
        return ApplicationService(self.path, initial_state=game or self.game())

    @staticmethod
    def rows(state):
        return {item['id']: item for item in state['shop']}

    def command(self, app, action, item):
        result = app.handle({'action': action, 'item': item}, now=NOW)
        self.assertTrue(result['ok'], result)
        return result['state']

    def test_direct_model_cannot_buy_g2_without_owned_g1_even_with_enough_coins(self):
        for coins in (360, 1000):
            with self.subTest(coins=coins):
                game = self.game(coins)
                before = copy.deepcopy(_state_dict(game))
                self.assertFalse(game.buy('shrine_g2'))
                self.assertEqual(_state_dict(game), before)

    def test_service_rejects_locked_g2_before_balance_without_writing(self):
        for coins in (0, 1000):
            with self.subTest(coins=coins):
                app = self.app(self.game(coins))
                before = copy.deepcopy(_state_dict(app.game))
                app.pending_sale = ('existing-preview', [], 0)
                result = app.handle({'action': 'buy', 'item': 'shrine_g2'}, now=NOW)
                self.assertFalse(result['ok'])
                self.assertIn('先整修神龛', result['error'])
                self.assertEqual(_state_dict(app.game), before)
                self.assertEqual(app.pending_sale, ('existing-preview', [], 0))
                self.assertFalse(self.path.exists())
                self.assertFalse(self.backup.exists())

    def test_g1_ownership_unlocks_g2_without_placing_and_g2_costs_additional_360(self):
        game = self.game(480)
        self.assertTrue(game.buy('shrine_g1'))
        self.assertEqual(game.coins, 360)
        self.assertEqual(game.placed_items, {})
        self.assertTrue(game.buy('shrine_g2'))
        self.assertEqual(game.coins, 0)
        self.assertEqual(game.owned_items, {'shrine_g1', 'shrine_g2'})
        self.assertEqual(game.shrine_stage, 0)
        before = copy.deepcopy(_state_dict(game))
        self.assertFalse(game.buy('shrine_g2'))
        self.assertEqual(_state_dict(game), before)

    def test_snapshot_availability_priorities_and_static_requirement(self):
        cases = (
            (0, (), 'shrine_g2', False, '先整修神龛'),
            (1000, (), 'shrine_g2', False, '先整修神龛'),
            (359, ('shrine_g1',), 'shrine_g2', False, '铜钱不足'),
            (360, ('shrine_g1',), 'shrine_g2', True, None),
            (0, ('shrine_g2',), 'shrine_g2', False, '已拥有'),
            (1000, ('shrine_g1', 'shrine_g2'), 'shrine_g2', False, '已拥有'),
            (11, (), 'offering_plate', False, '铜钱不足'),
            (12, (), 'offering_plate', True, None),
            (0, ('offering_plate',), 'offering_plate', False, '已拥有'),
        )
        for coins, owned, item, can_buy, reason in cases:
            with self.subTest(coins=coins, owned=owned, item=item):
                game = self.game(coins)
                game.owned_items.update(owned)
                rows = self.rows(self.app(game).snapshot(NOW))
                self.assertEqual(set(rows), set(ITEMS))
                self.assertIs(rows[item]['can_buy'], can_buy)
                self.assertEqual(rows[item]['unavailable_reason'], reason)
                for key, row in rows.items():
                    self.assertEqual(row['requires'], 'shrine_g1' if key == 'shrine_g2' else None)

    def test_snapshot_is_read_only_and_placement_mapping_is_detached(self):
        game = self.game()
        game.owned_items.update(ITEMS)
        game.placed_items = {'plate': 'offering_plate', 'incense': 'incense_burner',
                             'bell': 'bell', 'shrine': 'shrine_g1'}
        game.placed_item = 'offering_plate'
        app = self.app(game)
        before = copy.deepcopy(_state_dict(game))
        state = app.handle({'action': 'snapshot'}, now=NOW)['state']
        self.assertEqual(state['placed_items'], before['placed_items'])
        self.assertEqual(state['shrine_stage'], 1)
        rows = self.rows(state)
        for item in ITEMS:
            self.assertIs(rows[item]['placed'], item != 'shrine_g2')
        state['placed_items']['shrine'] = 'shrine_g2'
        state['placed_items'].pop('plate')
        self.assertEqual(_state_dict(game), before)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.backup.exists())

    def test_snapshot_and_purchase_reply_use_same_reason_for_every_item(self):
        for item in ITEMS:
            for already_owned in (False, True):
                with self.subTest(item=item, already_owned=already_owned):
                    game = self.game(0)
                    if already_owned:
                        game.owned_items.add(item)
                    app = self.app(game)
                    row = self.rows(app.snapshot(NOW))[item]
                    self.assertFalse(row['can_buy'])
                    before = copy.deepcopy(_state_dict(game))
                    result = app.handle({'action': 'buy', 'item': item}, now=NOW)
                    self.assertFalse(result['ok'])
                    self.assertIn(row['unavailable_reason'], result['error'])
                    self.assertEqual(_state_dict(app.game), before)
                    self.assertFalse(self.path.exists())

    def test_successful_service_purchase_persists_ownership_without_placement(self):
        app = self.app(self.game(480))
        first = self.command(app, 'buy', 'shrine_g1')
        self.assertEqual(first['coins'], 360)
        self.assertTrue(self.rows(first)['shrine_g2']['can_buy'])
        self.assertEqual(first['placed_items'], {})
        second = self.command(app, 'buy', 'shrine_g2')
        self.assertEqual(second['coins'], 0)
        self.assertEqual(second['shrine_stage'], 0)
        self.assertEqual(second['placed_items'], {})
        restored = ApplicationService(self.path)
        self.assertEqual(restored.game.owned_items, {'shrine_g1', 'shrine_g2'})
        self.assertEqual(restored.game.coins, 0)
        self.assertEqual(restored.game.placed_items, {})
        original = self.path.read_bytes()
        result = restored.handle({'action': 'buy', 'item': 'shrine_g2'}, now=NOW)
        self.assertFalse(result['ok'])
        self.assertIn('已拥有', result['error'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_legacy_g2_only_save_loads_equips_and_reverts_without_g1_or_charge(self):
        game = self.game(7)
        # This is an existing ownership record, not a new purchase under 160.
        game.owned_items.add('shrine_g2')
        save_state(self.path, game)
        original = self.path.read_bytes()
        app = ApplicationService(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(app.game.owned_items, {'shrine_g2'})
        state = self.command(app, 'place', 'shrine_g2')
        self.assertEqual((state['coins'], state['shrine_stage']), (7, 2))
        self.assertEqual(state['placed_items'], {'shrine': 'shrine_g2'})
        restored = ApplicationService(self.path)
        self.assertEqual(restored.game.owned_items, {'shrine_g2'})
        state = self.command(restored, 'place', 'shrine_g2')
        self.assertEqual((state['coins'], state['shrine_stage']), (7, 0))
        self.assertEqual(state['placed_items'], {})
        final = load_state(self.path)
        self.assertEqual((final.coins, final.owned_items), (7, {'shrine_g2'}))

    def test_independent_slots_switch_shrine_and_revert_without_repurchase(self):
        app = self.app()
        app.game.routine.bell_trial_played = True
        for item in ITEMS:
            self.command(app, 'buy', item)
            self.command(app, 'place', item)
        expected = {'plate': 'offering_plate', 'incense': 'incense_burner',
                    'bell': 'bell', 'shrine': 'shrine_g2'}
        self.assertEqual(app.snapshot(NOW)['placed_items'], expected)
        self.assertEqual(app.game.coins, 424)
        self.command(app, 'place', 'shrine_g1')
        expected['shrine'] = 'shrine_g1'
        self.assertEqual(app.snapshot(NOW)['placed_items'], expected)
        self.assertEqual(app.game.shrine_stage, 1)
        self.command(app, 'place', 'shrine_g1')
        expected.pop('shrine')
        self.command(app, 'place', 'offering_plate')
        expected.pop('plate')
        self.assertEqual(app.snapshot(NOW)['placed_items'], expected)
        self.assertIsNone(app.game.placed_item)
        restored = ApplicationService(self.path)
        self.assertEqual(restored.game.placed_items, expected)
        self.assertEqual(restored.game.coins, 424)
        self.assertEqual(restored.game.owned_items, set(ITEMS))
        self.assertEqual(restored.game.shrine_stage, 0)

    def test_decoration_changes_preserve_fruit_bugs_clocks_rng_and_history(self):
        for age, stage in ((0, 'fresh'), (8, 'soft'), (20, 'ripe')):
            with self.subTest(fruit_stage=stage):
                game = self.game(age=age)
                game.routine.bell_trial_played = True  # Existing trial is not replayed.
                if game.desktop:
                    game.catch([next(iter(game.desktop))], now=NOW)
                game.active_capture_seconds = 321
                game.sign_history = {'2032-04-04': '3'}
                game.daily_sign_date, game.daily_sign = '2032-04-04', '3'
                game.timer_session.countdown_seconds = 120
                game.timer_session.start('countdown', now=NOW - 30)
                game.timer_deadline = game.timer_session.deadline
                game.timer_remaining = game.timer_session.remaining_seconds
                app = self.app(game)
                before = copy.deepcopy(_state_dict(game))
                self.assertEqual(game.routine.fruit_stage(age), stage)
                for item in ITEMS:
                    self.command(app, 'buy', item)
                    self.command(app, 'place', item)
                    self.command(app, 'place', item)
                after = copy.deepcopy(_state_dict(app.game))
                for key in ('coins', 'owned_items', 'placed_item', 'placed_items'):
                    before.pop(key)
                    after.pop(key)
                self.assertEqual(after, before)
                self.assertEqual(app.game.routine.fruit_stage(age), stage)

    def test_failed_purchase_or_placement_save_rolls_back_state_preview_and_both_files(self):
        cases = (('buy', 'shrine_g1', (), {}),
                 ('buy', 'shrine_g2', ('shrine_g1',), {}),
                 ('place', 'incense_burner', ('incense_burner',), {}),
                 ('place', 'shrine_g2', ('shrine_g1', 'shrine_g2'), {'shrine': 'shrine_g1'}),
                 ('place', 'shrine_g2', ('shrine_g2',), {'shrine': 'shrine_g2'}))
        for action, item, owned, placed in cases:
            with self.subTest(action=action, item=item, placed=placed):
                game = self.game()
                game.owned_items.update(owned)
                game.placed_items.update(placed)
                bug = next(iter(game.desktop.values()))
                game.catch([bug.id], now=NOW)
                app = self.app(game)
                save_state(self.path, game)
                save_state(self.path, game)
                app.handle({'action': 'sale_preview', 'color': bug.color, 'count': 1}, now=NOW)
                pending = copy.deepcopy(app.pending_sale)
                before = copy.deepcopy(_state_dict(game))
                original, backup = self.path.read_bytes(), self.backup.read_bytes()
                with patch('tianmu_mvp.service.save_state', side_effect=OSError('disk full')):
                    result = app.handle({'action': action, 'item': item}, now=NOW)
                self.assertFalse(result['ok'])
                self.assertIn('disk full', result['error'])
                self.assertEqual(_state_dict(app.game), before)
                self.assertEqual(app.pending_sale, pending)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.backup.read_bytes(), backup)


if __name__ == '__main__':
    unittest.main()
