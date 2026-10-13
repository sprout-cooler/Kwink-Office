"""工作汇总计算单测（V10 3.7 口径：分区优先 + 关键词兜底 + 优先级 + 手工锁定）。

本模块是纯规则，最容易出现「多命中取错」「跨分区移动后没重算」「手工覆盖被自动规则冲掉」
这类静默错误 —— 线上无报错只丢数据，必须靠单测兜住。
"""
from __future__ import annotations

import unittest

from app.modules.weekly_report.summary import (
    CAT_OFFLINE,
    CAT_OFFLINE_SERVICE,
    CAT_ONLINE_SERVICE,
    CAT_PLAN,
    CAT_PRESALE,
    CAT_TRAINING,
    CAT_UNCLASSIFIED,
    TaskView,
    classify_task,
    compute_summary,
)


def T(id_: int, partition: str, title: str, manual: str | None = None) -> TaskView:
    return TaskView(id=id_, partition=partition, title=title, manual_category=manual)


class TestClassifyByPartition(unittest.TestCase):
    """分区优先：线上售后 / 下周计划 由上传分区直接确定，不看标题关键词。"""

    def test_online_done_always_online_service(self):
        # 标题含「培训」，但分区是线上售后 → 分区优先
        self.assertEqual(
            classify_task(T(1, "online_done", "培训材料整理")), CAT_ONLINE_SERVICE
        )

    def test_plan_always_plan(self):
        self.assertEqual(classify_task(T(1, "plan", "售前演示准备")), CAT_PLAN)

    def test_offline_falls_to_keywords(self):
        # 线下分区才走关键词
        self.assertEqual(classify_task(T(1, "offline_done", "给新员工做培训")), CAT_TRAINING)


class TestClassifyByKeyword(unittest.TestCase):
    """关键词兜底：未命中 → 未分类，绝不硬塞。"""

    def test_training_keywords(self):
        for title in ("培训", "组织实训", "授课准备", "教学演练"):
            self.assertEqual(classify_task(T(1, "offline_done", title)), CAT_TRAINING, title)

    def test_offline_service_keywords(self):
        for title in ("售后支持", "客户回访", "上门处理", "现场支持"):
            self.assertEqual(classify_task(T(1, "offline_done", title)), CAT_OFFLINE_SERVICE, title)

    def test_presale_keywords(self):
        for title in ("售前咨询", "产品演示", "试用部署", "客户拜访", "商机跟进"):
            self.assertEqual(classify_task(T(1, "offline_done", title)), CAT_PRESALE, title)

    def test_no_keyword_is_unclassified(self):
        """边界：没命中任何关键词 → 未分类，交人工，绝不随便归类。"""
        self.assertEqual(classify_task(T(1, "offline_done", "整理周报文档")), CAT_UNCLASSIFIED)
        self.assertEqual(classify_task(T(1, "offline_done", "")), CAT_UNCLASSIFIED)

    def test_unrelated_keyword_not_matched(self):
        """边界：「售后服务」含「售后」→ 命中售后，不是培训。"""
        self.assertEqual(classify_task(T(1, "offline_done", "售后服务响应")), CAT_OFFLINE_SERVICE)


class TestMultiHitPriority(unittest.TestCase):
    """多命中按 培训 > 售后 > 售前 取优先级最高。"""

    def test_training_wins_over_service(self):
        self.assertEqual(
            classify_task(T(1, "offline_done", "培训售后团队")), CAT_TRAINING
        )

    def test_training_wins_over_all(self):
        self.assertEqual(
            classify_task(T(1, "offline_done", "售前培训售后全覆盖")), CAT_TRAINING
        )

    def test_service_wins_over_presale(self):
        self.assertEqual(
            classify_task(T(1, "offline_done", "售后回访兼售前介绍")), CAT_OFFLINE_SERVICE
        )

    def test_presale_only_when_alone(self):
        self.assertEqual(
            classify_task(T(1, "offline_done", "售前演示")), CAT_PRESALE
        )


class TestManualOverrideLock(unittest.TestCase):
    """手工归类后锁定：自动规则不得改写。"""

    def test_manual_overrides_keyword(self):
        # 标题命中培训，但用户手工归为售前 → 以手工为准
        self.assertEqual(
            classify_task(T(1, "offline_done", "培训", manual=CAT_PRESALE)), CAT_PRESALE
        )

    def test_manual_overrides_partition(self):
        # 线上分区，用户手工归为培训 → 以手工为准（未分类清单归类场景）
        self.assertEqual(
            classify_task(T(1, "online_done", "任何标题", manual=CAT_TRAINING)), CAT_TRAINING
        )

    def test_manual_unclassifiable_still_locked(self):
        self.assertEqual(
            classify_task(T(1, "offline_done", "培训", manual=CAT_UNCLASSIFIED)),
            CAT_UNCLASSIFIED,
        )


