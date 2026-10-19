"""上传目录安全路径

所有来自数据库/导入包的文件路径都必须经过这里：
- 只允许相对路径；
- 解析后必须仍位于 UPLOAD_DIR 之内（防止 ../、绝对路径、符号链接逃逸）。
"""
from pathlib import Path

from flask import current_app

from server.common import ApiError


def upload_root() -> Path:
    return Path(current_app.config['UPLOAD_DIR']).resolve()


def is_safe_relative(rel) -> bool:
    """判断数据库中的 storage_path 是否仍应被视为上传目录内的相对路径。"""
    text = str(rel or '').strip()
    if not text:
        return True
    raw = Path(text)
    if raw.is_absolute():
        return False
    if any(part == '..' for part in raw.parts):
        return False
    root = upload_root()
    try:
        resolved = (root / raw).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return resolved == root or root in resolved.parents


def safe_upload_path(rel, must_exist=False) -> Path:
    """把相对路径解析为上传目录内的绝对路径；不安全或文件不存在时抛 ApiError。"""
    text = str(rel or '').strip()
    if not text:
        raise ApiError('资源文件不存在', code=404)
    raw = Path(text)
    if raw.is_absolute() or any(part == '..' for part in raw.parts):
        raise ApiError('非法文件路径', code=400)
    root = upload_root()
    try:
        path = (root / raw).resolve()
    except (OSError, ValueError, RuntimeError):
        raise ApiError('非法文件路径', code=400)
    if path == root or root not in path.parents:
        raise ApiError('非法文件路径', code=400)
    if must_exist and not path.is_file():
        raise ApiError('文件已丢失', code=404)
    return path


def sanitize_resource_paths(con):
    """清理历史库中逃逸上传目录的 storage_path（只清空，不删文件）。"""
    try:
        rows = con.execute('SELECT id, storage_path FROM resource').fetchall()
    except Exception:
        return
    for row in rows:
        if not is_safe_relative(row['storage_path']):
            con.execute('UPDATE resource SET storage_path=? WHERE id=?', ('', row['id']))
    con.commit()
