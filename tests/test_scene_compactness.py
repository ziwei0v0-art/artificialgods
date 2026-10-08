"""Small continuous scene scale is preserved instead of forced back to 60%."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CompactSceneTests(unittest.TestCase):
    def test_small_scale_roundtrip_and_edge_placement(self):
        harness = r'''
import AppKit
let screen = NSRect(x:0,y:0,width:1440,height:900)
let frame = scaledOverlayFrame(NSRect(x:120,y:80,width:370,height:190),percent:25.7,screens:[screen])
assert(abs(sceneScalePercent(frame) - 25.7) < 0.001, "Small continuous scale must not be clamped to 60 percent")
assert(frame.width < 100 && frame.height < 55, "Empty margins must not enlarge the small desktop scene")
let corner = fitOverlayFrame(NSRect(x:1400,y:-80,width:frame.width,height:frame.height),screens:[screen])
assert(abs(corner.maxX - 1440) < 0.001 && corner.minY == 0, "Scene must reach the actual screen corner")
let store = WindowPlacementStore(url:URL(fileURLWithPath:CommandLine.arguments[1]))
try! store.save(corner)
assert(store.restore(screens:[screen]) == corner)
let other = NSRect(x:-1280,y:0,width:1280,height:800)
assert(other.contains(store.restore(screens:[other])))
// A pre-crop record must preserve the old visible art position, not its empty border.
try! Data(#"{"x":120,"y":80,"width":540,"height":380}"#.utf8).write(to:store.url)
assert(store.restore(screens:[screen]) == NSRect(x:175,y:140,width:370,height:190))
print("PASS continuous small size, compact bounds, screen corner, isolated placement restore")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-compact-') as directory:
            folder=Path(directory); (folder/'main.swift').write_text(harness)
            result=subprocess.run(['swiftc',str(ROOT/'native/v1/WindowPlacement.swift'),str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(folder/'check'),str(folder/'placement.json')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout)
