"""日期归一化全场景单测（V10 3.5，MS2 强制项）。

运行：python -m unittest app.tests.test_dateparse -v
（纯标准库，便携 Python 可直接跑；不依赖数据库/网络）
"""
from __future__ import annotations

import unittest
from datetime import date

from app.modules.weekly_report.dateparse import DateParseError, normalize_task, parse_date

# 固定周报周期：2026-10-05(周一) ~ 2026-10-11(周日)
PS = "2026-10-05"
PSD = date(2026, 10, 5)


class TestParseDate(unittest.TestCase):
    def test_full_formats(self):
        self.assertEqual(parse_date("2026/10/09", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("2026-10-09", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("2026.10.9", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("2026年10月9日", PSD), date(2026, 10, 9))

    def test_missing_year_filled_by_period(self):
        self.assertEqual(parse_date("10-09", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("10/9", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("10月9日", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("10 月 9 号", PSD), date(2026, 10, 9))

    def test_english_month(self):
        self.assertEqual(parse_date("Oct 9", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("Oct. 9 15:30", PSD), date(2026, 10, 9))
        self.assertEqual(parse_date("September 30", PSD), date(2026, 9, 30))

    def test_compact_yymmdd(self):
        # 工单「预计时间」6 位压缩写法
        self.assertEqual(parse_date("261012", PSD), date(2026, 10, 12))
        self.assertEqual(parse_date("预计 261008 处理", PSD), date(2026, 10, 8))

    def test_chinese_weekday_in_period(self):
        self.assertEqual(parse_date("周四", PSD), date(2026, 10, 8))
        self.assertEqual(parse_date("星期四", PSD), date(2026, 10, 8))
        self.assertEqual(parse_date("礼拜一", PSD), date(2026, 10, 5))
        self.assertEqual(parse_date("周日", PSD), date(2026, 10, 11))
        self.assertEqual(parse_date("周天", PSD), date(2026, 10, 11))

    def test_english_weekday_in_period(self):
        self.assertEqual(parse_date("Thu", PSD), date(2026, 10, 8))
        self.assertEqual(parse_date("Thursday", PSD), date(2026, 10, 8))
        self.assertEqual(parse_date("Mon", PSD), date(2026, 10, 5))

    def test_invalid(self):
        for bad in ("", "   ", "下周吧", "13月40日", "随便一天"):
            with self.assertRaises(DateParseError, msg=bad):
                parse_date(bad, PSD)


class TestNormalizeTask(unittest.TestCase):
    def test_slash_full(self):
        r = normalize_task("2026/10/09 15:30 至 22:00", period_start=PS)
        self.assertEqual(r.start_at, "2026-10-09T15:30")
        self.assertEqual(r.end_at, "2026-10-09T22:00")
        self.assertEqual(r.weekday, 5)  # 周五
        self.assertFalse(r.out_of_period)

    def test_chinese_date_with_range(self):
        r = normalize_task("10月8日 15:30 至 22:00", period_start=PS)
        self.assertEqual(r.start_at, "2026-10-08T15:30")
        self.assertEqual(r.end_at, "2026-10-08T22:00")
        self.assertEqual(r.weekday, 4)  # 周四

    def test_dash_missing_year(self):
        r = normalize_task("10-09 09:00-18:00", period_start=PS)
        self.assertEqual((r.start_at, r.end_at), ("2026-10-09T09:00", "2026-10-09T18:00"))

    def test_end_clock_only_inherits_start_date(self):
        # V10 3.5 原文场景（单段文本）：结束只有时刻，结束日期天然=开始日期
        r = normalize_task("10月8日 15:30 至 22:00", period_start=PS)
        self.assertTrue(r.end_at.startswith("2026-10-08"))
        self.assertEqual(r.end_at, "2026-10-08T22:00")

    def test_end_field_clock_only_inherits_date(self):
        # 字段分离形态：end_raw 只有时刻没有日期 → 显式继承开始日期并打标
        r = normalize_task("10月8日 15:30", "22:00", period_start=PS)
        self.assertEqual(r.end_at, "2026-10-08T22:00")
        self.assertIn("END_DATE_INHERITED", r.warnings)

    def test_split_start_end_fields(self):
        # VLM 拆字段形态：start_raw 与 end_raw 分开
        r = normalize_task("10月8日 15:30", "10月8日 22:00", period_start=PS)
        self.assertEqual(r.start_at, "2026-10-08T15:30")
        self.assertEqual(r.end_at, "2026-10-08T22:00")

    def test_overnight_end_next_day(self):
        r = normalize_task("10月8日 23:00 至 02:00", period_start=PS)
        self.assertEqual(r.start_at, "2026-10-08T23:00")
        self.assertEqual(r.end_at, "2026-10-09T02:00")
        self.assertIn("END_NEXT_DAY", r.warnings)
        # 跨天默认归属开始日期（周四）
        self.assertEqual(r.weekday, 4)

    def test_overnight_strategy_end(self):
        r = normalize_task("10月8日 23:00 至 02:00", period_start=PS, strategy="end")
        self.assertEqual(r.weekday, 5)  # 归属结束日期 → 周五

    def test_weekday_based(self):
        r = normalize_task("周四 10:00 至 12:00", period_start=PS)
        self.assertEqual(r.start_at, "2026-10-08T10:00")
        self.assertEqual(r.end_at, "2026-10-08T12:00")

    def test_out_of_period_highlight(self):
        # 10-12 是下周一，落在周期（10-05~10-11）之外
        r = normalize_task("261012 09:00 至 10:00", period_start=PS)
        self.assertTrue(r.out_of_period)
        self.assertIn("OUT_OF_PERIOD", r.warnings)

    def test_within_period_boundary(self):
        # 周期首尾两天不算越界
        self.assertFalse(normalize_task("10月5日 09:00 至 10:00", period_start=PS).out_of_period)
        self.assertFalse(normalize_task("10月11日 09:00 至 10:00", period_start=PS).out_of_period)

    def test_missing_end_time_marked(self):
        r = normalize_task("10月9日 15:30", period_start=PS)
        self.assertEqual(r.start_at, "2026-10-09T15:30")
        self.assertIn("END_TIME_MISSING", r.warnings)

    def test_chinese_colon_and_tilde(self):
        r = normalize_task("10月9日 15：30～17：00", period_start=PS)
        self.assertEqual((r.start_at, r.end_at), ("2026-10-09T15:30", "2026-10-09T17:00"))

    def test_bad_input_raises(self):
        with self.assertRaises(DateParseError):
            normalize_task("下周某天 15:30 至 22:00", period_start=PS)
        with self.assertRaises(DateParseError):
            normalize_task("10月9日", period_start="not-a-date")


if __name__ == "__main__":
    unittest.main(verbosity=2)
