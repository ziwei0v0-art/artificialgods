"""Reproducible presentation-only 60 second comparison; no windows, workers or saves."""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNNER = r'''
import Foundation
import JavaScriptCore
let context = JSContext()!
context.exceptionHandler = { _, error in print(error?.toString() ?? "JS error"); exit(1) }
context.evaluateScript(try String(contentsOfFile:CommandLine.arguments[1],encoding:.utf8))
let start = ProcessInfo.processInfo.systemUptime
let value = context.evaluateScript(try String(contentsOfFile:CommandLine.arguments[2],encoding:.utf8))!
let elapsed = ProcessInfo.processInfo.systemUptime - start
print(value.toString()!)
print(elapsed)
'''
FIXTURE = r'''
(function() {
 const api=TianmuFlyMotion, rate=30, duration=60;
 const rows=Array.from({length:12},(_,i)=>({id:'adult-'+i,seed:String(7501+i*97),x:160+i*132,y:220+(i%3)*250,sex:i%2?'m':'f'}));
 const screens=[{id:'main',x:0,y:0,w:1920,h:1080}];
 const icons=[];
 for(const x of [0,944,1888]) for(const y of [0,524,1048]) if(x!==944||y!==524) icons.push({id:'site-'+x+'-'+y,name:'site',x,y,w:32,h:32});
 let speeds=[],rest=0,visibleFrames=0,longest=0,maxVisible=0,maxFlying=0,seen=new Set(),last={},stays={},timeline=[],countPreserved=true,previousAlpha={},maxAlphaJump=0;
 for(let frame=0;frame<=duration*rate;frame++) {
  const result=api.step({rows,screens,icons,pointer:{enabled:false},suppressThreat:false,time:10+frame/rate});
  countPreserved=countPreserved&&result.length===rows.length&&new Set(result.map(r=>r.id)).size===rows.length;
  let visible=0,flying=0;
  for(const r of result) {
   const alpha=r.opacity===undefined?1:r.opacity;
   if(previousAlpha[r.id]!==undefined) maxAlphaJump=Math.max(maxAlphaJump,Math.abs(alpha-previousAlpha[r.id]));
   previousAlpha[r.id]=alpha;
   if(alpha>0.001) {
    visible++;seen.add(r.id);visibleFrames++;
    if(r.activity==='flying') {flying++;speeds.push(Math.hypot(r.vx,r.vy));}
    if(r.activity==='resting') rest++;
    if(r.activity==='resting'&&last[r.id]&&r.x===last[r.id].x&&r.y===last[r.id].y) stays[r.id]=(stays[r.id]||0)+1/rate;
    else stays[r.id]=0;
    longest=Math.max(longest,stays[r.id]);
   } else stays[r.id]=0;
   last[r.id]=r;
  }
  maxVisible=Math.max(maxVisible,visible);maxFlying=Math.max(maxFlying,flying);
  if(frame%rate===0) timeline.push({second:frame/rate,visible,flying});
 }
 speeds.sort((a,b)=>a-b);
 return JSON.stringify({seed:'7501+i*97',duration,rate,authoritativeIDs:12,countPreserved,seenIDs:seen.size,
  meanFlyingSpeed:speeds.reduce((a,b)=>a+b,0)/Math.max(1,speeds.length),p95FlyingSpeed:speeds[Math.floor(speeds.length*.95)]||0,
  maxFlyingSpeed:speeds.at(-1)||0,restTimeRatio:rest/Math.max(1,visibleFrames),longestContinuousRestSeconds:longest,
  maxVisible,maxFlying,maxAlphaJump,timeline});
})();
'''

def measure(module, repeats=3):
    with tempfile.TemporaryDirectory(prefix='tianmu-insect-171-') as temporary:
        folder=Path(temporary)
        (folder/'main.swift').write_text(RUNNER)
        (folder/'fixture.js').write_text(FIXTURE)
        subprocess.run(['swiftc','-O','-framework','JavaScriptCore',str(folder/'main.swift'),'-o',str(folder/'check')],check=True,capture_output=True,text=True)
        times=[]
        for _ in range(repeats):
            result=subprocess.run([str(folder/'check'),str(module),str(folder/'fixture.js')],check=True,capture_output=True,text=True)
            lines=result.stdout.splitlines()
            metrics=json.loads(lines[-2]);times.append(float(lines[-1]))
        metrics['simulationWallSeconds']=times
        return metrics

def main():
    old=ROOT/'evidence/1.0/171-before/third_party/fly-paradise/desktop-motion.js'
    new=ROOT/'third_party/fly-paradise/desktop-motion.js'
    report={'before':measure(old),'after':measure(new),'boundary':'simulation wall time only; no visible application or GPU/compositor measurement'}
    target=ROOT/'evidence/1.0/171-motion-comparison.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:{k:v for k,v in value.items() if k!='timeline'} for key,value in report.items() if isinstance(value,dict)},indent=2))

if __name__=='__main__':main()
