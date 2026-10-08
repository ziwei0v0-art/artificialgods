import Foundation
import Combine

// This service owns only the explicitly configured weather sidecar. Construction and
// configuration never discover a location, request permission, or start networking.
enum WeatherCondition: String, Codable {
    case clear, cloudy, fog, rain, snow, storm, unknown

    static func from(wmo: Int) -> WeatherCondition {
        switch wmo {
        case 0, 1: return .clear
        case 2, 3: return .cloudy
        case 45, 48: return .fog
        case 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82: return .rain
        case 71, 73, 75, 77, 85, 86: return .snow
        case 95, 96, 97, 99: return .storm
        default: return .unknown
        }
    }
}

enum WeatherDayPhase: String { case dawn, day, dusk, night }

private func weatherText(_ value: String, maximum: Int = 120, allowEmpty: Bool = false) -> Bool {
    (allowEmpty || !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) && value.count <= maximum &&
        value.rangeOfCharacter(from: .controlCharacters) == nil &&
        value.rangeOfCharacter(from: .newlines) == nil
}

private func weatherNumber(_ value: Any?) -> Double? {
    guard let number = value as? NSNumber,
          CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite else { return nil }
    return number.doubleValue
}

struct WeatherCity: Codable, Hashable, Identifiable {
    let id: Int
    let name: String
    let admin1: String
    let country: String
    let latitude: Double
    let longitude: Double
    let timezone: String

    var displayName: String { [name, admin1, country].filter { !$0.isEmpty }.joined(separator: " · ") }
    var isValid: Bool {
        id > 0 && weatherText(name) && weatherText(admin1, allowEmpty: true) && weatherText(country) &&
        latitude.isFinite && longitude.isFinite && (-90...90).contains(latitude) &&
        (-180...180).contains(longitude) && timezone.count <= 80 && TimeZone(identifier: timezone) != nil
    }

    init?(geocoding row: [String: Any]) {
        guard let number = weatherNumber(row["id"]), let id = Int(exactly: number),
              let name = row["name"] as? String, let country = row["country"] as? String,
              let latitude = weatherNumber(row["latitude"]), let longitude = weatherNumber(row["longitude"]),
              let timezone = row["timezone"] as? String else { return nil }
        self.id = id; self.name = name; self.country = country
        self.admin1 = row["admin1"] as? String ?? ""
        self.latitude = latitude; self.longitude = longitude; self.timezone = timezone
        if !isValid { return nil }
    }
}

struct WeatherSnapshot: Codable, Equatable {
    let cityID: Int
    let temperatureC: Double
    let weatherCode: Int
    let isDay: Bool
    let windSpeedKmh: Double
    let observedAt: Date
    let fetchedAt: Date

    func isValid(for city: WeatherCity, now: Date) -> Bool {
        cityID == city.id && temperatureC.isFinite && (-100...70).contains(temperatureC) &&
        windSpeedKmh.isFinite && (0...500).contains(windSpeedKmh) &&
        WeatherCondition.from(wmo: weatherCode) != .unknown &&
        observedAt.timeIntervalSince1970.isFinite && fetchedAt.timeIntervalSince1970.isFinite &&
        observedAt <= now.addingTimeInterval(900) && fetchedAt <= now.addingTimeInterval(60) &&
        observedAt <= fetchedAt.addingTimeInterval(900)
    }
}

struct WeatherHTTPResponse {
    let data: Data
    let statusCode: Int
    var retryAfter: TimeInterval? = nil
}

protocol WeatherRequestCancellation: AnyObject { func cancel() }
protocol WeatherTransport {
    @discardableResult
    func load(_ request: URLRequest, completion: @escaping (Result<WeatherHTTPResponse, Error>) -> Void) -> WeatherRequestCancellation
}

private enum WeatherServiceError: Error { case invalidData, oversized, invalidStorage, http(Int) }

final class URLSessionWeatherTransport: WeatherTransport {
    func load(_ request: URLRequest, completion: @escaping (Result<WeatherHTTPResponse, Error>) -> Void) -> WeatherRequestCancellation {
        WeatherNetworkTask(request: request, completion: completion)
    }
}

