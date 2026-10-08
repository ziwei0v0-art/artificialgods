import AppKit
import SwiftUI

func leisureSymbol(_ route: String) -> String {
    ["求签":"sparkles", "神前":"sparkles", "虫瓶":"mug", "装扮":"tshirt",
     "虫谱":"book.closed", "计时":"timer", "设置":"slider.horizontal.3", "调整":"slider.horizontal.3",
     "移动":"arrow.up.and.down.and.arrow.left.and.right", "隐藏":"eye.slash", "显示":"eye", "退出":"power", "收起":"xmark"][route] ?? "circle"
}

struct QuietIconButton: View {
    let title: String
    let symbol: String
    var prominent = false
    let action: () -> Void
    var body: some View {
        Button(action:action) { Image(systemName:symbol).font(.system(size:15,weight:.medium)).frame(width:30,height:28) }
            .buttonStyle(.bordered).tint(prominent ? accent : .secondary)
            .help(title).accessibilityLabel(title)
    }
}

struct WeatherSettingsPanel: View {
    @ObservedObject var weather: WeatherAtmosphereStore
    @State private var query = ""
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            Text("窗外天气").font(.headline)
            HStack {
                TextField("城市",text:$query).textFieldStyle(.roundedBorder).onSubmit { weather.searchCities(query) }
                QuietIconButton(title:"搜索城市",symbol:"magnifyingglass") { weather.searchCities(query) }.disabled(weather.searching)
            }
            if weather.searching { ProgressView().controlSize(.small) }
            if !weather.searchStatusText.isEmpty { Text(weather.searchStatusText).font(.caption).foregroundStyle(.secondary) }
            ForEach(weather.candidates) { city in
                Button { weather.selectCity(city) } label: {
                    Text(city.displayName).frame(maxWidth:.infinity,alignment:.leading)
                }.buttonStyle(.borderless).padding(.vertical,3)
            }
            if weather.selectedCity != nil {
                Text(weather.displayName).font(.callout)
                HStack {
                    Button("更新") { weather.refreshIfNeeded(force:true) }.disabled(weather.loading)
                    Button("仅随昼夜") { weather.disable() }
                }
            }
            if !weather.statusText.isEmpty { Text(weather.statusText).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true) }
            if let error=weather.persistenceError, !error.isEmpty { Text(error).font(.caption).foregroundStyle(.red) }
            Text("按所选城市联动，不读取定位。").font(.caption).foregroundStyle(.secondary)
            Link("天气数据 · Open-Meteo",destination:weather.attributionURL).font(.caption)
            Link("CC BY 4.0 · 按天气类别简化呈现",destination:weather.licenceURL).font(.caption)
            Link("城市资料 · GeoNames",destination:URL(string:"https://www.geonames.org/")!).font(.caption)
        }.padding(18).frame(width:330)
    }
}

struct WeatherBadge: View {
    @ObservedObject var weather: WeatherAtmosphereStore
    @State private var editing = false
    var body: some View {
        HStack(spacing:6) {
            Button { editing.toggle() } label: {
                HStack(spacing:6) {
                    Image(systemName:weather.symbol)
                    Text(weather.selectedCity == nil ? "随昼夜" : "\(weather.displayName)  \(weather.temperatureText)")
                        .lineLimit(1)
                }
            }.buttonStyle(.plain).help("选择城市与天气").accessibilityLabel("选择城市与天气")
                .popover(isPresented:$editing) { WeatherSettingsPanel(weather:weather) }
            Spacer(minLength:6)
            if weather.selectedCity != nil { Link("Open-Meteo",destination:weather.attributionURL).font(.system(size:10)) }
        }.font(.caption).foregroundStyle(.secondary)
    }
}

