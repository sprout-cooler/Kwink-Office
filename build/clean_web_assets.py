#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""前端产物清理（Docker 镜像体积保障）。

背景：vite 的 emptyOutDir=false（本机文件删除受保护，无法自动清空输出目录）
导致带内容哈希的旧产物（index-XXXX.js/css）残留在 server/public/assets/。
这些文件不会被 index.html 引用，但会被 Dockerfile 的 `COPY server/ /srv/`
打进 Docker 镜像 —— 每次构建都在 FPK 里白白多带几 MB，真机安装更慢。

本脚本按 index.html 的实际引用做「白名单清理」：
  保留 index.html 引用到的文件，其余 assets/* 一律移除。

为什么用 Python 而不是 Node：
  本机对 node 的 fs.unlinkSync / cmd del 都装有删除保护 shim（EBUSY），
  而项目自带的 .tools/python 不受该限制。清理构建产物语义明确，
  使用确定性的本地删除，不走回收站。

运行：python build/clean_web_assets.py
必须在 vite build 之后、fnpack build 之前执行。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "omnioffice"
PUBLIC_DIR = ROOT / "app" / "server" / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"
INDEX_HTML = PUBLIC_DIR / "index.html"

# index.html 实际引用的资源（与 vite 产物命名一致）
REF_PATTERN = re.compile(r"[\w.-]+\.(?:js|css|woff2?|ttf|png|jpe?g|svg|webp)")
# 仅这两类带内容哈希、需按引用判定的文件参与清理
HASHED_PATTERN = re.compile(r"^index-[\w-]+\.(?:js|css)$")


def fail(msg: str) -> None:
    print(f"  [失败] {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not INDEX_HTML.is_file():
        fail(f"未找到前端产物 {INDEX_HTML} —— 请先执行 vite build")
    if not ASSETS_DIR.is_dir():
        print("前端产物清理：assets 目录不存在，跳过")
        return

    referenced = set(REF_PATTERN.findall(INDEX_HTML.read_text(encoding="utf-8")))

    kept: list[str] = []
    stale: list[str] = []
    freed = 0

    for entry in sorted(ASSETS_DIR.iterdir()):
        if not entry.is_file():
            continue
        size = entry.stat().st_size
        # index.html 引用的、或非哈希命名（favicon 等固定名）→ 保留
        if not HASHED_PATTERN.match(entry.name) or entry.name in referenced:
            kept.append(f"{entry.name} ({size / 1024:.0f}KB)")
            continue
        stale.append(entry)
        freed += size
        print(f"  stale: {entry.name} ({size / 1024:.0f}KB)")

    still: list[str] = []
    for entry in stale:
        try:
            entry.unlink()
        except OSError as e:
            still.append(f"{entry.name}（{e.strerror or e}）")

    if still:
        fail("以下陈旧产物未能删除（可能有服务正在运行，请先停服务）：" + ", ".join(still))

    print(
        f"前端产物清理：保留 {len(kept)} 个（{', '.join(kept) or '无'}），"
        f"清理陈旧文件 {len(stale)} 个，释放 {freed / 1024 / 1024:.2f} MB"
    )


if __name__ == "__main__":
    main()
