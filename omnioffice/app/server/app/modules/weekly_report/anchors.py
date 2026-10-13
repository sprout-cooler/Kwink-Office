"""模板锚点定义与校验（V10 3.6.2 / 3.6.5）。

真实模板结构（本周工作总结-46230-46236.xlsx，单工作表 Sheet1，有效区域 A1:F26）：

    A1:F1   合并，「本周工作总结」标题          → TITLE_A1
    A2:A16  左侧竖排区块标题（B 星期/C 日期/D 工作内容/E 遇到的问题/F 解决办法）
    A3:A16  逐个星期块，每块 2 行：
            星期X  B/C/D/E/F 各列均按整块两行合并；其中 D 列仅当当天有 2 条及
            以上任务时才拆开逐行填写（0/1 条都保持合并，与模板空表版式完全一致）
    A17:A18 合并  → 工作汇总
            B17 线下培训数量 / D17 值；E17 线下售后数量 / F17 值
            B18 线上售后数量 / D18 值；E18 线下售前数量 / F18 值
    A19:A20 合并  → 重点问题跟进（用户手工录入）
            B19:C19 问题一 / D19:F19 填写区；B20:C20 问题二 / D20:F20 填写区
    A21:A22 合并  → 工作需求（用户手工录入）
            B21:C21 需求一 / D21:F21；B22:C22 需求二 / D22:F22
    A23:A26 合并  → 下周工作计划（模板预留 4 条）
            B23:C26 合并「主要工作安排」；D23:F23 … D26:F26 为四条计划位

设计约束（V10 3.6.3 关键）：
- 同日 0 条 → 整块留空；1 条 → 保持 D 合并写入合并单元格；
  2 条 → 取消 D 合并拆两格；3 条及以上 → 块内插行并扩展 B/C/E/F 合并区间。
- **插行后必须同步下移所有后续区块的行号**，否则汇总/问题/需求/计划全部错位。
  本模块用「行号偏移映射」统一处理，见 fill.py 的 RowShifter。
- C 列写 Excel 日期序列号（1899-12-30 基准）且保留原日期格式，不得写文本。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---- 基础常量 ---------------------------------------------------------------

COL_TITLE = "A"
COL_LABEL = "B"          # 星期 / 统计项名称
COL_DATE = "C"           # 日期序列号
COL_CONTENT = "D"        # 工作内容 / 统计值
COL_ISSUE = "E"          # 遇到的问题
COL_SOLUTION = "F"       # 解决办法

MERGE_COLUMNS = (COL_LABEL, COL_DATE, COL_CONTENT, COL_ISSUE, COL_SOLUTION)

# Excel 日期序列号基准（Windows 1900 日期系统，含著名的 1900 闰年 bug 偏移）
EXCEL_EPOCH_DATE = None  # 由 excel_serial() 内联实现，避免在此处 import datetime 造成循环
FIRST_DATA_ROW = 3       # 第一个星期块起始行
WEEKDAY_COUNT = 7
ROWS_PER_WEEKDAY = 2
LAST_WEEKDAY_ROW = FIRST_DATA_ROW + WEEKDAY_COUNT * ROWS_PER_WEEKDAY - 1  # = 16

SUMMARY_ROW_1 = 17
SUMMARY_ROW_2 = 18
ISSUE_ROW_1 = 19
ISSUE_ROW_2 = 20
DEMAND_ROW_1 = 21
DEMAND_ROW_2 = 22
PLAN_ROW_1 = 23
PLAN_ROW_2 = 26           # 下周计划 4 条：D23:F26

TOTAL_ROWS = 26


@dataclass(frozen=True)
class WeekdayBlock:
    """一个星期块（模板固定 2 行）。"""

    weekday: int          # 1=周一 … 7=周日
    start_row: int        # 基准行号（未插行前）
    label: str

    @property
    def end_row(self) -> int:
        return self.start_row + ROWS_PER_WEEKDAY - 1

    @property
    def date_cell(self) -> str:
        return f"{COL_DATE}{self.start_row}"

    @property
    def content_range(self) -> str:
        return f"{COL_CONTENT}{self.start_row}:{COL_CONTENT}{self.end_row}"

    def merged_range(self, col: str) -> str:
        return f"{col}{self.start_row}:{col}{self.end_row}"


@dataclass(frozen=True)
class Anchors:
    """模板锚点集合。基准行号固定，插行后由 RowShifter 换算实际行号。"""

    sheet: str = "Sheet1"
    title_cell: str = "A1"
    weekdays: tuple[WeekdayBlock, ...] = field(
        default_factory=lambda: tuple(
            WeekdayBlock(
                weekday=i + 1,
                start_row=FIRST_DATA_ROW + i * ROWS_PER_WEEKDAY,
                label=name,
            )
            for i, name in enumerate(("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"))
        )
    )
    # 工作汇总：四项统计值写入位置
    summary_cells: dict[str, str] = field(
        default_factory=lambda: {
            "training": "D17",        # 线下培训数量
            "offline_service": "F17",  # 线下售后数量
            "online_service": "D18",   # 线上售后数量
            "presale": "F18",          # 线下售前数量
        }
    )
    summary_row_range: tuple[int, int] = (SUMMARY_ROW_1, SUMMARY_ROW_2)
    issue_row_range: tuple[int, int] = (ISSUE_ROW_1, ISSUE_ROW_2)
    demand_row_range: tuple[int, int] = (DEMAND_ROW_1, DEMAND_ROW_2)
    plan_row_range: tuple[int, int] = (PLAN_ROW_1, PLAN_ROW_2)
    plan_slots: int = 4
    total_rows: int = TOTAL_ROWS

    def block(self, weekday: int) -> WeekdayBlock:
        for b in self.weekdays:
            if b.weekday == weekday:
                return b
        raise KeyError(f"非法星期：{weekday}（应为 1~7）")


# ---- 真实模板实测的合并结构（本周工作总结.xlsx，2026-10-13 再次逐格核对）----
#
# 汇总区（A17:F18）真实布局 —— D/E 两列**绝不合并**（v1.0.18 曾误合并 D17:E17，
# openpyxl 合并时会清掉非左上格 E17 的值，导致「线下售后数量」标签整个消失）：
#   B17:C17 线下培训数量 | D17 数值(独立格) | E17 线下售后数量(独立格) | F17 数值
#   B18:C18 线上售后数量 | D18 文本(独立格) | E18 线下售前数量(独立格) | F18 数值
# D18 按模板口径写文本「企微会话量：413次」，不是数字（模板样例即此格式）。
# 重点问题 / 工作需求：标签 B:C 合并，填写区 D:F 三列合并
#   B19:C19 问题一 / D19:F19     B20:C20 问题二 / D20:F20
# 下周计划：A23:A26 竖排标题，B23:C26 合并「主要工作安排」，D23:F23 … D26:F26 四条计划位
#
# 这些合并在插行后必须按实际行号整体重建 —— 否则填写区会散成独立单元格，
# 用户填一个字就撑破表格视觉（原 openpyxl 解除合并的副作用）。
SUMMARY_LABEL_MERGES: tuple[tuple[int, int], ...] = (
    (SUMMARY_ROW_1, SUMMARY_ROW_1),   # B17:C17
    (SUMMARY_ROW_2, SUMMARY_ROW_2),   # B18:C18
)
# 汇总区四个标签（解除/重建合并过程中标签值可能被 openpyxl 清掉，填充时统一写回保底）。
# 键：(列字母, 行)，值：模板原文标签，**逐字照抄模板，不得改写**。
SUMMARY_LABEL_TEXTS: dict[tuple[str, int], str] = {
    (COL_LABEL, SUMMARY_ROW_1): "线下培训数量",
    (COL_ISSUE, SUMMARY_ROW_1): "线下售后数量",
    (COL_LABEL, SUMMARY_ROW_2): "线上售后数量",
    (COL_ISSUE, SUMMARY_ROW_2): "线下售前数量",
}
ISSUE_DEMAND_MERGES: tuple[tuple[str, int], ...] = (
    (f"{COL_LABEL}:{COL_DATE}", ISSUE_ROW_1),    # B19:C19
    (f"{COL_CONTENT}:{COL_SOLUTION}", ISSUE_ROW_1),  # D19:F19
    (f"{COL_LABEL}:{COL_DATE}", ISSUE_ROW_2),    # B20:C20
    (f"{COL_CONTENT}:{COL_SOLUTION}", ISSUE_ROW_2),  # D20:F20
    (f"{COL_LABEL}:{COL_DATE}", DEMAND_ROW_1),   # B21:C21
    (f"{COL_CONTENT}:{COL_SOLUTION}", DEMAND_ROW_1),  # D21:F21
    (f"{COL_LABEL}:{COL_DATE}", DEMAND_ROW_2),   # B22:C22
    (f"{COL_CONTENT}:{COL_SOLUTION}", DEMAND_ROW_2),  # D22:F22
)
# 计划区合并（B23:C26「主要工作安排」+ 每槽 D:F）由 fill.py 按实际行数动态重建
# （计划条数超出 4 个槽位时会在计划区末尾追加行，固定常量无法表达，故不再保留
#  PLAN_MERGES 常量——曾因它在追加行后只合并到旧行号导致新区间漏建）。


DEFAULT_ANCHORS = Anchors()


# ---- 结构校验 ---------------------------------------------------------------


class AnchorError(RuntimeError):
    """模板结构不符预期 —— 填充前必须阻断，绝不猜测写入位置。"""


def validate_template(ws, anchors: Anchors = DEFAULT_ANCHORS) -> None:
    """填充前校验模板结构。任何不符都抛 AnchorError 阻断。

    校验项（只查「写入依赖」的关键结构，避免对模板样式过度假设）：
    1. 有效区域至少到 A1:F26；
    2. 7 个星期块的位置存在且 B 列有星期标签（容许 B 合并后仅首行有值）；
    3. 汇总区块四个写入单元格所在行有对应标签文字。
    """
    if ws.max_row < anchors.total_rows or ws.max_column < 6:
        raise AnchorError(
            f"模板有效区域不足：实际 {ws.max_row} 行 × {ws.max_column} 列，"
            f"至少需要 {anchors.total_rows} 行 × 6 列"
        )

    # 星期块：B 列首行应能读到星期名（合并单元格只在首行有值）
    for b in anchors.weekdays:
        v = _cell_text(ws, f"{COL_LABEL}{b.start_row}")
        if not v:
            raise AnchorError(f"星期块缺失：{COL_LABEL}{b.start_row} 为空（应为「{b.label}」）")

    # 汇总四项：值单元格同一行必须有标签。
    # 标签列按模板结构确定：B/D 一组（值在 B→D），E/F 一组（值在 E→F）。
    label_col_for = {"D": COL_LABEL, "F": COL_ISSUE}
    for key, cell in anchors.summary_cells.items():
        row = int("".join(ch for ch in cell if ch.isdigit()))
        value_col = "".join(ch for ch in cell if ch.isalpha())
        label_col = label_col_for.get(value_col, COL_LABEL)
        v = _cell_text(ws, f"{label_col}{row}")
        if not v:
            raise AnchorError(
                f"工作汇总区块异常：{cell} 同行的 {label_col}{row} 为空，"
                f"无法确认「{key}」应写入何处（模板结构可能已变更）"
            )


def _cell_text(ws, ref: str) -> str:
    v = ws[ref].value
    return "" if v is None else str(v).strip()
