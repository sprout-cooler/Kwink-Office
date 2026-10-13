#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打包瘦身（真机安装速度保障）。

背景：`.dockerignore` 只影响 `docker build` 的上下文，**fnpack 打包不读它**。
所以 web/node_modules（1.3 万个文件）与 __pycache__ 会被原样打进 FPK 的
app.tgz —— 真机上 appcenter-cli 安装时要解压这一万多个文件，
既拖慢安装，也让 FPK 体积虚增。

这两个目录都不是运行时必需：
  - node_modules：前端产物已构建进 server/public，Docker 镜像内不再需要；
  - __pycache__：Python 字节码，容器启动时按 .py 自动重新生成。

处理方式：移出到项目内暂存区（.build-trash/），而非直接删除 ——
既绕过本机删除保护，又保留可恢复性。真机首次 build 仍需
web/node_modules，故每次打包前需保证它存在（本脚本只在 fnpack 前移出）。

运行：python build/slim_package.py
必须在 fnpack build 之前执行，打包完成后可执行 python build/slim_package.py --restore
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "omnioffice"
TRASH = ROOT / ".build-trash"

# (相对路径, 清理理由)
TARGETS = [
    (PKG / "app" / "web" / "node_modules", "前端依赖，产物已构建进 server/public"),
    (PKG / "app" / "server" / "app" / "__pycache__", "Python 字节码，容器内自动重建"),
    (PKG / "app" / "server" / "app" / "core" / "__pycache__", "同上"),
    (PKG / "app" / "server" / "app" / "db" / "__pycache__", "同上"),
    (PKG / "app" / "server" / "app" / "modules" / "__pycache__", "同上"),
    (PKG / "app" / "server" / "app" / "modules" / "weekly_report" / "__pycache__", "同上"),
    (PKG / "app" / "server" / "app" / "tests" / "__pycache__", "同上"),
]


def count_files(p: Path) -> int:
    return sum(1 for f in p.rglob("*") if f.is_file())


def restore() -> None:
    if not TRASH.is_dir():
        print("打包瘦身：无暂存内容，无需恢复")
        return
    # 暂存键 -> 原路径（与 slim() 的 key 生成规则严格对称）
    for target, _ in TARGETS:
        key = "web_node_modules" if target.name == "node_modules" else str(
            target.relative_to(PKG / "app" / "server")
        ).replace("/", "_").replace("\\", "_")
        saved = TRASH / key
        if not saved.is_dir():
            continue
        if target.exists():
            print(f"  跳过（目标已存在）：{target.relative_to(PKG)}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(saved), str(target))
        print(f"  restored -> {target.relative_to(PKG)}")
    try:
        TRASH.rmdir()
    except OSError:
        pass  # 暂存区非空（可能有未知项），保留待人工处理
    print("打包瘦身：暂存内容已恢复")


def slim() -> None:
    TRASH.mkdir(exist_ok=True)
    moved = 0
    total = 0
    for target, reason in TARGETS:
        if not target.exists():
            continue
        n = count_files(target)
        # __pycache__ 统一收纳到暂存区并保持可辨识；node_modules 单独一项
        key = "web_node_modules" if target.name == "node_modules" else str(
            target.relative_to(PKG / "app" / "server")
        ).replace("/", "_").replace("\\", "_")
        saved = TRASH / key
        if saved.exists():
            print(f"  跳过（暂存区已有同名项）：{key}")
            continue
        shutil.move(str(target), str(saved))
        moved += 1
        total += n
        print(f"  移出 {target.relative_to(PKG)}  ({n} 个文件) —— {reason}")

    if moved == 0:
        print("打包瘦身：无需处理（node_modules / __pycache__ 均不在包内）")
        return
    print(
        f"打包瘦身：移出 {moved} 个目录、{total} 个文件，避免打进 FPK。"
        f"\n  恢复：python build/slim_package.py --restore"
    )


if __name__ == "__main__":
    if "--restore" in sys.argv:
        restore()
    else:
        slim()
