"""Inventory/status presentation from isolated snapshots, no worker or save."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BottleStatusTests(unittest.TestCase):
    def test_inventory_and_capture_status_follow_snapshot(self):
        harness = r'''
import Foundation
let rows: [[String:Any]] = [
 ["color":"普通褐色","female":2,"male":3],
 ["color":"中褐色","female":4,"male":0],
 ["color":"深褐色","female":0,"male":1],
 ["color":"白色","female":6,"male":7]]
func check(_ rows:[[String:Any]], _ seconds:Int, _ paused:Bool,
           _ total:String, _ time:String, _ status:String) {
 let state:[String:Any] = ["bottle":rows,"capture_seconds":seconds,"auto_paused":paused]
 let before = NSDictionary(dictionary:state)
 let summary = BottleStatus(state:state)
 assert(summary.inventoryText == total, summary.inventoryText)
 assert(summary.captureText.contains(time), summary.captureText)
 assert(summary.captureText.contains(status), summary.captureText)
 assert(before.isEqual(to:state), "Presentation mutated snapshot")
 print("PASS \(total) · \(summary.captureText)")
}
check([],0,false,"总库存 0 只","00:00:00 / 24:00:00","自动捕捉中")
check(rows,3661,false,"总库存 23 只","01:01:01 / 24:00:00","自动捕捉中")
check(rows,86399,false,"总库存 23 只","23:59:59 / 24:00:00","自动捕捉中")
check(rows,86400,true,"总库存 23 只","24:00:00 / 24:00:00","已达上限 · 自动捕捉暂停")
// Successful release/sale leaves inventory and restarts this round.
check([["female":6,"male":7]],0,false,"总库存 13 只","00:00:00 / 24:00:00","自动捕捉中")
// Respect the supplied paused flag; do not invent a timer rule in the UI.
check(rows,3600,true,"总库存 23 只","01:00:00 / 24:00:00","自动捕捉暂停")
'''
        with tempfile.TemporaryDirectory(prefix='tianmu-bottle-status-') as folder:
            folder=Path(folder)
            (folder/'main.swift').write_text(harness)
            build=subprocess.run(['swiftc',str(ROOT/'native/v1/Presentation.swift'),str(folder/'main.swift'),'-o',str(folder/'check')],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(folder/'check')],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertEqual(run.stdout.count('PASS '),6,run.stdout)
            print(run.stdout.strip())
