"""识别服务抽象（V10 4.x：多模态大模型为主 + OCR 为辅）。

M2 阶段 T13（Key 提供方式）未定，先落地 StubRecognizer：上传后只落 pending 记录，
不产生 TaskItem。Key 与 Prompt v2 就绪后新增 VLMRecognizer 实现并由配置切换，
调用方（worker / API）零改动。
"""
from __future__ import annotations

from typing import Protocol


class Recognizer(Protocol):
    async def recognize(self, image_path: str) -> dict:
        """读取一张截图，返回结构化结果 {title,start_at,end_at,status,confidence,extra}。"""
        ...


class StubRecognizer:
    """占位实现：未配置 LLM_API_KEY 时使用，明确返回不可用，不伪造识别结果。"""

    available = False

    async def recognize(self, image_path: str) -> dict:
        raise RuntimeError("识别服务未配置：尚未提供大模型 API Key（T13 待确认）")
