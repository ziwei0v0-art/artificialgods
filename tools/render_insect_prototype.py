"""Read-only offscreen insect size, recolor and frame-anchor prototypes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CUTE = ROOT / 'assets/incoming/insects_oga_20261001/greyfly_spritesheet-original.png'
REALISTIC = ROOT / 'assets/incoming/insects_realistic_20261001/realistic-base-v01-original.png'
BODY = ROOT / 'assets/incoming/insects_realistic_20261001/realistic-body-v01-original.png'
WINGS = ROOT / 'assets/incoming/insects_realistic_20261001/realistic-wings-v01-original.png'
OUT = ROOT / 'evidence/1.0/161-insect-prototype'

SWIFT = r'''
import AppKit
import ImageIO
import CryptoKit
let cuteURL=URL(fileURLWithPath:CommandLine.arguments[1]),output=URL(fileURLWithPath:CommandLine.arguments[2])
func source(_ url:URL)->CGImage {
    let s=CGImageSourceCreateWithURL(url as CFURL,nil)!
    return CGImageSourceCreateImageAtIndex(s,0,nil)!
}
func raw(_ i:CGImage)->[UInt8] {
    // ImageIO's original decoded sample buffer, before any display conversion.
    precondition(i.bitsPerPixel==32 && i.bitsPerComponent==8 && i.alphaInfo == .last && i.bitmapInfo.rawValue==3)
    return Array(i.dataProvider!.data! as Data)
}
let sheet=source(cuteURL),sheetPixels=raw(sheet)
precondition(sheet.width==48 && sheet.height==16)
let colorSpace=sheet.colorSpace!
func makeImage(_ data:[UInt8],_ width:Int,_ height:Int)->CGImage {
    let provider=CGDataProvider(data:Data(data) as CFData)!
    return CGImage(width:width,height:height,bitsPerComponent:8,bitsPerPixel:32,bytesPerRow:width*4,
        space:colorSpace,bitmapInfo:CGBitmapInfo(rawValue:CGImageAlphaInfo.last.rawValue),provider:provider,
        decode:nil,shouldInterpolate:false,intent:.defaultIntent)!
}
func rgb(_ p:[UInt8],_ i:Int)->Int {Int(p[i])<<16|Int(p[i+1])<<8|Int(p[i+2])}
let keys=[0x323C39,0x595652,0x847E87]
let expected=Set([0x000000,0x222034,0x323C39,0x45283C,0x595652,0x847E87,0x9BADB7,0xAC3232,0xD95763])
let palettes:[(String,[Int])]=[("普通褐色",[0x604027,0xA87542,0xD6A66A]),("中褐色",[0x422D22,0x7B5033,0xAF8053]),("深褐色",[0x29221F,0x4C372C,0x76513B]),("白色",[0x827E74,0xC6C1AF,0xEFEAD7])]
func mask(_ f:Int,_ x:Int,_ y:Int)->Bool {
    switch f {
    case 0:return (y==8 && (4...9).contains(x)) || ((y==9 || y==10) && (3...12).contains(x)) || (y==11 && (4...11).contains(x)) || (y==12 && x==7)
    case 1:return (y==7 && (4...9).contains(x)) || ((y==8 || y==9) && (3...12).contains(x)) || (y==10 && (4...11).contains(x)) || (y==11 && x==7)
    default:return (y==6 && [8,9].contains(x)) || (y==7 && x==10) || (y==8 && [7,10].contains(x)) || (y==9 && (7...11).contains(x)) || (y==10 && x==7)
    }
}
func bbox(_ points:[(Int,Int)])->[Int] {
    guard !points.isEmpty else{return []}
    let xs=points.map{$0.0},ys=points.map{$0.1},x=xs.min()!,y=ys.min()!
    return [x,y,xs.max()!-x+1,ys.max()!-y+1]
}
func centroid(_ points:[(Int,Int)])->[Double] {
    guard !points.isEmpty else{return []}
    return [points.reduce(0){$0+Double($1.0)+0.5}/Double(points.count),points.reduce(0){$0+Double($1.1)+0.5}/Double(points.count)]
}
let anchors=[NSPoint(x:8,y:10),NSPoint(x:8,y:9),NSPoint(x:8,y:8)]
var frameData=[[UInt8]](),frames=[CGImage](),cache=[[CGImage]](),frameReports=[[String:Any]](),mappingReports=[[String:Any]]()
var sourceColors=Set<Int>()
for f in 0..<3 {
    var p=[UInt8](repeating:0,count:16*16*4)
    for y in 0..<16 {for x in 0..<16 {
        let from=y*sheet.bytesPerRow+(x+f*16)*4,to=(y*16+x)*4
        p[to..<to+4]=sheetPixels[from..<from+4]
        precondition(p[to+3]==0 || p[to+3]==255)
        if p[to+3]==255 {sourceColors.insert(rgb(p,to))}
    }}
    frameData.append(p);frames.append(makeImage(p,16,16))
    var visible=[(Int,Int)](),body=[(Int,Int)](),eyes=[(Int,Int)]()
    for y in 0..<16 {for x in 0..<16 {let o=(y*16+x)*4,c=rgb(p,o)
        if p[o+3]>16 {visible.append((x,y))}
        if p[o+3]==255 && mask(f,x,y) && keys.contains(c){body.append((x,y))}
        if p[o+3]==255 && [0xAC3232,0xD95763].contains(c){eyes.append((x,y))}
    }}
    let eyeC=centroid(eyes),bodyC=centroid(body)
    frameReports.append(["frame":f+1,"visible_pixels":visible.count,"visible_bbox":bbox(visible),"recolored_body_bbox":bbox(body),
        "body_plus_red_eyes_bbox":bbox(body+eyes),"recolored_body_pixels":body.count,"eyes_bbox":bbox(eyes),
        "eye_centroid":eyeC,"body_centroid":bodyC,"anchor":[Double(anchors[f].x),Double(anchors[f].y)],
        "anchored_eye_centroid":[eyeC[0]-Double(anchors[f].x),eyeC[1]-Double(anchors[f].y)],
        "anchored_body_centroid":[bodyC[0]-Double(anchors[f].x),bodyC[1]-Double(anchors[f].y)]])
}
precondition(sourceColors==expected,"The decoded sample buffer must match the original PNG RGB keys exactly")
for (colorName,palette) in palettes {
    var set=[CGImage]()
    for f in 0..<3 {
        let before=frameData[f];var after=before,changed=0
        for y in 0..<16 {for x in 0..<16 {
            let o=(y*16+x)*4
            if before[o+3]==255 && mask(f,x,y),let index=keys.firstIndex(of:rgb(before,o)) {
                let c=palette[index];after[o]=UInt8((c>>16)&255);after[o+1]=UInt8((c>>8)&255);after[o+2]=UInt8(c&255);changed+=1
            }
            precondition(after[o+3]==before[o+3])
            if !mask(f,x,y) || !keys.contains(rgb(before,o)) {precondition(after[o..<o+4]==before[o..<o+4])}
        }}
        precondition(changed==[27,27,11][f]);set.append(makeImage(after,16,16))
        mappingReports.append(["color":colorName,"frame":f+1,"changed_body_pixels":changed,"alpha_preserved":true,"non_body_pixels_preserved":true])
    }
    cache.append(set)
}
let backgrounds:[(String,NSColor,NSColor)]=[("light",NSColor(calibratedWhite:0.94,alpha:1),.darkGray),("dark",NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1),.white)]
func bitmap(_ w:Int,_ h:Int,_ backing:Int=1,_ draw:()->Void)->NSBitmapImageRep {
    let b=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:w*backing,pixelsHigh:h*backing,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    b.size=NSSize(width:w,height:h)
    NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:b)
    NSGraphicsContext.current!.imageInterpolation = .none
    // NSGraphicsContext already derives the backing transform from b.size.
    NSColor.clear.setFill();NSRect(x:0,y:0,width:w,height:h).fill(using:.copy);draw();NSGraphicsContext.restoreGraphicsState()
    return b
}
func png(_ b:NSBitmapImageRep,_ name:String){try! b.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name))}
func label(_ text:String,_ x:CGFloat,_ y:CGFloat,_ color:NSColor,_ size:CGFloat=11){(text as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:size),.foregroundColor:color])}
func draw(_ image:CGImage,_ rect:NSRect){NSGraphicsContext.current!.imageInterpolation = .none;NSImage(cgImage:image,size:NSSize(width:image.width,height:image.height)).draw(in:rect,from:.zero,operation:.sourceOver,fraction:1,respectFlipped:false,hints:nil)}
func cross(_ x:CGFloat,_ y:CGFloat,_ color:NSColor){color.withAlphaComponent(0.35).setStroke();let p=NSBezierPath();p.move(to:NSPoint(x:x-5,y:y));p.line(to:NSPoint(x:x+5,y:y));p.move(to:NSPoint(x:x,y:y-5));p.line(to:NSPoint(x:x,y:y+5));p.lineWidth=0.5;p.stroke()}
func cute(_ image:CGImage,_ frame:Int,_ size:CGFloat,_ x:CGFloat,_ y:CGFloat,_ fixed:Bool=true){let a=fixed ? anchors[frame]:NSPoint(x:8,y:10),s=size/16;draw(image,NSRect(x:x-a.x*s,y:y-(16-a.y)*s,width:size,height:size))}
func boardCute(_ frame:Int?,_ backing:Int,_ theme:(String,NSColor,NSColor),_ corrected:Bool=true)->NSBitmapImageRep {
    bitmap(690,326,backing){
        theme.1.setFill();NSRect(x:0,y:0,width:690,height:326).fill();label("可爱 · 四体色 · 16/20/24 pt 帧尺寸 · @\(backing)x",12,305,theme.2,12)
        for c in 0..<4 {let yy=CGFloat(250-c*66);label(palettes[c].0,12,yy+8,theme.2)
            for (column,size)in [16,20,24].enumerated(){let xx=CGFloat(128+column*184)
                if let f=frame {cute(cache[c][f],f,CGFloat(size),xx+48,yy+14,corrected)}
                else {for f in 0..<3 {cute(cache[c][f],f,CGFloat(size),xx+CGFloat(f*40),yy+14,corrected)}}
                label("\(size) pt · body \(String(format:"%.1f",Double(size)*10/16))×\(String(format:"%.1f",Double(size)*5/16))",xx-12,yy-14,theme.2,10)
            }
        }
    }
}
for backing in [1,2] {for theme in backgrounds {
    png(boardCute(nil,backing,theme),"cute-normal-\(backing)x-\(theme.0).png")
    let dest=CGImageDestinationCreateWithURL(output.appendingPathComponent("cute-flight-\(backing)x-\(theme.0).gif") as CFURL,"com.compuserve.gif" as CFString,3,nil)!
    CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
    for f in 0..<3 {let b=boardCute(f,backing,theme);CGImageDestinationAddImage(dest,b.cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:0.10,kCGImagePropertyGIFUnclampedDelayTime:0.10]] as CFDictionary)}
    precondition(CGImageDestinationFinalize(dest))
}}
for theme in backgrounds {
    let b=bitmap(540,604){theme.1.setFill();NSRect(x:0,y:0,width:540,height:604).fill();label("可爱原像素 ×6 · 四色三帧 · 原 RGB 遮罩映射",12,583,theme.2,12)
        for c in 0..<4 {let y=CGFloat(460-c*140);label(palettes[c].0,12,y+40,theme.2)
            for f in 0..<3 {let x=CGFloat(180+f*140);cute(cache[c][f],f,96,x,y+45);label("frame \(f+1)",x-22,y-18,theme.2)}
        }
    };png(b,"cute-enlarged-\(theme.0).png")
    let comparison=bitmap(820,360){theme.1.setFill();NSRect(x:0,y:0,width:820,height:360).fill();label("原位播放 / 固定身体锚点 · 相同原三帧，×8 放大",12,339,theme.2,12)
        for row in 0..<2 {let y=CGFloat(244-row*152);label(row==0 ? "未校正":"锚点校正",12,y+15,theme.2)
            for f in 0..<3 {let x=CGFloat(228+f*228);cross(x,y,theme.2);cute(cache[0][f],f,128,x,y,row==1);label("frame \(f+1) / (\(Int(anchors[f].x)),\(Int(anchors[f].y)))",x-67,y-63,theme.2,10)}
        }
    };png(comparison,"cute-anchor-\(theme.0).png")
    let dest=CGImageDestinationCreateWithURL(output.appendingPathComponent("cute-anchor-flight-\(theme.0).gif") as CFURL,"com.compuserve.gif" as CFString,3,nil)!
    CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
    for f in 0..<3 {let b=bitmap(580,270){theme.1.setFill();NSRect(x:0,y:0,width:580,height:270).fill();label("原位 / 固定锚点 · 10 fps · ×8",12,248,theme.2,12)
        label("未校正",90,22,theme.2);label("锚点校正",356,22,theme.2);cross(130,140,theme.2);cross(394,140,theme.2);cute(cache[0][f],f,128,130,140,false);cute(cache[0][f],f,128,394,140,true)
    };CGImageDestinationAddImage(dest,b.cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:0.1]] as CFDictionary)}
    precondition(CGImageDestinationFinalize(dest))
}
var sizeReports=[[String:Any]]()
for size in [16,20,24] {for f in 0..<3 {
    let s=Double(size)/16,b=frameReports[f]["visible_bbox"] as! [Int],body=frameReports[f]["body_plus_red_eyes_bbox"] as! [Int],a=anchors[f]
    let extents=[(Double(a.x)-Double(b[0]))*s,(Double(b[0]+b[2])-Double(a.x))*s,(Double(a.y)-Double(b[1]))*s,(Double(b[1]+b[3])-Double(a.y))*s]
    sizeReports.append(["frame":f+1,"frame_size_pt":size,"visible_size_pt":[Double(b[2])*s,Double(b[3])*s],"body_color_plus_eyes_size_pt":[Double(body[2])*s,Double(body[3])*s],"capture_center_extents_left_right_top_bottom_pt":extents,"within_12pt_capture_inset":extents.max()!<=12])
}}
var result:[String:Any]=["cute_source_size":[48,16],"source_alpha_values":[0,255],"runtime_cache_images":12,"frames":frameReports,"recolor_checks":mappingReports,"sizes":sizeReports,"frame_sequence":[0,1,2],"frame_duration_seconds":0.10,"frame_anchors_top_left":anchors.map{[Double($0.x),Double($0.y)]},"old_placeholder_body_size_pt":[14,10],"sampling":"nearest; sourceOver alpha; original RGB before display color conversion","offscreen_only":true,"no_NSApplication":true,"no_NSWindow":true,"no_worker":true,"no_save_access":true,"production_enabled":false]
if CommandLine.arguments.count>3 {
    let realisticURL=URL(fileURLWithPath:CommandLine.arguments[3]),real=source(realisticURL),pixels=raw(real)
    var visible=[(Int,Int)](),core=[(Int,Int)](),hist=[Int](repeating:0,count:256)
    for y in 0..<real.height {for x in 0..<real.width {let a=Int(pixels[y*real.bytesPerRow+x*4+3]);hist[a]+=1;if a>0{visible.append((x,y))};if a>16{core.append((x,y))}}}
    let box=bbox(core),all=bbox(visible)
    let crop=real.cropping(to:CGRect(x:box[0],y:box[1],width:box[2],height:box[3]))!
    let maxEdge=CGFloat(max(box[2],box[3]))
    // A measurement guide only, not a segmented/recolored/derived sprite.
    // This rectangle covers the visible head, thorax and abdomen, excluding legs/wings.
    let bodyReference=NSRect(x:292,y:440,width:695,height:253)
    let realisticAnchor=NSPoint(x:bodyReference.midX-CGFloat(box[0]),y:bodyReference.midY-CGFloat(box[1]))
    func realDraw(_ size:CGFloat,_ x:CGFloat,_ y:CGFloat,_ useBodyAnchor:Bool=false){let s=size/maxEdge
        let a=useBodyAnchor ? realisticAnchor:NSPoint(x:CGFloat(box[2])/2,y:CGFloat(box[3])/2)
        draw(crop,NSRect(x:x-a.x*s,y:y-(CGFloat(box[3])-a.y)*s,width:CGFloat(box[2])*s,height:CGFloat(box[3])*s))
    }
    var realSizes=[[String:Any]]()
    for size in [20,24,28] {let s=Double(size)/Double(maxEdge),a=realisticAnchor
        realSizes.append(["visible_long_edge_pt":size,"visible_size_pt":[Double(box[2])*s,Double(box[3])*s],"body_reference_size_pt":[Double(bodyReference.width)*s,Double(bodyReference.height)*s],"body_reference_anchor_extents_left_right_top_bottom_pt":[Double(a.x)*s,Double(CGFloat(box[2])-a.x)*s,Double(a.y)*s,Double(CGFloat(box[3])-a.y)*s],"centered_full_crop_max_extent_pt":Double(size)/2,"final_size_eligible_for_12pt_inset":size<=24])
    }
    for backing in [1,2] {for theme in backgrounds {
        let b=bitmap(730,302,backing){theme.1.setFill();NSRect(x:0,y:0,width:730,height:302).fill();label("同场正常尺寸 · 可爱三帧 / 写实单个原基帧 · @\(backing)x",12,280,theme.2,12)
            label("可爱帧尺寸",12,222,theme.2);label("写实可见长边",12,145,theme.2)
            for j in 0..<3 {let x=CGFloat(188+j*210),cs=CGFloat([16,20,24][j]),rs=CGFloat([20,24,28][j])
                for f in 0..<3 {cute(cache[0][f],f,cs,x+CGFloat(f*31)-31,228)}
                label("\(Int(cs)) pt",x-12,202,theme.2);realDraw(rs,x,142);label("\(Int(rs)) pt\(j==2 ? "（仅参考）":"")",x-22,108,theme.2)
            }
            label("写实源图只作整体可见裁框缩放；28 pt 不满足当前 ≤12 pt 边界。",12,54,theme.2,11)
            label("下方体宽对照另图采用手工测量参考框，尚未锁定生产锚点或尺寸。",12,30,theme.2,11)
        };png(b,"styles-normal-\(backing)x-\(theme.0).png")
        let equal=bitmap(730,260,backing){theme.1.setFill();NSRect(x:0,y:0,width:730,height:260).fill();label("等身体宽参考 · cute 着色体+眼 / realistic 手工身体框 · @\(backing)x",12,238,theme.2,12)
            for j in 0..<3 {let cs=CGFloat([16,20,24][j]),body=CGFloat((frameReports[0]["body_plus_red_eyes_bbox"] as! [Int])[2])*cs/16,rs=body/bodyReference.width*maxEdge,x=CGFloat(175+j*210)
                cute(cache[0][0],0,cs,x,174);realDraw(rs,x,102,true)
                label("体宽 \(String(format:"%.2f",Double(body))) pt",x-39,53,theme.2,10)
                label("cute \(Int(cs)) / real crop \(String(format:"%.1f",Double(rs))) pt",x-63,29,theme.2,10)
            }
        };png(equal,"styles-equal-body-\(backing)x-\(theme.0).png")
    }}
    for theme in backgrounds {
        let enlarged=bitmap(630,520){theme.1.setFill();NSRect(x:0,y:0,width:630,height:520).fill();label("写实原基帧 · visible crop / 测量参考（非生产裁切）",12,497,theme.2,12)
            let s:CGFloat=0.48,x:CGFloat=108,y:CGFloat=55
            draw(crop,NSRect(x:x,y:y,width:CGFloat(box[2])*s,height:CGFloat(box[3])*s))
            NSColor.systemOrange.setStroke();let reference=NSRect(x:x+(bodyReference.minX-CGFloat(box[0]))*s,y:y+(CGFloat(box[1]+box[3])-bodyReference.maxY)*s,width:bodyReference.width*s,height:bodyReference.height*s);let path=NSBezierPath(rect:reference);path.lineWidth=1;path.stroke()
            label("橙框仅估量头胸腹宽高；身体/翼/腿未拆分。",12,20,theme.2,11)
        };png(enlarged,"realistic-measurement-\(theme.0).png")
    }
    result["realistic"]=["source_size":[real.width,real.height],"alpha_gt0_bbox":all,"alpha_gt16_bbox":box,"alpha_histogram":hist,
        "display_crop":box,"display_reference":"longer edge of alpha>16 bbox; preserve aspect ratio",
        "manual_body_reference_rect":[Double(bodyReference.minX),Double(bodyReference.minY),Double(bodyReference.width),Double(bodyReference.height)],
        "manual_body_reference_is_approximate":true,"sizes":realSizes,"animation_complete":false,"body_and_wings_not_split":true]
}
if CommandLine.arguments.count>5 {
    let bodyURL=URL(fileURLWithPath:CommandLine.arguments[4]),wingURL=URL(fileURLWithPath:CommandLine.arguments[5])
    let bodySource=source(bodyURL),wingSource=source(wingURL),bodyPixels=raw(bodySource),wingPixels=raw(wingSource)
    func alphaBox(_ image:CGImage,_ pixels:[UInt8],_ region:NSRect?=nil)->[Int] {
        var points=[(Int,Int)]()
        for y in 0..<image.height {for x in 0..<image.width where pixels[y*image.bytesPerRow+x*4+3]>16 {
            if region==nil || region!.contains(NSPoint(x:x,y:y)){points.append((x,y))}
        }}
        return bbox(points)
    }
    let bodyBox=alphaBox(bodySource,bodyPixels),upperBox=alphaBox(wingSource,wingPixels,NSRect(x:0,y:0,width:wingSource.width,height:600)),lowerBox=alphaBox(wingSource,wingPixels,NSRect(x:0,y:600,width:wingSource.width,height:wingSource.height-600))
    func cropImage(_ image:CGImage,_ box:[Int])->CGImage {image.cropping(to:CGRect(x:box[0],y:box[1],width:box[2],height:box[3]))!}
    let upper=cropImage(wingSource,upperBox),lower=cropImage(wingSource,lowerBox)
    // Explicit top-left source polygon bounds only the head/thorax/abdomen.
    // Eyes are protected by the warm-color gate; wings and all outside pixels are untouched.
    let polygon:[[Double]]=[[295,450],[375,442],[410,486],[426,451],[466,435],[511,426],[566,446],[591,476],[643,502],[709,516],[770,533],[825,553],[887,590],[946,614],[983,643],[992,674],[984,705],[947,722],[889,720],[829,714],[747,708],[693,697],[646,680],[607,677],[574,681],[540,676],[509,670],[479,667],[454,649],[426,647],[405,659],[365,655],[334,650],[295,631]]
    let localPolygon=polygon.map{[$0[0]-Double(bodyBox[0]),$0[1]-Double(bodyBox[1])]}
    func inside(_ x:Double,_ y:Double)->Bool {
        var hit=false,j=polygon.count-1
        for i in 0..<polygon.count {let a=polygon[i],b=polygon[j]
            if ((a[1]>y) != (b[1]>y)) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0] {hit = !hit};j=i
        };return hit
    }
    let gate:[String:Double]=["minRed":45,"minGreenOverRed":0.63,"minGreenMinusBlue":4]
    func warm(_ offset:Int)->Bool {
        let r=Double(bodyPixels[offset]),g=Double(bodyPixels[offset+1]),b=Double(bodyPixels[offset+2])
        return r>=gate["minRed"]! && g/r>=gate["minGreenOverRed"]! && g-b>=gate["minGreenMinusBlue"]!
    }
    func luma(_ offset:Int)->Double {0.2126*Double(bodyPixels[offset])+0.7152*Double(bodyPixels[offset+1])+0.0722*Double(bodyPixels[offset+2])}
    var chosen=[Int](),lum=[Double](),redEyes=[Int](),legPixels=[Int](),oldGateEyeChanges=0
    let eyeROI=NSRect(x:295,y:430,width:125,height:235)
    let legROIs=[NSRect(x:210,y:725,width:225,height:250),NSRect(x:400,y:745,width:235,height:305),NSRect(x:570,y:725,width:275,height:325)]
    for y in 0..<bodySource.height {for x in 0..<bodySource.width {
        let o=y*bodySource.bytesPerRow+x*4
        if bodyPixels[o+3]>0 && inside(Double(x)+0.5,Double(y)+0.5) && warm(o){chosen.append(o);lum.append(luma(o))}
        let r=Double(bodyPixels[o]),g=Double(bodyPixels[o+1]),b=Double(bodyPixels[o+2])
        if bodyPixels[o+3]>0 && eyeROI.contains(NSPoint(x:x,y:y)) && r>60 && r>1.6*g && r>1.6*b {
            redEyes.append(o)
            if inside(Double(x)+0.5,Double(y)+0.5) && r>=45 && g/r>=0.42 && g-b>=4 {oldGateEyeChanges+=1}
        }
        if bodyPixels[o+3]>0 && legROIs.contains(where:{$0.contains(NSPoint(x:x,y:y))}) {legPixels.append(o)}
    }}
    let range=[floor(lum.min()!),ceil(lum.max()!)],selected=Set(chosen)
    let colorNames=["原身体"]+palettes.map{$0.0}
    var bodyImages=[cropImage(bodySource,bodyBox)],colorMetrics=[[String:Any]]()
    for (name,palette) in palettes {
        var changed=bodyPixels;var bands=[0,0,0]
        for o in chosen {let t=max(0,min(1,(luma(o)-range[0])/(range[1]-range[0]))),band=t<0.333 ? 0:t<0.667 ? 1:2,c=palette[band]
            changed[o]=UInt8((c>>16)&255);changed[o+1]=UInt8((c>>8)&255);changed[o+2]=UInt8(c&255);bands[band]+=1
        }
        for y in 0..<bodySource.height {for x in 0..<bodySource.width {let o=y*bodySource.bytesPerRow+x*4
            precondition(changed[o+3]==bodyPixels[o+3]);if !selected.contains(o){precondition(changed[o..<o+4]==bodyPixels[o..<o+4])}
        }}
        let preservedEyes=redEyes.allSatisfy{changed[$0..<$0+4]==bodyPixels[$0..<$0+4]};precondition(preservedEyes)
        let changedEyes=redEyes.filter{changed[$0..<$0+4] != bodyPixels[$0..<$0+4]}.count
        let changedLegs=legPixels.filter{changed[$0..<$0+4] != bodyPixels[$0..<$0+4]}.count
        precondition(changedEyes==0 && changedLegs==0)
        // Repack provider rows before constructing an image in the original color space.
        var packed=[UInt8]()
        for y in 0..<bodySource.height {packed.append(contentsOf:changed[(y*bodySource.bytesPerRow)..<(y*bodySource.bytesPerRow+bodySource.width*4)])}
        bodyImages.append(cropImage(makeImage(packed,bodySource.width,bodySource.height),bodyBox))
        colorMetrics.append(["color":name,"selected_body_pixels":chosen.count,"actual_changed_body_pixels":chosen.filter{changed[$0..<$0+4] != bodyPixels[$0..<$0+4]}.count,"quantized_band_counts":bands,"source_red_eye_pixels":redEyes.count,"red_eyes_unchanged":preservedEyes,"changed_red_eye_pixels":changedEyes,"protected_leg_pixels":legPixels.count,"changed_leg_pixels":changedLegs,"outside_polygon_and_gate_unchanged":true,"alpha_unchanged":true])
    }
    let capture=NSPoint(x:610,y:600),bodyUpperRoot=NSPoint(x:590,y:465),bodyLowerRoot=NSPoint(x:588,y:604),upperRoot=NSPoint(x:600,y:478),lowerRoot=NSPoint(x:620,y:684)
    let scales:[CGFloat]=[0.024,0.026],wingYScales:[CGFloat]=[1,0.55,0.18],sequence=[0,1,2,1]
    func bounds(_ box:[Int],_ scale:CGFloat,_ root:NSPoint?=nil,_ attach:NSPoint?=nil)->NSRect {
        let offset=root==nil ? NSPoint.zero:NSPoint(x:attach!.x-root!.x,y:attach!.y-root!.y)
        return NSRect(x:(CGFloat(box[0])+offset.x-capture.x)*scale,y:(CGFloat(box[1])+offset.y-capture.y)*scale,width:CGFloat(box[2])*scale,height:CGFloat(box[3])*scale)
    }
    func pivot(_ root:NSPoint,_ scale:CGFloat)->NSPoint {NSPoint(x:(root.x-capture.x)*scale,y:(root.y-capture.y)*scale)}
    func posed(_ rect:NSRect,_ pivot:NSPoint,_ scaleY:CGFloat)->NSRect {NSRect(x:rect.minX,y:pivot.y+(rect.minY-pivot.y)*scaleY,width:rect.width,height:rect.height*scaleY)}
    func layer(_ image:CGImage,_ b:NSRect){draw(image,NSRect(x:12+b.minX,y:12-b.maxY,width:b.width,height:b.height))}
    func paint(_ scale:CGFloat,_ color:Int,_ frame:Int,_ bodyOnly:Bool=false) {
            if !bodyOnly {
                layer(lower,posed(bounds(lowerBox,scale,lowerRoot,bodyLowerRoot),pivot(bodyLowerRoot,scale),wingYScales[frame]))
                layer(upper,posed(bounds(upperBox,scale,upperRoot,bodyUpperRoot),pivot(bodyUpperRoot,scale),wingYScales[frame]))
            }
            layer(bodyImages[color],bounds(bodyBox,scale))
    }
    func cached(_ scale:CGFloat,_ color:Int,_ frame:Int,_ bodyOnly:Bool=false)->NSBitmapImageRep {
        bitmap(24,24,2){paint(scale,color,frame,bodyOnly)}
    }
    func data(_ bitmap:NSBitmapImageRep)->Data {Data(bytes:bitmap.bitmapData!,count:bitmap.bytesPerRow*bitmap.pixelsHigh)}
    func array(_ rect:NSRect)->[Double]{[Double(rect.minX),Double(rect.minY),Double(rect.width),Double(rect.height)]}
    var caches=[[[CGImage]]](),candidateScales=[[String:Any]](),poseChecks=[[String:Any]]()
    for scale in scales {
        var colors=[[CGImage]]()
        let bodyB=bounds(bodyBox,scale),upperB=bounds(upperBox,scale,upperRoot,bodyUpperRoot),lowerB=bounds(lowerBox,scale,lowerRoot,bodyLowerRoot),up=pivot(bodyUpperRoot,scale),lp=pivot(bodyLowerRoot,scale)
        let item:[String:Any]=["kind":"wingLayers","canvasSize":[24,24],"sampleScale":2,"fps":12,"sequence":sequence,"frames":wingYScales.map{["upperYScale":Double($0),"lowerYScale":Double($0)]},"body":["file":bodyURL.lastPathComponent,"sourceRect":bodyBox,"bounds":array(bodyB)],"upperWing":["file":wingURL.lastPathComponent,"sourceRect":upperBox,"bounds":array(upperB),"pivot":[Double(up.x),Double(up.y)]],"lowerWing":["file":wingURL.lastPathComponent,"sourceRect":lowerBox,"bounds":array(lowerB),"pivot":[Double(lp.x),Double(lp.y)]],"bodyPolygon":localPolygon,"warmGate":gate,"lumaRange":range,"sourceToPointScale":Double(scale),"captureCenterSource":[610,600],"drawOrder":["lowerWing","upperWing","body"]]
        candidateScales.append(item)
        for color in 0..<bodyImages.count {
            var images=[CGImage](),pixelStates=[Data](),bodyStates=[Data]()
            for frame in 0..<3 {
                let b=cached(scale,color,frame),only=cached(scale,color,frame,true)
                images.append(b.cgImage!);pixelStates.append(data(b));bodyStates.append(data(only))
                let union=bodyB.union(posed(upperB,up,wingYScales[frame])).union(posed(lowerB,lp,wingYScales[frame]))
                let extent=max(abs(union.minX),abs(union.maxX),abs(union.minY),abs(union.maxY));precondition(extent<=12)
                let extended=bitmap(28,28,2){NSGraphicsContext.current!.cgContext.translateBy(x:2,y:2);paint(scale,color,frame)}
                let e=extended.bitmapData!;var outsideAlpha=0
                for y in 0..<56 {for x in 0..<56 where x<4 || x>=52 || y<4 || y>=52 {outsideAlpha=max(outsideAlpha,Int(e[y*extended.bytesPerRow+x*4+3]))}}
                precondition(outsideAlpha==0,"Actual wing/body pixels must stay inside 24pt canvas")
                let pixels=b.bitmapData!,n=b.bytesPerRow;var alphaValues=Set<Int>()
                for y in 0..<48 {for x in 0..<48{alphaValues.insert(Int(pixels[y*n+x*4+3]))}}
                poseChecks.append(["source_to_point_scale":Double(scale),"color":colorNames[color],"frame":frame,"wing_scale_y":Double(wingYScales[frame]),"bounds":array(union),"maximum_extent_from_capture_center_pt":Double(extent),"within_12pt_capture_inset":true,"body_pixel_cache_unchanged":true,"outside_canvas_alpha_max":outsideAlpha,"cache_size_px":[48,48],"cache_alpha_values":alphaValues.sorted()])
            }
            precondition(Set(pixelStates).count==3,"Every wing pose must create different actual cache pixels")
            precondition(Set(bodyStates).count==1,"Body cache must remain byte-identical through all poses")
            colors.append(images)
        };caches.append(colors)
    }
    for backing in [1,2] {for theme in backgrounds {
        let b=bitmap(830,442,backing){theme.1.setFill();NSRect(x:0,y:0,width:830,height:442).fill();label("固定身体 + 双翼三姿 · 24 pt 缓存画布 · @\(backing)x",12,419,theme.2,12)
            label("0.024 source→pt",190,390,theme.2);label("0.026 source→pt",535,390,theme.2)
            for color in 0..<5 {let y=CGFloat(341-color*68);label(colorNames[color],12,y+7,theme.2)
                for scale in 0..<2 {for frame in 0..<3 {let x=CGFloat(180+scale*350+frame*52);draw(caches[scale][color][frame],NSRect(x:x,y:y,width:24,height:24));if color==4{label("y×\(wingYScales[frame])",x-3,y-16,theme.2,9)}}}
            }
        };png(b,"rig-normal-\(backing)x-\(theme.0).png")
        let dest=CGImageDestinationCreateWithURL(output.appendingPathComponent("rig-flight-\(backing)x-\(theme.0).gif") as CFURL,"com.compuserve.gif" as CFString,sequence.count,nil)!
        CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
        for frame in sequence {let b=bitmap(650,394,backing){theme.1.setFill();NSRect(x:0,y:0,width:650,height:394).fill();label("固定身体 · 三姿往返 · 12 fps · @\(backing)x",12,371,theme.2,12)
            for color in 0..<5 {let y=CGFloat(304-color*64);label(colorNames[color],12,y+5,theme.2)
                for scale in 0..<2 {let x=CGFloat(210+scale*270);draw(caches[scale][color][frame],NSRect(x:x,y:y,width:24,height:24));label("\(scales[scale])",x-8,y-16,theme.2,9)}
            }
        };CGImageDestinationAddImage(dest,b.cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:1.0/12,kCGImagePropertyGIFUnclampedDelayTime:1.0/12]] as CFDictionary)}
        precondition(CGImageDestinationFinalize(dest))
    }}
    for theme in backgrounds {
        let b=bitmap(980,860){theme.1.setFill();NSRect(x:0,y:0,width:980,height:860).fill();label("0.026 固定身体与双翼 · ×6 缓存放大 · 原身体 / 四档候选",12,837,theme.2,12)
            for color in 0..<5 {let y=CGFloat(659-color*157);label(colorNames[color],12,y+57,theme.2)
                for frame in 0..<3 {let x=CGFloat(160+frame*265);draw(caches[1][color][frame],NSRect(x:x,y:y,width:144,height:144));if color==4{label("wing Y \(wingYScales[frame])",x+10,y-15,theme.2,10)}}
            }
        };png(b,"rig-enlarged-\(theme.0).png")
    }
    result["rig"]=["source_size":[bodySource.width,bodySource.height],"body_source_rect":bodyBox,"upper_wing_source_rect":upperBox,"lower_wing_source_rect":lowerBox,"color_metrics":colorMetrics,"pose_checks":poseChecks,"candidates":candidateScales,"fixed_body_across_all_three_poses":true,"all_three_pose_caches_distinct":true,"production_enabled":false]
    try! JSONSerialization.data(withJSONObject:["status":"candidate_for_root_visual_review","candidate_scales":candidateScales],options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("rig-candidates.json"))
    var selectedStyle=candidateScales.last!
    for key in ["sourceToPointScale","captureCenterSource","drawOrder"]{selectedStyle.removeValue(forKey:key)}
    selectedStyle["palette"]=Dictionary(uniqueKeysWithValues:palettes.map{($0.0,$0.1.map{[($0>>16)&255,($0>>8)&255,$0&255]})})
    try! JSONSerialization.data(withJSONObject:selectedStyle,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("realistic.json"))
    result["rig_pixel_protection"]=["eye_roi":[295,430,125,235],"eye_rgb_rule":"alpha>0, R>60, R>1.6G, R>1.6B", "old_gate_042_would_change_eye_pixels":oldGateEyeChanges,"new_gate_063_changed_eye_pixels":0,"eye_pixels_tested":redEyes.count,"leg_pixels_tested":legPixels.count,"new_gate_changed_leg_pixels":0,"leg_rois":legROIs.map{array($0)},"final_gate":gate,"selected_body_pixels":chosen.count]
    // Final cross-style boards reuse a 24pt/48px cache, matching the chosen schema.
    var cuteFinal=[[CGImage]](),hashes=[[String:Any]]()
    for color in 0..<4 {var row=[CGImage]()
        for frame in 0..<3 {let box=frameReports[frame]["visible_bbox"] as! [Int],part=cache[color][frame].cropping(to:CGRect(x:box[0],y:box[1],width:box[2],height:box[3]))!,s:CGFloat=1.25
            let a=NSPoint(x:anchors[frame].x-CGFloat(box[0]),y:anchors[frame].y-CGFloat(box[1]))
            let b=bitmap(24,24,2){draw(part,NSRect(x:12-a.x*s,y:12-(CGFloat(box[3])-a.y)*s,width:CGFloat(box[2])*s,height:CGFloat(box[3])*s))}
            row.append(b.cgImage!)
            hashes.append(["style":"cute","color":palettes[color].0,"frame":frame,"cache_size_px":[48,48],"sha256_rgba":SHA256.hash(data:data(b)).map{String(format:"%02x",$0)}.joined()])
            let real=cached(0.026,color+1,frame)
            hashes.append(["style":"realistic","color":palettes[color].0,"frame":frame,"cache_size_px":[48,48],"sha256_rgba":SHA256.hash(data:data(real)).map{String(format:"%02x",$0)}.joined()])
        };cuteFinal.append(row)
    }
    func finalBoard(_ frame:Int?,_ backing:Int,_ theme:(String,NSColor,NSColor))->NSBitmapImageRep {
        bitmap(730,350,backing){theme.1.setFill();NSRect(x:0,y:0,width:730,height:350).fill();label("最终同场 · cute 20pt / realistic 0.026 · 同一24pt缓存 · @\(backing)x",12,327,theme.2,12)
            label("可爱 · 三帧",180,295,theme.2);label("写实 · 固定身体三翼姿",472,295,theme.2)
            for color in 0..<4 {let y=CGFloat(244-color*66);label(palettes[color].0,12,y+8,theme.2)
                for style in 0..<2 {let imageSet=style==0 ? cuteFinal[color]:caches[1][color+1],base=CGFloat(166+style*302)
                    if let f=frame {draw(imageSet[f],NSRect(x:base+48,y:y,width:24,height:24))}
                    else {for f in 0..<3 {draw(imageSet[f],NSRect(x:base+CGFloat(f*48),y:y,width:24,height:24))}}
                }
            }
            label("12 fps · sequence 0,1,2,1 · 原图不变 · 两套同ID业务尚待接入验收",12,15,theme.2,10)
        }
    }
    for backing in [1,2] {for theme in backgrounds {
        png(finalBoard(nil,backing,theme),"final-styles-\(backing)x-\(theme.0).png")
        let dest=CGImageDestinationCreateWithURL(output.appendingPathComponent("final-styles-flight-\(backing)x-\(theme.0).gif") as CFURL,"com.compuserve.gif" as CFString,sequence.count,nil)!
        CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
        for f in sequence {let b=finalBoard(f,backing,theme);CGImageDestinationAddImage(dest,b.cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:1.0/12,kCGImagePropertyGIFUnclampedDelayTime:1.0/12]] as CFDictionary)}
        precondition(CGImageDestinationFinalize(dest))
    }}
    try! JSONSerialization.data(withJSONObject:hashes,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("final-cache-hashes.json"))
}

try! JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("prototype-checks.json"))
print("INSECT_PROTOTYPE_PASS: 12 in-memory color frames; 27/27/11 exact body pixels; alpha/source colors preserved; 1x/2x normal, enlarged, 3-frame GIF and anchor review; no app/window/worker/save")
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--realistic',type=Path,default=REALISTIC)
    parser.add_argument('--body',type=Path,default=BODY)
    parser.add_argument('--wings',type=Path,default=WINGS)
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[CUTE]
    if args.realistic.exists():sources.append(args.realistic.resolve())
    if args.body.exists() and args.wings.exists():sources.extend([args.body.resolve(),args.wings.resolve()])
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    with tempfile.TemporaryDirectory(prefix='tianmu-insect-prototype-') as directory:
        work=Path(directory);(work/'main.swift').write_text(SWIFT)
        subprocess.run(['swiftc','-framework','AppKit','-framework','ImageIO',str(work/'main.swift'),'-o',str(work/'render')],check=True)
        subprocess.run([str(work/'render'),str(CUTE),str(OUT),*[str(p) for p in sources[1:]]],check=True)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in hashes.items())
    report=json.loads((OUT/'prototype-checks.json').read_text());report.update(source_sha256=hashes,source_bytes_preserved=True)
    (OUT/'prototype-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