// The delegate queue is serial. Only cancel() crosses queues, and URLSessionTask.cancel
// is thread safe. Streaming enforces the cap before accumulating an oversized body.
private final class WeatherNetworkTask: NSObject, URLSessionDataDelegate, WeatherRequestCancellation, @unchecked Sendable {
    static let maximumBytes = 262_144
    private var session: URLSession!
    private var task: URLSessionDataTask!
    private var response: HTTPURLResponse?
    private var data = Data()
    private var pendingError: Error?
    private var completed = false
    private let completion: (Result<WeatherHTTPResponse, Error>) -> Void

    init(request: URLRequest, completion: @escaping (Result<WeatherHTTPResponse, Error>) -> Void) {
        self.completion = completion
        super.init()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 8
        configuration.timeoutIntervalForResource = 10
        configuration.waitsForConnectivity = false
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        task = session.dataTask(with: request)
        task.resume()
    }
    func cancel() { task.cancel() }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse else {
            pendingError = WeatherServiceError.invalidData; completionHandler(.cancel); return
        }
        guard response.expectedContentLength <= Int64(Self.maximumBytes) else {
            pendingError = WeatherServiceError.oversized; completionHandler(.cancel); return
        }
        self.response = http
        completionHandler(.allow)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive chunk: Data) {
        guard data.count + chunk.count <= Self.maximumBytes else {
            pendingError = WeatherServiceError.oversized; dataTask.cancel(); return
        }
        data.append(chunk)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard !completed else { return }
        completed = true
        defer { session.finishTasksAndInvalidate() }
        if let failure = pendingError ?? error { completion(.failure(failure)); return }
        guard let response = response else { completion(.failure(WeatherServiceError.invalidData)); return }
        var retry: TimeInterval?
        if let text = response.value(forHTTPHeaderField: "Retry-After") {
            if let seconds = Double(text), seconds.isFinite { retry = max(0, seconds) }
            else {
                let formatter = DateFormatter()
                formatter.locale = Locale(identifier: "en_US_POSIX")
                formatter.timeZone = TimeZone(secondsFromGMT: 0)
                formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss z"
                retry = formatter.date(from: text).map { max(0, $0.timeIntervalSinceNow) }
            }
        }
        completion(.success(WeatherHTTPResponse(data: data, statusCode: response.statusCode, retryAfter: retry)))
    }
}

private struct WeatherSidecar: Codable {
    let version: Int
    let city: WeatherCity?
    let snapshot: WeatherSnapshot?
}

final class WeatherAtmosphereStore: ObservableObject {
    @Published private(set) var selectedCity: WeatherCity?
    @Published private(set) var snapshot: WeatherSnapshot?
    @Published private(set) var candidates: [WeatherCity] = []
    @Published private(set) var searching = false
    @Published private(set) var loading = false
    @Published private(set) var statusText = "未选择城市 · 使用本地日夜"
    @Published private(set) var searchStatusText = ""
    @Published private(set) var persistenceError: String?

    let attributionURL = URL(string: "https://open-meteo.com/")!
    let licenceURL = URL(string: "https://creativecommons.org/licenses/by/4.0/")!
    private let transport: WeatherTransport
    private let now: () -> Date
    private let localHour: () -> Int
    private var storageURL: URL?
    private var searchRequest: WeatherRequestCancellation?
    private var weatherRequest: WeatherRequestCancellation?
    private var searchGeneration = 0
    private var weatherGeneration = 0
    private var nextWeatherAttempt: Date?
    private var weatherRateLimitedUntil: Date?
    private var searchRateLimitedUntil: Date?
    private var failureCount = 0
    private var latestFetchFailed = false
    private var refreshTimer: Timer?

    init(transport: WeatherTransport = URLSessionWeatherTransport(),
         now: @escaping () -> Date = Date.init,
         localHour: @escaping () -> Int = { Calendar.current.component(.hour, from: Date()) }) {
        self.transport = transport; self.now = now; self.localHour = localHour
    }
    deinit { searchRequest?.cancel(); weatherRequest?.cancel(); refreshTimer?.invalidate() }

