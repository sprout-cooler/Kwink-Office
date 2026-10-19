"""Pillow 底层封装：安全解码、元数据、编码保存、色彩模式归一。

**本文件是唯一允许 import PIL 的地方**（除 ocr.py 的 base64 读字节外）。
上层能力文件只调用这里暴露的函数，不直接触碰 Pillow API ——
这样做的收益：① 像素炸弹防护只需实现一次；② JPEG 不支持 alpha 这类
「格式能力差异」集中在一处处理，不必散落到每个能力里。
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFile, ImageOps

from . import constants
from .errors import ImageToolError

# Pillow 默认对超长图直接抛 DecompressionBombError；对「略超」的情况抛 Warning。
# 这里把 Warning 也升格为 Error，避免解码一个 1.2 亿像素的畸形文件把内存吃光
# 之后才在别处崩掉 —— 那时报错现场早已丢失，极难定位。
Image.MAX_IMAGE_PIXELS = constants.MAX_PIXELS
ImageFile.LOAD_TRUNCATED_IMAGES = False


@dataclass(frozen=True)
class ImageInfo:
    """一张图片的关键元信息（列表展示与处理后回报共用）。"""

    format: str
    width: int
    height: int
    mode: str
    frames: int
    has_alpha: bool
    animated: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "label": constants.format_label(self.format),
            "width": self.width,
            "height": self.height,
            "mode": self.mode,
            "frames": self.frames,
            "hasAlpha": self.has_alpha,
            "animated": self.animated,
            "pixels": self.width * self.height,
        }


def open_image(path: Path) -> Image.Image:
    """安全打开图片（自动纠正 EXIF 方向、拒绝超大图与畸形文件）。

    `ImageOps.exif_transpose` 必须调：手机拍的照片横竖信息存在 EXIF 里，
    不纠正的话用户转个格式就会发现「图躺下了」——这是格式转换最常见的投诉。
    """
    try:
        with Image.open(path) as probe:
            probe.verify()  # 先验结构，再真正解码（verify 后对象不可用）
    except Image.DecompressionBombError:
        raise ImageToolError(
            "IMAGE_TOO_LARGE",
            f"图片像素数超出安全上限（{constants.MAX_PIXELS:,}）。请先缩小图片。",
            413,
        ) from None
    except Image.DecompressionBombWarning as e:  # 略超上限的警告也拦下
        raise ImageToolError(
            "IMAGE_TOO_LARGE",
            f"图片像素数接近安全上限（{constants.MAX_PIXELS:,}）。请先缩小图片。",
            413,
        ) from None
    except (OSError, SyntaxError, ValueError) as e:
        # 原始异常只进日志（排障用），用户看到的是中文可行动提示
        print(
            f"[image_tool] 解码校验失败 {path}: {type(e).__name__}: {e}",
            flush=True,
        )
        raise ImageToolError(
            "DECODE_FAILED",
            "无法解码这张图片：文件可能已损坏，或实际格式与扩展名不符"
            "（例如把 .jpg 改成了 .png）。请确认文件能正常打开后重试。",
            400,
        ) from None

    try:
        img = Image.open(path)
    except Exception as e:  # noqa: BLE001 —— Pillow 各格式异常类型不统一，统一兜住
        print(f"[image_tool] 打开失败 {path}: {type(e).__name__}: {e}", flush=True)
        raise ImageToolError(
            "DECODE_FAILED",
            "无法打开这张图片：文件可能已损坏或不是有效的图片。",
            400,
        ) from None

    img = ImageOps.exif_transpose(img) or img
    _guard_size(img)
    fmt = (img.format or "").upper()
    if fmt and fmt not in constants.ALLOWED_INPUT_FORMATS:
        #  Pillow 可能支持本模块没开放的格式（如 ICO/PPM），显式拒绝而非静默放行
        raise ImageToolError(
            "UNSUPPORTED_FORMAT",
            f"暂不支持该格式：{constants.format_label(fmt)}。"
            f"当前支持：{'、'.join(constants.format_label(f) for f in constants.ALLOWED_INPUT_FORMATS)}",
            400,
            allowed=list(constants.ALLOWED_INPUT_FORMATS),
        )
    return img


def _guard_size(img: Image.Image) -> None:
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ImageToolError("DECODE_FAILED", "图片尺寸异常（宽或高为 0）", 400)
    if w > constants.MAX_EDGE or h > constants.MAX_EDGE:
        raise ImageToolError(
            "IMAGE_TOO_LARGE",
            f"图片单边尺寸 {max(w, h):,} 超过上限 {constants.MAX_EDGE:,}。请先缩小图片。",
            413,
        )
    if w * h > constants.MAX_PIXELS:
        raise ImageToolError(
            "IMAGE_TOO_LARGE",
            f"图片像素数 {w * h:,} 超过上限 {constants.MAX_PIXELS:,}。请先缩小图片。",
            413,
        )


def probe(path: Path) -> ImageInfo:
    """只读元信息不解码整图（图库列表用，避免一次请求解码几十张大图）。"""
    try:
        with Image.open(path) as img:
            fmt = (img.format or "").upper()
            frames = getattr(img, "n_frames", 1)
            return ImageInfo(
                format=fmt,
                width=img.width,
                height=img.height,
                mode=img.mode,
                frames=int(frames),
                has_alpha=mode_has_alpha(img.mode),
                animated=frames > 1 and fmt in constants.ANIMATED_FORMATS,
            )
    except ImageToolError:
        raise
    except Exception as e:  # noqa: BLE001
        # 只在开发/日志里带上原始类型名，**不**把它塞进给用户看的 message：
        # UnidentifiedImageError 这类词对用户毫无意义，还会让人以为是应用坏了。
        print(
            f"[image_tool] probe 失败 {path}: {type(e).__name__}: {e}",
            flush=True,
        )
        raise ImageToolError(
            "DECODE_FAILED",
            "无法读取这张图片：文件已损坏，或实际格式与扩展名不符"
            "（例如把 .jpg 改成了 .png）。请确认文件能正常打开后重试。",
            400,
        ) from None


def mode_has_alpha(mode: str) -> bool:
    return mode in ("RGBA", "LA", "PA") or "transparency" in mode


def normalize_mode(img: Image.Image, target_format: str) -> Image.Image:
    """把图像色彩模式调整到目标格式能接受的样子。

    必须做这一步，否则 Pillow 抛的 `cannot write mode RGBA as JPEG` /
    `cannot write mode P as WEBP` 是用户完全看不懂的原始异常（避坑指南：错误文案用户化）。
    """
    fmt = target_format.upper()

    if fmt == constants.Format.JPEG:
        # JPEG 无 alpha：先合成到纯色背景再转 RGB。
        # 直接 convert("RGB") 会把透明像素压成黑色，导出白底文档时出现黑块。
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.mode:
            img = _flatten(img, (255, 255, 255))
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img

    if fmt == constants.Format.GIF:
        # GIF 只支持 256 色（P 模式）。RGBA 必须先合成背景色再量化。
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.mode:
            img = _flatten(img, (255, 255, 255))
        if img.mode != "P":
            img = img.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256)
        return img

    if fmt == constants.Format.BMP:
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.mode:
            img = _flatten(img, (255, 255, 255))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img

    # PNG / WEBP / TIFF 均可承载 RGB、RGBA、L、P
    if img.mode in ("RGBA", "LA", "P"):
        # P 模式若带 transparency，转 RGBA 才能保住透明；不带则留在 P（更省体积）
        if img.mode == "P" and "transparency" not in img.mode:
            return img
        return img.convert("RGBA") if img.mode != "RGBA" else img
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGBA" if mode_has_alpha(img.mode) else "RGB")
    return img


def _flatten(img: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """把带透明通道的图合成到纯色背景上。"""
    rgba = img.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, background)
    canvas.paste(rgba, mask=rgba.split()[-1])
    return canvas


def encode(img: Image.Image, fmt: str, quality: int | None = None) -> bytes:
    """按目标格式编码为字节流。

    quality 只对 JPEG/WEBP 有意义；PNG 用 compress_level 表达压缩强度
    （Pillow 的 quality 对 PNG 无效，传了也白传 —— 用户调滑块却发现体积不变，
    这正是需要显式区分的地方）。
    """
    fmt = fmt.upper()
    buf = io.BytesIO()
    prepared = normalize_mode(img, fmt)
    q = clamp_quality(quality)

    params: dict[str, Any] = {}
    if fmt in (constants.Format.JPEG, constants.Format.WEBP):
        params["quality"] = q
        if fmt == constants.Format.JPEG:
            # subsampling=0 保画质（体积换清晰度）；用户要小体积时用 compress 里的
            # keep_exif=False + 更高 quality 调节，而不是这里偷偷降采样。
            params["subsampling"] = 0
            params["optimize"] = True
        else:
            params["method"] = 4  # 0~6，越大压得越狠越慢；4 是质量/速度平衡点
    elif fmt == constants.Format.PNG:
        # quality 1~100 映射到 compress_level 9~1（反向：质量数字越大 = 压得越狠）
        level = 9 - round((q - constants.QUALITY_MIN) / (constants.QUALITY_MAX - constants.QUALITY_MIN) * 8)
        params["compress_level"] = max(1, min(9, level))
    elif fmt == constants.Format.GIF:
        params["optimize"] = True

    try:
        prepared.save(buf, format=fmt, **params)
    except (OSError, ValueError) as e:
        raise ImageToolError(
            "ENCODE_FAILED",
            f"保存为 {constants.format_label(fmt)} 失败：{type(e).__name__}: {e}",
            500,
        ) from None
    return buf.getvalue()


def clamp_quality(quality: int | None) -> int:
    if quality is None:
        return constants.QUALITY_DEFAULT
    try:
        q = int(quality)
    except (TypeError, ValueError):
        raise ImageToolError("BAD_PARAM", f"质量参数非法：{quality!r}，应为 {constants.QUALITY_MIN}~{constants.QUALITY_MAX} 的整数", 400) from None
    return max(constants.QUALITY_MIN, min(constants.QUALITY_MAX, q))


def guess_format(path: Path, fallback: str = constants.Format.PNG) -> str:
    """按后缀猜格式（仅在探测失败时兜底，不作为主要判据）。"""
    suffix = path.suffix.lower().lstrip(".")
    mapping = {
        "png": constants.Format.PNG, "jpg": constants.Format.JPEG, "jpeg": constants.Format.JPEG,
        "webp": constants.Format.WEBP, "gif": constants.Format.GIF,
        "bmp": constants.Format.BMP, "tiff": constants.Format.TIFF, "tif": constants.Format.TIFF,
    }
    return mapping.get(suffix, fallback)


def fit_within(img: Image.Image, max_edge: int) -> Image.Image:
    """等比缩小到单边不超过 max_edge（不放大）。"""
    w, h = img.size
    if max(w, h) <= max_edge:
        return img
    ratio = max_edge / max(w, h)
    return img.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)
