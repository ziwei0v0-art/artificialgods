import AppKit
import Foundation

// A menu-bar-only alternative. Original curves, no image inputs or production edits.
// Coordinates are SVG-style y-down in a 24-unit square.
let outline = [
    "M 12 5.1",
    "C 16.5 5.1 19.8 6.8 20.8 9.6",
    "C 21.55 9.55 22.15 9.15 22.65 8.95",
    "C 23.05 8.78 23.23 9.06 22.98 9.44",
    "C 22.73 10.24 22.3 10.95 22.05 11.4",
    "C 22.6 13.6 22.0 16.1 20.6 17.8",
    "C 18.9 19.5 15.5 20.0 12.0 20.0",
    "C 8.5 20.0 5.1 19.5 3.4 17.8",
    "C 2.0 16.1 1.4 13.6 1.95 11.4",
    "C 1.7 10.95 1.27 10.24 1.02 9.44",
    "C 0.77 9.06 0.95 8.78 1.35 8.95",
    "C 1.85 9.15 2.45 9.55 3.2 9.6",
    "C 4.2 6.8 7.5 5.1 12.0 5.1", "Z"
]

func path() -> NSBezierPath {
    let result = NSBezierPath()
    for line in outline {
        let words = line.split(separator: " ")
        let n = words.dropFirst().map { CGFloat(Double($0)!) }
        switch words[0] {
        case "M": result.move(to: NSPoint(x:n[0],y:n[1]))
        case "C": result.curve(to:NSPoint(x:n[4],y:n[5]), controlPoint1:NSPoint(x:n[0],y:n[1]), controlPoint2:NSPoint(x:n[2],y:n[3]))
        case "Z": result.close()
        default: fatalError("Invalid path")
        }
    }
    return result
}

func ink(_ value: UInt32) -> NSColor {
    NSColor(srgbRed:CGFloat((value >> 16)&255)/255, green:CGFloat((value >> 8)&255)/255,
            blue:CGFloat(value&255)/255, alpha:1)
}

func drawMark(_ frame:NSRect, white:Bool=false) {
    let context=NSGraphicsContext.current!.cgContext
    context.saveGState()
    context.beginTransparencyLayer(auxiliaryInfo:nil)
    context.translateBy(x:frame.minX,y:frame.maxY)
    let scale=frame.width/24
    context.scaleBy(x:scale,y:-scale)
    (white ? NSColor.white : NSColor.black).setFill()
    path().fill()
    context.setBlendMode(.clear)
    // Slightly above the cheek midpoint. Two short eyes, no mouth or hair detail.
    for cx:CGFloat in [8.1,15.9] {
        let x=(floor(cx*scale)+0.5)/scale
        let y=(floor(11.9*scale)+0.5)/scale
        let w=max(2,1.35/scale), h=max(3,1.9/scale)
        NSBezierPath(roundedRect:NSRect(x:x-w/2,y:y-h/2,width:w,height:h),
                     xRadius:w/2,yRadius:w/2).fill()
    }
    context.endTransparencyLayer()
    context.restoreGState()
}

func png(_ width:Int,_ height:Int,_ url:URL,_ draw:()->Void) throws {
    let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:width,pixelsHigh:height,
        bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,
        bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
    NSGraphicsContext.current!.cgContext.clear(CGRect(x:0,y:0,width:width,height:height))
    draw()
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using:.png,properties:[:])!.write(to:url,options:.withoutOverwriting)
}

func label(_ s:String,_ rect:NSRect,size:CGFloat=14,color:UInt32=0x525A62,weight:NSFont.Weight = .regular) {
    (s as NSString).draw(in:rect,withAttributes:[.font:NSFont.systemFont(ofSize:size,weight:weight),.foregroundColor:ink(color)])
}

