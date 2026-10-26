"""OpenAI 兼容 VLM 识别器（V10 3.5 / 4.x；Prompt v2）。

- 任何 OpenAI-compatible chat/completions 端点都可接入：通义千问（百炼
  DashScope 通用域名或业务空间专属域名）、豆包方舟、以及任何自建兼容网关；
- 服务商预设集中维护在 core.settings_service.AI_PROVIDERS（单一事实来源），
  阿里云 2026-09 域名调整时此处曾与 settings_service 各存一份而漏改，故改为引用；
- 图片以 base64 data URL 内联（无需公网可访问的图片地址）；
- 输出强制 JSON，7 级容错解析（json → markdown 代码围栏 → 首尾大括号截取 → 尝试修复）。
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib import request as urlreq

# 协议头补全统一走 settings_service（单一事实来源）：
# 早期此处与 settings_service 各存一份实现，规则一旦调整极易漏改。
from ...core.settings_service import AI_PROVIDERS, ensure_url_scheme

PROMPT_V3 = """你是工作截图信息抽取助手。截图有两类，先判断类型再抽取，只输出一个 JSON 对象。

类型一「task」：来自工作任务系统的任务/工单/排期截图（有任务标题、开始结束时间、状态）。
类型二「wechat_summary」：企业微信「一周小结」类统计截图，典型特征是含
「一周小结 x.x-x.x」「处理了 N 次工作会话」「总共花了 N 分钟」「最晚时间在…」等汇总文案，
**没有逐条任务**。

输出格式：
{
  "type": "task 或 wechat_summary",
  "tasks": [
    {
      "title": "任务标题或内容（原文，不要改写总结，不要省略）",
      "start_time": "开始时间原文（图中怎么写就怎么抄，如 10月8日 15:30 / 周四 10:00 / Oct 9 / 261012）",
      "end_time": "结束时间原文；若图中只有时刻没有日期也按原文抄；确实没有结束时间填空字符串",
      "status": "任务状态原文（如 已完成/进行中/处理中/待处理，没有则填空字符串）",
      "confidence": 0.0
    }
  ],
  "wechat_summary": {
    "session_count": 413,
    "total_minutes": 902,
    "latest_time": "最晚时间原文，如 周四深夜 10:33；没有填空字符串",
    "period_text": "小结周期原文，如 10.5-10.9；没有填空字符串",
    "confidence": 0.0
  }
}

要求：
1. 只输出 JSON，不要任何解释文字；
2. task 类型：每行/每条任务对应 tasks 数组一个元素，顺序与图中从上到下一致；
   时间字段原样抄录，不要自行换算或补全；wechat_summary 字段给 null；
3. wechat_summary 类型：tasks 给空数组 []，session_count/total_minutes 必须是阿拉伯数字
   （「处理了413次工作会话」→ 413），识别不出的数字给 null；
4. confidence 给出抽取质量置信度（0~1），图片模糊、文字残缺时如实降低；
5. 既非任务截图也非一周小结时，返回 {"type": "task", "tasks": []}。
"""

MAX_TOKENS = 2000
TIMEOUT_S = 60

# ---- 客户指认提示词（客户名单动态注入）--------------------------------
#
# 为什么是「指认」而不是「抽取」：
# 自由抽取会产出「XX科技公司」「xx科技」「XX 科技」这类变体，与客户表对不上，
# 后续匹配必然失败。而「在给定名单里选一个」输出的天然可精确匹配。
#
# 客户名单为空时**不注入**这一段 —— 客户都还没建档，指认没有对象，
# 此时退回纯抽取（抽到什么算什么，匹配不上就标 none）。
CUSTOMER_HINT_HEADER = """已知客户名单（只能从里面选，或留空）：
{list}

6. 每个 task 增加 "customer" 字段：若任务内容明确涉及名单中的某个客户，
   填该客户的**原名**（与名单完全一致）；涉及多个客户用「、」分隔；
   没有客户线索填空字符串。名单里没有但确实提到客户时，填你看到的名字。
