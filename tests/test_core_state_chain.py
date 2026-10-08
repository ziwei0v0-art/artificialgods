"""Single service-level lifecycle from an empty temporary save; no UI or worker."""
import copy
import random
from pathlib import Path
import tempfile
import unittest

from tianmu_mvp.model import COLORS, SHOP
from tianmu_mvp.service import ApplicationService


class CoreStateChainTests(unittest.TestCase):
    def test_spawn_breed_capture_release_sell_decorate_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix='tianmu-core-chain-') as directory:
            path = Path(directory)/'state.json'
            print('TEMP_SAVE',path,flush=True)
            app = ApplicationService(path)
            app.game.rng = random.Random(12)  # Only stabilize randomness; do not grant money or insects.
            base = 1790769600
            def invariant():
                game=app.game
                desktop,bottle,sold=set(game.desktop),set(game.bottle),game.sold_ids
                self.assertFalse(desktop & bottle or desktop & sold or bottle & sold)
                for bug in [*game.desktop.values(),*game.bottle.values()]:
                    self.assertEqual(game.color_for(bug.genotype),bug.color)
            def act(action, **values):
                reply=app.handle({'action':action,**values},now=base+app.game.elapsed_seconds)
                self.assertTrue(reply['ok'],reply)
                invariant()
                return reply
            def until(target):
                while app.game.elapsed_seconds<target:
                    delta=min(2,target-app.game.elapsed_seconds)
                    reply=app.tick(now=base+app.game.elapsed_seconds+delta,active_seconds=delta)
                    self.assertTrue(reply['ok'],reply)
                    invariant()
            self.assertFalse(path.exists())
            self.assertEqual(app.game.coins,0)
            self.assertFalse(app.game.desktop or app.game.bottle)
            until(14);self.assertFalse(app.game.desktop)
            until(15)
            self.assertEqual(len(app.game.desktop),6)
            founders=copy.deepcopy(app.game.desktop)
            until(60)
            self.assertEqual(len(app.game.bottle),1,'Scheduled auto capture must put one founder in bottle')
            auto=copy.deepcopy(next(iter(app.game.bottle.values())))
            self.assertEqual(auto,founders[auto.id])
            act('release',color=auto.color,sex=auto.sex,count=1)
            self.assertEqual(app.game.desktop[auto.id],auto)
            self.assertNotIn(auto.id,app.game.bottle)
            self.assertEqual(app.game.active_capture_seconds,0)
            until(75)
            offspring=set(app.game.desktop)-set(founders)
            self.assertEqual(len(offspring),4,'Natural breeding must occur without injected insects')
            manual=copy.deepcopy(app.game.desktop[sorted(offspring)[0]])
            reply=act('catch',ids=[manual.id,manual.id])
            self.assertEqual(app.game.bottle[manual.id],manual)
            self.assertNotIn(manual.id,app.game.desktop)
            self.assertIn('1',reply['message'])
            print('CHAIN spawn=6 auto_caught=1 returned_original='+auto.id+' offspring=4 manual_caught='+manual.id,flush=True)
            # Let the normal schedule earn stock. Keep live breeders and a bottle survivor.
            until(315)
            act('catch',ids=list(app.game.desktop)[2:])
            keep=manual.id
            self.assertIn(keep,app.game.bottle)
            retained=copy.deepcopy(app.game.bottle[keep])
            discovered=set(app.game.discovered_colors)
            earned=0;sold_ids=set()
            for color in COLORS:
                # Selection is ordered; preserve the first matching bottle individual.
                candidates=[bug for bug in app.game.bottle.values() if bug.color==color and bug.id!=keep]
                for bug in candidates:
                    # Sell via normal sex/color selection; if it would select keep, leave this group.
                    first=next(b for b in app.game.bottle.values() if b.color==color and b.sex==bug.sex)
                    if first.id==keep: continue
                    preview=act('sale_preview',color=color,sex=bug.sex,count=1)
                    self.assertEqual(preview['sale']['amount'],app.game.prices[color])
                    token=preview['sale']['token'];before=app.game.coins
                    act('sale_confirm',token=token)
                    earned+=app.game.prices[color];sold_ids.add(first.id)
                    self.assertEqual(app.game.coins-before,app.game.prices[color])
                    self.assertEqual(app.game.active_capture_seconds,0)
                    self.assertFalse(app.handle({'action':'sale_confirm','token':token},now=base+315)['ok'])
            self.assertEqual(app.game.coins,earned)
            self.assertGreaterEqual(earned,SHOP['offering_plate']['price'])
            self.assertEqual(app.game.bottle[keep],retained)
            self.assertTrue(discovered.issubset(app.game.discovered_colors))
            self.assertTrue(sold_ids.issubset(app.game.sold_ids))
            act('buy',item='offering_plate')
            self.assertIn('offering_plate',app.game.owned_items)
            self.assertIsNone(app.game.placed_item)
            self.assertEqual(app.game.coins,earned-SHOP['offering_plate']['price'])
            act('place',item='offering_plate')
            self.assertEqual(app.game.placed_item,'offering_plate')
            act('checkpoint')
            before=copy.deepcopy(app.game)
            app=ApplicationService(path)
            for field in ('desktop','bottle','sold_ids','coins','owned_items','placed_items','placed_item','discovered_colors','discovery_dates','elapsed_seconds','active_capture_seconds','next_insect_number','_first_spawn_at','_next_breed_at','_next_auto_capture_at','_next_empty_refill_at'):
                self.assertEqual(getattr(app.game,field),getattr(before,field),field)
            self.assertEqual(app.game.rng.getstate(),before.rng.getstate())
            self.assertEqual(app.game.bottle[keep],retained)
            invariant()
            print('CHAIN restored coins='+str(app.game.coins)+' sold='+str(len(sold_ids))+' bottle='+str(len(app.game.bottle))+' elapsed='+str(app.game.elapsed_seconds)+' plate=offering_plate',flush=True)
        self.assertFalse(Path(directory).exists())
        print('TEMP_CLEANED',directory,flush=True)
