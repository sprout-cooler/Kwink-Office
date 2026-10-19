"""图片文件存储：按账号隔离的目录 + md5 命名 + 原子落盘。

**铁律（避坑 K）：数据目录必须与数据库同命。**
本模块文件落 `${DATA_DIR}/images/<owner_uid>/`，而 DATA_DIR 在真机上挂
`${TRIM_PKGVAR}/data`（与库同命、升级保留）。绝不挂 `${TRIM_APPDEST}`
（安装目录 target，升级会被清空 → 记录在、文件没了）。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from ...core.config import settings
from . import constants
from .errors import ImageToolError


def images_root(owner_uid: str) -> Path:
    """某账号的图片根目录（按需创建）。

    owner_uid 来自 Identity.uid（应用账号 data_key），目录名由服务端决定，
    不接受客户端传入 —— 否则就是路径穿越入口（避坑指南 §3.1）。
    """
    safe = "".join(ch for ch in str(owner_uid) if ch.isalnum() or ch in "-_")
    if not safe:
        raise ImageToolError("BAD_OWNER", "账号标识非法，无法定位存储目录", 400)
    p = Path(settings.data_dir) / "images" / safe
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ImageToolError(
            "STORAGE_UNAVAILABLE",
            f"图片目录不可写：{type(e).__name__}: {e}。"
            f"请检查数据目录 {settings.data_dir} 的权限与剩余空间",
            500,
        ) from None
    return p


def md5_of(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def write_bytes(owner_uid: str, data: bytes, ext: str) -> tuple[Path, str]:
    """原子落盘，返回 (最终路径, md5)。

    为什么不用 `if not exists(): write_bytes()`（周报 upload_screenshots 至今仍是这个写法）：
    write_bytes 是「截断 → 写入」，中途断电/磁盘满会留下**半截文件**，
    后续 decode 直接抛 DECODE_FAILED，用户看到的是「图片损坏」这种误导性提示。
    这里统一 mkstemp + fsync + os.replace，任何中断要么是旧文件要么是新文件，不存在半截。

    同 md5 已存在且大小一致时直接复用（幂等：同一张图重复上传不重复占盘）。
    """
    md5 = md5_of(data)
    target = images_root(owner_uid) / f"{md5}.{ext}"
    try:
        if target.is_file() and target.stat().st_size == len(data):
            return target, md5
    except OSError:
        pass

    fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ImageToolError(
            "WRITE_FAILED",
            f"图片写入失败：{type(e).__name__}: {e}。"
            f"请检查数据目录 {settings.data_dir} 的写权限与剩余空间",
            500,
        ) from None
    return target, md5


def remove_file(path: str) -> bool:
    """删除文件。返回是否真的删掉了。

    删不掉**只记日志不抛错** —— 记录删除已经提交，文件残留不该把用户卡死
    （与 v1.0.24/v1.0.25 模板删除踩过的坑同一处理原则）。
    """
    if not path:
        return False
    p = Path(path)
    try:
        if p.is_file():
            p.unlink()
            return True
    except OSError as e:
        print(f"[image_tool] 文件删除失败 {p}: {type(e).__name__}: {e}", flush=True)
    return False


def read_source(owner_uid: str, path: str) -> Path:
    """读库里的路径前先做两道校验。

    1. 文件真实存在（否则 FILE_GONE，前端可引导重传）；
    2. 路径必须落在该账号的图片目录内 —— 库里若被写入越界路径（迁移 bug、
       外部直改 DB），这里直接挡住，不给「任意文件读取」留口子。
    """
    p = Path(path)
    if not p.is_file():
        raise ImageToolError("FILE_GONE", f"图片文件已丢失：{path}", 410, path=str(path))
    root = images_root(owner_uid).resolve()
    try:
        p.resolve().relative_to(root)
    except ValueError:
        raise ImageToolError(
            "PATH_ESCAPE",
            "图片路径越界（记录指向了本账号目录之外的文件），已拒绝访问",
            403,
            path=str(path),
        ) from None
    return p


def ext_for(fmt: str) -> str:
    """Pillow 格式名 → 落盘后缀。"""
    try:
        return constants.OUTPUT_FORMATS[fmt.upper()]
    except KeyError:
        raise ImageToolError(
            "UNSUPPORTED_FORMAT",
            f"不支持的输出格式：{fmt}",
            400,
            allowed=list(constants.OUTPUT_FORMATS),
        ) from None
