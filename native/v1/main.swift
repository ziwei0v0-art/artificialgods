import AppKit
import SwiftUI
import Combine
import Foundation

let pageNames = ["求签", "虫瓶", "装扮"]
let paper = Color(red: 0.97, green: 0.95, blue: 0.90)
let ink = Color(red: 0.19, green: 0.23, blue: 0.21)
let accent = Color(red: 0.39, green: 0.48, blue: 0.40)

func argument(_ name: String) -> String? {
    guard let i = CommandLine.arguments.firstIndex(of: name), i + 1 < CommandLine.arguments.count else { return nil }
    return CommandLine.arguments[i + 1]
}

var uiDiagnosticsEnabled: Bool {
    CommandLine.arguments.contains("--ui-diagnostics") || Bundle.main.object(forInfoDictionaryKey:"TianmuQASaveFile") != nil
}

func saveFileURL() -> URL {
    if let path = argument("--save-file") { return URL(fileURLWithPath: path) }
    if let path = Bundle.main.object(forInfoDictionaryKey:"TianmuQASaveFile") as? String, path.hasPrefix("/") {
        return URL(fileURLWithPath:path)
    }
    return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/TianmuMVP/state.json")
}

func startWorker() throws -> (Process, Pipe, Pipe) {
    let bundle = Bundle.main
    let runtime = bundle.object(forInfoDictionaryKey: "TianmuPythonExecutable") as? String ?? "/usr/bin/python3"
    let backend = bundle.resourceURL!.appendingPathComponent("backend")
    let path = saveFileURL().path
    let process = Process(), input = Pipe(), output = Pipe()
    process.executableURL = runtime.hasPrefix("/") ? URL(fileURLWithPath:runtime) : bundle.resourceURL!.appendingPathComponent(runtime)
    process.arguments = ["-E", "-s", "-B", "-m", "tianmu_mvp.worker", "--save-file", path]
    process.currentDirectoryURL = backend
    process.standardInput = input; process.standardOutput = output
    process.standardError = FileHandle.standardError
    try process.run()
    return (process, input, output)
}

func write(_ request: [String: Any], to pipe: Pipe) {
    guard let data = try? JSONSerialization.data(withJSONObject: request) else { return }
    pipe.fileHandleForWriting.write(data + Data([10]))
}

// Startup greetings and heartbeat snapshots are not the numbered check reply.
func checkedBackendReply(_ buffer: inout Data) throws -> [String: Any]? {
    while let end = buffer.firstIndex(of: 10) {
        let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
        guard let reply = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
            throw NSError(domain: "Tianmu", code: 2, userInfo: [NSLocalizedDescriptionKey: "数据服务回执无效"])
        }
        if reply["id"] as? Int == 1 || ["failed", "recovery"].contains(reply["phase"] as? String ?? "") { return reply }
    }
    return nil
}

if CommandLine.arguments.contains("--check-backend") {
    do {
        let (process, input, output) = try startWorker()
        write(["id": 1, "action": "snapshot"], to: input)
        var data = Data()
        var response: [String: Any]?
        while response == nil {
            let chunk = output.fileHandleForReading.availableData
            if chunk.isEmpty { throw NSError(domain: "Tianmu", code: 1) }
            data.append(chunk); response = try checkedBackendReply(&data)
        }
        let reply = response!
        let state = reply["state"] as? [String: Any] ?? [:]
        let timer = state["timer"] as? [String: Any] ?? [:]
        let result: [String: Any] = ["ok": reply["ok"] as? Bool ?? false, "pages": pageNames, "mode": timer["mode"] ?? ""]
        if process.isRunning { write(["id": 2, "action": "quit"], to: input) }
        process.waitUntilExit()
        print(String(data: try JSONSerialization.data(withJSONObject: result), encoding: .utf8)!)
        exit(reply["ok"] as? Bool == true ? process.terminationStatus : 1)
    } catch { fputs("\(error)\n", stderr); exit(1) }
}

final class Store: ObservableObject {
    let atmosphere = WeatherAtmosphereStore()
    let notifications: TimerNotifications
    var playSound: () -> Void = { NSSound.beep() }
    init(notificationClient: TimerNotificationClient = SystemTimerNotificationClient()) {
        notifications = TimerNotifications(client: notificationClient)
    }
    @Published private(set) var runtimePhase = "starting"
    @Published private(set) var startupIssue: [String: Any]?
    @Published private(set) var recoveryInfo: [String: Any]?
    var onRuntimeChange: ((String) -> Void)?
    var retryStartup: (() -> Void)?
    private var workerGeneration = 0
    private var quitRequests = Set<Int>()
    private var expectedShutdown = false
    private var connectionEnded = false
    lazy var recoveryControls = RecoveryControls(store: self)
    @Published var sceneTransparency: Double = 100
    @Published var sceneScale: Double = 75
    @Published var pointerAvoidance = true
    @Published var insectsOnTop = false
    @Published var naturalCaptureEnabled = true
    @Published var exitAction: SceneExitAction = .hideShrine
    @Published var exitActionError = ""
    var onExitActionChange: ((SceneExitAction) throws -> Void)?
    func setExitAction(_ action: SceneExitAction) {
        guard let save = onExitActionChange else {
            exitActionError = "退出设置暂时不可用。"; return
        }
        do { try save(action); exitAction = action; exitActionError = "" }
        catch { exitActionError = "退出设置未保存，已保留原设置。" }
    }
    var onNaturalCaptureChange: ((Bool) throws -> Void)?
    func setNaturalCaptureEnabled(_ enabled: Bool) {
        do { try onNaturalCaptureChange?(enabled); naturalCaptureEnabled = enabled; transparencyError = "" }
        catch { transparencyError = "设置未保存，已保留原设置。" }
    }
    @Published var insectStyle: InsectStyle = .cute
    @Published var availableInsectStyles: Set<InsectStyle> = []
    @Published var insectStyleError = ""
    var onInsectStyleChange: ((InsectStyle) throws -> Void)?
    func setInsectStyle(_ style: InsectStyle) {
        guard availableInsectStyles.contains(style) else {
            insectStyleError = "此款虫形暂不可用。"; return
        }
        guard style != insectStyle else { return }
        guard let save = onInsectStyleChange else {
            insectStyleError = "虫形未保存，已保留原设置。"; return
        }
        do {
            try save(style)
            insectStyle = style; insectStyleError = ""
        } catch {
            insectStyleError = "虫形未保存，已保留原设置。"
        }
    }
    var onPointerAvoidanceChange: ((Bool) throws -> Void)?
    var onInsectLevelChange: ((Bool) throws -> Void)?
    func setPointerAvoidance(_ enabled: Bool) {
        do { try onPointerAvoidanceChange?(enabled); pointerAvoidance = enabled; transparencyError = "" }
        catch { transparencyError = "设置未保存，已保留原设置。" }
    }
    func setInsectsOnTop(_ enabled: Bool) {
        do { try onInsectLevelChange?(enabled); insectsOnTop = enabled; transparencyError = "" }
        catch { transparencyError = "设置未保存，已保留原设置。" }
    }
    @Published var sceneSizeError = ""
    var onSceneScaleChange: ((Double) throws -> Double)?
    func setSceneScale(_ percent: Double) {
        let requested = normalizedSceneScale(percent)
        do {
            sceneScale = try onSceneScaleChange?(requested) ?? requested
            sceneSizeError = ""
        } catch {
            sceneSizeError = "位置或大小未保存，已保留原设置。"
            message = sceneSizeError
        }
    }
    @Published var transparencyError = ""
    var onTransparencyChange: ((Double) throws -> Void)?
    func setSceneTransparency(_ value: Double) {
        let value = SceneTransparencyStore.normalized(value)
        do {
            try onTransparencyChange?(value)
            sceneTransparency = value
            transparencyError = ""
        } catch {
            transparencyError = "透明度未保存，已保留原设置。\(error.localizedDescription)"
        }
    }
    @Published var state: [String: Any] = [:] { didSet { timerControls.refresh(); bottleControls.refresh(); gameSettings.refresh(); shopControls.refresh() } }
    lazy var timerControls = TimerControls(store: self)
    lazy var bottleControls = BottleControls(store: self)
    lazy var shopControls = ShopControls(store: self)
    lazy var gameSettings = GameSettingsControls(store: self)
    // A transport seam for isolated native tests; production uses the one worker below.
    var commandSink: ((String, [String: Any], ((Bool) -> Void)?) -> Void)?
    var requestSink: (([String: Any]) -> Void)?
    @Published var message = "正在读取小庙…"
    @Published var sale: [String: Any]?
    private(set) var saleRevision = 0
    private var saleRequests: [Int: Int] = [:]
    var onState: (([String: Any]) -> Void)?
    var onReminder: (() -> Void)?
    var onDiscovery: (([String]) -> Void)?
    private var knownDiscoveries = Set<String>()
    var completions: [Int: (Bool) -> Void] = [:]
    var process: Process?
    var input: Pipe?
    var output: Pipe?
    var buffer = Data()
    var number = 0
    private var lastReplyID = 0
    var timer: [String: Any] { state["timer"] as? [String: Any] ?? [:] }
    var coins: Int { state["coins"] as? Int ?? 0 }
    func rows(_ key: String) -> [[String: Any]] { state[key] as? [[String: Any]] ?? [] }
    func start() {
        guard process?.isRunning != true else { return }
        workerGeneration += 1
        let generation = workerGeneration
        runtimePhase = "starting"; startupIssue = nil; recoveryInfo = nil
        expectedShutdown = false; connectionEnded = false; quitRequests.removeAll()
        buffer = Data(); lastReplyID = 0; message = "正在读取小庙…"
        recoveryControls.refresh()
        do {
            let (process, input, output) = try startWorker()
            self.process = process; self.input = input; self.output = output
            process.terminationHandler = { [weak self] process in
                DispatchQueue.main.async {
                    guard let self, generation == self.workerGeneration else { return }
                    // stdout's final data can already be queued on another callback.
                    // Let it settle before reporting an unacknowledged termination.
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                        guard let self, generation == self.workerGeneration, !self.connectionEnded else { return }
                        self.transportStopped(status: process.terminationStatus)
                    }
                }
            }
            output.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                if data.isEmpty { handle.readabilityHandler = nil }
                DispatchQueue.main.async {
                    guard let self, generation == self.workerGeneration else { return }
                    if data.isEmpty { self.transportStopped(status: nil) }
                    else { self.receive(data) }
                }
            }
            // The worker's startup handshake already contains the first state
            // or precise recovery issue. A redundant snapshot would be rejected
            // in recovery and obscure that initial diagnosis.
            DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
                guard let self, self.workerGeneration == generation, self.runtimePhase == "starting" else { return }
                self.transportStopped(status: nil, fallback: "读取存档超时。请退出后重新打开；原存档没有被清空。")
            }
        } catch {
            startupIssue = ["code": "runtime_unavailable", "message": "无法启动数据服务：\(error.localizedDescription)"]
            transportStopped(status: nil)
        }
    }
    func transportStopped(status: Int32?, fallback: String? = nil) {
        guard !expectedShutdown else { return }
        connectionEnded = true
        runtimePhase = "failed"
        if startupIssue == nil {
            startupIssue = ["code": "runtime_stopped", "message": fallback ?? "数据服务已断开，请重新打开。原存档没有被清空。"]
        }
        message = process?.isRunning == true ? "数据服务没有回应，请退出后重新打开。" : "数据服务已退出，可重试打开。"
        let callbacks = Array(completions.values)
        completions.removeAll(); saleRequests.removeAll(); sale = nil
        for callback in callbacks { callback(false) }
        recoveryControls.refresh()
        onRuntimeChange?("failed")
    }
    func retryOpening() {
        guard runtimePhase == "failed", process?.isRunning != true else { return }
        if let retryStartup { retryStartup() } else { start() }
    }
    func receive(_ data: Data) {
        buffer.append(data)
        while let end = buffer.firstIndex(of: 10) {
            let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
            guard let reply = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            // A terminated connection can contribute its precise failure reason,
            // but never a late state, reminder, completion, or readiness signal.
            if connectionEnded {
                if let issue = reply["issue"] as? [String: Any] {
                    startupIssue = issue
                    if let recovery = reply["recovery"] as? [String: Any] { recoveryInfo = recovery }
                    recoveryControls.refresh(); onRuntimeChange?("failed")
                }
                continue
            }
            // The single worker replies to numbered requests in order. Its ticks
            // have no id. An old reply must not restore an earlier whole snapshot.
            if let id = reply["id"] as? Int {
                if id <= lastReplyID {
                    saleRequests.removeValue(forKey: id)
                    completions.removeValue(forKey: id)?(reply["ok"] as? Bool == true)
                    continue
                }
                lastReplyID = id
            }
            let phase = reply["phase"] as? String
            if let phase, ["ready", "recovery", "failed"].contains(phase) {
                runtimePhase = phase
                if phase == "ready" { startupIssue = nil; recoveryInfo = nil }
                else {
                    message = phase == "recovery" ? "存档尚未打开，未载入游戏进度。" : "启动未完成，请检查提示后重试。"
                    if let issue = reply["issue"] as? [String: Any] { startupIssue = issue }
                    if let recovery = reply["recovery"] as? [String: Any] { recoveryInfo = recovery }
                }
            }
            knownDiscoveries.formUnion(rows("discoveries").filter { $0["found"] as? Bool == true }.map { $0.colorKey })
            if let state = reply["state"] as? [String: Any] {
                if self.state.isEmpty { message = "" }
                self.state = state; onState?(state)
            }
            if let text = reply["error"] as? String { message = text }
            if let text = reply["message"] as? String { message = text }
            if let id = reply["id"] as? Int, let revision = saleRequests.removeValue(forKey: id),
               revision == saleRevision, reply["ok"] as? Bool == true,
               let sale = reply["sale"] as? [String: Any] { self.sale = sale }
            if let id = reply["id"] as? Int, quitRequests.remove(id) != nil, reply["ok"] as? Bool == true { expectedShutdown = true }
            if let id = reply["id"] as? Int, let callback = completions.removeValue(forKey: id) { callback(reply["ok"] as? Bool == true) }
            if let phase { recoveryControls.refresh(); onRuntimeChange?(phase) }
            if reply["ok"] as? Bool == true {
                let found = Set(rows("discoveries").filter { $0["found"] as? Bool == true }.map { $0.colorKey })
                var fresh: [String] = []
                for color in reply["new_discoveries"] as? [String] ?? [] {
                    if found.contains(color), !knownDiscoveries.contains(color) {
                        knownDiscoveries.insert(color); fresh.append(color)
                    }
                }
                knownDiscoveries.formUnion(found)
                if !fresh.isEmpty { onDiscovery?(fresh) }
            }
            if (reply["events"] as? [String])?.contains("timer_expired") == true {
                message = "计时结束，休息一下。"
                if timer["sound_enabled"] as? Bool ?? true { playSound() }
                if timer["widget_enabled"] as? Bool ?? true { onReminder?() }
                notifications.timerCompleted(enabled: timer["notification_enabled"] as? Bool ?? true)
            }
        }
    }
    func send(_ action: String, _ values: [String: Any] = [:], completion: ((Bool) -> Void)? = nil) {
        if runtimePhase == "failed" || (runtimePhase == "recovery" && !["recovery_inspect", "recovery_restore", "quit"].contains(action)) {
            completion?(false); return
        }
        if let commandSink { commandSink(action, values, completion); return }
        guard requestSink != nil || (input != nil && process?.isRunning == true) else { completion?(false); return }
        number += 1
        if let completion { completions[number] = completion }
        if action == "sale_preview" { saleRequests[number] = saleRevision }
        if action == "quit" { quitRequests.insert(number) }
        var request = values; request["action"] = action; request["id"] = number
        if let requestSink { requestSink(request) }
        else if let input { write(request, to: input) }
    }
    func cancelSale() { saleRevision &+= 1; sale = nil; send("sale_cancel") }
    func stop() { send("quit"); output?.fileHandleForReading.readabilityHandler = nil }
}

struct SmallHeading: View {
    let title: String; let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 25, weight: .medium, design: .serif))
            Text(subtitle).font(.callout).foregroundStyle(.secondary)
        }.padding(.bottom, 14)
    }
}

func applySceneState(_ state: [String: Any], to view: TianmuView,
                     appearanceOverride: SceneAppearance? = nil, staticAppearancePreview: Bool = false) {
    view.previewBackgroundColor = staticAppearancePreview ? NSColor(paper).blended(withFraction: 0.45, of: .white) : nil
    view.sceneAppearance = appearanceOverride ?? SceneAppearance(snapshot: state)
    view.offeringPlate = view.sceneAppearance.itemID(in: "plate") == "offering_plate"
    if staticAppearancePreview {
        let actualFruit = (state["routine"] as? [String: Any])?["fruit_stage"] as? String ?? "fresh"
        view.applyRoutine(["action": "idle", "action_serial": 0, "action_duration": 0,
                           "action_elapsed": 0, "progress": 0,
                           "fruit_stage": ["fresh", "soft", "ripe"].contains(actualFruit) ? actualFruit : "fresh"])
    } else { view.applyRoutine(state["routine"] as? [String: Any]) }
}

struct ScenePreview: NSViewRepresentable {
    @ObservedObject var store: Store
    var appearanceOverride: SceneAppearance? = nil
    var staticAppearancePreview = false
    var ritualStage: String? = nil
    var animationElapsed: TimeInterval? = nil
    func makeNSView(context: Context) -> TianmuView {
        let view = TianmuView(frame: NSRect(origin: .zero, size: TianmuView.sceneCanvas.size))
        apply(to: view)
        return view
    }
    func apply(to view: TianmuView) {
        applySceneState(store.state, to: view, appearanceOverride: appearanceOverride,
                        staticAppearancePreview: staticAppearancePreview)
        view.ritualStage = ritualStage
        if let elapsed = animationElapsed { view.updateAnimation(elapsed:elapsed) }
    }
    func updateNSView(_ view: TianmuView, context: Context) { apply(to: view) }
}

