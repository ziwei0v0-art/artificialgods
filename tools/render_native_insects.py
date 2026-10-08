"""Inspect the real InsectArtwork production cache without creating an app or window."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/1.0/161-native-insects'

SWIFT=r'''
import AppKit
import ImageIO
import CryptoKit
let directory=URL(fileURLWithPath:CommandLine.arguments[1]),output=URL(fileURLWithPath:CommandLine.arguments[2]),prototype=URL(fileURLWithPath:CommandLine.arguments[3])
let artwork=InsectArtwork(directory:directory)
precondition(artwork.complete,"Production must load both complete styles: \(artwork.issues)")
precondition(artwork.availableStyles==Set([InsectStyle.cute,InsectStyle.realistic]))
let styles:[InsectStyle]=[.cute,.realistic],colors=["普通褐色","中褐色","深褐色","白色"],sequence=[0,1,2,1]
let manifest=try! JSONSerialization.jsonObject(with:Data(contentsOf:directory.appendingPathComponent("manifest.json"))) as! [String:Any]
let themes:[(String,NSColor,NSColor)]=[("light",NSColor(calibratedWhite:0.94,alpha:1),.darkGray),("dark",NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1),.white)]
func bitmap(_ width:Int,_ height:Int,_ backing:Int=1,_ draw:()->Void)->NSBitmapImageRep {
    let b=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:width*backing,pixelsHigh:height*backing,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    b.size=NSSize(width:width,height:height)
    NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:b);NSGraphicsContext.current!.imageInterpolation = .none
    NSColor.clear.setFill();NSRect(x:0,y:0,width:width,height:height).fill(using:.copy);draw();NSGraphicsContext.restoreGraphicsState();return b
}
func png(_ b:NSBitmapImageRep,_ name:String){try! b.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name))}
func bytes(_ b:NSBitmapImageRep)->Data{Data(bytes:b.bitmapData!,count:b.bytesPerRow*b.pixelsHigh)}
func sha(_ b:NSBitmapImageRep)->String {SHA256.hash(data:bytes(b)).map{String(format:"%02x",$0)}.joined()}
func label(_ value:String,_ x:CGFloat,_ y:CGFloat,_ ink:NSColor,_ size:CGFloat=11){(value as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:size),.foregroundColor:ink])}
func sample(_ style:InsectStyle,_ color:String,_ frame:Int)->InsectArtwork.RenderSample {
    let value=artwork.sample(style:style,color:color,time:Double(frame)/12+0.001,phase:0)!
    precondition(value.frameIndex==frame && value.canvasSize==NSSize(width:24,height:24) && value.style==style && value.color==color)
    return value
}
func raw(_ style:InsectStyle,_ color:String,_ frame:Int,_ backing:Int=2)->NSBitmapImageRep {bitmap(24,24,backing){sample(style,color,frame).draw(at:NSPoint(x:12,y:12))}}
func bbox(_ points:[(Int,Int)])->[Int] {guard !points.isEmpty else{return []};let xs=points.map{$0.0},ys=points.map{$0.1},x=xs.min()!,y=ys.min()!;return[x,y,xs.max()!-x+1,ys.max()!-y+1]}
var cacheChecks=[[String:Any]](),timeChecks=[[String:Any]](),eyeChecks=[[String:Any]](),prototypeComparisons=[[String:Any]](),phaseChecks=[[String:Any]](),gifChecks=[[String:Any]]()
var rawImages=[String:NSBitmapImageRep]()
for style in styles {for color in colors {
    var hashes=Set<String>()
    for frame in 0..<3 {
        let render=raw(style,color,frame),d=render.bitmapData!,key="\(style.rawValue)/\(color)/\(frame)"
        rawImages[key]=render;hashes.insert(sha(render))
        let repeated=raw(style,color,frame);precondition(bytes(render)==bytes(repeated),"Repeated sample must draw stable cached bytes")
        let extended=bitmap(28,28,2){sample(style,color,frame).draw(at:NSPoint(x:14,y:14))},e=extended.bitmapData!
        var outside=0,points=[(Int,Int)](),edge=0
        for y in 0..<56 {for x in 0..<56 where x<4 || x>=52 || y<4 || y>=52 {outside=max(outside,Int(e[y*extended.bytesPerRow+x*4+3]))}}
        for y in 0..<48 {for x in 0..<48 {let a=Int(d[y*render.bytesPerRow+x*4+3]);if a>16{points.append((x,y))};if x==0 || y==0 || x==47 || y==47 {edge=max(edge,a)}}}
        precondition(outside==0 && !points.isEmpty)
        let s=sample(style,color,frame)
        precondition(s === sample(style,color,frame),"Repeated sample must reuse the same immutable object")
        let specs=manifest["styles"] as! [String:Any],spec=specs[style.rawValue] as! [String:Any],palette=spec["palette"] as! [String:[[Int]]],target=palette[color]!,cacheBytes=Array(s.image.dataProvider!.data! as Data)
        var paletteCounts=[Int](repeating:0,count:3)
        for y in 0..<s.image.height {for x in 0..<s.image.width {let offset=y*s.image.bytesPerRow+x*4
            if cacheBytes[offset+3]>0 {for shade in 0..<3 where (0..<3).allSatisfy({Int(cacheBytes[offset+$0])==target[shade][$0]}) {paletteCounts[shade]+=1}}
        }}
        precondition(paletteCounts.allSatisfy{$0>0},"All three declared body colors must occur in the actual cache")
        cacheChecks.append(["style":style.rawValue,"color":color,"frame":frame,"canvas_pt":[24,24],"rendered_px":[48,48],"alpha_gt16_bbox":bbox(points),"outside_canvas_alpha_max":outside,"edge_alpha_max":edge,"actual_rgba_sha256":sha(render),"loader_pixel_hash":String(describing:s.pixelHash),"repeated_sample_bytes_identical":true,"same_cached_object_reused":true,"style_and_color_identity_match":true,"exact_palette_rgb_pixel_counts":paletteCounts])
    }
    precondition(hashes.count==3,"Every loaded style/color needs three different rendered frames")
    for step in 0..<16 {
        let t=Double(step)/12+0.001,s=artwork.sample(style:style,color:color,time:t,phase:0)!
        precondition(s.frameIndex==sequence[step%4],"Production frame clock does not follow 12fps 0,1,2,1")
        timeChecks.append(["style":style.rawValue,"color":color,"time":t,"phase":0,"frame":s.frameIndex,"expected":sequence[step%4]])
    }
    for phase in 0..<10 {let a=artwork.sample(style:style,color:color,time:0.041,phase:Double(phase))!,b=artwork.sample(style:style,color:color,time:0.041,phase:Double(phase))!
        precondition(a === b && a.style==style && a.color==color)
        phaseChecks.append(["style":style.rawValue,"color":color,"time":0.041,"phase":phase,"frame":a.frameIndex,"same_cached_object_reused":true])
    }
}}
for style in styles {for frame in 0..<3 {
    let base=rawImages["\(style.rawValue)/普通褐色/\(frame)"]!,p=base.bitmapData!
    // Known eye regions in the final 48px cache; compare actual rendered pixels.
    let roi=style == .cute ? NSRect(x:22,y:19,width:17,height:11):NSRect(x:6,y:13,width:11,height:17)
    var eyePixels=[(Int,Int)]()
    for y in 0..<48 {for x in 0..<48 where roi.contains(NSPoint(x:x,y:y)) {
        let o=y*base.bytesPerRow+x*4,r=Double(p[o]),g=Double(p[o+1]),b=Double(p[o+2])
        if p[o+3]>0 && r>60 && r>1.6*g && r>1.6*b {eyePixels.append((x,y))}
    }}
    precondition(!eyePixels.isEmpty,"Expected red eye pixels must exist in the actual cache")
    var changed=[String:Int]()
    for color in colors {let candidate=rawImages["\(style.rawValue)/\(color)/\(frame)"]!,c=candidate.bitmapData!
        let count=eyePixels.filter{point in let o=point.1*base.bytesPerRow+point.0*4,q=point.1*candidate.bytesPerRow+point.0*4;return (0..<4).contains{p[o+$0] != c[q+$0]}}.count
        changed[color]=count;precondition(count==0,"Changing body color must preserve rendered red eyes")
    }
    eyeChecks.append(["style":style.rawValue,"frame":frame,"actual_red_eye_pixels":eyePixels.count,"eye_bbox":bbox(eyePixels),"changed_eye_pixels_by_color":changed])
}}
for style in styles {
    let rows=eyeChecks.filter{($0["style"] as! String)==style.rawValue},boxes=rows.map{$0["eye_bbox"] as! [Int]}
    precondition(boxes.allSatisfy{$0==boxes[0]},"Eye anchor must remain fixed between animation frames")
}
func board(_ frame:Int?,_ backing:Int,_ theme:(String,NSColor,NSColor))->NSBitmapImageRep {
    bitmap(730,350,backing){theme.1.setFill();NSRect(x:0,y:0,width:730,height:350).fill()
        label("可爱",180,295,theme.2,13);label("写实",472,295,theme.2,13)
        for (row,color)in colors.enumerated(){let y=CGFloat(244-row*66);label(color,12,y+8,theme.2)
            for (column,style)in styles.enumerated(){let base=CGFloat(166+column*302)
                if let f=frame {sample(style,color,f).draw(at:NSPoint(x:base+60,y:y+12))}
                else {for f in 0..<3 {sample(style,color,f).draw(at:NSPoint(x:base+CGFloat(f*48)+12,y:y+12))}}
            }
        }
    }
}
func imageRGBA(_ url:URL)->(CGImage,[UInt8]) {
    let source=CGImageSourceCreateWithURL(url as CFURL,nil)!,image=CGImageSourceCreateImageAtIndex(source,0,nil)!
    precondition(image.bitsPerComponent==8 && image.bitsPerPixel==32 && image.alphaInfo == .last && image.bitmapInfo.rawValue==3)
    return(image,Array(image.dataProvider!.data! as Data))
}
for backing in [1,2] {for theme in themes {
    let b=board(nil,backing,theme),name="styles-\(backing)x-\(theme.0).png";png(b,name)
    let reference=prototype.appendingPathComponent("final-styles-\(backing)x-\(theme.0).png")
    if FileManager.default.fileExists(atPath:reference.path){let (native,np)=imageRGBA(output.appendingPathComponent(name)),(original,op)=imageRGBA(reference)
        precondition(native.width==original.width && native.height==original.height)
        for color in 0..<4 {for style in 0..<2 {for frame in 0..<3 {
            let x=(166+style*302+frame*48)*backing,y=(350-(244-color*66)-24)*backing
            var changed=0,maximum=0,nearbyExact=0
            for yy in y..<(y+24*backing){for xx in x..<(x+24*backing){let n=yy*native.bytesPerRow+xx*4,o=yy*original.bytesPerRow+xx*4;var differs=false
                for channel in 0..<4 {let delta=abs(Int(np[n+channel])-Int(op[o+channel]));maximum=max(maximum,delta);differs = differs || delta>0};if differs{
                    changed+=1;var found=false
                    for dy in -1...1 {for dx in -1...1 {let neighbor=(yy+dy)*original.bytesPerRow+(xx+dx)*4;if (0..<4).allSatisfy({np[n+$0]==op[neighbor+$0]}){found=true}}}
                    if found{nearbyExact+=1}
                }
            }}
            var best=changed,bestOffset=[0,0]
            for dy in -2...2 {for dx in -2...2 {var count=0
                for yy in y..<(y+24*backing){for xx in x..<(x+24*backing){let n=yy*native.bytesPerRow+xx*4,o=(yy+dy)*original.bytesPerRow+(xx+dx)*4
                    if (0..<4).contains(where:{np[n+$0] != op[o+$0]}){count+=1}
                }}
                if count<best{best=count;bestOffset=[dx,dy]}
            }}
            func redBox(_ bytes:[UInt8],_ image:CGImage)->[Int]{var points=[(Int,Int)]()
                for yy in y..<(y+24*backing){for xx in x..<(x+24*backing){let o=yy*image.bytesPerRow+xx*4,r=Double(bytes[o]),g=Double(bytes[o+1]),b=Double(bytes[o+2]);if r>60 && r>1.6*g && r>1.6*b{points.append((xx-x,yy-y))}}};return bbox(points)
            }
            prototypeComparisons.append(["style":styles[style].rawValue,"color":colors[color],"frame":frame,"backing_scale":backing,"theme":theme.0,"crop":[x,y,24*backing,24*backing],"different_pixels":changed,"different_pixels_with_exact_rgb_within_one_pixel":nearbyExact,"maximum_channel_delta":maximum,"best_translation_pixels":bestOffset,"different_pixels_after_best_translation":best,"native_eye_bbox":redBox(np,native),"prototype_eye_bbox":redBox(op,original)])
        }}}
    }
    let gifURL=output.appendingPathComponent("styles-flight-\(backing)x-\(theme.0).gif")
    let dest=CGImageDestinationCreateWithURL(gifURL as CFURL,"com.compuserve.gif" as CFString,12,nil)!
    CGImageDestinationSetProperties(dest,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
    // GIF has centisecond precision: twelve 8/8/9-centisecond steps make exactly one second.
    for step in 0..<12 {let f=sequence[step%4],delay=step%3==2 ? 0.09:0.08,b=board(f,backing,theme);CGImageDestinationAddImage(dest,b.cgImage!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:delay,kCGImagePropertyGIFUnclampedDelayTime:delay]] as CFDictionary)}
    precondition(CGImageDestinationFinalize(dest))
    let gif=CGImageSourceCreateWithURL(gifURL as CFURL,nil)!
    var delays=[Double]()
    for index in 0..<CGImageSourceGetCount(gif){let p=CGImageSourceCopyPropertiesAtIndex(gif,index,nil)! as NSDictionary,g=p[kCGImagePropertyGIFDictionary] as! NSDictionary;delays.append((g[kCGImagePropertyGIFUnclampedDelayTime] as? Double) ?? (g[kCGImagePropertyGIFDelayTime] as! Double))}
    precondition(delays.count==12 && abs(delays.reduce(0,+)-1)<0.000001)
    gifChecks.append(["file":gifURL.lastPathComponent,"encoded_frames":delays.count,"frame_delays_seconds":delays,"loop_duration_seconds":delays.reduce(0,+),"average_frames_per_second":12,"pose_sequence":(0..<12).map{sequence[$0%4]}])
}}
let report:[String:Any]=["complete":artwork.complete,"available_styles":artwork.availableStyles.map{$0.rawValue}.sorted(),"issues":artwork.issues,"cache_checks":cacheChecks,"timing_checks":timeChecks,"phase_checks":phaseChecks,"eye_checks":eyeChecks,"gif_checks":gifChecks,"prototype_png_pixel_comparisons":prototypeComparisons,"renderer":"actual InsectArtwork.RenderSample.draw(at:)","no_NSApplication":true,"no_NSWindow":true,"no_worker":true,"no_save_access":true]
try! JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("checks.json"))
print("NATIVE_INSECT_PASS: actual production loader; 24 cached frame samples, 128 timing checks, eye color and anchor protection, zero outside-canvas alpha; no app/window/worker/save")
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-only',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    source=ROOT/'assets/production/insects'
    files=[source/'manifest.json',ROOT/'native/v1/WindowPlacement.swift',ROOT/'native/v1/InsectArtwork.swift']
    manifest=json.loads((source/'manifest.json').read_text())
    def refs(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='file' and isinstance(v,str):yield v
                else:yield from refs(v)
        elif isinstance(value,list):
            for v in value:yield from refs(v)
    files.extend(source/name for name in set(refs(manifest)))
    digests={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with tempfile.TemporaryDirectory(prefix='tianmu-native-insects-') as folder:
        work=Path(folder);(work/'main.swift').write_text(SWIFT)
        # Only the two source files needed by the real cache loader; no host/UI/worker.
        subprocess.run(['swiftc','-framework','AppKit','-framework','ImageIO',str(ROOT/'native/v1/WindowPlacement.swift'),str(ROOT/'native/v1/InsectArtwork.swift'),str(work/'main.swift'),'-o',str(work/'render')],check=True)
        if args.compile_only:print('COMPILE_ONLY_PASS; executable not run');return
        subprocess.run([str(work/'render'),str(source),str(OUT),str(ROOT/'evidence/1.0/161-insect-prototype')],check=True)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in digests.items()),'An input changed during the native review'
    (OUT/'fixture.json').write_text(json.dumps({'source_sha256':digests,'source_bytes_preserved':True,'renderer':'actual production InsectArtwork cache','no_app':True,'no_window':True,'no_worker':True,'no_save_access':True},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
