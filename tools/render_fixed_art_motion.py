"""Unapproved fixed-art motion study. AppKit runtime crops only; no window/worker/save."""
import argparse
import hashlib
import json
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
let sceneURL = URL(fileURLWithPath: CommandLine.arguments[2])
let out = URL(fileURLWithPath: CommandLine.arguments[3])
guard let art = AttendantArtwork.load(from: artURL), let scene = ShrineArtwork.load(from: sceneURL) else {
    fatalError("The accepted source art or production G0 layers could not be read.")
}
let stand = art.frame(walking: false, elapsed: 0)
let width = stand.width, height = stand.height
var proposed = NSRect(x: 0, y: 0, width: width, height: height)
let cg = stand.image.cgImage(forProposedRect: &proposed, context: nil, hints: nil)!
func runs(_ y: Int) -> [(Int, Int)] {
    var result: [(Int, Int)] = [], start: Int? = nil
    for x in 0...width {
        let filled = x < width && stand.alpha[y * width + x] > 16
        if filled && start == nil { start = x }
        if !filled, let first = start { if x - first >= 8 { result.append((first, x)) }; start = nil }
    }
    return result
}
print("SOURCE_FRAME \(width)x\(height), facingLeft=\(stand.facesLeft)")
for y in stride(from: height - 200, through: height - 8, by: 16) { print("ALPHA_ROW \(y): \(runs(y))") }
if CommandLine.arguments.contains("--inspect-only") { exit(0) }
// This bounded study is specifically for the inspected 489x978 production crop.
precondition(width == 489 && height == 978 && !stand.facesLeft, "Different art requires a fresh crop review")
let lowerRuns = runs(height - 35)
precondition(lowerRuns.count == 2, "Two separate visible shoes are required")
let split = (lowerRuns[0].1 + lowerRuns[1].0) / 2
// Alpha rows stay connected through y874 and separate by y890. Keep the robe
// in the fixed upper painting, with 24 source pixels of overlap above the ankles.
let bodyCut = height - 96
let legStart = bodyCut - 24
func crop(_ rect: NSRect) -> NSImage {
    let image = cg.cropping(to: rect)!
    return NSImage(cgImage: image, size: rect.size)
}
let body = crop(NSRect(x: 0, y: 0, width: width, height: bodyCut))
let left = crop(NSRect(x: 0, y: legStart, width: split, height: height - legStart))
let right = crop(NSRect(x: split, y: legStart, width: width - split, height: height - legStart))
let distance = 80.0, lift = 32.0
let lead = 0.35, step = 0.7, duration = 2.4
func smooth(_ value: Double) -> Double { let p = min(1, max(0, value)); return p * p * (3 - 2 * p) }
struct Pose {
    var root = 0.0, leftX = 0.0, rightX = 0.0, leftY = 0.0, rightY = 0.0
    var movingLeft = false, movingRight = false
}
func pose(_ time: Double) -> Pose {
    if time <= lead { return Pose() }
    if time >= lead + 2 * step { return Pose(root: 2 * distance, leftX: 2 * distance, rightX: 2 * distance) }
    if time < lead + step {
        let p = (time - lead) / step, s = smooth(p)
        return Pose(root: distance * s, leftX: 2 * distance * s, leftY: lift * sin(.pi * p), movingLeft: true)
    }
    let p = (time - lead - step) / step, s = smooth(p)
    return Pose(root: distance + distance * s, leftX: 2 * distance,
                rightX: 2 * distance * s, rightY: lift * sin(.pi * p), movingRight: true)
}
func drawImage(_ image: NSImage, _ rect: NSRect) {
    image.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1,
               respectFlipped: true, hints: [.interpolation: NSImageInterpolation.none])
}
func drawMotion(_ time: Double, at point: NSPoint, subjectHeight: CGFloat, facingLeft: Bool) {
    let p = pose(time), scale = subjectHeight / CGFloat(height)
    NSGraphicsContext.saveGraphicsState()
    let transform = NSAffineTransform()
    transform.translateX(by: point.x + (facingLeft ? CGFloat(width) * scale : 0), yBy: point.y)
    transform.scaleX(by: facingLeft ? -scale : scale, yBy: scale)
    transform.concat()
    if !p.movingLeft && !p.movingRight {
        // Exact original pixels at both rests. Only the finished position differs.
        stand.draw(in: NSRect(x: p.root, y: 0, width: Double(width), height: Double(height)), mirrored: false)
    } else {
        let leftRect = NSRect(x: p.leftX, y: p.leftY, width: Double(split), height: Double(height - legStart))
        let rightRect = NSRect(x: Double(split) + p.rightX, y: p.rightY,
                               width: Double(width - split), height: Double(height - legStart))
        // Swinging foot is drawn last; both are behind the untouched upper painting.
        if p.movingLeft { drawImage(right, rightRect); drawImage(left, leftRect) }
        else { drawImage(left, leftRect); drawImage(right, rightRect) }
        drawImage(body, NSRect(x: p.root, y: Double(height - bodyCut), width: Double(width), height: Double(bodyCut)))
    }
    NSGraphicsContext.restoreGraphicsState()
}
let light = NSColor(calibratedWhite: 0.94, alpha: 1)
let dark = NSColor(calibratedRed: 0.12, green: 0.15, blue: 0.19, alpha: 1)
func bitmap(_ w: Int, _ h: Int, _ drawing: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor.clear.setFill(); NSRect(x: 0, y: 0, width: w, height: h).fill(using: .copy)
    drawing(); NSGraphicsContext.restoreGraphicsState(); return rep
}
func fill(_ w: Int, _ h: Int, _ color: NSColor) { color.setFill(); NSRect(x: 0, y: 0, width: w, height: h).fill() }
func text(_ value: String, _ x: CGFloat, _ y: CGFloat, _ color: NSColor, _ size: CGFloat = 11) {
    (value as NSString).draw(at: NSPoint(x: x, y: y), withAttributes:
        [.font: NSFont.systemFont(ofSize: size), .foregroundColor: color])
}
func png(_ image: NSBitmapImageRep, _ name: String) throws {
    try image.representation(using: .png, properties: [:])!.write(to: out.appendingPathComponent(name))
}
let samples: [(String, Double)] = [("原站", 0), ("左脚抬起", 0.525), ("左脚前移", 0.875),
    ("首次落地", 1.05), ("右脚抬起", 1.225), ("右脚前移", 1.575), ("再次落地", 1.75), ("回原站姿", 2.2)]
