"""数据模型（V10 3.4 / 3.5）。

分区（用户上传时指定，不靠识别推断）：
  offline_done  本周线下工作
  online_done   线上售后
  plan          下周工作计划
识别状态：pending → processing → done / failed
统计分类（M3 汇总计算）：training / offline_service / online_service / presale / unclassified
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Report(Base):
    """周报批次：一个用户一个自然周一条（周一起算，Asia/Shanghai）。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 周期周一日期，格式 YYYY-MM-DD
    period_start: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    # 绑定的模板版本（导出时按此版本填充；为空则用该用户最新版本）。
    # 绑定而非「总是用最新」是刻意的：模板改版后，历史周报重新导出仍走旧模板，
    # 否则同一份周报两次导出的样式会不一致（V10 4.5「历史周报绑定旧版本可追溯」）。
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    screenshots: Mapped[list["Screenshot"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class Screenshot(Base):
    """上传的任务截图原图与归属分区。"""

    __tablename__ = "screenshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True, nullable=False)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    partition: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending / processing / done / failed
    recognize_status: Mapped[str] = mapped_column(String(16), default="pending", index=True, nullable=False)
    recognize_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    report: Mapped[Report] = relationship(back_populates="screenshots")
    tasks: Mapped[list["TaskItem"]] = relationship(back_populates="screenshot", cascade="all, delete-orphan")


class TaskItem(Base):
    """截图识别出的结构化任务记录（标题/开始/结束/状态）。"""

    __tablename__ = "task_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screenshot_id: Mapped[int] = mapped_column(ForeignKey("screenshots.id"), index=True, nullable=False)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 归属分区（冗余截图分区，跨分区移动时随截图更新；归属与识别解耦）
    partition: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 归一化后的 ISO8601（日期归一化模块产出，M2 先存识别原值与归一化结果）
    start_at: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    end_at: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    raw_status: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    # 归属星期 1~7（M3 校对可改）；0=未归组
    weekday: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 统计分类（M3「分区优先+关键词兜底」计算）
    stat_category: Mapped[str] = mapped_column(String(20), default="unclassified", nullable=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    screenshot: Mapped[Screenshot] = relationship(back_populates="tasks")


class Setting(Base):
    """应用配置：key-value 持久化（通用 AI + 模块独立覆盖 + 未来扩展）。

    key 命名约定：
      ai.default.{base_url,model,api_key}     — 通用 AI 配置（所有模块默认）
      ai.{module_id}.{base_url,model,api_key} — 模块独立覆盖（如 weekly_report 用不同模型）
      app.{key}                               — 应用级配置
      manual.{report_id}.{issues|demands}     — 周报手工补充文本
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TemplateVersion(Base):
    """周报模板版本（V10 4.5：模板文件入库带版本号，历史周报绑定旧版本可追溯）。

    设计要点：
    - 模板文件落 data/templates/<md5>.xlsx，库里只存路径与元信息，避免 DB 膨胀；
    - md5 唯一：同一模板重复上传只登记版本记录，不重复存文件；
    - owner_uid 遵循全局规则：数据归属键只来自网关注入身份（避坑指南 §3.1）；
    - 一个周报批次绑定一个模板版本（Report.template_id），导出时按绑定版本填充，
      保证「历史周报用当时的模板」而不是「用最新模板」—— 模板改版不影响已导出内容。
    """

    __tablename__ = "template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 版本号：同一 owner 下递增，用于展示「v1 / v2」
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 结构指纹：填充前用它做锚点校验的快速前置判断（不匹配直接阻断并提示重新校验）
    anchor_ok: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ExportArtifact(Base):
    """导出产物记录（V10 4.5：两产物成对产出、可回溯版本）。

    一次导出 = 一条记录 + 1~2 个文件：
      - xlsx   保真导出（Excel 成品）
      - png    区域截图（口径一：连续内容区；口径二：完整表体；超宽拆 _p1/_p2）
    文件落共享目录 exports/<用户名>/周报_<姓名>_<起-止>/，文件管理器可直接取用。
    """

    __tablename__ = "export_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True, nullable=False)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("template_versions.id"), nullable=True)
    # 周报_<姓名>_<起-止>，用于文件名与目录名
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    xlsx_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 截图可能多张（超宽分页），JSON 数组
    png_paths: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # content | full（T8 两口径）
    scope: Mapped[str] = mapped_column(String(16), default="content", nullable=False)
    # 截图 DPI
    dpi: Mapped[int] = mapped_column(Integer, default=192, nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # ok | partial（xlsx 成功但截图失败）| failed
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    report: Mapped[Report] = relationship("Report")
