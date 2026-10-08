import AppKit
import Foundation

// Original candidate artwork. This generator reads no source image and no user data.
// The paths deliberately belong to the same small native icon family as BrandArtwork,
// but production selection is left untouched. All coordinates are y-up, in 100 units.
// Usage: swift tools/brand_options_167.swift <new-output-directory>

struct Outline {
    let data: [String]
    var svg: String { data.joined(separator: " ") }
    var bezier: NSBezierPath {
        let p = NSBezierPath()
        for line in data {
            let fields = line.split(separator: " ")
            let values = fields.dropFirst().compactMap { Double($0) }.map { CGFloat($0) }
            switch fields.first {
            case "M": p.move(to: NSPoint(x: values[0], y: values[1]))
            case "L": p.line(to: NSPoint(x: values[0], y: values[1]))
            case "C": p.curve(to: NSPoint(x: values[4], y: values[5]),
                              controlPoint1: NSPoint(x: values[0], y: values[1]),
                              controlPoint2: NSPoint(x: values[2], y: values[3]))
            case "Z": p.close()
            default: fatalError("Unknown path command")
            }
        }
        return p
    }
}

struct BrandOption {
    let id: String
    let title: String
    let subtitle: String
    let description: String
    let outline: Outline
    let hair: Outline
    let hairShadow: Outline
    let leftEar: Outline
    let rightEar: Outline
    let leftEye: NSRect
    let rightEye: NSRect
    let smile: Outline
}

let options: [BrandOption] = [
    BrandOption(
        id: "A-round", title: "A · 圆团", subtitle: "圆脸低耳，安静陪伴",
        description: "团子感最直接；耳尖平伸，脸和小髻形成稳定的正面轮廓。",
        outline: Outline(data: [
            "M 50 13", "C 33 13 21 20 19 36", "C 18 40 18 44 19 47",
            "C 13 49 6 57 4 66", "C 3 69 4 71 7 70", "C 14 68 21 65 25 63",
            "C 25 73 32 80 42 82", "C 39 85 39 89 42 93", "C 45 97 54 97 58 93",
            "C 62 90 61 85 58 82", "C 69 80 76 73 76 63",
            "C 81 65 88 68 94 70", "C 97 71 98 69 97 66", "C 95 57 88 49 81 47",
            "C 83 29 73 13 50 13", "Z"
        ]),
        hair: Outline(data: [
            "M 25 62", "C 24 72 32 80 42 82", "C 39 85 39 89 42 93",
            "C 45 97 54 97 58 93", "C 62 90 61 85 58 82", "C 69 80 77 72 76 62",
            "C 73 63 71 67 70 70", "C 59 77 42 77 31 69", "C 30 66 28 63 25 62", "Z"
        ]),
        hairShadow: Outline(data: [
            "M 42 82", "C 47 84 53 84 58 82", "C 55 79 46 79 42 82", "Z"
        ]),
        leftEar: Outline(data: [
            "M 10 63", "C 16 61 20 58 22 54", "C 17 55 13 58 10 63", "Z"
        ]),
        rightEar: Outline(data: [
            "M 90 63", "C 84 61 80 58 78 54", "C 83 55 87 58 90 63", "Z"
        ]),
        leftEye: NSRect(x: 34, y: 43, width: 7, height: 9),
        rightEye: NSRect(x: 59, y: 43, width: 7, height: 9),
        smile: Outline(data: ["M 45 33", "C 48 30 52 30 55 33"])
    ),
    BrandOption(
        id: "B-lift", title: "B · 抬耳", subtitle: "尖耳上扬，更有精神",
        description: "脸部略收、耳尖上扬；菜单栏里最容易先读到精灵身份。",
        outline: Outline(data: [
            "M 50 12", "C 33 12 23 23 23 39", "C 12 42 7 57 6 74",
            "C 6 77 8 78 10 75", "C 16 69 22 63 27 58", "C 26 71 33 80 42 82",
            "C 41 84 39 88 42 92", "C 44 96 51 98 56 95", "C 62 92 62 87 58 82",
            "C 68 80 75 70 74 58", "C 79 63 85 69 91 75", "C 94 78 96 77 95 73",
            "C 93 57 88 42 77 39", "C 77 23 67 12 50 12", "Z"
        ]),
        hair: Outline(data: [
            "M 27 57", "C 26 70 33 80 42 82", "C 41 84 39 88 42 92",
            "C 44 96 51 98 56 95", "C 62 92 62 87 58 82", "C 68 80 75 70 74 57",
            "C 70 60 69 65 68 69", "C 57 76 42 76 32 68", "C 31 63 30 60 27 57", "Z"
        ]),
        hairShadow: Outline(data: [
            "M 42 82", "C 47 84 53 84 58 82", "C 54 79 47 79 42 82", "Z"
        ]),
        leftEar: Outline(data: [
            "M 12 65", "C 18 59 21 54 22 47", "C 17 51 14 57 12 65", "Z"
        ]),
        rightEar: Outline(data: [
            "M 89 65", "C 83 59 80 54 79 47", "C 84 51 87 57 89 65", "Z"
        ]),
        leftEye: NSRect(x: 34, y: 41, width: 7, height: 9),
        rightEye: NSRect(x: 59, y: 41, width: 7, height: 9),
        smile: Outline(data: ["M 46 30", "C 49 28 52 28 55 31"])
    ),
    BrandOption(
        id: "C-turned", title: "C · 侧团", subtitle: "微微侧脸，轻巧亲近",
        description: "沿用道童微侧的姿态；一高一低的耳朵和偏髻保留自然感。",
        outline: Outline(data: [
            "M 53 13", "C 35 11 24 19 22 33", "C 21 38 21 43 22 47",
            "C 15 49 7 57 4 67", "C 3 70 4 72 7 71", "C 13 69 18 66 25 62",
            "C 25 71 29 78 36 82", "C 31 83 29 87 31 92", "C 33 97 40 99 45 96",
            "C 51 93 51 89 48 85", "C 62 85 75 79 79 67",
            "C 84 71 90 76 94 79", "C 97 82 99 80 97 75", "C 94 62 90 54 84 50",
            "C 86 42 85 32 81 25", "C 75 17 66 13 53 13", "Z"
        ]),
        hair: Outline(data: [
            "M 25 62", "C 25 71 29 78 36 82", "C 31 83 29 87 31 92",
            "C 33 97 40 99 45 96", "C 51 93 51 89 48 85", "C 62 85 75 79 79 67",
            "C 77 65 74 63 72 62", "C 73 69 68 75 59 76",
            "C 46 78 35 73 30 63", "C 28 61 27 61 25 62", "Z"
        ]),
        hairShadow: Outline(data: [
            "M 36 82", "C 39 84 44 86 48 85", "C 47 81 40 79 36 82", "Z"
        ]),
        leftEar: Outline(data: [
            "M 11 64", "C 17 61 22 57 24 53", "C 18 54 14 58 11 64", "Z"
        ]),
        rightEar: Outline(data: [
            "M 92 71", "C 88 66 83 61 80 57", "C 86 58 89 64 92 71", "Z"
        ]),
        leftEye: NSRect(x: 40, y: 41, width: 7, height: 9),
        rightEye: NSRect(x: 64, y: 43, width: 6.5, height: 8.5),
        smile: Outline(data: ["M 51 30", "C 54 27 58 28 61 32"])
    )
]

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: alpha)
}

