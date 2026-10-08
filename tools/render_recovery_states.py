"""Render production recovery PanelView with explicit samples and hidden windows."""
import argparse,hashlib,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
let app=NSApplication.shared;app.setActivationPolicy(.prohibited)
let output=URL(fileURLWithPath:CommandLine.arguments[1])
func cards(_ view:NSView)->[RecoveryControlView] {
    (view as? RecoveryControlView).map { [$0] } ?? view.subviews.flatMap { cards($0) }
}
func invalidate(_ view:NSView) { view.needsDisplay=true;view.subviews.forEach { invalidate($0) } }
for scenario in ["inspect","confirm","missing-backup","in-use"] {
    let store=Store();store.requestSink={_ in fatalError("Rendering must not submit")}
    var reply:[String:Any] = ["ok":false,"phase":"recovery","issue":["code":"save_corrupt","message":"存档内容损坏，原文件已保留。"],
        "recovery":["backup_available":true,"token":"sample-only","backup_summary":["coins":9,"desktop_count":6,"bottle_count":3,"modified_at":1700000000]]]
    if scenario=="missing-backup" { reply["recovery"]=["backup_available":false] }
    if scenario=="in-use" {
        reply=["ok":false,"phase":"failed","issue":["code":"save_in_use","message":"这个存档正在使用，请先返回已打开的天姥。"]]
    }
    store.receive(try! JSONSerialization.data(withJSONObject:reply)+Data([10]))
    store.message="隔离错误样例 · 数量与日期非实况"
    if scenario=="confirm" { store.recoveryControls.beginRestore() }
    let presentation=PresentationState();presentation.open("设置")
    let view=NSHostingView(rootView:PanelView(store:store,presentation:presentation,adjust:{_ in},hide:{},dismiss:{}))
    let frame=NSRect(x:0,y:0,width:460,height:520)
    let window=NSWindow(contentRect:frame,styleMask:[.borderless],backing:.buffered,defer:false)
    window.isReleasedWhenClosed=false;window.contentView=view;view.frame=frame
    for _ in 0..<3 {
        view.layoutSubtreeIfNeeded()
        let warmup=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
        view.cacheDisplay(in:view.bounds,to:warmup)
        RunLoop.current.run(until:Date().addingTimeInterval(0.08))
    }
    let actual=cards(view);assert(actual.count==1)
    let card=actual[0]
    for button in [card.restoreButton,card.inspectButton,card.retryButton,card.confirmButton,card.cancelButton] where !button.isHidden {
        assert(card.visibleRect.contains(button.frame),"Actual recovery button must be fully visible")
    }
    assert(!window.isVisible && store.process==nil)
    invalidate(view)
    let bitmap=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
    view.cacheDisplay(in:view.bounds,to:bitmap)
    try! bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("recovery-\(scenario).png"))
    print("PASS \(scenario): actual PanelView 460x520; sample only; no click, worker, save or visible window")
    window.close()
}
'''
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
 output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
 main_source=ROOT/'native/v1/main.swift'
 print('main.swift SHA256',hashlib.sha256(main_source.read_bytes()).hexdigest(),flush=True)
 with tempfile.TemporaryDirectory(prefix='tianmu-recovery-render-') as folder:
  folder=Path(folder)
  (folder/'main.swift').write_text(main_source.read_text().split('let application = NSApplication.shared')[0]+HARNESS)
  (folder/'Scene.swift').write_text((ROOT/'native/OverlayHost.swift').read_text().split('final class Host:')[0])
  subprocess.run(['swiftc','-framework','AppKit','-framework','SwiftUI',str(folder/'Scene.swift'),*(str(ROOT/'native/v1'/name) for name in ['Presentation.swift','WindowPlacement.swift','DesktopInsects.swift', 'InsectArtwork.swift','TimerControls.swift']),str(folder/'main.swift'),'-o',str(folder/'render')],check=True,timeout=90)
  subprocess.run([str(folder/'render'),str(output)],check=True,timeout=30)
if __name__=='__main__':main()
