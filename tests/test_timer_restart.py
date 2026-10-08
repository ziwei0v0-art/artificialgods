"""Sequential real worker restarts; temporary saves only, no desktop UI."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest


class TimerRestartTests(unittest.TestCase):
    def run_until_ticks(self, args, ticks):
        worker = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        replies, buffer = [], b''
        try:
            worker.stdin.write(b'{"id":1,"action":"snapshot"}\n')
            worker.stdin.flush()
            limit = time.monotonic() + 12
            while sum(r.get('id') is None for r in replies) < ticks:
                self.assertLess(time.monotonic(), limit, 'Worker heartbeats timed out')
                if not select.select([worker.stdout], [], [], 0.25)[0]:
                    continue
                chunk = os.read(worker.stdout.fileno(), 65536)
                self.assertTrue(chunk, 'Worker exited before expected heartbeats')
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    replies.append(json.loads(line))
            stdout, stderr = worker.communicate(b'{"id":99,"action":"quit"}\n', timeout=5)
            replies.extend(json.loads(line) for line in (buffer + stdout).splitlines())
            self.assertEqual(worker.returncode, 0, stderr.decode())
            self.assertTrue(all(r['ok'] for r in replies), replies)
            self.assertEqual(replies[-1]['id'], 99)
            return replies
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.communicate()

    def test_running_timer_restarts_and_persists_single_expiry(self):
        for mode in ('countdown', 'pomodoro'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='tianmu-timer-restart-') as directory:
                path = Path(directory) / 'state.json'
                args = [sys.executable, '-m', 'tianmu_mvp.worker', '--save-file', str(path)]
                requests = [{'id':1, 'action':'timer_start', 'mode':mode,
                             'duration':'4s', 'work':'4s', 'rest':'3s'},
                            {'id':2, 'action':'quit'}]
                first = subprocess.run(args, input=''.join(json.dumps(r)+'\n' for r in requests),
                                       capture_output=True, text=True, timeout=10)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertTrue(all(json.loads(line)['ok'] for line in first.stdout.splitlines()))
                saved = json.loads(path.read_text())['timer_session']
                self.assertEqual(saved['status'], 'running')
                self.assertEqual(saved['mode'], mode)
                deadline = saved['deadline']
                second = self.run_until_ticks(args, 6)
                restored = second[0]['state']['timer']
                self.assertEqual(restored['status'], 'running')
                self.assertEqual(restored['deadline'], deadline)
                self.assertEqual(restored['mode'], mode)
                events = [event for reply in second for event in reply.get('events', [])]
                self.assertEqual(events, ['timer_expired'])
                self.assertEqual(json.loads(path.read_text())['timer_session']['status'], 'finished')
                third = self.run_until_ticks(args, 2)
                self.assertEqual(third[0]['state']['timer']['status'], 'finished')
                self.assertEqual([event for r in third for event in r.get('events', [])], [])
                if mode == 'pomodoro':
                    self.assertEqual(third[-1]['state']['timer']['phase'], 'work')
                print(mode + ': quit running -> restore same deadline -> one expiry -> quit/reopen -> no duplicate')

    def test_expiry_while_closed_is_delivered_once_after_reopen(self):
        for mode in ('countdown', 'pomodoro'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='tianmu-closed-expiry-') as directory:
                path = Path(directory) / 'state.json'
                args = [sys.executable, '-m', 'tianmu_mvp.worker', '--save-file', str(path)]
                requests = [{'id':1, 'action':'timer_start', 'mode':mode,
                             'duration':'2s', 'work':'2s', 'rest':'3s'},
                            {'id':2, 'action':'quit'}]
                first = subprocess.run(args, input=''.join(json.dumps(r)+'\n' for r in requests),
                                       capture_output=True, text=True, timeout=10)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertTrue(all(json.loads(line)['ok'] for line in first.stdout.splitlines()))
                before_bytes = path.read_bytes()
                saved = json.loads(before_bytes)
                timer = saved['timer_session']
                self.assertEqual(timer['status'], 'running')
                # The worker has exited. Let the actual wall-clock deadline pass,
                # without advancing the game, altering a save, or changing system time.
                time.sleep(max(0, timer['deadline'] - time.time()) + 0.15)
                self.assertGreater(time.time(), timer['deadline'])
                self.assertEqual(path.read_bytes(), before_bytes)
                replies = self.run_until_ticks(args, 3)
                initial = replies[0]['state']
                self.assertEqual(initial['timer']['deadline'], timer['deadline'])
                self.assertEqual(initial['timer']['mode'], mode)
                self.assertEqual(initial['capture_seconds'], saved['active_capture_seconds'])
                events = [e for r in replies for e in r.get('events', [])]
                self.assertEqual(events, ['timer_expired'])
                self.assertEqual(replies[-1]['state']['timer']['status'], 'finished')
                if mode == 'pomodoro':
                    self.assertEqual(replies[-1]['state']['timer']['phase'], 'work')
                reopened = self.run_until_ticks(args, 2)
                self.assertEqual(reopened[0]['state']['timer']['status'], 'finished')
                self.assertEqual([e for r in reopened for e in r.get('events', [])], [])
                if mode == 'pomodoro':
                    self.assertEqual(reopened[-1]['state']['timer']['phase'], 'work')
                print(mode + ': deadline passed with worker closed -> one deferred expiry -> reopen again -> no duplicate; no offline capture time')
