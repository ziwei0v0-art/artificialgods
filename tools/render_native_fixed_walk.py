"""Exercise the real native fixed-art walk using isolated service snapshots."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--production-art', action='store_true',
                    help='Read the production A01 manifest directly without injecting a temporary fixedWalk rig.')
args = parser.parse_args()
OUT = ROOT / 'evidence/1.0' / ('157-native-walk-production' if args.production_art else '157-native-walk')
RIG = dict(sourceSize=[489, 978], bodyCutY=882, legStartY=858,
           legSplitX=278, maxRootStep=80, footLift=32)
SWIFT = r'''
import AppKit
import ImageIO
let app=NSApplication.shared; app.setActivationPolicy(.prohibited)
let art=AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[1]))!
let shrine=ShrineArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[2]))!
let output=URL(fileURLWithPath:CommandLine.arguments[3])
precondition(art.hasWalkMotion && !art.hasWalkFrames)
let light=NSColor(calibratedWhite:0.94,alpha:1)
let dark=NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1)
func bitmap(_ w:Int,_ h:Int,_ draw:()->Void)->NSBitmapImageRep {
 let b=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:w,pixelsHigh:h,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:b)
 draw();NSGraphicsContext.restoreGraphicsState();return b
}
func png(_ b:NSBitmapImageRep,_ name:String){try! b.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name))}
func label(_ text:String,_ x:CGFloat,_ y:CGFloat,_ ink:NSColor){
 (text as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:11),.foregroundColor:ink])
}
for size in [64,128] { for (name,bg,ink) in [("light",light,NSColor.darkGray),("dark",dark,NSColor.white)] {
 let scale=CGFloat(size)/shrine.attendantHeight
 let view=TianmuView(frame:NSRect(x:0,y:0,width:370*scale,height:190*scale))
 view.persistLegacyFrame=false;view.attendantArtwork=art;view.shrineArtwork=shrine
 func feed(_ action:String,_ serial:Int,_ elapsed:Double,_ duration:Double,_ clock:Double){
  view.updateAnimation(elapsed:clock)
  precondition(view.applyRoutine(["action":action,"action_serial":serial,"action_elapsed":elapsed,
   "action_duration":duration,"progress":duration>0 ? elapsed/duration : 0,"fruit_stage":"fresh"]))
 }
 func render()->NSBitmapImageRep {
  bitmap(Int(ceil(view.bounds.width)),Int(ceil(view.bounds.height))) {
   view.draw(view.bounds)
   NSGraphicsContext.current!.cgContext.setBlendMode(.destinationOver)
   bg.setFill();view.bounds.fill()
   NSGraphicsContext.current!.cgContext.setBlendMode(.normal)
  }
 }
 // Prime to the right endpoint, so the loop closes without a position reset.
 feed("walk",0,0,5,0);feed("walk",0,5,5,5)
 feed("walk",1,0,5,5);feed("walk",1,5,5,10)
 let destination=CGImageDestinationCreateWithURL(output.appendingPathComponent("scene-\(size)pt-\(name).gif") as CFURL,"com.compuserve.gif" as CFString,180,nil)!
 CGImageDestinationSetProperties(destination,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
 let properties=[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:1.0/15,kCGImagePropertyGIFUnclampedDelayTime:1.0/15]] as CFDictionary
 let samples=[0,9,15,23,38,53,68,75]
 var contacts:[[CGImage]]=[[],[]]
 for leg in 0..<2 {
  let serial=2+leg*2,start=10+Double(leg)*6
  var lastSecond = -1
  for index in 0..<90 {
   let elapsed=Double(index)/15
   view.updateAnimation(elapsed:start+elapsed)
   if index<75 {
    let second=Int(elapsed)
    if second != lastSecond {feed("walk",serial,Double(second),5,start+elapsed);lastSecond=second}
   } else if index==75 {
    feed("walk",serial,5,5,start+5)
    feed("idle",serial+1,0,1,start+5)
   }
   let b=render();CGImageDestinationAddImage(destination,b.cgImage!,properties)
   if samples.contains(index) {
    let box=view.attendantBounds.insetBy(dx:-5,dy:-5)
    let crop=NSRect(x:floor(box.minX),y:floor(view.bounds.height-box.maxY),width:ceil(box.width),height:ceil(box.height))
    contacts[leg].append(b.cgImage!.cropping(to:crop)!)
    if index==23 {png(b,"scene-\(size)pt-\(leg==0 ? "left" : "right")-\(name).png")}
   }
  }
 }
 precondition(CGImageDestinationFinalize(destination))
 let cell=size/2+34,row=size+40,w=cell*8+24,h=row*2+38
 let board=bitmap(w,h){
  bg.setFill();NSRect(x:0,y:0,width:w,height:h).fill()
  label("原生固定原画步行 · \(size) pt · 每秒服务快照 / 连续走停 / 无位置复位",12,CGFloat(h-24),ink)
  for leg in 0..<2 {for i in 0..<8 {
   let image=contacts[leg][i],x=CGFloat(12+i*cell),y=CGFloat(12+(1-leg)*row)
   NSImage(cgImage:image,size:NSSize(width:image.width,height:image.height)).draw(in:NSRect(x:x,y:y+18,width:CGFloat(image.width),height:CGFloat(image.height)))
   label("\(leg==0 ? "向左" : "向右") \(samples[i]<75 ? String(format:"%.1fs",Double(samples[i])/15) : "落脚停下")",x,y,ink)
  }}
 }
 png(board,"contact-\(size)pt-\(name).png")
}
}
print("NATIVE_WALK_RENDER_PASS: actual TianmuView, closed left/right journeys, 1Hz service fixtures, 64/128pt light/dark; no window, worker or save")
'''

OUT.mkdir(exist_ok=True)
source = ROOT / 'assets/production/A01'
manifest_path = source / 'manifest.json'
manifest_bytes = manifest_path.read_bytes()
manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
manifest = json.loads(manifest_bytes)
assert 'walk' not in manifest, 'Withdrawn frame table must not enter this fixture'
original = source / manifest['stand']['file']
digest = hashlib.sha256(original.read_bytes()).hexdigest()
if args.production_art:
    assert isinstance(manifest.get('fixedWalk'), dict), 'Production fixedWalk must already be enabled'
else:
    manifest['fixedWalk'] = RIG
with tempfile.TemporaryDirectory(prefix='tianmu-native-fixed-walk-') as folder:
    work = Path(folder)
    if args.production_art:
        assets = source
    else:
        assets = work / 'A01'; assets.mkdir()
        shutil.copy2(original, assets / original.name)
        (assets / 'manifest.json').write_text(json.dumps(manifest))
    (work / 'Scene.swift').write_text((ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0])
    (work / 'main.swift').write_text(SWIFT)
    subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'ImageIO', str(work / 'Scene.swift'), str(work / 'main.swift'), '-o', str(work / 'render')], check=True)
    subprocess.run([str(work / 'render'), str(assets), str(ROOT / 'assets/production/scene'), str(OUT)], check=True)
assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == manifest_digest
(OUT / 'fixture.json').write_text(json.dumps({'source_sha256': digest, 'rig': manifest['fixedWalk'], 'art_mode': 'production' if args.production_art else 'temporary_rig_fixture', 'source_manifest': str(manifest_path), 'source_manifest_sha256': manifest_digest, 'renderer': 'actual TianmuView', 'snapshots': '1Hz synthetic service data; 5s walk and 1s idle, both directions', 'production_manifest_changed': False, 'no_window': True, 'no_worker': True, 'no_save_access': True}, ensure_ascii=False, indent=2))
