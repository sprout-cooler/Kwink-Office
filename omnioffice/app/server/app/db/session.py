"""数据库会话：真机 PostgreSQL（Compose 注入 DATABASE_URL），本地回退 SQLite。

双后端兼容约束：
- JSON 字段统一用 SQLAlchemy 通用 JSON 类型（SQLite/PG 均支持）；
- 主键用 Integer 自增（不用 PG 专有类型）；
- 时间统一 UTC 存库，展示层再转时区。
"""
from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ..core.config import settings


def _resolve_url() -> str:
    if settings.database_url:
        return settings.database_url
    db_path = Path(settings.data_dir) / "omnioffice.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


URL = _resolve_url()
_connect_args = {"check_same_thread": False} if URL.startswith("sqlite") else {}
engine = create_engine(URL, connect_args=_connect_args, future=True)

if URL.startswith("sqlite"):
    # **让 SQLite 与真机 PostgreSQL 的外键行为一致**（v1.0.25 加固）。
    #
    # 真机事故（v1.0.24）：删模板必 500，报
    #   export_artifacts_template_id_fkey  violates foreign key constraint
    # 而 211 项单测全绿 —— 因为 SQLite **默认不强制外键**
    # （PRAGMA foreign_keys 默认 OFF），删主表时依赖表里残留引用也照删不误。
    # 也就是说测试环境根本没有复现真机约束的能力，这类缺陷必然漏到真机才炸。
    #
    # 该 PRAGMA 是**连接级**的，不能写在 connect_args 里（那是驱动参数），
    # 必须对每个新连接执行 —— 用 pool 监听器保证任意连接都生效。
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_enable_foreign_keys(dbapi_conn, _conn_record) -> None:  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def _wait_for_database(max_wait_s: int = 90) -> None:
    """等待数据库就绪。

    真机坑（v1.0.3 Bad Gateway）：compose depends_on 只保证容器启动顺序，不保证
    PostgreSQL 已接受连接；api 启动即建表会撞上 PG 初始化窗口而崩溃重启。
    用 SELECT 1 探活 + 指数退避重试，不依赖平台 compose 是否支持 healthcheck 条件。
    """
    deadline = time.time() + max_wait_s
    delay = 1.0
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:  # 容器启动早期各种连接拒绝/认证未就绪，统一重试
            last_err = e
            print(f"[startup] database not ready, retry in {delay:.0f}s: {type(e).__name__}: {e}", flush=True)
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)
    raise RuntimeError(f"database not ready after {max_wait_s}s: {last_err}")


def _sql_literal(engine, default, col=None) -> str | None:
    """把 ORM 列的 default 渲染成 SQL DEFAULT 字面量。

    返回 None 表示「渲染不出默认值」—— 此时该列不加 DEFAULT，
    迁移在非空表上会失败（NOT NULL 列必须带 DEFAULT），但**失败是显式的**，
    比静默写入类型错误的默认值安全。

    ⚠️ 为什么不能直接对 ``col.default.arg`` 求值（实测 SQLAlchemy 2.1.6）：
    ``default=list`` 会被 SQLAlchemy 包装成 ``CallableColumnDefault``，其 ``arg``
    虽保留原签名 ``(iterable=())``，实际调用却要求 ``ctx`` 参数
    （``TypeError: list() missing 1 required positional argument: 'ctx'``），
    且 ``get_column_default_string`` 对它返回 None。
    所以这里**按列类型**决定默认值，而不是执行工厂：
    - JSON 列   → 该类型的空值是 ``[]`` / ``{}``
    - Numeric 列 → ``0``
    - 布尔列   → ``0``
    - 文本列   → ``''``
    """
    from decimal import Decimal

    if default is None:
        return None
    arg = getattr(default, "arg", default)

    # ---- 1) 标量默认值（ScalarElementColumnDefault）----
    if not callable(arg):
        if isinstance(arg, bool):
            return "1" if arg else "0"
        if isinstance(arg, Decimal):
            # Numeric 列必须是数值字面量：写成 '' 会让该列变成字符串类型，
            # 后续写入 Decimal 时报类型不匹配（实测已复现）。
            return str(arg)
        if isinstance(arg, (int, float)):
            return str(arg)
        if isinstance(arg, str):
            escaped = arg.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(arg, (list, dict)):
            import json as _json

            return f"'{_json.dumps(arg, ensure_ascii=False)}'"
        return None

    # ---- 2) 可调用默认值（CallableColumnDefault）：按列类型推断空初始值 ----
    # 无法从工厂本身求值（见上方 docstring），改用「列类型 + 工厂名字」推断。
    type_name = ""
    if col is not None:
        type_name = type(col.type).__name__.upper()
    factory_name = getattr(arg, "__name__", "").lower()

    if type_name in ("JSON",):
        # JSON 列的 DEFAULT 必须是**合法 JSON 文本**：
        # 写成 '' 会让 ORM 读这一行时 JSON 解析失败（实测 JSONDecodeError）。
        if factory_name == "dict":
            return "'{}'"
        return "'[]'"
    if type_name in ("NUMERIC", "INTEGER", "FLOAT", "REAL", "SMALLINT", "BIGINT"):
        return "0"
    if type_name == "BOOLEAN":
        return "0"
    if type_name in ("TEXT", "VARCHAR", "CHAR", "NVARCHAR"):
        return "''"
    return None