let sage: UInt32 = 0x527C6A
let face: UInt32 = 0x41484B
let snow: UInt32 = 0xF7F3E9
let eye: UInt32 = 0xC96F6B

enum RenderStyle { case color, template, inverted }

func drawHead(_ option: BrandOption, in rect: NSRect, style: RenderStyle) {
    let context = NSGraphicsContext.current!.cgContext
    context.saveGState()
    defer { context.restoreGState() }
    context.translateBy(x: rect.minX, y: rect.minY)
    context.scaleBy(x: rect.width / 100, y: rect.height / 100)
    switch style {
    case .color:
        color(face).setFill(); option.outline.bezier.fill()
        color(0x5C6464).setFill(); option.leftEar.bezier.fill(); option.rightEar.bezier.fill()
        color(snow).setFill(); option.hair.bezier.fill()
        color(0xD5D4C9).setFill(); option.hairShadow.bezier.fill()
        color(eye).setFill()
        NSBezierPath(ovalIn: option.leftEye).fill(); NSBezierPath(ovalIn: option.rightEye).fill()
        color(0xAEBAB0).setStroke()
        let smile = option.smile.bezier; smile.lineWidth = 2.1; smile.lineCapStyle = .round; smile.stroke()
    case .template, .inverted:
        (style == .template ? NSColor.black : NSColor.white).setFill()
        option.outline.bezier.fill()
        // Eye holes are slightly larger than the colored pupils. At small sizes,
        // align their centers to pixel centers and retain a 1.8 px minimum diameter;
        // otherwise a correct vector hole can vanish into four antialiased pixels.
        context.setBlendMode(.clear)
        for eye in [option.leftEye, option.rightEye] {
            let base = eye.insetBy(dx: -1, dy: -0.4)
            let unitX = rect.width / 100, unitY = rect.height / 100
            let centerX = (floor(base.midX * unitX) + 0.5) / unitX
            let centerY = (floor(base.midY * unitY) + 0.5) / unitY
            let width = max(base.width, 1.8 / unitX), height = max(base.height, 1.8 / unitY)
            let hole = NSRect(x: centerX - width / 2, y: centerY - height / 2, width: width, height: height)
            NSBezierPath(ovalIn: hole).fill()
        }
        context.setBlendMode(.normal)
    }
}