struct ShrineAtmosphere: View {
    @ObservedObject var weather: WeatherAtmosphereStore
    var time: TimeInterval
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var night: Bool { weather.hasCurrentWeather ? !weather.isDaylight : weather.dayPhase == .night }
    private var dusk: Bool { !weather.hasCurrentWeather && (weather.dayPhase == .dawn || weather.dayPhase == .dusk) }
    var body: some View {
        Canvas { context,size in
            let upper = night ? Color(red:0.21,green:0.29,blue:0.33) : dusk ? Color(red:0.89,green:0.71,blue:0.53) : Color(red:0.83,green:0.88,blue:0.79)
            let lower = night ? Color(red:0.49,green:0.52,blue:0.45) : Color(red:0.95,green:0.91,blue:0.79)
            context.fill(Path(CGRect(origin:.zero,size:size)),with:.linearGradient(Gradient(colors:[upper,lower]),startPoint:.zero,endPoint:CGPoint(x:0,y:size.height)))
            let moon = CGRect(x:size.width-58,y:21,width:24,height:24)
            context.fill(Path(ellipseIn:moon),with:.color((night ? Color(red:0.96,green:0.94,blue:0.77) : .white).opacity(0.65)))
            var ridge = Path(); ridge.move(to:CGPoint(x:0,y:size.height*0.68))
            ridge.addCurve(to:CGPoint(x:size.width,y:size.height*0.60),control1:CGPoint(x:size.width*0.23,y:size.height*0.20),control2:CGPoint(x:size.width*0.62,y:size.height*0.91))
            ridge.addLine(to:CGPoint(x:size.width,y:size.height)); ridge.addLine(to:CGPoint(x:0,y:size.height)); ridge.closeSubpath()
            context.fill(ridge,with:.color(Color(red:0.41,green:0.50,blue:0.40).opacity(0.14)))
            let motion = reduceMotion ? 0 : time
            switch weather.condition {
            case .rain, .storm:
                for index in 0..<20 {
                    let x = CGFloat((index*71)%431)/431*size.width
                    let y = (CGFloat(index*43)+CGFloat(motion*70)).truncatingRemainder(dividingBy:size.height)
                    var drop=Path(); drop.move(to:CGPoint(x:x,y:y)); drop.addLine(to:CGPoint(x:x-3,y:y+11))
                    context.stroke(drop,with:.color(.white.opacity(0.24)),lineWidth:1)
                }
            case .snow:
                for index in 0..<16 {
                    let x = CGFloat((index*89)%431)/431*size.width + CGFloat(sin(motion*0.3+Double(index)))*5
                    let y = (CGFloat(index*53)+CGFloat(motion*12)).truncatingRemainder(dividingBy:size.height)
                    context.fill(Path(ellipseIn:CGRect(x:x,y:y,width:3,height:3)),with:.color(.white.opacity(0.62)))
                }
            case .fog, .cloudy:
                for index in 0..<3 {
                    let x = CGFloat(index)*size.width*0.36-40+CGFloat(sin(motion*0.08+Double(index)))*8
                    context.fill(Path(ellipseIn:CGRect(x:x,y:26+CGFloat(index)*18,width:size.width*0.55,height:26)),with:.color(.white.opacity(weather.condition == .fog ? 0.21 : 0.12)))
                }
            default: break
            }
        }.clipShape(RoundedRectangle(cornerRadius:20)).allowsHitTesting(false).accessibilityHidden(true)
    }
}

