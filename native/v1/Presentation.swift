import AppKit
import Combine

let menuRoutes = ["求签", "虫瓶", "装扮", "计时", "设置"]

func canonicalRoute(_ route: String) -> String {
    if route == "神前" { return "求签" }
    if route == "虫谱" { return "装扮" }
    return route
}

struct BottleStatus {
    let inventoryText: String
    let captureText: String
    init(state: [String: Any]) {
        let rows = state["bottle"] as? [[String: Any]] ?? []
        let total = rows.reduce(0) { $0 + ($1["female"] as? Int ?? 0) + ($1["male"] as? Int ?? 0) }
        inventoryText = "总库存 \(total) 只"
        let seconds = max(0, state["capture_seconds"] as? Int ?? 0)
        let elapsed = String(format: "%02d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
        let paused = state["auto_paused"] as? Bool == true
        let status = paused ? (seconds >= 86400 ? "已达上限 · 自动捕捉暂停" : "自动捕捉暂停") : "自动捕捉中"
        captureText = "本轮有效运行 \(elapsed) / 24:00:00 · \(status)"
    }
}

// The ceremony is presentation only: the persisted daily sign always precedes it.
// Uptime keeps clock/date corrections from replaying or stretching an animation.
final class PresentationState: ObservableObject {
    static let ritualDuration: TimeInterval = 5
    @Published private(set) var route: String?
    @Published private(set) var ritualStarted: TimeInterval?
    func open(_ route: String) {
        let resolved = canonicalRoute(route)
        guard menuRoutes.contains(resolved) else { return }
        if resolved == "求签", self.route != resolved { skipRitual() }
        self.route = resolved
    }
    func dismiss() { route = nil }
    func beginRitual(now: TimeInterval = ProcessInfo.processInfo.systemUptime) {
        guard now.isFinite else { return }
        ritualStarted = now
    }
    func skipRitual() { ritualStarted = nil }
    func ritualElapsed(now: TimeInterval = ProcessInfo.processInfo.systemUptime) -> TimeInterval? {
        guard let start = ritualStarted, now.isFinite else { return nil }
        let elapsed = max(0,now-start)
        return elapsed < Self.ritualDuration ? elapsed : nil
    }
    func ritualStage(now: TimeInterval = ProcessInfo.processInfo.systemUptime) -> String? {
        guard let elapsed = ritualElapsed(now:now) else { return nil }
        if elapsed < 0.47 { return "迎候" }
        if elapsed < 1.56 { return "上香" }
        if elapsed < 2.19 { return "入炉" }
        if elapsed < 3.13 { return "摇签" }
        if elapsed < 4.06 { return "呈签" }
        return "余烟"
    }
}

func sidebarFrame(near anchor: NSRect, screen: NSRect, route: String? = nil) -> NSRect {
    let compact = canonicalRoute(route ?? "") == "求签"
    let size = NSSize(width: min(compact ? 360 : 420, screen.width), height: min(compact ? 440 : 540, screen.height))
    let right = anchor.maxX + 8
    let x = right + size.width <= screen.maxX ? right : anchor.minX - size.width - 8
    return NSRect(x: min(max(x, screen.minX), screen.maxX - size.width),
                  y: min(max(anchor.midY - size.height / 2, screen.minY), screen.maxY - size.height),
                  width: size.width, height: size.height)
}

// Local timer notifications. Creating the client does not contact macOS.
import UserNotifications

enum NotificationAccess { case unknown, notDetermined, denied, authorized, quiet, unavailable }
protocol TimerNotificationClient: AnyObject {
    var onOpen: (() -> Void)? { get set }
    func settings(_ done: @escaping (NotificationAccess) -> Void)
    func requestPermission(_ done: @escaping (String?) -> Void)
    func submit(_ done: @escaping (String?) -> Void)
}
final class SystemTimerNotificationClient: NSObject, TimerNotificationClient, UNUserNotificationCenterDelegate {
    var onOpen: (() -> Void)?
    private func center() -> UNUserNotificationCenter? {
        guard Bundle.main.bundleURL.pathExtension == "app", Bundle.main.bundleIdentifier != nil else { return nil }
        let center = UNUserNotificationCenter.current(); center.delegate = self
        return center
    }
    func settings(_ done: @escaping (NotificationAccess) -> Void) {
        guard let center = center() else { done(.unavailable); return }
        center.getNotificationSettings { settings in
            let access: NotificationAccess
            switch settings.authorizationStatus {
            case .notDetermined: access = .notDetermined
            case .denied: access = .denied
            case .authorized: access = settings.alertSetting == .enabled ? .authorized : .quiet
            case .provisional: access = .quiet
            default: access = .unavailable
            }
            done(access)
        }
    }
    // Called only by the explicitly labelled user action, never by settings/expiry.
    func requestPermission(_ done: @escaping (String?) -> Void) {
        guard let center = center() else { done("此启动方式无法使用系统通知，请使用.app候选入口。"); return }
        center.requestAuthorization(options: [.alert]) { _, error in done(error?.localizedDescription) }
    }
    func submit(_ done: @escaping (String?) -> Void) {
        guard let center = center() else { done("系统通知不可用"); return }
        let content = UNMutableNotificationContent()
        content.title = "灶神 · 计时结束"; content.body = "这一段已结束，休息一下。点击查看计时。"
        content.userInfo = ["route": "timer"]
        // Sound is the existing independent app preference; avoid a second chime.
        content.sound = nil
        center.add(UNNotificationRequest(identifier: "tianmu-timer-" + UUID().uuidString, content: content, trigger: nil)) { error in
            done(error?.localizedDescription)
        }
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void) {
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier,
           response.notification.request.content.userInfo["route"] as? String == "timer" {
            DispatchQueue.main.async { [weak self] in self?.onOpen?() }
        }
        completionHandler()
    }
}
final class TimerNotifications: ObservableObject {
    @Published private(set) var access: NotificationAccess = .unknown
    @Published private(set) var deliveryText = ""
    @Published private(set) var requesting = false
    var onOpenTimer: (() -> Void)?
    private let client: TimerNotificationClient
    init(client: TimerNotificationClient) {
        self.client = client
        client.onOpen = { [weak self] in self?.onOpenTimer?() }
    }
    private func onMain(_ action: @escaping () -> Void) {
        if Thread.isMainThread { action() } else { DispatchQueue.main.async(execute: action) }
    }
    var statusText: String {
        switch access {
        case .unknown: return "系统通知状态未读取；可点“刷新通知状态”。"
        case .notDetermined: return "尚未授权；点击下方按钮后才会请求系统权限。"
        case .denied: return "系统通知已拒绝。请在系统设置 → 通知 → 灶神开启，再刷新状态。"
        case .authorized: return "系统通知已授权；横幅仍受系统通知样式与专注模式影响。"
        case .quiet: return "系统已授权，但横幅未开启或为静默通知。请在系统设置 → 通知 → 灶神调整。"
        case .unavailable: return "当前启动方式的系统通知不可用或状态未知；请使用.app候选，并检查系统设置 → 通知。"
        }
    }
    func refresh() {
        client.settings { [weak self] value in self?.onMain { self?.access = value } }
    }
    func requestFromUserClick() {
        guard access == .notDetermined, !requesting else { return }
        requesting = true
        client.requestPermission { [weak self] error in
            self?.onMain {
                self?.requesting = false
                if let error { self?.deliveryText = "授权请求失败：" + error }
                self?.refresh()
            }
        }
    }
    func timerCompleted(enabled: Bool) {
        guard enabled else { return }
        client.settings { [weak self] value in
            self?.onMain {
                guard let self else { return }
                self.access = value
                guard value == .authorized || value == .quiet else {
                    self.deliveryText = "本次未提交系统通知；声音和应用内提示仍按各自开关工作。"
                    return
                }
                self.client.submit { [weak self] error in
                    self?.onMain {
                        self?.deliveryText = error.map { "系统通知提交失败：" + $0 } ?? "已提交系统通知；是否显示由 macOS 决定。"
                    }
                }
            }
        }
    }
}

private final class DiscoveryNoticePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

private final class DiscoveryNoticeView: NSView {
    var text = "" { didSet { needsDisplay = true; setAccessibilityLabel(text) } }
    override var isOpaque: Bool { false }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        let background = NSBezierPath(roundedRect: bounds.insetBy(dx: 1, dy: 1), xRadius: 10, yRadius: 10)
        NSColor(calibratedRed: 0.98, green: 0.95, blue: 0.87, alpha: 0.97).setFill(); background.fill()
        NSColor(calibratedRed: 0.50, green: 0.43, blue: 0.32, alpha: 0.6).setStroke()
        background.lineWidth = 1; background.stroke()
        ("虫谱" as NSString).draw(in: NSRect(x: 14, y: bounds.height - 24, width: bounds.width - 28, height: 14),
            withAttributes: [.font: NSFont.systemFont(ofSize: 11),
                             .foregroundColor: NSColor(calibratedRed: 0.44, green: 0.36, blue: 0.24, alpha: 1)])
        (text as NSString).draw(in: NSRect(x: 14, y: 12, width: max(0, bounds.width - 28), height: 23),
            withAttributes: [.font: NSFont.systemFont(ofSize: 13, weight: .medium),
                             .foregroundColor: NSColor(calibratedWhite: 0.18, alpha: 1)])
    }
}

