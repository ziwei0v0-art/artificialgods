import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WorkerTests(unittest.TestCase):
    def test_same_save_cannot_be_opened_by_two_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            args = [sys.executable, '-m', 'tianmu_mvp.worker', '--save-file', str(path)]
            first = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                first.stdin.write('{"id":1,"action":"snapshot"}\n'); first.stdin.flush()
                self.assertEqual(json.loads(first.stdout.readline())['phase'], 'ready')
                self.assertEqual(json.loads(first.stdout.readline())['id'], 1)
                second = subprocess.run(args, input='{ "id":2, "action":"quit" }\n', text=True, capture_output=True, timeout=10)
                self.assertNotEqual(second.returncode, 0)
                failure = json.loads(second.stdout)
                self.assertEqual(failure['phase'], 'failed')
                self.assertEqual(failure['issue']['code'], 'save_in_use')
            finally:
                first.communicate('{"id":3,"action":"quit"}\n', timeout=10)

    def test_native_interface_protocol_has_no_tk_and_saves_before_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            requests = [
                {'id': 1, 'action': 'snapshot'},
                {'id': 2, 'action': 'timer_start', 'mode': 'countdown', 'duration': '90s'},
                {'id': 3, 'action': 'quit'},
            ]
            run = subprocess.run([sys.executable, '-c', "import runpy,sys; sys.argv=['worker']+sys.argv[1:]; runpy.run_module('tianmu_mvp.worker', run_name='__main__'); assert 'tkinter' not in sys.modules", '--save-file', str(path)],
                input=''.join(json.dumps(item) + '\n' for item in requests),
                text=True, capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            replies = [json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual([item['id'] for item in replies], [None, 1, 2, 3])
            self.assertEqual(replies[0]['phase'], 'ready')
            self.assertTrue(all(item['ok'] for item in replies))
            self.assertEqual(json.loads(path.read_text())['timer_session']['countdown_seconds'], 90)

    def test_quit_commits_new_state_before_acknowledging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            run = subprocess.run([sys.executable, '-m', 'tianmu_mvp.worker', '--save-file', str(path)],
                                 input='{"id":1,"action":"quit"}\n', text=True, capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            replies = [json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual([item['id'] for item in replies], [None, 1])
            self.assertTrue(replies[-1]['ok'])
            self.assertTrue(path.exists(), 'Quit acknowledged without committing the new game')