struct ShrineCeremonyView: View {
    @ObservedObject var store: Store
    @ObservedObject var presentation: PresentationState
    let request: () -> Void
    var requesting: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    static var paperImage = AttendantArtwork.shared?.propFrame("paper")?.image
    private var hasToday: Bool {
        let zone = TimeZone(identifier:store.state["game_timezone"] as? String ?? "UTC") ?? .gmt
        let today = Date().formatted(Date.ISO8601FormatStyle(timeZone:zone).year().month().day().dateSeparator(.dash))
        return store.rows("signs").contains { $0["date"] as? String == today }
    }
    var body: some View {
        TimelineView(.animation(minimumInterval:reduceMotion ? 1 : 1.0/30)) { _ in
            let elapsed = presentation.ritualElapsed()
            let active = elapsed != nil
            let t = elapsed ?? 0
            let shake = max(0,min(1,(t-7)/0.5))*max(0,min(1,(10-t)/0.5))
            let lift = max(0,min(1,(t-10)/1.5))
            let settle = lift*lift*(3-2*lift)
            ZStack(alignment:.bottom) {
                if active && t >= 10, let image = Self.paperImage {
                    Image(nsImage:image).resizable().interpolation(.none).scaledToFit()
                        .frame(width:31,height:70)
                        .rotationEffect(.degrees(8*settle))
                        .offset(x:38*settle,y:-55-75*settle)
                        .opacity(min(1,lift*4)).allowsHitTesting(false).accessibilityHidden(true)
                }
                Button { if !requesting && !active { request() } } label: {
                    Group {
                        if let image = UIArtifactLibrary.shared.image("divination-vessel") {
                            Image(nsImage:image).resizable().interpolation(.none).scaledToFit()
                        } else {
                            Image(systemName:"rectangle.stack").resizable().scaledToFit().padding(22)
                        }
                    }.frame(width:108,height:162)
                        .rotationEffect(.degrees(!reduceMotion ? sin((t-7)*15)*5*shake : 0),anchor:.bottom)
                }.buttonStyle(.plain).allowsHitTesting(!requesting && !active)
                    .help(hasToday ? "查看今日签" : "上香，求一支今日签")
                    .accessibilityLabel(hasToday ? "查看今日签" : "求今日签")
                    .accessibilityHint("轻点一次，仪式自然演完；今日已求则直接查看")
                    .accessibilityValue(requesting ? "请求中" : (active ? "仪式中" : "可点按"))
                    .accessibilityIdentifier("shrine-draw")
                    .padding(.bottom,26)
                Text(active ? (t < 7 ? "香起，心定" : t < 13 ? "静候一签" : "今日有寄") : (hasToday ? "今日签" : "轻点上香求签"))
                    .font(.system(size:12,design:.serif)).foregroundStyle(.secondary)
                    .padding(.bottom,3).allowsHitTesting(false)
            }.frame(maxWidth:.infinity).frame(height:204)
                .overlay(alignment:.bottomLeading) {
                    if requesting {
                        ProgressView().controlSize(.small).padding(6)
                            .accessibilityLabel("正在求签")
                    }
                }
                .overlay(alignment:.bottomTrailing) {
                    if active {
                        QuietIconButton(title:"直接看签",symbol:"forward.end") { presentation.skipRitual() }
                    }
                }
        }
    }
}

struct TimerDialView: View {
    let snapshot: [String:Any]
    var size: CGFloat = 265
    var body: some View {
        TimelineView(.periodic(from:.now,by:1)) { context in
            let readout = snapshot[snapshot["mode"] as? String == "clock" ? "clock_readout" : "readout"] as? String ?? "--:--"
            let lines = readout.components(separatedBy:"\n")
            ZStack {
                if let image=UIArtifactLibrary.shared.image("timer-dial") {
                    Image(nsImage:image).resizable().interpolation(.none).scaledToFit().frame(width:size,height:size*1.265)
                }
                VStack(spacing:5) {
                    Text(lines.first ?? "--:--").font(.system(size:size*0.105,weight:.medium,design:.rounded)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.6)
                    if lines.count>1 { Text(lines.dropFirst().joined(separator:" ")).font(.system(size:11)).foregroundStyle(.secondary) }
                }.frame(width:size*0.60).offset(y:-size*0.105)
                Circle().trim(from:0,to:TimerVisualProgress(snapshot:snapshot,now:context.date.timeIntervalSince1970).fraction)
                    .stroke(accent.opacity(0.8),style:StrokeStyle(lineWidth:3,lineCap:.round))
                    .frame(width:size*0.64,height:size*0.64).rotationEffect(.degrees(-90)).offset(y:-size*0.105)
                    .accessibilityHidden(true)
            }.frame(width:size,height:size*1.265).accessibilityElement(children:.ignore).accessibilityLabel(readout)
        }
    }
}

// MARK: - Compact collection
// These are display projections only. Ownership, discovery and all transactions
// remain in the backend snapshot and the existing ShopControls.
struct CollectionInsectEntry: Identifiable {
    let id: String
    let found: Bool
    private let date: String?
    private let description: String
    static let colors = ["普通褐色", "中褐色", "深褐色", "白色"]