struct ShrinePage: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ObservedObject var store: Store
    @ObservedObject var presentation: PresentationState
    @State private var historyDate = "今日"
    @State private var requesting = false
    @State private var showingHistory = false
    var signs: [[String:Any]] { store.rows("signs") }
    var today: String {
        let zone = TimeZone(identifier:store.state["game_timezone"] as? String ?? "UTC") ?? .gmt
        return Date().formatted(Date.ISO8601FormatStyle(timeZone:zone).year().month().day().dateSeparator(.dash))
    }
    var hasToday: Bool { signs.contains { $0["date"] as? String == today } }
    func requestSign() {
        guard !requesting, presentation.ritualStage() == nil else { return }
        historyDate = "今日"
        if hasToday { presentation.skipRitual(); return }
        requesting = true
        store.send("sign", completion: { ok in
            requesting = false
            // A saved result precedes every first-draw animation.
            if ok && presentation.route == "求签" && !reduceMotion { presentation.beginRitual() }
        })
    }
    var body: some View {
        VStack(alignment:.leading,spacing:10) {
            ShrineCeremonyView(store:store,presentation:presentation,request:requestSign,requesting:requesting)
                .accessibilityIdentifier("shrine-ceremony")
                .overlay(alignment:.topTrailing) {
                    if !signs.isEmpty {
                        QuietIconButton(title:"签簿",symbol:"book.closed") { showingHistory = true }
                            .accessibilityIdentifier("shrine-history")
                            .popover(isPresented:$showingHistory,arrowEdge:.trailing) {
                                VStack(alignment:.leading,spacing:12) {
                                    Picker("日期",selection:$historyDate) {
                                        Text("今日").tag("今日")
                                        ForEach(signs,id:\.dateKey) { sign in
                                            Text(sign["date"] as? String ?? "").tag(sign["date"] as? String ?? "")
                                        }
                                    }.onChange(of:historyDate) { _ in
                                        presentation.skipRitual()
                                        showingHistory = false
                                    }
                                    Text("游戏原创签文，同日同签。").font(.caption).foregroundStyle(.secondary)
                                }.padding(16).frame(width:240)
                            }
                    }
                }
            TimelineView(.periodic(from:.now,by:0.2)) { context in
                let active = presentation.ritualStage() != nil
                if !active {
                    if let sign = signs.first(where: { $0["date"] as? String == (historyDate == "今日" ? today : historyDate) }) {
                        VStack(alignment:.leading,spacing:8) {
                            Text(sign["date"] as? String ?? "").font(.caption).foregroundStyle(.secondary)
                            Text(sign["verse"] as? String ?? "").font(.system(size:18,weight:.medium,design:.serif))
                                .lineSpacing(6).fixedSize(horizontal:false,vertical:true)
                            Text(sign["meaning"] as? String ?? "").font(.callout).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                        }.padding(14).frame(maxWidth:.infinity,alignment:.leading)
                            .background(Color.white.opacity(0.45),in:RoundedRectangle(cornerRadius:12))
                            .accessibilityIdentifier("shrine-result")
                    }
                }
            }
        }
    }
}

extension Dictionary where Key == String, Value == Any {
    var dateKey: String { self["date"] as? String ?? "" }
    var colorKey: String { self["color"] as? String ?? "" }
    var itemKey: String { self["id"] as? String ?? "" }
}

// Only view intent lives here; the service retains every individual and transaction.
final class BottleControls: ObservableObject {
    private unowned let store: Store
    @Published private(set) var color = "普通褐色"
    @Published var count = 1
    @Published private(set) var releaseExpanded = false
    @Published var releaseSex = "全部"
    @Published var releaseCount = 1
    @Published private(set) var isSubmitting = false
    init(store: Store) { self.store = store }
    var selected: [String: Any] { store.rows("bottle").first { $0.colorKey == color } ?? [:] }
    var female: Int { selected["female"] as? Int ?? 0 }
    var male: Int { selected["male"] as? Int ?? 0 }
    var available: Int { female + male }
    var totalInventory: Int { store.rows("bottle").reduce(0) { $0 + ($1["female"] as? Int ?? 0) + ($1["male"] as? Int ?? 0) } }
    var saleCount: Int { min(count, available) }
    var saleAmount: Int { saleCount * (selected["price"] as? Int ?? 0) }
    var releaseAvailable: Int { releaseSex == "雌" ? female : releaseSex == "雄" ? male : available }
    var releaseSelectedCount: Int { min(releaseCount, releaseAvailable) }
    var locked: Bool { isSubmitting || store.sale != nil }
    func refresh() {
        count = max(1, min(count, available)); releaseCount = max(1, min(releaseCount, releaseAvailable))
        objectWillChange.send()
    }
    func chooseColor(_ name: String) {
        guard !isSubmitting, store.rows("bottle").contains(where: { $0.colorKey == name }) else { return }
        store.cancelSale(); color = name; count = 1; dismissRelease()
    }
    func beginRelease() {
        guard !locked, available > 0 else { return }
        releaseSex = "全部"; releaseCount = max(1, saleCount); releaseExpanded = true
    }
    func dismissRelease() { releaseExpanded = false; releaseSex = "全部"; releaseCount = 1 }
    func previewSale() {
        guard !locked, saleCount > 0 else { return }
        dismissRelease()
        submit("sale_preview", ["color":color, "count":saleCount])
    }
    func release() {
        guard releaseExpanded, !locked, releaseSelectedCount > 0 else { return }
        var values: [String:Any] = ["color":color, "count":releaseSelectedCount]
        if releaseSex != "全部" { values["sex"] = releaseSex == "雌" ? "F" : "M" }
        submit("release", values) { [weak self] ok in if ok { self?.dismissRelease() } }
    }
    func confirmSale() {
        guard !isSubmitting, let token = store.sale?["token"] as? String else { return }
        submit("sale_confirm", ["token":token]) { [weak self] ok in if ok { self?.store.sale = nil } }
    }
    func cancelSale() { if !isSubmitting { store.cancelSale() } }
    private func submit(_ action: String, _ values: [String:Any], done: ((Bool)->Void)? = nil) {
        isSubmitting = true
        store.send(action, values) { [weak self] ok in self?.isSubmitting = false; done?(ok) }
    }
}

// Inventory art is a read-only view of the accepted snapshot, never a second simulation.
struct BottleDisplayInventory {
    let total: Int
    let visibleColors: [String]
    let visibleSexes: [String]
    let visibleIDs: [String]
    let hasAuthoritativeIDs: Bool
    init(rows: [[String: Any]], individuals: [[String: Any]]? = nil) {
        let counts = rows.map { (max(0, $0["female"] as? Int ?? 0), max(0, $0["male"] as? Int ?? 0), $0.colorKey) }
        total = counts.reduce(0) { $0 + $1.0 + $1.1 }
        if let individuals {
            var ids: [String] = [], colors: [String] = [], sexes: [String] = []
            var seen = Set<String>(), used: [String: Int] = [:]
            for item in individuals where ids.count < 12 {
                guard let id = item["id"] as? String, !id.isEmpty,
                      let color = item["color"] as? String, let sex = item["sex"] as? String,
                      sex == "F" || sex == "M", !seen.contains(id),
                      let count = counts.first(where: { $0.2 == color }) else { continue }
                let key = color + ":" + sex, limit = sex == "F" ? count.0 : count.1
                guard used[key, default: 0] < limit else { continue }
                seen.insert(id); used[key, default: 0] += 1
                ids.append(id); colors.append(color); sexes.append(sex)
            }
            visibleIDs = ids; visibleColors = colors; visibleSexes = sexes
            hasAuthoritativeIDs = true
            return
        }
        var colors: [String] = []
        var sexes: [String] = []
        var ids: [String] = []
        // Round robin retains a rare colour even when another colour fills the bottle.
        for index in 0..<12 {
            for (female, male, color) in counts where female + male > index {
                if colors.count < 12 {
                    colors.append(color)
                    sexes.append(index < female ? "F" : "M")
                    ids.append("aggregate-fixture:\(color):\(index)")
                }
            }
        }
        visibleColors = colors
        visibleSexes = sexes
        visibleIDs = ids
        hasAuthoritativeIDs = false
    }
}

final class BottleInventoryView: NSView {
    var inventory = BottleDisplayInventory(rows: [])
    var style: InsectStyle = .cute
    var elapsed: TimeInterval = 0
    private let motion = BottleMotionEngine()
    func updateMotion() { motion.update(ids: inventory.visibleIDs, now: elapsed) }
    // Trim only the invisible canvas while drawing; the accepted PNG stays intact.
    private static let visibleCanvas: NSRect = {
        guard let image = BottleArtwork.production.image,
              let original = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            return NSRect(x: 0, y: 0, width: 1, height: 1)
        }
        let width = original.width, height = original.height
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        guard let context = CGContext(data: &rgba, width: width, height: height, bitsPerComponent: 8,
                bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else {
            return NSRect(x: 0, y: 0, width: 1, height: 1)
        }
        context.draw(original, in: CGRect(x: 0, y: 0, width: width, height: height))
        var left = width, right = 0, top = height, bottom = 0
        for y in 0..<height {
            for x in 0..<width where rgba[(y * width + x) * 4 + 3] > 8 {
                left = min(left, x); right = max(right, x)
                top = min(top, y); bottom = max(bottom, y)
            }
        }
        guard left <= right, top <= bottom else { return NSRect(x: 0, y: 0, width: 1, height: 1) }
        left = max(0, left - 2); right = min(width - 1, right + 2)
        top = max(0, top - 2); bottom = min(height - 1, bottom + 2)
        return NSRect(x: CGFloat(left) / CGFloat(width), y: CGFloat(height - bottom - 1) / CGFloat(height),
                      width: CGFloat(right - left + 1) / CGFloat(width), height: CGFloat(bottom - top + 1) / CGFloat(height))
    }()
    override func draw(_ dirtyRect: NSRect) {
        let bottle = BottleArtwork.production
        guard bottle.image != nil else {
            ("虫瓶图暂不可用" as NSString).draw(at: NSPoint(x: 45, y: bounds.midY), withAttributes: [.foregroundColor: NSColor.secondaryLabelColor])
            return
        }
        let crop = Self.visibleCanvas
        let scale = min(bounds.width / crop.width, bounds.height / crop.height)
        let canvas = NSRect(x: bounds.midX - crop.midX * scale, y: bounds.midY - crop.midY * scale,
                            width: scale, height: scale)
        bottle.draw(in: canvas)
        let interior = bottle.interiorRect(in: canvas)
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: interior).addClip()
        let safe = interior.insetBy(dx: 12, dy: 12)
        for (index, color) in inventory.visibleColors.enumerated() {
            guard let pose = motion.frames[inventory.visibleIDs[index]] else { continue }
            let u = pose.x / 180, v = pose.y / 320
            let center = NSPoint(x: safe.minX + CGFloat(u) * safe.width, y: safe.minY + CGFloat(v) * safe.height)
            // The original jar is 180×320. Map its velocity through the actual
            // bottle aspect ratio so the head follows the displayed trajectory.
            let dx = cos(pose.heading) * safe.width / 180
            let dy = sin(pose.heading) * safe.height / 320
            FlyParadiseArtwork.shared.draw(at:center, color:color, sex:inventory.visibleSexes[index],
                heading:atan2(dy,dx), motion:.flying, now:pose.animationTime, seed:pose.seed)
        }
        NSGraphicsContext.restoreGraphicsState()
    }
}

struct BottleInventoryScene: NSViewRepresentable {
    let inventory: BottleDisplayInventory
    let style: InsectStyle
    let elapsed: TimeInterval
    func makeNSView(context: Context) -> BottleInventoryView { BottleInventoryView() }
    func updateNSView(_ view: BottleInventoryView, context: Context) {
        view.inventory = inventory; view.style = style; view.elapsed = elapsed
        view.updateMotion(); view.needsDisplay = true
        view.setAccessibilityElement(true)
        view.setAccessibilityLabel("瓶内 \(inventory.total) 只，画面显示 \(inventory.visibleColors.count) 只")
    }
}

struct BottlePage: View {
    @ObservedObject var store: Store
    @ObservedObject var controls: BottleControls
    var capture: () -> Void
    init(store: Store, capture: @escaping () -> Void = {}) {
        self.store = store; controls = store.bottleControls; self.capture = capture
    }
    var body: some View {
        ScrollViewReader { scroll in
        VStack(alignment: .leading, spacing: 8) {
            let status = BottleStatus(state: store.state)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("虫瓶 · \(status.inventoryText)").font(.system(size: 20, weight: .medium, design: .serif))
                    Spacer()
                }
                Text(status.captureText).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            let inventory = BottleDisplayInventory(rows: store.rows("bottle"),
                individuals: store.state["bottle_individuals"] as? [[String: Any]])
            TimelineView(.animation(minimumInterval: 1.0 / 30)) { _ in
                BottleInventoryScene(inventory: inventory, style: store.insectStyle,
                    elapsed: ProcessInfo.processInfo.systemUptime)
            }.frame(width: 252, height: 252).allowsHitTesting(false)
                .frame(maxWidth: .infinity)
                .overlay(alignment: .bottomTrailing) {
                    if inventory.total > inventory.visibleColors.count {
                        Text("展示 \(inventory.visibleColors.count) 只").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            HStack(spacing: 8) {
                ForEach(store.rows("bottle"), id: \.colorKey) { row in
                    let name = row.colorKey
                    Button { controls.chooseColor(name) } label: {
                        VStack(spacing: 3) {
                            Text(name).font(.callout)
                            Text("\((row["female"] as? Int ?? 0) + (row["male"] as? Int ?? 0)) 只")
                                .font(.caption).foregroundStyle(.secondary)
                        }.frame(maxWidth: .infinity).padding(.vertical, 6)
                            .background(controls.color == name ? accent.opacity(0.17) : Color.white.opacity(0.7))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }.buttonStyle(.plain).disabled(controls.locked)
                        .accessibilityIdentifier("bottle-color-\(name)")
                }
            }
            if controls.totalInventory == 0 {
                Text("瓶里暂时没有虫").foregroundStyle(.secondary)
                Text("在桌面空白处框选，松手后等蜘蛛织网。").font(.caption).foregroundStyle(.secondary)
            } else {
                Divider().padding(.vertical, 4)
                HStack {
                    Text(controls.color)
                    Spacer()
                    Stepper("数量 \(controls.saleCount)", value: $controls.count, in: 1...max(1, controls.available)).frame(width: 170)
                }.disabled(controls.locked || controls.available == 0)
                HStack(spacing: 14) {
                    Button("放回…") { controls.beginRelease() }
                    Button("出售 \(controls.saleCount) 只 · \(controls.saleAmount) 铜钱") { controls.previewSale() }
                        .buttonStyle(.borderedProminent)
                }.disabled(controls.locked || controls.available == 0)
                if controls.releaseExpanded {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("放回 \(controls.color)").font(.headline)
                            Spacer()
                            Button("收起") { controls.dismissRelease() }
                        }
                        Text("雌 \(controls.female) · 雄 \(controls.male)").font(.caption).foregroundStyle(.secondary)
                        HStack {
                            Picker("性别", selection: $controls.releaseSex) {
                                ForEach(["全部", "雌", "雄"], id: \.self) { Text($0) }
                            }.frame(width: 160)
                            Spacer()
                            Stepper("数量 \(controls.releaseSelectedCount)", value: $controls.releaseCount, in: 1...max(1, controls.releaseAvailable)).frame(width: 170)
                        }
                        Button("放回桌面") { controls.release() }.disabled(controls.releaseAvailable == 0)
                    }.padding(12).background(accent.opacity(0.10)).clipShape(RoundedRectangle(cornerRadius: 10))
                        .disabled(controls.locked).id("bottle-release-controls")
                }
                if let sale = store.sale {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("确认出售 \(sale["count"] as? Int ?? 0) 只，到账 \(sale["amount"] as? Int ?? 0) 铜钱？")
                        HStack {
                            Button("确认出售") { controls.confirmSale() }
                            Button("取消") { controls.cancelSale() }
                        }
                    }.padding(12).background(Color.white.opacity(0.7)).clipShape(RoundedRectangle(cornerRadius: 10))
                        .disabled(controls.isSubmitting).id("bottle-sale-confirmation")
                } else if controls.available == 0 {
                    Text("这个体色暂时没有库存，可选择其他体色。").foregroundStyle(.secondary)
                }
            }
            Text(store.state["auto_paused"] as? Bool == true ? "自动捕捉已暂停：出售或放回至少一只即可继续；手动捕虫仍可用。" : "瓶里暂停繁殖，长期保存，无需清洁。")
                .font(.callout).foregroundStyle(.secondary).padding(.top, 4)
        }.onChange(of: controls.releaseExpanded) { expanded in
            if expanded {
                DispatchQueue.main.async { scroll.scrollTo("bottle-release-controls", anchor: .bottom) }
            }
        }.onChange(of: store.sale?["token"] as? String) { token in
            if token != nil {
                DispatchQueue.main.async { scroll.scrollTo("bottle-sale-confirmation", anchor: .bottom) }
            }
        }.onDisappear { controls.dismissRelease() }
        }
    }
}

