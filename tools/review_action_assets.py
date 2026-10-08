"""Inspect real image alpha and render small light/dark composites with AppKit."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile


SWIFT = r'''
import AppKit
import ImageIO

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let reportURL = URL(fileURLWithPath: CommandLine.arguments[3])
let source = CGImageSourceCreateWithURL(sourceURL as CFURL, nil)!
let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
let rep = NSBitmapImageRep(data: try! Data(contentsOf: sourceURL))!
let width = rep.pixelsWide, height = rep.pixelsHigh
var histogram = [Int](repeating: 0, count: 256)
var boxes = [[width, height, -1, -1], [width, height, -1, -1]]
for y in 0..<height { for x in 0..<width {
    let alpha = Int((rep.colorAt(x: x, y: y)!.alphaComponent * 255).rounded())
    histogram[alpha] += 1
    for (index, threshold) in [0, 16].enumerated() where alpha > threshold {
        boxes[index][0] = min(boxes[index][0], x)
        boxes[index][1] = min(boxes[index][1], y)
        boxes[index][2] = max(boxes[index][2], x)
        boxes[index][3] = max(boxes[index][3], y)
    }
}}
func bounds(_ index: Int) -> [Int] {
    let b = boxes[index]
    if b[2] < 0 { return [] }
    return [b[0], b[1], b[2] - b[0] + 1, b[3] - b[1] + 1]
}
let bbox = bounds(0)
precondition(!bbox.isEmpty, "Source has no visible alpha")
let core = bounds(1)
let referenceHeight = CGFloat(core.isEmpty ? bbox[3] : core[3])
let referenceWidth = CGFloat(core.isEmpty ? bbox[2] : core[2])
let cropped = image.cropping(to: CGRect(x: bbox[0], y: bbox[1], width: bbox[2], height: bbox[3]))!
let sprite = NSImage(cgImage: cropped, size: NSSize(width: cropped.width, height: cropped.height))
let sizes = CommandLine.arguments[4].split(separator: ",").map { Int($0)! }
let minimumWidth = CGFloat(Double(CommandLine.arguments[5])!)
func visibleWidth(_ size: Int) -> CGFloat {
    max(CGFloat(size) * referenceWidth / referenceHeight, minimumWidth)
}
func stretched(_ size: Int) -> Bool {
    minimumWidth > CGFloat(size) * referenceWidth / referenceHeight
}
func renderWidth(_ size: Int) -> CGFloat {
    let original = CGFloat(size) * CGFloat(cropped.width) / referenceHeight
    guard stretched(size) else { return original }
    // Keep the full alpha extent: only the core's displayed width has a minimum.
    let horizontalScale = minimumWidth / (CGFloat(size) * referenceWidth / referenceHeight)
    return original * horizontalScale
}
let largest = sizes.max()!
let cellWidth = max(148, Int(ceil(sizes.map(renderWidth).max()!)) + 44)
let rowHeight = max(144, Int(ceil(CGFloat(largest) * CGFloat(cropped.height) / referenceHeight)) + 80)
let boardWidth = cellWidth * sizes.count, boardHeight = rowHeight * 2
let board = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: boardWidth, pixelsHigh: boardHeight,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: board)
NSGraphicsContext.current!.imageInterpolation = .none
func label(_ text: String, _ x: CGFloat, _ y: CGFloat, _ ink: NSColor) {
    (text as NSString).draw(at: NSPoint(x: x, y: y), withAttributes:
        [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: ink])
}
let backgrounds: [(String, NSColor, NSColor)] = [
    ("light", NSColor(calibratedWhite: 0.94, alpha: 1), .darkGray),
    ("dark", NSColor(calibratedRed: 0.12, green: 0.15, blue: 0.19, alpha: 1), .white)]
for (index, entry) in backgrounds.enumerated() {
    let rowY = CGFloat((1 - index) * rowHeight)
    entry.1.setFill()
    NSRect(x: 0, y: rowY, width: CGFloat(boardWidth), height: CGFloat(rowHeight)).fill()
    label("\(entry.0) · normal alpha · nearest", 12, rowY + CGFloat(rowHeight - 20), entry.2)
    for (column, size) in sizes.enumerated() {
        let targetHeight = CGFloat(size) * CGFloat(cropped.height) / referenceHeight
        let targetWidth = renderWidth(size)
        let x = CGFloat(column * cellWidth) + (CGFloat(cellWidth) - targetWidth) / 2
        sprite.draw(in: NSRect(x: x, y: rowY + 40, width: targetWidth, height: targetHeight),
                    from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: false, hints: nil)
        if minimumWidth > 0 {
            label("\(size) pt h / \(String(format: "%.2f", Double(visibleWidth(size)))) pt w",
                  CGFloat(column * cellWidth + 12), rowY + 14, entry.2)
            if stretched(size) {
                label("nonuniform x-scale", CGFloat(column * cellWidth + 12), rowY + 27, entry.2)
            }
        } else {
            label("\(size) pt visible", CGFloat(column * cellWidth + 12), rowY + 14, entry.2)
        }
    }
}
NSGraphicsContext.restoreGraphicsState()
try! board.representation(using: .png, properties: [:])!.write(to: outputURL)
let report: [String: Any] = [
    "source_size": [width, height], "bbox_format": "x, y, width, height; source top-left origin",
    "alpha_gt_0_bbox": bounds(0), "alpha_gt_16_bbox": bounds(1),
    "alpha_histogram": histogram, "fully_transparent_pixels": histogram[0],
    "alpha_1_to_16_pixels": histogram[1...16].reduce(0, +),
    "alpha_17_to_254_pixels": histogram[17...254].reduce(0, +),
    "fully_opaque_pixels": histogram[255], "render_crop": bounds(0),
    "render_heights_pt": sizes, "output_scale_pixels_per_point": 1,
    "height_reference": "alpha>16 bounding-box height; full alpha>0 extent still composited",
    "minimum_visible_width_pt": Double(minimumWidth),
    "width_reference": "alpha>16 bounding-box width; full alpha>0 extent still composited",
    "render_visible_widths_pt": sizes.map { Double(visibleWidth($0)) },
    "render_full_alpha_widths_pt": sizes.map { Double(renderWidth($0)) },
    "nonuniform_width_applied": sizes.map(stretched),
    "sampling": "nearest", "compositing": "normal sourceOver alpha",
    "renderer": "Swift/AppKit", "no_window": true, "no_worker": true, "no_save_access": true]
try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: reportURL)
print("ACTION_ASSET_REVIEW_PASS: \(width)x\(height), alpha>0=\(bounds(0)), alpha>16=\(bounds(1)); \(sizes.map(String.init).joined(separator: "/"))pt light/dark; no window, worker or save")
if minimumWidth > 0 {
    print("DISPLAY_WIDTH_ONLY: min visible width \(minimumWidth)pt; widths \(sizes.map { Double(visibleWidth($0)) }); nonuniform \(sizes.map(stretched)); source alpha unchanged")
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Original image to inspect without modifying it.')
    parser.add_argument('--output', required=True, type=Path, help='Evidence file prefix; writes .png and .json.')
    parser.add_argument('--heights', nargs='+', type=int, default=[30, 45, 64],
                        help='Positive display heights in points (default: 30 45 64).')
    parser.add_argument('--min-width', type=float, default=0,
                        help='Minimum alpha>16 core width in points; stretches display width only (default: 0).')
    args = parser.parse_args()
    if any(height <= 0 for height in args.heights):
        parser.error('Display heights must be positive.')
    if not math.isfinite(args.min_width) or args.min_width < 0:
        parser.error('Minimum width must be a finite nonnegative number.')
    source = args.input.resolve()
    output = args.output.resolve()
    png_path, report_path = output.with_suffix('.png'), output.with_suffix('.json')
    if source == png_path or source == report_path:
        parser.error('Evidence output must not overwrite the original image.')
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='tianmu-action-asset-review-') as folder:
        work = Path(folder)
        swift = work / 'main.swift'
        swift.write_text(SWIFT)
        executable = work / 'review'
        subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'ImageIO',
                        str(swift), '-o', str(executable)], check=True)
        subprocess.run([str(executable), str(source), str(png_path), str(report_path),
                        ','.join(map(str, args.heights)), str(args.min_width)], check=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, 'Source image changed during review'
    report = json.loads(report_path.read_text())
    report.update(source_file=str(source), source_sha256=digest, source_bytes_preserved=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
