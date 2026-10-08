"""Recovery contract checks: temporary files only, no worker subprocess or UI."""

import importlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from tianmu_mvp.model import GameState
from tianmu_mvp.storage import _state_dict, load_state


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        try:
            self.recovery = importlib.import_module('tianmu_mvp.recovery')
        except ImportError as error:
            self.fail('Recovery session is not available: ' + str(error))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'state.json'
        self.backup = self.path.with_name('state.json.bak')
        self.original = b'{broken original\xff'
        game = GameState.new()
        game.coins = 17
        self.good = json.dumps(_state_dict(game), ensure_ascii=False, indent=2).encode('utf-8')

    def session(self):
        session = self.recovery.WorkerSession(self.path)
        self.addCleanup(session.close)
        return session

    def broken_session(self):
        self.path.write_bytes(self.original)
        self.backup.write_bytes(self.good)
        return self.session()

    def restore(self, session, token=None, confirmed=True):
        if token is None:
            token = session.handle({'action': 'recovery_inspect'}, 100)['recovery'].get('token')
        return session.handle({'action': 'recovery_restore', 'token': token,
                               'confirmed': confirmed}, 100)

    def test_pristine_start_and_close_do_not_create_a_save(self):
        session = self.session()
        result = session.startup(100)
        self.assertEqual(result['phase'], 'ready')
        self.assertTrue(result['ok'])
        self.assertEqual(result['state']['coins'], 0)
        session.close()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.backup.exists())
        self.assertTrue(Path(str(self.path.resolve()) + '.lock').exists())

    def test_corrupt_and_incompatible_are_distinct_without_touching_files(self):
        for data, expected in ((self.original, 'save_corrupt'),
                               (b'{"schema_version":999}', 'save_incompatible')):
            with self.subTest(expected=expected):
                self.path.write_bytes(data)
                session = self.session()
                reply = session.startup(100)
                self.assertEqual(reply['phase'], 'recovery')
                self.assertEqual(reply['issue']['code'], expected)
                self.assertNotIn('state', reply)
                self.assertEqual(self.path.read_bytes(), data)
                session.close()

    def test_missing_main_with_backup_never_starts_a_new_game(self):
        self.backup.write_bytes(self.good)
        session = self.session()
        reply = session.startup(100)
        self.assertEqual(reply['phase'], 'recovery')
        self.assertEqual(reply['issue']['code'], 'save_missing')
        self.assertEqual(reply['recovery']['backup_summary']['coins'], 17)
        restored = self.restore(session)
        self.assertTrue(restored['ok'])
        self.assertEqual(self.path.read_bytes(), self.good)
        self.assertNotIn('original', restored['restored_archives'])
        self.assertEqual(Path(restored['restored_archives']['backup']).read_bytes(), self.good)

    def test_recovery_inspection_is_successful_and_has_numeric_summary(self):
        session = self.broken_session()
        result = session.handle({'action': 'recovery_inspect'}, 100)
        self.assertTrue(result['ok'])
        self.assertEqual(result['phase'], 'recovery')
        info = result['recovery']
        self.assertEqual(info['save_path'], str(self.path.resolve()))
        self.assertTrue(info['backup_available'])
        self.assertIsInstance(info['token'], str)
        self.assertEqual(info['backup_summary']['coins'], 17)
        self.assertEqual(info['backup_summary']['desktop_count'], 0)
        self.assertEqual(info['backup_summary']['bottle_count'], 0)
        self.assertIsInstance(info['backup_summary']['modified_at'], (int, float))

    def test_recovery_rejects_gameplay_and_tick_and_quit_never_write(self):
        session = self.broken_session()
        for action in ('snapshot', 'checkpoint', 'offer', 'timer_start', 'sleep', 'wake'):
            result = session.handle({'action': action}, 100)
            self.assertFalse(result['ok'], action)
            self.assertNotIn('state', result)
        self.assertIsNone(session.tick(90000, 2))
        self.assertTrue(session.handle({'action': 'quit'}, 100)['should_exit'])
        session.close()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.good)

    def test_same_path_lock_blocks_before_reading_any_save(self):
        first = self.broken_session()
        with patch.object(self.recovery, '_read_regular', side_effect=AssertionError('read before lock')):
            with self.assertRaises(self.recovery.StartupIssue) as raised:
                self.recovery.WorkerSession(self.path)
        self.assertEqual(raised.exception.code, 'save_in_use')
        first.close()
        second = self.session()
        self.assertEqual(second.startup(100)['phase'], 'recovery')

    def test_missing_invalid_and_future_backup_never_offer_restore(self):
        for backup in (None, b'not json', b'{"schema_version":999}'):
            with self.subTest(backup=backup):
                self.path.write_bytes(self.original)
                if backup is not None:
                    self.backup.write_bytes(backup)
                elif self.backup.exists():
                    self.backup.unlink()
                session = self.session()
                reply = session.handle({'action': 'recovery_inspect'}, 100)
                self.assertTrue(reply['ok'])
                self.assertFalse(reply['recovery']['backup_available'])
                self.assertNotIn('token', reply['recovery'])
                self.assertFalse(self.restore(session, token='made-up')['ok'])
                self.assertEqual(self.path.read_bytes(), self.original)
                session.close()

    def test_explicit_boolean_confirmation_and_valid_token_are_required(self):
        session = self.broken_session()
        token = session.startup(100)['recovery']['token']
        for confirmed in (False, None, 1, 'true'):
            self.assertFalse(self.restore(session, token, confirmed)['ok'])
        self.assertFalse(self.restore(session, 'made-up', True)['ok'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.good)
        self.assertEqual(list(self.path.parent.glob('*.recovery-*')), [])

    def test_changed_or_removed_main_or_backup_invalidates_old_confirmation(self):
        for target in ('main', 'backup', 'removed_main', 'removed_backup'):
            with self.subTest(target=target):
                session = self.broken_session()
                token = session.startup(100)['recovery']['token']
                if target == 'main':
                    self.path.write_bytes(b'changed main')
                elif target == 'backup':
                    self.backup.write_bytes(self.good + b'\n')
                elif target == 'removed_main':
                    self.path.unlink()
                else:
                    self.backup.unlink()
                before_main = self.path.read_bytes() if self.path.exists() else None
                before_backup = self.backup.read_bytes() if self.backup.exists() else None
                result = self.restore(session, token)
                self.assertFalse(result['ok'])
                self.assertEqual(result['issue']['code'], 'recovery_stale')
                self.assertEqual(self.path.read_bytes() if self.path.exists() else None, before_main)
                self.assertEqual(self.backup.read_bytes() if self.backup.exists() else None, before_backup)
                self.assertEqual(list(self.path.parent.glob('*.recovery-*')), [])
                session.close()

    def test_success_preserves_exact_original_and_backup_and_reopens(self):
        session = self.broken_session()
        result = self.restore(session)
        self.assertTrue(result['ok'])
        self.assertEqual(result['phase'], 'ready')
        self.assertTrue(result['reset_active_clock'])
        self.assertEqual(result['state']['coins'], 17)
        self.assertEqual(session.service.game.elapsed_seconds, 0)
        self.assertEqual(self.path.read_bytes(), self.good)
        self.assertEqual(self.backup.read_bytes(), self.good)
        archives = result['restored_archives']
        self.assertEqual(Path(archives['original']).read_bytes(), self.original)
        self.assertEqual(Path(archives['backup']).read_bytes(), self.good)
        session.close()
        self.assertEqual(self.session().startup(100)['state']['coins'], 17)

    def test_archive_failure_does_not_replace_main_or_backup(self):
        session = self.broken_session()
        real_open = os.open
        def refuse_archive(path, flags, *args, **kwargs):
            if '.recovery-' in str(path) and flags & os.O_EXCL:
                raise PermissionError('archive denied')
            return real_open(path, flags, *args, **kwargs)
        with patch.object(self.recovery.os, 'open', side_effect=refuse_archive):
            result = self.restore(session)
        self.assertFalse(result['ok'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.good)

    def test_archive_collision_never_overwrites_an_existing_archive(self):
        session = self.broken_session()
        real_open = os.open
        collisions = []
        def collide_archive(path, flags, *args, **kwargs):
            if '.recovery-' in str(path) and flags & os.O_EXCL:
                Path(path).write_bytes(b'previous archive')
                collisions.append(Path(path))
            return real_open(path, flags, *args, **kwargs)
        with patch.object(self.recovery.os, 'open', side_effect=collide_archive):
            result = self.restore(session)
        self.assertFalse(result['ok'])
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].read_bytes(), b'previous archive')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_staging_sync_failure_keeps_main_and_backup_unchanged(self):
        session = self.broken_session()
        with patch.object(self.recovery.os, 'fsync', side_effect=OSError('stage sync failed')):
            result = self.restore(session)
        self.assertFalse(result['ok'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.good)
        self.assertEqual(list(self.path.parent.glob('*.recovery-*')), [])

    def test_replace_failure_preserves_main_and_both_archives(self):
        session = self.broken_session()
        with patch.object(self.recovery.os, 'replace', side_effect=OSError('replace failed')):
            result = self.restore(session)
        self.assertFalse(result['ok'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.good)
        copies = [p.read_bytes() for p in self.path.parent.glob('*.recovery-*')]
        self.assertCountEqual(copies, [self.original, self.good])

    def test_sources_are_checked_again_after_archives_are_durable(self):
        session = self.broken_session()
        real_fsync = os.fsync
        def change_during_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                self.backup.write_bytes(b'external change')
            real_fsync(fd)
        with patch.object(self.recovery.os, 'fsync', side_effect=change_during_directory_sync):
            result = self.restore(session)
        self.assertFalse(result['ok'])
        self.assertEqual(result['issue']['code'], 'recovery_stale')
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), b'external change')

    def test_post_replace_sync_failure_reports_committed_uncertainty(self):
        session = self.broken_session()
        real_fsync = os.fsync
        def fail_committed_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode) and self.path.read_bytes() == self.good:
                raise OSError('directory sync failed')
            real_fsync(fd)
        with patch.object(self.recovery.os, 'fsync', side_effect=fail_committed_directory_sync):
            result = self.restore(session)
        self.assertFalse(result['ok'])
        self.assertEqual(result['phase'], 'recovery')
        self.assertEqual(result['issue']['code'], 'recovery_uncertain')
        self.assertIn('已替换', result['issue']['message'])
        self.assertNotIn('token', result['recovery'])
        self.assertNotIn('state', result)
        self.assertEqual(self.path.read_bytes(), self.good)
        self.assertEqual(self.backup.read_bytes(), self.good)
        self.assertIsNone(session.tick(1000, 2))

    def test_symlink_backup_is_not_followed_or_offered_for_restore(self):
        self.path.write_bytes(self.original)
        elsewhere = self.path.parent / 'elsewhere.json'
        elsewhere.write_bytes(self.good)
        self.backup.symlink_to(elsewhere)
        reply = self.session().startup(100)
        self.assertFalse(reply['recovery']['backup_available'])
        self.assertNotIn('token', reply['recovery'])
        self.assertEqual(elsewhere.read_bytes(), self.good)

    def test_ready_quit_only_exits_after_checkpoint_succeeds(self):
        session = self.session()
        with patch('tianmu_mvp.service.save_state', side_effect=OSError('disk full')):
            result = session.handle({'action': 'quit'}, 100)
        self.assertFalse(result['ok'])
        self.assertFalse(result.get('should_exit', False))
        self.assertFalse(self.path.exists())
        self.assertTrue(session.handle({'action': 'quit'}, 100)['should_exit'])
        self.assertEqual(load_state(self.path).coins, 0)

    def test_worker_driver_discards_recovery_wait_and_consumes_internal_flags(self):
        from tianmu_mvp.worker import WorkerDriver
        session = self.broken_session()
        driver = WorkerDriver(session, 1)
        self.assertIsNone(driver.tick(10000, 10000))
        token = session.startup(100)['recovery']['token']
        reply = driver.handle({'action': 'recovery_restore', 'confirmed': True, 'token': token},
                              10000, 10000)
        self.assertTrue(reply['ok'])
        self.assertNotIn('reset_active_clock', reply)
        self.assertEqual(session.service.game.elapsed_seconds, 0)
        self.assertIsNone(driver.tick(10030, 10030))
        self.assertEqual(session.service.game.elapsed_seconds, 0)
        driver.tick(10031, 10031)
        self.assertEqual(session.service.game.elapsed_seconds, 1)
        quit_reply = driver.handle({'action': 'quit'}, 10031, 10031)
        self.assertTrue(driver.should_exit)
        self.assertNotIn('should_exit', quit_reply)

    def test_worker_bootstrap_reports_lock_and_dependency_failures(self):
        from tianmu_mvp.worker import bootstrap
        self.broken_session()
        driver, reply = bootstrap(self.path, 100, 100)
        self.assertIsNone(driver)
        self.assertEqual(reply['phase'], 'failed')
        self.assertEqual(reply['issue']['code'], 'save_in_use')
        with patch('tianmu_mvp.worker.importlib.import_module',
                   side_effect=ModuleNotFoundError('missing runtime dependency')):
            driver, reply = bootstrap(self.path, 100, 100)
        self.assertIsNone(driver)
        self.assertEqual(reply['phase'], 'failed')
        self.assertEqual(reply['issue']['code'], 'runtime_unavailable')


if __name__ == '__main__':
    unittest.main()
