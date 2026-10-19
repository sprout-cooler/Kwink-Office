"""能力②：图片拼接（水平 / 垂直 / 网格），含间距与背景色设置。

可独立调用：
    from app.modules.image_tool.stitch import stitch_files
    stitch_files([Path("a.png"), Path("b.jpg")], "horizontal", gap=16, background="#ffffff")

设计要点：
- **尺寸不等也能拼**：默认按最大边拉伸留白（letterbox），而不是直接对齐顶部
  —— 截图长宽不一才是常态，直接对齐会得到参差不齐的锯齿边；
- **可选统一尺寸**：uniform=True 时先缩放到同一尺寸，输出更整齐（适合拼图分享）；
- **动图不参与拼接**：各自动画帧时长不一致，拼出来的动画会错帧，直接拒绝并说明原因。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from . import constants, imaging
from .errors import ImageToolError


@dataclass(frozen=True)
class StitchResult:
    data: bytes
    info: imaging.ImageInfo
    meta: dict[str, Any]


def stitch_files(
    srcs: list[Path],
    mode: str = "horizontal",
    gap: int = 0,
    background: str = "#ffffff",
    target_format: str = constants.Format.PNG,
    uniform: bool = False,
    quality: int | None = None,
) -> StitchResult:
    """把多张图拼成一张。

    Args:
        srcs: 源图路径列表（至少 2 张）。
        mode: horizontal（左右）| vertical（上下）| grid（网格）。
        gap: 图与图之间的间距像素，0~500。
        background: 间隙与留白填充色，`#RGB` / `#RRGGBB`。
        target_format: 输出格式，默认 PNG（无损，适合拼接后二次编辑）。
        uniform: 是否先把所有图等比缩放到同一尺寸（更整齐，但会损失细节）。
        quality: 有损格式的质量因子。
    """
    if len(srcs) < 2:
        raise ImageToolError(
            "NEED_TWO_IMAGES",
            f"拼接至少需要 2 张图片，当前只有 {len(srcs)} 张",
            400,
        )
    if mode not in constants.STITCH_MODES:
        raise ImageToolError(
            "BAD_PARAM",
            f"拼接方式不支持：{mode}。可用：{'、'.join(constants.STITCH_MODES)}",
            400,
            allowed=list(constants.STITCH_MODES),
        )
    gap = clamp_gap(gap)
    bg = parse_color(background)
    fmt = target_format.upper()
    if fmt not in constants.OUTPUT_FORMATS:
        raise ImageToolError("UNSUPPORTED_FORMAT", f"不支持的输出格式：{target_format}", 400)

    images: list[Image.Image] = []
    try:
        for p in srcs:
            img = imaging.open_image(p)
            if getattr(img, "is_animated", False):
                raise ImageToolError(
                    "ANIMATED_NOT_SUPPORTED",
                    f"暂不支持拼接动图：{p.name}。请先转成静帧（GIF 仅取首帧）后再拼接。",
                    400,
                    filename=p.name,
                )
            # 统一转成 RGBA：不同源的色彩模式（P / L / RGB / CMYK）混拼会报
            # "images do not match" 或静默错色，先归一最省事。
            images.append(img.convert("RGBA"))

        if uniform:
            tw = max(i.width for i in images)
            th = max(i.height for i in images)
            images = [letterbox(i, tw, th, bg) for i in images]

        canvas, cols, rows = _compose(images, mode, gap, bg)
        guard_canvas(canvas)
        data = imaging.encode(canvas, fmt, quality)
        info = imaging.ImageInfo(
            format=fmt,
            width=canvas.width,
            height=canvas.height,
            mode="RGBA",
            frames=1,
            has_alpha=fmt in constants.ALPHA_FORMATS,
            animated=False,
        )
        meta = {
            "mode": mode,
            "gap": gap,
            "background": background,
            "count": len(images),
            "columns": cols,
            "rows": rows,
            "uniform": uniform,
            "targetFormat": fmt,
            "order": [p.name for p in srcs],
        }
        return StitchResult(data=data, info=info, meta=meta)
    finally:
        for i in images:
            try:
                i.close()
            except Exception:  # noqa: BLE001 —— close 失败无需影响主流程
                pass


def _compose(
    images: list[Image.Image], mode: str, gap: int, bg: tuple[int, int, int, int]
) -> tuple[Image.Image, int, int]:
    """按拼接方式生成画布。返回 (画布, 列数, 行数)。"""
    n = len(images)
    if mode == "horizontal":
        width = sum(i.width for i in images) + gap * (n - 1)
        height = max(i.height for i in images)
        canvas = Image.new("RGBA", (width, height), bg)
        x = 0
        for i in images:
            # 垂直居中，避免长短图拼出来上下不齐
            canvas.paste(i, (x, (height - i.height) // 2), i)
            x += i.width + gap
        return canvas, n, 1

    if mode == "vertical":
        width = max(i.width for i in images)
        height = sum(i.height for i in images) + gap * (n - 1)
        canvas = Image.new("RGBA", (width, height), bg)
        y = 0
        for i in images:
            canvas.paste(i, ((width - i.width) // 2, y), i)
            y += i.height + gap
        return canvas, 1, n

    # grid：cols 由调用方按需指定，默认取接近正方形的列数（视觉最均衡）
    cols = _grid_columns(n)
    return _compose_grid(images, cols, gap, bg)


def compose_grid(
    images: list[Image.Image], cols: int, gap: int, bg: tuple[int, int, int, int]
) -> tuple[Image.Image, int, int]:
    """网格拼接（公开入口，供 service 层显式指定列数时调用）。"""
    return _compose_grid(images, cols, gap, bg)


def _compose_grid(
    images: list[Image.Image], cols: int, gap: int, bg: tuple[int, int, int, int]
) -> tuple[Image.Image, int, int]:
    cols = max(1, min(cols, constants.GRID_MAX, len(images)))
    rows = (len(images) + cols - 1) // cols
    cell_w = max(i.width for i in images)
    cell_h = max(i.height for i in images)
    width = cols * cell_w + gap * (cols - 1)
    height = rows * cell_h + gap * (rows - 1)
    canvas = Image.new("RGBA", (width, height), bg)
    for idx, i in enumerate(images):
        r, c = divmod(idx, cols)
        canvas.paste(i, (c * (cell_w + gap), r * (cell_h + gap)), i)
    return canvas, cols, rows


def _grid_columns(n: int) -> int:
    """默认列数：取最接近 √n 的整数（网格排版惯例）。"""
    import math

    return max(1, min(constants.GRID_MAX, round(math.sqrt(n))))


def letterbox(img: Image.Image, w: int, h: int, bg: tuple[int, int, int, int]) -> Image.Image:
    """等比缩放并居中贴到 (w,h) 的画布上（不裁剪、不变形）。"""
    ratio = min(w / img.width, h / img.height)
    new = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), bg)
    canvas.paste(new, ((w - new.width) // 2, (h - new.height) // 2), new)
    return canvas


def guard_canvas(canvas: Image.Image) -> None:
    """产物尺寸硬校验：拼接最容易失控（20 张竖图拼起来能到几万像素）。"""
    if max(canvas.size) > constants.MAX_OUTPUT_EDGE or canvas.width * canvas.height > constants.MAX_PIXELS:
        raise ImageToolError(
            "OUTPUT_TOO_LARGE",
            f"拼接结果尺寸 {canvas.width}×{canvas.height} 超过上限"
            f"（单边 {constants.MAX_OUTPUT_EDGE:,}）。请减少图片数量或调小间距。",
            413,
            width=canvas.width,
            height=canvas.height,
        )


def clamp_gap(gap: Any) -> int:
    try:
        g = int(gap)
    except (TypeError, ValueError):
        raise ImageToolError("BAD_PARAM", f"间距参数非法：{gap!r}，应为 0~500 的整数", 400) from None
    if g < 0:
        return 0
    return min(g, 500)


def parse_color(value: Any) -> tuple[int, int, int, int]:
    """解析背景色，支持 `#RGB` / `#RRGGBB` / `rgb(r,g,b)`，非法则回退白色。"""
    if not isinstance(value, str) or not value.strip():
        return (255, 255, 255, 255)
    s = value.strip()
    try:
        if s.startswith("#"):
            h = s[1:]
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if s.lower().startswith("rgb"):
            nums = s[s.find("(") + 1 : s.find(")")].split(",")
            if len(nums) >= 3:
                return (int(nums[0]), int(nums[1]), int(nums[2]), 255)
    except (ValueError, IndexError):
        pass
    # 非法颜色不报错：背景色填错不至于让整个拼接失败，回退白色更符合直觉
    return (255, 255, 255, 255)
