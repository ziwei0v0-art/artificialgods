"""Independent interruption checks through real rendering; no game windows or saves."""
import json
from pathlib import Path
import unittest

from tests import test_fixed_daily_actions as daily_tests


class DailyRitualPriorityTests(unittest.TestCase):
    def run_swift(self, body):
        scene=Path(__file__).resolve().parents[1]/'assets/production/scene'
        prefix='let actualScene=ShrineArtwork.load(from:URL(fileURLWithPath:'+json.dumps(str(scene),ensure_ascii=False)+'))!\n'
        prefix+='view.shrineArtwork=actualScene;referenceView.shrineArtwork=actualScene\nlet actualStand=render(referenceView)\n'
        daily_tests.FixedDailyActionsTests.run_swift(self, prefix+body.replace('referenceStand','actualStand'))

    def test_press_holds_all_three_ritual_changes_then_releases_into_current_paper(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0.8,18,"read")), "Initial reading")
check(!propPixels(render(),"book").isEmpty, "Reading is visible before press")
let frozen=bytes(render())
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0))
view.updateAnimation(elapsed:0.1);view.ritualStage="取香行礼"
view.updateAnimation(elapsed:0.6)
check(bytes(render())==frozen, "Taking incense cannot override an existing press")
view.updateAnimation(elapsed:2.1);view.ritualStage="炉烟升起"
view.updateAnimation(elapsed:2.5)
check(bytes(render())==frozen, "Burner incense and smoke stay visually frozen during press")
check(view.applyRoutine(snapshot(2,0,0,"idle")), "Latest service idle arrives while pressed")
view.updateAnimation(elapsed:4.1);view.ritualStage="呈出签纸"
view.updateAnimation(elapsed:4.4)
check(bytes(render())==frozen, "Paper stage cannot change the held image")
view.cancelInteraction()
check(bytes(render())==frozen, "Release begins from the exact held frame")
view.updateAnimation(elapsed:4.57)
check(propPixels(render(),"book").isEmpty, "Held book leaves after static settling")
check(!propPixels(render(),"paper").isEmpty, "Release uses current paper stage without replaying incense")
view.updateAnimation(elapsed:6.1);view.ritualStage=nil
view.updateAnimation(elapsed:6.3)
check(bytes(render())==bytes(referenceStand), "Completed ritual returns to latest idle")
''')

    def test_response_expires_while_ritual_owns_the_display(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Idle service")
view.respond();view.updateAnimation(elapsed:0.25)
check(bytes(render()) != bytes(referenceStand), "Response visibly begins")
view.ritualStage="取香行礼";view.updateAnimation(elapsed:0.65)
check(!propPixels(render(),"incense").isEmpty, "Ritual has display priority over response")
view.updateAnimation(elapsed:1.5)
view.ritualStage=nil;view.updateAnimation(elapsed:1.7)
check(bytes(render())==bytes(referenceStand), "Response that expired under ritual must not replay")
view.updateAnimation(elapsed:1.9)
check(bytes(render())==bytes(referenceStand), "No delayed response after ritual settling")
''')

    def test_press_does_not_extend_response_clock_and_release_consumes_latest_read(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Idle service")
view.respond();view.updateAnimation(elapsed:0.35)
let frozen=bytes(render())
check(frozen != bytes(referenceStand), "Response visibly begins before press")
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0.35))
view.updateAnimation(elapsed:2.5)
check(view.applyRoutine(snapshot(2,4,18,"read")), "Latest read arrives while response is held")
view.updateAnimation(elapsed:3)
check(bytes(render())==frozen, "Pressed response appearance stays frozen despite elapsed time")
view.cancelInteraction();view.updateAnimation(elapsed:3.17)
check(!propPixels(render(),"book").isEmpty, "Expired response cannot block latest read after release")
let latest=TianmuView(frame:view.frame);latest.attendantArtwork=artwork;latest.shrineArtwork=actualScene;latest.persistLegacyFrame=false
check(latest.applyRoutine(snapshot(2,4.67,18,"read")), "Reference current read")
check(bytes(render())==bytes(render(latest)), "Release joins current service elapsed without restarting read")
''')

    def test_ritual_ending_during_press_cannot_reappear_after_release(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Idle service")
view.ritualStage="呈出签纸";view.updateAnimation(elapsed:0.7)
check(!propPixels(render(),"paper").isEmpty, "Paper is visible before press")
let frozen=bytes(render())
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0.7))
view.updateAnimation(elapsed:1);view.ritualStage=nil
check(view.applyRoutine(snapshot(2,0,0,"idle")), "Idle while held")
view.updateAnimation(elapsed:4)
check(bytes(render())==frozen, "Ending ritual does not change held paper")
view.cancelInteraction();view.updateAnimation(elapsed:4.17)
check(bytes(render())==bytes(referenceStand), "Expired ritual settles directly into latest idle")
view.updateAnimation(elapsed:5)
check(bytes(render())==bytes(referenceStand), "Paper and smoke cannot reappear")
''')

    def test_active_burner_incense_and_smoke_are_frozen_with_the_character(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Idle service")
view.ritualStage="炉烟升起";view.updateAnimation(elapsed:0.6)
let frozen=bytes(render())
check(frozen != bytes(referenceStand), "Real G0 burner visibly receives incense and smoke")
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0.6))
view.updateAnimation(elapsed:1.6)
check(bytes(render())==frozen, "Already visible scene smoke must stop moving while pressed")
view.updateAnimation(elapsed:2);view.ritualStage="呈出签纸"
view.updateAnimation(elapsed:2.4)
check(bytes(render())==frozen, "New ritual stage cannot replace held scene smoke or character")
view.cancelInteraction();view.updateAnimation(elapsed:2.57)
check(!propPixels(render(),"paper").isEmpty, "Release joins current paper while burner remains active")
check(bytes(render()) != frozen, "Display resumes after release")
''')

    def test_click_during_ritual_tail_is_not_replayed_when_ritual_ends(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Idle service")
view.ritualStage="呈出签纸";view.updateAnimation(elapsed:1.6)
view.respond();view.updateAnimation(elapsed:1.8)
view.ritualStage=nil;view.updateAnimation(elapsed:1.97)
check(bytes(render())==bytes(referenceStand), "Click under ritual is not queued for after the ritual")
''')


if __name__=='__main__':unittest.main()
