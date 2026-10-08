import AppKit
import ImageIO
import CryptoKit

// A finite, immutable display cache. It never reads a clock, changes insects,
// schedules work, or creates application/window objects.
final class InsectArtwork {
    final class RenderSample {
        let style: InsectStyle
        let color: String
        let frameIndex: Int
        let pixelHash: String
        let canvasSize: NSSize
        let image: CGImage
        private let displayImage: NSImage

        fileprivate init(style: InsectStyle, color: String, frameIndex: Int,
                         pixels: Pixels, canvasSize: NSSize) throws {
            guard let provider = CGDataProvider(data: Data(pixels.bytes) as CFData),
                  let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let image = CGImage(width: pixels.width, height: pixels.height,
                    bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: pixels.width * 4,
                    space: space, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
                    provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
            else { throw Invalid("无法创建图片缓存") }
            self.style = style; self.color = color; self.frameIndex = frameIndex
            self.canvasSize = canvasSize; self.image = image
            self.displayImage = NSImage(cgImage: image, size: canvasSize)
            let hash = pixels.bytes.reduce(UInt64(14695981039346656037)) { ($0 ^ UInt64($1)) &* 1099511628211 }
            self.pixelHash = String(hash, radix: 16)
        }

        func draw(at center: NSPoint) {
            guard center.x.isFinite, center.y.isFinite else { return }
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current?.imageInterpolation = .none
            displayImage.draw(in: NSRect(x: center.x - canvasSize.width / 2,
                                        y: center.y - canvasSize.height / 2,
                                        width: canvasSize.width, height: canvasSize.height),
                              from: .zero, operation: .sourceOver, fraction: 1,
                              respectFlipped: false, hints: [.interpolation: NSImageInterpolation.none])
            NSGraphicsContext.restoreGraphicsState()
        }
    }

    static let production = InsectArtwork(directory: Bundle.main.resourceURL?.appendingPathComponent("art/insects", isDirectory: true))
    let availableStyles: Set<InsectStyle>
    let issues: [String]
    var complete: Bool { availableStyles == Set([.cute, .realistic]) }
    private let cache: [InsectStyle: StyleCache]
    private static let colors = ["普通褐色", "中褐色", "深褐色", "白色"]

    init(directory: URL?) {
        var loaded: [InsectStyle: StyleCache] = [:]
        var failures: [String] = []
        do {
            guard let directory else { throw Invalid("缺少虫图资源目录") }
            let manifestURL = try Self.safeURL("manifest.json", in: directory)
            let data = try Self.fileData(manifestURL, maximumBytes: 1_048_576)
            let manifest = try JSONDecoder().decode(Manifest.self, from: data)
            guard manifest.version == 1, manifest.sampling == "nearest" else { throw Invalid("虫图清单版本或采样方式不支持") }
            var decoded: [String: Pixels] = [:]
            for style: InsectStyle in [.cute, .realistic] {
                do {
                    switch style {
                    case .cute:
                        guard let spec = manifest.styles.cute else { throw Invalid("清单缺失或字段格式不符") }
                        loaded[style] = try Self.loadAtlas(spec, directory: directory, decoded: &decoded)
                    case .realistic:
                        guard let spec = manifest.styles.realistic else { throw Invalid("清单缺失或字段格式不符") }
                        loaded[style] = try Self.loadLayers(spec, directory: directory, decoded: &decoded)
                    }
                } catch {
                    failures.append("\(style.title)：\(Self.message(error))")
                }
            }
        } catch {
            failures.append(Self.message(error))
        }
        self.cache = loaded
        self.availableStyles = Set(loaded.keys)
        self.issues = failures
    }

    func sample(style: InsectStyle, color: String, time: TimeInterval, phase: Double) -> RenderSample? {
        guard let entry = cache[style] else { return nil }
        let period = Double(entry.sequence.count) / entry.fps
        // Reduce before multiplying: an extreme finite uptime must not overflow Int.
        let elapsed = time.isFinite ? time.truncatingRemainder(dividingBy: period) : 0
        let idPhase = phase.isFinite ? phase.truncatingRemainder(dividingBy: 10) / 10 : 0
        var cycle = (elapsed / period + idPhase).truncatingRemainder(dividingBy: 1)
        if cycle < 0 { cycle += 1 }
        let slot = min(entry.sequence.count - 1, max(0, Int(floor(cycle * Double(entry.sequence.count)))))
        let frame = entry.sequence[slot]
        return entry.samples[color]?[frame] ?? entry.samples[Self.colors[0]]?[frame]
    }

