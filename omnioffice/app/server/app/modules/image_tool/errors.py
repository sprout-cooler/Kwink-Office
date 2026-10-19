"""图片处理模块统一异常。

设计原则：**业务代码只抛 ImageToolError，绝不直接抛 HTTPException**。
这样做的收益：
1. 能力文件（convert/stitch/compress/transform/ocr）可以脱离 FastAPI 独立调用
   —— 它们只依赖本模块的 errors + constants，不依赖 web 框架；
2. 错误文案只在一处构造，路由层统一翻译成 HTTP 响应，不会出现
   「有的路径 400、有的路径 500」的不一致；
3. 每个错误码都带**可行动的中文提示**（用户下一步该做什么），而不是
   Pillow 的原始英文异常 —— 与项目「错误文案用户化」的要求一致。
"""
from __future__ import annotations

from typing import Any


class ImageToolError(RuntimeError):
    """图片处理可预期的业务错误。

    Attributes:
        code: 稳定的机器可读错误码，前端可据此做分支（如引导去配置 AI Key）。
        status: 建议的 HTTP 状态码。
        detail: 附加结构化信息（会原样放进响应体 detail 内）。
    """

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        **detail: Any,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail

    def to_payload(self) -> dict[str, Any]:
        """转成与全项目一致的响应体：{"detail": {"error", "message", ...}}。"""
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        payload.update(self.detail)
        return {"detail": payload}


# ---- 构造器：让调用处读起来像一句话，而不是一堆关键字参数 -------------------


def unsupported_format(fmt: str, allowed: tuple[str, ...] | list[str]) -> ImageToolError:
    return ImageToolError(
        "UNSUPPORTED_FORMAT",
        f"不支持的图片格式：{fmt or '未知'}。可用格式：{'、'.join(allowed)}",
        400,
        allowed=list(allowed),
    )


def decode_failed(reason: str) -> ImageToolError:
    return ImageToolError(
        "DECODE_FAILED",
        f"图片无法解码：{reason}。文件可能已损坏，或不是有效的图片。",
        400,
    )


def too_large(pixels: int, limit: int) -> ImageToolError:
    return ImageToolError(
        "IMAGE_TOO_LARGE",
        f"图片像素数 {pixels:,} 超过上限 {limit:,}。请先缩小图片后再上传。",
        413,
        pixels=pixels,
        limit=limit,
    )


def bad_param(name: str, reason: str) -> ImageToolError:
    return ImageToolError("BAD_PARAM", f"参数 {name} 不合法：{reason}", 400, param=name)


def asset_not_found(asset_id: int) -> ImageToolError:
    """越权与不存在返回**同一个错误**（404 NOT_FOUND）。

    刻意不区分「存在但不属于你」与「根本不存在」：前者若给 403，
    等于向调用者泄露「该 id 确实存在」，属于信息泄露（避坑指南 §3.1 信任链红线）。
    """
    return ImageToolError("NOT_FOUND", f"图片不存在：{asset_id}", 404, id=asset_id)


def file_gone(asset_id: int) -> ImageToolError:
    return ImageToolError(
        "FILE_GONE",
        f"图片文件已丢失（记录仍在，磁盘上找不到）：{asset_id}。"
        f"通常是数据目录被外部清理所致，请重新上传该图片。",
        410,
        id=asset_id,
    )


def no_images() -> ImageToolError:
    return ImageToolError("NO_IMAGE", "请先选择至少一张图片", 400)


def ai_not_configured() -> ImageToolError:
    return ImageToolError(
        "AI_NOT_CONFIGURED",
        "未配置大模型 API，无法执行图片 OCR。请在「设置 → AI 模型」中填写"
        "服务地址、API Key 与模型（可单独为图片处理模块指定 qwen3.5-ocr）。",
        400,
    )


def ocr_failed(reason: str) -> ImageToolError:
    return ImageToolError("OCR_FAILED", f"图片文字识别失败：{reason}", 502, reason=reason)
