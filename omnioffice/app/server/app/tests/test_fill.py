"""填充引擎单测（V10 3.6.3 四场景 + 3.6.4 序列号 + 行号重算）。

本模块是全项目最容易静默出错的地方：
- 插行后工作汇总/问题/需求/计划整体错位（线上只表现为「导出的表不对」，不报错）；
- C 列写成文本而非序列号（Excel 里日期显示成 46230，用户以为坏了）；
- 合并区间与实际行数不匹配（LibreOffice 渲染时截图错位）。

因此对四场景、偏移累加、序列号基准、结构校验阻断都做了显式断言。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from openpyxl import Workbook

from app.modules.weekly_report.anchors import (
    DEFAULT_ANCHORS,
    AnchorError,
    validate_template,
)
from app.modules.weekly_report.fill import (
    FillItem,
    build_plan,
    excel_serial,
    fill_weekly_report,
)
from app.modules.weekly_report.row_shift import RowShifter

PERIOD = "2026-10-12"  # 周一


def make_template() -> "Workbook":
    """按 V10 3.6.2/3.6.5 造一个结构合规的模板。

    合并规则：A1:F1 标题；A2:A16 区块标题；每个星期块 B/C/D/E/F 各跨 2 行；
    A17:A18 / A19:A20 / A21:A22 / A23:A26 竖排标题；B23:C26 合并。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    ws.merge_cells("A1:F1")
    ws["A1"] = "本周工作总结"

    # A2:A16 本周工作区竖排标题
    ws.merge_cells("A2:A16")
    ws["A2"] = "本周工作"

    names = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
    for i, name in enumerate(names):
        r = 3 + i * 2
        for col in ("B", "C", "D", "E", "F"):
            ws.merge_cells(f"{col}{r}:{col}{r+1}")
        ws[f"B{r}"] = name

    # C 列原始日期格式（模板里是日期格式，填充必须保留）
    for i in range(7):
        r = 3 + i * 2
        ws[f"C{r}"].number_format = "yyyy-mm-dd"

    ws.merge_cells("A17:A18")
    ws["B17"] = "线下培训数量"
    ws["E17"] = "线下售后数量"
    ws["B18"] = "线上售后数量"
    ws["E18"] = "线下售前数量"

    ws.merge_cells("A19:A20")
    ws["B19"] = "问题一"
    ws["B20"] = "问题二"

    ws.merge_cells("A21:A22")
    ws["B21"] = "需求一"
    ws["B22"] = "需求二"

    ws.merge_cells("A23:A26")
    ws.merge_cells("B23:C26")
    ws["B23"] = "主要工作安排"
    return wb


def merged_set(ws) -> set[str]:
    return {str(r) for r in ws.merged_cells.ranges}


def sheet(ws, ref: str):
    return ws[ref].value


class TestExcelSerial(unittest.TestCase):
    """V10 3.6.4：序列号基准 1899-12-30。"""

    def test_known_value_from_spec(self):
        # V10 文档给出的对照：46230 = 2026-07-27（星期一）
        self.assertEqual(excel_serial(date(2026, 7, 27)), 46230)

    def test_consecutive_days_differ_by_one(self):
        a = excel_serial(date(2026, 10, 12))
        b = excel_serial(date(2026, 10, 13))
        self.assertEqual(b - a, 1)

    def test_period_week_seven_days(self):
        ps = date(2026, 10, 12)
        serials = [excel_serial(ps + timedelta(days=i)) for i in range(7)]
        self.assertEqual(serials, [excel_serial(date(2026, 10, 12 + i)) for i in range(7)])
        self.assertEqual(serials[-1] - serials[0], 6)


