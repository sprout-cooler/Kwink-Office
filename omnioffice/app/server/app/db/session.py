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
                ddl = f"{ddl} NOT NULL" if not col.nullable else ddl
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
