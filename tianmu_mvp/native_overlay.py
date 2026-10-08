"""Bridge to the small AppKit host that draws the click-through desktop pet."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading


class NativeOverlay:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.events = queue.Queue()
        self.process = None

    @property
    def available(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if os.uname().sysname != "Darwin":
            return False
        source = self.project_root / "native" / "OverlayHost.swift"
        binary = Path.home() / "Library" / "Application Support" / "TianmuMVP" / "bin" / "TianmuOverlayHost"
        binary.parent.mkdir(parents=True, exist_ok=True)
        if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                ["swiftc", "-framework", "AppKit", str(source), "-o", str(binary)],
                check=True, capture_output=True, text=True, timeout=60,
            )
        self.process = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        threading.Thread(target=self._read_events, name="tianmu-overlay-events", daemon=True).start()
        return True

    def _read_events(self):
        if self.process is None or self.process.stdout is None:
            return
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except (json.JSONDecodeError, TypeError):
                continue
        self.events.put({"type": "host_stopped"})

    def send(self, kind, **values):
        if not self.available or self.process.stdin is None:
            return False
        message = {"type": kind, **values}
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def close(self):
        if self.available:
            self.send("quit")
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
        self.process = None
