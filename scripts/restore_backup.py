"""离线恢复全库备份。

用法（请先停止服务）：
    python scripts/restore_backup.py data/backups/backup_xxx.zip --yes

备份 ZIP 结构由 server/service/backup.py 生成：
    data/db_*.db
    uploads/...
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def safe_extract(z, dest):
    for info in z.infolist():
        name = info.filename
        target = (dest / name).resolve()
        if path_is_absolute(name) or dest.resolve() not in target.parents:
            raise SystemExit(f'备份包包含非法路径，已中止：{name}')
    z.extractall(dest)


def path_is_absolute(name):
    return Path(name).is_absolute() or name.startswith(('/', '\\')) or '..' in Path(name).parts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('backup', help='backup_*.zip 路径')
    parser.add_argument('--data-dir', default=str(REPO / 'data'), help='数据目录，默认仓库 data/')
    parser.add_argument('--yes', action='store_true', help='跳过确认')
    args = parser.parse_args()

    backup = Path(args.backup).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve()
    if not backup.is_file():
        raise SystemExit(f'备份不存在：{backup}')
    if not data_dir.is_dir():
        raise SystemExit(f'数据目录不存在：{data_dir}')

    if not args.yes:
        print('即将用备份覆盖：')
        print(f'  备份：{backup}')
        print(f'  数据：{data_dir}')
        print('请确认服务已停止，否则可能损坏 SQLite。')
        if input('输入 YES 继续：').strip() != 'YES':
            print('已取消')
            return

    with tempfile.TemporaryDirectory(prefix='fts_restore_') as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(backup) as z:
            safe_extract(z, tmp)
        db_files = sorted((tmp / 'data').glob('db_*.db'))
        if not db_files:
            raise SystemExit('备份包中未找到 data/db_*.db')
        src_db = db_files[-1]
        # 完整性预检
        con = sqlite3.connect(str(src_db))
        try:
            result = con.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            con.close()
        if result != 'ok':
            raise SystemExit(f'备份数据库完整性检查失败：{result}')

        stamp = backup.stem
        target_db = data_dir / 'app.db'
        if target_db.exists():
            target_db.replace(data_dir / f'app.db.before-restore-{stamp}')
        shutil.copy2(src_db, target_db)
        for suffix in ('-wal', '-shm'):
            leftover = data_dir / f'app.db{suffix}'
            if leftover.exists():
                leftover.unlink()
        print(f'数据库已恢复：{target_db}')

        src_uploads = tmp / 'uploads'
        if src_uploads.is_dir():
            shutil.copytree(src_uploads, data_dir / 'uploads', dirs_exist_ok=True)
            print(f'资源目录已恢复：{data_dir / "uploads"}')

    print('恢复完成。请重启服务，并确认 secret.key 未随备份替换（会话会重新登录）。')


if __name__ == '__main__':
    main()
