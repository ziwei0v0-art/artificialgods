"""QA-only AppKit renders of a real four-frame A01 manifest; no window or worker."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SWIFT = r'''
import AppKit
import ImageIO
import Foundation
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let artURL = URL(fileURLWithPath: CommandLine.arguments[1])
let out = URL(fileURLWithPath: CommandLine.arguments[2])
let fps = Double(CommandLine.arguments[3])!
guard let art = AttendantArtwork.load(from: artURL), art.hasWalkFrames else {
    fputs("REFUSED: production renderer did not load the four walk frames.\n", stderr)
    exit(2)
}
let light = NSColor(calibratedWhite: 0.95, alpha: 1)
let dark = NSColor(calibratedRed: 0.12, green: 0.15, blue: 0.19, alpha: 1)
func bitmap(_ width: Int, _ height: Int, _ draw: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor.clear.setFill(); NSRect(x: 0, y: 0, width: width, height: height).fill(using: .copy)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    return rep
}
func png(_ rep: NSBitmapImageRep, _ name: String) throws {
    try rep.representation(using: .png, properties: [:])!.write(to: out.appendingPathComponent(name))
}
func label(_ text: String, _ x: CGFloat, _ y: CGFloat, _ color: NSColor) {
    (text as NSString).draw(at: NSPoint(x: x, y: y), withAttributes:
        [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: color])
}
// Exact production frame selection. The midpoint avoids floating point boundary ambiguity.
let sequence = [0, 1, 2, 3, -1, 0, 1, 2, 3]
let frames = sequence.map { art.frame(walking: $0 >= 0, elapsed: Double(max(0, $0)) / fps + 0.25 / fps) }
for height in [64, 128] {
    let subjectHeight = CGFloat(height)
    let cell = max(70, Int(ceil(frames.map { subjectHeight * CGFloat($0.width) / CGFloat($0.height) }.max()!)) + 20)
    let row = height + 42, width = cell * 9 + 32, canvasHeight = row * 2 + 42
    for (name, background, ink) in [("light", light, NSColor.darkGray), ("dark", dark, NSColor.white)] {
        let rep = bitmap(width, canvasHeight) {
            background.setFill(); NSRect(x: 0, y: 0, width: width, height: canvasHeight).fill()
            label("QA fixture | production frame.draw | 4 walk / stand / 4 walk | \(height) pt", 16, CGFloat(canvasHeight - 23), ink)
            for (directionIndex, faceLeft) in [(0, true), (1, false)] {
                let bottom = CGFloat(16 + directionIndex * row)
                for (index, frame) in frames.enumerated() {
                    let subjectWidth = subjectHeight * CGFloat(frame.width) / CGFloat(frame.height)
                    let x = CGFloat(16 + index * cell) + (CGFloat(cell) - subjectWidth) / 2
                    frame.draw(in: NSRect(x: x, y: bottom + 20, width: subjectWidth, height: subjectHeight),
                               mirrored: faceLeft != frame.facesLeft)
                    let title = sequence[index] < 0 ? "stand" : "walk \(sequence[index] + 1)"
                    label("\(faceLeft ? "L" : "R") \(title)", CGFloat(16 + index * cell), bottom + 3, ink)
                }
            }
        }
        try png(rep, "contact-\(height)pt-\(name).png")
    }
}
// All motion below is an explicit synthetic service-snapshot fixture. There is no service process.
let view = TianmuView(frame: NSRect(x: 0, y: 0, width: 370, height: 190))
view.persistLegacyFrame = false
view.attendantArtwork = art
view.offeringPlate = true
func snapshot(_ action: String, _ serial: Int, _ elapsed: Double, _ duration: Double, _ clock: Double) {
    view.updateAnimation(elapsed: clock)
    precondition(view.applyRoutine(["action": action, "action_serial": serial,
        "action_elapsed": elapsed, "action_duration": duration,
        "progress": duration == 0 ? 0 : elapsed / duration, "fruit_stage": "fresh"]))
}
// Prime through two actual service actions so the repeating loop begins/ends at the same endpoint.
var clock = 0.0
for serial in 0..<2 {
    snapshot("walk", serial, 0, 5, clock)
    clock += 5
    snapshot("walk", serial, 5, 5, clock)
}
func scene(_ background: NSColor) -> NSBitmapImageRep {
    bitmap(370, 218) {
        // Real TianmuView.draw uses its production 370x190 scene coordinates.
        view.draw(view.bounds)
        NSGraphicsContext.current!.cgContext.setBlendMode(.destinationOver)
        background.setFill(); NSRect(x: 0, y: 0, width: 370, height: 218).fill()
        NSGraphicsContext.current!.cgContext.setBlendMode(.normal)
        label("QA fixture | service walk | virtual time | no game", 10, 198,
              background == dark ? NSColor.white : NSColor.darkGray)
    }
}
let gifURL = out.appendingPathComponent("scene-service-walk-loop.gif")
let walkCount = Int(ceil(5 * fps)), holdCount = max(1, Int(ceil(fps)))
let frameCount = (walkCount + holdCount) * 2
let destination = CGImageDestinationCreateWithURL(gifURL as CFURL, "com.compuserve.gif" as CFString, frameCount, nil)!
CGImageDestinationSetProperties(destination, [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)
let frameProperties = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: 1 / fps,
    kCGImagePropertyGIFUnclampedDelayTime: 1 / fps]] as CFDictionary
for leg in 0..<2 {
    let serial = 2 + leg * 2, start = clock
    for index in 0..<walkCount {
        let elapsed = min(5, Double(index) / fps)
        snapshot("walk", serial, elapsed, 5, start + elapsed)
        let image = scene(light)
        CGImageDestinationAddImage(destination, image.cgImage!, frameProperties)
        if index == walkCount / 2 {
            let direction = leg == 0 ? "left" : "right"
            try png(image, "scene-\(direction)-light.png")
            try png(scene(dark), "scene-\(direction)-dark.png")
        }
    }
    clock = start + 5
    snapshot("idle", serial + 1, 0, 0, clock)
    for _ in 0..<holdCount {
        CGImageDestinationAddImage(destination, scene(light).cgImage!, frameProperties)
    }
    clock += Double(holdCount) / fps
}
guard CGImageDestinationFinalize(destination) else { fatalError("GIF finalization failed") }
print("QA_RENDER_OK: 4 contact sheets, 4 real-scene stills, 1 GIF; fixture snapshots only; no window/worker/save")
'''


def input_files(directory):
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    walk = manifest.get('walk')
    if not isinstance(walk, dict) or not isinstance(walk.get('frames'), list) or len(walk['frames']) != 4:
        raise ValueError('REFUSED: manifest must declare exactly four real walk frames; no substitute animation is rendered.')
    fps = walk.get('fps')
    if type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 60:
        raise ValueError('REFUSED: walk.fps must be a finite number in (0, 60].')
    paths = [manifest_path]
    for spec in [manifest.get('stand'), *walk['frames']]:
        if not isinstance(spec, dict) or not isinstance(spec.get('file'), str):
            raise ValueError('REFUSED: stand and all walk frames must name actual PNG files.')
        source = (directory / spec['file']).resolve()
        if not source.is_relative_to(directory) or source.suffix.lower() != '.png' or not source.is_file():
            raise ValueError('REFUSED: frame is missing, outside --art, or is not a PNG: ' + spec['file'])
        paths.append(source)
    return float(fps), paths


def digest(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--art', type=Path, default=ROOT / 'assets/production/A01')
    parser.add_argument('--out', type=Path, default=ROOT / 'evidence/1.0/walk-art-qa')
    parser.add_argument('--compile-only', action='store_true', help='Compile the actual renderer and QA helper; do not load art or render.')
    args = parser.parse_args()
    art, out = args.art.resolve(), args.out.resolve()
    if out == art or out.is_relative_to(art):
        parser.error('--out must be outside the read-only art directory')
    try:
        fps, paths = (0, []) if args.compile_only else input_files(art)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')
    before = digest(paths)
    try:
        with tempfile.TemporaryDirectory(prefix='tianmu-walk-qa-') as folder:
            work = Path(folder)
            source = (ROOT / 'native/OverlayHost.swift').read_text(encoding='utf-8')
            marker = 'final class Host:'
            if source.count(marker) != 1:
                raise RuntimeError('Cannot safely isolate production rendering classes from the host.')
            (work / 'Scene.swift').write_text(source.split(marker)[0], encoding='utf-8')
            (work / 'main.swift').write_text(SWIFT, encoding='utf-8')
            subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'ImageIO',
                            str(work / 'Scene.swift'), str(work / 'main.swift'), '-o', str(work / 'render')], check=True)
            if args.compile_only:
                print('COMPILE_ONLY_OK: actual renderer + helper compiled; no art loaded or rendered; not visual acceptance.')
                return
            out.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(work / 'render'), str(art), str(out), str(fps)], check=True)
            (out / 'render-fixture.json').write_text(json.dumps({
                'kind': 'QA render; explicit synthetic service snapshots; not runtime acceptance',
                'art': str(art), 'input_sha256': before, 'manifest_fps': fps,
                'contact_sequence': [1, 2, 3, 4, 'stand', 1, 2, 3, 4],
                'contact_heights_pt': [64, 128], 'scene_fixture': 'walk 5s left, idle 1s, walk 5s right, idle 1s',
                'renderer': 'native/OverlayHost.swift: AttendantArtwork.Frame.draw, TianmuView.draw/applyRoutine/updateAnimation',
                'no_window': True, 'no_worker': True, 'no_save_access': True,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if digest(paths) != before:
            raise RuntimeError('Source input bytes changed during QA rendering; outputs must not be accepted.')


if __name__ == '__main__':
    main()
