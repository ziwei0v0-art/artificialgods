import AppKit
import CoreGraphics
import JavaScriptCore

struct DesktopInsectScreen: Equatable {
    let id: String
    let frame: NSRect

    static func current() -> [DesktopInsectScreen] {
        NSScreen.screens.compactMap { screen in
            guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return nil }
            return DesktopInsectScreen(id: number.stringValue, frame: screen.frame)
        }
    }
}

struct DesktopNaturalEventProof: Equatable {
    let targetProcessID: Int
    let handlingWindowNumber: Int

    static func from(_ event: CGEvent?) -> DesktopNaturalEventProof? {
        guard let event else { return nil }
        let process = event.getIntegerValueField(.eventTargetUnixProcessID)
        let window = event.getIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent)
        guard process > 0, process <= Int64(Int32.max), window > 0, window <= Int64(UInt32.max) else { return nil }
        return DesktopNaturalEventProof(targetProcessID: Int(process), handlingWindowNumber: Int(window))
    }
}

struct DesktopNaturalDockWindow: Equatable {
    let number: Int
    let ownerProcessID: Int
    let layer: Int
    let frame: NSRect
    let alpha: Double
}

// Geometry plus the current event's Finder desktop target establish exposed
// desktop input, not individual icon hit testing. The drag pasteboard counter
// separately vetoes file drags. No titles, pixels, AX or pasteboard content.
struct DesktopNaturalCaptureContext {
    let screenID: String
    let visibleFrame: NSRect
    let desktopFrames: [NSRect]
    var blockedFrames: [NSRect]
    let isReliable: Bool
    let dragPasteboardChangeCount: Int
    var sourceIsLocal = false
    var desktopEventTargets: [DesktopNaturalEventProof] = []
    // Keys are indexes into blockedFrames, so overlapping unrelated windows
    // remain blockers when one precise non-receiving Dock window is omitted.
    var dockBackgrounds: [Int: DesktopNaturalDockWindow] = [:]
    var eventProof: DesktopNaturalEventProof? = nil
    var approvedDockWindows: [DesktopNaturalDockWindow] = []

    func validatingDesktopEvent(_ proof: DesktopNaturalEventProof?,
                                observedWindowNumber: Int? = nil,
                                observerProcessID: Int? = nil) -> DesktopNaturalCaptureContext? {
        guard let proof, isReliable, !sourceIsLocal else { return nil }
        let desktopProof: DesktopNaturalEventProof
        if desktopEventTargets.contains(proof) {
            desktopProof = proof
        } else {
            // A real global NSEvent copy can expose this observer's PID in its
            // corresponding CGEvent, not the owner of the original window.
            // Normalize only that observed case: the associated NSEvent window
            // and CG handling window must agree on an exact current Finder
            // desktop target. Coordinates or a foreground Finder never suffice.
            guard let observerProcessID, observerProcessID > 0,
                  proof.targetProcessID == observerProcessID,
                  let observedWindowNumber, observedWindowNumber > 0,
                  observedWindowNumber == proof.handlingWindowNumber,
                  let target = desktopEventTargets.first(where: {
                      $0.handlingWindowNumber == observedWindowNumber
                  }) else { return nil }
            desktopProof = target
        }
        return omittingDockWindows(Array(dockBackgrounds.values), proof: desktopProof)
    }

    func revalidatingReleasedEvent(_ proof: DesktopNaturalEventProof,
                                  dockWindows: [DesktopNaturalDockWindow]) -> DesktopNaturalCaptureContext? {
        guard isReliable, !sourceIsLocal, desktopEventTargets.contains(proof),
              dockWindows.count == dockBackgrounds.count,
              dockWindows.allSatisfy({ dockBackgrounds.values.contains($0) }) else { return nil }
        // A changed, removed or new full-screen Dock invalidates this bounded
        // proof. Ordinary app windows may cover an already released net.
        return omittingDockWindows(dockWindows, proof: proof)
    }

    private func omittingDockWindows(_ windows: [DesktopNaturalDockWindow],
                                    proof: DesktopNaturalEventProof) -> DesktopNaturalCaptureContext {
        var result = self
        result.blockedFrames = blockedFrames.enumerated().compactMap { index, frame in
            if let dock = dockBackgrounds[index], windows.contains(dock) { return nil }
            return frame
        }
        result.eventProof = proof
        result.approvedDockWindows = windows
        result.dockBackgrounds = [:]
        return result
    }

    // Coverage alone never authorizes a new gesture. It is also used after a
    // proven release, when later application windows may cover the locked net.
    func coversDesktopFrame(_ rectangle: NSRect) -> Bool {
        guard isReliable, !sourceIsLocal, rectangle.minX.isFinite, rectangle.minY.isFinite,
              rectangle.width.isFinite, rectangle.height.isFinite else { return false }
        func covers(_ frame: NSRect) -> Bool {
            rectangle.minX >= frame.minX && rectangle.maxX <= frame.maxX
                && rectangle.minY >= frame.minY && rectangle.maxY <= frame.maxY
        }
        return covers(visibleFrame) && desktopFrames.contains(where: covers)
    }

    func permits(_ rectangle: NSRect) -> Bool {
        guard coversDesktopFrame(rectangle) else { return false }
        return !blockedFrames.contains { frame in
            // Include the boundary: a window resize border belongs to its app.
            rectangle.maxX >= frame.minX && rectangle.minX <= frame.maxX
                && rectangle.maxY >= frame.minY && rectangle.minY <= frame.maxY
        }
    }

    static func fromWindowInfo(_ rows: [[String: Any]], screenID: String, visibleFrame: NSRect,
                               primaryTop: CGFloat, excludingWindowNumbers: Set<Int>,
                               dragPasteboardChangeCount: Int,
                               applicationIdentifier: (Int) -> String? = {
                                   guard $0 > 0, $0 <= Int(Int32.max) else { return nil }
                                   return NSRunningApplication(processIdentifier: pid_t($0))?.bundleIdentifier
                               }) -> DesktopNaturalCaptureContext {
        var desktop: [NSRect] = [], blocked: [NSRect] = []
        var desktopTargets: [DesktopNaturalEventProof] = []
        var dockBackgrounds: [Int: DesktopNaturalDockWindow] = [:]
        var reliable = primaryTop.isFinite && !rows.isEmpty
        let desktopLevel = Int(CGWindowLevelForKey(.desktopWindow))
        let iconLevel = Int(CGWindowLevelForKey(.desktopIconWindow))
        for row in rows {
            guard let number = row[kCGWindowNumber as String] as? NSNumber else { reliable = false; continue }
            // Only this layer's known window IDs are safe to ignore. Other own
            // windows (settings, pet, reminders) must remain blockers.
            if excludingWindowNumbers.contains(number.intValue) { continue }
            guard let layer = row[kCGWindowLayer as String] as? NSNumber,
                  let alpha = row[kCGWindowAlpha as String] as? NSNumber,
                  let dictionary = row[kCGWindowBounds as String] as? [String: Any],
                  let bounds = CGRect(dictionaryRepresentation: dictionary as CFDictionary),
                  bounds.minX.isFinite, bounds.minY.isFinite,
                  bounds.width.isFinite, bounds.height.isFinite else { reliable = false; continue }
            guard alpha.doubleValue > 0, bounds.width > 0, bounds.height > 0 else { continue }
            let frame = NSRect(x: bounds.minX, y: primaryTop - bounds.maxY, width: bounds.width, height: bounds.height)
            let coversScreen = frame.minX <= visibleFrame.minX && frame.maxX >= visibleFrame.maxX
                && frame.minY <= visibleFrame.minY && frame.maxY >= visibleFrame.maxY
            if layer.intValue == desktopLevel || layer.intValue == iconLevel {
                desktop.append(frame)
                if layer.intValue == iconLevel, coversScreen,
                   let owner = row[kCGWindowOwnerPID as String] as? NSNumber,
                   applicationIdentifier(owner.intValue) == "com.apple.finder" {
                    desktopTargets.append(DesktopNaturalEventProof(targetProcessID: owner.intValue,
                        handlingWindowNumber: number.intValue))
                }
            } else if layer.intValue > desktopLevel {
                if layer.intValue == Int(CGWindowLevelForKey(.dockWindow)), coversScreen,
                   let owner = row[kCGWindowOwnerPID as String] as? NSNumber,
                   applicationIdentifier(owner.intValue) == "com.apple.dock" {
                    dockBackgrounds[blocked.count] = DesktopNaturalDockWindow(number: number.intValue,
                        ownerProcessID: owner.intValue, layer: layer.intValue, frame: frame, alpha: alpha.doubleValue)
                }
                blocked.append(frame)
            }
        }
        return DesktopNaturalCaptureContext(screenID: screenID, visibleFrame: visibleFrame,
            desktopFrames: desktop, blockedFrames: blocked, isReliable: reliable,
            dragPasteboardChangeCount: dragPasteboardChangeCount, desktopEventTargets: desktopTargets,
            dockBackgrounds: dockBackgrounds)
    }