    var displayName: String { selectedCity?.displayName ?? "未选城市" }
    var dayPhase: WeatherDayPhase {
        switch localHour() {
        case 5..<8: return .dawn
        case 8..<17: return .day
        case 17..<20: return .dusk
        default: return .night
        }
    }
    private var usableSnapshot: WeatherSnapshot? {
        guard let city = selectedCity, let sample = snapshot, sample.isValid(for: city, now: now()),
              now().timeIntervalSince(sample.observedAt) <= 21_600,
              now().timeIntervalSince(sample.fetchedAt) <= 21_600 else { return nil }
        return sample
    }
    var hasCurrentWeather: Bool {
        guard !latestFetchFailed, let sample = usableSnapshot else { return false }
        return now().timeIntervalSince(sample.fetchedAt) < 1_800 && now().timeIntervalSince(sample.observedAt) <= 5_400
    }
    var condition: WeatherCondition {
        hasCurrentWeather ? WeatherCondition.from(wmo: snapshot!.weatherCode) : .unknown
    }
    var isDaylight: Bool {
        hasCurrentWeather ? snapshot!.isDay : dayPhase != .night
    }
    var symbol: String {
        switch condition {
        case .clear: return isDaylight ? "sun.max" : "moon.stars"
        case .cloudy: return "cloud"
        case .fog: return "cloud.fog"
        case .rain: return "cloud.rain"
        case .snow: return "cloud.snow"
        case .storm: return "cloud.bolt.rain"
        case .unknown:
            switch dayPhase {
            case .dawn: return "sunrise"
            case .day: return "sun.max"
            case .dusk: return "sunset"
            case .night: return "moon.stars"
            }
        }
    }
    var temperatureText: String {
        guard let sample = usableSnapshot else { return "—" }
        let value = String(format: "%.0f°", sample.temperatureC)
        return hasCurrentWeather ? value : "上次 " + value
    }

