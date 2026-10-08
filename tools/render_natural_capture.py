"""Render actual capture views offscreen; no host, worker or stored state."""
import argparse
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import AppKit
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let output = URL(fileURLWithPath:CommandLine.arguments[1])
var now:TimeInterval = 37
let layer = DesktopInsects(screens:[DesktopInsectScreen(id:"fixture",frame:NSRect(x:0,y:0,width:480,height:320))],
    renderTime:{now},windowPresenter:{_ in})
layer.update(rows:[["id":"fly","x":0.5,"y":0.5,"color":"普通褐色"]]); layer.show()
let insect = layer.positions[0].point
layer.updatePointer(insect,buttonsPressed:0)
let handle = layer.captureHandleWindow!, desktop = layer.windows[0]
func render(_ name:String) {
    let image = NSImage(size:desktop.frame.size)
    image.lockFocus()
    NSColor(calibratedRed:0.93,green:0.91,blue:0.86,alpha:1).setFill()
    NSRect(origin:.zero,size:desktop.frame.size).fill()
    func composite(_ window:NSWindow) {
        let view = window.contentView!
        let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
        view.cacheDisplay(in:view.bounds,to:bitmap)
        let tile = NSImage(size:view.bounds.size); tile.addRepresentation(bitmap)
        tile.draw(in:window.frame,from:.zero,operation:.sourceOver,fraction:1)
    }
    composite(desktop)
    if layer.isNaturalHandleVisible {
        composite(handle)
    }
    image.unlockFocus()
    let bitmap = NSBitmapImageRep(data:image.tiffRepresentation!)!
    try! bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name+".png"))
}
func mouse(_ type:NSEvent.EventType,_ point:NSPoint)->NSEvent {
    NSEvent.mouseEvent(with:type,location:handle.convertPoint(fromScreen:point),modifierFlags:[],timestamp:now,
        windowNumber:handle.windowNumber,context:nil,eventNumber:1,clickCount:1,pressure:1)!
}
render("hover")
let start = NSPoint(x:handle.frame.midX,y:handle.frame.midY), end = NSPoint(x:start.x+170,y:start.y-115)
handle.contentView!.mouseDown(with:mouse(.leftMouseDown,start))
handle.contentView!.mouseDragged(with:mouse(.leftMouseDragged,end)); render("selection")
handle.contentView!.mouseUp(with:mouse(.leftMouseUp,end))
now += 0.65; layer.refresh(); render("weaving")
assert(!desktop.isVisible && !handle.isVisible && desktop.ignoresMouseEvents)
layer.close()
print("PASS: three actual AppKit views rendered offscreen; no worker, save or visible window")
'''
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args().output.resolve(); output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tianmu-net-render-') as directory:
        folder=Path(directory); source=folder/'main.swift'; source.write_text(HARNESS)
        binary=folder/'render'
        subprocess.run(['swiftc','-framework','AppKit',str(ROOT/'native/v1/WindowPlacement.swift'), str(ROOT/'native/v1/DesktopInsects.swift'), str(ROOT/'native/v1/InsectArtwork.swift'),str(source),'-o',str(binary)],check=True,timeout=60)
        subprocess.run([str(binary),str(output)],check=True,timeout=20)
if __name__ == '__main__': main()