    static func current(at point: NSPoint, excludingWindowNumbers: Set<Int>) -> DesktopNaturalCaptureContext? {
        guard let primary = NSScreen.screens.first,
              let screen = NSScreen.screens.first(where: { $0.frame.contains(point) }),
              let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber,
              let rows = CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String: Any]] else { return nil }
        return fromWindowInfo(rows, screenID: number.stringValue, visibleFrame: screen.visibleFrame,
            primaryTop: primary.frame.maxY, excludingWindowNumbers: excludingWindowNumbers,
            dragPasteboardChangeCount: NSPasteboard(name: .drag).changeCount)
    }
}

struct DesktopInsectPosition {
    let id: String
    let screenID: String
    // Global AppKit screen coordinates, in points, including negative screen origins.
    let point: NSPoint
    let color: String
    var activity: DesktopInsectActivity = .flying
    var velocity: NSPoint = .zero
    var heading: Double = 0
    var facingLeft = false
    var animationTime: TimeInterval = 0
    var sex: String = ""
    var opacity: Double = 1
    var scale: Double = 1
    var artworkSeed: Double = 0
}

enum DesktopInsectActivity: String { case flying, resting, crawling }

// Small host-owned landing rectangles, in global AppKit coordinates. These are
// geometry only: no Finder icon titles, accessibility data or screenshots.
struct DesktopInsectLandingSurface: Equatable {
    let id: String
    let frame: NSRect
}

// Runs the pinned original stepFly chain in one isolated JS context. The module
// is bundled alongside its unchanged source and provenance, never loaded from
// the working directory. Tests provide an explicit source URL.
private final class DesktopInsectMotion {
    private let context: JSContext?
    private var api: JSValue?
    private(set) var unavailableReason: String?

    init(moduleURL: URL?) {
        context = JSContext()
        let url = moduleURL ?? Bundle.main.resourceURL?
            .appendingPathComponent("backend/third_party/fly-paradise/desktop-motion.js")
        guard let context, let url else {
            unavailableReason = "原作果蝇运动模块不可用"; return
        }
        context.exceptionHandler = { [weak self] _, exception in
            self?.unavailableReason = "原作果蝇运动模块：" + (exception?.toString() ?? "未知错误")
        }
        do {
            let source = try String(contentsOf: url, encoding: .utf8)
            context.evaluateScript(source, withSourceURL: url)
            guard unavailableReason == nil,
                  let value = context.objectForKeyedSubscript("TianmuFlyMotion"),
                  !value.isUndefined, !value.isNull else {
                if unavailableReason == nil { unavailableReason = "原作果蝇运动模块未初始化" }
                return
            }
            api = value
        } catch { unavailableReason = "原作果蝇运动模块读取失败：\(error.localizedDescription)" }
    }

    func advance(_ input: [String: Any]) -> [[String: Any]] {
        guard unavailableReason == nil, let api,
              let value = api.invokeMethod("step", withArguments: [input]),
              unavailableReason == nil, let rows = value.toArray() as? [[String: Any]] else { return [] }
        return rows
    }

    func reset() { _ = api?.invokeMethod("reset", withArguments: []) }
}

struct DesktopWeavingConfiguration {
    var minimumDuration: TimeInterval = 1
    var maximumDuration: TimeInterval = 4
    var fullDurationArea: CGFloat = 800_000
    var retractionDuration: TimeInterval = 0.25

    func duration(for rectangle: NSRect) -> TimeInterval {
        let fraction = min(1, max(0, rectangle.width * rectangle.height / fullDurationArea))
        return minimumDuration + (maximumDuration - minimumDuration) * Double(fraction)
    }
}

private struct DesktopWeaveFrame {
    let rectangle: NSRect
    let progress: Double
    let retraction: Double
}

final class DesktopInsectWindow: NSWindow {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    // A desktop surface covers screen.frame, including the areas behind Dock/menu bar.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

private final class DesktopCaptureHandlePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

private final class DesktopCaptureHandleView: NSView {
    var onDown: ((NSPoint) -> Void)?
    var onDrag: ((NSPoint) -> Void)?
    var onUp: ((NSPoint) -> Void)?
    var onActivate: (() -> Bool)?

    override var isOpaque: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    private func screenPoint(_ event: NSEvent) -> NSPoint {
        window?.convertPoint(toScreen: event.locationInWindow) ?? event.locationInWindow
    }
    override func mouseDown(with event: NSEvent) { onDown?(screenPoint(event)) }
    override func mouseDragged(with event: NSEvent) { onDrag?(screenPoint(event)) }
    override func mouseUp(with event: NSEvent) { onUp?(screenPoint(event)) }
    override func rightMouseDown(with event: NSEvent) {}
    override func accessibilityPerformPress() -> Bool { onActivate?() ?? false }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        let outline = NSBezierPath(roundedRect: bounds.insetBy(dx: 1, dy: 1), xRadius: 7, yRadius: 7)
        NSColor(calibratedRed: 0.96, green: 0.91, blue: 0.79, alpha: 0.96).setFill(); outline.fill()
        NSColor(calibratedRed: 0.42, green: 0.35, blue: 0.28, alpha: 0.9).setStroke()
        outline.lineWidth = 1; outline.stroke()
        let paragraph = NSMutableParagraphStyle(); paragraph.alignment = .center
        ("拉网" as NSString).draw(in: NSRect(x: 1, y: 6, width: bounds.width - 2, height: 16),
            withAttributes: [.font: NSFont.systemFont(ofSize: 11), .paragraphStyle: paragraph,
                             .foregroundColor: NSColor(calibratedWhite: 0.2, alpha: 1)])
    }
}

// Quiet mode keeps only small backing surfaces resident. The full-screen views
// below are reserved for selection/weaving, with the exact same capture model.
private final class DesktopInsectSpriteView: NSView {
    private var insect: DesktopInsectPosition?
    private var localPoint = NSPoint.zero
    private var frameTime: TimeInterval = 0
    private struct FrameKey: Equatable {
        let pose: Int
        let point: NSPoint
        let heading: Double
        let scale: Double
        let opacity: Double
    }
    private var frameKey: FrameKey?
    @discardableResult
    func update(_ insect: DesktopInsectPosition?, at point: NSPoint = .zero, now: TimeInterval = 0) -> Bool {
        let next: FrameKey?
        if let insect {
            let motion: FlyParadiseArtwork.Motion = insect.activity == .flying ? .flying
                : insect.activity == .resting ? .resting : .crawling
            next = FrameKey(pose: FlyParadiseArtwork.shared.cachedPoseKey(color: insect.color, sex: insect.sex,
                motion: motion, now: now, seed: insect.artworkSeed), point: point,
                heading: insect.heading, scale: insect.scale, opacity: insect.opacity)
        } else { next = nil }
        self.insect = insect; localPoint = point; frameTime = now
        guard frameKey != next else { return false }
        frameKey = next; needsDisplay = true; return true
    }
    override var isOpaque: Bool { false }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        guard let insect, insect.opacity > 0 else { return }
        let motion: FlyParadiseArtwork.Motion = insect.activity == .flying ? .flying
            : insect.activity == .resting ? .resting : .crawling
        FlyParadiseArtwork.shared.drawCached(at: localPoint, color: insect.color, sex: insect.sex,
            heading: insect.heading, motion: motion, now: frameTime, seed: insect.artworkSeed,
            scale: insect.scale, opacity: insect.opacity)
    }
}

