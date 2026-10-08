import AppKit

let sceneCanvasSize = NSSize(width: 370, height: 190)
private let defaultOverlayFrame = NSRect(x: 24, y: 24, width: 277.5, height: 142.5)

func normalizedSceneScale(_ percent: Double) -> Double {
    percent.isFinite ? min(150, max(20, percent)) : 75
}

func sceneScalePercent(_ frame: NSRect) -> Double {
    Double(min(frame.width / sceneCanvasSize.width, frame.height / sceneCanvasSize.height) * 100)
}

// Placement can use Dock space without allowing art into the menu bar/notch
// strip. Menus and floating tools still use NSScreen.visibleFrame separately.
func scenePlacementScreen(frame: NSRect, visibleFrame: NSRect) -> NSRect {
    let top = min(frame.maxY, visibleFrame.maxY)
    return NSRect(x: frame.minX, y: frame.minY, width: frame.width, height: max(0, top-frame.minY))
}

private func placementContentBounds(_ bounds: NSRect?) -> NSRect {
    let full = NSRect(x: 0, y: 0, width: 1, height: 1)
    guard let bounds, [bounds.minX,bounds.minY,bounds.width,bounds.height].allSatisfy({ $0.isFinite }),
          bounds.width > 0, bounds.height > 0 else { return full }
    let clipped = bounds.intersection(full)
    return clipped.isNull || clipped.width <= 0 || clipped.height <= 0 ? full : clipped
}

// contentBounds uses normalized, non-flipped view coordinates. Transparent
// canvas may leave the display; the complete stable artwork envelope may not.
func scaledOverlayFrame(_ frame: NSRect, percent: Double, screens: [NSRect], contentBounds: NSRect? = nil) -> NSRect {
    let art = placementContentBounds(contentBounds)
    let scale = normalizedSceneScale(percent) / 100
    let size = NSSize(width: sceneCanvasSize.width * scale, height: sceneCanvasSize.height * scale)
    return fitOverlayFrame(NSRect(x: frame.minX + (frame.width-size.width)*art.midX,
                                  y: frame.minY + (frame.height-size.height)*art.midY,
                                  width: size.width, height: size.height), screens: screens, contentBounds: art)
}

func fitOverlayFrame(_ candidate: NSRect, screens: [NSRect], contentBounds: NSRect? = nil) -> NSRect {
    let art = placementContentBounds(contentBounds)
    let available = screens.filter {
        [$0.minX,$0.minY,$0.width,$0.height].allSatisfy { $0.isFinite } && $0.width > 0 && $0.height > 0
    }
    guard let first = available.first else { return defaultOverlayFrame }
    let values = [candidate.minX, candidate.minY, candidate.width, candidate.height]
    let valid = values.allSatisfy { $0.isFinite } && candidate.width > 0 && candidate.height > 0
    let frame = valid ? candidate : defaultOverlayFrame
    let visible = NSRect(x: frame.minX+frame.width*art.minX, y: frame.minY+frame.height*art.minY,
                         width: frame.width*art.width, height: frame.height*art.height)
    let screen = available.max { a, b in
        let ai = a.intersection(visible), bi = b.intersection(visible)
        let aa = ai.isNull ? 0 : ai.width * ai.height
        let ba = bi.isNull ? 0 : bi.width * bi.height
        return aa < ba
    } ?? first
    // If a monitor disappeared, restore all visible art onto the primary screen.
    let target = available.contains(where: { $0.intersects(visible) }) ? screen : first
    let requested = max(0.2, min(frame.width / sceneCanvasSize.width, frame.height / sceneCanvasSize.height))
    let scale = min(1.5, requested, target.width / (sceneCanvasSize.width*art.width),
                    target.height / (sceneCanvasSize.height*art.height))
    let size = NSSize(width: sceneCanvasSize.width * scale, height: sceneCanvasSize.height * scale)
    let minX = target.minX-art.minX*size.width, maxX = target.maxX-art.maxX*size.width
    let minY = target.minY-art.minY*size.height, maxY = target.maxY-art.maxY*size.height
    return NSRect(x: min(max(frame.minX, minX), maxX), y: min(max(frame.minY, minY), maxY),
                  width: size.width, height: size.height)
}

