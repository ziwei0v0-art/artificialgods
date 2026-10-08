"""Compare only the pinned upstream draw closure with its native mechanical port.

No game process, app bundle, worker, save, network request or on-screen window.
WebKit executes extracted drawing functions plus deterministic fixtures, never overlay.js.
"""
from pathlib import Path
import base64
import hashlib
import json
import math
import subprocess
import tempfile
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/1.0/164-fly-paradise-comparison'
EXPECTED = 'dcfe5153feff4b5bfd47ad5fdde63cf5da337cbf286bb41ba0cb0562c7f2ac95'
WEBKIT = r'''
import AppKit
import WebKit
final class Result: NSObject, WKScriptMessageHandler {
 var finished = false
 var result: Any?
 func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
  result = message.body; finished = true
 }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let receiver = Result()
let configuration = WKWebViewConfiguration()
configuration.websiteDataStore = .nonPersistent()
configuration.userContentController.add(receiver, name: "result")
let view = WKWebView(frame: NSRect(x:0,y:0,width:24,height:24), configuration:configuration)
let html = try String(contentsOfFile:CommandLine.arguments[1],encoding:.utf8)
view.loadHTMLString(html,baseURL:nil)
let deadline = Date().addingTimeInterval(30)
while !receiver.finished && Date() < deadline { RunLoop.current.run(until:Date().addingTimeInterval(0.02)) }
guard let result = receiver.result else { print("FAIL: WebKit drawing timeout"); exit(1) }
let bytes = try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys])
try bytes.write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
guard app.windows.allSatisfy({!$0.isVisible}) else { print("FAIL: Unexpected visible application window"); exit(1) }
print("PASS: pinned original JavaScript closure rendered off screen; zero visible windows")
'''
NATIVE = r'''
import AppKit
import ImageIO
let cases = try JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [[String:Any]]
for item in cases {
 let motion:FlyParadiseArtwork.Motion
 switch item["motion"] as! String { case "flying": motion = .flying; case "resting": motion = .resting; default: motion = .crawling }
 let image = FlyParadiseArtwork.shared.sample(color:item["color"] as! String, sex:item["sex"] as! String,
  heading:item["heading"] as! Double, motion:motion, now:item["now"] as! Double,
  seed:item["seed"] as! Double, scale:item["scale"] as! Double)!
 let target = URL(fileURLWithPath:CommandLine.arguments[2]).appendingPathComponent((item["name"] as! String)+".png")
 let destination = CGImageDestinationCreateWithURL(target as CFURL,"public.png" as CFString,1,nil)!
 CGImageDestinationAddImage(destination,image,nil)
 guard CGImageDestinationFinalize(destination) else { print("FAIL: PNG output"); exit(1) }
}
guard NSApp == nil else { print("FAIL: Unexpected NSApplication"); exit(1) }
print("PASS: native renderer samples without NSApplication")
'''


def run(command):
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    if result.stdout.strip():
        print(result.stdout.strip())


