"""Actual timer snapshots and AppKit artwork decoding; no app windows, worker or real save."""
from pathlib import Path
import datetime
import json
import os
import subprocess
import tempfile
import unittest

from tianmu_mvp.timer import TimerSession

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import AppKit
import Foundation
func near(_ value:Double,_ expected:Double) -> Bool { abs(value-expected)<0.0000001 }
switch CommandLine.arguments[1] {
case "timers":
    let data=try! Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[2]))
    let rows=try! JSONSerialization.jsonObject(with:data) as! [[String:Any]]
    for row in rows {
        let timer=row["snapshot"] as! [String:Any]
        let expected=(row["fraction"] as! NSNumber).doubleValue
        let result=TimerVisualProgress(snapshot:timer,now:(row["now"] as! NSNumber).doubleValue)
        assert(near(result.fraction,expected),"Wrong progress for \(row["name"]!): \(result.fraction) expected \(expected)")
        assert(result.running == (row["running"] as! Bool),"Wrong running state for \(row["name"]!)")
        assert(result.fraction.isFinite && result.fraction >= 0 && result.fraction <= 1)
    }
    assert(TimerVisualProgress(snapshot:["mode":"countdown","status":"running","countdown_seconds":0],now:0).fraction == 0)
    assert(TimerVisualProgress(snapshot:["mode":"countdown","status":"running","countdown_seconds":Double.nan],now:0).fraction == 0)
    print("PASS timers: \(rows.count) actual TimerSession snapshots")
case "artwork":
    let library=UIArtifactLibrary(resourceRoot:URL(fileURLWithPath:CommandLine.arguments[2],isDirectory:true))
    for name in ["divination-vessel","timer-dial"] {
        guard let image=library.image(name),let cg=image.cgImage(forProposedRect:nil,context:nil,hints:nil) else {
            fatalError("Production artwork could not load: \(name)")
        }
        let bitmap=NSBitmapImageRep(cgImage:cg)
        assert(cg.width>100 && cg.height>200,"Artwork cropped to unusable size")
        var transparent=0,painted=0
        for y in stride(from:0,to:cg.height,by:7) {
            for x in stride(from:0,to:cg.width,by:7) {
                let alpha=bitmap.colorAt(x:x,y:y)!.alphaComponent
                if alpha<0.01 { transparent += 1 }
                if alpha>0.7 { painted += 1 }
            }
        }
        assert(transparent>10 && painted>100,"Production crop must retain a visible object and transparent surround")
    }
    assert(library.image("missing-art") == nil)
    print("PASS artwork: actual production crops loaded with visible transparent content")
case "symbols":
    for route in ["神前","虫瓶","拉网","装扮","虫谱","计时","设置","调整","移动","隐藏","显示","退出","收起"] {
        assert(NSImage(systemSymbolName:leisureSymbol(route),accessibilityDescription:nil) != nil,"Missing symbol for \(route)")
    }
    for image in [TianmuBrandArtwork.spider(size:18),TianmuBrandArtwork.spider(size:18,reminder:true)] {
        guard let cg=image.cgImage(forProposedRect:nil,context:nil,hints:nil) else { fatalError("Brand artwork did not render") }
        let bitmap=NSBitmapImageRep(cgImage:cg)
        var visible=0,clear=0
        for y in 0..<cg.height { for x in 0..<cg.width {
            let alpha=bitmap.colorAt(x:x,y:y)!.alphaComponent
            if alpha>0.5 { visible += 1 }; if alpha<0.01 { clear += 1 }
        } }
        assert(visible>15 && clear>4,"Icon must not render as blank or an opaque rectangle")
    }
    print("PASS symbols: all production route symbols resolve, icons render")
