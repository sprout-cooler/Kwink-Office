"""审计日志：上传/识别/校对/导出等关键操作必须留痕（V10 非功能需求）。

排障入口约定（避坑指南 §1.4）：关键启动参数与关键操作打印到 stdout（fnOS 汇总到
/var/apps/{appname}/var/app.log），同时结构化落盘到数据目录 audit.log。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import settings

_AUDIT_FILE = Path(settings.data_dir) / "audit.log"


def log(event: str, identity_uid: str | None, detail: dict | None = None) -> None:
    record = {
        "ts": int(time.time() * 1000),
        "event": event,
        "uid": identity_uid,
        "detail": detail or {},
    }
    line = json.dumps(record, ensure_ascii=False)
    print(f"[audit] {line}", flush=True)
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        # 审计写盘失败不阻断业务；stdout 已有记录
        pass
