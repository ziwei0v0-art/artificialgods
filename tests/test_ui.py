import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
import time
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from tianmu_mvp.model import GameState
from tianmu_mvp.storage import load_state
from tianmu_mvp.ui import TianmuApp


class FakeOverlay:
    def __init__(self):
        self.events = queue.Queue()
        self.sent = []
        self.available = True

    def send(self, kind, **values):
        self.sent.append((kind, values))
        return True


class NativeOverlayUIBridgeTests(unittest.TestCase):
    def test_invalid_timer_duration_does_not_start_or_crash(self):
        root = tk.Tk(); self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            app.timer_mode_var.set("倒计时"); app._choose_timer_mode()
            app.custom_minutes.set("not a duration")
            try:
                app._toggle_timer()
            except (ValueError, tk.TclError):
                self.fail("invalid text escaped the timer UI callback")
            self.assertEqual(app.timer_session.status, "idle")
            self.assertIn("分钟", app.status.get())

    def test_sale_confirmation_stays_in_page_and_freezes_selection(self):
        root = tk.Tk(); self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            game = GameState.new(); game.advance(15)
            first, second = list(game.desktop.values())[:2]
            game.catch([first.id])
            app = TianmuApp(root, game, Path(directory) / "state.json", enable_native_overlay=False)
            with patch("tianmu_mvp.ui.messagebox.askyesno", return_value=False) as modal:
                app._sell()
            self.assertFalse(modal.called, "sale confirmation must not open a modal")
            self.assertIn(first.id, game.bottle)
            game.catch([second.id])
            app._confirm_sale()
            self.assertNotIn(first.id, game.bottle)
            self.assertIn(second.id, game.bottle)
            self.assertEqual(game.coins, 1)

    def test_daily_sign_history_survives_next_day_and_restart(self):
        root = tk.Tk(); self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            game = GameState.new()
            app = TianmuApp(root, game, path, enable_native_overlay=False)
            import datetime
            with patch("tianmu_mvp.ui.datetime") as dates:
                dates.date.today.return_value = datetime.date(2026, 9, 25)
                dates.datetime.now.return_value = datetime.datetime(2026, 9, 25, 12)
                app._draw_sign()
                first = app.game.daily_sign
                app._draw_sign()
                dates.date.today.return_value = datetime.date(2026, 9, 26)
                dates.datetime.now.return_value = datetime.datetime(2026, 9, 26, 12)
                app._draw_sign()
            restored = load_state(path)
            history = getattr(restored, "sign_history", {})
            self.assertEqual(history.get("2026-09-25"), first)
            self.assertEqual(history.get("2026-09-26"), restored.daily_sign)

    def test_four_pages_include_scene_and_daily_sign_together(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            labels = [app.notebook.tab(tab, "text") for tab in app.notebook.tabs()]
            self.assertEqual(labels, ["神前", "虫瓶", "装扮", "虫谱"])
            self.assertTrue(str(app.scene).startswith(str(app.pages["神前"])))
            self.assertTrue(str(app.sign_text).startswith(str(app.pages["神前"])))

    def test_failed_transaction_save_restores_inventory_and_money(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            game = GameState.new(); game.advance(15)
            insect = next(iter(game.desktop.values()))
            game.catch([insect.id]); game.coins = 17
            app = TianmuApp(root, game, path, enable_native_overlay=False)
            app._save()
            original = path.read_bytes()
            app.selected_color.set(insect.color)
            with patch("tianmu_mvp.ui.messagebox.askyesno", return_value=True), patch("tianmu_mvp.ui.save_state", side_effect=OSError("disk full")):
                try:
                    app._sell()
                    app._confirm_sale()
                except OSError:
                    self.fail("save failure escaped the transaction without recovery")
            self.assertIn(insect.id, app.game.bottle)
            self.assertEqual(app.game.coins, 17)
            self.assertNotIn(insect.id, app.game.sold_ids)
            self.assertIn("保存失败", app.status.get())
            self.assertEqual(path.read_bytes(), original)

    def test_changing_page_cancels_pending_capture(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            app._toggle_capture()
            app.notebook.select(app.pages["虫瓶"])
            app._tab_changed()
            self.assertFalse(app.capture_mode)
            self.assertIsNone(app.drag_start)

    def test_hidden_app_keeps_active_simulation_without_offline_catchup(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            root.withdraw()
            app._last_tick_at = 100
            with patch("tianmu_mvp.ui.time.monotonic", return_value=101):
                app._tick()
            self.assertEqual(app.game.elapsed_seconds, 1)
            with patch("tianmu_mvp.ui.time.monotonic", return_value=1001):
                app._tick()
            self.assertEqual(app.game.elapsed_seconds, 1)

    def test_timer_window_switches_modes_and_collapses_without_stopping(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            app._open_timer()
            root.update()
            self.assertEqual(app._timer_window.title(), "专注计时")
            self.assertRegex(app._timer_label.cget("text"), r"^\d{2}:\d{2}:\d{2}")

            app.timer_mode_var.set("番茄钟")
            app.work_minutes.set(1)
            app.break_minutes.set(1)
            app._choose_timer_mode()
            app._toggle_timer()
            self.assertEqual(app.timer_session.status, "running")
            deadline = app.timer_session.deadline
            app._collapse_timer()
            self.assertTrue(app._timer_compact)
            self.assertTrue(app._timer_window.winfo_exists())
            self.assertEqual(app.timer_session.status, "running")
            self.assertEqual(app.timer_session.deadline, deadline)

            app._hide_timer()
            self.assertEqual(app.timer_session.status, "running")
            app._open_timer()
            root.update()
            self.assertEqual(app.timer_session.status, "running")
            root.destroy()

    def test_tick_refreshes_bottle_and_codex_only_when_their_tab_is_selected(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            scene = Mock()
            bottle = Mock()
            codex = Mock()
            app._render_scene = scene
            app._render_bottle = bottle
            app._render_codex = codex

            app._render_selected_dynamic_page()
            scene.assert_called_once_with()
            bottle.assert_not_called()
            codex.assert_not_called()

            app.notebook.select(app.pages["虫瓶"])
            app._render_selected_dynamic_page()
            scene.assert_called_once_with()
            bottle.assert_called_once_with()
            codex.assert_not_called()

            app.notebook.select(app.pages["虫谱"])
            app._render_selected_dynamic_page()
            self.assertEqual(bottle.call_count, 1)
            codex.assert_called_once_with()

            root.withdraw()
            app.notebook.select(app.pages["神前"])
            app._render_selected_dynamic_page()
            scene.assert_called_once_with()
            root.destroy()

    def test_panel_capture_stays_in_the_panel_and_never_enables_native_interception(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            game = GameState.new()
            game.advance(15)
            app = TianmuApp(root, game, Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            overlay = FakeOverlay()
            app.overlay = overlay
            app.native_overlay = True
            insect = next(iter(game.desktop.values()))
            x, y = app.insect_positions[insect.id]

            app._toggle_capture()
            self.assertNotIn(("mode", {"mode": "capture"}), overlay.sent)
            app._start_net_drag(SimpleNamespace(x=int(x - 10), y=int(y - 8)))
            app._finish_net_drag(SimpleNamespace(x=int(x + 10), y=int(y + 8)))

            self.assertIn(insect.id, game.bottle)
            self.assertFalse(app.capture_mode)
            self.assertFalse(any(kind == "mode" for kind, _ in overlay.sent))
            root.destroy()

    def test_panel_capture_cancels_when_panel_loses_focus(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            overlay = FakeOverlay()
            app.overlay = overlay
            app.native_overlay = True

            app._toggle_capture()
            app._focus_out()

            self.assertFalse(app.capture_mode)
            self.assertFalse(any(kind == "mode" for kind, _ in overlay.sent))
            root.destroy()

    def test_closing_panel_keeps_explicitly_hidden_overlay_hidden(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            overlay = FakeOverlay()
            app.overlay = overlay
            app.native_overlay = True
            app.overlay_visible = False
            app.overlay_requested_visible = False

            app.close()

            self.assertNotIn(("show", {}), overlay.sent)
            self.assertEqual(root.state(), "withdrawn")
            root.destroy()

    def test_closing_initial_panel_shows_overlay_requested_by_default(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            app = TianmuApp(root, GameState.new(), Path(directory) / "state.json", enable_native_overlay=False)
            overlay = FakeOverlay()
            app.overlay = overlay
            app.native_overlay = True
            app.overlay_visible = False
            app.overlay_requested_visible = True

            app.close()

            self.assertIn(("show", {}), overlay.sent)
            root.destroy()

    def test_native_capture_event_moves_same_insect_into_bottle(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            game = GameState.new()
            game.advance(15)
            app = TianmuApp(root, game, Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            overlay = FakeOverlay()
            app.overlay = overlay
            app.native_overlay = True
            insect = next(iter(game.desktop.values()))
            overlay.events.put({"type": "capture", "ids": [insect.id]})
            app._poll_overlay()
            self.assertNotIn(insect.id, game.desktop)
            self.assertIs(game.bottle[insect.id], insect)
            self.assertIn(("mode", {"mode": "passthrough"}), overlay.sent)
            self.assertEqual(app.status.get(), "手动捕获 1 只；鼠标穿透已恢复。")
            self.assertIn(insect.id, load_state(Path(directory) / "state.json").bottle)
            root.destroy()

    def test_timer_expiry_is_handled_even_when_timer_window_is_closed(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            app = TianmuApp(root, GameState.new(), path, enable_native_overlay=False)
            root.bell = Mock()
            app.timer_session.mode = "countdown"
            app.game.timer_deadline = time.time() - 1
            app._refresh_timer()
            self.assertIsNone(app.game.timer_deadline)
            self.assertEqual(app.game.timer_remaining, 0)
            self.assertEqual(app.status.get(), "倒计时结束。")
            root.bell.assert_called_once()
            saved_game = load_state(path)
            self.assertIsNone(saved_game.timer_deadline)
            self.assertTrue(saved_game.timer_completed)
            app.game = saved_game
            app._open_timer()
            self.assertEqual(app._timer_label.cget("text"), "已结束")
            root.destroy()

    def test_sale_requires_confirmation_and_reports_fixed_count_and_total(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            game = GameState.new()
            game.advance(15)
            insect = next(iter(game.desktop.values()))
            game.catch([insect.id])
            app = TianmuApp(root, game, Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            app.selected_color.set(insect.color)
            app.selected_sex.set("雌" if insect.sex == "F" else "雄")
            app.selected_count.set(1)
            expected_total = game.prices[insect.color]

            app._sell()
            self.assertIn(insect.id, game.bottle)
            self.assertEqual(app.pending_sale, ([insect.id], expected_total))
            app._confirm_sale()

            self.assertIn(insect.id, game.sold_ids)
            self.assertEqual(game.coins, expected_total)
            root.destroy()

    def test_cancel_sale_keeps_insect_coins_and_capture_clock_unchanged(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            game = GameState.new()
            game.advance(15)
            insect = next(iter(game.desktop.values()))
            game.catch([insect.id])
            game.coins = 17
            capture_seconds = game.active_capture_seconds
            app = TianmuApp(root, game, Path(directory) / "state.json", enable_native_overlay=False)
            root.update()
            app.selected_color.set(insect.color)
            app.selected_sex.set("雌" if insect.sex == "F" else "雄")
            app.selected_count.set(1)

            app._sell()
            app._cancel_sale()

            self.assertIn(insect.id, game.bottle)
            self.assertNotIn(insect.id, game.sold_ids)
            self.assertEqual(game.coins, 17)
            self.assertEqual(game.active_capture_seconds, capture_seconds)
            root.destroy()

    def test_shop_buttons_purchase_place_and_restore_saved_decoration(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: {0}".format(error))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            game = GameState.new()
            game.coins = 12
            app = TianmuApp(root, game, path, enable_native_overlay=False)
            root.update()

            buttons = [child for child in app.shop_body.winfo_children()[1].winfo_children()
                       if isinstance(child, ttk.Button)]
            self.assertEqual(buttons[0].cget("text"), "购买")
            buttons[0].invoke()
            self.assertEqual(game.coins, 0)
            self.assertIn("offering_plate", game.owned_items)
            self.assertIn("已购买素色供盘", app.status.get())
            self.assertEqual(load_state(path).coins, 0)

            buttons = [child for child in app.shop_body.winfo_children()[1].winfo_children()
                       if isinstance(child, ttk.Button)]
            self.assertEqual(buttons[0].cget("text"), "摆上")
            buttons[0].invoke()
            self.assertEqual(game.placed_item, "offering_plate")
            self.assertIn("供盘状态已更新", app.status.get())
            restored = load_state(path)
            self.assertEqual(restored.placed_item, "offering_plate")
            self.assertEqual(restored.coins, 0)

            buttons = [child for child in app.shop_body.winfo_children()[1].winfo_children()
                       if isinstance(child, ttk.Button)]
            buttons[0].invoke()
            self.assertIsNone(game.placed_item)
            self.assertEqual(game.coins, 0)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
