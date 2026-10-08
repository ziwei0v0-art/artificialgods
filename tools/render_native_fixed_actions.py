"""Review fixed catch through actual TianmuView/G0 using isolated service snapshots."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/1.0/158-native-catch'
INCOMING = ROOT / 'assets/incoming/A01_action_parts_20261001'
FIXED_ACTIONS = {
    'sourceSize': [489, 978],
    'catch': {
        'nearSleeve': {
            'mask': [[0, 583], [235, 583], [235, 610], [265, 640], [265, 734],
                     [250, 766], [218, 803], [218, 846], [212, 861], [0, 861]],
            'pivot': [217, 591], 'hand': [181, 797],
        },
        'torsoUnderlay': {
            'file': 'torso-underlay-v01-original.png', 'sourceRect': [364, 548, 394, 518],
            'bounds': [194, 555, 218, 313],
            'bodyArea': [[218, 568], [330, 566], [360, 620], [390, 862],
                         [195, 862], [190, 758], [205, 646]],
        },
        'net': {'file': 'net-v01-original.png', 'sourceRect': [279, 116, 555, 1306],
                'height': 400, 'grip': [0.32, 0.89], 'rotation': 110},
    },
}

SWIFT = r'''
import AppKit
import ImageIO
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let art = AttendantArtwork.load(from: URL(fileURLWithPath: CommandLine.arguments[1]))!
let shrine = ShrineArtwork.load(from: URL(fileURLWithPath: CommandLine.arguments[2]))!
let output = URL(fileURLWithPath: CommandLine.arguments[3])
precondition(art.hasWalkMotion && !art.hasWalkFrames)
let backgrounds: [(String, NSColor, NSColor)] = [
    ("light", NSColor(calibratedWhite: 0.94, alpha: 1), .darkGray),
    ("dark", NSColor(calibratedRed: 0.12, green: 0.15, blue: 0.19, alpha: 1), .white)]
func bitmap(_ w: Int, _ h: Int, _ draw: () -> Void) -> NSBitmapImageRep {
    let b = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: b)
    NSColor.clear.setFill(); NSRect(x: 0, y: 0, width: w, height: h).fill(using: .copy)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    return b
}
func png(_ b: NSBitmapImageRep, _ name: String) {
    try! b.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(name))
}
func bytes(_ b: NSBitmapImageRep) -> Data {
    Data(bytes: b.bitmapData!, count: b.bytesPerRow * b.pixelsHigh)
}
func snapshot(_ action: String, _ serial: Int, _ elapsed: Double, _ duration: Double) -> [String: Any] {
    ["action": action, "action_serial": serial, "action_elapsed": elapsed,
     "action_duration": duration, "progress": duration > 0 ? elapsed / duration : 0,
     "fruit_stage": "fresh"]
}
func feed(_ v: TianmuView, _ action: String, _ serial: Int,
          _ elapsed: Double, _ duration: Double, _ clock: Double) {
    v.updateAnimation(elapsed: clock)
    precondition(v.applyRoutine(snapshot(action, serial, elapsed, duration)), "Rejected fixture snapshot")
}
func rawRender(_ v: TianmuView) -> NSBitmapImageRep {
    let w = Int(ceil(v.bounds.width)), h = Int(ceil(v.bounds.height))
    return bitmap(w, h) { v.draw(v.bounds) }
}
func composite(_ b: NSBitmapImageRep, _ bg: NSColor) -> NSBitmapImageRep {
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: b)
    NSGraphicsContext.current!.cgContext.setBlendMode(.destinationOver)
    bg.setFill(); NSRect(x: 0, y: 0, width: b.pixelsWide, height: b.pixelsHigh).fill()
    NSGraphicsContext.restoreGraphicsState()
    return b
}
func render(_ v: TianmuView, _ bg: NSColor) -> NSBitmapImageRep {
    composite(rawRender(v), bg)
}
struct AlphaEdges {
    let any: [Int], visible: [Int], rightEdgeMaximum: Int
    var rightGap: Int { visible.isEmpty ? 0 : anyWidth - visible[0] - visible[2] }
    let anyWidth: Int
}
func alphaEdges(_ b: NSBitmapImageRep) -> AlphaEdges {
    precondition(b.samplesPerPixel == 4 && !b.bitmapFormat.contains(.alphaFirst))
    var boxes = [[b.pixelsWide, b.pixelsHigh, -1, -1], [b.pixelsWide, b.pixelsHigh, -1, -1]]
    var edge = 0
    for y in 0..<b.pixelsHigh { for x in 0..<b.pixelsWide {
        let alpha = Int(b.bitmapData![y * b.bytesPerRow + x * 4 + 3])
        if x == b.pixelsWide - 1 { edge = max(edge, alpha) }
        for (index, threshold) in [0, 16].enumerated() where alpha > threshold {
            boxes[index][0] = min(boxes[index][0], x); boxes[index][1] = min(boxes[index][1], y)
            boxes[index][2] = max(boxes[index][2], x); boxes[index][3] = max(boxes[index][3], y)
        }
    }}
    func box(_ index: Int) -> [Int] {
        let b = boxes[index]
        return b[2] < 0 ? [] : [b[0], b[1], b[2]-b[0]+1, b[3]-b[1]+1]
    }
    return AlphaEdges(any: box(0), visible: box(1), rightEdgeMaximum: edge, anyWidth: b.pixelsWide)
}
func prepared(_ size: Int, _ direction: String) -> (TianmuView, Double, Int) {
    let scale = CGFloat(size) / shrine.attendantHeight
    let v = TianmuView(frame: NSRect(x: 0, y: 0,
        width: TianmuView.sceneCanvas.width * scale, height: TianmuView.sceneCanvas.height * scale))
    v.persistLegacyFrame = false; v.attendantArtwork = art; v.shrineArtwork = shrine
    // Reach each facing through the real presentation's completed service walks.
    feed(v, "walk", 1, 0, 5, 0); feed(v, "walk", 1, 5, 5, 5)
    if direction == "right" {
        feed(v, "walk", 2, 0, 5, 5); feed(v, "walk", 2, 5, 5, 10)
        precondition(v.routinePresentation.pose(at: 10).direction > 0)
        return (v, 10, 3)
    }
    precondition(v.routinePresentation.pose(at: 5).direction < 0)
    return (v, 5, 2)
}
func mouse(_ point: NSPoint, _ time: Double) -> NSEvent {
    NSEvent.mouseEvent(with: .leftMouseDown, location: point, modifierFlags: [], timestamp: time,
        windowNumber: 0, context: nil, eventNumber: 1, clickCount: 1, pressure: 1)!
}
func headPoint(_ v: TianmuView, _ stand: NSRect) -> NSPoint {
    let y = stand.maxY - stand.height * 0.3
    for x in stride(from: stand.midX - stand.width * 0.2, through: stand.midX + stand.width * 0.2, by: 1) {
        let p = NSPoint(x: x, y: y)
        if v.subject(at: p) == "attendant" { return p }
    }
    fatalError("No actual head pixel available for isolated press")
}
func gif(_ frames: [NSBitmapImageRep], _ name: String) {
    let destination = CGImageDestinationCreateWithURL(output.appendingPathComponent(name) as CFURL,
        "com.compuserve.gif" as CFString, frames.count, nil)!
    CGImageDestinationSetProperties(destination,
        [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)
    let properties = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: 0.05,
        kCGImagePropertyGIFUnclampedDelayTime: 0.05]] as CFDictionary
    for frame in frames { CGImageDestinationAddImage(destination, frame.cgImage!, properties) }
    precondition(CGImageDestinationFinalize(destination))
}
struct ReviewRow {
    let direction: String
    let pictures: [CGImage]
    let labels: [String]
}
var checks: [[String: Any]] = []
var frameBounds: [[String: Any]] = []
var edgeChecks: [[String: Any]] = []
func sequence(_ size: Int, _ direction: String, _ theme: String, _ bg: NSColor, _ interrupted: Bool) -> ReviewRow {
    let (v, start, serial) = prepared(size, direction)
    let standBox = v.attendantBounds
    let stand = bytes(render(v, bg))
    feed(v, "catch", serial, 0, 3, start)
    precondition(v.unavailableRoutineAction == nil, "fixedActions catch is not connected")
    let kind = interrupted ? "press-switch" : "catch"
    var frames: [NSBitmapImageRep] = [], union = standBox
    var held: Data?
    var edgeFrames: [Int] = [], closestRightGap = Int.max
    for index in 0..<80 {
        let elapsed = Double(index) / 20, clock = start + elapsed
        v.updateAnimation(elapsed: clock)
        if index < (interrupted ? 24 : 60), index % 20 == 0 {
            feed(v, "catch", serial, elapsed, 3, clock)
        }
        if interrupted {
            if index == 16 {
                let before = bytes(render(v, bg))
                precondition(before != stand, "Catch did not visibly animate before press")
                v.mouseDown(with: mouse(headPoint(v, standBox), clock))
                held = bytes(render(v, bg))
                precondition(held == before, "Press changed the first held pose")
            }
            if index == 24 { feed(v, "idle", serial + 1, 0, 0, clock) }
            if index == 40 {
                v.cancelInteraction()
                precondition(bytes(render(v, bg)) == held!, "Release discarded the held catch pose")
            }
        } else {
            if index == 16 {
                let before = bytes(render(v, bg))
                feed(v, "catch", serial, 0, 3, clock)
                precondition(bytes(render(v, bg)) == before, "Duplicate catch receipt reset its pixels")
            }
            if index == 60 {
                feed(v, "catch", serial, 3, 3, clock)
                feed(v, "idle", serial + 1, 0, 1, clock)
            }
        }
        let raw = rawRender(v), alpha = alphaEdges(raw)
        if alpha.rightEdgeMaximum > 0 { edgeFrames.append(index) }
        closestRightGap = min(closestRightGap, alpha.rightGap)
        let currentBounds = v.attendantBounds
        frameBounds.append(["case": kind, "direction": direction, "size_pt": size,
            "background": theme, "frame": index, "elapsed": elapsed,
            "scene_alpha_gt0_bbox": alpha.any, "scene_alpha_gt16_bbox": alpha.visible,
            "rightmost_canvas_column_alpha_max": alpha.rightEdgeMaximum,
            "right_gap_after_alpha_gt16_px": alpha.rightGap,
            "attendant_geometry_bbox": [Double(currentBounds.minX), Double(currentBounds.minY),
                Double(currentBounds.width), Double(currentBounds.height)]])
        let picture = composite(raw, bg)
        if interrupted, (16..<40).contains(index) {
            precondition(bytes(picture) == held!, "A new service action changed the pressed pose")
        }
        if !interrupted, index == 21 { precondition(bytes(picture) != stand, "Catch must move in actual scene") }
        if index == (interrupted ? 44 : 64) {
            precondition(bytes(picture) == stand, "Finished/released catch did not restore the original stand")
        }
        union = union.union(v.attendantBounds)
        frames.append(picture)
        if index == (interrupted ? 24 : 21) {
            png(picture, "scene-\(kind)-\(size)pt-\(direction)-\(theme).png")
        }
        if !interrupted, direction == "right", index == 44 {
            png(picture, "edge-audit-\(size)pt-right-\(theme)-2.2s.png")
        }
    }
    gif(frames, "scene-\(kind)-\(size)pt-\(direction)-\(theme).gif")
    let first = frames[0]
    let padded = union.insetBy(dx: -6, dy: -6)
    let crop = NSRect(x: floor(padded.minX), y: floor(CGFloat(first.pixelsHigh) - padded.maxY),
        width: ceil(padded.width), height: ceil(padded.height))
        .intersection(NSRect(x: 0, y: 0, width: first.pixelsWide, height: first.pixelsHigh))
    let indices = interrupted ? [0, 7, 16, 24, 40, 42, 44, 60] : [0, 7, 16, 21, 30, 44, 53, 60]
    let labels = interrupted ? ["0.0s", "0.35s", "按下0.8s", "切idle1.2s", "松开2.0s", "静收2.1s", "复原2.2s", "待机3.0s"]
        : ["0.0s", "0.35s", "重复0.8s", "1.05s", "1.5s", "2.2s", "2.65s", "停下3.0s"]
    checks.append(["case": kind, "direction": direction, "size_pt": size, "background": theme,
        "result": "PASS", "frames": frames.count, "source": "actual TianmuView; synthetic service snapshots",
        "attendant_bounds_union": [Double(union.minX), Double(union.minY), Double(union.width), Double(union.height)],
        "view_size": [Double(v.bounds.width), Double(v.bounds.height)]])
    edgeChecks.append(["case": kind, "direction": direction, "size_pt": size, "background": theme,
        "frames_with_alpha_at_rightmost_canvas_column": edgeFrames,
        "minimum_right_gap_after_alpha_gt16_px": closestRightGap,
        "alpha_source": "actual raw TianmuView/G0 rendering before background compositing"])
    return ReviewRow(direction: direction, pictures: indices.map { frames[$0].cgImage!.cropping(to: crop)! }, labels: labels)
}
func contact(_ rows: [ReviewRow], _ size: Int, _ theme: String, _ bg: NSColor, _ ink: NSColor, _ interrupted: Bool) {
    let cellWidth = rows.flatMap(\.pictures).map(\.width).max()! + 12
    let cellHeight = rows.flatMap(\.pictures).map(\.height).max()! + 30
    let width = cellWidth * 8 + 12, height = cellHeight * 2 + 36
    func label(_ text: String, _ x: CGFloat, _ y: CGFloat) {
        (text as NSString).draw(at: NSPoint(x: x, y: y), withAttributes:
            [.font: NSFont.systemFont(ofSize: 10), .foregroundColor: ink])
    }
    let b = bitmap(width, height) {
        bg.setFill(); NSRect(x: 0, y: 0, width: width, height: height).fill()
        label("真实TianmuView / G0 · \(size) pt · \(interrupted ? "按压中切换与松开" : "捕虫3秒、重复回执与待机")", 12, CGFloat(height - 22))
        for (rowIndex, row) in rows.enumerated() {
            for (index, picture) in row.pictures.enumerated() {
                let x = CGFloat(12 + index * cellWidth), y = CGFloat(12 + (1-rowIndex) * cellHeight)
                NSImage(cgImage: picture, size: NSSize(width: picture.width, height: picture.height))
                    .draw(in: NSRect(x: x, y: y + 20, width: CGFloat(picture.width), height: CGFloat(picture.height)))
                label("\(row.direction == "left" ? "向左" : "向右") \(row.labels[index])", x, y)
            }
        }
    }
    png(b, "contact-\(interrupted ? "press-switch" : "catch")-\(size)pt-\(theme).png")
}
for size in [64, 128] {
    for (theme, bg, ink) in backgrounds {
        for interrupted in [false, true] {
            let rows = ["left", "right"].map { sequence(size, $0, theme, bg, interrupted) }
            contact(rows, size, theme, bg, ink, interrupted)
        }
    }
}
try! JSONSerialization.data(withJSONObject: checks, options: [.prettyPrinted, .sortedKeys])
    .write(to: output.appendingPathComponent("checks.json"))
try! JSONSerialization.data(withJSONObject: frameBounds, options: [.prettyPrinted, .sortedKeys])
    .write(to: output.appendingPathComponent("frame-bounds.json"))
try! JSONSerialization.data(withJSONObject: edgeChecks, options: [.prettyPrinted, .sortedKeys])
    .write(to: output.appendingPathComponent("edge-audit.json"))
precondition(edgeChecks.allSatisfy { ($0["frames_with_alpha_at_rightmost_canvas_column"] as! [Int]).isEmpty },
             "Actual scene alpha still reaches the rightmost canvas column")
print("NATIVE_FIXED_ACTIONS_PASS: \(checks.count) actual TianmuView/G0 cases; catch 3s/idle, duplicate receipt, pressed action switch/release; both directions, 64/128pt light/dark; no window, worker or save")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-art', action='store_true',
                        help='Read production A01 assets and manifest directly without temporary rig injection.')
    args = parser.parse_args()
    out = ROOT / 'evidence/1.0/158-native-catch-production' if args.production_art else OUT
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'assets/production/A01'
    manifest_path = source / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert 'walk' not in manifest, 'Withdrawn frame table must not enter this fixture'
    stand = source / manifest['stand']['file']
    if args.production_art:
        assert isinstance(manifest.get('fixedActions'), dict), 'Production fixedActions must already be enabled'
        fixed_actions = manifest['fixedActions']
        originals = [stand, source / fixed_actions['catch']['net']['file'],
                     source / fixed_actions['catch']['torsoUnderlay']['file']]
    else:
        fixed_actions = FIXED_ACTIONS
        originals = [stand, INCOMING / 'net-v01-original.png', INCOMING / 'torso-underlay-v01-original.png']
        manifest['fixedActions'] = fixed_actions
    scene = ROOT / 'assets/production/scene'
    scene_manifest_path = scene / 'manifest.json'
    scene_manifest = json.loads(scene_manifest_path.read_text())
    scene_images = {scene / layer['file'] for layer in scene_manifest['layers']}
    scene_images.update(scene / item['file'] for item in scene_manifest.get('fruitVariants', {}).values())
    watched = [*originals, manifest_path, scene_manifest_path, *sorted(scene_images)]
    digests = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
    native = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
    with tempfile.TemporaryDirectory(prefix='tianmu-native-fixed-actions-') as folder:
        work = Path(folder)
        if args.production_art:
            assets = source
        else:
            assets = work / 'A01'
            assets.mkdir()
            for original in originals:
                shutil.copy2(original, assets / original.name)
            (assets / 'manifest.json').write_text(json.dumps(manifest))
        (work / 'Scene.swift').write_text(native)
        (work / 'main.swift').write_text(SWIFT)
        subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'ImageIO',
                        str(work / 'Scene.swift'), str(work / 'main.swift'), '-o', str(work / 'render')], check=True)
        subprocess.run([str(work / 'render'), str(assets), str(scene), str(out)], check=True)
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in digests.items())
    (out / 'fixture.json').write_text(json.dumps({
        'source_sha256': digests, 'native_prefix_sha256': hashlib.sha256(native.encode()).hexdigest(),
        'fixedActions': fixed_actions, 'renderer': 'actual TianmuView with production G0',
        'art_mode': 'production' if args.production_art else 'original PNG byte copies and temporary fixedActions manifest',
        'source_manifest': str(manifest_path),
        'snapshots': 'synthetic service facts; catch 3s, idle, duplicate receipt, pressed action switch/release',
        'release_transition': '0.16s static sleeve/net return to latest idle; held catch time does not advance or replay',
        'production_manifest_changed': False, 'no_window': True, 'no_worker': True, 'no_save_access': True,
    }, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
