import AppKit
import Foundation

// A small monochrome silhouette stays readable in the menu bar and handles.
// The application icon is packaged from the separately generated production PNG.
enum TianmuBrandArtwork {
    static func spider(size: CGFloat = 18, template: Bool = true, reminder: Bool = false) -> NSImage {
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { rectangle in
            drawSpider(in: rectangle, template: template, reminder: reminder)
            return true
        }
        image.isTemplate = template
        image.accessibilityDescription = reminder ? "灶神，计时结束" : "灶神"
        return image
    }
    static func drawSpider(in rectangle: NSRect, template: Bool, reminder: Bool = false) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState(); defer { context.restoreGState() }
        context.translateBy(x: rectangle.minX, y: rectangle.minY)
        context.scaleBy(x: rectangle.width / 100, y: rectangle.height / 100)
        let body = template ? NSColor.black : NSColor(red:0.98,green:0.96,blue:0.86,alpha:1)
        body.setFill()
        // Eight soft nubs merge into a low, broad body at menu-bar size.
        for side: CGFloat in [-1, 1] {
            for point in [(33.0,36.0),(31.0,29.0),(23.0,24.0),(12.0,22.0)] {
                NSBezierPath(ovalIn:NSRect(x:50+side*point.0-8,y:point.1-6,width:16,height:13)).fill()
            }
        }
        NSBezierPath(ovalIn:NSRect(x:14,y:22,width:72,height:51)).fill()
        if template {
            context.setBlendMode(.clear)
            context.fillEllipse(in:NSRect(x:34,y:40,width:9,height:11))
            context.fillEllipse(in:NSRect(x:57,y:40,width:9,height:11))
            context.setBlendMode(.normal)
        } else {
            NSColor(red:0.28,green:0.22,blue:0.17,alpha:1).setFill()
            NSBezierPath(ovalIn:NSRect(x:35,y:40,width:9,height:11)).fill()
            NSBezierPath(ovalIn:NSRect(x:56,y:40,width:9,height:11)).fill()
            NSColor.white.setFill()
            NSBezierPath(ovalIn:NSRect(x:37,y:47,width:2.5,height:2.5)).fill()
            NSBezierPath(ovalIn:NSRect(x:58,y:47,width:2.5,height:2.5)).fill()
            NSColor(red:0.85,green:0.55,blue:0.40,alpha:0.65).setFill()
            NSBezierPath(ovalIn:NSRect(x:26,y:34,width:9,height:5)).fill()
            NSBezierPath(ovalIn:NSRect(x:65,y:34,width:9,height:5)).fill()
        }
        if reminder {
            (template ? NSColor.black : NSColor(red:0.78,green:0.40,blue:0.22,alpha:1)).setFill()
            NSBezierPath(ovalIn:NSRect(x:78,y:78,width:17,height:17)).fill()
        }
    }

}

final class UIArtifactLibrary {
    static var shared = UIArtifactLibrary()
    private let images: [String:NSImage]
    init(resourceRoot: URL? = Bundle.main.resourceURL?.appendingPathComponent("art/ui")) {
        var loaded: [String:NSImage] = [:]
        if let root = resourceRoot,
           let data = try? Data(contentsOf:root.appendingPathComponent("manifest.json")), data.count < 65536,
           let document = try? JSONSerialization.jsonObject(with:data) as? [String:Any],
           document["version"] as? Int == 1,
           let assets = document["assets"] as? [String:[String:Any]] {
            for (key,row) in assets {
                guard let file = row["file"] as? String, !file.contains("/"), file.hasSuffix(".png"),
                      let crop = row["sourceRect"] as? [Double], crop.count == 4,
                      crop.allSatisfy({ $0.isFinite && $0 >= 0 }), crop[2] > 0, crop[3] > 0,
                      let image = NSImage(contentsOf:root.appendingPathComponent(file)),
                      let cg = image.cgImage(forProposedRect:nil,context:nil,hints:nil),
                      crop[0]+crop[2] <= Double(cg.width), crop[1]+crop[3] <= Double(cg.height),
                      let clipped = cg.cropping(to:CGRect(x:crop[0],y:crop[1],width:crop[2],height:crop[3])) else { continue }
                loaded[key] = NSImage(cgImage:clipped,size:NSSize(width:crop[2],height:crop[3]))
            }
        }
        images = loaded
    }
    func image(_ name: String) -> NSImage? { images[name] }
}

