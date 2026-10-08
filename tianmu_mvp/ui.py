"""Tkinter presentation and input layer for the local playable MVP."""

import copy
import datetime
import math
from pathlib import Path
import queue
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, ttk
from zoneinfo import ZoneInfo

from .drawing import draw_daoist, draw_shrine
from .clock import consume_active_delta
from .model import COLORS, SHOP
from .storage import save_state
from .native_overlay import NativeOverlay


from .content import SIGN_TEXTS


COLOR_HEX = {
    "普通褐色": "#9b6540",
    "中褐色": "#b98658",
    "深褐色": "#51453e",
    "白色": "#efe9dd",
}


class TianmuApp:
    def __init__(self, root, game, save_path, enable_native_overlay=True):
        self.root = root
        self.game = game
        self.save_path = save_path
        self.status = tk.StringVar(value="第一轮可玩原型 · 角色与场景为程序绘制占位")
        self.capture_mode = False
        self.native_capture_active = False
        self.drag_start = None
        self.drag_rect = None
        self.insect_positions = {}
        self.selected_color = tk.StringVar(value=COLORS[0])
        self.selected_sex = tk.StringVar(value="全部")
        self.selected_count = tk.IntVar(value=1)
        self.pending_sale = None
        self._last_save_at = 0
        self._last_tick_at = time.monotonic()
        self._active_tick_fraction = 0.0
        self._timer_window = None
        self._timer_label = None
        self._timer_body = None
        self._timer_compact = False
        self.timer_session = self.game.timer_session
        self.timer_mode_var = tk.StringVar(value=self._timer_mode_label(self.timer_session.mode))
        self.timer_status_var = tk.StringVar(value="")
        self.timer_zone_var = tk.StringVar(value="北京时间" if self.timer_session.clock_timezone == "Asia/Shanghai" else "本地时间")
        self.timer_traditional_var = tk.BooleanVar(value=self.timer_session.show_traditional)
        self.timer_sound_var = tk.BooleanVar(value=self.timer_session.sound_enabled)
        self.timer_widget_var = tk.BooleanVar(value=self.timer_session.widget_enabled)
        self.custom_minutes = tk.IntVar(value=max(1, self.timer_session.countdown_seconds // 60))
        self.work_minutes = tk.IntVar(value=max(1, self.timer_session.work_seconds // 60))
        self.break_minutes = tk.IntVar(value=max(1, self.timer_session.break_seconds // 60))
        self.overlay = NativeOverlay(Path(__file__).resolve().parents[1])
        self.native_overlay = False
        self.overlay_visible = True
        self.overlay_requested_visible = True
        if enable_native_overlay:
            try:
                self.native_overlay = self.overlay.start()
            except (OSError, subprocess.SubprocessError) as error:
                self.status.set("桌面图层未启动，当前为窗口模式：{0}".format(error))

        root.title("天姥 · 桌角小庙（可玩原型）")
        root.geometry("980x710")
        root.minsize(820, 620)
        root.configure(background="#f4efe5")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._build_shell()
        root.bind("<Escape>", self._escape)
        root.bind("<FocusOut>", self._focus_out)
        self._render_scene()
        self._render_bottle()
        self._render_shop()
        self._render_codex()
        self._update_status()
        root.after(1000, self._tick)
        if self.native_overlay:
            self.overlay_visible = False
            self.overlay.send("hide")

    def _style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f4efe5")
        style.configure("TLabel", background="#f4efe5", foreground="#302b27", font=("Helvetica", 12))
        style.configure("Title.TLabel", font=("Helvetica", 20, "bold"), foreground="#322b25")
        style.configure("Subtle.TLabel", foreground="#746b61", font=("Helvetica", 10))
        style.configure("TButton", padding=(12, 7), font=("Helvetica", 11))
        style.configure("Accent.TButton", padding=(13, 8), font=("Helvetica", 11, "bold"))
        style.configure("TNotebook", background="#f4efe5", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), font=("Helvetica", 11))

    def _build_shell(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="天姥", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="神龛桌宠 · 本地可玩原型", style="Subtle.TLabel").pack(side="left", padx=(12, 0), pady=(7, 0))
        tools = ttk.Frame(header)
        tools.pack(side="right")
        ttk.Button(tools, text="⏱ 计时", command=self._open_timer).pack(side="left", padx=4)
        self.net_button = ttk.Button(tools, text="🕸 开始拉网", command=self._toggle_capture)
        self.net_button.pack(side="left", padx=4)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self.pages = {}
        for name in ("神前", "虫瓶", "装扮", "虫谱"):
            page = ttk.Frame(self.notebook, padding=14)
            self.notebook.add(page, text=name)
            self.pages[name] = page
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status).pack(side="left", fill="x", expand=True)
        self.counter = ttk.Label(footer, style="Subtle.TLabel")
        self.counter.pack(side="right")
        self._build_home()
        self._build_shrine()
        self._build_bottle()
        self._build_shop()
        self._build_codex()

    def _build_home(self):
        container = self.pages["神前"]
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(0, weight=1)
        page = ttk.Frame(container, padding=(0, 0, 18, 0))
        page.grid(row=0, column=0, sticky="nsew")
        self.shrine_side = ttk.Frame(container, padding=(18, 0, 0, 0))
        self.shrine_side.grid(row=0, column=1, sticky="nsew")
        ttk.Label(page, text="小庙日常", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="供果招虫 · 抓放选育 · 添置陈设", style="Subtle.TLabel").pack(anchor="w", pady=(2, 10))
        self.scene = tk.Canvas(page, height=385, background="#e8dfd0", highlightthickness=0)
        self.scene.pack(fill="both", expand=True)
        self.scene.bind("<Configure>", lambda event: self._render_scene())
        self.scene.bind("<ButtonPress-1>", self._start_net_drag)
        self.scene.bind("<ButtonRelease-1>", self._finish_net_drag)
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="开启拉网后拖框，松手捕获，Esc 取消。", wraplength=270,
                  style="Subtle.TLabel").pack(side="left")
        ttk.Button(row, text="打开虫瓶", command=lambda: self.notebook.select(self.pages["虫瓶"])).pack(side="right")

    def _build_shrine(self):
        page = self.shrine_side
        ttk.Label(page, text="今日签", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="每日一签固定保存；求签不花铜钱。", style="Subtle.TLabel").pack(anchor="w", pady=(3, 16))
        self.sign_text = ttk.Label(page, text="今天还没有求签。", font=("Georgia", 19), wraplength=285, justify="left")
        self.sign_text.pack(anchor="w", pady=(20, 8))
        self.sign_explanation = ttk.Label(page, text="", wraplength=285, justify="left")
        self.sign_explanation.pack(anchor="w", pady=(8, 20))
        ttk.Button(page, text="上香并求今日签", style="Accent.TButton", command=self._draw_sign).pack(anchor="w", pady=8)
        ttk.Label(page, text="历日签簿 · 游戏原创签文", style="Subtle.TLabel").pack(anchor="w", pady=(20, 6))
        self.sign_history_var = tk.StringVar(value="今日")
        self.sign_history_box = ttk.Combobox(page, textvariable=self.sign_history_var, state="readonly", width=22)
        self.sign_history_box.pack(anchor="w")
        self.sign_history_box.bind("<<ComboboxSelected>>", lambda event: self._render_sign())

    def _build_bottle(self):
        page = self.pages["虫瓶"]
        ttk.Label(page, text="虫瓶", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="瓶内个体保留原编号、性别、体色与基因；放回的是原个体。", style="Subtle.TLabel").pack(anchor="w", pady=(3, 14))
        self.bottle_summary = ttk.Frame(page)
        self.bottle_summary.pack(fill="x", anchor="w")
        controls = ttk.LabelFrame(page, text="选择一批", padding=12)
        controls.pack(fill="x", pady=16)
        ttk.Label(controls, text="体色").grid(row=0, column=0, sticky="w", padx=4)
        color_box = ttk.Combobox(controls, textvariable=self.selected_color, values=COLORS, state="readonly", width=15)
        color_box.grid(row=0, column=1, padx=4)
        color_box.bind("<<ComboboxSelected>>", lambda event: self._render_bottle())
        ttk.Label(controls, text="性别").grid(row=0, column=2, sticky="w", padx=(14, 4))
        sex_box = ttk.Combobox(controls, textvariable=self.selected_sex, values=("全部", "雌", "雄"), state="readonly", width=8)
        sex_box.grid(row=0, column=3, padx=4)
        sex_box.bind("<<ComboboxSelected>>", lambda event: self._render_bottle())
        ttk.Label(controls, text="数量").grid(row=0, column=4, sticky="w", padx=(14, 4))
        self.count_spin = ttk.Spinbox(controls, from_=1, to=999, textvariable=self.selected_count, width=6)
        self.count_spin.grid(row=0, column=5, padx=4)
        actions = ttk.Frame(page)
        actions.pack(fill="x")
        self.release_button = ttk.Button(actions, text="放回桌面", command=self._release)
        self.release_button.pack(side="left")
        self.sale_button = ttk.Button(actions, text="出售所选", command=self._sell)
        self.sale_button.pack(side="left", padx=8)
        ttk.Label(actions, text="铜钱按体色结算；查看和零数量操作不会重置 24 小时积攒。", style="Subtle.TLabel").pack(side="left", padx=12)

        self.sale_confirmation = ttk.Frame(page, padding=(0, 16))
        self.sale_confirmation.pack(fill="x")
        self.selected_count.trace_add("write", lambda *_: self._update_bottle_actions())

    def _build_shop(self):
        page = self.pages["装扮"]
        ttk.Label(page, text="装扮", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="先购买永久拥有，再摆上或换回。预览不扣钱。", style="Subtle.TLabel").pack(anchor="w", pady=(3, 16))
        self.shop_selection = tk.StringVar(value=SHOP["offering_plate"]["name"])
        selector = ttk.Combobox(page, textvariable=self.shop_selection, values=[item["name"] for item in SHOP.values()], state="readonly", width=24)
        selector.pack(anchor="w", pady=(0, 12))
        selector.bind("<<ComboboxSelected>>", lambda event: self._render_shop())
        self.shop_body = ttk.Frame(page)
        self.shop_body.pack(fill="x", anchor="w")
        self.decor_scene = tk.Canvas(page, height=260, background="#e8dfd0", highlightthickness=0)
        self.decor_scene.pack(fill="x", expand=True, pady=16)

    def _build_codex(self):
        page = self.pages["虫谱"]
        ttk.Label(page, text="虫谱", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="第一次捕获某种体色后记录；出售或放回不抹去发现。", style="Subtle.TLabel").pack(anchor="w", pady=(3, 14))
        self.codex_body = ttk.Frame(page)
        self.codex_body.pack(fill="x", anchor="w")

    def _tab_changed(self, _event=None):
        if self.capture_mode:
            self._escape()
        if self.pending_sale is not None:
            self._cancel_sale()
        current = self.notebook.tab(self.notebook.select(), "text")
        self.net_button.configure(state="normal" if current == "神前" else "disabled")
        if current == "神前":
            self._render_scene()
            self._render_sign()
        elif current == "虫瓶":
            self._render_bottle()
        elif current == "装扮":
            self._render_shop()
        elif current == "虫谱":
            self._render_codex()

    def _render_selected_dynamic_page(self):
        """Refresh only visible pages whose content changes during simulation."""
        if not self.root.winfo_viewable():
            return
        current = self.notebook.tab(self.notebook.select(), "text")
        if current == "神前":
            self._render_scene()
            self._render_sign()
        elif current == "虫瓶":
            self._render_bottle()
        elif current == "虫谱":
            self._render_codex()

    def _render_scene(self):
        if not hasattr(self, "scene") or not self.scene.winfo_exists():
            return
        canvas = self.scene
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.create_rectangle(0, 0, width, height, fill="#e8dfd0", outline="")
        canvas.create_oval(width*0.05, height*0.03, width*0.32, height*0.75,
                           fill="#efe8dc", outline="")
        shrine_x, floor_y = width * 0.25, height * 0.67
        draw_shrine(canvas, shrine_x, floor_y, 0.72, self.game.placed_item == "offering_plate")
        dao_x, dao_y = width * 0.56, floor_y + 20
        draw_daoist(canvas, dao_x, dao_y, 0.86, math.sin(self.game.elapsed_seconds / 2.4))
        canvas.create_text(shrine_x, height*0.88, text="六臂泥像 · 静态图标占位", fill="#5b5044", font=("Helvetica", 10))
        canvas.create_text(dao_x, height*0.88, text="道童 · 临时程序绘制", fill="#5b5044", font=("Helvetica", 10))
        self.insect_positions = {}
        for index, insect in enumerate(self.game.desktop.values()):
            drift = math.sin(self.game.elapsed_seconds * 1.2 + index * 2.3) * 5
            x = width * insect.x + drift
            y = height * insect.y + math.cos(self.game.elapsed_seconds + index) * 4
            color = COLOR_HEX[insect.color]
            canvas.create_oval(x-8, y-6, x+8, y+6, fill=color, outline="#655444", width=1)
            canvas.create_oval(x-3, y-2, x-1, y, fill="#332b25", outline="")
            canvas.create_line(x+5, y-3, x+10, y-7, fill="#655444", width=1)
            self.insect_positions[insect.id] = (x, y)
        canvas.create_text(width-18, 18, text="可玩原型 · {0}".format("桌面图层" if self.native_overlay else "窗口模式"),
                           anchor="ne", fill="#71695e", font=("Helvetica", 10))

    def _start_net_drag(self, event):
        if not self.capture_mode:
            return
        self.drag_start = (event.x, event.y)
        if self.drag_rect:
            self.scene.delete(self.drag_rect)
        self.drag_rect = self.scene.create_rectangle(event.x, event.y, event.x, event.y,
                                                     outline="#b8423d", width=2, dash=(5, 3))

    def _finish_net_drag(self, event):
        if not self.capture_mode or not self.drag_start:
            return
        x1, y1 = self.drag_start
        x2, y2 = event.x, event.y
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        hits = [bug_id for bug_id, (x, y) in self.insect_positions.items()
                if left <= x <= right and top <= y <= bottom]
        caught = self._change(lambda: self.game.catch(hits))
        self.capture_mode = False
        if self.native_capture_active:
            self.overlay.send("mode", mode="passthrough")
        self.native_capture_active = False
        self.drag_start = None
        self.drag_rect = None
        self.net_button.configure(text="🕸 开始拉网")
        if caught is not None:
            self._after_change("手动捕获 {0} 只。".format(len(caught)) if caught else "没有框中虫，捕捉结束；鼠标已恢复。")

    def _toggle_capture(self):
        self.capture_mode = not self.capture_mode
        self.drag_start = None
        self.net_button.configure(text="取消拉网" if self.capture_mode else "🕸 开始拉网")
        self.status.set("拖出网框；松手结束，Esc 取消。" if self.capture_mode else "已退出拉网模式。")
        if self.native_overlay and not self.root.winfo_viewable():
            self.native_capture_active = self.capture_mode
            self.overlay.send("mode", mode="capture" if self.capture_mode else "passthrough")

    def _escape(self, _event=None):
        if self.capture_mode:
            self.capture_mode = False
            self.drag_start = None
            if self.drag_rect:
                self.scene.delete(self.drag_rect)
                self.drag_rect = None
            self.net_button.configure(text="🕸 开始拉网")
            self.status.set("已取消拉网，鼠标操作恢复。")
            if self.native_capture_active:
                self.overlay.send("mode", mode="passthrough")
            self.native_capture_active = False

    def _focus_out(self, _event=None):
        if self.capture_mode and not self.native_capture_active:
            self._escape()

    def _render_bottle(self):
        if not hasattr(self, "bottle_summary"):
            return
        for child in self.bottle_summary.winfo_children():
            child.destroy()
        ttk.Label(self.bottle_summary, text="当前总量：{0} 只　·　铜钱：{1}　·　自动捕捉：{2}".format(
            len(self.game.bottle), self.game.coins,
            "已达 24 小时上限（手动仍可用）" if self.game.auto_capture_paused else "运行中"
        ), style="Subtle.TLabel").pack(anchor="w", pady=(0, 10))
        for color in COLORS:
            group = [bug for bug in self.game.bottle.values() if bug.color == color]
            females = sum(bug.sex == "F" for bug in group)
            males = len(group) - females
            ttk.Label(self.bottle_summary, text="{0}　{1} 只（雌 {2} / 雄 {3}）　出售价 {4} 铜钱/只".format(
                color, len(group), females, males, self.game.prices[color]
            )).pack(anchor="w", pady=3)

        self._update_bottle_actions()

    def _update_bottle_actions(self):
        ids, amount = self.game.quote_sale(self.selected_color.get(), self._selected_sex(), self._safe_count())
        self.release_button.configure(state="normal" if ids and self.pending_sale is None else "disabled")
        self.sale_button.configure(state="normal" if ids and self.pending_sale is None else "disabled",
                                   text="出售 {0} 只 · {1} 铜钱".format(len(ids), amount))

    def _render_shop(self):
        if not hasattr(self, "shop_body"):
            return
        for child in self.shop_body.winfo_children():
            child.destroy()
        item_id = self._selected_shop_item()
        item = SHOP[item_id]
        owned = item_id in self.game.owned_items
        placed = self.game.placed_items.get(item["slot"]) == item_id
        state = "使用中" if placed else "已拥有" if owned else "价格 {0} 铜钱".format(item["price"])
        ttk.Label(self.shop_body, text="{0} · {1}".format(item["name"], state), font=("Helvetica", 14, "bold")).pack(anchor="w", pady=5)
        row = ttk.Frame(self.shop_body)
        row.pack(anchor="w")
        if not owned:
            missing = max(0, item["price"] - self.game.coins)
            ttk.Button(row, text="购买", command=self._buy_plate, state="disabled" if missing else "normal").pack(side="left", padx=(0, 8))
            ttk.Label(row, text="还差 {0} 铜钱".format(missing) if missing else "购买后永久拥有", style="Subtle.TLabel").pack(side="left")
        else:
            ttk.Button(row, text="换回初始外观" if placed else "摆上", command=self._place_plate).pack(side="left", padx=(0, 8))
            ttk.Label(row, text="旧物件仍保留，可随时换回。", style="Subtle.TLabel").pack(side="left")
        self.decor_scene.delete("all")
        draw_shrine(self.decor_scene, 190, 208, 0.85, item_id == "offering_plate" or self.game.placed_item == "offering_plate")
        self.decor_scene.create_text(400, 90, anchor="w", text="预览 · " + item["name"], fill="#5b5044", font=("Helvetica", 15, "bold"))
        self.decor_scene.create_text(400, 125, anchor="w", width=280,
            text="只改变陈设与生活表现，不提高效率或容量。\n正式物件图待 Chat 交付，当前预览仍为占位。", fill="#71695e", font=("Helvetica", 11))

    def _selected_shop_item(self):
        return next((key for key, item in SHOP.items() if item["name"] == self.shop_selection.get()), "offering_plate")

    def _render_codex(self):
        if not hasattr(self, "codex_body"):
            return
        for child in self.codex_body.winfo_children():
            child.destroy()
        for color in COLORS:
            found = color in self.game.discovered_colors
            ttk.Label(self.codex_body, text="{0}　{1}".format(color, "已发现" if found else "尚未发现"),
                      foreground="#423a31" if found else "#8a8278").pack(anchor="w", pady=(12, 3))
            if found:
                date = self.game.discovery_dates.get(color, "旧存档未记录日期")
                ttk.Label(self.codex_body, text="首次发现：{0} · {1}".format(date, {
                    "普通褐色": "常见的褐色，是抓放选育的起点。",
                    "中褐色": "温暖的中褐色，可放回雌雄个体参与繁殖。",
                    "深褐色": "深色体表，与另外三种体色属于同一物种。",
                    "白色": "浅白体表；出售或放回不会清除发现记录。",
                }[color]), wraplength=680, style="Subtle.TLabel").pack(anchor="w")

    def _draw_sign(self):
        today = datetime.datetime.now(ZoneInfo(self.game.game_timezone)).date().isoformat()
        self.sign_history_var.set("今日")
        if self.game.daily_sign_date == today and self.game.daily_sign:
            self.status.set("今天已经求过签，仍是同一支。")
            self._render_sign()
            return
        index = sum(ord(character) for character in today) % len(SIGN_TEXTS)
        def assign_sign():
            self.game.daily_sign_date = today
            self.game.daily_sign = self.game.sign_history.setdefault(today, str(index))
            return True
        if not self._change(assign_sign):
            return
        self._after_change("已保存今日签；今天再次查看结果不变。")
        self._render_sign()

    def _render_sign(self):
        if not hasattr(self, "sign_text"):
            return
        today = datetime.datetime.now(ZoneInfo(self.game.game_timezone)).date().isoformat()
        self.sign_history_box.configure(values=["今日"] + sorted(self.game.sign_history, reverse=True))
        selected = self.sign_history_var.get()
        date = today if selected == "今日" else selected
        index = self.game.sign_history.get(date)
        if index is None:
            self.sign_text.configure(text="今天还没有求签。")
            self.sign_explanation.configure(text="上香求一支今日签；同一天结果保持不变。")
            return
        verse, meaning = SIGN_TEXTS[int(index)]
        self.sign_text.configure(text=verse)
        self.sign_explanation.configure(text=meaning)

    def _selected_sex(self):
        value = self.selected_sex.get()
        return {"全部": None, "雌": "F", "雄": "M"}.get(value)

    def _safe_count(self):
        try:
            return max(0, int(self.selected_count.get()))
        except (ValueError, tk.TclError):
            return 0

    def _release(self):
        selected = self._change(lambda: self.game.release(self.selected_color.get(), self._selected_sex(), self._safe_count()))
        if selected:
            self._after_change("已放回 {0} 只原个体，自动积攒重新开始。".format(len(selected)))
        elif selected is not None:
            self.status.set("所选条件下没有可放回的虫。")

    def _sell(self):
        selected_ids, amount = self.game.quote_sale(
            self.selected_color.get(), self._selected_sex(), self._safe_count()
        )
        if not selected_ids:
            self.status.set("所选条件下没有可出售的虫。")
            return
        self.pending_sale = (selected_ids, amount)
        for child in self.sale_confirmation.winfo_children():
            child.destroy()
        ttk.Label(self.sale_confirmation, text="出售 {0} 只，到账 {1} 铜钱？".format(len(selected_ids), amount)).pack(side="left")
        ttk.Button(self.sale_confirmation, text="确认出售", command=self._confirm_sale).pack(side="left", padx=8)
        ttk.Button(self.sale_confirmation, text="取消", command=self._cancel_sale).pack(side="left")
        self._update_bottle_actions()

    def _cancel_sale(self):
        self.pending_sale = None
        for child in self.sale_confirmation.winfo_children():
            child.destroy()
        self.status.set("已取消出售；库存、铜钱与积攒进度均未改变。")
        self._update_bottle_actions()

    def _confirm_sale(self):
        if self.pending_sale is None:
            return
        selected_ids, amount = self.pending_sale
        self.pending_sale = None
        for child in self.sale_confirmation.winfo_children():
            child.destroy()
        selected = self._change(lambda: self.game.sell_ids(selected_ids))
        if selected:
            self._after_change("已出售 {0} 只，到账 {1} 铜钱；其余库存保留。".format(len(selected), amount))
        elif selected is not None:
            self.status.set("这批虫的库存已变化，请重新选择；没有扣除库存。")
        self._update_bottle_actions()

    def _buy_plate(self):
        item_id = self._selected_shop_item()
        purchased = self._change(lambda: self.game.buy(item_id))
        if purchased is None:
            return
        if not purchased:
            self.status.set("余额不足或该物件已拥有；没有扣款。")
            return
        self._after_change("已购买{0}，可再选择摆上。".format(SHOP[item_id]["name"]))

    def _place_plate(self):
        item_id = self._selected_shop_item()
        if self._change(lambda: self.game.place(item_id)):
            self._after_change("{0}状态已更新，没有重复扣款。".format(SHOP[item_id]["name"]))

    def _change(self, action):
        """Persist a mutation before reporting success, or restore its prior state."""
        before = copy.deepcopy(self.game)
        result = action()
        if not self._save():
            self.game.__dict__.clear()
            self.game.__dict__.update(before.__dict__)
            self.timer_session = self.game.timer_session
            self.status.set("保存失败，本次操作已撤回；请检查磁盘后重试。")
            return None
        return result

    def _after_change(self, message):
        self.status.set(message)
        self._render_scene()
        self._render_bottle()
        self._render_shop()
        self._render_codex()
        self._update_status()

    def _update_status(self):
        self.counter.configure(text="桌面 {0} 只　·　虫瓶 {1} 只　·　铜钱 {2}".format(
            len(self.game.desktop), len(self.game.bottle), self.game.coins
        ))
        self._render_sign()

    def _open_timer(self):
        if self._timer_window and self._timer_window.winfo_exists():
            self._timer_window.deiconify()
            self._timer_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._timer_window = window
        window.title("专注计时")
        window.minsize(280, 220)
        window.geometry("430x500")
        window.protocol("WM_DELETE_WINDOW", self._hide_timer)
        self._timer_body = ttk.Frame(window, padding=18)
        self._timer_body.pack(fill="both", expand=True)
        self._render_timer_window()
        self._refresh_timer()

    @staticmethod
    def _timer_mode_label(mode):
        return {"clock": "时钟", "countdown": "倒计时", "stopwatch": "正计时", "pomodoro": "番茄钟"}.get(mode, "倒计时")

    def _render_timer_window(self):
        if not self._timer_body or not self._timer_body.winfo_exists():
            return
        for child in self._timer_body.winfo_children():
            child.destroy()
        title = "专注计时 · {0}".format(self._timer_mode_label(self.timer_session.mode))
        ttk.Label(self._timer_body, text=title, style="Title.TLabel").pack(anchor="w")
        self._timer_label = ttk.Label(self._timer_body, text="尚未开始", font=("Helvetica", 28, "bold"))
        self._timer_label.pack(anchor="center", pady=(18, 2))
        self.timer_status_var.set(self._timer_status_text())
        ttk.Label(self._timer_body, textvariable=self.timer_status_var, style="Subtle.TLabel").pack(anchor="center", pady=(0, 14))
        actions = ttk.Frame(self._timer_body)
        actions.pack(anchor="center", pady=(4, 10))
        if self.timer_session.mode != "clock":
            action_text = "暂停" if self.timer_session.status == "running" else "继续" if self.timer_session.status == "paused" else "开始"
            primary = ttk.Button(actions, text=action_text, command=self._toggle_timer)
            primary.pack(side="left", padx=4)
            if self.timer_session.mode == "pomodoro" and self.timer_session.status == "finished":
                primary.configure(state="disabled")
            if self.timer_session.mode == "stopwatch" and self.timer_session.status in ("running", "paused"):
                ttk.Button(actions, text="结束并记录", command=self._finish_stopwatch).pack(side="left", padx=4)
            ttk.Button(actions, text="重置", command=self._stop_timer).pack(side="left", padx=4)

        if self._timer_compact:
            ttk.Button(self._timer_body, text="展开计时设置", command=self._expand_timer).pack(anchor="center", pady=(6, 0))
            return

        settings = ttk.LabelFrame(self._timer_body, text="计时方式", padding=10)
        settings.pack(fill="x", pady=(2, 8))
        mode_box = ttk.Combobox(settings, textvariable=self.timer_mode_var,
                                values=("时钟", "倒计时", "正计时", "番茄钟"), state="readonly", width=12)
        mode_box.pack(anchor="w")
        mode_box.bind("<<ComboboxSelected>>", self._choose_timer_mode)
        active = self.timer_session.status in ("running", "paused")
        mode_box.configure(state="readonly")
        if self.timer_session.mode == "countdown":
            quick = ttk.Frame(settings)
            quick.pack(fill="x", pady=(8, 2))
            active = self.timer_session.status in ("running", "paused")
            for minutes in (5, 15, 25, 45):
                ttk.Button(quick, text="{0}分".format(minutes), command=lambda m=minutes: self._start_timer(m),
                           state="disabled" if active else "normal").pack(side="left", padx=2)
            custom = ttk.Frame(settings)
            custom.pack(anchor="w", pady=(6, 0))
            ttk.Label(custom, text="自定义").pack(side="left")
            ttk.Spinbox(custom, from_=1, to=240, textvariable=self.custom_minutes, width=5).pack(side="left", padx=5)
            ttk.Label(custom, text="分钟").pack(side="left")
            ttk.Button(custom, text="开始", command=self._toggle_timer,
                       state="disabled" if active else "normal").pack(side="left", padx=8)
        elif self.timer_session.mode == "pomodoro":
            durations = ttk.Frame(settings)
            durations.pack(anchor="w", pady=(8, 0))
            ttk.Label(durations, text="工作").pack(side="left")
            ttk.Spinbox(durations, from_=1, to=240, textvariable=self.work_minutes, width=4,
                        state="disabled" if active else "normal").pack(side="left", padx=(4, 10))
            ttk.Label(durations, text="休息").pack(side="left")
            ttk.Spinbox(durations, from_=1, to=120, textvariable=self.break_minutes, width=4,
                        state="disabled" if active else "normal").pack(side="left", padx=4)
            ttk.Button(durations, text="确认下一段", command=self._next_pomodoro_phase,
                       state="normal" if self.timer_session.status == "finished" else "disabled").pack(side="left", padx=8)
        preferences = ttk.Frame(self._timer_body)
        preferences.pack(fill="x", pady=6)
        zone = ttk.Combobox(preferences, textvariable=self.timer_zone_var, values=("本地时间", "北京时间"), state="readonly", width=12)
        zone.pack(side="left")
        zone.bind("<<ComboboxSelected>>", lambda event: self._timer_preferences())
        ttk.Checkbutton(preferences, text="传统时辰", variable=self.timer_traditional_var, command=self._timer_preferences).pack(side="left", padx=8)
        reminders = ttk.Frame(self._timer_body)
        reminders.pack(fill="x")
        ttk.Checkbutton(reminders, text="声音", variable=self.timer_sound_var, command=self._timer_preferences).pack(side="left")
        ttk.Checkbutton(reminders, text="控件提醒", variable=self.timer_widget_var, command=self._timer_preferences).pack(side="left", padx=8)
        ttk.Label(self._timer_body, text="系统通知：当前开发运行方式尚未接入。应用内提醒可用。", wraplength=385, style="Subtle.TLabel").pack(anchor="w", pady=6)
        ttk.Button(self._timer_body, text="收成迷你控件", command=self._collapse_timer).pack(anchor="e", pady=(2, 0))
        ttk.Label(self._timer_body, text="计时使用真实经过时间；关闭主面板时仍继续。",
                  style="Subtle.TLabel").pack(anchor="w", pady=(8, 0))

    def _timer_preferences(self):
        self.timer_session.clock_timezone = "Asia/Shanghai" if self.timer_zone_var.get() == "北京时间" else "local"
        self.timer_session.show_traditional = self.timer_traditional_var.get()
        self.timer_session.sound_enabled = self.timer_sound_var.get()
        self.timer_session.widget_enabled = self.timer_widget_var.get()
        self._save()
        self._refresh_timer()

    def _timer_status_text(self):
        timer = self.timer_session
        if timer.mode == "clock":
            return "北京时间" if timer.clock_timezone == "Asia/Shanghai" else "设备本地时间"
        if timer.mode == "pomodoro":
            phase = "工作段" if timer.phase == "work" else "休息段"
            if timer.status == "finished":
                return "{0}结束 · 确认后进入下一段".format(phase)
            return "{0} · {1}".format(phase, {"idle": "待开始", "running": "进行中", "paused": "已暂停"}.get(timer.status, ""))
        return {"idle": "准备就绪", "running": "进行中", "paused": "已暂停", "finished": "本轮已结束"}.get(timer.status, "")

    def _choose_timer_mode(self, _event=None):
        label_to_mode = {"时钟": "clock", "倒计时": "countdown", "正计时": "stopwatch", "番茄钟": "pomodoro"}
        mode = label_to_mode.get(self.timer_mode_var.get(), "countdown")
        if self.timer_session.status in ("running", "paused"):
            if not messagebox.askyesno("替换当前计时", "结束当前计时，切换到所选模式？", parent=self._timer_window or self.root):
                self.timer_mode_var.set(self._timer_mode_label(self.timer_session.mode))
                return
        self.timer_session.stop()
        self.timer_session.mode = mode
        self._sync_legacy_timer_fields()
        self._save()
        self._render_timer_window()
        self._refresh_timer()

    def _collapse_timer(self):
        self._timer_compact = True
        self._render_timer_window()
        if self._timer_window:
            self._timer_window.geometry("280x240")

    def _expand_timer(self):
        self._timer_compact = False
        self._render_timer_window()
        if self._timer_window:
            self._timer_window.geometry("430x500")

    def _hide_timer(self):
        if self._timer_window and self._timer_window.winfo_exists():
            self._timer_window.withdraw()

    def _start_timer(self, minutes):
        if self.timer_session.status in ("running", "paused"):
            self.status.set("当前计时仍在运行，请先暂停或重置后再换时长。")
            return
        if self.timer_session.mode == "pomodoro":
            self.timer_session.work_seconds = max(1, int(self.work_minutes.get())) * 60
            self.timer_session.break_seconds = max(1, int(self.break_minutes.get())) * 60
        self.timer_session.start(self.timer_session.mode, now=time.time(), minutes=minutes)
        self.custom_minutes.set(max(1, int(minutes)))
        self.status.set("{0}已开始。".format(self._timer_mode_label(self.timer_session.mode)))
        self._sync_legacy_timer_fields()
        self._save()
        self._render_timer_window()
        self._refresh_timer()

    def _toggle_timer(self):
        if self.timer_session.mode == "clock":
            return
        try:
            if self.timer_session.status not in ("running", "paused"):
                variables = [self.custom_minutes] if self.timer_session.mode == "countdown" else [self.work_minutes, self.break_minutes] if self.timer_session.mode == "pomodoro" else []
                if any(not 1 <= int(variable.get()) <= 240 for variable in variables):
                    raise ValueError("duration out of range")
        except (ValueError, tk.TclError):
            self.status.set("请输入 1–240 的整数分钟，再开始计时。")
            return
        now = time.time()
        old_status = self.timer_session.status
        if self.timer_session.status == "running":
            self.timer_session.pause(now)
            self.status.set("计时已暂停。")
        elif self.timer_session.status == "paused":
            self.timer_session.resume(now)
            self.status.set("计时继续。")
        else:
            if self.timer_session.mode == "pomodoro":
                self.timer_session.work_seconds = max(1, int(self.work_minutes.get())) * 60
                self.timer_session.break_seconds = max(1, int(self.break_minutes.get())) * 60
            minutes = self.custom_minutes.get() if self.timer_session.mode == "countdown" else None
            self.timer_session.start(self.timer_session.mode, now=now, minutes=minutes)
            self.status.set("{0}已开始。".format(self._timer_mode_label(self.timer_session.mode)))
        self._sync_legacy_timer_fields()
        self._save()
        self._render_timer_window()
        self._refresh_timer()

    def _stop_timer(self):
        self.timer_session.stop()
        self._sync_legacy_timer_fields()
        self._save()
        self._render_timer_window()
        self._refresh_timer()

    def _finish_stopwatch(self):
        self.timer_session.finish_stopwatch(now=time.time())
        self._sync_legacy_timer_fields()
        self._save()
        self._render_timer_window()
        self._refresh_timer()

    def _next_pomodoro_phase(self):
        if self.timer_session.next_phase():
            self._sync_legacy_timer_fields()
            self._save()
            self._render_timer_window()
            self._refresh_timer()

    def _sync_legacy_timer_fields(self):
        self.game.timer_deadline = self.timer_session.deadline
        self.game.timer_remaining = self.timer_session.remaining_seconds
        self.game.timer_completed = self.timer_session.status == "finished"

    def _refresh_timer(self):
        # Preserve compatibility for older tests and countdown-only save editing.
        if self.timer_session.mode == "countdown" and self.game.timer_deadline != self.timer_session.deadline:
            self.timer_session.deadline = self.game.timer_deadline
            self.timer_session.remaining_seconds = self.game.timer_remaining
            self.timer_session.status = ("running" if self.game.timer_deadline is not None
                                         else "finished" if self.game.timer_completed
                                         else "paused" if self.game.timer_remaining > 0 else "idle")
        result = self.timer_session.tick(now=time.time())
        self._sync_legacy_timer_fields()
        if result == "expired":
            self._expire_timer()
        if not self._timer_label or not self._timer_label.winfo_exists():
            return
        self._timer_label.configure(text=self.timer_session.readout(now=time.time()))
        self.timer_status_var.set(self._timer_status_text())

    def _expire_timer(self):
        self.status.set("{0}结束。".format(self._timer_mode_label(self.timer_session.mode)))
        if self.timer_session.sound_enabled:
            self.root.bell()
        if self.timer_session.widget_enabled:
            if self.native_overlay:
                self.overlay.send("timer_expired")
            if self._timer_window and self._timer_window.winfo_exists():
                self._timer_window.deiconify()
        self._sync_legacy_timer_fields()
        self._render_timer_window()
        self._save()

    def _poll_overlay(self):
        if not self.native_overlay:
            return
        while True:
            try:
                event = self.overlay.events.get_nowait()
            except queue.Empty:
                break
            kind = event.get("type")
            if kind == "ready":
                self.status.set("透明桌面图层已启动；菜单栏“天姥”可打开控制面板。")
            elif kind == "show_panel":
                self.root.deiconify()
                self.root.lift()
            elif kind == "capture_mode":
                self.capture_mode = bool(event.get("enabled"))
                self.native_capture_active = self.capture_mode
                self.net_button.configure(text="取消拉网" if self.capture_mode else "🕸 开始拉网")
                self.status.set("拖动网框捕捉；松手恢复鼠标穿透。" if self.capture_mode else "已退出拉网模式。")
            elif kind == "capture":
                caught = self._change(lambda: self.game.catch(event.get("ids", [])))
                self.capture_mode = False
                self.native_capture_active = False
                self.net_button.configure(text="🕸 开始拉网")
                self.overlay.send("mode", mode="passthrough")
                if self.root.winfo_viewable():
                    self.overlay.send("hide")
                    self.overlay_visible = False
                if caught is not None:
                    self._after_change("手动捕获 {0} 只；鼠标穿透已恢复。".format(len(caught)))
            elif kind == "mode":
                self.capture_mode = event.get("mode") == "capture"
                self.native_capture_active = self.capture_mode
                self.net_button.configure(text="取消拉网" if self.capture_mode else "🕸 开始拉网")
                if not self.capture_mode and self.root.winfo_viewable():
                    self.overlay.send("hide")
                    self.overlay_visible = False
            elif kind == "window_frame":
                self.status.set("桌面小庙位置／大小已更新并保存。")
            elif kind == "overlay_visibility":
                self.overlay_visible = bool(event.get("visible"))
                if "requested_visible" in event:
                    self.overlay_requested_visible = bool(event["requested_visible"])
                self.status.set("桌面图层已{0}。".format("显示" if event.get("visible") else "隐藏"))
            elif kind == "timer_dismissed":
                self.status.set("计时提醒已清除。")
            elif kind == "quit":
                if not self._save():
                    self.root.deiconify()
                    continue
                self.overlay.close()
                self.root.destroy()
                return
            elif kind == "host_stopped":
                self.native_overlay = False
                self.overlay_visible = False
                self.root.deiconify()
                self.status.set("桌面图层已退出；游戏回到控制窗口模式。")
        if self.native_overlay:
            self.overlay.send("state", insects=[{"id": bug.id, "x": bug.x, "y": bug.y, "color": bug.color}
                                                   for bug in self.game.desktop.values()],
                              placed_item=self.game.placed_item)

    def _tick(self):
        self._poll_overlay()
        now = time.monotonic()
        # A hidden panel/pet is still an active app (v0.4 §9.1–9.2).
        # Sleep and stalled callbacks are excluded by consume_active_delta.
        visible = True
        wall_delta = max(0.0, now - self._last_tick_at)
        self._last_tick_at = now
        # Tk can be suspended while macOS sleeps or the event loop is stalled.
        # Discard long gaps instead of slowly replaying them as a catch-up queue.
        delta, self._active_tick_fraction = consume_active_delta(
            wall_delta, visible, self._active_tick_fraction
        )
        if delta:
            self.game.advance(delta)
            self._render_selected_dynamic_page()
            self._update_status()
        self._refresh_timer()
        if time.monotonic() - self._last_save_at >= 10:
            self._save()
        self.root.after(1000, self._tick)

    def _save(self):
        try:
            save_state(self.save_path, self.game)
        except (OSError, ValueError) as error:
            self.status.set("保存失败：{0}。进度仍在内存，请检查磁盘后重试。".format(error))
            return False
        self._last_save_at = time.monotonic()
        return True

    def close(self):
        if self.capture_mode:
            self._escape()
        if not self._save():
            return
        if self.native_overlay and self.overlay.available:
            self.root.withdraw()
            if self.overlay_requested_visible:
                self.overlay.send("show")
                self.status.set("控制面板已收起；桌面图层仍在运行。菜单栏“天姥”可重新打开。")
            else:
                self.status.set("控制面板已收起；桌面图层保持隐藏。菜单栏“天姥”可重新显示。")
        else:
            self.root.destroy()

    def shutdown(self):
        self._save()
        self.overlay.close()
