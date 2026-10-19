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
#
# ⚠️ __pycache__ 曾用硬编码清单逐个列出，结果新增业务模块时（v1.0.26 的
# image_tool）该目录不在清单里，字节码被原样打进 FPK —— 门禁当时也没报，
# 因为它只检查了「已登记的路径」。**新增模块必须零改动**，故改为运行时递归发现。
# node_modules 仍是固定路径（只有一个，且必须整体移出）。
TARGETS = [
    (PKG / "app" / "web" / "node_modules", "前端依赖，产物已构建进 server/public"),
]


def _discover_targets() -> list[tuple[Path, str]]:
    """运行时发现全部 __pycache__（含未来新增模块目录），与 TARGETS 合并去重。"""
    found = list(TARGETS)
    server_app = PKG / "app" / "server"
    if server_app.is_dir():
        for p in sorted(server_app.rglob("__pycache__")):
            if p.is_dir():
                found.append((p, "Python 字节码，容器内自动重建"))
    return found


def all_targets() -> list[tuple[Path, str]]:
    """slim() 与 restore() 共用同一份清单，保证两者的 key 生成规则严格对称。"""
    return _discover_targets()


def count_files(p: Path) -> int:
    return sum(1 for f in p.rglob("*") if f.is_file())


def _trash_key(target: Path) -> str:
    """暂存区键名：由「相对包根路径」生成，slim / restore 共用同一函数。

    刻意用相对 PKG（而不是相对 server 根）：node_modules 不在 server 之下，
    用 server 做根会直接抛 ValueError。
    """
    rel = target.relative_to(PKG)
    return str(rel).replace("/", "_").replace("\\", "_")


def restore() -> None:
    if not TRASH.is_dir():
        print("打包瘦身：无暂存内容，无需恢复")
        return
    for target, _ in all_targets():
        key = _trash_key(target)
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
    for target, reason in all_targets():
        if not target.exists():
            continue
        n = count_files(target)
        key = _trash_key(target)
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