func drawApplicationIcon(_ option: BrandOption, in rect: NSRect) {
    let side = rect.width
    let tile = rect.insetBy(dx: side * 0.07, dy: side * 0.07)
    color(sage).setFill()
    NSBezierPath(roundedRect: tile, xRadius: side * 0.193, yRadius: side * 0.193).fill()
    // Single, flat field shared by all options, so silhouette is the comparison.
    drawHead(option, in: NSRect(x: rect.minX + side * 0.105, y: rect.minY + side * 0.083,
                               width: side * 0.79, height: side * 0.79), style: .color)
}

func writePNG(width: Int, height: Int, to url: URL, draw: () -> Void) throws {
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
                                    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                    isPlanar: false, colorSpaceName: .deviceRGB,
                                    bytesPerRow: 0, bitsPerPixel: 0),
          let context = NSGraphicsContext(bitmapImageRep: rep) else {
        fatalError("Cannot create drawing surface")
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.cgContext.clear(CGRect(x: 0, y: 0, width: width, height: height))
    draw()
    NSGraphicsContext.restoreGraphicsState()
    try rep.representation(using: .png, properties: [:])!.write(to: url, options: .withoutOverwriting)
}

func text(_ value: String, in rect: NSRect, size: CGFloat, weight: NSFont.Weight = .regular,
          ink: UInt32 = 0x283B33, alignment: NSTextAlignment = .left) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = alignment
    paragraph.lineSpacing = 4
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: color(ink), .paragraphStyle: paragraph
    ]
    (value as NSString).draw(in: rect, withAttributes: attributes)
}

func roundedCard(_ rect: NSRect, fill: UInt32, radius: CGFloat = 20) {
    color(fill).setFill()
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).fill()
}

// The board draws the original vectors directly; it does not edit source images.
func menuRow(_ option: BrandOption, rect: NSRect, dark: Bool, multiplier: CGFloat = 1) {
    roundedCard(rect, fill: dark ? 0x202925 : 0xEEF2ED, radius: 11)
    let context = NSGraphicsContext.current!.cgContext
    let centers: [CGFloat] = [rect.minX + 67, rect.midX, rect.maxX - 67]
    for (index, nominal) in [16, 18, 22].enumerated() {
        let size = CGFloat(nominal) * multiplier
        // Composite into a small layer, so clear eye holes reveal the bar behind.
        context.saveGState()
        context.beginTransparencyLayer(auxiliaryInfo: nil)
        drawHead(option, in: NSRect(x: centers[index] - size / 2, y: rect.midY - size / 2 + 2,
                                   width: size, height: size), style: dark ? .inverted : .template)
        context.endTransparencyLayer()
        context.restoreGState()
    }
}

func makeSVG(_ option: BrandOption, template: Bool) -> String {
    func path(_ value: Outline, _ fill: String) -> String { "<path d=\"\(value.svg)\" fill=\"\(fill)\"/>" }
    func ellipse(_ rect: NSRect, _ fill: String) -> String {
        "<ellipse cx=\"\(rect.midX)\" cy=\"\(rect.midY)\" rx=\"\(rect.width/2)\" ry=\"\(rect.height/2)\" fill=\"\(fill)\"/>"
    }
    let eyes = [option.leftEye, option.rightEye]
    if template {
        return """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <title>天姥 \(option.title) menu template candidate</title>
        <defs><mask id="eyes" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
        <rect width="100" height="100" fill="white"/>
        \(eyes.map { ellipse($0.insetBy(dx: -1, dy: -0.4), "black") }.joined(separator: "\n"))
        </mask></defs>
        <g transform="translate(0,100) scale(1,-1)" mask="url(#eyes)">\(path(option.outline, "currentColor"))</g>
        </svg>
        """
    }
    return """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
    <title>天姥 \(option.title) transparent head candidate</title>
    <g transform="translate(0,100) scale(1,-1)">
    \(path(option.outline, "#41484B"))
    \(path(option.leftEar, "#5C6464"))\(path(option.rightEar, "#5C6464"))
    \(path(option.hair, "#F7F3E9"))\(path(option.hairShadow, "#D5D4C9"))
    \(eyes.map { ellipse($0, "#C96F6B") }.joined(separator: "\n"))
    <path d="\(option.smile.svg)" fill="none" stroke="#AEBAB0" stroke-width="2.1" stroke-linecap="round"/>
    </g></svg>
    """
}