def _migrate_add_missing_columns() -> list[str]:
    """补齐「表已存在但缺列」的情况。

    ``create_all`` 只建缺失的**表**，不会给已存在的表**加列**。本项目通过 FPK 升级
    安装时数据卷是保留的（V10 M0 S7 验证项），所以老库必然存在 ——
    新增字段后若只靠 create_all，真机会直接抛
    ``column reports.template_id does not exist`` 而启动失败。

    这里做**幂等**的加列：只补 ORM 里声明、而库里缺失的列，列类型用 SQLAlchemy
    的 DDL 编译（SQLite 与 PostgreSQL 各自适配）。不删列、不改类型、不动数据 ——
    真机上做破坏性迁移的风险远大于收益，正式迁移仍应在 M3 前切 Alembic。
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # 表本身由 create_all 负责
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                # 注意：col.compile() 会带上表名前缀（reports.template_id），
                # 直接拼进 ALTER TABLE 会报语法错 —— 迁移语句里必须用「列定义」部分。
                # 取 col.type 的 DDL 再手工补 NOT NULL，避开表名前缀问题。
                ddl = col.type.compile(engine.dialect)
                if not col.nullable:
                    ddl = f"{ddl} NOT NULL"
                    # 必须带 DEFAULT：给已有表加 NOT NULL 列时，
                    # SQLite 报「Cannot add a NOT NULL column with default value NULL」，
                    # PostgreSQL 在表非空时同样拒绝无 DEFAULT 的 NOT NULL 列。
                    # 实测（2026-10-26）两者都要求 DEFAULT，且 DEFAULT 会应用到既有行。
                    # 不带 DEFAULT 时加列会被下面的 except 吞掉 → 老库上该字段根本不存在
                    # → 真机启动后访问该字段直接报错（本项目 v1.0.25 的同类教训）。
                    dflt = _sql_literal(engine, col.default, col)
                    if dflt is not None:
                        ddl = f"{ddl} DEFAULT {dflt}"
                try:
                    conn.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}")
                except Exception as e:  # noqa: BLE001 —— 迁移失败不应阻断启动
                    print(
                        f"[migrate] 跳过 {table.name}.{col.name}：{type(e).__name__}: {e}",
                        flush=True,
                    )
                    continue
                applied.append(f"{table.name}.{col.name}")
    return applied


def init_db() -> None:
    _wait_for_database()
    # M2 用 create_all 建表；表结构稳定后（M3 前）切换 Alembic 迁移
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    added = _migrate_add_missing_columns()
    if added:
        print(f"[migrate] 已补列：{', '.join(added)}", flush=True)
    print("[startup] database schema ready", flush=True)