default: fatalError("Unknown case")
}
'''


def timer_fixtures():
    rows = []
    def record(name, timer, now, expected):
        rows.append({'name': name, 'snapshot': timer.to_dict(), 'now': now,
                     'fraction': expected, 'running': timer.status == 'running'})
    countdown = TimerSession(countdown_seconds=600)
    countdown.start('countdown', now=1000)
    record('countdown running', countdown, 1150, 0.25)
    countdown.pause(now=1180)
    record('countdown paused does not advance', countdown, 1700, 0.3)
    countdown.resume(now=2000)
    record('countdown resume keeps completed fraction', countdown, 2000, 0.3)
    countdown.tick(now=2420)
    record('countdown finished', countdown, 2500, 1)
    countdown.stop()
    record('countdown idle', countdown, 2600, 0)
    pomodoro = TimerSession(work_seconds=1800, break_seconds=300)
    pomodoro.start('pomodoro', now=1000)
    record('pomodoro work', pomodoro, 1450, 0.25)
    pomodoro.tick(now=2800)
    record('pomodoro work finished', pomodoro, 2800, 1)
    pomodoro.next_phase()
    record('pomodoro break ready', pomodoro, 2900, 0)
    pomodoro.start(now=3000)
    record('pomodoro break uses break duration', pomodoro, 3150, 0.5)
    pomodoro.pause(now=3150)
    record('pomodoro break paused', pomodoro, 3900, 0.5)
    stopwatch = TimerSession()
    stopwatch.start('stopwatch', now=1000)
    record('stopwatch running seconds sweep', stopwatch, 1020, 1 / 3)
    stopwatch.pause(now=1020)
    record('stopwatch paused seconds sweep', stopwatch, 2000, 1 / 3)
    stopwatch.resume(now=3000)
    record('stopwatch resumed adds prior elapsed', stopwatch, 3010, 0.5)
    stopwatch.finish_stopwatch(now=3020)
    record('stopwatch explicit completion', stopwatch, 3040, 1)
    fractional = TimerSession(countdown_seconds=60)
    fractional.start('countdown', now=100)
    fractional.pause(now=100.75)
    record('paused copper dial retains subsecond remainder', fractional, 200, .75 / 60)
    fractional = TimerSession()
    fractional.start('stopwatch', now=100)
    fractional.pause(now=100.75)
    record('paused stopwatch arc retains milliseconds', fractional, 200, .75 / 60)
    fractional.resume(now=300)
    record('resumed stopwatch arc retains accumulated milliseconds', fractional, 300.5, 1.25 / 60)
    moment = datetime.datetime(2026, 10, 4, tzinfo=datetime.timezone.utc).timestamp()
    clock = TimerSession(clock_timezone='local')
    record('clock local using process UTC', clock, moment, 0)
    clock.clock_timezone = 'Asia/Shanghai'
    record('clock explicit Beijing time', clock, moment, 2 / 3)
    return rows


class LeisureArtIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-leisure-tests-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.fixtures = cls.folder / 'timers.json'
        cls.fixtures.write_text(json.dumps(timer_fixtures()))
        # Run the production route mapping rather than maintaining a test copy.
        symbol_mapping = (ROOT / 'native/v1/LeisureViews.swift').read_text().split('struct QuietIconButton:')[0]
        (cls.folder / 'main.swift').write_text(symbol_mapping + HARNESS)
        cls.binary = cls.folder / 'check'
        result = subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'SwiftUI',
            str(ROOT / 'native/v1/BrandArtwork.swift'), str(cls.folder / 'main.swift'), '-o', str(cls.binary)],
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name, argument):
        result = subprocess.run([str(self.binary), name, str(argument)],
            env={**os.environ, 'TZ': 'UTC'}, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ' + name, result.stdout)
        print(result.stdout.strip())

    def test_progress_follows_actual_timer_snapshots_and_timezone(self):
        self.run_case('timers', self.fixtures)

    def test_production_vessel_and_dial_load_visible_transparent_artwork(self):
        self.run_case('artwork', ROOT / 'assets/production/ui')

    def test_native_route_symbols_and_brand_icons_are_visible(self):
        self.run_case('symbols', self.folder)
