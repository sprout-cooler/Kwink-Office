"""能力⑤：图片 OCR（文字提取 + 位置信息）。

**为什么复用 VLM 通道而不是引入 tesseract/PaddleOCR**：
1. 项目已有 OpenAI-compatible 识别链，且百炼 `qwen3.5-ocr` 就是文字提取专项模型，
   复用后 OCR 能力零新增依赖、零新增镜像体积；
2. 通过 `settings_service.resolve_ai(db, "image_tool", owner=owner)` 取配置，
   自动获得「模块级 AI 覆盖 + 按账号隔离」——用户在设置页可为图片模块
   单独指定模型，与周报模块互不影响（踩坑 K9 的反面：不省略 owner）；
3. tesseract 需 apt + 中文语言包，NAS 离线构建风险高，收益不匹配。

**返回结构**：整图纯文本 + 每行/每块文字的归一化坐标（0~1），
坐标是 VLM 依据像素估读的近似值，前端用于「点文字高亮原文位置」，
不追求像素级精确 —— 文档中如实说明，不假装是几何引擎的精确框。

可独立调用：
    from app.modules.image_tool.ocr import ocr_path
    ocr_path(Path("a.png"), owner="1000")
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib import request as urlreq

from ...core.settings_service import ensure_url_scheme
from .errors import ImageToolError, ai_not_configured, ocr_failed

MODULE_ID = "image_tool"
TIMEOUT_S = 90
MAX_TOKENS = 3000

OCR_PROMPT = """你是图片文字提取助手。请提取图中所有文字，只输出一个 JSON 对象。

输出格式：
{
  "text": "整图文字，按从上到下、从左到右顺序拼接的完整纯文本",
  "blocks": [
    {
      "text": "这一块/这一行的文字原文",
      "box": [左, 上, 右, 下],
      "confidence": 0.0
    }
  ]
}

要求：
1. 只输出 JSON，不要任何解释文字；
2. box 是该块文字在图中的位置，用 0~1000 的整数表示（相对整图的千分比，
   左上角为 [0,0]，右下角为 [1000,1000]），不要用像素值；
