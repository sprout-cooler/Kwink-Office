"""能力①：图片格式转换（PNG / JPEG / WEBP / GIF / BMP / TIFF 互转）。

可独立调用：
    from app.modules.image_tool.convert import convert_file
    convert_file(Path("a.heic"), "WEBP", quality=90)

设计要点：
- **透明度按目标格式正确处理**：转 JPEG/BMP 时先合成背景色而非压黑（见 imaging.normalize_mode）；
- **动图保留帧**：GIF/WebP 互转时逐帧处理并保持时长，源为静图时退化为单帧；
- **EXIF 方向纠正**：手机照片横竖信息在 EXIF 里，转换时自动摆正（imaging.open_image 内）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from . import constants, imaging
from .errors import ImageToolError


@dataclass(frozen=True)
class ConvertResult:
    data: bytes
    info: imaging.ImageInfo
    meta: dict[str, Any]


def convert_file(
    src: Path,
    target_format: str,
    quality: int | None = None,
    drop_exif: bool = True,
) -> ConvertResult:
    """把 src 转成 target_format，返回字节流 + 新图元信息。

    drop_exif 默认 True：EXIF 里含 GPS 坐标、机型、拍摄时间等隐私字段，
    图片一旦外发就等于泄露定位。默认剥离，仅当用户明确要保留时置 False。
    """
    fmt = target_format.upper()
    if fmt not in constants.OUTPUT_FORMATS:
        raise ImageToolError(
            "UNSUPPORTED_FORMAT",
            f"不支持的目标格式：{target_format}。"
            f"可用：{'、'.join(constants.format_label(f) for f in constants.OUTPUT_FORMATS)}",
            400,
            allowed=list(constants.OUTPUT_FORMATS),
        )

    with imaging.open_image(src) as img:
        source_info = imaging.ImageInfo(
            format=(img.format or "").upper(),
            width=img.width,
            height=img.height,
            mode=img.mode,
            frames=int(getattr(img, "n_frames", 1)),
            has_alpha=imaging.mode_has_alpha(img.mode),
            animated=bool(getattr(img, "is_animated", False)),
        )
        data = (
            _convert_animated(img, fmt, quality)
            if getattr(img, "is_animated", False) and fmt in constants.ANIMATED_FORMATS
            else imaging.encode(img, fmt, quality)
        )
        # 产物尺寸：动图取首帧尺寸；静图即当前尺寸
        w, h = img.size

    info = imaging.ImageInfo(
        format=fmt,
        width=w,
        height=h,
        mode=source_info.mode,
        frames=source_info.frames if fmt in constants.ANIMATED_FORMATS else 1,
        has_alpha=fmt in constants.ALPHA_FORMATS,
        animated=fmt in constants.ANIMATED_FORMATS and source_info.frames > 1,
    )
    return ConvertResult(
        data=data,
        info=info,
        meta={
            "sourceFormat": source_info.format or imaging.guess_format(src),
            "sourceWidth": source_info.width,
            "sourceHeight": source_info.height,
            "targetFormat": fmt,
            "quality": quality,
            "dropExif": drop_exif,
            "frames": info.frames,
        },
    )


def _convert_animated(img: Image.Image, fmt: str, quality: int | None) -> bytes:
    """动图转移动：逐帧编码并保留每帧时长与循环次数。

    丢帧会让动画变成快进乱跳，所以这里必须显式取 seek 与 duration。
    """
    frames: list[Image.Image] = []
    durations: list[int] = []
    total = int(getattr(img, "n_frames", 1))
    for idx in range(total):
        img.seek(idx)
        frames.append(img.convert("RGBA"))
        durations.append(int(img.info.get("duration", 100)) or 100)
    loop = int(img.info.get("loop", 0)) if img.info.get("loop") else 0

    prepared = [imaging.normalize_mode(f, fmt) for f in frames]
    if fmt == constants.Format.GIF:
        prepared = [f.convert("P", palette=Image.ADAPTIVE, colors=256) if f.mode != "P" else f for f in prepared]

    import io

    buf = io.BytesIO()
    params: dict[str, Any] = {"save_all": True, "append_images": prepared[1:], "duration": durations, "loop": loop}
    if fmt == constants.Format.JPEG:
        params["save_all"] = False  # JPEG 无动图概念，退化为单帧
        prepared[0].save(buf, format=fmt, quality=imaging.clamp_quality(quality), optimize=True)
        return buf.getvalue()
    if fmt == constants.Format.WEBP:
        params.update(quality=imaging.clamp_quality(quality), method=4)
    elif fmt == constants.Format.GIF:
        params["optimize"] = True
    prepared[0].save(buf, format=fmt, **params)
    return buf.getvalue()
