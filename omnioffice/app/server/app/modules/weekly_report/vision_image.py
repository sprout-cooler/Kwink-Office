"""发给 VLM 前的图片预处理（单一事实来源）。

背景（2026-11-17 实报 bug）：
- 本地 8GB 显存的 Ollama 默认上下文 4096；一张 1440x3136 的企微小结长截图
  被视觉编码器切成 8 个 tile，共需 4663 token → HTTP 400。
- 实测对照：**决定 token 的是像素总量（分辨率），不是内容裁剪**。
  只裁黑边（−3% 面积）token 几乎不变（4616）；缩放到宽 720 则降到约 2350，
  且 4 个指标全部识别正确（甚至缩到宽 400 仍正确）。
- 因此策略是「长边超阈值才等比缩放」，不做智能内容检测/裁剪：
  内容检测复杂且易误裁（状态栏/二维码），且裁剪会引入坐标偏移风险。

设计要点：
- 只在超过阈值时处理；小图**字节完全不变**（不重编码、不损失画质）。
- 透明通道（RGBA/LA/P）合成白底 —— 直接转 JPEG 会变黑底/报错。
- 保持原格式；JPEG 重新编码用高质量，避免二次压缩明显劣化。
- 不改变图片相对坐标（等比缩放），下游即使将来加 bounding box 也安全。
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

# 识别前图片长边上限。实测依据：1440x3136 长图需 4663 token（超 4096 报 400），
# 等比缩到长边 1536 后 token 降到约 3000，落在 4096 内且大字号/密集表格均识别正确。
# 取值保守（不盲目压到 720/400），给任务列表类密集小字留余量。
MAX_IMAGE_EDGE = 1536

# 重新编码质量：JPEG 用高质量，WebP 用高质量，PNG 无损。
_JPEG_QUALITY = 90
_WEBP_QUALITY = 90

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def mime_for(path: Path) -> str:
    """按扩展名推断 MIME（识别器与 OCR 共用，避免两处口径不一致）。"""
    return _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")


def prepare_image(path: Path, max_edge: int = MAX_IMAGE_EDGE) -> tuple[bytes, str]:
    """读取图片，必要时等比缩放，返回 (字节, mime)。

    - 长边 <= max_edge：直接返回原始字节（零损失、零开销）。
    - 超过：等比缩放到长边 = max_edge；透明模式合成白底；保持原格式。
    - max_edge <= 0 表示禁用缩放（保留原图），便于特殊场景绕开。
    """
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    mime = mime_for(path)
    # 只处理能无损保持「格式↔MIME」一致的常见格式；其他格式（gif/bmp/tif）
    # 原样返回，避免重编码成 PNG 但 MIME 仍报 image/gif 的错位。
    if max_edge <= 0 or suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        return raw, mime

    with Image.open(io.BytesIO(raw)) as im:
        if max(im.size) <= max_edge:
            return raw, mime

        w, h = im.size
        scale = max_edge / max(w, h)
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        # Low-res 模式让 PIL 在缩略图阶段就直接降采样，避免先全尺寸解码再缩。
        im.draft("RGB", new_size)
        out = im.resize(new_size, Image.LANCZOS)

        # 透明/带 alpha 的模式合成白底：直接 JPEG 编码会失败或变黑底。
        if out.mode in ("RGBA", "LA") or (out.mode == "P" and "transparency" in out.info):
            rgba = out.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            out = bg
        elif out.mode not in ("RGB", "L"):
            out = out.convert("RGB")

        buf = io.BytesIO()
        if suffix in (".jpg", ".jpeg"):
            out.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        elif suffix == ".webp":
            out.save(buf, format="WEBP", quality=_WEBP_QUALITY, method=4)
        else:
            out.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), mime