class TestComputeSummary(unittest.TestCase):
    def test_counts_and_offline_total(self):
        tasks = [
            T(1, "offline_done", "新员工培训"),        # training
            T(2, "offline_done", "客户售后回访"),      # offline_service
            T(3, "offline_done", "售前演示"),          # presale
            T(4, "online_done", "线上工单"),           # online_service
            T(5, "plan", "下周排期"),                  # plan
            T(6, "offline_done", "写周报"),            # unclassified
        ]
        r = compute_summary(tasks)
        self.assertEqual(r.counts[CAT_TRAINING], 1)
        self.assertEqual(r.counts[CAT_OFFLINE_SERVICE], 1)
        self.assertEqual(r.counts[CAT_PRESALE], 1)
        self.assertEqual(r.counts[CAT_ONLINE_SERVICE], 1)
        self.assertEqual(r.counts[CAT_PLAN], 1)
        self.assertEqual(r.counts[CAT_UNCLASSIFIED], 1)
        # 线下合计 = 培训 + 线下售后 + 售前（不含未分类、不含线上与计划）
        self.assertEqual(r.counts[CAT_OFFLINE], 3)
        self.assertEqual(r.total, 6)
        self.assertEqual(r.unclassified, [6])

    def test_unclassified_ids_sorted(self):
        tasks = [T(9, "offline_done", "x"), T(2, "offline_done", "y"), T(5, "offline_done", "z")]
        self.assertEqual(compute_summary(tasks).unclassified, [2, 5, 9])

    def test_empty_input(self):
        r = compute_summary([])
        self.assertEqual(r.total, 0)
        self.assertEqual(r.unclassified, [])
        for cat in (CAT_TRAINING, CAT_OFFLINE_SERVICE, CAT_PRESALE, CAT_ONLINE_SERVICE):
            self.assertEqual(r.counts[cat], 0)

    def test_offline_total_excludes_unclassified(self):
        """边界：未分类不能算进线下合计，否则统计虚高。"""
        tasks = [T(1, "offline_done", "培训"), T(2, "offline_done", "无关内容")]
        r = compute_summary(tasks)
        self.assertEqual(r.counts[CAT_TRAINING], 1)
        self.assertEqual(r.counts[CAT_UNCLASSIFIED], 1)
        self.assertEqual(r.counts[CAT_OFFLINE], 1)


class TestRecomputeOnMove(unittest.TestCase):
    """跨分区移动后统计重算（归属与识别解耦的连带要求）。"""

    def test_move_changes_category(self):
        before = compute_summary([T(1, "offline_done", "客户售后回访")])
        self.assertEqual(before.counts[CAT_OFFLINE_SERVICE], 1)
        # 移到线上分区 → 应变线上售后，线下售后归零
        after = compute_summary([T(1, "online_done", "客户售后回访")])
        self.assertEqual(after.counts[CAT_OFFLINE_SERVICE], 0)
        self.assertEqual(after.counts[CAT_ONLINE_SERVICE], 1)
        self.assertEqual(after.counts[CAT_OFFLINE], 0)


class TestReviewServiceTimeContract(unittest.TestCase):
    """校对服务的时间参数契约。

    背景：曾把 date 对象传给 dateparse.normalize_task(period_start: str)，
    真跑才报 TypeError（fromisoformat 收到 date），本地静态检查发现不了。
    这里固化签名契约，防再次传错类型。
    """

    def test_normalize_task_expects_string_period(self):
        import inspect

        from app.modules.weekly_report.dateparse import normalize_task

        ann = inspect.signature(normalize_task).parameters["period_start"].annotation
        self.assertEqual(ann, "str", "normalize_task 的 period_start 应收字符串 YYYY-MM-DD")

    def test_period_date_returns_str(self):
        from app.modules.weekly_report.review_service import _period_date

        self.assertIsInstance(_period_date("2026-10-12"), str)

    def test_period_date_rejects_bad_value(self):
        from fastapi import HTTPException

        from app.modules.weekly_report.review_service import _period_date

        with self.assertRaises(HTTPException) as ctx:
            _period_date("2026/10/12")
        self.assertEqual(ctx.exception.status_code, 500)

    def test_renormalize_accepts_iso_period_string(self):
        """端到端：编辑任务时传字符串周期不应抛 TypeError。"""
        from app.modules.weekly_report.review_service import _renormalize

        class FakeTask:
            extra = {"warnings": []}
            start_at = end_at = ""
            weekday = 0

        t = FakeTask()
        _renormalize(t, "10月9日 15:30", "17:00", "2026-10-12", is_manual=True)
        self.assertTrue(t.start_at.startswith("2026-10-"), f"got {t.start_at}")
        self.assertEqual(t.weekday, 5)  # 2026-10-12 是周一，10/9 是周五
        self.assertNotIn("DATE_PARSE_FAILED", (t.extra or {}).get("warnings", []))


