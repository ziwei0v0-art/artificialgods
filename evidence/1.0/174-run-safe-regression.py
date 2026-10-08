"""Release regression: omit known visible legacy apps and old evidence writers."""
import hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests"))
excluded_modules={'test_ui','test_native_reminder'}
excluded_methods={
 'test_native_overlay.NativeOverlayTests.test_native_host_builds_and_announces_transparent_desktop_layer',
 'test_native_overlay.NativeOverlayTests.test_native_host_accepts_mode_commands_and_exits_cleanly',
}
def flatten(suite):
 for item in suite:
  if isinstance(item,unittest.TestSuite):yield from flatten(item)
  else:yield item
source_paths = [p for folder in ['native','tianmu_mvp','tools','tests'] for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc',) and p.name != '.DS_Store']
source_hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
all_tests=list(flatten(unittest.defaultTestLoader.discover(str(ROOT/'tests'))))
kept=[];excluded=[]
for item in all_tests:
 name=item.id()
 (excluded if name.split('.')[0] in excluded_modules or name in excluded_methods else kept).append(item)
print('Excluded known visible/legacy-evidence tests:',*[x.id() for x in excluded],sep='\n',flush=True)
result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(kept))
source_changed = [name for name,digest in source_hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
summary={'source_hashes':source_hashes,'source_changed_during_run':source_changed,'run':result.testsRun,'failures':[x.id() for x,_ in result.failures], 'errors':[x.id() for x,_ in result.errors], 'skipped':[(x.id(),reason) for x,reason in result.skipped], 'excluded':[x.id() for x in excluded], 'successful':result.wasSuccessful()}
(ROOT/'evidence/1.0/174-safe-regression-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(0 if result.wasSuccessful() else 1)
