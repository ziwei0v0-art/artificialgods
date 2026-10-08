"""One locked save session, including an explicit, non-ticking recovery state."""

from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time

from .model import GameState
from .service import ApplicationService
from .storage import SaveLoadError, decode_state_bytes


class StartupIssue(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class FileImage:
    data: bytes
    modified_at: float

    @property
    def fingerprint(self):
        return len(self.data), hashlib.sha256(self.data).hexdigest()


def _fingerprint(image):
    # Missing is deliberately distinct from an existing empty file.
    return None if image is None else image.fingerprint


def _read_regular(path):
    """Read only regular files, without following a final symlink or FIFO."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SaveLoadError('save_unreadable', '无法读取存档文件：' + str(error)) from error
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SaveLoadError('save_unreadable', '存档位置不是普通文件，请检查所选位置。')
            return FileImage(stream.read(), info.st_mtime)
    except OSError as error:
        raise SaveLoadError('save_unreadable', '无法读取存档文件：' + str(error)) from error


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class WorkerSession:
    def __init__(self, path):
        selected = Path(path).expanduser().absolute()
        # Resolve the directory but keep the final component for no-follow reads.
        self.path = selected.parent.resolve() / selected.name
        self.backup_path = self.path.with_name(self.path.name + '.bak')
        self.phase = 'recovery'
        self.service = None
        self.issue = None
        self._lock_stream = None
        self._closed = False
        self._token_binding = None
        self._recovery_info = {'save_path': str(self.path), 'backup_available': False}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = str(self.path.resolve()) + '.lock'
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self._lock_stream = os.fdopen(descriptor, 'a+')
            if not stat.S_ISREG(os.fstat(self._lock_stream.fileno()).st_mode):
                raise OSError('存档锁不是普通文件')
            fcntl.flock(self._lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.close()
            raise StartupIssue('save_in_use', '这个存档正在使用，请先返回已打开的灶神。') from error
        except OSError as error:
            self.close()
            raise StartupIssue('save_unreadable', '无法取得存档锁：' + str(error)) from error
        try:
            primary = _read_regular(self.path)
            if primary is None:
                if _read_regular(self.backup_path) is not None:
                    raise SaveLoadError('save_missing', '主存档缺失，已发现备份。请检查备份后确认恢复。')
                self.service = ApplicationService(self.path, initial_state=GameState.new())
            else:
                self.service = self._candidate(primary.data, time.time())
            self.phase = 'ready'
        except SaveLoadError as error:
            self.issue = StartupIssue(error.code, error.message)
        except Exception:
            self.close()
            raise

    def _candidate(self, data, now):
        state = decode_state_bytes(data)
        candidate = ApplicationService(self.path, initial_state=state)
        try:
            candidate.snapshot(now)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
            raise SaveLoadError('save_corrupt', '存档内容无法完整显示：' + str(error)) from error
        return candidate

    def _reply(self, ok, issue=None):
        result = {'ok': ok, 'phase': self.phase}
        issue = issue or self.issue
        if issue is not None:
            result['issue'] = {'code': issue.code, 'message': issue.message}
            if not ok:
                result['error'] = issue.message
        if self.phase == 'recovery':
            result['recovery'] = dict(self._recovery_info)
        return result

    def startup(self, now):
        if self._closed:
            return self._reply(False)
        if self.phase == 'ready':
            return {'ok': True, 'phase': 'ready', 'state': self.service.snapshot(now),
                    'new_discoveries': []}
        result = self._inspect(now)
        result['ok'] = False
        result['error'] = result['issue']['message']
        return result

    def _inspect(self, now):
        self._token_binding = None
        self._recovery_info = {'save_path': str(self.path), 'backup_available': False}
        try:
            primary = _read_regular(self.path)
            backup = _read_regular(self.backup_path)
        except SaveLoadError as error:
            return self._reply(False, error)
        if backup is None:
            return self._reply(True)
        try:
            candidate = self._candidate(backup.data, now)
        except SaveLoadError:
            # Inspection itself succeeded; there simply is no usable backup.
            return self._reply(True)
        token = secrets.token_urlsafe(24)
        self._token_binding = (token, _fingerprint(primary), _fingerprint(backup))
        game = candidate.game
        self._recovery_info.update({
            'backup_available': True,
            'backup_summary': {'coins': game.coins, 'desktop_count': len(game.desktop),
                               'bottle_count': len(game.bottle), 'modified_at': backup.modified_at},
            'token': token,
        })
        return self._reply(True)

    def _check_sources(self, binding):
        primary, backup = _read_regular(self.path), _read_regular(self.backup_path)
        if (_fingerprint(primary), _fingerprint(backup)) != binding[1:]:
            raise StartupIssue('recovery_stale', '存档或备份已发生变化，请重新检查并确认恢复。')
        return primary, backup

    def _archive(self, label, data):
        path = self.path.with_name(self.path.name + '.recovery-' + str(time.time_ns())
                                   + '-' + secrets.token_hex(4) + '.' + label)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        # Once created, even an incomplete archive is kept for diagnosis.
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        image = _read_regular(path)
        if image is None or image.data != data:
            raise OSError('保留副本校验失败')
        return str(path)

    def _restore(self, request, now):
        if request.get('confirmed') is not True:
            return self._reply(False, StartupIssue('recovery_confirmation_required', '请先明确确认恢复备份。'))
        token = request.get('token')
        binding = self._token_binding
        if not isinstance(token, str) or binding is None or not secrets.compare_digest(token, binding[0]):
            return self._reply(False, StartupIssue('recovery_stale', '恢复确认已失效，请重新检查备份。'))
        self._token_binding = None
        self._recovery_info.pop('token', None)
        stage = None
        committed = False
        archives = {}
        try:
            primary, backup = self._check_sources(binding)
            candidate = self._candidate(backup.data, now)
            # Create the exact replacement bytes before touching either source.
            descriptor, name = tempfile.mkstemp(prefix='.' + self.path.name + '.restore-',
                                                 suffix='.tmp', dir=self.path.parent)
            stage = Path(name)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(backup.data)
                stream.flush()
                os.fsync(stream.fileno())
            if primary is not None:
                archives['original'] = self._archive('original', primary.data)
            archives['backup'] = self._archive('backup', backup.data)
            _sync_directory(self.path.parent)
            self._check_sources(binding)
            os.replace(stage, self.path)
            committed, stage = True, None
            _sync_directory(self.path.parent)
        except (OSError, SaveLoadError, StartupIssue) as error:
            if committed:
                issue = StartupIssue('recovery_uncertain',
                                     '主存档已替换，但持久性未确认；原件与备份副本已保留。请重新检查。')
            elif isinstance(error, (SaveLoadError, StartupIssue)):
                issue = error
            else:
                issue = StartupIssue('recovery_failed', '恢复未完成，主存档未替换：' + str(error))
            result = self._reply(False, issue)
            if archives:
                result['restored_archives'] = archives
            return result
        finally:
            if stage is not None:
                try:
                    stage.unlink()
                except OSError:
                    pass
        self.service, self.phase, self.issue = candidate, 'ready', None
        return {'ok': True, 'phase': 'ready', 'state': candidate.snapshot(now),
                'new_discoveries': [], 'reset_active_clock': True,
                'restored_archives': archives, 'message': '备份已恢复，原件与备份副本已保留。'}

    def handle(self, request, now):
        if self._closed:
            return self._reply(False)
        action = request.get('action')
        if self.phase == 'recovery':
            if action == 'quit':
                return {'ok': True, 'phase': 'recovery', 'should_exit': True}
            if action == 'recovery_inspect':
                return self._inspect(now)
            if action == 'recovery_restore':
                return self._restore(request, now)
            return self._reply(False, StartupIssue('recovery_required', '请先检查并恢复存档，当前游戏尚未启动。'))
        if action == 'quit':
            result = self.service.handle({'action': 'checkpoint'}, now)
            return {**result, 'phase': 'ready', 'should_exit': bool(result['ok'])}
        return {**self.service.handle(request, now), 'phase': 'ready'}

    def tick(self, now, active_seconds):
        if self._closed or self.phase != 'ready':
            return None
        return {**self.service.tick(now, active_seconds), 'phase': 'ready'}

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._token_binding = None
        self.service = None
        self.phase = 'failed'
        self.issue = StartupIssue('session_closed', '数据服务已关闭。')
        if self._lock_stream is not None:
            self._lock_stream.close()
            self._lock_stream = None