class TestRowShifter(unittest.TestCase):
    """行号偏移映射。"""

    def test_no_shift(self):
        s = RowShifter()
        self.assertEqual(s.actual(17), 17)

    def test_single_shift(self):
        s = RowShifter()
        s.add_insert(3, 2)
        self.assertEqual(s.actual(3), 3, "块首行不偏移（插入发生在块内部）")
        self.assertEqual(s.actual(17), 19)

    def test_accumulate_multiple(self):
        s = RowShifter()
        s.add_insert(3, 1)   # 星期一 +1 行
        s.add_insert(9, 3)   # 星期四 +3 行
        # 块首行不偏移（插入发生在块内部），只有后续行累计位移
        self.assertEqual(s.actual(3), 3)
        self.assertEqual(s.actual(9), 10)   # 只受星期一 +1 影响
        self.assertEqual(s.actual(17), 21)  # 1 + 3 = +4
        self.assertEqual(s.total_inserted(), 4)

    def test_ref_conversion(self):
        s = RowShifter()
        s.add_insert(3, 2)
        self.assertEqual(s.actual_ref("D17"), "D19")

    def test_block_internal_expansion_preserves_order(self):
        """块内扩展无论插多少行，后续块整体顺移、顺序始终合法（不得误报）。"""
        s = RowShifter()
        s.add_insert(3, 10)
        s.validate_monotonic(DEFAULT_ANCHORS)  # 不抛异常即通过
        self.assertEqual(s.actual(17), 27, "汇总块应整体下移 10 行")

    def test_monotonic_validation_catches_bad_anchor_set(self):
        """校验的价值：拦住「锚点集合本身错乱」导致的区块错位。

        对应真实风险：模板结构变更后锚点常量没同步，越写越乱且不报错。
        这里把汇总区起点塞进星期块内部，校验必须拦下。
        """
        from dataclasses import replace

        broken = replace(DEFAULT_ANCHORS, summary_row_range=(4, 5))
        s = RowShifter()
        with self.assertRaises(AssertionError) as ctx:
            s.validate_monotonic(broken)
        self.assertIn("行号校验失败", str(ctx.exception))

    def test_monotonic_validation_catches_inverted_region(self):
        """区块首尾倒置（如计划区 end < start）必须报错。"""
        from dataclasses import replace

        broken = replace(DEFAULT_ANCHORS, plan_row_range=(30, 20))
        s = RowShifter()
        with self.assertRaises(AssertionError):
            s.validate_monotonic(broken)


class TestBuildPlan(unittest.TestCase):
    """填充计划：先算插多少行，再决定怎么写。"""

    def test_zero_one_two_three_rows(self):
        p = build_plan([])
        self.assertEqual(p.inserted_rows, 0)

        p = build_plan([FillItem(weekday=1, title="A")])
        self.assertEqual(p.inserted_rows, 0, "1 条保持合并，不插行")

        p = build_plan([FillItem(weekday=1, title="A"), FillItem(weekday=1, title="B")])
        self.assertEqual(p.inserted_rows, 0, "2 条正好用满 2 行，不插行")

        p = build_plan([FillItem(weekday=1, title="x%d" % i) for i in range(3)])
        self.assertEqual(p.inserted_rows, 1, "3 条需 1 行")

    def test_multiple_weekdays_accumulate(self):
        p = build_plan(
            [FillItem(weekday=1, title="a%d" % i) for i in range(3)]
            + [FillItem(weekday=4, title="b%d" % i) for i in range(4)]
        )
        # 星期一 +1 行；星期四 +2 行 → 共 3
        self.assertEqual(p.inserted_rows, 3)

    def test_invalid_weekday_ignored(self):
        """非法星期（1~7 之外）应被忽略，不得凭空建块。"""
        p = build_plan([FillItem(weekday=9, title="x")])
        self.assertEqual(p.inserted_rows, 0)
        self.assertEqual(sum(len(v) for v in p.per_weekday.values()), 0)


class TestFillScenarios(unittest.TestCase):
    """四场景真实写入验证。"""

    def _filled(self, items, summary=None):
        wb = make_template()
        ws = wb.active
        plan = fill_weekly_report(ws, items, PERIOD, summary_counts=summary)
        return ws, plan

    def test_scenario_0_tasks_leaves_blank(self):
        ws, plan = self._filled([])
        for i in range(7):
            r = 3 + i * 2
            self.assertIsNone(ws[f"D{r}"].value, f"星期{i+1} D 列应留空")
        self.assertEqual(plan.inserted_rows, 0)

    def test_scenario_1_task_keeps_merge(self):
        ws, plan = self._filled([FillItem(weekday=1, title="唯一任务")])
        self.assertIn("D3:D4", merged_set(ws), "1 条应保持 D3:D4 合并")
        self.assertEqual(ws["D3"].value, "唯一任务")

    def test_scenario_2_tasks_splits_merge(self):
        ws, _ = self._filled([FillItem(weekday=1, title="任务A"), FillItem(weekday=1, title="任务B")])
        self.assertNotIn("D3:D4", merged_set(ws), "2 条应取消 D 列合并")
        self.assertEqual(ws["D3"].value, "任务A")
        self.assertEqual(ws["D4"].value, "任务B")

    def test_scenario_3_tasks_inserts_row(self):
        ws, plan = self._filled([FillItem(weekday=1, title=f"任务{i}") for i in range(3)])
        self.assertEqual(plan.inserted_rows, 1)
        self.assertEqual(ws["D3"].value, "任务0")
        self.assertEqual(ws["D4"].value, "任务1")
        self.assertEqual(ws["D5"].value, "任务2")

    def test_weekday_four_two_tasks_no_insert(self):
        """V10 3.6.3 明确举例：星期四两条 → D9/D10 各写一条，不插行。"""
        ws, plan = self._filled([FillItem(weekday=4, title="周四A"), FillItem(weekday=4, title="周四B")])
        self.assertEqual(plan.inserted_rows, 0)
        self.assertEqual(ws["D9"].value, "周四A")
        self.assertEqual(ws["D10"].value, "周四B")

    def test_multiple_weekdays_independent(self):
        ws, _ = self._filled(
            [
                FillItem(weekday=1, title="周一任务"),
                FillItem(weekday=2, title="周二任务1"),
                FillItem(weekday=2, title="周二任务2"),
            ]
        )
        self.assertEqual(ws["D3"].value, "周一任务")
        self.assertEqual(ws["D5"].value, "周二任务1")
        self.assertEqual(ws["D6"].value, "周二任务2")


