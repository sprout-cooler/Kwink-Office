"""支付平台账单 CSV 解析（v1.0.32）。

支持支付宝 / 微信支付导出的账单文件，自动探测编码、识别平台、映射字段、
校验格式并生成去重键。

设计取舍：

- **不引第三方依赖**：用标准库 `csv` + `codecs`。NAS 上装 `chardet`/`pandas`
  会增加镜像体积与构建时间，而账单文件的编码只有 UTF-8 与 GBK 两种实际可能，
  用探测顺序就能可靠区分。

- **编码探测顺序不能反**：GB18030 是 GBK 的超集且几乎能解任意字节序列
  （包括合法 UTF-8），先试它会把 UTF-8 文件误判成 GB18030 而产出中文乱码。
  所以顺序恒为「UTF-8 BOM → UTF-8 → GB18030」。

- **按列名映射而不是按列序**：支付宝与微信的列数、列序、列名都不同，
  同一平台不同导出版本也有差异（支付宝旧版「交易号」/新版「订单号」）。
  按列序硬编码会在用户换一种导出方式时静默错位 —— 金额读到日期列上，
  后果比直接报错更严重。

- **表头位置不固定在第一行**：微信账单导出开头有若干行说明
  （「微信支付账单明细」「导出时间：…」），真正的表头在中间。
  所以要在前 N 行里找「可识别列最多且含金额列」的那一行。

- **本模块只做解析，不做去重落库**：产出每行状态与去重键，
  由 service 层与库内历史比对后决定最终是否写入。这样本模块可脱离数据库单测。
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import constants, errors

# 每行解析结果的状态
STATUS_OK = "ok"  # 可导入
STATUS_DUPLICATE = "duplicate"  # 与库内历史或本次文件内前面某行重复
STATUS_SKIPPED = "skipped"  # 业务上不纳入（不计收支 / 已退款），非错误
STATUS_FAILED = "failed"  # 格式错误，无法导入

# 收支方向：income 收入 / expense 支出 / none 不计收支
DIRECTION_INCOME = "income"
DIRECTION_EXPENSE = "expense"
DIRECTION_NONE = "none"

# 表头探测的最大扫描行数（账单头部说明一般不超过 20 行）
_HEADER_SCAN_ROWS = 30

# 微信账单里这些「当前状态」的交易不应计入收支（钱已退回或交易未成立）
_SKIP_TXN_STATES: tuple[str, ...] = (
    "已全额退款",
    "已退款",
    "部分退款",
    "交易关闭",
    "已关闭",
    "充值失败",
)

_DATE_RE = re.compile(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")
_BRACKET_RE = re.compile(r"[（(][^（()）]*[)）]")


# ---------------------------------------------------------------- 数据结构


@dataclass
class ParsedRow:
    """一行账单的解析结果。

    line 用 CSV 内的行号（1-based，含表头与说明行），
    这样前端显示的「第 N 行有问题」与用户在 Excel 里看到的行号一致。
    """

    line: int
    status: str
    reason: str = ""
    txn_time: str = ""
    txn_type: str = ""
    counterparty: str = ""
    amount: Decimal | None = None
    direction: str = ""
    order_no: str = ""
    note: str = ""
    payment_method: str = ""
    dedupe_key: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    def to_dto(self) -> dict:
        return {
            "line": self.line,
            "status": self.status,
            "reason": self.reason,
            "txnTime": self.txn_time,
            "txnType": self.txn_type,
            "counterparty": self.counterparty,
            # 原始的两列也回传：交易方是推导出来的，预览时要让用户能核对推导依据
            "payer": self.raw.get("payer", ""),
            "payee": self.raw.get("payee", ""),
            "paymentMethod": self.payment_method,
            # 映射后的最终类别（由 service 按用户规则算出，解析层不参与）
            "mappedCategory": self.raw.get("mappedCategory", ""),
            "amount": float(self.amount) if self.amount is not None else None,
            "direction": self.direction,
            "orderNo": self.order_no,
            "note": self.note,
            "dedupeKey": self.dedupe_key,
        }


@dataclass
class BillParseResult:
    encoding: str
    platform: str
    header_line: int
    # 标准字段 -> 列索引（缺失的字段不在 dict 里）
    mapping: dict[str, int]
    header_cells: list[str]
    rows: list[ParsedRow]

    def summary(self) -> dict:
        ok = sum(1 for r in self.rows if r.status == STATUS_OK)
        dup = sum(1 for r in self.rows if r.status == STATUS_DUPLICATE)
        skip = sum(1 for r in self.rows if r.status == STATUS_SKIPPED)
        fail = sum(1 for r in self.rows if r.status == STATUS_FAILED)
        return {
            "total": len(self.rows),
            "ok": ok,
            "duplicate": dup,
            "skipped": skip,
            "failed": fail,
        }


# ---------------------------------------------------------------- 编码与列名


def detect_encoding(raw: bytes) -> str:
    """探测账单文件编码。

    返回编码名；全部失败则抛 BILL_UNREADABLE（可行动提示）。
    """
    if not raw:
        raise errors.bill_empty()
    # 有 BOM 就一定是 UTF-8，无需试探
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    for enc in ("utf-8", "gb18030"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    raise errors.bill_unreadable()


def _normalize_header(name: str) -> str:
    """列名归一化：去空白、去括号补充说明。

    「金额(元)」「 交易时间 」都要能归到标准别名上。
    """
    s = (name or "").strip()
    s = _BRACKET_RE.sub("", s)
    s = s.replace(" ", "").replace("\u3000", "").replace("\t", "")
    return s


def _match_field(norm: str) -> str | None:
    """归一化列名 -> 标准字段名，未识别返回 None。"""
    for std, aliases in constants.BILL_FIELD_ALIASES.items():
        for alias in aliases:
            if norm == alias:
                return std
    # 二级：包含匹配。只对较长的列名启用，避免「金额」误命中「退款金额」这类
    # 语义不同的列 —— 因此要求列名比别名长，且别名出现在开头。
    for std, aliases in constants.BILL_FIELD_ALIASES.items():
        for alias in aliases:
            if len(norm) > len(alias) and norm.startswith(alias):
                return std
    return None


def detect_platform(header_cells: list[str]) -> str:
    """按表头特征列识别平台；命中不足则 unknown。"""
    norm = {_normalize_header(c) for c in header_cells}
    best = "unknown"
    best_score = 0
    for plat, hints in constants.BILL_PLATFORM_HINTS.items():
        score = sum(1 for h in hints if h in norm)
        if score > best_score:
            best, best_score = plat, score
    # 至少命中 2 个特征列才敢判定平台，否则宁可 unknown
    return best if best_score >= 2 else "unknown"


# ---------------------------------------------------------------- 值解析


def parse_date(value: str) -> str | None:
    """从任意日期/时间串里取出 YYYY-MM-DD。

    账单里常见「2024-01-15 12:30:45」「2024/1/15」「2024年1月15日」。
    """
    m = _DATE_RE.search(value or "")
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_amount(value: str) -> Decimal | None:
    """解析金额：容忍千分位、货币符号、括号负数、正负号。"""
    t = (value or "").strip()
    if not t:
        return None
    t = t.replace(",", "").replace("，", "")
    t = t.replace("¥", "").replace("￥", "").replace("元", "").strip()
    if not t:
        return None
    negative = False
    if t.startswith("-"):
        negative = True
        t = t[1:]
    elif t.startswith("+"):
        t = t[1:]
    elif t.startswith("(") and t.endswith(")"):
        negative = True
        t = t[1:-1]
    t = t.strip()
    if not t:
        return None
    try:
        amount = Decimal(t)
    except InvalidOperation:
        return None
    # 非有限值（NaN/Inf）在 Decimal 里能构造出来，必须挡掉
    if not amount.is_finite():
        return None
    return -amount if negative else amount


def parse_direction(value: str) -> str:
    """收支方向：income / expense / none，无法判定返回空串。"""
    t = (value or "").strip()
    if not t:
        return ""
    if t in ("收入", "入", "收", "+", "贷"):
        return DIRECTION_INCOME
    if t in ("支出", "出", "支", "-", "借"):
        return DIRECTION_EXPENSE
    if t in ("不计收支", "不计", "/", "—", "-", "其他", "中性"):
        return DIRECTION_NONE
    return ""


def resolve_counterparty(direction: str, direct: str = "", payer: str = "", payee: str = "") -> str:
    """从「收款方 / 付款方 / 交易对方」三类中定出**交易方**。

    交易方的定义：**与当前账户相对的一方** —— 我付钱时对方是收款方，
    我收钱时对方是付款方。命名上刻意不叫「客户」：交易对手可以是任何
    商户、个人或平台，未必在客户档案里建过档。

    取值优先级：
      1. 账单直接给出相对方列（交易对方 / 收/付款方 / 商户名称）→ 直接用；
      2. 只有「付款方 + 收款方」两列（银行流水常见）→ **按收支方向选**：
         支出取收款方，收入取付款方。这两列是绝对方向，不结合方向就会取反；
      3. 对应方向的那一列缺失 → 回落到另一列（宁可有值给用户核对，
         也不要留空；用户可在导入预览里逐行确认）。
    """
    if (direct or "").strip():
        return direct.strip()
    payer = (payer or "").strip()
    payee = (payee or "").strip()
    if direction == DIRECTION_EXPENSE:
        return payee or payer
    if direction == DIRECTION_INCOME:
        return payer or payee
    return payee or payer


def build_dedupe_key(
    platform: str,
    order_no: str,
    txn_time: str,
    amount: Decimal | None,
    counterparty: str,
) -> str:
    """去重键：**订单号优先，缺失时回落组合键**。

    - 有订单号：`平台:订单号` —— 平台前缀不可省，支付宝与微信的订单号
      命名空间独立，理论上可能撞号。
    - 无订单号：`平台:~:时间:金额:对方` —— 三元组在日常账单里足够区分。

    返回空串表示这行缺少生成键的必要信息（不应参与去重比对）。
    """
    if not txn_time or amount is None:
        return ""
    if order_no:
        return f"{platform}:{order_no.strip()}"
    return f"{platform}:~:{txn_time}:{amount}:{(counterparty or '').strip()}"


# ---------------------------------------------------------------- 主流程


def _locate_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """在前 N 行里定位真正的表头。

    取「可识别列数最多」且「必须含金额列」的那一行。
    要求含金额列是因为账单说明行里也可能出现「交易时间」这类词，
    没有金额列就不可能是数据表的表头。
    """
    best_idx = -1
    best_map: dict[str, int] = {}
    limit = min(_HEADER_SCAN_ROWS, len(rows))
    for idx in range(limit):
        cells = rows[idx]
        if not cells:
            continue
        mapping: dict[str, int] = {}
        for col_idx, name in enumerate(cells):
            std = _match_field(_normalize_header(name))
            # 同一标准字段只取第一列（避免「金额」与「退款金额」都命中）
            if std and std not in mapping:
                mapping[std] = col_idx
        if "amount" not in mapping:
            continue
        if len(mapping) > len(best_map):
            best_map = mapping
            best_idx = idx
    return best_idx, best_map


def _cell(cells: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(cells):
        return ""
    return (cells[idx] or "").strip()


_THOUSANDS_TAIL_RE = re.compile(r"^\d{3}\.\d{1,2}$")


def _detect_thousands_shift(cells: list[str], amount_idx: int | None, amount_text: str) -> str:
    """检测「金额里的千分位逗号把整行切成错位列」。

    判据（两条同时成立才报，避免误伤）：
      1. 金额列读到的是一个**整数**（原本应有小数，或至少不该在此处断掉）；
      2. 紧邻的下一列是 `NNN.NN` 形态（正是千分位切开后的尾巴）。

    返回尾巴文本（用于报错文案），未检测到返回空串。
    """
    if amount_idx is None:
        return ""
    nxt = amount_idx + 1
    if nxt >= len(cells):
        return ""
    tail = (cells[nxt] or "").strip()
    if not _THOUSANDS_TAIL_RE.match(tail):
        return ""
    head = amount_text.strip()
    # 金额列必须是纯整数（带小数点的正常金额不会被误判）
    if not re.match(r"^\d{1,7}$", head):
        return ""
    return tail


def parse_bill(raw: bytes, file_name: str = "") -> BillParseResult:
    """解析账单 CSV 原始字节。

    只做「读得懂 + 格式对不对」，不查库、不去重落库（由 service 负责）。
    """
    if not raw:
        raise errors.bill_empty()
    if len(raw) > constants.BILL_MAX_BYTES:
        raise errors.bill_too_big(len(raw), constants.BILL_MAX_BYTES)

    encoding = detect_encoding(raw)
    text = raw.decode(encoding)
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:  # 极少见：引号不闭合等畸形 CSV
        raise errors.bill_unreadable() from exc

    header_idx, mapping = _locate_header(rows)
    if header_idx < 0:
        raise errors.bill_no_header()
    header_cells = [c.strip() for c in rows[header_idx]]
    platform = detect_platform(header_cells)

    state_idx = None
    for idx, name in enumerate(header_cells):
        if _normalize_header(name) in ("当前状态", "交易状态", "状态"):
            state_idx = idx
            break

    has_direction_col = "direction" in mapping
    parsed: list[ParsedRow] = []
    for offset, cells in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if not cells or all(not (c or "").strip() for c in cells):
            continue  # 空行（账单结尾常见）
        joined = "".join((c or "") for c in cells)
        # 合计行 / 小计行不是交易，跳过且不计入任何统计
        if re.search(r"^(合计|小计|总计|共\s*\d+)", joined.strip()):
            continue

        row = _parse_row(
            line=offset,
            cells=cells,
            mapping=mapping,
            platform=platform,
            has_direction_col=has_direction_col,
            state_idx=state_idx,
        )
        parsed.append(row)

    if not parsed:
        raise errors.bill_empty()
    if len(parsed) > constants.BILL_MAX_ROWS:
        raise errors.bill_too_large(len(parsed), constants.BILL_MAX_ROWS)

    return BillParseResult(
        encoding=encoding,
        platform=platform,
        header_line=header_idx + 1,
        mapping=mapping,
        header_cells=header_cells,
        rows=parsed,
    )


def _parse_row(
    *,
    line: int,
    cells: list[str],
    mapping: dict[str, int],
    platform: str,
    has_direction_col: bool,
    state_idx: int | None,
) -> ParsedRow:
    raw = {
        "txnTime": _cell(cells, mapping.get("txn_time")),
        "txnType": _cell(cells, mapping.get("txn_type")),
        "counterparty": _cell(cells, mapping.get("counterparty")),
        "payer": _cell(cells, mapping.get("payer")),
        "payee": _cell(cells, mapping.get("payee")),
        "paymentMethod": _cell(cells, mapping.get("payment_method")),
        "amount": _cell(cells, mapping.get("amount")),
        "direction": _cell(cells, mapping.get("direction")) if has_direction_col else "",
        "orderNo": _cell(cells, mapping.get("order_no")),
        "note": _cell(cells, mapping.get("note")),
        "state": _cell(cells, state_idx),
    }

    # 1) 已退款 / 已关闭的交易不计入收支（钱没真正进出）
    if raw["state"] and any(raw["state"] == s for s in _SKIP_TXN_STATES):
        return ParsedRow(
            line=line,
            status=STATUS_SKIPPED,
            reason=f"交易状态为「{raw['state']}」，未计入收支",
            raw=raw,
        )

    txn_time = parse_date(raw["txnTime"])
    if not txn_time:
        return ParsedRow(
            line=line,
            status=STATUS_FAILED,
            reason=f"无法识别交易时间：{raw['txnTime'] or '（空）'}",
            raw=raw,
        )

    amount = parse_amount(raw["amount"])
    if amount is None:
        return ParsedRow(
            line=line,
            status=STATUS_FAILED,
            reason=f"金额无法解析为数字：{raw['amount'] or '（空）'}",
            raw=raw,
        )

    # 千分位逗号导致的列错位检测（实测发现，必须显式报错）。
    # 若金额「1,234.56」在文件里**没有用引号包裹**，CSV 会把它切成两列：
    # 金额列读到「1」，下一列读到「234.56」—— 金额静默少了三个数量级。
    # 财务数据静默错误的代价远高于报错，所以这里直接判失败并给出可行动提示。
    shifted = _detect_thousands_shift(cells, mapping.get("amount"), str(amount))
    if shifted:
        return ParsedRow(
            line=line,
            status=STATUS_FAILED,
            reason=(
                f"金额疑似带千分位逗号且未加引号，导致这一行的列整体错位"
                f"（金额列读到「{raw['amount']}」，其后还有「{shifted}」）。"
                f"请重新导出账单，或在 Excel 中把金额列设为「不带千分位」的纯数字后另存 CSV"
            ),
            raw=raw,
        )

    direction = parse_direction(raw["direction"]) if has_direction_col else ""
    if not direction:
        # 没有「收/支」列的账单：用金额符号判定，正数仍无法判定则报错。
        # 不默认成支出 —— 方向搞反会让财务统计整体反号，宁可让用户看清楚再处理。
        if amount < 0:
            direction = DIRECTION_EXPENSE
        else:
            return ParsedRow(
                line=line,
                status=STATUS_FAILED,
                reason="缺少「收/支」列且金额为正，无法判定是收入还是支出",
                raw=raw,
            )

    if direction == DIRECTION_NONE:
        return ParsedRow(
            line=line,
            status=STATUS_SKIPPED,
            reason="该笔标记为「不计收支」（如内部转账 / 余额变动），未纳入财务统计",
            raw=raw,
        )

    # 金额一律存正数，方向由 direction 表达（与 BizExpense.kind 一致）
    amount = abs(amount)

    order_no = raw["orderNo"]
    # 交易方 = 与当前账户相对的一方。账单给的是绝对方向的「付款方/收款方」两列时，
    # 必须按收支方向选，否则会把「我」当成交易对手。
    counterparty = resolve_counterparty(
        direction, raw["counterparty"], raw["payer"], raw["payee"]
    )
    return ParsedRow(
        line=line,
        status=STATUS_OK,
        txn_time=txn_time,
        txn_type=raw["txnType"],
        counterparty=counterparty,
        amount=amount,
        direction=direction,
        order_no=order_no,
        note=raw["note"],
        payment_method=raw["paymentMethod"],
        dedupe_key=build_dedupe_key(platform, order_no, txn_time, amount, counterparty),
        raw=raw,
    )
