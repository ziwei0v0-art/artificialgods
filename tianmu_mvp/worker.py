"""JSON-lines I/O for one locked backend session; never launches a window."""

import argparse
import importlib
import json
import os
from pathlib import Path
import select
import sys
import time


def emit(result):
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')), flush=True)


def failed(code, message):
    return {'id': None, 'ok': False, 'phase': 'failed', 'error': message,
            'issue': {'code': code, 'message': message}}


class WorkerDriver:
    """The production dispatcher, also usable without spawning a process."""

    def __init__(self, session, monotonic_now):
        self.consume_active_delta = importlib.import_module('.clock', __package__).consume_active_delta
        self.session = session
        self.last, self.fraction = monotonic_now, 0.0
        self.sleeping = False
        self.should_exit = False
        self._skip_tick = False

    def handle(self, request, now, monotonic_now):
        if not isinstance(request, dict):
            return {'id': None, 'ok': False, 'error': '操作必须是对象', 'phase': self.session.phase}
        action = request.get('action')
        try:
            if action in ('sleep', 'wake') and self.session.phase == 'ready':
                self.sleeping = action == 'sleep'
                self.last, self.fraction = monotonic_now, 0.0
                self._skip_tick = True
                result = {'ok': True, 'phase': 'ready'}
            else:
                result = self.session.handle(request, now)
            if result.pop('reset_active_clock', False):
                self.last, self.fraction = monotonic_now, 0.0
                self._skip_tick = True
            self.should_exit = bool(result.pop('should_exit', False))
            return {**result, 'id': request.get('id')}
        except (ValueError, TypeError) as error:
            return {'id': request.get('id'), 'ok': False, 'phase': self.session.phase,
                    'error': str(error)}

    def tick(self, now, monotonic_now):
        if self._skip_tick:
            self.last, self.fraction = monotonic_now, 0.0
            self._skip_tick = False
            return None
        active = self.session.phase == 'ready' and not self.sleeping
        delta, self.fraction = self.consume_active_delta(monotonic_now - self.last,
                                                       active, self.fraction)
        self.last = monotonic_now
        if not delta:
            return None
        result = self.session.tick(now, delta)
        return None if result is None else {**result, 'id': None}


def bootstrap(path, now, monotonic_now):
    """Produce the same startup handshake used by the native host and tests."""
    session = None
    try:
        recovery = importlib.import_module('.recovery', __package__)
        session = recovery.WorkerSession(path)
        driver = WorkerDriver(session, monotonic_now)
        return driver, {**session.startup(now), 'id': None}
    except (ImportError, ModuleNotFoundError) as error:
        result = failed('runtime_unavailable', '运行依赖不完整，无法启动数据服务：' + str(error))
    except Exception as error:
        code = getattr(error, 'code', 'startup_failed')
        message = getattr(error, 'message', '无法启动数据服务：' + str(error))
        result = failed(code, message)
    if session is not None:
        session.close()
    return None, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save-file', required=True, type=Path)
    args = parser.parse_args()
    driver, handshake = bootstrap(args.save_file, time.time(), time.monotonic())
    emit(handshake)
    if driver is None:
        return 2
    buffer = b''
    try:
        while True:
            ready, _, _ = select.select([sys.stdin.fileno()], [], [], 0.25)
            if ready:
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    return 0
                buffer += chunk
                if len(buffer) > 1048576:
                    emit(failed('protocol_error', '控制消息过长，数据服务已停止。'))
                    return 2
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        request = json.loads(line)
                    except (ValueError, UnicodeDecodeError) as error:
                        emit({'id': None, 'ok': False, 'phase': driver.session.phase,
                              'error': '无法读取操作：' + str(error)})
                        continue
                    emit(driver.handle(request, time.time(), time.monotonic()))
                    if driver.should_exit:
                        return 0
            result = driver.tick(time.time(), time.monotonic())
            if result is not None:
                emit(result)
    except Exception as error:
        emit(failed('runtime_error', '数据服务已停止：' + str(error)))
        return 2
    finally:
        driver.session.close()


if __name__ == '__main__':
    raise SystemExit(main())
