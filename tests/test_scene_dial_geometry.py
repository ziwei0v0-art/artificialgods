"""C-to-Swift differential checks catch translation drift, not mirrored expectations."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'third_party/bongocat-dial'

SWIFT_HARNESS = r'''
import AppKit
import Foundation
while let line = readLine() {
    let v = line.split(separator:" ").map(String.init)
    func f(_ n:Int)->Double { Double(v[n])! }
    func i(_ n:Int)->Int { Int(v[n])! }
    switch v[0] {
    case "S":
        let p = SceneDialGeometry.sector(inner:f(1),outer:f(2),start:f(3),end:f(4))
        print(([String(p.count)] + p.flatMap{[String(Double($0.x)),String(Double($0.y))]}).joined(separator:" "))
    case "A": print(SceneDialGeometry.rootAngle(index:i(1),count:i(2)))
    case "C": print(SceneDialGeometry.childStep(childCount:i(3),compact:i(1)==4 || i(1)==5), SceneDialGeometry.childAngle(root:i(1),index:i(4),count:i(2),childCount:i(3)))
    case "H":
        let h = SceneDialGeometry.hit(point:NSPoint(x:f(5),y:f(6)),count:i(1),active:i(2),childCount:i(3),childFocus:i(4) != 0)
        print(h.root,h.child,i(4))
    case "P":
        let h = SceneDialGeometry.pointerHit(point:NSPoint(x:f(5),y:f(6)),count:i(1),active:i(2),childCount:i(3),childFocus:i(4) != 0,click:i(7) != 0)
        print(h.root,h.child,h.childFocus ? 1 : 0)
    case "R": print(SceneDialGeometry.reveal(elapsedMilliseconds:f(1),index:i(2)))
    case "M": print(SceneDialGeometry.hoverLift(current:f(1),target:f(2),elapsedSeconds:f(3)/1000))
    case "O": print(SceneDialGeometry.opening(elapsedMilliseconds:f(1)))
    default: fatalError("Unknown oracle operation")
    }
}
'''


class SceneDialGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-dial-oracle-')
        cls.temp = Path(cls.temporary.name)
        cls.c = cls.temp/'upstream-oracle'
        cls.swift = cls.temp/'swift-port'
        for row in json.loads((PACKAGE/'manifest.json').read_text()):
            actual = hashlib.sha256((PACKAGE/row['path']).read_bytes()).hexdigest()
            if actual != row['sha256']:
                raise AssertionError(f"Preserved upstream source changed: {row['path']}")
        subprocess.run([sys.executable,str(PACKAGE/'extract_oracle.py'),str(cls.temp/'oracle.c')],check=True)
        subprocess.run(['clang','-std=c11','-ffp-contract=off',str(cls.temp/'oracle.c'),'-o',str(cls.c)],check=True,capture_output=True,text=True)
        (cls.temp/'main.swift').write_text(SWIFT_HARNESS)
        result = subprocess.run(['swiftc',str(ROOT/'native/v1/BrandArtwork.swift'),str(cls.temp/'main.swift'),'-o',str(cls.swift)],capture_output=True,text=True)
        if result.returncode:
            raise AssertionError('Production SceneDialGeometry API did not compile:\n'+result.stderr)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'temporary'): cls.temporary.cleanup()

    def differential(self, rows, tolerance=3e-5):
        stdin = '\n'.join(rows)+'\n'
        original = subprocess.run([str(self.c)],input=stdin,capture_output=True,text=True,check=True).stdout.splitlines()
        adapted = subprocess.run([str(self.swift)],input=stdin,capture_output=True,text=True,check=True).stdout.splitlines()
        self.assertEqual(len(original),len(rows))
        self.assertEqual(len(adapted),len(rows))
        for row,c,swift in zip(rows,original,adapted):
            with self.subTest(input=row):
                expected,actual = list(map(float,c.split())),list(map(float,swift.split()))
                self.assertEqual(len(expected),len(actual))
                for a,b in zip(expected,actual): self.assertAlmostEqual(a,b,delta=tolerance)

    def test_rounded_sector_vertex_order_and_corners_match_original_c(self):
        # C detects reversed arcs, omitted corner samples, changed Float rounding or gap.
        rows=[]
        for count in (6,7,11,12):
            for index in range(count):
                center=-math.pi/2+index*2*math.pi/count
                rows.append(f'S 82 184 {center-math.pi/count:.12g} {center+math.pi/count:.12g}')
                rows.append(f'A {index} {count}')
        for step in (.32,.50):
            for angle in (-3.7,-1.57079632679,0,.25,2.9,6.0):
                rows.append(f'S 198 262 {angle-step/2:.12g} {angle+step/2:.12g}')
        self.differential(rows)

    def test_outer_ring_focus_and_center_gap_transitions_match_original_c(self):
        # A wider arc hit, premature center clear or missing <190 escape must fail.
        rows=[]
        for count in (6,11,12):
            for active,children in ((-1,0),(0,3),(4,16),(5,10),(count-1,12)):
                for focus in (0,1):
                    for radius in (0,72.999,73,100,189.99,190,197.99,198,200,262,276.99,277,279.99,280,280.01):
                        for deg in (-180,-150,-120,-90,-60,-30,0,30,60,90,120,150,179):
                            angle=math.radians(deg)
                            x,y=radius*math.cos(angle),radius*math.sin(angle)
                            for operation,click in (('H',0),('P',0),('P',1)):
                                rows.append(f'{operation} {count} {active} {children} {focus} {x:.9g} {y:.9g} {click}')
        self.differential(rows,tolerance=0)

    def test_child_spacing_and_original_clockwise_layout(self):
        rows=[f'C {root} 12 {count} {index}' for root in (0,4,5,9) for count in (1,3,10,11,12,16) for index in range(count)]
        self.differential(rows)

    def test_reveal_opening_and_hover_response_match_original_c(self):
        # Detect wrong delay, curve exponent, milliseconds/seconds or response cap.
        rows=[f'R {ms} {index}' for index in (0,1,5,10,15) for ms in (0,1,21,22,23,100,180,359,360,361,690,700,999)]
        rows += [f'O {ms}' for ms in (0,1,22,180,360,699,700,999)]
        rows += [f'M {current} {target} {ms}' for current in (0,.2,.6,.999,1) for target in (0,1) for ms in (0,1,16,50,100,250)]
        self.differential(rows,tolerance=2e-7)


if __name__ == '__main__': unittest.main()