// A local, passive discovery acknowledgement. It never contacts notification,
// sound, persistence, or worker services; the host decides which colors are new.
final class DiscoveryNotice {
    private(set) var window: NSPanel?
    private(set) var isPresented = false
    private(set) var text = ""
    private let present: (NSWindow) -> Void
    private let schedule: (TimeInterval, @escaping () -> Void) -> Void
    private let colorOrder = ["普通褐色", "中褐色", "深褐色", "白色"]
    private var colors = Set<String>()
    private var generation: UInt64 = 0

    init(present: @escaping (NSWindow) -> Void = { $0.orderFrontRegardless() },
         schedule: @escaping (TimeInterval, @escaping () -> Void) -> Void = { delay, action in
             DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: action)
         }) {
        self.present = present
        self.schedule = schedule
    }

    deinit { window?.orderOut(nil); window?.close() }

    func show(colors newColors: [String], near anchor: NSRect, screens: [NSRect]) {
        let validColors = Set(newColors.filter { colorOrder.contains($0) })
        guard !validColors.isEmpty else { return }
        let validScreens = screens.filter {
            $0.origin.x.isFinite && $0.origin.y.isFinite && $0.width.isFinite && $0.height.isFinite
                && $0.width > 0 && $0.height > 0
        }
        guard !validScreens.isEmpty else { dismiss(); return }
        let combined = colors.union(validColors)
        guard !isPresented || combined != colors else { return }
        let panel: NSPanel
        if let existing = window {
            panel = existing
        } else {
            panel = DiscoveryNoticePanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel],
                                         backing: .buffered, defer: false)
            panel.isReleasedWhenClosed = false
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
            panel.ignoresMouseEvents = true; panel.hidesOnDeactivate = false
            panel.isFloatingPanel = false; panel.becomesKeyOnlyIfNeeded = true
            panel.level = .floating
            panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
            panel.contentView = DiscoveryNoticeView(frame: .zero)
            window = panel
        }
        colors = combined
        text = "新发现：" + colorOrder.filter { colors.contains($0) }.joined(separator: "、")
        let frame = noticeFrame(near: anchor, screens: validScreens)
        panel.setFrame(frame, display: false)
        panel.contentView?.frame = NSRect(origin: .zero, size: frame.size)
        (panel.contentView as? DiscoveryNoticeView)?.text = text
        isPresented = true
        generation &+= 1
        let shownGeneration = generation
        present(panel)
        guard isPresented, generation == shownGeneration else { return }
        schedule(4) { [weak self] in
            guard let self, self.generation == shownGeneration else { return }
            self.dismiss()
        }
    }

    func dismiss() {
        generation &+= 1
        isPresented = false; colors.removeAll(); text = ""
        window?.orderOut(nil); window?.close(); window = nil
    }

    private func noticeFrame(near anchor: NSRect, screens: [NSRect]) -> NSRect {
        let safeAnchor: NSRect
        if anchor.origin.x.isFinite && anchor.origin.y.isFinite && anchor.width.isFinite
            && anchor.height.isFinite && anchor.width >= 0 && anchor.height >= 0 {
            safeAnchor = anchor
        } else {
            safeAnchor = NSRect(x: screens[0].midX, y: screens[0].midY, width: 0, height: 0)
        }
        func overlap(_ screen: NSRect) -> CGFloat {
            let intersection = safeAnchor.intersection(screen)
            return intersection.isNull ? 0 : intersection.width * intersection.height
        }
        func distance(_ screen: NSRect) -> CGFloat {
            let x = max(screen.minX - safeAnchor.midX, 0, safeAnchor.midX - screen.maxX)
            let y = max(screen.minY - safeAnchor.midY, 0, safeAnchor.midY - screen.maxY)
            return x * x + y * y
        }
        let screen = screens.max {
            let lhs = overlap($0), rhs = overlap($1)
            return lhs == rhs ? distance($0) > distance($1) : lhs < rhs
        }!
        let width = min(300, screen.width), height = min(66, screen.height)
        let above = safeAnchor.maxY + 8
        let desiredY = above + height <= screen.maxY ? above : safeAnchor.minY - height - 8
        return NSRect(x: min(max(safeAnchor.midX - width / 2, screen.minX), screen.maxX - width),
                      y: min(max(desiredY, screen.minY), screen.maxY - height), width: width, height: height)
    }
}