3. 按阅读顺序排列 blocks（从上到下，同一行从左到右）；
4. 图中无文字时返回 {"text": "", "blocks": []}；
5. 表格、截图、证件、票据等一律按可见文字照抄，不要改写、概括或补全；
6. 模糊或被遮挡导致读不出的部分，用「□」占位，不要猜测；
7. confidence 为识别置信度 0~1，模糊时如实降低。
"""


def ocr_path(path: Path, owner: str = "") -> dict[str, Any]:
    """识别单张图片，返回 {text, blocks, meta}。

    owner 是数据归属键：必须显式传入，否则多账号下会串用别人的 AI Key
    （踩坑 K9）。上层 service 已在每个入口强制传 owner。
    """
    cfg = _resolve_config(owner)
    if not cfg["api_key"] or not cfg["base_url"] or not cfg["model"]:
        raise ai_not_configured()

    if not path.is_file():
        raise ImageToolError("FILE_GONE", f"图片文件已丢失：{path}", 410)

    mime = _mime_for(path)
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as e:
        print(f"[image_tool] OCR 读文件失败 {path}: {type(e).__name__}: {e}", flush=True)
        raise ImageToolError(
            "FILE_GONE",
            "读取图片失败：文件可能已被移动或删除，请重新上传后再试。",
            410,
        ) from None

    payload = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    body = _post(cfg, payload)
    content = _content_of(body)
    parsed = _extract_json(content)
    return _normalize(parsed, cfg)


def _resolve_config(owner: str) -> dict[str, str]:
    """按账号解析该模块的 AI 配置（每次调用都读库：设置页改完立即生效）。

    DB 异常在这里必须被翻译成 ImageToolError —— 否则首启建表竞态、
    连接中断等情况会以裸 OperationalError 冒泡成「无信息 500」，
    用户只看到"识别失败"，无从判断是自己的问题还是服务的问题。
    """
    from ...core.settings_service import resolve_ai
    from ...db.session import SessionLocal

    db = SessionLocal()
    try:
        cfg = resolve_ai(db, MODULE_ID, owner=owner)
    except ImageToolError:
        raise
    except Exception as e:  # noqa: BLE001 —— DB 层异常统一转可行动提示
        raise ocr_failed(
            f"读取 AI 配置失败（{type(e).__name__}）。请检查应用服务状态后重试。"
        ) from None
    finally:
        db.close()
    return {
        "api_key": cfg["api_key"],
        "base_url": ensure_url_scheme(cfg["base_url"].rstrip("/")),
        "model": cfg["model"],
    }


def _post(cfg: dict[str, str], payload: dict[str, Any], _retried: bool = False) -> dict[str, Any]:
    req = urlreq.Request(
        url=f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    try:
        with urlreq.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlreq.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code == 401:
            raise ocr_failed("API Key 无效或已过期（401），请在「设置 → AI 模型」中检查") from None
        # 端点不支持结构化输出（豆包/自建网关常见）→ 去掉该参数重试**一次**。
        # _retried 显式标记而不是靠判断 payload 里还有没有 response_format：
        # 后者依赖副作用状态，代码一改就会变成无限递归。
        if e.code == 400 and payload.get("response_format") and not _retried:
            payload.pop("response_format", None)
            return _post(cfg, payload, _retried=True)
        if e.code == 429:
            raise ocr_failed("调用频率超限（429），请稍后重试") from None
        if e.code == 404:
            raise ocr_failed(
                f"地址或模型不存在（404）：{detail}。请确认模型名在该地域已上线"
                f"（纯文字提取推荐 qwen3.5-ocr）"
            ) from None
        raise ocr_failed(f"识别服务返回 HTTP {e.code}：{detail}") from None
    except ImageToolError:
        raise
    except Exception as e:  # noqa: BLE001
        # 网络类异常的原始类型对用户无意义，但排障时有用 → 只进日志
        print(f"[image_tool] OCR 调用失败: {type(e).__name__}: {e}", flush=True)
        raise ocr_failed(
            "无法连接识别服务，请检查 NAS 网络与代理设置；"
            "若已在设置中填过地址，也请确认该地址可正常访问。"
        ) from None


def _content_of(body: dict[str, Any]) -> str:
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ocr_failed(f"识别服务响应结构异常：{str(body)[:200]}") from None


def _extract_json(text: str) -> dict[str, Any]:
    """容错提取 JSON（与周报 vlm._extract_json 同策略：模型常带 markdown 围栏）。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ocr_failed("模型返回内容无法解析为 JSON")


def _normalize(payload: dict[str, Any], cfg: dict[str, str]) -> dict[str, Any]:
    raw_text = str(payload.get("text") or "")
    raw_blocks = payload.get("blocks")
    blocks: list[dict[str, Any]] = []
    if isinstance(raw_blocks, list):
        for item in raw_blocks:
            if not isinstance(item, dict):
                continue
            txt = str(item.get("text") or "").strip()
            if not txt:
                continue
            blocks.append({"text": txt, "box": _clean_box(item.get("box")), "confidence": _conf(item.get("confidence"))})
    # blocks 为空但有整图文本时，兜一个整图块，前端至少能选中全文
    if not blocks and raw_text:
        blocks = [{"text": raw_text, "box": [0, 0, 1000, 1000], "confidence": 0.5}]
    return {
        "text": raw_text or "\n".join(b["text"] for b in blocks),
        "blocks": blocks,
        "meta": {"model": cfg["model"], "blockCount": len(blocks), "charCount": len(raw_text)},
    }


def _clean_box(box: Any) -> list[int]:
    """把 box 归一成 4 个 0~1000 的整数；非法则给整图框。"""
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return [0, 0, 1000, 1000]
    try:
        vals = [int(round(float(v))) for v in box[:4]]
    except (TypeError, ValueError):
        return [0, 0, 1000, 1000]
    return [max(0, min(1000, v)) for v in vals]


def _conf(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _mime_for(path: Path) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp", ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(path.suffix.lower(), "image/png")
