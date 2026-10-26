"""数据大屏常量：状态枚举、分类字典、限额。

集中定义的理由（沿用 image_tool 的做法）：
前端下拉、图表分类、校验规则全部由此驱动 —— 新增一个分类只需改这里，
前后端零散落。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 客户状态

CUSTOMER_STATUS: tuple[tuple[str, str], ...] = (
    ("active", "合作中"),
    ("dormant", "暂停合作"),
    ("archived", "已归档"),
)
CUSTOMER_STATUS_CODES: tuple[str, ...] = tuple(c for c, _ in CUSTOMER_STATUS)

# ---------------------------------------------------------------- 出差状态

TRIP_STATUS: tuple[tuple[str, str], ...] = (
    ("planned", "计划中"),
    ("ongoing", "进行中"),
    ("done", "已完成"),
    ("cancelled", "已取消"),
)
TRIP_STATUS_CODES: tuple[str, ...] = tuple(c for c, _ in TRIP_STATUS)

# ---------------------------------------------------------------- 交通方式

TRANSPORT_MODES: tuple[tuple[str, str], ...] = (
    ("", "未填写"),
    ("plane", "飞机"),
    ("train", "高铁"),
    ("car", "自驾"),
    ("bus", "大巴"),
    ("other", "其他"),
)
TRANSPORT_CODES: tuple[str, ...] = tuple(c for c, _ in TRANSPORT_MODES)

# ---------------------------------------------------------------- 财务

EXPENSE_KINDS: tuple[tuple[str, str], ...] = (
    ("expense", "支出"),
    ("income", "收入"),
)
EXPENSE_KIND_CODES: tuple[str, ...] = tuple(c for c, _ in EXPENSE_KINDS)

# 常用财务类别（自由文本，允许用户输入表外的值，此处仅用于前端建议）
EXPENSE_CATEGORIES: tuple[str, ...] = (
    "差旅",
    "餐饮",
    "住宿",
    "交通",
    "办公",
    "工资",
    "采购",
    "房租",
    "其他",
)

# ---------------------------------------------------------------- 分享

SHARE_SCOPES: tuple[tuple[str, str], ...] = (
    ("expense", "财务流水"),
    ("workload", "工作量"),
    ("trip", "出差记录"),
)
SHARE_SCOPE_CODES: tuple[str, ...] = tuple(c for c, _ in SHARE_SCOPES)

# 分享有效期上限（天）：防止「永久有效」的分享链接长期敞口
SHARE_MAX_DAYS = 90
SHARE_DEFAULT_DAYS = 7

# ---------------------------------------------------------------- 限额

# 单次查询返回的最大记录数（防止一次性拉爆前端与响应体）
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100

# 工时单条上限（小时）：一天不超过 24 小时，留一点余量给跨天任务
MAX_HOURS_PER_ENTRY = 24.0
MIN_HOURS_PER_ENTRY = 0.0

# 地图 Key 的设置键名（存 user_settings，按账号隔离）
MAP_KEY_SETTING = "biz_dashboard.map.key"

# 腾讯地图 WebService 反代地址（官方 SDK 走 /ws 路径）
TENCENT_MAP_WS_BASE = "https://apis.map.qq.com/ws"

# 允许反代到腾讯地图的路径前缀白名单（防路径注入 / SSRF）
# 只放行腾讯地图实际使用的服务前缀，其余一律拒绝。
TENCENT_MAP_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/geocoder/v1/",
    "/place/v1/",
    "/direction/v1/",
    "/distance/v1/",
)


def capabilities() -> dict:
    """能力清单：前端下拉由此驱动，新增分类前端零改动。"""
    return {
        "customerStatus": [{"value": c, "label": l} for c, l in CUSTOMER_STATUS],
        "tripStatus": [{"value": c, "label": l} for c, l in TRIP_STATUS],
        "transportModes": [{"value": c, "label": l} for c, l in TRANSPORT_MODES],
        "expenseKinds": [{"value": c, "label": l} for c, l in EXPENSE_KINDS],
        "expenseCategories": list(EXPENSE_CATEGORIES),
        "shareScopes": [{"value": c, "label": l} for c, l in SHARE_SCOPES],
        "shareMaxDays": SHARE_MAX_DAYS,
        "shareDefaultDays": SHARE_DEFAULT_DAYS,
        "maxPageSize": MAX_PAGE_SIZE,
    }
