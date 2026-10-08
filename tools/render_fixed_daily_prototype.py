"""AppKit study of daily gestures using original parts and generated props only."""
from pathlib import Path
import ast,hashlib,json,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/1.0/159-fixed-daily-prototype'
# Reuse the read-only source loader/alpha masks from the successful catch study.
tree=ast.parse((ROOT/'tools/render_fixed_catch_prototype.py').read_text())
shared=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SWIFT' for t in n.targets))
SWIFT=shared.split('let base=extracted(false),arm=extracted(true)')[0]+r'''
let farMask=polygon([(345,603),(489,603),(489,815),(395,815),(381,785),(370,725),(351,663)])
let headMask=CGPath(rect:NSRect(x:0,y:0,width:W,height:568),transform:nil)
func part(_ name:String)->CGImage {
 let rep=NSBitmapImageRep(cgImage:src),b=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:W,pixelsHigh:H,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 for y in 0..<H {for x in 0..<W {let p=CGPoint(x:Double(x)+0.5,y:Double(y)+0.5),near=sleeveMask.contains(p),far=farMask.contains(p),head=headMask.contains(p)
 let yes=name=="near" ? near:name=="far" ? far:name=="head" ? head:(!near && !far && !head)
 if yes {b.setColor(rep.colorAt(x:x,y:y)!,atX:x,y:y)}}};return b.cgImage!
}
let base=part("base"),near=part("near"),far=part("far"),head=part("head")
let np=CGPoint(x:217,y:591),nh=CGPoint(x:181,y:797),fp=CGPoint(x:348,y:633),fh=CGPoint(x:425,y:782),hp=CGPoint(x:296,y:556)
let names=["book","broom","incense-stick","paper-slip","bell"]
var props=[String:CGImage]()
for name in names {props[name]=visibleCrop(load("assets/incoming/A01_daily_props_20261001/\(name)-v01-original.png"))}
props["fruit"]=load("assets/production/scene/G0-fruit-fresh-v01.png",NSRect(x:372,y:191,width:822,height:637))
func smooth(_ x:Double)->Double{let t=min(1,max(0,x));return t*t*(3-2*t)}
func posed(_ p:CGPoint,_ pivot:CGPoint,_ angle:Double,_ scale:Double=1)->CGPoint {
 let a=angle*Double.pi/180,dx=Double(p.x-pivot.x)*scale,dy=Double(p.y-pivot.y)*scale
 return CGPoint(x:Double(pivot.x)+dx*cos(a)-dy*sin(a),y:Double(pivot.y)+dx*sin(a)+dy*cos(a))
}
func rotatePart(_ image:CGImage,_ pivot:CGPoint,_ degrees:Double,_ scale:Double=1){
 let c=NSGraphicsContext.current!.cgContext;c.saveGState();c.translateBy(x:pivot.x,y:pivot.y);c.rotate(by:degrees*Double.pi/180);c.scaleBy(x:scale,y:scale);c.translateBy(x:-pivot.x,y:-pivot.y);drawImage(image,full);c.restoreGState()
}
let durations:[String:Double]=["read":18,"sweep":12,"practice":45,"offer":8,"bell":4,"rest":60,"incense":2,"paper":2,"response":1.1]
func gesture(_ action:String,_ t:Double,_ displayHeight:Double){
 let duration=durations[action]!,edge=min(0.55,duration*0.24),amount=smooth(t/edge)*(1-smooth((t-duration+edge)/edge))
 if amount<0.000001 {drawImage(src,full);return}
 var na = -40.0*amount,fa=0.0,fs=1.0,ha=0.0
 switch action {
 case "read":na = -43*amount;fa=24*amount;fs=1-0.2*amount;ha=3*amount
 case "practice":na = -46*amount;fa=28*amount;fs=1-0.2*amount;ha=(4+3*sin(t*Double.pi/5))*amount
 case "offer":na = -43*amount;fa=24*amount;fs=1-0.2*amount;ha=3*amount
 case "sweep":na = (-60+8*sin(t*Double.pi*1.3))*amount;ha=2*amount
 case "bell":na = (-85+12*sin(t*Double.pi*4))*amount;ha=0
 case "rest":na=0;ha=(8+0.8*sin(t*Double.pi/5))*amount
 case "incense":na = -47*amount;fa=22*amount;fs=1-0.2*amount;ha=6*amount
 case "paper":na = -61*amount;ha=2*amount
 case "response":na = -40*amount;fa=24*amount;fs=1-0.2*amount;ha=6*amount
 default:break
 }
 let c=NSGraphicsContext.current!.cgContext
 if action=="rest" {
  // Only the original head tilts. Keep the whole original lower robe, arms and legs.
  c.saveGState();c.clip(to:NSRect(x:0,y:568,width:W,height:H-568));drawImage(src,full);c.restoreGState();rotatePart(head,hp,ha);return
 }
 c.saveGState();let missing=CGMutablePath();missing.addPath(sleeveMask);missing.addPath(farMask);c.addPath(missing);c.clip();c.addPath(bodyArea);c.clip();drawImage(torso,NSRect(x:194,y:555,width:218,height:313));c.restoreGState()
 drawImage(base,full);rotatePart(head,hp,ha);rotatePart(far,fp,fa,fs)
 let hand=posed(nh,np,na)
 func prop(_ name:String,_ h:Double,_ grip:CGPoint,_ rotation:Double=0,_ minWidth:Double=0){
  let im=props[name]!,height=h*amount,width=max(minWidth,height*Double(im.width)/Double(im.height))
  c.saveGState();c.setAlpha(amount);c.translateBy(x:hand.x,y:hand.y);c.rotate(by:rotation*Double.pi/180)
  drawImage(im,NSRect(x:-width*Double(grip.x),y:-height*Double(grip.y),width:width,height:height));c.restoreGState()
 }
 rotatePart(near,np,na)
 switch action {
 case "read":prop("book",100,CGPoint(x:0.5,y:0.9))
 case "offer":prop("fruit",130,CGPoint(x:0.5,y:0.9))
 case "sweep":
  let im=props["broom"]!,angle=(-20+8*sin(t*Double.pi*1.3)),a=angle*Double.pi/180
  // Use the actual ground as the broom's lower anchor, including its swing.
  let h=(976-Double(hand.y))/(0.70*cos(a)),w=h*Double(im.width)/Double(im.height)
  c.saveGState();c.setAlpha(amount);c.translateBy(x:hand.x,y:hand.y);c.rotate(by:a);drawImage(im,NSRect(x:-w*0.5,y:-h*0.30,width:w,height:h));c.restoreGState()
 case "bell":prop("bell",170,CGPoint(x:0.5,y:0.13),18*sin(t*Double.pi*4))
 case "incense":prop("incense-stick",240,CGPoint(x:0.5,y:0.92),15,1.5*Double(H)/displayHeight)
 case "paper":prop("paper-slip",165,CGPoint(x:0.5,y:0.9))
 default:break
 }
 if ["read","offer","sweep","bell","incense","paper"].contains(action) {
  c.saveGState();c.translateBy(x:np.x,y:np.y);c.rotate(by:na*Double.pi/180);c.translateBy(x:-np.x,y:-np.y)
  c.clip(to:NSRect(x:155,y:779,width:48,height:29));drawImage(src,full);c.restoreGState()
 }
}
let light=NSColor(calibratedWhite:0.94,alpha:1),dark=NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1)
func frame(_ action:String,_ t:Double,_ height:Int,_ bg:NSColor)->NSBitmapImageRep {
 let s=CGFloat(height)/CGFloat(H),w=Int(ceil(850*s))+22,h=height+26
 return bitmap(w,h){bg.setFill();NSRect(x:0,y:0,width:w,height:h).fill();let c=NSGraphicsContext.current!.cgContext;c.translateBy(x:11+100*s,y:CGFloat(h-12));c.scaleBy(x:s,y:-s);gesture(action,t,Double(height))}
}
let actions=["read","sweep","practice","offer","bell","rest","incense","paper","response"]
for size in [64,128] {for(name,bg)in[("light",light),("dark",dark)]{
 let cw=Int(ceil(850*CGFloat(size)/CGFloat(H)))+22,ch=size+48
 let board=bitmap(cw*5,ch*actions.count){bg.setFill();NSRect(x:0,y:0,width:cw*5,height:ch*actions.count).fill()
  for(row,action)in actions.enumerated(){let d=durations[action]!,times=[0,d*0.15,d*0.4,d*0.8,d]
   for(i,t)in times.enumerated(){let b=frame(action,t,size,bg),y=(actions.count-1-row)*ch+22
    NSImage(cgImage:b.cgImage!,size:NSSize(width:b.pixelsWide,height:b.pixelsHigh)).draw(in:NSRect(x:i*cw,y:y,width:b.pixelsWide,height:b.pixelsHigh))
    ("\(action) "+String(format:"%.1fs",t) as NSString).draw(at:NSPoint(x:i*cw+6,y:y-17),withAttributes:[.font:NSFont.systemFont(ofSize:10),.foregroundColor:name=="dark" ? NSColor.white:NSColor.darkGray])
   }
  }
 }
 png(board,"contact-\(size)pt-\(name).png")
}}
for action in actions {
 let d=durations[action]!,samples=min(120,max(30,Int(d*15))),dest=CGImageDestinationCreateWithURL(out.appendingPathComponent("\(action)-128pt-light.gif") as CFURL,"com.compuserve.gif" as CFString,samples,nil)!
 CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
 for i in 0..<samples {let t=Double(i)/Double(samples-1)*d
 CGImageDestinationAddImage(dest,frame(action,t,128,light).cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:d/Double(samples)]] as CFDictionary)}
 precondition(CGImageDestinationFinalize(dest))
 png(frame(action,min(1.1,d*0.4),384,light),"\(action)-384pt.png")
}
print("DAILY_PROTOTYPE_PASS: original head/limbs only, all source PNGs retained; isolated AppKit; no window/worker/save; not a production scene")
'''
OUT.mkdir(parents=True,exist_ok=True)
paths=[ROOT/'assets/production/A01/stand-pixel-20261001.png',*sorted((ROOT/'assets/incoming/A01_daily_props_20261001').glob('*.png'))]
digests={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
with tempfile.TemporaryDirectory(prefix='tianmu-daily-study-') as td:
 work=Path(td);(work/'main.swift').write_text(SWIFT)
 subprocess.run(['swiftc','-framework','AppKit','-framework','ImageIO',str(work/'main.swift'),'-o',str(work/'render')],check=True)
 subprocess.run([str(work/'render'),str(ROOT),str(OUT)],check=True)
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in digests.items())
(OUT/'fixture.json').write_text(json.dumps({'source_sha256':digests,'status':'visual prototype only; not production; poses pending review','head_regenerated':False,'no_window_worker_save':True},ensure_ascii=False,indent=2))