private final class DesktopInsectView: NSView {
    let screenFrame: NSRect
    let artwork: InsectArtwork
    var style: InsectStyle { didSet { if style != oldValue { needsDisplay = true } } }
    var frameTime: TimeInterval = 0
    var positions: [DesktopInsectPosition] = [] { didSet {
        // Clear the old footprint and paint the new one. A tiny fly must not
        // invalidate the entire Retina desktop backing surface every frame.
        for insect in oldValue where insect.opacity > 0 { invalidate(insect.point) }
        for insect in positions where insect.opacity > 0 { invalidate(insect.point) }
    } }
    var selection: NSRect? { didSet {
        if selection != oldValue { invalidate(oldValue); invalidate(selection) }
    } }
    var weave: DesktopWeaveFrame? { didSet { invalidate(oldValue?.rectangle); invalidate(weave?.rectangle) } }
    var onDown: ((NSPoint) -> Void)?
    var onDrag: ((NSPoint) -> Void)?
    var onUp: ((NSPoint) -> Void)?

    init(frame: NSRect, screenFrame: NSRect, artwork: InsectArtwork, style: InsectStyle) {
        self.screenFrame = screenFrame
        self.artwork = artwork; self.style = style
        super.init(frame: frame)
    }
    required init?(coder: NSCoder) { nil }
    override var isOpaque: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    private func invalidate(_ point: NSPoint) {
        invalidate(NSRect(x: point.x - 17, y: point.y - 17, width: 34, height: 34))
    }
    private func invalidate(_ rectangle: NSRect?) {
        guard let rectangle else { return }
        setNeedsDisplay(rectangle.offsetBy(dx: -screenFrame.minX, dy: -screenFrame.minY)
            .insetBy(dx: -3, dy: -3).intersection(bounds))
    }

    private func screenPoint(_ event: NSEvent) -> NSPoint {
        window?.convertPoint(toScreen: event.locationInWindow) ?? event.locationInWindow
    }
    override func mouseDown(with event: NSEvent) { onDown?(screenPoint(event)) }
    override func mouseDragged(with event: NSEvent) { onDrag?(screenPoint(event)) }
    override func mouseUp(with event: NSEvent) { onUp?(screenPoint(event)) }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill()
        dirtyRect.fill(using: .copy)
        for insect in positions where insect.opacity > 0 {
            let center = NSPoint(x: insect.point.x - screenFrame.minX, y: insect.point.y - screenFrame.minY)
            guard NSRect(x:center.x-17,y:center.y-17,width:34,height:34).intersects(dirtyRect) else { continue }
            let motion: FlyParadiseArtwork.Motion = insect.activity == .flying ? .flying
                : insect.activity == .resting ? .resting : .crawling
            FlyParadiseArtwork.shared.drawCached(at:center, color:insect.color, sex:insect.sex,
                heading:insect.heading, motion:motion, now:frameTime, seed:insect.artworkSeed,
                scale:insect.scale, opacity:insect.opacity)
        }
        if let selection {
            let local = selection.offsetBy(dx: -screenFrame.minX, dy: -screenFrame.minY)
            let net = NSBezierPath(rect: local)
            NSColor(calibratedRed: 0.74, green: 0.22, blue: 0.22, alpha: 0.15).setFill(); net.fill()
            NSColor(calibratedRed: 0.80, green: 0.18, blue: 0.18, alpha: 0.92).setStroke()
            net.lineWidth = 2; net.stroke()
        }
        if let weave { drawWeave(weave) }
    }

    private func drawWeave(_ weave: DesktopWeaveFrame) {
        let box = weave.rectangle.offsetBy(dx: -screenFrame.minX, dy: -screenFrame.minY)
        let center = NSPoint(x: box.midX, y: box.midY)
        let remaining = CGFloat(1 - weave.retraction)
        let halfWidth = box.width / 2 * remaining, halfHeight = box.height / 2 * remaining
        // Rectangular rings and their spokes cover the same area selected for capture.
        func webPoint(angle: Double, radius: Double) -> NSPoint {
            let x = cos(angle), y = sin(angle)
            let scale = max(abs(x), abs(y))
            return NSPoint(x: center.x + CGFloat(x / scale * radius) * halfWidth,
                           y: center.y + CGFloat(y / scale * radius) * halfHeight)
        }
        let skeleton = min(1, weave.progress / 0.2)
        let path = NSBezierPath()
        for spoke in 0..<8 {
            let length = min(1, max(0, skeleton * 8 - Double(spoke)))
            guard length > 0 else { continue }
            path.move(to: center)
            path.line(to: webPoint(angle: Double(spoke) * .pi / 4, radius: length))
        }
        let threadProgress = min(1, max(0, (weave.progress - 0.2) / 0.8))
        let fullAngle = Double.pi * 2 * 6
        let angle = threadProgress * fullAngle
        if threadProgress > 0 {
            path.move(to: center)
            let segments = max(1, Int(ceil(angle / (.pi / 32))))
            for index in 1...segments {
                let theta = angle * Double(index) / Double(segments)
                path.line(to: webPoint(angle: theta, radius: theta / fullAngle))
            }
        }
        if weave.progress >= 1 {
            path.appendRect(NSRect(x:center.x-halfWidth, y:center.y-halfHeight, width:halfWidth*2, height:halfHeight*2))
        }
        NSColor(calibratedRed: 0.42, green: 0.35, blue: 0.28, alpha: 0.7 * remaining).setStroke()
        path.lineWidth = 2; path.stroke()
        NSColor(calibratedRed: 0.96, green: 0.91, blue: 0.79, alpha: 0.95 * remaining).setStroke()
        path.lineWidth = 0.8; path.stroke()

        // A small temporary spider follows the growing thread from center outwards.
        let spider = webPoint(angle: angle, radius: threadProgress)
        let legs = NSBezierPath()
        for side: CGFloat in [-1, 1] {
            for leg in 0..<4 {
                let y = CGFloat(leg) * 2 - 3
                legs.move(to: NSPoint(x:spider.x + side * 2, y:spider.y + y))
                legs.line(to: NSPoint(x:spider.x + side * 6, y:spider.y + y * 1.5))
                legs.line(to: NSPoint(x:spider.x + side * 8, y:spider.y + y * 2))
            }
        }
        NSColor(calibratedWhite: 0.20, alpha: remaining).setStroke()
        legs.lineWidth = 1; legs.stroke()
        NSColor(calibratedWhite: 0.20, alpha: remaining).setFill()
        NSBezierPath(ovalIn: NSRect(x:spider.x-3, y:spider.y-4, width:6, height:8)).fill()
        NSBezierPath(ovalIn: NSRect(x:spider.x-2, y:spider.y+2, width:4, height:4)).fill()
    }
}

// The application host owns the existing refresh timer and keyboard focus.
// Construction and capture never show, activate, or key a window.
// A screen rebuild preserves the visibility last requested with show/hide.
enum DesktopCaptureState: String {
    case idle, armed, dragging, weaving, completed
}

// Optional diagnostics only. The host may attach a counter/logger when explicitly
// requested; these reasons contain no coordinates, window titles or user data.
enum DesktopNaturalCaptureObservation: String {
    case eventReceived, localInput, inputUnavailable, eventTooOld
    case contextUnavailable, eventProofMissing, eventTargetNotDesktop
    case gestureModified, desktopNotExposed, fileDrag, screenChanged
    case gestureBegan, weavingBegan, releaseContextInvalid, captureSubmitted
}

