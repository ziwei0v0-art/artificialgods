"""Continuous ceremony rendering and cancellation, without windows or save access."""
import json
from pathlib import Path
import unittest

from tests import test_fixed_daily_actions as daily_tests

ROOT = Path(__file__).resolve().parents[1]


class OneClickCeremonyMotionTests(unittest.TestCase):
    def run_swift(self, body):
        scene = ROOT / 'assets/production/scene'
        prefix = 'let actualScene=ShrineArtwork.load(from:URL(fileURLWithPath:' + json.dumps(str(scene), ensure_ascii=False) + '))!\n'
        prefix += 'view.shrineArtwork=actualScene;referenceView.shrineArtwork=actualScene\nlet actualStand=render(referenceView)\n'
        daily_tests.FixedDailyActionsTests.run_swift(self, prefix + body)

    def test_timeline_carries_one_incense_without_phase_restarts(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Initial ambient idle")
view.ceremonyElapsed=0
func sample(_ t:Double)->NSBitmapImageRep {
    view.ceremonyElapsed=t/3.2;view.updateAnimation(elapsed:t/3.2);return render()
}
let approach=sample(1)
check(bbox(approach,"head").midX < bbox(actualStand,"head").midX-25, "Original attendant walks toward the altar")
let before=sample(4.9999)
check(!propPixels(before,"incense").isEmpty, "The supplied incense is visible in hand")
let hand=box(propPixels(before,"incense"))
let transfer=sample(6)
check(!propPixels(transfer,"incense").isEmpty, "Transfer incense remains visible")
let middle=box(propPixels(transfer,"incense"))
let after=sample(7.0001)
check(!propPixels(after,"incense").isEmpty, "Placed incense remains visible")
let placed=box(propPixels(after,"incense"))
check(hand.midX > middle.midX && middle.midX > placed.midX, "Same incense travels continuously from hand to censer")
check(middle.width < 10, "Transfer does not leave a second incense at either endpoint")
check(!propPixels(sample(9),"incense").isEmpty, "Incense remains in censer during the response")
check(!propPixels(sample(11),"paper").isEmpty, "Original signed-paper prop is presented")
check(!propPixels(sample(13),"paper").isEmpty, "Paper does not vanish at the final phase boundary")
check(propPixels(sample(14),"paper").isEmpty, "Paper is put away before the return walk")
let end=sample(16)
check(propPixels(end,"incense").isEmpty && propPixels(end,"paper").isEmpty, "Final smoke and carried props settle fully")
view.ceremonyElapsed=nil;view.updateAnimation(elapsed:5.2)
check(bytes(render())==bytes(actualStand), "Completion releases back to the existing ambient scene")

// Each boundary is sampled with fresh views at adjacent times, avoiding a
// replay-based comparison that could accidentally hide a phase reset.
for boundary:Double in [1.5,5,7,10,13] {
    var frames:[NSBitmapImageRep]=[]
    for offset:Double in [-0.0001,0.0001] {
        let target=TianmuView(frame:view.frame);target.attendantArtwork=artwork;target.shrineArtwork=actualScene
        target.persistLegacyFrame=false;check(target.applyRoutine(snapshot(1,0,0,"idle")), "Boundary reference")
        target.ceremonyElapsed=0;target.updateAnimation(elapsed:(boundary+offset)/3.2)
        target.ceremonyElapsed=(boundary+offset)/3.2;frames.append(render(target))
    }
    check(!changed(bbox(frames[0],"head"),bbox(frames[1],"head")), "Original head does not reset at phase boundary")
    for prop in ["incense","paper"] {
        let a=propPixels(frames[0],prop),b=propPixels(frames[1],prop)
        check(a.isEmpty==b.isEmpty, "A phase boundary cannot remove/recreate its visible prop")
        if !a.isEmpty { check(!changed(box(a),box(b)), "Prop location is continuous across phase boundary") }
    }
}
''')

    def test_skip_at_any_phase_returns_to_latest_ambient_and_consumes_click(self):
        self.run_swift(r'''
for t:Double in [0.25,1,1.8125,2.6875,3.59375,4.53125] {
    let target=TianmuView(frame:view.frame);target.attendantArtwork=artwork;target.shrineArtwork=actualScene
    target.persistLegacyFrame=false;check(target.applyRoutine(snapshot(1,0.8,18,"read")), "Reading before ceremony")
    target.ceremonyElapsed=0;target.updateAnimation(elapsed:t);target.ceremonyElapsed=t
    check(propPixels(render(target),"book").isEmpty, "Ceremony takes display priority over ambient book")
    target.respond()
    check(target.applyRoutine(snapshot(2,0,0,"idle")), "Latest ambient update while ceremony owns display")
    let visible=bytes(render(target))
    target.ceremonyElapsed=nil
    check(bytes(render(target))==visible, "Skip begins from the exact visible pose")
    target.updateAnimation(elapsed:t+0.2)
    check(bytes(render(target))==bytes(actualStand), "Skip clears walk, incense, paper, smoke and latent response")
    target.updateAnimation(elapsed:t+5)
    check(bytes(render(target))==bytes(actualStand), "A skipped ceremony cannot reappear")
}
''')

    def test_pointer_hold_freezes_ceremony_then_release_uses_current_time(self):
        self.run_swift(r'''
check(view.applyRoutine(snapshot(1,0,0,"idle")), "Initial idle")
view.ceremonyElapsed=0;view.updateAnimation(elapsed:0.9375);view.ceremonyElapsed=0.9375
let frozen=bytes(render())
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),0.9375))
view.ceremonyElapsed=1.875;view.updateAnimation(elapsed:1.875)
check(bytes(render())==frozen, "Held hand/prop stays frozen while ceremony clock advances")
view.ceremonyElapsed=3.4375;view.updateAnimation(elapsed:3.4375)
check(bytes(render())==frozen, "Later paper and smoke cannot change a held scene")
view.cancelInteraction();view.updateAnimation(elapsed:3.6375)
check(!propPixels(render(),"paper").isEmpty, "Release joins the current paper phase without replaying incense")
view.mouseDown(with:mouse(.leftMouseDown,headPoint(render()),3.6375))
let heldPaper=bytes(render());view.ceremonyElapsed=nil;view.updateAnimation(elapsed:5.3)
check(bytes(render())==heldPaper, "Skip during press preserves held frame until release")
view.cancelInteraction();view.updateAnimation(elapsed:5.5)
check(bytes(render())==bytes(actualStand), "Release after skip goes directly to ambient")
''')


if __name__ == '__main__':
    unittest.main()