func bar(_ rect:NSRect,dark:Bool) {
    ink(dark ? 0x373B43 : 0xE6E9EE).setFill()
    NSBezierPath(roundedRect:rect,xRadius:10,yRadius:10).fill()
    let foreground:UInt32=dark ? 0xFFFFFF : 0x24272C
    let center=rect.midY
    // This is a newly drawn context mockup, not a screenshot or installed menu item.
    label("右上角",NSRect(x:rect.minX+15,y:center-8,width:90,height:20),size:13,color:foreground)
    drawMark(NSRect(x:rect.maxX-262,y:center-9,width:18,height:18),white:dark)
    for (symbol,offset,width):(String,CGFloat,CGFloat) in [("wifi",218,19),("battery.100percent",180,26)] {
        if let original=NSImage(systemSymbolName:symbol,accessibilityDescription:nil) {
            let image=original.withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize:14,weight:.medium))!
            let tint=NSImage(size:image.size,flipped:false) { r in
                image.draw(in:r)
                ink(foreground).setFill(); r.fill(using:.sourceAtop)
                return true
            }
            tint.draw(in:NSRect(x:rect.maxX-offset,y:center-7,width:width,height:14))
        }
    }
    label("周日  18:35",NSRect(x:rect.maxX-130,y:center-8,width:114,height:20),size:13,color:foreground)
}

guard CommandLine.arguments.count==2 else { fatalError("Usage: menu_mark_168 <new-directory>") }
let output=URL(fileURLWithPath:CommandLine.arguments[1],isDirectory:true)
guard !FileManager.default.fileExists(atPath:output.path) else { fatalError("Use a new output directory") }
try FileManager.default.createDirectory(at:output,withIntermediateDirectories:true)
for size in [16,18,22] {
    for scale in [1,2] {
        let pixels=size*scale
        try png(pixels,pixels,output.appendingPathComponent("MenuBarIcon-\(size)\(scale==2 ? "@2x" : "").png")) {
            drawMark(NSRect(x:0,y:0,width:pixels,height:pixels))
        }
    }
}
try png(240,240,output.appendingPathComponent("轮廓放大.png")) {
    drawMark(NSRect(x:0,y:0,width:240,height:240))
}
let svg="""
<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24">
 <defs><mask id="eyes"><rect width="24" height="24" fill="white"/>
 <rect x="7.1" y="10.4" width="2" height="3" rx="1" fill="black"/>
 <rect x="14.9" y="10.4" width="2" height="3" rx="1" fill="black"/>
 </mask></defs>
 <path d="\(outline.joined(separator:" "))" fill="currentColor" mask="url(#eyes)"/>
</svg>
"""
try svg.write(to:output.appendingPathComponent("menu-template.svg"),atomically:true,encoding:.utf8)
try png(820,394,output.appendingPathComponent("菜单栏_软团子_实际尺寸.png")) {
    ink(0xF8F8F7).setFill(); NSRect(x:0,y:0,width:820,height:394).fill()
    label("菜单栏 · 软团子",NSRect(x:28,y:337,width:460,height:32),size:25,color:0x22272B,weight:.semibold)
    label("先看实际大小：18 pt，单色，透明底",NSRect(x:29,y:305,width:560,height:23),size:14)
    bar(NSRect(x:28,y:228,width:600,height:52),dark:false)
    bar(NSRect(x:28,y:153,width:600,height:52),dark:true)
    drawMark(NSRect(x:655,y:181,width:132,height:132))
    label("轮廓放大",NSRect(x:681,y:161,width:100,height:22),size:13)
    label("16 pt",NSRect(x:28,y:84,width:70,height:22),size:13)
    drawMark(NSRect(x:100,y:88,width:16,height:16))
    label("18 pt",NSRect(x:180,y:84,width:70,height:22),size:13)
    drawMark(NSRect(x:252,y:87,width:18,height:18))
    label("22 pt",NSRect(x:332,y:84,width:70,height:22),size:13)
    drawMark(NSRect(x:404,y:85,width:22,height:22))
    label("饱满的脸 · 两颗短眼睛 · 轻轻翘起的耳尖",NSRect(x:29,y:28,width:710,height:24),size:14)
}
print(output.path)
