"""异步 Worker 占位（Compose worker 服务入口）。

M2 起：Celery/Redis 任务 —— 截图识别、模板填充、LibreOffice 渲染均走此进程，
避免 LibreOffice CPU 尖峰拖垮 api（评估方案 4.3 要点 3）。
"""
from __future__ import annotations

import time


def main() -> None:
    print("[worker] started (placeholder loop, 60s heartbeat)", flush=True)
    while True:
        time.sleep(60)
        print("[worker] heartbeat", flush=True)


if __name__ == "__main__":
    main()