class TestDateSerialWritten(unittest.TestCase):
    """V10 3.6.4：C 列必须写序列号且保留日期格式。"""

    def test_serial_values_seven_days(self):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(ws, [], PERIOD)
        ps = date(2026, 10, 12)
        for i in range(7):
            r = 3 + i * 2
            v = ws[f"C{r}"].value
            self.assertIsInstance(v, int, f"C{r} 应为整数序列号，实际 {type(v)}: {v!r}")
            self.assertEqual(v, excel_serial(ps.replace(day=12) + __import__("datetime").timedelta(days=i)))

    def test_date_format_preserved(self):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(ws, [], PERIOD)
        for i in range(7):
            r = 3 + i * 2
            fmt = ws[f"C{r}"].number_format
            self.assertIn("y", fmt.lower(), f"C{r} 应保留日期格式，实际 {fmt!r}")

    def test_not_written_as_text(self):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(ws, [], PERIOD)
        v = ws["C3"].value
        self.assertNotIsInstance(v, str, "C 列不得写成文本")


class TestInsertShiftsDownstreamBlocks(unittest.TestCase):
    """插行后所有后续区块必须整体下移（V10 3.6.3 硬要求）。"""

    def test_summary_block_shifts_by_1(self):
        wb = make_template()
        ws = wb.active
        plan = fill_weekly_report(
            ws,
            [FillItem(weekday=1, title=f"T{i}") for i in range(3)],
            PERIOD,
            summary_counts={"training": 1, "offline_service": 2, "online_service": 3, "presale": 4},
        )
        self.assertEqual(plan.inserted_rows, 1)
        # 原 D17 → 实际 D18（星期一插了 1 行）
        self.assertEqual(ws["D18"].value, 1, "线下培训数量应下移一行")
        self.assertEqual(ws["F18"].value, 2, "线下售后数量应下移一行")
        self.assertEqual(ws["D19"].value, 3, "线上售后数量应下移一行")
        self.assertEqual(ws["F19"].value, 4, "线下售前数量应下移一行")

    def test_summary_writes_without_insert(self):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(
            ws,
            [],
            PERIOD,
            summary_counts={"training": 5, "offline_service": 6, "online_service": 7, "presale": 8},
        )
        self.assertEqual(ws["D17"].value, 5)
        self.assertEqual(ws["F17"].value, 6)
        self.assertEqual(ws["D18"].value, 7)
        self.assertEqual(ws["F18"].value, 8)

    def test_two_weekday_inserts_shift_by_2(self):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(
            ws,
            [FillItem(weekday=1, title=f"A{i}") for i in range(3)]
            + [FillItem(weekday=4, title=f"B{i}") for i in range(4)],
            PERIOD,
            summary_counts={"training": 1},
        )
        # 星期一 +1、星期四 +2 → 汇总前累计 3 行
        self.assertEqual(ws["D20"].value, 1)

    def test_issue_demand_plan_blocks_not_overwritten(self):
        """E/F 与 ISSUE/DEMAND 区块属用户手工录入区，填充不得写入。"""
        wb = make_template()
        ws = wb.active
        ws["D19"] = "用户手填的问题一"
        ws["D21"] = "用户手填的需求一"
        fill_weekly_report(ws, [FillItem(weekday=1, title="X")], PERIOD, summary_counts={"training": 1})
        self.assertEqual(ws["D19"].value, "用户手填的问题一", "重点问题区不应被覆盖")
        self.assertEqual(ws["D21"].value, "用户手填的需求一", "工作需求区不应被覆盖")