// Preview intent is local. Only successful backend state receipts change ownership or placement.
final class ShopControls: ObservableObject {
    private unowned let store: Store
    private let availableArtwork: Set<String>
    @Published private(set) var category = "神龛"
    @Published private(set) var showingCategory = false
    @Published private(set) var selectedID: String?
    @Published private(set) var showingInitial = false
    @Published private(set) var isSubmitting = false
    init(store: Store, availableArtwork: Set<String>? = nil) {
        self.store = store
        self.availableArtwork = availableArtwork ?? ShrineArtwork.shared?.availableAppearanceIDs ?? []
    }
    var selected: [String: Any] { store.rows("shop").first { $0.itemKey == selectedID } ?? [:] }
    var selectedSlot: String { selected["slot"] as? String ?? "" }
    var selectedOwned: Bool { selected["owned"] as? Bool ?? false }
    var selectedPlaced: Bool {
        guard let selectedID else { return false }
        return SceneAppearance(snapshot: store.state).itemID(in: selectedSlot) == selectedID
    }
    var selectedArtworkAvailable: Bool { selectedID.map(availableArtwork.contains) ?? false }
    var canBuySelected: Bool {
        guard !isSubmitting, !selectedOwned, selectedArtworkAvailable, !selected.isEmpty else { return false }
        if let ready = selected["can_buy"] as? Bool { return ready }
        if let required = selected["requires"] as? String,
           !store.rows("shop").contains(where: { $0.itemKey == required && $0["owned"] as? Bool == true }) { return false }
        return store.coins >= (selected["price"] as? Int ?? Int.max)
    }
    var canPlaceSelected: Bool { !isSubmitting && selectedOwned && (selectedPlaced || selectedArtworkAvailable) }
    var unavailableReason: String? {
        guard selectedID != nil else { return nil }
        if !selectedArtworkAvailable { return "外观暂未具备" }
        if selectedOwned { return nil }
        return selected["unavailable_reason"] as? String ?? (canBuySelected ? nil : "铜钱不足")
    }
    var previewAppearance: SceneAppearance {
        let actual = SceneAppearance(snapshot: store.state)
        guard let selectedID else { return actual }
        return showingInitial ? actual.resetting(slot: selectedSlot) : actual.previewing(itemID: selectedID)
    }
    static let categories = ["神龛", "供具"]
    static func category(for slot: String) -> String? {
        switch slot {
        case "shrine": return "神龛"
        case "plate", "incense", "bell": return "供具"
        default: return nil
        }
    }
    var items: [[String: Any]] {
        store.rows("shop").filter { Self.category(for: $0["slot"] as? String ?? "") == category }
    }
    var currentShrineID: String? { SceneAppearance(snapshot: store.state).itemID(in: "shrine") }
    var currentShrineName: String {
        guard let id = currentShrineID else { return "初始神龛" }
        return store.rows("shop").first { $0.itemKey == id }?["name"] as? String ?? "当前神龛"
    }
    var currentUtensilsName: String {
        let actual = SceneAppearance(snapshot: store.state)
        let names = store.rows("shop").filter { row in
            let slot = row["slot"] as? String ?? ""
            return Self.category(for: slot) == "供具" && actual.itemID(in: slot) == row.itemKey
        }.compactMap { $0["name"] as? String }
        return names.isEmpty ? "初始供盘与香炉" : names.joined(separator: "、")
    }
    var placementActionTitle: String {
        guard selectedPlaced else { return "摆上" }
        return selectedSlot == "bell" ? "收起" : "恢复初始"
    }
    func refresh() {
        if let selectedID, !store.rows("shop").contains(where: { $0.itemKey == selectedID }) { dismissPreview() }
        objectWillChange.send()
    }
    func choose(_ itemID: String) {
        guard !isSubmitting, let row = store.rows("shop").first(where: { $0.itemKey == itemID }),
              let slot = row["slot"] as? String,
              SceneAppearance().previewing(itemID: itemID).itemID(in: slot) == itemID else { return }
        guard let group = Self.category(for: slot) else { return }
        category = group; showingCategory = true
        selectedID = itemID; showingInitial = false
    }
    func chooseCategory(_ value: String) { openCategory(value) }
    func openCategory(_ value: String) {
        let group = value == "神前" ? "神龛" : value
        guard !isSubmitting, Self.categories.contains(group) else { return }
        category = group; showingCategory = true; dismissPreview()
    }
    func showCollectionRoot() {
        guard !isSubmitting else { return }
        showingCategory = false; dismissPreview()
    }
    func previewInitial() { guard selectedID != nil, !isSubmitting else { return }; showingInitial = true }
    func previewSelected() { guard selectedID != nil, !isSubmitting else { return }; showingInitial = false }
    func dismissPreview() { selectedID = nil; showingInitial = false }
    func buySelected() {
        guard canBuySelected, let selectedID else { return }
        submit("buy", item: selectedID)
    }
    func placeSelected() {
        guard canPlaceSelected, let selectedID else { return }
        submit("place", item: selectedID)
    }
    private func submit(_ action: String, item: String) {
        isSubmitting = true
        store.send(action, ["item": item]) { [weak self] _ in self?.isSubmitting = false }
    }
}

// Compatibility entry point: the production panel and legacy ShopPage share one hierarchy.
struct ShopPage: View {
    @ObservedObject var store: Store
    var body: some View { CollectionPage(store: store) }
}

struct CodexPage: View {
    @ObservedObject var store: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SmallHeading(title: "虫谱", subtitle: "四种体色，同一种果蝇。发现过的颜色会一直留在这里。")
            ForEach(store.rows("discoveries"), id: \.colorKey) { item in
                HStack {
                    Image(systemName: item["found"] as? Bool == true ? "checkmark.seal" : "questionmark.circle").font(.title2).frame(width: 48)
                    VStack(alignment: .leading, spacing: 6) {
                        Text(item.colorKey).font(.headline)
                        Text(item["found"] as? Bool == true ? "首次发现：\(item["date"] as? String ?? "旧存档未记录")" : "尚未发现").foregroundStyle(.secondary)
                        Text(item["description"] as? String ?? "").font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                }.padding(16).background(Color.white.opacity(0.7)).clipShape(RoundedRectangle(cornerRadius: 10))
            }
            Text("体色继承采用本作简化遗传规则，不作为现实果蝇遗传模型。").font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
    }
}

// Confirmation freezes the inspected backup token; a refresh never silently retargets it.
final class RecoveryControls: ObservableObject {
    private unowned let store: Store
    @Published private(set) var confirmingToken: String?
    @Published private(set) var isSubmitting = false
    @Published private(set) var feedback = ""
    var onUpdate: (() -> Void)?
    init(store: Store) { self.store = store }
    var issueText: String { store.startupIssue?["message"] as? String ?? "正在读取存档…" }
    var phase: String { store.runtimePhase }
    var token: String? { store.recoveryInfo?["token"] as? String }
    var backupAvailable: Bool { store.recoveryInfo?["backup_available"] as? Bool == true }
    var canInspect: Bool { phase == "recovery" && !isSubmitting }
    var canRestore: Bool { canInspect && backupAvailable && token != nil }
    var canRetry: Bool { phase == "failed" && store.process?.isRunning != true && !isSubmitting }
    var backupText: String {
        guard backupAvailable, let summary = store.recoveryInfo?["backup_summary"] as? [String: Any] else {
            return phase == "failed" ? "重新打开后再检查存档。" : "没有可用的上一份备份。请保留现有文件。"
        }
        let coins = summary["coins"] as? Int ?? 0
        let desktop = summary["desktop_count"] as? Int ?? 0, bottle = summary["bottle_count"] as? Int ?? 0
        let date = (summary["modified_at"] as? Double).map { Date(timeIntervalSince1970: $0).formatted(date: .abbreviated, time: .shortened) } ?? "时间未记录"
        return "可用备份：\(date)\n\(coins) 铜钱 · 桌面 \(desktop) 只 · 虫瓶 \(bottle) 只"
    }
    func refresh() {
        if confirmingToken != nil && (token != confirmingToken || phase != "recovery" || !backupAvailable) { confirmingToken = nil }
        if phase == "ready" { confirmingToken = nil; feedback = "" }
        onUpdate?()
    }
    func beginRestore() { guard canRestore else { return }; confirmingToken = token; feedback = ""; onUpdate?() }
    func cancelRestore() { guard !isSubmitting else { return }; confirmingToken = nil; feedback = ""; onUpdate?() }
    func inspect() {
        guard canInspect else { return }
        confirmingToken = nil; submit("recovery_inspect")
    }
    func confirmRestore() {
        guard canRestore, let confirmed = confirmingToken, confirmed == token else { return }
        submit("recovery_restore", ["token": confirmed, "confirmed": true])
    }
    private func submit(_ action: String, _ values: [String: Any] = [:]) {
        isSubmitting = true; feedback = ""; onUpdate?()
        store.send(action, values) { [weak self] ok in
            guard let self else { return }
            self.isSubmitting = false
            if !ok { self.feedback = "操作未完成，请检查提示后重试。" }
            self.refresh()
        }
    }
    func retry() { guard canRetry else { return }; store.retryOpening() }
}

final class RecoveryControlView: NSView {
    let controls: RecoveryControls
    let titleLabel = NSTextField(labelWithString: "存档暂时打不开")
    let issueLabel = NSTextField(wrappingLabelWithString: "")
    let backupLabel = NSTextField(wrappingLabelWithString: "")
    let detailLabel = NSTextField(wrappingLabelWithString: "")
    let feedbackLabel = NSTextField(wrappingLabelWithString: "")
    let restoreButton = NSButton(title: "恢复备份…", target: nil, action: nil)
    let inspectButton = NSButton(title: "重新检查", target: nil, action: nil)
    let retryButton = NSButton(title: "重试打开", target: nil, action: nil)
    let confirmButton = NSButton(title: "保留原件并恢复", target: nil, action: nil)
    let cancelButton = NSButton(title: "取消", target: nil, action: nil)
    init(controls: RecoveryControls) {
        self.controls = controls
        super.init(frame: NSRect(x: 0, y: 0, width: 420, height: 400))
        titleLabel.font = .systemFont(ofSize: 22, weight: .medium)
        issueLabel.font = .systemFont(ofSize: 14)
        backupLabel.font = .systemFont(ofSize: 14)
        detailLabel.font = .systemFont(ofSize: 13)
        feedbackLabel.font = .systemFont(ofSize: 12)
        feedbackLabel.textColor = .systemRed
        for label in [titleLabel, issueLabel, backupLabel, detailLabel, feedbackLabel] { addSubview(label) }
        for (button, selector) in [(restoreButton, #selector(begin)), (inspectButton, #selector(inspect)),
                (retryButton, #selector(retry)), (confirmButton, #selector(confirm)), (cancelButton, #selector(cancel))] {
            button.bezelStyle = .rounded; button.target = self; button.action = selector; addSubview(button)
        }
        controls.onUpdate = { [weak self] in self?.sync() }
        sync()
    }
    required init?(coder: NSCoder) { nil }
    override var isFlipped: Bool { true }
    override var intrinsicContentSize: NSSize { NSSize(width: 400, height: 400) }
    func sync() {
        issueLabel.stringValue = controls.issueText
        backupLabel.stringValue = controls.backupText
        detailLabel.stringValue = controls.confirmingToken == nil
            ? "检查不会改动存档。恢复前会另存现有原件和这份备份。"
            : "确认用上述备份恢复？现有原件和这份备份会另存保留；备份之后的进度可能丢失。"
        feedbackLabel.stringValue = controls.isSubmitting ? "正在处理，请稍候…" : controls.feedback
        let confirming = controls.confirmingToken != nil
        restoreButton.isHidden = confirming || controls.phase != "recovery"
        inspectButton.isHidden = confirming || controls.phase != "recovery"
        retryButton.isHidden = controls.phase != "failed"
        confirmButton.isHidden = !confirming; cancelButton.isHidden = !confirming
        restoreButton.isEnabled = controls.canRestore; inspectButton.isEnabled = controls.canInspect
        retryButton.isEnabled = controls.canRetry; confirmButton.isEnabled = confirming && controls.canRestore
        cancelButton.isEnabled = !controls.isSubmitting
        needsLayout = true; layoutSubtreeIfNeeded()
    }
    override func layout() {
        super.layout()
        let width = max(100, bounds.width - 4)
        titleLabel.frame = NSRect(x: 0, y: 2, width: width, height: 30)
        issueLabel.frame = NSRect(x: 0, y: 48, width: width, height: 78)
        backupLabel.frame = NSRect(x: 0, y: 139, width: width, height: 55)
        detailLabel.frame = NSRect(x: 0, y: 207, width: width, height: 57)
        feedbackLabel.frame = NSRect(x: 0, y: 275, width: width, height: 45)
        for button in [restoreButton, retryButton, confirmButton] { button.frame = NSRect(x: 0, y: 340, width: 164, height: 30) }
        for button in [inspectButton, cancelButton] { button.frame = NSRect(x: 178, y: 340, width: 110, height: 30) }
    }
    @objc private func begin() { controls.beginRestore() }
    @objc private func inspect() { controls.inspect() }
    @objc private func retry() { controls.retry() }
    @objc private func confirm() { controls.confirmRestore() }
    @objc private func cancel() { controls.cancelRestore() }
}

struct SaveRecoveryView: NSViewRepresentable {
    @ObservedObject var controls: RecoveryControls
    func makeNSView(context: Context) -> RecoveryControlView { RecoveryControlView(controls: controls) }
    func updateNSView(_ view: RecoveryControlView, context: Context) { view.sync() }
}

// The draft changes only when the saved value changes, never on each heartbeat.
final class GameSettingsControls: ObservableObject {
    private unowned let store: Store
    private var observedTimezone: String?
    @Published var draftTimezone = ""
    @Published private(set) var isSubmitting = false
    @Published private(set) var feedback = ""
    init(store: Store) { self.store = store; refresh() }
    var savedTimezone: String { store.state["game_timezone"] as? String ?? "" }
    var timezones: [String] {
        var values: [String] = []
        for value in [savedTimezone, TimeZone.current.identifier, "Asia/Shanghai", "UTC"] where !value.isEmpty {
            if !values.contains(value) { values.append(value) }
        }
        return values
    }
    var canApply: Bool { !savedTimezone.isEmpty && !isSubmitting && timezones.contains(draftTimezone) && draftTimezone != savedTimezone }
    func refresh() {
        if observedTimezone != savedTimezone {
            observedTimezone = savedTimezone; draftTimezone = savedTimezone; feedback = ""
        }
    }
    func applyTimezone() {
        guard canApply else { return }
        let requested = draftTimezone
        isSubmitting = true; feedback = ""
        store.send("game_timezone_set", ["timezone": requested]) { [weak self] ok in
            guard let self else { return }
            self.isSubmitting = false
            self.feedback = ok ? "已保存。" : "时区未保存，请重试。"
        }
    }
}

struct GameTimezoneSettings: View {
    @ObservedObject var controls: GameSettingsControls
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("游戏时区").font(.headline)
            Text("当前：\(controls.savedTimezone.isEmpty ? "读取中" : controls.savedTimezone)").font(.caption).foregroundStyle(.secondary)
            Picker("时区", selection: $controls.draftTimezone) {
                ForEach(controls.timezones, id: \.self) { zone in
                    Text(zone == TimeZone.current.identifier ? "\(zone)（当前本机）" : zone).tag(zone)
                }
            }.disabled(controls.isSubmitting)
            Button(controls.isSubmitting ? "保存中…" : "应用") { controls.applyTimezone() }.disabled(!controls.canApply)
            Text("用于日签与小庙日常；计时时区单独设置。跨地区后可在此修改，不补过往日常。").font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if !controls.feedback.isEmpty { Text(controls.feedback).font(.caption) }
        }
    }
}

struct PanelView: View {
    @ObservedObject var store: Store
    @ObservedObject var presentation: PresentationState
    let adjust: (String) -> Void
    let hide: () -> Void
    let dismiss: () -> Void
    var detachTimer: () -> Void = {}
    var capture: () -> Void = {}
    var changeRoute: ((String) -> Void)?
    func selectPage(_ route: String) {
        if let changeRoute { changeRoute(route) }
        else { store.cancelSale(); presentation.open(route) }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                if store.startupIssue == nil {
                    ForEach(pageNames, id: \.self) { page in
                        Button { selectPage(page) } label: {
                            if let image = SceneMenuArtwork.image(page) {
                                Image(nsImage:image).resizable().scaledToFit().frame(width:25,height:25)
                            }
                        }.buttonStyle(.plain).padding(6)
                            .background(presentation.route == page ? accent.opacity(0.14) : .clear,in:Circle())
                            .help(page).accessibilityLabel(page)
                    }
                }
                Spacer()
                if ["虫瓶", "装扮"].contains(presentation.route ?? "") { Text("\(store.coins) 铜钱").font(.caption) }
                QuietIconButton(title:"收起",symbol:"xmark",action:dismiss)
            }
            ScrollView {
                Group {
                    if store.startupIssue != nil {
                        SaveRecoveryView(controls: store.recoveryControls).frame(height: 400)
                    } else {
                    switch presentation.route {
                    case "虫瓶": BottlePage(store: store, capture: capture)
                    case "装扮", "虫谱": CollectionPage(store: store)
                    case "计时": TimerView(store: store, detach: detachTimer)
                    case "设置":
                        VStack(alignment: .leading, spacing: 18) {
                            SceneSizeControl(store: store)
                            SceneTransparencyControl(store: store)
                            VStack(alignment: .leading, spacing: 6) {
                                Picker("点击退出时", selection: Binding(get: { store.exitAction }, set: { store.setExitAction($0) })) {
                                    ForEach(SceneExitAction.allCases, id: \.self) { action in Text(action.title).tag(action) }
                                }
                                Text(store.exitAction.detail).font(.caption).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                                if !store.exitActionError.isEmpty { Text(store.exitActionError).font(.caption).foregroundStyle(.red) }
                            }
                            Toggle("桌面框选时织网",isOn:Binding(get:{store.naturalCaptureEnabled},set:{store.setNaturalCaptureEnabled($0)}))
                                .help("跟随桌面空白处的框选，不接管鼠标；右键取消本次网。")
                            Toggle("飞虫置顶", isOn: Binding(get: { store.insectsOnTop }, set: { store.setInsectsOnTop($0) }))
                            InsectStyleControl(store: store)
                            DisclosureGroup("天气与城市") { WeatherSettingsPanel(weather:store.atmosphere) }
                            GameTimezoneSettings(controls: store.gameSettings)
                            NotificationSettingsView(store: store, notifications: store.notifications)
                        }
                    case "求签": ShrinePage(store: store, presentation: presentation)
                    default: EmptyView()
                    }
                    }
                }.frame(maxWidth: .infinity, alignment: .topLeading)
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            Text(store.message).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }.padding(16).frame(minWidth: 320, minHeight: 400).background(.ultraThinMaterial).foregroundStyle(.primary).tint(accent)
    }
}

struct InsectStyleControl: View {
    @ObservedObject var store: Store
    var value: Binding<InsectStyle> {
        Binding(get: { store.insectStyle }, set: { store.setInsectStyle($0) })
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("虫形 · 果蝇乐园").font(.callout).foregroundStyle(.secondary)
            if !store.insectStyleError.isEmpty { Text(store.insectStyleError).font(.caption).foregroundStyle(.red) }
        }
    }
}

struct SceneSizeControl: View {
    @ObservedObject var store: Store
    var value: Binding<Double> {
        Binding(get: { normalizedSceneScale(store.sceneScale) }, set: { store.setSceneScale($0) })
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("大小").font(.headline)
            Slider(value: value, in: 20...150).accessibilityLabel("大小")
            HStack {
                Text("小").font(.caption)
                Spacer()
                Text("大").font(.caption)
                Button("默认") { store.setSceneScale(75) }
            }
            if !store.sceneSizeError.isEmpty { Text(store.sceneSizeError).font(.caption).foregroundStyle(.red) }
        }
    }
}

