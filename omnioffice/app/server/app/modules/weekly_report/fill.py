"""模板填充引擎（V10 3.6.3 / 3.6.4 / 4.5）。

同日多条任务的四种场景（V10 原文）：
| 当天任务数 | 处理方式 |
|---|---|
| 0 条 | 该星期块全部留空，不写入 |
| 1 条 | 保持 D 列两行合并，内容写入合并单元格 |
| 2 条 | 取消 D 列合并，拆为两个独立单元格（D9、D10），各写一条 |
| 3 条及以上 | 块内插入新行，D 列逐行填写，同步扩展 B/C/E/F 合并区间 |

日期序列号（V10 3.6.4）：C 列写 Excel 序列号（1899-12-30 基准）并保留原日期格式，
**不得写文本**，否则模板中依赖日期的计算与展示会失效。

只写 D 列与 C 列；E/F 列（遇到的问题 / 解决办法）与 ISSUE / DEMAND 区块一律不写
（V10 明确要求：那两段由用户在校对界面手工录入）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Sequence

from copy import copy

from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .anchors import (
    COL_CONTENT,
    COL_DATE,
    COL_ISSUE,
    COL_LABEL,
    COL_SOLUTION,
    ISSUE_DEMAND_MERGES,
    PLAN_ROW_1,
    PLAN_ROW_2,
    SUMMARY_LABEL_MERGES,
    SUMMARY_LABEL_TEXTS,
    AnchorError,
    Anchors,
    DEFAULT_ANCHORS,
    validate_template,
)
from .row_shift import RowShifter

# Excel 1900 日期系统：序列号 1 = 1900-01-01，但含 1900 闰年 bug，
# 实际等价于「1899-12-30 为第 0 天」，故 2026-10-12 的序列号为 (date-1899-12-30).days。
_EXCEL_EPOCH = date(1899, 12, 30)

# 参考：模板示例 46230 = 2026-07-27（V10 3.6.4 给出）
assert (date(2026, 7, 27) - _EXCEL_EPOCH).days == 46230, "Excel 序列号基准错误"


def excel_serial(d: date) -> int:
    """日期 → Excel 序列号（1899-12-30 基准）。"""
    return (d - _EXCEL_EPOCH).days


@dataclass
class FillItem:
    """待写入的一条任务（已由调用方归一化）。"""

    weekday: int
    title: str
    start_at: str = ""
    end_at: str = ""
    status: str = ""


@dataclass
class FillPlan:
    """填充计划：每个星期块写什么 + 是否需要插行。"""

    per_weekday: dict[int, list[str]] = field(default_factory=dict)
    shifter: RowShifter = field(default_factory=RowShifter)
    stats: dict[str, int] = field(default_factory=dict)
    plan_titles: list[str] = field(default_factory=list)

    @property
    def inserted_rows(self) -> int:
        return self.shifter.total_inserted()

    @property
    def plan_extra_rows(self) -> int:
        """下周计划超出模板 4 个槽位需要追加的行数。"""
        return max(0, len(self.plan_titles) - anchors_default_plan_slots())


def anchors_default_plan_slots() -> int:
    return DEFAULT_ANCHORS.plan_slots


def _weekday_rows(weekday: int, count: int) -> int:
    """某星期块写入 count 条任务时，需要的总行数。"""
    if count <= 0:
        return 2  # 留空仍占原 2 行
    if count == 1:
        return 2  # 保持合并
    return count  # 2 条正好 2 行；3 条及以上需 3+ 行


def build_plan(
    items: Sequence[FillItem],
    anchors: Anchors = DEFAULT_ANCHORS,
    plan_texts: Sequence[str] = (),
) -> FillPlan:
    """先算「每个星期块写几条 + 插几行」，产出可校验的填充计划。

    与实际写文件分离，是为了让「行号重算」这一步可以被独立单测覆盖。
    plan_texts 为下周计划标题列表；超出模板槽位（默认 4）的部分通过在计划区
    末尾追加行容纳（计划区是全表最后一个区块，追加不影响任何既有行号）。
    """
    titles: dict[int, list[str]] = {b.weekday: [] for b in anchors.weekdays}
    for it in items:
        if it.weekday in titles and it.title.strip():
            titles[it.weekday].append(it.title.strip())

    plan = FillPlan(plan_titles=[t.strip() for t in plan_texts if t and t.strip()])
    shifter = RowShifter()
    for b in anchors.weekdays:
        lst = titles[b.weekday]
        plan.per_weekday[b.weekday] = lst
        need = _weekday_rows(b.weekday, len(lst))
        if need > 2:
            # 在本块起始行之前插入（保证本块原有 2 行仍保留，后续块顺移）
            shifter.add_insert(b.start_row, need - 2)
    plan.shifter = shifter
    shifter.validate_monotonic(anchors)
    return plan


# ------------------------------------------------------------------ 样式工具


def _copy_row_style(ws: Worksheet, src_row: int, dst_row: int) -> None:
    """把源行的行高与各列样式复制到目标行（插行后保持视觉一致）。"""
    ws.row_dimensions[dst_row].height = ws.row_dimensions[src_row].height
    for col in range(1, 7):
        letter = get_column_letter(col)
        src = ws[f"{letter}{src_row}"]
        dst = ws[f"{letter}{dst_row}"]
        if src.has_style:
            dst._style = src._style  # noqa: SLF001 —— openpyxl 复制样式的标准做法
        # alignment 属于不可变 StyleProxy，必须用 copy() 造新对象再赋值，
        # 直接把源代理赋过去会在 openpyxl 内部抛错（insert_rows 之后的常见崩溃点）。
        if src.has_style and src.alignment is not None:
            dst.alignment = copy(src.alignment)


def _unmerge(ws: Worksheet, ref: str) -> None:
    for rng in list(ws.merged_cells.ranges):
        if str(rng) == ref:
            ws.unmerge_cells(ref)


def _merge(ws: Worksheet, ref: str) -> None:
    if ref not in {str(r) for r in ws.merged_cells.ranges}:
        ws.merge_cells(ref)


def _clear_cell(ws: Worksheet, ref: str) -> None:
    """清空单元格，但绝不碰合并区里的只读格。

    步骤 4 会把块内 D 列整块合并（块高度 > 1 时）。合并之后只有左上角可写，
    其余行取到的是 `MergedCell`，对它赋值直接抛
    `AttributeError: 'MergedCell' object attribute 'value' is read-only`
    —— 清空样例内容这一步会整片崩掉，导出变成 FILL_FAILED 500。
    清掉左上角即等价于清掉整块，所以这里静默跳过即可。
    """
    cell = ws[ref]
    if isinstance(cell, MergedCell):
        return
    cell.value = None


def _style_content_cell(cell) -> None:
    """工作内容单元格样式：**以模板该格原有对齐为基准**，仅补自动换行。

    真实模板 D 列内容格是 horizontal=center / vertical=center（2026-10-13 逐格核对）。
    之前代码直接 new 一个 Alignment(vertical='center', wrap_text=True)，
    horizontal 退化为 General（左对齐），导出与模板肉眼可辨不一致。
    改为复制模板原 alignment 再开 wrap：模板居中则居中，模板改版也自动跟随。
    """
    base = cell.alignment
    cell.alignment = Alignment(
        horizontal=base.horizontal or "center",
        vertical=base.vertical or "center",
        wrap_text=True,
        text_rotation=base.text_rotation,
        indent=base.indent,
        shrink_to_fit=base.shrink_to_fit,
    )


def _write_series_date(ws: Worksheet, cell_ref: str, serial: int) -> None:
    """写 Excel 日期序列号，**保持原数字格式不变**（V10 3.6.4 硬要求）。

    真实模板实测（本周工作总结-46230-46236.xlsx）：C 列 7 个日期单元格
    46230~46236 的 number_format 全部是 ``General``，即模板刻意以纯数字显示序列号，
    并没有 yyyy-mm-dd 日期格式。

    因此本函数**不做任何格式改写** —— 只写值。理由：
    1. V10 只要求「保持 C 列原有的日期显示格式」，原格式就是 General；
    2. 擅自补 yyyy-mm-dd 会与模板其余单元格样式不一致，属于越权改动；
    3. 区域截图（T8 口径）渲染时用户看到的就是 46230，与模板手填时完全一致。

    若将来模板改成了真日期格式，这里写入 int 后 Excel 会自动按该格式显示，
    同样正确 —— 所以「只写值不碰格式」在两种模板下都成立。
    """
    ws[cell_ref].value = serial


# ------------------------------------------------------------------ 主入口


def fill_weekly_report(
    ws: Worksheet,
    items: Sequence[FillItem],
    period_start: str,
    summary_counts: dict[str, int | str] | None = None,
    anchors: Anchors = DEFAULT_ANCHORS,
    title_text: str = "",
    issue_text: str = "",
    demand_text: str = "",
    plan_texts: Sequence[str] = (),
) -> FillPlan:
    """填充周报工作表。

    写入内容：A1 标题（仅当显式传入，否则保留模板原标题）、C 列 7 个日期序列号、
    D 列各星期任务、工作汇总四项（D18 线上售后为文本「企微会话量：N次」）、
    重点问题/工作需求、下周工作计划。
    **不写** E/F 列星期块（遇到的问题/解决办法，用户手填）。

    版式保真原则（2026-10-13 与真实模板逐格比对后确立）：
    - 7 个星期块的 B/C/D/E/F 在**无数据时也保持整块合并**，与空模板完全一致；
    - 汇总区 D/E 列是独立格，绝不合并（合并会吞掉 E 列标签）；
    - 内容对齐跟随模板原样式（居中），仅开启自动换行。
    """
    validate_template(ws, anchors)

    plan = build_plan(items, anchors, plan_texts)
    shifter = plan.shifter

    # ---- 1. 标题（A1:F1 已合并，只写 A1）
    if title_text:
        ws[anchors.title_cell] = title_text

    # ---- 2. 解除全部合并（仅保留标题 A1:F1）
    #
    # 顺序很关键：openpyxl 的 insert_rows **不会**修正合并区间，插行后旧的
    # B3:B4 / D3:D4 仍挂在原处，会把新行里的单元格变成只读 MergedCell，
    # 后续写 D5 直接抛 'MergedCell' object attribute 'value' is read-only。
    # 因此必须「先全解 → 再插行 → 最后按实际行重建」。
    #
    # 判定标题合并必须比对**完整区间**（A1:F1），不能startswith("A1:") ——
    # 那会误判 A17:A18 / A19:A20 这类以 A1 开头的汇总区合并，导致旧区间残留、
    # 与重建后的新区间叠加（曾导致 A2:A20 这种跨区错位）。
    title_rng = anchors.title_cell
    for rng in list(ws.merged_cells.ranges):
        s = str(rng)
        if s == title_rng or s == f"A1:F1":
            continue
        _unmerge(ws, s)

    # ---- 3. 星期块插行（从后往前插，保证前面块的基准行号不受影响）
    for base_row, n in sorted(shifter.extra_before.items(), key=lambda kv: kv[0], reverse=True):
        at = shifter.actual(base_row)
        ws.insert_rows(at, amount=n)
        # 新行样式取本块原有首行，保持行高与字体一致
        _copy_row_style(ws, at + n, at)

    # ---- 4. C 列日期序列号 + B/C/D/E/F 五列整块合并重建
    #
    # D 列也按整块合并 —— 模板空表的 D3:D4…D15:D16 本就全部合并；
    # 当天有 2 条及以上任务时，在步骤 5 再拆开 D 列逐行写。
    # 星期块用 block_actual：块内扩展时块高度同步增长，用 actual() 算结束行会与
    # 起始行算出重叠区间（曾导致星期日块与汇总区合并错位）。
    ps = date.fromisoformat(period_start)
    last_weekday_end = 0
    for b in anchors.weekdays:
        actual_start, actual_end = shifter.block_actual(b.start_row, b.end_row)
        last_weekday_end = max(last_weekday_end, actual_end)
        _write_series_date(
            ws, f"{COL_DATE}{actual_start}", excel_serial(ps + timedelta(days=b.weekday - 1))
        )
        ws[f"{COL_LABEL}{actual_start}"] = b.label
        if actual_end > actual_start:
            for col in (COL_LABEL, COL_DATE, COL_CONTENT, COL_ISSUE, COL_SOLUTION):
                _merge(ws, f"{col}{actual_start}:{col}{actual_end}")

    # ---- 5. D 列任务内容（四场景）+ 下周计划区
    #
    # 先统一清空模板样例（星期块 D 列与计划区 D 列都带上周示例），
    # 不清会与本次数据混在一起，让用户以为识别出错。
    for b in anchors.weekdays:
        actual_start, actual_end = shifter.block_actual(b.start_row, b.end_row)
        for r in range(actual_start, actual_end + 1):
            _clear_cell(ws, f"{COL_CONTENT}{r}")

    # 下周计划区：先算实际行（可能因星期块插行而下移），再在其**末尾之后**追加
    # 超出槽位的行。计划区是全表最后一个区块，末尾追加不移动任何既有行。
    plan_start = shifter.actual(PLAN_ROW_1)
    plan_end_base = shifter.actual(PLAN_ROW_2)
    plan_extra = plan.plan_extra_rows
    if plan_extra > 0:
        insert_at = plan_end_base + 1
        ws.insert_rows(insert_at, amount=plan_extra)
        for k in range(plan_extra):
            _copy_row_style(ws, plan_end_base, insert_at + k)
    plan_end = plan_end_base + plan_extra

    for r in range(plan_start, plan_end + 1):
        _clear_cell(ws, f"{COL_CONTENT}{r}")

    for b in anchors.weekdays:
        titles = plan.per_weekday[b.weekday]
        actual_start, actual_end = shifter.block_actual(b.start_row, b.end_row)
        if not titles:
            continue  # 0 条：整块留空（D 合并已在步骤 4 建好，版式与空模板一致）
        if len(titles) == 1:
            # 1 条：D 已是整块合并，直接写锚点格
            cell = ws[f"{COL_CONTENT}{actual_start}"]
            cell.value = titles[0]
            _style_content_cell(cell)
        else:
            # 2 条及以上：拆开 D 列合并，逐行填写（3 条以上时块已在步骤 3 扩行）
            _unmerge(ws, f"{COL_CONTENT}{actual_start}:{COL_CONTENT}{actual_end}")
            for i, t in enumerate(titles):
                c = ws[f"{COL_CONTENT}{actual_start + i}"]
                c.value = t
                _style_content_cell(c)

    # 下周计划逐条写入 D:F 合并槽位
    for i, t in enumerate(plan.plan_titles):
        c = ws[f"{COL_CONTENT}{plan_start + i}"]
        c.value = t
        _style_content_cell(c)

    # ---- 6. 工作汇总四项（V10 3.6.6）
    #
    # 解除/重建合并过程中 E17/E18 标签可能已被 openpyxl 清掉，
    # 先把四个标签**逐字写回**，再写统计值。
    # D18「线上售后数量」按模板口径写文本「企微会话量：N次」（调用方传字符串）；
    # D17/F17/F18 写整数。D/E 列保持独立格，绝不做任何合并。
    for (col, base_row), text in SUMMARY_LABEL_TEXTS.items():
        ws[f"{col}{shifter.actual(base_row)}"] = text
    if summary_counts:
        for key, base_ref in anchors.summary_cells.items():
            if key not in summary_counts:
                continue
            ref = shifter.actual_ref(base_ref)
            value = summary_counts[key]
            if isinstance(value, bool):
                ws[ref] = str(value)
            elif isinstance(value, (int, float)):
                ws[ref] = int(value)
            else:
                ws[ref] = str(value)

    # ---- 6.1 重点问题跟进 / 工作需求（用户手工录入，每行一条）
    #
    # 模板各两个槽位（19/20 行、21/22 行）；用户文本按非空行拆分，
    # 第 1 条进槽位 1，其余并入槽位 2（换行连接，单元格自动换行显示）。
    def _split_lines(text: str) -> list[str]:
        return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    issue_lines = _split_lines(issue_text)
    demand_lines = _split_lines(demand_text)
    manual_slots: dict[int, list[str]] = {
        anchors.issue_row_range[0]: issue_lines[:1],
        anchors.issue_row_range[1]: issue_lines[1:],
        anchors.demand_row_range[0]: demand_lines[:1],
        anchors.demand_row_range[1]: demand_lines[1:],
    }
    for base_row, parts in manual_slots.items():
        r = shifter.actual(base_row)
        cell = ws[f"{COL_CONTENT}{r}"]
        if isinstance(cell, MergedCell):
            continue
        # 手工录入区：**没有内容就一个字都不要写**。
        # 早先这里无条件 `cell.value = "\n".join(parts) if parts else None`，
        # 于是用户没填也会把模板里已有的手工内容清成 None —— 而这一区是
        # 「用户手工录入」，填充逻辑本来就不该碰它（覆盖 = 用户数据丢失）。
        if not parts:
            continue
        cell.value = "\n".join(parts)
        _style_content_cell(cell)

    # ---- 7. 重建 A 列竖排区块标题的合并区间
    #
    # 解除合并时一并解掉了 A 列区块标题（它们跨多行，插行后跨度会变）。
    # 「本周工作」竖排标题必须覆盖到**最后一个星期块的实际结束行**。
    # 注意：last_weekday_end 已经是「实际行号」（步骤 4 用 block_actual 算出），
    # 这里不能再过 shifter.actual_row_range —— 那会二次偏移，曾导致 A2:A20 跨进汇总区。
    a_regions = [
        (2, last_weekday_end, "week"),                            # 本周工作（起点固定 2）
        (*anchors.summary_row_range, "shift"),                    # 工作汇总
        (*anchors.issue_row_range, "shift"),                      # 重点问题
        (*anchors.demand_row_range, "shift"),                     # 工作需求
        (PLAN_ROW_1, PLAN_ROW_2, "plan"),                         # 下周计划（含追加行）
    ]
    for s, e, kind in a_regions:
        if kind == "week":
            a_s, a_e = 2, e  # 本周工作区：起点固定为 2，终点直接用实际行
        elif kind == "plan":
            a_s, a_e = plan_start, plan_end
        else:
            a_s, a_e = shifter.actual_row_range(s, e)
        if a_e > a_s:
            _merge(ws, f"A{a_s}:A{a_e}")

    # 下游区块的合并区间重建
    #
    # 解除合并（第 2 步）会把汇总标签(B:C)、问题/需求填写区(D:F)
    # 一并解掉。若不重建，用户在这些区填一个字就会把表格视觉撑破。
    # 注意：汇总区 D/E 是独立格，**不重建任何 D:E 合并**（曾吞掉 E 列标签）。
    for row in SUMMARY_LABEL_MERGES:
        r = shifter.actual(row[0])
        _merge(ws, f"{COL_LABEL}{r}:{COL_DATE}{r}")
    for colspec, row in ISSUE_DEMAND_MERGES:
        r = shifter.actual(row)
        c1, c2 = colspec.split(":")
        _merge(ws, f"{c1}{r}:{c2}{r}")

    # 下周计划区：B:C 整块合并「主要工作安排」，每条计划 D:F 横向合并
    _merge(ws, f"{COL_LABEL}{plan_start}:{COL_DATE}{plan_end}")
    for r in range(plan_start, plan_end + 1):
        _merge(ws, f"{COL_CONTENT}{r}:{COL_SOLUTION}{r}")

    # ---- 8. 行号校验（V10：填充完成后做一次行号校验）
    shifter.validate_monotonic(anchors)

    return plan