class TestDateOnlyFallback(unittest.TestCase):
    """仅日期文本兜底：工单截图常只显示日期（如 261012），不应整条判失败。

    背景：normalize_task 要求文本含时刻，否则报「未找到开始时刻」→ DATE_PARSE_FAILED。
    但用户在校对时往往只想补日期。兜底策略是把时刻补成 00:00 并打 DATE_ONLY 标记。
    """

    def _task(self):
        class T:
            extra = {"warnings": []}
            start_at = end_at = ""
            weekday = 0
        return T()

    def test_compact_date_without_clock(self):
        from app.modules.weekly_report.review_service import _renormalize

        t = self._task()
        _renormalize(t, "261012", "", "2026-10-12", is_manual=True)
        self.assertEqual(t.start_at, "2026-10-12T00:00")
        w = (t.extra or {}).get("warnings", [])
        self.assertIn("DATE_ONLY", w)
        self.assertNotIn("DATE_PARSE_FAILED", w)

    def test_cn_date_without_clock(self):
        from app.modules.weekly_report.review_service import _renormalize

        t = self._task()
        _renormalize(t, "10月9日", "", "2026-10-12", is_manual=True)
        self.assertEqual(t.start_at, "2026-10-09T00:00")
        self.assertIn("DATE_ONLY", (t.extra or {}).get("warnings", []))

    def test_out_of_period_marked_not_failed(self):
        """越界不等于失败 —— 应保留日期并打 out_of_period。"""
        from app.modules.weekly_report.review_service import _renormalize

        t = self._task()
        # 周期 2026-10-12 起，10-09 在周期外
        _renormalize(t, "10-09", "", "2026-10-12", is_manual=True)
        self.assertEqual(t.start_at, "2026-10-09T00:00")
        self.assertTrue((t.extra or {}).get("out_of_period"))

    def test_unrecognizable_text_still_fails(self):
        """真认不出的文本仍应标红必填，绝不猜测（V10 3.5）。"""
        from app.modules.weekly_report.review_service import _renormalize

        t = self._task()
        _renormalize(t, "下下周某天", "", "2026-10-12", is_manual=True)
        self.assertEqual(t.start_at, "")
        w = (t.extra or {}).get("warnings", [])
        self.assertIn("DATE_PARSE_FAILED", w)
        self.assertTrue((t.extra or {}).get("parse_error"))

    def test_text_with_clock_but_bad_never_downgrades(self):
        """原文带时刻却解析失败 → 不走兜底（说明格式真不认识），直接标红。"""
        from app.modules.weekly_report.review_service import _renormalize

        t = self._task()
        _renormalize(t, "下下周某天 15:30", "", "2026-10-12", is_manual=True)
        self.assertEqual(t.start_at, "")
        self.assertIn("DATE_PARSE_FAILED", (t.extra or {}).get("warnings", []))


class TestUnclassifiedListContract(unittest.TestCase):
    """未分类清单口径一致性。

    背景：曾用 `stat_category == unclassified` 过滤未分类清单，但该列在识别写入时
    是模型默认值 —— 自动分类成功的任务在库里同样残留 unclassified，
    导致清单里混进 5 条已归类任务（而统计数字是对的，界面自相矛盾）。
    正确做法：以 compute_summary 的判定结果为唯一口径。
    """

    def test_list_uses_compute_result_not_raw_column(self):
        from app.modules.weekly_report.summary import CAT_TRAINING as T_

        # 自动分类成功：库里 stat_category 仍是默认 unclassified，但规则判定为 training
        tasks = [
            TaskView(id=1, partition="offline_done", title="培训新员工"),      # → training
            TaskView(id=2, partition="offline_done", title="整理周报文档"),    # → unclassified
        ]
        result = compute_summary(tasks)
        self.assertEqual(result.unclassified, [2], "只有真正未命中的才该进清单")
        self.assertEqual(result.counts[T_], 1)

        # 手工锁定后应移出清单
        tasks[0].manual_category = "unclassified"
        self.assertEqual(compute_summary(tasks).unclassified, [1, 2])

    def test_manual_category_clears_from_list(self):
        tasks = [TaskView(id=1, partition="offline_done", title="整理文档")]
        self.assertEqual(compute_summary(tasks).unclassified, [1])
        tasks[0].manual_category = "training"
        self.assertEqual(compute_summary(tasks).unclassified, [])


if __name__ == "__main__":
    unittest.main()
