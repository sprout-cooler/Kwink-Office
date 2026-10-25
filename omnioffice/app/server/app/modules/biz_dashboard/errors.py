"""经营大屏统一异常。

设计原则与 image_tool/errors.py 完全一致：
- 业务代码只抛 BizDashboardError，绝不直接抛 HTTPException；
- 每个错误码带**可行动的中文提示**（用户下一步该做什么），
  不出现英文异常类名（项目铁律：错误文案用户化）。

财务相关错误额外强调「数据不外泄」：越权访问与不存在返回**同一个错误码**，
绝不区分「存在但不属于你」与「根本不存在」—— 前者给 403 等于泄露该 id 确实存在。
"""
from __future__ import annotations

from typing import Any


class BizDashboardError(RuntimeError):
    """经营大屏可预期的业务错误。"""

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


# ---------------------------------------------------------------- 构造器


def bad_param(name: str, reason: str) -> BizDashboardError:
    return BizDashboardError("BAD_PARAM", f"参数 {name} 不合法：{reason}", 400, param=name)


def not_found(kind: str, obj_id: int) -> BizDashboardError:
    """越权与不存在返回**同一个错误**（404），避免泄露 id 的存在性。"""
    return BizDashboardError("NOT_FOUND", f"{kind}不存在：{obj_id}", 404, id=obj_id)


def required(field: str) -> BizDashboardError:
    return BizDashboardError("FIELD_REQUIRED", f"「{field}」为必填项，请填写后再保存", 400, field=field)


def bad_date(value: str, field: str) -> BizDashboardError:
    return BizDashboardError(
        "BAD_DATE",
        f"「{field}」的日期格式不正确：{value or '空'}。应为 YYYY-MM-DD 格式",
        400,
        field=field,
    )


def bad_range(start: str, end: str) -> BizDashboardError:
    return BizDashboardError(
        "BAD_RANGE",
        f"结束日期不能早于开始日期（{start} → {end}）",
        400,
        start=start,
        end=end,
    )


def bad_amount(value: Any) -> BizDashboardError:
    return BizDashboardError(
        "BAD_AMOUNT",
        f"金额不合法：{value}。金额应为不小于 0 的数字（收入/支出方向由类别决定）",
        400,
    )


def map_not_configured() -> BizDashboardError:
    return BizDashboardError(
        "MAP_NOT_CONFIGURED",
        "未配置腾讯地图 Key，无法使用地图选点与路径显示。"
        "请在「设置 → 经营大屏」中填写腾讯地图 Key（服务端代为调用，前端不会泄露）",
        400,
    )


def map_failed(reason: str) -> BizDashboardError:
    return BizDashboardError(
        "MAP_FAILED",
        f"地图服务调用失败：{reason}。请检查腾讯地图 Key 是否有效、是否已开通 WebService API 权限",
        502,
        reason=reason,
    )


def map_quota_exceeded(reason: str) -> BizDashboardError:
    """腾讯地图配额耗尽 —— 与普通调用失败分开提示，因为处置方式完全不同。

    腾讯对每个 Key 的每个接口限制日调用量（默认 1 万次）。
    配额耗尽时：换 Key / 在控制台申请提额 / 等待次日重置。
    这是**用户侧可自行解决**的问题，不该只丢一句「调用失败」。
    """
    return BizDashboardError(
        "MAP_QUOTA_EXCEEDED",
        f"腾讯地图调用配额已用尽（{reason}）。"
        "处置方式：① 在「设置 → 经营大屏」换一个 Key；"
        "② 到腾讯位置服务控制台「配额申请」提升日调用量（审核约 3 个工作日）；"
        "③ 等待次日 0 点配额重置。"
        "在此期间地图选点与路径显示不可用，其他功能不受影响。",
        429,
        reason=reason,
    )


def share_empty_scope() -> BizDashboardError:
    return BizDashboardError(
        "SHARE_EMPTY_SCOPE",
        "尚未勾选任何要分享的记录。请先选择要分享的财务记录，再创建分享链接",
        400,
    )


def share_invalid() -> BizDashboardError:
    """分享链接无效 —— 不区分「不存在 / 已撤销 / 已过期」三种原因。

    刻意统一措辞：若分别告知，攻击者可据此枚举哪些分享曾存在。
    """
    return BizDashboardError(
        "SHARE_INVALID",
        "分享链接无效或已失效。请向分享者索取新的链接",
        404,
    )


def share_expired() -> BizDashboardError:
    """已过期单独提示 —— 过期是可行动信息（找分享者续期），与「撤销」不同。"""
    return BizDashboardError(
        "SHARE_EXPIRED",
        "分享链接已过期。请向分享者索取新的链接",
        410,
    )
