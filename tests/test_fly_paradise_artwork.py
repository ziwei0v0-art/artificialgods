"""Exact-source fly renderer contracts without game, NSApplication or window launch."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PRELUDE=r'''
import AppKit
func check(_ value:@autoclosure ()->Bool,_ message:String) { if !value() { print("FAIL: "+message); exit(1) } }
let art=FlyParadiseArtwork.shared
func take(_ color:String="普通褐色",_ sex:String="F",_ heading:Double=Double.pi/2,
          _ motion:FlyParadiseArtwork.Motion = .flying,_ now:Double=0,_ seed:Double=7,_ scale:CGFloat=1)->CGImage {
 let result=art.sample(color:color,sex:sex,heading:heading,motion:motion,now:now,seed:seed,scale:scale)
 check(result != nil,"Expected drawable original fly")
 return result!
}
func pixels(_ image:CGImage)->[UInt8] { Array(image.dataProvider!.data! as Data) }
func difference(_ a:CGImage,_ b:CGImage)->Int { zip(pixels(a),pixels(b)).filter{$0 != $1}.count }
'''


class FlyParadiseArtworkTests(unittest.TestCase):
    def run_swift(self,body):
        with tempfile.TemporaryDirectory(prefix='tianmu-fly-paradise-art-') as temporary:
            folder=Path(temporary); main=folder/'main.swift'; binary=folder/'check'
            main.write_text(PRELUDE+body+'\ncheck(NSApp == nil,"Renderer must not create NSApplication")\n')
            built=subprocess.run(['swiftc','-framework','AppKit',str(ROOT/'native/v1/WindowPlacement.swift'),
                                  str(ROOT/'native/v1/InsectArtwork.swift'),str(main),'-o',str(binary)],
                                 capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
            self.assertIn('PASS:',ran.stdout); print(ran.stdout.strip())

    def test_original_four_palettes_sex_tip_and_explicit_motion_draw_distinctly(self):
        self.run_swift(r'''
var results=[[UInt8]]()
for color in ["普通褐色","中褐色","深褐色","白色"] {
 let image=take(color)
 check(image.width == 48 && image.height == 48,"Original fly uses 24pt 2x canvas")
 check(pixels(image).contains{$0 != 0},"Each palette must draw the original fly")
 results.append(pixels(image))
 check(difference(image,take(color)) == 0,"Same explicit inputs are deterministic")
 check(difference(image,take(color,"M")) > 0,"Original male abdominal tip must be retained")
}
for i in 0..<results.count { for j in (i+1)..<results.count {
 check(results[i] != results[j],"Original four palettes must remain distinct")
} }
check(difference(take(),take("普通褐色","F",Double.pi/2,.resting)) > 0,"Resting switches to original folded wings")
check(difference(take("普通褐色","F",Double.pi/2,.resting),take("普通褐色","F",Double.pi/2,.crawling)) > 0,"Only original resting state grooms front legs")
check(difference(take(),take("普通褐色","F",Double.pi/2,.flying,0.013)) > 0,"Original millisecond wing phase changes")
print("PASS: four original palettes, male tip, explicit flight/folded/grooming and deterministic input")
''')

    def test_appkit_headings_turn_red_eyes_toward_east_north_west_south(self):
        self.run_swift(r'''
for (heading,axis,positive) in [(0.0,0,true),(Double.pi/2,1,false),(Double.pi,0,false),(-Double.pi/2,1,true)] {
 let image=take("普通褐色","F",heading,.crawling), data=pixels(image)
 var count=0, sx=0.0, sy=0.0
 for y in 0..<48 { for x in 0..<48 {
  let i=y*image.bytesPerRow+x*4
  let r=Double(data[i]),g=Double(data[i+1]),b=Double(data[i+2])
  if data[i+3]>80 && r>g*1.8 && r>b*1.8 {
   count += 1; sx += Double(x)+0.5; sy += Double(y)+0.5
  }
 } }
 check(count>0,"Original red eyes must be readable")
 let delta=(axis == 0 ? sx:sy)/Double(count)-24
 check(positive ? delta>2:delta < -2,"Eyes must face actual AppKit heading, no side mirror")
}
print("PASS: original head faces each AppKit cardinal direction")
''')

    def test_invalid_inputs_fail_safely_and_crawling_wings_do_not_animate(self):
        self.run_swift(r'''
check(difference(take("白色","F",0,.crawling,0),take("白色","F",0,.crawling,500)) == 0,"Crawling uses time-independent original folded-wing branch")
check(art.sample(color:"普通褐色",sex:"F",heading:Double.nan,motion:.flying,now:0,seed:0) == nil,"Nonfinite heading is rejected")
check(art.sample(color:"普通褐色",sex:"F",heading:0,motion:.flying,now:Double.infinity,seed:0) == nil,"Nonfinite clock is rejected")
check(art.sample(color:"普通褐色",sex:"F",heading:0,motion:.flying,now:0,seed:0,scale:0) == nil,"Zero scale is rejected")
check(difference(take("unknown"),take()) == 0,"Unknown display color uses upstream wild palette")
check(difference(take("普通褐色","?"),take()) == 0,"Unknown sex does not invent a male tip")
print("PASS: invalid inputs safe, unknown display fields conservative, folded crawling remains static")
''')

    def test_cached_original_poses_keep_heading_opacity_and_bounded_memory(self):
        self.run_swift(r'''
func cached(_ heading:Double,_ opacity:Double=1,_ time:Double=0,_ motion:FlyParadiseArtwork.Motion = .flying,
            _ color:String="普通褐色",_ sex:String="F")->CGImage {
 let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:48,pixelsHigh:48,bitsPerSample:8,
  samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
 NSGraphicsContext.current!.cgContext.scaleBy(x:2,y:2)
 art.drawCached(at:NSPoint(x:12,y:12),color:color,sex:sex,heading:heading,motion:motion,now:time,seed:7,opacity:opacity)
 NSGraphicsContext.restoreGraphicsState();return bitmap.cgImage!
}
for heading in [0.0,Double.pi/2,Double.pi,-Double.pi/2,0.42] {
 let a=pixels(take("普通褐色","F",heading)),b=pixels(cached(heading))
 var intersection=0,union=0
 for i in stride(from:3,to:a.count,by:4) {
  if a[i]>32 && b[i]>32 {intersection+=1}
  if a[i]>32 || b[i]>32 {union+=1}
 }
 check(Double(intersection)/Double(union)>0.78,"Cached upstream shape must preserve full heading and silhouette")
}
let full=pixels(cached(0)),faint=pixels(cached(0,0.25))
let fullAlpha=stride(from:3,to:full.count,by:4).reduce(0){$0+Int(full[$1])}
let faintAlpha=stride(from:3,to:faint.count,by:4).reduce(0){$0+Int(faint[$1])}
check(abs(Double(faintAlpha)/Double(fullAlpha)-0.25)<0.02,"Source-over cached images must respect admission fade")
for color in ["普通褐色","中褐色","深褐色","白色"] {for sex in ["F","M"] {
 for motion:FlyParadiseArtwork.Motion in [.flying,.resting,.crawling] {
  for tick in 0..<140 {_ = cached(Double(tick),1,Double(tick)/31,motion,color,sex)}
 }
}}
check(art.cachedPoseCount<=392,"Cache must remain bounded independently of timestamp, heading or individual ID")
print("PASS: cached upstream poses preserve heading/silhouette/fade with at most 392 RGBA 48x48 images")
''')


if __name__=='__main__': unittest.main()