    var discoveryText: String {
        found ? "首次发现 · \(date ?? "旧存档未记录")" : "尚未发现"
    }
    var explanation: String { found ? description : "捕获这种体色后，再来看看。" }
    static func entries(snapshot: [String:Any]) -> [CollectionInsectEntry] {
        var seen = Set<String>()
        return (snapshot["discoveries"] as? [[String:Any]] ?? []).compactMap { row in
            guard let color = row["color"] as? String, colors.contains(color), seen.insert(color).inserted else { return nil }
            let date = (row["date"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            return CollectionInsectEntry(id:color, found:row["found"] as? Bool == true,
                date:date, description:row["description"] as? String ?? "")
        }
    }
}

/// Crops and composes the actual scene layers without modifying their sources.
/// No generic icon is substituted when a production appearance is unavailable.
final class CollectionArtwork {
    static let shared = CollectionArtwork(shrineArtwork:ShrineArtwork.shared)
    private let shrineArtwork: ShrineArtwork?
    private var imageCache: [String:NSImage] = [:]
    init(shrineArtwork: ShrineArtwork?) { self.shrineArtwork = shrineArtwork }

    func layers(for itemID: String) -> [ShrineArtwork.Layer] {
        guard let shrineArtwork, itemID == "shrine_g0" || shrineArtwork.availableAppearanceIDs.contains(itemID) else { return [] }
        let layerIDs: Set<String>
        switch itemID {
        case "shrine_g0", "shrine_g1", "shrine_g2": layerIDs = ["shrine", "idol"]
        case "offering_plate": layerIDs = ["fruit"]
        case "incense_burner": layerIDs = ["incense"]
        case "bell": layerIDs = ["bell"]
        default: return []
        }
        return shrineArtwork.resolve(appearance:SceneAppearance().previewing(itemID:itemID),fruitStage:"fresh")
            .layers.filter { layerIDs.contains($0.id) }
    }

    func image(for itemID: String) -> NSImage? {
        if let cached = imageCache[itemID] { return cached }
        guard let image = compose(layers: layers(for: itemID)) else { return nil }
        imageCache[itemID] = image
        return image
    }

    // Category cards reflect the equipped scene, including the unpurchased base layers.
    func currentImage(for category: String, snapshot: [String: Any]) -> NSImage? {
        guard let shrineArtwork, ["神龛", "供具"].contains(category) else { return nil }
        let appearance = SceneAppearance(snapshot: snapshot)
        let key = "current-" + category + "-" + SceneAppearance.slots.map { appearance.itemID(in: $0) ?? "base" }.joined(separator: "-")
        if let cached = imageCache[key] { return cached }
        let ids: Set<String> = category == "神龛" ? ["shrine", "idol"] : ["fruit", "incense", "bell"]
        let layers = shrineArtwork.resolve(appearance: appearance, fruitStage: "fresh").layers.filter { ids.contains($0.id) }
        guard let image = compose(layers: layers) else { return nil }
        imageCache[key] = image
        return image
    }

    private func compose(layers: [ShrineArtwork.Layer]) -> NSImage? {
        guard !layers.isEmpty else { return nil }
        let source = layers.reduce(NSRect.null) { $0.union($1.bounds) }
        let size = NSSize(width:144,height:128), pixels = 2
        guard let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(size.width)*pixels,
            pixelsHigh:Int(size.height)*pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,
            isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0),
            let graphics = NSGraphicsContext(bitmapImageRep:bitmap) else { return nil }
        let context = graphics.cgContext
        context.translateBy(x:0,y:CGFloat(bitmap.pixelsHigh)); context.scaleBy(x:2,y:-2)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext:context,flipped:true)
        let target = NSRect(origin:.zero,size:size).insetBy(dx:8,dy:8)
        let scale = min(target.width/source.width,target.height/source.height)
        for layer in layers {
            let rect = NSRect(x:target.midX + (layer.bounds.minX-source.midX)*scale,
                y:target.midY + (layer.bounds.minY-source.midY)*scale,
                width:layer.bounds.width*scale,height:layer.bounds.height*scale)
            layer.frame.draw(in:rect,mirrored:false)
        }
        NSGraphicsContext.restoreGraphicsState()
        guard let cgImage = bitmap.cgImage else { return nil }
        let image = NSImage(cgImage:cgImage,size:size)
        return image
    }

