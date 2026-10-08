"""Real PNG loading, fixed-wing composition, palette protection and frame sampling.

Temporary fixture files only; no NSApplication, window, worker or saved game.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from tests.test_attendant_art import png

ROOT = Path(__file__).resolve().parents[1]
PALETTE = {
    "普通褐色": [[96, 64, 39], [168, 117, 66], [214, 166, 106]],
    "中褐色": [[66, 45, 34], [123, 80, 51], [175, 128, 83]],
    "深褐色": [[41, 34, 31], [76, 55, 44], [118, 81, 59]],
    "白色": [[130, 126, 116], [198, 193, 175], [239, 234, 215]],
}
SOURCE_PALETTE = [[50, 60, 57], [89, 86, 82], [132, 126, 135]]
CUTE = {
    "kind": "atlas", "file": "cute.png", "canvasSize": [24, 24], "sampleScale": 2,
    "displayScale": 1.25, "fps": 12,
    "frames": [
        {"sourceRect": [2, 1, 12, 14], "anchor": [6, 9],
         "bodyRows": [[7, 2, 7], [8, 1, 10], [9, 1, 10], [10, 2, 9], [11, 5, 5]],
         "sourcePalette": SOURCE_PALETTE},
        {"sourceRect": [16, 4, 14, 10], "anchor": [8, 5],
         "bodyRows": [[3, 4, 9], [4, 3, 12], [5, 3, 12], [6, 4, 11], [7, 7, 7]],
         "sourcePalette": SOURCE_PALETTE},
        {"sourceRect": [33, 4, 13, 9], "anchor": [7, 4],
         "bodyRows": [[2, 7, 8], [3, 9, 9], [4, 6, 6], [4, 9, 9], [5, 6, 10], [6, 6, 6]],
         "sourcePalette": SOURCE_PALETTE},
    ], "palette": PALETTE,
}
REALISTIC = {
    "kind": "wingLayers", "canvasSize": [24, 24], "sampleScale": 2, "fps": 12,
    "body": {"file": "body.png", "sourceRect": [0, 0, 12, 10], "bounds": [-6, -2, 12, 10]},
    "upperWing": {"file": "wings.png", "sourceRect": [0, 0, 8, 6], "bounds": [-1, -6, 8, 6], "pivot": [-1, 0]},
    "lowerWing": {"file": "wings.png", "sourceRect": [8, 0, 8, 6], "bounds": [-2, -4, 8, 6], "pivot": [-2, 1]},
    "frames": [{"upperYScale": 1, "lowerYScale": 1},
               {"upperYScale": 0.55, "lowerYScale": 0.55},
               {"upperYScale": 0.18, "lowerYScale": 0.18}],
    "bodyPolygon": [[3, 1], [10, 1], [10, 5], [3, 5]],
    "warmGate": {"minRed": 20, "minGreenOverRed": 0.45, "minGreenMinusBlue": 5},
    "lumaRange": [0, 255], "palette": PALETTE,
}


def fixture(folder, mutate=None):
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "assets/incoming/insects_oga_20261001/greyfly_spritesheet-original.png", folder / "cute.png")
    body = {(x, y): ((60, 40, 20, 255) if x < 5 else (130, 90, 50, 255) if x < 8 else (220, 170, 110, 255))
            for y in range(1, 5) for x in range(3, 10)}
    body[(1, 2)] = (220, 35, 40, 255)  # Eye: outside polygon and outside the warm gate.
    body[(8, 8)] = (80, 50, 30, 255)   # Leg: warm but outside polygon.
    body[(7, 3)] = (130, 90, 50, 128)  # Partial alpha must survive body recoloring.
    png(folder / "body.png", 12, 10, body)
    wings = {(x, y): (180, 210, 230, 180) for y in range(0, 5) for x in range(1, 8)}
    wings.update({(x + 8, y): (180, 150, 230, 160) for y in range(0, 5) for x in range(1, 8)})
    png(folder / "wings.png", 16, 6, wings)
    manifest = {"version": 1, "sampling": "nearest", "styles": {"cute": copy.deepcopy(CUTE), "realistic": copy.deepcopy(REALISTIC)}}
    if mutate:
        mutate(manifest, folder)
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return manifest


PRELUDE = r'''
import AppKit
import ImageIO

func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { print("FAIL: " + message); exit(1) }
}
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory:true)
func art(_ name: String = "assets") -> InsectArtwork {
    InsectArtwork(directory: directory.appendingPathComponent(name, isDirectory:true))
}
func take(_ artwork:InsectArtwork, _ style:InsectStyle, _ color:String="普通褐色", _ index:Int=0) -> InsectArtwork.RenderSample {
    let value = artwork.sample(style:style,color:color,time:Double(index)/12+0.00001,phase:0)
    check(value != nil,"Expected actual cached frame for \(style)/\(color)/\(index): \(artwork.issues)")
    return value!
}
func rgba(_ image:CGImage,_ x:Int,_ y:Int) -> [UInt8] {
    let bytes = image.dataProvider!.data! as Data
    let offset = y * image.bytesPerRow + x * 4
    return Array(bytes[offset..<offset+4])
}
func source(_ path:String) -> CGImage {
    let data = try! Data(contentsOf:directory.appendingPathComponent(path))
    return CGImageSourceCreateImageAtIndex(CGImageSourceCreateWithData(data as CFData,nil)!,0,nil)!
}
'''


class InsectArtworkTests(unittest.TestCase):
    def run_swift(self, body, setup=None):
        with tempfile.TemporaryDirectory(prefix="tianmu-insect-art-") as temporary:
            folder = Path(temporary)
            fixture(folder / "assets")
            if setup:
                setup(folder)
            def hashes():
                return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in folder.rglob("*") if p.is_file() and p.suffix in (".json", ".png")}
            before = hashes()
            main = folder / "main.swift"
            main.write_text(PRELUDE + body + '\ncheck(NSApp == nil,"Resource code must not initialize NSApplication")\n')
            sources = [ROOT / "native/v1/WindowPlacement.swift", ROOT / "native/v1/InsectArtwork.swift"]
            binary = folder / "check"
            built = subprocess.run(["swiftc", "-framework", "AppKit", *map(str, sources), str(main),
                                    "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary), str(folder)], cwd=folder, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS:", result.stdout)
            self.assertEqual(hashes(), before, "Rendering must not write palettes, crops or caches to the source folder")
            print(result.stdout.strip())

    def test_two_real_styles_four_colors_three_frames_are_cached_and_drawable(self):
        self.run_swift(r'''
let artwork = art()
check(artwork.complete && artwork.availableStyles == Set([.cute,.realistic]),"Both real style resources must load: \(artwork.issues)")
check(artwork.issues.isEmpty,"Valid resources must not produce loader errors")
var identities=Set<ObjectIdentifier>()
for style:InsectStyle in [.cute,.realistic] {
    var colorHashes=Set<String>()
    for color in ["普通褐色","中褐色","深褐色","白色"] {
        var hashes=Set<String>()
        for index in 0..<3 {
            let sample=take(artwork,style,color,index)
            check(sample.style == style && sample.color == color && sample.frameIndex == index,"Metadata must identify the actual displayed sample")
            check(sample.canvasSize == NSSize(width:24,height:24) && sample.image.width == 48 && sample.image.height == 48,"Cache is a 2x point canvas")
            check(take(artwork,style,color,index) === sample,"Repeated sampling must reuse each cached image object")
            identities.insert(ObjectIdentifier(sample)); hashes.insert(sample.pixelHash)
            if index == 0 { colorHashes.insert(sample.pixelHash) }
        }
        check(hashes.count == 3,"Three declared frames must be visibly distinct")
    }
    check(colorHashes.count == 4,"Four body colors must not be identical copies")
}
check(identities.count == 24,"Only actual 2 x 4 x 3 frame objects are cached")
check(artwork.sample(style:.cute,color:"unknown",time:0,phase:0) === artwork.sample(style:.cute,color:"普通褐色",time:0,phase:0),"Unknown business color keeps ordinary-brown compatibility")
let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:80,pixelsHigh:80,bitsPerSample:8,samplesPerPixel:4,
    hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
take(artwork,.cute).draw(at:NSPoint(x:40,y:40))
NSGraphicsContext.restoreGraphicsState()
check(bitmap.colorAt(x:40,y:39)!.alphaComponent > 0.9,"Cached sample draw must occupy the same center used by capture")
check(bitmap.colorAt(x:10,y:10)!.alphaComponent == 0,"Sample drawing must preserve surrounding transparency")
print("PASS: 24 distinct cached samples; actual drawing and metadata share images; NO_WINDOWS_NO_WORKER")
''')

    def test_cute_only_changes_27_27_11_body_pixels_and_keeps_eyes_wings_legs_alpha(self):
        self.run_swift(r'''
let artwork=art(), original=source("assets/cute.png")
let boxes=[[2,1,12,14],[16,4,14,10],[33,4,13,9]], anchors=[[6,9],[8,5],[7,4]]
for index in 0..<3 {
    let sample=take(artwork,.cute,"白色",index), box=boxes[index], anchor=anchors[index]
    var changed=0
    for y in 0..<box[3] { for x in 0..<box[2] {
        let old=rgba(original,box[0]+x,box[1]+y)
        // Choose the center of each original pixel in the 2.5x cached image.
        let dx=Int(floor(24+(Double(x-anchor[0])+0.5)*2.5))
        let dy=Int(floor(24+(Double(y-anchor[1])+0.5)*2.5))
        let new=rgba(sample.image,dx,dy)
        check(new[3] == old[3],"Nearest placement must preserve source alpha at every sampled source pixel")
        if old[3] != 0 && Array(old[0..<3]) != Array(new[0..<3]) { changed += 1 }
        if old[3] != 0 && ![[50,60,57],[89,86,82],[132,126,135]].contains(old[0..<3].map(Int.init)) {
            check(new == old,"Eyes, wings, outline and legs must stay exactly unchanged")
        }
    } }
    check(changed == [27,27,11][index],"Only the 154 body mask may be recolored; count=\(changed)")
    check(rgba(sample.image,24,24) == [172,50,50,255],"The protected red eye anchor must remain fixed across poses")
}
check(rgba(take(artwork,.cute,"普通褐色").image,15,22) == [214,166,106,255],"Source highlight maps to the exact ordinary-brown highlight")
check(rgba(take(artwork,.cute,"白色",2).image,20,22) == [155,173,183,255],"Wing overlapping the body retains its original blue-grey")
print("PASS: exact cute mask counts, protected original pixels and fixed anchor; NO_WINDOWS_NO_WORKER")
''')

    def test_wing_layers_keep_body_eye_leg_and_partial_alpha_while_wings_change(self):
        self.run_swift(r'''
let artwork=art()
for color in ["普通褐色","中褐色","深褐色","白色"] { for index in 0..<3 {
    let sample=take(artwork,.realistic,color,index)
    check(rgba(sample.image,15,25) == [220,35,40,255],"Red eyes are neither recolored nor moved by wing motion")
    check(rgba(sample.image,29,37) == [80,50,30,255],"Warm-colored legs outside body polygon must remain original")
    check(rgba(sample.image,27,27)[3] == 128,"Body recoloring must not replace partial source alpha")
} }
let ordinary=take(artwork,.realistic)
check(rgba(ordinary.image,19,25) == [96,64,39,255],"Low luma maps to exact dark palette entry")
check(rgba(ordinary.image,25,25) == [168,117,66,255],"Middle luma maps to exact middle palette entry")
check(rgba(ordinary.image,31,25) == [214,166,106,255],"High luma maps to exact highlight palette entry")
let edges=art("edge-scales")
check(edges.complete,"Zero and negative wing scales within the square canvas are valid: \(edges.issues)")
check(Set((0..<3).map { take(edges,.realistic,"普通褐色",$0).pixelHash }).count == 3,"Scale zero hides the wing, not the whole body")
print("PASS: fixed body with protected pixels, three discrete tones and real wing transforms; NO_WINDOWS_NO_WORKER")
''', setup=lambda folder: fixture(folder / "edge-scales", lambda data, _: data["styles"]["realistic"].update(
            frames=[{"upperYScale": 1, "lowerYScale": 1}, {"upperYScale": 0, "lowerYScale": 0},
                    {"upperYScale": -0.5, "lowerYScale": -0.5}])))

    def test_sampling_uses_existing_time_and_phase_without_resetting_or_integer_overflow(self):
        self.run_swift(r'''
let artwork=art()
let expected=[0,1,2,1,0,1,2,1]
for i in expected.indices {
    let sample=artwork.sample(style:.realistic,color:"白色",time:Double(i)/12+0.00001,phase:0)!
    check(sample.frameIndex == expected[i],"Default sequence must play 0,1,2,1 at 12 steps per second")
}
check(artwork.sample(style:.cute,color:"白色",time:0,phase:5)!.frameIndex == 2,"Stable ID phase is normalized from the existing 0..<10 phase")
check(artwork.sample(style:.cute,color:"白色",time:-0.0001,phase:0)!.frameIndex == 1,"Negative times wrap deterministically")
for value in [Double.nan,Double.infinity,-Double.infinity,Double.greatestFiniteMagnitude,-Double.greatestFiniteMagnitude] {
    let one=artwork.sample(style:.cute,color:"白色",time:value,phase:0)!
    let two=artwork.sample(style:.cute,color:"白色",time:value,phase:0)!
    check(one === two,"All accepted clock values must be finite-safe and deterministic")
}
let before=take(artwork,.cute,"白色",1)
_ = take(artwork,.realistic,"白色",2)
check(before === take(artwork,.cute,"白色",1),"Sampling a different style cannot reset or evict previous samples")
print("PASS: one existing clock and stable phase; sequence, huge/invalid/negative time safe; NO_WINDOWS_NO_WORKER")
''')

    def test_invalid_style_is_isolated_and_cannot_claim_two_complete_styles(self):
        cases = {
            "missing-style": lambda m, p: m["styles"].pop("realistic"),
            "path-parent": lambda m, p: m["styles"]["realistic"]["body"].update(file="../body.png"),
            "absolute": lambda m, p: m["styles"]["realistic"]["body"].update(file=str(p / "body.png")),
            "bad-png": lambda m, p: (p / "body.png").write_bytes(b"not a png"),
            "empty-body": lambda m, p: png(p / "body.png", 12, 10, {(0, 0): (0, 0, 0, 0)}),
            "bad-crop": lambda m, p: m["styles"]["realistic"]["body"].update(sourceRect=[0, 0, 13, 10]),
            "huge-crop": lambda m, p: m["styles"]["realistic"]["body"].update(sourceRect=[2**62, 0, 2**62, 10]),
            "outside-pivot": lambda m, p: m["styles"]["realistic"]["upperWing"].update(pivot=[40, 0]),
            "outside-square": lambda m, p: m["styles"]["realistic"]["body"].update(bounds=[-6, -2, 19, 10]),
            "wrong-count": lambda m, p: m["styles"]["realistic"].update(frames=[{"upperYScale": 1, "lowerYScale": 1}]),
            "static-copies": lambda m, p: m["styles"]["realistic"].update(frames=[{"upperYScale": 1, "lowerYScale": 1}] * 3),
            "bad-sequence": lambda m, p: m["styles"]["realistic"].update(sequence=[0, 0, 1]),
            "wrong-ratio": lambda m, p: m["styles"]["realistic"]["warmGate"].update(minGreenOverRed=1.1),
            "no-warm-hits": lambda m, p: m["styles"]["realistic"]["warmGate"].update(minRed=255),
            "wrong-luma": lambda m, p: m["styles"]["realistic"].update(lumaRange=[50, 50]),
            "crossed-polygon": lambda m, p: m["styles"]["realistic"].update(bodyPolygon=[[3, 1], [10, 5], [10, 1], [3, 5]]),
            "missing-color": lambda m, p: m["styles"]["realistic"]["palette"].pop("白色"),
            "wrong-scale": lambda m, p: m["styles"]["realistic"].update(sampleScale=3),
            "wrong-fps": lambda m, p: m["styles"]["realistic"].update(fps=0),
            "wrong-kind": lambda m, p: m["styles"]["realistic"].update(kind="atlas"),
        }
        def setup(folder):
            for name, mutate in cases.items():
                fixture(folder / name, mutate)
            outside = folder / "outside.png"
            png(outside)
            def escaping(m, p):
                (p / "body.png").unlink()
                (p / "body.png").symlink_to(outside)
            fixture(folder / "symlink-escape", escaping)
        names = list(cases) + ["symlink-escape"]
        self.run_swift('let names = ' + json.dumps(names) + r'''
for name in names {
    let artwork=art(name)
    check(artwork.availableStyles == Set([.cute]),"Bad realistic style must be isolated: \(name) \(artwork.issues)")
    check(!artwork.complete && !artwork.issues.isEmpty,"Partial resources must never claim two complete styles: \(name)")
    check(artwork.sample(style:.realistic,color:"普通褐色",time:0,phase:0) == nil,"Cannot silently substitute cute for realistic: \(name)")
    _ = take(artwork,.cute)
}
print("PASS: invalid/missing/escaped/incomplete style rejected independently in \(names.count) cases; NO_WINDOWS_NO_WORKER")
''', setup=setup)

    def test_malformed_top_level_and_manifest_symlink_never_reach_external_art(self):
        def setup(folder):
            for name, edit in {
                "bad-version": lambda m: m.update(version=2),
                "bad-sampling": lambda m: m.update(sampling="linear"),
                "bad-container": lambda m: m.update(styles=[]),
            }.items():
                fixture(folder / name, lambda m, p, edit=edit: edit(m))
            escaped = folder / "manifest-escape"
            escaped.mkdir()
            (escaped / "manifest.json").symlink_to(folder / "assets/manifest.json")
            fixture(folder / "assets/production/insects")
        self.run_swift(r'''
for name in ["bad-version","bad-sampling","bad-container","manifest-escape","absent"] {
    let artwork=art(name)
    check(artwork.availableStyles.isEmpty && !artwork.complete && !artwork.issues.isEmpty,"Bad root manifest must fail visibly: \(name)")
}
check(InsectArtwork(directory:nil).availableStyles.isEmpty,"nil directory is a missing resource, not a generated insect")
check(InsectArtwork.production.availableStyles.isEmpty,"Bundle missing art cannot be hidden by a cwd assets/production/insects fallback")
print("PASS: root manifest and Bundle-only loading never escape or invent formal images; NO_WINDOWS_NO_WORKER")
''', setup=setup)


if __name__ == "__main__":
    unittest.main()
