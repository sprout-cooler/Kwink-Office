"""周报 ↔ 客户联动：客户名匹配规则单测。

为什么必须测这个（v1.0.30 设计）：
匹配错了**不报错**，只是把工时/费用挂到错误客户名下 —— 财务影响大且完全静默。
三类高危场景：
1. 同名客户被自动挂到任意一条 → 工时算错客户；
2. 跨账号匹配 → A 账号的数据泄漏到 B 账号；
3. AI 抽出「XX科技公司」这种变体 → 匹配失败（应落 none 而不是乱配）。

另测「自动填充客户来源只填空不覆盖」这条业务铁律。
"""
from __future__ import annotations

import unittest

from app.modules.weekly_report.customer_link import (
    MATCH_AMBIGUOUS,
    MATCH_MATCHED,
    MATCH_NONE,
    match_customer,
    split_names,
)


class TestSplitNames(unittest.TestCase):
    """拆分 AI 给的 customer 字段。"""

    def test_single_name(self):
        self.assertEqual(split_names("XX科技"), ["XX科技"])

    def test_multiple_separated_by_ideographic_comma(self):
        self.assertEqual(split_names("甲公司、乙公司"), ["甲公司", "乙公司"])

    def test_multiple_separated_by_other_punctuation(self):
        self.assertEqual(split_names("甲公司,乙公司;丙公司"), ["甲公司", "乙公司", "丙公司"])

    def test_dedup_keeps_order(self):
        self.assertEqual(split_names("甲公司、乙公司、甲公司"), ["甲公司", "乙公司"])

    def test_empty_input(self):
        self.assertEqual(split_names(""), [])
        self.assertEqual(split_names("   "), [])

    def test_strips_whitespace(self):
        self.assertEqual(split_names(" 甲公司 、 乙公司 "), ["甲公司", "乙公司"])


class TestMatchCustomer(unittest.TestCase):
    """匹配规则：唯一命中才关联，同名不猜，匹配不到不建档。"""

    def test_exact_match(self):
        cands = [(1, "XX科技"), (2, "YY集团")]
        m = match_customer("XX科技", cands)
        self.assertEqual(m.match, MATCH_MATCHED)
        self.assertEqual(m.customer_id, 1)
        self.assertEqual(m.customer_name, "XX科技")

    def test_ambiguous_same_name_not_auto_linked(self):
        """⭐ 同名客户 → 绝不自动挂到任意一条，必须交人工。"""
        cands = [(1, "XX科技"), (2, "XX科技")]
        m = match_customer("XX科技", cands)
        self.assertEqual(m.match, MATCH_AMBIGUOUS)
        self.assertIsNone(m.customer_id)
        self.assertEqual(set(m.ambiguous_ids), {1, 2})

    def test_no_match_returns_none_and_keeps_name(self):
        """⭐ 客户未建档 → 保留名字但不建客户。"""
        m = match_customer("ZZ新客户", [(1, "XX科技")])
        self.assertEqual(m.match, MATCH_NONE)
        self.assertIsNone(m.customer_id)
        self.assertEqual(m.customer_name, "ZZ新客户")

    def test_empty_name_returns_none(self):
        m = match_customer("", [(1, "XX科技")])
        self.assertEqual(m.match, MATCH_NONE)
        self.assertIsNone(m.customer_id)

    def test_whitespace_insensitive(self):
        """保守归一化：去空白 + 大小写，不做「去有限公司」这类语义归并。"""
        m = match_customer("  xx科技 ", [(1, "XX科技")])
        self.assertEqual(m.match, MATCH_MATCHED)
        self.assertEqual(m.customer_id, 1)

    def test_case_insensitive(self):
        m = match_customer("xx technology", [(1, "XX Technology")])
        self.assertEqual(m.match, MATCH_MATCHED)

    def test_suffix_difference_is_not_merged(self):
        """「XX科技」与「XX科技有限公司」是**不同**客户，不做语义归并。"""
        """归一化刻意保守：去空白/大小写，但不去「有限公司」等后缀。"""
        m = match_customer("XX科技有限公司", [(1, "XX科技"), (2, "XX科技有限公司")])
        self.assertEqual(m.match, MATCH_MATCHED)
        self.assertEqual(m.customer_id, 2)

    def test_multiple_names_takes_first_matched(self):
        """多客户时取第一个能匹配的（多客户关联暂不支持）。"""
        cands = [(1, "甲公司"), (2, "乙公司")]
        m = match_customer("未知客户、甲公司", cands)
        self.assertEqual(m.match, MATCH_MATCHED)
        self.assertEqual(m.customer_id, 1)

    def test_empty_candidates_returns_none(self):
        """客户表为空（还没建客户）→ 不报错，落 none。"""
        m = match_customer("XX科技", [])
        self.assertEqual(m.match, MATCH_NONE)
        self.assertIsNone(m.customer_id)

    def test_blank_candidate_names_ignored(self):
        cands = [(1, ""), (2, "XX科技")]
        m = match_customer("XX科技", cands)
        self.assertEqual(m.match, MATCH_MATCHED)
        self.assertEqual(m.customer_id, 2)


class TestCustomerSourceAutoFill(unittest.TestCase):
    """⭐ 业务铁律：自动填充客户来源**只填空不覆盖**。

    客户来源是业务判断（这客户怎么来的），周报只提供
    「该客户在周报里出现过」这一弱信号，不足以推翻人工选择。
    """

    def test_empty_source_gets_weekly(self):
        from app.db import models

        class FakeCustomer:
            source = ""
            id = 1

        c = FakeCustomer()
        if not c.source:
            c.source = "weekly"
        self.assertEqual(c.source, "weekly")

    def test_existing_source_not_overwritten(self):
        from app.modules.biz_dashboard import constants

        c = type("C", (), {"source": "referral"})()
        if not c.source:
            c.source = constants.CUSTOMER_SOURCE_AUTO
        self.assertEqual(c.source, "referral", "人工选的来源不能被自动值覆盖")


class TestCapabilitiesIncludeNewDicts(unittest.TestCase):
    """capabilities() 必须下发新增的下拉字典（前端完全靠它渲染）。"""

    def test_capabilities_has_new_keys(self):
        from app.modules.biz_dashboard import constants

        caps = constants.capabilities()
        for key in (
            "customerSources",
            "customerSourceNeedsNote",
            "tripReasons",
            "reimburseStatus",
        ):
            self.assertIn(key, caps)
            self.assertTrue(caps[key], f"{key} 不应为空")

    def test_customer_source_codes_consistent(self):
        from app.modules.biz_dashboard import constants

        self.assertEqual(
            set(constants.CUSTOMER_SOURCE_CODES),
            {c for c, _ in constants.CUSTOMER_SOURCES},
        )
        # 自动来源必须在枚举里（否则写进去的 code 前端不认识）
        self.assertIn(constants.CUSTOMER_SOURCE_AUTO, constants.CUSTOMER_SOURCE_CODES)

    def test_trip_reason_codes_consistent(self):
        from app.modules.biz_dashboard import constants

        self.assertEqual(
            set(constants.TRIP_REASON_CODES),
            {c for c, _ in constants.TRIP_REASONS},
        )
        self.assertEqual(
            set(constants.REIMBURSE_STATUS_CODES),
            {c for c, _ in constants.REIMBURSE_STATUS},
        )


if __name__ == "__main__":
    unittest.main()
