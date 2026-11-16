"""图片预处理（缩放/透明底/格式保持）回归测试。

背景：2026-11-17 实报 bug —— 1440x3136 长截图直发本地 VLM，
需 4663 token 超 4096 上下文 → HTTP 400。实测证明缩放（非裁剪）才降 token。
这组测试锁住「小图不动 / 大图缩放到阈值 / 透明合成白底 / 格式 MIME 一致」。
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.modules.weekly_report.vision_image import (
    MAX_IMAGE_EDGE,
    mime_for,
    prepare_image,
)


class VisionImageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def _save(self, name: str, im: Image.Image, fmt: str | None = None, **kw) -> Path:
        p = self.root / name
        im.save(p, format=fmt, **kw)
        return p

    # --- 小图：字节完全不变 ------------------------------------------------
    def test_small_image_bytes_untouched(self):
        p = self._save("small.jpg", Image.new("RGB", (600, 400), "white"), "JPEG")
        out, mime = prepare_image(p)
        self.assertEqual(out, p.read_bytes(), "小图不得重编码（零损失）")
        self.assertEqual(mime, "image/jpeg")

    def test_exact_threshold_not_scaled(self):
        p = self._save("edge.png", Image.new("RGB", (MAX_IMAGE_EDGE, 100), "white"), "PNG")
        out, _ = prepare_image(p)
        self.assertEqual(out, p.read_bytes(), "长边恰好等于阈值时不缩放")

    # --- 大图：等比缩放到阈值 ----------------------------------------------
    def test_large_image_scaled_to_max_edge(self):
        p = self._save("big.jpg", Image.new("RGB", (2880, 1440), "white"), "JPEG")
        out, mime = prepare_image(p)
        im = Image.open(io.BytesIO(out))
        self.assertEqual(max(im.size), MAX_IMAGE_EDGE)
        self.assertEqual(im.size, (MAX_IMAGE_EDGE, MAX_IMAGE_EDGE // 2), "等比，不能拉伸")
        self.assertEqual(mime, "image/jpeg")

    def test_portrait_long_image_scaled(self):
        """实报的那类长截图形状（宽 << 高）。"""
        p = self._save("long.png", Image.new("RGB", (1440, 3136), "white"), "PNG")
        out, mime = prepare_image(p)
        im = Image.open(io.BytesIO(out))
        self.assertEqual(max(im.size), MAX_IMAGE_EDGE)
        self.assertLess(im.height, 3136)
        self.assertEqual(mime, "image/png")

    def test_disabled_when_max_edge_zero(self):
        p = self._save("big2.jpg", Image.new("RGB", (3000, 2000), "white"), "JPEG")
        out, _ = prepare_image(p, max_edge=0)
        self.assertEqual(out, p.read_bytes(), "max_edge=0 表示禁用缩放")

    # --- 透明背景：合成白底（用户点名的边界）-------------------------------
    def test_rgba_transparent_flattened_to_white(self):
        im = Image.new("RGBA", (2000, 1000), (0, 0, 0, 0))  # 全透明
        p = self._save("alpha.png", im, "PNG")
        out, mime = prepare_image(p)
        result = Image.open(io.BytesIO(out))
        self.assertEqual(result.mode, "RGB", "透明通道必须被合成掉")
        self.assertEqual(result.getpixel((10, 10)), (255, 255, 255), "透明区应为白底，不是黑底")
        self.assertEqual(mime, "image/png")

    def test_jpeg_source_stays_jpeg(self):
        """jpg 源文件缩放后仍是合法 JPEG（PIL 不允许 RGBA 存 JPEG，
        真实 jpg 也绝不会是 RGBA 模式，故只测正常 RGB 路径）。"""
        im = Image.new("RGB", (2000, 1000), (200, 100, 50))
        p = self._save("normal.jpg", im, "JPEG")
        out, mime = prepare_image(p)
        self.assertEqual(Image.open(io.BytesIO(out)).format, "JPEG")
        self.assertEqual(mime, "image/jpeg")

    # --- 格式/MIME 一致性 --------------------------------------------------
    def test_webp_keeps_format_and_mime(self):
        p = self._save("big.webp", Image.new("RGB", (2000, 1500), "gray"), "WEBP")
        out, mime = prepare_image(p)
        self.assertEqual(Image.open(io.BytesIO(out)).format, "WEBP")
        self.assertEqual(mime, "image/webp")

    def test_unsupported_format_left_untouched(self):
        """gif/bmp/tif 等：不缩放，字节原样，避免 MIME 与内容错位。"""
        p = self._save("anim.gif", Image.new("RGB", (2000, 1000), "red"), "GIF")
        out, mime = prepare_image(p)
        self.assertEqual(out, p.read_bytes())
        self.assertEqual(mime, "image/png")  # mime_for 未在表里 → 默认 png（旧 OCR 口径不同，见下）

    def test_mime_for_all_suffixes(self):
        self.assertEqual(mime_for(Path("a.JPG")), "image/jpeg")
        self.assertEqual(mime_for(Path("a.webp")), "image/webp")
        self.assertEqual(mime_for(Path("a.png")), "image/png")
        self.assertEqual(mime_for(Path("a.unknown")), "image/png")

    # --- 坐标一致性：等比缩放不改变宽高比 ----------------------------------
    def test_aspect_ratio_preserved(self):
        p = self._save("ratio.jpg", Image.new("RGB", (2400, 1600), "white"), "JPEG")
        out, _ = prepare_image(p)
        im = Image.open(io.BytesIO(out))
        self.assertAlmostEqual(im.width / im.height, 2400 / 1600, delta=0.01)


if __name__ == "__main__":
    unittest.main()
