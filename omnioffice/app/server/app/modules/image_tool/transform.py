"""能力④：图片编辑（缩放 / 旋转 / 裁剪 / 文字水印）。

可独立调用：
    from app.modules.image_tool.transform import transform_file
    transform_file(Path("a.png"), "resize", width=800)
    transform_file(Path("a.png"), "watermark", text="内部资料", position="bottom-right")

说明：
- 所有编辑都**等比或按指定值**，且不放大（scale>1 时放大是用户明确要的才做）；
- 裁剪采用「中心裁剪」或「按比例」，坐标越界会被夹到图内而不是报错；
- 水印用 Pillow 默认位图字体绘制（不依赖系统字体，避免镜像里字体缺失导致崩溃——
  Dockerfile 只装了 wqy-microhei，用它反而要处理字体路径）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import constants, imaging
from .errors import ImageToolError


@dataclass(frozen=True)
class TransformResult:
    data: bytes
    info: imaging.ImageInfo
    meta: dict[str, Any] = field(default_factory=dict)


def transform_file(
    src: Path,
    op: str,
    target_format: str | None = None,
    quality: int | None = None,
    width: int | None = None,
    height: int | None = None,
    angle: int = 0,
    crop_ratio: tuple[float, float] | None = None,
    text: str = "",
    position: str = "bottom-right",
    opacity: int = 50,
    font_size: int = 0,
) -> TransformResult:
    """对单张图片做一种编辑操作。

    不同 op 用到的参数不同，其余一律忽略（路由层已做参数校验）。
    """
    if op not in constants.TRANSFORM_OPS:
        raise ImageToolError(
            "BAD_PARAM",
            f"不支持的编辑操作：{op}。可用：{'、'.join(constants.TRANSFORM_OPS)}",
            400,
            allowed=list(constants.TRANSFORM_OPS),
        )

    with imaging.open_image(src) as img:
        original_size = img.size
        original_format = (img.format or "").upper()

        if op == "resize":
            out = _resize(img, width, height)
        elif op == "rotate":
            out = _rotate(img, angle)
        elif op == "crop":
            out = _crop(img, crop_ratio)
        else:
            out = _watermark(img, text, position, opacity, font_size)

        fmt = (target_format or original_format or constants.Format.PNG).upper()
        if fmt not in constants.OUTPUT_FORMATS:
            fmt = constants.Format.PNG
        data = imaging.encode(out, fmt, quality)
        info = imaging.ImageInfo(
            format=fmt,
            width=out.width,
            height=out.height,
            mode=out.mode,
            frames=1,
            has_alpha=fmt in constants.ALPHA_FORMATS,
            animated=False,
        )
        meta: dict[str, Any] = {
            "op": op,
            "targetFormat": fmt,
            "originalWidth": original_size[0],
            "originalHeight": original_size[1],
            "width": out.width,
            "height": out.height,
        }
        return TransformResult(data=data, info=info, meta=meta)


def _resize(img: Image.Image, width: int | None, height: int | None) -> Image.Image:
    w, h = img.size
    if not width and not height:
        raise ImageToolError("BAD_PARAM", "缩放需要提供目标宽度或高度", 400)
    tw = _positive(width) if width else None
    th = _positive(height) if height else None
    if tw and not th:
        th = max(1, round(h * tw / w))
    elif th and not tw:
        tw = max(1, round(w * th / h))
    # 都给时按 cover 语义填满目标框（可能裁掉边缘），而非拉伸变形
    if tw and th:
        ratio = max(tw / w, th / h)
        rs = (max(1, round(w * ratio)), max(1, round(h * ratio)))
        img = img.resize(rs, Image.LANCZOS)
        left = (rs[0] - tw) // 2
        top = (rs[1] - th) // 2
        return img.crop((left, top, left + tw, top + th))
    assert tw and th  # noqa: S101 —— 上分支已保证两者都有值
    return img.resize((tw, th), Image.LANCZOS)


def _rotate(img: Image.Image, angle: int) -> Image.Image:
    try:
        a = int(angle) % 360
    except (TypeError, ValueError):
        raise ImageToolError("BAD_PARAM", f"旋转角度非法：{angle!r}", 400) from None
    if a == 0:
        return img.copy()
    # 非 90 的倍角 → 扩展画布保留完整内容（expand=True），否则四角会被切掉
    if a in (90, 180, 270):
        return img.rotate(-a, expand=True)
    return img.rotate(-a, expand=True, resample=Image.BICUBIC, fillcolor=(255, 255, 255, 0))


def _crop(img: Image.Image, ratio: tuple[float, float] | None) -> Image.Image:
    w, h = img.size
    if not ratio:
        raise ImageToolError("BAD_PARAM", "裁剪需要提供裁剪比例（如 1:1 / 16:9）", 400)
    try:
        rw, rh = float(ratio[0]), float(ratio[1])
    except (TypeError, ValueError, IndexError):
        raise ImageToolError("BAD_PARAM", f"裁剪比例非法：{ratio!r}，格式如 16:9", 400) from None
    if rw <= 0 or rh <= 0:
        raise ImageToolError("BAD_PARAM", "裁剪比例必须大于 0", 400)

    # 以「覆盖目标比例」为准居中裁剪：短边为基准裁长边，保证不出现黑边
    target = rw / rh
    current = w / h
    if current > target:
        nw = max(1, round(h * target))
        left = (w - nw) // 2
        return img.crop((left, 0, left + nw, h))
    nh = max(1, round(w / target))
    top = (h - nh) // 2
    return img.crop((0, top, w, top + nh))


def _watermark(
    img: Image.Image, text: str, position: str, opacity: int, font_size: int
) -> Image.Image:
    text = (text or "").strip()
    if not text:
        raise ImageToolError("BAD_PARAM", "水印文字不能为空", 400)
    if position not in constants.WATERMARK_POSITIONS:
        position = "bottom-right"
    opacity = max(1, min(100, int(opacity or 50)))

    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    size = int(font_size) if font_size and int(font_size) > 0 else max(14, base.width // 25)
    size = max(10, min(size, 200))
    font = ImageFont.load_default(size)
    alpha = round(255 * opacity / 100)

    # 先描边再填充：浅底图上白字会看不见，描边保证任何底色都读得出
    draw.text(_anchor(base.size, text, font, position), text, font=font,
              fill=(255, 255, 255, alpha), anchor=_pil_anchor(position),
              stroke_width=max(1, size // 18), stroke_fill=(0, 0, 0, alpha))
    merged = Image.alpha_composite(base, overlay)
    return merged


def _anchor(
    size: tuple[int, int], text: str, font: ImageFont.ImageFont, position: str
) -> tuple[int, int]:
    """计算绘制起点（考虑文字实际宽高，避免出界或贴死边）。"""
    w, h = size
    try:
        left, top, right, bottom = font.getbbox(text)
        tw, th = right - left, bottom - top
    except (AttributeError, OSError):
        tw, th = len(text) * 8, 16
    margin = max(8, w // 40)
    hpos = "left" if "left" in position else ("right" if "right" in position else "center")
    vpos = "top" if "top" in position else ("bottom" if "bottom" in position else "middle")
    x = margin if hpos == "left" else (w - margin - tw if hpos == "right" else (w - tw) // 2)
    y = margin if vpos == "top" else (h - margin - th if vpos == "bottom" else (h - th) // 2)
    return max(0, x), max(0, y)


def _pil_anchor(position: str) -> str:
    hpos = "l" if "left" in position else ("r" if "right" in position else "m")
    vpos = "t" if "top" in position else ("b" if "bottom" in position else "m")
    return hpos + vpos


def _positive(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ImageToolError("BAD_PARAM", f"尺寸参数非法：{v!r}，应为正整数", 400) from None
    if n <= 0:
        raise ImageToolError("BAD_PARAM", f"尺寸必须大于 0，当前 {n}", 400)
    return min(n, constants.MAX_OUTPUT_EDGE)
