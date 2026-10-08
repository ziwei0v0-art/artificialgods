"""AppKit-only fixed-original catch study; writes review artifacts, never source art."""
from pathlib import Path
import hashlib, json, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/1.0/158-fixed-catch-prototype'
SWIFT=r'''
import AppKit
import ImageIO
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let root=URL(fileURLWithPath:CommandLine.arguments[1]),out=URL(fileURLWithPath:CommandLine.arguments[2])
let W=489,H=978
func load(_ path:String,_ rect:NSRect?=nil)->CGImage {
 let b=NSBitmapImageRep(data:try! Data(contentsOf:root.appendingPathComponent(path)))!
 if let rect {return b.cgImage!.cropping(to:rect)!};return b.cgImage!
}
func visibleCrop(_ im:CGImage)->CGImage{
 let b=NSBitmapImageRep(cgImage:im);var x0=im.width,y0=im.height,x1=0,y1=0
 for y in 0..<im.height {for x in 0..<im.width {if (b.colorAt(x:x,y:y)?.alphaComponent ?? 0)>16.0/255 {x0=min(x0,x);y0=min(y0,y);x1=max(x1,x);y1=max(y1,y)}}}
 return im.cropping(to:NSRect(x:max(0,x0-2),y:max(0,y0-2),width:min(im.width,x1+3)-max(0,x0-2),height:min(im.height,y1+3)-max(0,y0-2)))!
}
let src=load("assets/production/A01/stand-pixel-20261001.png",NSRect(x:318,y:356,width:W,height:H))
let torso=visibleCrop(load("assets/incoming/A01_action_parts_20261001/torso-underlay-v01-original.png"))
let net=visibleCrop(load("assets/incoming/A01_action_parts_20261001/net-v01-original.png"))
func polygon(_ points:[(CGFloat,CGFloat)])->CGPath {let p=CGMutablePath();p.move(to:CGPoint(x:points[0].0,y:points[0].1));for pt in points.dropFirst(){p.addLine(to:CGPoint(x:pt.0,y:pt.1))};p.closeSubpath();return p}
let sleeveMask=polygon([(0,583),(235,583),(235,610),(265,640),(265,734),(250,766),(218,803),(218,846),(212,861),(0,861)])
let bodyArea=polygon([(218,568),(330,566),(360,620),(390,862),(195,862),(190,758),(205,646)])
func bitmap(_ w:Int,_ h:Int,_ draw:()->Void)->NSBitmapImageRep{
 let b=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:w,pixelsHigh:h,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:b);NSGraphicsContext.current!.cgContext.setShouldAntialias(false);draw();NSGraphicsContext.restoreGraphicsState();return b
}
func png(_ b:NSBitmapImageRep,_ name:String){try! b.representation(using:.png,properties:[:])!.write(to:out.appendingPathComponent(name))}
// Top-left source-pixel coordinates are identical to the accepted sourceRect.
func drawImage(_ image:CGImage,_ box:CGRect){
 let c=NSGraphicsContext.current!.cgContext;c.saveGState();c.translateBy(x:box.minX,y:box.maxY);c.scaleBy(x:1,y:-1);c.interpolationQuality = .none;c.draw(image,in:CGRect(x:0,y:0,width:box.width,height:box.height));c.restoreGState()
}
let full=NSRect(x:0,y:0,width:W,height:H)
func extracted(_ include:Bool)->CGImage {
 let rep=NSBitmapImageRep(cgImage:src),b=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:W,pixelsHigh:H,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 for y in 0..<H {for x in 0..<W {if sleeveMask.contains(CGPoint(x:Double(x)+0.5,y:Double(y)+0.5))==include {b.setColor(rep.colorAt(x:x,y:y)!,atX:x,y:y)}}}
 return b.cgImage!
}
let base=extracted(false),arm=extracted(true)
let pivot=CGPoint(x:217,y:591),hand=CGPoint(x:181,y:797)
func smooth(_ x:Double)->Double{let t=min(1,max(0,x));return t*t*(3-2*t)}
func pose(_ t:Double)->(Double,Double){
 // Take out, swing forward once, draw the net back, then put it away.
 let entry=smooth(t/0.42),exit=1-smooth((t-2.5)/0.5)
 let reach=smooth((t-0.5)/0.55)*(1-smooth((t-1.25)/0.65))
 return ((-40-35*reach)*entry*exit,entry*exit)
}
func character(_ t:Double,_ repaired:Bool){
 let (degrees,visible)=pose(t),c=NSGraphicsContext.current!.cgContext
 if visible<0.000001 {drawImage(src,full);return}
 if repaired {c.saveGState();c.addPath(sleeveMask);c.clip();c.addPath(bodyArea);c.clip();drawImage(torso,NSRect(x:194,y:555,width:218,height:313));c.restoreGState()}
 drawImage(base,full)
 c.saveGState();c.translateBy(x:pivot.x,y:pivot.y);c.rotate(by:degrees*Double.pi/180);c.translateBy(x:-pivot.x,y:-pivot.y)
 // Shaft stays under the original hand; no synthetic caught insect is added.
 c.saveGState();c.setAlpha(visible)
 c.translateBy(x:hand.x,y:hand.y);c.rotate(by:110*Double.pi/180);c.translateBy(x:-hand.x,y:-hand.y)
 let nh=400.0*visible,nw=nh*Double(net.width)/Double(net.height)
 drawImage(net,NSRect(x:Double(hand.x)-nw*0.32,y:Double(hand.y)-nh*0.89,width:nw,height:nh))
 c.restoreGState();drawImage(arm,full);c.restoreGState()
}
let light=NSColor(calibratedWhite:0.94,alpha:1),dark=NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1)
func frame(_ t:Double,_ height:Int,_ bg:NSColor,_ repaired:Bool)->NSBitmapImageRep{
 let scale=CGFloat(height)/CGFloat(H),width=Int(ceil(960*scale))+24,h=height+26
 return bitmap(width,h){bg.setFill();NSRect(x:0,y:0,width:width,height:h).fill();let c=NSGraphicsContext.current!.cgContext;c.translateBy(x:12+160*scale,y:CGFloat(h-12));c.scaleBy(x:scale,y:-scale);character(t,repaired)}
}
for size in [64,128] {for (name,bg) in [("light",light),("dark",dark)] {
 let times=[0.0,0.35,0.8,1.05,1.5,2.2,2.65,3.0]
 let frames=times.map{frame($0,size,bg,true)},cw=frames[0].pixelsWide,ch=frames[0].pixelsHigh
 let contact=bitmap(cw*8,ch+30){bg.setFill();NSRect(x:0,y:0,width:cw*8,height:ch+30).fill();for(i,f)in frames.enumerated(){NSImage(cgImage:f.cgImage!,size:NSSize(width:cw,height:ch)).draw(in:NSRect(x:i*cw,y:25,width:cw,height:ch));(String(format:"%.2fs",times[i]) as NSString).draw(at:NSPoint(x:i*cw+10,y:7),withAttributes:[.font:NSFont.systemFont(ofSize:10),.foregroundColor:name=="dark" ? NSColor.white:NSColor.darkGray])}}
 png(contact,"contact-\(size)pt-\(name).png")
 let dest=CGImageDestinationCreateWithURL(out.appendingPathComponent("catch-\(size)pt-\(name).gif") as CFURL,"com.compuserve.gif" as CFString,60,nil)!
 CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
 for i in 0..<60 {let t=min(3,Double(i)/15);CGImageDestinationAddImage(dest,frame(t,size,bg,true).cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:1.0/15]] as CFDictionary)}
 precondition(CGImageDestinationFinalize(dest))
}}
png(frame(1.05,384,light,false),"unfilled-384pt.png");png(frame(1.05,384,light,true),"repaired-384pt.png")
print("FIXED_CATCH_PROTOTYPE: original head/body retained, original sleeve rotated, generated torso only clipped under removed inner sleeve; isolated AppKit, no window, worker, or save")
'''
OUT.mkdir(parents=True,exist_ok=True)
paths=[ROOT/'assets/production/A01/stand-pixel-20261001.png',*sorted((ROOT/'assets/incoming/A01_action_parts_20261001').glob('*.png'))]
digests={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
with tempfile.TemporaryDirectory(prefix='tianmu-catch-study-') as td:
 work=Path(td);(work/'main.swift').write_text(SWIFT)
 subprocess.run(['swiftc','-framework','AppKit','-framework','ImageIO',str(work/'main.swift'),'-o',str(work/'render')],check=True)
 subprocess.run([str(work/'render'),str(ROOT),str(OUT)],check=True)
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in digests.items())
(OUT/'fixture.json').write_text(json.dumps({'source_sha256':digests,'type':'visual prototype only; not production TianmuView','production_changed':False,'head_regenerated':False,'no_window_worker_save':True},ensure_ascii=False,indent=2))
