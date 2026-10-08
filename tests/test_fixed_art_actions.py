"""Fixed-source catch through TianmuView; no windows, worker, or save access."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
import zlib

from tests.test_attendant_art import png
from tests.test_fixed_art_walk import PRELUDE

ROOT = Path(__file__).resolve().parents[1]
RIG = {'sourceSize': [24, 48], 'catch': {
    'nearSleeve': {'mask': [[0, 23], [11, 23], [13, 26], [12, 34], [10, 38], [10, 41], [0, 41]],
                   'pivot': [10, 24], 'hand': [8, 38]},
    'torsoUnderlay': {'file': 'underlay.png', 'bounds': [7, 24, 12, 18],
                     'bodyArea': [[7, 23], [19, 23], [20, 42], [7, 42]]},
    'net': {'file': 'net.png', 'height': 27, 'grip': [0.32, 0.89], 'rotation': 110}}}

EXTRA = r'''
func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { print("FAIL: " + message); exit(1) }
}
func netPixels(_ image: NSBitmapImageRep) -> Set<Pixel> {
    var result: Set<Pixel> = []
    for y in 0..<image.pixelsHigh { for x in 0..<image.pixelsWide {
        let c = image.colorAt(x: x, y: y)!.usingColorSpace(.deviceRGB)!
        if c.alphaComponent > 0.08 && c.redComponent > 0.9 && c.greenComponent > 0.9 && c.blueComponent < 0.1 {
            result.insert(Pixel(x: x, y: y))
        }
    }}
    return result
}
func catchSnapshot(_ serial: Int = 1, _ elapsed: Double = 0, _ duration: Double = 3) -> [String: Any] {
    snapshot(serial, elapsed, duration, "catch")
}
func finish() { check(app.windows.isEmpty, "A test must not open windows"); print("PASS: NO_WINDOWS_NO_WORKER_NO_SAVE") }
'''


class FixedArtActionsTests(unittest.TestCase):
    def run_swift(self, body, *, rigs=None, facing='right', mutate=None):
        with tempfile.TemporaryDirectory(prefix='tianmu-fixed-actions-test-') as directory:
            work = Path(directory)
            art_paths = []
            for index, rig in enumerate(rigs if rigs is not None else [RIG]):
                art = work / ('A01-' + str(index)); art.mkdir()
                fixture = {(x, y): (160, 160, 160, 255) for y in range(16, 44) for x in range(24)}
                fixture.update({(x, y): (255, 0, 255, 255) for y in range(16) for x in range(4, 20)})
                fixture.update({(x, y): (0, 255, 255, 255) for y in range(44, 48) for x in range(3, 9)})
                fixture.update({(x, y): (0, 255, 0, 255) for y in range(44, 48) for x in range(15, 21)})
                png(art / 'stand.png', width=24, height=48, pixels=fixture)
                net = {(x, y): (255, 255, 0, 255) for y in range(2, 23) for x in range(1, 7)
                       if (y < 11 and (x in [1, 6] or y in [2, 10])) or (y >= 10 and x == 3)}
                png(art / 'net.png', width=8, height=24, pixels=net)
                png(art / 'underlay.png', width=12, height=18,
                    pixels={(x, y): (160, 160, 160, 255) for y in range(18) for x in range(12)})
                manifest = {'version': 1, 'sampling': 'nearest', 'stand': {'file': 'stand.png', 'facing': facing},
                            'fixedWalk': {'sourceSize': [24, 48], 'bodyCutY': 44, 'legStartY': 42,
                                          'legSplitX': 12, 'maxRootStep': 3, 'footLift': 2}}
                if rig is not None: manifest['fixedActions'] = copy.deepcopy(rig)
                (art / 'manifest.json').write_text(json.dumps(manifest))
                if mutate: mutate(art, index)
                art_paths.append(art)
            preserved = {p: hashlib.sha256(p.read_bytes()).hexdigest() for art in art_paths for p in art.iterdir() if p.is_file()}
            source = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
            (work / 'Scene.swift').write_text(source)
            (work / 'main.swift').write_text(PRELUDE + EXTRA + body + '\nfinish()\n')
            build = subprocess.run(['swiftc', '-framework', 'AppKit', str(work / 'Scene.swift'), str(work / 'main.swift'),
                                    '-o', str(work / 'check')], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(work / 'check'), *map(str, art_paths)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(preserved, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved})
            print(run.stdout.strip())

    def test_catch_has_net_unchanged_head_and_exact_stand_endpoints(self):
        self.run_swift(r'''
check(view.applyRoutine(catchSnapshot()), "Catch snapshot is accepted")
let first = render()
check(bytes(first) == bytes(referenceStand), "At zero catch must use exact original stand")
view.updateAnimation(elapsed: 0.8)
let middle = render()
check(netPixels(middle).count > 12, "Catch must actually draw the supplied net")
check(pixels(middle, "head") == pixels(first, "head"), "The original head must not move or change")
check(view.unavailableRoutineAction == nil, "A valid fixed catch fulfills the service presentation")
check(view.applyRoutine(catchSnapshot(1, 3)), "Endpoint snapshot is accepted")
check(bytes(render()) == bytes(first), "At three seconds the entire original stand is exact")
view.updateAnimation(elapsed: 5)
check(bytes(render()) == bytes(first), "A completed catch cannot loop")
''')

    def test_service_time_midjoin_duplicate_stale_and_duration(self):
        self.run_swift(r'''
check(view.applyRoutine(catchSnapshot(7)), "Initial catch")
view.updateAnimation(elapsed:0.8)
let middle=bytes(render())
let joined=TianmuView(frame:view.frame); joined.attendantArtwork=artwork; joined.persistLegacyFrame=false
check(joined.applyRoutine(catchSnapshot(7,0.8)), "Join midcatch")
check(bytes(render(joined))==middle, "Midcatch must start at current service time")
check(view.applyRoutine(catchSnapshot(7)), "Identical receipt")
check(bytes(render())==middle, "Duplicate must not rewind")
check(!view.applyRoutine(catchSnapshot(6,0.9)), "Old serial rejected")
check(!view.applyRoutine(snapshot(7,0,3,"read")), "Conflicting action rejected")
view.updateAnimation(elapsed:1)
let stale=bytes(render())
view.updateAnimation(elapsed:9)
check(bytes(render())==stale, "No heartbeat means at most one second of interpolation")
check(view.applyRoutine(catchSnapshot(8,4,5)), "Nonstandard duration still valid")
view.updateAnimation(elapsed:9.2)
check(netPixels(render()).isEmpty, "Catch curve clamps at three seconds rather than looping")
''')

    def test_press_freezes_visible_pose_and_release_settles_static_parameters(self):
        self.run_swift(r'''
check(view.applyRoutine(catchSnapshot(1,0.8)), "Catch middle")
let frozen=bytes(render()), head=headPoint(render())
view.mouseDown(with:mouse(.leftMouseDown,head,0))
view.updateAnimation(elapsed:0.4)
check(view.applyRoutine(snapshot(2,0,0,"idle")), "New idle during press")
view.updateAnimation(elapsed:0.7)
check(bytes(render())==frozen, "Press holds the actually visible sleeve and net despite new service facts")
view.cancelInteraction()
check(bytes(render())==frozen, "Release begins at the visible held pose")
view.updateAnimation(elapsed:0.78)
check(!netPixels(render()).isEmpty, "Release performs a short static return")
view.updateAnimation(elapsed:0.87)
check(bytes(render())==bytes(referenceStand), "Release ends in latest idle after 0.16 seconds")
// A newer catch is resumed at its actual elapsed time, with no phase replay.
check(view.applyRoutine(catchSnapshot(3,0.8)), "Second catch")
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0.9))
check(view.applyRoutine(catchSnapshot(4,2.3)), "New catch while held")
view.cancelInteraction(); view.updateAnimation(elapsed:1.04)
let current=TianmuView(frame:view.frame); current.attendantArtwork=artwork; current.persistLegacyFrame=false
check(current.applyRoutine(catchSnapshot(4,2.47)), "Reference latest catch")
check(bytes(render())==bytes(render(current)), "Release follows the latest catch clock rather than restarting at zero")
''')

    def test_ritual_response_priority_cannot_override_an_existing_press(self):
        self.run_swift(r'''
check(view.applyRoutine(catchSnapshot(1,0.8)), "Catch middle")
let frozen=bytes(render())
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0))
view.ritualStage="取香行礼"
view.updateAnimation(elapsed:0.3)
check(bytes(render())==frozen, "Ritual beginning during press cannot change the held visible catch")
view.cancelInteraction(); view.updateAnimation(elapsed:0.5)
check(netPixels(render()).isEmpty, "Ritual takes priority after release")
let hidden=bytes(render())
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0.5))
view.ritualStage=nil
check(view.applyRoutine(catchSnapshot(2,0.9)), "Fresh catch while hidden by held pose")
view.updateAnimation(elapsed:0.7)
check(bytes(render())==hidden, "Ritual ending during press cannot reveal a net")
view.cancelInteraction(); view.updateAnimation(elapsed:0.9)
check(!netPixels(render()).isEmpty, "Release can resume latest catch after ritual")
view.respond(); view.updateAnimation(elapsed:1.1)
check(netPixels(render()).isEmpty, "Response hides catch")
check(view.applyRoutine(catchSnapshot(2,3)), "Catch expires during response")
view.updateAnimation(elapsed:2.1)
check(netPixels(render()).isEmpty, "Expired action cannot reappear after response")
''')

    def test_rotated_alpha_input_and_bounds_both_facings_and_scales(self):
        for facing in ['right', 'left']:
            with self.subTest(facing=facing):
                self.run_swift(r'''
for factor:CGFloat in [0.5,1,1.5] {
    for t:Double in [0.45,0.8,1.3,2.55] {
        let target=TianmuView(frame:NSRect(x:0,y:0,width:370*factor,height:190*factor))
        target.attendantArtwork=artwork; target.persistLegacyFrame=false
        check(target.applyRoutine(catchSnapshot(Int(t*10)+1,t)), "Catch pose")
        let image=render(target), net=netPixels(image)
        check(!net.isEmpty, "Net is visible for hit checks")
        let matches=net.filter { target.subject(at:NSPoint(x:CGFloat($0.x)+0.5,y:target.bounds.height-CGFloat($0.y)-0.5)) == "attendant" }.count
        check(Double(matches)/Double(net.count)>=0.97, "Rotated and mirrored net alpha must be clickable")
        for p in net {
            check(target.attendantBounds.insetBy(dx:-1,dy:-1).contains(NSPoint(x:CGFloat(p.x)+0.5,y:target.bounds.height-CGFloat(p.y)-0.5)), "Accessibility bounds enclose drawn net")
        }
        assertHitsMatchPixels(target)
    }
    let target=TianmuView(frame:NSRect(x:0,y:0,width:370*factor,height:190*factor))
    target.attendantArtwork=artwork; target.persistLegacyFrame=false
    check(target.applyRoutine(snapshot(40,5,5,"walk")), "Finish first direction")
    check(target.applyRoutine(snapshot(41)), "Reverse walk")
    target.updateAnimation(elapsed:3.6)
    check(target.applyRoutine(catchSnapshot(42,0.8)), "Catch after reverse")
    target.updateAnimation(elapsed:3.8)
    assertHitsMatchPixels(target)
}
''', facing=facing)

    def test_bad_optional_rigs_keep_stand_and_fixed_walk(self):
        rigs = [None, {'sourceSize': [24, 48], 'catch': 'bad'}]
        for path, value in [(['sourceSize'], [24, 49]), (['catch','nearSleeve','mask'], [[0,0],[1,1]]),
                            (['catch','nearSleeve','pivot'], [-1,24]), (['catch','net','height'], 0),
                            (['catch','net','grip'], [1.1,0.8]), (['catch','net','rotation'], 181),
                            (['catch','net','file'], '../outside.png'), (['catch','net','file'], 'missing.png'),
                            (['catch','net','sourceRect'], [0,0,80,24]),
                            (['catch','torsoUnderlay','bounds'], [7,24,12,-1]),
                            (['catch','torsoUnderlay','bodyArea'], [[1,1],[2,2],[3,3]])]:
            rig=copy.deepcopy(RIG); item=rig
            for key in path[:-1]: item=item[key]
            item[path[-1]]=value; rigs.append(rig)
        self.run_swift(r'''
for path in CommandLine.arguments.dropFirst() {
    let loaded=AttendantArtwork.load(from:URL(fileURLWithPath:path))!
    check(loaded.hasWalkMotion && !loaded.hasCatchMotion, "Malformed catch alone must be disabled")
    let target=TianmuView(frame:view.frame); target.attendantArtwork=loaded; target.persistLegacyFrame=false
    check(target.applyRoutine(catchSnapshot(1,0.8)), "Invalid art does not reject service facts")
    check(netPixels(render(target)).isEmpty && target.unavailableRoutineAction=="catch", "Invalid optional action retains stand")
    check(target.applyRoutine(snapshot(2)), "Walk remains usable")
    let start=bbox(render(target),"head").midX
    target.updateAnimation(elapsed:0.8)
    check(bbox(render(target),"head").midX < start, "Malformed catch cannot discard existing fixed walk")
}
''', rigs=rigs)

    def test_walk_to_catch_preserves_existing_short_foot_return(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1)), "Walk begins")
view.updateAnimation(elapsed:0.65)
let moving=render(), oldHead=bbox(moving,"head")
check(view.applyRoutine(catchSnapshot(2)), "Catch begins at service zero")
let joined=render()
check(normalizedFixture(moving)==normalizedFixture(joined), "Catch zero preserves inherited foot transition without jumping")
view.updateAnimation(elapsed:0.73)
check(pixels(render(),"head")==pixels(joined,"head"), "Foot return cannot move the head")
view.updateAnimation(elapsed:0.83)
let settled=render()
check(bbox(settled,"head")==oldHead, "Action transition cannot relocate the body")
assertStandFeet(settled)
view.updateAnimation(elapsed:1.1)
check(!netPixels(render()).isEmpty, "Catch emerges from the hand after inherited feet settle")
''')

    def test_bad_prop_payloads_and_symlink_escape_keep_original_art(self):
        def corrupt(art, index):
            if index == 0:
                (art / 'net.png').write_text('not a PNG')
            elif index == 1:
                png(art / 'net.png', width=8, height=24, pixels={(0,0):(0,0,0,0)})
            elif index == 2:
                outside = art.parent / 'outside.png'
                outside.write_bytes((art / 'net.png').read_bytes())
                (art / 'net.png').unlink(); (art / 'net.png').symlink_to(outside)
            elif index == 3:
                def chunk(kind, payload):
                    return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload))
                header=struct.pack('>IIBBBBB',8,24,8,2,0,0,0)
                raw=b''.join(b'\0'+bytes([255,255,0])*8 for _ in range(24))
                (art / 'net.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
                manifest=json.loads((art / 'manifest.json').read_text())
                del manifest['fixedWalk']
                manifest['walk']={'fps':6,'frames':[{'file':'stand.png'},{'file':'stand.png'}]}
                (art / 'manifest.json').write_text(json.dumps(manifest))
        self.run_swift(r'''
for path in CommandLine.arguments.dropFirst() {
    let loaded=AttendantArtwork.load(from:URL(fileURLWithPath:path))!
    check(!loaded.hasCatchMotion && loaded.hasWalkMotion, "Bad prop payload or escaping symlink disables only optional catch")
    let target=TianmuView(frame:view.frame); target.attendantArtwork=loaded; target.persistLegacyFrame=false
    check(target.applyRoutine(catchSnapshot(1,0.8)), "Service snapshot accepted with fallback art")
    check(bytes(render(target))==bytes(referenceStand), "Bad prop falls back to exact original stand")
}
''', rigs=[RIG]*4, mutate=corrupt)
