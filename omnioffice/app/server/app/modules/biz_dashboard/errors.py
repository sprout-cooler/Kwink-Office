"""数据大屏统一异常。

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
    """数据大屏可预期的业务错误。"""

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
        "请在「设置 → 数据大屏」中填写腾讯地图 Key（服务端代为调用，前端不会泄露）",
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

    腾讯对每个 Key 限制日调用量（默认 1 万次），且这个额度是**所有 WebService
    接口合计**的（实测 2026-10-26：geocoder 报配额耗尽时，place/v1 同样报耗尽）。
    配额耗尽时：换 Key / 在控制台申请提额 / 等待次日重置。
    这是**用户侧可自行解决**的问题，不该只丢一句「调用失败」。
    """
    return BizDashboardError(
        "MAP_QUOTA_EXCEEDED",
        f"腾讯地图调用配额已用尽（{reason}）。"
        "注意：腾讯位置服务的日调用量配额是**该 Key 下所有接口合计**的，"
        "地址解析、POI 搜索、路线规划会互相占用，因此配额用尽后地图相关功能会一起不可用。"
        "处置方式：① 在「设置 → 数据大屏」换一个 Key；"
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


def share_pass_required() -> BizDashboardError:
    """分享设置了访问口令，请求未带口令。

    与「口令错误」分开：没带口令时提示「需要口令」，带了但错时提示「口令不正确」，
    接收者据此知道下一步是「问分享者要口令」还是「核对口令」。
    """
    return BizDashboardError(
        "SHARE_PASS_REQUIRED",
        "该分享设置了访问口令，请输入分享者给你的口令后重试",
        401,
    )


def share_pass_invalid() -> BizDashboardError:
    return BizDashboardError(
        "SHARE_PASS_INVALID",
        "访问口令不正确，请核对后重试（可向分享者确认）",
        401,
    )


# ---------------------------------------------------------------- 账单导入


def bill_empty() -> BizDashboardError:
    return BizDashboardError(
        "BILL_EMPTY",
        "文件里没有可解析的数据行。请确认导出的是账单明细 CSV（不是空文件或仅含说明文字的封面行）",
        400,
    )


def bill_too_large(rows: int, limit: int) -> BizDashboardError:
    return BizDashboardError(
        "BILL_TOO_LARGE",
        f"账单行数过多（{rows} 行，上限 {limit} 行）。"
        "请在支付平台按月份分批导出后再导入，避免一次处理过久",
        413,
        rows=rows,
        limit=limit,
    )


def bill_too_big(size: int, limit: int) -> BizDashboardError:
    return BizDashboardError(
        "BILL_TOO_BIG",
        f"文件过大（{round(size / 1024 / 1024, 1)} MB，上限 {round(limit / 1024 / 1024, 1)} MB）。"
        "请缩短导出时间范围后重新导出",
        413,
        size=size,
        limit=limit,
    )


def bill_unreadable() -> BizDashboardError:
    """常见编码都解不开 —— 多数情况不是 CSV，或文件已损坏。"""
    return BizDashboardError(
        "BILL_UNREADABLE",
        "无法识别文件编码（已尝试 UTF-8 与 GBK/GB18030）。"
        "请确认上传的是**文本格式的 CSV 文件**；若从 Excel 另存，请选择「CSV UTF-8（逗号分隔）」格式",
        400,
    )


def bill_no_header() -> BizDashboardError:
    """表头里一个可识别的列都没有。

    支付宝/微信账单导出常带若干行说明（如「支付宝交易明细」「导出时间：…」），
    真正的表头在中间。这里已做多行探测仍失败，说明确实不是账单文件。
    """
    return BizDashboardError(
        "BILL_NO_HEADER",
        "未能识别账单表头（未找到交易时间、金额、交易对方等任何一列）。"
        "请使用支付平台**官方导出的原始账单文件**，不要自行编辑或另存为 Excel 表格",
        400,
    )
