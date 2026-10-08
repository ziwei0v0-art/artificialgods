"""Required original desktop motion must be valid before a candidate is created."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def builder():
    spec = importlib.util.spec_from_file_location('motion_builder',ROOT/'tools/build_native.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopMotionPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tianmu-motion-package-')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder/'source'
        shutil.copytree(ROOT/'third_party/fly-paradise',self.source)
        for path in self.source.rglob('*'):
            if path.is_file(): path.chmod(path.stat().st_mode | 0o200)
        self.build = builder()

    def validate(self):
        self.assertTrue(callable(getattr(self.build,'_validated_desktop_motion_files',None)),
                        'Build must validate the required desktop motion module before creating a candidate')
        return self.build._validated_desktop_motion_files(self.source)

    def test_real_module_executes_and_source_provenance_is_unchanged(self):
        before = {str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        result = self.validate()
        self.assertIn('desktop-motion.js',result)
        self.assertIn('upstream/renderer/overlay.js',result)
        self.assertIn('NOTICE.md',result)
        self.assertEqual({str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()},before)

    def test_missing_bad_source_or_manifest_is_rejected(self):
        for name in ('desktop-motion.js','source-manifest.json','NOTICE.md','upstream/renderer/overlay.js'):
            path = self.source/name; original = path.read_bytes()
            with self.subTest(missing=name):
                path.unlink()
                try:
                    with self.assertRaisesRegex(ValueError,'Desktop motion'): self.validate()
                finally:
                    path.write_bytes(original)
        overlay = self.source/'upstream/renderer/overlay.js'
        overlay.write_bytes(overlay.read_bytes()+b'\n// different source\n')
        with self.assertRaisesRegex(ValueError,'Desktop motion'): self.validate()

    def test_modified_original_function_and_parseable_but_broken_adapter_are_rejected(self):
        path = self.source/'desktop-motion.js'; original=path.read_text()
        variants = [original.replace('function stepFly(fly, dt, now) {','function stepFly(fly, dt, now) { /* changed */',1),
                    original+'\nthis is not valid JavaScript }',
                    original+'\nglobalThis.TianmuFlyMotion.step = () => [];',
                    original+'\nglobalThis.TianmuFlyMotion.reset = undefined;']
        for text in variants:
            with self.subTest(variant=text[-90:]):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError,'Desktop motion'): self.validate()
        path.write_text(original)

    def test_bundle_is_validated_and_byte_identical_to_preflight_source(self):
        expected = self.validate()
        bundle = self.folder/'Contents/Resources/backend/third_party/fly-paradise'
        shutil.copytree(self.source,bundle)
        self.assertTrue(callable(getattr(self.build,'_validate_bundled_desktop_motion',None)),
                        'Copied motion resources must be checked before reporting build success')
        self.build._validate_bundled_desktop_motion(bundle,expected)
        module = bundle/'desktop-motion.js'
        module.write_text(module.read_text()+'\n// accidental different wrapper\n')
        with self.assertRaisesRegex(ValueError,'Desktop motion'): self.build._validate_bundled_desktop_motion(bundle,expected)
        module.unlink()
        with self.assertRaisesRegex(ValueError,'Desktop motion'): self.build._validate_bundled_desktop_motion(bundle,expected)

    def test_main_rejects_missing_motion_before_output_directory_or_compiler(self):
        project = self.folder/'project'
        (project/'assets/production/insects').mkdir(parents=True)
        # Include the required brand resource so this fixture reaches the motion preflight.
        shutil.copytree(ROOT/'assets/production/brand', project/'assets/production/brand')
        output = self.folder/'NotCreated.app'
        # The independent bottle validator is already covered by bottle packaging tests.
        with patch.object(self.build,'ROOT',project), \
             patch.object(self.build.sys,'argv',['build_native.py','--output',str(output)]), \
             patch.object(self.build,'_validated_bottle_files',return_value={}), \
             patch.object(self.build,'copy_insect_art',side_effect=AssertionError('Candidate must not be created')), \
             patch.object(self.build.subprocess,'run',side_effect=AssertionError('Compiler must not run')):
            with self.assertRaisesRegex(ValueError,'Desktop motion'): self.build.main()
        self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
