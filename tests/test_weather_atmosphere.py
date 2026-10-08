"""Weather service contract: injected HTTP, temporary sidecars, no location or app launch."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import Foundation
import Combine

final class RequestToken: WeatherRequestCancellation {
    var cancelled = false
    func cancel() { cancelled = true }
}
final class RecordingWeatherTransport: WeatherTransport {
    struct Call { let request: URLRequest; let token: RequestToken; let done: (Result<WeatherHTTPResponse, Error>) -> Void }
    var calls: [Call] = []
    func load(_ request: URLRequest, completion: @escaping (Result<WeatherHTTPResponse, Error>) -> Void) -> WeatherRequestCancellation {
        let token = RequestToken()
        calls.append(Call(request: request, token: token, done: completion))
        return token
    }
    func reply(_ index: Int, _ value: [String: Any], status: Int = 200, retryAfter: TimeInterval? = nil) {
        calls[index].done(.success(WeatherHTTPResponse(data: try! JSONSerialization.data(withJSONObject: value), statusCode: status, retryAfter: retryAfter)))
    }
}
let fm = FileManager.default
let folder = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let sidecar = folder.appendingPathComponent("test.weather.json")
let transport = RecordingWeatherTransport()
var clock = Date(timeIntervalSince1970: 1_790_000_000)
var hour = 6
let store = WeatherAtmosphereStore(transport: transport, now: { clock }, localHour: { hour })
let berlin: [String: Any] = ["id":2950159,"name":"柏林","country":"德国","country_code":"DE","admin1":"柏林","latitude":52.52437,"longitude":13.41053,"timezone":"Europe/Berlin"]
let other: [String: Any] = ["id":5083330,"name":"柏林","country":"美国","country_code":"US","admin1":"新罕布什尔州","latitude":44.46867,"longitude":-71.18508,"timezone":"America/New_York"]
func weather(_ code: Int = 61, temperature: Double = 12, time: Double? = nil) -> [String: Any] {
    ["latitude":52.52,"longitude":13.41,"timezone":"Europe/Berlin","utc_offset_seconds":7200,
     "current_units":["time":"unixtime","temperature_2m":"°C","weather_code":"wmo code","is_day":"","wind_speed_10m":"km/h"],
     "current":["time":time ?? clock.timeIntervalSince1970,"interval":900,"temperature_2m":temperature,"weather_code":code,"is_day":1,"wind_speed_10m":8.5]]
}
func search(_ entries: [[String: Any]] = [berlin, other]) {
    store.searchCities("Berlin")
    transport.reply(transport.calls.count - 1, ["results":entries])
}
func chooseFirst() {
    search(); store.selectCity(store.candidates[0])
}
switch CommandLine.arguments[1] {
case "consent":
    assert(transport.calls.isEmpty && store.selectedCity == nil && store.condition == .unknown)
    assert(store.dayPhase == .dawn && store.temperatureText == "—")
    hour = 12; assert(store.dayPhase == .day)
    hour = 18; assert(store.dayPhase == .dusk)
    hour = 23; assert(store.dayPhase == .night)
    store.configure(storageURL: sidecar); store.refreshIfNeeded(force: true)
    assert(transport.calls.isEmpty && !fm.fileExists(atPath: sidecar.path))
    store.searchCities(" "); store.searchCities("北")
    assert(transport.calls.isEmpty && store.candidates.isEmpty)
    search()
    assert(store.selectedCity == nil && store.candidates.count == 2 && !fm.fileExists(atPath: sidecar.path))
    assert(store.candidates[0].displayName == "柏林 · 柏林 · 德国")
    assert(store.candidates[1].displayName == "柏林 · 新罕布什尔州 · 美国")
    store.selectCity(store.candidates[1])
    assert(store.selectedCity?.id == 5083330 && fm.fileExists(atPath: sidecar.path))
    let query = URLComponents(url: transport.calls.last!.request.url!, resolvingAgainstBaseURL: false)!.queryItems!
    let values = Dictionary(uniqueKeysWithValues: query.map { ($0.name, $0.value ?? "") })
    assert(values["latitude"] == "44.46867" && values["longitude"] == "-71.18508")
    assert(values["current"] == "temperature_2m,weather_code,is_day,wind_speed_10m")
    assert(values["timeformat"] == "unixtime" && values["apikey"] == nil)
    assert(transport.calls.last!.request.timeoutInterval == 8)
    assert(store.attributionURL.absoluteString == "https://open-meteo.com/")
case "search_race":
    store.configure(storageURL: sidecar)
    store.searchCities("Berlin"); store.searchCities("New York")
    assert(transport.calls[0].token.cancelled)
    transport.reply(1, ["results":[other]])
    transport.reply(0, ["results":[berlin]])
    assert(store.candidates.count == 1 && store.candidates[0].id == 5083330)
    store.searchCities("London"); store.searchCities("")
    transport.reply(2, ["results":[berlin]])
    assert(store.candidates.isEmpty && !store.searching)
    store.searchCities("a&countryCode=US")
    let items = URLComponents(url: transport.calls.last!.request.url!, resolvingAgainstBaseURL:false)!.queryItems!
    assert(items.first(where: {$0.name == "name"})?.value == "a&countryCode=US")
    assert(!items.contains(where: {$0.name == "countryCode"}), "Search input must not inject query parameters")
case "city_race":
    store.configure(storageURL: sidecar); chooseFirst()
    let oldWeather = transport.calls.count - 1
    search(); store.selectCity(store.candidates[1])
    let newWeather = transport.calls.count - 1
    assert(transport.calls[oldWeather].token.cancelled)
    transport.reply(newWeather, weather(71, temperature: -2))
    assert(store.condition == .snow && store.temperatureText == "-2°")
    transport.reply(oldWeather, weather(0, temperature: 26))
    assert(store.condition == .snow && store.selectedCity?.id == 5083330)
    store.disable()
    transport.reply(newWeather, weather(61))
    assert(store.selectedCity == nil && store.snapshot == nil && store.condition == .unknown)
case "cache":
    store.configure(storageURL: sidecar); chooseFirst()
    transport.reply(transport.calls.count - 1, weather())
    assert(store.condition == .rain && store.hasCurrentWeather && store.temperatureText == "12°")
    let count = transport.calls.count
    clock += 1799; store.refreshIfNeeded()
    assert(transport.calls.count == count)
    clock += 2; store.refreshIfNeeded()
    assert(transport.calls.count == count + 1 && store.loading)
    transport.calls.last!.done(.failure(URLError(.timedOut)))
    assert(!store.loading && !store.hasCurrentWeather && store.temperatureText.contains("上次"))
    assert(store.condition == .unknown && store.statusText.contains("上次"))
    store.refreshIfNeeded(); assert(transport.calls.count == count + 1)
    clock += 21_601
    store.refreshIfNeeded()
    assert(store.temperatureText == "—" && store.condition == .unknown)
case "restore":
    store.configure(storageURL: sidecar); chooseFirst()
    transport.reply(transport.calls.count - 1, weather(97))
    let secondTransport = RecordingWeatherTransport()
    let restored = WeatherAtmosphereStore(transport:secondTransport, now:{clock}, localHour:{hour})
    restored.configure(storageURL:sidecar)
    assert(secondTransport.calls.isEmpty && restored.selectedCity?.id == 2950159)
    assert(restored.condition == .storm && restored.hasCurrentWeather)
    restored.refreshIfNeeded(); assert(secondTransport.calls.isEmpty)
    restored.disable()
    let disabled = WeatherAtmosphereStore(transport:secondTransport)
    disabled.configure(storageURL:sidecar); disabled.refreshIfNeeded(force:true)
    assert(disabled.selectedCity == nil && secondTransport.calls.isEmpty)
case "invalid_responses":
    store.configure(storageURL: sidecar)
    var badCity = berlin; badCity["latitude"] = 91.0
    var badName = other; badName["name"] = "\n假的城市"
    var blankName = other; blankName["name"] = "    "
    search([badCity, badName, blankName, berlin]); assert(store.candidates.count == 1)
    store.selectCity(store.candidates[0]); transport.reply(transport.calls.count - 1, weather(999))
    assert(store.snapshot == nil && store.condition == .unknown && !store.loading)
    for invalid in [weather(61, temperature:200), weather(61, time:clock.timeIntervalSince1970 + 86400)] {
        store.refreshIfNeeded(force:true); transport.reply(transport.calls.count - 1, invalid)
        assert(store.snapshot == nil)
    }
    store.refreshIfNeeded(force:true)
    transport.calls.last!.done(.success(WeatherHTTPResponse(data:Data("not-json".utf8), statusCode:200)))
    assert(store.snapshot == nil && !store.statusText.isEmpty)
    store.refreshIfNeeded(force:true)
    transport.calls.last!.done(.success(WeatherHTTPResponse(data:Data(repeating:32,count:300_000), statusCode:200)))
    assert(store.snapshot == nil && !store.loading)
    store.searchCities("Berlin")
    transport.reply(transport.calls.count - 1, ["results":[["id":1,"name":"fake"]]])
    assert(store.candidates.isEmpty && !store.searching)
case "disk_failure":
    store.configure(storageURL: sidecar); chooseFirst()
    transport.reply(transport.calls.count - 1, weather())
    let original = try! Data(contentsOf:sidecar)
    let moved = folder.deletingLastPathComponent().appendingPathComponent(folder.lastPathComponent + "-preserved")
    try! fm.moveItem(at:folder,to:moved)
    try! Data("blocks-directory".utf8).write(to:folder)
    search(); let chosen = store.candidates[1]
    let before = transport.calls.count
    store.selectCity(chosen)
    assert(store.selectedCity?.id == 2950159 && store.condition == .rain)
    assert(transport.calls.count == before && store.persistenceError != nil)
    store.disable()
    assert(store.selectedCity?.id == 2950159 && store.persistenceError != nil)
    assert(try! Data(contentsOf:moved.appendingPathComponent("test.weather.json")) == original)
case "bad_sidecar":
    let broken = Data("{ broken JSON".utf8); try! broken.write(to:sidecar)
    store.configure(storageURL:sidecar)
    assert(store.selectedCity == nil && transport.calls.isEmpty && !store.statusText.isEmpty)
    assert(try! Data(contentsOf:sidecar) == broken)
    try! Data(repeating:32,count:300_000).write(to:sidecar)
    store.configure(storageURL:sidecar)
    assert(store.selectedCity == nil && transport.calls.isEmpty)
    chooseFirst(); transport.reply(transport.calls.count - 1, weather())
    var data = try! JSONSerialization.jsonObject(with:Data(contentsOf:sidecar)) as! [String:Any]
    var city = data["city"] as! [String:Any]; city["longitude"] = 181; data["city"] = city
    try! JSONSerialization.data(withJSONObject:data).write(to:sidecar)
    store.configure(storageURL:sidecar)
    assert(store.selectedCity == nil && store.snapshot == nil)
case "rate_limit":
    store.configure(storageURL:sidecar); chooseFirst()
    transport.reply(transport.calls.count - 1, [:], status:429, retryAfter:600)
    let count = transport.calls.count
    store.refreshIfNeeded(force:true); assert(transport.calls.count == count)
    clock += 601; store.refreshIfNeeded()
    assert(transport.calls.count == count + 1)
    transport.reply(transport.calls.count - 1, weather(3))
    assert(store.condition == .cloudy && store.hasCurrentWeather)
case "scheduled_expiry":
    store.configure(storageURL:sidecar); chooseFirst()
    transport.reply(transport.calls.count - 1, weather(61, time:clock.timeIntervalSince1970 - 5399))
    assert(store.hasCurrentWeather)
    let count = transport.calls.count
    clock += 2
    let deadline = Date().addingTimeInterval(2.5)
    while transport.calls.count == count && Date() < deadline {
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))
    }
    assert(transport.calls.count == count + 1, "Observation age must invalidate the display without reopening a view")
    assert(store.condition == .unknown && store.statusText.contains("上次"))
case "background_callback":
    store.configure(storageURL:sidecar); chooseFirst()
    var updatesOnMain = true
    let observer = store.objectWillChange.sink { if !Thread.isMainThread { updatesOnMain = false } }
    let result = WeatherHTTPResponse(data:try! JSONSerialization.data(withJSONObject:weather(71)),statusCode:200)
    let done = transport.calls.last!.done
    DispatchQueue.global().async { done(.success(result)) }
    let deadline = Date().addingTimeInterval(2)
    while store.snapshot == nil && Date() < deadline { RunLoop.main.run(until:Date().addingTimeInterval(0.02)) }
    assert(store.condition == .snow && updatesOnMain)
    withExtendedLifetime(observer) {}
default: fatalError("Unknown case")
}
print("PASS \(CommandLine.arguments[1]): NO_REAL_LOCATION_NO_NETWORK_NO_GAME_SAVE")
'''


class WeatherAtmosphereTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-weather-tests-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.source = ROOT / 'native/v1/WeatherAtmosphere.swift'
        if not cls.source.exists():
            raise AssertionError('WeatherAtmosphere service is not implemented yet')
        (cls.folder / 'main.swift').write_text(HARNESS)
        cls.binary = cls.folder / 'check'
        result = subprocess.run(['swiftc', '-framework', 'Foundation', '-framework', 'Combine',
            str(cls.source), str(cls.folder / 'main.swift'), '-o', str(cls.binary)],
            capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name):
        folder = self.folder / name
        folder.mkdir()
        result = subprocess.run([str(self.binary), name, str(folder)],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ' + name, result.stdout)

    def test_no_implicit_location_network_or_selection(self): self.run_case('consent')
    def test_search_cancellation_and_query_encoding(self): self.run_case('search_race')
    def test_previous_city_callbacks_cannot_replace_new_selection(self): self.run_case('city_race')
    def test_fresh_cache_and_failed_or_expired_data_labels(self): self.run_case('cache')
    def test_restore_requires_no_network_and_disable_persists(self): self.run_case('restore')
    def test_invalid_or_oversized_responses_do_not_become_weather(self): self.run_case('invalid_responses')
    def test_atomic_write_failure_preserves_previous_selection_and_file(self): self.run_case('disk_failure')
    def test_bad_sidecar_remains_untouched_until_explicit_selection(self): self.run_case('bad_sidecar')
    def test_http_429_backoff_applies_even_to_manual_refresh(self): self.run_case('rate_limit')
    def test_observation_age_expires_without_reopening_a_panel(self): self.run_case('scheduled_expiry')
    def test_background_transport_publishes_only_on_main_thread(self): self.run_case('background_callback')
