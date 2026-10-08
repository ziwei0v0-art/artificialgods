"""Production sprite loading/rendering/input in temporary bundles, no windows or worker."""
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


def png(path, width=8, height=12, pixels=None):
    # A deliberately asymmetric sprite with transparent margins and an interior hole.
    pixels = pixels or {(1, 1): (255, 0, 0, 255), (6, 10): (0, 0, 255, 255),
                        **{(x, y): (0, 255, 0, 255) for y in range(3, 9) for x in (3, 4)
                           if (x, y) != (4, 5)}}
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    raw = b''.join(b'\0' + b''.join(bytes(pixels.get((x, y), (0, 0, 0, 0))) for x in range(width))
                   for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


PRELUDE = r'''
import AppKit
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
let view = TianmuView(frame:NSRect(origin:.zero,size:TianmuView.sceneCanvas.size))
func point(_ x:CGFloat,_ y:CGFloat)->NSPoint {
    let c = TianmuView.sceneCanvas, s = min(view.bounds.width/c.width,view.bounds.height/c.height)
    return NSPoint(x:(view.bounds.width-c.width*s)/2+(x-c.minX)*s,
                   y:view.bounds.height-(view.bounds.height-c.height*s)/2-(y-c.minY)*s)
}
func render()->NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(view.bounds.width),pixelsHigh:Int(view.bounds.height),bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
    view.draw(view.bounds); NSGraphicsContext.restoreGraphicsState(); return rep
}
func colorAt(_ rep:NSBitmapImageRep,_ x:CGFloat,_ y:CGFloat)->NSColor {
    let p = point(x,y)
    return rep.colorAt(x:Int(p.x),y:Int(view.bounds.height-p.y))!.usingColorSpace(.deviceRGB)!
}
'''


class AttendantArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-art-offscreen-')
        cls.folder = Path(cls.temporary.name)
        source = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
        cls.scene = cls.folder / 'Scene.swift'
        cls.scene.write_text(source)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_swift(self, body, *, manifest=None, missing=False, custom=None):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            d = Path(directory)
            contents = d / 'Check.app/Contents'
            macos = contents / 'MacOS'; macos.mkdir(parents=True)
            assets = contents / 'Resources/art/A01'; assets.mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'local.tianmu.art-test', 'CFBundleExecutable': 'check', 'CFBundlePackageType': 'APPL'}))
            if not missing:
                png(assets / 'stand.png')
                (assets / 'manifest.json').write_text(json.dumps(manifest or {'version': 1, 'stand': {'file': 'stand.png'}}))
            if custom:
                custom(assets)
            (d / 'main.swift').write_text(PRELUDE + body)
            build = subprocess.run(['swiftc', '-framework', 'AppKit', str(self.scene), str(d/'main.swift'), '-o', str(macos/'check')], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(macos/'check')], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

    def test_bundled_png_replaces_vectors_and_uses_its_alpha(self):
        self.run_swift(r'''
assert(view.subject(at:point(397.5,148.5)) == "attendant", "Bundled PNG visible corner must be clickable outside vector art")
assert(view.subject(at:point(346.5,216.5)) == nil, "Transparent PNG hole must pass through even inside the old vector robe")
assert(view.subject(at:point(380.5,250.5)) == nil, "No invisible vector fallback hit region may accompany a loaded PNG")
let image = render()
let red = colorAt(image,397.5,148.5), blue = colorAt(image,312.5,301.5)
assert(red.redComponent > 0.95 && red.greenComponent < 0.05 && red.alphaComponent > 0.95, "PNG top pixel must render in the correct vertical orientation")
assert(blue.blueComponent > 0.95 && blue.redComponent < 0.05, "PNG foot must stay on the ground")
assert(colorAt(image,346.5,216.5).alphaComponent == 0, "PNG transparent hole must stay transparent when rendered")
assert(abs(view.attendantBounds.height-170) < 0.01 && abs(view.attendantBounds.minY-10) < 0.01, "Alpha occupancy crop must be 170 high, grounded at design y310")
print("PASS: Bundle PNG replaces geometry; actual alpha holes/corners match rendering, top/bottom orientation and grounded crop; NO_WINDOWS_NO_WORKER")
''')

    def test_scaled_mirrored_moving_sprite_matches_same_source_pixels(self):
        self.run_swift(r'''
for factor:CGFloat in [0.25,0.6,1,1.7] {
 view.setFrameSize(NSSize(width:370*factor,height:190*factor))
 assert(view.subject(at:point(397.5,148.5)) == "attendant")
 assert(view.subject(at:point(346.5,216.5)) == nil)
}
view.setFrameSize(NSSize(width:370,height:190))
view.updateAnimation(elapsed:14)
// At t14 the smooth halfway return walk is x326.5 and faces right.
assert(view.subject(at:point(284,148.5)) == "attendant", "Mirroring must preserve the original top-left opaque source pixel")
assert(view.subject(at:point(335,216.5)) == nil, "Mirrored original source hole must still release input")
assert(view.subject(at:point(397.5,148.5)) == nil, "Old pixels must release the pointer after movement")
let image = render()
assert(colorAt(image,284,148.5).redComponent > 0.95 && colorAt(image,284,148.5).greenComponent < 0.05)
assert(colorAt(image,335,216.5).alphaComponent == 0)
print("PASS: one source pixel maps consistently through resize, reflection and movement; old position releases input; NO_WINDOWS_NO_WORKER")
''')

    def test_missing_or_invalid_art_keeps_safe_existing_fallback(self):
        for manifest in [None, {'version': 1, 'stand': {'file': '../outside.png'}},
                         {'version': 1, 'stand': {'file': '/tmp/outside.png'}},
                         {'version': 1, 'stand': {'file': 'missing.png'}},
                         {'version': 9, 'stand': {'file': 'stand.png'}}]:
            with self.subTest(manifest=manifest):
                self.run_swift(r'''
assert(view.subject(at:point(355,190)) == "attendant", "Missing/rejected art must retain usable vector fallback")
assert(view.subject(at:point(397.5,148.5)) == nil)
assert(colorAt(render(),355,190).alphaComponent > 0.9)
print("PASS: absent/invalid asset safely falls back; NO_WINDOWS_NO_WORKER")
''', manifest=manifest, missing=manifest is None)

    def test_partial_alpha_and_explicit_left_facing_are_preserved(self):
        def partial(assets):
            png(assets/'stand.png', pixels={(1,1):(255,0,0,128), (6,10):(0,0,255,128)})
        self.run_swift(r'''
assert(view.subject(at:point(312.5,148.5)) == "attendant", "Non-opaque source pixels remain clickable")
assert(view.subject(at:point(397.5,148.5)) == nil, "An already left-facing asset must not be mirrored twice")
let red = colorAt(render(),312.5,148.5)
assert(red.redComponent > 0.95 && red.greenComponent < 0.05 && red.alphaComponent > 0.48 && red.alphaComponent < 0.53)
assert(view.attendantArtwork != nil && !view.attendantArtwork!.hasWalkFrames)
print("PASS: partial alpha retained and clickable; manifest left facing honored; static art reports no walk; NO_WINDOWS_NO_WORKER")
''', manifest={'version':1,'stand':{'file':'stand.png','facing':'left'}}, custom=partial)

    def test_walk_sheet_rects_change_render_and_hit_mask_together(self):
        def sheet(assets):
            pixels = {}
            for index, (left, top) in enumerate([(0,0),(8,0),(0,12),(8,12)]):
                pixels[(left+6,top+10)] = (0,0,255,255)
                pixels[(left+(2 if index == 1 else 1),top+1)] = ((0,255,0,255) if index == 1 else (255,0,0,255))
            png(assets/'sheet.png', width=16, height=24, pixels=pixels)
        manifest={'version':1,'stand':{'file':'stand.png'},'walk':{'fps':6,'facing':'right','frames':[
            {'file':'sheet.png','sourceRect':[x,y,8,12]} for x,y in [(0,0),(8,0),(0,12),(8,12)]]}}
        self.run_swift(r'''
assert(view.attendantArtwork!.hasWalkFrames)
view.updateAnimation(elapsed:4)
assert(view.subject(at:point(390.74,148.5)) == "attendant")
assert(colorAt(render(),390.74,148.5).redComponent > 0.95)
view.updateAnimation(elapsed:4.2)
assert(view.subject(at:point(388.06512,148.5)) == nil, "Current frame must release the previous frame's transparent source pixel")
assert(view.subject(at:point(371.06512,148.5)) == "attendant")
let green = colorAt(render(),371.06512,148.5)
assert(green.greenComponent > 0.95 && green.redComponent < 0.05)
assert(abs(view.attendantBounds.height-170) < 0.01, "Walk union crop must prevent frame scale jitter")
print("PASS: top-left sprite-sheet source rects, optional frame playback, union crop, per-frame alpha/render agreement; NO_WINDOWS_NO_WORKER")
''', manifest=manifest, custom=sheet)

    def test_runtime_rejects_symlink_escape_and_out_of_image_rect(self):
        def escape(assets):
            outside = assets.parent/'outside.png'; png(outside)
            (assets/'escape.png').symlink_to(outside)
        for spec in [{'file':'escape.png'}, {'file':'stand.png','sourceRect':[0,0,80,120]},
                     {'file':'stand.png','sourceRect':[0,0,8]}, {'file':'stand.png','facing':'down'}]:
            with self.subTest(spec=spec):
                self.run_swift(r'''
assert(view.attendantArtwork == nil)
assert(view.subject(at:point(355,190)) == "attendant")
print("PASS: untrusted resource reference rejected with usable fallback; NO_WINDOWS_NO_WORKER")
''', manifest={'version':1,'stand':spec}, custom=escape)

    def test_nearest_sampling_preserves_palette_for_stand_walk_and_mirroring(self):
        def palette(assets):
            png(assets/'stand.png', width=2, height=2,
                pixels={(x,y):((255,0,0,255) if x == 0 else (0,0,255,255))
                        for x in range(2) for y in range(2)})
            png(assets/'walk.png', width=2, height=2,
                pixels={(x,y):((0,0,255,255) if x == 0 else (255,0,0,255))
                        for x in range(2) for y in range(2)})
        manifest={'version':1,'sampling':'nearest','stand':{'file':'stand.png'},
                  'walk':{'fps':6,'frames':[{'file':'stand.png'},{'file':'walk.png'}]}}
        self.run_swift(r'''
let artwork = view.attendantArtwork!
assert(artwork.hasWalkFrames)
for frame in [artwork.frame(walking:false,elapsed:0), artwork.frame(walking:true,elapsed:0), artwork.frame(walking:true,elapsed:0.2)] {
 for mirrored in [false,true] {
  let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:31,pixelsHigh:17,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
  NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
  frame.draw(in:NSRect(x:0,y:0,width:31,height:17),mirrored:mirrored)
  NSGraphicsContext.restoreGraphicsState()
  let row = (0..<31).map { rep.colorAt(x:$0,y:8)!.usingColorSpace(.deviceRGB)! }
  let mixed = row.filter { $0.redComponent > 0.05 && $0.blueComponent > 0.05 }.count
  print("Nearest sampling mixed pixels: \(mixed)"); fflush(stdout)
  assert(mixed == 0, "Nearest sampling must not invent blended palette colors")
  assert(row.allSatisfy { $0.alphaComponent > 0.99 })
  assert(row.contains { $0.redComponent > 0.99 } && row.contains { $0.blueComponent > 0.99 })
 }
}
print("PASS: nearest keeps stand, both walk frames and reflections palette-exact at fractional scale; NO_WINDOWS_NO_WORKER")
''', manifest=manifest, custom=palette)

    def test_default_and_explicit_smooth_sampling_preserve_painted_behavior(self):
        def palette(assets):
            png(assets/'stand.png', width=2, height=2,
                pixels={(x,y):((255,0,0,255) if x == 0 else (0,0,255,255))
                        for x in range(2) for y in range(2)})
        for extra in [{}, {'sampling':'smooth'}]:
            with self.subTest(extra=extra):
                self.run_swift(r'''
let frame = view.attendantArtwork!.frame(walking:false,elapsed:0)
let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:31,pixelsHigh:17,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
frame.draw(in:NSRect(x:0,y:0,width:31,height:17),mirrored:false)
NSGraphicsContext.restoreGraphicsState()
let mixed = (0..<31).filter { x in
 let color = rep.colorAt(x:x,y:8)!.usingColorSpace(.deviceRGB)!
 return color.redComponent > 0.05 && color.blueComponent > 0.05
}.count
assert(mixed > 0, "Default and smooth must retain the existing interpolation for painted art")
print("PASS: existing smooth interpolation retained; mixed pixels: \(mixed); NO_WINDOWS_NO_WORKER")
''', manifest={'version':1,'stand':{'file':'stand.png'},**extra}, custom=palette)

    def test_unknown_sampling_rejects_the_manifest(self):
        for sampling in ['bilinear', '', 1]:
            with self.subTest(sampling=sampling):
                self.run_swift(r'''
assert(view.attendantArtwork == nil, "Unknown sampling must reject the manifest")
assert(view.subject(at:point(355,190)) == "attendant")
print("PASS: unknown sampling rejected with safe fallback; NO_WINDOWS_NO_WORKER")
''', manifest={'version':1,'sampling':sampling,'stand':{'file':'stand.png'}})

    def test_low_alpha_pixels_do_not_capture_input_but_remain_drawn(self):
        def alpha_steps(assets):
            png(assets/'stand.png', width=5, height=2,
                pixels={(x,y):(255,0,0,alpha) for x,alpha in enumerate([1,16,17,128,255])
                        for y in range(2)})
        self.run_swift(r'''
let frame = view.attendantArtwork!.frame(walking:false,elapsed:0)
let bounds = NSRect(x:10,y:20,width:100,height:40)
for mirrored in [false,true] {
 for (sourceX, alpha) in [1,16,17,128,255].enumerated() {
  let screenX = mirrored ? 4-sourceX : sourceX
  let sample = NSPoint(x:bounds.minX+(CGFloat(screenX)+0.5)*20,y:bounds.minY+10)
  assert(frame.contains(sample,in:bounds,mirrored:mirrored) == (alpha > 16),
         "Alpha 1/16 must release input; alpha 17/128 must remain clickable, including reflection")
 }
}
let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:5,pixelsHigh:2,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
frame.draw(in:NSRect(x:0,y:0,width:5,height:2),mirrored:false)
NSGraphicsContext.restoreGraphicsState()
for (x, expected) in [1,16,17,128,255].enumerated() {
 let alpha = Int((rep.colorAt(x:x,y:0)!.alphaComponent*255).rounded())
 assert(alpha == expected, "Input threshold must not discard any rendered alpha")
}
print("PASS: alpha 1/16 release input; 17/128/255 hit in both orientations; rendered alpha unchanged; NO_WINDOWS_NO_WORKER")
''', custom=alpha_steps)

    def test_packaging_copies_only_validated_manifest_resources(self):
        spec = importlib.util.spec_from_file_location('tianmu_build', ROOT/'tools/build_native.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module, 'copy_attendant_art', None)), 'Native build needs a validated art resource copy step')
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            d = Path(directory); source = d/'A01'; source.mkdir()
            png(source/'stand.png'); png(source/'walk.png')
            (source/'private.txt').write_text('do not bundle unrelated inputs')
            manifest = {'version': 1, 'stand': {'file': 'stand.png'}, 'walk': {'fps': 6, 'frames': [{'file':'walk.png'}]}}
            (source/'manifest.json').write_text(json.dumps(manifest))
            resources = d/'Candidate.app/Contents/Resources'
            module.copy_attendant_art(source, resources)
            result = resources/'art/A01'
            self.assertEqual(sorted(p.name for p in result.iterdir()), ['manifest.json','stand.png','walk.png'])
            self.assertEqual((source/'stand.png').read_bytes(), (result/'stand.png').read_bytes())
            self.assertEqual(json.loads((result/'manifest.json').read_text()), manifest)
            outside = d/'outside.png'; png(outside)
            (source/'escape.png').symlink_to(outside)
            for filename in ['../outside.png',str(outside),'escape.png']:
                (source/'manifest.json').write_text(json.dumps({'version':1,'stand':{'file':filename}}))
                with self.assertRaises(ValueError): module.copy_attendant_art(source, resources)
            self.assertEqual(json.loads((result/'manifest.json').read_text()), manifest, 'Rejected manifest must preserve prior copied assets')

    def test_missing_source_rejects_stale_bundled_art_without_changing_it(self):
        spec = importlib.util.spec_from_file_location('tianmu_build', ROOT/'tools/build_native.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            d = Path(directory)
            source = d/'missing-source'
            resources = d/'Candidate.app/Contents/Resources'
            self.assertFalse(module.copy_attendant_art(source, resources),
                             'A new development output may fall back when both source and bundled art are absent')
            self.assertFalse(resources.exists(), 'An absent source must not create an empty art output')
            target = resources/'art/A01'
            target.mkdir(parents=True)
            png(target/'stand.png')
            (target/'manifest.json').write_text(json.dumps({'version':1,'stand':{'file':'stand.png'}}))
            before = {p.name:p.read_bytes() for p in target.iterdir()}
            with self.assertRaisesRegex(ValueError, 'source'):
                module.copy_attendant_art(source, resources)
            self.assertEqual({p.name:p.read_bytes() for p in target.iterdir()}, before,
                             'Rejecting stale art must preserve the previous candidate byte for byte')
