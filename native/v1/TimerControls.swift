import AppKit
import Combine

enum TimerSurface { case sidebar, quick, detached }

struct TimerStartRequest {
    let mode: String
    var duration = "25"
    var rest = "5"
    var label: String {
        switch mode {
        case "stopwatch": return "正计时"
        case "pomodoro": return "番茄钟（从工作段开始）"
        default: return "倒计时（\(Int(duration) == nil ? duration : duration + " 分钟")）"
        }
    }
}

struct PendingTimerStart {
    let request: TimerStartRequest
    let surface: TimerSurface
}

// UI intent only. The Store and its existing service own the sole timer session.
final class TimerControls: ObservableObject {
    private unowned let store: Store
    @Published var draftMode = "clock"
    @Published var draftDuration = "25"
    @Published var draftRest = "5"
    @Published var presetDrafts = ["5", "15", "25", "45"]
    @Published var teaDraft = "10"
    @Published var incenseDraft = "30"
    @Published private(set) var unitFeedback = ""
    @Published private(set) var editingPresets = false
    @Published private(set) var presetFeedback = ""
    @Published private(set) var pending: PendingTimerStart? { didSet { refresh() } }
    @Published private(set) var isSubmitting = false { didSet { refresh() } }
    @Published private(set) var feedback = "" { didSet { refresh() } }
    private var observers: [UUID: () -> Void] = [:]
    init(store: Store) { self.store = store; prepareEditor() }
    var snapshot: [String: Any] { store.timer }
    var status: String { snapshot["status"] as? String ?? "idle" }
    var mode: String { snapshot["mode"] as? String ?? "clock" }
    var active: Bool { ["running", "paused"].contains(status) }
    var ready: Bool { !snapshot.isEmpty }
    var unitPresets: [[String: Any]] {
        snapshot["unit_presets"] as? [[String: Any]] ?? [
            ["label":"一盏茶","input":"一盏茶","seconds":600], ["label":"一刻","input":"一刻","seconds":900],
            ["label":"一炷香","input":"一炷香","seconds":1800], ["label":"一时辰","input":"一时辰","seconds":7200]]
    }
    func unitTitle(_ index: Int) -> String { unitPresets.indices.contains(index) ? unitPresets[index]["label"] as? String ?? "" : "" }
    func unitHint(_ index: Int) -> String {
        guard unitPresets.indices.contains(index), let seconds = unitPresets[index]["seconds"] as? Int else { return "" }
        let modern = seconds % 60 == 0 ? "\(seconds / 60)分钟" : "\(seconds)秒"
        return "\(unitTitle(index)) = \(modern)"
    }
    func startUnit(at index: Int, from surface: TimerSurface) {
        guard unitPresets.indices.contains(index), let input = unitPresets[index]["input"] as? String else { return }
        start(TimerStartRequest(mode: "countdown", duration: input), from: surface)
    }
    func prepareUnits() {
        let tea = snapshot["tea_seconds"] as? Int ?? 600, incense = snapshot["incense_seconds"] as? Int ?? 1800
        teaDraft = tea % 60 == 0 ? String(tea / 60) : "\(tea)s"
        incenseDraft = incense % 60 == 0 ? String(incense / 60) : "\(incense)s"
        unitFeedback = ""
    }
    func saveUnits() {
        guard ready, !isSubmitting, pending == nil else { return }
        unitFeedback = ""; isSubmitting = true
        store.send("timer_preferences", ["tea_duration": teaDraft, "incense_duration": incenseDraft]) { [weak self] ok in
            guard let self else { return }
            self.isSubmitting = false
            self.unitFeedback = ok ? "已保存；当前计时保持原时长。" : "未保存。请填写1秒至24小时的时长。"
        }
    }
    var presetSeconds: [Int] {
        guard let values = snapshot["preset_seconds"] as? [Int], values.count == 4,
              Set(values).count == 4, values.allSatisfy({ (1...86400).contains($0) }) else {
            return [300,900,1500,2700]
        }
        return values
    }
    func presetInput(_ index: Int) -> String {
        guard presetSeconds.indices.contains(index) else { return "" }
        let seconds = presetSeconds[index]
        return seconds % 60 == 0 ? String(seconds / 60) : "\(seconds)s"
    }
    func presetTitle(_ index: Int) -> String {
        guard presetSeconds.indices.contains(index) else { return "" }
        let seconds = presetSeconds[index]
        if seconds % 3600 == 0 { return "\(seconds / 3600)时" }
        if seconds % 60 == 0 { return "\(seconds / 60)分" }
        if seconds < 1000 { return "\(seconds)秒" }
        if seconds >= 3600 { return String(format:"%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60) }
        return String(format:"%d:%02d", seconds / 60, seconds % 60)
    }
    var modeTitle: String { ["clock": "时钟", "countdown": "倒计时", "stopwatch": "正计时", "pomodoro": "番茄钟"][mode] ?? "计时" }
    var statusTitle: String { ["running": "进行中", "paused": "已暂停", "finished": "已结束", "idle": "准备就绪"][status] ?? "" }
    var primaryTitle: String {
        if status == "paused" { return "继续" }
        if status == "finished" && mode == "pomodoro" { return "下一段" }
        return "暂停"
    }
    var canUsePrimary: Bool { active || (status == "finished" && mode == "pomodoro") }
    func observe(_ change: @escaping () -> Void) -> UUID {
        let token = UUID(); observers[token] = change; return token
    }
    func removeObserver(_ token: UUID) { observers.removeValue(forKey: token) }
    func refresh() { for observer in Array(observers.values) { observer() } }
    func prepareEditor(custom: Bool = false) {
        draftMode = custom ? "countdown" : mode
        let key = draftMode == "pomodoro" ? "work_seconds" : "countdown_seconds"
        if let seconds = snapshot[key] as? Int { draftDuration = "\(seconds)s" }
        if let seconds = snapshot["break_seconds"] as? Int { draftRest = "\(seconds)s" }
    }
    func start(_ request: TimerStartRequest, from surface: TimerSurface) {
        guard ready, !isSubmitting, pending == nil,
              ["countdown", "stopwatch", "pomodoro"].contains(request.mode) else { return }
        feedback = ""
        if active { pending = PendingTimerStart(request: request, surface: surface) }
        else { submit(request, replacing: false) }
    }
    var canRestart: Bool { ready && ["countdown", "stopwatch", "pomodoro"].contains(mode) }
    func restart(from surface: TimerSurface) {
        guard canRestart else { return }
        let duration = snapshot[mode == "pomodoro" ? "work_seconds" : "countdown_seconds"] as? Int ?? 1500
        let rest = snapshot["break_seconds"] as? Int ?? 300
        start(TimerStartRequest(mode: mode, duration: "\(duration)s", rest: "\(rest)s"), from: surface)
    }
    func startCustom(_ text: String, from surface: TimerSurface) {
        guard ready, !isSubmitting, pending == nil else { return }
        let duration = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !duration.isEmpty else { feedback = "请输入时长，如一盏茶、三刻或25。"; return }
        start(TimerStartRequest(mode: "countdown", duration: duration), from: surface)
    }
    func reportPositionFailure() { feedback = "窗口位置未保存，下次打开可能回到原位。" }
    func startPreset(at index: Int, from surface: TimerSurface) {
        guard presetSeconds.indices.contains(index) else { return }
        start(TimerStartRequest(mode: "countdown", duration: presetInput(index)), from: surface)
    }
    func beginPresetEditing() {
        guard ready, !isSubmitting, pending == nil else { return }
        presetDrafts = (0..<4).map(presetInput)
        presetFeedback = ""; editingPresets = true
    }
    func cancelPresetEditing() {
        guard !isSubmitting else { return }
        editingPresets = false; presetFeedback = ""
    }
    func savePresetEdits() {
        guard ready, editingPresets, !isSubmitting, pending == nil, presetDrafts.count == 4 else { return }
        presetFeedback = ""; isSubmitting = true
        store.send("timer_preferences", ["preset_durations": presetDrafts]) { [weak self] ok in
            guard let self else { return }
            self.isSubmitting = false
            if ok { self.editingPresets = false }
            else { self.presetFeedback = "未保存。请填四个不同的时长（1 秒至 24 小时），或稍后重试。" }
        }
    }
    func confirmReplacement(from surface: TimerSurface) {
        guard !isSubmitting, let requested = pending, requested.surface == surface else { return }
        pending = nil
        submit(requested.request, replacing: true)
    }
    func cancelReplacement(from surface: TimerSurface) {
        if pending?.surface == surface { pending = nil }
    }
    private func submit(_ request: TimerStartRequest, replacing: Bool) {
        send("timer_start", ["mode": request.mode, "duration": request.duration,
                            "work": request.duration, "rest": request.rest, "replace": replacing])
    }
    func performPrimary() {
        if status == "running" { command("timer_pause") }
        else if status == "paused" { command("timer_resume") }
        else if status == "finished" && mode == "pomodoro" { command("timer_next") }
    }
    func command(_ action: String) {
        guard ready, !isSubmitting, pending == nil else { return }
        let allowed = (action == "timer_pause" && status == "running") ||
            (action == "timer_resume" && status == "paused") || (action == "timer_end" && active) ||
            (action == "timer_next" && status == "finished" && mode == "pomodoro")
        guard allowed else { return }
        send(action)
    }
    private func send(_ action: String, _ values: [String: Any] = [:]) {
        guard !isSubmitting else { return }
        let previousMessage = store.message
        feedback = ""; isSubmitting = true
        store.send(action, values) { [weak self] ok in
            guard let self else { return }
            self.isSubmitting = false
            if !ok {
                self.feedback = self.store.message != previousMessage && !self.store.message.isEmpty
                    ? self.store.message : "计时操作未完成，请检查时长或重试。"
            }
        }
    }
}

private func timerScreen(for frame: NSRect, screens: [NSRect]) -> NSRect {
    let valid = screens.filter { $0.width > 0 && $0.height > 0 && [$0.minX, $0.minY, $0.width, $0.height].allSatisfy(\.isFinite) }
    guard let first = valid.first else { return NSRect(x: 0, y: 0, width: 1440, height: 900) }
    if let screen = valid.first(where: { $0.contains(NSPoint(x: frame.midX, y: frame.midY)) }) { return screen }
    let intersecting = valid.filter { $0.intersects(frame) }
    return intersecting.max { a, b in
        let aa = a.intersection(frame), bb = b.intersection(frame)
        return aa.width * aa.height < bb.width * bb.height
    } ?? first
}

func fitTimerToolFrame(_ candidate: NSRect, screens: [NSRect]) -> NSRect {
    let valid = [candidate.minX, candidate.minY, candidate.width, candidate.height].allSatisfy(\.isFinite) && candidate.width > 0 && candidate.height > 0
    let frame = valid ? candidate : NSRect(x: 0, y: 0, width: 320, height: 210)
    let screen = timerScreen(for: frame, screens: screens)
    let size = NSSize(width: min(frame.width, screen.width), height: min(frame.height, screen.height))
    return NSRect(x: max(screen.minX, min(frame.minX, screen.maxX - size.width)),
                  y: max(screen.minY, min(frame.minY, screen.maxY - size.height)), width: size.width, height: size.height)
}

func timerToolFrame(near anchor: NSRect, size: NSSize, screens: [NSRect]) -> NSRect {
    let screen = timerScreen(for: anchor, screens: screens)
    let x = anchor.maxX + 10 + size.width <= screen.maxX ? anchor.maxX + 10 : anchor.minX - 10 - size.width
    return fitTimerToolFrame(NSRect(x: x, y: anchor.midY - size.height / 2, width: size.width, height: size.height), screens: [screen])
}

final class TimerActionButton: NSButton {
    var invoke: () -> Void
    init(_ title: String, action: @escaping () -> Void) {
        invoke = action
        super.init(frame: .zero)
        self.title = title; target = self; self.action = #selector(run)
        bezelStyle = .rounded; isBordered = false; setButtonType(.momentaryPushIn)
        font = .systemFont(ofSize: 12, weight: .regular)
        contentTintColor = .labelColor
        setAccessibilityLabel(title)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    @objc private func run() { invoke() }
}

// A native backdrop, clipped to the small tool. The clear surrounding window
// remains transparent; this view never steals controls or background dragging.
private final class TimerGlassView: NSVisualEffectView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

// Read-only display text is a window handle. Editable/selectable fields keep
// NSTextField's usual text interaction instead of starting a window drag.
final class TimerDraggableLabel: NSTextField {
    override var mouseDownCanMoveWindow: Bool { !isEditable && !isSelectable }
    override func mouseDown(with event: NSEvent) {
        guard event.type == .leftMouseDown, !isEditable, !isSelectable,
              let window, window.isMovable else { super.mouseDown(with: event); return }
        window.performDrag(with: event)
    }
}

private final class TimerProgressBar: NSView {
    var fraction: Double = 0 {
        didSet { setAccessibilityValue("\(Int(min(1, max(0, fraction)) * 100))%") ; needsDisplay = true }
    }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.quaternaryLabelColor.setFill()
        NSBezierPath(roundedRect: bounds, xRadius: bounds.height / 2, yRadius: bounds.height / 2).fill()
        let filled = NSRect(x: bounds.minX, y: bounds.minY, width: bounds.width * min(1, max(0, fraction)), height: bounds.height)
        NSColor(red: 0.27, green: 0.43, blue: 0.36, alpha: 0.75).setFill()
        NSBezierPath(roundedRect: filled, xRadius: bounds.height / 2, yRadius: bounds.height / 2).fill()
    }
}

// A small numeric tool. Every view observes the same saved service snapshot;
// no view owns a clock, elapsed-time accumulator, or completion side effect.
final class TimerControlPanelView: NSView, NSTextFieldDelegate {
    static let compactHeight: CGFloat = 132
    let controls: TimerControls
    let surface: TimerSurface
    let readout = TimerDraggableLabel(labelWithString: "--:--")
    let detail = TimerDraggableLabel(labelWithString: "")
    let heading = TimerDraggableLabel(labelWithString: "计时")
    let feedback = TimerDraggableLabel(labelWithString: "")
    let confirmation = TimerDraggableLabel(wrappingLabelWithString: "")
    let durationInput = NSTextField(string: "")
    private let glass = TimerGlassView()
    private let timerIcon = NSImageView()
    private let progress = TimerProgressBar()
    var primaryButton: TimerActionButton!
    var restartButton: TimerActionButton!
    var editDurationButton: TimerActionButton?
    private(set) var isEditingDuration = false
    var onSizeChange: ((NSSize) -> Void)?
    var preferredContentSize: NSSize {
        if surface == .quick { return NSSize(width: 312, height: 260) }
        let hasFeedback = !controls.feedback.isEmpty || controls.isSubmitting || (controls.pending != nil && controls.pending?.surface != surface)
        return NSSize(width: 280, height: controls.pending?.surface == surface ? 194 : (isEditingDuration || hasFeedback ? 178 : 132))
    }
    var endButton: TimerActionButton!
    var presetButtons: [TimerActionButton] = []
    var unitButtons: [TimerActionButton] = []
    private var unitModeButton: TimerActionButton?
    private var showingUnits = true
    var customButton: TimerActionButton!
    var expandButton: TimerActionButton!
    var detachButton: TimerActionButton!
    var closeButton: TimerActionButton!
    var confirmButton: TimerActionButton!
    var cancelButton: TimerActionButton!
    var onExpand: () -> Void = {}
    var onDetach: () -> Void = {}
    var onClose: () -> Void = {}
    private var observation: UUID?
    override var isFlipped: Bool { true }
    init(controls: TimerControls, surface: TimerSurface) {
        self.controls = controls; self.surface = surface
        let size = surface == .quick ? NSSize(width: 312, height: 260) : NSSize(width: 280, height: 132)
        super.init(frame: NSRect(origin: .zero, size: size))
        autoresizingMask = [.width, .height]
        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor
        layer?.cornerRadius = 16; layer?.masksToBounds = true
        glass.material = .hudWindow; glass.blendingMode = .behindWindow; glass.state = .active; glass.alphaValue = 0.78
        glass.wantsLayer = true; glass.layer?.cornerRadius = 16; glass.layer?.masksToBounds = true
        addSubview(glass)
        heading.font = .systemFont(ofSize: 12, weight: .medium)
        detail.font = .systemFont(ofSize: 12)
        detail.textColor = .secondaryLabelColor
        feedback.font = .systemFont(ofSize: 11); feedback.textColor = .secondaryLabelColor
        feedback.lineBreakMode = .byTruncatingTail
        confirmation.font = .systemFont(ofSize: 12)
        for label in [readout, detail, heading, feedback, confirmation] {
            label.alignment = .center; addSubview(label)
        }
        heading.alignment = .left
        readout.setAccessibilityLabel("当前时间读数")
        timerIcon.image = NSImage(systemSymbolName: "timer", accessibilityDescription: nil)
        timerIcon.contentTintColor = NSColor(red: 0.27, green: 0.43, blue: 0.36, alpha: 1)
        timerIcon.setAccessibilityElement(false); addSubview(timerIcon)
        progress.setAccessibilityRole(.progressIndicator)
        progress.setAccessibilityLabel("计时进度"); addSubview(progress)
        durationInput.placeholderString = "一盏茶、三刻、25…"
        durationInput.font = .systemFont(ofSize: 13)
        durationInput.bezelStyle = .roundedBezel
        durationInput.target = self; durationInput.action = #selector(submitDuration)
        durationInput.delegate = self
        (durationInput.cell as? NSTextFieldCell)?.sendsActionOnEndEditing = false
        durationInput.setAccessibilityLabel("自定义倒计时时长")
        durationInput.toolTip = "支持一盏茶、一炷香、三刻、半个时辰，也支持90s、1h30m；纯数字按分钟。回车开始。"
        addSubview(durationInput)
        func button(_ title: String, _ action: @escaping () -> Void) -> TimerActionButton {
            let result = TimerActionButton(title, action: action); addSubview(result); return result
        }
        primaryButton = button("暂停") { [weak self] in self?.controls.performPrimary() }
        restartButton = button("重来") { [weak self] in
            guard let self else { return }; self.controls.restart(from: self.surface)
        }
        endButton = button("结束") { [weak self] in self?.controls.command("timer_end") }
        closeButton = button("收起") { [weak self] in self?.onClose() }
        expandButton = button("更多计时设置") { [weak self] in self?.onExpand() }
        customButton = button("开始") { [weak self] in self?.submitDuration() }
        customButton.bezelColor = NSColor(red: 0.27, green: 0.43, blue: 0.36, alpha: 1)
        confirmButton = button("替换并开始") { [weak self] in
            guard let self else { return }; self.controls.confirmReplacement(from: self.surface)
        }
        cancelButton = button("保留当前") { [weak self] in
            guard let self else { return }; self.controls.cancelReplacement(from: self.surface)
        }
        if surface == .quick {
            presetButtons = (0..<4).map { index in
                button(controls.presetTitle(index)) { [weak self] in
                    guard let self else { return }; self.controls.startPreset(at: index, from: self.surface)
                }
            }
            unitButtons = (0..<4).map { index in
                button(controls.unitTitle(index)) { [weak self] in
                    guard let self else { return }; self.controls.startUnit(at: index, from: self.surface)
                }
            }
            unitModeButton = button("国风 ▾") { [weak self] in
                guard let self else { return }; self.showingUnits.toggle(); self.refresh()
            }
            detachButton = button("独立计时窗") { [weak self] in self?.onDetach() }
        } else {
            editDurationButton = button("设时长") { [weak self] in
                guard let self, !self.controls.isSubmitting, self.controls.pending == nil else { return }
                self.isEditingDuration.toggle()
                self.refresh()
                if self.isEditingDuration { self.window?.makeFirstResponder(self.durationInput) }
                else { self.window?.makeFirstResponder(nil) }
            }
        }
        observation = controls.observe { [weak self] in self?.refresh() }
        refresh(); layout()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    deinit { if let observation { controls.removeObserver(observation) } }
    override var mouseDownCanMoveWindow: Bool { true }
    override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
    @objc private func submitDuration() { controls.startCustom(durationInput.stringValue, from: surface) }
    func control(_ control: NSControl, textView: NSTextView, doCommandBy commandSelector: Selector) -> Bool {
        guard control === durationInput, commandSelector == #selector(NSResponder.insertNewline(_:)) else { return false }
        durationInput.stringValue = textView.string
        submitDuration(); return true
    }
    private func icon(_ button: TimerActionButton?, _ symbol: String, only: Bool = false) {
        guard let button else { return }
        button.image = NSImage(systemSymbolName: symbol, accessibilityDescription: button.title)
        button.imagePosition = button.image == nil ? .noImage : (only ? .imageOnly : .imageLeading)
        button.toolTip = button.title; button.setAccessibilityLabel(button.title)
    }
    func refresh() {
        let raw = controls.snapshot[controls.mode == "clock" ? "clock_readout" : "readout"] as? String ?? "--:--"
        let lines = raw.components(separatedBy: "\n")
        readout.stringValue = lines.first ?? "--:--"
        readout.setAccessibilityValue(readout.stringValue)
        let secondary = lines.dropFirst().joined(separator: " ")
        detail.stringValue = controls.mode == "clock" ? secondary
            : controls.statusTitle + (secondary.isEmpty ? "" : " · " + secondary)
        if controls.mode != "clock", let traditional = controls.snapshot["traditional_readout"] as? String, !traditional.isEmpty {
            detail.stringValue = (controls.mode == "stopwatch" ? "已用 " : "余 ") + traditional + (controls.status == "paused" ? " · 已暂停" : "")
        }
        if !controls.ready { detail.stringValue = "正在读取计时…" }
        heading.stringValue = controls.modeTitle
        if controls.mode != "clock", controls.mode != "stopwatch", let equivalent = controls.snapshot["duration_equivalent"] as? String {
            heading.stringValue = equivalent
            heading.toolTip = "本轮原始时长 · " + equivalent
        }
        let pending = controls.pending
        let ownConfirmation = pending?.surface == surface
        confirmation.isHidden = !ownConfirmation
        confirmButton.isHidden = !ownConfirmation; cancelButton.isHidden = !ownConfirmation
        confirmation.stringValue = ownConfirmation ? "结束当前任务，改为\(pending!.request.label)？" : ""
        confirmation.toolTip = confirmation.stringValue
        for button in [primaryButton, restartButton, endButton, customButton] { button?.isHidden = ownConfirmation }
        let showsInput = surface == .quick || isEditingDuration
        durationInput.isHidden = ownConfirmation || !showsInput
        customButton.isHidden = durationInput.isHidden
        primaryButton.title = controls.primaryTitle
        icon(primaryButton, controls.status == "paused" ? "play.fill" : (controls.status == "finished" ? "forward.end.fill" : "pause.fill"), only: true)
        icon(restartButton, "arrow.counterclockwise", only: true); icon(endButton, "stop.fill", only: true)
        restartButton.toolTip = controls.mode == "pomodoro" ? "重来番茄钟（从工作段开始）" : "按原时长重来"
        icon(expandButton, "slider.horizontal.3", only: true)
        icon(closeButton, "xmark", only: true); closeButton.toolTip = "收起窗口，计时继续"
        icon(detachButton, "macwindow.on.rectangle", only: true)
        icon(customButton, "play.fill")
        editDurationButton?.title = isEditingDuration ? "收起" : "设时长"
        icon(editDurationButton, isEditingDuration ? "chevron.up" : "pencil", only: true)
        editDurationButton?.toolTip = isEditingDuration ? "收起输入，保留草稿与计时" : "在小窗中输入新的倒计时时长"
        let long = readout.stringValue.count > 7
        readout.font = .monospacedDigitSystemFont(ofSize: surface == .quick ? (long ? 36 : 42) : (long ? 33 : 38), weight: .regular)
        readout.textColor = controls.status == "paused" ? NSColor(red: 0.52, green: 0.37, blue: 0.15, alpha: 1) : .labelColor
        progress.fraction = TimerVisualProgress(snapshot: controls.snapshot).fraction
        progress.isHidden = ownConfirmation || controls.mode == "clock" || controls.mode == "stopwatch"
        let available = controls.ready && !controls.isSubmitting && pending == nil
        primaryButton.isEnabled = controls.canUsePrimary && available
        restartButton.isEnabled = controls.canRestart && available
        endButton.isEnabled = controls.active && available
        durationInput.isEnabled = available; customButton.isEnabled = available
        for (index, button) in presetButtons.enumerated() {
            button.title = controls.presetTitle(index)
            button.toolTip = button.title; button.setAccessibilityLabel(button.title)
            button.font = .systemFont(ofSize: button.title.count > 6 ? 11 : 13, weight: .medium)
            button.isEnabled = available; button.isHidden = ownConfirmation || showingUnits
        }
        for (index, button) in unitButtons.enumerated() {
            button.title = controls.unitTitle(index); button.toolTip = controls.unitHint(index)
            button.setAccessibilityLabel(controls.unitHint(index)); button.isEnabled = available
            button.isHidden = ownConfirmation || !showingUnits
        }
        unitModeButton?.title = showingUnits ? "国风 ▾" : "常用 ▾"
        unitModeButton?.toolTip = "切换国风单位与常用时长"
        unitModeButton?.setAccessibilityLabel("切换国风单位与常用时长")
        unitModeButton?.isHidden = ownConfirmation
        // Keep a pending confirmation on the surface that owns it.
        expandButton.isEnabled = !controls.isSubmitting && pending == nil
        detachButton?.isEnabled = !controls.isSubmitting && pending == nil
        editDurationButton?.isEnabled = !controls.isSubmitting && pending == nil
        confirmButton.isEnabled = !controls.isSubmitting
        cancelButton.isEnabled = !controls.isSubmitting
        if controls.isSubmitting { feedback.stringValue = "正在保存…" }
        else if !controls.feedback.isEmpty { feedback.stringValue = controls.feedback }
        else if pending != nil && !ownConfirmation { feedback.stringValue = "请在发起操作的窗口确认或取消。" }
        else if ownConfirmation { feedback.stringValue = "当前任务会结束，新的计时从头开始。" }
        else { feedback.stringValue = showsInput ? "纯数字按分钟 · 回车开始" : "" }
        feedback.isHidden = feedback.stringValue.isEmpty
        feedback.textColor = controls.feedback.isEmpty ? .secondaryLabelColor : .systemRed
        feedback.toolTip = feedback.stringValue
        if frame.size != preferredContentSize {
            if let onSizeChange { onSizeChange(preferredContentSize) }
            else { setFrameSize(preferredContentSize) }
        }
        needsLayout = true
    }
    override func layout() {
        super.layout()
        let w = bounds.width, quick = surface == .quick
        let inset: CGFloat = 14
        glass.frame = bounds
        timerIcon.frame = NSRect(x: inset, y: 10, width: 15, height: 15)
        heading.frame = NSRect(x: 35, y: 9, width: w - 158, height: 18)
        closeButton.frame = NSRect(x: w - 40, y: 3, width: 28, height: 28)
        expandButton.frame = NSRect(x: w - 72, y: 3, width: 28, height: 28)
        detachButton?.frame = NSRect(x: w - 104, y: 3, width: 28, height: 28)
        editDurationButton?.frame = NSRect(x: w - 104, y: 3, width: 28, height: 28)
        readout.frame = NSRect(x: inset, y: 32, width: w - inset * 2, height: 46)
        detail.frame = NSRect(x: inset, y: 78, width: w - inset * 2, height: 16)
        progress.frame = NSRect(x: 24, y: 97, width: w - 48, height: 2)
        for (index, button) in [primaryButton!, restartButton!, endButton!].enumerated() {
            button.frame = NSRect(x: w / 2 - 62 + CGFloat(index) * 48, y: 102, width: 28, height: 28)
        }
        if quick {
            unitModeButton?.frame = NSRect(x: 12, y: 132, width: 70, height: 28)
            let presetWidth = (w - inset * 2 - 12) / 4
            for buttons in [presetButtons, unitButtons] {
                for (index, button) in buttons.enumerated() {
                    button.frame = NSRect(x: inset + CGFloat(index) * (presetWidth + 4), y: 164, width: presetWidth, height: 28)
                }
            }
        }
        let inputY: CGFloat = quick ? 204 : 134
        durationInput.frame = NSRect(x: inset, y: inputY, width: w - 83, height: 26)
        customButton.frame = NSRect(x: w - 63, y: inputY - 1, width: 49, height: 28)
        feedback.frame = NSRect(x: 12, y: quick ? 240 : (controls.pending?.surface == surface ? 176 : 161), width: w - 24, height: 15)
        confirmation.frame = NSRect(x: 20, y: quick ? 136 : 98, width: w - 40, height: 40)
        confirmButton.frame = NSRect(x: w / 2 - 112, y: quick ? 192 : 142, width: 108, height: 28)
        cancelButton.frame = NSRect(x: w / 2 + 4, y: quick ? 192 : 142, width: 108, height: 28)
    }
}

final class TimerToolPanel: NSPanel {
    var onEscape: () -> Void = {}
    override var canBecomeKey: Bool { true }
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        // This accessory app has no main Edit menu to route these equivalents.
        // Limit the fallback to this window's active, editable text editor.
        let modifiers = event.modifierFlags.intersection([.command, .shift, .control, .option])
        guard event.type == .keyDown, modifiers == [.command] || modifiers == [.command, .shift],
              let editor = firstResponder as? NSTextView, editor.isEditable, editor.window === self,
              let key = event.charactersIgnoringModifiers?.lowercased(),
              !modifiers.contains(.shift) || key == "z" else { return super.performKeyEquivalent(with: event) }
        switch key {
        case "a": editor.selectAll(self)
        case "c": editor.copy(self)
        case "v": editor.paste(self)
        case "x": editor.cut(self)
        case "z":
            if modifiers.contains(.shift) {
                if editor.undoManager?.canRedo == true { editor.undoManager?.redo() }
            } else if editor.undoManager?.canUndo == true { editor.undoManager?.undo() }
        default: return super.performKeyEquivalent(with: event)
        }
        return true
    }
    override func cancelOperation(_ sender: Any?) { onEscape() }
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 { onEscape() } else { super.keyDown(with: event) }
    }
}

final class TimerToolWindows: NSObject, NSWindowDelegate {
    let controls: TimerControls
    let screens: () -> [NSRect]
    var present: (NSWindow) -> Void
    var onExpand: (Bool) -> Void = { _ in }
    private(set) var quickWindow: TimerToolPanel?
    private(set) var detachedWindow: TimerToolPanel?
    private(set) var quickPresented = false
    private(set) var detachedPresented = false
    private var detachedFrame: NSRect?
    private let placementURL: URL?
    private var restoredOrigin: NSPoint?
    private var restoringFrame = false
    private struct Position: Codable { let x: Double; let y: Double }
    private var anchor = NSRect.zero
    init(controls: TimerControls, screens: @escaping () -> [NSRect], placementURL: URL? = nil,
         present: @escaping (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }) {
        self.controls = controls; self.screens = screens; self.present = present; self.placementURL = placementURL
        if let placementURL, let data = try? Data(contentsOf: placementURL),
           let saved = try? JSONDecoder().decode(Position.self, from: data), saved.x.isFinite, saved.y.isFinite {
            restoredOrigin = NSPoint(x: saved.x, y: saved.y)
        }
    }
    private func makeWindow(surface: TimerSurface) -> TimerToolPanel {
        let view = TimerControlPanelView(controls: controls, surface: surface)
        let mask: NSWindow.StyleMask = [.borderless]
        let window = TimerToolPanel(contentRect: view.bounds, styleMask: mask, backing: .buffered, defer: false)
        window.title = "灶神 · 计时"; window.isReleasedWhenClosed = false; window.delegate = self
        window.isOpaque = false; window.backgroundColor = .clear; window.hasShadow = true
        window.isMovableByWindowBackground = true; window.isMovable = true
        window.level = .floating; window.hidesOnDeactivate = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.contentView = view
        view.onClose = { [weak self] in self?.dismiss(surface) }
        window.onEscape = { [weak self] in
            guard let self else { return }
            if self.controls.pending?.surface == surface { self.controls.cancelReplacement(from: surface) }
            else { self.dismiss(surface) }
        }
        window.initialFirstResponder = surface == .quick ? view.durationInput : view.primaryButton
        if surface == .detached {
            view.onSizeChange = { [weak self] size in self?.resizeDetached(to: size) }
        }
        view.onExpand = { [weak self] in self?.dismissQuick(); self?.onExpand(false) }
        view.onDetach = { [weak self] in guard let self else { return }; self.showDetached(near: self.anchor) }
        return window
    }
    func showQuick(near anchor: NSRect) {
        self.anchor = anchor
        if quickWindow == nil { quickWindow = makeWindow(surface: .quick) }
        guard let window = quickWindow else { return }
        window.setFrame(timerToolFrame(near: anchor, size: window.frame.size, screens: screens()), display: false)
        quickPresented = true; present(window)
        if let view = window.contentView as? TimerControlPanelView { window.makeFirstResponder(view.durationInput) }
    }
    func showDetached(near anchor: NSRect) {
        self.anchor = anchor; dismissQuick()
        if detachedWindow == nil { detachedWindow = makeWindow(surface: .detached) }
        guard let window = detachedWindow else { return }
        let remembered = detachedFrame ?? restoredOrigin.map { origin in
            // Persisted coordinates describe the compact tool. Initial error
            // or confirmation rows grow downward while keeping its top fixed.
            // detachedFrame already describes this process's current size.
            let extraHeight = max(0, (window.contentView?.bounds.height ?? TimerControlPanelView.compactHeight) - TimerControlPanelView.compactHeight)
            return NSRect(origin: NSPoint(x: origin.x, y: origin.y - extraHeight), size: window.frame.size)
        }
        let frame = remembered.map { fitTimerToolFrame($0, screens: screens()) } ?? timerToolFrame(near: anchor, size: window.frame.size, screens: screens())
        restoringFrame = true; window.setFrame(frame, display: false); restoringFrame = false
        detachedFrame = frame
        detachedPresented = true; present(window)
    }
    func dismissQuick() { dismiss(.quick) }
    func dismiss(_ surface: TimerSurface) {
        controls.cancelReplacement(from: surface)
        if surface == .quick { quickPresented = false; quickWindow?.orderOut(nil) }
        if surface == .detached {
            rememberDetachedPosition()
            detachedPresented = false; detachedWindow?.orderOut(nil)
        }
    }
    func dismissAll() { dismiss(.quick); dismiss(.detached) }
    func screensChanged(near anchor: NSRect) {
        self.anchor = anchor
        if quickPresented, let window = quickWindow {
            window.setFrame(timerToolFrame(near: anchor, size: window.frame.size, screens: screens()), display: true)
        }
        if let window = detachedWindow {
            let frame = fitTimerToolFrame(window.frame, screens: screens())
            restoringFrame = true; window.setFrame(frame, display: true); restoringFrame = false
            rememberDetachedPosition()
        }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        dismiss(sender === detachedWindow ? .detached : .quick); return false
    }
    func windowDidResignKey(_ notification: Notification) {
        if notification.object as? NSWindow === quickWindow { dismissQuick() }
    }
    private func resizeDetached(to size: NSSize) {
        guard let window = detachedWindow else { return }
        let resized = window.frameRect(forContentRect: NSRect(origin: .zero, size: size))
        let proposed = NSRect(x: window.frame.minX, y: window.frame.maxY - resized.height,
                              width: resized.width, height: resized.height)
        restoringFrame = true
        window.setFrame(fitTimerToolFrame(proposed, screens: screens()), display: false)
        restoringFrame = false
        rememberDetachedPosition()
    }
    private func rememberDetachedPosition() {
        guard let window = detachedWindow else { return }
        detachedFrame = window.frame
        guard let placementURL else { return }
        do {
            // Save the equivalent compact origin so reopening compact does
            // not drift down after the user last closed an expanded input.
            let extraHeight = max(0, (window.contentView?.bounds.height ?? TimerControlPanelView.compactHeight) - TimerControlPanelView.compactHeight)
            let saved = Position(x: window.frame.minX, y: window.frame.minY + extraHeight)
            let data = try JSONEncoder().encode(saved)
            try FileManager.default.createDirectory(at: placementURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: placementURL, options: .atomic)
        } catch { controls.reportPositionFailure() }
    }
    func windowDidMove(_ notification: Notification) {
        if notification.object as? NSWindow === detachedWindow && !restoringFrame { rememberDetachedPosition() }
    }
}
