"""G0 production loader/render/hit contracts, using temporary PNGs and no windows."""
import copy
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]


def png(path, width, height, pixels, *, alpha=True):
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload)))
    channels = 4 if alpha else 3
    raw = b''.join(b'\0' + b''.join(bytes(pixels.get((x, y), (0, 0, 0, 0))[:channels])
                                  for x in range(width)) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6 if alpha else 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def manifest():
    return {'version': 1, 'sampling': 'nearest', 'layers': [
        {'id': 'shrine', 'file': 'shrine.png', 'bounds': [65, 135, 160, 160]},
        {'id': 'idol', 'file': 'idol.png', 'bounds': [115, 175, 80, 80]},
        {'id': 'incense', 'file': 'incense.png', 'bounds': [95, 280, 20, 20]},
        {'id': 'fruit', 'file': 'fruit.png', 'bounds': [180, 280, 30, 20]},
    ]}


def scene_pngs(folder):
    folder.mkdir(parents=True, exist_ok=True)
    png(folder/'shrine.png', 8, 8,
        {(1, 1): (255, 0, 0, 255), (6, 6): (0, 0, 255, 255), (4, 3): (255, 0, 0, 255)})
    png(folder/'idol.png', 4, 4, {(1, 1): (0, 255, 0, 255), (2, 2): (255, 255, 0, 255)})
    png(folder/'incense.png', 2, 2, {(0, 0): (0, 255, 255, 255), (1, 1): (255, 255, 255, 128)})
    png(folder/'fruit.png', 3, 2, {(1, 0): (255, 0, 255, 255)})


PRELUDE = r'''
import AppKit
import Foundation
func check(_ condition: @autoclosure () -> Bool, _ message: String = "") {
 if !condition() { fputs("FAIL: \(message)\n", stderr); exit(1) }
}
let app = NSApplication.shared; app.setActivationPolicy(.prohibited)
check(app.windows.isEmpty)
let fixtureRoot = URL(fileURLWithPath:CommandLine.arguments[1])
let caseRoot = URL(fileURLWithPath:CommandLine.arguments[2])
let view = TianmuView(frame:NSRect(origin:.zero,size:TianmuView.sceneCanvas.size))
func point(_ x:CGFloat,_ y:CGFloat)->NSPoint {
 let c=TianmuView.sceneCanvas, s=min(view.bounds.width/c.width,view.bounds.height/c.height)
 return NSPoint(x:(view.bounds.width-c.width*s)/2+(x-c.minX)*s,
                y:view.bounds.height-(view.bounds.height-c.height*s)/2-(y-c.minY)*s)
}
func render()->NSBitmapImageRep {
 let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(view.bounds.width),pixelsHigh:Int(view.bounds.height),bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:rep)
 view.draw(view.bounds);NSGraphicsContext.restoreGraphicsState();return rep
}
func colorAt(_ rep:NSBitmapImageRep,_ x:CGFloat,_ y:CGFloat)->NSColor {
 let p=point(x,y)
 return rep.colorAt(x:Int(p.x),y:Int(view.bounds.height-p.y))!.usingColorSpace(.deviceRGB)!
}
func bytes(_ rep:NSBitmapImageRep)->[UInt8] {
 Array(UnsafeBufferPointer(start:rep.bitmapData!,count:rep.bytesPerRow*rep.pixelsHigh))
}
func snapshot(_ action:String,_ serial:Int,_ fruit:String="fresh")->[String:Any] {
 ["action":action,"action_serial":serial,"action_elapsed":0,"action_duration":5,"progress":0,"fruit_stage":fruit]
}
'''


class ShrineArtTests(unittest.TestCase):
    def run_swift(self, body, *, scene_manifest=None, custom=None):
        with tempfile.TemporaryDirectory(prefix='tianmu-shrine-offscreen-') as directory:
            d = Path(directory)
            contents = d/'Check.app/Contents'
            macos = contents/'MacOS'; macos.mkdir(parents=True)
            scene = contents/'Resources/art/scene'; scene_pngs(scene)
            (scene/'manifest.json').write_text(json.dumps(scene_manifest or manifest()))
            attendant = contents/'Resources/art/A01'; attendant.mkdir()
            png(attendant/'stand.png', 2, 4, {(x, y): (0, 255, 255, 255) for y in range(4) for x in range(2)})
            (attendant/'manifest.json').write_text(json.dumps({'version': 1, 'sampling': 'nearest',
                                                             'stand': {'file': 'stand.png'}}))
            if custom:
                custom(scene, d)
            original_images = {p: p.read_bytes() for p in d.rglob('*.png') if p.is_file()}
            (contents/'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'local.tianmu.shrine-test', 'CFBundleExecutable': 'check',
                'CFBundlePackageType': 'APPL'}))
            (d/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
            (d/'main.swift').write_text(PRELUDE + body + '\ncheck(app.windows.isEmpty)\n')
            build = subprocess.run(['swiftc', '-framework', 'AppKit', str(d/'Scene.swift'),
                                    str(d/'main.swift'), '-o', str(macos/'check')],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(macos/'check'), str(scene), str(d)], capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual({p: p.read_bytes() for p in original_images}, original_images,
                             'Loading/rendering must not modify any PNG, including the accepted stand fixture')
            print(run.stdout.strip())

    def test_bundle_layers_replace_geometry_and_keep_explicit_transparent_canvas(self):
        # Dropping the production early return, auto-cropping, or flipping rows breaks this.
        self.run_swift(r'''
check(view.subject(at:point(95,165)) == "shrine", "A visible production PNG pixel outside legacy geometry must be clickable")
check(view.subject(at:point(160,240)) == nil, "Transparent production space must not retain the old geometric hit region")
check(!view.shouldCapturePointer(at:point(160,240)))
let image=render()
let red=colorAt(image,95,165), blue=colorAt(image,195,265), green=colorAt(image,145,205)
check(red.redComponent>0.95 && red.greenComponent<0.05 && red.alphaComponent>0.95, "Explicit bounds preserve transparent margins and PNG top-left orientation")
check(blue.blueComponent>0.95 && blue.redComponent<0.05)
check(green.greenComponent>0.95 && green.redComponent<0.05, "Later idol layer must cover the earlier shrine pixel")
check(colorAt(image,160,240).alphaComponent==0, "No geometry may be drawn behind transparent formal layers")
check(abs(colorAt(image,110,295).alphaComponent-128.0/255.0)<0.01)
view.offeringPlate=true
check(bytes(render())==bytes(image), "G0 must not append the legacy purchased-plate drawing to formal assets")
print("PASS: bundled G0 layers, explicit canvas, render order, alpha hole, original alpha and no geometric overlay; NO_WINDOWS_NO_WORKER")
''')

    def test_nonzero_source_rect_and_low_alpha_render_without_capturing_input(self):
        config = manifest()
        config['layers'][0].update(file='sheet.png', sourceRect=[2, 1, 5, 2], bounds=[70, 140, 100, 40])

        def sheet(scene, _):
            pixels = {(x, y): (0, 255, 0, 255) for y in range(4) for x in range(10)}
            for x, a in enumerate([0, 16, 17, 128, 255]):
                pixels[(x+2, 1)] = (255, 0, 0, a)
                pixels[(x+2, 2)] = (0, 0, 255, 255-a)
            png(scene/'sheet.png', 10, 4, pixels)

        self.run_swift(r'''
let image=render()
for (index,alpha) in [0,16,17,128,255].enumerated() {
 let x=CGFloat(80+index*20)
 check((view.subject(at:point(x,150)) == "shrine") == (alpha>16), "Source alpha threshold must control input")
 let drawn=colorAt(image,x,150)
 check(abs(drawn.alphaComponent-Double(alpha)/255.0)<0.01, "Low-alpha rendering must remain unchanged")
 if alpha>16 {check(drawn.redComponent>0.95 && drawn.greenComponent<0.05)}
}
let lower=colorAt(image,80,170)
check(lower.blueComponent>0.95 && lower.redComponent<0.05 && lower.alphaComponent>0.95, "Nonzero sourceRect must preserve the second row's orientation")
check(view.subject(at:point(80,170)) == "shrine")
check(colorAt(image,160,170).alphaComponent==0)
print("PASS: top-left sourceRect, alpha 0/16/17/128/255, lower-row orientation and unchanged rendered alpha; NO_WINDOWS_NO_WORKER")
''', scene_manifest=config, custom=sheet)

    def test_scaled_hit_accessibility_union_and_injected_attendant_height(self):
        def replacement(_, directory):
            folder = directory/'replacement'; scene_pngs(folder)
            config = manifest(); config['layers'][0]['bounds'] = [75, 145, 140, 140]
            config['attendantHeight'] = 112
            (folder/'manifest.json').write_text(json.dumps(config))

        self.run_swift(r'''
check(view.shrineArtwork != nil)
for scale:CGFloat in [0.5,1,1.5] {
 view.setFrameSize(NSSize(width:370*scale,height:190*scale))
 check(view.subject(at:point(95,165)) == "shrine")
 check(view.subject(at:point(160,240)) == nil)
 check(colorAt(render(),95,165).redComponent>0.95)
 let children=view.accessibilityChildren()!
 let expected=NSRect(x:10*scale,y:20*scale,width:160*scale,height:165*scale)
 check((children[0] as! NSAccessibilityElement).accessibilityFrame()==expected, "Shrine accessibility must follow the formal layer union at the scene scale")
 check((children[2] as! NSAccessibilityElement).accessibilityFrame()==expected, "Menu accessibility must use that same formal union")
 check(abs(view.attendantBounds.height-170*scale)<0.01, "Omitted attendantHeight preserves old fixtures")
}
view.setFrameSize(NSSize(width:370,height:190))
view.shrineArtwork=ShrineArtwork.load(from:caseRoot.appendingPathComponent("replacement"))
check(view.shrineArtwork != nil)
let expected=NSRect(x:20,y:20,width:140,height:155)
let children=view.accessibilityChildren()!
check((children[0] as! NSAccessibilityElement).accessibilityFrame()==expected, "Cached accessibility elements must refresh after art injection")
check((children[2] as! NSAccessibilityElement).accessibilityFrame()==expected)
check(abs(view.attendantBounds.height-112)<0.01 && abs(view.attendantBounds.width-56)<0.01)
check(abs(view.attendantBounds.minY-10)<0.01, "Resized original stand must keep its design-y310 foot baseline")
check(view.subject(at:point(355,250)) == "attendant")
view.shrineArtwork=nil
check(abs(view.attendantBounds.height-170)<0.01)
check(view.subject(at:point(160,240)) == "shrine", "Explicitly missing scene art retains the development fallback")
print("PASS: scaled pixels/hits, explicit union accessibility, injected resource refresh, optional stand height and fixed foot baseline; NO_WINDOWS_NO_WORKER")
''', custom=replacement)

    def test_manifest_layer_order_and_attendant_foreground_priority(self):
        config = manifest()
        config['layers'][0], config['layers'][1] = config['layers'][1], config['layers'][0]
        config['layers'][2]['bounds'] = [330, 205, 40, 40]

        def opaque_incense(scene, _):
            png(scene/'incense.png', 2, 2, {(x, y): (255, 0, 0, 255) for y in range(2) for x in range(2)})

        self.run_swift(r'''
let image=render()
let overlap=colorAt(image,145,205)
check(overlap.redComponent>0.95 && overlap.greenComponent<0.05, "Drawing must follow manifest order rather than a hard-coded id order")
check(view.subject(at:point(340,215)) == "attendant", "The visible child remains the first hit over overlapping shrine layers")
let foreground=colorAt(image,340,215)
check(foreground.greenComponent>0.95 && foreground.blueComponent>0.95 && foreground.redComponent<0.05)
print("PASS: literal layer order and the original attendant's draw/hit foreground priority; NO_WINDOWS_NO_WORKER")
''', scene_manifest=config, custom=opaque_incense)

    def test_formal_idol_remains_static_across_service_time_and_response(self):
        self.run_swift(r'''
check(view.subject(at:point(95,165)) == "shrine")
check(view.applyRoutine(snapshot("idle",1)))
func idolPixels()->[UInt8] {
 let image=render();var result:[UInt8]=[]
 for y in 175..<255 {for x in 115..<195 {
  let c=colorAt(image,CGFloat(x)+0.5,CGFloat(y)+0.5)
  result += [c.redComponent,c.greenComponent,c.blueComponent,c.alphaComponent].map{UInt8(($0*255).rounded())}
 }};return result
}
let original=idolPixels()
for (index,action) in ["walk","practice","read","rest","offer","catch","bell"].enumerated() {
 check(view.applyRoutine(snapshot(action,index+2)))
 view.updateAnimation(elapsed:Double((index+1)*11))
 check(idolPixels()==original, "A static statue must not inherit routine action motion")
}
view.respond();view.updateAnimation(elapsed:77.5)
check(idolPixels()==original)
view.ritualStage="取香行礼";view.updateAnimation(elapsed:79)
check(idolPixels()==original)
print("PASS: static formal idol across service actions, elapsed time and attendant response; later ritual smoke is outside this assertion; NO_WINDOWS_NO_WORKER")
''')

    def test_invalid_manifests_and_resources_fail_as_a_complete_scene(self):
        def invalid_fixtures(_, directory):
            cases = directory/'invalid'; cases.mkdir()
            configs = []

            def add(name, change):
                value = manifest(); change(value); configs.append((name, value))

            add('version', lambda m: m.update(version=2))
            add('sampling', lambda m: m.update(sampling='smooth'))
            add('sampling-missing', lambda m: m.pop('sampling'))
            add('missing-layer', lambda m: m['layers'].pop())
            add('duplicate-layer', lambda m: m['layers'][3].update(id='idol'))
            add('extra-layer', lambda m: m['layers'].append(copy.deepcopy(m['layers'][0])))
            add('unknown-layer', lambda m: m['layers'][3].update(id='cloud'))
            for name in ['', '/tmp/outside.png', '../outside.png', 'nested/shrine.png', 'escape.png', 'missing.png', 'noalpha.png', 'empty.png', 'not-png.jpg']:
                add('file-'+str(len(configs)), lambda m, value=name: m['layers'][0].update(file=value))
            for rect in [[0, 0, 8], [-1, 0, 8, 8], [0, 0, 0, 8], [0, 0, 9, 8],
                         [8, 0, 1, 1], [0, 0, 2.5, 8], [0, 0, 2**63-1, 8]]:
                add('rect-'+str(len(configs)), lambda m, value=rect: m['layers'][0].update(sourceRect=value))
            for bounds in [[65, 135, 0, 10], [65, 135, -1, 10], [54, 135, 10, 10],
                           [65, 129, 10, 10], [420, 135, 10, 10], [65, 315, 10, 10],
                           [65, 135, 10], [65, 135, float('inf'), 10]]:
                add('bounds-'+str(len(configs)), lambda m, value=bounds: m['layers'][0].update(bounds=value))
            for height in [0, -1, 180.1, 190, float('inf'), True]:
                add('height-'+str(len(configs)), lambda m, value=height: m.update(attendantHeight=value))
            add('variant-key', lambda m: m.update(fruitVariants={'rotten': {'file': 'fruit.png'}}))
            add('variant-missing-file', lambda m: m.update(fruitVariants={'ripe': {'file': 'missing.png'}}))
            add('variant-escape', lambda m: m.update(fruitVariants={'soft': {'file': '../outside.png'}}))
            add('variant-empty', lambda m: m.update(fruitVariants={'fresh': {'file': 'empty.png'}}))
            add('variant-crop', lambda m: m.update(fruitVariants={'ripe': {'file': 'fruit.png', 'sourceRect': [0, 0, 100, 10]}}))
            png(directory/'outside.png', 1, 1, {(0, 0): (255, 0, 0, 255)})
            for name, config in configs:
                folder = cases/name; scene_pngs(folder)
                png(folder/'noalpha.png', 2, 2, {(0, 0): (255, 0, 0, 255)}, alpha=False)
                png(folder/'empty.png', 2, 2, {})
                (folder/'nested').mkdir(); png(folder/'nested/shrine.png', 1, 1, {(0, 0): (255, 0, 0, 255)})
                (folder/'escape.png').symlink_to(directory/'outside.png')
                (folder/'not-png.jpg').write_bytes((folder/'idol.png').read_bytes())
                (folder/'manifest.json').write_text(json.dumps(config))
            escaped = cases/'manifest-symlink'; scene_pngs(escaped)
            outside_manifest = directory/'outside-manifest.json'
            outside_manifest.write_text(json.dumps(manifest()))
            (escaped/'manifest.json').symlink_to(outside_manifest)

        self.run_swift(r'''
check(ShrineArtwork.load(from:fixtureRoot) != nil, "Valid control must load before checking invalid scenes")
let urls=try! FileManager.default.contentsOfDirectory(at:caseRoot.appendingPathComponent("invalid"),includingPropertiesForKeys:nil)
for url in urls {
 let art=ShrineArtwork.load(from:url)
 check(art==nil, "Invalid scene must fail atomically: \(url.lastPathComponent)")
 view.shrineArtwork=art
 check(view.subject(at:point(160,240)) == "shrine", "Rejected production data retains usable explicit development fallback")
 check(colorAt(render(),160,240).alphaComponent>0.9)
}
print("PASS: \(urls.count) malformed manifests/paths/crops/images/heights/variants rejected with complete-scene fallback; NO_WINDOWS_NO_WORKER")
''', custom=invalid_fixtures)

    def test_fruit_stage_variants_change_real_render_and_hit_in_the_same_layer(self):
        config = manifest()
        config['fruitVariants'] = {'soft': {'file': 'soft.png'},
                                   'ripe': {'file': 'ripe-sheet.png', 'sourceRect': [1, 1, 3, 2]}}

        def variants(scene, directory):
            png(scene/'soft.png', 3, 2, {(0, 0): (255, 255, 0, 255)})
            png(scene/'ripe-sheet.png', 5, 4, {(3, 1): (0, 0, 255, 255), (0, 0): (255, 0, 0, 255)})
            default = directory/'no-variants'; scene_pngs(default)
            (default/'manifest.json').write_text(json.dumps(manifest()))

        self.run_swift(r'''
check(view.shrineArtwork != nil)
for (stage,x,rgb) in [("fresh",CGFloat(195),[1.0,0.0,1.0]),("soft",CGFloat(185),[1.0,1.0,0.0]),("ripe",CGFloat(205),[0.0,0.0,1.0])] {
 check(view.applyRoutine(snapshot("idle",1,stage)), "Same action serial may update fruit age without restarting")
 let image=render(), c=colorAt(image,x,285)
 check(abs(c.redComponent-rgb[0])<0.01 && abs(c.greenComponent-rgb[1])<0.01 && abs(c.blueComponent-rgb[2])<0.01)
 for p:CGFloat in [185,195,205] {
  check((view.subject(at:point(p,285)) == "shrine") == (p==x), "Fruit input must use the currently selected variant, not the base alpha")
  check((colorAt(image,p,285).alphaComponent>0.1) == (p==x))
 }
 check(colorAt(image,145,205).greenComponent>0.95, "Fruit age must not replace or tint the static idol")
}
view.shrineArtwork=ShrineArtwork.load(from:caseRoot.appendingPathComponent("no-variants"))
let fallback=render()
check(colorAt(fallback,195,285).redComponent>0.95 && colorAt(fallback,195,285).blueComponent>0.95)
check(view.subject(at:point(195,285)) == "shrine" && view.subject(at:point(205,285)) == nil, "Missing optional variant falls back to the base fruit frame")
print("PASS: service fruitStage selects real soft/ripe PNGs for both drawing and input, preserving base fallback and other layers; NO_WINDOWS_NO_WORKER")
''', scene_manifest=config, custom=variants)


if __name__ == '__main__':
    unittest.main()