private final class OnboardingGuidePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

private final class OnboardingGuideView: NSView {
    let titleLabel = NSTextField(labelWithString: "")
    let detailLabel = NSTextField(wrappingLabelWithString: "")
    let errorLabel = NSTextField(wrappingLabelWithString: "")
    let actionButton: NSButton
    let skipButton: NSButton

    init(actionButton: NSButton, skipButton: NSButton) {
        self.actionButton = actionButton
        self.skipButton = skipButton
        super.init(frame: .zero)
        titleLabel.font = .systemFont(ofSize: 15, weight: .medium)
        titleLabel.textColor = NSColor(calibratedWhite: 0.18, alpha: 1)
        detailLabel.font = .systemFont(ofSize: 12)
        detailLabel.textColor = NSColor(calibratedWhite: 0.32, alpha: 1)
        detailLabel.maximumNumberOfLines = 3
        errorLabel.font = .systemFont(ofSize: 11)
        errorLabel.textColor = NSColor(calibratedRed: 0.62, green: 0.24, blue: 0.18, alpha: 1)
        errorLabel.maximumNumberOfLines = 2
        errorLabel.isHidden = true
        for view in [titleLabel, detailLabel, errorLabel, actionButton, skipButton] { addSubview(view) }
    }
    required init?(coder: NSCoder) { nil }
    override var isOpaque: Bool { false }

