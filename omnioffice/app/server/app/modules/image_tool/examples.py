"""图片处理模块 · 典型使用场景示例。

这些示例同时充当**可执行的用法文档**：直接 `python examples.py` 即可跑通全部本地能力
（不需要数据库、不需要 AI），照着改就是自己的脚本。

每个示例只依赖能力文件（convert/stitch/compress/transform），不碰数据库与身份 ——
这正是本模块「各功能模块之间解耦、可独立调用」的体现。

    python examples.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.modules.image_tool import compress, constants, convert, imaging, stitch, transform


def _make_demo_images(workdir: Path) -> list[Path]:
    """造 3 张演示图（含一张带透明通道的 PNG）。"""
    from PIL import Image, ImageDraw

    paths: list[Path] = []
    colors = [(220, 80, 80), (80, 160, 220), (100, 200, 120)]
    for i, color in enumerate(colors, start=1):
        p = workdir / f"demo{i}.png"
        img = Image.new("RGB", (320, 240), color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 280, 200], outline=(255, 255, 255), width=3)
        draw.text((120, 110), f"DEMO {i}", fill=(255, 255, 255))
        img.save(p)
        paths.append(p)
    return paths


# ============================================================ 场景一：格式转换


def scenario_convert(workdir: Path, src: Path) -> None:
    """把手机随手拍的 PNG 批量转成体积小得多的 WebP，发朋友圈/嵌网页。

    要点：
    - 转换产出**新文件**，原图不动；
    - 透明度会被正确保留（PNG→WebP 是无损于 alpha 的）；
    - EXIF 默认剥离，避免 GPS 坐标随图外发。
    """
    for fmt, q in (("WEBP", 88), ("JPEG", 85), ("PNG", None)):
        r = convert.convert_file(src, fmt, quality=q)
        out = workdir / f"out.{constants.OUTPUT_FORMATS[fmt]}"
        out.write_bytes(r.data)
        print(
            f"  {fmt:5} {r.info.width}×{r.info.height}  "
            f"{len(r.data):>8,} B  → {out.name}"
        )
    print("  转 JPEG 时透明区已合成为白色（JPEG 无 alpha 通道）")


# ============================================================ 场景二：格式转换的坑


def scenario_alpha_to_jpeg(workdir: Path) -> None:
    """透明 PNG 转 JPEG：透明像素**不能**直接压黑，否则白底文档会出现黑块。

    本模块的处理是合成到白底（imaging.normalize_mode 内），这里演示效果差异。
    """
    from PIL import Image

    p = workdir / "alpha.png"
    img = Image.new("RGBA", (200, 120), (255, 255, 255, 0))  # 全透明
    img.paste((200, 60, 60, 255), (20, 20, 120, 80))  # 画一块半透明红
    img.save(p)

    # 错误做法：直接 convert("RGB") —— 透明区变成黑色
    bad = Image.open(p).convert("RGB")
    bad_path = workdir / "alpha_bad.jpg"
    bad.save(bad_path, "JPEG")

    # 本模块做法：合成白底
    good = convert.convert_file(p, "JPEG", quality=90)
    good_path = workdir / "alpha_good.jpg"
    good_path.write_bytes(good.data)

    print(f"  直接转 RGB（黑底）  → {bad_path.name}")
    print(f"  本模块合成白底      → {good_path.name}")


# ============================================================ 场景三：拼接


def scenario_stitch(workdir: Path, srcs: list[Path]) -> None:
    """把多张截图拼成一张长图，便于一次性发群里。

    场景 A：横纵随便哪种都行 —— 用水平拼。
    场景 B：手机截图尺寸不一致 —— 勾 uniform 等比缩放到统一尺寸更整齐。
    场景 C：网格排版做九宫格。
    """
    a = stitch.stitch_files(srcs[:2], mode="horizontal", gap=16, background="#f5f5f5")
    (workdir / "stitch_h.png").write_bytes(a.data)
    print(f"  水平（间距16，灰底）→ {a.info.width}×{a.info.height}")

    b = stitch.stitch_files(srcs, mode="vertical", gap=8, background="#ffffff", uniform=True)
    (workdir / "stitch_v.png").write_bytes(b.data)
    print(f"  垂直（统一尺寸）    → {b.info.width}×{b.info.height}")

    c = stitch.stitch_files(srcs + srcs[:3], mode="grid", gap=12, background="#eeeeee")
    (workdir / "stitch_grid.png").write_bytes(c.data)
    print(
        f"  网格 {c.meta['columns']}列×{c.meta['rows']}行   → "
        f"{c.info.width}×{c.info.height}（{c.meta['count']} 张）"
    )


# ============================================================ 场景四：压缩


def scenario_compress(workdir: Path, src: Path) -> None:
    """两种压缩诉求：

    A. 「我只知道要更小」→ 目标体积模式，服务端二分搜索质量因子；
    B. 「我知道要 80 分画质」→ 直接给质量因子。
    """
    print(f"  原图体积：{src.stat().st_size:,} B")

    q = compress.compress_file(src, target_format="JPEG", quality=70)
    print(f"  质量因子 70 → {len(q.data):,} B（省 {q.meta['savedRatio']}%）")

    t = compress.compress_file(src, target_format="JPEG", target_bytes=20_000)
    flag = "达标" if t.meta["reachedTarget"] else "未达标"
    print(
        f"  目标 20 KB → 实际 {t.meta['compressedSize']:,} B"
        f"（质量 {t.meta['quality']}，{flag}，二分 {t.meta['searchSteps']} 轮）"
    )
    if t.meta.get("hint"):
        print(f"    提示：{t.meta['hint']}")

    # 诚实的边界：已高度压缩的图（如纯色截图）压不动，如实回报而不是给更大的文件
    flat = workdir / "flat.png"
    from PIL import Image

    Image.new("RGB", (400, 300), (128, 128, 128)).save(flat)
    f = compress.compress_file(flat, target_format="JPEG", target_bytes=3_000)
    print(f"  纯色图压到 3 KB → {f.meta['compressedSize']:,} B（{f.meta['quality']}）")
    if f.meta.get("hint"):
        print(f"    提示：{f.meta['hint']}")


# ============================================================ 场景五：编辑


def scenario_transform(workdir: Path, src: Path) -> None:
    """缩放、旋转、裁剪、水印 —— 四个日常小操作。"""
    r1 = transform.transform_file(src, "resize", width=160)
    (workdir / "t_resize.png").write_bytes(r1.data)
    print(f"  缩放到宽 160   → {r1.info.width}×{r1.info.height}")

    r2 = transform.transform_file(src, "rotate", angle=90)
    (workdir / "t_rotate.png").write_bytes(r2.data)
    print(f"  旋转 90°       → {r2.info.width}×{r2.info.height}（自动交换宽高）")

    r3 = transform.transform_file(src, "crop", crop_ratio=(16, 9))
    (workdir / "t_crop.png").write_bytes(r3.data)
    print(f"  裁剪 16:9      → {r3.info.width}×{r3.info.height}")

    r4 = transform.transform_file(src, "watermark", text="内部资料", position="bottom-right", opacity=45)
    (workdir / "t_wm.png").write_bytes(r4.data)
    print(f"  右下角水印     → {r4.info.width}×{r4.info.height}")


# ============================================================ 场景六：OCR


def scenario_ocr(workdir: Path, src: Path) -> None:
    """OCR 需要配置 AI Key；未配置时给出的是**可行动提示**而非原始异常。

    配置方式：应用内「设置 → AI 模型 → 图片处理」，模型推荐 qwen3.5-ocr。
    """
    from app.modules.image_tool import ocr

    print("  OCR 需要 AI Key。未配置时的行为：")
    try:
        # owner 传空串 = 读全局默认配置；真实调用须传 Identity.uid（多账号隔离）
        ocr.ocr_path(src, owner="")
    except Exception as e:  # noqa: BLE001 —— 演示如何展示错误
        code = getattr(e, "code", "?")
        print(f"    → [{code}] {getattr(e, 'message', str(e))}")
    print("  配置后返回：{'text': 整图文本, 'blocks': [{'text','box','confidence'}], ...}")
    print("  box 为 0~1000 千分比坐标（非像素），用于在图上叠加高亮框。")


# ============================================================ 场景七：异常契约


def scenario_errors(workdir: Path, src: Path) -> None:
    """统一异常：每条错误都带**可行动的中文提示**，且能被 HTTP 层原样翻译。"""
    from app.modules.image_tool.errors import ImageToolError

    broken = workdir / "broken.png"
    broken.write_bytes(b"this is definitely not an image")

    cases = [
        ("损坏文件", lambda: imaging.probe(broken)),
        ("非法目标格式", lambda: convert.convert_file(src, "PDF")),
        ("目标体积过小", lambda: compress.compress_file(src, target_format="JPEG", target_bytes=10)),
        ("拼接图不足两张", lambda: stitch.stitch_files([src], "horizontal")),
        ("水印文字为空", lambda: transform.transform_file(src, "watermark", text="")),
        ("非法拼接方式", lambda: stitch.stitch_files([src, src], "diagonal")),
    ]
    for label, fn in cases:
        try:
            fn()
            print(f"  {label:12} → 未报错（不符合预期）")
        except ImageToolError as e:
            print(f"  {label:12} → [{e.code}] HTTP {e.status}")
            print(f"               {e.message}")
            # 这就是路由层会返回的响应体
            assert set(e.to_payload()["detail"]) >= {"error", "message"}


# ============================================================ 主流程


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="image-tool-demo-") as tmp:
        workdir = Path(tmp)
        srcs = _make_demo_images(workdir)
        src = srcs[0]

        print("\n【场景一】格式转换：PNG → WebP / JPEG / PNG")
        scenario_convert(workdir, src)

        print("\n【场景二】透明度处理：透明 PNG → JPEG 不变黑")
        scenario_alpha_to_jpeg(workdir)

        print("\n【场景三】拼接：水平 / 垂直 / 网格")
        scenario_stitch(workdir, srcs)

        print("\n【场景四】压缩：质量因子 / 目标体积 / 压不动的诚实回报")
        scenario_compress(workdir, src)

        print("\n【场景五】编辑：缩放 / 旋转 / 裁剪 / 水印")
        scenario_transform(workdir, src)

        print("\n【场景六】OCR：未配 Key 时的可行动提示")
        scenario_ocr(workdir, src)

        print("\n【场景七】统一异常契约")
        scenario_errors(workdir, src)

        print("\n所有产物已写入：", workdir)


if __name__ == "__main__":
    main()