    private static let insects: [String:NSImage] = Dictionary(uniqueKeysWithValues:CollectionInsectEntry.colors.compactMap { color in
        // The same dorsal renderer as the desktop, at enough pixels for the
        // expanded card; the 48 px source-comparison sample would blur here.
        guard let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:256,pixelsHigh:256,
            bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,
            bytesPerRow:0,bitsPerPixel:0), let graphics = NSGraphicsContext(bitmapImageRep:bitmap) else { return nil }
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = graphics
        graphics.cgContext.scaleBy(x:256/24,y:256/24)
        FlyParadiseArtwork.shared.draw(at:NSPoint(x:12,y:12),color:color,sex:"F",heading:.pi/2,
            motion:.flying,now:0,seed:0,scale:1.1)
        NSGraphicsContext.restoreGraphicsState()
        guard let image = bitmap.cgImage else { return nil }
        return (color,NSImage(cgImage:image,size:NSSize(width:24,height:24)))
    })
    static func insectImage(color: String) -> NSImage? { insects[color] }
}

private struct CollectionItemCard: View {
    let item: [String:Any]
    let selected: Bool
    let placed: Bool
    let action: () -> Void
    @State private var hovering = false
    private var name: String { item["name"] as? String ?? item.itemKey }
    private var status: String {
        placed ? "已摆上" : item["owned"] as? Bool == true ? "已拥有" : "\(item["price"] as? Int ?? 0) 铜钱"
    }
    var body: some View {
        Button(action:action) {
            ZStack(alignment:.topTrailing) {
                Group {
                    if let image = CollectionArtwork.shared.image(for:item.itemKey) {
                        Image(nsImage:image).resizable().interpolation(.none).scaledToFit()
                            .scaleEffect(hovering ? 1.06 : 1)
                    } else { Text("外观暂不可用").font(.caption).foregroundStyle(.secondary) }
                }.frame(maxWidth:.infinity).frame(height:80).padding(8)
                if placed { Circle().fill(accent).frame(width:6,height:6).padding(7).accessibilityHidden(true) }
            }
            .background(selected ? accent.opacity(0.14) : Color.white.opacity(0.56))
            .clipShape(RoundedRectangle(cornerRadius:12))
            .overlay { RoundedRectangle(cornerRadius:12).strokeBorder(accent.opacity(selected ? 0.65 : hovering ? 0.3 : 0.10),lineWidth:1) }
            .contentShape(RoundedRectangle(cornerRadius:12))
        }.buttonStyle(.plain).onHover { hovering = $0 }
            .help("\(name) · \(status)").accessibilityLabel("\(name)，\(status)")
            .accessibilityHint("查看外观与购买或摆放选项")
    }
}

private struct CollectionInsectCard: View {
    let entry: CollectionInsectEntry
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false
    var body: some View {
        Button(action:action) {
            ZStack(alignment:.topTrailing) {
                CollectionInsectImage(entry:entry).frame(width:54,height:54)
                    .scaleEffect(hovering ? 1.15 : 1).frame(maxWidth:.infinity).frame(height:80)
                if !entry.found {
                    Image(systemName:"lock.fill").font(.system(size:9)).foregroundStyle(.secondary.opacity(0.6))
                        .padding(7).accessibilityHidden(true)
                }
            }.background(selected ? accent.opacity(0.14) : Color.white.opacity(0.56))
                .clipShape(RoundedRectangle(cornerRadius:12))
                .overlay { RoundedRectangle(cornerRadius:12).strokeBorder(accent.opacity(selected ? 0.65 : hovering ? 0.3 : 0.10),lineWidth:1) }
                .contentShape(RoundedRectangle(cornerRadius:12))
        }.buttonStyle(.plain).onHover { hovering = $0 }
            .help("\(entry.id) · \(entry.discoveryText)")
            .accessibilityLabel("\(entry.id)，\(entry.discoveryText)").accessibilityHint("放大查看虫谱")
    }
}

private struct CollectionInsectImage: View {
    let entry: CollectionInsectEntry
    var body: some View {
        if let image = CollectionArtwork.insectImage(color:entry.id) {
            Image(nsImage:image).resizable().renderingMode(entry.found ? .original : .template)
                .interpolation(.high).scaledToFit().foregroundStyle(ink.opacity(0.24))
        }
    }
}

