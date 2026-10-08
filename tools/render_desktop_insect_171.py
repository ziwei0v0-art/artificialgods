"""Compare production cached desktop drawing with pinned original JS off screen."""
from pathlib import Path
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('original_fly_review',ROOT/'tools/render_fly_paradise_reference.py')
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
reference.OUT=ROOT/'evidence/1.0/171-fly-paradise-comparison'
old=''' let image = FlyParadiseArtwork.shared.sample(color:item["color"] as! String, sex:item["sex"] as! String,
  heading:item["heading"] as! Double, motion:motion, now:item["now"] as! Double,
  seed:item["seed"] as! Double, scale:item["scale"] as! Double)!'''
new=''' let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:48,pixelsHigh:48,bitsPerSample:8,
  samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
 NSGraphicsContext.current!.cgContext.scaleBy(x:2,y:2)
 FlyParadiseArtwork.shared.drawCached(at:NSPoint(x:12,y:12),color:item["color"] as! String,sex:item["sex"] as! String,
  heading:item["heading"] as! Double,motion:motion,now:item["now"] as! Double,
  seed:item["seed"] as! Double,scale:item["scale"] as! Double)
 NSGraphicsContext.restoreGraphicsState()
 let image=bitmap.cgImage!'''
assert old in reference.NATIVE
reference.NATIVE=reference.NATIVE.replace(old,new)
if __name__=='__main__':reference.main()
