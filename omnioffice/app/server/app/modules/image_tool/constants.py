"""图片处理模块常量（单一事实来源）。

前端的能力清单接口直接吐这里的结构，因此**新增格式只需改本文件**，
前端下拉与后端校验自动同步，不存在两处各维护一份导致漏改的问题
（与 settings_service.QWEN_MODELS 同源思路）。
"""
from __future__ import annotations

# 模块 id：用于 AI 模块级覆盖（settings_service 的 ai.{module}.*）与前端注册表
MODULE_ID = "image_tool"


class Format:
    """支持的图片格式（Pillow format 名 → 落盘后缀 / MIME）。"""

    PNG = "PNG"
    JPEG = "JPEG"
    WEBP = "WEBP"
    GIF = "GIF"
    BMP = "BMP"
    TIFF = "TIFF"


#: 可作为**输出**的格式。输入另算（见 ALLOWED_INPUT_FORMATS），
#: 因为 TIFF/BMP 只作为兼容输入，不鼓励当交付格式。
OUTPUT_FORMATS: dict[str, str] = {
    Format.PNG: "png",
    Format.JPEG: "jpg",
    Format.WEBP: "webp",
    Format.GIF: "gif",
    Format.BMP: "bmp",
    Format.TIFF: "tiff",
}

#: 可作为**输入**的格式：多加了 TIFF（扫描件/印刷稿常见）与 BMP。
ALLOWED_INPUT_FORMATS: tuple[str, ...] = (
    Format.PNG,
    Format.JPEG,
    Format.WEBP,
    Format.GIF,
    Format.BMP,
    Format.TIFF,
)

#: 格式 → MIME。存库与回显时用，避免每次散落硬编码字符串。
MIME_BY_FORMAT: dict[str, str] = {
    Format.PNG: "image/png",
    Format.JPEG: "image/jpeg",
    Format.WEBP: "image/webp",
    Format.GIF: "image/gif",
    Format.BMP: "image/bmp",
    Format.TIFF: "image/tiff",
}

#: 支持透明通道的格式。JPEG/BMP 无 alpha，转出这两者时必须先合成背景色，
#: 否则 Pillow 直接抛 "cannot write mode RGBA as JPEG"（用户看不懂的原始异常）。
ALPHA_FORMATS: frozenset[str] = frozenset({Format.PNG, Format.WEBP, Format.GIF, Format.TIFF})

#: 动图格式：GIF 支持多帧，转换/压缩时保留帧数而非只取首帧。
ANIMATED_FORMATS: frozenset[str] = frozenset({Format.GIF, Format.WEBP})

# ---- 质量参数 ----------------------------------------------------------------
# JPEG/WEBP 的 quality 取值范围（Pillow 语义）。前端滑块与后端校验共用。
QUALITY_MIN = 1
QUALITY_MAX = 100
QUALITY_DEFAULT = 85

#: 无损优化开关：只改容器不重编码像素，体积可能不变，收益有限故默认关闭。
LOSSLESS_SUPPORTED: frozenset[str] = frozenset({Format.PNG, Format.WEBP, Format.GIF, Format.TIFF})

# ---- 压缩 --------------------------------------------------------------------
#: 目标体积下限（字节）。低于 1KB 的目标对任何真实图片都不可能达成，
#: 与其让二分搜索空转 12 轮，不如直接判定不可达并给出可行动提示。
TARGET_SIZE_MIN = 1024
#: 二分搜索最大轮数。8 轮精度已到体积的 0.4%，再多纯属浪费 CPU。
COMPRESS_BSEARCH_STEPS = 8
#: 命中目标体积后允许的余量（2%）：JPEG 量化档位是离散的，
#: 要求「精确等于目标」会导致永远命中不了，只能无限降低画质。
TARGET_TOLERANCE_RATIO = 0.02
#: 压缩后反而变大的容差：PNG 转 JPEG 等场景下低画质可能比原图还大，
#: 超过这个比例就判定「压不动了」，如实回报而不是给用户一个更大的文件。
NO_GAIN_TOLERANCE_RATIO = 1.02

# ---- 拼接 --------------------------------------------------------------------
STITCH_MODES: tuple[str, ...] = ("horizontal", "vertical", "grid")
#: 网格拼接单边最多几张（cols 或 rows）。再大容易触发 Pillow 的尺寸上限。
GRID_MAX = 20

# ---- 通用限制 ----------------------------------------------------------------
#: 像素炸弹防护：超过此像素数直接拒收。1.5 亿像素约等于 15000×10000，
#: 远超 NAS 常规图片，又不至于误伤正常长图。
MAX_PIXELS = 150_000_000
#: 单边像素上限（Pillow 解码时的硬限制，防止 1×1.5 亿的畸形图耗尽内存）。
MAX_EDGE = 30_000
#: 输出尺寸硬上限：拼接与压缩的产物不得超过此边长。
MAX_OUTPUT_EDGE = 20_000

# ---- 编辑 --------------------------------------------------------------------
TRANSFORM_OPS: tuple[str, ...] = ("resize", "rotate", "crop", "watermark")
WATERMARK_POSITIONS: tuple[str, ...] = (
    "top-left", "top", "top-right", "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
)


def format_label(fmt: str) -> str:
    """面向用户的中文格式名（错误提示与前端展示共用）。"""
    return {
        Format.PNG: "PNG",
        Format.JPEG: "JPEG",
        Format.WEBP: "WebP",
        Format.GIF: "GIF",
        Format.BMP: "BMP",
        Format.TIFF: "TIFF",
    }.get(fmt.upper(), fmt.upper())


def capabilities() -> dict:
    """能力清单：前端表单（格式下拉、质量滑块范围、拼接方式）由此驱动。

    刻意不硬编码在前端 —— 新增一种格式时前端零改动。
    """
    return {
        "inputFormats": [
            {"id": f, "label": format_label(f), "mime": MIME_BY_FORMAT[f], "alpha": f in ALPHA_FORMATS}
            for f in ALLOWED_INPUT_FORMATS
        ],
        "outputFormats": [
            {"id": f, "label": format_label(f), "mime": MIME_BY_FORMAT[f], "alpha": f in ALPHA_FORMATS}
            for f in OUTPUT_FORMATS
        ],
        "quality": {"min": QUALITY_MIN, "max": QUALITY_MAX, "default": QUALITY_DEFAULT},
        "stitchModes": [
            {"id": "horizontal", "label": "水平拼接（左右）"},
            {"id": "vertical", "label": "垂直拼接（上下）"},
            {"id": "grid", "label": "网格拼接"},
        ],
        "transformOps": [
            {"id": "resize", "label": "缩放"},
            {"id": "rotate", "label": "旋转"},
            {"id": "crop", "label": "裁剪"},
            {"id": "watermark", "label": "文字水印"},
        ],
        "watermarkPositions": list(WATERMARK_POSITIONS),
        "limits": {
            "maxPixels": MAX_PIXELS,
            "maxEdge": MAX_EDGE,
            "maxOutputEdge": MAX_OUTPUT_EDGE,
            "gridMax": GRID_MAX,
            "targetSizeMin": TARGET_SIZE_MIN,
        },
    }