    override func layout() {
        super.layout()
        let inset: CGFloat = min(14, bounds.width / 8)
        let width = max(0, bounds.width - inset * 2)
        titleLabel.frame = NSRect(x: inset, y: bounds.height - 34, width: width, height: 20)
        detailLabel.frame = NSRect(x: inset, y: bounds.height - 80, width: width, height: 40)
        errorLabel.frame = NSRect(x: inset, y: 54, width: width, height: 32)
        let skipWidth = min(60, max(0, (width - 12) / 2))
        let actionWidth = min(180, max(0, width - skipWidth - 12))
        actionButton.frame = NSRect(x: inset, y: 14, width: actionWidth, height: 28)
        skipButton.frame = NSRect(x: bounds.width - inset - skipWidth, y: 14, width: skipWidth, height: 28)
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        let background = NSBezierPath(roundedRect: bounds.insetBy(dx: 1, dy: 1), xRadius: 10, yRadius: 10)
        NSColor(calibratedRed: 0.98, green: 0.95, blue: 0.87, alpha: 0.98).setFill(); background.fill()
        NSColor(calibratedRed: 0.50, green: 0.43, blue: 0.32, alpha: 0.6).setStroke()
        background.lineWidth = 1; background.stroke()
    }
}

// The host owns navigation and persisted onboarding progress. Closing this local
// card is never a completed step or a saved skip.
final class OnboardingGuide: NSObject {
    private(set) var window: NSPanel?
    private(set) var isPresented = false
    private(set) var step: String?
    let actionButton = NSButton(title: "", target: nil, action: nil)
    let skipButton = NSButton(title: "跳过", target: nil, action: nil)
    var onAction: (() -> Void)?
    var onSkip: (() -> Void)?

    private let present: (NSWindow) -> Void
    private var content: OnboardingGuideView?
    private var busy = false
    private var errorMessage = ""
    private var anchor = NSRect.zero
    private var screens: [NSRect] = []

    init(present: @escaping (NSWindow) -> Void = { $0.orderFrontRegardless() }) {
        self.present = present
        super.init()
        actionButton.bezelStyle = .rounded
        skipButton.bezelStyle = .rounded
        actionButton.target = self; actionButton.action = #selector(performAction)
        skipButton.target = self; skipButton.action = #selector(performSkip)
        updateButtons()
    }

    deinit { window?.orderOut(nil); window?.close() }