final class DesktopInsects {
    private struct Insect {
        let id: String
        let x: CGFloat
        let y: CGFloat
        let color: String
        let sex: String
    }
    private(set) var windows: [DesktopInsectWindow] = []
    private(set) var spriteWindows: [DesktopInsectWindow] = []
    // Exclude only this layer's passive surfaces. Its interactive legacy handle
    // retains the existing desktop-occlusion rules.
    var contextExcludedWindowNumbers: Set<Int> {
        Set((windows + spriteWindows).map { $0.windowNumber }.filter { $0 > 0 })
    }
    private(set) var captureOverlayPresented = false
    private var spriteViews: [DesktopInsectSpriteView] = []
    private var spriteScreenIDs: [String] = []
    private var orderedSpriteWindows = Set<ObjectIdentifier>()
    private var spriteRequestedOrigins: [NSPoint?] = []
    private(set) var spriteWindowMoveCount = 0
    private(set) var spriteRedrawRequestCount = 0
    private(set) var positions: [DesktopInsectPosition] = []
    private(set) var style: InsectStyle
    var availableStyles: Set<InsectStyle> { artwork.availableStyles }
    private(set) var isCapturing = false
    var isWeaving: Bool { weavingState != nil }
    private(set) var weaveProgress: Double?
    private(set) var captureState: DesktopCaptureState = .idle
    // Number of current IDs submitted by the completed net. The host owns
    // backend acknowledgement and must not treat this as a save receipt.
    private(set) var lastCaptureCount: Int?
    var onCaptureStateChange: ((DesktopCaptureState) -> Void)?
    var onCapture: (([String]) -> Void)?
    var onNaturalCaptureBegin: (() -> Void)?
    var onNaturalCaptureObservation: ((DesktopNaturalCaptureObservation) -> Void)?
    private(set) var captureHandleWindow: NSWindow?
    private(set) var isNaturalHandleVisible = false
    private(set) var naturalCaptureEnabled = true
    // Remains true through released weaving, so the host can keep HUD/focus
    // behavior reserved for the explicit menu entry.
    private(set) var captureIsNatural = false
    var hasNaturalGesture: Bool { naturalGesture?.isNatural == true || (captureIsNatural && isCapturing) }

    private struct NaturalGesture {
        let origin: NSPoint
        let screenID: String
        let pasteboardChangeCount: Int
        let isNatural: Bool
    }
    private var naturalGesture: NaturalGesture?

    private struct WeavingState {
        let rectangle: NSRect
        let startedAt: TimeInterval
        let duration: TimeInterval
        let naturalScreenID: String?
        let naturalEventProof: DesktopNaturalEventProof?
        let approvedDockWindows: [DesktopNaturalDockWindow]
        let naturalReleaseIDs: Set<String>?
        var completedAt: TimeInterval?
    }

    private var screens: [DesktopInsectScreen] = []
    private var insects: [Insect] = []
    private var screenForID: [String: String] = [:]
    private var byID: [String: Insect] = [:]
    private var cachedSourceRows: [[String: Any]] = []
    private var cachedScreens: [[String: Any]] = []
    private var cachedSurfaces: [[String: Any]] = []
    private var motionInputDirty = true
    private(set) var motionInputBuildCount = 0
    private let quietPresentation: Bool
    private let motion: DesktopInsectMotion
    var motionUnavailableReason: String? { motion.unavailableReason }
    private var behaviorPointer: [String: Any] = ["enabled": false]
    private var previousBehaviorPointer: (point: NSPoint, time: TimeInterval)?
    private var behaviorButtonsPressed = 0
    private var landingSurfaces: [DesktopInsectLandingSurface]?
    private var views: [DesktopInsectView] = []
    private var aboveApplications = false
    private var shown = false
    private var closed = false
    private var dragStart: NSPoint?
    private var dragCurrent: NSPoint?
    private var naturalAnchorID: String?
    private var naturalAnchorPoint: NSPoint?
    private var naturalPressStart: NSPoint?
    private let renderTime: () -> TimeInterval
    private let naturalEventTime: () -> TimeInterval
    private let artwork: InsectArtwork
    private let windowPresenter: (NSWindow) -> Void
    private let naturalContextProvider: (NSPoint, Set<Int>) -> DesktopNaturalCaptureContext?
    private let weaving: DesktopWeavingConfiguration
    private var weavingState: WeavingState?
    private var captureGeneration = 0
    private var resignObserver: NSObjectProtocol?