class TestTemplateValidation(unittest.TestCase):
    """填充前结构校验：不符即阻断，绝不猜测写入位置。"""

    def test_valid_template_passes(self):
        wb = make_template()
        validate_template(wb.active)  # 不抛异常即通过

    def test_missing_rows_blocked(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        with self.assertRaises(AnchorError):
            validate_template(ws)

    def test_missing_weekday_label_blocked(self):
        wb = make_template()
        ws = wb.active
        ws["B3"] = None
        with self.assertRaises(AnchorError) as ctx:
            validate_template(ws)
        self.assertIn("星期块缺失", str(ctx.exception))

    def test_missing_summary_label_blocked(self):
        wb = make_template()
        ws = wb.active
        ws["B17"] = None  # 清掉「线下培训数量」标签
        with self.assertRaises(AnchorError) as ctx:
            validate_template(ws)
        self.assertIn("工作汇总", str(ctx.exception))

    def test_missing_summary_label_f18_blocked(self):
        """F17 的标签在 E17，只清 B17 不应误报 —— 校验要按各自标签列走。"""
        wb = make_template()
        ws = wb.active
        ws["E17"] = None  # 清掉「线下售后数量」标签
        with self.assertRaises(AnchorError) as ctx:
            validate_template(ws)
        self.assertIn("工作汇总", str(ctx.exception))

    def test_fill_refuses_invalid_template(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        with self.assertRaises(AnchorError):
            fill_weekly_report(ws, [FillItem(weekday=1, title="X")], PERIOD)


class TestDoesNotWriteEFColumns(unittest.TestCase):
    """只写 D/C：E（遇到的问题）F（解决办法）不得被填。"""

    def test_ef_untouched(self):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(ws, [FillItem(weekday=1, title="任务")], PERIOD)
        for r in range(3, 17):
            self.assertIsNone(ws[f"E{r}"].value, f"E{r} 不应被写入")
            self.assertIsNone(ws[f"F{r}"].value, f"F{r} 不应被写入")


class TestColumnAMerges(unittest.TestCase):
    """A 列竖排区块标题的合并区间（最容易错位的一处）。

    曾两次出错：
    1. 用 startswith("A1:") 判定标题合并 → 误跳过 A17:A18/A19:A20 等汇总区合并；
    2. 把已是「实际行号」的 last_weekday_end 又过了一次 shifter → A2:A20 跨进汇总区。
    """

    def _a_merges(self, items):
        wb = make_template()
        ws = wb.active
        fill_weekly_report(ws, items, PERIOD)
        return sorted(str(r) for r in ws.merged_cells.ranges if str(r)[0] == "A")

    def test_no_insert_matches_template(self):
        ms = self._a_merges([FillItem(weekday=1, title="x")])
        for expect in ("A1:F1", "A2:A16", "A17:A18", "A19:A20", "A21:A22", "A23:A26"):
            self.assertIn(expect, ms, f"无插行时应与模板一致，缺 {expect}")

    def test_insert_shifts_all_a_regions(self):
        """星期四 4 条 → 插 2 行，所有 A 列区块整体下移 2。"""
        ms = self._a_merges([FillItem(weekday=4, title=f"w{i}") for i in range(4)])
        self.assertIn("A2:A18", ms, "本周工作区应到星期日块实际末行 18")
        self.assertIn("A19:A20", ms, "工作汇总应下移到 19-20")
        self.assertIn("A21:A22", ms)
        self.assertIn("A23:A24", ms)
        self.assertIn("A25:A28", ms)

    def test_a_regions_never_overlap(self):
        """任意插行量下，A 列各区块合并不得重叠（重叠=区块标题串位）。"""

        def ranges(ms):
            out = []
            for m in ms:
                if ":" not in m:
                    continue
                a, b = m.split(":")
                r1 = int("".join(c for c in a if c.isdigit()))
                r2 = int("".join(c for c in b if c.isdigit()))
                out.append((m, r1, r2))
            return sorted(out, key=lambda x: x[1])

        for n_task in (1, 3, 5, 8):
            ms = self._a_merges([FillItem(weekday=1, title=f"t{i}") for i in range(n_task)])
            rs = [r for r in ranges(ms) if r[0] != "A1:F1"]
            for i in range(len(rs) - 1):
                self.assertLess(
                    rs[i][2], rs[i + 1][1],
                    f"任务 {n_task} 条时 A 列区块重叠：{rs[i][0]} 与 {rs[i+1][0]}",
                )

    def test_multiple_blocks_insert(self):
        """两块都插行时，A 列合并需按累计偏移下移且不重叠。"""
        ms = self._a_merges(
            [FillItem(weekday=1, title=f"a{i}") for i in range(4)]
            + [FillItem(weekday=6, title=f"b{i}") for i in range(5)]
        )
        # 星期一 +2、星期六 +3 → 累计 5
        self.assertIn("A2:A21", ms)
        self.assertIn("A22:A23", ms)


if __name__ == "__main__":
    unittest.main()
