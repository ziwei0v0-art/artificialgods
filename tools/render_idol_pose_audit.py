"""Read-only v02 statue checks and actual TianmuView composites using AppKit.

Python only stages source files and invokes Swift. All bitmap decoding, alpha
inspection, drawing, and PNG output are performed by native AppKit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/production/scene"
INCOMING = ROOT / "assets/incoming/pose_20261003"

SWIFT = r'''
import AppKit
let app=NSApplication.shared
app.setActivationPolicy(.prohibited)
let output=URL(fileURLWithPath:CommandLine.arguments[1])
let artURL=URL(fileURLWithPath:CommandLine.arguments[2])
let sceneURL=URL(fileURLWithPath:CommandLine.arguments[3])
let legacyURL=URL(fileURLWithPath:CommandLine.arguments[4])
let art=AttendantArtwork.load(from:artURL)!
let current=ShrineArtwork.load(from:sceneURL)!
let legacy=ShrineArtwork.load(from:legacyURL)!
let manifest=try! JSONSerialization.jsonObject(with:Data(contentsOf:sceneURL.appendingPathComponent("manifest.json"))) as! [String:Any]
let base=(manifest["layers"] as! [[String:Any]]).first{$0["id"] as? String == "idol"}!
let paid=((manifest["appearances"] as! [String:[String:Any]])["shrine_g2"]!["layers"] as! [[String:Any]]).first{$0["id"] as? String == "idol"}!
var audits=[[String:Any]]()
for spec in [base,paid] {
    let filename=spec["file"] as! String,crop=spec["sourceRect"] as! [Int]
    let image=NSBitmapImageRep(data:try! Data(contentsOf:sceneURL.appendingPathComponent(filename)))!
    var minX=image.pixelsWide,minY=image.pixelsHigh,maxX=0,maxY=0,material=0,outside=0,faintOutside=0
    for y in 0..<image.pixelsHigh {for x in 0..<image.pixelsWide {
        let alpha=image.colorAt(x:x,y:y)!.alphaComponent
        let inCrop=x>=crop[0] && x<crop[0]+crop[2] && y>=crop[1] && y<crop[1]+crop[3]
        if alpha>CGFloat(16)/255 {
            material += 1;minX=min(minX,x);minY=min(minY,y);maxX=max(maxX,x);maxY=max(maxY,y)
            if !inCrop {outside += 1}
        } else if alpha>0 && !inCrop {faintOutside += 1}
    }}
    precondition(image.hasAlpha && material>0 && outside==0,"Crop must retain all material pixels, including feet and implements")
    audits.append(["file":filename,"dimensions":[image.pixelsWide,image.pixelsHigh],"has_alpha":image.hasAlpha,
        "material_threshold_alpha_gt":16,"material_bbox":[minX,minY,maxX-minX+1,maxY-minY+1],
        "material_pixels":material,"material_outside_crop":outside,"faint_pixels_outside_crop":faintOutside,
        "source_rect":crop,"bounds":spec["bounds"]!])
}
func bitmap(_ width:Int,_ height:Int,_ draw:()->Void)->NSBitmapImageRep {
    let result=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:width,pixelsHigh:height,bitsPerSample:8,samplesPerPixel:4,
        hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:result)
    NSGraphicsContext.current!.imageInterpolation = .none
    draw();NSGraphicsContext.restoreGraphicsState();return result
}
func save(_ bitmap:NSBitmapImageRep,_ name:String) {
    try! bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name+".png"))
}
let light=NSColor(calibratedWhite:0.94,alpha:1)
let dark=NSColor(calibratedRed:0.12,green:0.15,blue:0.19,alpha:1)
func appearance(_ stage:Int)->SceneAppearance { SceneAppearance(snapshot:["shrine_stage":stage]) }
func render(_ shrine:ShrineArtwork,_ stage:Int,_ scale:Double,_ background:NSColor?)->NSBitmapImageRep {
    let view=TianmuView(frame:NSRect(x:0,y:0,width:370*scale,height:190*scale))
    view.attendantArtwork=art;view.shrineArtwork=shrine;view.sceneAppearance=appearance(stage)
    precondition(view.applyRoutine(["action":"idle","action_serial":1,"action_elapsed":0.0,"action_duration":0.0,
        "progress":0.0,"fruit_stage":"fresh"]))
    return bitmap(Int(ceil(view.bounds.width)),Int(ceil(view.bounds.height))) {
        view.draw(view.bounds)
        if let background {
            NSGraphicsContext.current!.cgContext.setBlendMode(.destinationOver)
            background.setFill();view.bounds.fill()
        }
    }
}
let g0=current.resolve(appearance:appearance(0),fruitStage:"fresh")
let g1=current.resolve(appearance:appearance(1),fruitStage:"fresh")
let g2=current.resolve(appearance:appearance(2),fruitStage:"fresh")
let baseIdol=g0.layers.first{$0.id=="idol"}!
precondition(g1.layers.first{$0.id=="idol"}!.frame.image === baseIdol.frame.image,"G1 must share the corrected static G0 statue")
precondition(g2.layers.first{$0.id=="idol"}!.frame.image !== baseIdol.frame.image,"G2 must select the corrected painted statue")
precondition(g0.unavailableIDs.isEmpty && g1.unavailableIDs.isEmpty && g2.unavailableIDs.isEmpty)
for stage in 0...2 {for(scale,label)in[(0.2,"20"),(0.75,"75"),(1.5,"150")] {
    for(theme,color)in[("light",Optional(light)),("dark",Optional(dark)),("transparent",nil)] {
        save(render(current,stage,scale,color),"g\(stage)-\(label)pct-\(theme)")
    }
}}
for(theme,color)in[("light",light),("dark",dark)] {
    save(render(legacy,0,0.75,color),"legacy-g0-75pct-\(theme)")
    let entries:[(String,ShrineArtwork,Int)]=[("原 G0（盘腿）",legacy,0),("新 G0（垂足）",current,0),("新 G2（垂足彩塑）",current,2)]
    let board=bitmap(960,530) {
        color.setFill();NSRect(x:0,y:0,width:960,height:530).fill()
        let ink=theme=="dark" ? NSColor.white:NSColor.black
        ("实际 TianmuView · 75% 场景 / 150% 独立供像" as NSString).draw(at:NSPoint(x:18,y:497),withAttributes:[.font:NSFont.systemFont(ofSize:17),.foregroundColor:ink])
        for(index,entry)in entries.enumerated() {
            let x=CGFloat(18+index*314)
            (entry.0 as NSString).draw(at:NSPoint(x:x,y:463),withAttributes:[.font:NSFont.systemFont(ofSize:14),.foregroundColor:ink])
            let scene=render(entry.1,entry.2,0.75,color)
            NSImage(cgImage:scene.cgImage!,size:NSSize(width:scene.pixelsWide,height:scene.pixelsHigh)).draw(in:NSRect(x:x,y:302,width:278,height:143))
            let layer=entry.1.resolve(appearance:appearance(entry.2),fruitStage:"fresh").layers.first{$0.id=="idol"}!
            let size=NSSize(width:layer.bounds.width*1.5,height:layer.bounds.height*1.5)
            layer.frame.draw(in:NSRect(x:x+63,y:91,width:size.width,height:size.height),mirrored:false)
            ("完整法器 / 六臂 / 双足与神座" as NSString).draw(at:NSPoint(x:x+21,y:54),withAttributes:[.font:NSFont.systemFont(ofSize:11),.foregroundColor:ink])
        }
    }
    save(board,"contact-\(theme)")
}
let report:[String:Any]=["renderer":"actual TianmuView and ShrineArtwork","assets":audits,
    "stages":[0,1,2],"scales":[0.2,0.75,1.5],"available_appearance_ids":current.availableAppearanceIDs.sorted(),
    "g0_g1_share_idol":true,"g2_has_own_painted_idol":true,"no_window":true,"no_worker":true,"no_save_access":true]
try! JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("audit.json"))
precondition(!app.isActive && app.windows.isEmpty,"Offscreen QA must not show a window")
print("PASS: native v02 alpha + G0/G1/G2 selection + actual scene composites; no window/worker/save")
'''


def _files(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "file" and isinstance(item, str):
                yield item
            else:
                yield from _files(item)
    elif isinstance(value, list):
        for item in value:
            yield from _files(item)


def render(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    watched = [SCENE / "manifest.json", *(SCENE / name for name in _files(json.loads((SCENE / "manifest.json").read_text())))]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
    with tempfile.TemporaryDirectory(prefix="tianmu-idol-pose-") as directory:
        folder = Path(directory)
        old = folder / "old-scene"
        old.mkdir()
        old_manifest = INCOMING / "scene-manifest-before-v02.json"
        shutil.copy2(old_manifest, old / "manifest.json")
        for filename in set(_files(json.loads(old_manifest.read_text()))):
            shutil.copy2(SCENE / filename, old / filename)
        (folder / "Scene.swift").write_text((ROOT / "native/OverlayHost.swift").read_text().split("final class Host:")[0])
        (folder / "main.swift").write_text(SWIFT)
        binary = folder / "render"
        build = subprocess.run(["swiftc", "-framework", "AppKit", str(folder / "Scene.swift"), str(folder / "main.swift"), "-o", str(binary)],
            capture_output=True, text=True, timeout=90)
        if build.returncode:
            raise RuntimeError(build.stdout + build.stderr)
        result = subprocess.run([str(binary), str(output), str(ROOT / "assets/production/A01"), str(SCENE), str(old)],
            capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        print(result.stdout.strip())
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}, "QA changed a production asset"
    report = json.loads((output / "audit.json").read_text())
    report["production_assets_unchanged_by_render"] = True
    report["production_sha256"] = before
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/1.0/164-idol-pose")
    render(parser.parse_args().output)