    private struct Invalid: Error { let text: String; init(_ text: String) { self.text = text } }
    private static func message(_ error: Error) -> String {
        (error as? Invalid)?.text ?? "虫图资源无法读取或清单字段格式不符"
    }
    private struct Manifest: Decodable {
        let version: Int
        let sampling: String
        let styles: StyleSpecs
    }
    private struct StyleSpecs: Decodable {
        let cute: AtlasSpec?
        let realistic: LayerSpec?
        private enum Keys: String, CodingKey { case cute, realistic }
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: Keys.self)
            // A broken optional style never discards the other genuine style.
            cute = try? values.decode(AtlasSpec.self, forKey: .cute)
            realistic = try? values.decode(LayerSpec.self, forKey: .realistic)
        }
    }
    private struct AtlasSpec: Decodable {
        let kind: String
        let file: String
        let canvasSize: [Double]
        let sampleScale: Int
        let displayScale: Double
        let fps: Double
        let sequence: [Int]?
        let frames: [AtlasFrame]
        let palette: [String: [[Int]]]
    }
    private struct AtlasFrame: Decodable {
        let sourceRect: [Int]
        let anchor: [Double]
        let bodyRows: [[Int]]
        let sourcePalette: [[Int]]
    }
    private struct LayerSpec: Decodable {
        let kind: String
        let canvasSize: [Double]
        let sampleScale: Int
        let fps: Double
        let sequence: [Int]?
        let body: ComponentSpec
        let upperWing: ComponentSpec
        let lowerWing: ComponentSpec
        let frames: [WingFrame]
        let bodyPolygon: [[Double]]
        let warmGate: WarmGate
        let lumaRange: [Double]
        let palette: [String: [[Int]]]
    }
    private struct ComponentSpec: Decodable {
        let file: String
        let sourceRect: [Int]
        let bounds: [Double]
        let pivot: [Double]?
    }
    private struct WingFrame: Decodable { let upperYScale: Double; let lowerYScale: Double }
    private struct WarmGate: Decodable { let minRed: Int; let minGreenOverRed: Double; let minGreenMinusBlue: Int }
    private struct StyleCache {
        let fps: Double
        let sequence: [Int]
        let samples: [String: [RenderSample]]
    }
    fileprivate struct Pixels {
        let width: Int
        let height: Int
        var bytes: [UInt8]
        init(width: Int, height: Int, bytes: [UInt8]? = nil) {
            self.width = width; self.height = height
            self.bytes = bytes ?? [UInt8](repeating: 0, count: width * height * 4)
        }
    }
    private struct Point: Hashable { let x: Double; let y: Double }
    private struct Box {
        let x: Double; let y: Double; let width: Double; let height: Double
        var maxX: Double { x + width }; var maxY: Double { y + height }
        func contains(_ point: Point) -> Bool {
            point.x >= x && point.x <= maxX && point.y >= y && point.y <= maxY
        }
    }
    private struct Component {
        let pixels: Pixels
        let bounds: Box
        let pivot: Point?
    }
    private struct Canvas {
        let size: NSSize
        let scale: Int
        let width: Int
        let height: Int
        func empty() -> Pixels { Pixels(width: width, height: height) }
        func contains(_ box: Box) -> Bool {
            let epsilon = 0.00000001
            return box.x >= -Double(size.width) / 2 - epsilon && box.maxX <= Double(size.width) / 2 + epsilon
                && box.y >= -Double(size.height) / 2 - epsilon && box.maxY <= Double(size.height) / 2 + epsilon
        }
    }

    private static func settings(size: [Double], scale: Int, fps: Double, sequence: [Int]?) throws -> (Canvas, [Int]) {
        guard size.count == 2, size.allSatisfy({ $0.isFinite && $0 > 0 && $0 <= 24 }), scale == 2,
              size.allSatisfy({ ($0 * Double(scale)).rounded() == $0 * Double(scale) }),
              fps.isFinite, fps > 0, fps <= 30 else { throw Invalid("画布、采样倍率或帧速无效") }
        let order = sequence ?? [0, 1, 2, 1]
        guard (3...16).contains(order.count), Set(order) == Set([0, 1, 2]) else { throw Invalid("播放序列必须包含全部三帧") }
        return (Canvas(size: NSSize(width: size[0], height: size[1]), scale: scale,
                       width: Int(size[0] * Double(scale)), height: Int(size[1] * Double(scale))), order)
    }
    private static func palette(_ values: [String: [[Int]]]) throws -> [String: [[UInt8]]] {
        guard Set(values.keys) == Set(colors) else { throw Invalid("必须提供四种体色") }
        return try values.mapValues { try rgbTriplet($0) }
    }
    private static func rgbTriplet(_ values: [[Int]]) throws -> [[UInt8]] {
        guard values.count == 3, values.allSatisfy({ $0.count == 3 && $0.allSatisfy({ (0...255).contains($0) }) })
        else { throw Invalid("调色板必须为三组 RGB 整数") }
        return values.map { $0.map(UInt8.init) }
    }
    private static func point(_ values: [Double]) throws -> Point {
        guard values.count == 2, values.allSatisfy(\.isFinite) else { throw Invalid("锚点或顶点无效") }
        return Point(x: values[0], y: values[1])
    }
    private static func box(_ values: [Double]) throws -> Box {
        guard values.count == 4, values.allSatisfy(\.isFinite), values[2] > 0, values[3] > 0,
              (values[0] + values[2]).isFinite, (values[1] + values[3]).isFinite else { throw Invalid("部件显示范围无效") }
        return Box(x: values[0], y: values[1], width: values[2], height: values[3])
    }
    private static func safeURL(_ name: String, in directory: URL) throws -> URL {
        guard !name.isEmpty, !NSString(string: name).isAbsolutePath,
              !name.split(separator: "/").contains("..") else { throw Invalid("资源必须使用目录内的相对路径") }
        let root = directory.resolvingSymlinksInPath().standardizedFileURL
        let file = root.appendingPathComponent(name).resolvingSymlinksInPath().standardizedFileURL
        guard file.path.hasPrefix(root.path + "/"),
              (try? file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
        else { throw Invalid("资源不存在、不是普通文件或越出资源目录") }
        return file
    }
    private static func fileData(_ url: URL, maximumBytes: Int) throws -> Data {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let size = attributes[.size] as? NSNumber, size.int64Value > 0,
              size.int64Value <= Int64(maximumBytes) else { throw Invalid("资源文件大小超出限制") }
        let data = try Data(contentsOf: url)
        guard data.count <= maximumBytes else { throw Invalid("资源文件大小超出限制") }
        return data
    }
    private static func crop(file: String, rectangle: [Int], directory: URL, decoded: inout [String: Pixels]) throws -> Pixels {
        let url = try safeURL(file, in: directory)
        guard url.pathExtension.lowercased() == "png" else { throw Invalid("虫图必须为 PNG") }
        let original: Pixels
        if let previous = decoded[url.path] { original = previous }
        else {
            let data = try fileData(url, maximumBytes: 32 * 1_048_576)
            guard data.count >= 33, data.starts(with: [137,80,78,71,13,10,26,10]) else { throw Invalid("PNG 签名无效") }
            func integer(_ offset: Int) -> UInt32 {
                data[offset..<offset + 4].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
            }
            let width = Int(integer(16)), height = Int(integer(20))
            guard (1...4096).contains(width), (1...4096).contains(height), width * height <= 16_777_216,
                  let source = CGImageSourceCreateWithData(data as CFData, nil),
                  CGImageSourceGetCount(source) == 1,
                  let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
                  image.width == width, image.height == height,
                  image.bitsPerComponent == 8, image.bitsPerPixel == 32,
                  image.alphaInfo == .last, image.bitmapInfo.rawValue == 3,
                  image.bytesPerRow >= width * 4, let provider = image.dataProvider?.data
            else { throw Invalid("PNG 必须是尺寸受限的原始 8 位 RGBA 图片") }
            let sourceBytes = provider as Data
            guard sourceBytes.count >= image.bytesPerRow * height else { throw Invalid("PNG 像素数据不完整") }
            var bytes = [UInt8](repeating: 0, count: width * height * 4)
            for y in 0..<height {
                bytes.replaceSubrange(y * width * 4..<(y + 1) * width * 4,
                                      with: sourceBytes[y * image.bytesPerRow..<y * image.bytesPerRow + width * 4])
            }
            original = Pixels(width: width, height: height, bytes: bytes)
            decoded[url.path] = original
        }
        guard rectangle.count == 4 else { throw Invalid("裁片必须有四个整数") }
        let x = rectangle[0], y = rectangle[1], width = rectangle[2], height = rectangle[3]
        guard x >= 0, y >= 0, width > 0, height > 0, x < original.width, y < original.height,
              width <= original.width - x, height <= original.height - y else { throw Invalid("裁片越出原图") }
        var bytes = [UInt8](repeating: 0, count: width * height * 4)
        for row in 0..<height {
            let start = ((y + row) * original.width + x) * 4
            bytes.replaceSubrange(row * width * 4..<(row + 1) * width * 4, with: original.bytes[start..<start + width * 4])
        }
        guard stride(from: 3, to: bytes.count, by: 4).contains(where: { bytes[$0] > 0 }) else { throw Invalid("裁片不能全透明") }
        return Pixels(width: width, height: height, bytes: bytes)
    }

    private static func loadAtlas(_ spec: AtlasSpec, directory: URL, decoded: inout [String: Pixels]) throws -> StyleCache {
        guard spec.kind == "atlas", spec.frames.count == 3, spec.displayScale.isFinite,
              spec.displayScale > 0, spec.displayScale <= 4 else { throw Invalid("可爱虫需要合法的三帧 atlas") }
        let (canvas, sequence) = try settings(size: spec.canvasSize, scale: spec.sampleScale, fps: spec.fps, sequence: spec.sequence)
        let palettes = try palette(spec.palette)
        var samples = Dictionary(uniqueKeysWithValues: colors.map { ($0, [RenderSample]()) })
        for (index, frame) in spec.frames.enumerated() {
            let pixels = try crop(file: spec.file, rectangle: frame.sourceRect, directory: directory, decoded: &decoded)
            let anchor = try point(frame.anchor)
            guard anchor.x >= 0, anchor.x <= Double(pixels.width), anchor.y >= 0, anchor.y <= Double(pixels.height)
            else { throw Invalid("atlas 锚点越出裁片") }
            let bounds = Box(x: -anchor.x * spec.displayScale, y: -anchor.y * spec.displayScale,
                             width: Double(pixels.width) * spec.displayScale, height: Double(pixels.height) * spec.displayScale)
            guard canvas.contains(bounds) else { throw Invalid("atlas 裁片越出固定画布") }
            let sourcePalette = try rgbTriplet(frame.sourcePalette)
            guard Set(sourcePalette).count == 3, !frame.bodyRows.isEmpty else { throw Invalid("身体源色或遮罩无效") }
            var visited = Set<Int>()
            var selected: [(offset: Int, shade: Int)] = []
            for row in frame.bodyRows {
                guard row.count == 3, row[0] >= 0, row[0] < pixels.height,
                      row[1] >= 0, row[1] <= row[2], row[2] < pixels.width else { throw Invalid("身体遮罩越出裁片") }
                for x in row[1]...row[2] {
                    let offset = (row[0] * pixels.width + x) * 4
                    guard visited.insert(offset).inserted else { throw Invalid("身体遮罩重复覆盖像素") }
                    guard pixels.bytes[offset + 3] == 255 else { continue }
                    if let shade = sourcePalette.firstIndex(of: Array(pixels.bytes[offset..<offset + 3])) {
                        selected.append((offset, shade))
                    }
                }
            }
            guard !selected.isEmpty else { throw Invalid("身体遮罩没有命中任何源色") }
            for color in colors {
                let recolored = recolor(pixels, selected: selected, palette: palettes[color]!)
                var result = canvas.empty()
                composite(recolored, bounds: bounds, pivot: nil, yScale: 1, canvas: canvas, into: &result)
                samples[color]!.append(try RenderSample(style: .cute, color: color, frameIndex: index, pixels: result, canvasSize: canvas.size))
            }
        }
        try distinct(samples)
        return StyleCache(fps: spec.fps, sequence: sequence, samples: samples)
    }
    private static func component(_ spec: ComponentSpec, needsPivot: Bool, canvas: Canvas,
                                  directory: URL, decoded: inout [String: Pixels]) throws -> Component {
        let bounds = try box(spec.bounds)
        guard canvas.contains(bounds) else { throw Invalid("部件越出固定画布") }
        let pivot = try spec.pivot.map(point)
        if needsPivot { guard let pivot, bounds.contains(pivot) else { throw Invalid("翅根必须位于对应翅片范围内") } }
        else if pivot != nil { throw Invalid("固定身体不接受翅片变换") }
        return Component(pixels: try crop(file: spec.file, rectangle: spec.sourceRect, directory: directory, decoded: &decoded),
                         bounds: bounds, pivot: pivot)
    }
    private static func transformed(_ box: Box, pivot: Point, yScale: Double) -> Box {
        let a = pivot.y + (box.y - pivot.y) * yScale, b = pivot.y + (box.maxY - pivot.y) * yScale
        return Box(x: box.x, y: min(a, b), width: box.width, height: abs(b - a))
    }
    private static func loadLayers(_ spec: LayerSpec, directory: URL, decoded: inout [String: Pixels]) throws -> StyleCache {
        guard spec.kind == "wingLayers", spec.frames.count == 3 else { throw Invalid("写实虫需要固定身体与三帧翅片姿态") }
        let (canvas, sequence) = try settings(size: spec.canvasSize, scale: spec.sampleScale, fps: spec.fps, sequence: spec.sequence)
        let palettes = try palette(spec.palette)
        let body = try component(spec.body, needsPivot: false, canvas: canvas, directory: directory, decoded: &decoded)
        let upper = try component(spec.upperWing, needsPivot: true, canvas: canvas, directory: directory, decoded: &decoded)
        let lower = try component(spec.lowerWing, needsPivot: true, canvas: canvas, directory: directory, decoded: &decoded)
        for frame in spec.frames {
            guard frame.upperYScale.isFinite, frame.lowerYScale.isFinite,
                  (-1...1).contains(frame.upperYScale), (-1...1).contains(frame.lowerYScale),
                  canvas.contains(transformed(upper.bounds, pivot: upper.pivot!, yScale: frame.upperYScale)),
                  canvas.contains(transformed(lower.bounds, pivot: lower.pivot!, yScale: frame.lowerYScale))
            else { throw Invalid("翅片姿态无效或越出固定画布") }
        }
        let selected = try warmPixels(body.pixels, polygon: spec.bodyPolygon, gate: spec.warmGate, luma: spec.lumaRange)
        var samples: [String: [RenderSample]] = [:]
        for color in colors {
            let coloredBody = recolor(body.pixels, selected: selected, palette: palettes[color]!)
            samples[color] = try spec.frames.enumerated().map { index, frame in
                var result = canvas.empty()
                composite(lower.pixels, bounds: lower.bounds, pivot: lower.pivot, yScale: frame.lowerYScale, canvas: canvas, into: &result)
                composite(upper.pixels, bounds: upper.bounds, pivot: upper.pivot, yScale: frame.upperYScale, canvas: canvas, into: &result)
                composite(coloredBody, bounds: body.bounds, pivot: nil, yScale: 1, canvas: canvas, into: &result)
                return try RenderSample(style: .realistic, color: color, frameIndex: index, pixels: result, canvasSize: canvas.size)
            }
        }
        try distinct(samples)
        return StyleCache(fps: spec.fps, sequence: sequence, samples: samples)
    }
    private static func distinct(_ samples: [String: [RenderSample]]) throws {
        guard colors.allSatisfy({ Set(samples[$0]!.map(\.pixelHash)).count == 3 }),
              Set(colors.map { samples[$0]![0].pixelHash }).count == 4 else { throw Invalid("三帧或四体色没有产生真实差异") }
    }
    private static func recolor(_ pixels: Pixels, selected: [(offset: Int, shade: Int)], palette: [[UInt8]]) -> Pixels {
        var result = pixels
        for pixel in selected {
            for channel in 0..<3 { result.bytes[pixel.offset + channel] = palette[pixel.shade][channel] }
        }
        return result
    }

    private static func cross(_ a: Point, _ b: Point, _ c: Point) -> Double {
        (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
    }
    private static func intersects(_ a: Point, _ b: Point, _ c: Point, _ d: Point) -> Bool {
        let epsilon = 0.00000001
        guard max(min(a.x, b.x), min(c.x, d.x)) <= min(max(a.x, b.x), max(c.x, d.x)) + epsilon,
              max(min(a.y, b.y), min(c.y, d.y)) <= min(max(a.y, b.y), max(c.y, d.y)) + epsilon else { return false }
        let abC = cross(a, b, c), abD = cross(a, b, d), cdA = cross(c, d, a), cdB = cross(c, d, b)
        return abC * abD <= epsilon && cdA * cdB <= epsilon
    }
    private static func warmPixels(_ pixels: Pixels, polygon values: [[Double]], gate: WarmGate,
                                   luma: [Double]) throws -> [(offset: Int, shade: Int)] {
        guard (3...256).contains(values.count), (0...255).contains(gate.minRed),
              (0...255).contains(gate.minGreenMinusBlue), gate.minGreenOverRed.isFinite,
              (0...1).contains(gate.minGreenOverRed), luma.count == 2, luma.allSatisfy(\.isFinite),
              luma[0] >= 0, luma[0] < luma[1], luma[1] <= 255 else { throw Invalid("身体多边形、暖色色域或亮度范围无效") }
        let polygon = try values.map(point)
        guard Set(polygon).count == polygon.count,
              polygon.allSatisfy({ $0.x >= 0 && $0.x <= Double(pixels.width) && $0.y >= 0 && $0.y <= Double(pixels.height) })
        else { throw Invalid("身体多边形越界或顶点重复") }
        var area = 0.0
        for i in polygon.indices {
            let j = (i + 1) % polygon.count
            area += polygon[i].x * polygon[j].y - polygon[j].x * polygon[i].y
            for k in polygon.indices where k > i {
                let l = (k + 1) % polygon.count
                if j == k || l == i { continue }
                if intersects(polygon[i], polygon[j], polygon[k], polygon[l]) { throw Invalid("身体多边形不能自交") }
            }
        }
        guard abs(area) > 0.000001 else { throw Invalid("身体多边形面积为空") }
        // Scan each polygon row once, then reuse selected offsets and luma bands
        // for all four palettes and every wing frame.
        var selected: [(offset: Int, shade: Int)] = []
        let firstY = max(0, Int(floor(polygon.map(\.y).min()!)))
        let lastY = min(pixels.height - 1, Int(ceil(polygon.map(\.y).max()!)))
        for y in firstY...lastY {
            let scanY = Double(y) + 0.5
            var intersections: [Double] = []
            for i in polygon.indices {
                let a = polygon[i], b = polygon[(i + 1) % polygon.count]
                if (a.y <= scanY && b.y > scanY) || (b.y <= scanY && a.y > scanY) {
                    intersections.append(a.x + (scanY - a.y) * (b.x - a.x) / (b.y - a.y))
                }
            }
            intersections.sort()
            guard intersections.count % 2 == 0 else { throw Invalid("身体多边形扫描不完整") }
            for index in stride(from: 0, to: intersections.count, by: 2) {
                let first = max(0, Int(ceil(intersections[index] - 0.5)))
                let last = min(pixels.width - 1, Int(ceil(intersections[index + 1] - 0.5)) - 1)
                if first > last { continue }
                for x in first...last {
                    let offset = (y * pixels.width + x) * 4
                    guard pixels.bytes[offset + 3] > 0 else { continue }
                    let r = Double(pixels.bytes[offset]), g = Double(pixels.bytes[offset + 1]), b = Double(pixels.bytes[offset + 2])
                    guard r > 0, r >= Double(gate.minRed), g / r >= gate.minGreenOverRed,
                          g - b >= Double(gate.minGreenMinusBlue) else { continue }
                    let t = min(1, max(0, (0.2126 * r + 0.7152 * g + 0.0722 * b - luma[0]) / (luma[1] - luma[0])))
                    selected.append((offset, t < 0.333 ? 0 : t < 0.667 ? 1 : 2))
                }
            }
        }
        guard !selected.isEmpty else { throw Invalid("身体遮罩和暖色色域没有命中像素") }
        return selected
    }

    // Nearest source sampling in the fixed point canvas. Straight RGBA source
    // bytes retain their palette/alpha; no color-space conversion is involved.
    private static func composite(_ source: Pixels, bounds: Box, pivot: Point?, yScale: Double,
                                  canvas: Canvas, into result: inout Pixels) {
        guard yScale != 0 else { return }
        for y in 0..<canvas.height {
            let py = (Double(y) + 0.5) / Double(canvas.scale) - Double(canvas.size.height) / 2
            let originalY = pivot.map { $0.y + (py - $0.y) / yScale } ?? py
            let sourceY = (originalY - bounds.y) / bounds.height * Double(source.height)
            guard sourceY >= 0, sourceY < Double(source.height) else { continue }
            let sy = Int(floor(sourceY))
            for x in 0..<canvas.width {
                let px = (Double(x) + 0.5) / Double(canvas.scale) - Double(canvas.size.width) / 2
                let sourceX = (px - bounds.x) / bounds.width * Double(source.width)
                guard sourceX >= 0, sourceX < Double(source.width) else { continue }
                let sx = Int(floor(sourceX)), from = (sy * source.width + sx) * 4, to = (y * canvas.width + x) * 4
                let alpha = source.bytes[from + 3]
                if alpha == 0 { continue }
                if alpha == 255 || result.bytes[to + 3] == 0 {
                    for channel in 0..<4 { result.bytes[to + channel] = source.bytes[from + channel] }
                } else {
                    let sa = Double(alpha) / 255, da = Double(result.bytes[to + 3]) / 255
                    let combined = sa + da * (1 - sa)
                    for channel in 0..<3 {
                        let value = (Double(source.bytes[from + channel]) * sa + Double(result.bytes[to + channel]) * da * (1 - sa)) / combined
                        result.bytes[to + channel] = UInt8(min(255, max(0, value.rounded())))
                    }
                    result.bytes[to + 3] = UInt8(min(255, max(0, (combined * 255).rounded())))
                }
            }
        }
    }
}

// A separately loaded, immutable bottle resource. The interior rectangle is
// normalized in AppKit's lower-left coordinates relative to the full PNG canvas.
final class BottleArtwork {
    static let production = BottleArtwork(directory: Bundle.main.resourceURL?.appendingPathComponent("art/bottle", isDirectory: true))
    let image: NSImage?
    let issue: String?
    let interiorRect: NSRect

    private struct Manifest: Decodable {
        let version: Int
        let sampling: String
        let file: String
        let sha256: String
        let interiorRect: [Double]
    }
    private struct Invalid: Error { let text: String; init(_ text: String) { self.text = text } }
    private static func safeURL(_ name: String, directory: URL) throws -> URL {
        guard !name.isEmpty, name != ".", name != "..", !name.contains("\\"),
              !NSString(string: name).isAbsolutePath, !name.split(separator: "/").contains("..")
        else { throw Invalid("虫瓶资源必须在其目录内") }
        let root = directory.resolvingSymlinksInPath().standardizedFileURL
        let file = root.appendingPathComponent(name).resolvingSymlinksInPath().standardizedFileURL
        guard file.path.hasPrefix(root.path + "/"),
              (try? file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
        else { throw Invalid("虫瓶资源缺失或越出目录") }
        return file
    }
    private static func read(_ url: URL, limit: Int) throws -> Data {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let size = attributes[.size] as? NSNumber, size.int64Value > 0, size.int64Value <= Int64(limit)
        else { throw Invalid("虫瓶资源大小无效") }
        let data = try Data(contentsOf: url)
        guard data.count <= limit else { throw Invalid("虫瓶资源超过大小限制") }
        return data
    }

    init(directory: URL?) {
        do {
            guard let directory else { throw Invalid("缺少虫瓶资源目录") }
            let manifestData = try Self.read(Self.safeURL("manifest.json", directory: directory), limit: 1_048_576)
            let manifest = try JSONDecoder().decode(Manifest.self, from: manifestData)
            guard manifest.version == 1, manifest.sampling == "nearest",
                  manifest.sha256.count == 64,
                  manifest.sha256.allSatisfy({ "0123456789abcdef".contains($0) })
            else { throw Invalid("虫瓶清单版本、采样或校验值无效") }
            let r = manifest.interiorRect
            guard r.count == 4, r.allSatisfy(\.isFinite), r[0] >= 0, r[1] >= 0,
                  r[2] > 0, r[3] > 0, r[0] + r[2] <= 1, r[1] + r[3] <= 1
            else { throw Invalid("虫瓶内部范围必须位于完整图片内") }
            let file = try Self.safeURL(manifest.file, directory: directory)
            guard file.pathExtension.lowercased() == "png" else { throw Invalid("虫瓶图片必须为 PNG") }
            let data = try Self.read(file, limit: 32 * 1_048_576)
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard digest == manifest.sha256 else { throw Invalid("虫瓶原图校验不一致") }
            guard data.count >= 45, data.starts(with: [137,80,78,71,13,10,26,10]),
                  Array(data[12..<16]) == [73,72,68,82],
                  Array(data.suffix(12)) == [0,0,0,0,73,69,78,68,174,66,96,130]
            else { throw Invalid("虫瓶 PNG 不完整") }
            func integer(_ start: Int) -> Int { data[start..<start + 4].reduce(0) { ($0 << 8) | Int($1) } }
            let width = integer(16), height = integer(20)
            guard (1...4096).contains(width), (1...4096).contains(height), width * height <= 16_777_216,
                  let source = CGImageSourceCreateWithData(data as CFData, nil),
                  CGImageSourceGetCount(source) == 1, CGImageSourceGetStatus(source) == .statusComplete,
                  let original = CGImageSourceCreateImageAtIndex(source, 0, nil),
                  original.width == width, original.height == height,
                  [.first, .last, .premultipliedFirst, .premultipliedLast, .alphaOnly].contains(original.alphaInfo)
            else { throw Invalid("虫瓶 PNG 尺寸或透明通道无效") }
            var rgba = [UInt8](repeating: 0, count: width * height * 4)
            guard let context = CGContext(data: &rgba, width: width, height: height, bitsPerComponent: 8,
                    bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)
            else { throw Invalid("虫瓶图片无法解码") }
            context.draw(original, in: CGRect(x: 0, y: 0, width: width, height: height))
            guard stride(from: 3, to: rgba.count, by: 4).contains(where: { rgba[$0] > 0 })
            else { throw Invalid("虫瓶图片完全透明") }
            image = NSImage(cgImage: original, size: NSSize(width: width, height: height))
            interiorRect = NSRect(x: r[0], y: r[1], width: r[2], height: r[3])
            issue = nil
        } catch {
            image = nil; interiorRect = .zero
            issue = (error as? Invalid)?.text ?? "虫瓶资源无法读取或清单字段无效"
        }
    }

    private func valid(_ bounds: NSRect) -> Bool {
        [bounds.origin.x, bounds.origin.y, bounds.width, bounds.height, bounds.maxX, bounds.maxY].allSatisfy(\.isFinite)
            && bounds.width > 0 && bounds.height > 0
    }
    func interiorRect(in bounds: NSRect) -> NSRect {
        guard image != nil, valid(bounds) else { return .zero }
        return NSRect(x: bounds.minX + interiorRect.minX * bounds.width,
                      y: bounds.minY + interiorRect.minY * bounds.height,
                      width: interiorRect.width * bounds.width, height: interiorRect.height * bounds.height)
    }
    func draw(in bounds: NSRect) {
        guard let image, valid(bounds) else { return }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current?.imageInterpolation = .none
        image.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1,
                   respectFlipped: false, hints: [.interpolation: NSImageInterpolation.none])
        NSGraphicsContext.restoreGraphicsState()
    }
}

/// Mechanical Core Graphics port of fly-paradise v0.3.6's live dorsal drawFly closure.
/// Source, pinned hashes and license provenance: third_party/fly-paradise/NOTICE.md.
/// Canvas coordinates, paths, palettes, compositing order and millisecond phases are retained.
final class FlyParadiseArtwork {
    enum Motion { case flying, resting, crawling }
    static let shared = FlyParadiseArtwork()
    // Canonical upstream poses at 2x, keyed by palette/sex/activity/phase only.
    // Heading, placement, original per-individual scale and fade stay live.
    // Maximum: 4 palettes * 2 sexes * (32 flight + 16 groom + 1 crawl) * 48² RGBA.
    private var poseCache: [Int: CGImage] = [:]
    var cachedPoseCount: Int { poseCache.count }
    private static let space = CGColorSpace(name: CGColorSpace.sRGB)!
    private static func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> CGColor {
        CGColor(colorSpace: space, components: [CGFloat((hex >> 16) & 255) / 255,
            CGFloat((hex >> 8) & 255) / 255, CGFloat(hex & 255) / 255, alpha])!
    }
    private struct Palette {
        let thorax: CGColor, thoraxDark: CGColor, abdomen: CGColor, band: CGColor, head: CGColor, leg: CGColor
        init(_ t: UInt32, _ d: UInt32, _ a: UInt32, _ b: UInt32, _ h: UInt32, _ l: UInt32) {
            thorax = color(t); thoraxDark = color(d); abdomen = color(a)
            band = color(b); head = color(h); leg = color(l)
        }
    }
    private static let palettes = [
        Palette(0xd4a056, 0xb07a38, 0xead7aa, 0x2e2014, 0xc48a48, 0xc6a66c),
        Palette(0xaa743c, 0xc49050, 0xc8a878, 0x3a2410, 0x8e5c28, 0x966834),
        Palette(0x4a2c12, 0x8a5a28, 0x6b4524, 0x1a0e08, 0x3a220e, 0x4a3218),
        Palette(0xf3eee4, 0xd8d0c4, 0xfffcf6, 0x6b6358, 0xefe8dc, 0xc4b8a8)
    ]
    private static let wing = color(0xf8fafc, 0.5), vein = color(0x464646, 0.4)
    private static let shadow = color(0, 0.16), antenna = color(0x5a3a18), maleTip = color(0x140c08)
    private static let eyeGradient = CGGradient(colorsSpace: space,
        colors: [color(0xf4a090), color(0xd44532), color(0x7a1810)] as CFArray,
        locations: [0, 0.45, 1])!

    private func valid(at: NSPoint, heading: Double, now: TimeInterval, seed: Double, scale: CGFloat) -> Bool {
        at.x.isFinite && at.y.isFinite && heading.isFinite && now.isFinite && (now * 1000).isFinite
            && seed.isFinite && scale.isFinite && scale > 0 && (scale * 4 / 3).isFinite
    }
    func draw(at point: NSPoint, color: String, sex: String, heading: Double,
              motion: Motion, now: TimeInterval, seed: Double, scale: CGFloat = 1) {
        guard valid(at: point, heading: heading, now: now, seed: seed, scale: scale),
              let context = NSGraphicsContext.current?.cgContext else { return }
        render(context, at: point, color: color, sex: sex, heading: heading,
               motion: motion, now: now, seed: seed, scale: scale)
    }
    func drawCached(at point: NSPoint, color: String, sex: String, heading: Double,
                    motion: Motion, now: TimeInterval, seed: Double, scale: CGFloat = 1, opacity: Double = 1) {
        guard valid(at: point, heading: heading, now: now, seed: seed, scale: scale),
              opacity.isFinite, opacity > 0, let context = NSGraphicsContext.current?.cgContext else { return }
        let pose = cachedPose(color: color, sex: sex, motion: motion, now: now, seed: seed)
        let key = pose.key
        let image: CGImage
        if let cached = poseCache[key] { image = cached }
        else {
            guard let rendered = sample(color: color, sex: sex, heading: 0, motion: motion,
                                        now: pose.time, seed: 0) else { return }
            poseCache[key] = rendered; image = rendered
        }
        context.saveGState()
        context.translateBy(x: point.x, y: point.y); context.rotate(by: heading)
        context.setAlpha(min(1,opacity)); context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: -12 * scale, y: -12 * scale, width: 24 * scale, height: 24 * scale))
        context.restoreGState()
    }

    // A view can reject an unchanged frame without allocating or drawing a pose.
    func cachedPoseKey(color: String, sex: String, motion: Motion, now: TimeInterval, seed: Double) -> Int {
        guard now.isFinite, (now * 1000).isFinite, seed.isFinite else { return -1 }
        return cachedPose(color: color, sex: sex, motion: motion, now: now, seed: seed).key
    }

    private func cachedPose(color: String, sex: String, motion: Motion, now: TimeInterval, seed: Double) -> (key: Int, time: Double) {
        let palette: Int
        switch color { case "中褐色": palette = 1; case "深褐色": palette = 2; case "白色": palette = 3; default: palette = 0 }
        let male = sex.lowercased() == "m", count = motion == .flying ? 32 : motion == .resting ? 16 : 1
        let cycle = motion == .flying ? now * 550 + seed : motion == .resting ? now * 28 : 0
        let fraction = (cycle / (2 * .pi)).truncatingRemainder(dividingBy: 1)
        let bucket = Int(((fraction + 1).truncatingRemainder(dividingBy: 1) * Double(count)).rounded()) % count
        let kind = motion == .flying ? 0 : motion == .resting ? 1 : 2
        let key = (((palette * 2 + (male ? 1 : 0)) * 3 + kind) * 32) + bucket
        let phaseTime = Double(bucket) / Double(count) * 2 * .pi / (motion == .flying ? 550 : 28)
        return (key, phaseTime)
    }
    /// A fixed 24-point, 2x transparent sample for source comparisons, independent of NSApplication.
    func sample(color: String, sex: String, heading: Double, motion: Motion,
                now: TimeInterval, seed: Double, scale: CGFloat = 1) -> CGImage? {
        guard valid(at: .zero, heading: heading, now: now, seed: seed, scale: scale),
              let context = CGContext(data: nil, width: 48, height: 48, bitsPerComponent: 8,
                    bytesPerRow: 48 * 4, space: Self.space,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)
        else { return nil }
        context.scaleBy(x: 2, y: 2)
        render(context, at: NSPoint(x: 12, y: 12), color: color, sex: sex, heading: heading,
               motion: motion, now: now, seed: seed, scale: scale)
        return context.makeImage()
    }
    private func render(_ c: CGContext, at point: NSPoint, color: String, sex: String,
                        heading: Double, motion: Motion, now: TimeInterval, seed: Double, scale: CGFloat) {
        let index: Int
        switch color { case "中褐色": index = 1; case "深褐色": index = 2; case "白色": index = 3; default: index = 0 }
        c.saveGState()
        c.setAlpha(1); c.setBlendMode(.normal); c.setLineCap(.butt); c.setLineJoin(.miter)
        c.translateBy(x: point.x, y: point.y)
        // Canvas has downward y; AppKit heading uses upward y. This preserves full heading rotation.
        c.rotate(by: heading - .pi / 2)
        c.scaleBy(x: scale * 4 / 3, y: -scale * 4 / 3)
        dorsal(c, palette: Self.palettes[index], male: sex.lowercased() == "m",
               flying: motion == .flying, grooms: motion == .resting, now: now * 1000, seed: seed)
        c.restoreGState()
    }
    private func ellipse(_ c: CGContext, _ x: CGFloat, _ y: CGFloat, _ rx: CGFloat, _ ry: CGFloat, _ angle: CGFloat = 0) {
        c.beginPath()
        var transform = CGAffineTransform(translationX: x, y: y).rotated(by: angle)
        c.addPath(CGPath(ellipseIn: CGRect(x: -rx, y: -ry, width: rx * 2, height: ry * 2), transform: &transform))
    }
    private func fillAndStroke(_ c: CGContext) {
        let path = c.path
        c.fillPath()
        if let path { c.addPath(path); c.strokePath() }
    }
    private func abdomenPath(_ c: CGContext) {
        c.beginPath(); c.move(to: CGPoint(x: -0.55, y: 1.7))
        c.addCurve(to: CGPoint(x: 0, y: 5.35), control1: CGPoint(x: -1.85, y: 2.5), control2: CGPoint(x: -1.65, y: 4.2))
        c.addCurve(to: CGPoint(x: 0.55, y: 1.7), control1: CGPoint(x: 1.65, y: 4.2), control2: CGPoint(x: 1.85, y: 2.5))
        c.closePath()
    }
    private func strokeLeg(_ c: CGContext, _ p: Palette, _ ax: CGFloat, _ ay: CGFloat,
                           _ bx: CGFloat, _ by: CGFloat, _ cx: CGFloat, _ cy: CGFloat) {
        c.setStrokeColor(p.leg); c.setLineWidth(0.55); c.setLineCap(.round); c.setLineJoin(.round)
        c.beginPath(); c.move(to: CGPoint(x: ax, y: ay)); c.addLine(to: CGPoint(x: bx, y: by))
        c.addLine(to: CGPoint(x: cx, y: cy)); c.strokePath()
    }
    private func wingAngle(_ now: Double, _ seed: Double, _ phase: Double) -> CGFloat {
        0.12 + 0.5 * sin(now * 0.55 + seed + phase)
    }
    private func dorsalWing(_ c: CGContext, _ side: CGFloat, _ angle: CGFloat) {
        c.saveGState(); c.translateBy(x: side * 1.5, y: 0.22); c.rotate(by: side * angle)
        c.setFillColor(Self.wing); c.setStrokeColor(Self.vein); c.setLineWidth(0.35)
        c.beginPath(); c.move(to: .zero)
        c.addCurve(to: CGPoint(x: side * 5.15, y: 0.12), control1: CGPoint(x: side * 2.2, y: -1.15), control2: CGPoint(x: side * 4.5, y: -0.75))
        c.addCurve(to: CGPoint(x: side * 0.2, y: 0.4), control1: CGPoint(x: side * 4.6, y: 1.15), control2: CGPoint(x: side * 2.0, y: 1.25))
        c.closePath(); fillAndStroke(c)
        c.beginPath(); c.move(to: .zero)
        c.addQuadCurve(to: CGPoint(x: side * 4.9, y: 0.16), control: CGPoint(x: side * 3.0, y: -0.12)); c.strokePath()
        c.restoreGState()
    }
    private func foldedWings(_ c: CGContext) {
        for side: CGFloat in [-1, 1] {
            c.saveGState(); c.setAlpha(0.55); c.translateBy(x: side * 0.28, y: 0.55); c.rotate(by: side * 0.08)
            c.setFillColor(Self.wing); c.setStrokeColor(Self.vein); c.setLineWidth(0.3)
            c.beginPath(); c.move(to: .zero)
            c.addCurve(to: CGPoint(x: side * 0.25, y: 4.3), control1: CGPoint(x: side * 0.7, y: 0.5), control2: CGPoint(x: side * 0.9, y: 2.2))
            c.addCurve(to: CGPoint(x: 0, y: 0.25), control1: CGPoint(x: side * -0.35, y: 4.5), control2: CGPoint(x: 0, y: 2.0))
            c.closePath(); fillAndStroke(c); c.restoreGState()
        }
    }
    private func dorsal(_ c: CGContext, palette p: Palette, male: Bool, flying: Bool, grooms: Bool, now: Double, seed: Double) {
        let flap = flying ? wingAngle(now, seed, 0) : 0.85
        c.setFillColor(Self.shadow); ellipse(c, 0.4, 4, 2.4, 1.1); c.fillPath()
        if flying {
            c.saveGState(); c.setAlpha(0.28)
            dorsalWing(c, -1, wingAngle(now, seed, 0.9)); dorsalWing(c, 1, wingAngle(now, seed, 0.9))
            c.setAlpha(0.18)
            dorsalWing(c, -1, wingAngle(now, seed, 1.8)); dorsalWing(c, 1, wingAngle(now, seed, 1.8))
            c.restoreGState(); dorsalWing(c, -1, flap); dorsalWing(c, 1, flap)
        } else { foldedWings(c) }
        c.setFillColor(p.abdomen); abdomenPath(c); c.fillPath()
        if male {
            c.saveGState(); abdomenPath(c); c.clip(); c.setFillColor(Self.maleTip)
            ellipse(c, 0, 4.55, 1.7, 1.45); c.fillPath(); c.restoreGState()
        }
        c.setStrokeColor(p.band); c.setLineWidth(0.45)
        for i in 0..<4 {
            let y = 2.25 + CGFloat(i) * 0.68, w = 1.35 - CGFloat(i) * 0.18
            c.beginPath(); c.move(to: CGPoint(x: -w, y: y))
            c.addQuadCurve(to: CGPoint(x: w, y: y), control: CGPoint(x: 0, y: y + 0.2)); c.strokePath()
        }
        c.setFillColor(p.thorax); ellipse(c, 0, 1.85, 0.48, 0.32); c.fillPath()
        ellipse(c, 0, 0.4, 1.65, 1.35); c.fillPath()
        c.setFillColor(p.thoraxDark); c.setAlpha(0.35); ellipse(c, 0, 0.3, 0.95, 0.9); c.fillPath(); c.setAlpha(1)
        c.setFillColor(p.head); ellipse(c, 0, -1.15, 0.48, 0.36); c.fillPath()
        ellipse(c, 0, -1.85, 0.88, 0.74); c.fillPath()
        c.setStrokeColor(Self.antenna); c.setLineWidth(0.28); c.setLineCap(.round)
        for side: CGFloat in [-1, 1] {
            c.beginPath(); c.move(to: CGPoint(x: side * 0.3, y: -2.45)); c.addLine(to: CGPoint(x: side * 0.62, y: -3.05)); c.strokePath()
        }
        for side: CGFloat in [-1, 1] {
            c.saveGState(); ellipse(c, side * 0.7, -1.88, 0.58, 0.64, side * 0.18); c.clip()
            c.drawRadialGradient(Self.eyeGradient, startCenter: CGPoint(x: side * 0.5, y: -2.0), startRadius: 0.12,
                endCenter: CGPoint(x: side * 0.62, y: -1.85), endRadius: 0.78,
                options: [.drawsBeforeStartLocation, .drawsAfterEndLocation]); c.restoreGState()
        }
        if grooms {
            let rub = CGFloat(sin(now * 0.028))
            strokeLeg(c, p, -0.7, -1.1, -1.35, -1.7 + rub * 0.35, -0.85, -2.15 - rub * 0.2)
            strokeLeg(c, p, 0.7, -1.1, 1.35, -1.7 - rub * 0.35, 0.85, -2.15 + rub * 0.2)
        }
    }
}

