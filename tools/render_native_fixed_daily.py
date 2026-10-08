"""Review daily gestures and ritual priority through actual TianmuView/G0, without a live game."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / 'assets/incoming/A01_daily_props_20261001'
DAILY = {
    'farSleeve': {'mask': [[345, 603], [489, 603], [489, 815], [395, 815],
                           [381, 785], [370, 725], [351, 663]], 'pivot': [348, 633]},
    'head': {'mask': [[0, 0], [489, 0], [489, 568], [0, 568]], 'pivot': [296, 556]},
    'handCover': [155, 779, 48, 29],
    'props': {
        'book': {'file': 'book-v01-original.png', 'sourceRect': [330, 341, 876, 402],
                 'height': 100, 'grip': [0.5, 0.9]},
        'broom': {'file': 'broom-v01-original.png', 'sourceRect': [376, 96, 317, 1284],
                  'grip': [0.5, 0.30], 'groundY': 976},
        'fruit': {'file': 'G0-fruit-fresh-v01.png', 'sourceRect': [372, 191, 822, 637],
                  'height': 130, 'grip': [0.5, 0.9]},
        'bell': {'file': 'bell-v01-original.png', 'sourceRect': [362, 287, 459, 756],
                 'height': 170, 'grip': [0.5, 0.13]},
        'incense': {'file': 'incense-stick-v01-original.png', 'sourceRect': [494, 222, 36, 1100],
                    'height': 240, 'grip': [0.5, 0.92], 'rotation': 15, 'minCoreWidth': 1.5},
        'paper': {'file': 'paper-slip-v01-original.png', 'sourceRect': [291, 265, 444, 1009],
                  'height': 165, 'grip': [0.5, 0.9]},
    },
}

# Share the already verified offscreen I/O and preparation helpers, never its run loop.
SHARED_PATH = ROOT / 'tools/render_native_fixed_actions.py'
READ_ONLY_REVIEW = r'''
extension TianmuView {
    func drawDailyReviewLayer(_ kind:String) {
        if kind=="stove-incense" {sceneIncenseSprite()?.draw(designToView:designToViewTransform)}
        else if kind=="smoke" {drawRitualSmoke()}
        else if kind=="held-incense",let frame=attendantArtwork?.propFrame("incense") {
            for sprite in attendantSprites() ?? [] where sprite.frame.width==frame.width && sprite.frame.height==frame.height {
                sprite.draw(designToView:designToViewTransform)
            }
        }
    }
    func dailyReviewMetrics() -> [[String:Any]] {
        guard let art=attendantArtwork,let frame=art.propFrame("incense"),
              let core=art.propCoreBounds("incense") else {return []}
        var rows=[[String:Any]]()
        func row(_ kind:String,_ sprite:MappedSprite)->[String:Any] {
            let t=sprite.pixelToDesign
            let width=core.width*hypot(t.a,t.b)*scaleFactor
            return ["kind":kind,"fraction":Double(sprite.fraction),"core_width_pt":Double(width),
                    "core_bottom_center_design":[Double(NSPoint(x:core.midX,y:core.maxY).applying(t).x),
                                                 Double(NSPoint(x:core.midX,y:core.maxY).applying(t).y)]]
        }
        for sprite in attendantSprites() ?? [] where sprite.frame.width==frame.width && sprite.frame.height==frame.height {
            rows.append(row("held-incense",sprite))
        }
        if let sprite=sceneIncenseSprite(),let anchor=ritualAnchor {
            var value=row("stove-incense",sprite)
            value["expected_anchor_design"]=[Double(anchor.x),Double(anchor.y)]
            let bottom=NSPoint(x:core.midX,y:core.maxY).applying(sprite.pixelToDesign)
            value["anchor_error_design"]=Double(hypot(bottom.x-anchor.x,bottom.y-anchor.y))
            rows.append(value)
        }
        return rows
    }
}
'''
tree = ast.parse(SHARED_PATH.read_text())
shared = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'SWIFT' for target in node.targets))
SWIFT = shared.split('struct ReviewRow {')[0] + r'''
struct DailyAction {
    let name: String, title: String, duration: Int, stage: String?
    var service: Bool { stage == nil && name != "response" }
}
let actions = [
    DailyAction(name: "read", title: "读书", duration: 18000, stage: nil),
    DailyAction(name: "sweep", title: "扫地", duration: 12000, stage: nil),
    DailyAction(name: "practice", title: "肃立功课", duration: 45000, stage: nil),
    DailyAction(name: "offer", title: "托果反馈", duration: 8000, stage: nil),
    DailyAction(name: "bell", title: "摇铃", duration: 4000, stage: nil),
    DailyAction(name: "rest", title: "站立放松", duration: 60000, stage: nil),
    DailyAction(name: "incense", title: "持香", duration: 2000, stage: "取香行礼"),
    DailyAction(name: "paper", title: "持空白纸", duration: 2000, stage: "呈出签纸"),
    DailyAction(name: "response", title: "短回应", duration: 1100, stage: nil),
]
var checks: [[String: Any]] = [], boundaries: [[String: Any]] = [], productScaleChecks: [[String: Any]] = [], incenseMetrics: [[String:Any]] = [], incensePixelChecks: [[String:Any]] = []
func saveJSON(_ value: Any, _ name: String) {
    try! JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        .write(to: output.appendingPathComponent(name))
}
struct ContactRow {
    let name: String, title: String, direction: String
    let images: [CGImage], labels: [String]
}
func regularTimes(_ duration: Int, _ important: [Int]) -> [Int] {
    var times = Set(important + [0, 80, 160, 250, 350, 550, 800, duration, duration+80, duration+160, duration+220, duration+500])
    for i in 0...40 { times.insert(Int((Double(duration)*Double(i)/40).rounded())) }
    for delta in [550, 350, 200, 80] { times.insert(duration-delta) }
    return times.filter { $0 >= 0 && $0 <= duration+500 }.sorted()
}
func normalContactTimes(_ duration: Int) -> [Int] {
    [0, Int(Double(duration)*0.15), Int(Double(duration)*0.4), Int(Double(duration)*0.8), duration-80, duration, duration+220]
}
func preparedIdle(_ size: Int, _ direction: String) -> (TianmuView, Double, Int) {
    let (v, start, serial) = prepared(size, direction)
    feed(v, "idle", serial, 0, 0, start)
    return (v, start, serial+1)
}
func begin(_ action: DailyAction, _ v: TianmuView, _ serial: Int, _ start: Double, _ elapsed: Double = 0) {
    if action.service {
        feed(v, action.name, serial, elapsed, Double(action.duration)/1000, start)
        precondition(v.unavailableRoutineAction == nil, "Daily action unavailable: \(action.name)")
    } else if let stage = action.stage {
        v.ritualStage = stage; v.updateAnimation(elapsed: start)
    } else { v.respond(); v.updateAnimation(elapsed: start) }
}
func audit(_ b: NSBitmapImageRep, _ stand: NSBitmapImageRep, _ v: TianmuView,
           _ name: String, _ direction: String, _ size: Double, _ elapsed: Double) {
    for var metric in v.dailyReviewMetrics() {
        metric["case"]=name;metric["direction"]=direction;metric["attendant_height_pt"]=size;metric["elapsed"]=elapsed
        incenseMetrics.append(metric)
        if (metric["fraction"] as! Double)>0.99 {
            precondition((metric["core_width_pt"] as! Double)>=1.5-0.000001,"Visible incense core is narrower than 1.5pt")
        }
        if let error=metric["anchor_error_design"] as? Double {precondition(error<0.000001,"Stove incense missed actual ash-bed anchor")}
    }
    let width = b.pixelsWide, height = b.pixelsHigh, data = b.bitmapData!, base = stand.bitmapData!
    var x0=width, y0=height, x1 = -1, y1 = -1, vx0=width, vy0=height, vx1 = -1, vy1 = -1
    var edge = [0,0,0,0], newEdge = [0,0,0,0]
    for y in 0..<height { for x in 0..<width {
        let alpha = Int(data[y*b.bytesPerRow+x*4+3])
        if alpha > 0 { x0=min(x0,x);y0=min(y0,y);x1=max(x1,x);y1=max(y1,y) }
        if alpha > 16 { vx0=min(vx0,x);vy0=min(vy0,y);vx1=max(vx1,x);vy1=max(vy1,y) }
        if x==0 || x==width-1 || y==0 || y==height-1 {
            let added = alpha>16 && base[y*stand.bytesPerRow+x*4+3]<=16
            if x==0 {edge[0]=max(edge[0],alpha);if added {newEdge[0]+=1}}
            if x==width-1 {edge[1]=max(edge[1],alpha);if added {newEdge[1]+=1}}
            if y==0 {edge[2]=max(edge[2],alpha);if added {newEdge[2]+=1}}
            if y==height-1 {edge[3]=max(edge[3],alpha);if added {newEdge[3]+=1}}
        }
    }}
    let bounds=v.attendantBounds
    boundaries.append(["case":name,"direction":direction,"attendant_height_pt":size,"elapsed":elapsed,
        "scene_alpha_gt0_bbox":[x0,y0,x1-x0+1,y1-y0+1],"scene_alpha_gt16_bbox":[vx0,vy0,vx1-vx0+1,vy1-vy0+1],
        "edge_order":["left","right","top","bottom"],"edge_alpha_max":edge,"new_edge_core_pixels":newEdge,
        "attendant_geometry_bbox":[Double(bounds.minX),Double(bounds.minY),Double(bounds.width),Double(bounds.height)],
        "view_size":[Double(v.bounds.width),Double(v.bounds.height)]])
}
final class Capture {
    let name: String, direction: String, size: Int, times: [Int], contactTimes: [Int]
    let stand: NSBitmapImageRep
    var destinations: [CGImageDestination] = [], selected = [Int:CGImage](), union: NSRect
    init(_ name: String, _ direction: String, _ size: Int, _ times: [Int], _ contacts: [Int], _ stand: NSBitmapImageRep, _ box: NSRect) {
        self.name=name;self.direction=direction;self.size=size;self.times=times;contactTimes=contacts;self.stand=stand;union=box
        for (theme,_,_) in backgrounds {
            let file="scene-\(name)-\(size)pt-\(direction)-\(theme).gif"
            let destination=CGImageDestinationCreateWithURL(output.appendingPathComponent(file) as CFURL,"com.compuserve.gif" as CFString,times.count,nil)!
            CGImageDestinationSetProperties(destination,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
            destinations.append(destination)
        }
    }
    func add(_ raw: NSBitmapImageRep, _ v: TianmuView, _ index: Int, _ still: Bool=false) {
        let ms=times[index],delay=index+1<times.count ? Double(times[index+1]-ms)/1000 : 0.4
        audit(raw,stand,v,name,direction,Double(size),Double(ms)/1000)
        union=union.union(v.attendantBounds)
        if contactTimes.contains(ms) {selected[ms]=raw.cgImage!}
        for (themeIndex,entry) in backgrounds.enumerated() {
            let flat=composite(NSBitmapImageRep(cgImage:raw.cgImage!),entry.1)
            CGImageDestinationAddImage(destinations[themeIndex],flat.cgImage!,[kCGImagePropertyGIFDictionary:[
                kCGImagePropertyGIFDelayTime:max(0.02,delay),kCGImagePropertyGIFUnclampedDelayTime:max(0.02,delay)]] as CFDictionary)
            if still {png(flat,"scene-\(name)-\(size)pt-\(direction)-\(entry.0)-middle.png")}
        }
    }
    func finish(_ title: String, _ labels: [String]?=nil, _ wholeScene: Bool=false) -> ContactRow {
        for destination in destinations {precondition(CGImageDestinationFinalize(destination))}
        let first=selected[contactTimes[0]]!, padded=union.insetBy(dx:-6,dy:-6)
        let crop=NSRect(x:floor(padded.minX),y:floor(CGFloat(first.height)-padded.maxY),width:ceil(padded.width),height:ceil(padded.height))
            .intersection(NSRect(x:0,y:0,width:first.width,height:first.height))
        let images=contactTimes.map { ms in wholeScene ? selected[ms]! : selected[ms]!.cropping(to:crop)! }
        return ContactRow(name:name,title:title,direction:direction,images:images,
            labels:labels ?? contactTimes.map {String(format:"%.2fs",Double($0)/1000)})
    }
}
func normal(_ action: DailyAction, _ size: Int, _ direction: String) -> ContactRow {
    let (v,start,serial)=preparedIdle(size,direction),stand=rawRender(v),baseline=bytes(stand)
    var events=[[String:Any]]();v.emit={events.append($0)}
    let contacts=normalContactTimes(action.duration),times=regularTimes(action.duration,contacts+[800])
    let capture=Capture(action.name,direction,size,times,contacts,stand,v.attendantBounds)
    begin(action,v,serial,start)
    precondition(bytes(rawRender(v))==baseline,"\(action.name) must start at original stand")
    var heartbeat=1,ended=false
    for (index,ms) in times.enumerated() {
        if action.service {
            while heartbeat*1000 <= min(ms,action.duration-1) {
                feed(v,action.name,serial,Double(heartbeat),Double(action.duration)/1000,start+Double(heartbeat));heartbeat += 1
            }
        }
        if !ended && ms>=action.duration {
            v.updateAnimation(elapsed:start+Double(action.duration)/1000)
            if action.service {
                feed(v,action.name,serial,Double(action.duration)/1000,Double(action.duration)/1000,start+Double(action.duration)/1000)
                feed(v,"idle",serial+1,0,0,start+Double(action.duration)/1000)
            } else if action.stage != nil {v.ritualStage=nil}
            ended=true
        }
        v.updateAnimation(elapsed:start+Double(ms)/1000)
        if ms==800 && action.name != "response" {
            let before=bytes(rawRender(v))
            if action.service {precondition(v.applyRoutine(snapshot(action.name,serial,Double(heartbeat-1),Double(action.duration)/1000)))}
            else {v.ritualStage=action.stage}
            precondition(bytes(rawRender(v))==before,"Duplicate \(action.name) input reset its pose")
        }
        let raw=rawRender(v)
        if ms==contacts[2] {precondition(bytes(raw) != baseline,"\(action.name) has no visible middle pose")}
        if ms==action.duration+220 {precondition(bytes(raw)==baseline,"\(action.name) did not restore original stand")}
        capture.add(raw,v,index,ms==contacts[2])
    }
    let business=events.filter{($0["type"] as? String) != "mode"}
    precondition(business.isEmpty,"Rendering must not emit business actions")
    checks.append(["case":action.name,"direction":direction,"size_pt":size,"result":"PASS",
        "duration_seconds":Double(action.duration)/1000,"frames":times.count,"business_emissions":business.count,"ui_mode_emissions":events.count-business.count])
    return capture.finish(action.title)
}
func scenario(_ name: String, _ size: Int, _ direction: String) -> ContactRow {
    let (v,start,serial)=preparedIdle(size,direction),stand=rawRender(v),baseline=bytes(stand),standBox=v.attendantBounds
    let (reference,referenceStart,referenceSerial)=preparedIdle(size,direction)
    var events=[[String:Any]]();v.emit={events.append($0)}
    let isRitual = name=="ritual" || name=="press-ritual"
    let end = name=="press-expiry" ? 5000 : name=="press-switch" ? 3000 : name=="press-response" ? 2200 : 6800
    let contacts: [Int]
    switch name {
    case "ritual": contacts=[800,2800,4800,6220]
    case "press-ritual": contacts=[500,2800,4800,6400,6620]
    case "press-expiry": contacts=[0,800,2000,4000,4500,4580,4720]
    case "press-switch": contacts=[0,800,1200,2400,2480,2560,2620]
    default: contacts=[0,400,1000,1500,1600,1680,1820]
    }
    let eventTimes=[400,500,800,1000,1100,1200,1500,1600,1820,2000,2200,2400,2480,2560,2620,2800,3000,4000,4200,4500,4580,4720,4800,6000,6220,6400,6480,6560,6620]
    let times=regularTimes(end,contacts+eventTimes.filter{$0<=end})
    let capture=Capture(name,direction,size,times,contacts,stand,standBox)
    if isRitual {v.ritualStage="取香行礼"}
    else if name=="press-response" {v.respond()}
    else {feed(v,name=="press-switch" ? "read":"bell",serial,0,name=="press-switch" ? 18:4,start)}
    if name=="press-switch" {feed(reference,"read",referenceSerial,0,18,referenceStart)}
    var held: Data?
    for (index,ms) in times.enumerated() {
        let clock=start+Double(ms)/1000
        v.updateAnimation(elapsed:clock)
        if name=="press-switch" {reference.updateAnimation(elapsed:referenceStart+Double(ms)/1000)}
        if isRitual {
            if ms==400 && name=="ritual" {
                let before=bytes(rawRender(v));v.respond()
                precondition(bytes(rawRender(v))==before,"Response must not override active ritual")
            }
            if ms==500 && name=="press-ritual" {v.mouseDown(with:mouse(headPoint(v,standBox),clock));held=bytes(rawRender(v))}
            if ms==2000 {v.ritualStage="炉烟升起"}
            if ms==4000 {v.ritualStage="呈出签纸"}
            if ms==4200 && name=="press-ritual" {v.respond()}
            if ms==6000 {v.ritualStage=nil}
            if ms==6400 && name=="press-ritual" {v.cancelInteraction();precondition(bytes(rawRender(v))==held!,"Ritual release lost frozen first frame")}
        } else if name=="press-response" {
            if ms==400 {v.mouseDown(with:mouse(headPoint(v,standBox),clock));held=bytes(rawRender(v))}
            if ms==1600 {v.cancelInteraction();precondition(bytes(rawRender(v))==held!,"Response release lost frozen first frame")}
        } else if name=="press-expiry" {
            if ms==800 {v.mouseDown(with:mouse(headPoint(v,standBox),clock));held=bytes(rawRender(v))}
            if [1000,2000,3000,4000].contains(ms) {feed(v,"bell",serial,Double(ms)/1000,4,clock)}
            if ms==4000 {feed(v,"idle",serial+1,0,0,clock)}
            if ms==4500 {v.cancelInteraction();precondition(bytes(rawRender(v))==held!,"Expired service release lost frozen first frame")}
        } else {
            if ms==800 {v.mouseDown(with:mouse(headPoint(v,standBox),clock));held=bytes(rawRender(v))}
            if ms==1200 {
                feed(v,"offer",serial+1,4,8,clock)
                feed(reference,"offer",referenceSerial+1,4,8,referenceStart+1.2)
            }
            if ms==2200 {
                feed(v,"offer",serial+1,5,8,clock)
                feed(reference,"offer",referenceSerial+1,5,8,referenceStart+2.2)
            }
            if ms==2400 {v.cancelInteraction();precondition(bytes(rawRender(v))==held!,"Prop switch release lost frozen first frame")}
        }
        let raw=rawRender(v)
        let release = name=="press-ritual" ? 6400 : name=="press-response" ? 1600 : name=="press-expiry" ? 4500 : 2400
        if let held,ms<release {precondition(bytes(raw)==held,"Press failed to freeze complete displayed pose: \(name)")}
        if name=="press-switch",ms==2620 {precondition(bytes(raw)==bytes(rawRender(reference)),"Release did not consume current offer phase")}
        if (name=="ritual" && ms==6220) || (name=="press-ritual" && ms==6620)
            || (name=="press-response" && ms==1820) || (name=="press-expiry" && ms==4720) {
            precondition(bytes(raw)==baseline,"Expired covered action replayed: \(name)")
        }
        capture.add(raw,v,index,ms==contacts[min(2,contacts.count-1)])
    }
    let business=events.filter{($0["type"] as? String) != "mode"}
    precondition(business.isEmpty,"Visual overrides must not emit business actions")
    checks.append(["case":name,"direction":direction,"size_pt":size,"result":"PASS","frames":times.count,"business_emissions":business.count,"ui_mode_emissions":events.count-business.count])
    let title=["ritual":"求签三阶段与回应优先级","press-ritual":"按住时仪式结束","press-response":"按住时回应到期",
               "press-expiry":"按住时服务动作到期","press-switch":"按住时书切换为供果"][name]!
    return capture.finish(title,nil,isRitual)
}
func contact(_ rows: [ContactRow], _ size: Int, _ group: String) {
    let labels=rows.flatMap{row in row.labels.map{"\(row.title) \(row.direction=="left" ? "左":"右") \($0)"}}
    let textWidth=labels.map{($0 as NSString).size(withAttributes:[.font:NSFont.systemFont(ofSize:10)]).width}.max()!
    let columns=rows.map{$0.images.count}.max()!,cw=max(Int(ceil(textWidth))+16,rows.flatMap(\.images).map(\.width).max()!+16)
    let ch=rows.flatMap(\.images).map(\.height).max()!+32,w=cw*columns+16,h=ch*rows.count+34
    for (theme,bg,ink) in backgrounds {
        let board=bitmap(w,h){
            bg.setFill();NSRect(x:0,y:0,width:w,height:h).fill()
            func label(_ text:String,_ x:CGFloat,_ y:CGFloat){(text as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:10),.foregroundColor:ink])}
            label("实际TianmuView / G0 · \(size)pt · \(group)",12,CGFloat(h-22))
            for (r,row) in rows.enumerated(){for(i,image)in row.images.enumerated(){
                let x=CGFloat(12+i*cw),y=CGFloat(12+(rows.count-1-r)*ch)
                NSImage(cgImage:image,size:NSSize(width:image.width,height:image.height)).draw(in:NSRect(x:x,y:y+20,width:CGFloat(image.width),height:CGFloat(image.height)))
                label("\(row.title) \(row.direction=="left" ? "左":"右") \(row.labels[i])",x,y)
            }}
        }
        png(board,"contact-\(group)-\(size)pt-\(theme).png")
    }
}
func auditProductIncensePixels(_ v:TianmuView,_ action:String,_ direction:String,_ scale:CGFloat) {
    let kinds=action=="incense" ? ["held-incense"] : ["stove-incense","smoke"]
    for kind in kinds {
        if kind != "smoke" {
            precondition(v.dailyReviewMetrics().contains{($0["kind"] as? String)==kind && ($0["fraction"] as! Double)>0.99},
                         "Pixel review requires the fully visible middle pose")
        }
        let raw=bitmap(Int(ceil(v.bounds.width)),Int(ceil(v.bounds.height))){v.drawDailyReviewLayer(kind)}
        let data=raw.bitmapData!,edges=alphaEdges(raw)
        var maximum=0,nonzero=0,core=0,strong=0,rowsWithStrong=0
        for y in 0..<raw.pixelsHigh {
            var rowStrong=false
            for x in 0..<raw.pixelsWide {
                let a=Int(data[y*raw.bytesPerRow+x*4+3]);maximum=max(maximum,a)
                if a>0 {nonzero+=1};if a>16 {core+=1};if a>128 {strong+=1;rowStrong=true}
            }
            if rowStrong {rowsWithStrong+=1}
        }
        incensePixelChecks.append(["action":action,"kind":kind,"direction":direction,"product_scale":Double(scale),
            "phase":"fully visible middle at 0.8s","alpha_max":maximum,"alpha_gt0_pixels":nonzero,
            "alpha_gt16_pixels":core,"alpha_gt128_pixels":strong,"rows_with_alpha_gt128":rowsWithStrong,
            "alpha_gt0_bbox":edges.any,"alpha_gt16_bbox":edges.visible])
        if kind=="smoke" {precondition(core>0,"Smoke has no visible pixels at product scale")}
        else {precondition(strong>0,"Incense geometry exists but actual rendered core is missing at product scale")}
        png(raw,"layer-\(Int(scale*100))pct-\(action)-\(kind)-\(direction).png")
    }
}
func productScaleContact(_ direction: String) {
    let scales: [CGFloat]=[0.2,0.75,1.5],names=["read","sweep","incense","paper","smoke"]
    var pictures=[[NSBitmapImageRep]]()
    for name in names {
        var row=[NSBitmapImageRep]()
        for scale in scales {
            let(v,start,serial)=preparedIdle(128,direction)
            v.setFrameSize(NSSize(width:TianmuView.sceneCanvas.width*scale,height:TianmuView.sceneCanvas.height*scale))
            let stand=rawRender(v)
            if name=="smoke" {v.ritualStage="炉烟升起";v.updateAnimation(elapsed:start+0.8)}
            else {
                let action=actions.first{$0.name==name}!
                begin(action,v,serial,start,action.service ? 1 : 0)
                v.updateAnimation(elapsed:start+0.8)
            }
            let raw=rawRender(v),displayHeight=Double(shrine.attendantHeight*scale)
            audit(raw,stand,v,"product-scale-\(name)",direction,displayHeight,0.8)
            if ["incense","paper","smoke"].contains(name) {auditProductIncensePixels(v,name,direction,scale)}
            productScaleChecks.append(["action":name,"direction":direction,"product_scale":Double(scale),
                "attendant_height_pt":displayHeight,"scene_size":[Double(v.bounds.width),Double(v.bounds.height)]])
            for (theme,bg,_) in backgrounds {png(composite(NSBitmapImageRep(cgImage:raw.cgImage!),bg),"product-\(Int(scale*100))pct-\(name)-\(direction)-\(theme).png")}
            row.append(raw)
        }
        pictures.append(row)
    }
    let widths=scales.map{Int(ceil(TianmuView.sceneCanvas.width*$0))+24},rowHeight=Int(ceil(TianmuView.sceneCanvas.height*scales.last!))+42
    let width=widths.reduce(0,+),height=rowHeight*names.count+32
    for (theme,bg,ink) in backgrounds {
        let b=bitmap(width,height){
            bg.setFill();NSRect(x:0,y:0,width:width,height:height).fill()
            func label(_ text:String,_ x:CGFloat,_ y:CGFloat){(text as NSString).draw(at:NSPoint(x:x,y:y),withAttributes:[.font:NSFont.systemFont(ofSize:11),.foregroundColor:ink])}
            label("真实产品缩放20% / 75% / 150% · 人物23.6 / 88.5 / 177pt · \(direction)",12,CGFloat(height-22))
            for(row,name)in names.enumerated(){var x=12
                for(column,raw)in pictures[row].enumerated(){let y=12+(names.count-1-row)*rowHeight
                    NSImage(cgImage:raw.cgImage!,size:NSSize(width:raw.pixelsWide,height:raw.pixelsHigh)).draw(in:NSRect(x:x,y:y+22,width:raw.pixelsWide,height:raw.pixelsHigh))
                    label("\(name) \(Int(scales[column]*100))%",CGFloat(x),CGFloat(y));x += widths[column]
                }
            }
        };png(b,"contact-product-scales-\(direction)-\(theme).png")
    }
}
for size in [64,128] {
    for group in 0..<3 {
        var rows=[ContactRow]()
        for action in actions[(group*3)..<(group*3+3)] {for direction in ["left","right"] {rows.append(normal(action,size,direction))}}
        contact(rows,size,"daily-\(group+1)")
    }
    for name in ["ritual","press-ritual","press-response","press-expiry","press-switch"] {
        let rows=["left","right"].map{scenario(name,size,$0)}
        contact(rows,size,name)
    }
}
for direction in ["left","right"] {productScaleContact(direction)}
saveJSON(checks,"checks.json");saveJSON(boundaries,"frame-bounds.json");saveJSON(productScaleChecks,"product-scales.json");saveJSON(incenseMetrics,"incense-metrics.json");saveJSON(incensePixelChecks,"incense-pixel-checks.json")
let touching=boundaries.filter { ($0["new_edge_core_pixels"] as! [Int]).contains(where:{$0>0}) }
saveJSON(touching,"boundary-violations.json")
precondition(touching.isEmpty,"New visible action pixels touch a scene edge; inspect boundary-violations.json")
print("NATIVE_DAILY_PASS: \(checks.count) behavioral sequences / \(boundaries.count) raw-alpha frames / \(incensePixelChecks.count) actual incense and smoke layer checks; 9 gestures, 3-stage ritual, press/expiry/prop switch; both facings, 64/128pt light/dark; product 20/75/150 percent stills; no window, worker or save")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-art', action='store_true', help='Use the already enabled production daily manifest directly.')
    args = parser.parse_args()
    out = ROOT / 'evidence/1.0' / ('159-native-daily-production' if args.production_art else '159-native-daily')
    out.mkdir(parents=True, exist_ok=True)
    source, scene = ROOT / 'assets/production/A01', ROOT / 'assets/production/scene'
    manifest_path, scene_manifest_path = source / 'manifest.json', scene / 'manifest.json'
    manifest, scene_manifest = json.loads(manifest_path.read_text()), json.loads(scene_manifest_path.read_text())
    assert 'walk' not in manifest and manifest['fixedActions']['catch']['net']['height'] == 400
    catch = manifest['fixedActions']['catch']
    originals = [source / manifest['stand']['file'], source / catch['net']['file'], source / catch['torsoUnderlay']['file']]
    if args.production_art:
        daily = manifest['fixedActions']['daily']
        originals.extend(source / prop['file'] for prop in daily['props'].values())
    else:
        daily = DAILY
        manifest['fixedActions']['daily'] = daily
        originals.extend((scene if name == 'fruit' else INCOMING) / prop['file'] for name, prop in daily['props'].items())
    scene_images = {scene / item['file'] for item in scene_manifest['layers']}
    scene_images.update(scene / item['file'] for item in scene_manifest.get('fruitVariants', {}).values())
    watched = sorted({*originals, manifest_path, scene_manifest_path, *scene_images})
    digests = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
    native = (ROOT / 'native/OverlayHost.swift').read_text().split('final class Host:')[0]
    with tempfile.TemporaryDirectory(prefix='tianmu-native-daily-') as folder:
        work = Path(folder)
        if args.production_art:
            assets = source
        else:
            assets = work / 'A01'; assets.mkdir()
            for original in originals: shutil.copy2(original, assets / original.name)
            (assets / 'manifest.json').write_text(json.dumps(manifest))
        (work / 'Scene.swift').write_text(native+READ_ONLY_REVIEW)
        (work / 'main.swift').write_text(SWIFT)
        subprocess.run(['swiftc', '-framework', 'AppKit', '-framework', 'ImageIO', str(work / 'Scene.swift'),
                        str(work / 'main.swift'), '-o', str(work / 'render')], check=True)
        subprocess.run([str(work / 'render'), str(assets), str(scene), str(out)], check=True)
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in digests.items())
    (out / 'fixture.json').write_text(json.dumps({
        'art_mode': 'production' if args.production_art else 'original byte copies and temporary daily manifest',
        'source_manifest': str(manifest_path), 'source_sha256': digests,
        'native_prefix_sha256': hashlib.sha256(native.encode()).hexdigest(),
        'review_extension': 'Temporary same-file read-only access to mapped incense transforms; no production API edits',
        'incense_pixel_validation': 'Actual isolated layers in fully visible product middle poses: held/stove incense must have alpha > 128, smoke > 16; entry/exit fades excluded',
        'shared_helper_sha256': hashlib.sha256(SHARED_PATH.read_bytes()).hexdigest(), 'daily': daily,
        'renderer': 'actual TianmuView and production G0; normal alpha AppKit rendering',
        'time': 'synthetic monotonic clock and 1Hz service receipts; GIF delays retain source duration with sparse middle samples',
        'semantics': {'rest': 'standing relaxation', 'offer': 'present fruit feedback, not physically moving items to the altar',
                      'paper': 'blank prop; real fortune remains in existing UI'},
        'production_manifest_changed': False, 'no_window': True, 'no_worker': True, 'no_save_access': True,
    }, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