    func show(step requestedStep: String, near anchor: NSRect, screens: [NSRect]) {
        let title: String, detail: String, action: String
        switch requestedStep {
        case "shrine":
            title = "1 / 3 · 求签"
            detail = "点一下签筒，看看今日签。"
            action = "打开签筒"
        case "capture":
            title = "2 / 3 · 桌面框选"
            detail = "在桌面空白处照常框选，松手后蜘蛛会织网。抓到虫就能继续。"
            action = "知道了"
        case "bottle":
            title = "3 / 3 · 看看虫瓶"
            detail = "抓到的活虫都在这里，可以留着、放回或出售。"
            action = "查看虫瓶"
        default: dismiss(); return
        }
        let validScreens = screens.filter {
            $0.origin.x.isFinite && $0.origin.y.isFinite && $0.width.isFinite && $0.height.isFinite
                && $0.width > 0 && $0.height > 0
        }
        guard !validScreens.isEmpty else { dismiss(); return }
        self.anchor = anchor; self.screens = validScreens
        let firstPresentation = !isPresented
        if step != requestedStep {
            busy = false; errorMessage = ""
        }
        step = requestedStep
        let panel: NSPanel
        if let existing = window {
            panel = existing
        } else {
            panel = OnboardingGuidePanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel],
                                         backing: .buffered, defer: false)
            panel.isReleasedWhenClosed = false
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
            panel.ignoresMouseEvents = false; panel.hidesOnDeactivate = false
            panel.isFloatingPanel = false; panel.becomesKeyOnlyIfNeeded = true
            panel.level = .floating
            panel.appearance = NSAppearance(named: .aqua)
            panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
            let view = OnboardingGuideView(actionButton: actionButton, skipButton: skipButton)
            panel.contentView = view
            content = view; window = panel
        }
        content?.titleLabel.stringValue = title
        content?.detailLabel.stringValue = detail
        content?.errorLabel.stringValue = errorMessage
        content?.errorLabel.isHidden = errorMessage.isEmpty
        actionButton.title = action
        isPresented = true
        updateButtons(); updateFrame()
        if firstPresentation { present(panel) }
    }

    func setBusy(_ value: Bool) {
        busy = value
        updateButtons()
    }

    func showError(_ message: String) {
        guard isPresented else { return }
        errorMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        content?.errorLabel.stringValue = errorMessage
        content?.errorLabel.isHidden = errorMessage.isEmpty
        updateFrame()
    }

    func dismiss() {
        isPresented = false; step = nil
        busy = false; errorMessage = ""; screens = []
        updateButtons()
        window?.ignoresMouseEvents = true
        window?.orderOut(nil); window?.close()
        window = nil; content = nil
    }

    private func updateButtons() {
        actionButton.isEnabled = isPresented && !busy
        skipButton.isEnabled = isPresented && !busy
    }

    @objc private func performAction() {
        guard isPresented, !busy else { return }
        onAction?()
    }

    @objc private func performSkip() {
        guard isPresented, !busy else { return }
        onSkip?()
    }

    private func updateFrame() {
        guard let panel = window, let content, !screens.isEmpty else { return }
        let safeAnchor: NSRect
        if anchor.origin.x.isFinite && anchor.origin.y.isFinite && anchor.width.isFinite
            && anchor.height.isFinite && anchor.width >= 0 && anchor.height >= 0 {
            safeAnchor = anchor
        } else {
            safeAnchor = NSRect(x: screens[0].midX, y: screens[0].midY, width: 0, height: 0)
        }
        func overlap(_ screen: NSRect) -> CGFloat {
            let intersection = safeAnchor.intersection(screen)
            return intersection.isNull ? 0 : intersection.width * intersection.height
        }
        func distance(_ screen: NSRect) -> CGFloat {
            let x = max(screen.minX - safeAnchor.midX, 0, safeAnchor.midX - screen.maxX)
            let y = max(screen.minY - safeAnchor.midY, 0, safeAnchor.midY - screen.maxY)
            return x * x + y * y
        }
        let screen = screens.max {
            let lhs = overlap($0), rhs = overlap($1)
            return lhs == rhs ? distance($0) > distance($1) : lhs < rhs
        }!
        let width = min(320, screen.width), height = min(errorMessage.isEmpty ? 134 : 178, screen.height)
        let above = safeAnchor.maxY + 8
        let desiredY = above + height <= screen.maxY ? above : safeAnchor.minY - height - 8
        let frame = NSRect(x: min(max(safeAnchor.midX - width / 2, screen.minX), screen.maxX - width),
                           y: min(max(desiredY, screen.minY), screen.maxY - height), width: width, height: height)
        panel.setFrame(frame, display: false)
        content.frame = NSRect(origin: .zero, size: frame.size)
        content.needsLayout = true
        content.layoutSubtreeIfNeeded()
        content.needsDisplay = true
    }
}
