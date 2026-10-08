"""Generated product identity, source preservation and all actual ICNS sizes.

Uses disposable directories and an AppKit bitmap probe only; never NSApplication,
windows, the gameplay worker, or any saved game.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/production/brand'
SPEC = importlib.util.spec_from_file_location('brand_packaging_builder', ROOT / 'tools/build_native.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def snapshot(folder):
    if not folder.exists():
        return None
    return {str(path.relative_to(folder)): ('directory' if path.is_dir() else
            hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(folder.rglob('*'))}


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'), 'macOS + Swift required')
class BrandPackagingTests(unittest.TestCase):
    def test_bundle_display_names_change_without_changing_runtime_identity(self):
        normal = BUILDER.bundle_info('15.0', embed_python=True)
        qa = BUILDER.bundle_info('15.0', '/isolated/state.json', embed_python=True)
        for key in ['CFBundleName', 'CFBundleDisplayName']:
            self.assertEqual(normal[key], '灶神')
            self.assertEqual(qa[key], '灶神测试')
        self.assertEqual(normal['CFBundleExecutable'], 'Tianmu')
        self.assertEqual(normal['CFBundleIdentifier'], 'local.tianmu.garden')
        self.assertEqual(qa['CFBundleIdentifier'], 'local.tianmu.garden.qa')
        self.assertEqual(normal['CFBundleShortVersionString'], '1.0.6')
        self.assertEqual(normal['CFBundleVersion'], '26')
        self.assertEqual(normal['TianmuPythonExecutable'], 'Runtime/bin/python3')
        self.assertNotIn('TianmuQASaveFile', normal)

    def test_invalid_source_never_creates_or_changes_resources(self):
        cases = ['missing-source', 'missing-png', 'hash', 'dimensions', 'provenance', 'prompt',
                 'generation-png-mismatch', 'truncated-png', 'symlink-png']
        for case in cases:
            for existing in [False, True]:
                with self.subTest(case=case, existing=existing), tempfile.TemporaryDirectory() as directory:
                    folder = Path(directory)
                    source = folder / 'source'
                    shutil.copytree(SOURCE, source)
                    manifest = json.loads((source / 'manifest.json').read_text())
                    png = source / manifest['file']
                    provenance = source / manifest['provenance']
                    if case == 'missing-source':
                        shutil.rmtree(source)
                    elif case == 'missing-png':
                        png.unlink()
                    elif case == 'hash':
                        manifest['sha256'] = '0' * 64
                    elif case == 'dimensions':
                        manifest['pixelSize'] = [1024, 1024]
                    elif case == 'provenance':
                        provenance.write_text('{}')
                    elif case == 'prompt':
                        (source / manifest['prompt']).write_text('Changed prompt')
                    elif case == 'generation-png-mismatch':
                        record = json.loads(provenance.read_text())
                        record['sha256'] = '0' * 64
                        provenance.write_text(json.dumps(record))
                        manifest['provenance_sha256'] = hashlib.sha256(provenance.read_bytes()).hexdigest()
                    elif case == 'truncated-png':
                        png.write_bytes(png.read_bytes()[:64])
                        manifest['sha256'] = hashlib.sha256(png.read_bytes()).hexdigest()
                        record = json.loads(provenance.read_text())
                        record['sha256'] = manifest['sha256']
                        provenance.write_text(json.dumps(record))
                        manifest['provenance_sha256'] = hashlib.sha256(provenance.read_bytes()).hexdigest()
                    elif case == 'symlink-png':
                        png.unlink()
                        png.symlink_to(SOURCE / manifest['file'])
                    if source.exists():
                        (source / 'manifest.json').write_text(json.dumps(manifest))
                    resources = folder / 'Resources'
                    if existing:
                        (resources / 'art/brand').mkdir(parents=True)
                        (resources / 'art/brand/previous.png').write_bytes(b'previous art')
                        (resources / 'Tianmu.icns').write_bytes(b'previous icon')
                    before = snapshot(resources)
                    with patch.object(BUILDER.subprocess, 'run', side_effect=AssertionError('Invalid source reached conversion')):
                        with self.assertRaises(ValueError):
                            BUILDER.build_brand_icon(resources, source)
                    self.assertEqual(snapshot(resources), before)

    def test_failed_conversion_preserves_existing_icon_and_brand(self):
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory) / 'Resources'
            (resources / 'art/brand').mkdir(parents=True)
            (resources / 'art/brand/previous.png').write_bytes(b'previous art')
            (resources / 'Tianmu.icns').write_bytes(b'previous icon')
            before = snapshot(resources)
            with patch.object(BUILDER.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'swiftc')):
                with self.assertRaises(subprocess.CalledProcessError):
                    BUILDER.build_brand_icon(resources)
            self.assertEqual(snapshot(resources), before)

    def test_install_failure_or_interrupt_restores_prior_brand_and_icon(self):
        for entry, error in [('brand', OSError), ('Tianmu.icns', OSError),
                             ('brand', KeyboardInterrupt), ('Tianmu.icns', KeyboardInterrupt)]:
            with self.subTest(entry=entry, error=error.__name__), tempfile.TemporaryDirectory() as directory:
                resources = Path(directory) / 'Resources'
                (resources / 'art/brand').mkdir(parents=True)
                (resources / 'art/brand/previous.png').write_bytes(b'previous art')
                (resources / 'Tianmu.icns').write_bytes(b'previous icon')
                before = snapshot(resources)
                rename = Path.rename

                def interrupted(path, destination):
                    if path.name == entry and path.parent.name.startswith('brand-'):
                        raise error('synthetic final installation interruption')
                    return rename(path, destination)

                with patch.object(Path, 'rename', autospec=True, side_effect=interrupted):
                    with self.assertRaises(error):
                        BUILDER.build_brand_icon(resources)
                self.assertEqual(snapshot(resources), before)

    def test_failed_rollback_retains_recoverable_original_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory) / 'Resources'
            (resources / 'art/brand').mkdir(parents=True)
            (resources / 'art/brand/previous.png').write_bytes(b'previous art')
            (resources / 'Tianmu.icns').write_bytes(b'previous icon')
            rename = Path.rename

            def interrupted(path, destination):
                if ((path.name == 'Tianmu.icns' and path.parent.name.startswith('brand-'))
                        or path.name == 'previous-brand'):
                    raise OSError('synthetic install and restore failure')
                return rename(path, destination)

            with patch.object(Path, 'rename', autospec=True, side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, 'recovery files retained'):
                    BUILDER.build_brand_icon(resources)
            backups = list(resources.glob('brand-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'previous-brand/previous.png').read_bytes(), b'previous art')
            self.assertEqual((backups[0] / 'previous.icns').read_bytes(), b'previous icon')

    def test_every_packaged_icon_size_matches_generated_source_with_visible_alpha(self):
        before = snapshot(SOURCE)
        manifest = json.loads((SOURCE / 'manifest.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            resources = folder / 'Resources'
            BUILDER.build_brand_icon(resources)
            owned_names = ['manifest.json', manifest['file'], manifest['provenance'], manifest['prompt']]
            self.assertEqual(snapshot(resources / 'art/brand'), {name: before[name] for name in owned_names})
            iconset = folder / 'decoded.iconset'
            subprocess.run(['iconutil', '-c', 'iconset', str(resources / 'Tianmu.icns'), '-o', str(iconset)], check=True)
            expected = {f'icon_{size}x{size}{"@2x" if scale == 2 else ""}.png': size * scale
                        for size in [16, 32, 128, 256, 512] for scale in [1, 2]}
            self.assertEqual({path.name for path in iconset.iterdir()}, set(expected))
            (folder / 'sizes.json').write_text(json.dumps(expected))
            swift = folder / 'main.swift'
            swift.write_text(r'''
import AppKit
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let sizes=try! JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("sizes.json"))) as! [String:Int]
let source=NSImage(contentsOf:URL(fileURLWithPath:CommandLine.arguments[2]))!
for (name,pixels) in sizes {
    let data=try! Data(contentsOf:root.appendingPathComponent("decoded.iconset/"+name))
    let actual=NSBitmapImageRep(data:data)!
    assert(actual.pixelsWide == pixels && actual.pixelsHigh == pixels,"Wrong ICNS dimensions")
    let expected=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:expected)
    NSGraphicsContext.current!.imageInterpolation = .high
    source.draw(in:NSRect(x:0,y:0,width:pixels,height:pixels),from:.zero,operation:.copy,fraction:1)
    NSGraphicsContext.restoreGraphicsState()
    // PNG decoding applies its color profile. Compare like with like instead
    // of comparing a decoded PNG to an unencoded device-RGB bitmap.
    let roundtrip=NSBitmapImageRep(data:expected.representation(using:.png,properties:[:])!)!
    var visible=0,clear=0,colorSamples=0
    for y in stride(from:0,to:pixels,by:max(1,pixels/16)) {
        for x in stride(from:0,to:pixels,by:max(1,pixels/16)) {
            let a=actual.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
            let b=roundtrip.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
            if a.alphaComponent > 0.5 { visible += 1 }
            if a.alphaComponent < 0.01 { clear += 1 }
            assert(abs(a.alphaComponent-b.alphaComponent)<0.02,"ICNS alpha differs from production PNG")
            // iconutil's legacy 16/32 entries alter unpremultiplied edge RGB.
            // Require near-opaque colors there; modern PNG entries retain the
            // broader color check. Alpha remains checked at every sample.
            let legacy = name == "icon_16x16.png" || name == "icon_32x32.png"
            if a.alphaComponent > (legacy ? 0.98 : 0.9) {
                colorSamples += 1
                assert(abs(a.redComponent-b.redComponent)<0.02 && abs(a.greenComponent-b.greenComponent)<0.02 && abs(a.blueComponent-b.blueComponent)<0.02,"ICNS colors differ from production PNG")
            }
        }
    }
    assert(visible>30 && clear>5,"Each size must retain the painted subject and transparent outer corners")
    assert(colorSamples>30,"Each size must compare actual subject colors")
}
assert(NSApp == nil,"Never start an application during icon verification")
print("PASS: all 10 ICNS representations match the generated production PNG")
''')
            probe = folder / 'probe'
            subprocess.run(['swiftc', '-framework', 'AppKit', str(swift), '-o', str(probe)], check=True)
            result = subprocess.run([str(probe), str(folder), str(SOURCE / manifest['file'])],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('all 10 ICNS representations', result.stdout)
        self.assertEqual(snapshot(SOURCE), before)


if __name__ == '__main__':
    unittest.main()