// MARK: - Bottle motion adapted from fly-paradise
// MIT, desktop-fly-pet; pinned 9c6130681c1a112c3c7faaafbad6d335cc0a1c36.
// renderer/overlay.js: jarRandPos, bounceJar, and the adult stepJar branch.
// See third_party/fly-paradise/BOTTLE-MOTION-ADAPTATION.md and NOTICE.md.
// Display only: no reproduction, death, inventory operations, windows or timer.
struct BottleMotionFrame: Equatable {
    let x: Double
    let y: Double
    let heading: Double
    let animationTime: TimeInterval
    let seed: Double
}

final class BottleMotionEngine {
    private struct Individual {
        var x: Double = 0, y: Double = 0, heading: Double = 0
        var elapsed: Double = 0, turnAt: Double = 0, burstUntil: Double = 0
        var course: Double = 0, burstMultiplier: Double = 1
        var lastTime: TimeInterval?
        var randomState: UInt64
        let seed: Double

        init(id: String, now: TimeInterval) {
            let hash = id.utf8.reduce(UInt64(14695981039346656037)) { ($0 ^ UInt64($1)) &* 1099511628211 }
            randomState = hash; seed = Double(hash % 1000)
            lastTime = now.isFinite ? now : nil
            x = random(24, 156); y = random(28, 292)
            heading = random(0, 2 * .pi); course = heading
        }

