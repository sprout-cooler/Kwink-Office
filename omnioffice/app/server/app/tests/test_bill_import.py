"""账单导入与多类分享单测（v1.0.32）。

为什么必须有这些测试：

1. **编码与列映射错了是静默的** —— 文件能解析、行能入库，但金额读到日期列上、
   或者中文全成乱码，用户要等到对账时才发现。GB18030 几乎能解任意字节，
   探测顺序写反就会把 UTF-8 文件读成乱码，所以顺序本身必须被测。

2. **千分位逗号会把整行切成错位列** —— 实测发现：金额「1,234.56」若未加引号，
   CSV 把它切成两列，金额静默变成 1（差三个数量级）。财务数据静默错误的代价
   远高于报错，所以「必须报错而不是静默少掉」要有断言守住。

3. **去重漏判 = 重复记账** —— 用户重复导入同一个文件是最常见操作。
   订单号与组合键两条路径都要覆盖。

4. **分享是多类且免登录的** —— 这是全项目唯一不按 owner_uid 过滤的读接口，
   一旦归属校验漏了，就是拿别人的 id 建分享把数据读出去。
   口令与访问计数的先后关系也要测（输错口令不该被记成有效访问）。
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.identity import Identity
from app.db import models
from app.modules.biz_dashboard import bill_import as bi
from app.modules.biz_dashboard import service
from app.modules.biz_dashboard.errors import BizDashboardError

# ---- 微信账单（真实格式：开头有说明行，表头在中间，金额带 ¥）----
WECHAT_CSV = (
    "微信支付账单明细\n"
    "导出时间：2024-01-31 12:00:00\n"
    "微信昵称：测试\n"
    "----------------------微信支付账单明细列表--------------------\n"
    "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
    "2024-01-15 12:30:45,商户消费,永辉超市,/,支出,¥35.80,零钱,支付成功,W001,SHOP001,\n"
    "2024-01-16 09:10:00,转账,张三,/,收入,¥2000.00,零钱,已存入零钱,W002,,工资\n"
    "2024-01-17 20:00:00,商户消费,某某店,/,支出,¥99.00,零钱,已全额退款,W003,SHOP002,\n"
    "2024-01-18 08:00:00,零钱提现,/,/,不计收支,¥500.00,零钱,提现成功,W004,,\n"
    "2024-01-19 08:00:00,商户消费,坏数据店,/,支出,abc,零钱,支付成功,W005,SHOP003,\n"
    "合计,,,,,¥2634.80,,,\n"
)

# ---- 支付宝账单（表头在第一行，列序不同，千分位金额带引号）----
ALIPAY_CSV = (
    "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注\n"
    '2024/2/1 10:00:00,购物,天猫超市,,日用品,支出,"1,234.56",余额宝,交易成功,A001,A1002,\n'
    "2024/2/2 11:00:00,转账,李四,,借款归还,收入,800.00,余额,交易成功,A002,,还款\n"
    "2024/2/3 12:00:00,理财,余额宝,,转入,不计收支,3000.00,余额,交易成功,A003,,\n"
)

# ---- 畸形导出：千分位金额未加引号 ----
BROKEN_CSV = (
    "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注\n"
    "2024/2/1 10:00:00,购物,天猫超市,,日用品,支出,1,234.56,余额宝,交易成功,A001,A1002,\n"
)


def _fresh_db():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _ident(uid: str = "u1") -> Identity:
    return Identity(uid=uid, username=uid, is_admin=False)


def _expense(db, uid: str, **kw) -> models.BizExpense:
    row = models.BizExpense(
        owner_uid=uid,
        kind=kw.get("kind", "expense"),
        category=kw.get("category", ""),
        amount=Decimal(str(kw.get("amount", 10))),
        occurred_on=kw.get("occurred_on", "2024-01-01"),
        platform=kw.get("platform", "wechat"),
        order_no=kw.get("order_no", ""),
        counterparty=kw.get("counterparty", ""),
        customer_id=kw.get("customer_id"),
    )
    db.add(row)
    db.commit()
    return row


class TestEncoding(unittest.TestCase):
    """编码探测：顺序写反会把 UTF-8 读成 GB18030 乱码，必须守住。"""

    def test_utf8_bom(self):
        self.assertEqual(bi.detect_encoding(b"\xef\xbb\xbf" + "交易时间".encode("utf-8")), "utf-8-sig")

    def test_utf8_plain(self):
        self.assertEqual(bi.detect_encoding("交易时间,金额".encode("utf-8")), "utf-8")

    def test_gbk(self):
        # GBK 字节不是合法 UTF-8，应退回 gb18030
        self.assertEqual(bi.detect_encoding("交易时间,金额".encode("gb18030")), "gb18030")

    def test_empty_raises(self):
        with self.assertRaises(BizDashboardError):
            bi.detect_encoding(b"")


class TestPlatformAndMapping(unittest.TestCase):
    """平台识别与列映射：按列名匹配，而不是按列序硬编码。"""

    def test_wechat_recognized(self):
        r = bi.parse_bill(WECHAT_CSV.encode("utf-8"), "wx.csv")
        self.assertEqual(r.platform, "wechat")
        self.assertEqual(r.header_line, 5)  # 跳过 4 行说明

    def test_alipay_recognized(self):
        r = bi.parse_bill(ALIPAY_CSV.encode("utf-8"), "ali.csv")
        self.assertEqual(r.platform, "alipay")
        self.assertEqual(r.header_line, 1)

    def test_columns_mapped_by_name(self):
        r = bi.parse_bill(WECHAT_CSV.encode("utf-8"), "wx.csv")
        # 微信的金额在第 5 列、订单号在第 8 列 —— 与支付宝完全不同
        self.assertEqual(r.mapping["amount"], 5)
        self.assertEqual(r.mapping["order_no"], 8)
        self.assertEqual(r.mapping["txn_time"], 0)

    def test_gbk_content_readable(self):
        """GBK 文件解出来的中文不能是乱码。"""
        r = bi.parse_bill(WECHAT_CSV.encode("gb18030"), "wx.csv")
        ok = [x for x in r.rows if x.status == bi.STATUS_OK]
        self.assertEqual(ok[0].counterparty, "永辉超市")

    def test_unknown_platform(self):
        """有金额列但不含支付宝/微信特征列 -> unknown，仍能解析（不误判平台）。"""
        csv_text = "日期,项目,金额,收/支\n2024-01-01,吃饭,20,支出\n"
        r = bi.parse_bill(csv_text.encode("utf-8"), "x.csv")
        self.assertEqual(r.platform, "unknown")
        self.assertEqual(r.summary()["ok"], 1)


class TestRowStatus(unittest.TestCase):
    """逐行状态判定：退款/不计收支要跳过，坏数据要报错而非静默。"""

    def setUp(self):
        self.r = bi.parse_bill(WECHAT_CSV.encode("utf-8"), "wx.csv")

    def test_summary_counts(self):
        s = self.r.summary()
        self.assertEqual(s["ok"], 2)
        self.assertEqual(s["skipped"], 2)  # 已退款 + 不计收支
        self.assertEqual(s["failed"], 1)  # 金额 abc

    def test_refund_skipped(self):
        row = [x for x in self.r.rows if x.status == bi.STATUS_SKIPPED][0]
        self.assertIn("退款", row.reason)

    def test_bad_amount_failed(self):
        row = [x for x in self.r.rows if x.status == bi.STATUS_FAILED][0]
        self.assertIn("金额无法解析", row.reason)

    def test_total_row_not_counted(self):
        """合计行不是交易，不能进统计。"""
        self.assertFalse(any("合计" in str(x.raw) for x in self.r.rows))

    def test_amount_always_positive(self):
        """金额存正数，方向由 direction 表达。"""
        for row in self.r.rows:
            if row.status == bi.STATUS_OK:
                self.assertGreater(row.amount, 0)

    def test_thousands_separator_parsed(self):
        r = bi.parse_bill(ALIPAY_CSV.encode("utf-8"), "ali.csv")
        row = [x for x in r.rows if x.counterparty == "天猫超市"][0]
        self.assertEqual(row.amount, Decimal("1234.56"))

    def test_thousands_without_quotes_must_fail(self):
        """未加引号的千分位会切错列 —— 必须报错，绝不能静默变成 1 元。"""
        r = bi.parse_bill(BROKEN_CSV.encode("utf-8"), "bad.csv")
        self.assertEqual(r.summary()["failed"], 1)
        self.assertEqual(r.summary()["ok"], 0)
        self.assertIn("错位", r.rows[0].reason)


class TestDedupeKey(unittest.TestCase):
    """去重键：订单号优先，缺失回落组合键。"""

    def test_order_no_wins(self):
        k = bi.build_dedupe_key("wechat", "W001", "2024-01-15", Decimal("35.80"), "永辉超市")
        self.assertEqual(k, "wechat:W001")

    def test_fallback_combo(self):
        k = bi.build_dedupe_key("wechat", "", "2024-01-15", Decimal("35.80"), "永辉超市")
        self.assertEqual(k, "wechat:~:2024-01-15:35.80:永辉超市")

    def test_platform_is_part_of_key(self):
        """支付宝与微信订单号命名空间独立，不能撞号。"""
        a = bi.build_dedupe_key("alipay", "X1", "2024-01-01", Decimal("1"), "A")
        w = bi.build_dedupe_key("wechat", "X1", "2024-01-01", Decimal("1"), "A")
        self.assertNotEqual(a, w)


class TestCounterpartyResolution(unittest.TestCase):
    """交易方取值规则：**取与当前账户相对的一方**。

    「付款方/收款方」是绝对方向的两列，不结合收支方向就会把「我」当成交易对手，
    所以必须按方向选；账单若已直接给出相对方列（交易对方/收/付款方），则以它为准。
    """

    def test_direct_relative_column_wins(self):
        """账单已给出「交易对方」时直接取，不受方向影响。"""
        self.assertEqual(
            bi.resolve_counterparty("expense", direct="永辉超市", payer="我", payee="超市"),
            "永辉超市",
        )

    def test_expense_takes_payee(self):
        """我付钱 -> 对方是收款方。"""
        self.assertEqual(
            bi.resolve_counterparty("expense", payer="我的账户", payee="供应商A"), "供应商A"
        )

    def test_income_takes_payer(self):
        """我收钱 -> 对方是付款方。"""
        self.assertEqual(
            bi.resolve_counterparty("income", payer="客户B", payee="我的账户"), "客户B"
        )

    def test_missing_target_column_falls_back(self):
        """对应方向那一列缺失时回落到另一列（有值可核对，胜过留空）。"""
        self.assertEqual(bi.resolve_counterparty("expense", payer="对方X"), "对方X")

    def test_all_empty(self):
        self.assertEqual(bi.resolve_counterparty("expense"), "")


class TestBankStatementCounterparty(unittest.TestCase):
    """银行流水形态：只有「付款方 + 收款方」两列，必须按方向推导交易方。"""

    BANK_CSV = (
        "交易时间,摘要,付款方,收款方,金额,收支,余额\n"
        "2024-05-01 10:00:00,采购付款,我的公司,供应商A,1000.00,支出,5000\n"
        "2024-05-02 10:00:00,销售回款,客户B,我的公司,2000.00,收入,7000\n"
    )

    def setUp(self):
        self.r = bi.parse_bill(self.BANK_CSV.encode("utf-8"), "bank.csv")

    def test_expense_row_uses_payee(self):
        row = [x for x in self.r.rows if x.direction == bi.DIRECTION_EXPENSE][0]
        self.assertEqual(row.counterparty, "供应商A")
        self.assertNotEqual(row.counterparty, "我的公司")

    def test_income_row_uses_payer(self):
        row = [x for x in self.r.rows if x.direction == bi.DIRECTION_INCOME][0]
        self.assertEqual(row.counterparty, "客户B")

    def test_raw_columns_exposed_for_review(self):
        """原始两列要回传，预览时能核对推导依据。"""
        row = [x for x in self.r.rows if x.direction == bi.DIRECTION_EXPENSE][0]
        self.assertEqual(row.raw["payer"], "我的公司")
        self.assertEqual(row.raw["payee"], "供应商A")


class TestCounterpartyFilter(unittest.TestCase):
    """交易方筛选：必须能搜到只有关联客户的历史流水（读时兼容）。"""

    def setUp(self):
        self.db = _fresh_db()
        self.uid = "u1"

    def test_search_by_counterparty_text(self):
        _expense(self.db, self.uid, counterparty="永辉超市")
        _expense(self.db, self.uid, counterparty="张三")
        items = service.list_expenses(self.db, _ident(self.uid), counterparty="永辉")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["counterparty"], "永辉超市")

    def test_legacy_customer_only_record_is_searchable(self):
        """历史流水只有 customer_id、没有交易方 —— 按客户名也应搜得到。"""
        cust = models.BizCustomer(owner_uid=self.uid, name="老客户公司")
        self.db.add(cust)
        self.db.commit()
        _expense(self.db, self.uid, customer_id=cust.id, counterparty="")
        items = service.list_expenses(self.db, _ident(self.uid), counterparty="老客户")
        self.assertEqual(len(items), 1)

    def test_other_users_records_not_matched(self):
        cust = models.BizCustomer(owner_uid="u2", name="别人的客户")
        self.db.add(cust)
        self.db.commit()
        _expense(self.db, "u2", customer_id=cust.id)
        items = service.list_expenses(self.db, _ident(self.uid), counterparty="别人的")
        self.assertEqual(len(items), 0)

    def test_counterparty_is_writable(self):
        created = service.create_expense(
            self.db,
            _ident(self.uid),
            {"kind": "expense", "amount": 10, "occurredOn": "2024-06-01", "counterparty": "楼下便利店"},
        )
        self.assertEqual(created["counterparty"], "楼下便利店")
        updated = service.update_expense(
            self.db, _ident(self.uid), created["id"], {"counterparty": "改成超市"}
        )
        self.assertEqual(updated["counterparty"], "改成超市")


class TestImportFlow(unittest.TestCase):
    """导入全流程：预览与提交一致、去重生效、批次可撤销。"""

    def setUp(self):
        self.db = _fresh_db()
        self.uid = "u1"

    def test_preview_does_not_write(self):
        service.preview_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        self.assertEqual(self.db.query(models.BizExpense).count(), 0)

    def test_commit_writes_only_ok_rows(self):
        r = service.commit_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        self.assertEqual(r["imported"], 2)
        self.assertEqual(self.db.query(models.BizExpense).count(), 2)

    def test_reimport_same_file_is_deduplicated(self):
        """重复导入同一文件：第二次应全部判重，不能重复记账。"""
        service.commit_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        second = service.commit_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["summary"]["duplicate"], 2)
        self.assertEqual(self.db.query(models.BizExpense).count(), 2)

    def test_combo_key_dedupe_without_order_no(self):
        """无订单号时按「时间+金额+对方」判重。"""
        csv_text = (
            "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
            "2024-03-01 10:00:00,商户消费,老王水果店,/,支出,¥66.00,零钱,支付成功,,,\n"
        )
        service.commit_bill_import(self.db, _ident(self.uid), csv_text.encode("utf-8"), "a.csv")
        again = service.commit_bill_import(self.db, _ident(self.uid), csv_text.encode("utf-8"), "b.csv")
        self.assertEqual(again["imported"], 0)
        self.assertEqual(again["summary"]["duplicate"], 1)

    def test_same_order_no_different_platform_not_duplicate(self):
        """跨平台同订单号不算重复（命名空间独立）。"""
        base = (
            "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
            "2024-04-01 10:00:00,商户消费,A店,/,支出,¥10.00,零钱,支付成功,SAME001,,\n"
        )
        service.commit_bill_import(self.db, _ident(self.uid), base.encode("utf-8"), "wx.csv")
        # 换一个不触发微信特征的表头，让平台识别成 unknown
        other = (
            "交易时间,分类,对方,说明,收/支,金额,方式,状态,订单号,备注\n"
            "2024-04-01 10:00:00,购物,A店,/,支出,10.00,余额,成功,SAME001,\n"
        )
        r = service.commit_bill_import(self.db, _ident(self.uid), other.encode("utf-8"), "other.csv")
        self.assertEqual(r["imported"], 1)

    def test_other_users_data_not_touched(self):
        """别人的同订单号记录不应阻止我导入（按 owner 隔离）。"""
        _expense(self.db, "u2", platform="wechat", order_no="W001", amount=35.80, occurred_on="2024-01-15")
        r = service.commit_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        self.assertEqual(r["imported"], 2)

    def test_batch_record_and_rollback(self):
        r = service.commit_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        batch_id = r["batchId"]
        items = service.list_bill_imports(self.db, _ident(self.uid))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["importedRows"], 2)
        self.assertEqual(items[0]["platform"], "wechat")

        out = service.delete_bill_import(self.db, _ident(self.uid), batch_id)
        self.assertEqual(out["removed"], 2)
        self.assertEqual(self.db.query(models.BizExpense).count(), 0)
        self.assertEqual(len(service.list_bill_imports(self.db, _ident(self.uid))), 0)

    def test_rollback_requires_ownership(self):
        r = service.commit_bill_import(self.db, _ident(self.uid), WECHAT_CSV.encode("utf-8"), "wx.csv")
        with self.assertRaises(BizDashboardError):
            service.delete_bill_import(self.db, _ident("u2"), r["batchId"])


class TestShareScopes(unittest.TestCase):
    """多类分享：四类独立开关 + 口令 + 归属校验。"""

    def setUp(self):
        self.db = _fresh_db()
        self.uid = "u1"
        self.e1 = _expense(self.db, self.uid, amount=100, occurred_on="2024-01-01", order_no="E1")
        self.e2 = _expense(self.db, self.uid, amount=200, occurred_on="2024-01-02", order_no="E2")
        cust = models.BizCustomer(
            owner_uid=self.uid, name="甲公司", contact="王五", phone="13800000000", address="某地",
        )
        self.db.add(cust)
        self.db.commit()
        self.cust_id = cust.id

    def _create(self, scopes, **kw):
        body = {"scopes": scopes, "title": "t", "days": 7}
        body.update(kw)
        return service.create_share(self.db, _ident(self.uid), body)

    def test_multi_scope_share(self):
        created = self._create({"expense": [self.e1.id], "customer": [self.cust_id], "workload": []})
        self.assertEqual(created["scopeCount"], 2)  # workload 是聚合，不计条数
        self.assertIn("expense", created["scopes"])
        self.assertIn("customer", created["scopes"])
        self.assertIn("workload", created["scopes"])

        read = service.read_share(self.db, created["token"])
        self.assertIn("expense", read["sections"])
        self.assertIn("customer", read["sections"])
        self.assertIn("workload", read["sections"])

    def test_customer_share_hides_contact(self):
        """客户分享视图不得带出电话/地址/联系人。"""
        created = self._create({"customer": [self.cust_id]})
        read = service.read_share(self.db, created["token"])
        item = read["sections"]["customer"]["items"][0]
        self.assertEqual(item["name"], "甲公司")
        self.assertNotIn("phone", item)
        self.assertNotIn("address", item)
        self.assertNotIn("contact", item)

    def test_other_users_records_are_rejected(self):
        """拿别人的记录 id 建分享：过滤后为空 -> 拒绝创建（不静默分享出去）。"""
        other = _expense(self.db, "u2", amount=999, order_no="O1")
        with self.assertRaises(BizDashboardError):
            self._create({"expense": [other.id]})

    def test_mixed_ownership_keeps_only_mine(self):
        """混合勾选：只保留属于我的，不把我的一起丢掉也不混入别人的。"""
        other = _expense(self.db, "u2", amount=999, order_no="O2")
        created = self._create({"expense": [self.e1.id, other.id]})
        self.assertEqual(created["scopes"]["expense"], [self.e1.id])

    def test_empty_scope_rejected(self):
        with self.assertRaises(BizDashboardError):
            self._create({})

    def test_passcode_required_and_checked(self):
        created = self._create({"expense": [self.e1.id]}, passcode="6688")
        self.assertTrue(created["hasPass"])
        with self.assertRaises(BizDashboardError):
            service.read_share(self.db, created["token"])  # 未带口令
        with self.assertRaises(BizDashboardError):
            service.read_share(self.db, created["token"], "wrong")
        ok = service.read_share(self.db, created["token"], "6688")
        self.assertEqual(ok["sections"]["expense"]["count"], 1)

    def test_wrong_passcode_does_not_count_as_view(self):
        """输错口令不该被记成有效访问，否则 view_count 失去意义。"""
        created = self._create({"expense": [self.e1.id]}, passcode="6688")
        for _ in range(3):
            try:
                service.read_share(self.db, created["token"], "bad")
            except BizDashboardError:
                pass
        row = self.db.query(models.BizShare).filter(models.BizShare.id == created["id"]).first()
        self.assertEqual(row.view_count, 0)

    def test_legacy_single_scope_still_readable(self):
        """旧格式（scopeKind + scopeIds）创建的分享仍能被读取。"""
        created = service.create_share(
            self.db, _ident(self.uid), {"scopeKind": "expense", "scopeIds": [self.e1.id], "days": 7}
        )
        read = service.read_share(self.db, created["token"])
        self.assertEqual(read["sections"]["expense"]["count"], 1)

    def test_only_selected_records_are_visible(self):
        created = self._create({"expense": [self.e1.id]})
        read = service.read_share(self.db, created["token"])
        ids = [x["id"] for x in read["sections"]["expense"]["items"]]
        self.assertEqual(ids, [self.e1.id])
        self.assertNotIn(self.e2.id, ids)


if __name__ == "__main__":
    unittest.main()
