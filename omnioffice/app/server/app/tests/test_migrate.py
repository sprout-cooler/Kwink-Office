"""数据库迁移（补列）单测。

为什么必须有这个测试（v1.0.30 实测教训）：

``_migrate_add_missing_columns`` 给已有表补 NOT NULL 列时，**必须带 DEFAULT**。
实测 2026-10-26：
- SQLite 无 DEFAULT 加 NOT NULL 列 → ``Cannot add a NOT NULL column with default value NULL``
- PostgreSQL 在表非空时同样拒绝无 DEFAULT 的 NOT NULL 列

而迁移里的 ``except`` 会把失败**静默吞掉**（只打印一行日志）→ 老库上该字段根本不存在
→ 真机（PostgreSQL，数据卷保留）启动后访问该字段直接报错。
这类问题在开发期（本地 SQLite 新库）完全测不出来，**只在真机升级时炸**。

所以这里用真实的 ORM + 真实的「老库」表结构做端到端验证：
造一个缺列的旧表 → 跑迁移 → 断言列补上了、既有数据没丢、**值类型正确**。

特别关注「值类型正确」：
- Numeric 列的 DEFAULT 写成 ``''`` 会让该列变成字符串 → 后续写 Decimal 直接报错
- JSON 列的 DEFAULT 写成 ``''`` 会让 ORM 读这一行时 ``JSONDecodeError``
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import sqlalchemy

from app.db import models  # noqa: F401 —— 确保所有表已注册到 Base.metadata
from app.db.session import _migrate_add_missing_columns, _sql_literal

# 老库（v1.0.29 及之前）的 biz_customers 表结构 —— 缺 source / source_note
_OLD_CUSTOMERS_DDL = """
CREATE TABLE biz_customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_uid VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  contact VARCHAR(64) NOT NULL,
  phone VARCHAR(64) NOT NULL,
  address VARCHAR(255) NOT NULL,
  industry VARCHAR(64) NOT NULL,
  level VARCHAR(32) NOT NULL,
  region VARCHAR(64) NOT NULL,
  tags JSON NOT NULL,
  note TEXT NOT NULL,
  status VARCHAR(16) NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
)
"""

# 老库的 biz_trips 表结构 —— 缺 reason_code / reimburse_status / reimburse_amount / report_task_ids
_OLD_TRIPS_DDL = """
CREATE TABLE biz_trips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_uid VARCHAR(64) NOT NULL,
  customer_id INTEGER,
  title VARCHAR(128) NOT NULL,
  origin_name VARCHAR(128) NOT NULL,
  origin_lng FLOAT,
  origin_lat FLOAT,
  dest_name VARCHAR(128) NOT NULL,
  dest_lng FLOAT,
  dest_lat FLOAT,
  start_date VARCHAR(10) NOT NULL,
  end_date VARCHAR(10) NOT NULL,
  transport VARCHAR(32) NOT NULL,
  mileage_km FLOAT NOT NULL,
  cost_amount FLOAT NOT NULL,
  status VARCHAR(16) NOT NULL,
  note TEXT NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
)
"""


class MigrationHarness(unittest.TestCase):
    """建一个「老库」并让迁移函数作用在它上面。"""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="migrate-test-")
        self.db_path = str(Path(self.tmp) / "old.db")
        con = sqlite3.connect(self.db_path)
        con.execute(_OLD_CUSTOMERS_DDL)
        con.execute(_OLD_TRIPS_DDL)
        con.execute(
            "INSERT INTO biz_customers (owner_uid, name, contact, phone, address, industry,"
            " level, region, tags, note, status, created_at, updated_at)"
            " VALUES ('u1', '老客户A', '', '', '', '', '', '', '[]', '', 'active',"
            " '2026-01-01', '2026-01-01')"
        )
        con.execute(
            "INSERT INTO biz_trips (owner_uid, title, origin_name, dest_name, start_date,"
            " end_date, transport, mileage_km, cost_amount, status, note, created_at, updated_at)"
            " VALUES ('u1', '老出差', '北京', '上海', '2026-01-01', '2026-01-03', 'train',"
            " 100, 200, 'done', '', '2026-01-01', '2026-01-01')"
        )
        con.commit()
        con.close()

        # 迁移函数用的是模块级 engine，这里临时替换
        from app.db import session as session_mod

        self._orig_engine = session_mod.engine
        session_mod.engine = sqlalchemy.create_engine(f"sqlite:///{self.db_path}")
        session_mod.SessionLocal.configure(bind=session_mod.engine)

    def tearDown(self) -> None:
        from app.db import session as session_mod

        session_mod.engine = self._orig_engine
        session_mod.SessionLocal.configure(bind=session_mod.engine)
        try:
            import shutil

            shutil.rmtree(self.tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001 —— 清理失败不影响测试结论
            pass

    def _columns(self, table: str) -> set[str]:
        con = sqlite3.connect(self.db_path)
        try:
            return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        finally:
            con.close()

    def _raw_row(self, sql: str):
        con = sqlite3.connect(self.db_path)
        try:
            return con.execute(sql).fetchone()
        finally:
            con.close()


class TestAddMissingColumns(MigrationHarness):
    """补列本身：列要真的加上，且不能吞掉失败。"""

    def test_customer_source_columns_added(self):
        added = _migrate_add_missing_columns()
        self.assertIn("biz_customers.source", added)
        self.assertIn("biz_customers.source_note", added)

    def test_trip_new_columns_added(self):
        added = _migrate_add_missing_columns()
        for col in (
            "biz_trips.reason_code",
            "biz_trips.reimburse_status",
            "biz_trips.reimburse_amount",
            "biz_trips.report_task_ids",
        ):
            self.assertIn(col, added)

    def test_migration_is_idempotent(self):
        """重复跑不应报错、也不应重复加列。"""
        _migrate_add_missing_columns()
        second = _migrate_add_missing_columns()
        self.assertEqual(second, [])


class TestExistingDataPreserved(MigrationHarness):
    """加列是加列，既有数据与列都不能动。"""

    def test_existing_rows_kept(self):
        _migrate_add_missing_columns()
        row = self._raw_row("SELECT id, name FROM biz_customers")
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "老客户A")
        row2 = self._raw_row("SELECT id, title FROM biz_trips")
        self.assertEqual(row2[1], "老出差")

    def test_no_data_loss_in_untouched_columns(self):
        _migrate_add_missing_columns()
        row = self._raw_row("SELECT title, start_date, mileage_km FROM biz_trips")
        self.assertEqual(row[0], "老出差")
        self.assertEqual(row[1], "2026-01-01")
        self.assertAlmostEqual(row[2], 100.0)


class TestDefaultValueTypes(MigrationHarness):
    """⭐ 核心：DEFAULT 的**类型**必须正确，否则 ORM 读写会炸。

    - Numeric 列的 DEFAULT 写成 '' → 列变字符串 → 写 Decimal 报类型错
    - JSON 列的 DEFAULT 写成 '' → ORM 读这一行时 JSONDecodeError
    """

    def test_numeric_column_default_is_numeric(self):
        _migrate_add_missing_columns()
        row = self._raw_row("SELECT reimburse_amount FROM biz_trips")
        self.assertIsNotNone(row)
        self.assertNotIsInstance(row[0], str, "Numeric 列的 DEFAULT 不能是字符串")
        self.assertEqual(float(row[0]), 0.0)

    def test_json_column_default_is_valid_json(self):
        _migrate_add_missing_columns()
        row = self._raw_row("SELECT report_task_ids FROM biz_trips")
        self.assertIsNotNone(row)
        import json

        # 必须是能被 json 解析的合法 JSON 文本（列表或空串都不行）
        parsed = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        self.assertEqual(parsed, [])

    def test_string_column_default_is_empty_string(self):
        _migrate_add_missing_columns()
        row = self._raw_row("SELECT reason_code, reimburse_status FROM biz_trips")
        self.assertEqual(row[0], "")
        self.assertEqual(row[1], "none")


class TestOrmRoundTrip(MigrationHarness):
    """⭐ 迁移后老行能被 ORM 正常读写（这才是真机升级要过的关）。"""

    def test_orm_reads_migrated_row(self):
        _migrate_add_missing_columns()
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            trip = db.query(models.BizTrip).filter(models.BizTrip.title == "老出差").first()
            self.assertIsNotNone(trip)
            # JSON 列必须能读出列表（不是 ''，否则这里直接抛 JSONDecodeError）
            self.assertEqual(trip.report_task_ids, [])
            # Numeric 列必须能读出 Decimal
            self.assertIsInstance(trip.reimburse_amount, Decimal)
        finally:
            db.close()

    def test_orm_writes_new_fields(self):
        _migrate_add_missing_columns()
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            trip = db.query(models.BizTrip).filter(models.BizTrip.title == "老出差").first()
            trip.reason_code = "customer_visit"
            trip.reimburse_amount = Decimal("123.45")
            trip.report_task_ids = [1, 2, 3]
            db.commit()

            again = db.query(models.BizTrip).filter(models.BizTrip.title == "老出差").first()
            self.assertEqual(again.reason_code, "customer_visit")
            self.assertEqual(again.reimburse_amount, Decimal("123.45"))
            self.assertEqual(again.report_task_ids, [1, 2, 3])
        finally:
            db.close()

    def test_orm_reads_customer_source(self):
        _migrate_add_missing_columns()
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            cust = db.query(models.BizCustomer).filter(models.BizCustomer.name == "老客户A").first()
            self.assertIsNotNone(cust)
            self.assertEqual(cust.source, "")
            self.assertEqual(cust.source_note, "")
            cust.source = "referral"
            cust.source_note = "王总介绍"
            db.commit()
            again = (
                db.query(models.BizCustomer).filter(models.BizCustomer.name == "老客户A").first()
            )
            self.assertEqual(again.source, "referral")
            self.assertEqual(again.source_note, "王总介绍")
        finally:
            db.close()


class TestSqlLiteralRendering(unittest.TestCase):
    """_sql_literal 的类型渲染规则（纯函数，无需数据库）。"""

    def _col(self, name: str, col_type, default):
        from sqlalchemy import Column

        return Column(name, col_type, default=default)

    def test_string_default_quoted(self):
        from sqlalchemy import String

        col = self._col("x", String(32), "")
        self.assertEqual(_sql_literal(None, col.default, col), "''")

    def test_decimal_default_numeric(self):
        from sqlalchemy import Numeric

        col = self._col("x", Numeric(14, 2), Decimal("0"))
        self.assertEqual(_sql_literal(None, col.default, col), "0")

    def test_callable_json_default_is_json_text(self):
        """default=list → CallableColumnDefault → 必须渲染成 '[]'。"""
        from sqlalchemy import JSON

        col = self._col("x", JSON, list)
        rendered = _sql_literal(None, col.default, col)
        self.assertEqual(rendered, "'[]'")
        import json

        self.assertEqual(json.loads(rendered.strip("'")), [])

    def test_callable_dict_default_is_json_object(self):
        from sqlalchemy import JSON

        col = self._col("x", JSON, dict)
        self.assertEqual(_sql_literal(None, col.default, col), "'{}'")

    def test_none_default_returns_none(self):
        self.assertIsNone(_sql_literal(None, None, None))


if __name__ == "__main__":
    unittest.main()