private struct CollectionItemDetail: View {
    @ObservedObject var store: Store
    @ObservedObject var controls: ShopControls
    @State private var showingPlacement = false
    var body: some View {
        VStack(alignment:.leading,spacing:10) {
            HStack {
                Text(controls.selected["name"] as? String ?? "").font(.headline)
                Spacer()
                QuietIconButton(title:"收起外观",symbol:"xmark") { controls.dismissPreview() }.disabled(controls.isSubmitting)
            }
            if showingPlacement {
                ScenePreview(store:store,appearanceOverride:controls.previewAppearance,staticAppearancePreview:true)
                    .frame(width:296,height:152).frame(maxWidth:.infinity).allowsHitTesting(false).accessibilityHidden(true)
            } else if let id = controls.selectedID, let image = CollectionArtwork.shared.image(for:id) {
                Image(nsImage:image).resizable().interpolation(.none).scaledToFit()
                    .frame(height:152).frame(maxWidth:.infinity).accessibilityHidden(true)
            }
            HStack {
                Button(showingPlacement ? "看物件" : "看摆放") { showingPlacement.toggle() }.disabled(!controls.selectedArtworkAvailable)
                Spacer()
                if controls.selectedOwned {
                    Button(controls.placementActionTitle) { controls.placeSelected() }
                        .disabled(!controls.canPlaceSelected).accessibilityIdentifier("collection-place")
                } else {
                    Button("购买 · \(controls.selected["price"] as? Int ?? 0) 铜钱") { controls.buySelected() }
                        .disabled(!controls.canBuySelected).accessibilityIdentifier("collection-buy")
                }
            }
            HStack(alignment:.top) {
                if let reason = controls.unavailableReason { Text(reason).fixedSize(horizontal:false,vertical:true) }
                Spacer(minLength:8)
                Text("现有 \(store.coins) 铜钱")
            }.font(.caption).foregroundStyle(.secondary)
        }.padding(12).background(Color.white.opacity(0.62)).clipShape(RoundedRectangle(cornerRadius:14))
            .onChange(of:controls.selectedID) { _ in showingPlacement = false }
    }
}

private struct CollectionGroupCard: View {
    let title: String
    let summary: String
    let image: NSImage?
    let action: () -> Void
    @State private var hovering = false
    var body: some View {
        Button(action:action) {
            VStack(alignment:.leading,spacing:5) {
                Group {
                    if let image {
                        Image(nsImage:image).resizable().interpolation(.none).scaledToFit()
                    } else { Text("外观暂不可用").font(.caption).foregroundStyle(.secondary) }
                }.frame(maxWidth:.infinity).frame(height:88)
                HStack {
                    Text(title).font(.headline)
                    Spacer()
                    Image(systemName:"chevron.right").font(.caption).foregroundStyle(.secondary)
                }
                Text(summary).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    .frame(height:30,alignment:.topLeading)
            }.padding(10).frame(maxWidth:.infinity,alignment:.leading)
                .background(Color.white.opacity(hovering ? 0.78 : 0.56))
                .clipShape(RoundedRectangle(cornerRadius:12))
                .overlay { RoundedRectangle(cornerRadius:12).strokeBorder(accent.opacity(hovering ? 0.30 : 0.10),lineWidth:1) }
                .contentShape(RoundedRectangle(cornerRadius:12))
        }.buttonStyle(.plain).onHover { hovering = $0 }
            .help("\(title) · 当前：\(summary)")
            .accessibilityLabel("\(title)，当前：\(summary)")
            .accessibilityHint("进入类别，查看与切换外观")
    }
}

