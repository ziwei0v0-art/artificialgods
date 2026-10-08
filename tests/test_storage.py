import json
import random
import tempfile
import unittest
from pathlib import Path

from tianmu_mvp.model import GameState
from tianmu_mvp.storage import load_state, save_state


class StorageTests(unittest.TestCase):
    def test_first_discovery_record_survives_sale_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            game = GameState.new(); game.advance(15)
            insect = next(iter(game.desktop.values()))
            game.catch([insect.id])
            game.sell(insect.color, None, 1)
            save_state(path, game)
            restored = load_state(path)
            record = getattr(restored, "discovery_dates", {}).get(insect.color)
            self.assertIsInstance(record, str)
            self.assertRegex(record, r"^\d{4}-\d{2}-\d{2}$")

    def test_corrupt_individuals_are_rejected_without_dropping_or_recoloring(self):
        for case in ("duplicate", "swapped_loci", "wrong_color"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                game = GameState.new(); game.advance(15)
                save_state(path, game)
                raw = json.loads(path.read_text())
                if case == "duplicate":
                    raw["desktop"].append(dict(raw["desktop"][0]))
                elif case == "swapped_loci":
                    raw["desktop"][0]["genotype"] = ["Bb", "Aa"]
                else:
                    raw["desktop"][0]["color"] = "白色"
                path.write_text(json.dumps(raw))
                original = path.read_bytes()
                with self.assertRaises(ValueError):
                    load_state(path)
                self.assertEqual(path.read_bytes(), original)

    def test_invalid_timer_state_is_rejected_at_load(self):
        for change in ({"status": "running", "deadline": None},
                       {"mode": "nonsense"}, {"work_seconds": -1},
                       {"deadline": float("nan")}, {"elapsed_seconds": "bad"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                save_state(path, GameState.new())
                raw = json.loads(path.read_text())
                raw["timer_session"].update(change)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    load_state(path)

    def test_legacy_save_without_timer_completion_marker_still_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, GameState.new(rng=random.Random(7)))
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw.pop("timer_completed")
            path.write_text(json.dumps(raw), encoding="utf-8")

            restored = load_state(path)

            self.assertFalse(restored.timer_completed)

    def test_timer_modes_round_trip_and_old_countdown_fields_migrate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            game = GameState.new()
            game.timer_session.start("pomodoro", now=100, minutes=None)
            game.timer_session.work_seconds = 12 * 60
            game.timer_session.deadline = 100 + 25 * 60
            game.timer_deadline = game.timer_session.deadline
            game.timer_remaining = game.timer_session.remaining_seconds
            save_state(path, game)
            restored = load_state(path)
            self.assertEqual(restored.timer_session.mode, "pomodoro")
            self.assertEqual(restored.timer_session.status, "running")
            self.assertEqual(restored.timer_session.work_seconds, 12 * 60)

            raw = json.loads(path.read_text(encoding="utf-8"))
            raw.pop("timer_session")
            raw["timer_deadline"] = 900.0
            raw["timer_remaining"] = 120
            raw["timer_completed"] = False
            path.write_text(json.dumps(raw), encoding="utf-8")
            legacy = load_state(path)
            self.assertEqual(legacy.timer_session.mode, "countdown")
            self.assertEqual(legacy.timer_session.deadline, 900.0)
            self.assertEqual(legacy.timer_session.status, "running")

    def test_save_and_load_preserves_individuals_economy_and_simulation_clock(self):
        game = GameState.new(rng=random.Random(9))
        game.advance(15)
        first = next(iter(game.desktop.values()))
        game.catch([first.id])
        game.coins = 13
        game.active_capture_seconds = 456

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, game)
            restored = load_state(path)

        self.assertEqual(restored.desktop, game.desktop)
        self.assertEqual(restored.bottle, game.bottle)
        self.assertEqual(restored.coins, 13)
        self.assertEqual(restored.active_capture_seconds, 456)
        self.assertEqual(restored.elapsed_seconds, game.elapsed_seconds)

    def test_missing_file_creates_fresh_state_but_corrupt_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.assertEqual(load_state(path).desktop_count, 0)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_state(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_second_save_keeps_previous_valid_state_as_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            first = GameState.new(rng=random.Random(1))
            first.coins = 4
            save_state(path, first)
            second = GameState.new(rng=random.Random(2))
            second.coins = 9
            save_state(path, second)
            self.assertEqual(load_state(path).coins, 9)
            self.assertEqual(load_state(Path(str(path) + ".bak")).coins, 4)


if __name__ == "__main__":
    unittest.main()
