"""Same 60-second input and optimized compiler for old/new unshown native layers.

Draws each version's actual idle views into reused bitmaps: the old full desktop
view, or the new three small sprite views. No compositor/GPU timing is inferred.
No app bundle, visible window, worker, real input or save is opened.
"""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
import AppKit
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
var now=10.0
let frame=NSRect(x:0,y:0,width:1920,height:1080)
let layer=DesktopInsects(motionModuleURL:URL(fileURLWithPath:CommandLine.arguments[1]),
 screens:[DesktopInsectScreen(id:"main",frame:frame)],renderTime:{now},windowPresenter:{_ in})
var rows=[[String:Any]]()
for index in 0..<12 {
 let id="adult-\(index)",x=Double(index+1)/13.0,y=Double(index%3+1)/4.0
 let color=["普通褐色","中褐色","深褐色","白色"][index%4],sex=index%2==0 ? "F":"M"
 rows.append(["id":id,"x":x,"y":y,"color":color,"sex":sex])
}
layer.update(rows:rows)
let drawWindows=DRAW_WINDOWS
let bitmaps=drawWindows.map {window in
 NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(window.frame.width),pixelsHigh:Int(window.frame.height),bitsPerSample:8,
 samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
}
var refreshTime=0.0,drawTime=0.0
let start=ProcessInfo.processInfo.systemUptime
for _ in 0..<1800 {
 now+=1.0/30
 let beforeRefresh=ProcessInfo.processInfo.systemUptime;layer.refresh()
 refreshTime+=ProcessInfo.processInfo.systemUptime-beforeRefresh
 let beforeDraw=ProcessInfo.processInfo.systemUptime
 for (index,window) in drawWindows.enumerated() {
  NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmaps[index])
  let view=window.contentView!;view.draw(view.bounds);NSGraphicsContext.restoreGraphicsState()
 }
 drawTime+=ProcessInfo.processInfo.systemUptime-beforeDraw
}
let wall=ProcessInfo.processInfo.systemUptime-start
guard (layer.windows+drawWindows).allSatisfy({!$0.isVisible && !$0.isKeyWindow}) else {exit(1)}
let report:[String:Any]=["frames":1800,"duration":60,"realIDs":layer.positions.count,
 "refreshWallSeconds":refreshTime,"drawWallSeconds":drawTime,"combinedWallSeconds":wall,
 "idleBitmapPixels":bitmaps.reduce(0){$0+$1.pixelsWide*$1.pixelsHigh}]
print(String(data:try JSONSerialization.data(withJSONObject:report,options:[.sortedKeys]),encoding:.utf8)!)
layer.close()
'''

def measure(base,repeats=3):
    with tempfile.TemporaryDirectory(prefix='tianmu-native171-') as temp:
        folder=Path(temp)
        views='layer.spriteWindows' if base==ROOT else 'layer.windows'
        (folder/'main.swift').write_text(HARNESS.replace('DRAW_WINDOWS',views))
        source=base/'native/v1'
        sources=[source/name if (source/name).exists() else ROOT/'native/v1'/name for name in ['WindowPlacement.swift','InsectArtwork.swift','DesktopInsects.swift']]
        subprocess.run(['swiftc','-O','-framework','AppKit',*map(str,sources),str(folder/'main.swift'),'-o',str(folder/'check')],check=True,capture_output=True,text=True,timeout=60)
        samples=[]
        for _ in range(repeats):
            run=subprocess.run([str(folder/'check'),str(base/'third_party/fly-paradise/desktop-motion.js')],check=True,capture_output=True,text=True,timeout=60)
            samples.append(json.loads(run.stdout.splitlines()[-1]))
        return samples

def main():
    report={'before':measure(ROOT/'evidence/1.0/171-before'),'after':measure(ROOT),
      'boundary':'Optimized -O both. Actual idle view paths into reused 1x bitmaps: old full 1920x1080 vs new three 40x40 views. All windows unshown. Synthetic 12 ID/60s/30Hz input. Not application CPU percent, RSS or compositor timing.'}
    (ROOT/'evidence/1.0/171-native-insect-cost.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
