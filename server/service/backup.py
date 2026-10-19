"""数据备份：SQLite 主库 + 资源目录打包

多进程约束：gunicorn / 多 worker 下每个进程都会 import 应用，
如果各自起线程就会出现「同分钟两次备份、互相覆盖并清理」的问题。
这里用 data/backups/backup.lock 里的 PID 做单实例控制，只有抢到锁的进程跑定时备份，
锁文件在进程退出后成为残留，下次启动会识别 PID 已失效并自动接管。
"""
import logging
import os
import sqlite3
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from server.common import now_str

logger = logging.getLogger(__name__)

_stop = threading.Event()
_last_error = None
_last_success = None


def _stamp():
    """毫秒 + PID，避免多进程/同一秒内生成同名文件"""
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime('%Y%m%d_%H%M%S') + f'_{now.microsecond // 1000:03d}_{os.getpid()}'


def backup_db(db_path: str, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f'db_{_stamp()}.db'
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def backup_all(db_path: str, backup_dir: Path, upload_dir: Path, with_resources=True) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f'backup_{_stamp()}.zip'
    db_file = backup_db(db_path, backup_dir)
    try:
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(db_file, f'data/{db_file.name}')
            if with_resources and upload_dir.exists():
                for p in upload_dir.rglob('*'):
                    if p.is_file():
                        z.write(p, f'uploads/{p.relative_to(upload_dir).as_posix()}')
    finally:
        try:
            db_file.unlink()
        except OSError:
            pass
    return target


def clean_old(backup_dir: Path, keep: int):
    files = sorted(backup_dir.glob('backup_*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[max(keep, 1):]:
        try:
            p.unlink()
        except OSError:
            logger.warning('[backup] 旧备份删除失败：%s', p)


def do_backup(with_resources=True):
    global _last_success, _last_error
    app = current_app._get_current_object()
    bdir = Path(app.config['BACKUP_DIR'])
    try:
        path = backup_all(app.config['DB_PATH'], bdir, Path(app.config['UPLOAD_DIR']),
                          with_resources)
        from server.service import audit, settings
        clean_old(bdir, settings.get_int('storage.backup_keep_count', 5))
        audit.cleanup(settings.get_int('storage.operation_log_retention_days', 0))
        _last_success = now_str()
        _last_error = None
        return path
    except Exception as exc:
        _last_error = f'{now_str()} {exc}'
        raise


def status():
    return {'last_success': _last_success, 'last_error': _last_error}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_singleton(lock_file: Path) -> bool:
    """抢占备份单实例锁；锁内 PID 已退出则接管"""
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    def create():
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)

    try:
        create()
        return True
    except FileExistsError:
        pass
    try:
        holder = int((lock_file.read_text(encoding='utf-8') or '0').strip() or 0)
    except (OSError, ValueError):
        holder = 0
    if _pid_alive(holder):
        return False
    try:
        lock_file.unlink()
    except OSError:
        return False
    try:
        create()
        return True
    except OSError:
        return False


def _worker(app):
    while not _stop.wait(5):
        try:
            from server.service import settings
            with app.app_context():
                if not settings.get_bool('storage.backup_enabled', True):
                    continue
                interval = max(settings.get_int('storage.backup_interval_minutes', 60), 1)
                if time.time() - _worker.last < interval * 60:
                    continue
                _worker.last = time.time()
                path = do_backup()
                logger.info('[backup] 自动备份完成：%s', path.name)
        except Exception:
            # 备份失败必须有痕迹，静默吞错会导致「以为有备份，其实没有」
            logger.exception('[backup] 自动备份失败')


_worker.last = 0.0


def start_scheduler(app):
    if getattr(app, '_backup_thread', None):
        return
    lock_file = Path(app.config['BACKUP_DIR']) / 'backup.lock'
    if not _acquire_singleton(lock_file):
        logger.info('[backup] 其他进程已持有备份锁，本进程不启动定时备份')
        return
    t = threading.Thread(target=_worker, args=(app,), name='fts-backup', daemon=True)
    app._backup_thread = t
    t.start()


def stop_scheduler():
    _stop.set()
