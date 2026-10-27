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

# ---------------------------------------------------------------- 客户来源
#
# 「这个客户是怎么来的」—— 属于**业务判断**，不是系统能推导的事实。
# 所以：① 存 code 而非中文（code 稳定，中文文案可随时改，统计按 code 走）；
#       ② 提供 "other" + source_note 兜底（纯枚举覆盖不了真实业务，纯自由文本无法统计）；
#       ③ "weekly"（周报关联）是**自动填充值** —— 仅在用户未手动选时、
#          且该客户确实被周报任务关联到，才写入（自动同步只填空不覆盖）。
#
# 为什么"渠道推荐"与"老客户介绍"要分开：前者是外部渠道（代理商/集成商）带来的，
# 后者是存量客户转介绍 —— 这两者的转化率与维护方式不同，合并统计会失去意义。
CUSTOMER_SOURCES: tuple[tuple[str, str], ...] = (
    ("referral", "老客户介绍"),
    ("bid_win", "招标中标"),
    ("campaign", "市场活动"),
    ("outreach", "主动开发"),
    ("channel", "渠道推荐"),
    ("weekly", "周报关联"),
    ("other", "其他"),
)
CUSTOMER_SOURCE_CODES: tuple[str, ...] = tuple(c for c, _ in CUSTOMER_SOURCES)

# 需要补充说明的来源（前端据此决定是否显示「来源说明」输入框）
CUSTOMER_SOURCE_NEEDS_NOTE: tuple[str, ...] = ("other",)

# 自动填充来源：用户未手动选择时，由联动写入（只填空不覆盖）
CUSTOMER_SOURCE_AUTO: str = "weekly"

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

# ---------------------------------------------------------------- 出差事由
#
# 「这次出差是去干什么」—— 与「客户」「项目」的本质差异：
# 出差不是分类标签，而是**带时间区间与坐标的事件**，所以它独立成表，
# 靠 customer_id 挂到客户，而不是塞进某个分类列。
#
# 事由分类的用途：按事由聚合出差的次数与花费（如「售前演示 12 次，差旅 3.2 万」），
# 这是「客户」维度给不出来的另一视角。
TRIP_REASONS: tuple[tuple[str, str], ...] = (
    ("customer_visit", "客户拜访"),
    ("tech_support", "技术支持"),
    ("presale", "售前演示"),
    ("delivery", "交付实施"),
    ("training", "培训"),
    ("meeting", "会议"),
    ("other", "其他"),
)
TRIP_REASON_CODES: tuple[str, ...] = tuple(c for c, _ in TRIP_REASONS)

# ---------------------------------------------------------------- 报销状态
#
# 与 cost_amount（本次直接花费）配套：cost_amount 是"花了多少"，
# reimburse_amount 是"报销了/要报多少"，两者可能不等（自费部分、公司统一订票等）。
REIMBURSE_STATUS: tuple[tuple[str, str], ...] = (
    ("none", "无需报销"),
    ("pending", "待提交"),
    ("submitted", "已提交"),
    ("paid", "已报销"),
)
REIMBURSE_STATUS_CODES: tuple[str, ...] = tuple(c for c, _ in REIMBURSE_STATUS)

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
    ("customer", "客户信息"),
    ("workload", "工作量统计"),
    ("trip", "出差路径"),
)
SHARE_SCOPE_CODES: tuple[str, ...] = tuple(c for c, _ in SHARE_SCOPES)
# 需要「显式勾选具体记录」的类别（工作量是聚合口径，无逐条 id）
SHARE_ID_SCOPES: tuple[str, ...] = ("expense", "customer", "trip")

# 分享有效期上限（天）：防止「永久有效」的分享链接长期敞口
SHARE_MAX_DAYS = 90
SHARE_DEFAULT_DAYS = 7

# 访问口令长度范围（可选二次保护）
SHARE_PASS_MIN_LEN = 4
SHARE_PASS_MAX_LEN = 32

# ---------------------------------------------------------------- 账单导入

# 支持的支付平台。unknown 表示无法从表头识别（此时仍可按通用别名映射尝试）。
BILL_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("alipay", "支付宝"),
    ("wechat", "微信支付"),
    ("unknown", "未识别平台"),
)
BILL_PLATFORM_CODES: tuple[str, ...] = tuple(c for c, _ in BILL_PLATFORMS)
# code -> 中文标签（导出表头、列表展示用，避免各处重复写 if/else）
BILL_PLATFORM_LABELS: dict[str, str] = dict(BILL_PLATFORMS)

# 编码探测顺序：UTF-8 BOM 优先（有 BOM 就一定是 UTF-8），
# 其次 UTF-8，再退回 GB18030（它是 GBK/GB2312 的超集，能解所有 GBK 文件）。
# 注意顺序**不能反**：GB18030 几乎能解任意字节序列（包括合法 UTF-8），
# 先试它会把 UTF-8 文件误判成 GB18030 而产出乱码。
BILL_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030")

