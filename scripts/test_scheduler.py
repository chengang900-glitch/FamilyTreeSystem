"""Regression: the background backup worker must read settings inside an app context."""
from pathlib import Path
from _testenv import bootstrap, cleanup

bootstrap('scheduler')
try:
    from server.app import app
    from server.service import backup
    backup.stop_scheduler()
    thread = getattr(app, '_backup_thread', None)
    if thread:
        thread.join(timeout=2)
    class OneIteration:
        calls = 0
        def wait(self, seconds):
            self.calls += 1
            return self.calls > 1
    calls = []
    original_stop, original_backup = backup._stop, backup.do_backup
    try:
        backup._stop = OneIteration()
        backup._worker.last = 0
        backup.do_backup = lambda: calls.append(True) or Path('probe.zip')
        backup._worker(app)
        assert calls == [True], 'Background settings read or backup did not complete'
    finally:
        backup._stop, backup.do_backup = original_stop, original_backup
    print('PASS: background backup reads settings and completes inside app context')
finally:
    cleanup()
