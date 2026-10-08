import hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')];E=ROOT/'evidence/1.0'
modules=['test_brand_packaging','test_ui_art_packaging','test_launch_native','test_recovery_roundtrip','test_native_app','test_timer_controls','test_timer_artifact_panels']
paths=[p for folder in ('native','tianmu_mvp','tools','tests','assets/production') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='.DS_Store']
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p.relative_to(ROOT)):digest(p) for p in paths}
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('tests.'+m) for m in modules)
result=unittest.TextTestRunner(verbosity=2).run(suite)
changed=[n for n,h in hashes.items() if digest(ROOT/n)!=h]
summary={'version':'1.0.5','build':'25','run':result.testsRun,'successful':result.wasSuccessful() and not changed,'modules':modules,'failures':[t.id() for t,_ in result.failures],'errors':[t.id() for t,_ in result.errors],'skipped':[(t.id(),why) for t,why in result.skipped],'source_changed_during_run':changed,'source_hashes':hashes,'broad_gameplay_rerun':False,'physical_acceptance':False,'user_visual_acceptance':False}
(E/'176-targeted-checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('run','successful','source_changed_during_run')},ensure_ascii=False))
raise SystemExit(0 if summary['successful'] else 1)