        mutating func random(_ low: Double, _ high: Double) -> Double {
            randomState = randomState &* 6364136223846793005 &+ 1442695040888963407
            return low + (high - low) * Double(randomState >> 11) / 9007199254740992
        }

        mutating func advance(to time: TimeInterval) {
            guard time.isFinite else { lastTime = nil; return }
            guard let previous = lastTime else { lastTime = time; return }
            lastTime = time
            let interval = time - previous
            // Closing the page or sleeping establishes a fresh clock anchor.
            // A delayed redraw never simulates the time the bottle was unseen.
            guard interval > 0, interval <= 0.25 else { return }
            let dt = min(0.05, interval)
            elapsed += dt
            if elapsed > turnAt {
                turnAt = elapsed + random(0.3, 1)
                course = heading + random(-2.6, 2.6)
                burstMultiplier = 1 + random(0.2, 0.5)
                burstUntil = elapsed + random(0.2, 0.3)
            }
            var difference = course - heading
            while difference > .pi { difference -= 2 * .pi }
            while difference < -.pi { difference += 2 * .pi }
            heading += difference * min(1, dt * 7)
            heading += sin(elapsed * 7 + seed) * 0.8 * dt
            let speed = 30 * (elapsed < burstUntil ? burstMultiplier : 1)
            var vx = cos(heading) * speed, vy = sin(heading) * speed
            x += vx * dt; y += vy * dt
            var bounced = false
            if x < 18 { x = 18; vx = abs(vx); bounced = true }
            if x > 162 { x = 162; vx = -abs(vx); bounced = true }
            if y < 22 { y = 22; vy = abs(vy); bounced = true }
            if y > 298 { y = 298; vy = -abs(vy); bounced = true }
            if bounced { heading = atan2(vy, vx) + random(-0.6, 0.6) }
        }

        var frame: BottleMotionFrame {
            BottleMotionFrame(x: x, y: y, heading: heading, animationTime: elapsed, seed: seed)
        }
    }
    private var individuals: [String: Individual] = [:]
    private(set) var frames: [String: BottleMotionFrame] = [:]

    func update(ids: [String], now: TimeInterval) {
        var seen = Set<String>()
        let ids = Array(ids.filter { !$0.isEmpty && seen.insert($0).inserted }.prefix(12))
        let current = Set(ids)
        individuals = individuals.filter { current.contains($0.key) }
        frames = [:]
        for id in ids {
            var individual = individuals[id] ?? Individual(id: id, now: now)
            individual.advance(to: now)
            individuals[id] = individual; frames[id] = individual.frame
        }
    }
}
