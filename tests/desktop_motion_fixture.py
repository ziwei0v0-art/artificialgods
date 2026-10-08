"""Inject the production JS file into generated, unbundled native test hosts.

Packaged production hosts still use their own Bundle resource. This changes
only the temporary Swift harness source, never the production loading policy.
Historical geometry, capture and upstream motion fixtures explicitly bypass the
new admission schedule. Default quiet presentation has separate end-to-end tests
in test_insect_quiet_presentation.py, including visible-only capture and timing.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def with_desktop_motion_fixture(source):
    module = ROOT / "third_party/fly-paradise/desktop-motion.js"
    argument = "motionModuleURL: URL(fileURLWithPath: " + json.dumps(str(module), ensure_ascii=False) + "), quietPresentation: false, "
    return re.sub(r"DesktopInsects\((?=\s*screens:)", lambda _: "DesktopInsects(" + argument, source)
