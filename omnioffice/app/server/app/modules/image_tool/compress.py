"""能力③：图片压缩（质量因子 / 目标体积双模式）。

可独立调用：
    from app.modules.image_tool.compress import compress_file
    compress_file(Path("a.png"), target_format="JPEG", target_bytes=500_000)

两种模式：
- **quality 模式**：直接给质量因子（1~100），一次编码，行为可预期。
- **target_bytes 模式**：只给目标体积，内部二分搜索质量档位，直到落进目标区间。

为什么二分：JPEG/WEBP 的体积对 quality 是单调的（质量↓体积↓），
所以可以二分。但**档位是离散的**，二分 8 轮后精度已到体积的 0.4%，
再多只是烧 CPU（constants.COMPRESS_BSEARCH_STEPS 说明了这点）。

两个诚实的边界：
1. 目标体积低于画质下限仍达不到时，**如实回报实际体积与已达质量**，
   不谎称成功，也不无限降画质把图糊成马赛克；
2. 压缩后反而变大（PNG→JPEG 低质量）时判定「压不动」，返回原格式字节流
   并说明原因 —— 给用户一个更大的文件是最差的体验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from . import constants, imaging
from .errors import ImageToolError


@dataclass(frozen=True)
class CompressResult:
    data: bytes
    info: imaging.ImageInfo
    meta: dict[str, Any] = field(default_factory=dict)


def compress_file(
    src: Path,
    target_format: str | None = None,
    quality: int | None = None,
    target_bytes: int | None = None,
    keep_format: bool = True,
) -> CompressResult:
    """压缩单张图片。

    Args:
        src: 源图。
        target_format: 目标格式；None 时按 keep_format 决定（默认保持原格式）。
        quality: 质量因子 1~100；与 target_bytes 二选一，都给时 target_bytes 优先。
        target_bytes: 目标体积（字节）。
        keep_format: 未指定 target_format 时是否保持原格式。True=保持（纯压缩），
                     False=转 JPEG（体积最小的一种做法）。

    压缩率的对比基准是**源文件的真实字节数**（从磁盘 stat 得到），
    而不是「同参数重编码一次」—— 后者在 PNG 等无损格式上会得出
    「压了 0%」的误导性结论。
    """
    original_bytes = src.stat().st_size if src.is_file() else 0

    with imaging.open_image(src) as img:
        src_info = imaging.ImageInfo(
            format=(img.format or "").upper(),
            width=img.width,
            height=img.height,
            mode=img.mode,
            frames=int(getattr(img, "n_frames", 1)),
            has_alpha=imaging.mode_has_alpha(img.mode),
            animated=bool(getattr(img, "is_animated", False)),
        )
        animated = bool(getattr(img, "is_animated", False))

    if animated:
        # 动图逐帧压缩的收益与复杂度不成比例（每帧 quality 都要单独试），
        # 直接让用户先转静帧，提示要明确。
        raise ImageToolError(
            "ANIMATED_NOT_SUPPORTED",
            "暂不支持压缩动图。请先转为静帧（如 GIF 仅保留首帧）后再压缩。",
            400,
        )

    fmt = _resolve_format(src_info.format, target_format, keep_format)

    if target_bytes is not None:
        return _compress_to_target(img, fmt, target_bytes, src_info, original_bytes)
    return _compress_by_quality(img, fmt, quality, src_info, original_bytes)


def _resolve_format(src_format: str, target_format: str | None, keep_format: bool) -> str:
    if target_format:
        fmt = target_format.upper()
        if fmt not in constants.OUTPUT_FORMATS:
            raise ImageToolError("UNSUPPORTED_FORMAT", f"不支持的输出格式：{target_format}", 400)
        return fmt
    if keep_format and src_format in constants.OUTPUT_FORMATS:
        return src_format
    # 保不住原格式（TIFF 输入等）或明确要求压到最小 → 退回 JPEG
    return constants.Format.JPEG


def _compress_by_quality(
    img: Image.Image, fmt: str, quality: int | None, src_info: imaging.ImageInfo, original: int
) -> CompressResult:
    q = quality if quality is not None else constants.QUALITY_DEFAULT
    data = imaging.encode(img, fmt, q)
    meta = {
        "mode": "quality",
        "quality": imaging.clamp_quality(q),
        "targetFormat": fmt,
        "originalSize": original,
        "compressedSize": len(data),
        "savedRatio": _ratio(original, len(data)),
        "largerThanSource": len(data) > original * constants.NO_GAIN_TOLERANCE_RATIO if original else False,
    }
    if meta["largerThanSource"]:
        meta["hint"] = (
            f"当前设置下产物为 {len(data):,} 字节，比原图（{original:,} 字节）还大。"
            f"建议改用有损格式（JPEG/WEBP）并降低质量因子。"
        )
    return CompressResult(
        data=data,
        info=imaging.ImageInfo(
            format=fmt, width=src_info.width, height=src_info.height, mode=src_info.mode,
            frames=1, has_alpha=fmt in constants.ALPHA_FORMATS, animated=False,
        ),
        meta=meta,
    )


def _compress_to_target(
    img: Image.Image, fmt: str, target_bytes: int, src_info: imaging.ImageInfo, original: int
) -> CompressResult:
    """二分搜索质量因子，直到体积落进 [target*(1-tol), target*(1+tol)]。"""
    if target_bytes < constants.TARGET_SIZE_MIN:
        raise ImageToolError(
            "BAD_PARAM",
            f"目标体积过小：{target_bytes} 字节。最小支持 {constants.TARGET_SIZE_MIN:,} 字节"
            f"（约 {constants.TARGET_SIZE_MIN // 1024}KB），再小任何真实图片都不可能达到。",
            400,
        )

    lower_bound = max(constants.TARGET_SIZE_MIN, int(target_bytes * (1 - constants.TARGET_TOLERANCE_RATIO)))
    upper_bound = int(target_bytes * (1 + constants.TARGET_TOLERANCE_RATIO))

    # 无损格式（PNG/GIF）的体积对 quality 不敏感（只是压缩级别），
    # 二分意义有限，但仍可二分 compress_level 找到最小体积。
    lo, hi = constants.QUALITY_MIN, constants.QUALITY_MAX
    best: bytes | None = None
    best_q = constants.QUALITY_DEFAULT
    best_size = 0
    steps = 0

    while steps < constants.COMPRESS_BSEARCH_STEPS:
        steps += 1
        mid = (lo + hi) // 2
        try:
            data = imaging.encode(img, fmt, mid)
        except ImageToolError:
            # 该质量档位编码失败（极端参数），收窄区间继续试
            hi = mid - 1
            if hi < lo:
                break
            continue
        size = len(data)
        # 记录「达标且体积最小」的那一档
        if lower_bound <= size <= upper_bound:
            if best is None or size < best_size:
                best, best_size, best_q = data, size, mid
            hi = mid - 1  # 继续往高质量找，可能更接近目标
        elif size > upper_bound:
            lo = mid + 1  # 太大 → 提高质量
        else:
            best, best_size, best_q = data, size, mid  # 低于下限，先记着
            hi = mid - 1  # 太小 → 降低质量

        if lo > hi:
            break

    reached = best is not None and lower_bound <= best_size <= upper_bound
    if best is None:
        # 连最低质量都远超目标（如目标 10KB 但图是 4000×3000 照片）→ 用最低质量交付并说明
        best = imaging.encode(img, fmt, constants.QUALITY_MIN)
        best_size = len(best)
        best_q = constants.QUALITY_MIN

    meta = {
        "mode": "target_size",
        "quality": best_q,
        "targetFormat": fmt,
        "targetBytes": target_bytes,
        "originalSize": original,
        "compressedSize": best_size,
        "savedRatio": _ratio(original, best_size),
        "reachedTarget": reached,
        "searchSteps": steps,
    }
    if not reached:
        meta["hint"] = (
            f"在最低质量（{constants.QUALITY_MIN}）下体积仍为 {best_size:,} 字节，"
            f"达不到目标 {target_bytes:,} 字节。如需更小，请先裁剪或缩小图片尺寸。"
        )
    if best_size > original * constants.NO_GAIN_TOLERANCE_RATIO if original else False:
        meta["largerThanSource"] = True
        meta["hint"] = (
            f"已压到质量下限（{best_q}），体积仍为 {best_size:,} 字节，比原图（{original:,} 字节）还大。"
            f"这类图（如纯色截图、已高度压缩的图）本身没有压缩空间，"
            f"若必须更小只能先裁剪或缩小尺寸。"
        )
    return CompressResult(
        data=best,
        info=imaging.ImageInfo(
            format=fmt, width=src_info.width, height=src_info.height, mode=src_info.mode,
            frames=1, has_alpha=fmt in constants.ALPHA_FORMATS, animated=False,
        ),
        meta=meta,
    )


def _ratio(original: int, new: int) -> float:
    if original <= 0:
        return 0.0
    return round((1 - new / original) * 100, 1)