struct CollectionPage: View {
    @ObservedObject var store: Store
    @ObservedObject private var controls: ShopControls
    let initialSection: String?
    @State private var selectedInsect: String?
    private let itemColumns = Array(repeating:GridItem(.flexible(minimum:80),spacing:8),count:3)
    private let groupColumns = Array(repeating:GridItem(.flexible(minimum:120),spacing:8),count:2)
    private let insectColumns = Array(repeating:GridItem(.flexible(minimum:60),spacing:8),count:4)
    init(store: Store, initialSection: String? = nil) {
        self.store = store; self.controls = store.shopControls; self.initialSection = initialSection
    }
    private var insects: [CollectionInsectEntry] { CollectionInsectEntry.entries(snapshot:store.state) }
    var body: some View {
        ScrollViewReader { scroll in
            VStack(alignment:.leading,spacing:12) {
                HStack {
                    if controls.showingCategory {
                        QuietIconButton(title:"返回装扮",symbol:"chevron.left") { controls.showCollectionRoot() }
                            .disabled(controls.isSubmitting).accessibilityIdentifier("collection-back")
                    }
                    Text(controls.showingCategory ? controls.category : "装扮")
                        .font(.system(size:13,weight:.medium)).foregroundStyle(.secondary)
                    Spacer()
                }.id("collection-items")
                if controls.showingCategory {
                    LazyVGrid(columns:itemColumns,spacing:8) {
                        ForEach(controls.items,id:\.itemKey) { item in
                            CollectionItemCard(item:item,selected:controls.selectedID == item.itemKey,
                                placed:SceneAppearance(snapshot:store.state).itemID(in:item["slot"] as? String ?? "") == item.itemKey) {
                                selectedInsect = nil
                                if controls.selectedID == item.itemKey { controls.dismissPreview() }
                                else { controls.choose(item.itemKey) }
                            }.disabled(controls.isSubmitting).accessibilityIdentifier("collection-item-\(item.itemKey)")
                        }
                    }
                    if controls.selectedID != nil {
                        CollectionItemDetail(store:store,controls:controls).id("collection-item-detail")
                    }
                } else {
                    LazyVGrid(columns:groupColumns,spacing:8) {
                        ForEach(ShopControls.categories,id:\.self) { group in
                            CollectionGroupCard(title:group,
                                summary:group == "神龛" ? controls.currentShrineName : controls.currentUtensilsName,
                                image:CollectionArtwork.shared.currentImage(for:group,snapshot:store.state)) {
                                selectedInsect = nil; controls.openCategory(group)
                            }.disabled(controls.isSubmitting).accessibilityIdentifier("collection-group-\(group)")
                        }
                    }
                }
                Text("虫谱").font(.system(size:13,weight:.medium)).foregroundStyle(.secondary)
                    .padding(.top,6).id("collection-insects")
                LazyVGrid(columns:insectColumns,spacing:8) {
                    ForEach(insects) { entry in
                        CollectionInsectCard(entry:entry,selected:selectedInsect == entry.id) {
                            controls.dismissPreview()
                            selectedInsect = selectedInsect == entry.id ? nil : entry.id
                        }.disabled(controls.isSubmitting).accessibilityIdentifier("collection-insect-\(entry.id)")
                    }
                }
                if let entry = insects.first(where: { $0.id == selectedInsect }) {
                    VStack(alignment:.leading,spacing:10) {
                        HStack {
                            Text(entry.id).font(.headline)
                            Spacer()
                            QuietIconButton(title:"收起虫谱",symbol:"xmark") { selectedInsect = nil }
                        }
                        CollectionInsectImage(entry:entry).frame(width:112,height:112).frame(maxWidth:.infinity).accessibilityHidden(true)
                        Text(entry.discoveryText).font(.caption).foregroundStyle(.secondary)
                        Text(entry.explanation).font(.callout).fixedSize(horizontal:false,vertical:true)
                        if entry.found {
                            Text("本作采用简化体色遗传规则。").font(.caption).foregroundStyle(.secondary)
                        }
                    }.padding(12).background(Color.white.opacity(0.62)).clipShape(RoundedRectangle(cornerRadius:14))
                        .id("collection-insect-detail")
                }
            }.frame(maxWidth:.infinity,alignment:.leading)
                .onAppear {
                    if initialSection == "虫谱" { scroll.scrollTo("collection-insects",anchor:.top) }
                }
                .onChange(of:controls.showingCategory) { _ in
                    selectedInsect = nil
                    DispatchQueue.main.async { scroll.scrollTo("collection-items",anchor:.top) }
                }
                .onChange(of:controls.selectedID) { id in
                    if id != nil { DispatchQueue.main.async { scroll.scrollTo("collection-item-detail",anchor:.bottom) } }
                }
                .onChange(of:selectedInsect) { id in
                    if id != nil { DispatchQueue.main.async { scroll.scrollTo("collection-insect-detail",anchor:.bottom) } }
                }
                .onChange(of:insects.map(\.id)) { ids in
                    if let selectedInsect, !ids.contains(selectedInsect) { self.selectedInsect = nil }
                }
                .onDisappear { controls.showCollectionRoot(); selectedInsect = nil }
        }
    }
}
