"""Fixed-action resources are packaged atomically using temporary files only."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from tests.test_shrine_art_packaging import write_png

ROOT=Path(__file__).resolve().parents[1]

class FixedActionPackagingTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('fixed_action_build',ROOT/'tools/build_native.py')
        self.build=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.build)
        self.temp=tempfile.TemporaryDirectory(prefix='tianmu-fixed-action-package-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.resources=self.root/'Resources';self.target=self.resources/'art/A01'
        self.manifest={'version':1,'stand':{'file':'stand.png'},'fixedActions':{'sourceSize':[2,2],'catch':{'nearSleeve':{},'torsoUnderlay':{'file':'underlay.png'},'net':{'file':'net.png'}}}}
        for name in ('stand.png','underlay.png','net.png','unowned.png'):write_png(self.source/name)
    def package(self,value=None):
        (self.source/'manifest.json').write_text(json.dumps(self.manifest if value is None else value))
        return self.build.copy_attendant_art(self.source,self.resources)
    def test_owned_action_files_are_copied_once_without_unowned_art(self):
        self.target.mkdir(parents=True);(self.target/'withdrawn.png').write_bytes(b'old')
        self.assertTrue(self.package())
        self.assertEqual({p.name for p in self.target.iterdir()},{'manifest.json','stand.png','underlay.png','net.png'})
        for p in self.target.iterdir():self.assertEqual(p.read_bytes(),(self.source/p.name).read_bytes())
    def test_invalid_action_paths_do_not_replace_existing_output(self):
        outside=self.root/'outside.png';write_png(outside);(self.source/'escape.png').symlink_to(outside)
        self.target.mkdir(parents=True);(self.target/'keep.txt').write_text('old candidate')
        for name in ('../outside.png',str(outside),'escape.png','missing.png'):
            with self.subTest(name=name):
                value=copy.deepcopy(self.manifest);value['fixedActions']['catch']['net']['file']=name
                with self.assertRaises(ValueError):self.package(value)
                self.assertEqual((self.target/'keep.txt').read_text(),'old candidate')
                self.assertEqual({p.name for p in self.target.iterdir()},{'keep.txt'})
    def test_malformed_optional_action_spec_is_rejected_before_output(self):
        for config in (None,[],{'catch':None},{'catch':{}},{'catch':{'torsoUnderlay':{'file':'underlay.png'},'net':None}}):
            with self.subTest(config=config):
                value=copy.deepcopy(self.manifest);value['fixedActions']=config
                with self.assertRaises(ValueError):self.package(value)
                self.assertFalse(self.resources.exists())
    def test_optional_absence_keeps_stand_only_package_valid(self):
        value={'version':1,'stand':{'file':'stand.png'}}
        self.assertTrue(self.package(value))
        self.assertEqual({p.name for p in self.target.iterdir()},{'manifest.json','stand.png'})
    def test_daily_props_are_packaged_and_shared_references_are_deduplicated(self):
        for name in ('book.png','incense.png'):write_png(self.source/name)
        self.manifest['fixedActions']['daily']={'props':{'book':{'file':'book.png'},'incense':{'file':'incense.png'},'paper':{'file':'book.png'}}}
        self.assertTrue(self.package())
        self.assertEqual({p.name for p in self.target.iterdir()},{'manifest.json','stand.png','underlay.png','net.png','book.png','incense.png'})
        for name in ('book.png','incense.png'):self.assertEqual((self.target/name).read_bytes(),(self.source/name).read_bytes())
    def test_unsafe_daily_prop_cannot_replace_existing_candidate(self):
        outside=self.root/'outside.png';write_png(outside);(self.source/'escape.png').symlink_to(outside)
        self.target.mkdir(parents=True);(self.target/'keep.txt').write_text('old candidate')
        for name in ('../outside.png',str(outside),'escape.png','missing.png'):
            with self.subTest(name=name):
                value=copy.deepcopy(self.manifest);value['fixedActions']['daily']={'props':{'book':{'file':name}}}
                with self.assertRaises(ValueError):self.package(value)
                self.assertEqual({p.name for p in self.target.iterdir()},{'keep.txt'})
                self.assertEqual((self.target/'keep.txt').read_text(),'old candidate')
    def test_malformed_daily_resources_are_rejected_before_output(self):
        for daily in (None,[],{}, {'props':[]}, {'props':{'book':None}}, {'props':{'book':{}}}):
            with self.subTest(daily=daily):
                value=copy.deepcopy(self.manifest);value['fixedActions']['daily']=daily
                with self.assertRaises(ValueError):self.package(value)
                self.assertFalse(self.resources.exists())

if __name__=='__main__':unittest.main()