    init(motionModuleURL: URL? = nil, quietPresentation: Bool = true,
         screens: [DesktopInsectScreen] = DesktopInsectScreen.current(),
         renderTime: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         naturalEventTime: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         weaving: DesktopWeavingConfiguration = DesktopWeavingConfiguration(),
         windowPresenter: @escaping (NSWindow) -> Void = { $0.orderFrontRegardless() },
         naturalContextProvider: @escaping (NSPoint, Set<Int>) -> DesktopNaturalCaptureContext? = {
             DesktopNaturalCaptureContext.current(at: $0, excludingWindowNumbers: $1)
         },
         artwork: InsectArtwork = .production, style: InsectStyle = .cute) {
        self.motion = DesktopInsectMotion(moduleURL: motionModuleURL)
        self.quietPresentation = quietPresentation
        self.renderTime = renderTime
        self.naturalEventTime = naturalEventTime
        self.artwork = artwork
        self.style = artwork.availableStyles.contains(style) ? style
            : artwork.availableStyles.contains(.cute) ? .cute
            : artwork.availableStyles.contains(.realistic) ? .realistic : .cute
        self.weaving = weaving
        self.windowPresenter = windowPresenter
        self.naturalContextProvider = naturalContextProvider
        updateScreens(screens)
        resignObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didResignActiveNotification, object: nil, queue: .main
        ) { [weak self] _ in
            guard let self, !self.captureIsNatural, self.naturalGesture == nil,
                  self.captureState != .armed else { return }
            self.cancelActiveGesture()
        }
    }

    deinit {
        if let resignObserver { NotificationCenter.default.removeObserver(resignObserver) }
        for window in windows + spriteWindows { window.ignoresMouseEvents = true; window.close() }
        captureHandleWindow?.ignoresMouseEvents = true
        captureHandleWindow?.close()
    }

    @discardableResult
    func setStyle(_ style: InsectStyle) -> Bool {
        guard !closed, availableStyles.contains(style) else { return false }
        guard style != self.style else { return true }
        self.style = style
        // Retain the most recently refreshed positions and time. Calling refresh
        // here would also advance weaving and could submit a capture.
        for view in views { view.style = style }
        return true
    }

    func update(rows: [[String: Any]]) {
        guard !closed else { return }
        var seen = Set<String>()
        insects = rows.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty, !seen.contains(id),
                  let x = row["x"] as? NSNumber, let y = row["y"] as? NSNumber,
                  x.doubleValue.isFinite, y.doubleValue.isFinite,
                  let color = row["color"] as? String else { return nil }
            seen.insert(id)
            return Insect(id: id, x: CGFloat(min(1, max(0, x.doubleValue))),
                          y: CGFloat(min(1, max(0, y.doubleValue))), color: color,
                          sex: row["sex"] as? String ?? "")
        }
        screenForID = screenForID.filter { seen.contains($0.key) }
        byID = Dictionary(uniqueKeysWithValues: insects.map { ($0.id, $0) })
        motionInputDirty = true
        refresh()
    }

    func updateScreens(_ newScreens: [DesktopInsectScreen]) {
        guard !closed else { return }
        cancelCapture()
        var seen = Set<String>()
        let valid = newScreens.filter {
            !$0.id.isEmpty && $0.frame.minX.isFinite && $0.frame.minY.isFinite
                && $0.frame.width.isFinite && $0.frame.height.isFinite
                && $0.frame.width > 0 && $0.frame.height > 0 && seen.insert($0.id).inserted
        }
        guard valid != screens else { refresh(); return }
        for window in windows + spriteWindows { window.close() }
        spriteWindows = []; spriteViews = []; spriteScreenIDs = []; orderedSpriteWindows = []; spriteRequestedOrigins = []
        captureOverlayPresented = false
        windows = []; views = []; screens = valid
        motionInputDirty = true
        for screen in screens {
            appendCaptureWindow(for: screen)
            if quietPresentation {
                let side = min(40, screen.frame.width, screen.frame.height)
                for _ in 0..<3 {
                    let frame = NSRect(x: screen.frame.minX, y: screen.frame.minY, width: side, height: side)
                    let sprite = DesktopInsectWindow(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: true)
                    sprite.isReleasedWhenClosed = false
                    sprite.isOpaque = false; sprite.backgroundColor = .clear; sprite.hasShadow = false
                    sprite.ignoresMouseEvents = true
                    sprite.setAccessibilityElement(false)
                    sprite.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
                    let spriteView = DesktopInsectSpriteView(frame: NSRect(origin: .zero, size: frame.size))
                    spriteView.setAccessibilityElement(false)
                    sprite.contentView = spriteView
                    spriteWindows.append(sprite); spriteViews.append(spriteView); spriteScreenIDs.append(screen.id)
                    spriteRequestedOrigins.append(nil)
                }
            }
        }
        applyLevel()
        refresh()
        if shown && !quietPresentation { for window in windows { windowPresenter(window) } }
    }

    private func appendCaptureWindow(for screen: DesktopInsectScreen) {
        let window = DesktopInsectWindow(contentRect: screen.frame, styleMask: [.borderless], backing: .buffered, defer: quietPresentation)
        window.isReleasedWhenClosed = false
        window.isOpaque = false; window.backgroundColor = .clear; window.hasShadow = false
        window.ignoresMouseEvents = true
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        let view = DesktopInsectView(frame: NSRect(origin: .zero, size: screen.frame.size), screenFrame: screen.frame,
                                     artwork: artwork, style: style)
        view.onDown = { [weak self] in self?.startDrag(at: $0) }
        view.onDrag = { [weak self] in self?.continueDrag(at: $0) }
        view.onUp = { [weak self] in self?.finishDrag(at: $0) }
        window.contentView = view
        windows.append(window); views.append(view)
    }

    func setLevel(aboveApplications: Bool) {
        self.aboveApplications = aboveApplications
        applyLevel()
    }

    private func applyLevel() {
        let desktopLevel = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        let insectLevel = aboveApplications ? NSWindow.Level.floating : desktopLevel
        // Pinning insects must not put the passive Finder net over work windows.
        // The production presentation has separate sprite and net surfaces.
        let netLevel = captureIsNatural ? desktopLevel
            : aboveApplications || isCapturing ? NSWindow.Level.floating : desktopLevel
        for window in windows { window.level = netLevel }
        for window in spriteWindows { window.level = insectLevel }
        captureHandleWindow?.level = netLevel
    }

    func show() {
        guard !closed else { return }
        shown = true; refresh()
        if !quietPresentation { for window in windows { windowPresenter(window) } }
    }

    func hide() {
        shown = false; cancelCapture()
        for window in windows + spriteWindows { window.orderOut(nil) }
        orderedSpriteWindows = []; captureOverlayPresented = false
    }

    func close() {
        hide(); closed = true
        if let resignObserver { NotificationCenter.default.removeObserver(resignObserver) }
        resignObserver = nil
        for window in windows + spriteWindows { window.close() }
        captureHandleWindow?.close(); captureHandleWindow = nil
        windows = []; views = []; positions = []; insects = []; screenForID = [:]
        spriteWindows = []; spriteViews = []; spriteScreenIDs = []; orderedSpriteWindows = []; spriteRequestedOrigins = []
        byID = [:]; cachedSourceRows = []; cachedScreens = []; cachedSurfaces = []
        motion.reset()
    }

    private func rebuildMotionInputs() {
        guard motionInputDirty else { return }
        motionInputDirty = false; motionInputBuildCount += 1
        cachedSourceRows = insects.compactMap { insect in
            let hash = Self.stableHash(insect.id)
            guard !screens.isEmpty else {
                return ["id": insect.id, "seed": String(hash), "x": 0, "y": 0, "sex": insect.sex.lowercased()]
            }
            let screen = screens.first { $0.id == screenForID[insect.id] }
                ?? screens[Int(hash % UInt64(screens.count))]
            let frame = screen.frame
            let insetX = min(12, frame.width / 2), insetY = min(12, frame.height / 2)
            return ["id": insect.id, "seed": String(hash),
                    "x": frame.minX + insetX + insect.x * (frame.width - 2 * insetX),
                    "y": -(frame.maxY - insetY - insect.y * (frame.height - 2 * insetY)),
                    "sex": insect.sex.lowercased()]
        }
        let surfaces = landingSurfaces ?? screens.flatMap { screen -> [DesktopInsectLandingSurface] in
            let f = screen.frame, w = min(32, f.width), h = min(32, f.height)
            let xs = [f.minX, f.midX - w/2, f.maxX - w]
            let ys = [f.minY, f.midY - h/2, f.maxY - h]
            return (0..<3).flatMap { x in (0..<3).compactMap { y in
                guard x != 1 || y != 1 else { return nil }
                return DesktopInsectLandingSurface(id: "screen-edge-\(screen.id)-\(x)-\(y)",
                    frame: NSRect(x: xs[x], y: ys[y], width: w, height: h))
            } }
        }
        func rectangle(_ frame: NSRect, id: String) -> [String: Any] {
            ["id": id, "name": id, "x": frame.minX, "y": -frame.maxY, "w": frame.width, "h": frame.height]
        }
        cachedScreens = screens.map { rectangle($0.frame, id: $0.id) }
        cachedSurfaces = surfaces.filter { surface in screens.contains { $0.frame.contains(surface.frame) } }
            .map { rectangle($0.frame, id: $0.id) }
    }

    // Positions keep every real ID; opacity limits presentation without deleting
    // population or inventing proxy IDs. Coordinates remain global AppKit points.
    func refresh() {
        guard !closed else { return }
        let time = renderTime()
        let now = time.isFinite ? time : 0
        rebuildMotionInputs()
        let input: [String: Any] = ["rows": cachedSourceRows,
            "screens": cachedScreens, "icons": cachedSurfaces, "quietPresentation": quietPresentation,
            "pointer": behaviorPointer, "time": time.isFinite ? time as Any : NSNull(),
            "suppressThreat": isCapturing || isWeaving || hasNaturalGesture || behaviorButtonsPressed != 0]
        positions = motion.advance(input).compactMap { row in
            guard let id = row["id"] as? String, let insect = byID[id],
                  let screenID = row["screenID"] as? String, screens.contains(where: { $0.id == screenID }),
                  let x = row["x"] as? Double, let y = row["y"] as? Double,
                  let vx = row["vx"] as? Double, let vy = row["vy"] as? Double,
                  let heading = row["heading"] as? Double, let animationTime = row["animationTime"] as? Double,
                  [x,y,vx,vy,heading,animationTime].allSatisfy(\.isFinite),
                  let rawActivity = row["activity"] as? String,
                  let activity = DesktopInsectActivity(rawValue: rawActivity) else { return nil }
            screenForID[id] = screenID
            return DesktopInsectPosition(id: id, screenID: screenID, point: NSPoint(x: x, y: -y), color: insect.color,
                activity: activity, velocity: NSPoint(x: vx, y: -vy), heading: -heading,
                facingLeft: cos(heading) < 0, animationTime: animationTime, sex: insect.sex,
                opacity: min(1,max(0,row["opacity"] as? Double ?? 1)),
                scale: row["scale"] as? Double ?? 1, artworkSeed: row["seed"] as? Double ?? 0)
        }
        for (index, view) in views.enumerated() {
            view.frameTime = now
            if !quietPresentation { view.positions = positions.filter { $0.screenID == screens[index].id && $0.opacity > 0 } }
        }
        updateSpriteWindows(now: now)
        // The fly owns a hover/press affordance, but never an active selection.
        // Automatic capture may remove it while the player is still drawing a net.
        if !isCapturing, let anchor = naturalAnchorID, !positions.contains(where: { $0.id == anchor }) {
            cancelCapture()
        }
        advanceWeaving(now: now)
    }

    private func updateSpriteWindows(now: TimeInterval) {
        guard quietPresentation else { return }
        var visibleByScreen: [String: [DesktopInsectPosition]] = [:]
        for insect in positions where insect.opacity > 0 { visibleByScreen[insect.screenID, default: []].append(insect) }
        for id in visibleByScreen.keys { visibleByScreen[id]?.sort { $0.id < $1.id } }
        var nextIndex: [String: Int] = [:]
        for index in spriteWindows.indices {
            let id = spriteScreenIDs[index], slot = nextIndex[id, default: 0]
            nextIndex[id] = slot + 1
            let window = spriteWindows[index], view = spriteViews[index]
            guard let insects = visibleByScreen[id], slot < insects.count,
                  let screen = screens.first(where: { $0.id == id }) else {
                if view.update(nil) { spriteRedrawRequestCount += 1 }
                if orderedSpriteWindows.remove(ObjectIdentifier(window)) != nil { window.orderOut(nil) }
                continue
            }
            let insect = insects[slot], size = window.frame.size
            let x = min(screen.frame.maxX - size.width, max(screen.frame.minX, insect.point.x - size.width / 2))
            let y = min(screen.frame.maxY - size.height, max(screen.frame.minY, insect.point.y - size.height / 2))
            let backingScale = max(1, window.backingScaleFactor)
            let origin = NSPoint(x: (x * backingScale).rounded() / backingScale,
                                 y: (y * backingScale).rounded() / backingScale)
            // Comparing a fractional model point to AppKit's rounded result can
            // repeatedly send stationary windows through setFrameCommon/AX.
            // Remember the requested backing-pixel origin as well as the result.
            if spriteRequestedOrigins[index] != origin {
                if window.frame.origin != origin { window.setFrameOrigin(origin); spriteWindowMoveCount += 1 }
                spriteRequestedOrigins[index] = origin
            }
            // AppKit may align an ordered window to backing pixels. Use its
            // actual origin so the drawn body still matches capture coordinates.
            let localPoint = NSPoint(x: insect.point.x - window.frame.minX, y: insect.point.y - window.frame.minY)
            if view.update(insect, at: localPoint, now: now) { spriteRedrawRequestCount += 1 }
            if shown && orderedSpriteWindows.insert(ObjectIdentifier(window)).inserted { windowPresenter(window) }
        }
    }

    private func syncCaptureWindowsVisibility() {
        guard quietPresentation else { return }
        let selectionVisible = !captureIsNatural && (captureRectangle.map { $0.width > 0 && $0.height > 0 } ?? false)
        let desired = shown && (selectionVisible || isWeaving)
        guard desired != captureOverlayPresented else { return }
        captureOverlayPresented = desired
        for window in windows {
            if desired { windowPresenter(window) } else { window.orderOut(nil) }
        }
        if !desired {
            // orderOut alone can retain a large WindowServer backing store.
            // Once the net is gone, replace it with an unshown deferred window.
            // Sprite windows and every insect/capture coordinate stay intact.
            for window in windows { window.close() }
            windows = []; views = []
            for screen in screens { appendCaptureWindow(for: screen) }
            applyLevel()
        }
    }

    // Ambient observation only. The host supplies an enabled sample only over
    // exposed desktop; this never intercepts input or requests permissions.
    func updateBehaviorPointer(_ point: NSPoint, buttonsPressed: Int, enabled: Bool = true) {
        let time = renderTime()
        behaviorButtonsPressed = buttonsPressed
        guard !closed, enabled, point.x.isFinite, point.y.isFinite, time.isFinite else {
            previousBehaviorPointer = nil; behaviorPointer = ["enabled": false]; return
        }
        var vx = 0.0, vy = 0.0
        if let previous = previousBehaviorPointer {
            let dt = time - previous.time
            if dt > 0 && dt <= 0.25 {
                vx = (point.x - previous.point.x) / dt
                vy = -(point.y - previous.point.y) / dt
            }
        }
        previousBehaviorPointer = (point, time)
        behaviorPointer = ["enabled": true, "x": point.x, "y": -point.y, "vx": vx, "vy": vy]
    }

    func updateBehaviorLandingSurfaces(_ surfaces: [DesktopInsectLandingSurface]?) {
        var seen = Set<String>()
        let valid = surfaces?.filter { surface in
            !surface.id.isEmpty && seen.insert(surface.id).inserted && surface.frame.width >= 18 && surface.frame.height >= 18
                && [surface.frame.minX,surface.frame.minY,surface.frame.width,surface.frame.height].allSatisfy(\.isFinite)
                && screens.contains(where: { $0.frame.contains(surface.frame) })
        }
        if valid != landingSurfaces { landingSurfaces = valid; motionInputDirty = true }
    }

    // Polling observes hover only. A press already owned by another application
    // can never create a handle or start a capture midway through its gesture.
    func updatePointer(_ point: NSPoint, buttonsPressed: Int, enabled: Bool = true) {
        if naturalCaptureEnabled { hideNaturalHandle(); return }
        guard !closed, shown, enabled, point.x.isFinite, point.y.isFinite else {
            if naturalAnchorID != nil { cancelCapture() }
            return
        }
        if naturalPressStart != nil { return }
        guard !isCapturing, !isWeaving else { return }
        guard buttonsPressed == 0 else { hideNaturalHandle(); return }
        if let anchor = naturalAnchorPoint, isNaturalHandleVisible {
            if hypot(point.x - anchor.x, point.y - anchor.y) > 90 { hideNaturalHandle() }
            return
        }
        guard let nearest = positions.filter({ $0.opacity > 0.05 }).min(by: {
            hypot($0.point.x - point.x, $0.point.y - point.y)
                < hypot($1.point.x - point.x, $1.point.y - point.y)
        }), hypot(nearest.point.x - point.x, nearest.point.y - point.y) <= 60,
        let screen = screens.first(where: { $0.id == nearest.screenID }),
        screen.frame.width >= 40, screen.frame.height >= 28 else { return }
        showNaturalHandle(near: nearest, on: screen)
    }

    private func showNaturalHandle(near insect: DesktopInsectPosition, on screen: DesktopInsectScreen) {
        let window: NSWindow
        if let existing = captureHandleWindow {
            window = existing
        } else {
            let panel = DesktopCaptureHandlePanel(contentRect: NSRect(x: 0, y: 0, width: 40, height: 28),
                styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.isReleasedWhenClosed = false
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
            panel.hidesOnDeactivate = false; panel.isFloatingPanel = false
            panel.becomesKeyOnlyIfNeeded = true
            panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
            let view = DesktopCaptureHandleView(frame: NSRect(x: 0, y: 0, width: 40, height: 28))
            view.toolTip = "点击准备拉网，或按住拖动"
            view.setAccessibilityElement(true)
            view.setAccessibilityRole(.button)
            view.setAccessibilityLabel("拉网")
            view.setAccessibilityHelp("点击准备拉网，或按住拖动")
            view.onDown = { [weak self, weak panel] point in
                guard let panel else { return }; self?.pressNaturalHandle(at: point, from: panel)
            }
            view.onDrag = { [weak self, weak panel] point in
                guard let panel else { return }; self?.dragNaturalHandle(to: point, from: panel)
            }
            view.onUp = { [weak self, weak panel] point in
                guard let panel else { return }; self?.releaseNaturalHandle(at: point, from: panel)
            }
            view.onActivate = { [weak self, weak panel] in
                guard let self, let panel else { return false }
                return self.activateNaturalHandle(from: panel)
            }
            panel.contentView = view
            captureHandleWindow = panel; window = panel
        }
        let x = min(screen.frame.maxX - 40, max(screen.frame.minX, insect.point.x - 40))
        let y = min(screen.frame.maxY - 28, max(screen.frame.minY, insect.point.y + 10))
        window.setFrame(NSRect(x: x, y: y, width: 40, height: 28), display: true)
        naturalAnchorID = insect.id; naturalAnchorPoint = insect.point
        isNaturalHandleVisible = true; window.ignoresMouseEvents = false
        applyLevel(); windowPresenter(window)
    }

    private func hideNaturalHandle() {
        naturalAnchorID = nil; naturalAnchorPoint = nil; naturalPressStart = nil
        isNaturalHandleVisible = false
        captureHandleWindow?.ignoresMouseEvents = true
        captureHandleWindow?.orderOut(nil)
    }

    private func pressNaturalHandle(at point: NSPoint, from window: NSWindow) {
        guard !closed, shown, isNaturalHandleVisible, captureHandleWindow === window,
              !isCapturing, !isWeaving, point.x.isFinite, point.y.isFinite,
              window.frame.contains(point) else { return }
        naturalPressStart = point
    }

    private func dragNaturalHandle(to point: NSPoint, from window: NSWindow) {
        guard captureHandleWindow === window, let origin = naturalPressStart,
              point.x.isFinite, point.y.isFinite else { return }
        if isCapturing { continueDrag(at: point); return }
        guard hypot(point.x - origin.x, point.y - origin.y) >= 5 else { return }
        beginCapture(preservingNaturalHandle: true)
        guard isCapturing else { return }
        startDrag(at: origin); continueDrag(at: point)
        // The original panel stays ordered and owns this press until release.
        // Establish state first; a focus callback may synchronously cancel it.
        if isCapturing { onNaturalCaptureBegin?() }
    }

    private func releaseNaturalHandle(at point: NSPoint, from window: NSWindow) {
        guard captureHandleWindow === window, let origin = naturalPressStart else { return }
        guard point.x.isFinite, point.y.isFinite else { cancelCapture(); return }
        if isCapturing { finishDrag(at: point); return }
        if hypot(point.x - origin.x, point.y - origin.y) < 5 {
            // A click is a deliberate entry too. Clear this panel's completed
            // press before arming so a duplicate/late up cannot finish the net.
            _ = activateNaturalHandle(from: window)
            return
        }
        // A fast gesture can arrive as down/up without a delivered dragged event.
        // Its terminal position is authoritative, but the already released mouse
        // must not arm screen-wide input or request application focus.
        dragStart = origin; dragCurrent = point
        guard let rectangle = captureRectangle else { cancelCapture(); return }
        finishSelection(rectangle)
    }

    private func activateNaturalHandle(from window: NSWindow) -> Bool {
        guard !closed, shown, isNaturalHandleVisible, captureHandleWindow === window,
              !isCapturing, !isWeaving else { return false }
        beginCapture()
        if isCapturing { onNaturalCaptureBegin?() }
        return isCapturing
    }

    func beginCapture() {
        beginCapture(preservingNaturalHandle: false)
    }

    private func beginCapture(preservingNaturalHandle: Bool) {
        guard !closed && !windows.isEmpty else { return }
        if !preservingNaturalHandle { cancelCapture() }
        captureIsNatural = false
        lastCaptureCount = nil
        isCapturing = true
        // Even an explicitly requested net observes desktop events. Never turn
        // a screen-sized transparent drawing surface into a mouse shield.
        for window in windows { window.ignoresMouseEvents = true }
        applyLevel()
        setCaptureState(.armed)
    }

    private func setCaptureState(_ state: DesktopCaptureState) {
        guard captureState != state else { return }
        captureState = state
        onCaptureStateChange?(state)
    }

    private func releaseActiveInput() {
        isCapturing = false; dragStart = nil; dragCurrent = nil; naturalGesture = nil
        hideNaturalHandle()
        for window in windows { window.ignoresMouseEvents = true }
        for view in views { view.selection = nil }
        applyLevel()
    }

    // Focus loss abandons a held gesture. A released net is a passive animation
    // and continues while the player returns to another application.
    func cancelActiveGesture() {
        releaseActiveInput()
        if weavingState == nil {
            lastCaptureCount = nil
            setCaptureState(.idle)
        }
        syncCaptureWindowsVisibility()
    }

    // Explicit cancellation (Esc, hide, screen changes, sleep or a new task)
    // also abandons the released net and any future capture submission.
    func cancelCapture() {
        captureGeneration += 1
        weavingState = nil; weaveProgress = nil
        captureIsNatural = false
        for view in views { view.weave = nil }
        cancelActiveGesture()
    }

    func setNaturalCaptureEnabled(_ enabled: Bool) {
        guard naturalCaptureEnabled != enabled else { return }
        naturalCaptureEnabled = enabled
        hideNaturalHandle()
        if captureIsNatural || naturalGesture != nil { cancelCapture() }
    }

    // Suitable for either monitor: a global monitor discards the returned
    // reference, a local monitor returns exactly this same NSEvent. This method
    // never posts, forwards, replaces or consumes an event.
    @discardableResult
    func observeNaturalEvent(_ event: NSEvent, isLocal: Bool = false,
                             context supplied: DesktopNaturalCaptureContext? = nil) -> NSEvent {
        if event.type == .keyDown {
            if event.keyCode == 53 { cancelCapture() }
            return event
        }
        guard [.leftMouseDown, .leftMouseDragged, .leftMouseUp, .rightMouseDown, .otherMouseDown].contains(event.type) else { return event }
        if !isLocal { onNaturalCaptureObservation?(.eventReceived) }
        if captureIsNatural && isWeaving {
            // A released net owns a fixed rectangle and release-time ID set.
            // Later ordinary app input neither cancels nor seeds another net.
            if event.type == .rightMouseDown { cancelCapture() }
            return event
        }
        if isLocal || supplied?.sourceIsLocal == true {
            onNaturalCaptureObservation?(.localInput)
            cancelNaturalGesture()
            return event
        }
        if event.type == .rightMouseDown || event.type == .otherMouseDown {
            if naturalGesture != nil || captureIsNatural { cancelCapture() }
            return event
        }
        if event.type == .leftMouseDown {
            guard naturalCaptureEnabled || captureState == .armed else { return event }
        } else if naturalGesture == nil {
            // Application drags that failed the initial desktop check do not
            // repeatedly query WindowServer while the user works.
            return event
        }
        // Global monitors deliver asynchronously. Once an input has sat in the
        // queue, today's window/pasteboard state cannot validate its origin.
        // Fail closed after 100 ms, including mid-gesture stalls. NSEvent's
        // timestamp and systemUptime share the seconds-since-boot clock.
        let now = naturalEventTime()
        let age = now - event.timestamp
        guard now.isFinite, event.timestamp.isFinite, age.isFinite,
              age >= 0, age <= 0.1 else {
            onNaturalCaptureObservation?(.eventTooOld)
            cancelNaturalGesture(); return event
        }
        let point: NSPoint
        if supplied != nil {
            // Injected contexts use the event's explicit screen point. Runtime
            // global NSEvents use their CGEvent point, never a later mouse poll.
            point = event.locationInWindow
        } else if let cgPoint = event.cgEvent?.location, let primary = NSScreen.screens.first {
            point = NSPoint(x: cgPoint.x, y: primary.frame.maxY - cgPoint.y)
        } else {
            onNaturalCaptureObservation?(.eventProofMissing)
            cancelNaturalGesture(); return event
        }
        let context: DesktopNaturalCaptureContext
        if let supplied { context = supplied }
        else {
            guard let current = naturalContextProvider(point, contextExcludedWindowNumbers), current.isReliable else {
                onNaturalCaptureObservation?(.contextUnavailable)
                cancelNaturalGesture(); return event
            }
            guard let proof = DesktopNaturalEventProof.from(event.cgEvent) else {
                onNaturalCaptureObservation?(.eventProofMissing)
                cancelNaturalGesture(); return event
            }
            guard let verified = current.validatingDesktopEvent(proof,
                observedWindowNumber: event.windowNumber,
                observerProcessID: Int(ProcessInfo.processInfo.processIdentifier)) else {
                onNaturalCaptureObservation?(.eventTargetNotDesktop)
                cancelNaturalGesture(); return event
            }
            context = verified
        }
        let modifiers = event.modifierFlags.intersection([.command, .control, .option])
        if !modifiers.isEmpty || (event.type == .leftMouseDown && event.clickCount > 1) {
            onNaturalCaptureObservation?(.gestureModified)
            cancelNaturalGesture(); return event
        }
        observeNaturalMouse(event.type, at: point, context: context)
        return event
    }

    private func cancelNaturalGesture() {
        guard naturalGesture != nil || (captureIsNatural && isCapturing) else { return }
        cancelCapture()
    }

    // Space changes invalidate the desktop identity for pending and released
    // work. Merely activating another app does not invalidate a locked release.
    func cancelForWorkspaceChange() {
        if naturalGesture != nil || captureIsNatural { cancelCapture() }
    }

    // Pure input boundary used by the event adapter and synthetic safety tests.
    // CGWindow metadata cannot identify individual desktop file icons. A changed
    // drag pasteboard counter therefore vetoes the complete gesture, including
    // a change first observed on release. Unknown geometry also fails closed.
    func observeNaturalMouse(_ type: NSEvent.EventType, at point: NSPoint,
                             context: DesktopNaturalCaptureContext) {
        guard !closed, shown else {
            onNaturalCaptureObservation?(.inputUnavailable)
            cancelNaturalGesture(); return
        }
        if captureIsNatural && isWeaving {
            if type == .rightMouseDown { cancelCapture() }
            return
        }
        if type == .rightMouseDown || type == .otherMouseDown {
            if naturalGesture != nil || captureIsNatural { cancelCapture() }
            return
        }
        guard point.x.isFinite, point.y.isFinite, !context.sourceIsLocal else {
            onNaturalCaptureObservation?(context.sourceIsLocal ? .localInput : .contextUnavailable)
            cancelNaturalGesture(); return
        }
        guard context.isReliable else {
            onNaturalCaptureObservation?(.contextUnavailable)
            cancelNaturalGesture(); return
        }
        if type == .leftMouseDown {
            cancelNaturalGesture()
            guard naturalCaptureEnabled || captureState == .armed, !isWeaving else { return }
            guard context.permits(NSRect(origin: point, size: .zero)) else {
                onNaturalCaptureObservation?(.desktopNotExposed); return
            }
            naturalGesture = NaturalGesture(origin: point, screenID: context.screenID,
                pasteboardChangeCount: context.dragPasteboardChangeCount,
                isNatural: captureState != .armed)
            onNaturalCaptureObservation?(.gestureBegan)
            return
        }
        guard type == .leftMouseDragged || type == .leftMouseUp, let gesture = naturalGesture else { return }
        let rectangle = NSRect(x: min(gesture.origin.x, point.x), y: min(gesture.origin.y, point.y),
            width: abs(point.x - gesture.origin.x), height: abs(point.y - gesture.origin.y))
        guard context.screenID == gesture.screenID else {
            onNaturalCaptureObservation?(.screenChanged); cancelCapture(); return
        }
        guard context.dragPasteboardChangeCount == gesture.pasteboardChangeCount else {
            onNaturalCaptureObservation?(.fileDrag); cancelCapture(); return
        }
        guard context.permits(rectangle) else {
            onNaturalCaptureObservation?(.desktopNotExposed); cancelCapture(); return
        }
        guard hypot(rectangle.width, rectangle.height) >= 5 else {
            if type == .leftMouseUp { cancelCapture() }
            return
        }
        if !isCapturing || dragStart == nil {
            captureIsNatural = gesture.isNatural
            lastCaptureCount = nil; isCapturing = true
            applyLevel()
            startDrag(at: gesture.origin)
        }
        continueDrag(at: point)
        if type == .leftMouseUp { finishDrag(at: point, naturalContext: context) }
    }

    private func startDrag(at point: NSPoint) {
        guard isCapturing else { return }
        dragStart = point; dragCurrent = point; updateSelection()
        setCaptureState(.dragging)
    }
    private func continueDrag(at point: NSPoint) {
        guard isCapturing, dragStart != nil else { return }
        dragCurrent = point; updateSelection()
    }
    private var captureRectangle: NSRect? {
        guard let start = dragStart, let current = dragCurrent else { return nil }
        return NSRect(x: min(start.x, current.x), y: min(start.y, current.y),
                      width: abs(current.x - start.x), height: abs(current.y - start.y))
    }
    private func updateSelection() {
        // Finder already owns and paints the selection while the button is held.
        // Our mouse-pass-through canvas is needed only after a valid release.
        for view in views { view.selection = captureIsNatural ? nil : captureRectangle }
        syncCaptureWindowsVisibility()
    }
    private func finishDrag(at point: NSPoint, naturalContext: DesktopNaturalCaptureContext? = nil) {
        guard isCapturing else { return }
        dragCurrent = point
        guard let rectangle = captureRectangle else { cancelCapture(); return }
        finishSelection(rectangle, naturalContext: naturalContext)
    }

    private func finishSelection(_ rectangle: NSRect, naturalContext: DesktopNaturalCaptureContext? = nil) {
        // Release input atomically into weaving, without an intermediate idle
        // notification that would briefly close/reopen the host's mode prompt.
        let naturalScreenID = captureIsNatural ? naturalGesture?.screenID : nil
        let releaseIDs: Set<String>? = naturalScreenID.map { screenID in
            Set(positions.filter {
                $0.opacity > 0.05 && $0.screenID == screenID && $0.point.x >= rectangle.minX && $0.point.x <= rectangle.maxX
                    && $0.point.y >= rectangle.minY && $0.point.y <= rectangle.maxY
            }.map { $0.id })
        }
        releaseActiveInput()
        captureGeneration += 1
        weavingState = nil; weaveProgress = nil; lastCaptureCount = nil
        for view in views { view.weave = nil }
        guard rectangle.width > 0 && rectangle.height > 0 else { setCaptureState(.idle); return }
        let time = renderTime()
        let now = time.isFinite ? time : 0
        weavingState = WeavingState(rectangle: rectangle, startedAt: now,
                                    duration: weaving.duration(for: rectangle),
                                    naturalScreenID: naturalScreenID,
                                    naturalEventProof: naturalScreenID == nil ? nil : naturalContext?.eventProof,
                                    approvedDockWindows: naturalScreenID == nil ? [] : naturalContext?.approvedDockWindows ?? [],
                                    naturalReleaseIDs: releaseIDs,
                                    completedAt: nil)
        setCaptureState(.weaving)
        if naturalScreenID != nil { onNaturalCaptureObservation?(.weavingBegan) }
        advanceWeaving(now: now)
    }

    private func advanceWeaving(now: TimeInterval) {
        defer { syncCaptureWindowsVisibility() }
        guard var state = weavingState else { return }
        if let completed = state.completedAt {
            let retraction = min(1, max(0, (now - completed) / weaving.retractionDuration))
            if retraction >= 1 {
                weavingState = nil; weaveProgress = nil
                for view in views { view.weave = nil }
            } else {
                for view in views { view.weave = DesktopWeaveFrame(rectangle:state.rectangle, progress:1, retraction:retraction) }
            }
            return
        }
        let progress = min(1, max(0, (now - state.startedAt) / state.duration))
        weaveProgress = progress
        for view in views { view.weave = DesktopWeaveFrame(rectangle:state.rectangle, progress:progress, retraction:0) }
        guard progress >= 1 else { return }
        // Commit completion before the callback: backend replies can synchronously refresh rows.
        state.completedAt = now; weavingState = state
        // Natural release locks intent before the user returns to work. Use only
        // its original IDs that still exist inside the rectangle; never add a
        // newly spawned, replaced or later-entering insect.
        let rectangle = state.rectangle
        if let screenID = state.naturalScreenID {
            var context = naturalContextProvider(NSPoint(x: rectangle.midX, y: rectangle.midY),
                                                 contextExcludedWindowNumbers)
            if let proof = state.naturalEventProof {
                context = context?.revalidatingReleasedEvent(proof, dockWindows: state.approvedDockWindows)
            }
            guard let context, context.screenID == screenID,
                  context.coversDesktopFrame(rectangle) else {
                onNaturalCaptureObservation?(.releaseContextInvalid); cancelCapture(); return
            }
        }
        let ids = positions.filter {
            guard $0.opacity > 0.05 else { return false }
            if let screenID = state.naturalScreenID {
                guard $0.screenID == screenID, state.naturalReleaseIDs?.contains($0.id) == true else { return false }
            }
            return $0.point.x >= rectangle.minX && $0.point.x <= rectangle.maxX
                && $0.point.y >= rectangle.minY && $0.point.y <= rectangle.maxY
        }.map { $0.id }
        let completedGeneration = captureGeneration
        lastCaptureCount = ids.count
        if state.naturalScreenID != nil { onNaturalCaptureObservation?(.captureSubmitted) }
        onCapture?(ids)
        // A synchronous host callback may have hidden the pet or started a new
        // net; never overwrite that newer state with the old completion.
        guard captureGeneration == completedGeneration, weavingState != nil else { return }
        setCaptureState(.completed)
    }

    fileprivate static func stableHash(_ id: String) -> UInt64 {
        id.utf8.reduce(UInt64(14695981039346656037)) { ($0 ^ UInt64($1)) &* 1099511628211 }
    }
}