guard CommandLine.arguments.count == 2 else { fatalError("Provide a new output directory") }
let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let manager = FileManager.default
guard !manager.fileExists(atPath: output.path) else { fatalError("Output must be new; refusing to overwrite candidates") }
try manager.createDirectory(at: output, withIntermediateDirectories: true)

var manifest: [[String: Any]] = []
for option in options {
    let directory = output.appendingPathComponent(option.id, isDirectory: true)
    try manager.createDirectory(at: directory, withIntermediateDirectories: true)
    try writePNG(width: 1024, height: 1024, to: directory.appendingPathComponent("app-1024.png")) {
        drawApplicationIcon(option, in: NSRect(x: 0, y: 0, width: 1024, height: 1024))
    }
    for size in [64, 128, 512] {
        try writePNG(width: size, height: size, to: directory.appendingPathComponent("head-\(size).png")) {
            drawHead(option, in: NSRect(x: 0, y: 0, width: size, height: size), style: .color)
        }
    }
    for size in [16, 18, 22] {
        for scale in [1, 2] {
            let suffix = scale == 1 ? "" : "@2x"
            let pixels = size * scale
            try writePNG(width: pixels, height: pixels,
                         to: directory.appendingPathComponent("MenuBarIcon-\(size)\(suffix).png")) {
                drawHead(option, in: NSRect(x: 0, y: 0, width: pixels, height: pixels), style: .template)
            }
        }
    }
    try makeSVG(option, template: false).write(to: directory.appendingPathComponent("head.svg"),
                                               atomically: true, encoding: .utf8)
    try makeSVG(option, template: true).write(to: directory.appendingPathComponent("menu-template.svg"),
                                              atomically: true, encoding: .utf8)
    let iconset = directory.appendingPathComponent("Tianmu-\(option.id).iconset", isDirectory: true)
    try manager.createDirectory(at: iconset, withIntermediateDirectories: true)
    for nominal in [16, 32, 128, 256, 512] {
        for scale in [1, 2] {
            let pixels = nominal * scale
            let name = "icon_\(nominal)x\(nominal)\(scale == 1 ? "" : "@2x").png"
            try writePNG(width: pixels, height: pixels, to: iconset.appendingPathComponent(name)) {
                drawApplicationIcon(option, in: NSRect(x: 0, y: 0, width: pixels, height: pixels))
            }
        }
    }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
    process.arguments = ["-c", "icns", iconset.path, "-o", directory.appendingPathComponent("Tianmu-\(option.id).icns").path]
    try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { fatalError("iconutil failed") }
    manifest.append(["id": option.id, "title": option.title, "description": option.description,
                     "application": "\(option.id)/app-1024.png", "head": "\(option.id)/head-512.png",
                     "menu_nominal_points": [16,18,22], "menu_scales": [1,2],
                     "icns": "\(option.id)/Tianmu-\(option.id).icns", "status": "candidate_not_installed"])
}