// Values remain tied to the service timer; the art never starts another timer.
struct TimerVisualProgress {
    let fraction: Double
    let running: Bool
    init(snapshot: [String:Any], now: TimeInterval = Date().timeIntervalSince1970) {
        running = snapshot["status"] as? String == "running"
        let mode = snapshot["mode"] as? String ?? "clock"
        let status = snapshot["status"] as? String ?? "idle"
        if status == "finished" { fraction = 1; return }
        if mode == "countdown" || mode == "pomodoro" {
            let key = mode == "countdown" ? "countdown_seconds"
                : (snapshot["phase"] as? String == "break" ? "break_seconds" : "work_seconds")
            let duration = (snapshot[key] as? NSNumber)?.doubleValue ?? 0
            var remaining = (snapshot["remaining_milliseconds"] as? NSNumber).map { $0.doubleValue / 1000 }
                ?? (snapshot["remaining_seconds"] as? NSNumber)?.doubleValue ?? duration
            if running, let deadline = (snapshot["deadline"] as? NSNumber)?.doubleValue { remaining = max(0,deadline-now) }
            fraction = status != "idle" && duration.isFinite && duration > 0 && remaining.isFinite
                ? min(1,max(0,1-remaining/duration)) : 0
        } else if mode == "stopwatch" {
            let base = (snapshot["elapsed_milliseconds"] as? NSNumber).map { $0.doubleValue / 1000 }
                ?? (snapshot["elapsed_seconds"] as? NSNumber)?.doubleValue ?? 0
            let start = (snapshot["started_at"] as? NSNumber)?.doubleValue ?? now
            let elapsed = base + (running ? max(0,now-start) : 0)
            fraction = elapsed.isFinite ? elapsed.truncatingRemainder(dividingBy:60)/60 : 0
        } else {
            var calendar = Calendar(identifier:.gregorian)
            if let zone = snapshot["clock_timezone"] as? String, zone != "local", let timezone = TimeZone(identifier:zone) {
                calendar.timeZone = timezone
            }
            let parts = calendar.dateComponents([.hour,.minute,.second],from:Date(timeIntervalSince1970:now))
            let hours = ((parts.hour ?? 0) % 12) * 3600
            let minutes = (parts.minute ?? 0) * 60
            let seconds = parts.second ?? 0
            fraction = Double(hours + minutes + seconds) / 43200.0
        }
    }
}

// Adapted from BongoCat's historical dial implementation (AGPL-3.0-only).
// Pinned sources, original license and translation/oracle notes:
// third_party/bongocat-dial/NOTICE.md. Coordinates intentionally retain y-down.
enum SceneDialGeometry {
    private static let pi: Float = 3.14159265358979323846
    private static let pathPointLimit = 160

    private struct Point {
        var x: Float
        var y: Float
        var native: NSPoint { NSPoint(x:Double(x),y:Double(y)) }
    }
    private static func polar(_ radius: Float, _ angle: Float) -> Point {
        Point(x:radius*cosf(angle),y:radius*sinf(angle))
    }
    private static func angleDistance(_ a: Float, _ b: Float) -> Float {
        atan2f(sinf(a-b),cosf(a-b))
    }
    private static func rootAngleFloat(index: Int, count: Int) -> Float {
        -pi/2 + Float(index)*2*pi/Float(count)
    }
    static func rootAngle(index: Int, count: Int) -> Double {
        guard count > 0 else { return 0 }
        return Double(rootAngleFloat(index:index,count:count))
    }

    /// Original dial_sector vertex sequence; CGPath can fill the resulting polygon directly.
    static func sector(inner: Double, outer: Double, start: Double, end: Double) -> [NSPoint] {
        let inner = Float(inner), outer = Float(outer), start = Float(start), end = Float(end)
        guard inner.isFinite, outer.isFinite, start.isFinite, end.isFinite,
              inner > 0, outer > inner, end > start,
              (end-start)*outer/3 < 100_000 else { return [] }
        var points: [Point] = []
        func point(_ value: Point) {
            if let last = points.last, hypotf(value.x-last.x,value.y-last.y) < 0.001 { return }
            if points.count < pathPointLimit { points.append(value) }
        }
        func quad(_ a: Point, _ control: Point, _ b: Point) {
            point(a)
            for index in 1...6 {
                let t = Float(index)/6, u: Float = 1-t
                let x: Float = u*u*a.x + 2*u*t*control.x + t*t*b.x
                let y: Float = u*u*a.y + 2*u*t*control.y + t*t*b.y
                point(Point(x:x,y:y))
            }
        }
        func arc(_ radius: Float, _ a: Float, _ b: Float) {
            let steps = max(1,Int(ceilf(fabsf(b-a)*radius/3)))
            for index in 0...steps {
                point(polar(radius,a+(b-a)*Float(index)/Float(steps)))
            }
        }
        let corner: Float = 12, a = start+0.024, b = end-0.024
        let ci = corner/inner, co = corner/outer
        point(polar(outer-corner,b))
        quad(polar(inner+corner,b),polar(inner,b),polar(inner,b-ci))
        arc(inner,b-ci,a+ci)
        quad(polar(inner,a+ci),polar(inner,a),polar(inner+corner,a))
        quad(polar(outer-corner,a),polar(outer,a),polar(outer,a+co))
        arc(outer,a+co,b-co)
        quad(polar(outer,b-co),polar(outer,b),polar(outer-corner,b))
        if points.count > 1 { points.removeLast() }
        return points.map(\.native)
    }

