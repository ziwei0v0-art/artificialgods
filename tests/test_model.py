import random
import unittest

from tianmu_mvp.model import GameState


class GameStateTests(unittest.TestCase):
    def test_first_six_insects_appear_after_fifteen_active_seconds(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(14)
        self.assertEqual(game.desktop_count, 0)
        game.advance(1)
        self.assertEqual(game.desktop_count, 6)
        self.assertEqual(len({insect.id for insect in game.desktop.values()}), 6)
        self.assertEqual(sum(insect.sex == "F" for insect in game.desktop.values()), 3)
        self.assertEqual(sum(insect.sex == "M" for insect in game.desktop.values()), 3)
        self.assertTrue(all(insect.genotype == ("Aa", "Bb") for insect in game.desktop.values()))

    def test_catch_and_release_moves_same_individual_without_changing_genes(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(15)
        insect = next(iter(game.desktop.values()))
        caught = game.catch([insect.id])
        self.assertEqual(caught, [insect.id])
        self.assertNotIn(insect.id, game.desktop)
        returned = game.release(insect.color, insect.sex, 1)
        self.assertEqual(returned, [insect.id])
        self.assertEqual(game.desktop[insect.id], insect)
        self.assertEqual(game.active_capture_seconds, 0)
        self.assertEqual(game.discovered_colors, {insect.color})

    def test_duplicate_catch_and_zero_release_have_no_side_effect(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(15)
        insect = next(iter(game.desktop.values()))
        self.assertEqual(game.catch([insect.id, insect.id]), [insect.id])
        game.active_capture_seconds = 123
        self.assertEqual(game.release(insect.color, insect.sex, 0), [])
        self.assertEqual(game.active_capture_seconds, 123)

    def test_sale_pays_price_and_partial_sale_resets_capture_limit(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(15)
        caught = list(game.desktop.values())
        game.catch([insect.id for insect in caught[:2]])
        game.active_capture_seconds = 86400
        before = game.coins
        sold = game.sell(caught[0].color, caught[0].sex, 1)
        self.assertEqual(sold, [caught[0].id])
        self.assertEqual(game.coins - before, game.prices[caught[0].color])
        self.assertEqual(game.active_capture_seconds, 0)
        self.assertIn(caught[1].id, game.bottle)
        self.assertIn(caught[0].id, game.sold_ids)

    def test_sale_quote_reports_count_and_amount_without_mutation(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(15)
        bugs = list(game.desktop.values())[:2]
        game.catch([bug.id for bug in bugs])
        before = dict(game.bottle)
        ids, amount = game.quote_sale(bugs[0].color, bugs[0].sex, 1)
        self.assertEqual(ids, [bugs[0].id])
        self.assertEqual(amount, game.prices[bugs[0].color])
        self.assertEqual(game.bottle, before)

    def test_confirmed_sale_uses_frozen_ids_when_matching_insect_arrives_later(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(15)
        first, second = list(game.desktop.values())[:2]
        self.assertEqual(first.color, second.color)
        self.assertEqual(first.sex, second.sex)
        game.catch([first.id])
        selected_ids, expected_amount = game.quote_sale(first.color, first.sex, 1)
        self.assertEqual(selected_ids, [first.id])

        # Model an automatic capture arriving while the confirmation dialog is open.
        game.catch([second.id])
        sold = game.sell_ids(selected_ids)

        self.assertEqual(sold, [first.id])
        self.assertIn(first.id, game.sold_ids)
        self.assertIn(second.id, game.bottle)
        self.assertEqual(game.coins, expected_amount)

    def test_capture_limit_stops_auto_capture_but_keeps_manual_capture(self):
        game = GameState.new(rng=random.Random(2))
        game.advance(15)
        game.active_capture_seconds = 86400 - 45
        game.advance(45)
        self.assertTrue(game.auto_capture_paused)
        self.assertEqual(len(game.bottle), 0)
        remaining = next(iter(game.desktop.values()))
        self.assertEqual(game.catch([remaining.id]), [remaining.id])

    def test_decorations_keep_independent_slots_and_growth_can_be_reverted(self):
        game = GameState.new()
        game.coins = 1000
        for item in ("offering_plate", "incense_burner", "bell", "shrine_g1", "shrine_g2"):
            self.assertTrue(game.buy(item), item)
            self.assertTrue(game.place(item), item)
        self.assertEqual(game.coins, 424)
        self.assertEqual(game.placed_item, "offering_plate")
        self.assertEqual(game.shrine_stage, 2)
        self.assertTrue(game.place("shrine_g2"))
        self.assertEqual(game.shrine_stage, 0)
        self.assertIn("shrine_g2", game.owned_items)
        self.assertTrue(game.place("shrine_g1"))
        self.assertEqual(game.shrine_stage, 1)
        self.assertFalse(game.buy("bell"))
        self.assertEqual(game.coins, 424)

    def test_purchase_and_placement_are_separate_and_do_not_charge_twice(self):
        game = GameState.new(rng=random.Random(2))
        game.coins = 20
        self.assertTrue(game.buy("offering_plate"))
        self.assertEqual(game.coins, 8)
        self.assertTrue(game.place("offering_plate"))
        self.assertEqual(game.placed_item, "offering_plate")
        self.assertTrue(game.place("offering_plate"))
        self.assertEqual(game.coins, 8)
        self.assertIsNone(game.placed_item)

    def test_breeding_inherits_each_locus_from_parent(self):
        game = GameState.new(rng=random.Random(8))
        offspring = game.make_offspring("Aa", "Bb", "aa", "bb")
        self.assertIn(offspring.genotype[0], ("Aa", "aa"))
        self.assertEqual(offspring.genotype[1], "bb")
        self.assertEqual(offspring.color, GameState.color_for(offspring.genotype))

    def test_automatic_capture_and_breeding_follow_configured_intervals(self):
        game = GameState.new(rng=random.Random(3))
        game.advance(59)
        self.assertEqual(len(game.bottle), 0)
        game.advance(1)
        self.assertEqual(len(game.bottle), 1)
        game.advance(15)
        self.assertLessEqual(game.desktop_count, 9)

    def test_empty_desktop_refills_after_sixty_active_seconds(self):
        game = GameState.new(rng=random.Random(5))
        game.advance(15)
        game.catch(list(game.desktop))
        game.advance(59)
        self.assertEqual(game.desktop_count, 0)
        game.advance(1)
        self.assertEqual(game.desktop_count, 2)

    def test_empty_desktop_resumes_breeding_before_auto_capture(self):
        game = GameState.new(rng=random.Random(5))
        game.advance(15)
        game.catch(list(game.desktop))

        # The two deterministic refill insects are one female and one male.
        # Give them enough active time to breed before the next automatic catch.
        game.advance(90)

        self.assertEqual(game.desktop_count, 6)

    def test_unsuccessful_transaction_does_not_reset_capture_clock(self):
        game = GameState.new(rng=random.Random(5))
        game.advance(15)
        game.active_capture_seconds = 700
        self.assertEqual(game.sell("普通褐色", None, 1), [])
        self.assertEqual(game.release("普通褐色", None, 1), [])
        self.assertEqual(game.active_capture_seconds, 700)


if __name__ == "__main__":
    unittest.main()
