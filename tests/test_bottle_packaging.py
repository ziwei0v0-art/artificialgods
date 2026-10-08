"""Validate/copy the bottle in temporary resources, without app or worker launch."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_bottle_artwork import bottle_fixture
from tests.test_insect_packaging import png

ROOT = Path(__file__).resolve().parents[1]


def builder():
    spec = importlib.util.spec_from_file_location('bottle_builder', ROOT/'tools/build_native.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class BottlePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='tianmu-bottle-package-')
        self.addCleanup(self.temporary.cleanup)
        self.folder=Path(self.temporary.name); self.source=self.folder/'source'
        self.value=bottle_fixture(self.source)
        self.resources=self.folder/'resources'; self.target=self.resources/'art/bottle'
        self.build=builder()

    def package(self):
        return self.build.copy_bottle_art(self.source,self.resources)

    def bytes(self):
        return {str(p.relative_to(self.target)):p.read_bytes() for p in self.target.rglob('*') if p.is_file()}

    def save(self,value):
        (self.source/'manifest.json').write_text(json.dumps(value))

    def test_exact_png_and_manifest_only_are_copied_and_stale_owned_files_removed(self):
        (self.source/'source.json').write_text('{"accepted":false,"integrated":false}')
        (self.source/'private.png').write_bytes(b'not owned')
        self.target.mkdir(parents=True); (self.target/'stale.png').write_bytes(b'stale')
        before={p.name:p.read_bytes() for p in self.source.iterdir()}
        self.assertTrue(self.package())
        self.assertEqual(self.bytes(),{k:before[k] for k in ('manifest.json','bottle.png')})
        self.assertEqual({p.name:p.read_bytes() for p in self.source.iterdir()},before)

    def test_bad_schema_hash_rect_and_missing_source_leave_existing_output_unchanged(self):
        self.package(); before=self.bytes()
        invalid=[None,[],{},dict(self.value,version=True),dict(self.value,version=1.0),
                 dict(self.value,sampling='linear'),dict(self.value,sha256='0'*64),
                 dict(self.value,interiorRect=[0,0,2,1]),dict(self.value,interiorRect=[0,0,0,1]),
                 dict(self.value,interiorRect=[0,0,True,1]),dict(self.value,interiorRect=[0,0,float('nan'),1]),
                 dict(self.value,interiorRect=[0,0,1]),dict(self.value,unsupported='anything')]
        for value in invalid:
            self.save(value)
            with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
            self.assertEqual(self.bytes(),before)
        with self.assertRaisesRegex(ValueError,'Bottle'):
            self.build.copy_bottle_art(self.folder/'missing',self.resources)
        self.assertEqual(self.bytes(),before)
        (self.source/'manifest.json').write_text('{"version":1,"version":2}')
        with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
        self.assertEqual(self.bytes(),before)

    def test_incomplete_crc_bad_png_no_alpha_and_empty_png_are_rejected_before_writes(self):
        original=(self.source/'bottle.png').read_bytes()
        wrong_crc=bytearray(original); wrong_crc[29]^=1
        variants=[b'not PNG',original[:-8],original+b'extra',bytes(wrong_crc)]
        for data in variants:
            (self.source/'bottle.png').write_bytes(data)
            self.save(dict(self.value,sha256=hashlib.sha256(data).hexdigest()))
            with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
            self.assertFalse(self.resources.exists())
        for alpha,pixels in [(False,{(0,0):(1,2,3,255)}),(True,{})]:
            png(self.source/'bottle.png',8,8,pixels,alpha=alpha)
            self.save(dict(self.value,sha256=hashlib.sha256((self.source/'bottle.png').read_bytes()).hexdigest()))
            with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
            self.assertFalse(self.resources.exists())

    def test_escaping_resource_paths_symlinks_and_output_symlinks_are_rejected(self):
        outside=self.folder/'outside.png'; outside.write_bytes((self.source/'bottle.png').read_bytes())
        for name in ['../outside.png',str(outside),'sub/../../outside.png']:
            self.save(dict(self.value,file=name))
            with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
            self.assertFalse(self.resources.exists())
        self.save(self.value); (self.source/'bottle.png').unlink(); (self.source/'bottle.png').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
        (self.source/'bottle.png').unlink(); (self.source/'bottle.png').write_bytes(outside.read_bytes())
        destination=self.folder/'unrelated'; destination.mkdir(); (destination/'keep').write_text('keep')
        self.resources.symlink_to(destination,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Bottle'): self.package()
        self.assertEqual([p.name for p in destination.iterdir()],['keep'])

    def test_copy_failure_keeps_previous_bundle_bottle(self):
        self.package(); before=self.bytes()
        with patch.object(self.build.shutil,'copy2',side_effect=OSError('test copy failure')):
            with self.assertRaises(OSError): self.package()
        self.assertEqual(self.bytes(),before)
        self.assertEqual([p.name for p in self.target.parent.iterdir()],['bottle'])

    def test_real_production_source_passes_and_provenance_is_not_rewritten(self):
        self.source=ROOT/'assets/production/bottle'
        source=ROOT/'assets/incoming/bottle_20261003'
        before={p.name:p.read_bytes() for p in source.iterdir() if p.is_file()}
        self.assertTrue(self.package())
        value=json.loads((self.source/'manifest.json').read_text())
        self.assertEqual(hashlib.sha256((self.target/value['file']).read_bytes()).hexdigest(),value['sha256'])
        self.assertEqual({p.name:p.read_bytes() for p in source.iterdir() if p.is_file()},before)

    def test_build_rejects_missing_required_bottle_before_creating_candidate(self):
        project=self.folder/'project'
        (project/'assets/production/insects').mkdir(parents=True)
        output=self.folder/'Untouched.app'
        with patch.object(self.build,'ROOT',project), \
                patch.object(self.build.sys,'argv',['build_native.py','--output',str(output)]), \
                patch.object(self.build.subprocess,'run',side_effect=AssertionError('No compiler or app may run')):
            with self.assertRaisesRegex(ValueError,'Bottle'):
                self.build.main()
        self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