final class WindowPlacementStore {
    let url: URL
    init(url: URL) { self.url = url }
    private struct Record: Codable { var version: Int? = 2; let x: Double; let y: Double; let width: Double; let height: Double }
    func restore(screens: [NSRect], contentBounds: NSRect? = nil) -> NSRect {
        guard let data = try? Data(contentsOf: url), let record = try? JSONDecoder().decode(Record.self, from: data) else {
            return fitOverlayFrame(defaultOverlayFrame, screens: screens, contentBounds: contentBounds)
        }
        var frame = NSRect(x: record.x, y: record.y, width: record.width, height: record.height)
        if record.version == nil {
            let scale = min(record.width / 540, record.height / 380)
            frame = NSRect(x: record.x + 55 * scale, y: record.y + 60 * scale,
                           width: 370 * scale, height: 190 * scale)
        }
        return fitOverlayFrame(frame, screens: screens, contentBounds: contentBounds)
    }
    func save(_ frame: NSRect) throws {
        let record = Record(x: frame.minX, y: frame.minY, width: frame.width, height: frame.height)
        let data = try JSONEncoder().encode(record)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
    }
}

enum InsectStyle: String, CaseIterable, Codable {
    case cute, realistic
    var title: String { self == .cute ? "可爱" : "写实" }
}

enum SceneExitAction: String, CaseIterable, Codable {
    case hideShrine, hideCompanions, quitApplication
    var title: String {
        switch self {
        case .hideShrine: return "关闭道童与神龛"
        case .hideCompanions: return "关闭道童、神龛与果蝇"
        case .quitApplication: return "关闭整个程序"
        }
    }
    var detail: String {
        switch self {
        case .hideShrine: return "保留果蝇与计时；从菜单栏小蜘蛛恢复。"
        case .hideCompanions: return "保留计时；从菜单栏小蜘蛛恢复桌宠。"
        case .quitApplication: return "退出后不再运行或提醒；再次打开应用恢复。"
        }
    }
}

// Kept beside the selected save, never in global preferences.
final class SceneTransparencyStore {
    let url: URL
    init(url: URL) { self.url = url }
    private struct Record: Codable {
        var transparency: Double = 100
        var avoidPointer: Bool? = true
        var insectsOnTop: Bool? = false
        var naturalCapture: Bool? = true
        var insectStyle: InsectStyle = .cute
        var exitAction: SceneExitAction = .hideShrine

        private enum CodingKeys: String, CodingKey {
            case transparency, avoidPointer, insectsOnTop, insectStyle, naturalCapture, exitAction
        }
        init() {}
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            transparency = try values.decode(Double.self, forKey: .transparency)
            avoidPointer = try values.decodeIfPresent(Bool.self, forKey: .avoidPointer)
            insectsOnTop = try values.decodeIfPresent(Bool.self, forKey: .insectsOnTop)
            naturalCapture = try values.decodeIfPresent(Bool.self,forKey:.naturalCapture)
            insectStyle = (try? values.decode(InsectStyle.self, forKey: .insectStyle)) ?? .cute
            exitAction = (try? values.decode(SceneExitAction.self, forKey: .exitAction)) ?? .hideShrine
        }
    }
    private func record() -> Record {
        guard let data = try? Data(contentsOf: url), let record = try? JSONDecoder().decode(Record.self, from: data) else { return Record() }
        return record
    }
    private func write(_ record: Record) throws {
        let data = try JSONEncoder().encode(record)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
    }
    static func normalized(_ value: Double) -> Double {
        value.isFinite ? min(100, max(0, value)) : 100
    }
    func restore() -> Double {
        Self.normalized(record().transparency)
    }
    func save(_ value: Double) throws {
        var next = record(); next.transparency = Self.normalized(value); try write(next)
    }
    func restoreAvoidance() -> Bool { record().avoidPointer ?? true }
    func saveAvoidance(_ enabled: Bool) throws { var next = record(); next.avoidPointer = enabled; try write(next) }
    func restoreInsectsOnTop() -> Bool { record().insectsOnTop ?? false }
    func saveInsectsOnTop(_ enabled: Bool) throws { var next = record(); next.insectsOnTop = enabled; try write(next) }
    func restoreNaturalCapture() -> Bool { record().naturalCapture ?? true }
    func saveNaturalCapture(_ enabled: Bool) throws { var next=record(); next.naturalCapture=enabled; try write(next) }
    func restoreInsectStyle() -> InsectStyle { record().insectStyle }
    func saveInsectStyle(_ style: InsectStyle) throws { var next = record(); next.insectStyle = style; try write(next) }
    func restoreExitAction() -> SceneExitAction { record().exitAction }
    func saveExitAction(_ action: SceneExitAction) throws { var next = record(); next.exitAction = action; try write(next) }
}
