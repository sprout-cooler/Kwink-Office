"""v1.0.43 手动补充「下周工作计划」结构化任务 —— 后端回归。

用户拍板的口径：
  ① 每条任务含 title / startTime / endTime / weekday 四字段，
     导出时拼成**一行文本**写进模板现有的 D:F 合并槽位（不改模板）；
  ② 手动补充的任务与「任务上传 → 下周工作计划分区」识别出的任务
     两路独立分行，两路都有时加小标题区分来源。
"""
from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Report, Setting
from app.modules.weekly_report import export_service as ES
from app.modules.weekly_report import review_service as RS
from fastapi import HTTPException


class _DBCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.report = Report(
            owner_uid="u1", period_start="2026-11-02", status="draft"
        )
        self.db.add(self.report)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _save(self, tasks):
        return RS.save_manual(
            self.db,
            type("Ident", (), {"uid": "u1"})(),
            self.report,
            {"planTasks": tasks},
        )


class TestPlanTaskNormalize(unittest.TestCase):
    def test_full_fields(self):
        out = RS.normalize_plan_tasks(
            [{"title": "回访客户", "startTime": "11月9日 10:00",
              "endTime": "11月9日 12:00", "weekday": 1}]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["weekday"], 1)
        self.assertEqual(out[0]["title"], "回访客户")

    def test_blank_rows_dropped(self):
        out = RS.normalize_plan_tasks(
            [{"title": "", "startTime": "", "endTime": "", "weekday": 0},
             {"title": "有效", "weekday": 3}]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "有效")

    def test_bad_weekday_falls_back_to_zero(self):
        for bad in (99, -1, "abc", None):
            with self.subTest(bad=bad):
                out = RS.normalize_plan_tasks([{"title": "x", "weekday": bad}])
                self.assertEqual(out[0]["weekday"], 0)

    def test_only_whitelist_fields_kept(self):
        out = RS.normalize_plan_tasks(
            [{"title": "x", "evil": "drop me", "id": 999}]
        )
        self.assertEqual(set(out[0]), {"title", "startTime", "endTime", "weekday"})

    def test_rejects_non_list_and_over_limit(self):
        with self.assertRaises(HTTPException):
            RS.normalize_plan_tasks("not a list")
        with self.assertRaises(HTTPException):
            RS.normalize_plan_tasks([{"title": "x"}] * (RS.MANUAL_PLAN_MAX + 1))

    def test_json_string_accepted(self):
        import json

        out = RS.normalize_plan_tasks(json.dumps([{"title": "x", "weekday": 2}]))
        self.assertEqual(out[0]["title"], "x")


class TestPlanTaskFormat(unittest.TestCase):
    def test_all_four_fields_in_one_line(self):
        line = RS.format_plan_task_line(
            {"title": "回访客户", "startTime": "11月9日 10:00",
             "endTime": "11月9日 12:00", "weekday": 1}
        )
        self.assertIn("星期一", line)
        self.assertIn("11月9日 10:00-11月9日 12:00", line)
        self.assertIn("回访客户", line)
        self.assertIn("｜", line)
        self.assertNotIn("\n", line, "必须是一行，模板 D:F 槽位只有一行")

    def test_partial_fields_no_empty_brackets(self):
        self.assertEqual(
            RS.format_plan_task_line({"title": "只写标题", "weekday": 0}), "只写标题"
        )
        line = RS.format_plan_task_line({"title": "有星期", "weekday": 5})
        self.assertEqual(line, "星期五｜有星期")
        line = RS.format_plan_task_line(
            {"title": "只有开始", "startTime": "11/9 09:00", "weekday": 2}
        )
        self.assertNotIn("｜｜", line)
        self.assertIn("11/9 09:00", line)


class TestManualPlanStorage(_DBCase):
    def test_roundtrip(self):
        saved = self._save(
            [{"title": "回访客户", "startTime": "11月9日 10:00",
              "endTime": "11月9日 12:00", "weekday": 1}]
        )
        self.assertEqual(len(saved["planTasks"]), 1)
        self.assertEqual(saved["planTasks"][0]["title"], "回访客户")
        # 重新读一次库，确认确实落盘而不是只在返回里
        self.assertEqual(len(RS.load_plan_tasks(self.db, self.report)), 1)

    def test_issues_demands_unchanged(self):
        out = RS.save_manual(
            self.db, type("Ident", (), {"uid": "u1"})(), self.report,
            {"issues": "问题A", "demands": "需求B", "planTasks": [{"title": "计划C"}]},
        )
        self.assertEqual(out["issues"], "问题A")
        self.assertEqual(out["demands"], "需求B")
        self.assertEqual(out["planTasks"][0]["title"], "计划C")

    def test_saving_empty_clears(self):
        self._save([{"title": "A"}])
        out = self._save([])
        self.assertEqual(out["planTasks"], [])
        self.assertEqual(RS.load_plan_tasks(self.db, self.report), [])

    def test_corrupt_stored_json_does_not_break_export(self):
        self.db.add(
            Setting(key=f"manual.{self.report.id}.plan_tasks", value="{not json")
        )
        self.db.commit()
        self.assertEqual(RS.load_plan_tasks(self.db, self.report), [])

    def test_batch_isolation(self):
        other = Report(owner_uid="u1", period_start="2026-11-09", status="draft")
        self.db.add(other)
        self.db.commit()
        self._save([{"title": "本周计划"}])
        self.assertEqual(RS.load_plan_tasks(self.db, other), [])


class TestBuildPlanLines(_DBCase):
    def test_manual_only(self):
        self._save(
            [{"title": "回访客户", "startTime": "11月9日 10:00",
              "endTime": "11月9日 12:00", "weekday": 1}]
        )
        lines = ES.build_plan_lines(self.db, self.report, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("星期一", lines[0])
        self.assertNotIn(ES.PLAN_SECTION_MANUAL, lines, "单路时不加小标题")

    def test_recognized_only_keeps_old_layout(self):
        lines = ES.build_plan_lines(self.db, self.report, ["识别任务A", "识别任务B"])
        self.assertEqual(lines, ["识别任务A", "识别任务B"])

    def test_both_routes_two_sections_with_headers(self):
        self._save(
            [{"title": "手工任务1", "weekday": 1}, {"title": "手工任务2", "weekday": 3}]
        )
        lines = ES.build_plan_lines(self.db, self.report, ["识别任务A"])
        self.assertEqual(lines[0], ES.PLAN_SECTION_MANUAL)
        self.assertIn(ES.PLAN_SECTION_RECOGNIZED, lines)
        mi = lines.index(ES.PLAN_SECTION_MANUAL)
        ri = lines.index(ES.PLAN_SECTION_RECOGNIZED)
        self.assertLess(mi, ri, "手动补充在前")
        self.assertIn("手工任务1", lines[mi + 1])
        self.assertIn("手工任务2", lines[mi + 2])
        self.assertEqual(lines[ri + 1], "识别任务A", "识别任务保持纯标题")

    def test_empty_both(self):
        self.assertEqual(ES.build_plan_lines(self.db, self.report, []), [])

    def test_blank_recognized_titles_filtered(self):
        lines = ES.build_plan_lines(self.db, self.report, ["A", "", "  ", None])
        self.assertEqual(lines, ["A"])


if __name__ == "__main__":
    unittest.main()