"""

CUSTOMER_HINT_FOOTER = """6. 每个 task 增加 "customer" 字段：若任务内容明确涉及某个客户，
填该客户的名字；没有客户线索填空字符串。
"""


def build_prompt(customer_names: list[str] | None = None) -> str:
    """构造识别提示词。

    有客户名单时注入名单段（让模型在名单内指认），无名单时用基础版。
    名单用「、」分隔并限制条数 —— 客户上千时提示词会爆炸。
    """
    names = [n.strip() for n in (customer_names or []) if n and n.strip()]
    if not names:
        return PROMPT_V3 + CUSTOMER_HINT_FOOTER
    listed = "、".join(names[:100])
    if len(names) > 100:
        listed += f"（共 {len(names)} 个客户，此处仅列出最近 100 个）"
    return PROMPT_V3 + CUSTOMER_HINT_HEADER.format(list=listed)

# 已知 OpenAI-compatible 端点预设（前端下拉 + wizard tips 一致）。
# 单一事实来源：core.settings_service.AI_PROVIDERS —— 两处曾各维护一份，
# 阿里云 2026-09 域名调整时已验证会漏改，故此处只做引用。
PROVIDER_PRESETS = AI_PROVIDERS


class RecognizeError(RuntimeError):
    """识别调用失败（网络/鉴权/响应无法解析）——外部可见，不应吞掉。

    附带的 http_code 属性供调用方判断是否可降级重试（如 400 表示端点不支持某参数）。
    """

    http_code: int | None = None


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中容错提取 JSON 对象。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 去掉 markdown 代码围栏
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 首尾大括号截取（模型前后加解释文字的常见情况）
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise RecognizeError("模型返回内容无法解析为 JSON")


def _normalize_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("tasks")
    if not isinstance(raw, list):
        return []
    tasks: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        tasks.append(
            {
                "title": title,
                "start_time": str(item.get("start_time") or "").strip(),
                "end_time": str(item.get("end_time") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                # 客户名（AI 指认或抽取）。匹配客户表的工作在落库时做（recognize_queue），
                # 这里只负责把模型给的原文带出来。
                "customer": str(item.get("customer") or "").strip(),
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return tasks


def _as_int(v: Any) -> int | None:
    """模型有时把数字包成字符串（"413"）或带中文（"413次"），统一抽取整数。"""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    m = re.search(r"\d+", str(v))
    return int(m.group(0)) if m else None


def _normalize_wechat_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    """归一化企微一周小结指标。无会话量（核心字段）则视为未识别到，返回 None。"""
    raw = payload.get("wechat_summary")
    # 某些模型可能不标 type 但直接给了 wechat_summary 结构；也可能只在文案里出现
    if not isinstance(raw, dict):
        return None
    sessions = _as_int(raw.get("session_count"))
    if sessions is None:
        # 兜底：从任意字符串字段里找「处理了 N 次工作会话」
        blob = json.dumps(raw, ensure_ascii=False)
        m = re.search(r"处理了\s*(\d+)\s*次工作会话", blob)
        sessions = int(m.group(1)) if m else None
    if sessions is None:
        return None
    try:
        confidence = float(raw.get("confidence", 0.8))
    except (TypeError, ValueError):
        confidence = 0.8
    return {
        "session_count": sessions,
        "total_minutes": _as_int(raw.get("total_minutes")),
        "latest_time": str(raw.get("latest_time") or "").strip(),
        "period_text": str(raw.get("period_text") or "").strip(),
        "confidence": max(0.0, min(1.0, confidence)),
    }


class OpenAICompatibleRecognizer:
    """OpenAI-compatible chat/completions 视觉识别。"""

    available = True

    def __init__(self, api_key: str, base_url: str, model: str, json_mode: bool = True):
        if not api_key:
            raise RecognizeError("LLM_API_KEY 为空")
        self.api_key = api_key
        self.base_url = ensure_url_scheme(base_url.rstrip("/"))
        self.model = model
        # 是否发送 response_format=json_object。
        # 百炼 qwen3 系列支持；豆包/自建网关不一定支持，遇到 400 会自动降级并记住结果。
        self.json_mode = json_mode

    async def recognize(self, image_path: str, customer_names: list[str] | None = None) -> dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(self._call, image_path, customer_names)

    def _call(self, image_path: str, customer_names: list[str] | None = None) -> dict[str, Any]:
        path = Path(image_path)
        if not path.is_file():
            raise RecognizeError(f"图片不存在：{image_path}")
        suffix = path.suffix.lower()
        mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_prompt(customer_names)},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.1,
        }
        # 结构化输出：qwen3 系列原生支持 response_format=json_object，
        # 命中后模型直接产出合法 JSON，省掉 markdown 围栏/前后解释文字的容错解析。
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            body = self._post(payload)
        except RecognizeError as e:
            # 端点不支持 response_format（400）→ 降级重试一次，并记住该端点不支持，
            # 后续调用直接不带该参数，省掉每次都白跑一趟的往返。
            if self.json_mode and getattr(e, "http_code", None) == 400:
                self.json_mode = False
                payload.pop("response_format", None)
                try:
                    body = self._post(payload)
                except RecognizeError as e2:
                    raise e2 from None
            else:
                raise

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RecognizeError(f"识别服务响应结构异常：{str(body)[:200]}") from None

        payload = _extract_json(content)
        tasks = _normalize_tasks(payload)
        ws_summary = _normalize_wechat_summary(payload)

        # 最终兜底：模型没按结构给 wechat_summary，但返回文本里明确出现
        # 「处理了 N 次工作会话」（且没有任何任务）→ 判定为企微小结。
        if ws_summary is None and not tasks:
            m = re.search(r"处理了\s*(\d+)\s*次工作会话", content)
            if m:
                ws_summary = {
                    "session_count": int(m.group(1)),
                    "total_minutes": None,
                    "latest_time": "",
                    "period_text": "",
                    "confidence": 0.6,
                }

        kind = "wechat_summary" if ws_summary is not None else "task"
        return {"type": kind, "tasks": tasks, "wechat_summary": ws_summary}

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发起一次 chat/completions 请求；错误统一转 RecognizeError（带 http_code 供降级判断）。"""
        req = urlreq.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urlreq.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlreq.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                msg = "API Key 无效或已过期（401），请在设置中检查"
            elif e.code == 429:
                msg = "调用频率超限（429），请稍后重试"
            elif e.code == 400:
                msg = f"请求被拒绝（400）：{detail}"
            else:
                msg = f"识别服务返回 HTTP {e.code}：{detail}"
            err = RecognizeError(msg)
            err.http_code = e.code  # type: ignore[attr-defined]
            raise err from None
        except RecognizeError:
            raise
        except Exception as e:
            raise RecognizeError(f"无法连接识别服务：{type(e).__name__}: {e}") from None