def main():
    upstream = ROOT / 'third_party/fly-paradise/upstream/renderer/overlay.js'
    data = upstream.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED, 'Pinned source hash mismatch'
    source = data.decode()
    closure = source[source.index('const COL = {'):source.index('function drawSide(')]
    closure += source[source.index('function drawFly('):source.index('function drawDeadEgg(')]
    # Nothing outside these pure drawing functions is evaluated.
    assert all(text not in closure for text in ['require(', 'requestAnimationFrame(', 'addEventListener(', 'ipcRenderer'])
    colors = ['普通褐色','中褐色','深褐色','白色']
    cases = []
    for c, color in enumerate(colors):
        for sex in ['F','M']:
            for motion in ['flying','resting','crawling']:
                for direction, heading in enumerate([0,math.pi/2,math.pi,-math.pi/2]):
                    for ti, now in enumerate([0,0.013,0.123]):
                        cases.append(dict(name=f'c{c}-{sex}-{motion}-d{direction}-t{ti}',color=color,sex=sex,
                                          motion=motion,heading=heading,now=now,seed=7,scale=1))
    for scale in [.95,1.2]:
        for motion in ['flying','resting','crawling']:
            for direction,heading in enumerate([0,math.pi/2,math.pi,-math.pi/2]):
                cases.append(dict(name=f'bounds-{scale}-{motion}-d{direction}',color=colors[0],sex='F',
                                  motion=motion,heading=heading,now=.013,seed=7,scale=scale))
    for directory in [OUT/'original',OUT/'native']:
        directory.mkdir(parents=True,exist_ok=True)
    (OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2))
    fixture = '''
const cases = CASES;
const paletteGenes = {'普通褐色':[0,0],'中褐色':[0,2],'深褐色':[2,0],'白色':[2,2]};
const canvas=document.createElement('canvas'); canvas.width=48; canvas.height=48;
const ctx=canvas.getContext('2d',{colorSpace:'srgb'});
CLOSURE
try {
 const results=[];
 for(const item of cases) {
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,48,48);ctx.scale(2,2);
  const genes=paletteGenes[item.color];
  drawFly({x:12,y:12,geneD:genes[0],geneP:genes[1],geneG:0,geneX:0,geneY:0,
   sex:item.sex.toLowerCase(),state:item.motion==='flying'?'fly':'perch',
   crawling:item.motion==='crawling',glow:false,scale:item.scale,visHead:-item.heading,seed:item.seed},item.now*1000);
  results.push({name:item.name,png:canvas.toDataURL('image/png')});
 }
 window.webkit.messageHandlers.result.postMessage({results});
} catch(error) {window.webkit.messageHandlers.result.postMessage({error:String(error)});}
'''.replace('CASES',json.dumps(cases,ensure_ascii=False)).replace('CLOSURE',closure)
    html = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'"><script>'+fixture+'</script>'
    (OUT/'isolated-original-render.html').write_text(html)
    with tempfile.TemporaryDirectory(prefix='tianmu-original-fly-') as temp:
        folder=Path(temp)
        for name, code, frameworks in [('webkit',WEBKIT,['AppKit','WebKit']),('native',NATIVE,['AppKit','ImageIO'])]:
            swift=folder/'main.swift'; swift.write_text(code)
            command=['swiftc']
            for framework in frameworks: command += ['-framework',framework]
            if name=='native': command += [str(ROOT/'native/v1/WindowPlacement.swift'),str(ROOT/'native/v1/InsectArtwork.swift')]
            command += [str(swift),'-o',str(folder/name)]
            run(command)
        run([str(folder/'webkit'),str(OUT/'isolated-original-render.html'),str(OUT/'original-results.json')])
        payload=json.loads((OUT/'original-results.json').read_text())
        assert 'error' not in payload,payload
        assert len(payload['results'])==len(cases)
        for result in payload['results']:
            assert result['name'] in {case['name'] for case in cases}
            (OUT/'original'/(result['name']+'.png')).write_bytes(base64.b64decode(result['png'].split(',',1)[1]))
        run([str(folder/'native'),str(OUT/'cases.json'),str(OUT/'native')])
    metrics=[]
    for case in cases:
        original=Image.open(OUT/'original'/(case['name']+'.png')).convert('RGBA')
        native=Image.open(OUT/'native'/(case['name']+'.png')).convert('RGBA')
        a=list(original.getdata());b=list(native.getdata())
        nonempty=sum(p[3]>8 or q[3]>8 for p,q in zip(a,b))
        intersection=sum(p[3]>32 and q[3]>32 for p,q in zip(a,b))
        union=sum(p[3]>32 or q[3]>32 for p,q in zip(a,b))
        # Compare source-over black/white composites, avoiding irrelevant transparent RGB.
        error=sum(abs(p[k]*p[3]/255-q[k]*q[3]/255) for p,q in zip(a,b) for k in range(3))
        alpha=sum(abs(p[3]-q[3]) for p,q in zip(a,b))
        metrics.append(dict(name=case['name'],alpha_iou=intersection/max(1,union),
                            active_premultiplied_rgb_mae=error/max(1,nonempty)/3,
                            active_alpha_mae=alpha/max(1,nonempty),
                            original_bbox=original.getbbox(),native_bbox=native.getbbox()))
    report=dict(source_sha256=EXPECTED,cases=len(cases),worst_alpha_iou=min(m['alpha_iou'] for m in metrics),
                max_active_rgb_mae=max(m['active_premultiplied_rgb_mae'] for m in metrics),
                mean_active_rgb_mae=sum(m['active_premultiplied_rgb_mae'] for m in metrics)/len(metrics),
                metrics=metrics)
    (OUT/'metrics.json').write_text(json.dumps(report,indent=2))
    # The contact sheet keeps actual 24-point views alongside a nearest-neighbour 2x enlargement.
    for background in ['light','dark']:
        sheet=Image.new('RGB',(1120,1120),'#f2f2f2' if background=='light' else '#20232a')
        draw=ImageDraw.Draw(sheet); ink='#171717' if background=='light' else '#eeeeee'
        draw.text((14,10),'Original JavaScript (left) | Native port (right). Each pair: normal 24 pt + 2x detail.',fill=ink)
        for direction,heading in enumerate(['EAST','NORTH','WEST','SOUTH']):
            ox=(direction%2)*560; oy=(direction//2)*540+30
            draw.text((ox+12,oy),heading+'   WILD / MID / DEEP / WHITE',fill=ink)
            for row,(sex,motion) in enumerate((sex,motion) for sex in ['F','M'] for motion in ['flying','resting','crawling']):
                draw.text((ox+8,oy+28+row*78),sex+' '+motion,fill=ink)
                for c in range(4):
                    name=f'c{c}-{sex}-{motion}-d{direction}-t1'
                    x=ox+108+c*108;y=oy+22+row*78
                    for n,version in enumerate(['original','native']):
                        image=Image.open(OUT/version/(name+'.png')).convert('RGBA')
                        # Source 48 pixel samples represent 24 pt at 2x. Both remain unaltered in the paired PNG files.
                        normal=image.resize((24,24),Image.Resampling.LANCZOS)
                        detail=image.resize((48,48),Image.Resampling.NEAREST)
                        sheet.paste(normal,(x+n*50,y),normal);sheet.paste(detail,(x+n*50,y+24),detail)
        sheet.save(OUT/('comparison-'+background+'.png'))
    print(json.dumps({k:v for k,v in report.items() if k!='metrics'},indent=2))

if __name__=='__main__':main()