try writePNG(width: 1536, height: 1180, to: output.appendingPathComponent("天姥_团子精灵_三案对照.png")) {
    color(0xF4F3EE).setFill(); NSRect(x: 0, y: 0, width: 1536, height: 1180).fill()
    text("天姥 · 团子精灵", in: NSRect(x: 54, y: 1093, width: 1100, height: 52), size: 37, weight: .semibold)
    text("同一道童的三套图标备选  /  深灰脸 · 白发小髻 · 长尖耳 · 红眼", in: NSRect(x: 57, y: 1049, width: 1350, height: 34), size: 21, ink: 0x69776F)
    text("备选  ·  未替换现用图标", in: NSRect(x: 1160, y: 1105, width: 324, height: 25), size: 17, ink: 0x69776F, alignment: .right)
    for (index, option) in options.enumerated() {
        let x: CGFloat = 54 + CGFloat(index) * 486
        roundedCard(NSRect(x: x, y: 90, width: 456, height: 920), fill: 0xFFFFFF, radius: 24)
        text(option.title, in: NSRect(x: x+26, y: 946, width: 390, height: 39), size: 29, weight: .semibold)
        text(option.subtitle, in: NSRect(x: x+27, y: 909, width: 390, height: 28), size: 18, ink: 0x65786C)
        drawApplicationIcon(option, in: NSRect(x: x+98, y: 617, width: 260, height: 260))
        text("应用图标", in: NSRect(x: x+20, y: 588, width: 416, height: 24), size: 16, ink: 0x7D8780, alignment: .center)

        // Larger head and enlarged monochrome permit clean alpha / shape inspection.
        roundedCard(NSRect(x: x+24, y: 432, width: 408, height: 137), fill: 0xF5F5F0, radius: 14)
        drawHead(option, in: NSRect(x: x+52, y: 445, width: 108, height: 108), style: .color)
        let context = NSGraphicsContext.current!.cgContext
        context.saveGState(); context.beginTransparencyLayer(auxiliaryInfo: nil)
        drawHead(option, in: NSRect(x: x+190, y: 445, width: 108, height: 108), style: .template)
        context.endTransparencyLayer(); context.restoreGState()
        text("透明头像\n与剪影", in: NSRect(x: x+314, y: 476, width: 93, height: 52), size: 15, ink: 0x7D8780)

        text("菜单栏 · 原尺寸 1×", in: NSRect(x: x+27, y: 389, width: 390, height: 25), size: 17, ink: 0x65786C)
        menuRow(option, rect: NSRect(x: x+24, y: 326, width: 408, height: 49), dark: false)
        menuRow(option, rect: NSRect(x: x+24, y: 265, width: 408, height: 49), dark: true)
        for (i, value) in ["16 pt", "18 pt", "22 pt"].enumerated() {
            let centers: [CGFloat] = [x+91,x+228,x+365]
            text(value, in: NSRect(x: centers[i]-34, y: 233, width: 68, height: 22), size: 14, ink: 0x7D8780, alignment: .center)
        }
        text(option.description, in: NSRect(x: x+27, y: 136, width: 400, height: 64), size: 18, ink: 0x52645A)
    }
    text("参考 Memmy 的圆润与简省；保留天姥道童身份。请以 100% 显示查看 16 / 18 / 22 pt 菜单尺寸。", in: NSRect(x: 57, y: 35, width: 1420, height: 27), size: 17, ink: 0x69776F)
}

try writePNG(width: 900, height: 430, to: output.appendingPathComponent("菜单剪影_实际尺寸_浅深底.png")) {
    color(0xF4F3EE).setFill(); NSRect(x: 0, y: 0, width: 900, height: 430).fill()
    text("菜单剪影 · 按 100% 查看", in: NSRect(x: 30, y: 375, width: 840, height: 32), size: 22, weight: .medium)
    for (index, option) in options.enumerated() {
        let x: CGFloat = 30 + CGFloat(index) * 294
        text(option.title, in: NSRect(x: x, y: 322, width: 260, height: 30), size: 21, weight: .medium)
        // The narrow board uses exact 16/18/22 and twice-sized retina pixels.
        menuRow(option, rect: NSRect(x: x, y: 254, width: 264, height: 48), dark: false)
        menuRow(option, rect: NSRect(x: x, y: 196, width: 264, height: 48), dark: true)
        text("16              18              22 pt", in: NSRect(x: x, y: 162, width: 264, height: 24), size: 13, ink: 0x69776F, alignment: .center)
        menuRow(option, rect: NSRect(x: x, y: 63, width: 264, height: 75), dark: false, multiplier: 2)
    }
    text("上：实际像素大小 1×    下：2× 像素检查（显示尺寸仍应设置为 16 / 18 / 22 pt）", in: NSRect(x: 30, y: 21, width: 850, height: 23), size: 14, ink: 0x69776F)
}

let payload: [String: Any] = ["version": 1, "created": "2026-10-04", "purpose": "Tianmu alternate brand marks",
                              "generator": "tools/brand_options_167.swift", "production_replaced": false,
                              "palette": ["sage": "#527C6A", "face": "#41484B", "hair": "#F7F3E9", "eyes": "#C96F6B"],
                              "options": manifest]
try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted,.sortedKeys])
    .write(to: output.appendingPathComponent("manifest.json"), options: .withoutOverwriting)
print("Rendered \(options.count) original candidate families to \(output.path)")
