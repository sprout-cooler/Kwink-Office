"""真实模板回归测试（基准文件：本周工作总结-46230-46236.xlsx）。

**为什么必须有这组测试**：填充引擎最初是按 V10 需求文档的文字描述实现的，
接入真实模板后发现 5 处文档未描述或描述不准的细节 —— 见下方各测试的说明。
纯人工造模板的单测无法发现这类偏差，必须拿真实文件跑。

真实模板实测要点（2026-10-12 核对）：
- 单工作表，有效区域 A1:F26，共 56 个合并区域；
- C 列 7 个日期是 **int 序列号**（46230~46236），但 number_format 全是 ``General``
  —— 模板刻意以纯数字显示，**不是** yyyy-mm-dd 日期格式；
- 星期四 D9/D10 在模板里就**没有合并**（两条内容各占一格），说明「2 条拆两格」
  是模板既有做法，不是引擎要新造的；
- 汇总区标签是 **B:C 两列合并**（B17:C17 / B18:C18），不是只占 B；
- 第 2 行是表头行（B2:C2 合并 + '时间' / '工作内容' / '遇到的问题' / '解决办法'）；
- 模板内 D 列带上一周样例内容（'韶关-学成口腔…' 等），填充时必须清空；
- 汇总区 D18 原值是文本「企微会话量：484次」（V10 已说明会改为按条数统计）。
"""
from __future__ import annotations

import shutil
import unittest
from datetime import date, timedelta
from pathlib import Path

from openpyxl import load_workbook

from app.modules.weekly_report.anchors import DEFAULT_ANCHORS, AnchorError, validate_template
from app.modules.weekly_report.fill import FillItem, excel_serial, fill_weekly_report

FIXTURE = Path(__file__).parent / "fixtures" / "template_weekly.xlsx"
PERIOD = "2026-10-12"  # 周一


def fresh() -> "object":
    """每次都从基准模板重新载入，保证用例互不干扰（填充会改文件）。"""
    if not FIXTURE.is_file():
        raise unittest.SkipTest(f"缺少真实模板基准文件：{FIXTURE}")
    return load_workbook(FIXTURE)


def col_of(ref: str) -> str:
    return "".join(c for c in ref if c.isalpha())


class TestRealTemplateStructure(unittest.TestCase):
    """真实模板的结构事实（锁死基准，防止模板更新后引擎静默失配）。"""

    def setUp(self):
        self.ws = fresh().active

    def test_sheet_name_and_extent(self):
        self.assertEqual(self.ws.title, "Sheet1")
        self.assertGreaterEqual(self.ws.max_row, 26)
        self.assertGreaterEqual(self.ws.max_column, 6)

    def test_pass_validate_template(self):
        validate_template(self.ws)  # 不抛异常即通过

    def test_real_c_column_is_general_format(self):
        """关键事实：C 列是 General 而非日期格式 —— 写入时不得改格式。"""
        for i in range(7):
            r = 3 + i * 2
            c = self.ws[f"C{r}"]
            self.assertIsInstance(c.value, int, f"C{r} 应为 int 序列号")
            self.assertEqual(c.number_format, "General", f"C{r} 原格式应为 General")

    def test_real_serial_matches_spec(self):
        """模板里的 46230 必须等于 2026-07-27（V10 3.6.4 对照值）。"""
        self.assertEqual(self.ws["C3"].value, excel_serial(date(2026, 7, 27)))
        self.assertEqual(self.ws["C3"].value, 46230)

    def test_summary_labels_span_two_columns(self):
        """真实模板汇总区标签是 B:C 合并，不是单列。"""
        ms = {str(r) for r in self.ws.merged_cells.ranges}
        self.assertIn("B17:C17", ms, "汇总标签应跨 B:C")
        self.assertIn("B18:C18", ms)

    def test_issue_and_demand_write_areas_span_d_to_f(self):
        ms = {str(r) for r in self.ws.merged_cells.ranges}
        for ref in ("D19:F19", "D20:F20", "D21:F21", "D22:F22"):
            self.assertIn(ref, ms, f"{ref} 填写区应跨 D:F")

    def test_plan_slots_are_four(self):
        ms = {str(r) for r in self.ws.merged_cells.ranges}
        for ref in ("D23:F23", "D24:F24", "D25:F25", "D26:F26"):
            self.assertIn(ref, ms, f"计划位 {ref} 缺失")

    def test_template_carries_sample_content(self):
        """模板 D 列带上一周样例内容 —— 填充必须清空，否则与新数据混淆。"""
        d5 = self.ws["D5"].value
        self.assertTrue(d5, "模板 D5 应有样例内容（用于验证清空逻辑）")
        self.assertIn("售后回访", str(d5))