# 单次导入的最大行数/字节数（防止超大文件拖垮请求与内存）
BILL_MAX_ROWS = 20000
BILL_MAX_BYTES = 10 * 1024 * 1024

# 标准字段（解析结果用的内部名）
BILL_FIELDS: tuple[str, ...] = (
    "txn_time",  # 交易时间
    "txn_type",  # 交易类型
    "counterparty",  # 交易方（与当前账户相对的一方）
    "payer",  # 付款方（原始列）
    "payee",  # 收款方（原始列）
    "payment_method",  # 支付方式（钱走的渠道，如零钱 / 余额宝 / 银行卡）
    "amount",  # 金额
    "direction",  # 收支方向：收入 / 支出 / 不计收支
    "order_no",  # 订单号 / 交易号
    "note",  # 备注 / 商品说明
)

# 表头别名 → 标准字段。
# 为什么用别名表而不是硬编码列序：支付宝与微信的导出列数、列序、列名都不同，
# 且同一平台不同版本导出也有差异（微信账单有的版本叫「交易时间」有的叫「交易时间」，
# 支付宝旧版叫「交易号」新版叫「订单号」）。按列名匹配才能兼容。
BILL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "txn_time": ("交易时间", "交易创建时间", "时间", "日期", "交易日期", "记账日期"),
    "txn_type": ("交易类型", "类型", "交易分类"),
    # 交易方：账单里直接给出「相对方」的列。
    # 注意不包括「付款方」「收款方」——那是**绝对方向**的两列，
    # 只有在与收支方向结合后才能推导出交易方，单独映射会取反（见 bill_import）。
    "counterparty": (
        "交易对方",
        "对方",
        "商户名称",
        "对方户名",
        "商户",
        "收/付款方",  # 单列形式：本身就是相对方，可直接取
    ),
    # 付款方 / 收款方：银行与部分平台导出是两列，且是**绝对方向**。
    # 「我支出」时对方是收款方；「我收入」时对方是付款方 —— 必须按方向选。
    "payer": ("付款方", "付款人", "付款账户", "付款方名称", "付款户名", "对方付款方"),
    "payee": ("收款方", "收款人", "收款账户", "收款方名称", "收款户名", "对方收款方"),
    # 支付方式 = 这笔钱走的渠道（零钱 / 余额宝 / 银行卡），
    # 与 platform（账单来自哪个平台）是两回事，别混用。
    # 注意「收/付款方式」已从 txn_type 别名里移除，否则同一列会被两个字段抢。
    "payment_method": (
        "支付方式",
        "收/付款方式",
        "付款方式",
        "支付账户",
        "账户",
        "支付渠道",
    ),
    "amount": ("金额", "金额(元)", "金额（元）", "交易金额", "发生金额", "amount"),
    "direction": ("收/支", "收支", "收/付款", "收支方向", "资金流向"),
    "order_no": ("订单号", "交易号", "交易单号", "订单编号", "流水号", "交易订单号"),
    "note": ("备注", "商品说明", "商品名称", "说明", "交易说明", "商品"),
}

# 平台识别依据：命中任一特征列名即判定为该平台。
# 支付宝导出必带「交易对方」「收/支」，微信必带「收/支」且带「交易类型」+「支付方式」。
BILL_PLATFORM_HINTS: dict[str, tuple[str, ...]] = {
    "alipay": ("交易对方", "交易号", "收/支", "商品说明"),
    "wechat": ("交易对方", "交易类型", "收/支", "支付方式", "当前状态"),
}

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
        "customerSources": [{"value": c, "label": l} for c, l in CUSTOMER_SOURCES],
        "customerSourceNeedsNote": list(CUSTOMER_SOURCE_NEEDS_NOTE),
        "tripStatus": [{"value": c, "label": l} for c, l in TRIP_STATUS],
        "tripReasons": [{"value": c, "label": l} for c, l in TRIP_REASONS],
        "reimburseStatus": [{"value": c, "label": l} for c, l in REIMBURSE_STATUS],
        "transportModes": [{"value": c, "label": l} for c, l in TRANSPORT_MODES],
        "expenseKinds": [{"value": c, "label": l} for c, l in EXPENSE_KINDS],
        "expenseCategories": list(EXPENSE_CATEGORIES),
        "shareScopes": [{"value": c, "label": l} for c, l in SHARE_SCOPES],
        "shareIdScopes": list(SHARE_ID_SCOPES),
        "shareMaxDays": SHARE_MAX_DAYS,
        "shareDefaultDays": SHARE_DEFAULT_DAYS,
        "sharePassMinLen": SHARE_PASS_MIN_LEN,
        "sharePassMaxLen": SHARE_PASS_MAX_LEN,
        "billPlatforms": [{"value": c, "label": l} for c, l in BILL_PLATFORMS],
        "billEncodings": list(BILL_ENCODINGS),
        "billMaxRows": BILL_MAX_ROWS,
        "billMaxBytes": BILL_MAX_BYTES,
        "maxPageSize": MAX_PAGE_SIZE,
    }