struct SceneTransparencyControl: View {
    @ObservedObject var store: Store
    var value: Binding<Double> {
        Binding(get: { store.sceneTransparency }, set: { store.setSceneTransparency($0) })
    }
    func reset() { store.setSceneTransparency(100) }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("鼠标靠近时隐身", isOn: Binding(get: { store.pointerAvoidance }, set: { store.setPointerAvoidance($0) }))
            Text("透明度 \(Int(store.sceneTransparency.rounded()))%").font(.headline)
            Slider(value: value, in: 0...100).accessibilityLabel("透明度")
            Text("100% 完全隐身，移开后恢复。隐身时鼠标穿透。").font(.caption).foregroundStyle(.secondary)
            if !store.transparencyError.isEmpty {
                Text(store.transparencyError).font(.caption).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

struct NotificationSettingsView: View {
    @ObservedObject var store: Store
    @ObservedObject var notifications: TimerNotifications
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("系统通知", isOn: Binding(get: { store.timer["notification_enabled"] as? Bool ?? true }, set: { store.send("timer_preferences", ["notification_enabled": $0]) }))
            Text(notifications.statusText).font(.caption).fixedSize(horizontal: false, vertical: true)
            if notifications.access == .notDetermined {
                Button("请求 macOS 通知权限…") { notifications.requestFromUserClick() }.disabled(notifications.requesting)
            }
            Button("刷新通知状态") { notifications.refresh() }
            if !notifications.deliveryText.isEmpty { Text(notifications.deliveryText).font(.caption).fixedSize(horizontal: false, vertical: true) }
            Text("未授权或拒绝时，声音和应用内提示仍按各自开关工作。").font(.caption).foregroundStyle(.secondary)
        }.onAppear { notifications.refresh() }
    }
}

struct TimerView: View {
    @ObservedObject var store: Store
    @ObservedObject var controls: TimerControls
    var detach: () -> Void
    @State private var unitsExpanded = false
    init(store: Store, detach: @escaping () -> Void = {}) {
        self.store = store; self.controls = store.timerControls; self.detach = detach
    }
    var mode: String { controls.draftMode }
    var active: Bool { controls.active }
    var displayedTimer: [String:Any] {
        var value = store.timer
        if mode == "clock" { value["mode"]="clock"; value["status"]="idle" }
        return value
    }
    func begin() { controls.start(TimerStartRequest(mode:mode,duration:controls.draftDuration,rest:controls.draftRest),from:.sidebar) }
    var body: some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                Spacer()
                QuietIconButton(title:"独立计时窗",symbol:"macwindow.on.rectangle",action:detach)
            }
            VStack(spacing: 6) {
                let lines = (displayedTimer[mode == "clock" ? "clock_readout" : "readout"] as? String ?? "--:--").components(separatedBy: "\n")
                Text(lines.first ?? "--:--")
                    .font(.system(size: 48, weight: .medium, design: .monospaced))
                    .lineLimit(1).minimumScaleFactor(0.65)
                    .accessibilityLabel("当前时间读数")
                    .accessibilityValue(lines.joined(separator: " "))
                if lines.count > 1 { Text(lines.dropFirst().joined(separator: " ")).font(.caption).foregroundStyle(.secondary) }
                if mode != "clock", let traditional = store.timer["traditional_readout"] as? String, !traditional.isEmpty {
                    Text((mode == "stopwatch" ? "已用 " : "余 ") + traditional).font(.system(size:16,design:.serif)).foregroundStyle(.secondary)
                }
                if mode != "clock" { Text(controls.statusTitle).font(.caption).foregroundStyle(.secondary) }
            }.frame(maxWidth: .infinity).padding(.vertical, 14).accessibilityIdentifier("timer-readout")
            if let pending=controls.pending, pending.surface == .sidebar {
                VStack(alignment: .leading, spacing: 8) {
                    Text("结束当前任务，改为\(pending.request.label)？").font(.callout)
                    HStack {
                        Button("替换并开始") { controls.confirmReplacement(from:.sidebar) }
                        Button("保留当前") { controls.cancelReplacement(from:.sidebar) }
                    }
                }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
            }
            HStack(spacing:16) {
                Spacer()
                QuietIconButton(title:controls.primaryTitle,symbol:controls.status == "running" ? "pause.fill" : "play.fill") { controls.performPrimary() }
                    .disabled(!controls.canUsePrimary || controls.isSubmitting || controls.pending != nil)
                QuietIconButton(title:"重来",symbol:"arrow.counterclockwise") { controls.restart(from: .sidebar) }
                    .disabled(!controls.canRestart || controls.isSubmitting || controls.pending != nil)
                QuietIconButton(title:"结束",symbol:"stop.fill") { controls.command("timer_end") }
                    .disabled(!active || controls.isSubmitting || controls.pending != nil)
                Spacer()
            }
            Picker("方式",selection:$controls.draftMode) {
                Text("时钟").tag("clock"); Text("倒计时").tag("countdown"); Text("正计时").tag("stopwatch"); Text("番茄钟").tag("pomodoro")
            }.pickerStyle(.segmented)
            if mode != "stopwatch" && mode != "clock" {
                HStack {
                    Text(mode == "pomodoro" ? "工作" : "时长").font(.caption)
                    TextField("一盏茶、三刻、25…",text:$controls.draftDuration).textFieldStyle(.roundedBorder).help("不写单位按分钟；支持国风时长、90s、1h30m")
                        .onSubmit { begin() }
                    if mode == "pomodoro" {
                        Text("休息").font(.caption)
                        TextField("5",text:$controls.draftRest).textFieldStyle(.roundedBorder).frame(width:56)
                            .onSubmit { begin() }
                    }
                }
                HStack(spacing: 8) {
                    ForEach(0..<4,id:\.self) { index in
                        Button(controls.unitTitle(index)) {
                            controls.draftDuration = controls.unitPresets[index]["input"] as? String ?? "一刻"
                            if mode == "countdown" { controls.startUnit(at:index,from:.sidebar) }
                        }.help(controls.unitHint(index))
                            .disabled(!controls.ready || controls.isSubmitting || controls.pending != nil)
                    }
                }
                HStack {
                    ForEach(0..<4,id:\.self) { index in
                        Button(controls.presetTitle(index)) {
                            controls.draftDuration=controls.presetInput(index)
                            if mode == "countdown" { controls.startPreset(at:index,from:.sidebar) }
                        }.disabled(!controls.ready || controls.isSubmitting || controls.pending != nil)
                    }
                    Spacer()
                    QuietIconButton(title:"编辑常用时长",symbol:"slider.horizontal.3") { controls.beginPresetEditing() }
                        .disabled(!controls.ready || controls.isSubmitting || controls.pending != nil)
                }
            }
            if controls.editingPresets {
                VStack(alignment:.leading,spacing:8) {
                    Text("常用时长").font(.caption)
                    HStack(spacing:8) {
                        ForEach(0..<4,id:\.self) { index in
                            TextField("时长",text:Binding(get:{ controls.presetDrafts[index] },set:{ controls.presetDrafts[index]=$0 }))
                                .textFieldStyle(.roundedBorder)
                                .accessibilityLabel("常用时长 \(index+1)")
                                .disabled(controls.isSubmitting)
                        }
                    }
                    Text("不写单位按分钟；也可填 90s、1h30m。").font(.caption2).foregroundStyle(.secondary)
                    HStack {
                        Button("保存") { controls.savePresetEdits() }.disabled(controls.isSubmitting)
                        Button("取消") { controls.cancelPresetEditing() }.disabled(controls.isSubmitting)
                            .accessibilityLabel("取消常用时长编辑")
                        Spacer()
                        Button("恢复默认") { controls.presetDrafts=["5","15","25","45"] }.disabled(controls.isSubmitting)
                    }
                    if !controls.presetFeedback.isEmpty {
                        Text(controls.presetFeedback).font(.caption).foregroundStyle(.red).fixedSize(horizontal:false,vertical:true)
                    }
                }.padding(10).background(paper).clipShape(RoundedRectangle(cornerRadius:10))
            }
            if mode != "clock" {
                Button(active ? "替换计时…" : "开始",action:begin).buttonStyle(.borderedProminent)
                    .disabled(!controls.ready || controls.isSubmitting || controls.pending != nil).frame(maxWidth:.infinity)
            }
            if !controls.feedback.isEmpty { Text(controls.feedback).font(.caption).foregroundStyle(.red) }
            DisclosureGroup("国风单位", isExpanded:$unitsExpanded) {
                VStack(alignment:.leading,spacing:10) {
                    Text("一刻15分钟，一时辰2小时。茶与香是本作的可调约定。").font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Text("一盏茶").frame(width:50,alignment:.leading)
                        TextField("10",text:$controls.teaDraft).textFieldStyle(.roundedBorder).frame(maxWidth:120)
                            .accessibilityLabel("一盏茶的时长").disabled(controls.isSubmitting)
                        Spacer()
                    }.font(.caption)
                    HStack {
                        Text("一炷香").frame(width:50,alignment:.leading)
                        TextField("30",text:$controls.incenseDraft).textFieldStyle(.roundedBorder).frame(maxWidth:120)
                            .accessibilityLabel("一炷香的时长").disabled(controls.isSubmitting)
                        Spacer()
                    }.font(.caption)
                    HStack {
                        Text("纯数字按分钟；不改变当前计时。").font(.caption2).foregroundStyle(.secondary)
                        Spacer()
                        Button("保存单位") { controls.saveUnits() }.disabled(!controls.ready || controls.isSubmitting || controls.pending != nil)
                    }
                    if !controls.unitFeedback.isEmpty { Text(controls.unitFeedback).font(.caption).foregroundStyle(.secondary) }
                }.padding(.top,8)
            }.onChange(of:unitsExpanded) { if $0 { controls.prepareUnits() } }
            DisclosureGroup("提醒与显示") {
                VStack(alignment:.leading,spacing:12) {
                    Picker("时区",selection:Binding(get:{store.timer["clock_timezone"] as? String ?? "local"},set:{store.send("timer_preferences",["timezone":$0])})) {
                        Text("本地").tag("local"); Text("北京时间").tag("Asia/Shanghai")
                    }
                    Toggle("国风换算",isOn:Binding(get:{store.timer["show_traditional"] as? Bool ?? true},set:{store.send("timer_preferences",["show_traditional":$0])}))
                    Toggle("声音",isOn:Binding(get:{store.timer["sound_enabled"] as? Bool ?? true},set:{store.send("timer_preferences",["sound_enabled":$0])}))
                    Toggle("到时提示",isOn:Binding(get:{store.timer["widget_enabled"] as? Bool ?? true},set:{store.send("timer_preferences",["widget_enabled":$0])}))
                    NotificationSettingsView(store:store,notifications:store.notifications)
                    Text("收起继续计时；关闭整个程序后不能提醒。").font(.caption).foregroundStyle(.secondary)
                }.padding(.top,10)
            }.font(.caption)
        }.padding(.horizontal,4).foregroundStyle(.primary).tint(accent)
    }
}

final class SceneSizeMenuView: NSView {
    let slider: NSSlider
    private let store: Store
    init(store: Store) {
        self.store = store
        slider = NSSlider(value: store.sceneScale, minValue: 20, maxValue: 150, target: nil, action: nil)
        super.init(frame: NSRect(x: 0, y: 0, width: 220, height: 66))
        let label = NSTextField(labelWithString: "大小")
        label.frame = NSRect(x: 16, y: 40, width: 180, height: 20); addSubview(label)
        slider.frame = NSRect(x: 14, y: 12, width: 192, height: 24)
        slider.target = self; slider.action = #selector(changed); slider.isContinuous = true
        slider.setAccessibilityLabel("大小"); addSubview(slider)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    @objc func changed() { store.setSceneScale(slider.doubleValue); slider.doubleValue = store.sceneScale }
    func sync() { slider.doubleValue = store.sceneScale }
}

private final class SceneAdjustmentPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
// The menu uses the same vessel and jar as their pages, at icon size.
// Replace enum SceneMenuArtwork in full. Production objects remain the same
// ones used by the fortune, bottle and timer pages.
enum SceneMenuArtwork {
    static func image(_ route: String) -> NSImage? {
        switch route {
        case "求签", "神前": return UIArtifactLibrary.shared.image("divination-vessel")
        case "虫瓶": return BottleArtwork.production.image
        default:
            let symbol: String
            switch route {
            case "装扮": symbol = "tshirt"
            case "计时": symbol = "timer"
            case "设置": symbol = "gearshape"
            case "显示": symbol = "eye"
            case "返回": symbol = "chevron.backward"
            default: symbol = "power"
            }
            return NSImage(systemSymbolName:symbol,accessibilityDescription:route)
        }
    }
}

// A separate, masked sibling stays behind the icon button. Keeping the
// effect out of the button's subview tree prevents it from covering the icon.
final class SceneDialGlassView: NSVisualEffectView {
    override init(frame:NSRect) {
        super.init(frame:frame)
        material = .hudWindow; blendingMode = .behindWindow; state = .active
        setAccessibilityElement(false)
    }
    required init?(coder:NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func hitTest(_ point:NSPoint) -> NSView? { nil }
}

final class SceneWheelButton: NSButton {
    var shape = NSBezierPath()
    var iconCenter = NSPoint.zero
    var iconSide: CGFloat = 28
    var selected = false
    var checked = false
    var emphasized = false
    var opacity: CGFloat = 1
    var trigger: (() -> Void)?
    var onPressStateChanged: (() -> Void)?
    let glass = SceneDialGlassView(frame:.zero)
    private var held = false
    override var isFlipped: Bool { false }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    func syncGlass() {
        glass.frame = frame; glass.isHidden = isHidden; glass.alphaValue = 0.72*opacity
        guard !isHidden, bounds.width > 0, bounds.height > 0 else { return }
        let maskPath = shape.copy() as! NSBezierPath
        glass.maskImage = NSImage(size:bounds.size,flipped:false) { _ in
            NSColor.white.setFill(); maskPath.fill(); return true
        }
    }
    override func hitTest(_ point: NSPoint) -> NSView? {
        guard !isHidden, isEnabled, opacity > 0.03,
              shape.contains(convert(point,from:superview)) else { return nil }
        return self
    }
    override func mouseDown(with event: NSEvent) {
        guard isEnabled else { return }
        held = true; highlight(true); needsDisplay = true; onPressStateChanged?()
    }
    override func mouseDragged(with event: NSEvent) {
        highlight(shape.contains(convert(event.locationInWindow,from:nil)))
        needsDisplay = true; onPressStateChanged?()
    }
    override func mouseUp(with event: NSEvent) {
        let accepted = held && isEnabled && shape.contains(convert(event.locationInWindow,from:nil))
        held = false; highlight(false); needsDisplay = true; onPressStateChanged?()
        if accepted { trigger?() }
    }
    override func performClick(_ sender: Any?) { if isEnabled { trigger?() } }
    override func accessibilityPerformPress() -> Bool {
        guard isEnabled, !isHidden else { return false }; trigger?(); return true
    }
    override func draw(_ dirtyRect: NSRect) {
        NSGraphicsContext.saveGraphicsState(); defer { NSGraphicsContext.restoreGraphicsState() }
        let shadow = NSShadow(); shadow.shadowColor = NSColor.black.withAlphaComponent(0.04*opacity)
        shadow.shadowBlurRadius = 2; shadow.shadowOffset = NSSize(width:0,height:-1); shadow.set()
        NSColor.white.withAlphaComponent(0.055*opacity).setFill(); shape.fill()
        NSShadow().set()
        let tint = selected ? NSColor.controlAccentColor:NSColor.white
        NSGradient(starting:tint.withAlphaComponent((selected ? 0.14:0.07)*opacity),
                   ending:tint.withAlphaComponent((selected ? 0.045:0.018)*opacity))?.draw(in:shape,angle:-70)
        NSColor.white.withAlphaComponent((selected ? 0.34:0.23)*opacity).setStroke()
        shape.lineWidth = 0.5; shape.stroke()
        let ink = (selected && !emphasized ? NSColor.controlAccentColor:NSColor.labelColor)
            .withAlphaComponent(0.88)
        if let image {
            let ratio = min(iconSide / max(1,image.size.width),iconSide / max(1,image.size.height))
            let size = NSSize(width:image.size.width*ratio,height:image.size.height*ratio)
            let rectangle = NSRect(x:iconCenter.x-size.width/2,y:iconCenter.y-size.height/2,
                                   width:size.width,height:size.height)
            if image.isTemplate {
                let tinted = NSImage(size:image.size,flipped:false) { rect in
                    image.draw(in:rect); ink.setFill(); rect.fill(using:.sourceAtop); return true
                }
                tinted.draw(in:rectangle,from:.zero,operation:.sourceOver,
                    fraction:opacity*(isHighlighted ? 0.72:1),respectFlipped:true,hints:nil)
            } else {
                image.draw(in:rectangle,from:.zero,operation:.sourceOver,
                    fraction:opacity*(isHighlighted ? 0.72:1),respectFlipped:true,hints:nil)
            }
        }
    }
}

// Add before SceneDialSurface. Uses AppKit screen coordinates and the existing
// BongoCat-derived SceneDialGeometry sector and animation helpers unchanged.
enum SceneMenuDirection: CaseIterable {
    case up, right, left, down
    var vector: NSPoint {
        switch self {
        case .up: return NSPoint(x:0,y:1)
        case .down: return NSPoint(x:0,y:-1)
        case .right: return NSPoint(x:1,y:0)
        case .left: return NSPoint(x:-1,y:0)
        }
    }
}

struct SceneMenuPlacement {
    let frame: NSRect
    let direction: SceneMenuDirection
    var anchor: NSPoint {
        let local = SceneSemicircleLayout.anchor(for:direction)
        return NSPoint(x:frame.minX+local.x,y:frame.minY+local.y)
    }
}

enum SceneSemicircleLayout {
    static let innerRadius: CGFloat = 64
    static let outerRadius: CGFloat = 122
    static let iconRadius: CGFloat = 94
    static let hubRadius: CGFloat = 30
    static let gap: CGFloat = 6