class TestFillOnRealTemplate(unittest.TestCase):
    """在真实模板上跑四场景 + 插行 + 下游区块。"""

    def _fill(self, items, summary=None):
        ws = fresh().active
        plan = fill_weekly_report(ws, items, PERIOD, summary_counts=summary)
        return ws, plan

    def test_serial_written_without_touching_format(self):
        """写入新周期序列号，且 number_format 仍为 General。"""
        ws, _ = self._fill([])
        ps = date(2026, 10, 12)
        for i in range(7):
            r = 3 + i * 2
            c = ws[f"C{r}"]
            self.assertIsInstance(c.value, int)
            self.assertEqual(c.value, excel_serial(ps + timedelta(days=i)))
            self.assertEqual(c.number_format, "General", "填充不得改写 C 列数字格式")

    def test_sample_content_cleared(self):
        """模板样例内容必须被清空，不与新数据混排。"""
        ws, _ = self._fill([FillItem(weekday=1, title="新任务A")])
        self.assertEqual(ws["D5"].value, None, "D5 样例内容应被清空")
        self.assertEqual(ws["D3"].value, "新任务A")

    def test_plan_area_sample_cleared(self):
        """下周计划位 D23~D26 的样例内容同样要清空。"""
        ws, _ = self._fill([])
        for r in range(23, 27):
            self.assertIsNone(ws[f"D{r}"].value, f"D{r} 计划位样例应被清空")

    def test_single_task_keeps_merge(self):
        ws, plan = self._fill([FillItem(weekday=1, title="唯一")])
        self.assertEqual(plan.inserted_rows, 0)
        self.assertIn("D3:D4", {str(r) for r in ws.merged_cells.ranges})
        self.assertEqual(ws["D3"].value, "唯一")

    def test_two_tasks_split_merge(self):
        ws, plan = self._fill(
            [FillItem(weekday=4, title="周四A"), FillItem(weekday=4, title="周四B")]
        )
        self.assertEqual(plan.inserted_rows, 0, "2 条正好用满 2 行，不需插行")
        ms = {str(r) for r in ws.merged_cells.ranges}
        self.assertNotIn("D9:D10", ms, "2 条应拆为两个独立格")
        self.assertEqual(ws["D9"].value, "周四A")
        self.assertEqual(ws["D10"].value, "周四B")

    def test_three_tasks_insert_row_and_shift_all(self):
        """3 条 → 插 1 行，所有下游区块整体下移且合并完整。"""
        ws, plan = self._fill(
            [FillItem(weekday=4, title=f"T{i}") for i in range(3)],
            summary={"training": 1, "offline_service": 4, "online_service": 2, "presale": 0},
        )
        self.assertEqual(plan.inserted_rows, 1)
        self.assertEqual(ws.max_row, 27)

        # 任务写入
        self.assertEqual([ws[f"D{r}"].value for r in (9, 10, 11)], ["T0", "T1", "T2"])

        # 汇总区下移 1 行：原 D17/F17/D18/F18 → D18/F18/D19/F19
        self.assertEqual(ws["D18"].value, 1)
        self.assertEqual(ws["F18"].value, 4)
        self.assertEqual(ws["D19"].value, 2)
        self.assertEqual(ws["F19"].value, 0)

        ms = {str(r) for r in ws.merged_cells.ranges}
        # 汇总标签（B:C）必须重建
        self.assertIn("B18:C18", ms, "汇总标签合并丢失")
        # 汇总填写区 D/E 是**独立格** —— 模板实测如此（B17:C17/B18:C18 才是标签
        # 合并，D/E 列从未合并）。fill 的注释「汇总区 D/E 是独立格，不重建任何
        # D:E 合并（曾吞掉 E 列标签）」说的就是这件事。
        # 这里反过来断言「不得出现 D:E 合并」，防止有人手滑把它「补」上：
        # D:E 一旦合并，用户填完 D 格就再也点不到 E 格。
        self.assertNotIn("D18:E18", ms, "汇总填写区 D/E 应为独立格，不得合并")
        self.assertNotIn("D17:D18", ms, "模板汇总区 D 列本就是逐格填写，不存在竖排合并")
        # 汇总区上方的竖排合并不受插行影响，应整体下移 1 行后仍完整
        self.assertIn("D16:D17", ms, "汇总区上方竖排合并被误伤")
        self.assertIn("E16:E17", ms, "汇总区上方 E 列竖排合并被误伤")
        # 问题 / 需求区
        for ref in ("D20:F20", "D21:F21", "D22:F22", "D23:F23"):
            self.assertIn(ref, ms, f"{ref} 应随插行下移并保留")
        # 计划位四条
        for ref in ("D24:F24", "D25:F25", "D26:F26", "D27:F27"):
            self.assertIn(ref, ms, f"{ref} 计划位合并丢失")
        self.assertIn("B24:C27", ms, "「主要工作安排」B:C 合并丢失")

    def test_a_column_regions_shift_without_overlap(self):
        """A 列竖排区块标题必须随插行整体下移，且各区间不重叠。

        真实模板基准：A2:A16（本周工作） / A17:A18（汇总） / A19:A20（问题）
        / A21:A22（需求） / A23:A26（计划）。
        星期四插 1 行后应整体下移 1 行 → A2:A17 / A18:A19 / … / A24:A27。
        """
        ws, plan = self._fill([FillItem(weekday=4, title=f"T{i}") for i in range(3)])
        self.assertEqual(plan.inserted_rows, 1)

        am = [str(r) for r in ws.merged_cells.ranges if str(r)[0] == "A" and ":" in str(r)]
        for expect in ("A1:F1", "A2:A17", "A18:A19", "A20:A21", "A22:A23", "A24:A27"):
            self.assertIn(expect, am, f"插行 1 行后应存在 {expect}")

        # 逐区间不得重叠（重叠 = 竖排标题串位）
        spans = []
        for m in am:
            a, b = m.split(":")
            spans.append(
                (int("".join(c for c in a if c.isdigit())), int("".join(c for c in b if c.isdigit())), m)
            )
        spans.sort()
        for i in range(len(spans) - 1):
            self.assertLessEqual(
                spans[i][1] + 1, spans[i + 1][0],
                f"A 列区块重叠：{spans[i][2]} 与 {spans[i+1][2]}",
            )

    def test_issue_demand_content_not_written(self):
        """问题 / 需求区属用户手工录入，填充不得写入内容。"""
        ws, _ = self._fill([FillItem(weekday=1, title="X")])
        for r in (19, 20, 21, 22):
            self.assertIsNone(ws[f"D{r}"].value, f"D{r} 不应被自动填充")
        # 汇总区 D18 的文本「企微会话量」应已被数字统计覆盖
        self.assertIsNotNone(ws["D18"].value)

    def test_summary_overwrites_text_stat(self):
        """V10 3.6.6：示例模板 D18 原为文本「企微会话量：484次」，改为按条数统计。"""
        ws = fresh().active
        self.assertIn("企微", str(ws["D18"].value), "基准模板 D18 应先是文本")
        fill_weekly_report(ws, [], PERIOD, summary_counts={"online_service": 7})
        self.assertEqual(ws["D18"].value, 7)
        self.assertIsInstance(ws["D18"].value, int)


class TestRealTemplateRejectsBroken(unittest.TestCase):
    """结构被破坏时必须阻断。"""

    def test_missing_weekday_label_rejected(self):
        ws = fresh().active
        ws["B3"] = None
        with self.assertRaises(AnchorError):
            validate_template(ws)

    def test_missing_summary_label_rejected(self):
        ws = fresh().active
        ws["E17"] = None
        with self.assertRaises(AnchorError):
            validate_template(ws)

    def test_truncated_template_rejected(self):
        ws = fresh().active
        ws.delete_rows(20, 10)
        with self.assertRaises(AnchorError):
            validate_template(ws)


if __name__ == "__main__":
    unittest.main()
