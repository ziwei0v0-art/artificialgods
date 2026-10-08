"""Render the production G0 scene through AppKit, without a window or worker."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/1.0/156-scene-visual'
OUT.mkdir(exist_ok=True)
SWIFT = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let out = URL(fileURLWithPath:CommandLine.arguments[1])
let art = AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[2]))!
let scene = ShrineArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[3]))!
func render(_ scale:Double, _ name:String, _ background:NSColor?, _ stage:String="fresh") -> NSImage {
    let view = TianmuView(frame:NSRect(x:0,y:0,width:370*scale,height:190*scale))
    view.attendantArtwork = art
    view.shrineArtwork = scene
    precondition(view.applyRoutine(["action":"idle","action_serial":1,"action_elapsed":0.0,
        "action_duration":0.0,"progress":0.0,"fruit_stage":stage]))
    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(ceil(370*scale)),pixelsHigh:Int(ceil(190*scale)),bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
    view.draw(view.bounds)
    if let background {
        NSGraphicsContext.current!.cgContext.setBlendMode(.destinationOver)
        background.setFill(); view.bounds.fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    try! bitmap.representation(using:.png,properties:[:])!.write(to:out.appendingPathComponent(name+".png"))
    return NSImage(cgImage:bitmap.cgImage!,size:view.bounds.size)
}
let light=NSColor(calibratedWhite:0.94,alpha:1)
let dark=NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1)
for (scale,label) in [(0.2,"minimum"),(0.75,"default"),(1.5,"large")] {
    _=render(scale,label+"-transparent",nil)
    _=render(scale,label+"-light",light)
    _=render(scale,label+"-dark",dark)
}
for stage in ["soft","ripe"] { _=render(0.75,"default-"+stage,light,stage) }
// A normal-alpha overview. Each row retains its actual AppKit raster size.
let board=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:940,pixelsHigh:770,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:board)
NSColor(calibratedWhite:0.98,alpha:1).setFill(); NSRect(x:0,y:0,width:940,height:770).fill()
func title(_ text:String,_ x:Double,_ y:Double,_ size:Double=16){
    (text as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:size),.foregroundColor:NSColor.darkGray])
}
title("G0 · 实际原生场景 / 原图未改",24,731,22)
title("默认 75% · 浅色与深色桌面",24,688)
for (i,name) in ["default-light","default-dark"].enumerated(){
    let image=NSImage(contentsOf:out.appendingPathComponent(name+".png"))!
    image.draw(in:NSRect(x:24+CGFloat(i)*450,y:525,width:277.5,height:142.5))
}
title("最小 20% · 缩放上限 150%",24,486)
NSImage(contentsOf:out.appendingPathComponent("minimum-light.png"))!.draw(in:NSRect(x:24,y:421,width:74,height:38))
NSImage(contentsOf:out.appendingPathComponent("large-light.png"))!.draw(in:NSRect(x:350,y:186,width:555,height:285))
title("同一供果：新鲜 → 软化 → 熟透（实际场景尺寸）",24,143)
for (i,name) in ["default-light","default-soft","default-ripe"].enumerated(){
    let image=NSImage(contentsOf:out.appendingPathComponent(name+".png"))!
    image.draw(in:NSRect(x:24+CGFloat(i)*290,y:6,width:277.5,height:142.5))
}
NSGraphicsContext.restoreGraphicsState()
try! board.representation(using:.png,properties:[:])!.write(to:out.appendingPathComponent("overview.png"))
print("RENDER_PASS: production G0 + accepted stand, 20/75/150 percent, normal alpha, fresh/soft/ripe; no window or worker")
'''

with tempfile.TemporaryDirectory(prefix='tianmu-g0-render-') as folder:
    work = Path(folder)
    (work / 'Scene.swift').write_text((ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0])
    (work / 'main.swift').write_text(SWIFT)
    result = subprocess.run(['swiftc', '-framework', 'AppKit', str(work / 'Scene.swift'), str(work / 'main.swift'), '-o', str(work / 'render')], capture_output=True, text=True)
    print(result.stdout, result.stderr)
    result.check_returncode()
    result = subprocess.run([str(work / 'render'), str(OUT), str(ROOT / 'assets/production/A01'), str(ROOT / 'assets/production/scene')], capture_output=True, text=True)
    print(result.stdout, result.stderr)
    result.check_returncode()