    // Ten points include the small hover lift and the button shadow. The
    // subject-facing edge is only four points beyond the visible hub.
    static func size(for direction: SceneMenuDirection) -> NSSize {
        switch direction {
        case .up, .down: return NSSize(width:264,height:166)
        case .left, .right: return NSSize(width:166,height:264)
        }
    }
    static func anchor(for direction: SceneMenuDirection) -> NSPoint {
        switch direction {
        case .up: return NSPoint(x:132,y:34)
        case .down: return NSPoint(x:132,y:132)
        case .right: return NSPoint(x:34,y:132)
        case .left: return NSPoint(x:132,y:132)
        }
    }
    // Input retains SceneDialGeometry's y-down polar convention. Only geometry
    // turns at an edge; artwork and Chinese captions always remain upright.
    static func point(_ reference: NSPoint, direction: SceneMenuDirection) -> NSPoint {
        let center = anchor(for:direction)
        let x = reference.x, y = -reference.y
        let rotated: NSPoint
        switch direction {
        case .up: rotated = NSPoint(x:x,y:y)
        case .down: rotated = NSPoint(x:-x,y:-y)
        case .right: rotated = NSPoint(x:y,y:-x)
        case .left: rotated = NSPoint(x:-y,y:x)
        }
        return NSPoint(x:center.x+rotated.x,y:center.y+rotated.y)
    }
    static func angle(index: Int, count: Int) -> Double {
        guard count > 0 else { return -.pi/2 }
        return -.pi + (Double(index)+0.5) * .pi / Double(count)
    }
    static func sector(index: Int, count: Int) -> [NSPoint] {
        guard count > 0, index >= 0, index < count else { return [] }
        let center = angle(index:index,count:count), half = min(Double.pi / 10, Double.pi / Double(count) / 2)
        return SceneDialGeometry.sector(inner:Double(innerRadius),outer:Double(outerRadius),
            start:center-half,end:center+half)
    }

    static func placement(near subject: NSRect, in screen: NSRect,
                          preferred: SceneMenuDirection = .up) -> SceneMenuPlacement {
        let directions = [preferred] + SceneMenuDirection.allCases.filter { $0 != preferred }
        var best: (placement: SceneMenuPlacement, score: CGFloat)?
        for (rank,direction) in directions.enumerated() {
            let size = size(for:direction), local = anchor(for:direction)
            let contact: NSPoint
            switch direction {
            case .up: contact = NSPoint(x:subject.midX,y:subject.maxY)
            case .down: contact = NSPoint(x:subject.midX,y:subject.minY)
            case .right: contact = NSPoint(x:subject.maxX,y:subject.midY)
            case .left: contact = NSPoint(x:subject.minX,y:subject.midY)
            }
            let heading = direction.vector
            let desired = NSPoint(x:contact.x+heading.x*(hubRadius+gap),
                                  y:contact.y+heading.y*(hubRadius+gap))
            let frame = NSRect(
                x:max(screen.minX,min(desired.x-local.x,screen.maxX-size.width)),
                y:max(screen.minY,min(desired.y-local.y,screen.maxY-size.height)),
                width:size.width,height:size.height)
            let candidate = SceneMenuPlacement(frame:frame,direction:direction)
            let center = candidate.anchor
            let nearest = NSPoint(x:max(subject.minX,min(center.x,subject.maxX)),
                                  y:max(subject.minY,min(center.y,subject.maxY)))
            let clearance = max(0,hypot(center.x-nearest.x,center.y-nearest.y)-hubRadius)
            let overlap = frame.intersection(subject)
            let area = overlap.isNull ? 0 : overlap.width*overlap.height
            let visible = frame.intersection(screen)
            let visibleArea = visible.isNull ? 0 : visible.width*visible.height
            let overflow = max(0,size.width*size.height-visibleArea)
            // Prefer a wholly visible, non-overlapping menu, then its actual
            // hub-to-art gap. Rank breaks equal clearances deterministically.
            let score = overflow*100_000 + area*1_000 + clearance + CGFloat(rank)*0.1
            if best == nil || score < best!.score { best = (candidate,score) }
        }
        return best!.placement
    }
}

// Replace final class SceneDialSurface in full. The half-circle changes the
// arrangement only; sector vertices/reveal/hover use the preserved upstream
// SceneDialGeometry implementation and its existing AGPL attribution.
final class SceneDialSurface: NSView {
    static let diameter: CGFloat = 264 // Legacy call sites must use menuSize.
    static let menuSize = SceneSemicircleLayout.size(for:.up)
    private(set) var roots: [SceneWheelButton] = []
    private(set) var children: [SceneWheelButton] = []
    private(set) var active = -1
    private(set) var child = -1
    private(set) var childFocus = false
    let direction: SceneMenuDirection
    private var collectionChildren: [SceneWheelButton] = []
    private var lift: [Double] = []
    private var childLift = Array(repeating:Double(0),count:2)
    private var openedAt = 0.0, changedAt = 0.0, lastFrame = 0.0
    private var ticker: Timer?
    private let hub = SceneWheelButton()
    private let store: Store
    private let sceneHidden: Bool
    var onRoute: ((String) -> Void)?
    var onItem: ((String?) -> Void)? // Kept for source compatibility with host wiring.
    var onCollectionGroup: ((String) -> Void)?
    var onVisibility: (() -> Void)?
    var onQuit: (() -> Void)?
    var onDismiss: (() -> Void)?
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event:NSEvent?) -> Bool { true }

    init(store: Store, hidden: Bool, direction: SceneMenuDirection = .up) {
        self.store = store; self.direction = direction; self.sceneHidden = hidden
        super.init(frame:NSRect(origin:.zero,size:SceneSemicircleLayout.size(for:direction)))
        for (index,title) in ["虫瓶","装扮","计时","设置","退出"].enumerated() {
            let button = makeButton(title,image:SceneMenuArtwork.image(title)); roots.append(button)
            button.trigger = { [weak self] in self?.activateRoot(index) }
        }
        for group in ["神龛","供具"] {
            let button = makeButton(group,image:CollectionArtwork.shared.currentImage(for:group,snapshot:store.state))
            button.trigger = { [weak self] in self?.onCollectionGroup?(group) }
            collectionChildren.append(button)
        }
        hub.isBordered = false; hub.imagePosition = .imageOnly
        hub.trigger = { [weak self] in
            guard let self else { return }
            if self.childFocus { _ = self.back() }
            else if self.sceneHidden { self.onVisibility?() }
            else { self.onRoute?("求签") }
        }
        addSubview(hub.glass); addSubview(hub)
        hub.onPressStateChanged = { [weak self] in self?.wakeAnimation() }
        updateHub(); startAnimation()
    }
    required init?(coder:NSCoder) { fatalError("init(coder:) has not been implemented") }
    deinit { ticker?.invalidate() }
    private func makeButton(_ title:String,image:NSImage?) -> SceneWheelButton {
        let button = SceneWheelButton(title:title,target:nil,action:nil)
        button.image = image; button.imagePosition = .imageOnly; button.isBordered = false
        button.toolTip = title; button.setAccessibilityLabel(title)
        addSubview(button.glass); addSubview(button)
        button.onPressStateChanged = { [weak self] in self?.wakeAnimation() }
        return button
    }
    private func updateHub() {
        let title = childFocus ? "返回":sceneHidden ? "显示":"求签"
        hub.title = title; hub.image = SceneMenuArtwork.image(title)
        hub.toolTip = title; hub.setAccessibilityLabel(title); hub.emphasized = !childFocus
        hub.setAccessibilityHelp(childFocus ? "返回主菜单":sceneHidden ? "显示神龛与道童":"上香求签")
    }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect:bounds,options:[.mouseMoved,.mouseEnteredAndExited,.activeAlways,.inVisibleRect],owner:self))
    }
    func stopAnimation() { ticker?.invalidate(); ticker = nil }
    private func wakeAnimation() {
        let now = ProcessInfo.processInfo.systemUptime
        if ticker == nil {
            lastFrame = now
            ticker = Timer(timeInterval:1/60,repeats:true) { [weak self] _ in
                self?.render(at:ProcessInfo.processInfo.systemUptime)
            }
            RunLoop.main.add(ticker!,forMode:.common)
        }
        render(at:now)
    }
    func startAnimation() {
        stopAnimation(); openedAt = ProcessInfo.processInfo.systemUptime; changedAt = openedAt; lastFrame = openedAt
        active = -1; child = -1; childFocus = false; children = []
        lift = Array(repeating:0,count:roots.count); childLift = Array(repeating:0,count:2)
        updateHub(); wakeAnimation()
    }
    // The harness uses these exact, displayed hit regions; no desktop input.
    func point(at reference:NSPoint) -> NSPoint { SceneSemicircleLayout.point(reference,direction:direction) }
    private func contains(_ button:SceneWheelButton,_ location:NSPoint) -> Bool {
        !button.isHidden && button.shape.contains(button.convert(location,from:self))
    }
    func select(at location:NSPoint) {
        if childFocus {
            let next = children.firstIndex { contains($0,location) } ?? -1
            guard next != child else { return }; child = next
        } else {
            let next = roots.firstIndex { contains($0,location) } ?? -1
            guard next != active else { return }; active = next
        }
        wakeAnimation()
    }
    override func mouseMoved(with event:NSEvent) { select(at:convert(event.locationInWindow,from:nil)) }
    override func mouseExited(with event:NSEvent) {
        if childFocus { guard child != -1 else { return }; child = -1 }
        else { guard active != -1 else { return }; active = -1 }
        wakeAnimation()
    }
    override func mouseDown(with event:NSEvent) { onDismiss?() }
    override func rightMouseDown(with event:NSEvent) { onDismiss?() }
    func activateRoot(_ index:Int) {
        guard roots.indices.contains(index) else { return }
        active = index
        if roots[index].title == "装扮" {
            children = collectionChildren
            for button in collectionChildren {
                button.image = CollectionArtwork.shared.currentImage(for:button.title,snapshot:store.state)
            }
            childFocus = true; child = -1; changedAt = ProcessInfo.processInfo.systemUptime
            childLift = Array(repeating:0,count:children.count)
            updateHub(); wakeAnimation(); return
        }
        if roots[index].title == "退出" { onQuit?() }
        else { onRoute?(roots[index].title) }
    }
    @discardableResult func back() -> Bool {
        guard childFocus else { return false }
        childFocus = false; children = []; child = -1; active = -1
        updateHub(); wakeAnimation(); return true
    }
    override func keyDown(with event:NSEvent) {
        switch event.keyCode {
        case 53: if !back() { onDismiss?() }
        case 36,49:
            if childFocus, child >= 0 { children[child].performClick(nil) }
            else if !childFocus, active >= 0 { activateRoot(active) }
            else { hub.performClick(nil) }
        case 123,124,125,126,48:
            let step = [123,126].contains(event.keyCode) || (event.keyCode == 48 && event.modifierFlags.contains(.shift)) ? -1:1
            let count = childFocus ? children.count:roots.count
            let current = childFocus ? child:active
            let next = ((current+1+step+(count+1)) % (count+1))-1
            if childFocus { child = next } else { active = next }
            wakeAnimation()
        default: super.keyDown(with:event)
        }
    }
    func render(at time:Double) {
        let dt = max(0,min(0.1,time-lastFrame)); lastFrame = time
        let opening = SceneDialGeometry.opening(elapsedMilliseconds:max(0,time-openedAt)*1000)
        func hover(_ value:Double,_ selected:Bool) -> Double {
            let target = selected ? 1.0:0.0
            let next = SceneDialGeometry.hoverLift(current:value,target:target,elapsedSeconds:dt)
            return abs(next-target) < 0.001 ? target:next
        }
        func place(_ button:SceneWheelButton,_ points:[NSPoint],icon:NSPoint,iconSide:CGFloat,opacity:CGFloat) {
            let global = points.map { point(at:NSPoint(x:$0.x*opening,y:$0.y*opening)) }
            guard let first = global.first else { return }
            let minX = global.map(\.x).min()!, maxX = global.map(\.x).max()!
            let minY = global.map(\.y).min()!, maxY = global.map(\.y).max()!
            let frame = NSRect(x:minX-3,y:minY-3,width:maxX-minX+6,height:maxY-minY+6)
            button.frame = frame
            let path = NSBezierPath(); path.move(to:NSPoint(x:first.x-frame.minX,y:first.y-frame.minY))
            for p in global.dropFirst() { path.line(to:NSPoint(x:p.x-frame.minX,y:p.y-frame.minY)) }; path.close()
            button.shape = path
            let center = point(at:NSPoint(x:icon.x*opening,y:icon.y*opening))
            // Artwork stays upright and centered when the menu turns at a screen edge.
            button.iconCenter = NSPoint(x:center.x-frame.minX,y:center.y-frame.minY)
            button.iconSide = iconSide; button.opacity = opacity; button.needsDisplay = true
        }
        let elapsed = max(0,time-openedAt)*1000
        let globalAlpha = max(0.15,min(1,elapsed/180))
        // Original BongoCat local transform, with radial travel scaled to this
        // smaller half-wheel. The icon shares the same local scale and pull.
        func petal(_ button:SceneWheelButton,index:Int,count:Int,ease:Double,lift:Double,side:Double) {
            let angle = SceneSemicircleLayout.angle(index:index,count:count)
            let anchor = NSPoint(x:SceneSemicircleLayout.iconRadius*cos(angle),
                                 y:SceneSemicircleLayout.iconRadius*sin(angle))
            var zoom = 0.72+0.28*ease+0.055*lift
            var pull = (-26*(1-ease)+7.5*lift)*Double(SceneSemicircleLayout.outerRadius)/184
            if button.isHighlighted { zoom *= 0.96; pull *= 0.4 }
            func transformed(_ p:NSPoint) -> NSPoint {
                NSPoint(x:p.x*zoom+anchor.x*(1-zoom)+cos(angle)*pull,
                        y:p.y*zoom+anchor.y*(1-zoom)+sin(angle)*pull)
            }
            place(button,SceneSemicircleLayout.sector(index:index,count:count).map(transformed),
                  icon:transformed(anchor),iconSide:side*(1+0.15*lift)*zoom*opening,
                  opacity:CGFloat(ease*globalAlpha))
        }
        for button in collectionChildren { button.isHidden = true }
        for (index,button) in roots.enumerated() {
            button.isHidden = childFocus; guard !childFocus else { continue }
            let ease = max(index == 0 ? 0.15:0,SceneDialGeometry.reveal(elapsedMilliseconds:elapsed,index:index))
            lift[index] = hover(lift[index],index == active)
            button.selected = index == active
            petal(button,index:index,count:roots.count,ease:ease,lift:lift[index],side:28)
        }
        if childFocus {
            for (index,button) in children.enumerated() {
                button.isHidden = false
                let ease = SceneDialGeometry.reveal(elapsedMilliseconds:max(0,time-changedAt)*1000,index:index)
                childLift[index] = hover(childLift[index],index == child)
                button.selected = index == child
                petal(button,index:index,count:children.count,ease:ease,lift:childLift[index],side:36)
            }
        }
        let center = SceneSemicircleLayout.anchor(for:direction), radius = SceneSemicircleLayout.hubRadius
        hub.frame = NSRect(x:center.x-radius,y:center.y-radius,width:radius*2,height:radius*2)
        hub.shape = NSBezierPath(ovalIn:hub.bounds.insetBy(dx:1,dy:1))
        hub.iconCenter = NSPoint(x:radius,y:radius); hub.iconSide = 32
        hub.selected = childFocus ? child == -1:active == -1
        hub.opacity = CGFloat(globalAlpha); hub.needsDisplay = true
        for button in roots+collectionChildren+[hub] { button.syncGlass() }
        let values = childFocus ? childLift:lift
        let selected = childFocus ? child:active
        let hoverMoving = values.enumerated().contains { index,value in value != (index == selected ? 1:0) }
        let revealDuration = 0.36 + Double(max(0,children.count-1))*0.022
        if time-openedAt >= 0.7, (!childFocus || time-changedAt >= revealDuration), !hoverMoving {
            stopAnimation()
        }
    }
}

private final class SceneMenuPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// Open on the initial press, like a menu. There is no pending mouse-up action
// for the pointer poller to cancel while suppressing other held-button gestures.
private final class SceneAdjustmentButton: NSButton {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with event: NSEvent) {
        guard event.type == .leftMouseDown, isEnabled, let action else { return }
        NSApp.sendAction(action, to: target, from: self)
    }
}