def build_recognizer(module: str | None = None, owner: str = ""):
    """按配置实例化识别器；未配置 Key 时返回 None（状态接口如实上报）。

    配置来源优先级：账号私有 > 全局 > 环境变量(wizard) > 内置兜底（见 settings_service.resolve_ai）。
    每次调用都读库 —— 用户在设置页改完 Key 立即生效，不需要重启容器。

    owner 为当前账号的数据归属键：不同账号各用自己的 Key/模型，互不影响。
    """
    from ...db.session import SessionLocal
    from ...core.settings_service import resolve_ai

    db = SessionLocal()
    try:
        cfg = resolve_ai(db, module, owner=owner)
    finally:
        db.close()

    if not cfg["api_key"]:
        return None
    if not cfg["base_url"] or not cfg["model"]:
        return None
    return OpenAICompatibleRecognizer(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        model=cfg["model"],
    )


def _not_found_hint(url: str, model: str) -> str:
    """404「地址或模型不存在」时的可自查指引。

    百炼的三要素必须互相匹配：接入域名所在地域 == API Key 所属地域，
    且该模型在该地域已上线。否则一律 404，而原始报错只有一句 HTTP 404，
    用户无法自查，故在此按当前配置给出最可能的原因。
    """
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    tips: list[str] = []
    if host.endswith(".dashscope.aliyuncs.com") or host == "dashscope.aliyuncs.com":
        tips.append(
            "当前是 DashScope 通用域名，官方自 2026-09-30 起不再支持新特性，"
            "调用现役模型会返回 404，请换成业务空间专属域名 "
            "（https://{WorkspaceId}.{地域}.maas.aliyuncs.com/compatible-mode/v1）"
        )
    elif ".maas.aliyuncs.com" in host:
        tips.append("请核对 WorkspaceId 与地域是否与 API Key 所属地域一致（各地域 Key 不能混用）")
    else:
        tips.append("请确认地址完整、以 /compatible-mode/v1 结尾（末尾不要带 /chat/completions）")
    if model.startswith(("qwen-vl-", "qwen3-vl-")):
        tips.append(
            f"模型 {model} 属旧版，官方已不作为首选推荐，该地域可能已不支持，建议改用 qwen3.8-flash"
        )
    else:
        tips.append(f"请到百炼「模型广场」确认 {model} 在你所选地域已上线")
    return "排查：" + "；".join(tips)


def probe_connection(base_url: str, model: str, api_key: str, timeout: int = 15) -> tuple[bool, str]:
    """连通性探测：发一个最小 chat/completions 请求，校验 base_url/model/key 组合可用。

    返回 (是否成功, 面向用户的中文提示)。设置页「测试连接」按钮使用。
    """
    if not api_key:
        return False, "API Key 为空"
    if not base_url:
        return False, "服务地址为空"
    if not model:
        return False, "模型名称为空"

    url = ensure_url_scheme(base_url).rstrip("/")
    # 兼容 base_url 误填到 /chat/completions 的情况
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
    ).encode("utf-8")
    req = urlreq.Request(
        url=f"{url}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True, "连接成功"
    except urlreq.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code == 401:
            return False, "API Key 无效或已过期（401）"
        if e.code == 404:
            return False, f"地址或模型不存在（404）：{detail}｜{_not_found_hint(url, model)}"
        if e.code == 429:
            return False, "调用频率超限（429），请稍后重试"
        return False, f"HTTP {e.code}：{detail}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