for size in [64, 128] {
    let cell = size == 64 ? 86 : 136, row = size + 40, w = cell * samples.count + 24, h = row * 2 + 52
    for (name, color, ink) in [("light", light, NSColor.darkGray), ("dark", dark, NSColor.white)] {
        let board = bitmap(w, h) {
            fill(w, h, color)
            text("待审部件小样 · 原画不变 / 两小步后回原站姿 · \(size) pt", 12, CGFloat(h - 25), ink, 14)
            for (index, sample) in samples.enumerated() {
                for direction in 0..<2 {
                    let baseline = CGFloat(22 + direction * row)
                    let travel = CGFloat(2 * distance) * CGFloat(size) / CGFloat(height)
                    let x = CGFloat(12 + index * cell) + 9 + (direction == 1 ? travel : 0)
                    drawMotion(sample.1, at: NSPoint(x: x, y: baseline + 16), subjectHeight: CGFloat(size), facingLeft: direction == 1)
                    text(sample.0, CGFloat(12 + index * cell), baseline - 1, ink, 10)
                }
            }
        }
        try png(board, "contact-\(size)pt-\(name).png")
    }
}
func sceneImage(_ time: Double, _ background: NSColor) -> NSBitmapImageRep {
    bitmap(555, 310) {
        fill(555, 310, background)
        let scale: CGFloat = 1.5
        // Identical layer bounds and draw implementation to production G0, composed without a view/window.
        for layer in scene.layers(for: "fresh") {
            let box = layer.bounds
            layer.frame.draw(in: NSRect(x: (box.minX - 55) * scale,
                y: (320 - box.maxY) * scale, width: box.width * scale, height: box.height * scale), mirrored: false)
        }
        let subjectHeight = scene.attendantHeight * scale
        let subjectWidth = subjectHeight * CGFloat(width) / CGFloat(height)
        drawMotion(time, at: NSPoint(x: (355 - 55) * scale - subjectWidth / 2, y: 10 * scale),
                   subjectHeight: subjectHeight, facingLeft: true)
        text("待审：固定原画部件小样 · 只移动原像素 · 非正式动画", 12, 290,
             background == dark ? NSColor.white : NSColor.darkGray, 13)
    }
}
for (index, sample) in samples.enumerated() {
    for (name, color) in [("light", light), ("dark", dark)] {
        try png(sceneImage(sample.1, color), "scene-\(index)-\(name).png")
    }
}
func gif(_ name: String, _ w: Int, _ h: Int, _ render: (Double) -> NSBitmapImageRep) {
    let count = 30, interval = duration / Double(count)
    let url = out.appendingPathComponent(name)
    let destination = CGImageDestinationCreateWithURL(url as CFURL, "com.compuserve.gif" as CFString, count, nil)!
    CGImageDestinationSetProperties(destination, [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)
    let properties = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: interval,
        kCGImagePropertyGIFUnclampedDelayTime: interval]] as CFDictionary
    for index in 0..<count { CGImageDestinationAddImage(destination, render(Double(index) * interval).cgImage!, properties) }
    precondition(CGImageDestinationFinalize(destination), "GIF finalization failed")
}
for (name, color) in [("light", light), ("dark", dark)] {
    gif("scene-two-steps-\(name).gif", 555, 310) { sceneImage($0, color) }
    for size in [64, 128] {
        let w = size + 80, h = size + 52
        gif("motion-\(size)pt-\(name).gif", w, h) { time in
            bitmap(w, h) {
                fill(w, h, color)
                drawMotion(time, at: NSPoint(x: 18, y: 12), subjectHeight: CGFloat(size), facingLeft: false)
                text("待审小样 / 循环边界复位", 8, CGFloat(h - 22), color == dark ? NSColor.white : NSColor.darkGray, 10)
            }
        }
    }
}
let diagnostics: [String: Any] = [
    "status": "UNAPPROVED fixed-art component study; not animation acceptance",
    "source_frame": [width, height], "body_cut_top_y": bodyCut, "leg_crop_top_y": legStart,
    "leg_split_x": split, "source_unit_root_step": distance, "source_unit_foot_lift": lift,
    "ground_contact": "During each step, the supporting shoe has constant world x and y=0; swing shoe follows an arc.",
    "identity": "No new pixels: two runtime shoe crops behind original upper-body crop; original full stand at both rests.",
    "loop": "Two steps advance the figure; GIF boundary resets the fixture position after an ending hold.",
    "background": "Actual production G0 layers and bounds through ShrineArtwork.Frame.draw; no product changes.",
    "limits": "Hidden leg and robe surfaces are absent; inspect overlap seams before approving any implementation."
]
try JSONSerialization.data(withJSONObject: diagnostics, options: [.prettyPrinted, .sortedKeys]).write(to: out.appendingPathComponent("study.json"))
print("STUDY_RENDERED: runtime crops only, no window/worker/save, NOT APPROVED. bodyCut=\(bodyCut), legStart=\(legStart), split=\(split)")
'''


def hashes(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--art', type=Path, default=ROOT / 'assets/production/A01')
    parser.add_argument('--scene', type=Path, default=ROOT / 'assets/production/scene')
    parser.add_argument('--out', type=Path, default=ROOT / 'evidence/1.0/157-fixed-motion')
    parser.add_argument('--inspect-only', action='store_true', help='Print original alpha-row crop diagnostics; produce no images.')
    args = parser.parse_args()
    art, scene, out = args.art.resolve(), args.scene.resolve(), args.out.resolve()
    if any(out == source or out.is_relative_to(source) for source in (art, scene)):
        parser.error('QA output must be outside the read-only source directories')
    source_paths = sorted([*art.glob('*.png'), *art.glob('*.json'), *scene.glob('*.png'), *scene.glob('*.json')])
    before = hashes(source_paths)
    try:
        with tempfile.TemporaryDirectory(prefix='tianmu-fixed-motion-') as directory:
            work = Path(directory)
            overlay = (ROOT / 'native/OverlayHost.swift').read_text(encoding='utf-8')
            if overlay.count('final class Host:') != 1:
                raise RuntimeError('Cannot safely isolate the read-only artwork classes')
            (work / 'Artwork.swift').write_text(overlay.split('final class Host:')[0], encoding='utf-8')
            (work / 'main.swift').write_text(SWIFT, encoding='utf-8')
            subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'ImageIO', str(work / 'Artwork.swift'),
                            str(work / 'main.swift'), '-o', str(work / 'render')], check=True)
            if not args.inspect_only:
                out.mkdir(parents=True, exist_ok=True)
            command = [str(work / 'render'), str(art), str(scene), str(out)]
            if args.inspect_only:
                command.append('--inspect-only')
            subprocess.run(command, check=True)
            if not args.inspect_only:
                (out / 'source-sha256.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if hashes(source_paths) != before:
            raise RuntimeError('Source bytes changed during the study; do not accept these outputs')


if __name__ == '__main__':
    main()