// This view owns only presses that began on the visible handle. Other held
// mouse gestures are still rejected by the handle's pointer policy.
private final class SceneAdjustmentDragButton: NSButton {
    var onPress: (() -> Void)?
    var onMove: ((NSPoint) -> Void)?
    var onFinish: ((Bool) -> Void)?
    private var start: NSPoint?
    private var dragged = false
    var isInteracting: Bool { start != nil }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    private func screenPoint(_ event: NSEvent) -> NSPoint {
        window?.convertPoint(toScreen: event.locationInWindow) ?? event.locationInWindow
    }
    override func mouseDown(with event: NSEvent) {
        guard event.type == .leftMouseDown, isEnabled else { return }
        start = screenPoint(event); dragged = false; highlight(true)
        // Hover never activates the app. Only an explicit press takes keyboard
        // focus in this nonactivating panel so Esc can cancel its own gesture.
        window?.makeFirstResponder(self)
        if window?.isVisible == true { window?.makeKey() }
        onPress?()
    }
    private func move(to point: NSPoint) {
        guard let start else { return }
        let delta = NSPoint(x: point.x - start.x, y: point.y - start.y)
        dragged = dragged || hypot(delta.x, delta.y) >= 6
        if dragged { onMove?(delta) }
    }
    override func mouseDragged(with event: NSEvent) { move(to: screenPoint(event)) }
    override func mouseUp(with event: NSEvent) {
        guard start != nil else { return }
        move(to: screenPoint(event))
        let didDrag = dragged
        start = nil; dragged = false; highlight(false)
        onFinish?(false)
        if !didDrag, bounds.contains(convert(event.locationInWindow, from: nil)), let action {
            NSApp.sendAction(action, to: target, from: self)
        }
    }
    func cancelGesture() {
        guard start != nil else { return }
        start = nil; dragged = false; highlight(false)
        onFinish?(true)
    }
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 { cancelGesture() } else { super.keyDown(with:event) }
    }
}
private final class SceneAdjustmentGesturePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// Only the small button owns mouse input; the bridge is a visibility test,
// never an input window. Its position stays fixed from approach to press.
final class SceneAdjustmentHandle: NSObject {
    private(set) var window: NSPanel?
    private(set) var isPresented = false
    var onActivate: (() -> Void)?
    var onPress: (() -> Void)?
    var onMove: ((NSPoint) -> Void)?
    var onMoveEnd: ((Bool) -> Void)?
    private var dragButton: SceneAdjustmentDragButton? { window?.contentView as? SceneAdjustmentDragButton }
    var isInteracting: Bool { dragButton?.isInteracting == true }
    private let present: (NSWindow) -> Void
    init(present: @escaping (NSWindow) -> Void = { $0.orderFrontRegardless() }) {
        self.present = present
        super.init()
        NotificationCenter.default.addObserver(self,selector:#selector(cancelOnFocusLoss),
            name:NSApplication.didResignActiveNotification,object:nil)
    }
    deinit { NotificationCenter.default.removeObserver(self) }
    @objc private func cancelOnFocusLoss(_ notification: Notification) {
        if isInteracting { dismiss() }
    }
    func update(pointer: NSPoint, sceneFrame: NSRect, screens: [NSRect], enabled: Bool, buttonsPressed: Int) {
        // A press acquired by this button survives the ordinary held-button
        // suppression and host's temporary movement bypass. Lifecycle exits
        // call dismiss(), which rolls back the gesture before hiding the panel.
        if isInteracting { return }
        guard enabled, buttonsPressed == 0, let screen = screens.max(by: {
            let a = $0.intersection(sceneFrame), b = $1.intersection(sceneFrame)
            return (a.isNull ? 0 : a.width*a.height) < (b.isNull ? 0 : b.width*b.height)
        }), screen.width >= 32, screen.height >= 32 else { dismiss(); return }
        let size = NSSize(width: 32, height: 32), gap: CGFloat = 6
        let choices = [
            NSRect(x: sceneFrame.midX - 16, y: sceneFrame.maxY + gap, width: size.width, height: size.height),
            NSRect(x: sceneFrame.maxX + gap, y: sceneFrame.midY - 16, width: size.width, height: size.height),
            NSRect(x: sceneFrame.minX - gap - size.width, y: sceneFrame.midY - 16, width: size.width, height: size.height),
            NSRect(x: sceneFrame.midX - 16, y: sceneFrame.minY - gap - size.height, width: size.width, height: size.height)
        ]
        func fitted(_ frame: NSRect) -> NSRect {
            NSRect(x: max(screen.minX, min(frame.minX, screen.maxX - size.width)),
                   y: max(screen.minY, min(frame.minY, screen.maxY - size.height)), width: size.width, height: size.height)
        }
        guard let frame = choices.map(fitted).first(where: { !$0.intersects(sceneFrame) }) else { dismiss(); return }
        let near = sceneFrame.insetBy(dx: -20, dy: -20).contains(pointer)
        let bridge = sceneFrame.union(frame).insetBy(dx: -20, dy: -20)
        guard near || (isPresented && bridge.contains(pointer)) else { dismiss(); return }
        if window == nil {
            let panel = SceneAdjustmentGesturePanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.isReleasedWhenClosed = false; panel.level = .floating
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
            panel.hidesOnDeactivate = false; panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            let button = SceneAdjustmentDragButton(title: "设置", target: self, action: #selector(activate))
            button.frame = NSRect(origin: .zero, size: size); button.bezelStyle = .rounded
            button.image = NSImage(systemSymbolName: "gearshape", accessibilityDescription: "设置")
            button.imagePosition = button.image == nil ? .noImage : .imageOnly
            button.toolTip = "设置 · 可拖动 · Esc 取消"
            button.setAccessibilityIdentifier("scene-adjustment-handle")
            button.setAccessibilityLabel("设置：拖动移动，轻点打开")
            button.onPress = { [weak self] in self?.onPress?() }
            button.onMove = { [weak self] delta in self?.onMove?(delta) }
            button.onFinish = { [weak self] cancelled in self?.onMoveEnd?(cancelled) }
            panel.contentView = button; window = panel
            NotificationCenter.default.addObserver(self,selector:#selector(cancelOnFocusLoss),
                name:NSWindow.didResignKeyNotification,object:panel)
        }
        window?.setFrame(frame, display: false)
        window?.alphaValue = 1; window?.ignoresMouseEvents = false
        if !isPresented, let window { isPresented = true; present(window) }
    }
    @objc private func activate() { dismiss(); onActivate?() }
    func dismiss() {
        dragButton?.cancelGesture()
        window?.orderOut(nil); isPresented = false
    }
}

final class CaptureFeedback: NSObject {
    private(set) var window: NSPanel?
    private(set) var isPresented = false
    private(set) var title = ""
    var onRepeat: (() -> Void)?
    var onCancel: (() -> Void)?
    private let present: (NSWindow) -> Void
    private let heading = NSTextField(labelWithString: "")
    private let detail = NSTextField(labelWithString: "")
    private var again: NSButton!
    private var cancel: NSButton!
    init(present: @escaping (NSWindow) -> Void = { $0.orderFrontRegardless() }) {
        self.present = present; super.init()
    }
    func update(_ state: DesktopCaptureState, progress: Double?, near subject: NSRect, screens: [NSRect]) {
        guard state != .idle, let screen = screens.max(by: {
            $0.intersection(subject).width * $0.intersection(subject).height
                < $1.intersection(subject).width * $1.intersection(subject).height
        }) else { dismiss(); return }
        if window == nil {
            let panel = SceneAdjustmentPanel(contentRect:NSRect(x:0,y:0,width:330,height:76),
                styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
            panel.isReleasedWhenClosed = false; panel.level = NSWindow.Level(rawValue:NSWindow.Level.floating.rawValue+1)
            panel.title = "灶神 · 拉网"
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
            panel.hidesOnDeactivate = false; panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary]
            let surface = NSVisualEffectView(frame:NSRect(x:0,y:0,width:330,height:76))
            surface.material = .popover; surface.state = .active; surface.wantsLayer = true
            surface.layer?.cornerRadius = 12; surface.layer?.masksToBounds = true
            heading.frame = NSRect(x:14,y:44,width:300,height:20); heading.font = .systemFont(ofSize:13,weight:.semibold)
            detail.frame = NSRect(x:14,y:24,width:300,height:16); detail.font = .systemFont(ofSize:11)
            detail.textColor = .secondaryLabelColor
            again = SceneAdjustmentButton(title:"再拉一网",target:self,action:#selector(repeatCapture))
            again.frame = NSRect(x:210,y:4,width:104,height:26); again.bezelStyle = .rounded
            cancel = SceneAdjustmentButton(title:"取消",target:self,action:#selector(cancelCapture))
            cancel.frame = NSRect(x:14,y:3,width:64,height:26); cancel.bezelStyle = .rounded
            for view in [heading,detail,again!,cancel!] { surface.addSubview(view) }
            panel.contentView = surface; window = panel
        }
        switch state {
        case .idle: break
        case .armed: title = "按住左键，拖出红色网框"; detail.stringValue = "在桌面选一块区域 · Esc 取消"
        case .dragging: title = "松手后，蜘蛛开始织网"; detail.stringValue = "网越大，织得越久 · Esc 取消"
        case .weaving:
            title = "织网中 · \(Int(max(0,min(1,progress ?? 0))*100))%"
            detail.stringValue = "已经松手，可继续使用桌面"
        case .completed: title = "织网完成"; detail.stringValue = "再拉一网，或收起提示"
        }
        heading.stringValue = title
        again.isHidden = state != .completed
        cancel.title = state == .completed ? "收起" : "取消"
        let x = max(screen.minX+6,min(subject.minX,screen.maxX-336))
        let above = subject.maxY+10
        let y = above+76 <= screen.maxY-6 ? above : max(screen.minY+6,subject.minY-86)
        window?.setFrameOrigin(NSPoint(x:x,y:y))
        if !isPresented, let window { isPresented = true; present(window) }
    }
    @objc private func repeatCapture() { onRepeat?() }
    @objc private func cancelCapture() { onCancel?() }
    func dismiss() { window?.orderOut(nil); isPresented = false }
}

private final class FortunePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

func currentSignDate(state:[String:Any],now:Date=Date())->String {
    let zone=TimeZone(identifier:state["game_timezone"] as? String ?? "UTC") ?? .gmt
    return now.formatted(Date.ISO8601FormatStyle(timeZone:zone).year().month().day().dateSeparator(.dash))
}

struct DesktopFortuneCard: View {
    @ObservedObject var store:Store
    let close:()->Void
    let retry:()->Void
    var resultDate:String? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var revealed=false
    @State private var selectedDate=""
    var signs:[[String:Any]] { store.rows("signs") }
    var sign:[String:Any]? { signs.first { $0["date"] as? String == (selectedDate.isEmpty ? (resultDate ?? currentSignDate(state:store.state)):selectedDate) } }
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                Text(selectedDate.isEmpty ? "今日签":"签簿").font(.system(size:18,weight:.medium,design:.serif))
                Spacer()
                if !signs.isEmpty {
                    Menu { ForEach(signs,id:\.dateKey) { row in
                        Button(row.dateKey) { selectedDate=row.dateKey }
                    } } label: { Image(systemName:"book.closed") }
                    .menuStyle(.borderlessButton).frame(width:24).help("签簿").accessibilityLabel("签簿")
                }
                Button(action:close) { Image(systemName:"xmark").frame(width:24,height:24) }
                    .buttonStyle(.plain).help("收签").accessibilityLabel("收签")
            }
            if let sign {
                Text((sign["verse"] as? String ?? "").replacingOccurrences(of:"，",with:"，\n")).font(.system(size:21,weight:.medium,design:.serif))
                    .lineSpacing(8).fixedSize(horizontal:false,vertical:true).accessibilityIdentifier("desktop-fortune-verse")
                Rectangle().fill(accent.opacity(0.3)).frame(height:1)
                Text(sign["meaning"] as? String ?? "").font(.system(size:13)).lineSpacing(5)
                    .fixedSize(horizontal:false,vertical:true)
                Text(sign.dateKey+" · 同日同签").font(.system(size:10)).foregroundStyle(.secondary)
            } else {
                Text(store.message.isEmpty ? "暂未取得今日签。":store.message).font(.callout)
                    .fixedSize(horizontal:false,vertical:true)
                Button("再试一次",action:retry).buttonStyle(.bordered)
            }
            Spacer(minLength:0)
        }.padding(20).frame(width:260,height:250,alignment:.topLeading)
            .background(paper,in:RoundedRectangle(cornerRadius:8))
            .overlay(RoundedRectangle(cornerRadius:8).stroke(accent.opacity(0.4),lineWidth:1))
            .foregroundStyle(ink).tint(accent)
            .rotation3DEffect(.degrees(revealed || reduceMotion ? 0:-78),axis:(x:1,y:0,z:0),anchor:.bottom,perspective:0.35)
            .opacity(revealed ? 1:0)
            .onAppear { withAnimation(reduceMotion ? nil:.easeOut(duration:0.24)) { revealed=true } }
            .accessibilityIdentifier("desktop-fortune-card")
    }
}

