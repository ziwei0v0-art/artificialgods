"""Render two untouched source assets through the production stand renderer."""
import argparse,hashlib,json,subprocess,tempfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PIXEL=ROOT/'assets/incoming/A01_style_comparison_20261001/A01_pixel_latest_chat_20261001_000844_original.png'
PAINT=ROOT/'assets/production/A01/stand.png'
parser=argparse.ArgumentParser()
parser.add_argument('--pixel',type=Path,default=PIXEL)
parser.add_argument('--output',type=Path,default=ROOT/'evidence/1.0/145-style-20261001.png')
parser.add_argument('--label',default='最新像素稿 · 肤色待改')
args=parser.parse_args()
PIXEL=args.pixel.resolve()
HARNESS=r'''
import AppKit
import Foundation
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let painted=AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[1]))!
let pixel=AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[2]))!
for (name,art) in [("paint",painted),("pixel",pixel)] {
 let f=art.frame(walking:false,elapsed:0)
 print("\(name) alpha-positive crop \(f.width)x\(f.height)")
 for threshold:UInt8 in [16,64,128,240] {
  var box=NSRect.null
  for y in 0..<f.height { for x in 0..<f.width { if f.alpha[y*f.width+x]>threshold { box=box.union(NSRect(x:x,y:y,width:1,height:1)) } } }
  print("\(name) alpha>\(threshold): \(box)")
 }
}
final class Comparison:NSView {
    override var isFlipped:Bool { true }
    override func draw(_ dirty:NSRect) {
        NSColor(calibratedWhite:0.94,alpha:1).setFill();bounds.fill()
        let title:[NSAttributedString.Key:Any] = [.font:NSFont.systemFont(ofSize:15,weight:.medium),.foregroundColor:NSColor.darkGray]
        let detail:[NSAttributedString.Key:Any] = [.font:NSFont.systemFont(ofSize:11),.foregroundColor:NSColor.darkGray]
        for (column,art,name) in [(0,painted,"现有手绘站姿"),(1,pixel,CommandLine.arguments[4])] {
            let x:CGFloat=CGFloat(column)*380
            (name as NSString).draw(at:NSPoint(x:x+20,y:15),withAttributes:title)
            for (row,height) in [(0,CGFloat(128)),(1,CGFloat(64))] {
                let top:CGFloat=row==0 ? 52 : 228
                let frame=art.frame(walking:false,elapsed:0)
                // Align the visible subject; tiny near-transparent export specks
                // otherwise make the two untouched canvases incomparable.
                var visible=NSRect.null
                for y in 0..<frame.height { for x in 0..<frame.width {
                    if frame.alpha[y*frame.width+x]>16 { visible=visible.union(NSRect(x:x,y:y,width:1,height:1)) }
                } }
                let factor=height/visible.height
                let width=CGFloat(frame.width)*factor
                for (side,color) in [(0,NSColor(calibratedWhite:0.98,alpha:1)),(1,NSColor(calibratedWhite:0.14,alpha:1))] {
                    let box=NSRect(x:x+15+CGFloat(side)*175,y:top,width:165,height:height+20)
                    color.setFill();box.fill()
                    NSGraphicsContext.saveGraphicsState();NSBezierPath(rect:box).addClip()
                    frame.draw(in:NSRect(x:box.midX-visible.midX*factor,y:box.minY+10-visible.minY*factor,width:width,height:CGFloat(frame.height)*factor),mirrored:false)
                    NSGraphicsContext.restoreGraphicsState()
                }
                ("可见主体 \(Int(height)) pt · 原图渲染" as NSString).draw(at:NSPoint(x:x+20,y:top+height+23),withAttributes:detail)
            }
        }
        ("按可见主体对齐的比较样例；源图保留，未替换生产素材，未启动游戏。" as NSString).draw(at:NSPoint(x:20,y:342),withAttributes:detail)
    }
}
let view=Comparison(frame:NSRect(x:0,y:0,width:760,height:374))
let window=NSWindow(contentRect:view.frame,styleMask:[.borderless],backing:.buffered,defer:false)
window.isReleasedWhenClosed=false;window.contentView=view
view.layoutSubtreeIfNeeded()
let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
view.cacheDisplay(in:view.bounds,to:bitmap)
try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[3]))
assert(!window.isVisible)
print("PASS: unshown production stand renderer, 128/64 pt on light/dark; no worker or save")
window.close()
'''
with tempfile.TemporaryDirectory(prefix='tianmu-style-compare-') as folder:
    folder=Path(folder);fixture=folder/'pixel';fixture.mkdir()
    paint_fixture=folder/'paint';paint_fixture.mkdir()
    shutil.copy2(PAINT,paint_fixture/'stand.png')
    (paint_fixture/'manifest.json').write_text(json.dumps({'version':1,'sampling':'smooth','stand':{'file':'stand.png','facing':'left'}}))
    shutil.copy2(PIXEL,fixture/'stand.png')
    (fixture/'manifest.json').write_text(json.dumps({'version':1,'sampling':'nearest','stand':{'file':'stand.png','facing':'right'}}))
    source=(ROOT/'native/OverlayHost.swift').read_text().split('// A presentation of service facts')[0]
    (folder/'Artwork.swift').write_text(source);(folder/'main.swift').write_text(HARNESS)
    subprocess.run(['swiftc',str(folder/'Artwork.swift'),str(folder/'main.swift'),'-o',str(folder/'render')],check=True)
    subprocess.run([str(folder/'render'),str(paint_fixture),str(fixture),str(args.output.resolve()),args.label],check=True)
    assert PIXEL.read_bytes()==(fixture/'stand.png').read_bytes()
    print('pixel',hashlib.sha256(PIXEL.read_bytes()).hexdigest())
    print('paint',hashlib.sha256(PAINT.read_bytes()).hexdigest())
