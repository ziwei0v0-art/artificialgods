"""Render the actual AppKit PNG scene without a window or game service."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
out = root / 'evidence/1.0/151-visual'
out.mkdir(exist_ok=True)
swift = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let out = URL(fileURLWithPath:CommandLine.arguments[1])
let art = AttendantArtwork.load(from:URL(fileURLWithPath:CommandLine.arguments[2]))!
func render(_ scale:Double, _ name:String, _ background:NSColor?) {
    let view = TianmuView(frame:NSRect(x:0,y:0,width:370*scale,height:190*scale))
    view.attendantArtwork = art
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
}
render(0.2,"small-transparent",nil)
render(0.75,"default-transparent",nil)
render(0.75,"default-light",NSColor(calibratedWhite:0.94,alpha:1))
render(0.75,"default-dark",NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1))
render(1.5,"large-light",NSColor(calibratedWhite:0.94,alpha:1))
print("RENDER_PASS actual production PNG at 20/75/150 percent. No window, no worker. walk=\(art.hasWalkFrames)")
'''
with tempfile.TemporaryDirectory(prefix='tianmu-a01-render-') as folder:
    work = Path(folder)
    (work / 'Scene.swift').write_text((root / 'native/OverlayHost.swift').read_text().split('final class Host:')[0])
    (work / 'main.swift').write_text(swift)
    result = subprocess.run(['swiftc', '-framework', 'AppKit', str(work / 'Scene.swift'), str(work / 'main.swift'), '-o', str(work / 'render')], capture_output=True, text=True)
    print(result.stdout, result.stderr)
    result.check_returncode()
    result = subprocess.run([str(work / 'render'), str(out), str(root / 'assets/production/A01')], capture_output=True, text=True)
    print(result.stdout, result.stderr)
    result.check_returncode()