final class ApplicationHost: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate {
    let store = Store()
    var panel: NSWindow!
    let presentation = PresentationState()
    var outsideMonitor: Any?
    var localMonitor: Any?
    let localObservedEvents: NSEvent.EventTypeMask = [.keyDown, .leftMouseDown, .rightMouseDown, .otherMouseDown]
    var pointerTimer: Timer?
    var ambientContextProvider: (NSPoint, Set<Int>) -> DesktopNaturalCaptureContext? = {
        DesktopNaturalCaptureContext.current(at:$0,excludingWindowNumbers:$1)
    }
    var ambientClock: () -> Double = { ProcessInfo.processInfo.systemUptime }
    private var ambientContextCache: (time:Double, context:DesktopNaturalCaptureContext)?
    var contextMenu: NSMenu!
    var reminderWindow: NSPanel?
    var reminderGeneration = 0
    var overlay: OverlayWindow!
    var scene: TianmuView!
    var statusItem: NSStatusItem!
    var petHidden = false
    var desktopInsectsHidden = false
    private var naturalObservationCounts: [String:Int] = [:]
    private var naturalObservationLastReport: TimeInterval = 0
    var pointerAvoiding = false
    var manualInteraction = false
    var sceneAdjustmentActive = false
    lazy var adjustmentHandle = SceneAdjustmentHandle(present: { [weak self] window in
        if self?.overlay?.isVisible == true { window.orderFrontRegardless() }
    })
    lazy var captureFeedback = CaptureFeedback(present: { [weak self] window in
        if self?.overlay?.isVisible == true { window.orderFrontRegardless() }
    })
    var menuTracking = false
    private var nativeMenuTracking = false
    private var sceneMenuPresented = false
    var sceneMenuWindow: NSPanel?
    var fortuneWindow:NSPanel?
    private var fortuneResultDate:String?
    private(set) var fortuneRequesting=false
    private var fortuneAwaitingReveal=false
    private var fortuneGeneration=0
    var fortuneClock:()->TimeInterval = { ProcessInfo.processInfo.systemUptime }
    var fortuneReduceMotion:()->Bool = { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
    var fortunePresenter:(NSWindow)->Void = { $0.orderFrontRegardless() }
    var scenePopupPresenter: (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true) }
    var animationStart = ProcessInfo.processInfo.systemUptime
    var desktopInsects: DesktopInsects?
    var discoveryNotice = DiscoveryNotice()
    var onboardingGuide = OnboardingGuide()
    private var onboardingPendingStep: String?
    private var onboardingFeedback: (step: String, text: String)?
    private var isSleeping = false
    var overlayPresenter: (NSWindow) -> Void = { $0.orderFrontRegardless() }
    var desktopScreens: () -> [DesktopInsectScreen] = { DesktopInsectScreen.current() }
    var availableScreens: () -> [NSRect] = { NSScreen.screens.map { $0.visibleFrame } }
    var panelPresenter: (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    var captureFocus: (OverlayWindow, TianmuView) -> Void = { window, scene in
        window.makeKeyAndOrderFront(nil); window.makeFirstResponder(scene)
        NSApp.activate(ignoringOtherApps: true)
    }
    var timerPlacementURL: URL?
    var terminateApplication: () -> Void = { NSApp.terminate(nil) }
    lazy var timerTools: TimerToolWindows = {
        let tools = TimerToolWindows(controls: store.timerControls, screens: { [weak self] in self?.availableScreens() ?? [] }, placementURL: timerPlacementURL)
        tools.onExpand = { [weak self] custom in
            self?.openRoute("计时")
            if custom { self?.store.timerControls.prepareEditor(custom: true) }
        }
        return tools
    }()
    var committedPlacement: NSRect?
    var placementScreens: (() -> [NSRect])?
    private var adjustmentStartFrame: NSRect?
    private var adjustmentMoved = false
    func sceneScreens() -> [NSRect] { placementScreens?() ?? availableScreens() }
    var sceneMenuPresenter: ((NSMenu, NSPoint, TianmuView) -> Void)?
    lazy var placement = WindowPlacementStore(url: saveFileURL().appendingPathExtension("window.json"))
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        timerPlacementURL = saveFileURL().appendingPathExtension("timer-window.json")
        placementScreens = { NSScreen.screens.map { scenePlacementScreen(frame:$0.frame,visibleFrame:$0.visibleFrame) } }
        store.atmosphere.configure(storageURL:saveFileURL().appendingPathExtension("weather.json"))
        panel = NSWindow(contentRect: NSRect(x: 150, y: 120, width: 480, height: 580), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        panel.title = "灶神"; panel.isReleasedWhenClosed = false; panel.delegate = self
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.titlebarAppearsTransparent = true
        panel.contentView = NSHostingView(rootView: PanelView(store: store, presentation: presentation, adjust: { [weak self] in self?.adjust($0) }, hide: { [weak self] in self?.hidePet() }, dismiss: { [weak self] in self?.dismissPanel() }, detachTimer: { [weak self] in self?.detachTimer() }, capture: { [weak self] in self?.capture() }, changeRoute: { [weak self] in self?.openRoute($0) }))
        panel.contentMinSize = NSSize(width: 320, height: 400)
        overlay = OverlayWindow(contentRect: placement.restore(screens:sceneScreens()), styleMask: [.borderless], backing: .buffered, defer: false)
        overlay.isOpaque = false; overlay.backgroundColor = .clear; overlay.hasShadow = false; overlay.level = .floating
        overlay.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        overlay.ignoresMouseEvents = true
        scene = TianmuView(frame: overlay.contentView!.bounds); scene.attach(window: overlay); scene.persistLegacyFrame = false; scene.autoresizingMask = [.width, .height]; overlay.contentView = scene
        overlay.setFrame(placement.restore(screens:sceneScreens(),contentBounds:scene.placementUnitBounds),display:false)
        configureGeometry(placement)
        let appearance = SceneTransparencyStore(url: saveFileURL().appendingPathExtension("appearance.json"))
        configureTransparency(appearance)
        desktopInsects = DesktopInsects(screens: desktopScreens())
        configureInsects(appearance)
        configureDiscovery()
        configureOnboarding()
        configureRuntime()
        configureSceneState()
        store.onReminder = { [weak self] in self?.showReminder() }
        store.notifications.onOpenTimer = { [weak self] in self?.openRoute("计时") }
        store.notifications.refresh()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        updateStatusIcon()
        let menu = makeSceneMenu()
        statusItem.button?.target = self
        statusItem.button?.action = #selector(openStatusMenu)
        contextMenu = menu
        configureSceneActions()
        outsideMonitor = NSEvent.addGlobalMonitorForEvents(matching:[.leftMouseDown,.leftMouseDragged,.leftMouseUp,.rightMouseDown,.otherMouseDown]) { [weak self] event in
            _ = self?.handleGlobalEvent(event)
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: localObservedEvents) { [weak self] event in
            guard let self else { return event }
            return self.handleLocalEvent(event)
        }
        pointerTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            guard let self else { return }
            if self.overlay.isVisible {
                self.scene.ceremonyElapsed = self.presentation.ritualElapsed()
                self.refreshFortune()
                self.scene.updateAnimation(elapsed: ProcessInfo.processInfo.systemUptime - self.animationStart)
                self.updatePointer(NSEvent.mouseLocation, buttonsPressed: NSEvent.pressedMouseButtons)
            }
            self.updateInsectPointer(NSEvent.mouseLocation, buttonsPressed: NSEvent.pressedMouseButtons)
            self.desktopInsects?.refresh()
            if let issue=self.desktopInsects?.motionUnavailableReason { self.store.insectStyleError=issue }
            self.refreshCaptureFeedback()
            self.refreshOnboarding()
        }
        RunLoop.main.add(pointerTimer!, forMode: .common)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(sleepNow), name: NSWorkspace.willSleepNotification, object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(wakeNow), name: NSWorkspace.didWakeNotification, object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(desktopSpaceChanged), name: NSWorkspace.activeSpaceDidChangeNotification, object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(desktopApplicationActivated), name: NSWorkspace.didActivateApplicationNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(screensChanged), name: NSApplication.didChangeScreenParametersNotification, object: nil)
        store.start()
        showPet()
    }
    @discardableResult
    func handleGlobalEvent(_ event: NSEvent, context: DesktopNaturalCaptureContext? = nil) -> NSEvent {
        if event.type == .leftMouseDown || event.type == .rightMouseDown || event.type == .otherMouseDown { dismissTransientControls();dismissFortune() }
        guard !desktopInsectsHidden, !isSleeping, store.startupIssue == nil, !manualInteraction else { return event }
        return desktopInsects?.observeNaturalEvent(event,context:context) ?? event
    }
    func handleLocalEvent(_ event: NSEvent) -> NSEvent? {
        _ = desktopInsects?.observeNaturalEvent(event,isLocal:true)
        if event.type == .keyDown && event.keyCode == 53 {
            dismissFortune(cancelPending:true)
            if event.window === sceneMenuWindow, (sceneMenuWindow?.contentView as? SceneDialSurface)?.back() == true { return nil }
            scene.cancelInteraction(); desktopInsects?.cancelCapture(); manualInteraction = false
            dismissTransientControls()
            if event.window === timerTools.detachedWindow { timerTools.dismiss(.detached) }
            return event
        } else if event.type != .keyDown {
            // This monitor runs before the clicked view receives mouseDown.
            // Keep our own independent adjustment button alive until its action.
            let pressesAdjustment = adjustmentHandle.isPresented && event.window === adjustmentHandle.window
            if event.window !== panel && !pressesAdjustment { dismissPanel() }
            if event.window !== sceneMenuWindow && event.window !== statusItem?.button?.window { dismissSceneMenu() }
            if event.window !== timerTools.quickWindow { timerTools.dismissQuick() }
        }
        return event
    }
    func configureSceneState() {
        applySceneState(store.state, to: scene)
        store.onState = { [weak self] state in
            guard let self else { return }
            self.desktopInsects?.update(rows: state["desktop"] as? [[String: Any]] ?? [])
            applySceneState(state, to: self.scene)
            self.refreshOnboarding()
        }
    }
    func savePlacement() {
        let frame = fitOverlayFrame(overlay.frame,screens:sceneScreens(),contentBounds:scene.placementUnitBounds)
        do {
            try placement.save(frame)
            overlay.setFrame(frame, display: true); committedPlacement = frame
            store.sceneScale = sceneScalePercent(frame); store.sceneSizeError = ""
        } catch {
            if let saved = committedPlacement { overlay.setFrame(fitOverlayFrame(saved,screens:sceneScreens(),contentBounds:scene.placementUnitBounds), display: true) }
            store.sceneSizeError = "位置或大小未保存，已保留原设置。"
            store.message = store.sceneSizeError
        }
    }
    func configureGeometry(_ settings: WindowPlacementStore) {
        placement = settings; committedPlacement = overlay.frame
        store.sceneScale = sceneScalePercent(overlay.frame)
        scene.constrainFrame = { [weak self] frame in
            fitOverlayFrame(frame,screens:self?.sceneScreens() ?? [],contentBounds:self?.scene.placementUnitBounds)
        }
        adjustmentHandle.onActivate = { [weak self] in self?.adjustScene() }
        adjustmentHandle.onPress = { [weak self] in
            guard let self else { return }
            self.adjustmentStartFrame = self.overlay.frame; self.adjustmentMoved = false
            self.manualInteraction = true; self.pointerAvoiding = false; self.scene.alphaValue = 1
            self.overlay.ignoresMouseEvents = true
        }
        adjustmentHandle.onMove = { [weak self] delta in
            guard let self, let original = self.adjustmentStartFrame else { return }
            self.adjustmentMoved = true
            let frame = original.offsetBy(dx:delta.x,dy:delta.y)
            self.overlay.setFrame(fitOverlayFrame(frame,screens:self.sceneScreens(),contentBounds:self.scene.placementUnitBounds),display:true)
        }
        adjustmentHandle.onMoveEnd = { [weak self] cancelled in
            guard let self, let original = self.adjustmentStartFrame else { return }
            self.adjustmentStartFrame = nil
            if cancelled { self.overlay.setFrame(original,display:true) }
            else if self.adjustmentMoved { self.savePlacement() }
            self.adjustmentMoved = false; self.manualInteraction = false
            self.updatePointer(NSEvent.mouseLocation,buttonsPressed:0)
        }
        store.onSceneScaleChange = { [weak self] percent in
            guard let self else { return percent }
            let frame = scaledOverlayFrame(self.overlay.frame,percent:percent,screens:self.sceneScreens(),contentBounds:self.scene.placementUnitBounds)
            try settings.save(frame)
            self.overlay.setFrame(frame, display: true); self.committedPlacement = frame
            return sceneScalePercent(frame)
        }
    }
    func makeSceneMenu() -> NSMenu {
        let menu = NSMenu(); menu.delegate = self
        for route in menuRoutes {
            let item = NSMenuItem(title: route, action: #selector(selectRoute(_:)), keyEquivalent: "")
            item.target = self; menu.addItem(item)
        }
        menu.addItem(.separator())
        let size = NSMenuItem(title: "大小", action: nil, keyEquivalent: "")
        size.view = SceneSizeMenuView(store: store); menu.addItem(size)
        menu.addItem(.separator())
        for (title, action) in [("显示", #selector(showPet)), ("退出", #selector(quit))] {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item)
        }
        return menu
    }
    func menuWillOpen(_ menu: NSMenu) {
        dismissSceneMenu()
        nativeMenuTracking = true; menuTracking = true
        adjustmentHandle.dismiss()
        desktopInsects?.cancelCapture()
        for item in menu.items { (item.view as? SceneSizeMenuView)?.sync() }
    }
    func menuDidClose(_ menu: NSMenu) { nativeMenuTracking = false; menuTracking = sceneMenuPresented }
    @objc func selectSceneScale(_ sender: NSMenuItem) {
        guard let percent = sender.representedObject as? Double else { return }
        store.setSceneScale(percent)
    }
    private func sceneMenuPlacement() -> SceneMenuPlacement {
    // Anchor to the displayed shrine layers, not the transparent overlay frame
    // or the attendant's full walking envelope.
    let local = scene.shrineBounds
    let subject = overlay.convertToScreen(scene.convert(local,to:nil))
    let screen = availableScreens().max { a,b in
        let aa = a.intersection(subject), bb = b.intersection(subject)
        return (aa.isNull ? 0:aa.width*aa.height) < (bb.isNull ? 0:bb.width*bb.height)
    } ?? subject.insetBy(dx:-264,dy:-166)
    return SceneSemicircleLayout.placement(near:subject,in:screen)
}

    func openSceneMenu() {
    if let old = contextMenu.item(withTag:901) { contextMenu.removeItem(old) }
    if !store.sceneSizeError.isEmpty {
        let error = NSMenuItem(title:store.sceneSizeError,action:nil,keyEquivalent:"")
        error.tag = 901; error.isEnabled = false; contextMenu.insertItem(error,at:0)
    }
    contextMenu.update()
    if sceneMenuPresenter == nil {
        let placement = sceneMenuPlacement()
        presentSceneMenu(frame:placement.frame,direction:placement.direction)
        return
    }
    // Preserve the native-menu test/compatibility seam. It has its own size
    // and top-left origin semantics, independent of the semicircular panel.
    let size = contextMenu.size, subject = overlay.frame
    let screen = availableScreens().max { a,b in
        a.intersection(subject).width*a.intersection(subject).height
            < b.intersection(subject).width*b.intersection(subject).height
    } ?? subject.insetBy(dx:-size.width,dy:-size.height)
    let gap: CGFloat = 10
    let origins = [
        NSPoint(x:subject.minX,y:subject.maxY+gap),
        NSPoint(x:subject.maxX+gap,y:subject.maxY-size.height),
        NSPoint(x:subject.minX-gap-size.width,y:subject.maxY-size.height),
        NSPoint(x:subject.minX,y:subject.minY-gap-size.height)
    ]
    let candidates = origins.map { origin in
        NSRect(x:max(screen.minX,min(origin.x,screen.maxX-size.width)),
               y:max(screen.minY,min(origin.y,screen.maxY-size.height)),width:size.width,height:size.height)
    }
    let frame = candidates.first { !$0.intersects(subject) } ?? candidates[0]
    let point = scene.convert(overlay.convertPoint(fromScreen:NSPoint(x:frame.minX,y:frame.maxY)),from:nil)
    sceneMenuPresenter?(contextMenu,point,scene)
}
    private func presentSceneMenu(frame: NSRect, direction:SceneMenuDirection = .up) {
        invalidateAmbientContext()
        dismissPanel(); timerTools.dismissQuick(); adjustmentHandle.dismiss(); desktopInsects?.cancelCapture()
        scene.cancelInteraction(); manualInteraction = false; sceneMenuPresented = true; menuTracking = true
        if sceneMenuWindow == nil {
            let window = SceneMenuPanel(contentRect:frame,styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
            window.title = "灶神 · 菜单"; window.isReleasedWhenClosed = false; window.level = .floating
            window.isOpaque = false; window.backgroundColor = .clear; window.hasShadow = false
            window.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary]; window.delegate = self
            sceneMenuWindow = window
        }
        (sceneMenuWindow?.contentView as? SceneDialSurface)?.stopAnimation()
        let surface = SceneDialSurface(store:store,hidden:petHidden,direction:direction)
        surface.onRoute = { [weak self] route in
            guard let self else { return }
            self.dismissSceneMenu()
            if route == "计时" { self.showTimer() } else { self.openRoute(route) }
        }
        surface.onCollectionGroup = { [weak self] group in
            guard let self else { return }
            self.openRoute("装扮");self.store.shopControls.openCategory(group)
        }
        surface.onItem = { [weak self] id in
            guard let self else { return }
            self.openRoute("装扮")
            if let id { self.store.shopControls.choose(id) } else { self.store.shopControls.dismissPreview() }
        }
        surface.onVisibility = { [weak self] in
            guard let self else { return }
            self.dismissSceneMenu(); self.showPet()
        }
        surface.onQuit = { [weak self] in self?.quit() }
        surface.onDismiss = { [weak self] in self?.dismissSceneMenu() }
        sceneMenuWindow?.contentView = surface
        sceneMenuWindow?.acceptsMouseMovedEvents = true
        sceneMenuWindow?.setFrame(frame,display:true)
        if uiDiagnosticsEnabled { fputs("SCENE_MENU_PANEL frame=\(frame)\n",stderr) }
        scenePopupPresenter(sceneMenuWindow!)
        sceneMenuWindow?.makeFirstResponder(surface)
    }
    @objc private func selectSceneButton(_ sender:NSButton) {
        let route=sender.title
        dismissSceneMenu()
        if route == "计时" { showTimer() }
        else { openRoute(route) }
    }
    @objc private func closeSceneMenu() { dismissSceneMenu() }
    @objc private func showFromMenu() { dismissSceneMenu(); showPet() }
    @objc func openStatusMenu() {
    if sceneMenuPresented { dismissSceneMenu(); return }
    guard let button = statusItem?.button, let window = button.window else { openSceneMenu(); return }
    let anchor = window.convertToScreen(button.convert(button.bounds,to:nil))
    let screen = window.screen?.visibleFrame ?? availableScreens().first ?? anchor.insetBy(dx:-264,dy:-166)
    let placement = SceneSemicircleLayout.placement(near:anchor,in:screen,preferred:.down)
    presentSceneMenu(frame:placement.frame,direction:placement.direction)
}
    func dismissSceneMenu() {
        invalidateAmbientContext()
        (sceneMenuWindow?.contentView as? SceneDialSurface)?.stopAnimation()
        sceneMenuWindow?.orderOut(nil); sceneMenuPresented = false; menuTracking = nativeMenuTracking
    }
    func configureSceneActions() {
        scene.emit = { [weak self] event in
            if event["type"] as? String == "capture" { self?.store.send("catch", ["ids": event["ids"] ?? []]) }
            if event["type"] as? String == "window_frame" { self?.savePlacement(); self?.manualInteraction = false }
            if event["type"] as? String == "mode" { self?.manualInteraction = false }
        }
        scene.onSubjectClick = { [weak self] subject in
            if self?.fortuneAwaitingReveal == true { self?.requestFortune();return }
            if subject == "attendant" { self?.scene.respond() }
            self?.openSceneMenu()
        }
        scene.onSubjectMenu = { [weak self] _ in self?.openSceneMenu() }
        scene.onAccessibleMenu = { [weak self] in self?.openSceneMenu() }
    }
    @objc func screensChanged() {
        invalidateAmbientContext()
        dismissSceneMenu()
        adjustmentHandle.dismiss()
        discoveryNotice.dismiss(); onboardingGuide.dismiss()
        scene.cancelInteraction()
        desktopInsects?.updateScreens(desktopScreens())
        savePlacement()
        if panel.isVisible, let screen = overlay.screen?.visibleFrame {
            panel.setFrame(sidebarFrame(near: overlay.frame, screen: screen, route:presentation.route), display: true)
        }
        timerTools.screensChanged(near: overlay.frame)
    }
    func configureInsects(_ settings: SceneTransparencyStore) {
        overlay.delegate = self
        store.availableInsectStyles = desktopInsects?.availableStyles ?? []
        let savedStyle = settings.restoreInsectStyle()
        let restoredStyle = desktopInsects?.setStyle(savedStyle) ?? false
        store.insectStyle = desktopInsects?.style ?? .cute
        if let issue=desktopInsects?.motionUnavailableReason {
            store.insectStyleError=issue
        } else if store.availableInsectStyles.isEmpty {
            store.insectStyleError = "飞虫暂时无法显示。"
        } else if !restoredStyle {
            store.insectStyleError = "所选虫形暂不可用，已显示\(store.insectStyle.title)。"
        } else {
            store.insectStyleError = ""
        }
        store.onInsectStyleChange = { [weak self] style in
            guard let insects = self?.desktopInsects, insects.availableStyles.contains(style) else {
                throw NSError(domain: "Tianmu", code: 4)
            }
            try settings.saveInsectStyle(style)
            _ = insects.setStyle(style)
        }
        store.insectsOnTop = settings.restoreInsectsOnTop()
        desktopInsects?.setLevel(aboveApplications: store.insectsOnTop)
        store.naturalCaptureEnabled = settings.restoreNaturalCapture()
        desktopInsects?.setNaturalCaptureEnabled(store.naturalCaptureEnabled)
        store.onNaturalCaptureChange = { [weak self] enabled in
            try settings.saveNaturalCapture(enabled)
            self?.desktopInsects?.setNaturalCaptureEnabled(enabled)
        }
        desktopInsects?.onCapture = { [weak self] ids in
            self?.store.send("catch", ["ids": ids]) { ok in
                if uiDiagnosticsEnabled { fputs("CAPTURE_RECEIPT ok=\(ok) requested=\(ids.count)\n",stderr) }
            }
        }
        if uiDiagnosticsEnabled {
            desktopInsects?.onNaturalCaptureObservation = { [weak self] observation in
                guard let self else { return }
                self.naturalObservationCounts[observation.rawValue, default:0] += 1
                let now = ProcessInfo.processInfo.systemUptime
                if now-self.naturalObservationLastReport >= 2 || observation == .weavingBegan || observation == .captureSubmitted {
                    self.naturalObservationLastReport = now
                    let counts = self.naturalObservationCounts.keys.sorted().map { "\($0):\(self.naturalObservationCounts[$0]!)" }.joined(separator:",")
                    fputs("NATURAL_CAPTURE \(counts)\n",stderr)
                }
            }
        }
        captureFeedback.onRepeat = { [weak self] in self?.capture() }
        captureFeedback.onCancel = { [weak self] in self?.desktopInsects?.cancelCapture() }
        desktopInsects?.onCaptureStateChange = { [weak self] state in
            self?.refreshCaptureFeedback()
            if uiDiagnosticsEnabled {
                fputs("CAPTURE_STATE \(state.rawValue) hudVisible=\(self?.captureFeedback.window?.isVisible == true)\n",stderr)
            }
        }
        desktopInsects?.onNaturalCaptureBegin = { [weak self] in
            guard let self else { return }
            self.scene.cancelInteraction(); self.dismissTransientControls()
            self.refreshOnboarding()
        }
        store.onInsectLevelChange = { [weak self] enabled in
            try settings.saveInsectsOnTop(enabled)
            self?.desktopInsects?.setLevel(aboveApplications: enabled)
        }
    }
    func configureDiscovery() {
        store.onDiscovery = { [weak self] colors in
            guard let self, !self.petHidden else { return }
            self.discoveryNotice.show(colors: colors, near: self.overlay.frame, screens: self.availableScreens())
        }
    }
    func refreshCaptureFeedback() {
        guard let layer = desktopInsects, !layer.captureIsNatural, let overlay, !petHidden, !isSleeping else { captureFeedback.dismiss(); return }
        captureFeedback.update(layer.captureState, progress:layer.weaveProgress, near:overlay.frame, screens:availableScreens())
    }
    private var runtimeNeedsAttention = false
    func configureRuntime() {
        store.onRuntimeChange = { [weak self] phase in
            guard let self else { return }
            if phase == "ready" {
                if self.runtimeNeedsAttention {
                    self.runtimeNeedsAttention = false; self.dismissPanel(); self.showPet()
                }
            } else if phase == "recovery" || phase == "failed" {
                self.runtimeNeedsAttention = true
                self.onboardingGuide.dismiss(); self.discoveryNotice.dismiss()
                self.timerTools.dismiss(.detached); self.timerTools.dismissQuick()
                self.scene?.cancelInteraction(); self.desktopInsects?.hide()
                self.overlay?.orderOut(nil)
                self.openRoute("设置")
            }
        }
    }
    var onboardingCaptureHintDismissed = false
    func configureOnboarding() {
        onboardingGuide.onAction = { [weak self] in
            guard let self, self.onboardingPendingStep == nil else { return }
            switch self.store.state["onboarding"] as? String {
            case "shrine": self.openRoute("神前")
            case "capture": self.onboardingCaptureHintDismissed = true; self.onboardingGuide.dismiss()
            case "bottle": self.openRoute("虫瓶")
            default: break
            }
        }
        onboardingGuide.onSkip = { [weak self] in self?.saveOnboarding("onboarding_skip") }
    }
    func refreshOnboarding() {
        guard store.startupIssue == nil, !petHidden, !isSleeping, let overlay,
              desktopInsects?.isCapturing != true, desktopInsects?.isWeaving != true,
              let step = store.state["onboarding"] as? String,
              ["shrine", "capture", "bottle"].contains(step),
              !(step == "capture" && onboardingCaptureHintDismissed) else { onboardingGuide.dismiss(); return }
        onboardingGuide.show(step: step, near: overlay.frame, screens: availableScreens())
        onboardingGuide.setBusy(onboardingPendingStep != nil)
        onboardingGuide.showError(onboardingFeedback?.step == step ? onboardingFeedback!.text : "")
    }
    private func saveOnboarding(_ action: String, page: String? = nil) {
        guard onboardingPendingStep == nil, let step = store.state["onboarding"] as? String,
              ["shrine", "capture", "bottle"].contains(step) else { return }
        onboardingPendingStep = step; onboardingFeedback = nil; refreshOnboarding()
        let values: [String: Any] = page.map { ["page": $0] } ?? [:]
        store.send(action, values) { [weak self] ok in
            guard let self else { return }
            self.onboardingPendingStep = nil
            if !ok { self.onboardingFeedback = (step, "进度未保存，请重试。") }
            self.refreshOnboarding()
        }
    }
    private func recordOnboardingVisit(_ route: String) {
        guard canonicalRoute(route) == "求签" || panel.isVisible else { return }
        let step = store.state["onboarding"] as? String
        if (step == "shrine" && canonicalRoute(route) == "求签") || (step == "bottle" && route == "虫瓶") {
            saveOnboarding("onboarding_visit", page: route == "求签" ? "神前" : route)
        }
    }
    func configureTransparency(_ settings: SceneTransparencyStore) {
        store.sceneTransparency = settings.restore()
        store.pointerAvoidance = settings.restoreAvoidance()
        store.exitAction = settings.restoreExitAction()
        store.onExitActionChange = { action in try settings.saveExitAction(action) }
        scene.alphaValue = 1
        store.onTransparencyChange = { [weak self] value in
            try settings.save(value)
            if self?.pointerAvoiding == true { self?.scene.alphaValue = CGFloat(1 - value / 100) }
        }
        store.onPointerAvoidanceChange = { [weak self] enabled in
            try settings.saveAvoidance(enabled)
            if !enabled { self?.pointerAvoiding = false; self?.scene.alphaValue = 1 }
        }
    }
    // Keep the hovered area stable while invisible, preventing opacity flicker.
    func updatePointer(_ screenPoint: NSPoint, buttonsPressed: Int = 0) {
        let point = overlay.convertPoint(fromScreen: screenPoint)
        let pressed = scene.shouldCapturePointer(at: NSPoint(x: -10000, y: -10000))
        let bypass = manualInteraction || sceneAdjustmentActive || menuTracking || pressed || adjustmentHandle.isInteracting
        pointerAvoiding = store.pointerAvoidance && !bypass && overlay.frame.insetBy(dx: -8, dy: -8).contains(screenPoint)
        scene.alphaValue = pointerAvoiding ? CGFloat(1 - store.sceneTransparency / 100) : 1
        overlay.ignoresMouseEvents = adjustmentHandle.isInteracting || pointerAvoiding || !scene.shouldCapturePointer(at: point)
        adjustmentHandle.onActivate = { [weak self] in self?.adjustScene() }
        adjustmentHandle.update(pointer: screenPoint, sceneFrame: scene.placementScreenFrame, screens: sceneScreens(),
            enabled: store.pointerAvoidance && !bypass && !petHidden && !isSleeping && store.startupIssue == nil
                && presentation.route == nil && desktopInsects?.isCapturing != true && desktopInsects?.isWeaving != true,
            buttonsPressed: buttonsPressed)
    }
    func updateInsectPointer(_ screenPoint: NSPoint, buttonsPressed: Int) {
        let enabled = !desktopInsectsHidden && !isSleeping && store.startupIssue == nil
            && desktopInsects?.isCapturing != true && desktopInsects?.isWeaving != true
            && desktopInsects?.hasNaturalGesture != true && buttonsPressed == 0
        desktopInsects?.updateBehaviorPointer(screenPoint,buttonsPressed:buttonsPressed,
            enabled:enabled && ambientDesktopVisible(at:screenPoint))
        // Global monitors observe the original mouse stream; no hover trigger or
        // transparent capture window is made interactive.
        desktopInsects?.updatePointer(screenPoint,buttonsPressed:buttonsPressed,enabled:false)
    }
    func invalidateAmbientContext() {
        ambientContextCache=nil
        desktopInsects?.updateBehaviorPointer(.zero,buttonsPressed:0,enabled:false)
    }
    // This approximation controls animation only, never authorizes capture or
    // supplies an event proof. Known full-screen Dock wallpaper layers are
    // omitted here; ordinary app, widget, Dock and own-panel rectangles remain.
    // Workspace activation/Space notifications invalidate immediately; avoid
    // a synchronous LaunchServices frontmost-app query on every 30 Hz frame.
    func ambientDesktopVisible(at point:NSPoint) -> Bool {
        let now=ambientClock()
        guard now.isFinite, point.x.isFinite, point.y.isFinite else { invalidateAmbientContext(); return false }
        if let cached=ambientContextCache,
           now >= cached.time, now-cached.time < 0.2,
           cached.context.visibleFrame.contains(point) {
            return Self.ambientDesktopVisible(point,context:cached.context)
        }
        guard let context=ambientContextProvider(point,desktopInsects?.contextExcludedWindowNumbers ?? []),
              context.isReliable else { invalidateAmbientContext(); return false }
        ambientContextCache=(now,context)
        return Self.ambientDesktopVisible(point,context:context)
    }
    static func ambientDesktopVisible(_ point:NSPoint,context:DesktopNaturalCaptureContext) -> Bool {
        let sample=NSRect(x:point.x-0.1,y:point.y-0.1,width:0.2,height:0.2)
        guard context.coversDesktopFrame(sample) else { return false }
        return !context.blockedFrames.enumerated().contains { index,frame in
            context.dockBackgrounds[index] == nil && frame.intersects(sample)
        }
    }
    func applicationDidBecomeActive(_ notification: Notification) { store.notifications.refresh() }
    func applicationDidResignActive(_ notification: Notification) {
        dismissSceneMenu()
        manualInteraction = false; sceneAdjustmentActive = false; adjustmentHandle.dismiss()
        scene?.cancelInteraction()
        if desktopInsects?.hasNaturalGesture != true && desktopInsects?.captureState != .armed { desktopInsects?.cancelActiveGesture() }
    }
    @objc func sleepNow() { invalidateAmbientContext(); isSleeping = true; dismissFortune(cancelPending:true); dismissSceneMenu(); sceneAdjustmentActive = false; adjustmentHandle.dismiss(); onboardingGuide.dismiss(); discoveryNotice.dismiss(); scene.cancelInteraction(); desktopInsects?.cancelCapture(); store.send("sleep") }
    @objc func wakeNow() { invalidateAmbientContext(); isSleeping = false; store.send("wake"); refreshOnboarding() }
    @objc func desktopSpaceChanged() { invalidateAmbientContext(); desktopInsects?.cancelForWorkspaceChange() }
    @objc func desktopApplicationActivated() {
        invalidateAmbientContext()
        // App activation does not change an already verified, released selection.
        // DesktopInsects locks its rectangle and candidate IDs at release; new
        // application input cannot extend that set or start another net mid-weave.
    }
    func updateStatusIcon(reminder: Bool = false) {
        statusItem?.button?.title = ""
        statusItem?.button?.image = TianmuBrandArtwork.spider(size:18,template:true,reminder:reminder)
        statusItem?.button?.imagePosition = .imageOnly
        statusItem?.button?.toolTip = reminder ? "灶神 · 计时结束" : "灶神"
        statusItem?.button?.setAccessibilityLabel(reminder ? "灶神，计时结束" : "灶神")
    }
    func showReminder() {
        reminderGeneration += 1
        let generation = reminderGeneration
        updateStatusIcon(reminder:true)
        if reminderWindow == nil {
            let window = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 210, height: 48), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            window.level = .floating; window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: Button("计时结束 · 查看") { [weak self] in
                self?.reminderWindow?.orderOut(nil); self?.openRoute("计时")
            }.buttonStyle(.plain).frame(width: 210, height: 48).background(paper))
            reminderWindow = window
        }
        let screen = overlay.screen?.visibleFrame ?? NSScreen.main!.visibleFrame
        reminderWindow?.setFrameOrigin(NSPoint(x: max(screen.minX, min(overlay.frame.midX - 105, screen.maxX - 210)), y: max(screen.minY, min(overlay.frame.maxY, screen.maxY - 48))))
        reminderWindow?.orderFrontRegardless()
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
            guard let self, generation == self.reminderGeneration else { return }
            self.reminderWindow?.orderOut(nil); self.updateStatusIcon()
        }
    }
    func dismissPanel() {
        invalidateAmbientContext()
        sceneAdjustmentActive = false; adjustmentHandle.dismiss()
        panel?.orderOut(nil); presentation.dismiss(); store.cancelSale()
        store.timerControls.cancelReplacement(from: .sidebar)
    }
    func dismissTransientControls() { dismissSceneMenu(); dismissPanel(); timerTools.dismissQuick() }
    func dismissFortune(cancelPending:Bool=false) {
        fortuneWindow?.orderOut(nil);fortuneWindow=nil
        if cancelPending {
            fortuneGeneration += 1;fortuneRequesting=false;fortuneAwaitingReveal=false
            presentation.skipRitual();scene?.ceremonyElapsed=nil
        }
    }
    func requestFortune() {
        guard store.startupIssue == nil else { openRoute("设置");return }
        guard !isSleeping,!fortuneRequesting else { return }
        if petHidden { showPet() }
        dismissTransientControls();dismissFortune()
        scene.cancelInteraction();desktopInsects?.cancelCapture()
        if fortuneAwaitingReveal {
            fortuneAwaitingReveal=false;presentation.skipRitual();scene.ceremonyElapsed=nil
            recordOnboardingVisit("求签")
            showFortune();return
        }
        let today=currentSignDate(state:store.state)
        fortuneResultDate=today
        if store.rows("signs").contains(where:{$0.dateKey==today}) {
            fortuneAwaitingReveal=false;presentation.skipRitual();scene.ceremonyElapsed=nil
            recordOnboardingVisit("求签")
            showFortune();return
        }
        fortuneRequesting=true;fortuneGeneration += 1
        let generation=fortuneGeneration
        store.send("sign",completion:{ [weak self] ok in
            guard let self,self.fortuneGeneration==generation else { return }
            self.fortuneRequesting=false
            guard ok else { self.showFortune();return }
            self.fortuneResultDate=self.store.state["daily_sign_date"] as? String ?? today
            self.recordOnboardingVisit("求签")
            if self.fortuneReduceMotion() { self.showFortune();return }
            self.fortuneAwaitingReveal=true
            self.presentation.beginRitual(now:self.fortuneClock())
            self.scene.ceremonyElapsed=0
        })
    }
    func refreshFortune() {
        guard fortuneAwaitingReveal,presentation.ritualElapsed(now:fortuneClock()) == nil else { return }
        fortuneAwaitingReveal=false;presentation.skipRitual();scene?.ceremonyElapsed=nil
        if !petHidden { showFortune() }
    }
    func showFortune() {
        guard !isSleeping,!petHidden else { return }
        guard let overlay,let screen=overlay.screen?.visibleFrame ?? availableScreens().first else { return }
        dismissFortune()
        let subject=overlay.convertToScreen(scene.convert(scene.shrineBounds,to:nil))
        let width:CGFloat=260,height:CGFloat=250
        let above=subject.maxY+10
        let y=above+height<=screen.maxY ? above:subject.minY-height-10
        let frame=NSRect(x:min(max(subject.midX-width/2,screen.minX+8),screen.maxX-width-8),
            y:min(max(y,screen.minY+8),screen.maxY-height-8),width:width,height:height)
        let card=FortunePanel(contentRect:frame,styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
        card.title="灶神 · 今日签";card.isReleasedWhenClosed=false;card.isOpaque=false
        card.backgroundColor = .clear;card.hasShadow=true;card.level = .floating
        card.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary]
        card.contentView=NSHostingView(rootView:DesktopFortuneCard(store:store,
            close:{ [weak self] in self?.dismissFortune() },retry:{ [weak self] in self?.requestFortune() },resultDate:fortuneResultDate))
        fortuneWindow=card;fortunePresenter(card)
    }
    func detachTimer() {
        dismissPanel()
        timerTools.showDetached(near: overlay.frame)
    }
    func openRoute(_ requestedRoute: String) {
        dismissSceneMenu()
        let route = store.startupIssue == nil ? canonicalRoute(requestedRoute) : "设置"
        guard menuRoutes.contains(route) else { return }
        if route == "求签" { requestFortune();return }
        dismissFortune(cancelPending:true)
        timerTools.dismissQuick()
        scene.cancelInteraction()
        desktopInsects?.cancelCapture()
        adjustmentHandle.dismiss()
        sceneAdjustmentActive = route == "设置" && store.startupIssue == nil
        if sceneAdjustmentActive { pointerAvoiding = false; scene.alphaValue = 1 }
        if route == "计时" { store.timerControls.prepareEditor() }
        if presentation.route != route { store.message="" }
        store.cancelSale(); presentation.open(route)
        guard let screen = overlay.screen?.visibleFrame ?? availableScreens().first else { return }
        panel.setFrame(sidebarFrame(near: overlay.frame, screen: screen, route:route), display: true)
        panelPresenter(panel)
        recordOnboardingVisit(route)
    }
    @objc func selectRoute(_ sender: NSMenuItem) {
        if sender.title == "计时" { showTimer() }
        else { openRoute(sender.title) }
    }
    @objc func showPanel() { openRoute("神前") }
    @objc func showTimer() {
        guard store.startupIssue == nil else { openRoute("设置"); return }
        dismissFortune(cancelPending:true)
        scene.cancelInteraction(); desktopInsects?.cancelCapture(); dismissPanel()
        timerTools.showQuick(near: overlay.frame)
    }
    func adjust(_ mode: String) {
        guard store.startupIssue == nil else { openRoute("设置"); return }
        dismissFortune(cancelPending:true)
        scene.cancelInteraction(); desktopInsects?.cancelCapture(); dismissTransientControls(); showPet(); manualInteraction = true
        pointerAvoiding = false; scene.alphaValue = 1
        overlay.makeKeyAndOrderFront(nil); overlay.makeFirstResponder(scene)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc func movePet() { adjust("move") }
    @objc func adjustScene() { openRoute("设置") }
    @objc func capture() {
        guard store.startupIssue == nil else { openRoute("设置"); return }
        dismissFortune(cancelPending:true)
        scene.cancelInteraction(); dismissTransientControls()
        showPet()
        desktopInsects?.beginCapture()
        refreshOnboarding()
    }
    @objc func hidePet() { invalidateAmbientContext(); onboardingGuide.dismiss(); discoveryNotice.dismiss(); scene.cancelInteraction(); dismissSceneMenu(); dismissPanel(); dismissFortune(cancelPending:true); sceneAdjustmentActive = false; manualInteraction = false; adjustmentHandle.dismiss(); captureFeedback.dismiss(); petHidden = true; overlay.ignoresMouseEvents = true; overlay.orderOut(nil) }
    func hideDesktopCompanions() { hidePet(); desktopInsectsHidden = true; desktopInsects?.hide() }
    @objc func showPet() { invalidateAmbientContext(); guard store.startupIssue == nil else { openRoute("设置"); return }; petHidden = false; desktopInsectsHidden = false; overlay.ignoresMouseEvents = true; overlayPresenter(overlay); desktopInsects?.show(); refreshOnboarding() }
    func applicationWillTerminate(_ notification: Notification) {
        if let monitor=outsideMonitor { NSEvent.removeMonitor(monitor) }; if let monitor=localMonitor { NSEvent.removeMonitor(monitor) }
        pointerTimer?.invalidate(); dismissFortune(cancelPending:true); adjustmentHandle.dismiss(); captureFeedback.dismiss(); onboardingGuide.dismiss(); discoveryNotice.dismiss(); desktopInsects?.close() }
    @objc func quit() {
        switch store.exitAction {
        case .hideShrine:
            hidePet()
            desktopInsectsHidden = false
            if store.startupIssue == nil && !isSleeping { desktopInsects?.show() }
        case .hideCompanions: hideDesktopCompanions()
        case .quitApplication: terminateApplication()
        }
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard store.process?.isRunning == true, store.runtimePhase != "failed" else { return .terminateNow }
        store.send("quit", completion: { [weak self] ok in
            if !ok { self?.openRoute("设置") }
            NSApp.reply(toApplicationShouldTerminate: ok)
        })
        return .terminateLater
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { dismissPanel(); return false }
    func windowDidResignKey(_ notification: Notification) {
        if notification.object as? NSWindow === sceneMenuWindow { dismissSceneMenu() }
        if notification.object as? NSWindow === panel { dismissPanel() }
        if notification.object as? NSWindow === overlay {
            manualInteraction = false; scene?.cancelInteraction()
            if desktopInsects?.hasNaturalGesture != true && desktopInsects?.captureState != .armed {
                desktopInsects?.cancelActiveGesture()
            }
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

let application = NSApplication.shared
if let directory = argument("--render-panels") {
    application.setActivationPolicy(.prohibited)
    let store = Store()
    store.message = "界面检查 · 隔离样例数据"
    store.state = ["coins": 12, "bottle": ["普通褐色", "中褐色", "深褐色", "白色"].map { ["color": $0, "female": 2, "male": 1, "price": 1] as [String: Any] }]
    for page in menuRoutes.filter({ $0 != "拉网" }) {
        let presentation = PresentationState(); presentation.open(page)
        let view = NSHostingView(rootView: PanelView(store: store, presentation: presentation, adjust: { _ in }, hide: {}, dismiss: {}))
        view.frame = NSRect(x: 0, y: 0, width: 480, height: 580)
        view.layoutSubtreeIfNeeded()
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(2) }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { exit(3) }
        try! data.write(to: URL(fileURLWithPath: directory).appendingPathComponent("\(page).png"))
    }
    exit(0)
}
let host = ApplicationHost()
application.delegate = host
application.run()