    // Call on the main thread, with a path chosen by the owning host. No defaults.
    func configure(storageURL: URL) {
        invalidateRequests()
        selectedCity = nil; snapshot = nil; candidates = []; persistenceError = nil
        latestFetchFailed = false; nextWeatherAttempt = nil; weatherRateLimitedUntil = nil
        searchRateLimitedUntil = nil; failureCount = 0; searchStatusText = ""
        guard storageURL.isFileURL else {
            self.storageURL = nil; persistenceError = "天气设置路径不可用"; updateStatus(); return
        }
        self.storageURL = storageURL
        guard FileManager.default.fileExists(atPath: storageURL.path) else { updateStatus(); return }
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: storageURL.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.size] as? NSNumber)?.intValue ?? Int.max <= WeatherNetworkTask.maximumBytes else {
                throw WeatherServiceError.invalidStorage
            }
            let data = try Data(contentsOf: storageURL)
            guard data.count <= WeatherNetworkTask.maximumBytes else { throw WeatherServiceError.oversized }
            let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .secondsSince1970
            let saved = try decoder.decode(WeatherSidecar.self, from: data)
            guard saved.version == 1, saved.city?.isValid ?? true else { throw WeatherServiceError.invalidData }
            selectedCity = saved.city
            if let city = saved.city, let cached = saved.snapshot, cached.isValid(for: city, now: now()) {
                snapshot = cached
            }
        } catch { persistenceError = "天气设置无法读取，原文件已保留；可重新选择城市" }
        updateStatus()
    }

    func searchCities(_ query: String) {
        searchGeneration &+= 1
        searchRequest?.cancel(); searchRequest = nil; candidates = []; searching = false
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.count >= 2, weatherText(text, maximum: 100) else {
            searchStatusText = text.isEmpty ? "" : "请输入至少两个字的城市名"; return
        }
        if let until = searchRateLimitedUntil, now() < until { searchStatusText = "城市搜索暂忙，请稍后重试"; return }
        let generation = searchGeneration
        let request = makeRequest(host: "geocoding-api.open-meteo.com", path: "/v1/search",
                                  items: ["name": text, "count": "5", "language": "zh", "format": "json"])
        searching = true; searchStatusText = "搜索中…"
        let token = transport.load(request) { [weak self] result in
            self?.onMain { owner in
                guard owner.searchGeneration == generation else { return }
                owner.searching = false; owner.searchRequest = nil
                do {
                    let response = try result.get()
                    if response.statusCode == 429 { owner.searchRateLimitedUntil = owner.now().addingTimeInterval(owner.retryDelay(response.retryAfter)) }
                    let root = try owner.json(response)
                    let rows = root["results"] as? [[String: Any]] ?? []
                    var seen = Set<Int>()
                    owner.candidates = rows.prefix(100).compactMap(WeatherCity.init(geocoding:)).filter { seen.insert($0.id).inserted }.prefix(5).map { $0 }
                    owner.searchStatusText = owner.candidates.isEmpty ? "没有找到城市，可尝试英文名" : "请选择城市、州／省和国家"
                } catch { owner.searchStatusText = "城市搜索暂不可用，请稍后重试" }
            }
        }
        if searching && generation == searchGeneration { searchRequest = token }
        else { token.cancel() }
    }

    // Only a city from the currently visible search results can be selected.
    func selectCity(_ city: WeatherCity) {
        guard city.isValid, candidates.contains(city) else { return }
        if selectedCity == city { candidates = []; searchStatusText = ""; refreshIfNeeded(); return }
        guard persist(city: city, sample: nil) else { updateStatus(); return }
        invalidateRequests()
        selectedCity = city; snapshot = nil; candidates = []; searchStatusText = ""; latestFetchFailed = false
        failureCount = 0; nextWeatherAttempt = nil; weatherRateLimitedUntil = nil
        updateStatus(); refreshIfNeeded(force: true)
    }

    func disable() {
        guard persist(city: nil, sample: nil) else { updateStatus(); return }
        invalidateRequests()
        selectedCity = nil; snapshot = nil; candidates = []; searchStatusText = ""; latestFetchFailed = false
        nextWeatherAttempt = nil; weatherRateLimitedUntil = nil; failureCount = 0
        updateStatus()
    }

    func refreshIfNeeded(force: Bool = false) {
        updateStatus()
        guard let city = selectedCity, city.isValid, !loading else { return }
        if let until = weatherRateLimitedUntil, now() < until { scheduleRefresh(at: until); return }
        if !force {
            if let until = nextWeatherAttempt, now() < until { scheduleRefresh(at: until); return }
            if hasCurrentWeather, let sample = snapshot {
                scheduleRefresh(at: min(sample.fetchedAt.addingTimeInterval(1_800), sample.observedAt.addingTimeInterval(5_400))); return
            }
        }
        refreshTimer?.invalidate(); refreshTimer = nil
        weatherGeneration &+= 1
        let generation = weatherGeneration
        let request = makeRequest(host: "api.open-meteo.com", path: "/v1/forecast", items: [
            "latitude": String(city.latitude), "longitude": String(city.longitude),
            "current": "temperature_2m,weather_code,is_day,wind_speed_10m", "timezone": "auto",
            "forecast_days": "1", "timeformat": "unixtime", "temperature_unit": "celsius", "wind_speed_unit": "kmh"])
        loading = true; updateStatus()
        let token = transport.load(request) { [weak self] result in
            self?.onMain { owner in
                guard owner.weatherGeneration == generation, owner.selectedCity == city else { return }
                owner.loading = false; owner.weatherRequest = nil
                do {
                    let response = try result.get()
                    if response.statusCode == 429 { owner.weatherRateLimitedUntil = owner.now().addingTimeInterval(owner.retryDelay(response.retryAfter)) }
                    let root = try owner.json(response)
                    let sample = try owner.decodeSnapshot(root, city: city)
                    guard owner.persist(city: city, sample: sample) else {
                        owner.weatherFailure(); return
                    }
                    owner.snapshot = sample; owner.latestFetchFailed = false; owner.failureCount = 0
                    owner.nextWeatherAttempt = nil; owner.weatherRateLimitedUntil = nil
                    owner.updateStatus()
                    owner.scheduleRefresh(at: min(sample.fetchedAt.addingTimeInterval(1_800), sample.observedAt.addingTimeInterval(5_400)))
                } catch { owner.weatherFailure() }
            }
        }
        if loading && generation == weatherGeneration { weatherRequest = token }
        else { token.cancel() }
    }

    private func decodeSnapshot(_ root: [String: Any], city: WeatherCity) throws -> WeatherSnapshot {
        guard let current = root["current"] as? [String: Any],
              let time = weatherNumber(current["time"]), let temperature = weatherNumber(current["temperature_2m"]),
              let rawCode = weatherNumber(current["weather_code"]), let code = Int(exactly: rawCode),
              let day = weatherNumber(current["is_day"]), day == 0 || day == 1,
              let wind = weatherNumber(current["wind_speed_10m"]) else { throw WeatherServiceError.invalidData }
        let sample = WeatherSnapshot(cityID: city.id, temperatureC: temperature, weatherCode: code,
            isDay: day == 1, windSpeedKmh: wind, observedAt: Date(timeIntervalSince1970: time), fetchedAt: now())
        guard sample.isValid(for: city, now: now()), now().timeIntervalSince(sample.observedAt) <= 5_400 else {
            throw WeatherServiceError.invalidData
        }
        return sample
    }

    private func json(_ response: WeatherHTTPResponse) throws -> [String: Any] {
        guard response.statusCode == 200 else { throw WeatherServiceError.http(response.statusCode) }
        guard response.data.count <= WeatherNetworkTask.maximumBytes else { throw WeatherServiceError.oversized }
        guard let root = try JSONSerialization.jsonObject(with: response.data) as? [String: Any],
              root["error"] as? Bool != true else { throw WeatherServiceError.invalidData }
        return root
    }
    private func makeRequest(host: String, path: String, items: [String: String]) -> URLRequest {
        var components = URLComponents(); components.scheme = "https"; components.host = host; components.path = path
        components.queryItems = items.keys.sorted().map { URLQueryItem(name: $0, value: items[$0]) }
        var request = URLRequest(url: components.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 8)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }
    private func persist(city: WeatherCity?, sample: WeatherSnapshot?) -> Bool {
        guard let url = storageURL else { persistenceError = "尚未设置天气保存位置"; return false }
        do {
            if FileManager.default.fileExists(atPath: url.path) {
                let type = try FileManager.default.attributesOfItem(atPath: url.path)[.type] as? FileAttributeType
                guard type == .typeRegular else { throw WeatherServiceError.invalidStorage }
            }
            let encoder = JSONEncoder(); encoder.dateEncodingStrategy = .secondsSince1970; encoder.outputFormatting = .sortedKeys
            let data = try encoder.encode(WeatherSidecar(version: 1, city: city, snapshot: sample))
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            persistenceError = nil; return true
        } catch { persistenceError = "天气设置保存失败，保留原设置"; return false }
    }
    private func weatherFailure() {
        latestFetchFailed = true; failureCount += 1
        let delay: TimeInterval = failureCount == 1 ? 300 : (failureCount == 2 ? 900 : 1_800)
        nextWeatherAttempt = max(now().addingTimeInterval(delay), weatherRateLimitedUntil ?? now())
        updateStatus(); scheduleRefresh(at: nextWeatherAttempt!)
    }
    private func retryDelay(_ delay: TimeInterval?) -> TimeInterval {
        guard let delay = delay, delay.isFinite, delay >= 0 else { return 300 }
        return max(1, delay)
    }
    private func updateStatus() {
        if let error = persistenceError { statusText = error; return }
        guard selectedCity != nil else { statusText = "未选择城市 · 使用本地日夜"; return }
        if let sample = usableSnapshot {
            let formatter = DateFormatter(); formatter.locale = Locale(identifier: "zh_CN")
            formatter.timeZone = TimeZone(identifier: selectedCity!.timezone); formatter.dateFormat = "HH:mm"
            statusText = "\(hasCurrentWeather ? "城市天气" : "上次天气") · \(formatter.string(from: sample.observedAt))"
            if loading { statusText += " · 更新中" }
        } else { statusText = loading ? "正在更新天气…" : "天气暂不可用 · 使用本地日夜" }
    }
    private func scheduleRefresh(at date: Date) {
        refreshTimer?.invalidate()
        guard selectedCity != nil else { return }
        refreshTimer = Timer.scheduledTimer(withTimeInterval: max(1, date.timeIntervalSince(now())), repeats: false) { [weak self] _ in
            self?.refreshIfNeeded()
        }
    }
    private func invalidateRequests() {
        searchGeneration &+= 1; weatherGeneration &+= 1
        searchRequest?.cancel(); weatherRequest?.cancel(); refreshTimer?.invalidate()
        searchRequest = nil; weatherRequest = nil; refreshTimer = nil
        searching = false; loading = false
    }
    private func onMain(_ body: @escaping (WeatherAtmosphereStore) -> Void) {
        if Thread.isMainThread { body(self) }
        else { DispatchQueue.main.async { [weak self] in if let owner = self { body(owner) } } }
    }
}