    static func childStep(childCount: Int, compact: Bool = false) -> Double {
        Double(Float(compact || childCount > 11 ? 0.32 : 0.50))
    }
    static func childAngle(root: Int, index: Int, count: Int, childCount: Int,
                           compactChildren: Bool? = nil) -> Double {
        guard count > 0 else { return 0 }
        let childCount = min(16,max(0,childCount))
        let step = Float(childStep(childCount:childCount,compact:compactChildren ?? (root == 4 || root == 5)))
        return Double(rootAngleFloat(index:root,count:count) + (Float(index)-Float(childCount-1)/2)*step)
    }

    /// Raw upstream dial_hit: retains active across the center and radial gap.
    static func hit(point: NSPoint, count: Int, active: Int, childCount: Int, childFocus: Bool,
                    compactChildren: Bool? = nil) -> (root: Int, child: Int) {
        let x = Float(point.x), y = Float(point.y)
        guard count > 0, active >= -1, active < count, x.isFinite, y.isFinite else { return (-1,-1) }
        let radius = hypotf(x,y), angle = atan2f(y,x)
        let children = min(16,max(0,childCount))
        let step = Float(childStep(childCount:children,compact:compactChildren ?? (active == 4 || active == 5)))
        if active >= 0 && radius >= 190 && radius <= 277 {
            for index in 0..<children {
                let center = Float(childAngle(root:active,index:index,count:count,childCount:children,compactChildren:compactChildren))
                if fabsf(angleDistance(angle,center)) < step/2 { return (active,index) }
            }
        }
        if radius >= 73 && radius <= 198 {
            for index in 0..<count {
                if childFocus && index != active { continue }
                let center = rootAngleFloat(index:index,count:count)
                if fabsf(angleDistance(angle,center)) <= pi/Float(count) { return (index,-1) }
            }
        }
        return radius <= 280 ? (active,-1) : (-1,-1)
    }

    /// Coordinates are already relative to center and divided by layout × opening scale.
    static func pointerHit(point: NSPoint, count: Int, active: Int, childCount: Int,
                           childFocus: Bool, click: Bool, compactChildren: Bool? = nil)
        -> (root: Int, child: Int, childFocus: Bool) {
        let x = Float(point.x), y = Float(point.y), radius = hypotf(Float(point.x),Float(point.y))
        let focus = childFocus && !(radius < 190)
        var result = hit(point:point,count:count,active:active,childCount:childCount,
                         childFocus:focus,compactChildren:compactChildren)
        if click && result.child < 0 && result.root >= 0 {
            let angle = atan2f(y,x)-rootAngleFloat(index:result.root,count:count)
            if radius < 73 || radius > 198 || fabsf(atan2f(sinf(angle),cosf(angle))) > pi/Float(count) {
                result.root = -1
            }
        }
        return (result.root,result.child,focus)
    }

    static func reveal(elapsedMilliseconds: Double, index: Int) -> Double {
        guard elapsedMilliseconds.isFinite else { return 0 }
        let elapsed = Float(max(0,elapsedMilliseconds))-Float(index*22)
        let t = fmaxf(0,fminf(1,elapsed/360))
        return Double(1-powf(1-t,3))
    }
    static func opening(elapsedMilliseconds: Double) -> Double {
        guard elapsedMilliseconds.isFinite else { return 0.85 }
        let t = fminf(1,Float(max(0,elapsedMilliseconds))/700)
        return Double(0.85 + Float(0.15)*(1-powf(1-t,4)))
    }
    static func hoverLift(current: Double, target: Double, elapsedSeconds: Double) -> Double {
        guard current.isFinite, target.isFinite, elapsedSeconds.isFinite else { return 0 }
        let elapsed = fminf(0.1,Float(max(0,elapsedSeconds)))
        let response = 1-expf(-17*elapsed)
        let current = Float(current), target = Float(target)
        let next = current+(target-current)*response
        return Double(fabsf(next-target) < 0.002 ? target : next)
    }
}
