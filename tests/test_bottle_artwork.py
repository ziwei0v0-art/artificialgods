"""Windowless bottle loading and actual draw checks; temporary fixture files only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.test_insect_packaging import png

ROOT = Path(__file__).resolve().parents[1]


def bottle_fixture(folder):
    folder.mkdir(parents=True, exist_ok=True)
    pixels = {(x, y): (180, 130, 70, 255 if x == 0 else 128)
              for y in range(8) for x in range(8) if x in (0, 7) or y in (0, 7)}
    png(folder / 'bottle.png', 8, 8, pixels)
    value = {'version': 1, 'sampling': 'nearest', 'file': 'bottle.png',
             'sha256': hashlib.sha256((folder / 'bottle.png').read_bytes()).hexdigest(),
             'interiorRect': [.25, .25, .5, .5]}
    (folder / 'manifest.json').write_text(json.dumps(value))
    return value


class BottleArtworkTests(unittest.TestCase):
    def run_swift(self, body, setup=None):
        with tempfile.TemporaryDirectory(prefix='tianmu-bottle-art-') as temporary:
            folder = Path(temporary)
            bottle_fixture(folder / 'valid')
            if setup:
                setup(folder)
            def hashes():
                return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in folder.rglob('*') if p.is_file() and p.suffix in ('.json', '.png')}
            before = hashes()
            main = folder / 'main.swift'
            main.write_text('''import AppKit
func check(_ value: @autoclosure () -> Bool, _ message:String) {
 if !value() { print("FAIL: " + message); exit(1) }
}
let root=URL(fileURLWithPath:CommandLine.arguments[1])
''' + body + '\ncheck(NSApp == nil,"Loader must not create NSApplication")\n')
            (folder / 'bin').mkdir()
            binary = folder / 'bin/check'
            built = subprocess.run(['swiftc', '-framework', 'AppKit', str(ROOT / 'native/v1/WindowPlacement.swift'),
                                    str(ROOT / 'native/v1/InsectArtwork.swift'), str(main), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary), str(folder)], cwd=folder, capture_output=True, text=True, timeout=20)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('PASS:', ran.stdout)
            self.assertEqual(hashes(), before)
            print(ran.stdout.strip())

    def test_original_canvas_alpha_and_normalized_interior_are_used_by_actual_drawing(self):
        self.run_swift(r'''
let art=BottleArtwork(directory:root.appendingPathComponent("valid"))
check(art.issue == nil && art.image != nil,"Valid bottle must load")
check(art.image!.size == NSSize(width:8,height:8),"Original canvas is preserved")
check(art.interiorRect == NSRect(x:0.25,y:0.25,width:0.5,height:0.5),"Manifest interior must be preserved")
let bounds=NSRect(x:10,y:20,width:80,height:160)
check(art.interiorRect(in:bounds) == NSRect(x:30,y:60,width:40,height:80),"Interior maps to AppKit lower-left coordinates")
let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:80,pixelsHigh:80,bitsPerSample:8,samplesPerPixel:4,
 hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
art.draw(in:NSRect(x:0,y:0,width:80,height:80))
NSGraphicsContext.restoreGraphicsState()
check(bitmap.colorAt(x:3,y:40)!.alphaComponent > 0.99,"Original solid edge remains visible")
check(abs(bitmap.colorAt(x:77,y:40)!.alphaComponent - 128.0/255) < 0.02,"Source partial alpha is not flattened")
check(bitmap.colorAt(x:40,y:40)!.alphaComponent == 0,"Bottle interior stays transparent")
print("PASS: original pixels and alpha drawn, interior aligned; NO_WINDOWS_NO_WORKER")
''')

    def test_invalid_resource_manifest_hash_and_paths_disable_only_the_bottle(self):
        def setup(folder):
            cases = [lambda m, p:m.update(version=2), lambda m,p:m.update(sampling='linear'),
                     lambda m,p:m.update(sha256='0'*64), lambda m,p:m.update(interiorRect=[0,0,2,1]),
                     lambda m,p:m.update(interiorRect=[0,0,0,1]), lambda m,p:m.update(file='../valid/bottle.png'),
                     lambda m,p:m.update(file=str(folder/'valid/bottle.png')),
                     lambda m,p:(p/'bottle.png').write_bytes(b'not png'),
                     lambda m,p:(p/'bottle.png').write_bytes((p/'bottle.png').read_bytes()[:-8]),
                     lambda m,p:png(p/'bottle.png',8,8,{}),
                     lambda m,p:png(p/'bottle.png',8,8,{(0,0):(1,2,3,255)},alpha=False)]
            for i, change in enumerate(cases):
                part=folder/f'bad-{i}'; value=bottle_fixture(part); change(value,part)
                if i >= 7:
                    value['sha256']=hashlib.sha256((part/'bottle.png').read_bytes()).hexdigest()
                (part/'manifest.json').write_text(json.dumps(value))
            part=folder/'bad-symlink'; value=bottle_fixture(part)
            (part/'bottle.png').unlink(); (part/'bottle.png').symlink_to(folder/'valid/bottle.png')
            part=folder/'bad-manifest-link'; part.mkdir(); (part/'manifest.json').symlink_to(folder/'valid/manifest.json')
        self.run_swift(r'''
let paths=try! FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil).filter{$0.lastPathComponent.hasPrefix("bad-")}
check(paths.count == 13,"Expected all rejection fixtures")
for url in paths {
 let art=BottleArtwork(directory:url)
 check(art.image == nil && art.issue != nil,"Invalid resources must fail closed: \(url.lastPathComponent)")
 check(art.interiorRect == .zero,"Invalid bottle must not expose usable placement geometry")
}
check(BottleArtwork(directory:nil).image == nil,"Missing directory has no geometry fallback")
check(InsectArtwork(directory:root.appendingPathComponent("missing")).availableStyles.isEmpty,"Insect loader remains independent")
print("PASS: hash, PNG, alpha, rect, resource and symlink failures safely isolated")
''', setup)

    def test_production_never_loads_bottle_from_working_directory(self):
        self.run_swift(r'''
check(BottleArtwork.production.image == nil,"Production loads bundle resources only")
check(BottleArtwork.production.issue != nil,"Missing bundled art is explicitly unavailable")
let art=BottleArtwork(directory:root.appendingPathComponent("valid"))
check(art.interiorRect(in:NSRect(x:0,y:0,width:0,height:40)) == .zero,"Empty destination has empty interior")
check(art.interiorRect(in:NSRect(x:CGFloat.infinity,y:0,width:40,height:40)) == .zero,"Nonfinite bounds cannot produce clip geometry")
print("PASS: bundled path only and invalid geometry rejected")
''', lambda folder: shutil.copytree(folder/'valid',folder/'art/bottle'))


if __name__ == '__main__':
    unittest.main()
